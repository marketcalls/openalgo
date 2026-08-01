"""
Shared httpx client module with connection pooling support for all broker APIs
with automatic protocol negotiation (HTTP/2 when available, HTTP/1.1 fallback)
"""

import os
import threading
from typing import Optional

import httpx

from utils.logging import get_logger

# Set up logging
logger = get_logger(__name__)

# Global httpx client for connection pooling
_httpx_client = None

# Guards creation and teardown of the shared client.
#
# The previous `if _httpx_client is None: _httpx_client = _create_http_client()`
# is a check-then-act. Under eventlet it could not interleave, so the first
# caller always won. With real threads, two cold callers can both see None and
# both build a client with its own 100-connection pool -- the loser's pool is
# then unreachable and never closed, which is a file-descriptor leak in a
# worker that never restarts.
_httpx_client_lock = threading.RLock()

# Pool-acquisition timeout, kept separate from the 120s request timeout.
# A scalar timeout applies to pool waits too, so a saturated pool used to
# surface as a two-minute hang rather than an error. Seconds.
POOL_TIMEOUT = float(os.getenv("HTTPX_POOL_TIMEOUT", "10"))


def get_httpx_client() -> httpx.Client:
    """
    Returns an HTTP client with automatic protocol negotiation.
    The client will use HTTP/2 when the server supports it,
    otherwise automatically falls back to HTTP/1.1.

    Returns:
        httpx.Client: A configured HTTP client with protocol auto-negotiation
    """
    global _httpx_client

    # Fast path: already built, no lock needed for a plain attribute read.
    client = _httpx_client
    if client is not None:
        return client

    with _httpx_client_lock:
        # Re-check inside the lock: another thread may have built it while we
        # waited, and we must not replace a client others are already using.
        if _httpx_client is None:
            _httpx_client = _create_http_client()
            logger.debug(
                "Created HTTP client with automatic protocol negotiation "
                "(HTTP/2 preferred, HTTP/1.1 fallback)"
            )
        return _httpx_client


def get_pool_stats() -> dict:
    """Connection-pool saturation, for the thread-budget work in B1.

    The shared pool is consumed by Gunicorn request threads *and* by bot,
    keepalive, streaming and scheduler threads, so its saturation is not
    predictable from the worker thread count alone -- it has to be measured.
    """
    client = _httpx_client
    if client is None:
        return {"created": False}

    stats = {"created": True, "max_connections": None, "in_use": None, "pool_timeout": POOL_TIMEOUT}
    try:
        pool = client._transport._pool
        stats["max_connections"] = pool._max_connections
        stats["in_use"] = len(pool.connections)
    except Exception:  # pragma: no cover - httpx internals are not a contract
        logger.debug("Could not read httpx pool internals for saturation stats")
    return stats


def request(method: str, url: str, **kwargs) -> httpx.Response:
    """
    Make an HTTP request using the shared client with automatic protocol negotiation.

    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL to request
        **kwargs: Additional arguments to pass to the request

    Returns:
        httpx.Response: The HTTP response

    Raises:
        httpx.HTTPError: If the request fails
    """
    import time

    from flask import g

    client = get_httpx_client()

    # Track actual broker API call time for latency monitoring
    broker_api_start = time.time()
    response = client.request(method, url, **kwargs)
    broker_api_end = time.time()

    # Store broker API time in Flask's g object for latency tracking
    if hasattr(g, "latency_tracker"):
        broker_api_time_ms = (broker_api_end - broker_api_start) * 1000
        g.broker_api_time = broker_api_time_ms
        logger.debug(f"Broker API call took {broker_api_time_ms:.2f}ms")

    # Log the actual HTTP version used (info level for visibility)
    if response.http_version:
        logger.info(f"Request used {response.http_version} - URL: {url[:50]}...")

    return response


# Shortcut methods for common HTTP methods
def get(url: str, **kwargs) -> httpx.Response:
    """
    Send a GET request.

    Args:
        url (str): The URL to send the GET request to.
        **kwargs: Additional arguments passed to the underlying request method.

    Returns:
        httpx.Response: The HTTP response from the server.
    """
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> httpx.Response:
    """
    Send a POST request.

    Args:
        url (str): The URL to send the POST request to.
        **kwargs: Additional arguments passed to the underlying request method.

    Returns:
        httpx.Response: The HTTP response from the server.
    """
    return request("POST", url, **kwargs)


