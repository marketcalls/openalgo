"""TradeSmart (Noren v2) authentication.

OAuth-style flow:
  1. The user logs in on the TradeSmart portal and is redirected back to the
     OpenAlgo callback with a ``code`` query param.
  2. We build ``checksum = SHA-256(api_key + secret_key + code)`` and POST it to
     ``/GenAcsTok`` to receive an ``access_token`` valid for one trading day.

Note the checksum field order is ``api_key + secret_key + code`` per the
TradeSmart v2 docs (Quick start step 4) — this differs from flattrade's
``api_key + code + api_secret`` order, so do NOT copy flattrade's hash verbatim.
"""

import hashlib
import json
import os

from broker.tradesmart.api.baseurl import GENACSTOK_URL, get_api_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def sha256_hash(text):
    """Return the hex SHA-256 digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def authenticate_broker(code, password=None, totp_code=None):
    """Exchange the login ``code`` for a TradeSmart access token.

    Args:
        code: authorization code received on the redirect URL after login.

    Returns:
        Tuple ``(access_token, error_message)`` — success is ``(token, None)``,
        failure is ``(None, "message")``.
    """
    try:
        api_key = get_api_key()
        secret_key = os.getenv("BROKER_API_SECRET")

        if not api_key or not secret_key:
            return None, "BROKER_API_KEY / BROKER_API_SECRET not configured"
        if not code:
            return None, "Missing login code from TradeSmart callback"

        # checksum = SHA-256(api_key + secret_key + code)  [TradeSmart v2 docs]
        checksum = sha256_hash(f"{api_key}{secret_key}{code}")

        jdata = {"code": code, "checksum": checksum}
        payload = "jData=" + json.dumps(jdata)
        headers = {"Content-Type": "text/plain"}  # GenAcsTok needs no Bearer

        client = get_httpx_client()
        response = client.post(GENACSTOK_URL, content=payload, headers=headers)

        logger.debug(f"GenAcsTok status: {response.status_code}")

        try:
            response_data = response.json()
        except json.JSONDecodeError:
            return None, f"Invalid response from TradeSmart: {response.text}"

        if response_data.get("stat") == "Ok":
            # The v2 token field is documented as access_token; accept the common
            # Noren spellings as a fallback so a minor key change doesn't break login.
            token = (
                response_data.get("access_token")
                or response_data.get("accesstoken")
                or response_data.get("token")
                or response_data.get("susertoken")
            )
            if not token:
                return None, "Authentication succeeded but no access token in response"

            # Capture the client/account id when GenAcsTok returns it, and store
            # the token as the composite "<uid>:::<access_token>" so downstream
            # calls can populate the jData uid without it being in the env. If the
            # response carries no uid, store the bare token (downstream then needs
            # BROKER_API_KEY set as CLIENT_ID:::API_KEY).
            uid = (
                response_data.get("actid")
                or response_data.get("uid")
                or response_data.get("accountId")
                or response_data.get("actId")
                or response_data.get("client_id")
                or response_data.get("uname")
            )
            if uid:
                return f"{uid}:::{token}", None
            return token, None

        error_msg = response_data.get("emsg", "Authentication failed")
        logger.error(f"TradeSmart auth error: {error_msg}")
        return None, error_msg

    except Exception as e:
        logger.exception("TradeSmart authentication exception")
        return None, f"An exception occurred: {str(e)}"
