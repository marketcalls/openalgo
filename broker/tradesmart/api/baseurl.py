"""TradeSmart (Noren v2) hosts and request helpers.

Centralizes the v2 contract so every api module speaks it the same way:

  * REST root  : https://v2api.tradesmartonline.in/NorenWClientAPIv2
  * WebSocket  : wss://v2api.tradesmartonline.in/NorenWSAPI/
  * Auth model : ``Authorization: Bearer <access_token>`` HTTP header AND a raw
                 ``text/plain`` body of the form ``jData={...}``.

This is the single biggest difference from the classic Noren brokers
(shoonya/flattrade) which append ``&jKey=<token>`` to the body instead of
sending a Bearer header. TradeSmart v2 uses the header and NO jKey.

uid (client/account id) resolution
-----------------------------------
Every jData body needs the client id (``uid``/``actid``). Two supported sources,
in priority order:

  1. The stored auth token is a composite ``<uid>:::<access_token>`` — produced
     by auth_api when /GenAcsTok returns the client id. ``parse_auth`` splits it;
     the Bearer header always uses the bare access token.
  2. Env ``BROKER_API_KEY`` formatted ``<CLIENT_ID>:::<API_KEY>`` (the flattrade
     convention) — used when the token carries no uid.

If neither carries a uid, the whole ``BROKER_API_KEY`` is used as a last resort.
"""

import json
import os

from utils.httpx_client import get_httpx_client

# REST + streaming hosts (TradeSmart Noren v2)
REST_ROOT = "https://v2api.tradesmartonline.in/NorenWClientAPIv2"
WS_URL = "wss://v2api.tradesmartonline.in/NorenWSAPI/"

# OAuth token-exchange endpoint (needs no Bearer header — it mints the token).
GENACSTOK_URL = f"{REST_ROOT}/GenAcsTok"


def parse_auth(auth_token):
    """Split a stored token into ``(uid, bare_access_token)``.

    Returns ``(None, auth_token)`` when the token carries no embedded uid.
    """
    if auth_token and ":::" in auth_token:
        uid, token = auth_token.split(":::", 1)
        return uid, token
    return None, auth_token


def get_api_key():
    """Resolve the raw API key used for the auth checksum.

    Supports both ``<CLIENT_ID>:::<API_KEY>`` and a bare ``<API_KEY>`` env value.
    """
    full_api_key = os.getenv("BROKER_API_KEY", "")
    return full_api_key.split(":::")[1] if ":::" in full_api_key else full_api_key


def resolve_uid(auth_token=None):
    """Resolve the client/account id (uid/actid).

    Priority: composite-token uid -> env ``CLIENT_ID:::API_KEY`` -> bare env value.
    """
    if auth_token and ":::" in auth_token:
        return auth_token.split(":::", 1)[0]
    full_api_key = os.getenv("BROKER_API_KEY", "")
    if ":::" in full_api_key:
        return full_api_key.split(":::")[0]
    return full_api_key


def build_headers(bearer_token):
    """Build the standard authenticated v2 request headers."""
    return {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {bearer_token}",
    }


def post(endpoint, jdata, auth_token, timeout=None):
    """POST a ``jData`` payload to a v2 endpoint with the Bearer header.

    Strips any ``<uid>:::`` prefix from ``auth_token`` before using it as the
    Bearer credential.

    Returns the raw httpx ``Response`` (caller parses ``.json()`` / status).
    """
    _, bearer = parse_auth(auth_token)
    payload = "jData=" + json.dumps(jdata)
    client = get_httpx_client()
    url = f"{REST_ROOT}{endpoint}"
    if timeout is not None:
        return client.post(url, content=payload, headers=build_headers(bearer), timeout=timeout)
    return client.post(url, content=payload, headers=build_headers(bearer))
