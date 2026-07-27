# broker/arrow/api/auth_api.py
#
# Arrow login is a Zerodha-style redirect + checksum flow:
#   1. User is sent to https://app.arrow.trade/app/login?appID=<appID>
#   2. Arrow redirects back to REDIRECT_URL (/arrow/callback) with a
#      `request-token` (and a `checksum`) query param.
#   3. We compute SHA256("appID:appSecret:request-token") -- COLON separated,
#      appID:appSecret:request-token order (differs from Zerodha which
#      concatenates api_key+request_token+api_secret with no separators).
#   4. POST it to the authenticate-token endpoint and receive a JWT.
#
# The generic branch in blueprints/brlogin.py passes the request-token in as
# `code` and expects this 2-tuple contract: (auth_token, error_message).

import hashlib
import os

from broker.arrow.api.baseurl import AUTH_TOKEN_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(request_token):
    """Exchange the Arrow request-token for a JWT access token.

    Args:
        request_token: the `request-token` returned to the redirect URL.

    Returns:
        (auth_token, None) on success, (None, error_message) on failure.
    """
    try:
        app_id = os.getenv("BROKER_API_KEY")
        app_secret = os.getenv("BROKER_API_SECRET")

        if not app_id or not app_secret:
            return None, "Configuration error: BROKER_API_KEY / BROKER_API_SECRET not set."

        # Checksum = SHA256("appID:appSecret:request-token") -- colon separated.
        checksum_input = f"{app_id}:{app_secret}:{request_token}"
        checksum = hashlib.sha256(checksum_input.encode()).hexdigest()

        # Field names per https://docs.arrow.trade/rest-api/authentication:
        # checkSum (capital S), token (the request token), appID.
        payload = {
            "appID": app_id,
            "token": request_token,
            "checkSum": checksum,
        }

        client = get_httpx_client()
        response = client.post(
            AUTH_TOKEN_URL,
            json=payload,
            headers={"Content-Type": "application/json"},
        )
        response.raise_for_status()

        response_data = response.json()

        # Arrow envelope: {"status": "success", "data": {"name", "token", "userID"}}.
        # The JWT is returned under data.token (confirmed by the docs).
        if response_data.get("status") == "success":
            data = response_data.get("data", {})
            access_token = data.get("token")
            if access_token:
                return access_token, None
            return (
                None,
                "Authentication succeeded but no access token was returned. Please check the response.",
            )

        # Failure envelope: {"status": "failure"/"error", "message": ...}
        return None, response_data.get("message", "Authentication failed.")

    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_detail = e.response.json()
                error_message = error_detail.get("message", str(e))
        except Exception:
            pass
        logger.error(f"Arrow authentication error: {error_message}")
        return None, f"API error: {error_message}"
