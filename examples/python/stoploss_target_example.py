"""
CRUDEOIL Buy Order with Websocket-Based SL/Target Monitoring
Stop Loss: 10 points | Target: 10 points
"""

import time

from openalgo import api

# Configuration
API_KEY = "your-api-key-here"
HOST = "http://127.0.0.1:5000"
WS_URL = "ws://127.0.0.1:8765"

SYMBOL = "CRUDEOIL16JAN26FUT"
EXCHANGE = "MCX"
QUANTITY = 100
PRODUCT = "NRML"
STRATEGY = "SL_Target_Bot"

STOP_LOSS_POINTS = 3
TARGET_POINTS = 3

# Global variables
entry_price = 0
stop_loss = 0
target = 0
position_active = False
client = None


def place_entry_order():
    """Place market buy order"""
    response = client.placeorder(
        strategy=STRATEGY,
        symbol=SYMBOL,
        action="BUY",
        exchange=EXCHANGE,
        price_type="MARKET",
        product=PRODUCT,
        quantity=QUANTITY,
    )
    print(f"Entry Order Response: {response}")
    return response


def get_fill_price(order_id):
    """Get average fill price from order status"""
    # Wait a moment for order to fill
    time.sleep(1)

    response = client.orderstatus(order_id=order_id, strategy=STRATEGY)
    print(f"Order Status: {response}")

    # average_price is nested inside 'data'
    data = response.get("data", {})
    avg_price = float(data.get("average_price", 0))
    return avg_price


def exit_position(reason):
    """Exit the position"""
    global position_active
    print(f"\n>>> EXIT TRIGGERED: {reason}")
    response = client.placeorder(
        strategy=STRATEGY,
        symbol=SYMBOL,
        action="SELL",
        exchange=EXCHANGE,
        price_type="MARKET",
        product=PRODUCT,
        quantity=QUANTITY,
    )
    print(f"Exit Order Response: {response}")
    position_active = False
    return response


def on_ltp_update(data):
    """Callback for LTP updates - check SL/Target"""
    global position_active, stop_loss, target, entry_price

    if not position_active:
        return

    try:
        ltp = float(data["data"]["ltp"])

        print(
            f"LTP: {ltp:.2f} | Entry: {entry_price:.2f} | SL: {stop_loss:.2f} | Target: {target:.2f}",
            end="\r",
        )

        # Check stop loss
        if ltp <= stop_loss:
            exit_position(f"STOP LOSS HIT at {ltp:.2f}")

        # Check target
        elif ltp >= target:
            exit_position(f"TARGET HIT at {ltp:.2f}")

    except Exception as e:
        print(f"Error processing update: {e}")


def main():
    global client, entry_price, stop_loss, target, position_active

    # Initialize client with WebSocket
    client = api(api_key=API_KEY, host=HOST, ws_url=WS_URL, verbose=True)

    print("=" * 50)
    print("CRUDEOIL BUY - SL/Target Monitor")
    print(f"Stop Loss: {STOP_LOSS_POINTS} pts | Target: {TARGET_POINTS} pts")
    print("=" * 50)

    # Step 1: Place entry order
    print("\nPlacing BUY order...")
    entry_response = place_entry_order()

    if entry_response.get("status") != "success":
        print(f"Order failed: {entry_response}")
        return

    order_id = entry_response.get("orderid")
    print(f"Order ID: {order_id}")

    # Step 2: Get fill price from order status
    print("\nFetching fill price from order status...")
    entry_price = get_fill_price(order_id)

    if entry_price <= 0:
        print("Failed to get fill price. Exiting.")
        return

    # Calculate SL and Target
    stop_loss = entry_price - STOP_LOSS_POINTS
    target = entry_price + TARGET_POINTS

    print(f"\nEntry Price: {entry_price:.2f}")
    print(f"Stop Loss: {stop_loss:.2f}")
    print(f"Target: {target:.2f}")

    position_active = True

    # Step 3: Connect to WebSocket for monitoring
    print("\nConnecting to WebSocket...")
    client.connect()

    instruments = [{"exchange": EXCHANGE, "symbol": SYMBOL}]
    client.subscribe_ltp(instruments, on_data_received=on_ltp_update)

    print("Monitoring for SL/Target... Press Ctrl+C to exit\n")

    # Keep running until position exits
    try:
        while position_active:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\n\nManual exit requested...")

    # Cleanup
    print("Cleaning up...")
    client.unsubscribe_ltp(instruments)
    client.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()
