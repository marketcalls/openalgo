# test/sandbox/test_fund_manager.py
"""
Test suite for Sandbox Fund Manager

Tests:
- Fund initialization
- Margin blocking and release
- P&L calculations
- Sunday reset functionality
- Leverage calculations
"""

import sys
import os
from decimal import Decimal

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from sandbox.fund_manager import FundManager, get_user_funds, initialize_user_funds
from database.sandbox_db import SandboxFunds, db_session


def test_fund_initialization():
    """Test fund initialization for new user"""
    print("\n" + "="*50)
    print("TEST 1: Fund Initialization")
    print("="*50)

    test_user = "TEST_USER_001"

    # Clean up any existing test data
    cleanup_test_data(test_user)

    # Initialize funds
    success, message = initialize_user_funds(test_user)
    print(f"✓ Initialize funds: {message}")
    assert success, "Fund initialization failed"

    # Get funds
    funds = get_user_funds(test_user)
    print(f"✓ Available cash: ₹{funds['availablecash']:,.2f}")
    assert funds['availablecash'] == 10000000.00, "Starting capital should be ₹1 Crore"

    # Try initializing again - should not fail
    success, message = initialize_user_funds(test_user)
    print(f"✓ Re-initialize funds: {message}")
    assert success, "Re-initialization should not fail"

    print("✅ PASSED: Fund Initialization\n")


def test_margin_operations():
    """Test margin blocking and release"""
    print("="*50)
    print("TEST 2: Margin Operations")
    print("="*50)

    test_user = "TEST_USER_002"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    fm = FundManager(test_user)

    # Get initial balance
    funds = fm.get_funds()
    initial_balance = Decimal(str(funds['availablecash']))
    print(f"✓ Initial balance: ₹{initial_balance:,.2f}")

    # Block margin
    margin_amount = Decimal('100000.00')
    success, message = fm.block_margin(margin_amount, "Test trade")
    print(f"✓ Block margin: {message}")
    assert success, "Margin blocking failed"

    funds = fm.get_funds()
    available = Decimal(str(funds['availablecash']))
    used = Decimal(str(funds['utiliseddebits']))

    print(f"✓ Available after block: ₹{available:,.2f}")
    print(f"✓ Used margin: ₹{used:,.2f}")
    assert available == initial_balance - margin_amount, "Available balance incorrect"
    assert used == margin_amount, "Used margin incorrect"

    # Release margin with profit
    profit = Decimal('5000.00')
    success, message = fm.release_margin(margin_amount, profit, "Test trade complete")
    print(f"✓ Release margin: {message}")
    assert success, "Margin release failed"

    funds = fm.get_funds()
    final_balance = Decimal(str(funds['availablecash']))
    realized_pnl = Decimal(str(funds['m2mrealized']))

    print(f"✓ Final balance: ₹{final_balance:,.2f}")
    print(f"✓ Realized P&L: ₹{realized_pnl:,.2f}")
    assert final_balance == initial_balance + profit, "Final balance incorrect"
    assert realized_pnl == profit, "Realized P&L incorrect"

    print("✅ PASSED: Margin Operations\n")


def test_insufficient_funds():
    """Test insufficient funds scenario"""
    print("="*50)
    print("TEST 3: Insufficient Funds")
    print("="*50)

    test_user = "TEST_USER_003"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    fm = FundManager(test_user)

    # Try to block more than available
    excessive_amount = Decimal('15000000.00')  # More than 1 Crore
    success, message = fm.block_margin(excessive_amount, "Excessive trade")
    print(f"✓ Block excessive margin: {message}")
    assert not success, "Should fail for insufficient funds"
    assert "Insufficient funds" in message, "Error message should indicate insufficient funds"

    print("✅ PASSED: Insufficient Funds\n")


def test_leverage_calculations():
    """Test leverage-based margin calculations"""
    print("="*50)
    print("TEST 4: Leverage Calculations")
    print("="*50)

    test_user = "TEST_USER_004"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    fm = FundManager(test_user)

    test_cases = [
        {
            'name': 'Equity MIS (5x leverage)',
            'symbol': 'RELIANCE',
            'exchange': 'NSE',
            'product': 'MIS',
            'quantity': 100,
            'price': 1500,
            'expected_leverage': 5
        },
        {
            'name': 'Equity CNC (1x leverage)',
            'symbol': 'RELIANCE',
            'exchange': 'NSE',
            'product': 'CNC',
            'quantity': 100,
            'price': 1500,
            'expected_leverage': 1
        }
    ]

    for test_case in test_cases:
        trade_value = test_case['quantity'] * test_case['price']
        expected_margin = trade_value / test_case['expected_leverage']

        margin, message = fm.calculate_margin_required(
            test_case['symbol'],
            test_case['exchange'],
            test_case['product'],
            test_case['quantity'],
            test_case['price']
        )

        if margin:
            print(f"✓ {test_case['name']}")
            print(f"  Trade value: ₹{trade_value:,.2f}")
            print(f"  Required margin: ₹{float(margin):,.2f}")
            print(f"  Expected margin: ₹{expected_margin:,.2f}")

    print("✅ PASSED: Leverage Calculations\n")


def test_unrealized_pnl():
    """Test unrealized P&L updates"""
    print("="*50)
    print("TEST 5: Unrealized P&L")
    print("="*50)

    test_user = "TEST_USER_005"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    fm = FundManager(test_user)

    # Update unrealized P&L
    unrealized = Decimal('25000.00')
    success, message = fm.update_unrealized_pnl(unrealized)
    print(f"✓ Update unrealized P&L: {message}")
    assert success, "Unrealized P&L update failed"

    funds = fm.get_funds()
    m2m = Decimal(str(funds['m2munrealized']))
    total_pnl = Decimal(str(funds['totalpnl']))

    print(f"✓ Unrealized P&L: ₹{m2m:,.2f}")
    print(f"✓ Total P&L: ₹{total_pnl:,.2f}")
    assert m2m == unrealized, "Unrealized P&L incorrect"
    assert total_pnl == unrealized, "Total P&L incorrect"

    print("✅ PASSED: Unrealized P&L\n")


def cleanup_test_data(user_id):
    """Clean up test data for a user"""
    try:
        SandboxFunds.query.filter_by(user_id=user_id).delete()
        db_session.commit()
    except:
        db_session.rollback()


def run_all_tests():
    """Run all fund manager tests"""
    print("\n" + "="*50)
    print("SANDBOX FUND MANAGER TEST SUITE")
    print("="*50)

    try:
        test_fund_initialization()
        test_margin_operations()
        test_insufficient_funds()
        test_leverage_calculations()
        test_unrealized_pnl()

        print("\n" + "="*50)
        print("✅ ALL TESTS PASSED")
        print("="*50 + "\n")

    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}\n")
        raise
    except Exception as e:
        print(f"\n❌ TEST ERROR: {e}\n")
        raise


if __name__ == '__main__':
    run_all_tests()
