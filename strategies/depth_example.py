"""
OpenAlgo WebSocket Market Depth Example
"""

from openalgo import api
import time

# Initialize feed client with explicit parameters
client = api(
    api_key="8009e08498f085ff1a3e7da718c5f4b585eaf9c2b7ce0c72740ab2b5d283d36c",  # Replace with your API key
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