"""Shoonya history: each day's last intraday bar is rebuilt from 1m bars (#2343).

When one TPSeries request spans more than one trading day, the last bar of
each day comes back with the next trading day's first 1m bar folded in. The
bars below are real SBIN NSE replies from 2026-10-30 to 2026-11-03: the 5m
30-10 15:25 bar came back with high=close=965.00, the 02-11 09:14 pre-open
price, against its own close of 961.85.
"""

from datetime import datetime, timedelta, timezone

import pandas as pd

from broker.shoonya.api.data import BrokerData

IST = timezone(timedelta(hours=5, minutes=30))
COLUMNS = ["timestamp", "open", "high", "low", "close", "volume", "oi"]


def _ts(text):
    return int(datetime.strptime(text, "%Y-%m-%d %H:%M").replace(tzinfo=IST).timestamp())


def _bars(rows):
    return pd.DataFrame(
        [[_ts(t), o, h, low, c, v, 0.0] for t, o, h, low, c, v in rows], columns=COLUMNS
    )


# Shoonya's 5m reply for 30-10 to 02-11, as sent (last bars contaminated)
SBIN_5M = _bars(
    [
        ("2026-10-30 15:20", 960.05, 960.05, 960.05, 960.05, 0.0),
        ("2026-10-30 15:25", 960.05, 965.0, 960.05, 965.0, 6971359.0),
        ("2026-11-02 09:15", 968.75, 976.4, 964.65, 976.35, 453904.0),
        ("2026-11-02 15:25", 985.0, 992.7, 985.0, 992.7, 9608879.0),
    ]
)

SBIN_1M = _bars(
    [
        ("2026-10-30 15:24", 960.05, 960.05, 960.05, 960.05, 2653.0),
        ("2026-10-30 15:25", 960.05, 960.05, 960.05, 960.05, 495.0),
        ("2026-10-30 15:26", 960.05, 960.05, 960.05, 960.05, 1201.0),
        ("2026-10-30 15:27", 960.05, 960.05, 960.05, 960.05, 10506.0),
        ("2026-10-30 15:28", 961.85, 961.85, 961.85, 961.85, 6959157.0),
        ("2026-10-30 15:29", 961.85, 961.85, 961.85, 961.85, 0.0),
        ("2026-11-02 09:14", 965.0, 965.0, 965.0, 965.0, 0.0),
        ("2026-11-02 09:15", 968.75, 973.75, 964.65, 973.7, 102611.0),
        ("2026-11-02 15:25", 985.0, 985.0, 985.0, 985.0, 3184.0),
        ("2026-11-02 15:26", 985.0, 985.0, 985.0, 985.0, 531.0),
        ("2026-11-02 15:27", 985.0, 985.0, 985.0, 985.0, 0.0),
        ("2026-11-02 15:28", 985.0, 985.0, 985.0, 985.0, 2357.0),
        ("2026-11-02 15:29", 987.0, 987.0, 987.0, 987.0, 9602870.0),
        ("2026-11-03 09:14", 992.7, 992.7, 992.7, 992.7, 0.0),
    ]
)


def _rebuild(bars, minute_bars=SBIN_1M):
    out = BrokerData._rebuild_day_last_bars(bars, minute_bars, "NSE", "SBIN", "5m")
    return {
        datetime.fromtimestamp(int(r.timestamp), IST).strftime("%Y-%m-%d %H:%M"): r
        for r in out.itertuples()
    }


def test_last_bar_of_each_day_loses_the_next_days_pre_open_price():
    out = _rebuild(SBIN_5M)
    first = out["2026-10-30 15:25"]
    assert (first.open, first.high, first.low, first.close) == (960.05, 961.85, 960.05, 961.85)
    assert first.volume == 6971359.0  # same as Shoonya's own bar volume
    second = out["2026-11-02 15:25"]
    assert (second.open, second.high, second.low, second.close) == (985.0, 987.0, 985.0, 987.0)
    assert second.volume == 9608942.0


def test_other_bars_are_left_as_shoonya_sent_them():
    out = _rebuild(SBIN_5M)
    assert len(out) == len(SBIN_5M)
    bar = out["2026-11-02 09:15"]
    assert (bar.open, bar.high, bar.low, bar.close, bar.volume) == (
        968.75,
        976.4,
        964.65,
        976.35,
        453904.0,
    )
    assert out["2026-10-30 15:20"].close == 960.05


