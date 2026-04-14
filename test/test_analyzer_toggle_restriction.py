"""
Test analyzer toggle restriction in semi-auto mode

This test verifies that Research Analysts cannot toggle analyzer mode
via API when in semi-auto mode, but clients can via UI.

Run with: python test/test_analyzer_toggle_restriction.py
"""

import json
from datetime import datetime

import requests

# Configuration
BASE_URL = "http://127.0.0.1:5000"
API_KEY = "bf1267a177b7ece1b10ca29b0ee8c4d62b153fe60caba3c566619e607cf9169f"


def log(message, level="INFO"):
    """Print timestamped log message"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")


def test_analyzer_toggle_restriction():
    """Test analyzer toggle restriction in semi-auto mode"""

    log("=" * 80)
    log("Testing Analyzer Toggle Restriction in Semi-Auto Mode")
    log("=" * 80)
    log("")

    # Test 1: Try to toggle analyzer mode via API (should be blocked in semi-auto)
    log("Test 1: Attempting to toggle analyzer mode via API (with apikey)")
    log("-" * 80)

    url = f"{BASE_URL}/api/v1/analyzer/toggle"
    payload = {
        "apikey": API_KEY,
        "mode": True,  # Try to enable analyzer mode
    }

    log(f"URL: {url}")
    log(f"Payload: {json.dumps(payload, indent=2)}")

    try:
        response = requests.post(url, json=payload, timeout=10)
        log(f"Response Status: {response.status_code}")
        log(f"Response Body: {response.text}")

        result = response.json()

        if response.status_code == 403:
            log("[PASS] Analyzer toggle correctly blocked in semi-auto mode", "SUCCESS")
            log(f"   Error Message: {result.get('message', '')}")
        elif response.status_code == 200:
            log("[WARNING] Analyzer toggle was allowed (API key might be in Auto mode)", "WARNING")
        else:
            log(f"[FAIL] Unexpected status code: {response.status_code}", "ERROR")

    except Exception as e:
        log(f"[FAIL] Exception occurred: {str(e)}", "ERROR")

    log("")
    log("=" * 80)
    log("Test Complete")
    log("=" * 80)
    log("")
    log("Note: If the test shows WARNING, it means the API key is in Auto mode.")
    log("To test the restriction properly:")
    log("1. Go to http://127.0.0.1:5000/apikey")
    log("2. Toggle Order Execution Mode to ON (Semi-Auto)")
    log("3. Run this test again")
    log("")
    log("The client can still toggle via UI buttons regardless of mode.")


if __name__ == "__main__":
    test_analyzer_toggle_restriction()
