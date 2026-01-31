"""
Health Monitoring Utilities

Collects infrastructure-level health metrics:
- File descriptors
- Memory usage
- Database connections
- WebSocket connections
- Thread usage

ZERO LATENCY IMPACT:
- Runs in background daemon thread
- Does not block API/WebSocket operations
- Minimal CPU overhead (<1%)
- Sampling every 10 seconds (configurable)
"""

import logging
import os
import threading
import time
from datetime import datetime, timezone

import psutil

from database.health_db import (
    HealthAlert,
    HealthMetric,
    health_session,
    init_health_db,
    purge_old_metrics,
)

logger = logging.getLogger(__name__)

# Configuration from environment
HEALTH_MONITOR_ENABLED = os.getenv("HEALTH_MONITOR_ENABLED", "true").lower() == "true"
HEALTH_SAMPLE_INTERVAL = int(os.getenv("HEALTH_SAMPLE_INTERVAL", "10"))  # seconds
HEALTH_RETENTION_DAYS = int(os.getenv("HEALTH_RETENTION_DAYS", "7"))

# File Descriptor Thresholds
FD_WARNING_THRESHOLD = int(os.getenv("HEALTH_FD_WARNING_THRESHOLD", "700"))
FD_CRITICAL_THRESHOLD = int(os.getenv("HEALTH_FD_CRITICAL_THRESHOLD", "900"))

# Memory Thresholds (MB)
MEMORY_WARNING_THRESHOLD = int(os.getenv("HEALTH_MEMORY_WARNING_THRESHOLD", "500"))
MEMORY_CRITICAL_THRESHOLD = int(os.getenv("HEALTH_MEMORY_CRITICAL_THRESHOLD", "1000"))

# Database Connection Thresholds
DB_WARNING_THRESHOLD = int(os.getenv("HEALTH_DB_WARNING_THRESHOLD", "10"))
DB_CRITICAL_THRESHOLD = int(os.getenv("HEALTH_DB_CRITICAL_THRESHOLD", "20"))

# WebSocket Connection Thresholds
WS_WARNING_THRESHOLD = int(os.getenv("HEALTH_WS_WARNING_THRESHOLD", "10"))
WS_CRITICAL_THRESHOLD = int(os.getenv("HEALTH_WS_CRITICAL_THRESHOLD", "20"))

# Thread Thresholds
THREAD_WARNING_THRESHOLD = int(os.getenv("HEALTH_THREAD_WARNING_THRESHOLD", "50"))
THREAD_CRITICAL_THRESHOLD = int(os.getenv("HEALTH_THREAD_CRITICAL_THRESHOLD", "100"))

# Global collector thread
_collector_thread = None
_collector_running = False
_collector_lock = threading.Lock()

# Cached metrics for fast access (updated by background thread)
_cached_metrics = {
    "status": "pass",
    "timestamp": None,
    "fd": {},
    "memory": {},
    "database": {},
    "websocket": {},
    "threads": {},
}
_cache_lock = threading.Lock()


def get_cached_health_status():
    """
    Get cached health status (instant, no latency).
    For AWS ELB and monitoring tools.

    Returns:
        dict: {"status": "pass"|"warn"|"fail", "timestamp": "..."}
    """
    with _cache_lock:
        return {
            "status": _cached_metrics.get("status", "pass"),
            "timestamp": _cached_metrics.get("timestamp"),
        }


def check_db_connectivity():
    """
    Quick database connectivity check.
    For /health/check endpoint.

    Returns:
        dict: {
            "status": "pass"|"fail",
            "databases": {
                "openalgo": "pass"|"fail",
                "logs": "pass"|"fail",
                ...
            }
        }
    """
    results = {}
    overall_status = "pass"

    databases = {
        "openalgo": "database.auth_db",
        "logs": "database.traffic_db",
        "latency": "database.latency_db",
    }

    for db_name, module_path in databases.items():
        try:
            parts = module_path.rsplit(".", 1)
            if len(parts) == 2:
                module_name, _ = parts
                module = __import__(module_name, fromlist=["db_session"])

                # Try a simple query
                if hasattr(module, "db_session"):
                    session = getattr(module, "db_session")
                    # Execute simple query to test connectivity
                    session.execute("SELECT 1").fetchone()
                    results[db_name] = "pass"
                elif hasattr(module, "logs_session"):
                    session = getattr(module, "logs_session")
                    session.execute("SELECT 1").fetchone()
                    results[db_name] = "pass"
                elif hasattr(module, "latency_session"):
                    session = getattr(module, "latency_session")
                    session.execute("SELECT 1").fetchone()
                    results[db_name] = "pass"
                else:
                    results[db_name] = "pass"  # Assume pass if no session found
        except Exception as e:
            logger.error(f"Database connectivity check failed for {db_name}: {e}")
            results[db_name] = "fail"
            overall_status = "fail"

    return {"status": overall_status, "databases": results}


