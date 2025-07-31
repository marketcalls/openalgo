import json
import os
import httpx
from typing import Tuple, Optional
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(clientcode: str, broker_pin: str, totp_code: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Authenticate with the broker and return the auth token.
    
    Args:
        clientcode (str): Client's email ID
        broker_pin (str): Broker PIN
        totp_code (str): TOTP code for authentication
    
    Returns:
        Tuple[Optional[str], Optional[str]]: (access_token, error_message)
    """
    # Retrieve the BROKER_API_KEY and BROKER_API_SECRET environment variables
    broker_api_key = os.getenv('BROKER_API_KEY')
    api_secret = os.getenv('BROKER_API_SECRET')

    if not broker_api_key or not api_secret:
        return None, "BROKER_API_KEY or BROKER_API_SECRET not found in environment variables"

    # Split the string to separate the API key and the client ID
    try:
        api_key, user_id, client_id = broker_api_key.split(':::')
    except ValueError:
        return None, "BROKER_API_KEY format is incorrect. Expected format: 'api_key:::user_id:::client_id'"

    headers = {
        'Content-Type': 'application/json',
        'Accept': 'application/json'
    }

    try:
        # Step 1: Perform TOTP login
        totp_login_data = {
            "head": {"Key": api_key},
            "body": {
                "Email_ID": clientcode,
                "TOTP": totp_code,
                "PIN": broker_pin
            }
        }

        # Get the shared httpx client
        client = get_httpx_client()

        totp_response = client.post(
            "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/TOTPLogin",
            json=totp_login_data,
            headers=headers
        )
        totp_response.raise_for_status()
        totp_data = totp_response.json()

        logger.info(f"The Request Token response is :{totp_data}")

        request_token = totp_data.get('body', {}).get('RequestToken')
        logger.info(f"The Request Token is :{request_token}")

        if not request_token:
            error_message = totp_data.get('body', {}).get('Message', 'Failed to obtain request token. Please try again.')
            return None, f"TOTP Login Error: {error_message}"

        # Step 2: Get access token using the request token
        access_token_data = {
            "head": {"Key": api_key},
            "body": {
                "RequestToken": request_token,
                "EncryKey": api_secret,
                "UserId": user_id
            }
        }

        logger.info(f"The Access Token request is :{json.dumps(access_token_data)}")

        token_response = client.post(
            "https://Openapi.5paisa.com/VendorsAPI/Service1.svc/GetAccessToken",
            json=access_token_data,
            headers=headers
        )
        token_response.raise_for_status()
        token_data = token_response.json()

        logger.info(f"The Access Token response is :{token_data}")

        if 'body' in token_data and 'AccessToken' in token_data['body']:
            return token_data['body']['AccessToken'], None
        else:
            error_message = token_data.get('body', {}).get('Message', 'Failed to obtain access token. Please try again.')
            return None, f"Access Token Error: {error_message}"

    except httpx.HTTPStatusError as e:
        return None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except httpx.RequestError as e:
        return None, f"Request error occurred: {str(e)}"
    except json.JSONDecodeError:
        return None, "Failed to parse JSON response from the server"
    except Exception as e:
        return None, str(e)
