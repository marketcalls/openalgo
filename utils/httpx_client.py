"""
Shared httpx client module with connection pooling support for all broker APIs
with automatic HTTP/2 to HTTP/1.1 fallback
"""
import httpx
from typing import Optional, Union, Dict, Any, Callable
from utils.logging import get_logger

# Set up logging
logger = get_logger(__name__)

# Global httpx clients for connection pooling
_httpx_client_http2 = None  # For HTTP/2 with prior knowledge
_httpx_client_http1 = None  # For HTTP/1.1

class HTTP2FallbackError(Exception):
    """Raised when falling back from HTTP/2 to HTTP/1.1"""
    pass

def get_httpx_client() -> httpx.Client:
    """
    Returns an HTTP client with automatic HTTP/2 to HTTP/1.1 fallback.
    
    Returns:
        httpx.Client: A configured HTTP client
    """
    global _httpx_client_http1
    
    # Always return HTTP/1.1 client as fallback
    if _httpx_client_http1 is None:
        _httpx_client_http1 = _create_http_client(http2=False, http1=True)
    return _httpx_client_http1

def request_with_fallback(
    method: str,
    url: str,
    **kwargs
) -> httpx.Response:
    """
    Make an HTTP request with automatic HTTP/2 to HTTP/1.1 fallback.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL to request
        **kwargs: Additional arguments to pass to the request
        
    Returns:
        httpx.Response: The HTTP response
        
    Raises:
        httpx.HTTPError: If both HTTP/2 and HTTP/1.1 requests fail
    """
    global _httpx_client_http2
    
    # Try with HTTP/2 first if not already failed before
    if _httpx_client_http2 is None:
        try:
            _httpx_client_http2 = _create_http_client(http2=True, http1=False)
        except Exception as e:
            logger.warning(f"Failed to create HTTP/2 client, will use HTTP/1.1: {e}")
    
    if _httpx_client_http2 is not None:
        try:
            logger.debug(f"Trying HTTP/2 request to {url}")
            return _httpx_client_http2.request(method, url, **kwargs)
        except (httpx.HTTPError, httpx.ProtocolError) as e:
            logger.warning(f"HTTP/2 request failed, will try HTTP/1.1: {e}")
            _httpx_client_http2 = None  # Mark HTTP/2 as failed
    
    # Fall back to HTTP/1.1
    logger.debug(f"Trying HTTP/1.1 request to {url}")
    client = get_httpx_client()
    return client.request(method, url, **kwargs)

# Shortcut methods for common HTTP methods
def get(url: str, **kwargs) -> httpx.Response:
    return request_with_fallback('GET', url, **kwargs)

def post(url: str, **kwargs) -> httpx.Response:
    return request_with_fallback('POST', url, **kwargs)

def put(url: str, **kwargs) -> httpx.Response:
    return request_with_fallback('PUT', url, **kwargs)

def delete(url: str, **kwargs) -> httpx.Response:
    return request_with_fallback('DELETE', url, **kwargs)


def _create_http_client(http2: bool, http1: bool) -> httpx.Client:
    """
    Create a new HTTP client with specified HTTP version settings.
    
    Args:
        http2: Whether to enable HTTP/2
        http1: Whether to enable HTTP/1.1
    
    Returns:
        httpx.Client: A configured HTTP client
    """
    try:
        client = httpx.Client(
            http2=http2,
            http1=http1,
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=50,  # Increased from 10
                max_connections=100,  # Increased from 20
                keepalive_expiry=300.0  # Increased from 60 to 300 seconds (5 minutes)
            )
        )
        http_versions = []
        if http2:
            http_versions.append("HTTP/2" + (" (prior knowledge)" if not http1 else ""))
        if http1:
            http_versions.append("HTTP/1.1")
        
        logger.info(f"Created HTTP client with support for: {', '.join(http_versions)}")
        return client
        
    except Exception as e:
        logger.error(f"Failed to create HTTP client: {e}")
        raise


def cleanup_httpx_client():
    """
    Closes all global httpx clients and releases their resources.
    Should be called when the application is shutting down.
    """
    global _httpx_client_http2, _httpx_client_http1
    
    if _httpx_client_http2 is not None:
        _httpx_client_http2.close()
        _httpx_client_http2 = None
        logger.info("Closed HTTP/2 client")
    
    if _httpx_client_http1 is not None:
        _httpx_client_http1.close()
        _httpx_client_http1 = None
        logger.info("Closed HTTP/1.1 client")
