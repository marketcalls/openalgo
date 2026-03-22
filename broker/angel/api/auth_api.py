"""Angel One broker authentication module.

Handles authentication with the Angel One (formerly Angel Broking) REST API
using client credentials and TOTP-based two-factor authentication.
"""

import json
import os

import httpx

from utils.httpx_client import get_httpx_client


def authenticate_broker(clientcode, broker_pin, totp_code):
    """Authenticate with Angel One and obtain a JWT session token.

    Sends a login request to the Angel One API with the user's client code,
    PIN, and TOTP code. On success, returns both the JWT auth token and
    the feed token for WebSocket market data streaming.

    Args:
        clientcode (str): The Angel One client code (user ID).
        broker_pin (str): The user's trading PIN/password.
        totp_code (str): The time-based one-time password for 2FA.

    Returns:
        tuple: A 3-tuple of (auth_token, feed_token, error):
            - auth_token (str or None): JWT token for API authentication.
            - feed_token (str or None): Token for WebSocket feed access.
            - error (str or None): Error message if authentication failed.
    """
    api_key = os.getenv("BROKER_API_KEY")

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        payload = json.dumps({"clientcode": clientcode, "password": broker_pin, "totp": totp_code})
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-UserType": "USER",
            "X-SourceID": "WEB",
            "X-ClientLocalIP": "CLIENT_LOCAL_IP",  # Ensure these are handled or replaced appropriately
            "X-ClientPublicIP": "CLIENT_PUBLIC_IP",
            "X-MACAddress": "MAC_ADDRESS",
            "X-PrivateKey": api_key,
        }

        response = client.post(
            "https://apiconnect.angelone.in/rest/auth/angelbroking/user/v1/loginByPassword",
            headers=headers,
            content=payload,
        )

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        data = response.text
        data_dict = json.loads(data)

        if "data" in data_dict and "jwtToken" in data_dict["data"]:
            # Return both JWT token and feed token if available (None if not)
            auth_token = data_dict["data"]["jwtToken"]
            feed_token = data_dict["data"].get("feedToken", None)
            return auth_token, feed_token, None
        else:
            return None, None, data_dict.get("message", "Authentication failed. Please try again.")
    except Exception as e:
        return None, None, str(e)
