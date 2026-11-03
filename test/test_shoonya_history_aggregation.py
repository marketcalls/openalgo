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

    def __init__(self, native, minute):
        self.native = native
        self.minute = minute
        self.calls = []

    def __call__(self, endpoint, auth, payload=None):
        self.calls.append(payload)
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


def _history(monkeypatch, native, minute, interval, start, end):
    import broker.shoonya.api.data as shoonya_data

    fake = _FakeTPSeries(native, minute)
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
