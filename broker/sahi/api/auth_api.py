"""Sahi login: exchange the API key and secret for the day's access token.

Sahi has no redirect. The trader creates an API key in the Sahi web app (key
id ``pk_...``, secret ``sahi_sk_...``) and the token endpoint on the auth host
mints a Bearer token valid until the next 06:00 IST boundary
(broker-api-docs/sahi-api-docs, Authentication).

    POST https://apis.sahi.com/api/v1/apikeys/token
    {"key_id": "pk_...", "secret": "sahi_sk_...", "totp": "042917"}
    -> {"access_token": "...", "token_type": "Bearer", "expires_in": 65275,
        "expires_at": "...T06:00:00+05:30", "scope": "orders.write ..."}

A key is one of two types, fixed when it is created:

    Regular  approved by clicking Approve in the API Dashboard each trading
             day; the mint sends no ``totp`` (a Regular key with one is refused)
    TOTP     the first correct authenticator code of the day approves it; every
             mint must carry the current 6-digit code in ``totp``

BROKER_API_KEY holds the key id. BROKER_API_SECRET holds the secret, and for a
TOTP key the TOTP secret the dashboard showed at setup after ``:::``
(``sahi_sk_...:::JBSWY3DPEHPK3PXP``), the same ``:::`` joining other brokers
use for a second value. The code is worked out here at each login, so a TOTP
key logs in with no daily click, which is what Sahi built the key type for.
"""

import base64
import binascii
import hashlib
import hmac
import os
import struct
import time
from datetime import UTC, datetime, timezone

from broker.sahi.api.baseurl import AUTH_BASE_URL, USER_AGENT
from broker.sahi.api.rate_limiter import sahi_request
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

TOKEN_PATH = "/api/v1/apikeys/token"

# RFC 6238 as Sahi uses it: the dashboard's TOTP secret with no other settings,
# that is HMAC-SHA1, 30-second steps and 6 digits.
TOTP_STEP_SECONDS = 30
TOTP_DIGITS = 6
SECRET_SEPARATOR = ":::"


class TotpSecretError(ValueError):
    """The TOTP secret is not one an authenticator app could read."""


def split_secret(raw):
    """(api_secret, totp_secret or None) from BROKER_API_SECRET."""
    api_secret, sep, totp_secret = (raw or "").strip().partition(SECRET_SEPARATOR)
    totp_secret = totp_secret.strip()
    return api_secret.strip(), (totp_secret if sep and totp_secret else None)


