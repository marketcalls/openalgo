#!/usr/bin/env python3
"""
Test CNC SELL validation - ensures CNC sell orders are only allowed with existing positions/holdings
MIS orders allow short selling (negative positions)
"""
import sys
from decimal import Decimal
from database.sandbox_db import init_db, db_session, SandboxOrders, SandboxPositions, SandboxHoldings, SandboxFunds
from sandbox.order_manager import OrderManager

def reset_test_data(user_id='testuser'):
    """Reset test data"""
    print(f"\n🔄 Resetting data for user: {user_id}")

    # Delete all existing data - also delete ALL orders to avoid ID conflicts
    SandboxOrders.query.delete()  # Delete ALL orders to reset ID counter
    SandboxPositions.query.filter_by(user_id=user_id).delete()
    SandboxHoldings.query.filter_by(user_id=user_id).delete()

    # Ensure user has funds
    funds = SandboxFunds.query.filter_by(user_id=user_id).first()
    if not funds:
        funds = SandboxFunds(
            user_id=user_id,
            total_capital=Decimal('10000000.00'),
            available_balance=Decimal('10000000.00'),
            used_margin=Decimal('0.00')
        )
        db_session.add(funds)
    else:
        funds.available_balance = Decimal('10000000.00')
        funds.used_margin = Decimal('0.00')

    db_session.commit()
    print("✅ Data reset complete")


def test_cnc_sell_without_position():
    """Test 1: CNC SELL should fail without position/holdings"""
    print("\n" + "="*60)
    print("TEST 1: CNC SELL without position/holdings")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    om = OrderManager(user_id)

    # Try to sell without any position
    print("→ Attempting CNC SELL 100 RELIANCE (no position)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })

    if not success and 'No positions or holdings available' in response.get('message', ''):
        print(f"✅ PASS: {response['message']}")
        return True
    else:
        print(f"❌ FAIL: Expected rejection, got: {response}")
        return False


def test_cnc_sell_with_position():
    """Test 2: CNC SELL should succeed with existing position"""
    print("\n" + "="*60)
    print("TEST 2: CNC SELL with existing position")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    # Create a position
    position = SandboxPositions(
        user_id=user_id,
        symbol='RELIANCE',
        exchange='NSE',
        product='CNC',
        quantity=100,
        average_price=Decimal('2500.00')
    )
    db_session.add(position)
    db_session.commit()
    print("✅ Created position: RELIANCE 100 shares")

    om = OrderManager(user_id)

    # Try to sell within position limits
    print("→ Attempting CNC SELL 50 RELIANCE (have 100)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 50,
        'price_type': 'MARKET',
        'product': 'CNC'
    })

    if success:
        print(f"✅ PASS: Order placed successfully - {response.get('orderid')}")
        return True
    else:
        print(f"❌ FAIL: Order rejected: {response.get('message')}")
        return False


def test_cnc_sell_exceeding_position():
    """Test 3: CNC SELL should fail when exceeding available quantity"""
    print("\n" + "="*60)
    print("TEST 3: CNC SELL exceeding available quantity")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    # Create a position
    position = SandboxPositions(
        user_id=user_id,
        symbol='RELIANCE',
        exchange='NSE',
        product='CNC',
        quantity=50,
        average_price=Decimal('2500.00')
    )
    db_session.add(position)
    db_session.commit()
    print("✅ Created position: RELIANCE 50 shares")

    om = OrderManager(user_id)

    # Try to sell more than available
    print("→ Attempting CNC SELL 100 RELIANCE (have only 50)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'CNC'
    })

    if not success and 'Only 50 shares available' in response.get('message', ''):
        print(f"✅ PASS: {response['message']}")
        return True
    else:
        print(f"❌ FAIL: Expected rejection for exceeding quantity, got: {response}")
        return False


def test_cnc_sell_with_holdings():
    """Test 4: CNC SELL should work with holdings"""
    print("\n" + "="*60)
    print("TEST 4: CNC SELL with holdings")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    # Create holdings (T+1 settled shares)
    from datetime import date
    holding = SandboxHoldings(
        user_id=user_id,
        symbol='RELIANCE',
        exchange='NSE',
        quantity=200,
        average_price=Decimal('2400.00'),
        settlement_date=date.today()
    )
    db_session.add(holding)
    db_session.commit()
    print("✅ Created holdings: RELIANCE 200 shares")

    om = OrderManager(user_id)

    # Try to sell from holdings
    print("→ Attempting CNC SELL 150 RELIANCE (have 200 in holdings)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 150,
        'price_type': 'MARKET',
        'product': 'CNC'
    })

    if success:
        print(f"✅ PASS: Order placed successfully - {response.get('orderid')}")
        return True
    else:
        print(f"❌ FAIL: Order rejected: {response.get('message')}")
        return False


def test_mis_short_selling():
    """Test 5: MIS SELL should allow short selling (no position required)"""
    print("\n" + "="*60)
    print("TEST 5: MIS short selling (without position)")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    om = OrderManager(user_id)

    # Try MIS short sell without any position
    print("→ Attempting MIS SELL 100 RELIANCE (short selling)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 100,
        'price_type': 'MARKET',
        'product': 'MIS'
    })

    if success:
        print(f"✅ PASS: MIS short sell order placed - {response.get('orderid')}")
        return True
    else:
        print(f"❌ FAIL: MIS short sell rejected: {response.get('message')}")
        return False


def test_cnc_sell_with_position_and_holdings():
    """Test 6: CNC SELL should combine position and holdings"""
    print("\n" + "="*60)
    print("TEST 6: CNC SELL with both position and holdings")
    print("="*60)

    user_id = 'testuser'
    reset_test_data(user_id)

    # Create position
    position = SandboxPositions(
        user_id=user_id,
        symbol='RELIANCE',
        exchange='NSE',
        product='CNC',
        quantity=50,
        average_price=Decimal('2500.00')
    )
    db_session.add(position)

    # Create holdings
    from datetime import date
    holding = SandboxHoldings(
        user_id=user_id,
        symbol='RELIANCE',
        exchange='NSE',
        quantity=100,
        average_price=Decimal('2400.00'),
        settlement_date=date.today()
    )
    db_session.add(holding)
    db_session.commit()

    print("✅ Created position: 50 shares + holdings: 100 shares = Total: 150 shares")

    om = OrderManager(user_id)

    # Try to sell combined quantity
    print("→ Attempting CNC SELL 120 RELIANCE (have 150 total)...")
    success, response, code = om.place_order({
        'symbol': 'RELIANCE',
        'exchange': 'NSE',
        'action': 'SELL',
        'quantity': 120,
        'price_type': 'MARKET',
        'product': 'CNC'
    })

    if success:
        print(f"✅ PASS: Order placed successfully - {response.get('orderid')}")
        return True
    else:
        print(f"❌ FAIL: Order rejected: {response.get('message')}")
        return False


if __name__ == '__main__':
    # Initialize database
    init_db()

    print("\n🧪 TESTING CNC SELL VALIDATION")
    print("="*60)

    tests = [
        test_cnc_sell_without_position,
        test_cnc_sell_with_position,
        test_cnc_sell_exceeding_position,
        test_cnc_sell_with_holdings,
        test_mis_short_selling,
        test_cnc_sell_with_position_and_holdings
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            if test():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"❌ TEST ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1

    print("\n" + "="*60)
    print(f"TEST RESULTS: {passed} passed, {failed} failed")
    print("="*60)

    if failed == 0:
        print("🎉 ALL TESTS PASSED!")
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED")
        sys.exit(1)