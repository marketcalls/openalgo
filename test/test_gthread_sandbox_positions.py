"""One order at a time per sandbox position (gthread audit trading-17, rest-02).

Closing a position, the auto square-off, a smart order and a CNC sell all read
the position and then place an order sized from what they read, and a MARKET
order fills inside that same call. Two of them on one position, both reading
it before either order landed, acted on the same snapshot: two closers sold
the position twice and left it short, two exit alerts did the same through
the smart order path, and two CNC sells of the same shares both passed the
holdings check.

Each of those paths now holds a per-position lock from its read through its
order. The lock waits without limit under eventlet and on the development
server, as the code always did; only under the gthread worker is the wait
bounded, and a caller that runs out is told to try again.
"""

from __future__ import annotations

import threading
import time
from decimal import Decimal

import pytest
from test_gthread_sandbox_support import (
    CAPITAL,
    funds_of,
    prepare_databases,
    quote,
    release_sessions,
    reset_user,
    run_in_thread,
    run_in_threads,
)

USER = "gthread_sandbox_positions"
PRICE = Decimal("2500.00")


@pytest.fixture(autouse=True)
def fresh_account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from sandbox.execution_engine import ExecutionEngine

    monkeypatch.setattr(
        ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(PRICE)
    )
    yield
    release_sessions()


def _buy(quantity, symbol="RELIANCE"):
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": symbol,
        "exchange": "NSE",
        "action": "BUY",
        "quantity": quantity,
        "price_type": "MARKET",
        "product": "CNC",
    }
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(order))
    assert ok, response


def _state(symbol="RELIANCE"):
    from database.sandbox_db import SandboxPositions, SandboxTrades, db_session

    db_session.remove()
    position = SandboxPositions.query.filter_by(user_id=USER, symbol=symbol).first()
    sells = SandboxTrades.query.filter_by(user_id=USER, symbol=symbol, action="SELL").count()
    state = {"quantity": position.quantity if position else 0, "sells": sells}
    db_session.remove()
    return state


def _meet_before_placing(monkeypatch):
    """Both racers must have read the position before either places its order."""
    from sandbox.order_manager import OrderManager

    barrier = threading.Barrier(2)
    real_place = OrderManager.place_order

    def place_after_both_read(self, *args, **kwargs):
        try:
            barrier.wait(2)
        except threading.BrokenBarrierError:
            # The other racer is waiting on the position's lock: the fix.
            pass
        return real_place(self, *args, **kwargs)

    monkeypatch.setattr(OrderManager, "place_order", place_after_both_read)


def test_two_closers_do_not_reverse_the_position(monkeypatch):
    from sandbox.position_manager import PositionManager

    _buy(50)
    _meet_before_placing(monkeypatch)

    run_in_threads([lambda: PositionManager(USER).close_position("RELIANCE", "NSE", "CNC")] * 2)

    state = _state()
    assert state["quantity"] == 0
    assert state["sells"] == 1
    funds = funds_of(USER)
    assert funds["used"] == 0
    assert funds["available"] == CAPITAL


def test_two_cnc_sells_of_the_same_shares_cannot_both_pass(monkeypatch):
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.order_manager import OrderManager

    _buy(70)
    barrier = threading.Barrier(2)

    def quote_after_both_validated(self, symbol, exchange):
        # The MARKET sell prices itself after the holdings check.
        try:
            barrier.wait(2)
        except threading.BrokenBarrierError:
            pass
        return quote(PRICE)

    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", quote_after_both_validated)

    sell = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "SELL",
        "quantity": 70,
        "price_type": "MARKET",
        "product": "CNC",
    }
    results = run_in_threads([lambda: OrderManager(USER).place_order(dict(sell))] * 2)

    assert sorted(r[0] for r in results) == [False, True], results
    state = _state()
    assert state["quantity"] == 0
    assert state["sells"] == 1


def test_two_exit_smart_orders_do_not_reverse_the_position(monkeypatch):
    from services import sandbox_service

    _buy(50)
    monkeypatch.setattr(sandbox_service, "get_user_id_from_apikey", lambda api_key: USER)
    _meet_before_placing(monkeypatch)

    exit_alert = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "product": "CNC",
        "position_size": 0,
        "quantity": 0,
        "price_type": "MARKET",
    }
    results = run_in_threads(
        [lambda: sandbox_service.sandbox_place_smart_order(dict(exit_alert), "key", {})] * 2
    )

    messages = sorted(r[1].get("message", "") for r in results)
    assert "No OpenPosition Found. Not placing Exit order." in messages, results
    state = _state()
    assert state["quantity"] == 0
    assert state["sells"] == 1


def _hold_lock_in_background(symbol="RELIANCE", seconds=0.8):
    """Hold a position's lock on another thread for a while; return once it is held."""
    from sandbox.position_locks import position_lock

    held = threading.Event()

    def holder():
        with position_lock(USER, "NSE", symbol, "CNC"):
            held.set()
            time.sleep(seconds)

    thread = threading.Thread(target=holder, daemon=True)
    thread.start()
    assert held.wait(5)
    return thread


def test_the_wait_is_bounded_only_under_gthread(monkeypatch):
    from sandbox import position_locks
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price_type": "MARKET",
        "product": "CNC",
    }

    # gthread: refused with a sentence once the (shortened) wait runs out.
    monkeypatch.setattr(position_locks, "gthread_active", lambda: True)
    monkeypatch.setattr(position_locks, "POSITION_LOCK_WAIT_SECONDS", 0.2)
    holder = _hold_lock_in_background(seconds=1.0)
    started = time.monotonic()
    ok, response, status = run_in_thread(lambda: OrderManager(USER).place_order(dict(order)))
    assert time.monotonic() - started < 0.9
    assert not ok and status == 409
    assert response["message"].startswith("Another order for RELIANCE is still being processed")
    holder.join(5)

    # Anything else: waits as long as it takes, then goes through.
    monkeypatch.setattr(position_locks, "gthread_active", lambda: False)
    holder = _hold_lock_in_background(seconds=0.5)
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(dict(order)))
    assert ok, response
    holder.join(5)


def test_orders_on_different_positions_do_not_wait_for_each_other():
    from sandbox.order_manager import OrderManager

    holder = _hold_lock_in_background(symbol="RELIANCE", seconds=1.5)
    order = {
        "symbol": "ZEEL",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": 1,
        "price_type": "MARKET",
        "product": "CNC",
    }
    started = time.monotonic()
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(order))
    assert ok, response
    assert time.monotonic() - started < 1.0
    holder.join(5)


def test_the_lock_registry_forgets_positions_nobody_holds():
    from sandbox.position_locks import held_position_count
    from sandbox.position_manager import PositionManager

    _buy(5)
    run_in_thread(lambda: PositionManager(USER).close_position("RELIANCE", "NSE", "CNC"))
    assert held_position_count() == 0
