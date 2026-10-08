# broker/rupeezy/api/auth_api.py
#
# Rupeezy Vortex login is an SSO redirect + checksum flow
# (https://vortex.rupeezy.in/docs/latest/authentication/):
#   1. User is sent to https://flow.rupeezy.in?applicationId=<application_id>
#   2. Rupeezy redirects back to REDIRECT_URL (/rupeezy/callback) with an
#      `auth` query param.
#   3. checksum = SHA256(application_id + auth + api_key), no separators.
#   4. POST {token, applicationId, checksum} to /user/session with the
#      `x-api-key` header; the access token comes back under data.access_token.

import hashlib
import os

from broker.rupeezy.api.baseurl import BASE_URL
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(auth_code):
    """Exchange the Vortex SSO `auth` code for an access token.

    Returns:
        (access_token, None) on success, (None, error_message) on failure.
    """
    try:
        application_id = os.getenv("BROKER_API_KEY")
        api_key = os.getenv("BROKER_API_SECRET")

        if not application_id or not api_key:
            return None, "Configuration error: BROKER_API_KEY / BROKER_API_SECRET not set."
        if not auth_code:
            return None, "No auth code received from Rupeezy login."

        checksum = hashlib.sha256(f"{application_id}{auth_code}{api_key}".encode()).hexdigest()

        # Literal keys per the official vortex_api SDK (exchange_token()).
        payload = {
            "token": auth_code,
            "applicationId": application_id,
            "checksum": checksum,
        }

        client = get_httpx_client()
        response = client.post(
            f"{BASE_URL}/user/session",
            json=payload,
            headers={"Content-Type": "application/json", "x-api-key": api_key},
            timeout=30,
        )
        response.raise_for_status()
        response_data = response.json()

        data = response_data.get("data") or {}
        access_token = data.get("access_token")
        if access_token:
            return access_token, None

        return None, response_data.get(
            "message", "Authentication failed: no access token returned."
        )

    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_message = e.response.json().get("message", error_message)
        except Exception:
            pass
        logger.exception(f"Rupeezy authentication error: {error_message}")
        return None, f"API error: {error_message}"