def put(url: str, **kwargs) -> httpx.Response:
    """
    Send a PUT request.

    Args:
        url (str): The URL to send the PUT request to.
        **kwargs: Additional arguments passed to the underlying request method.

    Returns:
        httpx.Response: The HTTP response from the server.
    """
    return request("PUT", url, **kwargs)


def delete(url: str, **kwargs) -> httpx.Response:
    """
    Send a DELETE request.

    Args:
        url (str): The URL to send the DELETE request to.
        **kwargs: Additional arguments passed to the underlying request method.

    Returns:
        httpx.Response: The HTTP response from the server.
    """
    return request("DELETE", url, **kwargs)


def _create_http_client() -> httpx.Client:
    """
    Create a new HTTP client with automatic protocol negotiation and latency tracking.
    Enables both HTTP/2 and HTTP/1.1, letting httpx choose the best protocol.

    Returns:
        httpx.Client: A configured HTTP client with protocol auto-negotiation and timing hooks
    """
    import os
    import time

    from flask import g

    # Event hooks for tracking broker API timing
    def log_request(request):
        """Hook called before request is sent"""
        request.extensions["start_time"] = time.time()
        logger.debug(f"Starting request to {request.url}")

    def log_response(response):
        """Hook called after response is received"""
        try:
            start_time = response.request.extensions.get("start_time")
            if start_time:
                duration_ms = (time.time() - start_time) * 1000

                # Store broker API time in Flask's g object for latency tracking
                try:
                    from flask import has_request_context

                    if has_request_context() and hasattr(g, "latency_tracker"):
                        g.broker_api_time = duration_ms
                        logger.debug(f"Broker API call took {duration_ms:.2f}ms")
                except (RuntimeError, AttributeError):
                    # Not in Flask request context or g not available
                    pass

                logger.debug(f"Request completed in {duration_ms:.2f}ms")
        except Exception as e:
            logger.exception(f"Error in response hook: {e}")

    try:
        # Detect if running in standalone mode (Docker/production) vs integrated mode (local dev)
        # In standalone mode, disable HTTP/2 to avoid protocol negotiation issues
        app_mode = os.environ.get("APP_MODE", "integrated").strip().strip("'\"")
        is_standalone = app_mode == "standalone"

        # Disable HTTP/2 in standalone/Docker environments to avoid protocol negotiation issues
        http2_enabled = not is_standalone

        client = httpx.Client(
            http2=http2_enabled,  # Disable HTTP/2 in standalone mode, enable in integrated mode
            http1=True,  # Always enable HTTP/1.1 for compatibility
            # Explicit per-phase timeouts. A scalar timeout also governs pool
            # acquisition, so a saturated pool surfaced as a 120s hang instead
            # of a prompt PoolTimeout. Keep the generous read budget for large
            # historical downloads, but fail fast when no connection is free.
            timeout=httpx.Timeout(120.0, pool=POOL_TIMEOUT),
            limits=httpx.Limits(
                max_keepalive_connections=40,  # Increased from 20 for multi-strategy environments
                max_connections=100,  # Increased from 50 for 10+ concurrent strategies
                keepalive_expiry=30.0,  # Reduced from 120s to recycle stale connections faster
            ),
            # Add verify parameter to handle SSL/TLS issues in standalone mode
            verify=True,  # Can be set to False for debugging SSL issues (not recommended for production)
            # Add event hooks for latency tracking
            event_hooks={"request": [log_request], "response": [log_response]},
        )

        if is_standalone:
            logger.debug("Running in standalone mode - HTTP/2 disabled for compatibility")
        else:
            logger.debug("Running in integrated mode - HTTP/2 enabled for optimal performance")

        return client

    except Exception as e:
        logger.exception(f"Failed to create HTTP client: {e}")
        raise


def cleanup_httpx_client() -> None:
    """
    Closes the global httpx client and releases its resources.

    Should be called when the application is shutting down to prevent
    resource leaks.

    Returns:
        None
    """
    global _httpx_client

    # Same lock as construction: closing while another thread is mid-build
    # would leave a live client bound to a closed transport.
    with _httpx_client_lock:
        if _httpx_client is not None:
            _httpx_client.close()
            _httpx_client = None
            logger.info("Closed HTTP client")
