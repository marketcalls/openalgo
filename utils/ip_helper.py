import os
import logging

from flask import request

logger = logging.getLogger(__name__)


def get_real_ip():
    """
    Get the real client IP address, handling proxy headers securely.

    This function relies on the ProxyFix middleware being configured 
    in the Flask app via the TRUSTED_PROXIES environment variable.
    
    If TRUSTED_PROXIES is 0 (default), it returns request.remote_addr 
    directly, which is the peer IP. This prevents header spoofing.
    
    If TRUSTED_PROXIES > 0, ProxyFix will have already populated 
    request.remote_addr with the correct client IP from X-Forwarded-For.

    Returns:
        str: The real client IP address
    """
    trusted_proxies = os.getenv("TRUSTED_PROXIES", "0")
    
    # If we trust our proxy configuration, request.remote_addr is already fixed
    if trusted_proxies.isdigit() and int(trusted_proxies) > 0:
        return request.remote_addr

    # If not behind a proxy (or not configured), headers cannot be trusted
    # as they are trivially spoofable by the client.
    return request.remote_addr


def get_real_ip_from_environ(environ):
    """
    Get the real client IP address from WSGI environ securely.
    Used in middleware where Flask request object is not available.

    If OpenAlgo is behind a reverse proxy, ensure TRUSTED_PROXIES 
    is set in .env so ProxyFix middleware correctly populates REMOTE_ADDR.

    Args:
        environ: WSGI environment dictionary

    Returns:
        str: The client IP address
    """
    return environ.get("REMOTE_ADDR", "")
