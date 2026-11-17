"""Sandbox engine locks are never held across waits (gthread audit trading-12, trading-13).

Four places held a lock while waiting on something that needed it, or on
something slow:

* A fill held the process-wide position lock while it told the websocket
  engine about the position, and that notice can subscribe to the feed, which
  waits up to twelve seconds for an acknowledgement. Every other sandbox fill
  in the process, including those on the websocket dispatch thread, waited.
* Stopping the engine held its thread lock while joining the upgrade watcher,
  which takes the same lock: the join could only time out, and the watcher,
  declared stopped, went on to act afterwards.
* Stopping the websocket engine held the singleton's lock while the engine
  joined its fallback thread, so asking whether the engine was running waited
  out the join.
* Rebuilding the order index read the database while holding a real lock, so
  under eventlet a greenlet waiting for the database's write lock could yield
  holding it and freeze the hub for the next caller.

And a fill asked for the engine through the getter that creates one, so every
fill in polling mode built a dormant engine.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal
from types import SimpleNamespace

import pytest
from test_gthread_sandbox_support import (
    prepare_databases,
    release_sessions,
    reset_user,
    run_in_thread,
    run_in_threads,
)

USER = "gthread_sandbox_lifecycle"


@pytest.fixture(autouse=True)
def fresh_account():
    prepare_databases()
    reset_user(USER)
    release_sessions()
    yield
    release_sessions()


def _fill(symbol, price):
    """A filled order as _update_position reads it."""
    return SimpleNamespace(
        user_id=USER,
        orderid=f"LIFE-{symbol}",
        symbol=symbol,
        exchange="NSE",
        product="CNC",
        action="BUY",
        quantity=1,
        margin_blocked=Decimal("0.00"),
        price_type="MARKET",
        strategy="",
        trigger_price=None,
    )


def _running_engine(monkeypatch):
    from sandbox import websocket_execution_engine as wse

    engine = wse.WebSocketExecutionEngine()
    engine._running = True
    monkeypatch.setattr(wse, "_websocket_execution_engine", engine)
    return engine


def test_a_fill_does_not_hold_the_position_lock_across_a_feed_subscribe(monkeypatch):
    from sandbox.execution_engine import ExecutionEngine

    engine = _running_engine(monkeypatch)
    subscribing = threading.Event()
    calls = []

    def slow_first_subscribe(user_id, symbols):
        calls.append(symbols)
        if len(calls) == 1:
            subscribing.set()
            time.sleep(2.0)  # the feed taking its time to acknowledge

    monkeypatch.setattr(engine, "_subscribe_ws_symbols", slow_first_subscribe)

    def first_fill():
        ExecutionEngine()._update_position(_fill("RELIANCE", 2500), Decimal("2500"))

    def second_fill():
        assert subscribing.wait(5)
        started = time.monotonic()
        ExecutionEngine()._update_position(_fill("ZEEL", 200), Decimal("200"))
        return time.monotonic() - started

    _, elapsed = run_in_threads([first_fill, second_fill])
    _wait_for_feed_worker()
    assert elapsed < 1.0, f"the second fill waited {elapsed:.2f}s behind the first one's subscribe"
    assert len(calls) == 2


def test_a_fill_never_creates_an_engine(monkeypatch):
    from sandbox import websocket_execution_engine as wse
    from sandbox.execution_engine import ExecutionEngine

    monkeypatch.setattr(wse, "_websocket_execution_engine", None)
    run_in_thread(
        lambda: ExecutionEngine()._update_position(_fill("RELIANCE", 2500), Decimal("2500"))
    )
    assert wse._websocket_execution_engine is None


def test_asking_whether_the_engine_runs_does_not_wait_for_it_to_stop(monkeypatch):
    from sandbox import websocket_execution_engine as wse

    engine = _running_engine(monkeypatch)
    stopping = threading.Event()

    def slow_stop():
        stopping.set()
        time.sleep(1.0)  # joining the fallback thread
        engine._running = False

    monkeypatch.setattr(engine, "stop", slow_stop)

    stopper = threading.Thread(target=wse.stop_websocket_execution_engine, daemon=True)
    stopper.start()
    assert stopping.wait(5)
    started = time.monotonic()
    running = wse.is_websocket_execution_engine_running()
    elapsed = time.monotonic() - started
    stopper.join(5)

    assert running is False
    assert elapsed < 0.5, f"the question waited {elapsed:.2f}s for the stop"


def test_a_rebuild_holds_its_real_lock_only_to_merge(monkeypatch):
    from sandbox import gtt_manager
    from sandbox import websocket_execution_engine as wse

    engine = wse.WebSocketExecutionEngine()
    monkeypatch.setattr(engine, "_subscribe_ws_symbols", lambda user_id, symbols: None)
    reading = threading.Event()

    def slow_legs():
        reading.set()
        time.sleep(0.6)  # a statement waiting on the database
        return []

    monkeypatch.setattr(gtt_manager, "get_active_legs", slow_legs)

    rebuilder = threading.Thread(target=engine._rebuild_order_index, daemon=True)
    rebuilder.start()
    assert reading.wait(5)

    got = engine._lock.acquire(timeout=0.2)
    if got:
        engine._lock.release()
    # An order placed while the rebuild reads is kept by the merge.
    engine.notify_order_placed(
        SimpleNamespace(exchange="NSE", symbol="RELIANCE", orderid="LIFE-X1", user_id=USER)
    )
    rebuilder.join(5)

    assert got, "the rebuild held its real lock while it read the database"
    assert "LIFE-X1" in engine._pending_orders_index.get("NSE:RELIANCE", [])
    assert engine._user_symbol_refcounts[USER]["NSE:RELIANCE"] >= 1


def test_stopping_the_engine_does_not_wait_out_the_upgrade_watcher(monkeypatch):
    from sandbox import execution_thread as et
    from sandbox import websocket_execution_engine as wse

    real_sleep = time.sleep
    monkeypatch.setattr(
        et, "time", SimpleNamespace(sleep=lambda seconds: real_sleep(0.01), time=time.time)
    )
    in_check = threading.Event()
    proceed = threading.Event()

    def health_check_in_flight():
        in_check.set()
        proceed.wait(5)
        return True

    monkeypatch.setattr(et, "_is_websocket_proxy_healthy", health_check_in_flight)
    monkeypatch.setattr(
        wse, "start_websocket_execution_engine", lambda: (False, "not in this test")
    )

    class PollingEngine:
        name = "SandboxExecutionEngine"

        def is_alive(self):
            return True

        def stop(self):
            pass

        def join(self, timeout=None):
            pass

    monkeypatch.setattr(et, "_execution_thread", PollingEngine())
    monkeypatch.setattr(et, "_websocket_engine", None)
    monkeypatch.setattr(et, "_auto_upgrade_thread", None)
    monkeypatch.setattr(et, "_current_engine_type", "polling")

    et._start_websocket_upgrade_watcher()
    watcher = et._auto_upgrade_thread
    assert in_check.wait(5)

    def release_the_health_check_soon():
        real_sleep(0.2)
        proceed.set()

    threading.Thread(target=release_the_health_check_soon, daemon=True).start()
    started = time.monotonic()
    et.stop_execution_engine()
    elapsed = time.monotonic() - started
    watcher.join(5)

    assert elapsed < 2.0, f"stopping the engine waited {elapsed:.2f}s on its own watcher"
    assert not watcher.is_alive()
    assert et._auto_upgrade_thread is None


# Issue #2104. Placing, cancelling or filling a sandbox order used to call the
# proxy's subscribe or unsubscribe inline, and that waits up to 12 seconds for
# an acknowledgement. The order needs none of it, so the calls now run on one
# worker, in the order they were made.


def _slow_feed(monkeypatch, subscribe_delay=0.0, unsubscribe_delay=0.0):
    """Replace the proxy calls with recorders that take their time to acknowledge."""
    import database.auth_db as auth_db
    from sandbox import websocket_execution_engine as wse

    calls = []

    def recorder(kind, delay):
        def call(username, broker, symbols, mode):
            time.sleep(delay)  # the proxy taking its time to acknowledge
            calls.append((kind, [s["symbol"] for s in symbols]))
            return True, {}, 200

        return call

    monkeypatch.setattr(wse, "subscribe_to_symbols", recorder("subscribe", subscribe_delay))
    monkeypatch.setattr(wse, "unsubscribe_from_symbols", recorder("unsubscribe", unsubscribe_delay))
    monkeypatch.setattr(auth_db, "get_api_key_for_tradingview", lambda user_id: "test-key")
    monkeypatch.setattr(auth_db, "get_broker_name", lambda api_key: "zerodha")
    return calls


def _wait_for_feed_worker():
    """Return once every subscribe and unsubscribe queued so far has run."""
    from sandbox import websocket_execution_engine as wse

    wse._feed_executor.submit(lambda: None).result(timeout=10)


def _order(orderid, symbol="RELIANCE"):
    return SimpleNamespace(exchange="NSE", symbol=symbol, orderid=orderid, user_id=USER)


def test_placing_an_order_does_not_wait_for_the_feed_to_acknowledge(monkeypatch):
    engine = _running_engine(monkeypatch)
    calls = _slow_feed(monkeypatch, subscribe_delay=2.0)

    started = time.monotonic()
    run_in_thread(lambda: engine.notify_order_placed(_order("LIFE-W1")))
    elapsed = time.monotonic() - started
    _wait_for_feed_worker()

    assert elapsed < 1.5, f"placing the order waited {elapsed:.2f}s for the feed"
    assert calls == [("subscribe", ["RELIANCE"])]


@pytest.mark.parametrize("hook", ["order_completed", "position_opened", "gtt_placed"])
def test_no_order_path_hook_waits_for_the_feed(monkeypatch, hook):
    engine = _running_engine(monkeypatch)
    _slow_feed(monkeypatch, subscribe_delay=2.0, unsubscribe_delay=2.0)
    engine.notify_order_placed(_order("LIFE-W2"))
    _wait_for_feed_worker()
    gtt = SimpleNamespace(
        gtt_id="LIFE-G1",
        exchange="NSE",
        symbol="ZEEL",
        user_id=USER,
        legs=[SimpleNamespace(id=901, leg_status="pending")],
    )
    calls = {
        "order_completed": lambda: engine.notify_order_completed("LIFE-W2", "NSE:RELIANCE", USER),
        "position_opened": lambda: engine.notify_position_opened(USER, "ZEEL", "NSE"),
        "gtt_placed": lambda: engine.notify_gtt_placed(gtt),
    }

    started = time.monotonic()
    run_in_thread(calls[hook])
    elapsed = time.monotonic() - started
    _wait_for_feed_worker()

    assert elapsed < 1.5, f"notify_{hook} waited {elapsed:.2f}s for the feed"


def test_a_quick_place_then_cancel_unsubscribes_after_it_subscribes(monkeypatch):
    """The cancel's unsubscribe must not overtake the place's slower subscribe."""
    engine = _running_engine(monkeypatch)
    calls = _slow_feed(monkeypatch, subscribe_delay=0.5)

    def place_then_cancel():
        engine.notify_order_placed(_order("LIFE-W3"))
        engine.notify_order_completed("LIFE-W3", "NSE:RELIANCE", USER)

    run_in_thread(place_then_cancel)
    _wait_for_feed_worker()

    assert calls == [("subscribe", ["RELIANCE"]), ("unsubscribe", ["RELIANCE"])]


def test_a_cancel_racing_a_place_is_queued_after_it(monkeypatch):
    """The queue order is the refcount order, even when two threads interleave.

    The place takes the first reference and the cancel on another thread then
    releases it. The place's subscribe is held up until the cancel is done,
    which is where a call queued after the lock is released lets the cancel's
    unsubscribe go first and leaves the symbol subscribed with nothing in it.
    """
    engine = _running_engine(monkeypatch)
    calls = _slow_feed(monkeypatch)
    send_subscribe = engine._subscribe_ws_symbols
    cancelled = threading.Event()

    def subscribe_once_cancelled(user_id, symbols):
        cancelled.wait(5)
        send_subscribe(user_id, symbols)

    monkeypatch.setattr(engine, "_subscribe_ws_symbols", subscribe_once_cancelled)

    def cancel_once_placed():
        deadline = time.monotonic() + 5
        while USER not in engine._user_symbol_refcounts and time.monotonic() < deadline:
            time.sleep(0.005)
        engine.notify_order_completed("LIFE-W6", "NSE:RELIANCE", USER)
        cancelled.set()

    canceller = threading.Thread(target=cancel_once_placed, daemon=True)
    canceller.start()
    engine.notify_order_placed(_order("LIFE-W6"))
    canceller.join(10)
    _wait_for_feed_worker()

    assert calls == [("subscribe", ["RELIANCE"]), ("unsubscribe", ["RELIANCE"])]


def test_a_failed_subscribe_does_not_stop_the_next_one(monkeypatch):
    from sandbox import websocket_execution_engine as wse

    engine = _running_engine(monkeypatch)
    calls = _slow_feed(monkeypatch)
    recorded = wse.subscribe_to_symbols

    def fails_first(username, broker, symbols, mode):
        if not calls:
            calls.append(("failed", [s["symbol"] for s in symbols]))
            raise ConnectionError("the proxy is not reachable")
        return recorded(username, broker, symbols, mode)

    monkeypatch.setattr(wse, "subscribe_to_symbols", fails_first)
    engine.notify_order_placed(_order("LIFE-W4", "RELIANCE"))
    engine.notify_order_placed(_order("LIFE-W5", "ZEEL"))
    _wait_for_feed_worker()

    assert calls == [("failed", ["RELIANCE"]), ("subscribe", ["ZEEL"])]
