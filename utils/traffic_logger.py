from flask import request, g, has_request_context
from database.traffic_db import TrafficLog, logs_session
import time
from utils.logging import get_logger

logger = get_logger(__name__)

class TrafficLoggerMiddleware:
    def __init__(self, app):
        self.app = app
        
    def __call__(self, environ, start_response):
        path_info = environ.get('PATH_INFO', '')
        
        # Skip logging for:
        # 1. Static files and favicon
        # 2. Traffic monitoring endpoints themselves
        if (path_info.startswith('/static/') or 
            path_info == '/favicon.ico' or 
            path_info.startswith('/api/v1/latency/logs') or
            path_info.startswith('/traffic/') or
            path_info.startswith('/traffic/api/')):
            return self.app(environ, start_response)
            
        # Record start time
        start_time = time.time()
        
        def log_request(status_code, error=None):
            if not has_request_context():
                return
                
            try:
                duration_ms = (time.time() - start_time) * 1000
                TrafficLog.log_request(
                    client_ip=request.remote_addr,
                    method=request.method,
                    path=request.path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    host=request.host,
                    error=error,
                    user_id=getattr(g, 'user_id', None)
                )
            except Exception as e:
                logger.error(f"Error logging traffic: {e}")
            finally:
                logs_session.remove()
        
        # Store the original start_response to intercept the status code
        def custom_start_response(status, headers, exc_info=None):
            status_code = int(status.split()[0])
            try:
                log_request(status_code)
            except Exception as e:
                logger.error(f"Error in custom_start_response: {e}")
            return start_response(status, headers, exc_info)
            
        # Process the request
        try:
            return self.app(environ, custom_start_response)
        except Exception as e:
            # Log error and re-raise
            try:
                log_request(500, str(e))
            except Exception as log_error:
                logger.error(f"Error logging exception: {log_error}")
            raise

def init_traffic_logging(app):
    """Initialize traffic logging middleware"""
    # Initialize the logs database
    from database.traffic_db import init_logs_db
    init_logs_db()
    
    # Add middleware
    app.wsgi_app = TrafficLoggerMiddleware(app.wsgi_app)
