# DefinedGe Securities INTEGRATE API Base URL Configuration

# Base URL for trading API endpoints (orders, positions, holdings, limits, etc.)
BASE_URL = "https://integrate.definedgesecurities.com/dart/v1"

# Base URL for historical data API
DATA_URL = "https://data.definedgesecurities.com/sds"

# Base URL for authentication (login/token) endpoints
SESSION_URL = "https://signin.definedgesecurities.com/auth/realms/debroking/dsbpkc"


# Function to build full URL with endpoint
def get_url(endpoint):
    """
    Constructs a full trading API URL by combining the base URL and the endpoint

    Args:
        endpoint (str): The API endpoint path (should start with '/')

    Returns:
        str: The complete URL
    """
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    return BASE_URL + endpoint
