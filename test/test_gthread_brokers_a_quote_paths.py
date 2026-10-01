"""Which quote fan-out Flattrade and Definedge run, and what it costs.

Both plugins carry two fan-outs for a multiquote batch: an asyncio one, which
cannot run under eventlet and so only ever ran on the dev server, and a thread
pool one, which is what production has always run. They chose between them
with ``USE_ASYNC = not <eventlet patched>``, which is True under the gthread
worker, so switching a server to gthread would have switched its quotes to a
path production never ran. For Definedge that path also skipped the shared
per-host limiter and its 429 retry, so two option chains at once got blank
quotes back.

The decided policy is ``USE_ASYNC = not (is_monkey_patched() or
gthread_active())``: eventlet and gthread on the thread pool, the dev server on
asyncio, as before. Each runtime is tested in a child process, because the
flag is fixed at import.

The thread pool itself was built per call, which under gthread starts real OS
threads for every batch of every request; it is now one shared pool per
plugin. And Definedge's open-interest cache, keyed by contract and never
evicted, is now bounded.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[1]


#: A child reads no .env. utils.config calls load_dotenv(override=True) at
#: import, which would replace the isolated settings a test passes the child
#: with the installation's own; test/conftest.py does the same in this process.
NO_DOTENV = (
    "import dotenv\n"
    "dotenv.load_dotenv = lambda *args, **kwargs: False\n"
    "dotenv.main.load_dotenv = dotenv.load_dotenv\n"
)


def _no_dotenv(script: str) -> str:
    """Put NO_DOTENV into a child script, after eventlet's patch if it has one."""
    script = textwrap.dedent(script)
    marker = "eventlet.monkey_patch()\n"
    if marker in script:
        head, tail = script.split(marker, 1)
        return head + marker + NO_DOTENV + tail
    return NO_DOTENV + script


os.environ.setdefault("BROKER_API_KEY", "client:::key:::secret")

MODULES = ["broker.flattrade.api.data", "broker.definedge.api.data"]


