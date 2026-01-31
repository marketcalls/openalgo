"""
Health Monitoring Blueprint

Industry-standard health check endpoints:
- GET /health/status - Simple 200 OK for AWS ELB, K8s probes (unauthenticated)
- GET /health/check - DB connectivity + detailed status (unauthenticated)
- GET /health/api/* - Metrics API endpoints (authenticated)

Dashboard UI is served by React at /health (see frontend/src/pages/HealthMonitor.tsx)

Follows draft-inadarei-api-health-check-06 specification.
ZERO LATENCY IMPACT - all metrics collected in background thread.
"""

import csv
import io
from datetime import datetime

import pytz
from flask import Blueprint, Response, jsonify, request

from database.health_db import HealthAlert, HealthMetric, health_session
from limiter import limiter
from utils.health_monitor import check_db_connectivity, get_cached_health_status
from utils.logging import get_logger
from utils.session import check_session_validity

logger = get_logger(__name__)

health_bp = Blueprint("health_bp", __name__, url_prefix="/health")


def convert_to_ist(timestamp):
    """Convert UTC timestamp to IST"""
    if isinstance(timestamp, str):
        timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    utc = pytz.timezone("UTC")
    ist = pytz.timezone("Asia/Kolkata")
    if timestamp.tzinfo is None:
        timestamp = utc.localize(timestamp)
    return timestamp.astimezone(ist)


def format_ist_time(timestamp):
    """Format timestamp in IST with 12-hour format"""
    ist_time = convert_to_ist(timestamp)
    return ist_time.strftime("%d-%m-%Y %I:%M:%S %p")


# ============================================================================
# Simple Health Checks (for AWS ELB, K8s, Docker, monitoring tools)
# ============================================================================


@health_bp.route("/status", methods=["GET"])
@limiter.limit("300/minute")  # High limit for load balancer polling
def simple_health():
    """
    Simple health check endpoint for AWS ELB, Kubernetes probes, Docker healthcheck.
    Returns instant 200 OK if service is running.

    Use /health/status for load balancers (unauthenticated JSON response).
    Use /health for the React dashboard UI.

    This endpoint uses cached metrics (ZERO latency impact).
    Does not require authentication.

    Response format follows draft-inadarei-api-health-check:
    {
        "status": "pass"|"warn"|"fail",
        "version": "1.0",
        "releaseId": "...",
        "serviceId": "openalgo"
    }
    """
    try:
        # Get cached status (instant, no DB query)
        health_status = get_cached_health_status()

        status_code = 200
        if health_status["status"] == "warn":
            status_code = 200  # Still operational, just degraded
        elif health_status["status"] == "fail":
            status_code = 503  # Service unavailable

        return (
            jsonify(
                {
                    "status": health_status["status"],
                    "version": "1.0",
                    "serviceId": "openalgo",
                    "description": "OpenAlgo Trading Platform",
                }
            ),
            status_code,
        )
    except Exception as e:
        logger.error(f"Error in simple health check: {e}")
        return jsonify({"status": "fail", "description": str(e)}), 503


