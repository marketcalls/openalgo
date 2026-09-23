"""Broker quote fan-outs: one shared pool under gthread, a pool per call elsewhere.

IIFL Capital's open interest fan-out, TradeSmart's REST quote fallback and
Nubra's REST quote fan-out each built a ThreadPoolExecutor per call, up to 32,
90 and 5 threads. Under eventlet those are green threads and cost nothing.
Under the gthread worker they are real OS threads, outside the request pool,
created and torn down on every request and multiplied by every option chain
refreshing at once.

Under gthread each now submits to one named, process-wide pool from
``utils.shared_executors``: the thread count is bounded by the pool, and a
second request starts no new threads. Under eventlet and the dev server the
per-call pool is kept exactly as it was.
"""

from __future__ import annotations

import threading
import time

import pytest

from utils import runtime, shared_executors


@pytest.fixture(autouse=True)
def _fresh_pools():
    shared_executors.shutdown_all()
    yield
    shared_executors.shutdown_all()


@pytest.fixture
def gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)


@pytest.fixture
def not_gthread(monkeypatch):
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)


class PeakThreads:
    """Samples threading.active_count() while a block runs."""

    def __enter__(self):
        self._stop = threading.Event()
        self.peak = 0
        self._sampler = threading.Thread(target=self._sample, daemon=True)
        self._sampler.start()
        time.sleep(0.02)
        self.baseline = threading.active_count()
        return self

    def _sample(self):
        while not self._stop.is_set():
            self.peak = max(self.peak, threading.active_count())
            time.sleep(0.002)

    def __exit__(self, *exc):
        self._stop.set()
        self._sampler.join(2)

    @property
    def added(self) -> int:
        return self.peak - self.baseline


def _slow(result):
    def fetch(*args, **kwargs):
        time.sleep(0.02)
        return result(*args, **kwargs) if callable(result) else result

    return fetch


# --- IIFL Capital open interest ------------------------------------------------


def _iifl(monkeypatch):
    from broker.iiflcapital.api import data

    monkeypatch.setattr(data.BrokerData, "_fetch_openinterest", _slow(7))
    legs = [{"exchange": "NSEFO", "instrumentId": str(i)} for i in range(60)]
    return data, data.BrokerData("tok"), legs


def test_iifl_oi_fanout_uses_one_bounded_pool_under_gthread(gthread, monkeypatch):
    data, broker, legs = _iifl(monkeypatch)

    with PeakThreads() as first:
        oi = broker._fetch_openinterest_map(legs)
    assert len(oi) == 60 and set(oi.values()) == {7}
    assert first.added <= data._OI_SHARED_WORKERS

    with PeakThreads() as second:
        broker._fetch_openinterest_map(legs)
    assert second.added <= 0, "a second option chain must not start new threads"
    assert "iifl-open-interest" in shared_executors.executor_stats()


def test_iifl_oi_fanout_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, legs = _iifl(monkeypatch)
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )

    with PeakThreads() as run:
        oi = broker._fetch_openinterest_map(legs)

    assert len(oi) == 60
    assert run.added > data._OI_SHARED_WORKERS, "the per-call fan-out width is unchanged"


# --- TradeSmart REST quote fallback --------------------------------------------


def _tradesmart(monkeypatch):
    from broker.tradesmart.api import data

    monkeypatch.setattr(data, "get_token", lambda symbol, exchange: symbol[3:])
    monkeypatch.setattr(data.BrokerData, "_extend_from_stream", lambda self, prep, res: prep)
    monkeypatch.setattr(
        data.BrokerData,
        "_fetch_single_quote",
        _slow(lambda self, item: {"symbol": item["symbol"], "exchange": "NFO", "data": {}}),
    )
    symbols = [{"symbol": f"LEG{i}", "exchange": "NFO"} for i in range(82)]
    return data, data.BrokerData("uid:::tok"), symbols


def test_tradesmart_rest_fallback_uses_one_bounded_pool_under_gthread(gthread, monkeypatch):
    data, broker, symbols = _tradesmart(monkeypatch)

    with PeakThreads() as first:
        quotes = broker.get_multiquotes(symbols)
    assert len(quotes) == 82
    assert first.added <= data._REST_QUOTE_SHARED_WORKERS

    with PeakThreads() as second:
        broker.get_multiquotes(symbols)
    assert second.added <= 0


def test_tradesmart_rest_fallback_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, symbols = _tradesmart(monkeypatch)
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )

    with PeakThreads() as run:
        quotes = broker.get_multiquotes(symbols)

    assert len(quotes) == 82
    assert run.added > data._REST_QUOTE_SHARED_WORKERS


# --- Nubra REST quote fan-out --------------------------------------------------


def _nubra(monkeypatch):
    from broker.nubra.api import data

    monkeypatch.setattr(
        data.BrokerData, "get_quotes", _slow(lambda self, symbol, exchange: {"ltp": 1.0})
    )
    symbols = [{"symbol": f"S{i}", "exchange": "NSE"} for i in range(20)]
    return data, data.BrokerData("tok"), symbols


def test_nubra_fanout_reuses_one_pool_under_gthread(gthread, monkeypatch):
    data, broker, symbols = _nubra(monkeypatch)

    with PeakThreads() as first:
        quotes = broker._get_multiquotes_sequential(symbols)
    assert len(quotes) == 20
    assert first.added <= data._QUOTE_FANOUT_WORKERS

    with PeakThreads() as second:
        broker._get_multiquotes_sequential(symbols)
    assert second.added <= 0


def test_nubra_fanout_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, symbols = _nubra(monkeypatch)
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )
    assert len(broker._get_multiquotes_sequential(symbols)) == 20
