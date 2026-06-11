import time
from concurrent.futures import ThreadPoolExecutor

from flask import g, has_request_context, request

from database.traffic_db import TrafficLog, logs_session
from utils.ip_helper import get_real_ip
from utils.logging import get_logger

logger = get_logger(__name__)

# Shared single-worker executor: traffic-log commits run off the request
# thread so the SQLite fsync never delays the HTTP response. One worker keeps
# writes serialized (no lock contention) and bounds the scoped session to a
# single long-lived thread.
_traffic_log_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="traffic-log")


def _write_traffic_log(payload):
    """Persist one traffic log entry. Runs on the executor thread."""
    try:
        TrafficLog.log_request(**payload)
    except Exception as e:
        logger.exception(f"Error writing traffic log: {e}")
    finally:
        logs_session.remove()


class TrafficLoggerMiddleware:
    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        path_info = environ.get("PATH_INFO", "")

        # Skip logging for:
        # 1. Static files and favicon
        # 2. Traffic monitoring endpoints themselves
        if (
            path_info.startswith("/static/")
            or path_info == "/favicon.ico"
            or path_info.startswith("/api/v1/latency/logs")
            or path_info.startswith("/traffic/")
            or path_info.startswith("/traffic/api/")
        ):
            return self.app(environ, start_response)

        # Record start time
        start_time = time.time()

        def log_request(status_code, error=None):
            if not has_request_context():
                return

            try:
                duration_ms = (time.time() - start_time) * 1000
                # Capture request-context values now; the DB write happens on
                # the executor thread where the Flask context is gone.
                payload = {
                    "client_ip": get_real_ip(),
                    "method": request.method,
                    "path": request.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                    "host": request.host,
                    "error": error,
                    "user_id": getattr(g, "user_id", None),
                }
                _traffic_log_executor.submit(_write_traffic_log, payload)
            except Exception as e:
                logger.exception(f"Error logging traffic: {e}")

        # Store the original start_response to intercept the status code
        def custom_start_response(status, headers, exc_info=None):
            status_code = int(status.split()[0])
            try:
                log_request(status_code)
            except Exception as e:
                logger.exception(f"Error in custom_start_response: {e}")
            return start_response(status, headers, exc_info)

        # Process the request
        try:
            return self.app(environ, custom_start_response)
        except Exception as e:
            # Log error and re-raise
            try:
                log_request(500, str(e))
            except Exception as log_error:
                logger.exception(f"Error logging exception: {log_error}")
            raise


def init_traffic_logging(app):
    """Initialize traffic logging middleware"""
    # Initialize the logs database
    from database.traffic_db import init_logs_db, purge_old_traffic_logs

    init_logs_db()

    # Drop traffic log entries past the retention window so logs.db does not
    # grow unbounded over the install's lifetime
    purge_old_traffic_logs()

    # Add middleware
    app.wsgi_app = TrafficLoggerMiddleware(app.wsgi_app)
