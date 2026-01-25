"""
Test script for Options Multi-Order API

This script demonstrates how to place multiple option legs using the /api/v1/optionsmultiorder endpoint.
The API automatically resolves option symbols based on offset and executes BUY legs first for margin efficiency.

Works in both:
- Live Mode: Places real orders with the broker
- Analyze Mode (Sandbox): Places virtual orders for testing

Make sure the OpenAlgo application is running before executing this script.

Usage:
    cd D:/openalgo-class/openalgo/test
    python test_options_multiorder_api.py
"""

import os
import sys

# Add parent directory to path so we can import from openalgo modules if needed
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "c32eb9dee6673190bb9dfab5f18ef0a96b0d76ba484cd36bc5ca5f7ebc8745bf"


def test_iron_condor():
    """Test 1: Iron Condor Strategy - 4 Legs"""
    print("\n" + "=" * 60)
    print("Test 1: Iron Condor (4 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Iron Condor",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",
        "legs": [
            {"offset": "OTM10", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM10", "option_type": "PE", "action": "BUY", "quantity": 75},
            {"offset": "OTM5", "option_type": "CE", "action": "SELL", "quantity": 75},
            {"offset": "OTM5", "option_type": "PE", "action": "SELL", "quantity": 75},
        ],
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


def test_long_straddle():
    """Test 2: Long Straddle Strategy - 2 Legs"""
    print("\n" + "=" * 60)
    print("Test 2: Long Straddle (2 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Long Straddle",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30DEC25",
        "legs": [
            {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "ATM", "option_type": "PE", "action": "BUY", "quantity": 75},
        ],
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


def test_short_straddle():
    """Test 3: Short Straddle Strategy - 2 Legs"""
    print("\n" + "=" * 60)
    print("Test 3: Short Straddle (2 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Short Straddle",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30DEC25",
        "legs": [
            {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 75},
            {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": 75},
        ],
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


def test_bull_call_spread():
    """Test 4: Bull Call Spread - 2 Legs"""
    print("\n" + "=" * 60)
    print("Test 4: Bull Call Spread (2 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Bull Call Spread",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",
        "legs": [
            {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM3", "option_type": "CE", "action": "SELL", "quantity": 75},
        ],
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


def test_long_call_butterfly():
    """Test 5: Long Call Butterfly - 3 Legs with different quantities"""
    print("\n" + "=" * 60)
    print("Test 5: Long Call Butterfly (3 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Long Call Butterfly",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30DEC25",
        "legs": [
            {"offset": "ITM2", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 150},
            {"offset": "OTM2", "option_type": "CE", "action": "BUY", "quantity": 75},
        ],
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


def test_call_ratio_spread():
    """Test 6: Call Ratio Spread (1:2 ratio)"""
    print("\n" + "=" * 60)
    print("Test 6: Call Ratio Spread (1:2 ratio)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Call Ratio Spread",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30DEC25",
        "legs": [
            {"offset": "ATM", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM3", "option_type": "CE", "action": "SELL", "quantity": 150},
        ],
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


def test_iron_butterfly():
    """Test 7: Iron Butterfly - 4 Legs"""
    print("\n" + "=" * 60)
    print("Test 7: Iron Butterfly (4 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Iron Butterfly",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",
        "legs": [
            {"offset": "OTM5", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM5", "option_type": "PE", "action": "BUY", "quantity": 75},
            {"offset": "ATM", "option_type": "CE", "action": "SELL", "quantity": 75},
            {"offset": "ATM", "option_type": "PE", "action": "SELL", "quantity": 75},
        ],
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


def test_limit_orders():
    """Test 8: Multi-leg with LIMIT orders"""
    print("\n" + "=" * 60)
    print("Test 8: Straddle with LIMIT Orders")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Straddle LIMIT",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "30DEC25",
        "legs": [
            {
                "offset": "ATM",
                "option_type": "CE",
                "action": "BUY",
                "quantity": 75,
                "pricetype": "LIMIT",
                "product": "MIS",
                "price": 250.0,
            },
            {
                "offset": "ATM",
                "option_type": "PE",
                "action": "BUY",
                "quantity": 75,
                "pricetype": "LIMIT",
                "product": "MIS",
                "price": 250.0,
            },
        ],
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


def test_future_underlying():
    """Test 9: Using Future as Underlying"""
    print("\n" + "=" * 60)
    print("Test 9: Bull Call Spread with Future Underlying")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Futures Bull Spread",
        "underlying": "NIFTY25NOV25FUT",
        "exchange": "NFO",
        "expiry_date": "25NOV25",
        "legs": [
            {
                "offset": "ATM",
                "option_type": "CE",
                "action": "BUY",
                "quantity": 75,
                "product": "NRML",
            },
            {
                "offset": "OTM3",
                "option_type": "CE",
                "action": "SELL",
                "quantity": 75,
                "product": "NRML",
            },
        ],
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


def test_validation_error():
    """Test 10: Validation Error - Empty legs"""
    print("\n" + "=" * 60)
    print("Test 10: Validation Error - Empty Legs")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Test Strategy",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",
        "legs": [],  # Empty legs - should cause validation error
    }

    print("\nRequest Payload (Empty legs):")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        print(json.dumps(response.json(), indent=2))
    except Exception as e:
        print(f"Error: {e}")


def test_jade_lizard():
    """Test 11: Jade Lizard - 3 Legs"""
    print("\n" + "=" * 60)
    print("Test 11: Jade Lizard (3 Legs)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Jade Lizard",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "25NOV25",
        "legs": [
            {"offset": "OTM5", "option_type": "CE", "action": "BUY", "quantity": 75},
            {"offset": "OTM2", "option_type": "CE", "action": "SELL", "quantity": 75},
            {"offset": "OTM3", "option_type": "PE", "action": "SELL", "quantity": 75},
        ],
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


def test_diagonal_spread():
    """Test 12: Diagonal Spread - Different Strikes & Expiries"""
    print("\n" + "=" * 60)
    print("Test 12: Diagonal Spread (Different Strikes & Expiries)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Diagonal Spread",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "legs": [
            {
                "offset": "ITM2",
                "option_type": "CE",
                "action": "BUY",
                "quantity": 75,
                "expiry_date": "30DEC25",
            },
            {
                "offset": "OTM2",
                "option_type": "CE",
                "action": "SELL",
                "quantity": 75,
                "expiry_date": "25NOV25",
            },
        ],
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


def test_calendar_spread():
    """Test 13: Calendar Spread - Same Strike, Different Expiries"""
    print("\n" + "=" * 60)
    print("Test 13: Calendar Spread (Same Strike, Different Expiries)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsmultiorder"

    payload = {
        "apikey": API_KEY,
        "strategy": "Calendar Spread",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "legs": [
            {
                "offset": "ATM",
                "option_type": "CE",
                "action": "BUY",
                "quantity": 75,
                "expiry_date": "30DEC25",
            },
            {
                "offset": "ATM",
                "option_type": "CE",
                "action": "SELL",
                "quantity": 75,
                "expiry_date": "25NOV25",
            },
        ],
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


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OpenAlgo Options Multi-Order API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print("\nNote: Replace API_KEY in this script with your actual API key")
    print("\nExecution Order: BUY legs execute first, then SELL legs")
    print("\nAnalyze Mode Status:")
    print("  - If Analyze Mode is ON: Orders will be placed in sandbox (virtual)")
    print("  - If Analyze Mode is OFF: Orders will be placed with live broker")
    print("=" * 60)

    # Run tests with 3-second delay between each
    test_iron_condor()
    time.sleep(3)
    test_long_straddle()
    time.sleep(3)
    test_short_straddle()
    time.sleep(3)
    test_bull_call_spread()
    time.sleep(3)
    test_long_call_butterfly()
    time.sleep(3)
    test_call_ratio_spread()
    time.sleep(3)
    test_iron_butterfly()
    time.sleep(3)
    test_limit_orders()
    time.sleep(3)
    test_future_underlying()
    time.sleep(3)
    test_validation_error()
    time.sleep(3)
    test_jade_lizard()
    time.sleep(3)
    test_diagonal_spread()
    time.sleep(3)
    test_calendar_spread()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
