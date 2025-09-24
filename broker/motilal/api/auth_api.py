import httpx
import json
import os
import hashlib
import socket
import uuid
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_client_ip():
    """Get the client's local IP address"""
    try:
        # Connect to a remote server to get local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_mac_address():
    """Get the MAC address of the machine"""
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0,8*6,8)][::-1])
        return mac
    except:
        return "00:00:00:00:00:00"

def authenticate_broker(userid, password, totp_code=None, twofa=None):
    """
    Authenticate with Motilal Oswal broker according to official API documentation.
    
    Parameters:
    - userid: Motilal Oswal user ID (e.g., "AA017")
    - password: User's trading password 
    - totp_code: 6-digit TOTP code from authenticator app (optional)
    - twofa: Date of birth in DD/MM/YYYY format (e.g., "18/10/1988")
    
    Returns:
    - Tuple of (auth_token, feed_token, error_message)
    """
    api_key = os.getenv('BROKER_API_KEY')
    
    if not api_key:
        return None, None, "API Key not found in environment variables"

    try:
        # Get the shared httpx client
        client = get_httpx_client()
        
        # Generate SHA-256 hash of password + API key as per documentation
        password_hash = hashlib.sha256((password + api_key).encode()).hexdigest()
        logger.debug(f"Generated password hash for Motilal Oswal authentication")
        
        # Prepare payload based on authentication method
        payload = {
            "userid": userid,
            "password": password_hash,
            "2FA": twofa  # Date of birth in DD/MM/YYYY format
        }
        
        # Add TOTP if provided
        if totp_code:
            payload["totp"] = totp_code
            
        # Validate required fields
        if not twofa:
            return None, None, "Date of birth (2FA) is required"
            
        # Get system information for headers
        client_local_ip = get_client_ip()
        mac_address = get_mac_address()
        
        # Set headers as per Motilal Oswal API documentation
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'MOSL/V.1.1.0',
            'ApiKey': api_key,
            'ClientLocalIp': client_local_ip,
            'ClientPublicIp': client_local_ip,  # Using same IP for simplicity
            'MacAddress': mac_address,
            'SourceId': 'WEB',
            'vendorinfo': userid,  # Use client code (userid) as per documentation
            'osname': 'Windows 10',
            'osversion': '10.0.19041',
            'devicemodel': 'AHV',
            'manufacturer': 'DELL',
            'productname': 'OpenAlgo Trading Platform',
            'productversion': '1.0',
            'browsername': 'Chrome',
            'browserversion': '105.0',
            'Content-Type': 'application/json'
        }

        # Use production or UAT URL based on environment
        # Check if we're in development/testing mode
        is_testing = os.getenv('MOTILAL_USE_UAT', 'false').lower() == 'true'
        if is_testing:
            auth_url = "https://openapi.motilaloswaluat.com/rest/login/v3/authdirectapi"
            logger.info("Using Motilal Oswal UAT environment")
        else:
            auth_url = "https://openapi.motilaloswal.com/rest/login/v3/authdirectapi"
            logger.info("Using Motilal Oswal production environment")
        
        logger.info(f"Authenticating with Motilal Oswal for user: {userid}")
        logger.debug(f"Request payload: {payload}")
        logger.debug(f"Request headers: {dict(headers)}")
        
        response = client.post(
            auth_url,
            headers=headers,
            json=payload
        )
        
        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code
        
        logger.debug(f"Motilal Oswal auth response status: {response.status_code}")
        
        if response.status_code == 200:
            data_dict = response.json()
            
            if data_dict.get('status') == 'SUCCESS':
                auth_token = data_dict.get('AuthToken')
                if auth_token:
                    logger.info(f"Successfully authenticated with Motilal Oswal")
                    # Motilal Oswal doesn't provide separate feed token in auth response
                    return auth_token, None, None
                else:
                    return None, None, "Authentication succeeded but no AuthToken received"
            else:
                error_msg = data_dict.get('message', 'Authentication failed')
                logger.error(f"Motilal Oswal auth failed: {error_msg}")
                return None, None, error_msg
        else:
            try:
                error_data = response.json()
                error_msg = error_data.get('message', f'HTTP {response.status_code} error')
            except:
                error_msg = f'HTTP {response.status_code} error'
            
            logger.error(f"Motilal Oswal auth HTTP error: {error_msg}")
            return None, None, error_msg
            
    except Exception as e:
        logger.error(f"Motilal Oswal authentication exception: {str(e)}")
        return None, None, str(e)
