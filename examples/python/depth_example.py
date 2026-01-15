"""
OpenAlgo WebSocket Market Depth Example
"""

from openalgo import api
import time

# Initialize feed client with explicit parameters
client = api(
    api_key="7653f710c940cdf1d757b5a7d808a60f43bc7e9c0239065435861da2869ec0fc",  # Replace with your API key
    host="http://127.0.0.1:5000",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765"  # Explicit WebSocket URL (can be different from REST API host)
)

# MCX instruments for testing
instruments_list = [

    {"exchange": "NSE", "symbol": "TCS"}
]

def on_data_received(data):
    print("Market Depth Update:")
    print(data)

# Connect and subscribe
client.connect()
client.subscribe_depth(instruments_list, on_data_received=on_data_received)

# Poll Market Depth data a few times
for i in range(100):
    print(f"\nPoll {i+1}:")
    print(client.get_depth())
    time.sleep(0.5)

# Cleanup
client.unsubscribe_depth(instruments_list)
client.disconnect()