"""A sandbox order fills once, on its current terms (gthread audit trading-01).

The same resting order reaches the fill path from the websocket dispatch
thread, the polling engine, its fallback thread and a request placing a
marketable order. The fill used to be a check (no trade yet for this order)
followed by an insert and a status write on the caller's copy of the order,
so two of those could both pass the check: two trades for one order, and a
position and margin twice the order's size. The order row is now the claim,
one conditional UPDATE only one caller can win.

The same write-from-a-copy shape let a Stop-Loss release put "open" back on an
order that had just been cancelled, and let a fill decided on an order's old
price land after a modify had changed it.
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

USER = "gthread_sandbox_fills"
QTY = 10
LIMIT = Decimal("2500.00")


@pytest.fixture(autouse=True)
def fresh_account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from sandbox.execution_engine import ExecutionEngine

    # Placement checks marketability against a live quote; keep it above the
    # limit so the BUY rests.
    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600))
    yield
    release_sessions()


def _place(**overrides):
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": QTY,
        "price": float(LIMIT),
        "price_type": "LIMIT",
        "product": "CNC",
    }
    order.update(overrides)
    ok, response, _ = run_in_thread(lambda: OrderManager(USER).place_order(order))
    assert ok, response
    return response["orderid"]


def _counts(orderid):
    from database.sandbox_db import SandboxOrders, SandboxPositions, SandboxTrades, db_session

    db_session.remove()
    trades = SandboxTrades.query.filter_by(orderid=orderid).count()
    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    position = SandboxPositions.query.filter_by(user_id=USER, symbol="RELIANCE").first()
    result = {
        "trades": trades,
        "status": order.order_status,
        "price": order.price,
        "position": position.quantity if position else 0,
        "position_margin": position.margin_blocked if position else Decimal("0"),
    }
    db_session.remove()
    return result


def test_one_order_fills_once_under_two_threads(monkeypatch):
    from database.sandbox_db import SandboxOrders
    from sandbox.execution_engine import ExecutionEngine

    orderid = _place()
    barrier = threading.Barrier(2)
    real_trade_id = ExecutionEngine._generate_trade_id

    def trade_id_after_both_decided(self):
        # Both threads have decided to fill before either writes anything.
        barrier.wait(10)
        return real_trade_id(self)

    monkeypatch.setattr(ExecutionEngine, "_generate_trade_id", trade_id_after_both_decided)

    def fill():
        order = SandboxOrders.query.filter_by(orderid=orderid).first()
        ExecutionEngine()._process_order(order, quote(2490))

    run_in_threads([fill, fill])

    state = _counts(orderid)
    assert state["trades"] == 1
    assert state["status"] == "complete"
    assert state["position"] == QTY
    funds = funds_of(USER)
    assert funds["used"] == QTY * LIMIT
    assert funds["available"] + funds["used"] == CAPITAL


def test_a_stop_loss_release_cannot_reopen_a_cancelled_order():
    """The trigger-pending to open move must not overwrite a cancel.

    The engine holds the order as it loaded it, still "trigger pending". A
    cancel on another thread commits and releases the margin. The release
    then wrote "open" from its copy, leaving a live order with no margin
    behind it.
    """
    from database.sandbox_db import SandboxOrders, db_session
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.order_manager import OrderManager

    # BUY SL: trigger 2700 (LTP must rise to it), limit 2710. The quote at
    # placement (2600) is below the trigger, so it rests in the Stop-Loss book.
    orderid = _place(price_type="SL", trigger_price=2700, price=2710)

    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    assert order.order_status == "trigger pending"

    ok, response, _ = run_in_thread(lambda: OrderManager(USER).cancel_order(orderid))
    assert ok, response

    # Trigger met (2720 >= 2700) but the limit is not (2720 > 2710): release.
    ExecutionEngine()._process_trigger_pending_order(order, Decimal("2720"))
    db_session.remove()

    assert _counts(orderid)["status"] == "cancelled"


def test_a_modify_after_the_fill_was_decided_is_not_filled_at_the_old_terms():
    """A price change landing between the decision and the write stops the fill."""
    from database.sandbox_db import SandboxOrders, db_session
    from sandbox.execution_engine import ExecutionEngine
    from sandbox.order_manager import OrderManager

    orderid = _place()
    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    assert order.price == LIMIT  # decided at 2500

    ok, response, _ = run_in_thread(
        lambda: OrderManager(USER).modify_order(orderid, {"price": 2450})
    )
    assert ok, response

    ExecutionEngine()._execute_order(order, LIMIT)
    db_session.remove()

    state = _counts(orderid)
    assert state["trades"] == 0
    assert state["status"] == "open"
    assert state["price"] == Decimal("2450.00")


def test_a_single_fill_is_recorded_as_before():
    """The quiet path: one fill writes the order, trade, position and funds as always."""
    from database.sandbox_db import SandboxOrders, SandboxTrades, db_session
    from sandbox.execution_engine import ExecutionEngine

    orderid = _place()
    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    ExecutionEngine()._process_order(order, quote(2490))
    db_session.remove()

    order = SandboxOrders.query.filter_by(orderid=orderid).first()
    trade = SandboxTrades.query.filter_by(orderid=orderid).one()
    assert order.order_status == "complete"
    assert order.average_price == LIMIT
    assert order.filled_quantity == QTY
    assert order.pending_quantity == 0
    assert trade.quantity == QTY and trade.price == LIMIT and trade.action == "BUY"
    db_session.remove()

    state = _counts(orderid)
    assert state["position"] == QTY
    assert state["position_margin"] == QTY * LIMIT
    funds = funds_of(USER)
    assert funds["used"] == QTY * LIMIT
    assert funds["available"] == CAPITAL - QTY * LIMIT
