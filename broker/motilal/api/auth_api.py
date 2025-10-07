import httpx
import json
import os
import hashlib
from utils.httpx_client import get_httpx_client

def authenticate_broker(userid, broker_pin, totp_code, date_of_birth):
    """
    Authenticate with Motilal Oswal broker and return the auth token.

    Args:
        userid: Client user ID
        broker_pin: Trading password (will be hashed with API key)
        totp_code: TOTP code from authenticator app (optional, pass empty string if using OTP)
        date_of_birth: 2FA date in format DD/MM/YYYY (e.g., "18/10/1988")

    Returns:
        Tuple of (auth_token, None, error_message)
    """
    api_key = os.getenv('BROKER_API_KEY')

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # SHA-256(password + apikey) as per Motilal Oswal API documentation
        password_hash = hashlib.sha256(f"{broker_pin}{api_key}".encode()).hexdigest()

        # Build payload
        payload = {
            "userid": userid,
            "password": password_hash,
            "2FA": date_of_birth
        }

        # Add TOTP if provided
        if totp_code:
            payload["totp"] = totp_code

        # Motilal Oswal required headers as per API documentation
        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'User-Agent': 'MOSL/V.1.1.0',
            'ApiKey': api_key,
            'ClientLocalIp': '127.0.0.1',
            'ClientPublicIp': '127.0.0.1',
            'MacAddress': '00:00:00:00:00:00',
            'SourceId': 'WEB',
            'vendorinfo': userid,
            'osname': 'Windows',
            'osversion': '10.0',
            'devicemodel': 'PC',
            'manufacturer': 'Generic',
            'productname': 'OpenAlgo',
            'productversion': '1.0.0',
            'browsername': 'Chrome',
            'browserversion': '120.0'
        }

        response = client.post(
            "https://openapi.motilaloswal.com/rest/login/v3/authdirectapi",
            headers=headers,
            json=payload
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        data_dict = response.json()

        # Check for successful authentication
        if data_dict.get('status') == 'SUCCESS' and 'AuthToken' in data_dict:
            auth_token = data_dict['AuthToken']
            # Motilal Oswal doesn't have feed token, return None for compatibility
            return auth_token, None, None
        else:
            error_msg = data_dict.get('message', 'Authentication failed. Please try again.')
            return None, None, error_msg

    except Exception as e:
        return None, None, str(e)