def get_fd_metrics():
    """Get file descriptor metrics (lightweight, <1ms)"""
    try:
        process = psutil.Process(os.getpid())

        # Get FD count (Unix/Linux/macOS only)
        if hasattr(process, "num_fds"):
            fd_count = process.num_fds()
        else:
            # Windows - count handles instead
            fd_count = process.num_handles() if hasattr(process, "num_handles") else 0

        # Get FD limit
        if hasattr(os, "sysconf") and hasattr(os, "sysconf_names"):
            if "SC_OPEN_MAX" in os.sysconf_names:
                fd_limit = os.sysconf("SC_OPEN_MAX")
            else:
                fd_limit = 1024  # Default
        else:
            fd_limit = 16777216  # Windows default

        fd_usage_percent = (fd_count / fd_limit * 100) if fd_limit else 0
        fd_available = fd_limit - fd_count

        # Determine status
        if fd_count >= FD_CRITICAL_THRESHOLD:
            status = "fail"
            HealthAlert.create_alert(
                alert_type="fd_fail",
                severity="fail",
                metric_name="fd_count",
                metric_value=fd_count,
                threshold_value=FD_CRITICAL_THRESHOLD,
                message=f"File descriptor count critical: {fd_count}/{fd_limit} ({fd_usage_percent:.1f}%)",
            )
        elif fd_count >= FD_WARNING_THRESHOLD:
            status = "warn"
            HealthAlert.create_alert(
                alert_type="fd_warn",
                severity="warn",
                metric_name="fd_count",
                metric_value=fd_count,
                threshold_value=FD_WARNING_THRESHOLD,
                message=f"File descriptor count elevated: {fd_count}/{fd_limit} ({fd_usage_percent:.1f}%)",
            )
        else:
            status = "pass"
            HealthAlert.auto_resolve_alerts("fd_count", fd_count, FD_WARNING_THRESHOLD)

        return {
            "count": fd_count,
            "limit": fd_limit,
            "usage_percent": fd_usage_percent,
            "available": fd_available,
            "status": status,
        }
    except Exception as e:
        logger.error(f"Error getting FD metrics: {e}")
        return {"count": 0, "limit": 0, "usage_percent": 0, "available": 0, "status": "unknown"}


def get_memory_metrics():
    """Get memory usage metrics (lightweight, <1ms)"""
    try:
        process = psutil.Process(os.getpid())
        mem_info = process.memory_info()

        rss_mb = mem_info.rss / (1024 * 1024)  # Resident Set Size
        vms_mb = mem_info.vms / (1024 * 1024)  # Virtual Memory Size

        # Get system memory
        system_mem = psutil.virtual_memory()
        memory_percent = process.memory_percent()
        available_mb = system_mem.available / (1024 * 1024)

        # Get swap usage
        swap = psutil.swap_memory()
        swap_mb = swap.used / (1024 * 1024)

        # Determine status
        if rss_mb >= MEMORY_CRITICAL_THRESHOLD:
            status = "fail"
            HealthAlert.create_alert(
                alert_type="memory_fail",
                severity="fail",
                metric_name="memory_rss_mb",
                metric_value=rss_mb,
                threshold_value=MEMORY_CRITICAL_THRESHOLD,
                message=f"Memory usage critical: {rss_mb:.1f} MB (threshold: {MEMORY_CRITICAL_THRESHOLD} MB)",
            )
        elif rss_mb >= MEMORY_WARNING_THRESHOLD:
            status = "warn"
            HealthAlert.create_alert(
                alert_type="memory_warn",
                severity="warn",
                metric_name="memory_rss_mb",
                metric_value=rss_mb,
                threshold_value=MEMORY_WARNING_THRESHOLD,
                message=f"Memory usage elevated: {rss_mb:.1f} MB (threshold: {MEMORY_WARNING_THRESHOLD} MB)",
            )
        else:
            status = "pass"
            HealthAlert.auto_resolve_alerts("memory_rss_mb", rss_mb, MEMORY_WARNING_THRESHOLD)

        return {
            "rss_mb": rss_mb,
            "vms_mb": vms_mb,
            "percent": memory_percent,
            "available_mb": available_mb,
            "swap_mb": swap_mb,
            "status": status,
        }
    except Exception as e:
        logger.error(f"Error getting memory metrics: {e}")
        return {
            "rss_mb": 0,
            "vms_mb": 0,
            "percent": 0,
            "available_mb": 0,
            "swap_mb": 0,
            "status": "unknown",
        }


