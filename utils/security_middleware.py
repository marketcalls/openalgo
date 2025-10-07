from flask import request, abort, jsonify
from database.traffic_db import IPBan, Error404Tracker, logs_session
from functools import wraps
from utils.ip_helper import get_real_ip, get_real_ip_from_environ
import logging

logger = logging.getLogger(__name__)

class SecurityMiddleware:
    """Middleware to check for banned IPs and handle security"""

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        # Get real client IP (handles proxies)
        client_ip = get_real_ip_from_environ(environ)

        # Check if IP is banned
        if IPBan.is_ip_banned(client_ip):
            # Return 403 Forbidden for banned IPs
            status = '403 Forbidden'
            headers = [('Content-Type', 'text/plain')]
            start_response(status, headers)
            logger.warning(f"Blocked banned IP: {client_ip}")
            return [b'Access Denied: Your IP has been banned']

        # Continue with normal request processing
        return self.app(environ, start_response)

def check_ip_ban(f):
    """Decorator to check if IP is banned before processing request"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        client_ip = get_real_ip()

        if IPBan.is_ip_banned(client_ip):
            logger.warning(f"Blocked banned IP in decorator: {client_ip}")
            abort(403, description="Access Denied: Your IP has been banned")

        return f(*args, **kwargs)

    return decorated_function

def init_security_middleware(app):
    """Initialize security middleware"""
    # Wrap the WSGI app with security middleware
    app.wsgi_app = SecurityMiddleware(app.wsgi_app)

    logger.info("Security middleware initialized")

    # Note: 404 handler is now in app.py to avoid conflicts
    # The main app's 404 handler calls Error404Tracker.track_404()

    # Register 403 error handler for banned IPs
    @app.errorhandler(403)
    def handle_403(e):
        return jsonify({'error': 'Access Denied'}), 403

    logger.info("Security middleware initialized")