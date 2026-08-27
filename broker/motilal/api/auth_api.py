"""Motilal Oswal (MOFSL) login.

Flow implemented here (see broker-api-docs/motilaloswal-api-docs/):

  1. ``POST /rest/login/v7/authdirectapi``  (doc 08) -- returns ``AuthToken``.
  2. ``POST /rest/login/v1/getaccesstoken`` (doc 09) -- returns ``accesstoken``.
     Optional: it needs an ``apisecretkey``, so it is skipped (with a warning)
     when ``BROKER_API_SECRET`` is not configured, and a failure there never
     fails the login.

Env convention (same as every other OpenAlgo broker): ``BROKER_API_KEY`` is the
App API Key -- it is both the ``ApiKey`` header and the key hashed with the
password below -- and ``BROKER_API_SECRET`` is the App API Secret.

NOT IMPLEMENTED: the SMS/Email OTP path. Doc 08 allows omitting ``totp`` to have
an OTP delivered instead, which then has to be completed via
``/rest/login/v5/resendotp`` (doc 10) and ``/rest/login/v5/verifyotp`` (doc 11).
Those two endpoints have no implementation here and completing them needs UI +
blueprint support that does not exist yet, so when the login response reports
``isAuthTokenVerified`` != ``"TRUE"`` we return an error asking the user to use
TOTP rather than handing back an unverified token as a successful login.
"""

import hashlib
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

from .baseurl import (
    get_api_secret_key,
    get_common_headers,
    get_url,
    join_auth_token,
    set_client_code,
)

logger = get_logger(__name__)


def _format_error(data_dict, fallback):
    """Build an error message that keeps the documented ``errorcode`` (doc 04).

    The code distinguishes e.g. MO1093 Invalid TOTP from MO1007 Invalid 2FA and
    MO2035 Unauthorized IP Address, which the message alone may not.
    """
    message = data_dict.get("message") or fallback
    errorcode = data_dict.get("errorcode")
    if errorcode:
        return f"{message} (errorcode: {errorcode})"
    return message


def _get_access_token(auth_token, userid):
    """Run the optional getaccesstoken step (doc 09).

    Returns the access token, or ``None`` if it could not be obtained. Never
    raises: the caller falls back to the bare AuthToken.
    """
    if not get_api_secret_key():
        logger.warning(
            "Motilal: BROKER_API_SECRET not configured, skipping getaccesstoken; "
            "using the AuthToken alone."
        )
        return None

    try:
        client = get_httpx_client()
        # Doc 09: no request body, common headers only. Authorization = AuthToken,
        # apisecretkey added by get_common_headers when configured.
        headers = get_common_headers(auth=auth_token, vendor_info=userid)
        response = client.post(get_url("getaccesstoken"), headers=headers)

        if response.status_code != 200:
            logger.warning(
                "Motilal getaccesstoken failed with HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            return None

        data_dict = response.json()
        if data_dict.get("status") == "SUCCESS" and data_dict.get("accesstoken"):
            return data_dict["accesstoken"]

        logger.warning(
            "Motilal getaccesstoken did not return a token: %s",
            _format_error(data_dict, "unknown error"),
        )
        return None

    except Exception as e:
        logger.warning("Motilal getaccesstoken call failed: %s", e, exc_info=True)
        return None


def authenticate_broker(userid, broker_pin, totp_code, date_of_birth):
    """
    Authenticate with Motilal Oswal broker and return the auth token.

    Args:
        userid: Client user ID
        broker_pin: Trading password (will be hashed with API key)
        totp_code: TOTP code from authenticator app (optional, pass empty string if using OTP)
        date_of_birth: 2FA date in format DD/MM/YYYY (e.g., "18/10/1988")

    Returns:
        Tuple of (auth_token, None, error_message). ``auth_token`` is either the
        bare AuthToken or ``"<authtoken>:::<accesstoken>"`` -- use
        ``baseurl.split_auth_token`` to unpack it. Motilal has no feed token, so
        the second element is always ``None``.
    """
    # doc 08: SHA-256(Password + APIKey) uses the App API Key, which is the same
    # value sent in the ApiKey header -- BROKER_API_KEY under the standard
    # OpenAlgo naming. Using the secret here fails with MO2005 before the
    # password is ever checked.
    api_key = os.getenv("BROKER_API_KEY")

    # The client code is not an env variable; remember the one logging in now so
    # header/vendorinfo and the market-data feed can use it in this process.
    set_client_code(userid)

    try:
        # Get the shared httpx client
        client = get_httpx_client()

        # SHA-256(password + apikey) as per Motilal Oswal API documentation (doc 08)
        password_hash = hashlib.sha256(f"{broker_pin}{api_key}".encode()).hexdigest()

        # Build payload
        payload = {"userid": userid, "password": password_hash, "2FA": date_of_birth}

        # Add TOTP if provided (doc 08: omit or blank to receive an OTP instead)
        if totp_code:
            payload["totp"] = totp_code

        # Doc 05: Authorization is "Used in all API's excluding login API".
        headers = get_common_headers(vendor_info=userid, include_auth=False)

        response = client.post(get_url("authdirectapi"), headers=headers, json=payload)

        # Add status attribute for compatibility with the existing codebase
        response.status = response.status_code

        if response.status_code != 200:
            logger.error(
                "Motilal login failed with HTTP %s: %s",
                response.status_code,
                response.text[:500],
            )
            return (
                None,
                None,
                f"Authentication failed with HTTP status {response.status_code}.",
            )

        try:
            data_dict = response.json()
        except Exception:
            logger.error("Motilal login returned a non-JSON response: %s", response.text[:500])
            return None, None, "Authentication failed: invalid response from broker."

        # Check for successful authentication
        if data_dict.get("status") != "SUCCESS" or not data_dict.get("AuthToken"):
            error_msg = _format_error(data_dict, "Authentication failed. Please try again.")
            logger.error("Motilal login rejected: %s", error_msg)
            return None, None, error_msg

        auth_token = data_dict["AuthToken"]

        # Doc 08: the TOTP flow returns isAuthTokenVerified == "TRUE". Anything
        # else means the token still needs OTP verification, which is not
        # implemented (see module docstring).
        # Fail open: only an explicitly negative value gates the session. A
        # missing or unrecognised value must not block an otherwise-good login,
        # because a wrong block stops trading outright, whereas a wrong allow
        # merely surfaces a clearer MO8003/MO1100 on the next call.
        verified = str(data_dict.get("isAuthTokenVerified", "")).strip().upper()
        if verified in ("FALSE", "0", "NO", "N"):
            logger.error(
                "Motilal login returned an unverified AuthToken (isAuthTokenVerified=%r); "
                "OTP verification is not implemented.",
                data_dict.get("isAuthTokenVerified"),
            )
            return (
                None,
                None,
                "Login requires OTP verification, which is not yet supported by OpenAlgo. "
                "Please enable an authenticator app with Motilal Oswal and log in using a "
                "TOTP code instead.",
            )

        # Optional access-token step. Login must never fail because of it.
        access_token = _get_access_token(auth_token, userid)
        if access_token:
            logger.info("Motilal login successful (AuthToken + access token).")
        else:
            logger.info("Motilal login successful (AuthToken only).")

        # Motilal Oswal doesn't have a feed token, return None for compatibility
        return join_auth_token(auth_token, access_token), None, None

    except Exception as e:
        logger.error("Motilal authentication error: %s", e, exc_info=True)
        return None, None, str(e)
