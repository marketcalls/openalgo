import hashlib
import os
import time

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def generate_checksum(api_secret, timestamp):
    """
    Generate checksum using API secret and timestamp.
    Checksum = SHA256(secret + timestamp)

    Args:
        api_secret: The API secret from Groww
        timestamp: Unix timestamp in epoch seconds (as string)

    Returns:
        str: Generated checksum (hex digest)
    """
    input_str = api_secret + timestamp
    sha256 = hashlib.sha256()
    sha256.update(input_str.encode("utf-8"))
    return sha256.hexdigest()


def get_access_token_via_checksum(api_key, api_secret):
    """
    Get access token using API key and secret with checksum-based flow.
    Implements the authentication flow per Groww API documentation.

    Args:
        api_key: The API key from Groww
        api_secret: The API secret from Groww

    Returns:
        tuple: (access_token, error_message)
    """
    try:
        # Generate current timestamp in epoch seconds
        timestamp = str(int(time.time()))

        # Generate checksum = SHA256(secret + timestamp)
        checksum = generate_checksum(api_secret, timestamp)

        # Get the shared httpx client
        client = get_httpx_client()

        # Headers per Groww API documentation
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        # Payload per Groww API documentation
        payload = {"key_type": "approval", "checksum": checksum, "timestamp": timestamp}

        # Endpoint from Groww API documentation
        endpoint = "https://api.groww.in/v1/token/api/access"

        try:
            response = client.post(endpoint, headers=headers, json=payload, timeout=30)

            if response.status_code == 200:
                response_data = response.json()

                # Expect 'token' field in response
                if "token" in response_data:
                    return response_data["token"], None
                else:
                    return (
                        None,
                        f"Authentication succeeded but no token found in response: {response_data}",
                    )
            else:
                try:
                    error_data = response.json()
                    return None, f"HTTP error {response.status_code}: {error_data}"
                except:
                    return None, f"HTTP error {response.status_code}: {response.text}"

        except Exception as e:
            return None, f"Request failed: {str(e)}"

    except Exception as e:
        return None, f"Authentication error: {str(e)}"


def authenticate_broker(code):
    """
    Authenticate with Groww using API key and secret with checksum-based flow.
    The 'code' parameter is not used as authentication relies on environment variables.

    Args:
        code: Not used in checksum flow, kept for compatibility

    Returns:
        tuple: (access_token, error_message)
    """
    try:
        BROKER_API_KEY = os.getenv("BROKER_API_KEY")
        BROKER_API_SECRET = os.getenv("BROKER_API_SECRET")

        if not BROKER_API_KEY or not BROKER_API_SECRET:
            return (
                None,
                "BROKER_API_KEY and BROKER_API_SECRET environment variables are required for Groww authentication",
            )

        # Use checksum flow to get access token
        return get_access_token_via_checksum(BROKER_API_KEY, BROKER_API_SECRET)

    except Exception as e:
        return None, f"An exception occurred: {str(e)}"
