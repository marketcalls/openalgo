"""Cancel, modify and fill decide one resting order once (gthread audit trading-02).

A cancel checked the status on its copy of the order, set "cancelled" on that
copy and released the margin. Nothing was conditional on the row, so two
cancels of one order (cancel-all and a single cancel, the square-off job and
the user) both released the margin, and a cancel racing a fill released the
margin the new position still held while the fill's trade stood. A modify
could likewise rewrite the terms of an order that had already filled.

Each of these is now a conditional UPDATE on "open" or "trigger pending", the
same predicate as the fill claim, so only one of them acts on an order.
"""

from __future__ import annotations

import threading
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

USER = "gthread_sandbox_orders"
PRICE = Decimal("2500.00")


@pytest.fixture(autouse=True)
def fresh_account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from sandbox.execution_engine import ExecutionEngine

    # Keep the market above the limit so every BUY placed here rests.
    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600))
    yield
    release_sessions()


def _place(quantity, symbol="RELIANCE"):
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": symbol,
        "exchange": "NSE",
        "action": "BUY",
        "quantity": quantity,
        "price": float(PRICE),
        "price_type": "LIMIT",
        "product": "CNC",
    }
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(order))
    assert ok, response
    return response["orderid"]


def _order(orderid):
    from database.sandbox_db import SandboxOrders, SandboxTrades, db_session

    db_session.remove()
    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    state = {
        "status": order.order_status,
        "quantity": order.quantity,
        "trades": SandboxTrades.query.filter_by(orderid=orderid).count(),
    }
    db_session.remove()
    return state


def _position_margin():
    from database.sandbox_db import SandboxPositions, db_session

    db_session.remove()
    total = sum(
        Decimal(str(p.margin_blocked or 0))
        for p in SandboxPositions.query.filter_by(user_id=USER).all()
        if p.quantity != 0
    )
    db_session.remove()
    return total


def _pause_before_release(monkeypatch, barrier):
    """Make every margin release wait (briefly) for the other racer."""
    from sandbox.fund_manager import FundManager

    real_release = FundManager.release_margin

    def release_after_both_decided(self, *args, **kwargs):
        try:
            barrier.wait(2)
        except threading.BrokenBarrierError:
            # The other racer is held up behind this one, which is the fix.
            pass
        return real_release(self, *args, **kwargs)

    monkeypatch.setattr(FundManager, "release_margin", release_after_both_decided)


def test_two_cancels_of_one_order_release_its_margin_once(monkeypatch):
    from sandbox.order_manager import OrderManager

    target = _place(10)  # 25,000 margin
    _place(20, symbol="ZEEL")  # 50,000 more, so a second release is not refused
    _pause_before_release(monkeypatch, threading.Barrier(2))

    results = run_in_threads([lambda: OrderManager(USER).cancel_order(target) for _ in range(2)])

    assert sorted(r[0] for r in results) == [False, True], results
    loser = next(r for r in results if not r[0])
    assert loser[1]["message"] == "Cannot cancel order in cancelled status"
    funds = funds_of(USER)
    assert funds["used"] == 20 * PRICE
    assert funds["available"] == CAPITAL - 20 * PRICE


def test_a_cancel_racing_a_fill_leaves_one_outcome(monkeypatch):
    """Either the order filled and holds its margin, or it was cancelled and released it."""
    from database.sandbox_db import SandboxOrders
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.order_manager import OrderManager

    target = _place(10)
    barrier = threading.Barrier(2)
    _pause_before_release(monkeypatch, barrier)
    real_trade_id = ExecutionEngine._generate_trade_id

    def trade_id_after_both_decided(self):
        try:
            barrier.wait(2)
        except threading.BrokenBarrierError:
            pass
        return real_trade_id(self)

    monkeypatch.setattr(ExecutionEngine, "_generate_trade_id", trade_id_after_both_decided)

    def fill():
        order = SandboxOrders.query.filter_by(orderid=target).first()
        ExecutionEngine()._execute_order(order, PRICE)

    run_in_threads([fill, lambda: OrderManager(USER).cancel_order(target)])

    state = _order(target)
    funds = funds_of(USER)
    if state["trades"]:
        assert state["status"] == "complete"
        assert funds["used"] == 10 * PRICE == _position_margin()
    else:
        assert state["status"] == "cancelled"
        assert funds["used"] == 0 == _position_margin()
    assert funds["available"] + funds["used"] == CAPITAL


def test_a_modify_cannot_rewrite_an_order_that_filled_meanwhile(monkeypatch):
    from database.sandbox_db import SandboxOrders
    from sandbox import order_manager
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.order_manager import OrderManager

    target = _place(10)
    real_symbol_info = order_manager.get_symbol_info
    fired = []

    def symbol_info_then_fill(symbol, exchange):
        # The modify has read the order as open; the fill lands now.
        if not fired:
            fired.append(1)

            def fill():
                order = SandboxOrders.query.filter_by(orderid=target).first()
                ExecutionEngine()._execute_order(order, PRICE)

            run_in_thread(fill)
        return real_symbol_info(symbol, exchange)

    monkeypatch.setattr(order_manager, "get_symbol_info", symbol_info_then_fill)

    ok, response, status = OrderManager(USER).modify_order(target, {"quantity": 20})
    release_sessions()

    assert fired
    assert not ok and status == 400, response
    assert response["message"] == "Cannot modify order in complete status"
    state = _order(target)
    assert state["status"] == "complete"
    assert state["quantity"] == 10


def test_a_quiet_cancel_and_modify_behave_as_before():
    from sandbox.order_manager import OrderManager

    target = _place(10)
    ok, response, _ = OrderManager(USER).modify_order(target, {"quantity": 12, "price": 2450})
    assert ok and response["message"] == "Order modified successfully"
    release_sessions()
    assert _order(target)["quantity"] == 12

    ok, response, _ = OrderManager(USER).cancel_order(target)
    assert ok and response["message"] == "Order cancelled successfully"
    release_sessions()
    assert _order(target)["status"] == "cancelled"
    # The margin blocked at placement (10 x 2500) is what comes back: a modify
    # never re-blocked, and that is unchanged.
    funds = funds_of(USER)
    assert funds["used"] == 0
    assert funds["available"] == CAPITAL

    ok, response, status = OrderManager(USER).cancel_order(target)
    assert not ok and status == 400
    assert response["message"] == "Cannot cancel order in cancelled status"
