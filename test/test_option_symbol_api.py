"""
Test script for Option Symbol API

This script demonstrates how to use the /api/v1/optionsymbol endpoint
to fetch option symbols based on underlying, expiry, and strike offset.

Make sure the OpenAlgo application is running before executing this script.

Usage:
    cd D:/openalgo-sandbox-test/openalgo/test
    python test_option_symbol_api.py
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


def test_option_symbol_nifty_index():
    """Test with NIFTY index symbol"""
    print("\n" + "=" * 60)
    print("Test 1: NIFTY Index Option Symbol")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    payload = {
        "apikey": API_KEY,
        "strategy": "test_strategy",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",  # Use current month expiry
        "strike_int": 50,
        "offset": "ITM2",
        "option_type": "CE",
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


def test_option_symbol_with_embedded_expiry():
    """Test with underlying that includes expiry (NIFTY28OCT25FUT)"""
    print("\n" + "=" * 60)
    print("Test 2: NIFTY Future with Embedded Expiry")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    payload = {
        "apikey": API_KEY,
        "strategy": "test_strategy",
        "underlying": "NIFTY28NOV24FUT",  # Expiry embedded in symbol
        "exchange": "NFO",
        "strike_int": 50,
        "offset": "ATM",
        "option_type": "PE",
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


def test_option_symbol_banknifty():
    """Test with BANKNIFTY (different strike interval)"""
    print("\n" + "=" * 60)
    print("Test 3: BANKNIFTY Option Symbol")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    payload = {
        "apikey": API_KEY,
        "strategy": "test_strategy",
        "underlying": "BANKNIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 100,  # BANKNIFTY uses 100 strike interval
        "offset": "OTM5",
        "option_type": "CE",
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


def test_option_symbol_equity():
    """Test with equity symbol (RELIANCE)"""
    print("\n" + "=" * 60)
    print("Test 4: Equity Option Symbol (RELIANCE)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    payload = {
        "apikey": API_KEY,
        "strategy": "test_strategy",
        "underlying": "RELIANCE",
        "exchange": "NSE",
        "expiry_date": "28NOV24",
        "strike_int": 10,  # Equity options typically have smaller intervals
        "offset": "ITM1",
        "option_type": "PE",
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
    """Test with invalid offset to see validation error"""
    print("\n" + "=" * 60)
    print("Test 5: Validation Error (Invalid Offset)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    payload = {
        "apikey": API_KEY,
        "strategy": "test_strategy",
        "underlying": "NIFTY",
        "exchange": "NSE_INDEX",
        "expiry_date": "28NOV24",
        "strike_int": 50,
        "offset": "ITM100",  # Invalid - exceeds ITM50 limit
        "option_type": "CE",
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


def test_all_offsets():
    """Test multiple offsets for the same underlying"""
    print("\n" + "=" * 60)
    print("Test 6: Multiple Offsets for NIFTY")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optionsymbol"

    offsets = ["ITM5", "ITM3", "ITM1", "ATM", "OTM1", "OTM3", "OTM5"]

    for offset in offsets:
        payload = {
            "apikey": API_KEY,
            "strategy": "test_strategy",
            "underlying": "NIFTY",
            "exchange": "NSE_INDEX",
            "expiry_date": "28NOV24",
            "strike_int": 50,
            "offset": offset,
            "option_type": "CE",
        }

        try:
            response = requests.post(url, json=payload)
            data = response.json()

            if data.get("status") == "success":
                symbol = data.get("symbol", "N/A")
                lotsize = data.get("lotsize", "N/A")
                ltp = data.get("underlying_ltp", "N/A")
                print(f"\n{offset:6s}: Symbol={symbol}, LTP={ltp}, Lotsize={lotsize}")
            else:
                print(f"\n{offset:6s}: Error - {data.get('message')}")

        except Exception as e:
            print(f"\n{offset:6s}: Exception - {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OpenAlgo Option Symbol API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print("\nNote: Replace API_KEY in this script with your actual API key")
    print("=" * 60)

    # Run tests
    test_option_symbol_nifty_index()
    test_option_symbol_with_embedded_expiry()
    test_option_symbol_banknifty()
    test_option_symbol_equity()
    test_validation_error()
    test_all_offsets()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
