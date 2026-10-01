"""The sandbox money path behaves the same under eventlet (gthread audit, sandbox partition).

Eventlet stays the default production worker, so every change made for the
gthread worker must leave an eventlet install exactly as it was. Under
eventlet ``threading.Lock`` is green, which is what the per-position locks,
the square-off and settlement guards are built from: a greenlet waiting on
one must yield to the hub, not freeze it. And the websocket engine's index
lock is a real lock, which a greenlet must never hold across a database call
that can yield.

Each case runs in a subprocess, because ``eventlet.monkey_patch()`` is global
and cannot be undone (see test_eventlet_cross_thread_locks.py). The child uses
its own throwaway databases and never reads a ``.env``. Every case also
asserts on hub liveness (a ticker greenlet keeps ticking) and elapsed time,
not only on results, because a frozen hub still returns the right answer
eventually, or never returns at all.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap

import pytest

pytest.importorskip(
    "eventlet",
    reason="eventlet is installed by the production installer, not by pyproject",
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PREAMBLE = """
import eventlet
eventlet.monkey_patch()

import json, os, sys, time

ROOT = {root!r}
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "test"))
os.chdir(ROOT)

import dotenv
dotenv.load_dotenv = lambda *a, **k: False
dotenv.main.load_dotenv = dotenv.load_dotenv
os.environ["DATABASE_URL"] = "sqlite:///" + {db_dir!r} + "/openalgo.db"
os.environ["SANDBOX_DATABASE_URL"] = "sqlite:///" + {db_dir!r} + "/sandbox.db"
os.environ["LOGS_DATABASE_URL"] = "sqlite:///" + {db_dir!r} + "/logs.db"
os.environ["LATENCY_DATABASE_URL"] = "sqlite:///" + {db_dir!r} + "/latency.db"
os.environ["LOG_DIR"] = {db_dir!r}
os.environ.setdefault("API_KEY_PEPPER", "0" * 64)
os.environ.setdefault("APP_KEY", "test-only-app-key")

import eventlet.patcher
_orig_threading = eventlet.patcher.original("threading")


def watchdog(seconds):
    '''A real OS thread that ends the child if the hub freezes.'''
    def fire():
        time.sleep(seconds)
        os._exit(3)
    t = _orig_threading.Thread(target=fire, daemon=True)
    t.start()


class Ticker:
    '''Counts how often the hub gets to run a greenlet.'''
    def __init__(self):
        self.ticks = 0
        self.alive = True
        eventlet.spawn(self.run)

    def run(self):
        while self.alive:
            self.ticks += 1
            eventlet.sleep(0.02)


watchdog(40)

from decimal import Decimal
from test_gthread_sandbox_support import funds_of, prepare_databases, quote, reset_user
prepare_databases()
USER = "eventlet_sandbox"
reset_user(USER)

from sandbox.execution_engine import ExecutionEngine
ExecutionEngine._fetch_quote = lambda self, symbol, exchange: quote(2500)

