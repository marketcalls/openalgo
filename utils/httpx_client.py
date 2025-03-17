"""
Shared httpx client module with connection pooling support for all broker APIs
"""
import httpx

# Global httpx client for connection pooling
_httpx_client = None

def get_httpx_client():
    """
    Returns a global httpx client instance with connection pooling.
    The client is created when first needed and reused for subsequent requests.
    
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
    """
    global _httpx_client
    if _httpx_client is not None:
        _httpx_client.close()
        _httpx_client = None