def _child_env(tmp_path: Path) -> dict:
    env = dict(os.environ)
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    env.update(
        {
            "DATABASE_URL": f"sqlite:///{(db / 'openalgo.db').as_posix()}",
            "SANDBOX_DATABASE_URL": f"sqlite:///{(db / 'sandbox.db').as_posix()}",
            "LOGS_DATABASE_URL": f"sqlite:///{(db / 'logs.db').as_posix()}",
            "LATENCY_DATABASE_URL": f"sqlite:///{(db / 'latency.db').as_posix()}",
            "HEALTH_DATABASE_URL": f"sqlite:///{(db / 'health.db').as_posix()}",
            "LOG_DIR": str(tmp_path / "log"),
            "LOG_TO_FILE": "False",
            "API_KEY_PEPPER": "0" * 64,
            "APP_KEY": "test-only-app-key",
            "BROKER_API_KEY": "client:::key:::secret",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    return env


def _run_child(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", _no_dotenv(body)],
        cwd=str(REPO),
        env=_child_env(tmp_path),
        capture_output=True,
        text=True,
        timeout=180,
    )


def _eventlet_installed() -> bool:
    from importlib.util import find_spec

    return find_spec("eventlet") is not None


# --- USE_ASYNC under each runtime ------------------------------------------------


def test_the_dev_server_keeps_the_asyncio_fan_out(tmp_path):
    result = _run_child(
        tmp_path,
        f"""
        import importlib
        from utils import runtime
        assert runtime.worker_class() == "dev"
        for name in {MODULES!r}:
            assert importlib.import_module(name).USE_ASYNC is True, name
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


def test_the_gthread_worker_stays_on_the_thread_pool(tmp_path):
    """Before the policy USE_ASYNC was True here: an unrun path in production."""
    result = _run_child(
        tmp_path,
        f"""
        import importlib, sys, types

        # What gunicorn's gthread worker has loaded by the time it imports the
        # app. Stubs, because gunicorn does not import on Windows.
        for name in ("gunicorn", "gunicorn.workers", "gunicorn.workers.base",
                     "gunicorn.workers.gthread"):
            sys.modules.setdefault(name, types.ModuleType(name))

        from utils import runtime
        assert runtime.gthread_active() is True
        for name in {MODULES!r}:
            assert importlib.import_module(name).USE_ASYNC is False, name
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


@pytest.mark.skipif(not _eventlet_installed(), reason="eventlet is not installed (Windows dev)")
def test_eventlet_stays_on_the_thread_pool_as_on_main(tmp_path):
    result = _run_child(
        tmp_path,
        f"""
        import eventlet
        eventlet.monkey_patch()
        import importlib
        for name in {MODULES!r}:
            assert importlib.import_module(name).USE_ASYNC is False, name
        print("OK")
        """,
    )
    assert "OK" in result.stdout, result.stdout + result.stderr


# --- the shared pools -------------------------------------------------------------


def _quote_payload(request: httpx.Request) -> httpx.Response:
    if "piconnect.flattrade.in" in request.url.host:
        return httpx.Response(200, json={"stat": "Ok", "lp": "101.5", "v": "10"})
    return httpx.Response(200, json={"status": "SUCCESS", "ltp": "101.5", "volume": "10"})


class _Recorder:
    """An httpx transport that records each request's time and host."""

    def __init__(self, first_status: int | None = None):
        self.calls: list[tuple[float, str]] = []
        self.lock = threading.Lock()
        self.first_status = first_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self.lock:
            self.calls.append((time.monotonic(), request.url.host))
            first = len(self.calls) == 1
        if first and self.first_status is not None:
            return httpx.Response(self.first_status, headers={"Retry-After": "0.05"})
        return _quote_payload(request)


@pytest.fixture
def definedge(monkeypatch):
    from broker.definedge.api import data, rate_limiter

    monkeypatch.setattr(data, "USE_ASYNC", False)
    monkeypatch.setattr(data, "get_token", lambda symbol, exchange: f"T{symbol}")
    monkeypatch.setattr(rate_limiter, "_last_call_time", {})
    return data


def _patch_client(monkeypatch, recorder):
    import utils.httpx_client as httpx_client

    client = httpx.Client(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(httpx_client, "get_httpx_client", lambda: client)
    return client


def _symbols(count, exchange="NSE"):
    return [{"symbol": f"S{i}", "exchange": exchange} for i in range(count)]


def test_under_gthread_definedge_quotes_run_on_one_shared_pool(definedge, monkeypatch):
    from utils import runtime
    from utils.shared_executors import executor_stats

    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    recorder = _Recorder()
    _patch_client(monkeypatch, recorder)
    broker = definedge.BrokerData("key:::susertoken:::token")

    before = threading.active_count()
    for _ in range(3):
        results = broker._process_quotes_batch(_symbols(10))
        assert [r["data"]["ltp"] for r in results] == [101.5] * 10
    stats = executor_stats()["definedge-quotes"]
    assert stats["max_workers"] == definedge.QUOTE_POOL_SIZE
    # Three batches did not start three pools of threads.
    assert threading.active_count() - before <= definedge.QUOTE_POOL_SIZE


def test_definedge_concurrent_chains_stay_inside_the_per_host_pace(definedge, monkeypatch):
    """Two multiquote batches at once still share one clock per host."""
    recorder = _Recorder()
    _patch_client(monkeypatch, recorder)
    barrier = threading.Barrier(2)
    errors = []

    def chain():
        try:
            barrier.wait(10)
            definedge.BrokerData("key:::susertoken:::token")._process_quotes_batch(_symbols(10))
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)

    threads = [threading.Thread(target=chain) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(60)
    assert errors == []
    times = sorted(t for t, _host in recorder.calls)
    assert len(times) == 20
    busiest = max(sum(1 for t in times if start <= t < start + 1.0) for start in times)
    assert busiest <= 11, f"{busiest} requests to one host inside one second"


def test_definedge_retries_a_429_instead_of_blanking_the_quote(definedge, monkeypatch):
    recorder = _Recorder(first_status=429)
    _patch_client(monkeypatch, recorder)

    results = definedge.BrokerData("key:::susertoken:::token")._process_quotes_batch(_symbols(1))

    assert results[0].get("data", {}).get("ltp") == 101.5, results
    assert len(recorder.calls) == 2


def test_under_gthread_flattrade_quotes_run_on_one_shared_pool(monkeypatch):
    from broker.flattrade.api import data
    from broker.flattrade.api.rate_limit import SlidingWindowLimiter
    from utils import runtime
    from utils.shared_executors import executor_stats

    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(data, "USE_ASYNC", False)
    monkeypatch.setattr(data, "get_token", lambda symbol, exchange: f"T{symbol}")
    monkeypatch.setattr(data, "get_br_symbol", lambda symbol, exchange: f"{symbol}-EQ")
    limiter = SlidingWindowLimiter("data", max_per_second=1000, max_per_minute=100000)
    monkeypatch.setattr(data, "_apply_rate_limit", limiter.acquire)
    recorder = _Recorder()
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(data, "get_httpx_client", lambda: client)

    broker = data.BrokerData("susertoken")
    before = threading.active_count()
    for _ in range(3):
        results = broker._process_quotes_batch(_symbols(10))
        assert sorted(r["data"]["ltp"] for r in results) == [101.5] * 10
    stats = executor_stats()["flattrade-quotes"]
    assert stats["max_workers"] == data.QUOTE_POOL_SIZE
    assert threading.active_count() - before <= data.QUOTE_POOL_SIZE


def test_off_gthread_the_quote_fanouts_leave_no_threads_behind(definedge, monkeypatch):
    """Eventlet and the dev server keep main's pool per call: nothing outlives it."""
    from broker.flattrade.api import data as flattrade
    from broker.flattrade.api.rate_limit import SlidingWindowLimiter

    recorder = _Recorder()
    _patch_client(monkeypatch, recorder)
    monkeypatch.setattr(flattrade, "USE_ASYNC", False)
    monkeypatch.setattr(flattrade, "get_token", lambda symbol, exchange: f"T{symbol}")
    monkeypatch.setattr(flattrade, "get_br_symbol", lambda symbol, exchange: f"{symbol}-EQ")
    limiter = SlidingWindowLimiter("data", max_per_second=1000, max_per_minute=100000)
    monkeypatch.setattr(flattrade, "_apply_rate_limit", limiter.acquire)
    client = httpx.Client(transport=httpx.MockTransport(recorder))
    monkeypatch.setattr(flattrade, "get_httpx_client", lambda: client)

    before = threading.active_count()
    results = flattrade.BrokerData("susertoken")._process_quotes_batch(_symbols(10))
    assert sorted(r["data"]["ltp"] for r in results) == [101.5] * 10
    results = definedge.BrokerData("key:::susertoken:::token")._process_quotes_batch(_symbols(10))
    assert [r["data"]["ltp"] for r in results] == [101.5] * 10

    deadline = time.monotonic() + 5
    while threading.active_count() > before and time.monotonic() < deadline:
        time.sleep(0.05)
    assert threading.active_count() == before, "a quote fan-out left threads running"


# --- the OI cache -----------------------------------------------------------------


def test_definedge_oi_cache_is_bounded(definedge, monkeypatch):
    class _Response:
        status_code = 200
        text = "01012026091500,1,1,1,1,1,42"

    monkeypatch.setattr(definedge, "rate_limited_request", lambda *a, **k: _Response())
    monkeypatch.setattr(definedge, "_oi_cache", definedge.LockedTTLCache(maxsize=64, ttl=60))

    for token in range(500):
        assert definedge.fetch_latest_oi("NFO", str(token), "key") == 42
    assert len(definedge._oi_cache) <= 64


def test_definedge_oi_is_served_from_cache_within_its_ttl(definedge, monkeypatch):
    calls = []

    class _Response:
        status_code = 200
        text = "01012026091500,1,1,1,1,1,7"

    def fake_request(*args, **kwargs):
        calls.append(args)
        return _Response()

    monkeypatch.setattr(definedge, "rate_limited_request", fake_request)
    monkeypatch.setattr(definedge, "_oi_cache", definedge.LockedTTLCache(maxsize=64, ttl=60))

    assert definedge.fetch_latest_oi("NFO", "1", "key") == 7
    assert definedge.fetch_latest_oi("NFO", "1", "key") == 7
    assert len(calls) == 1
    assert definedge._OI_CACHE_MAXSIZE == 4096