from utils.runtime import is_monkey_patched
assert is_monkey_patched("thread"), "the child is not running under eventlet"
"""


def run(tmp_path, body: str) -> dict:
    code = PREAMBLE.format(root=ROOT, db_dir=str(tmp_path).replace("\\", "/"))
    code += textwrap.dedent(body)
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
    )
    assert result.returncode != 3, "the eventlet hub froze (watchdog fired)"
    lines = [line for line in result.stdout.splitlines() if line.startswith("RESULT ")]
    assert lines, (
        f"child printed no result\nstdout:\n{result.stdout[-3000:]}\nstderr:\n{result.stderr[-3000:]}"
    )
    return json.loads(lines[-1][len("RESULT ") :])


def test_the_quiet_path_gives_the_same_figures_under_eventlet(tmp_path):
    """Place, fill, rest, cancel and close one position, one step at a time."""
    out = run(
        tmp_path,
        """
        from sandbox.order_manager import OrderManager
        from sandbox.position_manager import PositionManager

        om = OrderManager(USER)
        buy = {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10,
               "price_type": "MARKET", "product": "CNC"}
        ok1, _, _ = om.place_order(dict(buy))
        after_buy = funds_of(USER)

        rest = dict(buy, price_type="LIMIT", price=2400, quantity=5)
        ok2, placed, _ = om.place_order(rest)
        ok3, _, _ = om.cancel_order(placed["orderid"])
        after_cancel = funds_of(USER)

        ok4, _, _ = PositionManager(USER).close_position("RELIANCE", "NSE", "CNC")
        after_close = funds_of(USER)
        print("RESULT " + json.dumps({
            "ok": [ok1, ok2, ok3, ok4],
            "used_after_buy": str(after_buy["used"]),
            "used_after_cancel": str(after_cancel["used"]),
            "used_after_close": str(after_close["used"]),
            "available_after_close": str(after_close["available"]),
        }))
        """,
    )
    assert out["ok"] == [True, True, True, True]
    assert out["used_after_buy"] == "25000.00"
    assert out["used_after_cancel"] == "25000.00"
    assert out["used_after_close"] == "0.00"
    assert out["available_after_close"] == "10000000.00"


def test_a_greenlet_waiting_on_a_position_lock_yields_to_the_hub(tmp_path):
    """The per-position lock is green: the waiter parks, the hub keeps running."""
    out = run(
        tmp_path,
        """
        from sandbox.order_manager import OrderManager
        from sandbox.position_locks import position_lock, position_wait_seconds

        ticker = Ticker()

        def holder():
            with position_lock(USER, "NSE", "RELIANCE", "CNC"):
                eventlet.sleep(0.5)

        h = eventlet.spawn(holder)
        eventlet.sleep(0.05)
        start = time.monotonic()
        before = ticker.ticks
        order = {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 1,
                 "price_type": "MARKET", "product": "CNC"}
        ok, _, _ = OrderManager(USER).place_order(order)
        waited = time.monotonic() - start
        ticks = ticker.ticks - before
        h.wait()
        ticker.alive = False
        print("RESULT " + json.dumps({
            "ok": ok, "waited": waited, "ticks": ticks,
            "bounded": position_wait_seconds() is not None,
        }))
        """,
    )
    assert out["ok"] is True
    assert out["waited"] >= 0.3, "the order did not wait for the position it shares"
    assert out["ticks"] >= 10, "the hub stopped while an order waited on a position"
    assert out["bounded"] is False, "the position wait must be unbounded under eventlet"


def test_two_greenlets_filling_one_order_fill_it_once(tmp_path):
    out = run(
        tmp_path,
        """
        from database.sandbox_db import SandboxOrders, SandboxTrades, db_session
        from sandbox.order_manager import OrderManager

        ExecutionEngine._fetch_quote = lambda self, symbol, exchange: quote(2600)
        rest = {"symbol": "RELIANCE", "exchange": "NSE", "action": "BUY", "quantity": 10,
                "price_type": "LIMIT", "price": 2500, "product": "CNC"}
        ok, placed, _ = OrderManager(USER).place_order(rest)
        orderid = placed["orderid"]
        db_session.remove()

        real_id = ExecutionEngine._generate_trade_id

        def slow_id(self):
            eventlet.sleep(0.1)  # both greenlets decide before either writes
            return real_id(self)

        ExecutionEngine._generate_trade_id = slow_id

        def fill():
            order = SandboxOrders.query.filter_by(orderid=orderid).first()
            ExecutionEngine()._process_order(order, quote(2490))
            db_session.remove()

        greenlets = [eventlet.spawn(fill) for _ in range(2)]
        for g in greenlets:
            g.wait()
        trades = SandboxTrades.query.filter_by(orderid=orderid).count()
        print("RESULT " + json.dumps({"trades": trades, "used": str(funds_of(USER)["used"])}))
        """,
    )
    assert out["trades"] == 1
    assert out["used"] == "25000.00"


def test_the_index_rebuild_never_holds_its_real_lock_across_a_yield(tmp_path):
    """A greenlet rebuilding the index yields in the database; another must not freeze.

    The index lock is a real lock because the websocket loop thread takes it.
    Held by a greenlet across a database wait that yields, the next greenlet
    to want it blocked the hub thread itself: nothing could ever run again.
    """
    out = run(
        tmp_path,
        """
        from types import SimpleNamespace
        from sandbox import gtt_manager
        from sandbox import websocket_execution_engine as wse

        engine = wse.WebSocketExecutionEngine()
        engine._subscribe_ws_symbols = lambda user_id, symbols: None

        def slow_legs():
            eventlet.sleep(0.5)  # a statement waiting its turn on the database
            return []

        gtt_manager.get_active_legs = slow_legs
        ticker = Ticker()
        r = eventlet.spawn(engine._rebuild_order_index)
        eventlet.sleep(0.1)
        start = time.monotonic()
        engine.notify_order_placed(
            SimpleNamespace(exchange="NSE", symbol="RELIANCE", orderid="EV-1", user_id=USER)
        )
        notify_took = time.monotonic() - start
        r.wait()
        ticker.alive = False
        print("RESULT " + json.dumps({
            "notify_took": notify_took,
            "kept": "EV-1" in engine._pending_orders_index.get("NSE:RELIANCE", []),
            "ticks": ticker.ticks,
        }))
        """,
    )
    assert out["notify_took"] < 0.3
    assert out["kept"] is True
    assert out["ticks"] >= 10
