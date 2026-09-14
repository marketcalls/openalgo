"""Dhan sandbox history fallback builds candles instead of crashing.

When the sandbox returns no candles, get_history generates placeholder candles
so charts and /api/v1/history still have something to draw. That fallback read
the interval straight out of timeframe_map, which holds Dhan's request codes as
strings ("5" for 5m, "D" for daily), so it crashed on every interval (issue
#2057):

    intraday: 375 // "5"      -> TypeError: unsupported operand for //
    daily:    base_ts + i*"D" -> TypeError: unsupported operand for +

The codes are also minutes, not seconds, so an int() alone would still have
spaced 5m candles five seconds apart. These tests pin both halves: no crash,
and spacing in real seconds.

The HTTP call is replaced with one returning no candles, so this runs without a
Dhan session.
"""

import pytest

import broker.dhan_sandbox.api.data as dsdata


@pytest.fixture
def sandbox(monkeypatch):
    monkeypatch.setattr(dsdata, "get_token", lambda symbol, exchange: "2885")
    monkeypatch.setattr(dsdata, "get_api_response", lambda *args, **kwargs: {})
    data = dsdata.BrokerData("token")
    # The daily path tops up "today" from a quote; keep it out of the picture.
    monkeypatch.setattr(data, "get_quotes", lambda *args, **kwargs: {"ltp": 0})
    return data


def spacing(df):
    return set(df["timestamp"].diff().dropna().astype(int))


@pytest.mark.parametrize(
    ("interval", "seconds", "candles"),
    [
        ("1m", 60, 75),  # 375 in the session, capped at 75
        ("5m", 300, 75),  # exactly 75 in the session
        ("15m", 900, 25),
        ("25m", 1500, 15),
        ("1h", 3600, 6),
    ],
)
def test_intraday_fallback_spaces_candles_by_the_interval(sandbox, interval, seconds, candles):
    df = sandbox.get_history("RELIANCE", "NSE", interval, "2026-09-08", "2026-09-10")

    assert len(df) == candles
    assert spacing(df) == {seconds}


def test_intraday_fallback_stays_inside_the_session(sandbox):
    """No placeholder candle may start at or after the 3:30 PM close."""
    df = sandbox.get_history("RELIANCE", "NSE", "1h", "2026-09-08", "2026-09-10")

    span = int(df["timestamp"].iloc[-1] - df["timestamp"].iloc[0])
    assert span < 6 * 3600 + 15 * 60


def test_daily_fallback_is_one_candle_per_day(sandbox):
    df = sandbox.get_history("RELIANCE", "NSE", "D", "2026-09-08", "2026-09-10")

    assert len(df) == 3
    assert spacing(df) == {24 * 60 * 60}
