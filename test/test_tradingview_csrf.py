#!/usr/bin/env python3
"""
Test script for TradingView CSRF protection

This script tests that the TradingView endpoint properly requires CSRF token
for POST requests.
"""

import requests
import sys
import json

def test_tradingview_csrf(base_url="http://127.0.0.1:5000"):
    """Test TradingView CSRF protection"""
    print(f"\n{'='*60}")
    print(f"Testing TradingView CSRF Protection")
    print(f"Server: {base_url}")
    print(f"{'='*60}\n")
    
    session = requests.Session()
    results = []
    
    # Test 1: GET request to TradingView page should work
    print("Test 1: GET request to TradingView page")
    try:
        response = session.get(f"{base_url}/tradingview/")
        if response.status_code == 200:
            print("✓ PASS: TradingView page loads successfully")
            # Check if CSRF meta tag is present
            if 'name="csrf-token"' in response.text:
                print("✓ PASS: CSRF meta tag found in page")
                results.append(True)
            else:
                print("✗ FAIL: CSRF meta tag not found in page")
                results.append(False)
        else:
            print(f"✗ FAIL: Page returned {response.status_code}")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error loading page: {e}")
        results.append(False)
    
    # Test 2: POST without CSRF token should fail
    print("\nTest 2: POST request without CSRF token")
    try:
        data = {
            "symbol": "ETERNAL",
            "exchange": "NSE",
            "product": "MIS"
        }
        response = session.post(
            f"{base_url}/tradingview/",
            json=data,
            headers={"Content-Type": "application/json"}
        )
        if response.status_code in [400, 403]:
            print(f"✓ PASS: POST without CSRF token rejected with {response.status_code}")
            results.append(True)
        else:
            print(f"✗ FAIL: POST without CSRF returned {response.status_code}")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error making POST request: {e}")
        results.append(False)
    
    # Test 3: Check JavaScript includes CSRF token
    print("\nTest 3: Check if JavaScript properly sends CSRF token")
    try:
        response = session.get(f"{base_url}/static/js/tradingview.js")
        if response.status_code == 200:
            js_content = response.text
            # Check for CSRF token in headers
            if "X-CSRFToken" in js_content and "getCSRFToken()" in js_content:
                print("✓ PASS: JavaScript includes CSRF token in requests")
                results.append(True)
            else:
                print("✗ FAIL: JavaScript missing CSRF token implementation")
                results.append(False)
        else:
            print(f"✗ FAIL: Could not load JavaScript file")
            results.append(False)
    except Exception as e:
        print(f"✗ FAIL: Error checking JavaScript: {e}")
        results.append(False)
    
    # Summary
    print(f"\n{'='*60}")
    passed = sum(results)
    total = len(results)
    print(f"Test Summary: {passed}/{total} tests passed")
    
    if passed == total:
        print("✅ All tests passed! TradingView is protected with CSRF.")
    else:
        print("❌ Some tests failed. Please review the implementation.")
    
    print(f"{'='*60}\n")
    
    return passed == total

if __name__ == "__main__":
    base_url = "http://127.0.0.1:5000"
    if len(sys.argv) > 1:
        base_url = sys.argv[1]
    
    success = test_tradingview_csrf(base_url)
    sys.exit(0 if success else 1)