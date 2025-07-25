import hashlib
import json
import os
from utils.logging import get_logger
from utils.httpx_client import get_httpx_client

logger = get_logger(__name__)

def sha256_hash(text):
    """
    Generate SHA256 hash for password encryption.
    
    Args:
        text (str): The plain text password to hash
        
    Returns:
        str: SHA256 hexadecimal hash of the input text
    """
    return hashlib.sha256(text.encode('utf-8')).hexdigest()

def authenticate_broker(userid, password, totp_code):
    """
    Authenticate with Firstock using the updated API and return the auth token.
    
    This function implements the Firstock Login API as per the latest documentation.
    It requires SHA256-hashed password and handles TOTP authentication.
    
    Args:
        userid (str): Unique identifier for Firstock account
        password (str): Plain text password (will be SHA256 hashed)
        totp_code (str): One-time password or 2FA code (required if TOTP is enabled)
        
    Returns:
        tuple: (token, error_message)
            - On success: (susertoken_string, None)
            - On failure: (None, error_message_string)
    """
    # Get the Firstock API credentials from environment variables
    api_key = os.getenv('BROKER_API_SECRET')  # This should be the apiKey
    vendor_code = os.getenv('BROKER_API_KEY')  # This should be the vendorCode
    
    # Validate required environment variables
    if not api_key:
        return None, "BROKER_API_SECRET (apiKey) not found in environment variables"
    
    if not vendor_code:
        return None, "BROKER_API_KEY (vendorCode) not found in environment variables"
    
    # Validate required parameters
    if not userid:
        return None, "User ID is required"
    
    if not password:
        return None, "Password is required"

    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Firstock API login URL
        url = "https://api.firstock.in/V1/login"

        # Prepare login payload with all required fields
        payload = {
            "userId": userid,
            "password": sha256_hash(password),  # Convert password to SHA256
            "TOTP": totp_code if totp_code else "",  # Include TOTP if provided
            "vendorCode": vendor_code,
            "apiKey": api_key
        }

        # Set headers for the API request
        headers = {
            'Content-Type': 'application/json'
        }

        logger.info(f"Attempting Firstock authentication for user: {userid}")
        logger.info(f"Vendor Code: {vendor_code}")

        # Send the POST request to Firstock's API using shared httpx client
        response = client.post(url, json=payload, headers=headers, timeout=30)
        
        # Add status attribute for compatibility with existing codebase
        response.status = response.status_code

        # Handle the response based on new API documentation
        if response.status_code == 200:
            data = response.json()
            
            if data.get('status') == "success":
                # Extract the session token from successful response
                token_data = data.get('data', {})
                susertoken = token_data.get('susertoken') or token_data.get('jKey')
                
                if susertoken:
                    logger.info("Firstock authentication successful")
                    return susertoken, None
                else:
                    return None, "Authentication successful but no session token received"
            else:
                # Handle failure response structure
                error_msg = data.get('message', 'Authentication failed')
                error_details = data.get('error', {})
                
                if isinstance(error_details, dict):
                    field_error = error_details.get('field', '')
                    error_message = error_details.get('message', '')
                    if field_error and error_message:
                        error_msg = f"Field '{field_error}': {error_message}"
                
                logger.error(f"Firstock authentication failed: {error_msg}")
                return None, error_msg
                
        elif response.status_code == 400:
            # Bad request - missing or invalid fields
            try:
                error_data = response.json()
                error_msg = error_data.get('error', {}).get('message', 'Bad request - check required fields')
                return None, f"Bad Request: {error_msg}"
            except:
                return None, "Bad Request: Missing or invalid required fields"
                
        elif response.status_code == 401:
            # Unauthorized - invalid credentials
            return None, "Unauthorized: Invalid credentials or API key"
            
        else:
            # Other HTTP errors
            return None, f"HTTP Error {response.status_code}: {response.text}"

    except Exception as e:
        if "timeout" in str(e).lower():
            return None, "Request timeout - please try again"
        elif "connection" in str(e).lower():
            return None, "Connection error - please check your internet connection"
        else:
            logger.error(f"Unexpected error during Firstock authentication: {str(e)}")
            return None, f"Unexpected error: {str(e)}"