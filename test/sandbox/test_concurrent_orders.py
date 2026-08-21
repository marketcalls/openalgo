#!/usr/bin/env python3
"""
Regression test for issue #1808 -- concurrent same-symbol sandbox orders
silently lose a position increment.

Before the fix, `ExecutionEngine._update_position` did a read-modify-write on
`SandboxPositions` with no Python-level lock and no SQL-level SELECT ... FOR
UPDATE. SQLite does not support SELECT FOR UPDATE, so the two concurrent fills
could both snapshot the same `position.quantity`, each compute
`old + its_own_delta`, and both write the result back -- last writer wins and
one increment is silently lost. Both orderbook rows still showed `complete`,
so the position book and the orderbook disagreed with no surface signal.

After the fix, a class-level `threading.Lock` around the RMW serializes the
two fills; both increments persist.

The test invokes `_update_position` directly from two threads released by a
`threading.Barrier`. The barrier is what makes the race actually happen: under
CPython the GIL releases between bytecode boundaries, so without the barrier
the two threads tend to be serialized by the interpreter before they reach
the critical section and the bug would not manifest.

Run: uv run python test/sandbox/test_concurrent_orders.py
"""

import sys
import threading
from concurrent.futures import ThreadPoolExecutor, wait
from decimal import Decimal
from types import SimpleNamespace

from database.sandbox_db import (
    SandboxFunds,
    SandboxPositions,
    db_session,
    init_db,
)
from sandbox.execution_engine import ExecutionEngine

USER_ID = "concurrency_1808"
SYMBOL = "RELIANCE"
EXCHANGE = "NSE"
PRODUCT = "CNC"
START_BALANCE = Decimal("10000000.00")
PER_ORDER_QTY = 10
EXEC_PRICE = Decimal("2500.00")
# Margin the BUY would have blocked. Picked so the user has plenty of headroom
# against the seeded ₹1 Cr balance and so the per-position margin_blocked
# accounting lands on a round number after both fills.
PER_ORDER_MARGIN = Decimal("50000.00")
# Pre-existing long position so both concurrent fills go through the
# "update existing" branch (issue #1808, Path 2). Without a pre-seeded row
# both fills take the "create new" branch and the second one trips the
# UniqueConstraint, which is the *loud* failure mode but not the dangerous
# one; the silent lost-update only happens once a position already exists.
SEED_QTY = 5


def _reset():
    """Wipe this test user's sandbox rows, reset funds, and seed a position.

    The seeded position is what makes the test exercise Path 2 from issue
    #1808 -- the silent lost-update -- instead of Path 1 (the loud
    UNIQUE-constraint failure when two threads both try to INSERT). A
    pre-existing position forces both fills into the
    "update existing position" branch, where the bug is last-write-wins on
    the read-modify-write.
    """
    SandboxPositions.query.filter_by(user_id=USER_ID).delete()

    funds = SandboxFunds.query.filter_by(user_id=USER_ID).first()
    if not funds:
        funds = SandboxFunds(
            user_id=USER_ID,
            total_capital=START_BALANCE,
            available_balance=START_BALANCE,
            used_margin=Decimal("0.00"),
        )
        db_session.add(funds)
    else:
        funds.available_balance = START_BALANCE
        funds.used_margin = Decimal("0.00")

    db_session.add(
        SandboxPositions(
            user_id=USER_ID,
            symbol=SYMBOL,
            exchange=EXCHANGE,
            product=PRODUCT,
            quantity=SEED_QTY,
            average_price=EXEC_PRICE,
            ltp=EXEC_PRICE,
            pnl=Decimal("0.00"),
            pnl_percent=Decimal("0.00"),
            accumulated_realized_pnl=Decimal("0.00"),
            today_realized_pnl=Decimal("0.00"),
            margin_blocked=Decimal("0.00"),
        )
    )
    db_session.commit()


def _order(orderid, qty=PER_ORDER_QTY):
    """A minimal filled-order stand-in for `_update_position`.

    Mirrors the fields `_update_position` reads off the order object; nothing
    here needs to be a SQLAlchemy row because the function only reads
    attributes off the object and never queries by orderid.
    """
    return SimpleNamespace(
        user_id=USER_ID,
        orderid=orderid,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        product=PRODUCT,
        action="BUY",
        quantity=qty,
        margin_blocked=PER_ORDER_MARGIN,
    )


def _position():
    return SandboxPositions.query.filter_by(
        user_id=USER_ID, symbol=SYMBOL, exchange=EXCHANGE, product=PRODUCT
    ).first()


def test_concurrent_same_symbol_buys_accumulate_position():
    """Two concurrent same-symbol BUYs on top of a seeded long position.

    Starting from `SEED_QTY` shares and adding two concurrent BUYs of
    `PER_ORDER_QTY` each, the final quantity should be
    `SEED_QTY + 2 * PER_ORDER_QTY`.

    Pre-fix: one of the two increments is lost to the RMW race; final
    quantity is `SEED_QTY + PER_ORDER_QTY` instead of
    `SEED_QTY + 2 * PER_ORDER_QTY`.

    Post-fix: the class-level lock serializes the two calls; final quantity is
    exactly `SEED_QTY + 2 * PER_ORDER_QTY`.
    """
    _reset()

    # Block enough margin up front so both BUYs can proceed. Without this the
    # second BUY could fail at the fund check rather than racing the position
    # update, which would mask the bug under test.
    from sandbox.fund_manager import FundManager

    FundManager(USER_ID).block_margin(2 * PER_ORDER_MARGIN, "concurrency test setup")

    order_a = _order("CONC-A")
    order_b = _order("CONC-B")

    engine = ExecutionEngine()

    # The barrier is shared by the two worker threads so they enter the
    # critical section at (effectively) the same moment. Without it the GIL
    # tends to serialize the two threads before they reach `_update_position`
    # and the race never actually happens.
    barrier = threading.Barrier(2)

    def worker(order):
        barrier.wait()
        return engine._update_position(order, EXEC_PRICE)

    with ThreadPoolExecutor(max_workers=2) as pool:
        f_a = pool.submit(worker, order_a)
        f_b = pool.submit(worker, order_b)
        wait([f_a, f_b])
        # Surface any exception raised inside the worker rather than
        # silently letting it pass the assertion below.
        f_a.result()
        f_b.result()

    db_session.expire_all()
    pos = _position()
    assert pos is not None, "no position row was created by the concurrent fills"
    assert pos.quantity == SEED_QTY + 2 * PER_ORDER_QTY, (
        f"expected position.quantity == {SEED_QTY + 2 * PER_ORDER_QTY} after two "
        f"concurrent same-symbol BUYs on top of a {SEED_QTY}-share seed (issue "
        f"#1808), got {pos.quantity} -- one update was lost to the "
        "read-modify-write race"
    )


if __name__ == "__main__":
    init_db()
    print("\n TESTING SANDBOX CONCURRENT ORDERS (issue #1808)")

    tests = [test_concurrent_same_symbol_buys_accumulate_position]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL: {t.__name__}: {e}")

    print("\n" + "=" * 60)
    print(f"RESULTS: {len(tests) - failed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
