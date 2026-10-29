"""Sahi login: exchange the API key and secret for the day's access token.

Sahi has no redirect and no TOTP. The trader creates an API key in the Sahi
web app (key id ``pk_...``, secret ``sahi_sk_...``), approves it once per
trading day in the API Dashboard, and the token endpoint on the auth host
mints a Bearer token valid until the next 06:00 IST boundary
(broker-api-docs/sahi-api-docs, Authentication).

    POST https://apis.sahi.com/api/v1/apikeys/token
    {"key_id": "pk_...", "secret": "sahi_sk_..."}
    -> {"access_token": "...", "token_type": "Bearer", "expires_in": 65275,
        "expires_at": "...T06:00:00+05:30", "scope": "orders.write ..."}

BROKER_API_KEY holds the key id and BROKER_API_SECRET the secret.
"""

import os

from broker.sahi.api.baseurl import AUTH_BASE_URL, USER_AGENT
from broker.sahi.api.rate_limiter import sahi_request
from utils.broker_backpressure import BROKER_BUSY_MESSAGE, BrokerBusyError
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

TOKEN_PATH = "/api/v1/apikeys/token"


def _login_error(status_code, body):
    """A login failure in words a trader can act on.

    The auth host answers with {"code", "message"} where code is PascalCase:
    InvalidRequest (400), Unauthorized or Locked (401), Forbidden (403, key not
    approved today) and TooManyRequests (429).
    """
    code = body.get("code") if isinstance(body, dict) else None
    reason = body.get("message") if isinstance(body, dict) else None

    if status_code == 403 or code == "Forbidden":
        return (
            "Sahi did not issue an access token because the API key is not approved for today. "
            "Open Sahi web, go to Profile, API Dashboard, and click Approve on the key, then log in again."
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
        return "Sahi is limiting login attempts. Wait a minute, then log in again."
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
    secret = (os.getenv("BROKER_API_SECRET") or "").strip()
    if not key_id or not secret:
        return None, (
            "Sahi needs BROKER_API_KEY (the API key id, pk_...) and BROKER_API_SECRET "
            "(the API secret, sahi_sk_...). Add both in your OpenAlgo settings."
        )

    client = get_httpx_client()
    try:
        response = sahi_request(
            client,
            "POST",
            f"{AUTH_BASE_URL}{TOKEN_PATH}",
            "auth",
            json={"key_id": key_id, "secret": secret},
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
            f"Sahi access token issued, expires at {body.get('expires_at')}, scopes: {body.get('scope')}"
        )
        return body["access_token"], None

    logger.error(
        f"Sahi login refused: HTTP {response.status_code}, code={body.get('code') if isinstance(body, dict) else None}, "
        f"message={body.get('message') if isinstance(body, dict) else None}"
    )
    return None, _login_error(response.status_code, body)