@health_bp.route("/check", methods=["GET"])
@limiter.limit("60/minute")
def detailed_health_check():
    """
    Detailed health check with component status.
    Includes database connectivity checks.

    Suitable for monitoring tools that need detailed status.
    Does not require authentication.

    Response format follows draft-inadarei-api-health-check:
    {
        "status": "pass"|"warn"|"fail",
        "version": "1.0",
        "serviceId": "openalgo",
        "checks": {
            "database:connectivity": [{
                "componentId": "openalgo",
                "status": "pass"|"fail",
                "time": "2026-01-30T10:15:30Z"
            }],
            "system:file-descriptors": [{
                "componentId": "fd_count",
                "status": "pass"|"warn"|"fail",
                "observedValue": 156,
                "observedUnit": "count"
            }],
            ...
        }
    }
    """
    try:
        # Get cached metrics (instant)
        cached_status = get_cached_health_status()

        # Perform DB connectivity check (adds ~10-50ms)
        db_check = check_db_connectivity()

        # Get current metrics from cache
        current_metric = HealthMetric.get_current_metrics()

        checks = {}

        # Database connectivity checks
        if db_check and "databases" in db_check:
            checks["database:connectivity"] = []
            for db_name, status in db_check["databases"].items():
                checks["database:connectivity"].append(
                    {
                        "componentId": db_name,
                        "status": status,
                        "time": datetime.utcnow().isoformat() + "Z",
                    }
                )

        # File descriptor checks
        if current_metric and current_metric.fd_count is not None:
            checks["system:file-descriptors"] = [
                {
                    "componentId": "fd_count",
                    "status": current_metric.fd_status or "pass",
                    "observedValue": current_metric.fd_count,
                    "observedUnit": "count",
                    "time": current_metric.timestamp.isoformat() + "Z"
                    if current_metric.timestamp
                    else None,
                }
            ]

        # Memory checks
        if current_metric and current_metric.memory_rss_mb is not None:
            checks["system:memory"] = [
                {
                    "componentId": "rss",
                    "status": current_metric.memory_status or "pass",
                    "observedValue": round(current_metric.memory_rss_mb, 2),
                    "observedUnit": "MiB",
                    "time": current_metric.timestamp.isoformat() + "Z"
                    if current_metric.timestamp
                    else None,
                }
            ]

        # Include WebSocket proxy resource health if available (best-effort)
        try:
            from websocket_proxy import get_resource_health

            ws_health = get_resource_health()
            checks["websocket:proxy"] = [
                {
                    "componentId": "websocket_proxy",
                    "status": "pass",
                    "observedValue": ws_health.get("active_pools", {}).get("count", 0),
                    "observedUnit": "count",
                    "time": datetime.utcnow().isoformat() + "Z",
                }
            ]
        except Exception:
            pass

        # Overall status (worst of all checks)
        overall_status = "pass"
        if db_check["status"] == "fail":
            overall_status = "fail"
        elif cached_status["status"] == "fail":
            overall_status = "fail"
        elif cached_status["status"] == "warn" or db_check["status"] == "warn":
            overall_status = "warn"

        status_code = 200
        if overall_status == "fail":
            status_code = 503

        return (
            jsonify(
                {
                    "status": overall_status,
                    "version": "1.0",
                    "serviceId": "openalgo",
                    "description": "OpenAlgo Trading Platform",
                    "checks": checks,
                }
            ),
            status_code,
        )

    except Exception as e:
        logger.exception(f"Error in detailed health check: {e}")
        return (
            jsonify(
                {
                    "status": "fail",
                    "version": "1.0",
                    "serviceId": "openalgo",
                    "description": str(e),
                }
            ),
            503,
        )


# ============================================================================
# Dashboard - Served by React (see frontend/src/pages/HealthMonitor.tsx)
# Route: /health (handled by React Router in App.tsx)
# ============================================================================

# Note: The dashboard UI is now a React component at /health
# All data is fetched via API endpoints below

# ============================================================================
# API Endpoints (Authenticated)
# ============================================================================


@health_bp.route("/api/current", methods=["GET"])
@check_session_validity
@limiter.limit("60/minute")
def get_current_metrics():
    """Get current metrics snapshot"""
    try:
        metric = HealthMetric.get_current_metrics()
        if not metric:
            return jsonify({"error": "No metrics available"}), 404

        return jsonify(
            {
                "timestamp": convert_to_ist(metric.timestamp).isoformat(),
                "fd": {
                    "count": metric.fd_count,
                    "limit": metric.fd_limit,
                    "usage_percent": metric.fd_usage_percent,
                    "status": metric.fd_status,
                },
                "memory": {
                    "rss_mb": metric.memory_rss_mb,
                    "vms_mb": metric.memory_vms_mb,
                    "percent": metric.memory_percent,
                    "available_mb": metric.memory_available_mb,
                    "swap_mb": metric.memory_swap_mb,
                    "status": metric.memory_status,
                },
                "database": {
                    "total": metric.db_connections_total,
                    "connections": metric.db_connections,
                    "status": metric.db_status,
                },
                "websocket": {
                    "total": metric.ws_connections_total,
                    "connections": metric.ws_connections,
                    "total_symbols": metric.ws_total_symbols,
                    "status": metric.ws_status,
                },
                "threads": {
                    "count": metric.thread_count,
                    "stuck": metric.stuck_threads,
                    "status": metric.thread_status,
                    "details": metric.thread_details,
                },
                "processes": metric.process_details or [],
                "overall_status": metric.overall_status,
            }
        )
    except Exception as e:
        logger.exception(f"Error fetching current metrics: {e}")
        return jsonify({"error": str(e)}), 500


@health_bp.route("/api/history", methods=["GET"])
@check_session_validity
@limiter.limit("60/minute")
def get_metrics_history():
    """Get metrics history"""
    try:
        hours = min(max(int(request.args.get("hours", 24)), 1), 168)  # Range [1, 168]
        metrics = HealthMetric.get_metrics_history(hours=hours)

        return jsonify(
            [
                {
                    "timestamp": convert_to_ist(m.timestamp).isoformat(),
                    "fd_count": m.fd_count,
                    "memory_rss_mb": m.memory_rss_mb,
                    "db_connections": m.db_connections_total,
                    "ws_connections": m.ws_connections_total,
                    "threads": m.thread_count,
                    "overall_status": m.overall_status,
                }
                for m in metrics
            ]
        )
    except Exception as e:
        logger.exception(f"Error fetching metrics history: {e}")
        return jsonify({"error": str(e)}), 500


