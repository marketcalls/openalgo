# test/sandbox/test_execution_engine_session.py
"""
Test suite for Execution Engine Session-Based Order Handling

Tests:
- Session start calculation
- Stale order detection and auto-cancellation
- Current session order processing
"""

import sys
import os
from datetime import datetime, timedelta
from decimal import Decimal

# Add parent directories to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from database.sandbox_db import (
    SandboxOrders, SandboxTrades, SandboxPositions, 
    SandboxFunds, db_session
)
from sandbox.utils import get_sandbox_session_start
from sandbox.execution_engine import ExecutionEngine
from sandbox.fund_manager import initialize_user_funds


def cleanup_test_data(user_id):
    """Clean up all test data for a user across all sandbox tables"""
    try:
        SandboxOrders.query.filter_by(user_id=user_id).delete()
        SandboxTrades.query.filter_by(user_id=user_id).delete()
        SandboxPositions.query.filter_by(user_id=user_id).delete()
        SandboxFunds.query.filter_by(user_id=user_id).delete()
        db_session.commit()
    except Exception as e:
        db_session.rollback()
        # Log cleanup warning but don't fail - tests should continue
        print(f"Warning: Cleanup for {user_id} failed: {e}")


def test_session_start_calculation():
    """Test session start time calculation"""
    import pytz
    
    print("\n" + "="*50)
    print("TEST 1: Session Start Calculation")
    print("="*50)

    session_start = get_sandbox_session_start()
    print(f"Session start: {session_start}")

    # Session start is a naive datetime representing IST time
    # We need to compare with IST time, not system-local time
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    # Strip timezone to get naive datetime for comparison (both represent IST)
    now_naive_ist = now_ist.replace(tzinfo=None)
    
    assert session_start <= now_naive_ist, "Session start should not be in the future"

    # Session start should be within the last 24 hours
    yesterday_ist = now_naive_ist - timedelta(days=1)
    assert session_start >= yesterday_ist, "Session start should be within last 24 hours"

    print("PASSED: Session Start Calculation\n")


def test_stale_order_detection():
    """Test that stale orders from previous sessions are detected and cancelled"""
    print("="*50)
    print("TEST 2: Stale Order Detection")
    print("="*50)

    test_user = "TEST_USER_SESSION_001"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    session_start = get_sandbox_session_start()

    # Create a stale order (from previous session)
    stale_timestamp = session_start - timedelta(hours=2)
    stale_order = SandboxOrders(
        orderid="STALE_ORDER_001",
        user_id=test_user,
        symbol="RELIANCE",
        exchange="NSE",
        action="BUY",
        quantity=100,
        price=Decimal('1430.00'),
        price_type="LIMIT",
        product="MIS",
        order_status="open",
        pending_quantity=100,
        margin_blocked=Decimal('30000.00'),
        order_timestamp=stale_timestamp
    )
    db_session.add(stale_order)

    # Create a current session order
    current_timestamp = session_start + timedelta(hours=1)
    current_order = SandboxOrders(
        orderid="CURRENT_ORDER_001",
        user_id=test_user,
        symbol="INFY",
        exchange="NSE",
        action="BUY",
        quantity=50,
        price=Decimal('1200.00'),
        price_type="LIMIT",
        product="MIS",
        order_status="open",
        pending_quantity=50,
        margin_blocked=Decimal('12000.00'),
        order_timestamp=current_timestamp
    )
    db_session.add(current_order)
    db_session.commit()

    print(f"Created stale order: {stale_order.orderid} @ {stale_timestamp}")
    print(f"Created current order: {current_order.orderid} @ {current_timestamp}")

    # Verify orders are in database
    all_orders = SandboxOrders.query.filter_by(user_id=test_user, order_status='open').all()
    assert len(all_orders) == 2, f"Expected 2 open orders, got {len(all_orders)}"
    print(f"Total open orders before processing: {len(all_orders)}")

    # Run execution engine
    engine = ExecutionEngine()
    engine.check_and_execute_pending_orders()

    # Expire all cached objects to get fresh data from DB
    db_session.expire_all()

    # Check results
    stale_order_after = SandboxOrders.query.filter_by(orderid="STALE_ORDER_001").first()
    current_order_after = SandboxOrders.query.filter_by(orderid="CURRENT_ORDER_001").first()

    print(f"Stale order status after processing: {stale_order_after.order_status}")
    print(f"Current order status after processing: {current_order_after.order_status}")

    assert stale_order_after.order_status == 'cancelled', "Stale order should be cancelled"
    assert current_order_after.order_status == 'open', "Current order should remain open"

    # Cleanup
    cleanup_test_data(test_user)

    print("PASSED: Stale Order Detection\n")


def test_no_stale_orders():
    """Test behavior when all orders are from current session"""
    print("="*50)
    print("TEST 3: No Stale Orders")
    print("="*50)

    test_user = "TEST_USER_SESSION_002"
    cleanup_test_data(test_user)
    initialize_user_funds(test_user)

    session_start = get_sandbox_session_start()

    # Create only current session orders
    current_timestamp = session_start + timedelta(minutes=30)
    current_order = SandboxOrders(
        orderid="CURRENT_ORDER_002",
        user_id=test_user,
        symbol="TCS",
        exchange="NSE",
        action="BUY",
        quantity=25,
        price=Decimal('3100.00'),
        price_type="LIMIT",
        product="MIS",
        order_status="open",
        pending_quantity=25,
        margin_blocked=Decimal('17500.00'),
        order_timestamp=current_timestamp
    )
    db_session.add(current_order)
    db_session.commit()

    print(f"Created current order: {current_order.orderid}")

    # Run execution engine
    engine = ExecutionEngine()
    engine.check_and_execute_pending_orders()

    # Expire all cached objects to get fresh data from DB
    db_session.expire_all()

    # Order should remain open (no stale orders to cancel)
    order_after = SandboxOrders.query.filter_by(orderid="CURRENT_ORDER_002").first()
    assert order_after.order_status == 'open', "Current order should remain open"

    print(f"Order status after processing: {order_after.order_status}")

    # Cleanup
    cleanup_test_data(test_user)

    print("PASSED: No Stale Orders\n")


def run_all_tests():
    """Run all execution engine session tests"""
    print("\n" + "="*50)
    print("EXECUTION ENGINE SESSION TEST SUITE")
    print("="*50)

    try:
        test_session_start_calculation()
        test_stale_order_detection()
        test_no_stale_orders()

        print("\n" + "="*50)
        print("ALL TESTS PASSED")
        print("="*50 + "\n")

    except AssertionError as e:
        print(f"\nTEST FAILED: {e}\n")
        raise
    except Exception as e:
        print(f"\nTEST ERROR: {e}\n")
        import traceback
        traceback.print_exc()
        raise


if __name__ == '__main__':
    run_all_tests()
