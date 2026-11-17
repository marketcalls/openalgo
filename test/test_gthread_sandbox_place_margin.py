"""A sandbox order that fails to place leaves no margin blocked (gthread audit trading-03).

Placing an order blocked its margin in one commit and wrote the order row in a
second. Anything that failed in between (an id clash on the insert, a database
error, an exception building the row) was rolled back by place_order's handler,
but the margin had already been committed: the funds stayed held with no order
to release them, and the trader's available balance fell for nothing.

The margin is now staged with the order, as the GTT paths already do, and both
land in the order's commit or neither does.
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

USER = "gthread_sandbox_place_margin"
QTY = 10
LIMIT = Decimal("2500.00")
TAKEN_ID = "26101299999999"


@pytest.fixture(autouse=True)
def fresh_account(monkeypatch):
    prepare_databases()
    reset_user(USER)
    release_sessions()
    from sandbox.execution_engine import ExecutionEngine

    # Keep the quote above the limit so the BUY rests and its margin stays
    # blocked on the order rather than moving to a position.
    monkeypatch.setattr(ExecutionEngine, "_fetch_quote", lambda self, symbol, exchange: quote(2600))
    yield
    reset_user(USER)
    release_sessions()


def _place(symbol="RELIANCE"):
    from sandbox.order_manager import OrderManager

    order = {
        "symbol": symbol,
        "exchange": "NSE",
        "action": "BUY",
        "quantity": QTY,
        "price": float(LIMIT),
        "price_type": "LIMIT",
        "product": "CNC",
    }
    return run_in_thread(lambda: OrderManager(USER).place_order(order))


def _store_order(orderid):
    from database.sandbox_db import SandboxOrders, db_session

    db_session.add(
        SandboxOrders(
            orderid=orderid,
            user_id=USER,
            symbol="RELIANCE",
            exchange="NSE",
            action="BUY",
            quantity=1,
            price_type="MARKET",
            product="CNC",
            order_status="complete",
            pending_quantity=0,
        )
    )
    db_session.commit()


def _orders():
    from database.sandbox_db import SandboxOrders, db_session

    db_session.remove()
    rows = [
        (row.orderid, row.order_status, row.margin_blocked)
        for row in SandboxOrders.query.filter_by(user_id=USER).all()
    ]
    db_session.remove()
    return rows


def _assert_untouched():
    funds = funds_of(USER)
    assert funds["available"] == CAPITAL, funds
    assert funds["used"] == Decimal("0"), funds


def test_an_insert_that_fails_blocks_no_margin(monkeypatch):
    """The order row cannot be written: here, its id is already taken."""
    from sandbox.order_manager import OrderManager

    run_in_thread(lambda: _store_order(TAKEN_ID))
    monkeypatch.setattr(OrderManager, "_generate_order_id", lambda self: TAKEN_ID)

    ok, response, status = _place()

    assert not ok and status == 500, response
    assert [orderid for orderid, _, _ in _orders()] == [TAKEN_ID]  # only the stored one
    _assert_untouched()


def test_a_failure_before_the_insert_blocks_no_margin(monkeypatch):
    """Anything raising between the margin and the order row."""
    from sandbox.order_manager import OrderManager

    def broken(self):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(OrderManager, "_generate_order_id", broken)

    ok, response, status = _place()

    assert not ok and status == 500, response
    assert _orders() == []
    _assert_untouched()


def test_a_placed_order_still_holds_its_margin():
    """The quiet path: the margin moves, and the order records what it holds."""
    ok, response, _ = _place()
    assert ok, response

    ((orderid, status, margin),) = _orders()
    assert orderid == response["orderid"]
    assert status == "open"
    assert margin > 0

    funds = funds_of(USER)
    assert funds["used"] == margin, funds
    assert funds["available"] == CAPITAL - margin, funds


def test_two_orders_for_the_last_funds_place_one_and_refuse_the_other():
    """Staging holds the funds write until the order commits; the loser must
    still be told plainly, not fail on a locked database.

    Different symbols, so the per-position lock does not serialise them and
    both pass the margin check before either has blocked anything.
    """
    margin = LIMIT * QTY
    reset_user(USER, capital=margin + Decimal("5000"))
    barrier = threading.Barrier(2)

    def place(symbol):
        def target():
            barrier.wait()
            return _place(symbol)

        return target

    results = run_in_threads([place("RELIANCE"), place("ZEEL")])
    for result in results:
        assert not isinstance(result, BaseException), result

    placed = [response for ok, response, _ in results if ok]
    refused = [(response, status) for ok, response, status in results if not ok]
    assert len(placed) == 1 and len(refused) == 1, results
    ((response, status),) = refused
    assert status == 400 and "Insufficient funds" in response["message"], response

    ((orderid, _, held),) = _orders()
    assert orderid == placed[0]["orderid"] and held == margin
    funds = funds_of(USER)
    assert funds["used"] == margin, funds
    assert funds["available"] == Decimal("5000"), funds
