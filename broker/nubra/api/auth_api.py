import json
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Nubra API Base URLs
UAT_BASE_URL = "https://uatapi.nubra.io"
PROD_BASE_URL = "https://api.nubra.io"


def get_base_url():
    """Get the base URL based on environment setting."""
    # Default to production, can be configured via env
    use_uat = os.getenv("NUBRA_USE_UAT", "false").lower() == "true"
    return UAT_BASE_URL if use_uat else PROD_BASE_URL


def get_device_id():
    """Get a consistent device ID for Nubra API calls."""
    return "OPENALGO"


def authenticate_broker(totp_code):
    """
    Authenticate with Nubra broker using TOTP flow.

    Since TOTP is enabled, the flow is:
    1. Login via TOTP (/totp/login) with phone + TOTP code
    2. Verify PIN (/verifypin) with MPIN to get session token

    Args:
        totp_code: The TOTP code from authenticator app

    Returns:
        tuple: (auth_token, feed_token, error_message)
               - auth_token: The session token for API calls
               - feed_token: None (Nubra doesn't return a separate feed token)
               - error_message: Error message if authentication failed
    """
    # Get credentials from environment
    phone = os.getenv("BROKER_API_KEY")  # Mobile number
    mpin = os.getenv("BROKER_API_SECRET")  # MPIN

    if not phone or not mpin:
        return (
            None,
            None,
            "Missing BROKER_API_KEY (phone) or BROKER_API_SECRET (mpin) in environment",
        )

    base_url = get_base_url()
    device_id = get_device_id()

    try:
        client = get_httpx_client()

        # Step 1: Login via TOTP
        logger.info(f"Nubra TOTP login initiated for phone: {phone[:5]}***")

        totp_login_payload = {"phone": phone, "totp": int(totp_code)}

        totp_login_headers = {"Content-Type": "application/json", "x-device-id": device_id}

        totp_response = client.post(
            f"{base_url}/totp/login", json=totp_login_payload, headers=totp_login_headers
        )

        totp_data = totp_response.json()
        logger.info(f"Nubra TOTP login response status: {totp_response.status_code}")
        logger.info(f"Nubra TOTP login response data: {totp_data}")

        # Check for auth_token in response (success indicator)
        auth_token = totp_data.get("auth_token")
        if not auth_token:
            error_msg = totp_data.get("message", "TOTP login failed")
            logger.error(f"Nubra TOTP login failed: {error_msg}")
            return None, None, error_msg

        logger.info(f"Nubra TOTP login successful, next step: {totp_data.get('next')}")

        # Step 2: Verify PIN to get session token
        logger.info("Nubra TOTP login successful, verifying PIN...")

        verify_pin_payload = {"pin": mpin}

        verify_pin_headers = {
            "Content-Type": "application/json",
            "x-device-id": device_id,
            "Authorization": f"Bearer {auth_token}",
        }

        pin_response = client.post(
            f"{base_url}/verifypin", json=verify_pin_payload, headers=verify_pin_headers
        )

        pin_data = pin_response.json()
        logger.debug(f"Nubra PIN verification response: {pin_data}")

        if pin_response.status_code != 200:
            error_msg = pin_data.get("message", "PIN verification failed")
            logger.error(f"Nubra PIN verification failed: {error_msg}")
            return None, None, error_msg

        session_token = pin_data.get("session_token")
        if not session_token:
            return None, None, "No session_token received from PIN verification"

        logger.info("Nubra authentication successful")

        # Return session_token as auth_token, no separate feed_token for Nubra
        return session_token, None, None

    except Exception as e:
        logger.error(f"Nubra authentication error: {str(e)}")
        return None, None, str(e)
