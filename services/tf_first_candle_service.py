# services/tf_first_candle_service.py
"""
First-candle "shock" enrichment for the TradeFinder Intraday Boost list.

Lets the frontend filter out stocks that already made a big move in the
day's opening 5-minute candle (09:15-09:20) before the boost list even
surfaced them. TF's market_pulse feed carries no OHLC at all, so this can't
be derived from that response.

Same rate-limit problem as tf_cpr_service.py: computing this inline on every
/tfmarketpulse poll would mean one broker history call per symbol per
request. Since the first candle is a fixed once-per-day value (immutable
once 09:20 has passed), it's computed once per symbol per day in a
background thread and cached here, same as tf_cpr_service. attach_first_candle()
serves whatever is cached so far - a symbol not yet computed (including
"market hasn't opened yet" / "candle hasn't closed yet") gets
first_candle_range_pct=None, never treated as "not shocked".
"""

from __future__ import annotations

import threading
from datetime import UTC, date, datetime

from services.history_service import get_history
from utils.logging import get_logger

logger = get_logger(__name__)

_cache: dict[str, tuple[str, float]] = {}   # symbol -> (date_str, range_pct)
_pending: set[str] = set()
_lock = threading.Lock()


def _row_date(row: dict) -> str:
    """history_service.get_history() (the raw internal path, unlike the SDK's
    .history() used elsewhere in this repo) returns 'timestamp' as a raw Unix
    epoch int/float, not an ISO string — str(ts)[:10] on an epoch int truncates
    the number itself and never matches a YYYY-MM-DD date, so that naive
    approach silently always fails to detect "first row is today"."""
    ts = row.get("timestamp") or row.get("date") or row.get("datetime")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
    return str(ts)[:10]


def _compute_first_candle_range_pct(
    symbol: str, exchange: str, auth_token: str, broker: str
) -> float | None:
    """Returns the day's first 5m candle's range as a % of its open
    ((high - low) / open * 100), or None if it can't be computed yet
    (market not open, candle not closed, or the fetch failed)."""
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        success, data, _status = get_history(
            symbol=symbol, exchange=exchange, interval="5m",
            start_date=today_str, end_date=today_str,
            auth_token=auth_token, broker=broker, source="api",
        )
    except Exception as e:
        logger.debug(f"tf_first_candle_service: history fetch failed for {symbol}: {e}")
        return None
    if not success:
        return None
    rows = data.get("data") or []
    if not rows:
        return None

    first = rows[0]
    if _row_date(first) != today_str:
        return None
    try:
        o, h, low = float(first["open"]), float(first["high"]), float(first["low"])
    except (KeyError, TypeError, ValueError):
        return None
    if not o:
        return None

    return (h - low) / o * 100


def _background_fill(symbols: list[str], exchange: str, auth_token: str, broker: str) -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        for symbol in symbols:
            pct = _compute_first_candle_range_pct(symbol, exchange, auth_token, broker)
            with _lock:
                if pct is not None:
                    _cache[symbol] = (today_str, pct)
                _pending.discard(symbol)
    except Exception as e:
        logger.warning(f"tf_first_candle_service: background fill error: {e}")
        with _lock:
            for symbol in symbols:
                _pending.discard(symbol)


def ensure_first_candle_cache(symbols: list[str], auth_token: str, broker: str, exchange: str = "NSE") -> None:
    """Non-blocking. Kicks a background thread to fill in symbols missing
    today's first-candle range. Safe to call on every /tfmarketpulse poll —
    symbols already cached today or already in flight are skipped. Symbols
    queried before the first candle has closed (09:20) fail silently and are
    NOT cached, so they're retried on the next poll instead of getting stuck
    with a stale None for the rest of the day."""
    today_str = date.today().strftime("%Y-%m-%d")
    with _lock:
        todo = [
            s for s in symbols
            if s not in _pending and (s not in _cache or _cache[s][0] != today_str)
        ]
        _pending.update(todo)
    if todo:
        threading.Thread(
            target=_background_fill, args=(todo, exchange, auth_token, broker),
            daemon=True, name="tf-first-candle-fill",
        ).start()


def attach_first_candle(items: list[dict]) -> list[dict]:
    """Adds 'first_candle_range_pct' to each item in place, from cache."""
    today_str = date.today().strftime("%Y-%m-%d")
    with _lock:
        for item in items:
            cached = _cache.get(item.get("symbol", ""))
            if not cached or cached[0] != today_str:
                item["first_candle_range_pct"] = None
                continue
            _, pct = cached
            item["first_candle_range_pct"] = pct
    return items
