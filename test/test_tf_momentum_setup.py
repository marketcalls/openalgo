"""Momentum Setup enrichment for the Intraday Boost list.

The underlying indicator math (EMA/MACD/Stochastic/Supertrend/VWAP, and the
Continuous-mode arm/fire state machine) is verified independently in
services/tf_momentum_setup_math.py's own self-check and against a live chart
signal -- these tests fake momentum_setup_signals() itself and check only
what this module is responsible for: fetching multi-day history, resolving
equity vs. future, the scan window, candle-close-aligned staleness, caching,
and the distinct-signal-per-day count.
"""

import time
from datetime import datetime, timedelta

import services.tf_momentum_setup_service as svc
from services.tf_momentum_setup_math import IST
from services.tf_momentum_setup_service import (
    CANDLE_INTERVAL_SEC,
    GRACE_SEC,
    _is_due,
    _latest_signal_in_window,
    _window_start_index,
    attach_momentum_setup,
    momentum_signals_today,
)


def _reset() -> None:
    svc._cache.clear()
    svc._pending.clear()
    svc._signals_today.clear()
    svc._signals_today_date = ""


def _bars(n=25):
    """A plain, otherwise-irrelevant bar list ending at the current moment --
    what it contains doesn't matter here since momentum_setup_signals() is
    faked, but the timestamps must be "now" so the scan window (previous
    trading day 15:15 through the latest bar) actually covers every bar
    rather than excluding a fixed old fixture date."""
    now = time.time()
    return [
        {
            "timestamp": now - (n - 1 - i) * 300,
            "open": 100 + i,
            "high": 101 + i,
            "low": 99 + i,
            "close": 100.5 + i,
            "volume": 1000,
        }
        for i in range(n)
    ]


def _no_future(monkeypatch):
    """Every test here exercises the equity path -- future_for() would
    otherwise hit the real SymToken table."""
    monkeypatch.setattr(svc, "future_for", lambda s: None)


def test_a_fired_signal_is_cached_and_attached(monkeypatch):
    _reset()
    _no_future(monkeypatch)
    bars = _bars()
    monkeypatch.setattr(svc, "get_history", lambda **k: (True, {"data": bars}, 200))
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {
            "long_trigger": [0] * (len(bars) - 1) + [1],
            "short_trigger": [0] * len(bars),
        },
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    items = [{"symbol": "RELIANCE"}]
    attach_momentum_setup(items)

    assert items[0]["momentum_signal"] == "buy"
    assert items[0]["momentum_signal_price"] == bars[-1]["close"]
    assert items[0]["momentum_signal_bar_time"] is not None
    assert items[0]["momentum_signal_count"] == 1
    assert momentum_signals_today() == 1


def test_no_trigger_anywhere_in_the_window_is_none(monkeypatch):
    _reset()
    _no_future(monkeypatch)
    bars = _bars()
    monkeypatch.setattr(svc, "get_history", lambda **k: (True, {"data": bars}, 200))
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {"long_trigger": [0] * len(bars), "short_trigger": [0] * len(bars)},
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    items = [{"symbol": "RELIANCE"}]
    attach_momentum_setup(items)

    assert items[0]["momentum_signal"] is None
    assert items[0]["momentum_signal_price"] is None
    assert items[0]["momentum_signal_count"] is None
    assert momentum_signals_today() == 0


def test_an_earlier_fire_in_the_window_still_wins_over_a_quiet_last_bar(monkeypatch):
    """The whole point of scanning a window rather than only the last bar:
    a setup that fired mid-window and has gone quiet since must still read
    as the active signal, not None."""
    _reset()
    _no_future(monkeypatch)
    bars = _bars()
    monkeypatch.setattr(svc, "get_history", lambda **k: (True, {"data": bars}, 200))
    fire_idx = len(bars) - 5
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {
            "long_trigger": [1 if i == fire_idx else 0 for i in range(len(bars))],
            "short_trigger": [0] * len(bars),
        },
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    items = [{"symbol": "RELIANCE"}]
    attach_momentum_setup(items)

    assert items[0]["momentum_signal"] == "buy"
    assert items[0]["momentum_signal_price"] == bars[fire_idx]["close"]


def test_the_future_is_scanned_instead_of_the_equity_when_one_is_listed(monkeypatch):
    """Options trade off the future, not the equity -- a symbol with a
    listed current-month future must be fetched on NFO under that symbol,
    not NSE under its own name."""
    _reset()
    bars = _bars()
    seen = {}

    def fake_get_history(**k):
        seen["symbol"] = k["symbol"]
        seen["exchange"] = k["exchange"]
        return True, {"data": bars}, 200

    monkeypatch.setattr(svc, "get_history", fake_get_history)
    monkeypatch.setattr(svc, "future_for", lambda s: "RELIANCE29SEP26FUT")
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {"long_trigger": [0] * len(bars), "short_trigger": [0] * len(bars)},
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")

    assert seen["symbol"] == "RELIANCE29SEP26FUT"
    assert seen["exchange"] == "NFO"


def test_no_listed_future_falls_back_to_the_equity(monkeypatch):
    _reset()
    bars = _bars()
    seen = {}

    def fake_get_history(**k):
        seen["symbol"] = k["symbol"]
        seen["exchange"] = k["exchange"]
        return True, {"data": bars}, 200

    monkeypatch.setattr(svc, "get_history", fake_get_history)
    monkeypatch.setattr(svc, "future_for", lambda s: None)
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {"long_trigger": [0] * len(bars), "short_trigger": [0] * len(bars)},
    )

    svc._background_fill(["DALBHARAT"], "NSE", "token", "upstox")

    assert seen["symbol"] == "DALBHARAT"
    assert seen["exchange"] == "NSE"


