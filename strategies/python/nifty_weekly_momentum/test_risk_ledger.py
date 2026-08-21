"""Tests for the risk ledger.

Run: python3 strategies/python/nifty_weekly_momentum/test_risk_ledger.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

from strategies.python.nifty_weekly_momentum.risk_ledger import RiskLedger, RiskState


def test_initial_state():
    ledger = RiskLedger()
    assert ledger.state == RiskState.READY
    assert ledger.can_enter()
    assert ledger.trade_count == 0
    assert ledger.remaining_risk == 2000.0


def test_open_trade():
    ledger = RiskLedger()
    trade = ledger.open_trade(1, 1000.0, "long", "NIFTY...CE", 1, 50.0, 500.0)
    assert trade.status == "open"
    assert ledger.state == RiskState.OPEN
    assert not ledger.can_enter()
    assert ledger.reserved_risk == 500.0


def test_close_trade_profit():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    trade = ledger.close_trade(1, 2000.0, 70.0, fees=20.0, slippage=5.0)
    assert trade.status == "closed"
    # pnl = (70-50)*1 = 20, realized = 20 - 20 - 5 = -5
    assert trade.realized_pnl == -5.0
    assert ledger.realized_pnl == -5.0
    assert ledger.state == RiskState.COOLDOWN


def test_close_trade_loss():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    trade = ledger.close_trade(1, 2000.0, 30.0, fees=20.0, slippage=5.0)
    # pnl = (30-50)*1 = -20, realized = -20 - 20 - 5 = -45
    assert trade.realized_pnl == -45.0
    assert ledger.realized_pnl == -45.0
    assert ledger.remaining_risk == 2000.0 - 45.0


def test_bearish_signal_is_still_a_long_put_position():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "short", "NIFTY-PE", 25, 50.0, 500.0)

    trade = ledger.close_trade(1, 2000.0, 60.0)

    assert trade.realized_pnl == 250.0


def test_entry_fill_update():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "long", "NIFTY-CE", 50, 40.0, 400.0)
    trade = ledger.update_open_trade(1, entry_price=41.0, quantity=25)
    assert trade.entry_price == 41.0
    assert trade.lots == 25


def test_unfilled_cancel_does_not_consume_trade_limit():
    ledger = RiskLedger(max_trades=1)
    ledger.open_trade(1, 1000.0, "long", "NIFTY-CE", 50, 40.0, 400.0)
    canceled = ledger.cancel_trade(1)
    assert canceled.status == "canceled"
    assert ledger.reserved_risk == 0.0
    assert ledger.trade_count == 0
    assert ledger.state == RiskState.READY
    assert ledger.can_enter()


def test_soft_halt():
    ledger = RiskLedger(daily_loss_budget=1000.0, soft_stop_pct=0.9)
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    # Unrealized loss of 900 → soft halt
    ledger.update_unrealized(bid_price=50.0 - 900.0, lots=1, direction="long", entry_price=50.0)
    assert ledger.state == RiskState.SOFT_HALTED
    assert not ledger.can_enter()


def test_hard_halt():
    ledger = RiskLedger(daily_loss_budget=1000.0)
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    # Unrealized loss of 1000 → hard halt
    ledger.update_unrealized(bid_price=50.0 - 1000.0, lots=1, direction="long", entry_price=50.0)
    assert ledger.state == RiskState.HARD_HALTED
    assert ledger.is_halted()


def test_max_trades():
    ledger = RiskLedger(max_trades=2)
    for i in range(2):
        ledger.open_trade(i + 1, 1000.0 + i, "long", "SYM", 1, 50.0, 100.0)
        ledger.close_trade(i + 1, 2000.0 + i, 55.0)
        ledger.end_cooldown()
    assert ledger.trade_count == 2
    assert not ledger.can_enter()


def test_insufficient_risk():
    ledger = RiskLedger(per_trade_risk=500.0, daily_loss_budget=600.0)
    # Open a trade that uses 500 of 600
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    ledger.close_trade(1, 2000.0, 45.0, fees=10.0)  # Loss of 5+10=15
    ledger.end_cooldown()
    # Remaining risk = 600 - 15 = 585, still > 500
    assert ledger.can_enter()
    # Open another
    ledger.open_trade(2, 3000.0, "long", "SYM", 1, 50.0, 500.0)
    ledger.close_trade(2, 4000.0, 40.0, fees=10.0)  # Loss of 10+10=20
    ledger.end_cooldown()
    # Remaining = 600 - 15 - 20 = 565, still > 500
    assert ledger.can_enter()
    # Open third
    ledger.open_trade(3, 5000.0, "long", "SYM", 1, 50.0, 500.0)
    ledger.close_trade(3, 6000.0, 35.0, fees=10.0)  # Loss of 15+10=25
    ledger.end_cooldown()
    # Remaining = 600 - 15 - 20 - 25 = 540, still > 500 but max_trades=3
    assert not ledger.can_enter()  # max_trades reached


def test_force_flat():
    ledger = RiskLedger()
    ledger.force_flat()
    assert ledger.state == RiskState.FLAT
    assert not ledger.can_enter()


def test_force_flat_state_survives_exit_fill():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    ledger.force_flat()
    ledger.close_trade(1, 2000.0, 55.0)
    assert ledger.state == RiskState.FLAT
    assert not ledger.can_enter()


def test_force_flat_state_survives_unfilled_cancel():
    ledger = RiskLedger()
    ledger.open_trade(1, 1000.0, "long", "SYM", 1, 50.0, 500.0)
    ledger.force_flat()
    ledger.cancel_trade(1)
    assert ledger.state == RiskState.FLAT
    assert not ledger.can_enter()


def main():
    tests = [
        test_initial_state,
        test_open_trade,
        test_close_trade_profit,
        test_close_trade_loss,
        test_bearish_signal_is_still_a_long_put_position,
        test_entry_fill_update,
        test_unfilled_cancel_does_not_consume_trade_limit,
        test_soft_halt,
        test_hard_halt,
        test_max_trades,
        test_insufficient_risk,
        test_force_flat,
        test_force_flat_state_survives_exit_fill,
        test_force_flat_state_survives_unfilled_cancel,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            print(f"  ✅ {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  ❌ {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
