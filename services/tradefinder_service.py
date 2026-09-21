# services/tradefinder_service.py
"""
TradeFinder market_pulse client — read-only HTTP client for the three ranked
lists (intraday_boost, breakout_beacon, high_powered_stocks). Ported from
strategies/isi_v56_live_strategy.py's TF auth/fetch logic, keeping all four
per-item fields instead of discarding everything but the score.

Auth: jwttoken (user-pasted, file-backed) + accesstoken (TOTP). Same token
file the ISI strategies already use — get the token: tradefinder.in ->
DevTools -> Application -> Local Storage -> 'lt', then:
echo '<token>' > strategies/tf_jwt.txt
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional

import requests

from utils.logging import get_logger

logger = get_logger(__name__)

TF_BASE = os.getenv("TF_BASE", "https://tradefinder.in/api_be")
TF_SECRET = os.getenv("TF_SECRET", "5ACHPKZUZNTWYPSJXNP7IULMACAM6P6Q")
TF_JWT_TOKEN = os.getenv("TF_JWT_TOKEN", "")

_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TF_JWT_FILE = os.getenv("TF_JWT_FILE", os.path.join(_project_root, "strategies", "tf_jwt.txt"))

# Response keys can vary; fall back through known alternates (matches the
# openalgo-chart TS client's mapRawItems()/fetchMarketPulse() behavior).
_LIST_KEYS = {
    "intraday_boost": ("intraday_boost",),
    "breakout_beacon": ("breakout_beacon", "beacon", "breakout"),
    "high_powered_stocks": ("high_powered_stocks", "high_powered", "powered"),
}


def _get_tf_jwt() -> str:
    """Read JWT fresh on every call (file first, then env fallback) so a manual
    refresh takes effect on the very next tick — no cache, no restart needed."""
    if TF_JWT_FILE and os.path.exists(TF_JWT_FILE):
        try:
            token = open(TF_JWT_FILE).read().strip()
            if token:
                return token
        except Exception:
            pass
    return TF_JWT_TOKEN


def has_tf_jwt() -> bool:
    """Whether a server-side JWT is present at all -- lets a caller whose
    fetch just failed tell "no token to authenticate with" apart from "token
    was fine, the request itself failed" (bad route, network error, TF
    outage), instead of collapsing every failure into one misleading
    "token unavailable or expired" message."""
    return bool(_get_tf_jwt())


def _tf_totp(ts_ms: int, step: int = 30) -> str:
    """RFC 6238 TOTP — HMAC-SHA1, 30s window, 6 digits."""
    counter = int(ts_ms / 1000 / step)
    key = base64.b32decode(TF_SECRET.upper() + "=" * ((8 - len(TF_SECRET) % 8) % 8))
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    code = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)


def _tf_server_time_ms() -> int:
    try:
        r = requests.get(f"{TF_BASE}/servertime", timeout=5)
        return int(r.json()["payload"]["data"])
    except Exception:
        return int(time.time() * 1000)


def _safe_float(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _map_items(raw: list[dict]) -> list[dict]:
    """Symbol->symbol, param_0->ltp, param_1->prev_close, param_2->change_pct,
    param_3->score. Sorted by |score| desc (same convention as the strategy
    and the openalgo-chart TS client's mapRawItems()).

    breakout_beacon uses a different schema per-field (param_2 is a "BULL"/
    "BEAR" sentiment label, not a numeric change_pct; param_0/param_1 aren't
    genuine ltp/prev_close either). Each field is converted independently
    (non-numeric -> 0.0) rather than in one all-or-nothing try/except, so one
    off-schema field (e.g. "BEAR") no longer drops the whole item — matching
    the TS client, which never dropped these rows to begin with."""
    items = []
    for it in raw:
        symbol = it.get("Symbol")
        if not symbol:
            continue
        items.append({
            "symbol": symbol,
            "ltp": _safe_float(it.get("param_0")),
            "prev_close": _safe_float(it.get("param_1")),
            "change_pct": _safe_float(it.get("param_2")),
            "score": _safe_float(it.get("param_3")),
        })
    items.sort(key=lambda x: abs(x["score"]), reverse=True)
    return items


def _on_auth_failure() -> None:
    """A live request just proved the cached token is dead -- possibly before
    its own exp claim says so (TF can revoke the session server-side
    independent of the JWT's stated expiry). Kick an immediate background
    refresh instead of waiting for the next scheduled keepalive tick, which
    is up to 20 minutes away: without this, every TradeFinder call fails for
    that whole window even though the self-heal (headless reload, falling
    back to an automated headed Google re-login) takes well under two
    minutes once it actually starts. Deduped by the keepalive service's own
    lock, so calling this on every failed request during the outage is
    harmless -- it's a no-op once a refresh is already in flight."""
    try:
        from services.tf_jwt_keepalive_service import trigger_refresh_if_needed
        trigger_refresh_if_needed(force=True)
    except Exception:
        logger.exception("Failed to trigger immediate TF JWT refresh after auth failure")


def fetch_market_pulse() -> dict[str, list[dict]] | None:
    """Fetch all three TradeFinder ranked lists in one call. Returns None on
    ANY failure (empty/expired JWT, network error, TF error payload) so the
    caller can skip this tick instead of writing partial/garbage data."""
    jwt = _get_tf_jwt()
    if not jwt:
        logger.warning(f"TF_JWT_TOKEN is empty. Quick fix: echo '<token>' > {TF_JWT_FILE}")
        return None
    totp = _tf_totp(_tf_server_time_ms())
    try:
        r = requests.get(f"{TF_BASE}/data/market_pulse",
                          headers={"jwttoken": jwt, "accesstoken": totp}, timeout=10)
        data = r.json()
    except Exception as e:
        logger.warning(f"TradeFinder market_pulse request failed: {e}")
        return None
    if data.get("status") == "ERROR":
        logger.warning(f"TradeFinder error: {data.get('code')} — {data.get('message')} "
                        f"(JWT expired? paste a fresh token into {TF_JWT_FILE})")
        _on_auth_failure()
        return None
    payload_data = (data.get("payload") or {}).get("data") or {}
    result = {}
    for list_type, alt_keys in _LIST_KEYS.items():
        raw = []
        for key in alt_keys:
            raw = payload_data.get(key)
            if raw:
                break
        result[list_type] = _map_items(raw or [])
    return result


def fetch_sector_scope() -> dict | None:
    """Fetch TradeFinder's sector rfactor index + per-sector stock breakdown.

    TF used to serve this as two separate calls (/data/order/daily-index +
    /data/order/all_sector) authenticated the same way as market_pulse
    (a custom 'jwttoken' header). As of 2026-09, both of those routes 404 —
    verified live against tradefinder.in's own Sector Scope page via a
    Playwright probe of the persisted, already-logged-in browser profile
    (strategies/.tf_browser_profile): TF now serves both halves from a single
    /data/sector_scope endpoint (payload.data.{'daily-index','all_sector'},
    identical shape to the old two responses), and that route only accepts
    the JWT as a standard 'Authorization: Bearer <token>' header — the
    'accesstoken' TOTP header is unchanged, and it's the exact same JWT
    (verified identical claims/allowed_pages to what 'jwttoken' still uses on
    market_pulse, just a fresher mint). market_pulse's legacy header still
    works as of this writing, so it's untouched here — but if it starts
    failing the same way, this is the header style to switch it to as well.
    Returns None on ANY failure (empty/expired JWT, network error, TF error
    payload) — mirrors fetch_market_pulse's all-or-nothing contract so the
    caller can fall back cleanly."""
    jwt = _get_tf_jwt()
    if not jwt:
        logger.warning(f"TF_JWT_TOKEN is empty. Quick fix: echo '<token>' > {TF_JWT_FILE}")
        return None
    totp = _tf_totp(_tf_server_time_ms())
    headers = {"Authorization": f"Bearer {jwt}", "accesstoken": totp}
    try:
        r = requests.get(f"{TF_BASE}/data/sector_scope", headers=headers, timeout=10)
        # A non-2xx response (e.g. TF renaming/removing the route again)
        # returns a plain-text body, not JSON — calling .json() on it raises
        # a cryptic "Extra data" JSONDecodeError that reads identically to an
        # expired token, hiding the real cause. Surface the status/body instead.
        if not r.ok:
            if r.status_code == 401:
                logger.warning(
                    f"TradeFinder sector_scope returned HTTP 401: {r.text[:200]!r} "
                    "— token rejected, triggering an immediate refresh"
                )
                _on_auth_failure()
            else:
                logger.warning(
                    f"TradeFinder sector_scope returned HTTP {r.status_code}: "
                    f"{r.text[:200]!r} — this is a TF-side route change, not a token problem"
                )
            return None
        data = r.json()
    except Exception as e:
        logger.warning(f"TradeFinder sector scope request failed: {e}")
        return None
    if data.get("status") == "ERROR":
        logger.warning(f"TradeFinder sector scope error (JWT expired? paste a fresh token into {TF_JWT_FILE})")
        _on_auth_failure()
        return None
    payload_data = (data.get("payload") or {}).get("data") or {}
    return {
        "index": payload_data.get("daily-index") or [],
        "sectors": payload_data.get("all_sector") or {},
    }
