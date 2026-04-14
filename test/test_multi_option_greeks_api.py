"""
Test script for Multi Option Greeks API

This script demonstrates how to use the /api/v1/multioptiongreeks endpoint
to calculate option Greeks for multiple symbols in a single request.

Prerequisites:
1. Install py_vollib library: pip install py_vollib
2. OpenAlgo must be running
3. Markets should be open for live prices

Usage:
    cd c:\\Users\\Karthik\\Downloads\\openalgo-chart\\openalgo\\test
    python test_multi_option_greeks_api.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "your_api_key_here"  # Replace with your actual API key


def test_multiple_nifty_options():
    """Test 1: Multiple NIFTY Options (CE + PE)"""
    print("\n" + "=" * 60)
    print("Test 1: Multiple NIFTY Options (CE + PE)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/multioptiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbols": [
            {"symbol": "NIFTY30DEC2526000CE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2526000PE", "exchange": "NFO"},
        ],
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        result = response.json()
        print("Response Body:")
        print(json.dumps(result, indent=2))

        if result.get("status") in ["success", "partial"]:
            print(f"\n📊 Summary: {result.get('summary', {})}")
            for data in result.get("data", []):
                if data.get("status") == "success":
                    print(
                        f"   {data['symbol']}: IV={data.get('implied_volatility', 'N/A')}%, Delta={data.get('greeks', {}).get('delta', 'N/A')}"
                    )

    except Exception as e:
        print(f"Error: {e}")


def test_with_custom_underlying():
    """Test 2: Options with Custom Underlying (Futures)"""
    print("\n" + "=" * 60)
    print("Test 2: Options with Custom Underlying (Futures)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/multioptiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbols": [
            {
                "symbol": "NIFTY30DEC2526000CE",
                "exchange": "NFO",
                "underlying_symbol": "NIFTY30DEC25FUT",
                "underlying_exchange": "NFO",
            },
            {
                "symbol": "NIFTY30DEC2526000PE",
                "exchange": "NFO",
                "underlying_symbol": "NIFTY30DEC25FUT",
                "underlying_exchange": "NFO",
            },
        ],
        "interest_rate": 7.0,
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        result = response.json()
        print("Response Body:")
        print(json.dumps(result, indent=2))

        if result.get("status") in ["success", "partial"]:
            print(f"\n📊 Using Futures as Underlying - Summary: {result.get('summary', {})}")

    except Exception as e:
        print(f"Error: {e}")


def test_mixed_options():
    """Test 3: Mixed Options - Different Strikes"""
    print("\n" + "=" * 60)
    print("Test 3: Mixed Options - Different Strikes")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/multioptiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbols": [
            {"symbol": "NIFTY30DEC2524000CE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2525000CE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2526000CE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2524000PE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2525000PE", "exchange": "NFO"},
            {"symbol": "NIFTY30DEC2526000PE", "exchange": "NFO"},
        ],
    }

    print("\nRequest Payload: (6 symbols)")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        result = response.json()

        if result.get("status") in ["success", "partial"]:
            print(f"\n📊 Summary: {result.get('summary', {})}")
            for data in result.get("data", []):
                if data.get("status") == "success":
                    print(
                        f"   {data['symbol']}: Delta={data.get('greeks', {}).get('delta', 'N/A'):.4f}"
                    )
        else:
            print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")


def test_invalid_symbol():
    """Test 4: Error Handling - Invalid Symbol"""
    print("\n" + "=" * 60)
    print("Test 4: Error Handling - Mixed Valid/Invalid Symbols")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/multioptiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbols": [
            {"symbol": "NIFTY30DEC2526000CE", "exchange": "NFO"},
            {"symbol": "INVALID_SYMBOL", "exchange": "NFO"},
        ],
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        result = response.json()
        print("Response Body:")
        print(json.dumps(result, indent=2))

        print("\n✓ Expected: status='partial', summary showing 1 success, 1 failed")

    except Exception as e:
        print(f"Error: {e}")


def test_empty_symbols():
    """Test 5: Error Handling - Empty Symbols Array"""
    print("\n" + "=" * 60)
    print("Test 5: Error Handling - Empty Symbols Array")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/multioptiongreeks"

    payload = {"apikey": API_KEY, "symbols": []}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        result = response.json()
        print("Response Body:")
        print(json.dumps(result, indent=2))

        print("\n✓ Expected: Validation error (min 1 symbol required)")

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OpenAlgo Multi Option Greeks API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print("\n⚠️  Prerequisites:")
    print("  1. Install py_vollib: pip install py_vollib")
    print("  2. OpenAlgo must be running")
    print("  3. Markets should be open for live prices")
    print("  4. Update symbols to current/future expiry dates")
    print("=" * 60)

    # Run tests
    test_multiple_nifty_options()
    test_with_custom_underlying()
    test_mixed_options()
    test_invalid_symbol()
    test_empty_symbols()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
