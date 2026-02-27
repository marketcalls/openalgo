"""
Shared utilities for Zerodha broker integration.

This module provides common helper functions used across the Zerodha
streaming adapter, data module, and other Zerodha-specific components.
"""

import os
import threading
import time

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Enctoken validation cache
# ---------------------------------------------------------------------------
# Calling the Zerodha OMS profile endpoint on every data request is wasteful.
# We cache the validation result for ZERODHA_ENCTOKEN_CACHE_TTL seconds
# (default: 300s / 5 minutes). If the enctoken expires mid-session the
# WebSocket adapter's on_auth_failure callback handles that case separately.
# ---------------------------------------------------------------------------
_enctoken_cache_lock = threading.Lock()
_enctoken_cache: dict = {
    "valid": False,
    "enctoken": None,
    "user_id": None,
    "expires_at": 0.0,
}


def validate_enctoken(enctoken: str, zerodha_user_id: str) -> bool:
    """
    Validate enctoken by calling the Zerodha OMS profile endpoint.

    Results are cached in memory for ZERODHA_ENCTOKEN_CACHE_TTL seconds
    (default: 300s) to avoid a live HTTP round-trip on every API call.
    The cache is invalidated automatically when the enctoken or user_id
    changes, or when the TTL expires.

    Args:
        enctoken: The enctoken value from ZERODHA_ENCTOKEN env variable
        zerodha_user_id: The Zerodha user ID from ZERODHA_USER_ID env variable

    Returns:
        True if enctoken is valid, False otherwise
    """
    ttl = int(os.getenv("ZERODHA_ENCTOKEN_CACHE_TTL", "300"))
    now = time.monotonic()

    with _enctoken_cache_lock:
        # Return cached result if still fresh and for the same credentials
        if (
            _enctoken_cache["enctoken"] == enctoken
            and _enctoken_cache["user_id"] == zerodha_user_id
            and now < _enctoken_cache["expires_at"]
        ):
            logger.debug(
                f"✅ enctoken cache hit for user {zerodha_user_id} "
                f"(expires in {_enctoken_cache['expires_at'] - now:.0f}s)"
            )
            return _enctoken_cache["valid"]

    # Cache miss or expired — make a live validation request
    url = "https://kite.zerodha.com/oms/user/profile/full"
    headers = {
        "Authorization": f"enctoken {enctoken}",
        "X-Kite-Version": "3.0.0",
        "X-Kite-Userid": zerodha_user_id,
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/142.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
    }
    try:
        client = get_httpx_client()
        response = client.get(url, headers=headers)

        is_valid = response.status_code == 200

        if is_valid:
            logger.info(f"✅ enctoken validated successfully for user {zerodha_user_id}")
        else:
            logger.warning(
                f"⚠️ enctoken validation failed (HTTP {response.status_code}) "
                f"for user {zerodha_user_id}. Will fall back to api_key + access_token method."
            )

    except Exception as e:
        logger.warning(
            f"⚠️ enctoken validation error: {e}. "
            f"Will fall back to api_key + access_token method."
        )
        is_valid = False

    # Update cache (valid or invalid — cache negative results too to avoid
    # hammering the profile endpoint when the token is genuinely expired)
    with _enctoken_cache_lock:
        _enctoken_cache["valid"] = is_valid
        _enctoken_cache["enctoken"] = enctoken
        _enctoken_cache["user_id"] = zerodha_user_id
        _enctoken_cache["expires_at"] = time.monotonic() + ttl

    return is_valid
