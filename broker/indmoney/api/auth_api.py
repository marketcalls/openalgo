"""
IndMoney (INDstocks) authentication.

Two ways to obtain the 24-hour access token (docs
broker-api-docs/indstocks-api-docs/04-authentication-users.md):

1. TOTP (preferred, scriptable) -- POST /generate/token with the static Client
   ID in the ``x-api-key`` header plus the account MPIN and a live 6-digit TOTP
   code. Returns a fresh token without a browser login.
2. Manual token -- the user pastes a token generated from the INDstocks
   dashboard into BROKER_API_SECRET.

Credential mapping:
    BROKER_API_KEY    -> Client ID shown on the INDstocks access-tokens page
                         after TOTP setup (sent as the x-api-key header).
    BROKER_API_SECRET -> optional. A manually generated access token. When set,
                         it is used as-is and the TOTP flow is skipped, which
                         keeps existing installations working unchanged.

The response field is ``token`` (not ``access_token``), and only one
TOTP-generated token is live at a time -- generating a new one invalidates the
previous token.
"""

import json
import os

from broker.indmoney.api.baseurl import get_url
from broker.indmoney.api.rate_limiter import rate_limited_request
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# POST /generate/token is throttled to 1 call per 60 seconds, and 5 wrong TOTP
# codes in 15 minutes locks the endpoint for 15 minutes (3 lockouts in an hour
# escalates to a 1-hour lockout). Never auto-retry -- a retry burns the throttle
# and, with a stale code, walks the account toward a lockout.
_TOKEN_ENDPOINT = "/generate/token"
_REQUEST_TIMEOUT = 30.0


def validate_access_token(access_token):
    """
    Check an access token against GET /user/profile.

    Worth the extra round trip: an INDstocks token expires after 24 hours, so a
    value pasted into BROKER_API_SECRET is dead by the next day. Without this
    check the login "succeeds", the dead token is stored, and every downstream
    call fails with TokenException while the UI claims the broker is connected.

    Returns:
        tuple[bool | None, str | None]: (is_valid, reason)

        True  - the broker accepted the token
        False - the broker REJECTED it; it is genuinely unusable
        None  - could not be determined (network/API failure). A transient
                outage is not evidence against the token, so callers must not
                treat this as a rejection - otherwise a blip locks a working
                installation out of its own broker session.
    """
    access_token = (str(access_token) if access_token is not None else "").strip()
    if not access_token:
        return False, "empty token"

    try:
        # Routed through the shared limiter so this shares the non-trading clock
        # with every other REST call; a login racing concurrent traffic must not
        # be what pushes the account over the documented rate.
        client = get_httpx_client()
        response = rate_limited_request(
            client,
            "GET",
            get_url("/user/profile"),
            headers={"Authorization": access_token, "Accept": "application/json"},
            timeout=_REQUEST_TIMEOUT,
        )

        if response.status_code in (200, 201):
            return True, None

        # Decide the verdict from the status code ALONE, before touching the
        # body. Parsing must only ever enrich the message: if it could raise,
        # a 403 would escape to the outer handler and be reported as
        # "unverifiable", and the caller would then proceed with a credential
        # the broker had explicitly rejected.
        rejected = response.status_code in (401, 403)

        reason = f"HTTP {response.status_code}"
        try:
            body = json.loads(response.text)
            # A JSON body need not be an object - a bare list or string has no
            # .get(), so check before using it.
            if isinstance(body, dict):
                reason = body.get("message") or body.get("error_type") or reason
        except Exception:
            pass

        # Only an auth rejection proves the token is bad. A 429 or a 5xx says
        # nothing about it.
        return (False, str(reason)) if rejected else (None, str(reason))

    except Exception as e:
        # A network failure is not proof the token is bad.
        logger.warning(f"Could not validate IndMoney access token: {e}")
        return None, f"validation request failed: {e}"


