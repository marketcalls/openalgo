"""Pocketful login: the OAuth 2.0 code exchange and the trading account behind it.

Where each piece comes from (checked 2026-11-17):

- Host and sign-in address. The docs' login page says a custom redirect URL
  is handled "on your server using OAuth 2.0 APIs" and that every API call
  goes to https://algo.pocketful.in, but names no OAuth endpoint; neither SDK
  (Python 0.1.2, JavaScript) nor the Postman collection has one, they sign in
  with a password instead (/api/v3/user/login). Pocketful's own developer
  portal (api.pocketful.in, the "Click here to generate" button) opens
  ``https://algo.pocketful.in/oauth2/auth`` with ``client_id``,
  ``response_type=code``, ``scope=orders holdings`` and ``state``, and its
  redirect page reads ``code``, ``state`` and ``scope`` back. The portal spells
  the redirect parameter ``redirect-uri``, which the OAuth server ignores
  (it then uses the app's registered address); OpenAlgo sends the standard
  ``redirect_uri`` (RFC 6749 4.1.1), as it always has, so the exchange below
  must repeat it.
- Code exchange. ``POST /oauth2/token`` on the same host answers as an OAuth
  2.0 token endpoint (an empty POST gets ``{"error": "invalid_request", ...}``).
  The request is the one this plugin sent to trade.pocketful.in before: HTTP
  Basic with the App ID and App Secret (RFC 6749 2.3.1) and the form
  ``grant_type=authorization_code``, ``code``, ``redirect_uri`` (4.1.3). A
  refusal carries ``error`` and ``error_description`` (5.2).
- Trading account. Every Pocketful endpoint takes the trading client id and
  the profile endpoint itself needs it, so it cannot tell us which account a
  token is for. ``GET /api/v1/user/trading_info`` (``data.client_id``) is what
  this plugin read on the old host, and the new host routes it. It is in no
  current doc or SDK. The access token is not read as a JWT for the id: the
  SDK sample tokens that carry a ``client_id`` claim come from the password
  login, and an unchecked claim is a label anyone can write.

The stored token is ``<client_id>:::<access_token>`` (baseurl.pack_token). The
keys and the redirect address are read when called: a login's callback runs
with its own broker's keys staged for that request (utils/broker_keys.py).
Nothing here logs the code, the App Secret or the access token.
"""

import base64
import os
import re
from urllib.parse import urlencode

from broker.pocketful.api import baseurl
from utils.config import get_broker_api_key, get_broker_api_secret
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

AUTHORIZE_URL = f"{baseurl.BASE_URL}/oauth2/auth"
TOKEN_URL = f"{baseurl.BASE_URL}/oauth2/token"
TRADING_INFO_PATH = "/api/v1/user/trading_info"
#: The scope Pocketful's own portal asks for, and this plugin always has.
SCOPE = "orders holdings"

#: A trading client id as the docs and SDKs show them (DEMO1, YA0002, SB3179).
#: It is stored before the access token and goes into request paths, so an
#: answer outside this shape is refused rather than stored.
_CLIENT_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")

MISSING_CODE = (
    "Pocketful did not send a login code back to OpenAlgo. Start the Pocketful login "
    "again from Select Broker."
)
MISSING_KEYS = (
    "The App ID or App Secret for Pocketful is missing. Add both on Broker "
    "Configuration, then log in again."
)
UNREACHABLE = (
    "OpenAlgo could not reach Pocketful to finish the login. Check this server's "
    "internet connection, then start the Pocketful login again."
)
KEYS_REFUSED = (
    "Pocketful did not accept the App ID or App Secret. Check both against your app "
    "on the Pocketful API portal, update them on Broker Configuration, then log in again."
)
REDIRECT_MISMATCH = (
    "Pocketful refused the login because the redirect URL does not match your "
    "Pocketful app. Register the redirect URL shown on Broker Configuration as your "
    "app's custom redirect URL on the Pocketful API portal, then log in again."
)
CODE_REFUSED = (
    "The Pocketful login code has expired or was already used. Start the Pocketful login again."
)
BROKER_UNAVAILABLE = (
    "Pocketful could not finish the login just now. Wait a minute, then start the "
    "Pocketful login again."
)
LOGIN_REFUSED = (
    "Pocketful did not complete the login. Start the Pocketful login again. If it "
    "fails again, check your app on the Pocketful API portal."
)
NO_SESSION = (
    "Pocketful accepted the login but sent no session back. Start the Pocketful login again."
)
NO_ACCOUNT = (
    "Pocketful signed you in but did not say which trading account the login is for, "
    "so OpenAlgo cannot use it. Start the Pocketful login again."
)
LOGIN_CANCELLED = (
    "The Pocketful login was cancelled or not approved. Start the Pocketful login "
    "again and approve access."
)
SCOPE_REFUSED = (
    "Pocketful did not allow the access OpenAlgo asks for at login, so the login "
    "stopped. Your keys are not the cause; report this to the OpenAlgo team."
)


def _short(value, limit=300):
    """A broker-supplied value as it may go into one log line."""
    return str(value or "")[:limit]


def _failure(message):
    return None, None, None, message


