import os
import json
from urllib.parse import urlencode
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


BASE_URL = 'https://api.tradejini.com/v2'

def authenticate_broker(password=None, twofa=None, twofa_type=None):
    """
    Authenticate with Tradejini using individual token service
    Args:
        password (str): User's password
        twofa (str): Two-factor authentication code (OTP or Time based OTP)
        twofa_type (str): Type of 2FA - 'otp' or 'totp'
    Returns:
        tuple: (access_token, error_message)
    """
    try:
        if not all([password, twofa]):
            return None, 'Password and TOTP code are required'
            
        # Force twofa_type to be totp
        twofa_type = 'totp'
            
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        if not BROKER_API_SECRET:
            return None, 'BROKER_API_SECRET environment variable not set'
        
        url = f'{BASE_URL}/api-gw/oauth/individual-token-v2'
        
        # Set up headers with bearer token
        headers = {
            'Authorization': f'Bearer {BROKER_API_SECRET}',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
        
        # Set up form data
        data = {
            'password': password,
            'twoFa': twofa,
            'twoFaTyp': twofa_type
        }
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        response = client.post(url, data=data, headers=headers)
        response_data = response.json()
        
        # Print the full response for debugging
        logger.info(f"Tradejini Response Status: {response.status_code}")
        logger.info(f"Tradejini Response Headers: {dict(response.headers)}")
        logger.info(f"Tradejini Response Data: {response_data}")
        
        if response.status_code == 200:
            # API returns: {scope, access_token, token_type, expires_in}
            if 'access_token' not in response_data:
                return None, 'No access token in response'
                
            if response_data.get('token_type') != 'Bearer':
                return None, 'Invalid token type in response'
                
            return response_data['access_token'], None
        else:
            error_msg = response_data.get('message', 'Authentication failed')
            return None, error_msg
    except requests.exceptions.RequestException as e:
        return None, f'Request failed: {str(e)}'
    except json.JSONDecodeError:
        return None, 'Invalid JSON response from server'
    except Exception as e:
        return None, str(e)

def get_auth_url():
    """
    Generate the authorization URL for Tradejini OAuth flow
    """
    BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
    REDIRECT_URI = os.getenv('REDIRECT_URI')
    
    params = {
        'client_id': BROKER_API_SECRET,
        'redirect_uri': REDIRECT_URI,
        'response_type': 'code',
        'scope': 'general',
        'state': 'random_state'
    }
    
    return f'{BASE_URL}/api-gw/oauth/authorize?{urlencode(params)}'

def authenticate_broker_oauth(code):
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        url = f'{BASE_URL}/api-gw/oauth/token'
        data = {
            'code': code,
            'client_id': BROKER_API_KEY,
            'client_secret': BROKER_API_SECRET,
            'redirect_uri': os.getenv('REDIRECT_URI'),
            'grant_type': 'authorization_code'
        }
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        response = client.post(url, data=data)
        
        if response.status_code == 200:
            response_data = response.json()
            if 'access_token' in response_data:
                return response_data['access_token'], None
            else:
                return None, 'No access token in response'
        else:
            return None, f'Authentication failed: {response.text}'
            
    except Exception as e:
        return None, str(e)