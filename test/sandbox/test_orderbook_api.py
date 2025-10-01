#!/usr/bin/env python3
"""
Test that rejected orders appear correctly in the orderbook API response
"""
from decimal import Decimal
from database.sandbox_db import init_db, db_session, SandboxOrders
from sandbox.order_manager import OrderManager

# Initialize database
init_db()

# Test user
user_id = 'rajandran'

# Get order manager
om = OrderManager(user_id)

# Get orderbook
success, response, code = om.get_orderbook()

print("📋 Orderbook API Response")
print("="*60)
print(f"Success: {success}")
print(f"Status Code: {code}")
print(f"\nResponse:")
print(f"  Status: {response.get('status')}")
print(f"  Mode: {response.get('mode')}")

# Check for rejected orders
if 'data' in response:
    data = response['data']

    # Extract orders list from data dict
    if isinstance(data, dict) and 'orders' in data:
        order_list = data['orders']
        print(f"\n  Total Orders: {len(order_list)}")
    elif isinstance(data, list):
        order_list = data
        print(f"\n  Total Orders: {len(order_list)}")
    else:
        order_list = []
        print(f"\n  Unexpected data structure")

    # Filter rejected orders
    rejected_orders = [o for o in order_list if isinstance(o, dict) and o.get('order_status') == 'rejected']

    if rejected_orders:
        print(f"\n  ❌ Rejected Orders: {len(rejected_orders)}")
        for order in rejected_orders:
            print(f"\n    Order ID: {order['orderid']}")
            print(f"    Symbol: {order['symbol']}")
            print(f"    Action: {order['action']}")
            print(f"    Quantity: {order['quantity']}")
            print(f"    Product: {order['product']}")
            print(f"    Status: {order['order_status']}")
            print(f"    Rejection Reason: {order.get('rejection_reason', 'N/A')}")
    else:
        print("\n  ✅ No rejected orders")

    # Check statistics
    if 'statistics' in response:
        stats = response['statistics']
        print(f"\n  📊 Statistics:")
        print(f"    Total Buy Orders: {stats.get('total_buy_orders', 0)}")
        print(f"    Total Sell Orders: {stats.get('total_sell_orders', 0)}")
        print(f"    Open Orders: {stats.get('total_open_orders', 0)}")
        print(f"    Completed Orders: {stats.get('total_completed_orders', 0)}")
        print(f"    Rejected Orders: {stats.get('total_rejected_orders', 0)}")

print("\n" + "="*60)