"""A Fyers history chunk with no candles is an answer, not an error.

Fyers answers a range with no candles (a holiday, a weekend, a contract not
yet listed) with ``{"s": "no_data", "candles": []}``. get_history treated any
status other than "ok" as a failure and retried it three times, sleeping
2 + 4 + 6 seconds and then 1 more, so every empty chunk cost about 13 seconds
(issue #2239). Network, database and the clock are all replaced here.
"""

import pandas as pd

import broker.fyers.api.data as data


def test_no_data_chunk_is_not_retried(monkeypatch):
    calls = []
    sleeps = []

    def fake_response(endpoint, auth, *args, **kwargs):
        calls.append(endpoint)
        return {"s": "no_data", "candles": [], "message": ""}

    monkeypatch.setattr(data, "get_br_symbol", lambda symbol, exchange: f"NSE:{symbol}-EQ")
    monkeypatch.setattr(data, "get_api_response", fake_response)
    monkeypatch.setattr(data.time, "sleep", sleeps.append)

    end = pd.Timestamp.now().normalize()
    df = data.BrokerData("token").get_history(
        "SBIN",
        "NSE",
        "5m",
        (end - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )

    assert df.empty
    assert len(calls) == 1
    assert sleeps == []


def test_error_chunk_is_still_retried(monkeypatch):
    calls = []

    def fake_response(endpoint, auth, *args, **kwargs):
        calls.append(endpoint)
        return {"s": "error", "message": "boom"}

    monkeypatch.setattr(data, "get_br_symbol", lambda symbol, exchange: f"NSE:{symbol}-EQ")
    monkeypatch.setattr(data, "get_api_response", fake_response)
    monkeypatch.setattr(data.time, "sleep", lambda s: None)

    end = pd.Timestamp.now().normalize()
    data.BrokerData("token").get_history(
        "SBIN",
        "NSE",
        "5m",
        (end - pd.Timedelta(days=3)).strftime("%Y-%m-%d"),
        end.strftime("%Y-%m-%d"),
    )

    assert len(calls) == 4
