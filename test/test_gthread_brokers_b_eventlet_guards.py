"""Every eventlet guard in brokers_b takes the branch it took before, per runtime.

Shoonya and Zebu run a quote batch on asyncio or on a thread pool, and
Zerodha's streaming modules pick real or green threading primitives. Each used
to decide by importing eventlet to ask, or by testing ``"eventlet" in
sys.modules``, which flips as soon as anything imports eventlet in a process
nothing patched (the gthread worker keeps eventlet installed as the fallback).

The decided policy for the quote batch: asyncio only on the development
server. Eventlet keeps the thread pool (asyncio cannot run under its hub), and
the gthread worker takes the thread pool too until the asyncio path has been
soaked there. Under gthread that pool is the shared one, not a new pool of real
threads per batch.

Each runtime is set up in a subprocess, because monkey-patching and a
registered gunicorn worker are both process-wide and cannot be undone.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from importlib.util import find_spec
from pathlib import Path

import pytest

from utils import runtime, shared_executors

REPO = Path(__file__).resolve().parents[1]

QUOTE_MODULES = ["broker.shoonya.api.data", "broker.zebu.api.data"]
ZERODHA_STREAMING = [
    "broker.zerodha.streaming.zerodha_adapter",
    "broker.zerodha.streaming.zerodha_websocket",
]

PREAMBLE = """
import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.main.load_dotenv = dotenv.load_dotenv
"""

# A gunicorn gthread worker as utils.runtime sees it, without gunicorn (which
# does not install on Windows): register_gunicorn_worker reads the class's
# module to name the worker.
FAKE_GTHREAD_WORKER = """
import types
from utils import runtime

class ThreadWorker:
    pass

ThreadWorker.__module__ = "gunicorn.workers.gthread"
worker = ThreadWorker()
worker.cfg = types.SimpleNamespace(threads=64, workers=1, graceful_timeout=30)
runtime.register_gunicorn_worker(worker)
assert runtime.gthread_active() is True
"""


def _run(tmp_path: Path, body: str) -> subprocess.CompletedProcess:
    db = tmp_path / "db"
    db.mkdir(exist_ok=True)
    env = dict(os.environ)
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
            "BROKER_API_KEY": "test",
            "BROKER_API_SECRET": "test",
            "PYTHONPATH": str(REPO),
        }
    )
    env.pop("OPENALGO_WORKER_CLASS", None)
    script = textwrap.dedent(PREAMBLE) + textwrap.dedent(body)
    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )


def _assert_ok(result: subprocess.CompletedProcess):
    assert "OK" in result.stdout, result.stdout[-3000:] + result.stderr[-3000:]


def test_the_dev_server_runs_the_quote_batch_on_asyncio(tmp_path):
    result = _run(
        tmp_path,
        f"""
        import importlib, sys
        for name in {QUOTE_MODULES!r}:
            assert importlib.import_module(name).USE_ASYNC is True, name
        assert "eventlet" not in sys.modules
        print("OK")
        """,
    )
    _assert_ok(result)


def test_gthread_runs_the_quote_batch_on_the_shared_pool(tmp_path):
    result = _run(
        tmp_path,
        FAKE_GTHREAD_WORKER
        + f"""
import importlib, sys
from concurrent.futures import ThreadPoolExecutor
from utils.shared_executors import executor_stats
for name in {QUOTE_MODULES!r}:
    module = importlib.import_module(name)
    assert module.USE_ASYNC is False, name
    with module._quote_pool(5) as pool:
        assert isinstance(pool, ThreadPoolExecutor)
    with module._quote_pool(5) as again:
        assert again is pool, "a second batch must reuse the pool"
    assert not pool._shutdown, "the with block must not shut the shared pool down"
