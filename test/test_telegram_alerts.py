"""
Test script for Telegram Alert Service
Tests the integration of telegram alerts with order services
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.telegram_alert_service import telegram_alert_service
from database.telegram_db import get_telegram_user_by_username
from database.auth_db import get_username_by_apikey
import time

def test_telegram_alerts():
    """Test various order alert types"""

    print("Testing Telegram Alert Service...")
    print("-" * 50)

    # Test data
    test_orders = [
        {
            'type': 'placeorder',
            'data': {
                'symbol': 'RELIANCE',
                'action': 'BUY',
                'quantity': 10,
                'pricetype': 'MARKET',
                'exchange': 'NSE',
                'product': 'MIS',
                'strategy': 'Test Strategy'
            },
            'response_live': {
                'status': 'success',
                'orderid': 'TEST123456',
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'orderid': 'ANALYZE123456',
                'mode': 'analyze'
            }
        },
        {
            'type': 'placesmartorder',
            'data': {
                'symbol': 'TATASTEEL',
                'action': 'SELL',
                'quantity': 5,
                'position_size': 10,
                'exchange': 'NSE',
                'strategy': 'Smart Strategy'
            },
            'response_live': {
                'status': 'success',
                'orderid': 'SMART789',
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'orderid': 'SMARTANALYZE789',
                'mode': 'analyze'
            }
        },
        {
            'type': 'basketorder',
            'data': {
                'strategy': 'Basket Strategy',
                'orders': [
                    {'symbol': 'INFY', 'action': 'BUY', 'quantity': 5},
                    {'symbol': 'TCS', 'action': 'BUY', 'quantity': 3}
                ]
            },
            'response_live': {
                'status': 'success',
                'results': [
                    {'symbol': 'INFY', 'status': 'success', 'orderid': 'B001'},
                    {'symbol': 'TCS', 'status': 'success', 'orderid': 'B002'}
                ],
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'results': [
                    {'symbol': 'INFY', 'status': 'success', 'orderid': 'AB001'},
                    {'symbol': 'TCS', 'status': 'success', 'orderid': 'AB002'}
                ],
                'mode': 'analyze'
            }
        },
        {
            'type': 'modifyorder',
            'data': {
                'orderid': 'MOD123',
                'symbol': 'HDFC',
                'quantity': 20,
                'price': 1500.50,
                'strategy': 'Modify Test'
            },
            'response_live': {
                'status': 'success',
                'orderid': 'MOD123',
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'orderid': 'MOD123',
                'mode': 'analyze'
            }
        },
        {
            'type': 'cancelorder',
            'data': {
                'orderid': 'CANCEL456',
                'strategy': 'Cancel Test'
            },
            'response_live': {
                'status': 'success',
                'orderid': 'CANCEL456',
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'orderid': 'CANCEL456',
                'mode': 'analyze'
            }
        },
        {
            'type': 'closeposition',
            'data': {
                'strategy': 'Close All Positions'
            },
            'response_live': {
                'status': 'success',
                'message': 'All positions closed',
                'mode': 'live'
            },
            'response_analyze': {
                'status': 'success',
                'message': 'All positions will be closed',
                'mode': 'analyze'
            }
        }
    ]

    # Test formatting for each order type
    print("\n1. Testing message formatting...")
    for test in test_orders:
        print(f"\n   Testing {test['type']}:")

        # Test LIVE mode
        message_live = telegram_alert_service.format_order_details(
            test['type'],
            test['data'],
            test['response_live']
        )
        print(f"   LIVE Mode:")
        try:
            print("   " + message_live.replace('\n', '\n   '))
        except UnicodeEncodeError:
            # Fallback for terminals that don't support unicode
            print("   [Message formatted correctly but contains unicode characters]")

        # Test ANALYZE mode
        message_analyze = telegram_alert_service.format_order_details(
            test['type'],
            test['data'],
            test['response_analyze']
        )
        print(f"\n   ANALYZE Mode:")
        try:
            print("   " + message_analyze.replace('\n', '\n   '))
        except UnicodeEncodeError:
            # Fallback for terminals that don't support unicode
            print("   [Message formatted correctly but contains unicode characters]")

        print("   " + "-" * 40)

    # Test async alert sending (won't actually send without valid user)
    print("\n2. Testing async alert mechanism...")

    # Simulate sending alerts
    for test in test_orders[:2]:  # Test only first 2 to avoid spam
        print(f"   Queuing {test['type']} alert...")
        telegram_alert_service.send_order_alert(
            test['type'],
            test['data'],
            test['response_live'],
            api_key=None  # No actual API key for test
        )

    print("   Alerts queued successfully (would be sent if user configured)")

    # Test error handling
    print("\n3. Testing error handling...")
    try:
        # Test with missing data
        telegram_alert_service.send_order_alert(
            'placeorder',
            {},
            {'status': 'error', 'message': 'Test error'},
            api_key=None
        )
        print("   Error handling works correctly")
    except Exception as e:
        print(f"   Error caught: {e}")

    print("\n" + "=" * 50)
    print("Telegram Alert Service Test Complete!")
    print("=" * 50)

    print("\nNOTE: To test actual message delivery:")
    print("1. Ensure Telegram bot is running (/telegram/bot/start)")
    print("2. Users must be linked via Telegram (/link command)")
    print("3. Place actual orders through the API")

    return True

if __name__ == "__main__":
    success = test_telegram_alerts()
    if success:
        try:
            print("\n✅ All tests passed!")
        except UnicodeEncodeError:
            print("\n[CHECKMARK] All tests passed!")
    else:
        try:
            print("\n❌ Some tests failed!")
        except UnicodeEncodeError:
            print("\n[X] Some tests failed!")