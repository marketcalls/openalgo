"""
Rate-limited HTTP client wrapper for all Mudrex API calls.

Current limit: 2 req/s (configurable via MUDREX_RATE_LIMIT env var; will
increase to 10/s when Mudrex raises the ceiling).

Uses ``threading.Lock`` + monotonic clock to enforce minimum inter-request
spacing, and applies exponential back-off on HTTP 429 responses.
"""

import os
import random
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from broker.mudrex.api.baseurl import get_auth_headers, get_url
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

_rate_limit: float = float(os.getenv("MUDREX_RATE_LIMIT", "2"))
_min_interval: float = 1.0 / _rate_limit if _rate_limit > 0 else 0.0

_lock = threading.Lock()
_last_call: float = 0.0

_MAX_RETRIES = 3
_RETRY_BASE = 1.0


def _enforce_rate_limit() -> None:
    """Block the calling thread until at least ``_min_interval`` has elapsed."""
    global _last_call
    with _lock:
        now = time.monotonic()
        wait = _min_interval - (now - _last_call)
        if wait > 0:
            logger.debug(f"[Mudrex] Rate limiter sleeping {wait:.3f}s")
            time.sleep(wait)
        _last_call = time.monotonic()


def mudrex_request(
    endpoint: str,
    *,
    method: str = "GET",
    payload: dict | str | None = None,
    params: dict | None = None,
    auth: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Execute a rate-limited request against the Mudrex REST API.

    Args:
        endpoint: API path relative to ``/fapi/v1``, e.g. ``/wallet/funds``.
        method:   HTTP verb (GET, POST, PATCH, DELETE).
        payload:  JSON-serializable body for POST/PATCH/DELETE.
        params:   Query parameters dict (GET only).
        auth:     API secret override (falls back to env).
        timeout:  Per-request timeout in seconds.

    Returns:
        Parsed JSON dict.  On transport/parse errors returns a dict with
        ``"status": "error"`` so callers always receive a dict.
    """
    headers = get_auth_headers(auth)
    url = get_url(endpoint)

    if params:
        url = f"{url}?{urlencode(sorted(params.items()))}"

    body: str | None = None
    if payload is not None:
        import json as _json
        body = payload if isinstance(payload, str) else _json.dumps(payload)

    client = get_httpx_client()
    response: httpx.Response | None = None

    for attempt in range(_MAX_RETRIES + 1):
        _enforce_rate_limit()

        try:
            m = method.upper()
            if m == "GET":
                response = client.get(url, headers=headers, timeout=timeout)
            elif m == "POST":
                response = client.post(url, headers=headers, content=body, timeout=timeout)
            elif m == "PATCH":
                response = client.patch(url, headers=headers, content=body, timeout=timeout)
            elif m == "DELETE":
                response = client.request("DELETE", url, headers=headers, content=body, timeout=timeout)
            else:
                response = client.request(m, url, headers=headers, content=body, timeout=timeout)
        except Exception as exc:
            logger.error(f"[Mudrex] Request error on {endpoint}: {exc}")
            return {"status": "error", "message": str(exc)}

        if response.status_code == 429 and attempt < _MAX_RETRIES:
            retry_after = response.headers.get("Retry-After")
            wait = (
                float(retry_after) if retry_after
                else (_RETRY_BASE * (2 ** attempt)) + random.uniform(0.0, 0.5)
            )
            logger.warning(
                f"[Mudrex] HTTP 429 on {endpoint} (attempt {attempt + 1}/{_MAX_RETRIES}). "
                f"Retrying in {wait:.1f}s"
            )
            time.sleep(wait)
            continue
        break

    if response is None:
        return {"status": "error", "message": "No response received"}

    logger.debug(f"[Mudrex] {method} {endpoint} → HTTP {response.status_code}")

    if not response.text.strip():
        logger.error(f"[Mudrex] Empty response from {endpoint}")
        return {"status": "error", "message": "Empty response"}

    try:
        data = response.json()
    except Exception as exc:
        logger.error(f"[Mudrex] JSON parse error: {exc} — body: {response.text[:300]}")
        return {"status": "error", "message": f"JSON parse error: {exc}"}

    if response.status_code not in (200, 201):
        logger.error(f"[Mudrex] HTTP {response.status_code}: {response.text[:300]}")

    return data
