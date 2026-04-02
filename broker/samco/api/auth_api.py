import os

from database.auth_db import samco_get_secret_key as get_secret_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"


def _log_raw(step, response):
    """Log raw HTTP response for debugging."""
    logger.debug(f"[Samco {step}] HTTP {response.status_code} | Headers: {dict(response.headers)}")
    logger.debug(f"[Samco {step}] Raw Body: (omitted, may contain sensitive data)")


def _parse_response(step, response):
    """Parse JSON response, handling non-JSON errors (502, 503, etc.)."""
    _log_raw(step, response)
    try:
        return response.json()
    except Exception:
        return {"status": "Failure", "statusMessage": f"HTTP {response.status_code}: {step} failed - {response.text[:200]}"}


def get_client_id():
    """Get the client ID (User ID) from environment variables."""
    return os.getenv("BROKER_API_KEY")


def get_password():
    """Get the password from environment variables."""
    return os.getenv("BROKER_API_SECRET")


def generate_otp(uid):
    """
    Step 1: Generate OTP - sends OTP to registered mobile and email.

    Args:
        uid: SAMCO user ID

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {"uid": uid}

        logger.info(f"Generating OTP for user: {uid}")
        response = client.post(f"{BASE_URL}/otp/generateOtp", headers=headers, json=payload)
        data = _parse_response("generateOtp", response)

        if data.get("status") == "Success":
            logger.info(f"OTP sent successfully for user: {uid}")
            return data, None
        else:
            error_msg = data.get("statusMessage", "Failed to generate OTP")
            logger.error(f"OTP generation failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"OTP generation error: {str(e)}")
        return None, str(e)


def generate_secret_key(uid, otp):
    """
    Step 2: Generate Secret API Key using OTP.
    The secret key is sent to the user's registered email.

    Args:
        uid: SAMCO user ID
        otp: OTP received via mobile/email

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {"uid": uid, "otp": otp}

        logger.info(f"Generating secret API key for user: {uid}")
        response = client.post(
            f"{BASE_URL}/otp/secretKeyGenerator", headers=headers, json=payload
        )
        data = _parse_response("secretKeyGenerator", response)

        if data.get("status") == "Success":
            logger.info(f"Secret API key sent to email for user: {uid}")
            return data, None
        else:
            error_msg = data.get("statusMessage", "Failed to generate secret key")
            logger.error(f"Secret key generation failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Secret key generation error: {str(e)}")
        return None, str(e)


def generate_access_token(uid, secret_api_key):
    """
    Step 3: Generate Access Token using secret API key.
    Access token is valid for 24 hours.

    Args:
        uid: SAMCO user ID
        secret_api_key: Permanent secret API key

    Returns:
        tuple: (access_token, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {"uid": uid, "secretApiKey": secret_api_key}

        logger.info(f"Generating access token for user: {uid}")
        response = client.post(f"{BASE_URL}/accessToken/token", headers=headers, json=payload)
        data = _parse_response("accessToken", response)

        if data.get("status") == "Success" and data.get("accessToken"):
            logger.info(f"Access token generated for user: {uid}")
            return data["accessToken"], None
        else:
            error_msg = data.get("statusMessage", "Failed to generate access token")
            logger.error(f"Access token generation failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Access token generation error: {str(e)}")
        return None, str(e)


def login(uid, password, access_token):
    """
    Step 4: Login with userId, password, and access token.

    Args:
        uid: SAMCO user ID
        password: Account password
        access_token: Token from generate_access_token

    Returns:
        tuple: (session_token, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {
            "userId": uid,
            "password": password,
            "accessToken": access_token,
        }

        logger.info(f"Attempting Samco login for user: {uid}")
        response = client.post(f"{BASE_URL}/login", headers=headers, json=payload)
        data = _parse_response("login", response)

        if data.get("status") == "Success" and data.get("sessionToken"):
            session_token = data["sessionToken"]
            logger.info(f"Samco login successful for user: {uid}")
            return session_token, None
        else:
            error_msg = data.get("statusMessage", "Login failed. Please try again.")
            logger.error(f"Samco login failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"Samco login error: {str(e)}")
        return None, str(e)


def register_ip(client_id, password, primary_ip, secondary_ip=None):
    """
    Register static IP addresses for secure API access.

    Args:
        client_id: SAMCO client ID
        password: Account password
        primary_ip: Primary static IPv4 address
        secondary_ip: Optional backup static IPv4 address

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {
            "clientId": client_id,
            "primaryIp": primary_ip,
            "password": password,
        }
        if secondary_ip:
            payload["secondaryIp"] = secondary_ip

        logger.info(f"Registering IP for user: {client_id}")
        response = client.post(f"{BASE_URL}/ip/ipRegistration", headers=headers, json=payload)
        data = _parse_response("ipRegistration", response)

        if data.get("status") == "Success":
            logger.info(f"IP registered successfully for user: {client_id}")
            return data, None
        else:
            error_msg = data.get("statusMessage", "IP registration failed")
            logger.error(f"IP registration failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"IP registration error: {str(e)}")
        return None, str(e)


def update_ip(client_id, password, primary_ip, secondary_ip=None):
    """
    Update static IP addresses. Can only be updated once per calendar week.

    Args:
        client_id: SAMCO client ID
        password: Account password
        primary_ip: Primary static IPv4 address
        secondary_ip: Optional backup static IPv4 address

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {
            "clientId": client_id,
            "primaryIp": primary_ip,
            "password": password,
        }
        if secondary_ip:
            payload["secondaryIp"] = secondary_ip

        logger.info(f"Updating IP for user: {client_id}")
        response = client.post(f"{BASE_URL}/ip/ipUpdate", headers=headers, json=payload)
        data = _parse_response("ipUpdate", response)

        if data.get("status") == "Success":
            logger.info(f"IP updated successfully for user: {client_id}")
            return data, None
        else:
            error_msg = data.get("statusMessage", "IP update failed")
            logger.error(f"IP update failed: {error_msg}")
            return None, error_msg

    except Exception as e:
        logger.error(f"IP update error: {str(e)}")
        return None, str(e)


def authenticate_broker():
    """
    Main authentication flow for Samco 2FA.
    Generates access token using stored secret key, then logs in.

    Returns:
        tuple: (session_token, error_message)
    """
    try:
        uid = get_client_id()
        password = get_password()

        if not uid:
            return None, "Client ID not configured. Please set BROKER_API_KEY in .env"
        if not password:
            return None, "Password not configured. Please set BROKER_API_SECRET in .env"

        # Get stored secret API key from DB
        secret_api_key = get_secret_key(uid)
        if not secret_api_key:
            return None, "Secret API key not found. Please complete the one-time setup first."

        # Step 1: Generate access token (valid 24 hours)
        access_token, error = generate_access_token(uid, secret_api_key)
        if not access_token:
            return None, f"Access token generation failed: {error}"

        # Step 2: Login with access token
        session_token, error = login(uid, password, access_token)
        if not session_token:
            return None, f"Login failed: {error}"

        return session_token, None

    except Exception as e:
        logger.error(f"Samco authentication error: {str(e)}")
        return None, str(e)
