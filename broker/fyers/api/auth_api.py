import os
import json
import hashlib
from typing import Dict, Any, Tuple, Optional
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(request_token: str) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
    """
    Authenticate with FYERS API using request token and return access token with user details.
    
    Args:
        request_token: The authorization code received from FYERS
        
    Returns:
        Tuple of (access_token, response_data). 
        - access_token: The authentication token if successful, None otherwise
        - response_data: Full response data or error details
    """
    # Initialize response data
    response_data = {
        'status': 'error',
        'message': 'Authentication failed',
        'data': None
    }
    
    # Get environment variables
    broker_api_key = os.getenv('BROKER_API_KEY')
    broker_api_secret = os.getenv('BROKER_API_SECRET')
    
    # Validate environment variables
    if not broker_api_key or not broker_api_secret:
        error_msg = "Missing BROKER_API_KEY or BROKER_API_SECRET in environment variables"
        logger.error(error_msg)
        response_data['message'] = error_msg
        return None, response_data
    
    if not request_token:
        error_msg = "No request token provided"
        logger.error(error_msg)
        response_data['message'] = error_msg
        return None, response_data
    
    # FYERS's endpoint for session token exchange
    url = 'https://api-t1.fyers.in/api/v3/validate-authcode'
    
    try:
        # Generate the checksum as a SHA-256 hash of concatenated api_key and api_secret
        checksum_input = f"{broker_api_key}:{broker_api_secret}"
        app_id_hash = hashlib.sha256(checksum_input.encode('utf-8')).hexdigest()
        
        # Prepare the request payload
        payload = {
            'grant_type': 'authorization_code',
            'appIdHash': app_id_hash,
            'code': request_token
        }
        
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }
        
        # Get shared HTTP client with connection pooling
        client = get_httpx_client()
        
        logger.debug(f"Authenticating with FYERS API. Request: {json.dumps(payload, indent=2)}")
        
        # Make the authentication request
        response = client.post(
            url,
            headers=headers,
            json=payload,
            timeout=30.0  # Increased timeout for auth requests
        )
        
        # Process the response
        response.raise_for_status()
        auth_data = response.json()
        logger.debug(f"FYERS auth API response: {json.dumps(auth_data, indent=2)}")
        
        if auth_data.get('s') == 'ok':
            access_token = auth_data.get('access_token')
            if not access_token:
                error_msg = "Authentication succeeded but no access token was returned"
                logger.error(error_msg)
                response_data['message'] = error_msg
                return None, response_data
                
            # Prepare success response
            response_data.update({
                'status': 'success',
                'message': 'Authentication successful',
                'data': {
                    'access_token': access_token,
                    'refresh_token': auth_data.get('refresh_token'),
                    'expires_in': auth_data.get('expires_in')
                }
            })
            
            logger.debug("Successfully authenticated with FYERS API")
            return access_token, response_data
            
        else:
            # Handle API error response
            error_msg = auth_data.get('message', 'Authentication failed')
            logger.error(f"FYERS API error: {error_msg}")
            response_data['message'] = f"API error: {error_msg}"
            return None, response_data
            
    except Exception as e:
        error_msg = f"Authentication failed: {e}"
        logger.exception("Authentication failed due to an unexpected error")
        response_data['message'] = error_msg
        return None, response_data
