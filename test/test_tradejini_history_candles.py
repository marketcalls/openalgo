"""Tradejini history: every candle satisfies low <= open, close <= high.

/trading rejects the whole series over one bad bar ("History contains an
invalid candle"). Tradejini's chart API returned MCX GOLDPETAL30NOV26FUT 1m at
2026-10-27 09:00 with open=14328 below low=14334.
"""

import math

import pandas as pd

import broker.tradejini.api.data as tjdata
from broker.tradejini.api.data import BrokerData


def _repair(rows):
    return BrokerData._repair_candles(pd.DataFrame(rows), "MCX", "GOLDPETAL30NOV26FUT", "1m")


def _valid(row):
    return (
        all(math.isfinite(row[k]) for k in ("open", "high", "low", "close", "volume"))
        and row["high"] >= max(row["open"], row["close"], row["low"])
        and row["low"] <= min(row["open"], row["close"])
        and row["volume"] >= 0
    )


def test_open_below_low_widens_the_wick():
    out = _repair(
        [{"open": 14328.0, "high": 14426.0, "low": 14334.0, "close": 14365.0, "volume": 1033}]
    )
    row = out.iloc[0]
    assert row["open"] == 14328.0  # the traded open is kept
    assert row["low"] == 14328.0
    assert row["high"] == 14426.0
    assert row["close"] == 14365.0
    assert _valid(row)


def test_close_above_high_widens_the_wick():
    out = _repair([{"open": 100.0, "high": 101.0, "low": 99.0, "close": 102.0, "volume": 5}])
    assert out.iloc[0]["high"] == 102.0


def test_valid_candles_are_unchanged():
    rows = [{"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 10}]
    out = _repair(rows)
    assert out.iloc[0].to_dict() == rows[0]


def test_negative_volume_is_zeroed_and_missing_prices_dropped():
    out = _repair(
        [
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": -7},
            {"open": None, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 3},
        ]
    )
    assert len(out) == 1
    assert out.iloc[0]["volume"] == 0
    assert all(_valid(r) for _, r in out.iterrows())


def test_infinite_prices_are_dropped_and_infinite_volume_zeroed():
    inf = float("inf")
    out = _repair(
        [
            {"open": inf, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 3},
            {"open": 100.0, "high": 105.0, "low": -inf, "close": 101.0, "volume": 3},
            {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": inf},
        ]
    )
    assert len(out) == 1
    assert out.iloc[0]["volume"] == 0
    assert all(_valid(r) for _, r in out.iterrows())


class _Response:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


def test_bar_missing_a_price_is_not_drawn_at_zero(monkeypatch):
    """A missing price must stay missing so the repair drops the bar."""
    bars = [
        {"time": 1793332800, "open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0},
        {"time": 1793332860, "high": 106.0, "low": 96.0, "close": 102.0, "volume": 9},
        {"open": 100.0, "high": 105.0, "low": 95.0, "close": 101.0, "volume": 1},
    ]

    class _Client:
        def get(self, *args, **kwargs):
            return _Response({"s": "ok", "d": {"bars": bars}})

    monkeypatch.setattr(tjdata, "get_httpx_client", lambda: _Client())
    monkeypatch.setattr(tjdata, "get_api_key", lambda: "key")
    monkeypatch.setattr(tjdata, "get_br_symbol", lambda s, e: "FUTCOM_X_MCX_2026-11-30")

    broker = BrokerData.__new__(BrokerData)
    broker.auth_token = "token"
    ok, rows = broker._get_historical_data("X", "MCX", "1", 0, 1)

    assert ok
    assert len(rows) == 2  # the bar without a time is skipped
    assert math.isnan(rows[1]["open"])
    assert math.isnan(rows[0]["volume"])

    out = _repair(rows)
    assert len(out) == 1
    assert out.iloc[0]["open"] == 100.0
    assert out.iloc[0]["volume"] == 0
