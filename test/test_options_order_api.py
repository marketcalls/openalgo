"""
Test script for Options Order API

This script demonstrates how to place options orders using the /api/v1/optionsorder endpoint.
The API automatically resolves the option symbol based on underlying and offset, then places the order.

Works in both:
- Live Mode: Places real orders with the broker
- Analyze Mode (Sandbox): Places virtual orders for testing

Make sure the OpenAlgo application is running before executing this script.

Usage:
    cd D:/openalgo-sandbox-test/openalgo/test
    python test_options_order_api.py
"""

import os
import sys

# Add parent directory to path so we can import from openalgo modules if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "your_api_key_here"  # Replace with your actual API key


def test_nifty_atm_call_buy():
    """Test 1: Buy NIFTY ATM Call Option"""
    print("\n" + "=" * 60)
    print("Test 1: Buy NIFTY ATM Call (MIS)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "nifty_options",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 50,
        "offset": "ATM",
        "option_type": "CE",
        "action": "BUY",
        "quantity": 75,  # 75 qty = 3 lots (25 lot size)
        "pricetype": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "disclosed_quantity": 0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_banknifty_itm2_put_sell():
    """Test 2: Sell BANKNIFTY ITM2 Put Option"""
    print("\n" + "=" * 60)
    print("Test 2: Sell BANKNIFTY ITM2 Put (NRML)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "banknifty_options",
        "underlying": "BANKNIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 100,
        "offset": "ITM2",
        "option_type": "PE",
        "action": "SELL",
        "quantity": 30,  # 30 qty = 2 lots (15 lot size)
        "pricetype": "MARKET",
        "product": "NRML",
        "price": 0.0,
        "trigger_price": 0.0,
        "disclosed_quantity": 0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_embedded_expiry():
    """Test 3: Using underlying with embedded expiry (NIFTY28NOV24FUT)"""
    print("\n" + "=" * 60)
    print("Test 3: Buy Option using Future with Embedded Expiry")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "futures_options",
        "underlying": "NIFTY28NOV24FUT",  # Expiry embedded
        "exchange": "NFO",
        "strike_int": 50,
        "offset": "OTM3",
        "option_type": "CE",
        "action": "BUY",
        "quantity": 50,
        "pricetype": "MARKET",
        "product": "MIS",
        "price": 0.0,
        "trigger_price": 0.0,
        "disclosed_quantity": 0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_limit_order():
    """Test 4: Place LIMIT order for option"""
    print("\n" + "=" * 60)
    print("Test 4: Buy NIFTY OTM1 Call with LIMIT order")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "nifty_scalping",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 50,
        "offset": "OTM1",
        "option_type": "CE",
        "action": "BUY",
        "quantity": 75,
        "pricetype": "LIMIT",
        "product": "MIS",
        "price": 50.0,  # Limit price
        "trigger_price": 0.0,
        "disclosed_quantity": 0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_sl_order():
    """Test 5: Place SL order for option"""
    print("\n" + "=" * 60)
    print("Test 5: Sell NIFTY ATM Put with SL order")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "straddle_exit",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 50,
        "offset": "ATM",
        "option_type": "PE",
        "action": "SELL",
        "quantity": 75,
        "pricetype": "SL",
        "product": "MIS",
        "price": 100.0,  # Limit price after trigger
        "trigger_price": 105.0,  # Stop loss trigger price
        "disclosed_quantity": 0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_iron_condor_legs():
    """Test 6: Place multiple legs for Iron Condor strategy"""
    print("\n" + "=" * 60)
    print("Test 6: Iron Condor - 4 Legs")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    # Iron Condor: Sell OTM1 Call, Sell OTM1 Put, Buy OTM3 Call, Buy OTM3 Put
    legs = [
        {"offset": "OTM1", "option_type": "CE", "action": "SELL", "desc": "Sell OTM1 Call"},
        {"offset": "OTM1", "option_type": "PE", "action": "SELL", "desc": "Sell OTM1 Put"},
        {"offset": "OTM3", "option_type": "CE", "action": "BUY", "desc": "Buy OTM3 Call"},
        {"offset": "OTM3", "option_type": "PE", "action": "BUY", "desc": "Buy OTM3 Put"},
    ]

    for leg in legs:
        print(f"\n--- {leg['desc']} ---")

        payload = {
            "apikey": API_KEY,
            "strategy": "iron_condor",
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry_date": "28NOV24",
            "strike_int": 50,
            "offset": leg["offset"],
            "option_type": leg["option_type"],
            "action": leg["action"],
            "quantity": 75,
            "pricetype": "MARKET",
            "product": "MIS",
            "price": 0.0,
            "trigger_price": 0.0,
            "disclosed_quantity": 0,
        }

        try:
            response = requests.post(url, json=payload)
            data = response.json()

            if data.get("status") == "success":
                print(f"✓ Order ID: {data.get('orderid')}")
                print(f"  Symbol: {data.get('symbol')}")
                print(f"  Exchange: {data.get('exchange')}")
                if "mode" in data:
                    print(f"  Mode: {data.get('mode')}")
            else:
                print(f"✗ Error: {data.get('message')}")

        except Exception as e:
            print(f"✗ Exception: {e}")


def test_validation_error():
    """Test 7: Validation error - Missing required field"""
    print("\n" + "=" * 60)
    print("Test 7: Validation Error Test")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "test",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        # Missing strike_int - should cause validation error
        "offset": "ATM",
        "option_type": "CE",
        "action": "BUY",
        "quantity": 75,
        "pricetype": "MARKET",
        "product": "MIS",
    }

    print("\nRequest Payload (Missing strike_int):")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OpenAlgo Options Order API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print("\nNote: Replace API_KEY in this script with your actual API key")
    print("\nAnalyze Mode Status:")
    print("  - If Analyze Mode is ON: Orders will be placed in sandbox (virtual)")
    print("  - If Analyze Mode is OFF: Orders will be placed with live broker")
    print("=" * 60)

    # Run tests
    test_nifty_atm_call_buy()
    test_banknifty_itm2_put_sell()
    test_embedded_expiry()
    test_limit_order()
    test_sl_order()
    test_iron_condor_legs()
    test_validation_error()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
