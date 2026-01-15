import os
import httpx
import base64
import json
from urllib.parse import urlencode
from utils.config import get_broker_api_key, get_broker_api_secret
from utils.httpx_client import get_httpx_client

# Pocketful API endpoints
BASE_URL = 'https://trade.pocketful.in'
TOKEN_ENDPOINT = f"{BASE_URL}/oauth2/token"
USER_INFO_ENDPOINT = f"{BASE_URL}/api/v1/user/trading_info"

def authenticate_broker(auth_code=None, state=None):
    """
    Authenticate with Pocketful using OAuth2 flow
    
    Args:
        auth_code: The authorization code received from Pocketful
        state: The state parameter received from Pocketful (for verification)
    
    Returns:
        Tuple of (access_token, feed_token, client_id, error_message)
        Where feed_token is always None for Pocketful
    """
    try:
        # For OAuth flow, we need the auth_code
        if not auth_code:
            return None, None, None, "No authorization code provided. Please authenticate through the OAuth flow."
        
        # Get client credentials from environment
        client_id = get_broker_api_key()
        client_secret = get_broker_api_secret()
        
        if not client_id or not client_secret:
            return None, None, None, "Missing API credentials. Please set BROKER_API_KEY and BROKER_API_SECRET in your environment."
        
        # Create base64 encoded Authorization header
        credentials = f"{client_id}:{client_secret}"
        encoded_credentials = base64.b64encode(credentials.encode()).decode()
        
        # Get the redirect URL from environment variable
        # This should match the registered redirect URI in Pocketful
        redirect_uri = os.getenv('REDIRECT_URL', 'http://127.0.0.1:5000/pocketful/callback')
        
        # Prepare the token request
        headers = {
            'Authorization': f'Basic {encoded_credentials}',
            'Content-Type': 'application/x-www-form-urlencoded',
            'Cache-Control': 'no-cache'
        }
        
        data = {
            'grant_type': 'authorization_code',
            'code': auth_code,
            'redirect_uri': redirect_uri
        }
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Exchange authorization code for access token
        response = client.post(TOKEN_ENDPOINT, headers=headers, content=urlencode(data))
        
        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code
        
        if response.status_code != 200:
            # Token exchange failed
            try:
                error_detail = response.json()
                error_message = error_detail.get('message', 'Authentication failed. Please check your authorization code.')
            except:
                error_message = f"Authentication failed with status code: {response.status_code}"
            
            return None, None, None, f"API error: {error_message}"
        
        # Parse token response
        token_data = response.json()
        access_token = token_data.get('access_token')
        
        if not access_token:
            return None, None, None, "Access token not found in response"
        
        # Now fetch the client_id from trading_info endpoint
        headers = {
            'Authorization': f'Bearer {access_token}'
        }
        
        # Make request to trading_info endpoint
        try:
            info_response = client.get(USER_INFO_ENDPOINT, headers=headers)
            # Add status attribute for compatibility
            info_response.status = info_response.status_code
            info_response.raise_for_status()  # Raise exception for non-200 status codes
            
            # Parse the response JSON
            info_data = info_response.json()
            
            if info_data.get('status') != 'success':
                return access_token, None, None, f"Failed to fetch client ID: {info_data.get('message', 'Unknown error')}"
            
            # Extract client_id from the response
            client_id = info_data.get('data', {}).get('client_id')
            
            if not client_id:
                return access_token, None, None, "Client ID not found in response"
            
            # Return token, None for feed_token (not used by Pocketful), and client_id
            return access_token, None, client_id, None
            
        except httpx.HTTPError as e:
            return access_token, None, None, f"Error fetching client ID: {str(e)}"
            
    except Exception as e:
        # Exception handling
        return None, None, None, f"An exception occurred: {str(e)}"

def get_authorization_url():
    """
    Generate the authorization URL for Pocketful OAuth
    
    Returns:
        Tuple of (url, state) or (None, error_message)
    """
    try:
        client_id = get_broker_api_key()
        if not client_id:
            return None, "Missing API key. Please set BROKER_API_KEY in your environment."
        
        # Get the redirect URL from environment variable
        redirect_uri = os.getenv('REDIRECT_URL', 'http://127.0.0.1:5000/pocketful/callback')
        
        # Define scopes - add more as needed
        scope = "orders holdings"
        
        # Generate a random state for security
        import random
        import string
        state = ''.join(random.choices(string.ascii_letters + string.digits, k=16))
        
        # Build the authorization URL
        params = {
            'client_id': client_id,
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': scope,
            'state': state
        }
        
        auth_url = f"{BASE_URL}/oauth2/auth?{urlencode(params)}"
        return auth_url, state
    
    except Exception as e:
        return None, f"Error generating authorization URL: {str(e)}"
