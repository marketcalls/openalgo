# services/tf_momentum_setup_service.py
"""
Momentum Setup (Vijay Thakare scalping setup) enrichment for the TradeFinder
Intraday Boost list.

Same non-blocking ensure_/attach_ shape as tf_cpr_service.py /
tf_first_candle_service.py / tf_directional_score_service.py / tf_first_
candle_service.py, computing this on every poll would mean one broker history
call per symbol per request. Two departures from that pattern, both driven by
what this signal actually is:

- The chart indicator's buy/sell trigger is a state machine that has to run
  forward over an ordered multi-day bar series to mean anything -- a setup
  "arming" near yesterday's close has to still be able to fire on today's
  early candles, so _compute_momentum_setup fetches HISTORY_LOOKBACK_DAYS of
  5-minute history rather than just today's, and tf_momentum_setup_math's
  state machine (which has no day-boundary concept at all, only bar order)
  carries that arming across midnight for free.
- Staleness here is candle-close-aligned, not a wall-clock TTL: a symbol is
  only re-fetched once its next 5-minute boundary has actually passed
  (last_bar_ts + CANDLE_INTERVAL_SEC + GRACE_SEC), not N seconds since it was
  last written. Doing this on a blind TTL would either recompute ~191
  symbols against the shared ~3 req/sec history rate limit far more often
  than a new candle can even exist, or lag behind by whatever the TTL is
  regardless of whether a fresh candle actually closed.

attach_momentum_setup() serves whatever is cached so far -- a symbol not yet
computed gets momentum_signal=None, never a fabricated "no signal".
momentum_signals_today() is a same-session count of distinct symbols that
fired a signal today, for the panel header; the durable per-signal record
(price, time) lives in tf_boost_snapshots via tf_boost_snapshot_service.py,
not here.

Two more things this module does beyond a bare "did the last bar trigger":

- **Scans a window, not one bar.** The Continuous-mode trigger is only 1 on
  the exact bar it fires -- it drops back to 0 immediately after, even while
  the setup that produced it is still the most recent thing that happened.
  A stock that fired at 15:30 the previous trading day must still read as
  signaling at 9:20 this morning, so _compute_momentum_setup scans every bar
  from the previous trading day's 15:15 IST through the latest fetched bar,
  and reports the most recent fire in that window (plus how many times that
  direction fired in it) rather than only the last bar's own state.
- **Prefers the current-month future over the equity.** TradeFinder's boost
  list carries NSE equity symbols, but options trade off the future, so a
  symbol with one listed (services.tf_future_liquidity_service.future_for)
  is scanned on its NFO future instead of NSE. A symbol with no listed
  future scans its equity, the only kind of history it has.
"""

from __future__ import annotations

import threading
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

from cachetools import TTLCache

from services.history_service import get_history
from services.tf_future_liquidity_service import future_for
from services.tf_momentum_setup_math import IST, momentum_setup_signals
from utils.logging import get_logger

logger = get_logger(__name__)

HISTORY_LOOKBACK_DAYS = 5  # enough trailing days that MACD/Stochastic/Supertrend
# warmup (longest is the MACD signal line's 15-period EMA, itself needing a
# 9-period EMA finite first -- both short against a ~75-bar trading day) has
# settled before today, while always including all of yesterday.
MIN_BARS = 20  # fewer than this and the state machine hasn't said anything yet
CANDLE_INTERVAL_SEC = 300  # 5m bars
GRACE_SEC = 15  # broker candle-close lag before a fresh bar is reliably available

# symbol -> (date_str, last_bar_ts, signal, signal_price, signal_bar_iso, signal_count)
# Bounded: the boost list rotates through a different slice of the NSE F&O
# universe every day, and a plain dict here would hold one entry per symbol
# ever seen for as long as the process runs. maxsize comfortably exceeds that
# universe; ttl outlives a session (these are intraday values anyway, already
# gated on date_str) but still guarantees eventual cleanup.
_cache: TTLCache = TTLCache(maxsize=2000, ttl=86400)
_pending: set[str] = set()
_lock = threading.Lock()

_signals_today: set[str] = set()
_signals_today_date: str = ""


def _row_time(row: dict) -> float:
    """history_service.get_history() returns 'timestamp' as a raw Unix epoch
    int/float (see tf_directional_score_service._row_date for the same
    caveat) -- not an ISO string."""
    ts = row.get("timestamp") or row.get("date") or row.get("datetime")
    if isinstance(ts, (int, float)):
        return float(ts)
    return datetime.fromisoformat(str(ts)).timestamp()


