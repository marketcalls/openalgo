"""PnL Tracker history fetches are shared across tabs for a short window (#1677)."""

import threading
import time

import pytest

import blueprints.pnltracker as pnltracker


@pytest.fixture
def fake_history(monkeypatch):
    calls = []

    def get_history(**kwargs):
        calls.append(kwargs["symbol"])
        time.sleep(0.05)
        return True, {"status": "success", "data": [{"timestamp": 1, "close": 100.0}]}, 200

    monkeypatch.setattr(pnltracker, "get_history", get_history)
    monkeypatch.setattr(pnltracker.history_rate_limiter, "wait", lambda: None)
    pnltracker._history_cache.clear()
    yield calls
    pnltracker._history_cache.clear()


def test_repeat_requests_hit_the_broker_once(fake_history):
    for _ in range(3):
        success, response, _ = pnltracker.fetch_intraday_history("SBIN", "NSE", "2026-11-02", "k")
        assert success and response["data"][0]["close"] == 100.0

    assert fake_history == ["SBIN"]


def test_concurrent_tabs_share_one_fetch(fake_history):
    threads = [
        threading.Thread(
            target=pnltracker.fetch_intraday_history, args=("SBIN", "NSE", "2026-11-02", "k")
        )
        for _ in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert fake_history == ["SBIN"]


def test_failures_are_not_cached(fake_history, monkeypatch):
    calls = []

    def failing(**kwargs):
        calls.append(kwargs["symbol"])
        return False, {"status": "error", "message": "rate limited"}, 429

    monkeypatch.setattr(pnltracker, "get_history", failing)
    pnltracker.fetch_intraday_history("SBIN", "NSE", "2026-11-02", "k")
    pnltracker.fetch_intraday_history("SBIN", "NSE", "2026-11-02", "k")

    assert len(calls) == 2


def test_symbols_and_days_are_cached_separately(fake_history):
    pnltracker.fetch_intraday_history("SBIN", "NSE", "2026-11-02", "k")
    pnltracker.fetch_intraday_history("INFY", "NSE", "2026-11-02", "k")
    pnltracker.fetch_intraday_history("SBIN", "NSE", "2026-11-03", "k")

    assert fake_history == ["SBIN", "INFY", "SBIN"]