def get_database_metrics():
    """Get database connection metrics (lightweight check)"""
    try:
        connections = {}

        # Check each database (minimal overhead)
        databases = {
            "openalgo": "database.auth_db",
            "logs": "database.traffic_db",
            "latency": "database.latency_db",
            "apilog": "database.apilog_db",
            "health": "database.health_db",
        }

        for db_name, module_path in databases.items():
            try:
                parts = module_path.rsplit(".", 1)
                if len(parts) == 2:
                    module_name, attr_name = parts
                    module = __import__(module_name, fromlist=[attr_name])

                    # Try different session variable names
                    session_names = [
                        "db_session",
                        "logs_session",
                        "latency_session",
                        "health_session",
                    ]
                    conn_count = 0

                    for session_name in session_names:
                        if hasattr(module, session_name):
                            session = getattr(module, session_name)
                            # Check if session has active connections
                            if hasattr(session, "registry"):
                                # Scoped session - check registry
                                if hasattr(session.registry, "has") and session.registry.has():
                                    conn_count = 1
                                break

                    connections[db_name] = conn_count
            except Exception:
                connections[db_name] = 0

        total_connections = sum(connections.values())

        # Determine status
        if total_connections >= DB_CRITICAL_THRESHOLD:
            status = "fail"
            HealthAlert.create_alert(
                alert_type="db_fail",
                severity="fail",
                metric_name="db_connections_total",
                metric_value=total_connections,
                threshold_value=DB_CRITICAL_THRESHOLD,
                message=f"Database connections critical: {total_connections} (threshold: {DB_CRITICAL_THRESHOLD})",
            )
        elif total_connections >= DB_WARNING_THRESHOLD:
            status = "warn"
            HealthAlert.create_alert(
                alert_type="db_warn",
                severity="warn",
                metric_name="db_connections_total",
                metric_value=total_connections,
                threshold_value=DB_WARNING_THRESHOLD,
                message=f"Database connections elevated: {total_connections} (threshold: {DB_WARNING_THRESHOLD})",
            )
        else:
            status = "pass"
            HealthAlert.auto_resolve_alerts(
                "db_connections_total", total_connections, DB_WARNING_THRESHOLD
            )

        return {"total": total_connections, "connections": connections, "status": status}
    except Exception as e:
        logger.error(f"Error getting database metrics: {e}")
        return {"total": 0, "connections": {}, "status": "unknown"}


