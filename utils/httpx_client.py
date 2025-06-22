"""
Shared httpx client module with connection pooling support for all broker APIs
Fully backward compatible with automatic HTTP/1.1 fallback support
"""
import httpx
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Global httpx client for connection pooling (original behavior)
_httpx_client = None

# Additional clients for fallback support
_httpx_client_http1 = None
_fallback_enabled = True  # Can be disabled if needed

# Track domains that require HTTP/1.1
_http1_only_domains = {
    "authapi.flattrade.in",  # Flattrade auth API - has HTTP/2 issues
    "piconnect.flattrade.in",  # Flattrade trading API - has HTTP/2 issues
}


def get_httpx_client():
    """
    Returns a global httpx client instance with connection pooling.
    The client is created when first needed and reused for subsequent requests.
    
    THIS FUNCTION MAINTAINS EXACT BACKWARD COMPATIBILITY.
    It returns the same HTTP/2 enabled client as before.
    
    Returns:
        httpx.Client: A shared httpx client instance with connection pooling
    """
    global _httpx_client
    if _httpx_client is None:
        # Create a client with connection pooling
        # Setting limits to allow connection reuse but prevent resource exhaustion
        _httpx_client = httpx.Client(
            http2=True,
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=60.0
            )
        )
    return _httpx_client


def cleanup_httpx_client():
    """
    Closes the global httpx client and releases its resources.
    Should be called when the application is shutting down.
    
    THIS FUNCTION MAINTAINS EXACT BACKWARD COMPATIBILITY.
    """
    global _httpx_client, _httpx_client_http1
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None
    
    # Also cleanup HTTP/1.1 client if it exists
    if _httpx_client_http1 is not None:
        _httpx_client_http1.close()
        _httpx_client_http1 = None


# ============= NEW FALLBACK FUNCTIONALITY BELOW =============
# These are additional functions that don't affect existing code

def _get_http1_client():
    """Get or create HTTP/1.1 client for fallback"""
    global _httpx_client_http1
    if _httpx_client_http1 is None:
        _httpx_client_http1 = httpx.Client(
            http2=False,  # HTTP/1.1 only
            timeout=30.0,
            limits=httpx.Limits(
                max_keepalive_connections=10,
                max_connections=20,
                keepalive_expiry=60.0
            )
        )
    return _httpx_client_http1


def _get_domain_from_url(url: str) -> str:
    """Extract domain from URL"""
    from urllib.parse import urlparse
    return urlparse(url).hostname or ""


def get_httpx_client_smart(url: Optional[str] = None):
    """
    NEW FUNCTION: Smart client selection based on URL.
    
    This is a new function that existing code won't use unless explicitly updated.
    It provides HTTP/1.1 fallback for known problematic domains.
    
    Args:
        url: Optional URL to determine which client to use
        
    Returns:
        httpx.Client: Either HTTP/2 or HTTP/1.1 client based on URL
    """
    if url and _fallback_enabled:
        domain = _get_domain_from_url(url).lower()
        if domain in _http1_only_domains:
            logger.debug(f"Using HTTP/1.1 client for {domain}")
            return _get_http1_client()
    
    return get_httpx_client()


def request_with_fallback(method: str, url: str, **kwargs) -> httpx.Response:
    """
    NEW FUNCTION: Make request with automatic HTTP/1.1 fallback.
    
    This is a new function that provides automatic fallback functionality.
    Existing code won't use this unless explicitly updated.
    
    Args:
        method: HTTP method (GET, POST, etc.)
        url: URL to request
        **kwargs: Additional arguments to pass to the request
        
    Returns:
        httpx.Response: The response object
    """
    if not _fallback_enabled:
        # If fallback is disabled, use original client
        client = get_httpx_client()
        return client.request(method, url, **kwargs)
    
    # Check if this domain is known to require HTTP/1.1
    domain = _get_domain_from_url(url).lower()
    if domain in _http1_only_domains:
        client = _get_http1_client()
        return client.request(method, url, **kwargs)
    
    # Try with HTTP/2 first
    client = get_httpx_client()
    
    try:
        response = client.request(method, url, **kwargs)
        return response
    except httpx.RemoteProtocolError as e:
        if "illegal request line" in str(e).lower():
            logger.warning(f"HTTP/2 failed for {url}, falling back to HTTP/1.1: {e}")
            
            # Remember this domain for future requests
            if domain:
                _http1_only_domains.add(domain)
                logger.info(f"Added {domain} to HTTP/1.1 only domains")
            
            # Retry with HTTP/1.1
            client_http1 = _get_http1_client()
            return client_http1.request(method, url, **kwargs)
        else:
            raise


# Convenience methods - NEW FUNCTIONS that won't affect existing code
def get(url: str, **kwargs) -> httpx.Response:
    """NEW: GET request with automatic HTTP/1.1 fallback"""
    return request_with_fallback("GET", url, **kwargs)


def post(url: str, **kwargs) -> httpx.Response:
    """NEW: POST request with automatic HTTP/1.1 fallback"""
    return request_with_fallback("POST", url, **kwargs)


def put(url: str, **kwargs) -> httpx.Response:
    """NEW: PUT request with automatic HTTP/1.1 fallback"""
    return request_with_fallback("PUT", url, **kwargs)


def delete(url: str, **kwargs) -> httpx.Response:
    """NEW: DELETE request with automatic HTTP/1.1 fallback"""
    return request_with_fallback("DELETE", url, **kwargs)


# Configuration functions
def add_http1_only_domain(domain: str):
    """NEW: Add a domain to the list of domains that require HTTP/1.1"""
    _http1_only_domains.add(domain.lower())
    logger.info(f"Added {domain} to HTTP/1.1 only domains")


def remove_http1_only_domain(domain: str):
    """NEW: Remove a domain from the HTTP/1.1 only list"""
    _http1_only_domains.discard(domain.lower())
    logger.info(f"Removed {domain} from HTTP/1.1 only domains")


def disable_fallback():
    """NEW: Disable automatic HTTP/1.1 fallback globally"""
    global _fallback_enabled
    _fallback_enabled = False
    logger.info("HTTP/1.1 fallback disabled")


def enable_fallback():
    """NEW: Enable automatic HTTP/1.1 fallback globally"""
    global _fallback_enabled
    _fallback_enabled = True
    logger.info("HTTP/1.1 fallback enabled")


# For debugging
def get_http1_only_domains():
    """NEW: Get current list of HTTP/1.1 only domains"""
    return list(_http1_only_domains)