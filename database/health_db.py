"""
Health Monitoring Database

Tracks infrastructure-level health metrics:
- File descriptors (FD count, usage, leaks)
- Memory usage (RSS, VMS, swap)
- Database connections (per database)
- WebSocket connections (per broker)
- Thread usage (count, stuck threads)

Follows industry standards (draft-inadarei-api-health-check):
- Status values: pass | warn | fail
- Zero latency impact on API/WebSocket operations
- Background collection only
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, Float, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.pool import NullPool
from sqlalchemy.sql import func

logger = logging.getLogger(__name__)

# Use a separate database for health monitoring
HEALTH_DATABASE_URL = os.getenv("HEALTH_DATABASE_URL", "sqlite:///db/health.db")

# Conditionally create engine based on DB type
if HEALTH_DATABASE_URL and "sqlite" in HEALTH_DATABASE_URL:
    # SQLite: Use NullPool to prevent connection pool exhaustion
    health_engine = create_engine(
        HEALTH_DATABASE_URL, poolclass=NullPool, connect_args={"check_same_thread": False}
    )
else:
    # For other databases like PostgreSQL, use connection pooling
    health_engine = create_engine(
        HEALTH_DATABASE_URL, pool_size=50, max_overflow=100, pool_timeout=10
    )

health_session = scoped_session(
    sessionmaker(autocommit=False, autoflush=False, bind=health_engine)
)
HealthBase = declarative_base()
HealthBase.query = health_session.query_property()


class HealthMetric(HealthBase):
    """Model for tracking infrastructure health metrics"""

    __tablename__ = "health_metrics"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    # File Descriptors
    fd_count = Column(Integer)
    fd_limit = Column(Integer)
    fd_usage_percent = Column(Float)
    fd_available = Column(Integer)
    fd_status = Column(String(20))  # pass | warn | fail

    # Memory Usage
    memory_rss_mb = Column(Float)  # Resident Set Size
    memory_vms_mb = Column(Float)  # Virtual Memory Size
    memory_percent = Column(Float)  # % of total system memory
    memory_available_mb = Column(Float)
    memory_swap_mb = Column(Float)
    memory_status = Column(String(20))  # pass | warn | fail

    # Database Connections
    db_connections_total = Column(Integer)
    db_connections = Column(JSON)  # {"openalgo": 2, "logs": 1, ...}
    db_status = Column(String(20))  # pass | warn | fail

    # WebSocket Connections
    ws_connections_total = Column(Integer)
    ws_connections = Column(JSON)  # {"zerodha": {"count": 2, "symbols": 1500}, ...}
    ws_total_symbols = Column(Integer)
    ws_status = Column(String(20))  # pass | warn | fail

    # Thread Usage
    thread_count = Column(Integer)
    stuck_threads = Column(Integer)
    thread_details = Column(JSON)  # List of thread info
    thread_status = Column(String(20))  # pass | warn | fail

    # Process Usage (top memory consumers)
    process_details = Column(JSON)  # List of process info

    # Overall Health (following draft-inadarei-api-health-check)
    overall_status = Column(String(20))  # pass | warn | fail

    @staticmethod
    def log_metrics(
        fd_metrics=None,
        memory_metrics=None,
        db_metrics=None,
        ws_metrics=None,
        thread_metrics=None,
        process_metrics=None,
    ):
        """Log health metrics (background thread only - zero API latency impact)"""
        try:
            # Calculate overall status following industry standards
            # pass: all components operational
            # warn: degraded performance, still functional
            # fail: one or more critical components failed
            statuses = []
            if fd_metrics:
                statuses.append(fd_metrics.get("status", "pass"))
            if memory_metrics:
                statuses.append(memory_metrics.get("status", "pass"))
            if db_metrics:
                statuses.append(db_metrics.get("status", "pass"))
            if ws_metrics:
                statuses.append(ws_metrics.get("status", "pass"))
            if thread_metrics:
                statuses.append(thread_metrics.get("status", "pass"))

            # Overall status is worst of all individual statuses
            if "fail" in statuses:
                overall_status = "fail"
            elif "warn" in statuses:
                overall_status = "warn"
            else:
                overall_status = "pass"

            metric = HealthMetric(
                # File Descriptors
                fd_count=fd_metrics.get("count") if fd_metrics else None,
                fd_limit=fd_metrics.get("limit") if fd_metrics else None,
                fd_usage_percent=fd_metrics.get("usage_percent") if fd_metrics else None,
                fd_available=fd_metrics.get("available") if fd_metrics else None,
                fd_status=fd_metrics.get("status") if fd_metrics else "unknown",
                # Memory
                memory_rss_mb=memory_metrics.get("rss_mb") if memory_metrics else None,
                memory_vms_mb=memory_metrics.get("vms_mb") if memory_metrics else None,
                memory_percent=memory_metrics.get("percent") if memory_metrics else None,
                memory_available_mb=memory_metrics.get("available_mb") if memory_metrics else None,
                memory_swap_mb=memory_metrics.get("swap_mb") if memory_metrics else None,
                memory_status=memory_metrics.get("status") if memory_metrics else "unknown",
                # Database
                db_connections_total=db_metrics.get("total") if db_metrics else None,
                db_connections=db_metrics.get("connections") if db_metrics else None,
                db_status=db_metrics.get("status") if db_metrics else "unknown",
                # WebSocket
                ws_connections_total=ws_metrics.get("total") if ws_metrics else None,
                ws_connections=ws_metrics.get("connections") if ws_metrics else None,
                ws_total_symbols=ws_metrics.get("total_symbols") if ws_metrics else None,
                ws_status=ws_metrics.get("status") if ws_metrics else "unknown",
                # Threads
                thread_count=thread_metrics.get("count") if thread_metrics else None,
                stuck_threads=thread_metrics.get("stuck_count") if thread_metrics else None,
                thread_details=thread_metrics.get("threads") if thread_metrics else None,
                thread_status=thread_metrics.get("status") if thread_metrics else "unknown",
                # Processes
                process_details=process_metrics if process_metrics else None,
                # Overall
                overall_status=overall_status,
            )

            health_session.add(metric)
            health_session.commit()
            return True
        except Exception as e:
            logger.exception(f"Error logging health metrics: {str(e)}")
            health_session.rollback()
            return False

    @staticmethod
    def get_current_metrics():
        """Get most recent metrics"""
        try:
            return HealthMetric.query.order_by(HealthMetric.timestamp.desc()).first()
        except Exception as e:
            logger.exception(f"Error getting current metrics: {str(e)}")
            return None

    @staticmethod
    def get_recent_metrics(limit=100):
        """Get recent metrics ordered by timestamp"""
        try:
            return (
                HealthMetric.query.order_by(HealthMetric.timestamp.desc()).limit(limit).all()
            )
        except Exception as e:
            logger.exception(f"Error getting recent metrics: {str(e)}")
            return []

    @staticmethod
    def get_metrics_history(hours=24):
        """Get metrics for the specified number of hours"""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
            return (
                HealthMetric.query.filter(HealthMetric.timestamp >= cutoff)
                .order_by(HealthMetric.timestamp.asc())
                .all()
            )
        except Exception as e:
            logger.exception(f"Error getting metrics history: {str(e)}")
            return []

    @staticmethod
    def get_stats(hours=24):
        """Get aggregated statistics for the specified time period"""
        try:
            cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

            # Get metrics for the time period
            metrics = (
                HealthMetric.query.filter(HealthMetric.timestamp >= cutoff)
                .order_by(HealthMetric.timestamp.asc())
                .all()
            )

            if not metrics:
                return {
                    "total_samples": 0,
                    "time_period_hours": hours,
                    "fd": {},
                    "memory": {},
                    "database": {},
                    "websocket": {},
                    "threads": {},
                    "status": {},
                }

            # Calculate statistics
            fd_counts = [m.fd_count for m in metrics if m.fd_count is not None]
            memory_rss = [m.memory_rss_mb for m in metrics if m.memory_rss_mb is not None]
            db_conns = [
                m.db_connections_total for m in metrics if m.db_connections_total is not None
            ]
            ws_conns = [
                m.ws_connections_total for m in metrics if m.ws_connections_total is not None
            ]
            threads = [m.thread_count for m in metrics if m.thread_count is not None]

            # Count status occurrences
            fd_fail_count = sum(1 for m in metrics if m.fd_status == "fail")
            fd_warn_count = sum(1 for m in metrics if m.fd_status == "warn")
            memory_fail_count = sum(1 for m in metrics if m.memory_status == "fail")
            memory_warn_count = sum(1 for m in metrics if m.memory_status == "warn")
            db_fail_count = sum(1 for m in metrics if m.db_status == "fail")
            db_warn_count = sum(1 for m in metrics if m.db_status == "warn")
            ws_fail_count = sum(1 for m in metrics if m.ws_status == "fail")
            ws_warn_count = sum(1 for m in metrics if m.ws_status == "warn")
            thread_fail_count = sum(1 for m in metrics if m.thread_status == "fail")
            thread_warn_count = sum(1 for m in metrics if m.thread_status == "warn")
            overall_fail_count = sum(1 for m in metrics if m.overall_status == "fail")
            overall_warn_count = sum(1 for m in metrics if m.overall_status == "warn")

            return {
                "total_samples": len(metrics),
                "time_period_hours": hours,
                "fd": {
                    "current": fd_counts[-1] if fd_counts else 0,
                    "avg": sum(fd_counts) / len(fd_counts) if fd_counts else 0,
                    "min": min(fd_counts) if fd_counts else 0,
                    "max": max(fd_counts) if fd_counts else 0,
                    "fail_count": fd_fail_count,
                    "warn_count": fd_warn_count,
                },
                "memory": {
                    "current_mb": memory_rss[-1] if memory_rss else 0,
                    "avg_mb": sum(memory_rss) / len(memory_rss) if memory_rss else 0,
                    "min_mb": min(memory_rss) if memory_rss else 0,
                    "max_mb": max(memory_rss) if memory_rss else 0,
                    "fail_count": memory_fail_count,
                    "warn_count": memory_warn_count,
                },
                "database": {
                    "current": db_conns[-1] if db_conns else 0,
                    "avg": sum(db_conns) / len(db_conns) if db_conns else 0,
                    "min": min(db_conns) if db_conns else 0,
                    "max": max(db_conns) if db_conns else 0,
                },
                "websocket": {
                    "current": ws_conns[-1] if ws_conns else 0,
                    "avg": sum(ws_conns) / len(ws_conns) if ws_conns else 0,
                    "min": min(ws_conns) if ws_conns else 0,
                    "max": max(ws_conns) if ws_conns else 0,
                },
                "threads": {
                    "current": threads[-1] if threads else 0,
                    "avg": sum(threads) / len(threads) if threads else 0,
                    "min": min(threads) if threads else 0,
                    "max": max(threads) if threads else 0,
                },
                "status": {
                    "overall": {
                        "pass": len(metrics) - (overall_warn_count + overall_fail_count),
                        "warn": overall_warn_count,
                        "fail": overall_fail_count,
                    },
                    "fd": {"warn": fd_warn_count, "fail": fd_fail_count},
                    "memory": {"warn": memory_warn_count, "fail": memory_fail_count},
                    "database": {"warn": db_warn_count, "fail": db_fail_count},
                    "websocket": {"warn": ws_warn_count, "fail": ws_fail_count},
                    "threads": {"warn": thread_warn_count, "fail": thread_fail_count},
                },
            }
        except Exception as e:
            logger.exception(f"Error getting stats: {str(e)}")
            return {}


class HealthAlert(HealthBase):
    """Model for tracking health alerts"""

    __tablename__ = "health_alerts"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())

    alert_type = Column(String(50))  # fd_fail, memory_warn, etc.
    severity = Column(String(20))  # warn | fail
    metric_name = Column(String(50))  # fd_count, memory_rss_mb, etc.
    metric_value = Column(Float)
    threshold_value = Column(Float)
    message = Column(String(500))

    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime(timezone=True))

    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime(timezone=True))

    @staticmethod
    def create_alert(alert_type, severity, metric_name, metric_value, threshold_value, message):
        """Create a new alert"""
        try:
            # Check if similar alert already exists (not resolved)
            existing = (
                HealthAlert.query.filter_by(alert_type=alert_type, resolved=False)
                .order_by(HealthAlert.timestamp.desc())
                .first()
            )

            if existing:
                # Update existing alert timestamp
                existing.timestamp = datetime.now(timezone.utc)
                existing.metric_value = metric_value
                health_session.commit()
                return existing

            # Create new alert
            alert = HealthAlert(
                alert_type=alert_type,
                severity=severity,
                metric_name=metric_name,
                metric_value=metric_value,
                threshold_value=threshold_value,
                message=message,
            )
            health_session.add(alert)
            health_session.commit()
            logger.warning(f"Health alert created: {message}")
            return alert
        except Exception as e:
            logger.exception(f"Error creating alert: {str(e)}")
            health_session.rollback()
            return None

    @staticmethod
    def get_active_alerts():
        """Get all active (not resolved) alerts"""
        try:
            return (
                HealthAlert.query.filter_by(resolved=False)
                .order_by(HealthAlert.timestamp.desc())
                .all()
            )
        except Exception as e:
            logger.exception(f"Error getting active alerts: {str(e)}")
            return []

    @staticmethod
    def acknowledge_alert(alert_id):
        """Acknowledge an alert"""
        try:
            alert = HealthAlert.query.get(alert_id)
            if alert:
                alert.acknowledged = True
                alert.acknowledged_at = datetime.now(timezone.utc)
                health_session.commit()
                return True
            return False
        except Exception as e:
            logger.exception(f"Error acknowledging alert: {str(e)}")
            health_session.rollback()
            return False

    @staticmethod
    def resolve_alert(alert_id):
        """Resolve an alert"""
        try:
            alert = HealthAlert.query.get(alert_id)
            if alert:
                alert.resolved = True
                alert.resolved_at = datetime.now(timezone.utc)
                health_session.commit()
                logger.info(f"Alert resolved: {alert.message}")
                return True
            return False
        except Exception as e:
            logger.exception(f"Error resolving alert: {str(e)}")
            health_session.rollback()
            return False

    @staticmethod
    def auto_resolve_alerts(metric_name, current_value, healthy_threshold):
        """Automatically resolve alerts when metrics return to healthy range"""
        try:
            # Get active alerts for this metric
            alerts = HealthAlert.query.filter_by(metric_name=metric_name, resolved=False).all()

            for alert in alerts:
                # Resolve if current value is below healthy threshold
                if current_value < healthy_threshold:
                    alert.resolved = True
                    alert.resolved_at = datetime.now(timezone.utc)
                    logger.info(
                        f"Auto-resolved alert: {alert.message} "
                        f"(current: {current_value}, threshold: {healthy_threshold})"
                    )

            health_session.commit()
        except Exception as e:
            logger.exception(f"Error auto-resolving alerts: {str(e)}")
            health_session.rollback()


def init_health_db():
    """Initialize the health monitoring database"""
    # Extract directory from database URL and create if it doesn't exist
    db_path = HEALTH_DATABASE_URL.replace("sqlite:///", "")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    from database.db_init_helper import init_db_with_logging

    init_db_with_logging(HealthBase, health_engine, "Health Monitoring DB", logger)


def purge_old_metrics(days=7):
    """
    Purge metrics older than specified days to keep database size manageable.
    Keep alerts forever for historical analysis.
    """
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)

        # Delete old metrics
        deleted = (
            health_session.query(HealthMetric)
            .filter(HealthMetric.timestamp < cutoff)
            .delete(synchronize_session=False)
        )

        health_session.commit()
        logger.debug(f"Purged {deleted} old health metrics (older than {days} days)")
        return deleted
    except Exception as e:
        logger.exception(f"Error purging old metrics: {str(e)}")
        health_session.rollback()
        return 0