def authenticate_broker(code):
    """
    Manual-token login: use the access token pasted into BROKER_API_SECRET,
    after confirming it is still live.

    Args:
        code: Unused; kept for the shared broker-auth call signature.

    Returns:
        tuple[str | None, str | None]: (access_token, error_message)
    """
    try:
        access_token = (os.getenv("BROKER_API_SECRET") or "").strip()

        if not access_token:
            return None, (
                "No access token found in BROKER_API_SECRET. Either paste an access "
                "token generated from https://indstocks.com/app/api-trading/access-tokens, "
                "or leave BROKER_API_SECRET blank and set BROKER_API_KEY to your Client ID "
                "to log in with MPIN + TOTP."
            )

        is_valid, reason = validate_access_token(access_token)
        if is_valid:
            return access_token, None

        if is_valid is None:
            # Unverifiable, not rejected. Proceed with the configured token
            # rather than locking a working installation out over a transient
            # outage - if it really is dead, the first API call says so.
            logger.warning(
                f"Could not verify the access token in BROKER_API_SECRET ({reason}); "
                "proceeding with it. If broker calls fail, regenerate the token."
            )
            return access_token, None

        logger.warning(f"Access token in BROKER_API_SECRET was rejected: {reason}")
        return None, (
            f"The access token in BROKER_API_SECRET is not usable ({reason}). "
            "INDstocks tokens expire after 24 hours. Either paste a fresh token from "
            "https://indstocks.com/app/api-trading/access-tokens, or clear "
            "BROKER_API_SECRET to log in with MPIN + TOTP instead."
        )

    except Exception as e:
        logger.exception(f"Error reading IndMoney access token: {e}")
        return None, f"An exception occurred: {str(e)}"


def authenticate_broker_totp(mpin, totp_code):
    """
    Generate a fresh access token via POST /generate/token.

    Args:
        mpin: The account MPIN.
        totp_code: Current 6-digit code from the authenticator app.

    Returns:
        tuple[str | None, str | None]: (access_token, error_message)
    """
    client_id = (os.getenv("BROKER_API_KEY") or "").strip()

    if not client_id:
        return None, (
            "BROKER_API_KEY is not set. For IndMoney this must be the Client ID "
            "shown on the INDstocks access-tokens page after TOTP setup."
        )

    mpin = (str(mpin) if mpin is not None else "").strip()
    # A TOTP code's leading zeros are significant, so keep it a string and never
    # coerce it through int().
    totp_code = (str(totp_code) if totp_code is not None else "").strip()

    if not mpin or not totp_code:
        return None, "Both MPIN and the 6-digit TOTP code are required."

    payload = json.dumps({"mpin": mpin, "totp": totp_code})
    headers = {
        "x-api-key": client_id,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        client = get_httpx_client()
        url = get_url(_TOKEN_ENDPOINT)

        logger.info("Requesting IndMoney access token via TOTP")
        response = client.post(url, headers=headers, content=payload, timeout=_REQUEST_TIMEOUT)
        # Compatibility with the rest of the codebase, which reads .status.
        response.status = response.status_code

        try:
            response_data = json.loads(response.text)
        except (json.JSONDecodeError, TypeError):
            logger.error(
                f"Non-JSON response from {_TOKEN_ENDPOINT} "
                f"(HTTP {response.status_code}): {response.text[:300]}"
            )
            return None, _http_error_message(response.status_code)

        if response.status_code in (200, 201):
            # The documented field is "token", not "access_token". Accept both
            # so a later rename does not silently break login.
            data = response_data.get("data") or {}
            token = (
                data.get("token")
                or data.get("access_token")
                or response_data.get("token")
                or response_data.get("access_token")
            )

            if token:
                logger.info("IndMoney TOTP authentication successful")
                return token, None

            logger.error(f"No token field in /generate/token response: {response_data}")
            return None, "Token generation succeeded but no token was returned."

        error_message = (
            response_data.get("message")
            or response_data.get("error")
            or _http_error_message(response.status_code)
        )
        logger.error(
            f"IndMoney TOTP authentication failed (HTTP {response.status_code}): {error_message}"
        )
        return None, _decorate_error(response.status_code, str(error_message))

    except Exception as e:
        logger.exception(f"Error during IndMoney TOTP authentication: {e}")
        return None, f"An exception occurred: {str(e)}"


def _http_error_message(status_code):
    """Fallback message when the API returns no parseable error body."""
    if status_code in (401, 403):
        return "Invalid Client ID, MPIN, or TOTP code."
    if status_code == 429:
        return "Token generation is throttled."
    if status_code >= 500:
        return "INDstocks is temporarily unavailable. Try again shortly."
    return f"Token generation failed with HTTP {status_code}."


def _decorate_error(status_code, message):
    """
    Append the actionable hint for the documented failure modes, so the user
    does not retry into a lockout.
    """
    if status_code == 429:
        return (
            f"{message} Token generation is limited to 1 request per 60 seconds. "
            "Wait a minute before trying again."
        )
    if status_code in (401, 403):
        return (
            f"{message} Check the Client ID in BROKER_API_KEY and your MPIN, and "
            "wait for a fresh TOTP code -- never resubmit a code you already used. "
            "5 wrong codes in 15 minutes locks token generation for 15 minutes; "
            "if codes keep failing, sync your server clock via NTP (clock drift is "
            "the most common cause)."
        )
    return message
