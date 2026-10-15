import hashlib
import os
import time
from datetime import datetime

from broker.groww.api.rate_limiter import groww_request
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError
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


def _login_error(body, status_code=None):
    """A login failure in words a trader can act on, with Groww's own reason.

    The advice depends on why Groww refused: too many token requests and a
    failure on Groww's side are not credential problems.
    """
    reason = None
    if isinstance(body, dict):
        error = body.get("error")
        reason = (error.get("message") if isinstance(error, dict) else None) or body.get("message")
    message = "Groww did not issue an access token"
    if reason:
        message += f": {reason}"
    if status_code == 429:
        return (
            f"{message}. Groww is limiting login requests (30 a minute, 150 a day). "
            "Wait a minute, then log in again."
        )
    if status_code is not None and status_code >= 500:
        return (
            f"{message}. Groww's login service is not responding right now; the API key "
            "is not the problem. Try again in a few minutes."
        )
    return (
        f"{message}. Check the API key and secret, and that the key is approved for today "
        "on Groww's API Keys page."
    )


def _token_from_response(body):
    """The access token from a token response (02-authentication "Token response").

    Groww returns token, tokenRefId, sessionName, expiry and isActive. A token
    Groww marks inactive, or one already past its expiry, is refused here
    rather than failing on the first order.
    """
    token = body.get("token") if isinstance(body, dict) else None
    if not token:
        return None, _login_error(body)
    if body.get("isActive") is False:
        return None, (
            "Groww issued an access token that is not active. Approve the API key for today "
            "on Groww's API Keys page, then log in again."
        )
    expiry = body.get("expiry")
    if expiry:
        try:
            expires_at = datetime.fromisoformat(str(expiry))
        except ValueError:
            logger.warning(f"Groww token expiry not understood: {expiry!r}")
        else:
            if expires_at <= datetime.now(expires_at.tzinfo):
                return None, (
                    f"Groww issued an access token that expired at {expiry}. "
                    "Log in again to get a new one."
                )
            logger.info(f"Groww access token valid until {expiry}")
    return token, None


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

        # Headers per Groww API documentation (01-introduction: all are mandatory)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-API-VERSION": "1.0",
        }

        # Payload per Groww API documentation
        payload = {"key_type": "approval", "checksum": checksum, "timestamp": timestamp}

        # Endpoint from Groww API documentation
        endpoint = "https://api.groww.in/v1/token/api/access"

        try:
            response = groww_request(client, "POST", endpoint, "auth", headers=headers, json=payload, timeout=30)

            try:
                response_data = response.json()
            except ValueError:
                response_data = {}
            if response.status_code != 200:
                logger.error(f"Groww login refused: HTTP {response.status_code}, {response.text}")
                return None, _login_error(response_data, response.status_code)
            return _token_from_response(response_data)

        except BrokerBusyError as e:
            # Refused by OpenAlgo's own pacing before anything was sent
            logger.warning(f"Groww login not sent, rate limit queue full: {e}")
            return None, str(e) or BROKER_BUSY_MESSAGE
        except Exception:
            logger.exception("Groww login request failed")
            return None, "Could not reach Groww to log in. Check your connection and try again."

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