def totp_code(totp_secret, now=None):
    """The current 6-digit code for a base32 TOTP secret, as a string.

    Spaces, dashes and lower case are allowed, as authenticator apps show and
    accept the secret that way; missing base32 padding is added.

    Raises:
        TotpSecretError: The secret is not base32.
    """
    cleaned = "".join(totp_secret.split()).replace("-", "").upper()
    cleaned += "=" * (-len(cleaned) % 8)
    try:
        key = base64.b32decode(cleaned)
    except (binascii.Error, ValueError) as e:
        raise TotpSecretError(str(e)) from e
    if not key:
        raise TotpSecretError("empty secret")
    counter = int((time.time() if now is None else now) // TOTP_STEP_SECONDS)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


def _clock_drift_seconds(body):
    """This computer's clock minus Sahi's, from an InvalidTotp reply, or None."""
    server_time = body.get("server_time") if isinstance(body, dict) else None
    if not server_time:
        return None
    try:
        server = datetime.fromisoformat(str(server_time).replace("Z", "+00:00"))
    except ValueError:
        return None
    if server.tzinfo is None:
        server = server.replace(tzinfo=UTC)
    return round(time.time() - server.timestamp())


def _login_error(status_code, body):
    """A login failure in words a trader can act on.

    The auth host answers with {"code", "message"} where code is PascalCase:
    InvalidRequest (400), Unauthorized, InvalidTotp or Locked (401), Forbidden
    (403: a Regular key not approved today, or API keys not enabled for the
    account yet) and TooManyRequests (429, also after too many wrong codes).
    """
    code = body.get("code") if isinstance(body, dict) else None
    reason = body.get("message") if isinstance(body, dict) else None

    if code == "InvalidTotp":
        drift = _clock_drift_seconds(body)
        message = (
            "Sahi did not accept the TOTP code worked out from the TOTP secret saved after ::: "
            "in BROKER_API_SECRET. Check that it is the TOTP secret Sahi showed when the key "
            "was set up"
        )
        if drift is not None and abs(drift) > TOTP_STEP_SECONDS:
            return (
                f"{message}. This computer's clock is {abs(drift)} seconds "
                f"{'ahead of' if drift > 0 else 'behind'} Sahi's: set it to update "
                "automatically, then log in again."
            )
        return message + ", and that this computer's clock is set automatically."
    if status_code == 403 or code == "Forbidden":
        return (
            "Sahi did not issue an access token. Either the API key is not approved for today "
            "(open Sahi web, go to Profile, API Dashboard, and click Approve on the key), or API "
            "keys are not enabled for your Sahi account yet (contact Sahi). Then log in again. "
            "A TOTP key needs no Approve: add its TOTP secret after ::: in BROKER_API_SECRET."
        )
    if status_code == 400 and code == "InvalidRequest":
        return (
            "Sahi refused the login request"
            + (f": {reason}" if reason else "")
            + ". A TOTP key needs its TOTP secret after ::: in BROKER_API_SECRET; a Regular key "
            "must have nothing after the secret."
        )
    if code == "Locked":
        return (
            "Sahi reports that your account is frozen or locked. Contact Sahi support to unlock it."
        )
    if status_code == 401:
        return (
            "Sahi did not accept the API key and secret. Check BROKER_API_KEY (the key id starting "
            "with pk_) and BROKER_API_SECRET (the secret starting with sahi_sk_), and that the key "
            "has not been deleted in the Sahi API Dashboard."
        )
    if status_code == 429:
        return (
            "Sahi is limiting login attempts, which also happens after several wrong TOTP "
            "codes. Wait a minute, then log in again."
        )
    if status_code is not None and status_code >= 500:
        return "Sahi's login service is not responding right now. Try again in a few minutes."
    message = "Sahi did not issue an access token"
    if reason:
        message += f": {reason}"
    return message + ". Check the API key and secret in your OpenAlgo settings."


def authenticate_broker(code=None):
    """Mint the day's Sahi access token from the API key and secret.

    Args:
        code: Unused. The login route passes a placeholder; the credentials come
            from BROKER_API_KEY and BROKER_API_SECRET.

    Returns:
        tuple: (access_token, None) on success, (None, error_message) on failure.
    """
    key_id = (os.getenv("BROKER_API_KEY") or "").strip()
    secret, totp_secret = split_secret(os.getenv("BROKER_API_SECRET"))
    if not key_id or not secret:
        return None, (
            "Sahi needs BROKER_API_KEY (the API key id, pk_...) and BROKER_API_SECRET "
            "(the API secret, sahi_sk_...). Add both in your OpenAlgo settings."
        )

    payload = {"key_id": key_id, "secret": secret}
    if totp_secret:
        try:
            payload["totp"] = totp_code(totp_secret)
        except TotpSecretError:
            logger.warning("Sahi TOTP secret in BROKER_API_SECRET is not base32")
            return None, (
                "The TOTP secret after ::: in BROKER_API_SECRET is not a valid authenticator "
                "secret. Copy the TOTP secret exactly as Sahi showed it when the key was set up."
            )

    client = get_httpx_client()
    try:
        response = sahi_request(
            client,
            "POST",
            f"{AUTH_BASE_URL}{TOKEN_PATH}",
            "auth",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            },
            timeout=30,
        )
    except BrokerBusyError as e:
        logger.warning(f"Sahi login not sent, rate limit queue full: {e}")
        return None, str(e) or BROKER_BUSY_MESSAGE
    except Exception:
        logger.exception("Sahi login request failed")
        return None, "Could not reach Sahi to log in. Check your internet connection and try again."

    try:
        body = response.json()
    except ValueError:
        body = {}

    if response.status_code == 200 and isinstance(body, dict) and body.get("access_token"):
        logger.info(
            f"Sahi access token issued ({'TOTP' if totp_secret else 'Regular'} key), "
            f"expires at {body.get('expires_at')}, scopes: {body.get('scope')}"
        )
        return body["access_token"], None

    logger.error(
        f"Sahi login refused: HTTP {response.status_code}, code={body.get('code') if isinstance(body, dict) else None}, "
        f"message={body.get('message') if isinstance(body, dict) else None}, "
        f"server_time={body.get('server_time') if isinstance(body, dict) else None}"
    )
    return None, _login_error(response.status_code, body)
