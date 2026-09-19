"""Dhan's derived timeframes: 30m and 4h from 15m, W and M from D.

Stamps are built the way broker/dhan/api/data.py builds them, a naive IST
wall-clock datetime passed through .timestamp(), so these hold on a server in
any timezone.
"""

from datetime import date, datetime, timedelta

import pandas as pd
import pytest

from broker.dhan.api import resample
from broker.dhan.api.resample import aggregate, get_derived_history


def _intraday(start: datetime, count: int, step_min: int = 15) -> pd.DataFrame:
    rows = []
    for i in range(count):
        wall = start + timedelta(minutes=step_min * i)
        rows.append(
            {
                "timestamp": int(wall.timestamp()),
                "open": 100.0 + i,
                "high": 101.0 + i,
                "low": 99.0 + i,
                "close": 100.5 + i,
                "volume": 10,
                "oi": i,
            }
        )
    return pd.DataFrame(rows)


def _daily(days: list[date]) -> pd.DataFrame:
    rows = []
    for i, d in enumerate(days):
        rows.append(
            {
                "timestamp": int(datetime(d.year, d.month, d.day).timestamp()) + 19800,
                "open": 100.0 + i,
                "high": 110.0 + i,
                "low": 90.0 + i,
                "close": 105.0 + i,
                "volume": 1000,
                "oi": 0,
            }
        )
    return pd.DataFrame(rows)


def _walls(df: pd.DataFrame) -> list[datetime]:
    return [datetime.fromtimestamp(t) for t in df["timestamp"]]


def test_30m_buckets_open_at_nse_session_start():
    # 09:15 .. 15:15, the 25 fifteen-minute bars of an NSE session
    df = _intraday(datetime(2026, 9, 14, 9, 15), 25)
    out = aggregate(df, "30m", "NSE")

    walls = _walls(out)
    assert walls[0] == datetime(2026, 9, 14, 9, 15)
    assert walls[1] == datetime(2026, 9, 14, 9, 45)
    assert walls[-1] == datetime(2026, 9, 14, 15, 15)
    assert len(out) == 13

    first = out.iloc[0]
    assert first["open"] == 100.0  # 09:15 bar's open
    assert first["close"] == 101.5  # 09:30 bar's close
    assert first["high"] == 102.0
    assert first["low"] == 99.0
    assert first["volume"] == 20
    assert first["oi"] == 1


def test_4h_splits_nse_session_at_1315():
    df = _intraday(datetime(2026, 9, 14, 9, 15), 25)
    out = aggregate(df, "4h", "NFO")

    assert _walls(out) == [datetime(2026, 9, 14, 9, 15), datetime(2026, 9, 14, 13, 15)]
    assert out["volume"].tolist() == [160, 90]


def test_4h_mcx_anchors_at_0900():
    # 09:00 .. 23:15
    df = _intraday(datetime(2026, 9, 14, 9, 0), 58)
    out = aggregate(df, "4h", "MCX")

    assert [w.strftime("%H:%M") for w in _walls(out)] == ["09:00", "13:00", "17:00", "21:00"]
    assert out["volume"].sum() == 580


def test_intraday_buckets_never_span_days():
    df = pd.concat(
        [
            _intraday(datetime(2026, 9, 14, 13, 15), 9),
            _intraday(datetime(2026, 9, 15, 9, 15), 4),
        ]
    )
    out = aggregate(df, "4h", "NSE")

    assert _walls(out) == [datetime(2026, 9, 14, 13, 15), datetime(2026, 9, 15, 9, 15)]


@pytest.mark.parametrize("interval", ["30m", "4h"])
def test_preopen_bar_folds_into_first_bucket(interval):
    # Dhan's 15m history has a stray 09:07 bar on a few days, e.g. SBIN 2021-08-12.
    preopen = _intraday(datetime(2021, 8, 12, 9, 7), 1)
    session = _intraday(datetime(2021, 8, 12, 9, 15), 4)
    session["open"] = 200.0
    out = aggregate(pd.concat([preopen, session]), interval, "NSE")

    assert _walls(out)[0] == datetime(2021, 8, 12, 9, 15)
    assert out.iloc[0]["open"] == 100.0  # the auction bar's price opens the session
    assert out["volume"].sum() == 50


def test_weekly_stamped_on_monday_even_when_monday_is_a_holiday():
    # Tue 15 .. Fri 18 Sep 2026, then Mon 21 .. Tue 22
    days = [date(2026, 9, d) for d in (15, 16, 17, 18, 21, 22)]
    out = aggregate(_daily(days), "W", "NSE")

    assert _walls(out) == [datetime(2026, 9, 14, 5, 30), datetime(2026, 9, 21, 5, 30)]
    week = out.iloc[0]
    assert week["open"] == 100.0
    assert week["close"] == 108.0
    assert week["high"] == 113.0
    assert week["low"] == 90.0
    assert week["volume"] == 4000


def test_monthly_stamped_on_the_first():
    days = [date(2026, 8, 28), date(2026, 8, 31), date(2026, 9, 1), date(2026, 9, 2)]
    out = aggregate(_daily(days), "M", "NSE")

    assert _walls(out) == [datetime(2026, 8, 1, 5, 30), datetime(2026, 9, 1, 5, 30)]
    assert out["volume"].tolist() == [2000, 2000]


def test_derived_stamps_match_native_daily_convention():
    # A weekly bar starting on a trading Monday carries that Monday's daily stamp.
    df = _daily([date(2026, 9, 14), date(2026, 9, 15)])
    out = aggregate(df, "W", "NSE")
    assert out["timestamp"].iloc[0] == df["timestamp"].iloc[0]


def test_empty_input_returns_empty_frame():
    out = aggregate(pd.DataFrame(columns=resample.COLUMNS), "4h", "NSE")
    assert out.empty
    assert list(out.columns) == resample.COLUMNS


@pytest.mark.parametrize(
    ("interval", "requested", "expected_base", "expected_range"),
    [
        ("30m", ("2026-09-02", "2026-09-09"), "15m", ("2026-09-02", "2026-09-09")),
        ("4h", ("2026-09-02", "2026-09-09"), "15m", ("2026-09-02", "2026-09-09")),
        # Wed .. Wed widens to Mon .. Sun
        ("W", ("2026-08-05", "2026-08-12"), "D", ("2026-08-03", "2026-08-16")),
        ("M", ("2026-06-10", "2026-07-15"), "D", ("2026-06-01", "2026-07-31")),
    ],
)
def test_fetches_native_interval_over_widened_range(
    interval, requested, expected_base, expected_range
):
    calls = []

    def fake_history(symbol, exchange, base, start, end):
        calls.append((base, start, end))
        return pd.DataFrame(columns=resample.COLUMNS)

    get_derived_history(fake_history, "SBIN", "NSE", interval, *requested)
    assert calls == [(expected_base, *expected_range)]


def test_widened_end_never_passes_today(monkeypatch):
    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 9, 16)

    monkeypatch.setattr(resample, "date", FixedDate)
    calls = []

    def fake_history(symbol, exchange, base, start, end):
        calls.append((start, end))
        return pd.DataFrame(columns=resample.COLUMNS)

    get_derived_history(fake_history, "SBIN", "NSE", "M", "2026-09-01", "2026-09-16")
    assert calls == [("2026-09-01", "2026-09-16")]


def test_dhan_advertises_derived_intervals():
    from broker.dhan.api.data import BrokerData

    offered = BrokerData("token").timeframe_map
    for interval in ("30m", "4h", "W", "M"):
        assert interval in offered
