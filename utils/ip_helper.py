from flask import request
import logging

logger = logging.getLogger(__name__)

def get_real_ip():
    """
    Get the real client IP address, handling proxy headers.

    Checks headers in order of preference:
    1. CF-Connecting-IP (Cloudflare - highest priority since you're using Cloudflare)
    2. X-Real-IP (commonly set by nginx)
    3. X-Forwarded-For (standard proxy header, uses first IP if multiple)
    4. True-Client-IP (Cloudflare Enterprise)
    5. X-Client-IP (some proxies)
    6. request.remote_addr (fallback to direct connection)

    Returns:
        str: The most likely real client IP address
    """
    # Try Cloudflare header first (since you're using Cloudflare)
    cf_ip = request.headers.get('CF-Connecting-IP')
    if cf_ip:
        logger.debug(f"Using CF-Connecting-IP: {cf_ip}")
        return cf_ip

    # Try Cloudflare Enterprise header
    true_client = request.headers.get('True-Client-IP')
    if true_client:
        logger.debug(f"Using True-Client-IP: {true_client}")
        return true_client

    # Try X-Real-IP (most reliable when properly configured)
    real_ip = request.headers.get('X-Real-IP')
    if real_ip:
        logger.debug(f"Using X-Real-IP: {real_ip}")
        return real_ip

    # Try X-Forwarded-For (may contain multiple IPs)
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
        # The first IP should be the original client
        ips = [ip.strip() for ip in forwarded_for.split(',')]
        if ips and ips[0]:
            logger.debug(f"Using X-Forwarded-For (first IP): {ips[0]}")
            return ips[0]

    # Try X-Client-IP
    client_ip = request.headers.get('X-Client-IP')
    if client_ip:
        logger.debug(f"Using X-Client-IP: {client_ip}")
        return client_ip

    # Fallback to remote_addr
    remote_addr = request.remote_addr
    logger.debug(f"Using request.remote_addr (direct connection): {remote_addr}")
    return remote_addr

def get_real_ip_from_environ(environ):
    """
    Get the real client IP address from WSGI environ, handling proxy headers.
    Used in middleware where Flask request object is not available.

    Args:
        environ: WSGI environment dictionary

    Returns:
        str: The most likely real client IP address
    """
    # Try Cloudflare header first (since you're using Cloudflare)
    cf_ip = environ.get('HTTP_CF_CONNECTING_IP')
    if cf_ip:
        logger.debug(f"Using CF-Connecting-IP from environ: {cf_ip}")
        return cf_ip

    # Try Cloudflare Enterprise header
    true_client = environ.get('HTTP_TRUE_CLIENT_IP')
    if true_client:
        logger.debug(f"Using True-Client-IP from environ: {true_client}")
        return true_client

    # Try X-Real-IP
    real_ip = environ.get('HTTP_X_REAL_IP')
    if real_ip:
        logger.debug(f"Using X-Real-IP from environ: {real_ip}")
        return real_ip

    # Try X-Forwarded-For
    forwarded_for = environ.get('HTTP_X_FORWARDED_FOR')
    if forwarded_for:
        # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
        # The first IP should be the original client
        ips = [ip.strip() for ip in forwarded_for.split(',')]
        if ips and ips[0]:
            logger.debug(f"Using X-Forwarded-For from environ (first IP): {ips[0]}")
            return ips[0]

    # Try X-Client-IP
    client_ip = environ.get('HTTP_X_CLIENT_IP')
    if client_ip:
        logger.debug(f"Using X-Client-IP from environ: {client_ip}")
        return client_ip

    # Fallback to REMOTE_ADDR
    remote_addr = environ.get('REMOTE_ADDR', '')
    logger.debug(f"Using REMOTE_ADDR from environ (direct connection): {remote_addr}")
    return remote_addr