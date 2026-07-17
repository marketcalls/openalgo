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
    """SELL 150 of a 200-share holding → holding 50, no short, proceeds credited."""
    print("\n" + "=" * 60)
    print("TEST 1: partial CNC sell from holdings (200 → sell 150)")
    print("=" * 60)
    _reset()
    _seed_holding(200)

    ExecutionEngine()._update_position(_order("SELL", 150), Decimal("2500.00"))
    db_session.expire_all()

    holding = _holding()
    short = _short_position()
    expected_balance = START_BALANCE + Decimal("150") * Decimal("2500.00")

    ok = True
    if not holding or holding.quantity != 50:
        print(f"❌ holding should be 50, got {holding.quantity if holding else None}")
        ok = False
    if short is not None:
        print(f"❌ a phantom short position was created: qty {short.quantity}")
        ok = False
    if _balance() != expected_balance:
        print(f"❌ proceeds not credited: {_balance()} != {expected_balance}")
        ok = False
    if ok:
        print("✅ PASS: holding 200→50, no short, ₹375000 proceeds credited")
    return ok


def test_full_holdings_sell():
    """SELL 200 of a 200-share holding → holding gone, no short."""
    print("\n" + "=" * 60)
    print("TEST 2: full CNC sell from holdings (200 → sell 200)")
    print("=" * 60)
    _reset()
    _seed_holding(200)

    ExecutionEngine()._update_position(_order("SELL", 200), Decimal("2500.00"))
    db_session.expire_all()

    holding = _holding()
    short = _short_position()

    ok = True
    if holding is not None and holding.quantity != 0:
        print(f"❌ holding should be gone/zero, got {holding.quantity}")
        ok = False
    if short is not None:
        print(f"❌ a phantom short position was created: qty {short.quantity}")
        ok = False
    if ok:
        print("✅ PASS: holding fully sold, no short position")
    return ok


def test_position_then_holdings_sell():
    """Open long 50 + holdings 100, SELL 120 → position closed, holding 30."""
    print("\n" + "=" * 60)
    print("TEST 3: CNC sell spanning open position + holdings (50+100, sell 120)")
    print("=" * 60)
    _reset()
    _seed_position(50, avg=Decimal("2500.00"), margin=Decimal("125000.00"))
    _seed_holding(100)

    ExecutionEngine()._update_position(_order("SELL", 120), Decimal("2600.00"))
    db_session.expire_all()

    holding = _holding()
    short = _short_position()
    long_pos = (
        SandboxPositions.query.filter_by(user_id=USER_ID, symbol="RELIANCE", exchange="NSE")
        .filter(SandboxPositions.quantity > 0)
        .first()
    )

    ok = True
    if not holding or holding.quantity != 30:
        print(f"❌ holding should be 30, got {holding.quantity if holding else None}")
        ok = False
    if short is not None:
        print(f"❌ a phantom short position was created: qty {short.quantity}")
        ok = False
    if long_pos is not None:
        print(f"❌ long position should be closed, still open at {long_pos.quantity}")
        ok = False
    if ok:
        print("✅ PASS: position closed (50), holding 100→30, proceeds for 70")
    return ok


if __name__ == "__main__":
    init_db()
    print("\n🧪 TESTING SANDBOX HOLDINGS SELL (issue #1640)")

    tests = [
        test_partial_holdings_sell,
        test_full_holdings_sell,
        test_position_then_holdings_sell,
    ]
    passed = sum(1 for t in tests if t())
    failed = len(tests) - passed

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
