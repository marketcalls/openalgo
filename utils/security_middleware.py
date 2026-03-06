import logging
from functools import wraps
from typing import Any, Callable, TypeVar

from flask import Flask, abort, jsonify, request

from database.traffic_db import Error404Tracker, IPBan, logs_session
from utils.ip_helper import get_real_ip, get_real_ip_from_environ

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


class SecurityMiddleware:
    """WSGI middleware that checks if the client IP is banned before processing requests.
    
    This middleware wraps the Flask application and intercepts incoming requests
    to check against the banned IP list. If an IP is banned, a 403 response
    is returned without invoking the application.
    """
    
    def __init__(self, app: Flask) -> None:
        """Initialize middleware with the WSGI application.
        
        Args:
            app: The Flask application to wrap.
        """
        self.app = app

    def __call__(self, environ: dict[str, Any], start_response: Callable) -> list[bytes]:
        """Check IP ban status and either block or forward the request.
        
        Args:
            environ: WSGI environment dictionary containing request information.
            start_response: WSGI callable to set response status and headers.
            
        Returns:
            List of bytes containing the response body.
        """
        # Get real client IP (handles proxies)
        client_ip = get_real_ip_from_environ(environ)

        # Check if IP is banned
        if IPBan.is_ip_banned(client_ip):
            # Clean up scoped session — this runs at WSGI level, outside Flask
            # request context, so blueprint/app teardown handlers won't fire.
            logs_session.remove()

            # Return 403 Forbidden for banned IPs
            status = "403 Forbidden"
            headers = [("Content-Type", "text/plain")]
            start_response(status, headers)
            logger.warning(f"Blocked banned IP: {client_ip}")
            return [b"Access Denied: Your IP has been banned"]

        # For non-banned IPs: session cleanup is handled by Flask's
        # teardown_app_request in traffic.py and security.py blueprints.
        return self.app(environ, start_response)


def check_ip_ban(f: F) -> F:
    """Decorator that returns 403 if the client IP is banned.
    
    This decorator checks if the client's IP address is in the banned list
    before executing the decorated function. If the IP is banned, a 403
    response is returned.
    
    Args:
        f: The function to decorate.
        
    Returns:
        The decorated function with IP ban checking.
    """
    
    @wraps(f)
    def decorated_function(*args: Any, **kwargs: Any) -> Any:
        client_ip = get_real_ip()

        if IPBan.is_ip_banned(client_ip):
            logger.warning(f"Blocked banned IP in decorator: {client_ip}")
            abort(403, description="Access Denied: Your IP has been banned")

        return f(*args, **kwargs)

    return decorated_function  # type: ignore[return-value]


def init_security_middleware(app: Flask) -> None:
    """Initialize and register security middleware with the Flask application.
    
    Args:
        app: The Flask application instance.
    """
    # Wrap the WSGI app with security middleware
    app.wsgi_app = SecurityMiddleware(app.wsgi_app)

    logger.debug("Security middleware initialized")

    # Note: 404 handler is now in app.py to avoid conflicts
    # The main app's 404 handler calls Error404Tracker.track_404()

    # Register 403 error handler for banned IPs
    @app.errorhandler(403)
    def handle_403(e: Exception) -> tuple[dict[str, str], int]:
        return jsonify({"error": "Access Denied"}), 403

    logger.debug("Security middleware initialized")