@health_bp.route("/api/stats", methods=["GET"])
@check_session_validity
@limiter.limit("60/minute")
def get_health_stats():
    """Get aggregated statistics"""
    try:
        hours = min(max(int(request.args.get("hours", 24)), 1), 168)  # Range [1, 168]
        stats = HealthMetric.get_stats(hours=hours)
        return jsonify(stats)
    except Exception as e:
        logger.exception(f"Error fetching stats: {e}")
        return jsonify({"error": str(e)}), 500


@health_bp.route("/api/alerts", methods=["GET"])
@check_session_validity
@limiter.limit("60/minute")
def get_alerts():
    """Get active alerts"""
    try:
        alerts = HealthAlert.get_active_alerts()
        return jsonify(
            [
                {
                    "id": alert.id,
                    "timestamp": convert_to_ist(alert.timestamp).isoformat(),
                    "alert_type": alert.alert_type,
                    "severity": alert.severity,
                    "metric_name": alert.metric_name,
                    "metric_value": alert.metric_value,
                    "threshold_value": alert.threshold_value,
                    "message": alert.message,
                    "acknowledged": alert.acknowledged,
                    "resolved": alert.resolved,
                }
                for alert in alerts
            ]
        )
    except Exception as e:
        logger.exception(f"Error fetching alerts: {e}")
        return jsonify({"error": str(e)}), 500


@health_bp.route("/api/alerts/<int:alert_id>/acknowledge", methods=["POST"])
@check_session_validity
@limiter.limit("30/minute")
def acknowledge_alert(alert_id):
    """Acknowledge an alert"""
    try:
        success = HealthAlert.acknowledge_alert(alert_id)
        if success:
            return jsonify({"status": "success", "message": "Alert acknowledged"})
        return jsonify({"status": "error", "message": "Alert not found"}), 404
    except Exception as e:
        logger.exception(f"Error acknowledging alert: {e}")
        return jsonify({"error": str(e)}), 500


@health_bp.route("/api/alerts/<int:alert_id>/resolve", methods=["POST"])
@check_session_validity
@limiter.limit("30/minute")
def resolve_alert(alert_id):
    """Resolve an alert"""
    try:
        success = HealthAlert.resolve_alert(alert_id)
        if success:
            return jsonify({"status": "success", "message": "Alert resolved"})
        return jsonify({"status": "error", "message": "Alert not found"}), 404
    except Exception as e:
        logger.exception(f"Error resolving alert: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Export
# ============================================================================


@health_bp.route("/export", methods=["GET"])
@check_session_validity
@limiter.limit("10/minute")
def export_metrics():
    """Export metrics to CSV"""
    try:
        hours = min(max(int(request.args.get("hours", 24)), 1), 168)  # Range [1, 168]
        metrics = HealthMetric.get_metrics_history(hours=hours)

        # Generate CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # Write header
        writer.writerow(
            [
                "Date & Time (IST)",
                "FD Count",
                "FD Limit",
                "FD Status",
                "Memory (MB)",
                "Memory Status",
                "DB Connections",
                "DB Status",
                "WebSocket Connections",
                "WS Status",
                "Threads",
                "Thread Status",
                "Overall Status",
            ]
        )

        # Write data
        for metric in metrics:
            writer.writerow(
                [
                    format_ist_time(metric.timestamp),
                    metric.fd_count or 0,
                    metric.fd_limit or 0,
                    metric.fd_status or "unknown",
                    round(metric.memory_rss_mb, 2) if metric.memory_rss_mb else 0,
                    metric.memory_status or "unknown",
                    metric.db_connections_total or 0,
                    metric.db_status or "unknown",
                    metric.ws_connections_total or 0,
                    metric.ws_status or "unknown",
                    metric.thread_count or 0,
                    metric.thread_status or "unknown",
                    metric.overall_status or "unknown",
                ]
            )

        csv_data = output.getvalue()

        # Create response
        response = Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=health_metrics.csv"},
        )

        return response

    except Exception as e:
        logger.exception(f"Error exporting metrics: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Teardown
# ============================================================================


@health_bp.teardown_app_request
def shutdown_session(exception=None):
    """Remove scoped session after request"""
    health_session.remove()
