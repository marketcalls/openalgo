"""Flattrade intraday history opens each session at the pre-open discovered price.

TPSeries returns bars from before the session opens: a flat 09:14 bar on a
normal day, and 14:05 to 14:19 on Muhurat 2026 (session 14:20 to 15:30), some
stamped with seconds (14:14:05). Stored in Historify, one such bar made the
chart refuse every 15m page reaching back past that day ("Could not load older
history"). The bars are left out, and the session's first bar opens at the last
pre-open close, the exchange's opening price. The session open comes from
OpenAlgo's market calendar; with no calendar row every bar is kept as sent.
"""

from datetime import date, datetime
from unittest.mock import patch

from broker.flattrade.api import data as ft

MUHURAT = date(2026, 11, 8)
# 14:20 and 15:30 IST on 8 Nov 2026, as the shipped calendar holds them.
MUHURAT_TIMINGS = [{"exchange": "NSE", "start_time": 1794127800000, "end_time": 1794132000000}]
# 09:15 and 15:30 IST on 9 Nov 2026.
REGULAR_TIMINGS = [{"exchange": "NSE", "start_time": 1794195900000, "end_time": 1794218400000}]


def _bar(stamp, o, h, low, c, v=10):
    return {
        "time": stamp,
        "into": str(o),
        "inth": str(h),
        "intl": str(low),
        "intc": str(c),
        "intv": str(v),
        "oi": "0",
    }


def _timings(day):
    return {MUHURAT: MUHURAT_TIMINGS, date(2026, 11, 9): REGULAR_TIMINGS}.get(day, [])


def _history(bars, interval="1m", timings=_timings, exchange="NSE"):
    with (
        patch.object(ft, "get_api_response", return_value=bars),
        patch.object(ft, "get_token", return_value="3045"),
        patch.object(ft, "get_market_timings_for_date", side_effect=timings),
        patch.dict("os.environ", {"BROKER_API_KEY": "UID:::KEY"}),
    ):
        df = ft.BrokerData("token").get_history(
            "SBIN", exchange, interval, "2026-11-08", "2026-11-09"
        )
    return [
        (
            datetime.fromtimestamp(int(r.timestamp)).strftime("%d %H:%M:%S"),
            r.open,
            r.high,
            r.low,
            r.close,
            r.volume,
        )
        for r in df.itertuples()
    ]


# TPSeries answers newest first; these are SBIN's real 8 Nov 2026 bars.
MUHURAT_1M = [
    _bar("08-11-2026 14:21:00", 1022.95, 1023.0, 1020.0, 1020.15, 60619),
    _bar("08-11-2026 14:20:00", 1023.7, 1025.0, 1020.05, 1023.0, 124262),
    _bar("08-11-2026 14:19:00", 1023.2, 1023.2, 1023.2, 1023.2, 0),
    _bar("08-11-2026 14:14:05", 1023.2, 1023.2, 1023.2, 1023.2, 1039),
    _bar("08-11-2026 14:06:00", 1018.5, 1018.5, 1018.5, 1018.5, 2125),
    _bar("08-11-2026 14:05:00", 1024.95, 1018.5, 1018.5, 1018.5, 15721),
]


def test_muhurat_opens_at_the_discovered_price_without_pre_open_bars():
    assert _history(MUHURAT_1M) == [
        ("08 14:20:00", 1023.2, 1025.0, 1020.05, 1023.0, 124262),
        ("08 14:21:00", 1022.95, 1023.0, 1020.0, 1020.15, 60619),
    ]


def test_regular_day_opens_at_the_09_14_price():
    bars = [
        _bar("09-11-2026 09:16:00", 1029.0, 1030.0, 1028.0, 1029.5),
        _bar("09-11-2026 09:15:00", 1027.6, 1029.0, 1027.0, 1028.5),
        _bar("09-11-2026 09:14:00", 1030.0, 1030.0, 1030.0, 1030.0, 0),
    ]
    assert _history(bars) == [
        ("09 09:15:00", 1030.0, 1030.0, 1027.0, 1028.5, 10),
        ("09 09:16:00", 1029.0, 1030.0, 1028.0, 1029.5, 10),
    ]


def test_coarser_interval_uses_the_last_pre_open_close():
    bars = [
        _bar("08-11-2026 14:20:00", 1023.7, 1025.0, 1020.0, 1022.6, 375072),
        _bar("08-11-2026 14:10:00", 1018.5, 1023.2, 1018.5, 1023.2, 5353),
        _bar("08-11-2026 14:05:00", 1024.95, 1018.5, 1018.5, 1018.5, 26911),
    ]
    assert _history(bars, interval="5m") == [
        ("08 14:20:00", 1023.2, 1025.0, 1020.0, 1022.6, 375072)
    ]


def test_a_bar_running_past_the_open_is_moved_to_it_not_left_out():
    bars = [
        _bar("08-11-2026 14:30:00", 1015.3, 1021.0, 1015.3, 1020.4, 500),
        _bar("08-11-2026 14:15:00", 1023.2, 1025.0, 1015.0, 1016.0, 900),
    ]
    assert _history(bars, interval="15m") == [
        ("08 14:20:00", 1023.2, 1025.0, 1015.0, 1016.0, 900),
        ("08 14:30:00", 1015.3, 1021.0, 1015.3, 1020.4, 500),
    ]


def test_index_follows_its_exchange_session():
    bars = [
        _bar("09-11-2026 09:15:00", 25000.0, 25010.0, 24990.0, 25005.0, 0),
        _bar("09-11-2026 09:14:00", 24980.0, 24980.0, 24980.0, 24980.0, 0),
    ]
    assert _history(bars, exchange="NSE_INDEX") == [
        ("09 09:15:00", 24980.0, 25010.0, 24980.0, 25005.0, 0)
    ]


def test_a_day_the_calendar_does_not_cover_keeps_every_bar():
    bars = [
        _bar("09-11-2026 09:15:00", 101, 102, 100, 101),
        _bar("09-11-2026 09:14:00", 100, 100, 100, 100, 0),
    ]
    assert [row[0] for row in _history(bars, timings=lambda day: [])] == [
        "09 09:14:00",
        "09 09:15:00",
    ]


def test_a_calendar_read_failure_keeps_every_bar():
    def broken(day):
        raise RuntimeError("calendar unavailable")

    bars = [
        _bar("09-11-2026 09:15:00", 101, 102, 100, 101),
        _bar("09-11-2026 09:14:00", 100, 100, 100, 100, 0),
    ]
    assert [row[0] for row in _history(bars, timings=broken)] == ["09 09:14:00", "09 09:15:00"]


def test_daily_candles_are_untouched():
    bars = [
        {
            "time": "08-NOV-2026",
            "ssboe": "1794076200",
            "into": "1023.2",
            "inth": "1025",
            "intl": "1015.1",
            "intc": "1016",
            "intv": "1950983",
        }
    ]
    with (
        patch.object(ft, "get_api_response", return_value=bars),
        patch.object(ft, "get_token", return_value="3045"),
        patch.object(ft, "get_market_timings_for_date", side_effect=_timings),
        patch.dict("os.environ", {"BROKER_API_KEY": "UID:::KEY"}),
    ):
        df = ft.BrokerData("token").get_history("SBIN", "NSE", "D", "2026-11-08", "2026-11-08")
    assert df["open"].tolist() == [1023.2]
