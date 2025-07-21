import json
import os
import httpx
import pyotp
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)



def generate_totp(api_secret):
    """
    Generate TOTP code using API secret.
    
    Args:
        api_secret: The API secret from Groww
        
    Returns:
        str: Generated TOTP code
    """
    totp_gen = pyotp.TOTP(api_secret)
    totp_code = totp_gen.now()
    
    # Debug output
    logger.debug(f"TOTP Generation:")
    logger.debug(f"  - API Secret length: {len(api_secret)} chars")
    logger.debug(f"  - API Secret (masked): {api_secret[:4]}...{api_secret[-4:]}")
    logger.debug(f"  - Generated TOTP: {totp_code}")
    logger.debug(f"  - TOTP length: {len(totp_code)} digits")
    logger.debug(f"  - TOTP is numeric: {totp_code.isdigit()}")
    
    return totp_code


def get_access_token_via_totp(api_key, api_secret):
    """
    Get access token using API key and secret with TOTP flow.
    Implements the authentication flow similar to Groww SDK.
    
    Args:
        api_key: The API key from Groww
        api_secret: The API secret from Groww
        
    Returns:
        tuple: (access_token, error_message)
    """
    try:
        # Generate TOTP
        totp = generate_totp(api_secret)
        
        # Debug API Key info
        logger.debug("API Key Info:")
        logger.debug(f"  - API Key length: {len(api_key)} chars")
        logger.debug(f"  - API Key (masked): {api_key[:8]}...{api_key[-4:]}")
        
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Use EXACT format from official Groww SDK
        # From auth.ts: Authorization header with Bearer token + TOTP in body
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        # Exact payload format from SDK
        payload = {
            'totp': totp
        }
        
        # Exact endpoint from SDK config
        endpoint = 'https://api.groww.in/v1/token/api/access'
        
        logger.debug("Official SDK Format:")
        logger.debug(f"  - Endpoint: {endpoint}")
        logger.debug(f"  - Headers: {headers}")
        logger.debug(f"  - Payload: {payload}")
        
        try:
            response = client.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30
            )
            
            logger.debug(f"  - Response Status: {response.status_code}")
            logger.debug(f"  - Response Headers: {dict(response.headers)}")
            logger.debug(f"  - Response Body: {response.text}")
            
            if response.status_code == 200:
                response_data = response.json()
                logger.info(f"Authentication successful! Response data: {response_data}")
                
                # Based on AccessToken.ts, expect 'token' field
                if 'token' in response_data:
                    logger.info("Access token retrieved successfully")
                    return response_data['token'], None
                else:
                    logger.error(f"Authentication succeeded but no token found in response: {response_data}")
                    return None, f"Authentication succeeded but no token found in response: {response_data}"
            else:
                try:
                    error_data = response.json()
                    logger.error(f"HTTP error {response.status_code}: {error_data}")
                    return None, f"HTTP error {response.status_code}: {error_data}"
                except:
                    logger.error(f"HTTP error {response.status_code}: {response.text}")
                    return None, f"HTTP error {response.status_code}: {response.text}"
                    
        except Exception as e:
            logger.error(f"Request exception: {str(e)}")
            return None, f"Request failed: {str(e)}"
        
        return None, "Unable to authenticate with Groww API. Please verify your API credentials and ensure you have an active API subscription."
        
    except Exception as e:
        return None, f"Authentication error: {str(e)}"


def authenticate_broker(code):
    """
    Authenticate with Groww using API key and secret with TOTP flow.
    The 'code' parameter is now expected to be None for TOTP flow,
    as authentication relies on environment variables.
    
    Args:
        code: Not used in TOTP flow, kept for compatibility
        
    Returns:
        tuple: (access_token, error_message)
    """
    try:
        BROKER_API_KEY = os.getenv('BROKER_API_KEY')
        BROKER_API_SECRET = os.getenv('BROKER_API_SECRET')
        
        if not BROKER_API_KEY or not BROKER_API_SECRET:
            return None, "BROKER_API_KEY and BROKER_API_SECRET environment variables are required for Groww TOTP authentication"
        
        # Use TOTP flow to get access token
        return get_access_token_via_totp(BROKER_API_KEY, BROKER_API_SECRET)
        
    except Exception as e:
        return None, f"An exception occurred: {str(e)}"


