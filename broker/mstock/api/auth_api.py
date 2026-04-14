import json
import os

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_with_totp(password, totp_code):
    """
    Authenticate with mstock using Type B TOTP authentication (single-step).

    Args:
        password (str): mStock account password
        totp_code (str): The 6-digit TOTP code from authenticator app

    Returns:
        tuple: (auth_token, feed_token, error_message)
    """
    logger.info("Starting mStock Type B TOTP authentication (single-step)")

    # Get credentials from environment variables
    clientcode = os.getenv("BROKER_API_KEY")

    if not clientcode:
        return None, None, "BROKER_API_KEY (clientcode) not found in environment variables."
    if not password:
        return None, None, "Password is required."
    if not totp_code:
        return None, None, "TOTP code is required."

    logger.info(f"Using clientcode: {clientcode}")

    try:
        client = get_httpx_client()

        # Login with clientcode, password, and TOTP to get token directly
        headers = {
            "X-Mirae-Version": "1",
            "Content-Type": "application/json",
        }
        login_data = {
            "clientcode": clientcode,
            "password": password,
            "totp": totp_code,
            "state": "",
        }

        logger.info(f"Sending login request with TOTP (length: {len(totp_code)})")

        login_response = client.post(
            "https://api.mstock.trade/openapi/typeb/connect/login", headers=headers, json=login_data
        )

        login_response.raise_for_status()
        login_result = login_response.json()

        logger.info(f"Login response status: {login_result.get('status')}")
        logger.info(f"Login response message: {login_result.get('message')}")

        # Check if login was successful (status can be boolean True or string "true")
        status = login_result.get("status")
        if status not in [True, "true"] or "data" not in login_result:
            error_message = login_result.get("message", "Authentication failed.")
            logger.error(f"Authentication failed: {error_message}")
            return None, None, error_message

        # Get refresh token from response (not the final auth token)
        data = login_result["data"]
        refresh_token = data.get("refreshToken") or data.get("jwtToken")

        if not refresh_token:
            logger.error("No refreshToken in login response")
            logger.info(f"Available fields in data: {data}")
            return None, None, "Failed to get refresh token from response."

        logger.info("Login with TOTP successful, now verifying TOTP to get final token")

        # Step 2: Verify TOTP with refresh token to get the final authentication token
        api_key = os.getenv("BROKER_API_SECRET")
        verify_headers = {
            "X-Mirae-Version": "1",
            "X-PrivateKey": api_key,
            "Content-Type": "application/json",
        }
        verify_data = {"refreshToken": refresh_token, "totp": totp_code}

        logger.info("Calling verifytotp endpoint to get final authentication token")

        verify_response = client.post(
            "https://api.mstock.trade/openapi/typeb/session/verifytotp",
            headers=verify_headers,
            json=verify_data,
        )

        verify_response.raise_for_status()
        verify_result = verify_response.json()

        logger.info(f"TOTP verification response status: {verify_result.get('status')}")
        logger.info(f"TOTP verification response message: {verify_result.get('message')}")

        # Check if verification was successful
        status = verify_result.get("status")
        if status not in [True, "true"] or "data" not in verify_result:
            error_message = verify_result.get("message", "TOTP verification failed.")
            logger.error(f"TOTP verification failed: {error_message}")
            return None, None, error_message

        # Get final authentication tokens
        final_data = verify_result["data"]
        auth_token = final_data.get("jwtToken")
        feed_token = final_data.get("feedToken")
        logger.debug(f"Feed token received: {auth_token}")

        if not auth_token:
            logger.error("No jwtToken in verification response")
            logger.debug(f"Available fields in data: {final_data}")
            return None, None, "Failed to get authentication token from verification response."

        logger.info("TOTP authentication successful, got final jwtToken")
        return auth_token, feed_token, None

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error occurred: {e.response.status_code}"
        try:
            error_detail = e.response.json()
            error_msg += f" - {error_detail.get('message', e.response.text)}"
            logger.error(f"HTTP Error: {e.response.status_code}, Details: {error_detail}")
        except:
            error_msg += f" - {e.response.text}"
            logger.error(f"HTTP Error: {e.response.status_code}, Raw: {e.response.text}")
        return None, None, error_msg
    except Exception as e:
        logger.exception("Unexpected error during TOTP authentication")
        return None, None, str(e)