def test_a_special_session_day_is_handled_like_any_other():
    # Sunday 01-02-2026 (Budget day) traded a full session; nothing assumes
    # which days or hours trade.
    bars = _bars(
        [
            ("2026-02-01 15:25", 1016.9, 1025.0, 1015.0, 1025.0, 100.0),
            ("2026-02-02 09:15", 1028.5, 1030.0, 1027.0, 1029.0, 50.0),
        ]
    )
    minute = _bars(
        [
            ("2026-02-01 15:25", 1016.9, 1018.0, 1015.0, 1017.0, 60.0),
            ("2026-02-01 15:29", 1017.0, 1020.0, 1016.0, 1019.8, 40.0),
            ("2026-02-02 09:14", 1025.0, 1025.0, 1025.0, 1025.0, 0.0),
        ]
    )
    out = _rebuild(bars, minute)
    sunday = out["2026-02-01 15:25"]
    assert (sunday.high, sunday.close, sunday.volume) == (1020.0, 1019.8, 100.0)


def test_a_day_without_1m_bars_keeps_the_bar_shoonya_sent():
    out = _rebuild(SBIN_5M, SBIN_1M[SBIN_1M["timestamp"] < _ts("2026-11-02 00:00")])
    assert out["2026-11-02 15:25"].close == 992.7
    assert out["2026-10-30 15:25"].close == 961.85


def test_empty_frames_pass_through():
    empty = pd.DataFrame(columns=COLUMNS)
    assert BrokerData._rebuild_day_last_bars(empty, SBIN_1M, "NSE", "SBIN", "5m").empty
    assert len(BrokerData._rebuild_day_last_bars(SBIN_5M, empty, "NSE", "SBIN", "5m")) == 4


def test_repair_window_skips_a_single_day_reply():
    one_day = SBIN_5M[SBIN_5M["timestamp"] < _ts("2026-10-31 00:00")]
    assert BrokerData._day_end_repair_window(one_day) is None
    assert BrokerData._day_end_repair_window(pd.DataFrame(columns=COLUMNS)) is None


def test_repair_window_covers_only_the_returned_span():
    start, end = BrokerData._day_end_repair_window(SBIN_5M)
    assert start == _ts("2026-10-30 15:25")  # first day's last bar
    assert end == _ts("2026-11-02 09:15") - 1  # just before the last day's first bar


class _FakeTPSeries:
    """Answers TPSeries like Shoonya: data only inside the bars it holds."""

    def __init__(self, native, minute, fail=None):
        self.native = native
        self.minute = minute
        self.fail = fail
        self.calls = []

    def __call__(self, endpoint, auth, payload=None):
        self.calls.append(payload)
        if self.fail and self.fail(payload):
            raise OSError("[WinError 10035] A non-blocking socket operation could not be completed")
        rows = self.minute if payload["intrv"] == "1" else self.native
        st, et = int(payload["st"]), int(payload["et"])
        hit = rows[(rows["timestamp"] >= st) & (rows["timestamp"] <= et)]
        if hit.empty:
            return {"stat": "Not_Ok", "emsg": 'Error Occurred : 5 "no data"'}
        return [
            {
                "stat": "Ok",
                "ssboe": str(int(r.timestamp)),
                "into": str(r.open),
                "inth": str(r.high),
                "intl": str(r.low),
                "intc": str(r.close),
                "intv": str(r.volume),
                "oi": "0",
            }
            for r in hit.itertuples()
        ]


def _history(monkeypatch, native, minute, interval, start, end, fail=None):
    import broker.shoonya.api.data as shoonya_data

    fake = _FakeTPSeries(native, minute, fail)
    monkeypatch.setattr(shoonya_data, "get_chart_api_response", fake)
    monkeypatch.setattr(shoonya_data, "get_br_symbol", lambda s, e: "SBIN-EQ")
    monkeypatch.setattr(shoonya_data, "get_token", lambda s, e: "3045")
    out = BrokerData("token").get_history("SBIN", "NSE", interval, start, end)
    return out, [c for c in fake.calls if c["intrv"] == "1"]


