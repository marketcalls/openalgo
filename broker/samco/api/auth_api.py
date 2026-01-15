import json
import os
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def get_client_id():
    """Get the client ID (User ID) from environment variables."""
    return os.getenv('BROKER_API_KEY')


def get_password():
    """Get the password from environment variables."""
    return os.getenv('BROKER_API_SECRET')


def authenticate_broker(yob=None):
    """
    Authenticate with Samco broker and return the session token.

    Args:
        yob: Year of birth (required)

    Returns:
        tuple: (auth_token, error_message)
    """
    try:
        client_id = get_client_id()
        password = get_password()

        if not client_id:
            return None, "Client ID not configured. Please set BROKER_API_KEY in .env"

        if not password:
            return None, "Password not configured. Please set BROKER_API_SECRET in .env"

        # Get the shared httpx client
        client = get_httpx_client()

        # Build payload
        payload = {
            "userId": client_id,
            "password": password
        }

        # Add yob if provided
        if yob:
            payload["yob"] = yob

        headers = {
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        }

        logger.info(f"Attempting Samco authentication for user: {client_id}")

        response = client.post(
            f"{BASE_URL}/login",
            headers=headers,
            json=payload
        )

        data = response.json()
        logger.debug(f"Samco login response: {data}")

        if data.get('status') == 'Success' and data.get('sessionToken'):
            session_token = data['sessionToken']
            logger.info(f"Samco authentication successful for user: {client_id}")
            logger.info(f"Session Token: {session_token}")
            return session_token, None
        else:
            error_msg = data.get('statusMessage', 'Authentication failed. Please try again.')
            logger.error(f"Samco authentication failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Samco authentication error: {str(e)}")
        return None, str(e)