def callback_refusal(error, description=None):
    """The sentence for a sign-in Pocketful sent back with an error instead of a code.

    RFC 6749 4.1.2.1: the redirect carries ``error`` (``access_denied`` when the
    trader declines or the sign-in is rejected) and ``error_description``. The
    broker's own words go to the log only.
    """
    logger.warning(
        "Pocketful sign-in came back without a code: error=%r description=%r",
        _short(error, 64),
        _short(description),
    )
    if error == "access_denied":
        return LOGIN_CANCELLED
    if error == "invalid_scope":
        return SCOPE_REFUSED
    return LOGIN_REFUSED


def _token_refusal(status_code, body):
    """The sentence for a token endpoint refusal (RFC 6749 5.2)."""
    body = body if isinstance(body, dict) else {}
    error = _short(body.get("error"), 64)
    # error_description carries the server's hint after its description; an
    # older format sends the hint as error_hint. The description of every
    # invalid_grant mentions the "redirection URI", so only the hint's own
    # "redirect_uri" names a mismatch.
    detail = f"{_short(body.get('error_description'))} {_short(body.get('error_hint'))}"
    logger.warning(
        "Pocketful refused the login code exchange: status=%s error=%r detail=%r",
        status_code,
        error,
        detail.strip(),
    )
    if error == "invalid_client" or status_code == 401:
        return KEYS_REFUSED
    if "redirect_uri" in detail.lower():
        return REDIRECT_MISMATCH
    if error == "invalid_grant":
        return CODE_REFUSED
    if status_code >= 500:
        return BROKER_UNAVAILABLE
    return LOGIN_REFUSED


def _redirect_uri():
    """The redirect address the sign-in was started with.

    The sign-in address is built from the same staged keys
    (utils/broker_login.login_url), so the exchange repeats it exactly.
    """
    redirect = (os.getenv("REDIRECT_URL") or "").strip()
    if redirect:
        return redirect
    from utils.broker_keys import default_redirect_url

    return default_redirect_url(baseurl.BROKER)


def _exchange_code(code, app_id, app_secret):
    """POST the code to the token endpoint. Returns (access_token, None) or (None, message)."""
    credentials = base64.b64encode(f"{app_id}:{app_secret}".encode()).decode()
    headers = {
        "Authorization": f"Basic {credentials}",
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
        "Cache-Control": "no-cache",
    }
    form = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(),
    }
    try:
        response = get_httpx_client().post(
            TOKEN_URL,
            headers=headers,
            content=urlencode(form),
            timeout=baseurl.REQUEST_TIMEOUT,
        )
    except Exception:
        logger.exception("Pocketful login code exchange did not reach Pocketful")
        return None, UNREACHABLE

    try:
        body = response.json()
    except ValueError:
        body = None
    if not 200 <= response.status_code < 300:
        return None, _token_refusal(response.status_code, body)

    access_token = body.get("access_token") if isinstance(body, dict) else None
    if not isinstance(access_token, str) or not access_token.strip():
        logger.warning(
            "Pocketful answered the login code exchange without an access token "
            "(status %s, fields %s)",
            response.status_code,
            sorted(body) if isinstance(body, dict) else "none",
        )
        return None, NO_SESSION
    return access_token.strip(), None


def _trading_client_id(access_token):
    """The trading client id Pocketful reports for an access token. Returns (id, None) or (None, message)."""
    try:
        answer = baseurl.pocketful_request("GET", TRADING_INFO_PATH, access_token)
    except Exception:
        logger.exception("Pocketful account lookup after login did not reach Pocketful")
        return None, UNREACHABLE

    payload = answer.payload if answer.ok else None
    client_id = payload.get("client_id") if isinstance(payload, dict) else None
    client_id = client_id.strip() if isinstance(client_id, str) else ""
    if not _CLIENT_ID.fullmatch(client_id):
        logger.warning(
            "Pocketful did not report a usable trading account after login: status=%s "
            "message=%r account present=%s",
            answer.status_code,
            _short(answer.message),
            bool(client_id),
        )
        return None, NO_ACCOUNT
    return client_id, None


def authenticate_broker(auth_code=None, state=None):
    """Exchange Pocketful's login code for a session and find its trading account.

    The state was matched to the login this browser started before this is
    called (utils/broker_login.has_pending_login) and is used up when the
    login is stored, so it is not checked again here.

    Args:
        auth_code: The ``code`` Pocketful sent back to the callback.
        state: The ``state`` Pocketful sent back (unused here).

    Returns:
        tuple: (auth_token, feed_token, client_id, error_message). On success
        auth_token is ``<client_id>:::<access_token>``, feed_token is None (the
        feed uses the access token) and client_id is the trading account,
        stored as the session's user id. On failure the first three are None
        and error_message is a sentence for the trader.
    """
    code = (auth_code or "").strip()
    if not code:
        return _failure(MISSING_CODE)

    app_id = (get_broker_api_key() or "").strip()
    app_secret = (get_broker_api_secret() or "").strip()
    if not app_id or not app_secret:
        return _failure(MISSING_KEYS)

    access_token, error = _exchange_code(code, app_id, app_secret)
    if error:
        return _failure(error)

    client_id, error = _trading_client_id(access_token)
    if error:
        return _failure(error)

    logger.info("Pocketful login exchanged its code and found the trading account")
    return baseurl.pack_token(client_id, access_token), None, client_id, None
