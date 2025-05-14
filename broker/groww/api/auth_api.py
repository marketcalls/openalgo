import json
import os
import httpx
from utils.httpx_client import get_httpx_client



def authenticate_broker(code):
    """
    Authenticate with Groww using the authorization code and return the access token.
    Uses shared httpx client with connection pooling.
    
    Args:
        code: The authorization code received from Groww's OAuth flow
        
    Returns:
        tuple: (access_token, error_message)
    """
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        #BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        REDIRECT_URL = os.getenv('REDIRECT_URL')
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Currently returning the API key for development purposes
        # In a real implementation, this would exchange the code for an access token
        
        # Example of how to use the shared client when ready to implement OAuth exchange:
        # headers = {
        #     'Content-Type': 'application/json'
        # }
        # 
        # payload = {
        #     'code': code,
        #     'client_id': BROKER_API_KEY,
        #     'client_secret': BROKER_API_SECRET,
        #     'redirect_uri': REDIRECT_URL,
        #     'grant_type': 'authorization_code'
        # }
        # 
        # response = client.post(
        #     'https://groww.in/api/v1/auth/token',
        #     headers=headers,
        #     json=payload
        # )
        # 
        # response.raise_for_status()
        # 
        # response_data = response.json()
        # if 'access_token' in response_data:
        #     return response_data['access_token'], None
        # else:
        #     return None, "Authentication succeeded but no access token was returned."
        
        # For now, just return the API key as a placeholder
        return BROKER_API_KEY, None
        
    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except httpx.RequestError as e:
        return None, f"Request error occurred: {str(e)}"
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"

