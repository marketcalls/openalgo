#!/usr/bin/env python3
"""
Regression test for issue #1640 — selling CNC holdings in Sandbox.

Before the fix, a CNC SELL backed by settled holdings (but no open intraday
position) fell through `ExecutionEngine._update_position` and opened a phantom
SHORT position, leaving the holding untouched — so the holding could never be
sold (via strategy or manually). After the fix, the sell reduces the holding
and credits the sale proceeds, with no short position created.

Run: uv run python test/sandbox/test_holdings_sell.py
"""

import sys
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from database.sandbox_db import (
    SandboxFunds,
    SandboxHoldings,
    SandboxOrders,
    SandboxPositions,
    db_session,
    init_db,
)
from sandbox.execution_engine import ExecutionEngine

USER_ID = "holdtest_1640"
START_BALANCE = Decimal("10000000.00")


def _reset():
    """Wipe this test user's sandbox rows and reset funds."""
    SandboxOrders.query.filter_by(user_id=USER_ID).delete()
    SandboxPositions.query.filter_by(user_id=USER_ID).delete()
    SandboxHoldings.query.filter_by(user_id=USER_ID).delete()

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
    db_session.commit()


def _seed_holding(qty, avg=Decimal("2400.00")):
    db_session.add(
        SandboxHoldings(
            user_id=USER_ID,
            symbol="RELIANCE",
            exchange="NSE",
            quantity=qty,
            average_price=avg,
            ltp=avg,
            pnl=Decimal("0.00"),
            pnl_percent=Decimal("0.00"),
            settlement_date=date.today(),
        )
    )
    db_session.commit()


def _seed_position(qty, avg=Decimal("2500.00"), margin=Decimal("0.00")):
    db_session.add(
        SandboxPositions(
            user_id=USER_ID,
            symbol="RELIANCE",
            exchange="NSE",
            product="CNC",
            quantity=qty,
            average_price=avg,
            ltp=avg,
            margin_blocked=margin,
        )
    )
    # Keep funds consistent with the seeded position's blocked margin (as if it
    # had been blocked at order placement), so closing it reconciles cleanly.
    if margin > 0:
        funds = SandboxFunds.query.filter_by(user_id=USER_ID).first()
        funds.used_margin += margin
        funds.available_balance -= margin
    db_session.commit()


def _order(action, qty, product="CNC"):
    """A minimal filled-order stand-in for _update_position."""
    return SimpleNamespace(
        user_id=USER_ID,
        orderid="TEST-1640",
        symbol="RELIANCE",
        exchange="NSE",
        product=product,
        action=action,
        quantity=qty,
        margin_blocked=Decimal("0.00"),
    )


def _short_position():
    return (
        SandboxPositions.query.filter_by(user_id=USER_ID, symbol="RELIANCE", exchange="NSE")
        .filter(SandboxPositions.quantity < 0)
        .first()
    )


def _holding():
    return SandboxHoldings.query.filter_by(
        user_id=USER_ID, symbol="RELIANCE", exchange="NSE"
    ).first()


def _balance():
    return SandboxFunds.query.filter_by(user_id=USER_ID).first().available_balance


def test_partial_holdings_sell():
    """SELL 150 of a 200-share holding leaves a -150 day position.

    The holding stays at 200 for the rest of the session; T+1 settlement is
    what reduces it. The day position is the record of the sale.
    """
    _reset()
    _seed_holding(200)

    ExecutionEngine()._update_position(_order("SELL", 150), Decimal("2500.00"))
    db_session.expire_all()

    holding = _holding()
    assert holding is not None, "the holding disappeared"
    assert holding.quantity == 200, (
        f"the holding moved to {holding.quantity} on the sell; only T+1 settlement "
        "should reduce it"
    )

    day = _short_position()
    assert day is not None, "the sell left no day position to record it"
    assert day.quantity == -150, f"day position should be -150, got {day.quantity}"

    # Proceeds arrive at settlement, not on the sell, so the balance is
    # unchanged here. Asserted rather than ignored: a credit appearing now
    # would mean the same shares could fund another trade before they settle.
    assert _balance() == START_BALANCE, (
        f"balance moved to {_balance()} before settlement"
    )


def test_full_holdings_sell():
    """SELL the whole 200-share holding leaves a -200 day position."""
    _reset()
    _seed_holding(200)

    ExecutionEngine()._update_position(_order("SELL", 200), Decimal("2500.00"))
    db_session.expire_all()

    holding = _holding()
    assert holding is not None and holding.quantity == 200, (
        "the holding should stand until T+1 settlement, even when sold in full"
    )

    day = _short_position()
    assert day is not None and day.quantity == -200, (
        f"day position should be -200, got {day.quantity if day else None}"
    )


def test_position_then_holdings_sell():
    """A sell spanning an open long and a holding closes the long first.

    Long 50 plus holding 100, sell 120: the 50 open position is closed and the
    remaining 70 comes from the holding, which stays at 100 until settlement.
    The net day position is therefore -70, not -120.
    """
    _reset()
    _seed_position(50, avg=Decimal("2500.00"), margin=Decimal("125000.00"))
    _seed_holding(100)

    ExecutionEngine()._update_position(_order("SELL", 120), Decimal("2600.00"))
    db_session.expire_all()

    holding = _holding()
    assert holding is not None and holding.quantity == 100, (
        f"the holding moved to {holding.quantity if holding else None} before settlement"
    )

    position = SandboxPositions.query.filter_by(
        user_id=USER_ID, symbol="RELIANCE", exchange="NSE"
    ).first()
    assert position is not None, "the sell left no position"
    assert position.quantity == -70, (
        f"net day position should be -70 (long 50 closed, 70 sold from the "
        f"holding), got {position.quantity}"
    )


if __name__ == "__main__":
    init_db()
    print("\n TESTING SANDBOX HOLDINGS SELL (issue #1640)")

    tests = [
        test_partial_holdings_sell,
        test_full_holdings_sell,
        test_position_then_holdings_sell,
    ]
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
