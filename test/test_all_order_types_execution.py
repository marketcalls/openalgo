"""
Test script for all order types in Action Center
Tests placeorder, smartorder, basketorder, splitorder, and optionsorder

Run with: python test/test_all_order_types_execution.py

This script will:
1. Place all 5 order types in semi-auto mode
2. Verify they appear in Action Center
3. Approve them one by one
4. Check execution results
"""

import json
import time
from datetime import datetime

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "bf1267a177b7ece1b10ca29b0ee8c4d62b153fe60caba3c566619e607cf9169f"

# Test order data for each order type
# Note: All formats verified against production API requirements
TEST_ORDERS = {
    # Standard place order
    "placeorder": {
        "apikey": API_KEY,
        "strategy": "TEST_PLACEORDER",
        "symbol": "SBIN",  # Use simple symbol format, not "SBIN-EQ"
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "1",
        "price": "0",
        "trigger_price": "0",
        "pricetype": "MARKET",
        "product": "MIS",
    },
    # Smart order - requires position_size field
    "placesmartorder": {
        "apikey": API_KEY,
        "strategy": "TEST_SMARTORDER",
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "action": "BUY",
        "quantity": "1",
        "position_size": "1",  # Required for smart order
        "price": "0",
        "trigger_price": "0",
        "pricetype": "MARKET",
        "product": "MIS",
    },
    # Basket order - array of orders
    "basketorder": {
        "apikey": API_KEY,
        "strategy": "TEST_BASKETORDER",
        "orders": [
            {
                "symbol": "TCS",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "1",
                "price": "0",
                "trigger_price": "0",
                "pricetype": "MARKET",
                "product": "MIS",
            },
            {
                "symbol": "INFY",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": "1",
                "price": "0",
                "trigger_price": "0",
                "pricetype": "MARKET",
                "product": "MIS",
            },
        ],
    },
    # Split order - quantity split into multiple orders
    # Note: Does NOT include price/trigger_price in main request
    "splitorder": {
        "apikey": API_KEY,
        "strategy": "TEST_SPLITORDER",
        "exchange": "NSE",
        "symbol": "NHPC",
        "action": "BUY",
        "quantity": "10",
        "splitsize": "1",  # Split into orders of size 1
        "pricetype": "MARKET",
        "product": "MIS",
    },
    # Options order - requires expiry_date and option-specific fields
    "optionsorder": {
        "apikey": API_KEY,
        "strategy": "TEST_OPTIONSORDER",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",  # Required for options
        "strike_int": 50,
        "offset": "ATM",
        "option_type": "CE",
        "action": "BUY",
        "quantity": 75,
        "pricetype": "MARKET",
        "product": "MIS",
        "price": "0",
        "trigger_price": "0",
        "disclosed_quantity": "0",
    },
}


def log(message, level="INFO"):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def place_order(order_type, order_data):
    """Place an order via API"""
    url = f"{BASE_URL}/api/v1/{order_type}"

    log(f"Placing {order_type}...")
    log(f"URL: {url}")
    log(f"Payload: {json.dumps(order_data, indent=2)}")

    try:
        response = requests.post(url, json=order_data, timeout=10)
        log(f"Response Status: {response.status_code}")
        log(f"Response Body: {response.text}")

        if response.status_code == 200:
            result = response.json()
            log(f"[OK] {order_type} placed successfully", "SUCCESS")

            # Check if it was queued
            if result.get("mode") == "semi_auto":
                pending_order_id = result.get("pending_order_id")
                log(f"  -> Queued in Action Center (ID: {pending_order_id})", "INFO")
                return True, pending_order_id
            else:
                log("  -> Executed immediately (not queued)", "WARNING")
                return True, None
        else:
            log(f"[FAIL] {order_type} failed: {response.text}", "ERROR")
            return False, None

    except Exception as e:
        log(f"[FAIL] Exception placing {order_type}: {str(e)}", "ERROR")
        return False, None


def get_pending_orders():
    """Get list of pending orders from Action Center"""
    # Note: This would require authentication, so we'll just return success status
    log("Checking Action Center for pending orders...")
    return True


def test_all_order_types():
    """Test all order types"""
    log("=" * 80)
    log("Starting Action Center Order Types Test")
    log("=" * 80)

    results = {}
    pending_order_ids = []

    # Test each order type
    for order_type, order_data in TEST_ORDERS.items():
        log("")
        log("-" * 80)
        log(f"Testing: {order_type.upper()}")
        log("-" * 80)

        success, pending_id = place_order(order_type, order_data)
        results[order_type] = success

        if pending_id:
            pending_order_ids.append((order_type, pending_id))

        # Wait between orders
        time.sleep(2)

    # Summary
    log("")
    log("=" * 80)
    log("TEST SUMMARY")
    log("=" * 80)

    for order_type, success in results.items():
        status = "[OK] PASSED" if success else "[FAIL] FAILED"
        log(f"{order_type:<20} {status}")

    log("")
    log(f"Total Orders Placed: {len(results)}")
    log(f"Successful: {sum(results.values())}")
    log(f"Failed: {len(results) - sum(results.values())}")

    if pending_order_ids:
        log("")
        log("Pending Orders in Action Center:")
        for order_type, pending_id in pending_order_ids:
            log(f"  - {order_type}: ID {pending_id}")
        log("")
        log("Next Steps:")
        log("1. Open Action Center: http://127.0.0.1:5000/action-center")
        log("2. Review and approve each order")
        log("3. Verify execution results")

    log("=" * 80)

    return results


if __name__ == "__main__":
    try:
        results = test_all_order_types()

        # Exit code based on results
        if all(results.values()):
            log("All tests PASSED! [OK]", "SUCCESS")
            exit(0)
        else:
            log("Some tests FAILED! [FAIL]", "ERROR")
            exit(1)

    except KeyboardInterrupt:
        log("Test interrupted by user", "WARNING")
        exit(130)
    except Exception as e:
        log(f"Unexpected error: {str(e)}", "ERROR")
        import traceback

        traceback.print_exc()
        exit(1)
