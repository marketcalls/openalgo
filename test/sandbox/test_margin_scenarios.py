#!/usr/bin/env python3
"""
Test script to verify margin calculations in all scenarios
"""
import sys
import time
from decimal import Decimal
from database.sandbox_db import init_db, db_session, SandboxFunds, SandboxOrders, SandboxPositions, SandboxTrades
from sandbox.order_manager import OrderManager
from sandbox.execution_engine import ExecutionEngine

def reset_user_data(user_id='rajandran'):
    """Reset all sandbox data for user"""
    print(f"\nResetting data for user: {user_id}")

    # Delete all existing data
    SandboxOrders.query.filter_by(user_id=user_id).delete()
    SandboxTrades.query.filter_by(user_id=user_id).delete()
    SandboxPositions.query.filter_by(user_id=user_id).delete()

    # Reset funds
    funds = SandboxFunds.query.filter_by(user_id=user_id).first()
    if funds:
        funds.total_capital = Decimal('10000000.00')
        funds.available_balance = Decimal('10000000.00')
        funds.used_margin = Decimal('0.00')
        funds.realized_pnl = Decimal('0.00')
        funds.unrealized_pnl = Decimal('0.00')
        funds.total_pnl = Decimal('0.00')

    db_session.commit()
    print("✓ Data reset complete")

def get_margin_status(user_id='rajandran'):
    """Get current margin status"""
    funds = SandboxFunds.query.filter_by(user_id=user_id).first()
    if funds:
        return {
            'available': float(funds.available_balance),
            'used': float(funds.used_margin),
            'total': float(funds.total_capital)
        }
    return None

def print_margin_status(label, status):
    """Print margin status nicely"""
    print(f"{label}:")
    print(f"  Available: ₹{status['available']:,.2f}")
    print(f"  Used: ₹{status['used']:,.2f}")
    print(f"  Total: ₹{status['total']:,.2f}")

def test_scenario_1():
    """Test: BUY 100 → SELL 50 → SELL 50"""
    print("\n" + "="*60)
    print("SCENARIO 1: BUY 100 → SELL 50 → SELL 50")
    print("="*60)

    user_id = 'rajandran'
    reset_user_data(user_id)

    om = OrderManager(user_id)
    ee = ExecutionEngine()

    # Initial status
    status = get_margin_status(user_id)
    print_margin_status("Initial", status)

    # BUY 100 ZEEL
    print("\n→ Placing BUY 100 ZEEL...")
    success, response, _ = om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    if success:
        print(f"  ✓ Order placed: {response.get('orderid')}")

    # Execute the order
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100", status)
    expected_margin = 100 * 112.37  # Assuming LTP is ₹112.37
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    # SELL 50 ZEEL
    print("\n→ Placing SELL 50 ZEEL...")
    success, response, _ = om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 50,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    if success:
        print(f"  ✓ Order placed: {response.get('orderid')}")

    # Execute the order
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After SELL 50", status)
    expected_margin = 50 * 112.37  # Half position closed
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    # SELL 50 ZEEL (close position)
    print("\n→ Placing SELL 50 ZEEL (closing position)...")
    success, response, _ = om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 50,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    if success:
        print(f"  ✓ Order placed: {response.get('orderid')}")

    # Execute the order
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After SELL 50 (position closed)", status)
    assert status['used'] == 0, f"Expected margin ₹0, got ₹{status['used']}"

    print("\n✅ SCENARIO 1 PASSED")

def test_scenario_2():
    """Test: BUY 100 → SELL 100 → BUY 100 → SELL 100"""
    print("\n" + "="*60)
    print("SCENARIO 2: BUY 100 → SELL 100 → BUY 100 → SELL 100")
    print("="*60)

    user_id = 'rajandran'
    reset_user_data(user_id)

    om = OrderManager(user_id)
    ee = ExecutionEngine()

    # Round 1: BUY 100 → SELL 100
    print("\n→ Round 1: BUY 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100", status)
    expected_margin = 100 * 112.37
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    print("\n→ Round 1: SELL 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After SELL 100", status)
    assert status['used'] == 0, f"Expected margin ₹0, got ₹{status['used']}"

    # Round 2: BUY 100 → SELL 100
    print("\n→ Round 2: BUY 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100 (reopened)", status)
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    print("\n→ Round 2: SELL 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After SELL 100 (closed again)", status)
    assert status['used'] == 0, f"Expected margin ₹0, got ₹{status['used']}"

    print("\n✅ SCENARIO 2 PASSED")

def test_scenario_3():
    """Test: BUY 100 → SELL 200 (position reversal)"""
    print("\n" + "="*60)
    print("SCENARIO 3: BUY 100 → SELL 200 (position reversal)")
    print("="*60)

    user_id = 'rajandran'
    reset_user_data(user_id)

    om = OrderManager(user_id)
    ee = ExecutionEngine()

    # BUY 100
    print("\n→ BUY 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100", status)
    expected_margin = 100 * 112.37
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    # SELL 200 (reversal to SHORT 100)
    print("\n→ SELL 200 ZEEL (reversing to SHORT 100)...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 200,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After SELL 200 (SHORT 100)", status)
    # Should have margin for SHORT 100
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    print("\n✅ SCENARIO 3 PASSED")

def test_scenario_4():
    """Test: BUY 100 → BUY 100 (adding to position)"""
    print("\n" + "="*60)
    print("SCENARIO 4: BUY 100 → BUY 100 (adding to position)")
    print("="*60)

    user_id = 'rajandran'
    reset_user_data(user_id)

    om = OrderManager(user_id)
    ee = ExecutionEngine()

    # BUY 100
    print("\n→ BUY 100 ZEEL...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100", status)
    expected_margin = 100 * 112.37
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    # BUY 100 more
    print("\n→ BUY 100 ZEEL (adding to position)...")
    om.place_order({
        'symbol': 'ZEEL',
        'exchange': 'NSE',
        'action': 'BUY',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })
    ee.check_and_execute_pending_orders()

    status = get_margin_status(user_id)
    print_margin_status("After BUY 100 (total 200)", status)
    expected_margin = 200 * 112.37
    assert abs(status['used'] - expected_margin) < 1, f"Expected margin ~₹{expected_margin}, got ₹{status['used']}"

    print("\n✅ SCENARIO 4 PASSED")

if __name__ == '__main__':
    # Initialize database
    init_db()

    print("\n🧪 TESTING MARGIN SCENARIOS")
    print("="*60)

    try:
        test_scenario_1()
        test_scenario_2()
        test_scenario_3()
        test_scenario_4()

        print("\n" + "="*60)
        print("🎉 ALL TESTS PASSED!")
        print("="*60)

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n💥 ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)