"""
Shared httpx client module with connection pooling support for all broker APIs
with automatic protocol negotiation (HTTP/2 when available, HTTP/1.1 fallback)
"""

from typing import Optional

import httpx

from utils.lazy import LazyInit
from utils.logging import get_logger

# Set up logging
logger = get_logger(__name__)

#: Seconds a request may wait for a free connection when all 100 are in use,
#: under the gthread worker only. Waiting happens before a byte is sent, so
#: giving up cannot duplicate an order; it turns pool saturation into a prompt
#: error instead of a two-minute hang on one of a fixed number of threads.
#: Under eventlet and the dev server the pool wait keeps the overall timeout.
GTHREAD_POOL_TIMEOUT_SECONDS = 10.0

REQUEST_TIMEOUT_SECONDS = 120.0


def _build_client() -> httpx.Client:
    client = _create_http_client()
    logger.debug(
        "Created HTTP client with automatic protocol negotiation (HTTP/2 preferred, HTTP/1.1 fallback)"
    )
    return client


# Global httpx client for connection pooling, built once by exactly one caller.
# Two cold threads used to be able to build one each, and the loser's pool was
# discarded without being closed.
_client = LazyInit(_build_client, name="httpx-client")


def get_httpx_client() -> httpx.Client:
    """
    Returns an HTTP client with automatic protocol negotiation.
    The client will use HTTP/2 when the server supports it,
    otherwise automatically falls back to HTTP/1.1.

    Returns:
        httpx.Client: A configured HTTP client with protocol auto-negotiation
    """
    return _client.get()


def get_pool_stats() -> dict | None:
    """Best-effort view of the shared connection pool, for diagnostics.

    Reads httpx's private transport attributes, each guarded, so a release
    that renames one costs that figure and nothing else.

    Returns:
        ``{"connections", "idle", "max_connections"}``, or None before the
        client exists.
    """
    client = _client.peek()
    if client is None:
        return None
    stats: dict = {"connections": None, "idle": None, "max_connections": 100}
    try:
        pool = client._transport._pool
        connections = list(pool.connections)
        stats["connections"] = len(connections)
        stats["idle"] = sum(1 for c in connections if c.is_idle())
    except Exception:
        pass
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
        from utils.url_redaction import redact_url_credentials

        logger.debug(f"Starting request to {redact_url_credentials(request.url)}")

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

        from utils.runtime import gthread_active

        # Increased timeout for large historical data requests. The pool wait
        # is bounded separately under gthread; see GTHREAD_POOL_TIMEOUT_SECONDS.
        if gthread_active():
            timeout = httpx.Timeout(REQUEST_TIMEOUT_SECONDS, pool=GTHREAD_POOL_TIMEOUT_SECONDS)
        else:
            timeout = REQUEST_TIMEOUT_SECONDS

        client = httpx.Client(
            http2=http2_enabled,  # Disable HTTP/2 in standalone mode, enable in integrated mode
            http1=True,  # Always enable HTTP/1.1 for compatibility
            timeout=timeout,
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
    closed = []

    def _close(client: httpx.Client) -> None:
        client.close()
        closed.append(True)

    # Under the same lock as creation, so no caller is handed the client while
    # it is being closed.
    _client.reset(close=_close)
    if closed:
        logger.info("Closed HTTP client")
