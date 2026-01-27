"""
Test script for Telegram Alert API

This script demonstrates how to use the /api/v1/telegram/notify endpoint
to send custom alert messages to Telegram users.

Prerequisites:
1. Telegram bot must be running (start from OpenAlgo Telegram settings)
2. User must be linked via /link command in Telegram
3. Replace API_KEY and USERNAME with your actual values

Usage:
    cd D:/openalgo-sandbox-test/openalgo/test
    python test_telegram_alert_api.py
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
USERNAME = "your_username_here"  # Replace with your linked Telegram username


def test_basic_alert():
    """Test 1: Basic Alert Message"""
    print("\n" + "=" * 60)
    print("Test 1: Basic Alert Message")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "Test alert from API - Basic message",
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


def test_priority_alert():
    """Test 2: Alert with Priority"""
    print("\n" + "=" * 60)
    print("Test 2: Alert with Priority (High)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "🚨 URGENT: High priority alert message!",
        "priority": 10,
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


def test_formatted_alert():
    """Test 3: Multi-line Formatted Alert"""
    print("\n" + "=" * 60)
    print("Test 3: Multi-line Formatted Alert")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "📊 Daily Trading Summary\n─────────────────────\n✅ Winning Trades: 5\n❌ Losing Trades: 1\n💰 Net P&L: +₹12,500\n📈 Win Rate: 83%",
        "priority": 5,
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


def test_price_alert():
    """Test 4: Price Alert Notification"""
    print("\n" + "=" * 60)
    print("Test 4: Price Alert Notification")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "🔔 Price Alert\nNIFTY crossed 24000!\nCurrent: 24,015.50\nChange: +1.2%",
        "priority": 8,
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


def test_trade_signal():
    """Test 5: Trade Signal Alert"""
    print("\n" + "=" * 60)
    print("Test 5: Trade Signal Alert")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "📈 BUY Signal Detected\n\nSymbol: BANKNIFTY 48000 CE\nEntry: ₹245.50\nTarget: ₹265.00\nStop Loss: ₹238.00\nRisk-Reward: 1:2.5",
        "priority": 9,
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


def test_risk_alert():
    """Test 6: Risk Management Alert"""
    print("\n" + "=" * 60)
    print("Test 6: Risk Management Alert")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        "message": "⚠️ Risk Alert\n\nDaily loss limit approaching\nCurrent Loss: -₹22,500\nLimit: -₹25,000\n\nReduce position sizes!",
        "priority": 10,
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
    """Test 7: Validation Error - Missing Message"""
    print("\n" + "=" * 60)
    print("Test 7: Validation Error (Missing Message)")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": USERNAME,
        # Missing message - should cause validation error
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


def test_invalid_user():
    """Test 8: Invalid Username"""
    print("\n" + "=" * 60)
    print("Test 8: Invalid Username")
    print("=" * 60)

    url = f"{BASE_URL}/api/v1/telegram/notify"

    payload = {
        "apikey": API_KEY,
        "username": "nonexistent_user_12345",  # Invalid username
        "message": "This should fail - user doesn't exist",
        "priority": 5,
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
    print("OpenAlgo Telegram Alert API Test Suite")
    print("=" * 60)
    print(f"\nBase URL: {BASE_URL}")
    print(f"API Key: {API_KEY[:10]}..." if len(API_KEY) > 10 else f"API Key: {API_KEY}")
    print(f"Username: {USERNAME}")
    print("\nNote: Replace API_KEY and USERNAME in this script with your actual values")
    print("\nPrerequisites:")
    print("  1. Telegram bot must be running")
    print("  2. User must be linked via /link command")
    print("  3. Valid API key required")
    print("=" * 60)

    # Run tests
    test_basic_alert()
    test_priority_alert()
    test_formatted_alert()
    test_price_alert()
    test_trade_signal()
    test_risk_alert()
    test_validation_error()
    test_invalid_user()

    print("\n" + "=" * 60)
    print("All tests completed!")
    print("=" * 60)
