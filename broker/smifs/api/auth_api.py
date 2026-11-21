"""SMIFS God Quant authentication for OpenAlgo.

SMIFS uses a direct-token model: the token is an access token minted in the
SMIFS developer portal. It is saved in Broker Configuration as the API key
(BROKER_API_KEY); BROKER_API_SECRET is still read for .env installs that
set it there. There is no OAuth redirect.
"""

import os

from broker.smifs.api.baseurl import REQUEST_TIMEOUT, get_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def authenticate_broker(code):
    """Called with the callback `code` (here the literal 'smifs').

    Returns (auth_token, error_message). The token is a token minted in the SMIFS
    developer portal: BROKER_API_KEY, or BROKER_API_SECRET for older .env installs.
    """
    token = (os.getenv("BROKER_API_KEY", "") or os.getenv("BROKER_API_SECRET", "")).strip()
    if not token:
        return None, "no SMIFS access token is saved; mint one in the SMIFS developer portal"
    ok, err = test_auth_token(token)
    if not ok:
        return None, err
    return token, None


def test_auth_token(auth_token):
    """True when the token can read the account (used at login and on refresh)."""
    try:
        client = get_httpx_client()
        r = client.get(
            get_url("/v1/funds/limits"),
            headers={"access-token": auth_token},
            timeout=REQUEST_TIMEOUT,
        )
        if r.status_code == 200:
            return True, None
        if r.status_code in (401, 403):
            return False, "the SMIFS token is invalid or expired; mint a fresh one in the portal"
        return False, f"SMIFS returned HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        logger.error(f"SMIFS auth check failed: {e}")
        return False, f"could not reach SMIFS: {e}"
