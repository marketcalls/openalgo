"""
Samco Trade API v3.2 authentication.

Uses the direct server-to-server flow: POST /session/token with the OAuth app's
apiKey + apiSecret, which returns a JWT session token sent as the x-session-token
header on every subsequent call. The token is valid until 08:00 IST the next day.

The legacy 4-step flow (/otp/generateOtp -> /otp/secretKeyGenerator ->
/accessToken/token -> /login) and the password-based /ip/ipRegistration and
/ip/ipUpdate endpoints are deprecated in v3.2 and are not used here. API keys,
secrets and static IPs are managed in the Samco Web Dashboard at
https://tradeapi.samco.in/app/login.
"""

import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# Samco API base URL
BASE_URL = "https://tradeapi.samco.in"

DASHBOARD_URL = "https://tradeapi.samco.in/app/login"

# Remediation hints for the error codes /session/token and the OAuth endpoints
# return. Kept to the fix only - Samco's statusMessage already states the problem.
ERROR_CODE_HELP = {
    "EOAUTH001": (
        "Check BROKER_API_KEY matches the API Key emailed when you created the OAuth "
        f"app, and that the app is Active at {DASHBOARD_URL}"
    ),
    "EOAUTH008": (
        "Re-copy the secret from the dashboard's API Keys -> Reveal Secret flow, or "
        "regenerate it, and update BROKER_API_SECRET"
    ),
    "EOAUTH009": (
        f"Register this server's IP under Static IPs at {DASHBOARD_URL}"
    ),
}


def _parse_response(step, response):
    """Parse a JSON response, tolerating non-JSON error bodies (502, 503, ...)."""
    logger.debug(f"[Samco {step}] HTTP {response.status_code}")
    try:
        return response.json()
    except Exception:
        return {
            "status": "Failure",
            "statusMessage": (
                f"HTTP {response.status_code}: {step} failed - {response.text[:200]}"
            ),
        }


def _error_message(data, default):
    """Build a user-facing error message, expanding Samco's OAuth error codes."""
    message = data.get("statusMessage") or default
    hint = ERROR_CODE_HELP.get(data.get("errorCode"))
    return f"{message}. {hint}" if hint else message


def get_api_key():
    """Get the OAuth app's API key from environment variables."""
    return os.getenv("BROKER_API_KEY")


def get_api_secret():
    """Get the OAuth app's API secret from environment variables."""
    return os.getenv("BROKER_API_SECRET")


def _log_ip_check(data):
    """
    Compare the source IP Samco saw against the registered static IPs.

    Order-related endpoints reject unregistered IPs with HTTP 403, so surfacing a
    mismatch at login is far clearer than a rejected order later. IP fields come
    back as "" (not null) when unset.
    """
    src_ip = data.get("srcIp") or ""
    primary_ip = data.get("primaryIp") or ""
    secondary_ip = data.get("secondaryIp") or ""

    if not src_ip:
        return

    if src_ip in (primary_ip, secondary_ip):
        logger.info(f"Samco source IP {src_ip} matches a registered static IP")
    elif not primary_ip and not secondary_ip:
        logger.warning(
            f"Samco reports no registered static IP (calling from {src_ip}). "
            f"Order APIs will reject this host - register it under Static IPs at {DASHBOARD_URL}"
        )
    else:
        logger.warning(
            f"Samco source IP {src_ip} does not match the registered static IPs "
            f"(primary={primary_ip or 'unset'}, secondary={secondary_ip or 'unset'}). "
            f"Order APIs will reject this host with HTTP 403"
        )


def generate_session_token(api_key, api_secret):
    """
    Generate a session token using the OAuth app's API key and secret.

    The apiKey and apiSecret are the AES-encrypted values Samco issues at app
    creation and are sent verbatim - no client-side encryption is applied.

    Args:
        api_key: API key of the OAuth app
        api_secret: API secret of the OAuth app

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        payload = {"apiKey": api_key, "apiSecret": api_secret}

        logger.info("Generating Samco session token")
        response = client.post(f"{BASE_URL}/session/token", headers=headers, json=payload)
        data = _parse_response("session/token", response)

        if data.get("status") == "Success" and data.get("sessionToken"):
            logger.info(
                f"Samco session token generated for account "
                f"{data.get('accountID', 'unknown')}"
            )
            return data, None

        error_msg = _error_message(data, "Failed to generate session token")
        logger.error(f"Samco session token generation failed: {error_msg}")
        return None, error_msg

    except Exception as e:
        logger.exception("Samco session token generation error")
        return None, str(e)


def get_whoami(session_token):
    """
    Report which public IP Samco sees for requests from this host.

    Read-only diagnostic; it does not consume the SEBI weekly IP-update slot.

    Args:
        session_token: Session token from generate_session_token

    Returns:
        tuple: (response_data, error_message)
    """
    try:
        client = get_httpx_client()
        headers = {"Accept": "application/json", "x-session-token": session_token}

        response = client.get(f"{BASE_URL}/ip/whoami", headers=headers)
        data = _parse_response("ip/whoami", response)

        if data.get("status") == "Success":
            return data, None

        error_msg = _error_message(data, "Failed to fetch IP status")
        logger.error(f"Samco whoami failed: {error_msg}")
        return None, error_msg

    except Exception as e:
        logger.exception("Samco whoami error")
        return None, str(e)


def authenticate_broker():
    """
    Authenticate with Samco and return a session token.

    Returns:
        tuple: (session_token, error_message)
    """
    try:
        api_key = get_api_key()
        api_secret = get_api_secret()

        if not api_key:
            return None, (
                "API key not configured. Set BROKER_API_KEY in .env to the API Key of "
                f"your Samco OAuth app (create one at {DASHBOARD_URL})"
            )
        if not api_secret:
            return None, (
                "API secret not configured. Set BROKER_API_SECRET in .env to the API "
                f"Secret shown once when the OAuth app was created (see {DASHBOARD_URL})"
            )

        data, error = generate_session_token(api_key, api_secret)
        if not data:
            return None, error

        _log_ip_check(data)

        return data["sessionToken"], None

    except Exception as e:
        logger.exception("Samco authentication error")
        return None, str(e)