def send_otp(password):
    """
    Step 1 of Type B authentication: Send password to trigger OTP.

    Args:
        password (str): mStock account password

    Returns:
        tuple: (refresh_token, success_message, error_message)
    """
    logger.info("Starting mStock Type B authentication - Step 1: Send OTP")

    # Get credentials from environment variables
    clientcode = os.getenv("BROKER_API_KEY")

    if not clientcode:
        return None, None, "BROKER_API_KEY (clientcode) not found in environment variables."
    if not password:
        return None, None, "Password is required."

    logger.debug(f"Using clientcode: {clientcode}")

    try:
        client = get_httpx_client()

        # Step 1: Login with clientcode and password to get refreshToken
        headers = {
            "X-Mirae-Version": "1",
            "Content-Type": "application/json",
        }
        login_data = {"clientcode": clientcode, "password": password, "totp": "", "state": ""}

        login_response = client.post(
            "https://api.mstock.trade/openapi/typeb/connect/login", headers=headers, json=login_data
        )

        login_response.raise_for_status()
        login_result = login_response.json()

        logger.info(f"Login response status: {login_result.get('status')}")
        logger.debug(f"Login response message: {login_result.get('message')}")
        logger.debug(f"Login response data keys: {list(login_result.get('data', {}).keys())}")

        # Check if login was successful (status can be boolean True or string "true")
        status = login_result.get("status")
        if status not in [True, "true"] or "data" not in login_result:
            error_message = login_result.get("message", "Login failed.")
            logger.error(f"Login failed: {error_message}")
            return None, None, error_message

        # Check if refreshToken field exists first, otherwise use jwtToken
        data = login_result["data"]
        refresh_token = data.get("refreshToken") or data.get("jwtToken")

        if not refresh_token:
            logger.error("No refreshToken or jwtToken in login response")
            logger.debug(f"Available fields in data: {data}")
            return None, None, "Failed to get refreshToken from login response."

        logger.debug(
            f"Using token as refreshToken: {refresh_token[:30]}... (length: {len(refresh_token)})"
        )

        success_message = login_result.get("message", "OTP sent successfully")
        logger.debug(f"Login successful, OTP sent. Message: {success_message}")

        return refresh_token, success_message, None

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error occurred: {e.response.status_code}"
        try:
            error_detail = e.response.json()
            error_msg += f" - {error_detail.get('message', e.response.text)}"
            logger.error(f"HTTP Error: {e.response.status_code}, Details: {error_detail}")
        except:
            error_msg += f" - {e.response.text}"
            logger.error(f"HTTP Error: {e.response.status_code}, Raw: {e.response.text}")
        return None, None, error_msg
    except Exception as e:
        logger.exception("Unexpected error during OTP send")
        return None, None, str(e)


def verify_otp(otp_code, refresh_token):
    """
    Step 2 of Type B authentication: Verify OTP to get access token.

    Args:
        otp_code (str): The 6-digit OTP sent to mobile/email
        refresh_token (str): The refresh token from Step 1

    Returns:
        tuple: (auth_token, feed_token, error_message)
    """
    logger.info("Starting mStock Type B authentication - Step 2: Verify OTP")

    api_key = os.getenv("BROKER_API_SECRET")

    if not api_key:
        return None, None, "BROKER_API_SECRET (API key) not found in environment variables."
    if not otp_code:
        return None, None, "OTP is required."
    if not refresh_token:
        return None, None, "Refresh token is required."

    try:
        client = get_httpx_client()

        # Step 2: Verify OTP with refreshToken to get final jwtToken
        token_headers = {
            "X-Mirae-Version": "1",
            "X-PrivateKey": api_key,
            "Content-Type": "application/json",
        }
        token_data = {"refreshToken": refresh_token, "otp": otp_code}

        logger.debug(f"Sending OTP verification request with OTP length: {len(otp_code)}")
        logger.debug(f"RefreshToken length: {len(refresh_token) if refresh_token else 0}")
        logger.debug(f"API Key (X-PrivateKey) length: {len(api_key) if api_key else 0}")
        logger.debug("Request URL: https://api.mstock.trade/openapi/typeb/session/token")
        logger.debug(f"Request headers: {token_headers}")
        logger.debug(f"Request body: refreshToken=[{refresh_token[:20]}...], otp={otp_code}")

        token_response = client.post(
            "https://api.mstock.trade/openapi/typeb/session/token",
            headers=token_headers,
            json=token_data,
        )

        logger.debug(f"OTP verification HTTP status: {token_response.status_code}")
        logger.debug(f"OTP verification response headers: {dict(token_response.headers)}")
        logger.debug(f"OTP verification raw response text: [{token_response.text}]")

        token_response.raise_for_status()
        token_result = token_response.json()

        logger.debug(f"OTP verification response status: {token_result.get('status')}")
        logger.debug(f"OTP verification response message: {token_result.get('message')}")

        # Check if OTP verification was successful (status can be boolean True or string "true")
        status = token_result.get("status")
        if status in [True, "true"] and "data" in token_result:
            auth_token = token_result["data"].get("jwtToken")
            feed_token = token_result["data"].get("feedToken")
            logger.info("OTP verification successful, got jwtToken")
            return auth_token, feed_token, None
        else:
            error_message = token_result.get("message", "Token generation failed.")
            logger.error(f"OTP verification failed: {error_message}")
            return None, None, error_message

    except httpx.HTTPStatusError as e:
        error_msg = f"HTTP error occurred: {e.response.status_code}"
        try:
            error_detail = e.response.json()
            error_msg += f" - {error_detail.get('message', e.response.text)}"
            logger.error(f"HTTP Error: {e.response.status_code}, Details: {error_detail}")
        except:
            error_msg += f" - {e.response.text}"
            logger.error(f"HTTP Error: {e.response.status_code}, Raw: {e.response.text}")
        return None, None, error_msg
    except Exception as e:
        logger.exception("Unexpected error during OTP verification")
        return None, None, str(e)


# Keep authenticate_broker for backward compatibility (deprecated, use send_otp + verify_otp)
def authenticate_broker(otp_code, password=None):
    """
    DEPRECATED: Use send_otp() and verify_otp() for proper two-step authentication.

    This function attempts to do both steps in one call, which won't work properly
    since the user needs to receive the OTP after Step 1 before providing it for Step 2.
    """
    logger.warning(
        "authenticate_broker called - this is deprecated. Use send_otp() and verify_otp() instead."
    )
    return None, None, "Please use the two-step authentication flow"
