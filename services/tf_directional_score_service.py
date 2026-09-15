# services/tf_directional_score_service.py
"""
Directional steadiness score enrichment for the TradeFinder Intraday Boost
list.

TF's market_pulse feed carries a proprietary "how hot is this symbol" score
(param_3), which says nothing about *how* the stock got there -- a symbol
that whipsawed up and down all morning before landing near its high ranks
identically to one that has climbed in a straight line since the open. This
computes that missing signal locally from OHLC, using Kaufman's Efficiency
Ratio: net move since the open divided by the total distance the price
actually travelled to get there. 1.0 is a perfectly straight move, values
near 0 are pure chop.

Same rate-limit shape as tf_cpr_service.py/tf_first_candle_service.py
(computing this inline on every poll would mean one broker history call per
symbol per request), but unlike those two -- which are static once-per-day
values -- "steadiness since open" changes as the day's price path grows, so
entries go stale after REFRESH_INTERVAL_SEC and are recomputed rather than
cached for the whole day. attach_directional_score() serves whatever is
cached so far -- a symbol not yet computed (including "market hasn't opened
yet" / fewer than 2 candles so far) gets directional_score=None, never
treated as "choppy."
"""

from __future__ import annotations

import threading
import time
from datetime import UTC, date, datetime

from services.history_service import get_history
from utils.logging import get_logger

logger = get_logger(__name__)

REFRESH_INTERVAL_SEC = 300  # recompute at most once every 5 minutes per symbol

# symbol -> (date_str, computed_at_monotonic, score, direction, reversals)
_cache: dict[str, tuple[str, float, float, str | None, int]] = {}
_pending: set[str] = set()
_lock = threading.Lock()


def _row_date(row: dict) -> str:
    """history_service.get_history() (the raw internal path, unlike the SDK's
    .history() used elsewhere in this repo) returns 'timestamp' as a raw Unix
    epoch int/float, not an ISO string — str(ts)[:10] on an epoch int truncates
    the number itself and never matches a YYYY-MM-DD date, so that naive
    approach silently always fails to detect "row is today"."""
    ts = row.get("timestamp") or row.get("date") or row.get("datetime")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%d")
    return str(ts)[:10]


def compute_efficiency_score(day_open: float, closes: list[float]) -> tuple[float, str | None, int]:
    """Kaufman's Efficiency Ratio applied to a day's candle closes, as a
    0-100 "directional steadiness" score plus direction and reversal count.
    Pure function, no I/O -- separated out so it can be unit-tested without a
    broker connection."""
    path = [day_open, *closes]
    path_length = sum(abs(path[i] - path[i - 1]) for i in range(1, len(path)))
    net_move = closes[-1] - day_open
    score = round(abs(net_move) / path_length * 100, 1) if path_length else 0.0
    direction = "up" if net_move > 0 else "down" if net_move < 0 else None

    reversals = 0
    prev_sign = 0
    for i in range(1, len(path)):
        diff = path[i] - path[i - 1]
        sign = 1 if diff > 0 else -1 if diff < 0 else 0
        if sign and prev_sign and sign != prev_sign:
            reversals += 1
        if sign:
            prev_sign = sign

    return score, direction, reversals


def _compute_directional_score(
    symbol: str, exchange: str, auth_token: str, broker: str
) -> tuple[float, str | None, int] | None:
    """Returns (score, direction, reversals) for today's price path since the
    open, or None if it can't be computed yet (market not open, fewer than 2
    candles so far, or the fetch failed)."""
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        success, data, _status = get_history(
            symbol=symbol, exchange=exchange, interval="5m",
            start_date=today_str, end_date=today_str,
            auth_token=auth_token, broker=broker, source="api",
        )
    except Exception as e:
        logger.debug(f"tf_directional_score_service: history fetch failed for {symbol}: {e}")
        return None
    if not success:
        return None
    rows = [r for r in (data.get("data") or []) if _row_date(r) == today_str]
    if len(rows) < 2:
        return None

    try:
        day_open = float(rows[0]["open"])
        closes = [float(r["close"]) for r in rows]
    except (KeyError, TypeError, ValueError):
        return None
    if not day_open:
        return None

    return compute_efficiency_score(day_open, closes)


def _background_fill(symbols: list[str], exchange: str, auth_token: str, broker: str) -> None:
    today_str = date.today().strftime("%Y-%m-%d")
    try:
        for symbol in symbols:
            result = _compute_directional_score(symbol, exchange, auth_token, broker)
            with _lock:
                if result is not None:
                    score, direction, reversals = result
                    _cache[symbol] = (today_str, time.monotonic(), score, direction, reversals)
                _pending.discard(symbol)
    except Exception as e:
        logger.warning(f"tf_directional_score_service: background fill error: {e}")
        with _lock:
            for symbol in symbols:
                _pending.discard(symbol)


def ensure_directional_score_cache(
    symbols: list[str], auth_token: str, broker: str, exchange: str = "NSE"
) -> None:
    """Non-blocking. Kicks a background thread to (re)fill symbols missing
    today's score or whose cached score is older than REFRESH_INTERVAL_SEC.
    Safe to call on every /tfmarketpulse poll — symbols already fresh or
    already in flight are skipped."""
    today_str = date.today().strftime("%Y-%m-%d")
    now = time.monotonic()
    with _lock:
        todo = []
        for s in symbols:
            if s in _pending:
                continue
            cached = _cache.get(s)
            if cached is None or cached[0] != today_str or now - cached[1] > REFRESH_INTERVAL_SEC:
                todo.append(s)
        _pending.update(todo)
    if todo:
        threading.Thread(
            target=_background_fill, args=(todo, exchange, auth_token, broker),
            daemon=True, name="tf-directional-score-fill",
        ).start()


def attach_directional_score(items: list[dict]) -> list[dict]:
    """Adds 'directional_score', 'directional_direction' and
    'directional_reversals' to each item in place, from cache."""
    today_str = date.today().strftime("%Y-%m-%d")
    with _lock:
        for item in items:
            cached = _cache.get(item.get("symbol", ""))
            if not cached or cached[0] != today_str:
                item["directional_score"] = None
                item["directional_direction"] = None
                item["directional_reversals"] = None
                continue
            _, _, score, direction, reversals = cached
            item["directional_score"] = score
            item["directional_direction"] = direction
            item["directional_reversals"] = reversals
    return items


def _demo() -> None:
    """Self-check for compute_efficiency_score — no I/O. A straight-line
    move scores ~100, a symmetric up-down-up-down round trip scores ~0."""
    score, direction, reversals = compute_efficiency_score(100.0, [102, 104, 106, 108])
    assert score == 100.0, score
    assert direction == "up"
    assert reversals == 0

    score, direction, reversals = compute_efficiency_score(100.0, [102, 100, 102, 100])
    assert score == 0.0, score
    assert direction is None
    assert reversals == 3

    score, direction, reversals = compute_efficiency_score(100.0, [98, 96, 99, 94])
    assert direction == "down"
    assert 0 < score < 100
    assert reversals == 2

    logger.info("tf_directional_score_service self-check passed")


if __name__ == "__main__":
    _demo()
