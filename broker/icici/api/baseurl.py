# ICICI Breeze API Base URL Configuration

# Base URL for Breeze Connect API endpoints
BASE_URL = "https://api.icicidirect.com/breezeapi/api/v1"

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
