import httpx
import json
import os
from utils.httpx_client import get_httpx_client
from broker.dhan.api.baseurl import get_url, BASE_URL



def authenticate_broker(code, api_key=None, api_secret=None, redirect_url=None):
    """
    Authenticate with Dhan broker
    
    Args:
        code: Authentication code
        api_key: API key (optional, falls back to env)
        api_secret: API secret (optional, falls back to env)
        redirect_url: Redirect URL (optional, falls back to env)
    
    Returns:
        tuple: (auth_token, error_message)
    """
    try:
        # Use provided credentials or fall back to environment
        BROKER_API_KEY = api_key or os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = api_secret or os.getenv('BROKER_API_SECRET')
        REDIRECT_URL = redirect_url or os.getenv('REDIRECT_URL')
        
        if not BROKER_API_KEY or not BROKER_API_SECRET:
            return None, "Missing API credentials"
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # TODO: Implement proper Dhan OAuth flow
        # For now, returning API secret as auth token (placeholder implementation)
        # This should be replaced with actual Dhan API authentication
        
        return BROKER_API_SECRET, None

        # Commented out until proper Dhan OAuth implementation
        # if response.status_code == 200:
        #     response_data = response.json()
        #     if 'access_token' in response_data:
        #         return response_data['access_token'], None
        #     else:
        #         return None, "Authentication succeeded but no access token was returned. Please check the response."
        # else:
        #     # Parsing the error message from the API response
        #     error_detail = response.json()  # Assuming the error is in JSON format
        #     error_messages = error_detail.get('errors', [])
        #     detailed_error_message = "; ".join([error['message'] for error in error_messages])
        #     return None, f"API error: {error_messages}" if detailed_error_message else "Authentication failed. Please try again."
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"

