"""
OpenAlgo WebSocket Feed Example
"""

from openalgo import api
import time

# Initialize feed client with explicit parameters
client = api(
    api_key="918d504f250e6f7d6b533b245a46009d3f3b8cad8e6314c8b45ae8a35b972d8a",  # Replace with your API key
    host="http://127.0.0.1:5000",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765"  # Explicit WebSocket URL (can be different from REST API host)
)

# MCX instruments for testing
instruments_list = [
    {"exchange": "MCX", "symbol": "GOLDPETAL30MAY25FUT"},
    {"exchange": "MCX", "symbol": "GOLD05JUN25FUT"}
]

def on_data_received(data):
    print("LTP Update:")
    print(data)

# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments_list, on_data_received=on_data_received)

# Poll LTP data a few times
for i in range(100):
    print(f"\nPoll {i+1}:")
    print(client.get_ltp())
    time.sleep(1)

# Cleanup
client.unsubscribe_ltp(instruments_list)
client.disconnect()