assert {{"shoonya-quotes", "zebu-quotes"}} <= set(executor_stats())
assert "eventlet" not in sys.modules
print("OK")
""",
    )
    _assert_ok(result)


def test_an_imported_but_unpatched_eventlet_changes_no_branch(tmp_path):
    """The gthread case: eventlet in sys.modules, nothing patched."""
    result = _run(
        tmp_path,
        f"""
        import importlib, sys, threading, types

        eventlet = types.ModuleType("eventlet")
        patcher = types.ModuleType("eventlet.patcher")
        patcher.is_monkey_patched = lambda name: False

        def original(name):
            raise AssertionError("original(%r) called on an unpatched process" % name)

        patcher.original = original
        eventlet.patcher = patcher
        sys.modules["eventlet"] = eventlet
        sys.modules["eventlet.patcher"] = patcher

        import websocket_proxy  # imports every streaming adapter, as the app does
        for name in {QUOTE_MODULES!r}:
            assert importlib.import_module(name).USE_ASYNC is True, name
        for name in {ZERODHA_STREAMING!r}:
            assert importlib.import_module(name)._real_threading is threading, name
        print("OK")
        """,
    )
    _assert_ok(result)


@pytest.mark.skipif(find_spec("eventlet") is None, reason="eventlet is not installed")
def test_under_eventlet_every_guard_takes_the_eventlet_branch(tmp_path):
    """What main did under gunicorn+eventlet, and still does."""
    result = _run(
        tmp_path,
        f"""
        import eventlet
        eventlet.monkey_patch()

        import importlib
        import eventlet.patcher as patcher
        from concurrent.futures import ThreadPoolExecutor

        original_threading = patcher.original("threading")
        for name in {QUOTE_MODULES!r}:
            module = importlib.import_module(name)
            assert module.USE_ASYNC is False, name
            with module._quote_pool(5) as pool:
                assert isinstance(pool, ThreadPoolExecutor)
            assert pool._shutdown, "eventlet keeps a pool of its own per batch"
        for name in {ZERODHA_STREAMING!r}:
            assert importlib.import_module(name)._real_threading is original_threading, name
        print("OK")
        """,
    )
    _assert_ok(result)


# --- The decision is also made at call time ---------------------------------


@pytest.fixture(params=QUOTE_MODULES)
def quotes(request, monkeypatch):
    import importlib

    module = importlib.import_module(request.param)
    monkeypatch.setenv("BROKER_API_KEY", "UID:::key")
    monkeypatch.setattr(module, "get_br_symbol", lambda symbol, exchange: symbol)
    monkeypatch.setattr(module, "get_token", lambda symbol, exchange: "22")
    monkeypatch.setattr(
        module.BrokerData,
        "_fetch_single_quote_sync",
        lambda self, symbol, exchange, api_exchange, token, api_key: {
            "symbol": symbol,
            "exchange": exchange,
            "data": {"ltp": 1.0},
        },
    )
    yield module
    shared_executors.shutdown_all()


def test_a_module_imported_before_the_worker_registered_still_uses_the_pool(quotes, monkeypatch):
    monkeypatch.setattr(quotes, "USE_ASYNC", True)
    monkeypatch.setattr(runtime, "gthread_active", lambda: True)
    monkeypatch.setattr(
        quotes.asyncio, "run", lambda *a, **k: pytest.fail("asyncio.run under gthread")
    )

    results = quotes.BrokerData("tok")._process_quotes_batch(
        [{"symbol": "SBIN", "exchange": "NSE"}, {"symbol": "INFY", "exchange": "NSE"}]
    )

    assert sorted(r["symbol"] for r in results) == ["INFY", "SBIN"]


def test_the_dev_server_still_takes_the_asyncio_path(quotes, monkeypatch):
    monkeypatch.setattr(quotes, "USE_ASYNC", True)
    monkeypatch.setattr(runtime, "gthread_active", lambda: False)
    ran = []

    def fake_run(coro):
        ran.append(coro)
        coro.close()
        return []

    monkeypatch.setattr(quotes.asyncio, "run", fake_run)
    quotes.BrokerData("tok")._process_quotes_batch([{"symbol": "SBIN", "exchange": "NSE"}])
    assert len(ran) == 1
