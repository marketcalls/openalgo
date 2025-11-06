from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_api_response(endpoint, auth, method="GET", payload=None):
    """
    Make an API request to Zerodha's API using shared httpx client with connection pooling.
    
    Args:
        endpoint (str): API endpoint (e.g., '/orders')
        auth (str): Authentication token
        method (str): HTTP method (GET, POST, etc.)
        payload (dict/str, optional): Request payload
        
    Returns:
        dict: API response data
    """
    AUTH_TOKEN = auth
    base_url = 'https://api.kite.trade'
    
    # Get the shared httpx client with connection pooling
    client = get_httpx_client()
    
    headers = {
        'X-Kite-Version': '3',
        'Authorization': f'token {AUTH_TOKEN}'
    }
    
    url = f"{base_url}{endpoint}"
    
    try:
        # Handle different HTTP methods
        if method.upper() == 'GET':
            response = client.get(
                url,
                headers=headers
            )
        elif method.upper() == 'POST':
            if isinstance(payload, str):
                # For form-urlencoded data
                headers['Content-Type'] = 'application/x-www-form-urlencoded'
                response = client.post(
                    url,
                    headers=headers,
                    content=payload
                )
            else:
                # For JSON data
                headers['Content-Type'] = 'application/json'
                response = client.post(
                    url,
                    headers=headers,
                    json=payload
                )
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")
            
        # Parse and return JSON response
        response.raise_for_status()
        return response.json()
        
    except Exception as e:
        error_msg = str(e)
        # Try to extract more error details if available
        try:
            if hasattr(e, 'response') and e.response is not None:
                error_detail = e.response.json()
                error_msg = error_detail.get('message', error_msg)
        except:
            pass
            
        logger.exception(f"API request failed: {error_msg}")
        raise

