import httpx
import json
import os
from utils.httpx_client import get_httpx_client

def authenticate_broker(api_key, totp_code):
    """
    Authenticate with mstock and return the auth token.
    """
    try:
        client = get_httpx_client()

        # If TOTP is enabled, we can directly verify it without a prior login call
        headers = {
            'X-Mirae-Version': '1',
            'Content-Type': 'application/x-www-form-urlencoded',
        }
        data = {
            'api_key': api_key,
            'totp': totp_code,
        }

        response = client.post(
            'https://api.mstock.trade/openapi/typea/session/verifytotp',
            headers=headers,
            data=data
        )

        response.raise_for_status()
        data_dict = response.json()

        if data_dict.get("status") == "success" and "data" in data_dict:
            auth_token = data_dict["data"].get("access_token")
            # mstock does not provide a separate feed token in this response
            feed_token = None
            return auth_token, feed_token, None
        else:
            error_message = data_dict.get("message", "Authentication failed.")
            return None, None, error_message

    except httpx.HTTPStatusError as e:
        return None, None, f"HTTP error occurred: {e.response.status_code} - {e.response.text}"
    except Exception as e:
        return None, None, str(e)
