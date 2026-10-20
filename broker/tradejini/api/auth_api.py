import json
import os
from urllib.parse import urlencode

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


BASE_URL = "https://api.tradejini.com/v2"

# 2FA types accepted by POST /api-gw/oauth/individual-token-v2
VALID_TWOFA_TYPES = ("otp", "totp")

# Values left untouched in .sample.env - treated as "not configured".
_PLACEHOLDER_PREFIXES = ("YOUR_",)


def get_api_key():
    """Return the Tradejini app API key used in the Authorization header.

    Docs 02 (API Basics): every authenticated call sends
    ``Bearer <api_key>:<access_token>``, and the individual-token endpoint sends
    ``Bearer <api_key>`` on its own. The api_key is the alphanumeric value from
    the app registration in the developer portal - the api_secret is only used by
    the third-party OAuth code exchange, which this integration does not use.

    ``BROKER_API_KEY`` holds it, matching every other broker plugin and the
    developer portal's own naming. Older Tradejini builds read the key from
    ``BROKER_API_SECRET``, so that is kept as a fallback for .env files that
    still carry the key there. The two values are indistinguishable at rest -
    both are 32-char alphanumeric strings - so a mix-up surfaces only as a bare
    401 "Unauthorized" from the login endpoint.

    Returns:
        str: The API key, or an empty string when neither variable is set.
    """
    for name in ("BROKER_API_KEY", "BROKER_API_SECRET"):
        value = (os.getenv(name) or "").strip()
        if value and not value.upper().startswith(_PLACEHOLDER_PREFIXES):
            return value
    return ""


# Message shown when neither credential variable carries a usable API key.
API_KEY_MISSING_ERROR = (
    "Tradejini API key not configured. Set BROKER_API_KEY in .env to the "
    "alphanumeric API key of your app from the Tradejini developer portal."
)

# Returned for a 401 from the login endpoint. Tradejini gives no detail: a
# non-whitelisted source IP, a wrong API key, a wrong password and a stale 2FA
# code all come back as the same bare "Unauthorized". The IP check happens at
# the gateway, before the credentials are read, so it is listed first.
UNAUTHORIZED_HINT = (
    "Unauthorized. Check, in order: the password field takes your CubePlus "
    "login PIN, not your account password; individual apps only accept requests "
    "from the static IP whitelisted on the app in the Tradejini developer portal "
    "(docs: API Basics - Static IP Requirement); BROKER_API_KEY must hold the "
    "app API key, since the login never sends the api secret; and the TOTP must "
    "be current. All four fail with this same bare 401."
)


def authenticate_broker(password=None, twofa=None, twofa_type=None):
    """
    Authenticate with Tradejini using individual token service
    Args:
        password (str): User's password
        twofa (str): Two-factor authentication code (OTP or Time based OTP)
        twofa_type (str): Type of 2FA - 'otp' or 'totp'
    Returns:
        tuple: (access_token, error_message)
    """
    try:
        if not all([password, twofa]):
            return None, "Password and TOTP code are required"

        # The API accepts 'otp' (SMS/email) and 'totp' (authenticator app).
        # Anything else is rejected with 401, so fall back to totp.
        twofa_type = (twofa_type or "totp").lower()
        if twofa_type not in VALID_TWOFA_TYPES:
            twofa_type = "totp"

        api_key = get_api_key()
        if not api_key:
            return None, API_KEY_MISSING_ERROR
        source = (
            "BROKER_API_KEY"
            if api_key == (os.getenv("BROKER_API_KEY") or "").strip()
            else "BROKER_API_SECRET"
        )
        logger.info(f"Tradejini login: api_key from {source}, twoFaTyp={twofa_type}")

        url = f"{BASE_URL}/api-gw/oauth/individual-token-v2"

        # This endpoint authenticates with the API key alone (docs 05) - the
        # access token it returns is what completes the api_key:access_token pair.
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Set up form data
        data = {"password": password, "twoFa": twofa, "twoFaTyp": twofa_type}

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        response = client.post(url, data=data, headers=headers)
        response_data = response.json()

        # Print the full response for debugging
        logger.info(f"Tradejini Response Status: {response.status_code}")
        logger.info(f"Tradejini Response header fields: {list(response.headers)}")
        logger.info(f"Tradejini Response Data: {response_data}")

        if response.status_code == 200:
            # API returns: {scope, access_token, token_type, expires_in}
            if "access_token" not in response_data:
                return None, "No access token in response"

            # The documented value is lowercase "bearer"; accept any casing.
            token_type = str(response_data.get("token_type", "")).lower()
            if token_type and token_type != "bearer":
                return None, f"Invalid token type in response: {response_data.get('token_type')}"

            return response_data["access_token"], None
        else:
            # Errors use the standard envelope: {"s": "error", "msg": "..."}
            error_msg = (
                response_data.get("msg") or response_data.get("message") or "Authentication failed"
            )
            if response.status_code == 401:
                error_msg = UNAUTHORIZED_HINT
            return None, error_msg
    except httpx.RequestError as e:
        return None, f"Request failed: {str(e)}"
    except json.JSONDecodeError:
        return None, "Invalid JSON response from server"
    except Exception as e:
        return None, str(e)


def get_auth_url():
    """
    Generate the authorization URL for Tradejini OAuth flow
    """
    # docs 05: client_id is the app's API key, not the secret.
    REDIRECT_URI = os.getenv("REDIRECT_URI")

    params = {
        "client_id": get_api_key(),
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": "general",
        "state": "random_state",
    }

    return f"{BASE_URL}/api-gw/oauth/authorize?{urlencode(params)}"


def authenticate_broker_oauth(code):
    try:
        # Public-app flow only (docs 05, step 2): the API secret is required here
        # and nowhere else - individual apps never send it.
        url = f"{BASE_URL}/api-gw/oauth/token"
        data = {
            "code": code,
            "client_id": get_api_key(),
            "client_secret": os.getenv("BROKER_API_SECRET"),
            "redirect_uri": os.getenv("REDIRECT_URI"),
            "grant_type": "authorization_code",
        }

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        response = client.post(url, data=data)

        if response.status_code == 200:
            response_data = response.json()
            if "access_token" in response_data:
                return response_data["access_token"], None
            else:
                return None, "No access token in response"
        else:
            return None, f"Authentication failed: {response.text}"

    except Exception as e:
        return None, str(e)
