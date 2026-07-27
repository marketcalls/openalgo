"""
Test script for Option Greeks API

This script demonstrates how to use the /api/v1/optiongreeks endpoint
to calculate option Greeks (Delta, Gamma, Theta, Vega, Rho) and Implied Volatility
for options across all supported exchanges.

Prerequisites:
1. Install mibian library: pip install mibian
2. OpenAlgo must be running
3. Markets should be open for live prices

Usage:
    cd D:/openalgo-sandbox-test/openalgo/test
    python test_option_greeks_api.py
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


def test_nifty_call_greeks():
    """Test 1: NIFTY Call Option Greeks (NFO)"""
    print("\n" + "=" * 60)
    print("Test 1: NIFTY Call Option Greeks (NFO)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {"apikey": API_KEY, "symbol": "NIFTY28NOV2424000CE", "exchange": "NFO"}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

        if result.get("status") == "success":
            print("\n📊 Greeks Summary:")
            print(f"   Delta: {result['greeks']['delta']}")
            print(f"   Gamma: {result['greeks']['gamma']}")
            print(f"   Theta: {result['greeks']['theta']}")
            print(f"   Vega: {result['greeks']['vega']}")
            print(f"   IV: {result['implied_volatility']}%")

    except Exception as e:
        print(f"Error: {e}")


def test_banknifty_put_greeks():
    """Test 2: BANKNIFTY Put Option Greeks (NFO)"""
    print("\n" + "=" * 60)
    print("Test 2: BANKNIFTY Put Option Greeks (NFO)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {"apikey": API_KEY, "symbol": "BANKNIFTY28NOV2448000PE", "exchange": "NFO"}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

        if result.get("status") == "success":
            print("\n📊 Greeks Summary:")
            print(f"   Delta: {result['greeks']['delta']} (Put delta is negative)")
            print(f"   Theta: {result['greeks']['theta']} (Time decay)")
            print(f"   Days to Expiry: {result['days_to_expiry']}")

    except Exception as e:
        print(f"Error: {e}")


def test_custom_interest_rate():
    """Test 3: Option Greeks with Custom Interest Rate"""
    print("\n" + "=" * 60)
    print("Test 3: Option Greeks with Custom Interest Rate")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbol": "NIFTY28NOV2424500CE",
        "exchange": "NFO",
        "interest_rate": 7.0,  # Custom interest rate
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

        if result.get("status") == "success":
            print(f"\n📊 Using Interest Rate: {result['interest_rate']}%")
            print(f"   Rho: {result['greeks']['rho']} (Interest rate sensitivity)")

    except Exception as e:
        print(f"Error: {e}")


def test_sensex_option_greeks():
    """Test 4: SENSEX Option Greeks (BFO)"""
    print("\n" + "=" * 60)
    print("Test 4: SENSEX Option Greeks (BFO)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {"apikey": API_KEY, "symbol": "SENSEX28NOV2475000CE", "exchange": "BFO"}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")


def test_currency_option_greeks():
    """Test 5: Currency Option Greeks (CDS)"""
    print("\n" + "=" * 60)
    print("Test 5: Currency Option Greeks (CDS)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbol": "USDINR28NOV2483.50CE",  # Note: Decimal strike
        "exchange": "CDS",
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

        if result.get("status") == "success":
            print("\n💱 Currency Option:")
            print(f"   Spot: {result['spot_price']}")
            print(f"   Strike: {result['strike']}")

    except Exception as e:
        print(f"Error: {e}")


def test_commodity_option_greeks():
    """Test 6: Commodity Option Greeks (MCX)"""
    print("\n" + "=" * 60)
    print("Test 6: Commodity Option Greeks (MCX)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {"apikey": API_KEY, "symbol": "GOLD28DEC2472000CE", "exchange": "MCX"}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")


def test_mcx_custom_expiry_time():
    """Test 7: MCX Option with Custom Expiry Time"""
    print("\n" + "=" * 60)
    print("Test 7: MCX Option with Custom Expiry Time (GOLD at 17:00)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbol": "GOLD28DEC2472000CE",
        "exchange": "MCX",
        "expiry_time": "17:00",  # Gold expires at 5:00 PM, not default 23:30
    }

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))
    print("\n⚠️  Note: Gold expires at 17:00 (5 PM), not the default 23:30")
    print("   Using custom expiry_time for accurate Greeks calculation")

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

        if result.get("status") == "success":
            print("\n📊 MCX Commodity Greeks:")
            print(f"   Days to Expiry: {result['days_to_expiry']}")
            print(f"   Theta: {result['greeks']['theta']} (Time decay)")
            print(f"   Delta: {result['greeks']['delta']}")

    except Exception as e:
        print(f"Error: {e}")


def test_equity_option_greeks():
    """Test 8: Equity Option Greeks (NFO)"""
    print("\n" + "=" * 60)
    print("Test 8: Equity Option Greeks - RELIANCE (NFO)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {"apikey": API_KEY, "symbol": "RELIANCE28NOV241500CE", "exchange": "NFO"}

    print("\nRequest Payload:")
    print(json.dumps(payload, indent=2))

    try:
        response = requests.post(url, json=payload)
        print(f"\nResponse Status: {response.status_code}")
        print("Response Body:")
        result = response.json()
        print(json.dumps(result, indent=2))

    except Exception as e:
        print(f"Error: {e}")


def test_invalid_symbol_format():
    """Test 9: Error - Invalid Symbol Format"""
    print("\n" + "=" * 60)
    print("Test 9: Error - Invalid Symbol Format")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbol": "NIFTY24000CE",  # Invalid - missing date
        "exchange": "NFO",
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


def test_expired_option():
    """Test 10: Error - Expired Option"""
    print("\n" + "=" * 60)
    print("Test 10: Error - Expired Option")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    payload = {
        "apikey": API_KEY,
        "symbol": "NIFTY28OCT2424000CE",  # Expired (past date)
        "exchange": "NFO",
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


def test_compare_call_put_greeks():
    """Test 11: Compare Call vs Put Greeks at Same Strike"""
    print("\n" + "=" * 60)
    print("Test 11: Compare Call vs Put Greeks (Same Strike)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/optiongreeks"

    # Test Call
    call_payload = {"apikey": API_KEY, "symbol": "NIFTY28NOV2424000CE", "exchange": "NFO"}

    # Test Put
    put_payload = {"apikey": API_KEY, "symbol": "NIFTY28NOV2424000PE", "exchange": "NFO"}

    try:
        print("\n📞 CALL Option:")
        call_response = requests.post(url, json=call_payload)
        call_result = call_response.json()

        if call_result.get("status") == "success":
            print(f"   Delta: {call_result['greeks']['delta']}")
            print(f"   Gamma: {call_result['greeks']['gamma']}")
            print(f"   IV: {call_result['implied_volatility']}%")

        print("\n📉 PUT Option:")
        put_response = requests.post(url, json=put_payload)
        put_result = put_response.json()

        if put_result.get("status") == "success":
            print(f"   Delta: {put_result['greeks']['delta']}")
            print(f"   Gamma: {put_result['greeks']['gamma']}")
            print(f"   IV: {put_result['implied_volatility']}%")

        if call_result.get("status") == "success" and put_result.get("status") == "success":
            print("\n✓ Put-Call Parity Check:")
            print(
                f"   Gamma should be equal: {call_result['greeks']['gamma']:.6f} vs {put_result['greeks']['gamma']:.6f}"
            )
            print(
                f"   IV should be similar: {call_result['implied_volatility']:.2f}% vs {put_result['implied_volatility']:.2f}%"
            )

    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("OpenAlgo Option Greeks API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print("\n⚠️  Prerequisites:")
    print("  1. Install mibian: pip install mibian")
    print("  2. OpenAlgo must be running")
    print("  3. Markets should be open for live prices")
    print("  4. Update symbols to current/future expiry dates")
    print("=" * 60)

    # Check if mibian is installed
    try:
        import mibian

        print("\n✓ mibian library is installed")
    except ImportError:
        print("\n✗ mibian library NOT installed!")
        print("  Install with: pip install mibian")
        print("  Or with uv: uv pip install mibian")
        print("\nExiting...")
        sys.exit(1)

    # Run tests
    test_nifty_call_greeks()
    test_banknifty_put_greeks()
    test_custom_interest_rate()
    test_sensex_option_greeks()
    test_currency_option_greeks()
    test_commodity_option_greeks()
    test_mcx_custom_expiry_time()
    test_equity_option_greeks()
    test_invalid_symbol_format()
    test_expired_option()
    test_compare_call_put_greeks()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