def test_long_request_fetches_1m_only_where_bars_exist(monkeypatch):
    # Five years requested, bars on two days: the old code asked for 1m in
    # 5-day chunks across all five years (about 365 calls).
    out, minute_calls = _history(monkeypatch, SBIN_5M, SBIN_1M, "5m", "2021-11-01", "2026-11-03")
    assert len(minute_calls) == 1
    assert int(minute_calls[0]["st"]) == _ts("2026-10-30 15:25")
    assert int(minute_calls[0]["et"]) == _ts("2026-11-02 09:15") - 1
    last = out[out["timestamp"] == _ts("2026-10-30 15:25")].iloc[0]
    assert (last["high"], last["close"]) == (961.85, 961.85)


def test_single_day_request_makes_no_1m_call(monkeypatch):
    out, minute_calls = _history(monkeypatch, SBIN_5M, SBIN_1M, "5m", "2026-10-30", "2026-10-30")
    assert minute_calls == []
    assert len(out) == 2


# Five trading days whose repair span is longer than one 5-day 1m chunk. The
# span starts at the first day's last bar (28-10 15:25), so the first chunk
# ends at 02-11 15:25:00 and the second starts at 15:25:01, inside the last
# bar of 02-11. Each day's last 5m bar comes back with the next day's 09:14
# price folded in, as TPSeries sends it.
_DAYS = [
    ("2026-10-28", 100.0),
    ("2026-10-29", 110.0),
    ("2026-10-30", 120.0),
    ("2026-11-02", 130.0),
    ("2026-11-03", 140.0),
]


def _boundary_bars():
    native, minute = [], []
    for i, (day, base) in enumerate(_DAYS):
        nxt = _DAYS[i + 1][1] + 5 if i + 1 < len(_DAYS) else None
        native.append((f"{day} 09:15", base, base + 1, base - 1, base, 10.0))
        top = max(base + 2, nxt) if nxt else base + 2
        native.append((f"{day} 15:25", base, top, base - 1, nxt or base + 2, 50.0))
        minute.append((f"{day} 09:14", base - 3, base - 3, base - 3, base - 3, 0.0))
        minute.append((f"{day} 09:15", base, base + 1, base - 1, base, 10.0))
        for m, close in (
            (25, base),
            (26, base + 1),
            (27, base - 1),
            (28, base + 2),
            (29, base + 2),
        ):
            minute.append((f"{day} 15:{m}", close, close, close, close, 10.0))
    return _bars(native), _bars(minute)


def test_a_failed_1m_chunk_keeps_the_affected_day_end_bar(monkeypatch):
    native, minute = _boundary_bars()
    boundary = _ts("2026-11-02 15:25")
    out, minute_calls = _history(
        monkeypatch,
        native,
        minute,
        "5m",
        "2026-10-28",
        "2026-11-03",
        fail=lambda p: p["intrv"] == "1" and int(p["st"]) == boundary + 1,
    )
    assert len(minute_calls) == 2
    bars = {
        datetime.fromtimestamp(int(r.timestamp), IST).strftime("%m-%d %H:%M"): r
        for r in out.itertuples()
    }
    # 02-11's last bar straddles the failed chunk: kept exactly as Shoonya sent
    # it rather than rebuilt from the 15:25 minute alone (close 130.0).
    kept = bars["11-02 15:25"]
    assert (kept.high, kept.close, kept.volume) == (145.0, 145.0, 50.0)
    # Days the first chunk covered in full are still repaired.
    for day, base in _DAYS[:3]:
        bar = bars[datetime.strptime(day, "%Y-%m-%d").strftime("%m-%d") + " 15:25"]
        assert (bar.high, bar.close) == (base + 2, base + 2)


def test_without_a_failure_every_day_end_bar_is_repaired(monkeypatch):
    native, minute = _boundary_bars()
    out, _ = _history(monkeypatch, native, minute, "5m", "2026-10-28", "2026-11-03")
    bars = {
        datetime.fromtimestamp(int(r.timestamp), IST).strftime("%m-%d %H:%M"): r
        for r in out.itertuples()
    }
    last = bars["11-02 15:25"]
    assert (last.high, last.close, last.volume) == (132.0, 132.0, 50.0)