def test_cache_miss_is_none_never_a_fabricated_default():
    _reset()
    items = [{"symbol": "UNSEEN"}]
    attach_momentum_setup(items)
    assert items[0]["momentum_signal"] is None
    assert items[0]["momentum_signal_price"] is None
    assert items[0]["momentum_signal_bar_time"] is None
    assert items[0]["momentum_signal_count"] is None


def test_broker_failure_clears_pending_without_caching(monkeypatch):
    _reset()
    _no_future(monkeypatch)
    monkeypatch.setattr(svc, "get_history", lambda **k: (False, {"message": "rate limited"}, 429))

    svc._pending.add("RELIANCE")
    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")

    assert "RELIANCE" not in svc._pending
    items = [{"symbol": "RELIANCE"}]
    attach_momentum_setup(items)
    assert items[0]["momentum_signal"] is None


def test_too_few_bars_is_not_computed(monkeypatch):
    """Fewer than MIN_BARS and the state machine hasn't said anything
    trustworthy yet -- must not be treated as 'no signal', just not
    computed."""
    _reset()
    _no_future(monkeypatch)
    short_bars = _bars(n=5)
    monkeypatch.setattr(svc, "get_history", lambda **k: (True, {"data": short_bars}, 200))
    called = []
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: called.append(1) or {"long_trigger": [], "short_trigger": []},
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    assert not called, "momentum_setup_signals must not run on too little history"
    assert "RELIANCE" not in svc._cache


def test_staleness_is_candle_close_aligned_not_wall_clock_ttl():
    now = 1_800_000_000.0
    assert _is_due(None, now) is True

    fresh = ("2026-09-23", now - 60, "buy", 100.0, "x", 1)
    assert _is_due(fresh, now) is False

    just_closed = ("2026-09-23", now - (CANDLE_INTERVAL_SEC + GRACE_SEC - 1), "buy", 100.0, "x", 1)
    assert _is_due(just_closed, now) is False

    due = ("2026-09-23", now - (CANDLE_INTERVAL_SEC + GRACE_SEC + 1), "buy", 100.0, "x", 1)
    assert _is_due(due, now) is True


def test_repeated_fires_on_one_symbol_do_not_inflate_the_daily_count(monkeypatch):
    """Continuous mode can re-fire on consecutive bars while a setup holds --
    the daily count is distinct symbols, not distinct fires."""
    _reset()
    _no_future(monkeypatch)
    bars = _bars()
    monkeypatch.setattr(svc, "get_history", lambda **k: (True, {"data": bars}, 200))
    monkeypatch.setattr(
        svc,
        "momentum_setup_signals",
        lambda bars: {"long_trigger": [1] * len(bars), "short_trigger": [0] * len(bars)},
    )

    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    svc._background_fill(["RELIANCE"], "NSE", "token", "upstox")
    svc._background_fill(["TCS"], "NSE", "token", "upstox")

    assert momentum_signals_today() == 2


def test_a_fire_on_yesterdays_last_candle_is_still_the_active_signal_this_morning():
    """A stock that fired on the previous trading day's 15:30 candle must
    read as signaling from today's 9:20 open onward, until superseded --
    the scan window opens at the previous trading day's 15:15, not today's."""
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    prev_fire_ts = (
        datetime.combine(yesterday, datetime.min.time(), tzinfo=IST)
        .replace(hour=15, minute=30)
        .timestamp()
    )
    today_open_ts = (
        datetime.combine(datetime.now(IST).date(), datetime.min.time(), tzinfo=IST)
        .replace(hour=9, minute=20)
        .timestamp()
    )
    bars = [
        {"time": prev_fire_ts, "close": 1900.0},
        {"time": today_open_ts, "close": 1905.0},
    ]
    start_idx = _window_start_index(bars)
    signal, price, bar_iso, count = _latest_signal_in_window(
        bars, {"long_trigger": [1, 0], "short_trigger": [0, 0]}, start_idx
    )
    assert signal == "buy"
    assert price == 1900.0, "the fire's own bar price, not today's unrelated open"
    assert bar_iso.startswith(yesterday.isoformat())
    assert count == 1


def test_a_fire_two_days_ago_does_not_leak_into_todays_window():
    two_days_ago = datetime.now(IST).date() - timedelta(days=2)
    yesterday = datetime.now(IST).date() - timedelta(days=1)
    old_fire_ts = (
        datetime.combine(two_days_ago, datetime.min.time(), tzinfo=IST)
        .replace(hour=15, minute=30)
        .timestamp()
    )
    yesterday_quiet_ts = (
        datetime.combine(yesterday, datetime.min.time(), tzinfo=IST)
        .replace(hour=15, minute=20)
        .timestamp()
    )
    bars = [
        {"time": old_fire_ts, "close": 100.0},
        {"time": yesterday_quiet_ts, "close": 101.0},
    ]
    start_idx = _window_start_index(bars)
    signal, _price, _bar_iso, _count = _latest_signal_in_window(
        bars, {"long_trigger": [1, 0], "short_trigger": [0, 0]}, start_idx
    )
    assert signal is None, "a fire from two trading days back is outside the window"
