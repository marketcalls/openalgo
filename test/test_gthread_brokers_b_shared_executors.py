"""Broker quote fan-outs: one shared pool under gthread, a pool per call elsewhere.

IIFL Capital's open interest fan-out, TradeSmart's REST quote fallback and
Nubra's REST quote fan-out each built a ThreadPoolExecutor per call, up to 32,
90 and 5 threads. Under eventlet those are green threads and cost nothing.
Under the gthread worker they are real OS threads, outside the request pool,
created and torn down on every request and multiplied by every option chain
refreshing at once.

Under gthread each now submits to one named, process-wide pool from
``utils.shared_executors``: the thread count is bounded by the pool, and a
second request reuses that pool. Under eventlet and the dev server the
per-call pool is kept exactly as it was.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

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


@pytest.fixture
def background_job():
    """Start an unrelated worker during a request, like the suite's scheduler."""
    stop = threading.Event()
    started = threading.Event()

    def job():
        started.set()
        stop.wait(10)

    with ThreadPoolExecutor(max_workers=1) as pool:

        def start():
            pool.submit(job)
            assert started.wait(5), "background job did not start"

        try:
            yield start
        finally:
            stop.set()


def _record_pools(monkeypatch, module, factory):
    """Observe real broker executors without counting unrelated scheduler threads."""
    original = getattr(module, factory)
    pools = []

    @contextmanager
    def recording(*args, **kwargs):
        with original(*args, **kwargs) as pool:
            pools.append(pool)
            yield pool

    monkeypatch.setattr(module, factory, recording)
    return pools


def _assert_shared_pool(pools, name, workers):
    assert len(pools) == 2
    first, second = pools
    assert first is second, "a second request must reuse the same executor"
    assert first is shared_executors.get_executor(name, workers)
    assert first._max_workers == workers
    # Workers start lazily: reuse need not mean zero additional threads if the
    # first request completed before the shared executor reached its capacity.
    assert 0 < len(first._threads) <= workers
    assert all(thread.is_alive() for thread in first._threads)


def _assert_per_call_pools(pools, workers):
    assert len(pools) == 2
    assert pools[0] is not pools[1], "off gthread each request owns its executor"
    for pool in pools:
        assert pool._max_workers == workers, "the per-call fan-out width is unchanged"
        assert pool._threads, "the fan-out did not execute any work"
        assert not any(thread.is_alive() for thread in pool._threads)


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
    pools = _record_pools(monkeypatch, data, "_oi_pool")

    for _ in range(2):
        oi = broker._fetch_openinterest_map(legs)
        assert len(oi) == 60 and set(oi.values()) == {7}

    _assert_shared_pool(pools, "iifl-open-interest", data._OI_SHARED_WORKERS)


def test_iifl_oi_fanout_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, legs = _iifl(monkeypatch)
    pools = _record_pools(monkeypatch, data, "_oi_pool")
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )

    for _ in range(2):
        oi = broker._fetch_openinterest_map(legs)
        assert len(oi) == 60 and set(oi.values()) == {7}

    _assert_per_call_pools(pools, 32)


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


@pytest.mark.parametrize("start_background_job", [False, True], ids=["idle", "background-job"])
def test_tradesmart_rest_fallback_uses_one_bounded_pool_under_gthread(
    gthread, monkeypatch, background_job, start_background_job
):
    data, broker, symbols = _tradesmart(monkeypatch)
    pools = _record_pools(monkeypatch, data, "_rest_quote_pool")

    quotes = broker.get_multiquotes(symbols)
    assert len(quotes) == 82

    if start_background_job:

        def pending_with_job(self, prep, res):
            background_job()
            return prep

        monkeypatch.setattr(data.BrokerData, "_extend_from_stream", pending_with_job)

    assert len(broker.get_multiquotes(symbols)) == 82
    _assert_shared_pool(pools, "tradesmart-rest-quotes", data._REST_QUOTE_SHARED_WORKERS)


def test_tradesmart_rest_fallback_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, symbols = _tradesmart(monkeypatch)
    pools = _record_pools(monkeypatch, data, "_rest_quote_pool")
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )

    for _ in range(2):
        quotes = broker.get_multiquotes(symbols)
        assert len(quotes) == 82

    _assert_per_call_pools(pools, 82)


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
    pools = _record_pools(monkeypatch, data, "_quote_fanout_pool")

    for _ in range(2):
        quotes = broker._get_multiquotes_sequential(symbols)
        assert len(quotes) == 20

    _assert_shared_pool(pools, "nubra-quotes", data._QUOTE_FANOUT_WORKERS)


def test_nubra_fanout_keeps_its_own_pool_outside_gthread(not_gthread, monkeypatch):
    data, broker, symbols = _nubra(monkeypatch)
    pools = _record_pools(monkeypatch, data, "_quote_fanout_pool")
    monkeypatch.setattr(
        data, "get_executor", lambda *a: pytest.fail("shared pool used outside gthread")
    )
    for _ in range(2):
        assert len(broker._get_multiquotes_sequential(symbols)) == 20
    _assert_per_call_pools(pools, 5)
