# services/tf_cpr_service.py
"""
Narrow-CPR (Central Pivot Range) enrichment for the TradeFinder Intraday
Boost list.

TF's market_pulse feed only carries prev_close (no prev high/low), so CPR
width can't be computed from that response alone. Computing it inline on
every /tfmarketpulse poll would mean one broker history call per symbol per
request — history_service.get_history() is rate-limited to 3 req/s, so an
~80-symbol boost list would stall the "always returns immediately" endpoint
for ~27s.

Instead: CPR width is a static daily value, so it's computed once per symbol
per day in a background thread and cached here. attach_cpr() serves whatever
is cached so far — a symbol not yet computed gets cpr_width_pct=None (treated
as "unknown", never as "wide", by callers).
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime, timedelta

from cachetools import TTLCache

from services.history_service import get_history
from utils.logging import get_logger

logger = get_logger(__name__)

# symbol -> (date_str, width_pct, tc, bc). Bounded: see
# services/tf_momentum_setup_service.py's _cache comment for the reasoning.
_cache: TTLCache = TTLCache(maxsize=2000, ttl=86400)
_pending: set[str] = set()
_lock = threading.Lock()


def _row_date(row: dict) -> str:
    """history_service.get_history() (the raw internal path, unlike the SDK's
    .history() used elsewhere in this repo) returns 'timestamp' as a raw Unix
    epoch int/float, not an ISO string — str(ts)[:10] on an epoch int truncates
    the number itself and never matches a YYYY-MM-DD date, so that naive
    approach silently always fails to detect "last row is today"."""
    ts = row.get("timestamp") or row.get("date") or row.get("datetime")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
    return str(ts)[:10]


def _compute_cpr_data(
    symbol: str, exchange: str, auth_token: str, broker: str
) -> tuple[float, float, float] | None:
    """Returns (width_pct, top, bottom) for today's CPR (Pivot/TC/BC from the
    previous day's H/L/C), or None if it can't be computed."""
    end = date.today()
    start = end - timedelta(days=7)  # buffer for weekends/holidays
    try:
        success, data, _status = get_history(
            symbol=symbol,
            exchange=exchange,
            interval="D",
            start_date=start.strftime("%Y-%m-%d"),
            end_date=end.strftime("%Y-%m-%d"),
            auth_token=auth_token,
            broker=broker,
            source="api",
        )
    except Exception as e:
        logger.debug(f"tf_cpr_service: history fetch failed for {symbol}: {e}")
        return None
    if not success:
        return None
    rows = data.get("data") or []
    if len(rows) < 2:
        return None

    today_str = end.strftime("%Y-%m-%d")
    prev = rows[-2] if _row_date(rows[-1]) == today_str else rows[-1]
    try:
        prev_h, prev_l, prev_c = float(prev["high"]), float(prev["low"]), float(prev["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (prev_h and prev_l and prev_c):
        return None

    cp = (prev_h + prev_l + prev_c) / 3
    bc = (prev_h + prev_l) / 2
    tc = (cp - bc) + cp
    bottom, top = (bc, tc) if bc <= tc else (tc, bc)
    if not cp:
        return None
    width_pct = (top - bottom) / cp * 100
    return (width_pct, top, bottom)


def _background_fill(symbols: list[str], exchange: str, auth_token: str, broker: str) -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        for symbol in symbols:
            cpr = _compute_cpr_data(symbol, exchange, auth_token, broker)
            with _lock:
                if cpr is not None:
                    width, top, bottom = cpr
                    _cache[symbol] = (today_str, width, top, bottom)
                _pending.discard(symbol)
    except Exception as e:
        logger.warning(f"tf_cpr_service: background fill error: {e}")
        with _lock:
            for symbol in symbols:
                _pending.discard(symbol)


def ensure_cpr_cache(
    symbols: list[str], auth_token: str, broker: str, exchange: str = "NSE"
) -> None:
    """Non-blocking. Kicks a background thread to fill in symbols missing
    today's CPR width. Safe to call on every /tfmarketpulse poll — symbols
    already cached today or already in flight are skipped, so a steady
    watchlist only triggers work once per day."""
    today_str = date.today().strftime("%Y-%m-%d")
    with _lock:
        todo = [
            s
            for s in symbols
            if s not in _pending and (s not in _cache or _cache[s][0] != today_str)
        ]
        _pending.update(todo)
    if todo:
        threading.Thread(
            target=_background_fill,
            args=(todo, exchange, auth_token, broker),
            daemon=True,
            name="tf-cpr-fill",
        ).start()


def attach_cpr(items: list[dict]) -> list[dict]:
    """Adds 'cpr_width_pct' and 'cpr_bias' to each item in place, from cache.

    cpr_bias is computed from the item's own 'ltp' (already fetched by
    TradeFinder for the boost list, so no extra broker call here) against
    today's cached CPR top/bottom: 'bullish' if ltp is above the zone,
    'bearish' if below, None if inside the zone or CPR not yet cached. This
    is independent of the narrow-width classification - the frontend
    combines "narrow AND bias present" for its "CPR Breakout" filter, so a
    wide-but-broken-out stock and a narrow-but-inside-the-zone stock are both
    still distinguishable from the full breakout setup.
    """
    today_str = date.today().strftime("%Y-%m-%d")
    with _lock:
        for item in items:
            cached = _cache.get(item.get("symbol", ""))
            if not cached or cached[0] != today_str:
                item["cpr_width_pct"] = None
                item["cpr_bias"] = None
                continue
            _, width, top, bottom = cached
            item["cpr_width_pct"] = width
            ltp = item.get("ltp")
            if isinstance(ltp, (int, float)) and ltp > top:
                item["cpr_bias"] = "bullish"
            elif isinstance(ltp, (int, float)) and ltp < bottom:
                item["cpr_bias"] = "bearish"
            else:
                item["cpr_bias"] = None
    return items
