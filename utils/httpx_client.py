"""
Shared httpx client module with connection pooling support for all broker APIs
with automatic protocol negotiation (HTTP/2 when available, HTTP/1.1 fallback)
"""
import httpx
from typing import Optional
from utils.logging import get_logger

# Set up logging
logger = get_logger(__name__)

# Global httpx client for connection pooling
_httpx_client = None

def get_httpx_client() -> httpx.Client:
    """
    Returns an HTTP client with automatic protocol negotiation.
    The client will use HTTP/2 when the server supports it, 
    otherwise automatically falls back to HTTP/1.1.
    
    Returns:
        httpx.Client: A configured HTTP client with protocol auto-negotiation
    """
    global _httpx_client
    
    if _httpx_client is None:
        _httpx_client = _create_http_client()
        logger.info("Created HTTP client with automatic protocol negotiation (HTTP/2 preferred, HTTP/1.1 fallback)")
    return _httpx_client

def request(
    method: str,
    url: str,
    **kwargs
) -> httpx.Response:
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
    client = get_httpx_client()
    response = client.request(method, url, **kwargs)
    
    # Log the actual HTTP version used (info level for visibility)
    if response.http_version:
        logger.info(f"Request used {response.http_version} - URL: {url[:50]}...")
    
    return response

# Shortcut methods for common HTTP methods
def get(url: str, **kwargs) -> httpx.Response:
    return request('GET', url, **kwargs)

def post(url: str, **kwargs) -> httpx.Response:
    return request('POST', url, **kwargs)

def put(url: str, **kwargs) -> httpx.Response:
    return request('PUT', url, **kwargs)

def delete(url: str, **kwargs) -> httpx.Response:
    return request('DELETE', url, **kwargs)


def _create_http_client() -> httpx.Client:
    """
    Create a new HTTP client with automatic protocol negotiation.
    Enables both HTTP/2 and HTTP/1.1, letting httpx choose the best protocol.
    
    Returns:
        httpx.Client: A configured HTTP client with protocol auto-negotiation
    """
    import os
    
    try:
        # Detect if running in standalone mode (Docker/production) vs integrated mode (local dev)
        # In standalone mode, disable HTTP/2 to avoid protocol negotiation issues
        app_mode = os.environ.get('APP_MODE', 'integrated').strip().strip("'\"")
        is_standalone = app_mode == 'standalone'

        # Disable HTTP/2 in standalone/Docker environments to avoid protocol negotiation issues
        http2_enabled = not is_standalone
        
        client = httpx.Client(
            http2=http2_enabled,  # Disable HTTP/2 in standalone mode, enable in integrated mode
            http1=True,  # Always enable HTTP/1.1 for compatibility
            timeout=120.0,  # Increased timeout for large historical data requests
            limits=httpx.Limits(
                max_keepalive_connections=20,  # Balanced for most broker APIs
                max_connections=50,  # Reasonable max without overloading
                keepalive_expiry=120.0  # 2 minutes - good balance
            ),
            # Add verify parameter to handle SSL/TLS issues in standalone mode
            verify=True  # Can be set to False for debugging SSL issues (not recommended for production)
        )
        
        if is_standalone:
            logger.info("Running in standalone mode - HTTP/2 disabled for compatibility")
        else:
            logger.info("Running in integrated mode - HTTP/2 enabled for optimal performance")
            
        return client
        
    except Exception as e:
        logger.error(f"Failed to create HTTP client: {e}")
        raise


def cleanup_httpx_client():
    """
    Closes the global httpx client and releases its resources.
    Should be called when the application is shutting down.
    """
    global _httpx_client
    
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None
        logger.info("Closed HTTP client")
