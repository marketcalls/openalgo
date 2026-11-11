"""Fyers get_history asks for each chunk once (issue #2422).

A chunk Fyers answers with s="no_data" (a weekend, a holiday, dates before
listing) used to be retried three times with 2 + 4 + 6 s of sleep plus 1 s
more, and any other failure was skipped after the same wait, so a rejected
token or a bad symbol came back as an empty success.
"""

import pytest

import broker.fyers.api.data as fyers_data

NO_DATA = {"s": "no_data", "code": 200, "message": "", "candles": []}
BAD_SYMBOL = {"s": "error", "code": -300, "message": "Invalid symbol"}
BLANK_ERROR = {"s": "error", "message": ""}


def _ok(ts):
    return {"s": "ok", "code": 200, "message": "", "candles": [[ts, 1, 2, 0.5, 1.5, 100]]}


@pytest.fixture
def fyers(monkeypatch):
    """Return (run, calls, sleeps): run(replies, start, end) fetches 5m history."""
    calls, sleeps = [], []
    monkeypatch.setattr(fyers_data, "get_br_symbol", lambda symbol, exchange: "NSE:SBIN-EQ")
    monkeypatch.setattr(fyers_data.time, "sleep", sleeps.append)

    def run(replies, start="2026-11-07", end="2026-11-08"):
        queue = list(replies)

        def fake_response(endpoint, auth, *args, **kwargs):
            calls.append(endpoint)
            return queue.pop(0)

        monkeypatch.setattr(fyers_data, "get_api_response", fake_response)
        return fyers_data.BrokerData("token").get_history("SBIN", "NSE", "5m", start, end)

    return run, calls, sleeps


def test_no_data_chunk_is_empty_without_retry(fyers):
    run, calls, sleeps = fyers
    df = run([NO_DATA])
    assert df.empty
    assert len(calls) == 1
    assert sleeps == []


@pytest.mark.parametrize(
    "reply, reason",
    [(BAD_SYMBOL, "Invalid symbol"), (BLANK_ERROR, "Fyers gave no reason")],
)
def test_failed_chunk_raises_once_with_reason(fyers, reply, reason):
    run, calls, sleeps = fyers
    with pytest.raises(Exception, match=reason):
        run([reply])
    assert len(calls) == 1
    assert sleeps == []


def test_empty_chunk_then_data_returns_the_data(fyers):
    run, calls, sleeps = fyers
    df = run([NO_DATA, _ok(1767000000)], start="2026-08-01", end="2026-11-08")
    assert len(calls) == 2
    assert df["timestamp"].tolist() == [1767000000]
    assert sleeps == []


def test_failure_after_data_is_not_returned_as_partial_success(fyers):
    run, calls, _ = fyers
    with pytest.raises(Exception, match="Invalid symbol"):
        run([_ok(1762400000), BAD_SYMBOL], start="2026-08-01", end="2026-11-08")
    assert len(calls) == 2
