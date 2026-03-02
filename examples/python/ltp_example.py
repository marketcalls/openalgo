"""
OpenAlgo WebSocket Feed Example
"""

import time

from openalgo import api

# Initialize feed client with explicit parameters
client = api(
    api_key="fb77b2df614f43f607c3cd7543200a3d0b7f8e133701ed40bebeceb901b4d440",  # Replace with your API key
    host="http://127.0.0.1:3300",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765",  # Explicit WebSocket URL (can be different from REST API host)
)

# MCX instruments for testing
instruments_list = [{"exchange": "NSE", "symbol": "TCS", "exchange": "NSE", "symbol": "INFY"}]


def on_data_received(data):
    print("LTP Update:")
    print(data)


# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments_list, on_data_received=on_data_received)

# Poll LTP data a few times
for i in range(100):
    print(f"\nPoll {i + 1}:")
    print(client.get_ltp())
    time.sleep(0.5)

# Cleanup
client.unsubscribe_ltp(instruments_list)
client.disconnect()
