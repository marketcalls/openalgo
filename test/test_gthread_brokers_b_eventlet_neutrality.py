"""Under a real eventlet hub the brokers_b changes behave as main did.

The smart-order cache and symbol lock now come from utils.smart_order_guard,
whose cache takes a real lock and whose per-symbol locks are stdlib (green
under eventlet); the limiters and feed gates have bounds that apply only under
gthread. None of that may change what production sees today: under eventlet a
queue of smart orders still waits its turn however long it takes, a full
limiter still sleeps rather than refusing, and nothing blocks the hub.

eventlet.monkey_patch() is global and cannot be undone, so every case runs in
a subprocess, as test/test_eventlet_cross_thread_locks.py does, and asserts on
elapsed time and hub liveness as well as on results.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

REPO = Path(__file__).resolve().parents[1]

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.main.load_dotenv = dotenv.load_dotenv

import importlib, threading, time
from utils import runtime
assert runtime.worker_class() == "eventlet" and runtime.gthread_active() is False

ticks = [0]
def ticker():
    while True:
        ticks[0] += 1
        eventlet.sleep(0.01)
eventlet.spawn(ticker)
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
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(PREAMBLE) + textwrap.dedent(body)],
        cwd=str(REPO),
        env=env,
        capture_output=True,
        text=True,
        timeout=240,
    )


def _assert_ok(result):
    assert "OK" in result.stdout, result.stdout[-3000:] + result.stderr[-3000:]


@pytest.mark.parametrize("broker", ["zerodha", "upstox", "shoonya", "indmoney"])
def test_green_smart_orders_for_one_symbol_place_one_order(tmp_path, broker):
    """Eight greenlets, one symbol, a broker that takes 0.1s per order.

    Each waits for the one before it as long as it takes (no bound under
    eventlet), each reads the book the previous order left, and the hub keeps
    running throughout.
    """
    result = _run(
        tmp_path,
        f"""
        module = importlib.import_module("broker.{broker}.api.order_api")
        module._SMART_ORDER_LOCKS._max_wait = 0.01  # would refuse if it applied

        book, orders = {{}}, []

        def get_positions(auth, **kwargs):
            snapshot = dict(book)
            eventlet.sleep(0.02)  # a network round trip
            return snapshot

        class Res:
            status = status_code = 200

        def place_order_api(data, auth):
            eventlet.sleep(0.1)
            qty = int(data["quantity"])
            orders.append((data["action"], qty))
            book[data["symbol"]] = book.get(data["symbol"], 0) + (qty if data["action"] == "BUY" else -qty)
            return Res(), {{"status": "success"}}, str(len(orders))

        def get_open_position(symbol, exchange, product, auth):
            return str(module._get_cached_positions(auth).get(symbol, 0))

        module.get_positions = get_positions
        # A placeholder book is a successful read here; the plugin's check of
        # a real reply is pinned per broker in test_position_read_failure.py.
        module._position_book_ok = lambda _data: True
        module.place_order_api = place_order_api
        module.get_open_position = get_open_position

        order = {{"symbol": "SBIN", "exchange": "NSE", "product": "MIS", "pricetype": "MARKET",
                  "action": "BUY", "quantity": "10", "position_size": "10"}}
        started, ticks_before = time.monotonic(), ticks[0]
        pool = eventlet.GreenPool()
        results = [pool.spawn(module.place_smartorder_api, dict(order), "tok") for _ in range(8)]
        pool.waitall()
        elapsed = time.monotonic() - started

        assert orders == [("BUY", 10)], orders
        assert all(r.wait()[0] is None or r.wait()[0].status == 200 for r in results)
        assert len(module._SMART_ORDER_LOCKS) == 0
        assert ticks[0] - ticks_before > 10, "the hub stalled while smart orders queued"
        assert elapsed < 10, elapsed
        print("OK")
        """,
    )
    _assert_ok(result)


def test_a_full_limiter_still_sleeps_under_eventlet(tmp_path):
    """Upstox's full half-hour window: a green sleep, never a refusal."""
    result = _run(
        tmp_path,
        """
        from broker.upstox.api import rate_limiter as rl
        from broker.iiflcapital.api import rate_limiter as iifl
        from broker.indmoney.api import rate_limiter as indmoney
        from broker.tradesmart.api import rate_limiter as tradesmart

        slept = []
        for module in (rl, iifl, indmoney, tradesmart):
            module.time.sleep = slept.append  # the same time module, patched once

        limiter = rl.SlidingWindowLimiter("t", 1, 1, 1, kind="order")
        limiter.acquire()
        limiter.acquire()
        assert slept and slept[-1] > 1700, slept

        iifl._last_call_time = time.time() + 100
        iifl.apply_rate_limit("order")
        assert slept[-1] > 99

        indmoney._next_free["order"] = time.monotonic() + 100
        indmoney.apply_rate_limit("order")
        assert slept[-1] > 99

        lock, reserved = threading.Lock(), __import__("collections").deque()
        for _ in range(3):
            tradesmart._reserve_slot(lock, reserved, 100, 2)
        print("OK")
        """,
    )
    _assert_ok(result)


def test_the_feed_gates_and_pools_stay_out_of_the_way_under_eventlet(tmp_path):
    result = _run(
        tmp_path,
        """
        from concurrent.futures import ThreadPoolExecutor
        from broker.motilal.api import data as motilal
        from broker.iiflcapital.api import data as iifl
        from utils.shared_executors import executor_stats

        for _ in range(motilal._FEED_WAITERS_MAX):
            assert motilal._feed_waiters.acquire(timeout=1)
        gated = motilal._feed_gated()(lambda: "ran")
        assert gated() == "ran", "a gate applied outside gthread"

        with iifl._oi_pool(40) as pool:
            assert isinstance(pool, ThreadPoolExecutor) and pool._max_workers == 32
        assert pool._shutdown and executor_stats() == {}
        print("OK")
        """,
    )
    _assert_ok(result)