def _window_start_index(bars: list[dict]) -> int:
    """Index of the first bar at/after the previous trading day's 15:15 IST.

    'Previous trading day' is the most recent IST calendar date in `bars`
    strictly before today's -- a signal fired in that day's last 15 minutes
    has to still read as active at today's open. Falls back to 0 (scan
    everything fetched) when there is no earlier day in the window at all,
    which is the correct answer on a symbol's very first day of history."""
    if not bars:
        return 0
    today = datetime.now(IST).date()
    prev_day = None
    for b in reversed(bars):
        d = datetime.fromtimestamp(b["time"], tz=IST).date()
        if d < today:
            prev_day = d
            break
    if prev_day is None:
        return 0
    window_start_ts = datetime.combine(prev_day, dtime(15, 15), tzinfo=IST).timestamp()
    for i, b in enumerate(bars):
        if b["time"] >= window_start_ts:
            return i
    return 0


def _latest_signal_in_window(
    bars: list[dict], out: dict, start_idx: int
) -> tuple[str | None, float | None, str | None, int]:
    """(signal, signal_price, signal_bar_iso, signal_count) for the most
    recent buy/sell fire from start_idx through the last bar, plus how many
    times that direction fired in the window -- Continuous mode can fire on
    more than one bar while a setup holds, and that count is worth carrying
    even though only the latest fire decides the badge."""
    fires: list[tuple[int, str]] = []
    for i in range(start_idx, len(bars)):
        if out["long_trigger"][i] == 1:
            fires.append((i, "buy"))
        if out["short_trigger"][i] == 1:
            fires.append((i, "sell"))
    if not fires:
        return None, None, None, 0

    last_idx, signal = fires[-1]
    signal_count = sum(1 for _, d in fires if d == signal)
    signal_price = bars[last_idx]["close"]
    signal_bar_iso = datetime.fromtimestamp(bars[last_idx]["time"], tz=IST).isoformat()
    return signal, signal_price, signal_bar_iso, signal_count


def _compute_momentum_setup(
    symbol: str, exchange: str, auth_token: str, broker: str
) -> tuple[float, str | None, float | None, str | None, int] | None:
    """Returns (last_bar_ts, signal, signal_price, signal_bar_iso,
    signal_count), or None if it can't be computed (fetch failed, or too
    little history yet). last_bar_ts is always the latest fetched bar's own
    time, regardless of the signal -- ensure_momentum_setup_cache's
    candle-close staleness check depends on that, not on when a signal fired.

    Scans the current-month future's history instead of the equity's when
    one is listed for this symbol (services.tf_future_liquidity_service.
    future_for) -- options trade off the future, so that is the series a
    trader actually cares about the setup on."""
    fut_symbol = future_for(symbol)
    fetch_symbol = fut_symbol or symbol
    fetch_exchange = "NFO" if fut_symbol else exchange

    end = date.today()
    start = end - timedelta(days=HISTORY_LOOKBACK_DAYS)
    try:
        success, data, _status = get_history(
            symbol=fetch_symbol,
            exchange=fetch_exchange,
            interval="5m",
            start_date=start.isoformat(),
            end_date=end.isoformat(),
            auth_token=auth_token,
            broker=broker,
            source="api",
        )
    except Exception as e:
        logger.debug(f"tf_momentum_setup_service: history fetch failed for {fetch_symbol}: {e}")
        return None
    if not success:
        return None

    rows = data.get("data") or []
    if len(rows) < MIN_BARS:
        return None

    try:
        bars = [
            {
                "time": _row_time(r),
                "open": float(r["open"]),
                "high": float(r["high"]),
                "low": float(r["low"]),
                "close": float(r["close"]),
                "volume": float(r["volume"]) if r.get("volume") is not None else None,
            }
            for r in rows
        ]
    except (KeyError, TypeError, ValueError):
        return None
    bars.sort(key=lambda b: b["time"])

    out = momentum_setup_signals(bars)
    last_bar_ts = bars[-1]["time"]
    signal, signal_price, signal_bar_iso, signal_count = _latest_signal_in_window(
        bars, out, _window_start_index(bars)
    )
    return last_bar_ts, signal, signal_price, signal_bar_iso, signal_count


def _note_signal_today(symbol: str) -> None:
    """Call only while holding _lock. Rolls the distinct-signal set over at
    the first call after the IST date has changed."""
    global _signals_today_date
    today_str = date.today().isoformat()
    if _signals_today_date != today_str:
        _signals_today.clear()
        _signals_today_date = today_str
    _signals_today.add(symbol)


def _background_fill(symbols: list[str], exchange: str, auth_token: str, broker: str) -> None:
    today_str = date.today().isoformat()
    try:
        for symbol in symbols:
            result = _compute_momentum_setup(symbol, exchange, auth_token, broker)
            with _lock:
                if result is not None:
                    last_bar_ts, signal, signal_price, signal_bar_iso, signal_count = result
                    _cache[symbol] = (
                        today_str,
                        last_bar_ts,
                        signal,
                        signal_price,
                        signal_bar_iso,
                        signal_count,
                    )
                    if signal is not None:
                        _note_signal_today(symbol)
                _pending.discard(symbol)
    except Exception as e:
        logger.warning(f"tf_momentum_setup_service: background fill error: {e}")
        with _lock:
            for symbol in symbols:
                _pending.discard(symbol)


