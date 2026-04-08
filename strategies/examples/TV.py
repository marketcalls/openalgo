"""
TV.py - TradingView Webhook Strategy for OpenAlgo
Upload this to http://localhost:5002/python to get a webhook URL.
Use that webhook URL in TradingView alerts to trigger trades.

Webhook URL format: http://your-server/python/webhook/<webhook_id>

=== TradingView Alert JSON Examples ===

1. Equity Order (placeorder):
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 1,
    "pricetype": "MARKET",
    "product": "MIS"
}

2. Smart Order with position sizing (placesmartorder):
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "{{strategy.order.action}}",
    "quantity": "{{strategy.order.contracts}}",
    "position_size": "{{strategy.position_size}}",
    "pricetype": "MARKET",
    "product": "MIS"
}

3. Options Order (optionsorder):
{
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS"
}

The webhook auto-detects the order type:
- Has "underlying" + "offset" + "option_type" -> optionsorder
- Has "position_size" -> placesmartorder
- Otherwise -> placeorder
"""

import time
import os

API_KEY = os.getenv("OPENALGO_APIKEY", "")
HOST = os.getenv("OPENALGO_HOST", "http://127.0.0.1:5000")

print("=" * 50)
print("TV.py - TradingView Webhook Strategy")
print("=" * 50)
print()
print("This strategy acts as a placeholder.")
print("Trades are triggered via the webhook URL,")
print("not from this script.")
print()
print("Keep this strategy RUNNING so the webhook stays active.")
print("Configure your TradingView alerts to POST JSON to:")
print("  http://your-server/python/webhook/<your-webhook-id>")
print()
print("Check the Python Strategy page for your webhook URL.")
print("=" * 50)

while True:
    time.sleep(60)
