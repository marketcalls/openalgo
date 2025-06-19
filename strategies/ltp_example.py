"""
OpenAlgo WebSocket Feed Example
"""

from openalgo import api
import time

# Initialize feed client with explicit parameters
client = api(
    api_key="82153b8f2dec355488bf99fb2333ae30794c063643f72c38bbd6d003383c246e",  # Updated API key
    host="http://127.0.0.1:5000",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765"  # Explicit WebSocket URL (can be different from REST API host)
)

# MCX instruments for testing
instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "INFY"},
    {"exchange": "NSE", "symbol": "TCS"}
]

def on_data_received(data):
    print("[DEBUG] on_data_received called!")
    print("[DEBUG] Raw data received in on_data_received callback:")
    print(data)
    print(f"[DEBUG] Type of data: {type(data)}")
    if isinstance(data, dict):
        for k, v in data.items():
            print(f"  {k}: {v}")
    else:
        print("[DEBUG] Data is not a dict!")

# Connect and subscribe
client.connect()
client.subscribe_ltp(instruments_list, on_data_received=on_data_received)

# Print client internal state if possible
print("[DEBUG] Client attributes:")
for attr in dir(client):
    if not attr.startswith("__"):
        try:
            print(f"  {attr}: {getattr(client, attr)}")
        except Exception as e:
            print(f"  {attr}: <error: {e}>")

# Print subscriptions if accessible
if hasattr(client, 'subscriptions'):
    print("[DEBUG] Client subscriptions:")
    print(client.subscriptions)

# Optionally, monkey-patch the client's internal message handler for deeper debug (if available)
if hasattr(client, '_ws') and hasattr(client._ws, 'on_message'):
    orig_on_message = client._ws.on_message
    def debug_on_message(msg):
        print(f"[DEBUG] Raw WebSocket message: {msg}")
        return orig_on_message(msg)
    client._ws.on_message = debug_on_message

# Poll LTP data a few times
for i in range(5):
    print(f"\nPoll {i+1}:")
    print("[DEBUG] client.get_ltp() output:")
    ltp = client.get_ltp()
    print(ltp)
    print(f"[DEBUG] Type of ltp: {type(ltp)}")
    if isinstance(ltp, dict):
        for k, v in ltp.items():
            print(f"  {k}: {v}")
    else:
        print("[DEBUG] LTP is not a dict!")
    time.sleep(0.5)

# Cleanup
client.unsubscribe_ltp(instruments_list)
client.disconnect()
