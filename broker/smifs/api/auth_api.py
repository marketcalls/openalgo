"""SMIFS God Quant authentication for OpenAlgo.

SMIFS uses a direct-token model: the token is an access token minted in the
SMIFS developer portal, supplied via BROKER_API_SECRET. There is no OAuth
redirect.
"""
import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger
from broker.smifs.api.baseurl import get_url

logger = get_logger(__name__)


def authenticate_broker(code):
    """Called with the callback `code` (here the literal 'smifs').

    Returns (auth_token, error_message). The token comes from BROKER_API_SECRET,
    which the operator sets to a token minted in the SMIFS developer portal.
    """
    token = os.getenv("BROKER_API_SECRET", "").strip()
    if not token:
        return None, "BROKER_API_SECRET is not set; mint a token in the SMIFS developer portal"
    ok, err = test_auth_token(token)
    if not ok:
        return None, err
    return token, None


def test_auth_token(auth_token):
    """True when the token can read the account (used at login and on refresh)."""
    try:
        client = get_httpx_client()
        r = client.get(get_url("/v1/funds/limits"),
                       headers={"access-token": auth_token})
        if r.status_code == 200:
            return True, None
        if r.status_code in (401, 403):
            return False, "the SMIFS token is invalid or expired; mint a fresh one in the portal"
        return False, f"SMIFS returned HTTP {r.status_code}"
    except Exception as e:  # noqa: BLE001
        logger.error(f"SMIFS auth check failed: {e}")
        return False, f"could not reach SMIFS: {e}"
