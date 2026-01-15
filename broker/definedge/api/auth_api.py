import os
import json
import urllib.parse
from hashlib import sha256
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

def authenticate_broker(otp_token, otp, api_secret=None):
    """
    Authenticate with DefinedGe Securities using OTP verification.
    This is called after OTP has been sent via login_step1.
    
    Parameters:
    - otp_token: The OTP token received from login_step1
    - otp: The OTP code entered by user
    - api_secret: Optional API secret (if not provided, fetches from env)
    
    Returns:
    - Tuple of (auth_string, feed_token, user_id, error_message)
    """
    try:
        # Get API credentials from environment if not provided
        if not api_secret:
            api_secret = os.getenv('BROKER_API_SECRET')
        api_token = os.getenv('BROKER_API_KEY')
        
        # Step 2: Verify OTP with auth code to get session keys
        session_response = login_step2(otp_token, otp, api_secret)
        if not session_response:
            return None, None, None, "Failed to verify OTP"

        # Check response status
        if session_response.get('stat') != 'Ok':
            error_msg = session_response.get('emsg', 'Unknown authentication error')
            return None, None, None, f"Authentication failed: {error_msg}"

        api_session_key = session_response.get('api_session_key')
        susertoken = session_response.get('susertoken')
        user_id = session_response.get('uid') or session_response.get('uccid')

        if not api_session_key:
            return None, None, None, "Failed to get API session key"

        # Return auth string in format expected by OpenAlgo
        auth_string = f"{api_session_key}:::{susertoken or ''}:::{api_token}"
        feed_token = susertoken  # susertoken is used as feed_token for websocket
        
        return auth_string, feed_token, user_id, None

    except Exception as e:
        logger.error(f"Authentication error: {e}")
        return None, None, None, str(e)

def login_step1(api_token=None, api_secret=None):
    """Step 1: Login with API credentials to trigger OTP"""
    try:
        # Get credentials from environment if not provided
        if not api_token:
            api_token = os.getenv('BROKER_API_KEY')
        if not api_secret:
            api_secret = os.getenv('BROKER_API_SECRET')
        
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        headers = {
            'api_secret': api_secret
        }

        url = f"https://signin.definedgesecurities.com/auth/realms/debroking/dsbpkc/login/{api_token}"
        
        response = client.get(url, headers=headers)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        
        response_data = response.json()
        
        # Add a message field if not present
        if 'message' not in response_data:
            response_data['message'] = 'OTP has been sent successfully'
        
        return response_data

    except Exception as e:
        logger.error(f"Step 1 error: {e}")
        return None

def login_step2(otp_token, otp, api_secret):
    """Step 2: Verify OTP with auth code to get session keys"""
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Calculate authentication code using SHA256
        auth_string = f"{otp_token}{otp}{api_secret}"
        auth_code = sha256(auth_string.encode("utf-8")).hexdigest()

        payload = {
            "otp_token": otp_token,
            "otp": otp,
            "ac": auth_code
        }

        headers = {
            'Content-Type': 'application/json'
        }

        url = "https://signin.definedgesecurities.com/auth/realms/debroking/dsbpkc/token"
        
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()  # Raise exception for 4XX/5XX responses
        
        return response.json()

    except Exception as e:
        logger.error(f"Step 2 error: {e}")
        return None