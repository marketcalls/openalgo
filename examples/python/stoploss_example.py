"""
🔁 OpenAlgo Python Bot is running.
"""

from openalgo import api
import time
from datetime import datetime

# Setup OpenAlgo client
client = api(
    api_key="your-openalgo-api-key",  # Replace with your API key
    host="http://127.0.0.1:5000",  # Replace with your API host
    ws_url="ws://127.0.0.1:8765"  # Explicit WebSocket URL (can be different from REST API host)
)

# Strategy details
STRATEGY_NAME = "LTP_Stoploss_Example"
SYMBOL = "GOLDPETAL30JUN25FUT"
EXCHANGE = "MCX"
QUANTITY = 1
PRODUCT = "MIS"
ACTION = "BUY"
PRICE_TYPE = "MARKET"
STOPLOSS_BUFFER = 5.0

order_id = None
entry_price = None
stoploss_price = None
ltp_hit = False

# Step 1: Place a buy order
def place_entry_order():
    global order_id
    print(f"Placing {ACTION} order for {SYMBOL}...")
    response = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        action=ACTION,
        price_type=PRICE_TYPE,
        product=PRODUCT,
        quantity=QUANTITY
    )
    print("Place Order Response:", response)
    if response.get("status") == "success":
        order_id = response.get("orderid")
        return True
    return False

# Step 2: Get order status and price
def wait_for_execution():
    global entry_price, stoploss_price
    print(f"Waiting for order execution: {order_id}")
    for _ in range(20):
        status_resp = client.orderstatus(order_id=order_id, strategy=STRATEGY_NAME)
        data = status_resp.get("data", {})
        order_status = data.get("order_status", "").lower()

        if order_status == "complete":
            entry_price = float(data["price"])
            stoploss_price = round(entry_price - STOPLOSS_BUFFER, 1)
            print("✅ Order completed!")
            print(f"🔹 Entry Price : {entry_price}")
            print(f"🔸 Stoploss    : {stoploss_price}")
            return True
        elif order_status == "rejected":
            print("❌ Order was rejected. Exiting.")
            exit(1)
        time.sleep(1)

    print("❌ Order not completed in time. Exiting.")
    exit(1)

# Step 3: LTP Callback
def on_data_received(data):
    global ltp_hit
    if data.get("type") == "market_data" and data.get("symbol") == SYMBOL:
        ltp = float(data["data"]["ltp"])
        timestamp = data["data"]["timestamp"]
        print(f"LTP {EXCHANGE}:{SYMBOL}: {ltp} | Time: {timestamp}")
        if not ltp_hit and ltp <= stoploss_price:
            ltp_hit = True
            print(f"🛑 Stoploss hit at LTP {ltp}. Sending exit order...")
            send_exit_order()

# Step 4: Exit order logic
def send_exit_order():
    response = client.placeorder(
        strategy=STRATEGY_NAME,
        symbol=SYMBOL,
        exchange=EXCHANGE,
        action="SELL",
        price_type="MARKET",
        product=PRODUCT,
        quantity=QUANTITY
    )
    print("Exit Order Response:", response)

# === Main Execution ===
if __name__ == "__main__":
    print("🔁 OpenAlgo Python Bot is running.")

    if place_entry_order() and wait_for_execution():
        try:
            client.connect()
            client.subscribe_ltp([{"exchange": EXCHANGE, "symbol": SYMBOL}], on_data_received)

            print("📡 Monitoring LTP for stoploss...")
            while not ltp_hit:
                time.sleep(1)

        except KeyboardInterrupt:
            print("🛑 CTRL+C received. Shutting down gracefully...")

        finally:
            client.unsubscribe_ltp([{"exchange": EXCHANGE, "symbol": SYMBOL}])
            client.disconnect()
            print("🔌 Disconnected from WebSocket.")
