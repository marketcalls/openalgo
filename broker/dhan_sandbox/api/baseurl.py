# Dhan API Base URL Configuration

# Base URL for Dhan API endpoints
BASE_URL = "https://sandbox.dhan.co"

# Function to build full URL with endpoint
def get_url(endpoint):
    """
    Constructs a full URL by combining the base URL and the endpoint
    
    Args:
        endpoint (str): The API endpoint path (should start with '/')
        
    Returns:
        str: The complete URL
    """
    if not endpoint.startswith('/'):
        endpoint = '/' + endpoint
    return BASE_URL + endpoint