def get_websocket_metrics():
    """Get WebSocket connection metrics (minimal overhead)"""
    try:
        connections = {}
        total_connections = 0
        total_symbols = 0

        # Try to import and check WebSocket proxy connection pools
        try:
            from websocket_proxy.broker_factory import get_pool_stats

            pool_stats = get_pool_stats()

            for pool_key, stats in pool_stats.items():
                conn_count = stats.get("active_connections", 0)
                symbols_count = stats.get("total_subscriptions", 0)
                broker_name = stats.get("broker") or pool_key

                connections[pool_key] = {
                    "broker": broker_name,
                    "count": conn_count,
                    "symbols": symbols_count,
                }
                total_connections += conn_count
                total_symbols += symbols_count

        except ImportError:
            pass  # WebSocket proxy not available
        except Exception:
            pass  # Error checking WebSocket connections

        # Determine status
        if total_connections >= WS_CRITICAL_THRESHOLD:
            status = "fail"
            HealthAlert.create_alert(
                alert_type="ws_fail",
                severity="fail",
                metric_name="ws_connections_total",
                metric_value=total_connections,
                threshold_value=WS_CRITICAL_THRESHOLD,
                message=f"WebSocket connections critical: {total_connections} (threshold: {WS_CRITICAL_THRESHOLD})",
            )
        elif total_connections >= WS_WARNING_THRESHOLD:
            status = "warn"
            HealthAlert.create_alert(
                alert_type="ws_warn",
                severity="warn",
                metric_name="ws_connections_total",
                metric_value=total_connections,
                threshold_value=WS_WARNING_THRESHOLD,
                message=f"WebSocket connections elevated: {total_connections} (threshold: {WS_WARNING_THRESHOLD})",
            )
        else:
            status = "pass"
            HealthAlert.auto_resolve_alerts(
                "ws_connections_total", total_connections, WS_WARNING_THRESHOLD
            )

        return {
            "total": total_connections,
            "total_symbols": total_symbols,
            "connections": connections,
            "status": status,
        }
    except Exception as e:
        logger.error(f"Error getting WebSocket metrics: {e}")
        return {"total": 0, "total_symbols": 0, "connections": {}, "status": "unknown"}


def get_thread_metrics():
    """Get thread usage metrics (minimal overhead)"""
    try:
        # Get all threads (lightweight enumeration)
        threads_info = []
        stuck_count = 0

        for thread in threading.enumerate():
            thread_info = {
                "id": thread.ident,
                "name": thread.name,
                "daemon": thread.daemon,
                "alive": thread.is_alive(),
            }
            threads_info.append(thread_info)

        thread_count = len(threads_info)

        # Determine status
        if thread_count >= THREAD_CRITICAL_THRESHOLD or stuck_count > 0:
            status = "fail"
            message = (
                f"Thread count critical: {thread_count} (threshold: {THREAD_CRITICAL_THRESHOLD})"
            )
            if stuck_count > 0:
                message += f", {stuck_count} stuck threads detected"

            HealthAlert.create_alert(
                alert_type="thread_fail",
                severity="fail",
                metric_name="thread_count",
                metric_value=thread_count,
                threshold_value=THREAD_CRITICAL_THRESHOLD,
                message=message,
            )
        elif thread_count >= THREAD_WARNING_THRESHOLD:
            status = "warn"
            HealthAlert.create_alert(
                alert_type="thread_warn",
                severity="warn",
                metric_name="thread_count",
                metric_value=thread_count,
                threshold_value=THREAD_WARNING_THRESHOLD,
                message=f"Thread count elevated: {thread_count} (threshold: {THREAD_WARNING_THRESHOLD})",
            )
        else:
            status = "pass"
            HealthAlert.auto_resolve_alerts("thread_count", thread_count, THREAD_WARNING_THRESHOLD)

        return {
            "count": thread_count,
            "stuck_count": stuck_count,
            "threads": threads_info[:50],  # Limit to first 50 for JSON size
            "status": status,
        }
    except Exception as e:
        logger.error(f"Error getting thread metrics: {e}")
        return {"count": 0, "stuck_count": 0, "threads": [], "status": "unknown"}


