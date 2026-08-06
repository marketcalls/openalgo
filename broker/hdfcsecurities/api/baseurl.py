# broker/hdfcsecurities/api/baseurl.py
#
# Central place for HDFC Securities (InvestRight) hosts, the auth-header
# builder and the client-id helper.
#
# InvestRight auth specifics (from the official docs):
#   - `Authorization: <access_token>` -- NO "Bearer " prefix.
#   - `User-Agent` is MANDATORY on essentially every request; requests without
#     it are rejected.
#   - Every authenticated endpoint additionally requires the app's `api_key` as
#     a QUERY param (not a header).
#
# InvestRight and HDFC Sky are two different products from the same house that
# share this gateway design and the GenericDTO market-data proto, but they are
# separate hosts, separate apps and separate credentials. Nothing here imports
# from broker.hdfcsky.
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

# REST host ---------------------------------------------------------------
ROOT_URL = "https://developer.hdfcsec.com"

# WebSocket market-data feed (protobuf GenericDTO frames).
WS_MARKET_DATA_PATH = "/wsapi/v1/session"

# Security master: a plain CSV (public, unauthenticated -- no api_key, no
# Authorization header, no User-Agent needed).
SECURITY_MASTER_URL = f"{ROOT_URL}/oapi/v1/security-master"

# The docs' sample User-Agent. InvestRight rejects requests without one.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
)


def get_root_url():
    return ROOT_URL


def get_ws_url(auth_token):
    """WebSocket URL for the market-data feed.

    The feed gateway authenticates on the query string: the access token as
    `token` (NOT `access_token`) together with the app `api_key`, matching the
    sibling InvestRight/Sky gateway.
    """
    host = get_root_url().replace("https://", "wss://").replace("http://", "ws://")
    query = urlencode({"token": auth_token, "api_key": get_api_key()})
    return f"{host}{WS_MARKET_DATA_PATH}?{query}"


def get_hdfcsecurities_headers(auth_token, with_json=False):
    """Build the standard InvestRight request headers.

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
    """Extract the InvestRight client id from the access token's JWT `sub` claim.

    The token is NOT verified here -- it was issued to us over TLS and is only
    being read for its account id. Returns the BROKER_CLIENT_ID fallback when
    the token is not a JWT.
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
        logger.debug(f"Could not read client id from HDFC Securities token: {e}")
    return _client_id_from_env()


def _client_id_from_env():
    return os.getenv("BROKER_CLIENT_ID", "") or ""


def base_params():
    """Query params every authenticated call needs.

    InvestRight only ever documents `api_key` here -- unlike HDFC Sky, no
    endpoint takes `client_id` as a query param (the account is implied by the
    access token).
    """
    return {"api_key": get_api_key()}
