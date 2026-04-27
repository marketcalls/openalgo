import logging
import os

from flask import request

logger = logging.getLogger(__name__)


def _trust_proxy_headers() -> bool:
    """Whether to honour client-supplied forwarded-IP headers.

    Defaults to False. When False, ``get_real_ip()`` and
    ``get_real_ip_from_environ()`` return the immediate peer only and
    ignore ``CF-Connecting-IP`` / ``X-Forwarded-For`` / ``X-Real-IP`` /
    ``True-Client-IP`` / ``X-Client-IP``.

    Set ``TRUST_PROXY_HEADERS=TRUE`` in .env ONLY when a reverse proxy
    (nginx / Cloudflare / a load balancer) sits in front of OpenAlgo and
    that proxy is the only path to the gunicorn/Flask listener. The
    ``install.sh``, ``install-docker.sh``, ``install-multi.sh``, and
    ``install-docker-multi-custom-ssl.sh`` scripts set this automatically
    because they configure the proxy as part of the install and bind
    gunicorn on a Unix socket / container-gateway-only port that cannot
    be reached directly from the internet.

    If gunicorn is bound on ``0.0.0.0`` with nothing in front of it,
    leave this OFF — any client could otherwise spoof any source IP just
    by sending forwarded-IP headers themselves, bypassing the IP ban
    list, the per-IP login rate-limiter, the 404 auto-ban tracker, and
    the login-attempt audit log.
    """
    return os.getenv("TRUST_PROXY_HEADERS", "false").lower() in ("true", "1", "yes", "t")


def get_real_ip():
    """
    Get the real client IP address.

    Behaviour depends on TRUST_PROXY_HEADERS (see ``_trust_proxy_headers``):

      * TRUST_PROXY_HEADERS=FALSE (default): returns ``request.remote_addr``
        only. Forwarded-IP headers are ignored, so an attacker reaching the
        gunicorn port directly cannot fake their source IP.

      * TRUST_PROXY_HEADERS=TRUE: walks the proxy headers in priority
        order — CF-Connecting-IP, True-Client-IP, X-Real-IP,
        X-Forwarded-For (first IP), X-Client-IP — falling back to
        ``request.remote_addr`` when none are set.

    Returns:
        str: The most likely real client IP address.
    """
    if _trust_proxy_headers():
        cf_ip = request.headers.get("CF-Connecting-IP")
        if cf_ip:
            logger.debug(f"Using CF-Connecting-IP: {cf_ip}")
            return cf_ip

        true_client = request.headers.get("True-Client-IP")
        if true_client:
            logger.debug(f"Using True-Client-IP: {true_client}")
            return true_client

        real_ip = request.headers.get("X-Real-IP")
        if real_ip:
            logger.debug(f"Using X-Real-IP: {real_ip}")
            return real_ip

        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            # X-Forwarded-For can contain multiple IPs: "client, proxy1, proxy2"
            # The first IP should be the original client.
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            if ips and ips[0]:
                logger.debug(f"Using X-Forwarded-For (first IP): {ips[0]}")
                return ips[0]

        client_ip = request.headers.get("X-Client-IP")
        if client_ip:
            logger.debug(f"Using X-Client-IP: {client_ip}")
            return client_ip

    # No trusted proxy mode (or no header found) — use the immediate peer.
    remote_addr = request.remote_addr
    logger.debug(f"Using request.remote_addr (direct connection): {remote_addr}")
    return remote_addr


def get_real_ip_from_environ(environ):
    """
    Get the real client IP address from a WSGI environ dict.

    Used by middleware that runs before Flask's request context exists
    (see ``utils/security_middleware.SecurityMiddleware``). Same gating
    behaviour as ``get_real_ip``: TRUST_PROXY_HEADERS=FALSE returns
    ``REMOTE_ADDR`` only; TRUST_PROXY_HEADERS=TRUE walks the forwarded
    headers in priority order.

    Args:
        environ: WSGI environment dictionary

    Returns:
        str: The most likely real client IP address.
    """
    if _trust_proxy_headers():
        cf_ip = environ.get("HTTP_CF_CONNECTING_IP")
        if cf_ip:
            logger.debug(f"Using CF-Connecting-IP from environ: {cf_ip}")
            return cf_ip

        true_client = environ.get("HTTP_TRUE_CLIENT_IP")
        if true_client:
            logger.debug(f"Using True-Client-IP from environ: {true_client}")
            return true_client

        real_ip = environ.get("HTTP_X_REAL_IP")
        if real_ip:
            logger.debug(f"Using X-Real-IP from environ: {real_ip}")
            return real_ip

        forwarded_for = environ.get("HTTP_X_FORWARDED_FOR")
        if forwarded_for:
            ips = [ip.strip() for ip in forwarded_for.split(",")]
            if ips and ips[0]:
                logger.debug(f"Using X-Forwarded-For from environ (first IP): {ips[0]}")
                return ips[0]

        client_ip = environ.get("HTTP_X_CLIENT_IP")
        if client_ip:
            logger.debug(f"Using X-Client-IP from environ: {client_ip}")
            return client_ip

    remote_addr = environ.get("REMOTE_ADDR", "")
    logger.debug(f"Using REMOTE_ADDR from environ (direct connection): {remote_addr}")
    return remote_addr
