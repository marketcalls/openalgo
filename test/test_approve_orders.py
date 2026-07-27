"""
Diagnostic script to test order approval and execution
Run with: python test/test_approve_orders.py
"""

import os
import sys

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

from database.action_center_db import get_pending_order_by_id, get_pending_orders
from services.pending_order_execution_service import execute_approved_order


def test_order_execution():
    """Test execution of pending orders"""

    # Get all pending orders
    print("=" * 80)
    print("PENDING ORDERS IN ACTION CENTER")
    print("=" * 80)

    # Note: Replace 'openalgo' with your actual user_id
    user_id = "openalgo"

    orders = get_pending_orders(user_id, status="pending")

    if not orders:
        print("No pending orders found")
        return

    print(f"\nFound {len(orders)} pending order(s):")
    print()

    for order in orders:
        print(f"Order ID: {order.id}")
        print(f"API Type: {order.api_type}")
        print(f"Status: {order.status}")
        print(f"Created: {order.created_at_ist}")

        # Parse and display order data
        try:
            order_data = json.loads(order.order_data)
            print(f"Order Data: {json.dumps(order_data, indent=2)}")
        except:
            print(f"Order Data (raw): {order.order_data}")

        print("-" * 80)

    # Ask user which order to test
    print()
    order_id_to_test = input("Enter Order ID to test execution (or 'q' to quit): ").strip()

    if order_id_to_test.lower() == "q":
        return

    try:
        order_id = int(order_id_to_test)
    except:
        print("Invalid order ID")
        return

    # Get the specific order
    pending_order = get_pending_order_by_id(order_id)
    if not pending_order:
        print(f"Order {order_id} not found")
        return

    print()
    print("=" * 80)
    print(f"TESTING EXECUTION OF ORDER {order_id}")
    print("=" * 80)
    print(f"API Type: {pending_order.api_type}")
    print()

    # First approve it
    from database.action_center_db import approve_pending_order

    approve_success = approve_pending_order(order_id, approved_by="test_user")

    if not approve_success:
        print("Failed to approve order")
        return

    print("✓ Order approved successfully")
    print()
    print("Attempting execution...")
    print()

    # Try to execute
    try:
        success, response_data, status_code = execute_approved_order(order_id)

        print("Execution Result:")
        print(f"  Success: {success}")
        print(f"  Status Code: {status_code}")
        print(f"  Response: {json.dumps(response_data, indent=2)}")

        if success:
            print()
            print("✓ ORDER EXECUTED SUCCESSFULLY!")
        else:
            print()
            print("✗ ORDER EXECUTION FAILED")
            print(f"  Error: {response_data.get('message', 'Unknown error')}")

    except Exception as e:
        print("✗ EXCEPTION DURING EXECUTION:")
        print(f"  {type(e).__name__}: {str(e)}")
        import traceback

        traceback.print_exc()


if __name__ == "__main__":
    test_order_execution()
