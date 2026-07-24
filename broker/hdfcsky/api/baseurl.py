# broker/hdfcsky/api/baseurl.py
#
# Central place for HDFC Sky hosts, the auth-header builder and the client-id
# helper.
#
# HDFC Sky auth specifics (from the official docs):
#   - `Authorization: <access_token>` -- NO "Bearer " prefix.
#   - `User-Agent` is MANDATORY on essentially every request; requests without
#     it are rejected.
#   - Most endpoints additionally require the app's `api_key` as a QUERY param
#     (not a header), and account endpoints also want `client_id`.
#
# The `client_id` is the broker's account id (e.g. "S0190007"). It is carried
# in the access token's JWT `sub` claim, so it is derived from the token rather
# than stored separately -- that keeps `authenticate_broker` on the plain
# 2-tuple contract with no token rewriting in blueprints/brlogin.py.

import base64
import binascii
import json
import os
from urllib.parse import urlencode

from utils.logging import get_logger

logger = get_logger(__name__)

# REST hosts -------------------------------------------------------------
ROOT_URL = "https://developer.hdfcsky.com"
# The docs show some samples against the UAT host; production is the default
# here and UAT can be selected with HDFCSKY_UAT=1 for sandbox testing.
UAT_ROOT_URL = "https://uat-developer.hdfcsky.com"

# WebSocket market-data feed (protobuf GenericDTO frames).
WS_MARKET_DATA_PATH = "/wsapi/v1/session"

# Security master: a ZIP containing CompactScrip.csv (public, unauthenticated).
SECURITY_MASTER_URL = "https://hdfcsky.com/api/v1/contract/Compact?info=download"

# The docs' sample User-Agent. HDFC Sky rejects requests without one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def get_root_url():
    """Production host by default; UAT when HDFCSKY_UAT is truthy."""
    if str(os.getenv("HDFCSKY_UAT", "")).strip().lower() in ("1", "true", "yes"):
        return UAT_ROOT_URL
    return ROOT_URL


def get_ws_url(auth_token):
    """WebSocket URL for the market-data feed.

    The feed gateway authenticates purely on the query string: it wants the
    access token as `token` (NOT `access_token`) together with the app
    `api_key`. Verified against the live handshake -- `token` alone, or the
    Authorization header, returns 401 "Full authentication is required"; only
    `token` + `api_key` upgrades (HTTP 101).
    """
    host = get_root_url().replace("https://", "wss://").replace("http://", "ws://")
    query = urlencode({"token": auth_token, "api_key": get_api_key()})
    return f"{host}{WS_MARKET_DATA_PATH}?{query}"


def get_hdfcsky_headers(auth_token, with_json=False):
    """Build the standard HDFC Sky request headers.

    Args:
        auth_token: the access token stored in the Auth table.
        with_json: set True for requests that carry a JSON body.
    """
    headers = {
        "Authorization": auth_token,
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    if with_json:
        headers["Content-Type"] = "application/json"
    return headers


def get_api_key():
    return os.getenv("BROKER_API_KEY")


def _b64url_decode(segment):
    """Decode a base64url JWT segment, restoring stripped '=' padding."""
    padding = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + padding)


def get_client_id(auth_token):
    """Extract the HDFC Sky client id from the access token's JWT `sub` claim.

    The token is NOT verified here -- it was issued to us over TLS and is only
    being read for its account id. Returns "" when the token is not a JWT, in
    which case callers fall back to BROKER_CLIENT_ID from the environment.
    """
    if not auth_token:
        return _client_id_from_env()
    try:
        parts = str(auth_token).split(".")
        if len(parts) >= 2:
            claims = json.loads(_b64url_decode(parts[1]))
            client_id = claims.get("sub") or claims.get("client_id") or ""
            if client_id:
                return str(client_id)
    except (ValueError, binascii.Error, UnicodeDecodeError) as e:
        logger.debug(f"Could not read client id from HDFC Sky token: {e}")
    return _client_id_from_env()


def _client_id_from_env():
    return os.getenv("BROKER_CLIENT_ID", "") or ""


def base_params(auth_token, client_id=True):
    """Query params every authenticated call needs: api_key (+ client_id)."""
    params = {"api_key": get_api_key()}
    if client_id:
        cid = get_client_id(auth_token)
        if cid:
            params["client_id"] = cid
    return params