def _is_due(cached: tuple | None, now: float) -> bool:
    """A symbol is due for recomputation once its next 5-minute candle close
    has actually passed (plus GRACE_SEC), not on a blind wall-clock TTL."""
    if cached is None:
        return True
    _, last_bar_ts, *_ = cached
    return now >= last_bar_ts + CANDLE_INTERVAL_SEC + GRACE_SEC


def ensure_momentum_setup_cache(
    symbols: list[str], auth_token: str, broker: str, exchange: str = "NSE"
) -> None:
    """Non-blocking. Kicks a background thread to (re)fill symbols whose
    cached signal is missing or whose next 5m candle close has passed. Safe
    to call on every /tfmarketpulse poll -- symbols already current or
    already in flight are skipped."""
    now = time.time()
    with _lock:
        todo = [s for s in symbols if s not in _pending and _is_due(_cache.get(s), now)]
        _pending.update(todo)
    if todo:
        threading.Thread(
            target=_background_fill,
            args=(todo, exchange, auth_token, broker),
            daemon=True,
            name="tf-momentum-setup-fill",
        ).start()


def attach_momentum_setup(items: list[dict]) -> list[dict]:
    """Adds 'momentum_signal', 'momentum_signal_price',
    'momentum_signal_bar_time' and 'momentum_signal_count' to each item in
    place, from cache."""
    with _lock:
        for item in items:
            cached = _cache.get(item.get("symbol", ""))
            if not cached:
                item["momentum_signal"] = None
                item["momentum_signal_price"] = None
                item["momentum_signal_bar_time"] = None
                item["momentum_signal_count"] = None
                continue
            _, _, signal, signal_price, signal_bar_iso, signal_count = cached
            item["momentum_signal"] = signal
            item["momentum_signal_price"] = signal_price
            item["momentum_signal_bar_time"] = signal_bar_iso
            item["momentum_signal_count"] = signal_count if signal is not None else None
    return items


def momentum_signals_today() -> int:
    """How many distinct boost-list symbols have fired a buy or sell signal
    today so far, for the panel header. Same-session convenience -- the
    durable per-signal record lives in tf_boost_snapshots."""
    with _lock:
        if _signals_today_date != date.today().isoformat():
            return 0
        return len(_signals_today)


def _demo() -> None:
    """Self-check for the pure/no-I/O parts -- staleness gating and the
    distinct-signal-per-day dedup. No broker call."""
    now = time.time()

    assert _is_due(None, now) is True
    fresh = ("2026-09-23", now - 60, "buy", 100.0, "x", 1)
    assert _is_due(fresh, now) is False
    stale = ("2026-09-23", now - (CANDLE_INTERVAL_SEC + GRACE_SEC + 1), "buy", 100.0, "x", 1)
    assert _is_due(stale, now) is True

    global _signals_today_date
    _signals_today.clear()
    _signals_today_date = ""
    with _lock:
        _note_signal_today("RELIANCE")
        _note_signal_today("RELIANCE")  # re-fires on a consecutive Continuous-mode bar
        _note_signal_today("TCS")
    assert _signals_today == {"RELIANCE", "TCS"}, (
        "a symbol re-firing must not inflate the distinct count"
    )

    # A fire on the previous trading day's last candle must still be the
    # active signal at today's open -- the whole point of scanning a window
    # instead of only the last bar.
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    prev_fire_ts = datetime.combine(yesterday, dtime(15, 30), tzinfo=IST).timestamp()
    today_open_ts = datetime.combine(datetime.now(IST).date(), dtime(9, 15), tzinfo=IST).timestamp()
    window_bars = [{"time": prev_fire_ts, "close": 100.0}, {"time": today_open_ts, "close": 105.0}]
    start_idx = _window_start_index(window_bars)
    assert start_idx == 0, "yesterday's 15:30 candle must fall inside a window opened at 15:15"

    signal, price, bar_iso, count = _latest_signal_in_window(
        window_bars, {"long_trigger": [1, 0], "short_trigger": [0, 0]}, start_idx
    )
    assert signal == "buy" and price == 100.0 and count == 1
    assert bar_iso.startswith(yesterday.isoformat()), (
        "must report YESTERDAY's fire, not today's blank bar"
    )

    # Continuous mode firing twice in the window is a count of 2, not a
    # second, separate signal.
    multi_bars = [{"time": today_open_ts + i * 300, "close": 100.0 + i} for i in range(3)]
    signal2, price2, _bar_iso2, count2 = _latest_signal_in_window(
        multi_bars, {"long_trigger": [0, 1, 1], "short_trigger": [0, 0, 0]}, 0
    )
    assert signal2 == "buy" and count2 == 2 and price2 == 102.0

    logger.info("tf_momentum_setup_service self-check passed")


if __name__ == "__main__":
    _demo()
