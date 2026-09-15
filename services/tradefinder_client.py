"""
Thin client for tradefinder.in's internal Option Apex money-flow data.

Reuses the SAME auth as services/tradefinder_service.py: the server-side JWT
(strategies/tf_jwt.txt, kept fresh by tf_jwt_keepalive_service.py's 20-minute
scheduler) plus a TOTP `accesstoken` derived from it. Confirmed by hand against
the live endpoint - `Authorization: Bearer <jwt>` alone gets an "INVALID TOKEN"
(AT_ERROR) response; `jwttoken` + `accesstoken` together is what the Option
Apex page's own money_flux calls actually require.

Not a public/documented API - this calls tradefinder.in's own internal
`api_be` surface.
"""

import os

from services.tradefinder_service import TF_JWT_FILE, _get_tf_jwt, _tf_server_time_ms, _tf_totp
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

TF_BASE = os.getenv("TF_BASE", "https://tradefinder.in/api_be")


class TradefinderTokenError(Exception):
    """Raised when strategies/tf_jwt.txt is missing/empty or tradefinder.in rejects it."""


class TradefinderExpiryError(Exception):
    """Raised when the requested script has no expiry of the requested type -
    e.g. Bank Nifty currently has no weekly expiry, only monthly. Not an auth
    problem, so callers must not surface this as a 401."""


def _get(path: str, params: dict) -> dict:
    jwt = _get_tf_jwt()
    if not jwt:
        raise TradefinderTokenError(
            f"No TradeFinder JWT at {TF_JWT_FILE}. The keep-alive scheduler "
            "(services/tf_jwt_keepalive_service.py) refreshes it automatically once "
            "strategies/tf_login_setup.py has been run once to establish the browser session."
        )
    accesstoken = _tf_totp(_tf_server_time_ms())
    client = get_httpx_client()
    response = client.get(
        f"{TF_BASE}{path}",
        params=params,
        headers={"jwttoken": jwt, "accesstoken": accesstoken},
        timeout=10.0,
    )
    if response.status_code == 401:
        raise TradefinderTokenError(
            "tradefinder.in rejected the current TF JWT (expired/invalid). "
            "It should self-heal on the next keep-alive tick (every 20 min); "
            "if it doesn't, check strategies/tf_jwt.txt and the browser profile."
        )
    response.raise_for_status()
    body = response.json()
    if body.get("status") == "ERROR":
        raise TradefinderTokenError(
            f"tradefinder.in error: {body.get('code')} - {body.get('message')}"
        )
    return body


def get_current_expiry(script: str, exp_type: str = "wk") -> str:
    """Resolve the current expiry label (e.g. '08Sep') for a script and expiry type."""
    body = _get("/option-apex/expiry", {"script": script})
    entries = body.get("data", [])
    match = next((e for e in entries if e.get("type") == exp_type), None)
    if not match:
        available = sorted({e.get("type") for e in entries if e.get("type")})
        raise TradefinderExpiryError(
            f"No {exp_type!r} expiry for script={script!r}. Available: {available}"
        )
    return match["exp"]


def get_money_flow_histogram(
    script: str,
    exp: str | None = None,
    exp_type: str = "wk",
    from_ts: int | None = None,
    to_ts: int | None = None,
) -> list[dict]:
    """
    Fetch tradefinder's own per-candle net options money-flow series.

    `exp`/`exp_type` must match what the chart's expiry selector is showing -
    tradefinder's histogram is per-expiry, so a mismatched expiry silently
    returns a real but wrong-context series, not an error. `from_ts`/`to_ts`
    (unix seconds) clip the result to the chart's visible window; tradefinder's
    endpoint has no such params and always returns the full session.

    Returns a list of {"time": <unix seconds>, "value": <float>} points,
    passed through unmodified - no recomputation, so values match
    tradefinder.in's own dashboard exactly.
    """
    exp = exp or get_current_expiry(script, exp_type)
    body = _get(
        "/money_flux/op_histogram",
        {"script": script, "exp": exp, "exp_type": exp_type},
    )
    rows = body.get("payload", {}).get("data", [])
    points = [
        {"time": row[0], "value": row[2]} for row in rows if isinstance(row, list) and len(row) == 3
    ]
    if from_ts is not None:
        points = [p for p in points if p["time"] >= from_ts]
    if to_ts is not None:
        points = [p for p in points if p["time"] <= to_ts]
    return points
