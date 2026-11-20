"""Flattrade intraday history drops bars before the day's session open.

TPSeries returns pre-open bars before the session opens: a flat 09:14 bar on
a normal day, and 14:05 to 14:19 on Muhurat 2026 (session 14:20 to 15:30),
some stamped with seconds (14:14:05). Stored in Historify, one such bar made
the chart refuse every 15m page reaching back past that day ("Could not load
older history"). The session open comes from OpenAlgo's market calendar.
"""

from datetime import date, datetime
from unittest.mock import patch

from broker.flattrade.api import data as ft

MUHURAT = date(2026, 11, 8)
# 14:20 and 15:30 IST on 8 Nov 2026, as the shipped calendar holds them.
MUHURAT_TIMINGS = [{"exchange": "NSE", "start_time": 1794127800000, "end_time": 1794132000000}]
# 09:15 and 15:30 IST on 11 Nov 2026.
REGULAR_TIMINGS = [{"exchange": "NSE", "start_time": 1794368700000, "end_time": 1794391200000}]


def _bar(stamp: str) -> dict:
    return {
        "time": stamp,
        "into": "100",
        "inth": "101",
        "intl": "99",
        "intc": "100.5",
        "intv": "10",
        "oi": "0",
    }


def _timings(day):
    return MUHURAT_TIMINGS if day == MUHURAT else REGULAR_TIMINGS if day.day == 11 else []


def _history(bars, timings=_timings):
    with (
        patch.object(ft, "get_api_response", return_value=bars),
        patch.object(ft, "get_token", return_value="3045"),
        patch.object(ft, "get_market_timings_for_date", side_effect=timings),
        patch.dict("os.environ", {"BROKER_API_KEY": "UID:::KEY"}),
    ):
        df = ft.BrokerData("token").get_history("SBIN", "NSE", "1m", "2026-11-08", "2026-11-11")
    return [datetime.fromtimestamp(int(t)).strftime("%d %H:%M:%S") for t in df["timestamp"]]


def test_muhurat_pre_open_bars_are_dropped():
    kept = _history(
        [
            _bar("08-11-2026 14:05:00"),
            _bar("08-11-2026 14:14:05"),
            _bar("08-11-2026 14:19:00"),
            _bar("08-11-2026 14:20:00"),
            _bar("08-11-2026 14:21:00"),
        ]
    )
    assert kept == ["08 14:20:00", "08 14:21:00"]


def test_regular_day_still_drops_the_09_14_bar():
    kept = _history([_bar("11-11-2026 09:14:00"), _bar("11-11-2026 09:15:00")])
    assert kept == ["11 09:15:00"]


def test_a_day_the_calendar_does_not_cover_falls_back_to_09_15():
    kept = _history(
        [_bar("09-11-2026 09:14:00"), _bar("09-11-2026 09:15:00")],
        timings=lambda day: [],
    )
    assert kept == ["09 09:15:00"]


def test_a_calendar_read_failure_falls_back_to_09_15():
    def broken(day):
        raise RuntimeError("calendar unavailable")

    kept = _history([_bar("09-11-2026 09:14:00"), _bar("09-11-2026 09:15:00")], timings=broken)
    assert kept == ["09 09:15:00"]
