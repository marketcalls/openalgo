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

#: Concurrent pairs fired per run. One pair reproduces the race only about
#: two thirds of the time, so a single round would miss a reintroduced bug
#: one run in three. See the test docstring for the measurement.
ROUNDS = 6


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
    """Concurrent same-symbol BUYs on top of a seeded long position.

    Starting from `SEED_QTY` shares, every round adds two concurrent BUYs of
    `PER_ORDER_QTY` each, so after round N the quantity must be
    `SEED_QTY + 2 * PER_ORDER_QTY * N`.

    Pre-fix, one of the two increments is lost to the read-modify-write race
    and the quantity comes up one order short.

    **Why it runs several rounds.** A single concurrent pair only actually
    interleaves about two thirds of the time: the barrier releases both
    threads together, but each then does a little database work before
    reaching the SELECT, and that is often enough for one to finish before the
    other starts. Measured on the unfixed engine, one round caught the bug in
    10 of 15 attempts, so a single-round test would sign off on a reintroduced
    race one time in three. Six rounds takes the odds of missing it from
    roughly 1 in 3 to roughly 1 in 1000, and the assertion runs after every
    round so it fails on the first lost update rather than at the end.

    With the fix this is deterministic: 15 of 15 runs pass.
    """
    _reset()

    # Block enough margin up front for every order this test places. Without
    # this a later BUY could fail at the fund check rather than racing the
    # position update, which would mask the bug under test.
    from sandbox.fund_manager import FundManager

    FundManager(USER_ID).block_margin(
        2 * ROUNDS * PER_ORDER_MARGIN, "concurrency test setup"
    )

    engine = ExecutionEngine()

    for round_no in range(1, ROUNDS + 1):
        # The barrier is shared by the two worker threads so they enter the
        # critical section at (effectively) the same moment. Without it the GIL
        # tends to serialize the two threads before they reach
        # `_update_position` and the race never happens at all.
        barrier = threading.Barrier(2)

        def worker(order, _barrier=barrier):
            _barrier.wait()
            return engine._update_position(order, EXEC_PRICE)

        order_a = _order(f"CONC-{round_no}-A")
        order_b = _order(f"CONC-{round_no}-B")

        with ThreadPoolExecutor(max_workers=2) as pool:
            f_a = pool.submit(worker, order_a)
            f_b = pool.submit(worker, order_b)
            wait([f_a, f_b])
            # Surface any exception raised inside a worker rather than
            # silently letting it pass the assertion below. Path 1 of the
            # issue, two INSERTs racing, surfaces here as an IntegrityError.
            f_a.result()
            f_b.result()

        db_session.expire_all()
        pos = _position()
        expected = SEED_QTY + 2 * PER_ORDER_QTY * round_no

        assert pos is not None, "no position row was created by the concurrent fills"
        assert pos.quantity == expected, (
            f"round {round_no} of {ROUNDS}: expected position.quantity == {expected} "
            f"after {2 * round_no} concurrent same-symbol BUYs on top of a "
            f"{SEED_QTY}-share seed (issue #1808), got {pos.quantity}. One "
            f"read-modify-write was lost to the race."
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