def get_process_metrics(limit: int = 5):
    """Get top memory-consuming processes (best-effort, may skip inaccessible processes)"""
    processes = []
    try:
        for proc in psutil.process_iter(attrs=["pid", "name", "memory_info", "memory_percent"]):
            try:
                info = proc.info
                mem_info = info.get("memory_info")
                if not mem_info:
                    mem_info = proc.memory_info()

                rss_mb = mem_info.rss / (1024 * 1024)
                vms_mb = mem_info.vms / (1024 * 1024)

                processes.append(
                    {
                        "pid": info.get("pid"),
                        "name": info.get("name") or "unknown",
                        "rss_mb": rss_mb,
                        "vms_mb": vms_mb,
                        "memory_percent": info.get("memory_percent") or 0,
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        processes.sort(key=lambda p: p.get("rss_mb", 0), reverse=True)
        return processes[:limit]
    except Exception as e:
        logger.error(f"Error getting process metrics: {e}")
        return []


def collect_metrics():
    """
    Collect all metrics and log to database.
    Runs in background thread - ZERO API LATENCY IMPACT.

    Returns:
        dict: All collected metrics
    """
    try:
        fd_metrics = get_fd_metrics()
        memory_metrics = get_memory_metrics()
        db_metrics = get_database_metrics()
        ws_metrics = get_websocket_metrics()
        thread_metrics = get_thread_metrics()
        process_metrics = get_process_metrics()

        # Log to database
        HealthMetric.log_metrics(
            fd_metrics=fd_metrics,
            memory_metrics=memory_metrics,
            db_metrics=db_metrics,
            ws_metrics=ws_metrics,
            thread_metrics=thread_metrics,
            process_metrics=process_metrics,
        )

        # Update cache for fast access
        overall_status = "pass"
        for metrics in [fd_metrics, memory_metrics, db_metrics, ws_metrics, thread_metrics]:
            if metrics.get("status") == "fail":
                overall_status = "fail"
                break
            elif metrics.get("status") == "warn":
                overall_status = "warn"

        with _cache_lock:
            _cached_metrics.update(
                {
                    "status": overall_status,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "fd": fd_metrics,
                    "memory": memory_metrics,
                    "database": db_metrics,
                    "websocket": ws_metrics,
                    "threads": thread_metrics,
                    "processes": process_metrics,
                }
            )

        return _cached_metrics.copy()
    except Exception as e:
        logger.exception(f"Error collecting metrics: {e}")
        return {}
    finally:
        # Always remove session
        health_session.remove()


def _collector_loop():
    """Background collector loop (daemon thread, low priority)"""
    global _collector_running

    logger.debug(f"Health monitoring collector started (interval: {HEALTH_SAMPLE_INTERVAL}s)")

    while _collector_running:
        try:
            collect_metrics()
        except Exception as e:
            logger.exception(f"Error in collector loop: {e}")

        # Sleep for interval (releases GIL, zero impact on API/WebSocket)
        time.sleep(HEALTH_SAMPLE_INTERVAL)

    logger.info("Health monitoring collector stopped")


def start_health_collector(interval=None):
    """
    Start background metrics collector.
    Daemon thread, zero latency impact on API/WebSocket operations.

    Args:
        interval (int, optional): Sampling interval in seconds. Uses HEALTH_SAMPLE_INTERVAL if not provided.
    """
    global _collector_thread, _collector_running, HEALTH_SAMPLE_INTERVAL

    if not HEALTH_MONITOR_ENABLED:
        logger.info("Health monitoring is disabled (HEALTH_MONITOR_ENABLED=false)")
        return

    if interval:
        HEALTH_SAMPLE_INTERVAL = interval

    with _collector_lock:
        if _collector_running:
            logger.warning("Health monitoring collector is already running")
            return

        _collector_running = True
        _collector_thread = threading.Thread(
            target=_collector_loop, name="HealthCollector", daemon=True  # Daemon = zero impact
        )
        _collector_thread.start()
        logger.debug("Started health monitoring collector (background daemon thread)")


def stop_health_collector():
    """Stop background metrics collector"""
    global _collector_running

    with _collector_lock:
        if not _collector_running:
            return

        _collector_running = False
        logger.info("Stopping health monitoring collector...")

        if _collector_thread:
            _collector_thread.join(timeout=5)


def init_health_monitoring(app):
    """
    Initialize health monitoring system.
    ZERO LATENCY IMPACT - all collection runs in background.

    Args:
        app: Flask application instance
    """
    try:
        # Initialize database
        init_health_db()

        # Purge old metrics
        purge_old_metrics(days=HEALTH_RETENTION_DAYS)

        # Start collector (background daemon thread)
        start_health_collector()

        logger.debug("Health monitoring initialized successfully (background mode)")
    except Exception as e:
        logger.exception(f"Error initializing health monitoring: {e}")
