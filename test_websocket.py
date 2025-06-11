import asyncio
import json
import os
import sys
import time
import websockets

# Configuration
WS_URL = "ws://localhost:8765"  # Update if your server is on a different host/port
API_KEY = "598279d805ee05b5988b22a363c64061434d7230228aacc7ced25cbb9a0a410a"  # Your OpenAlgo API key

# Test symbols
RELIANCE_NSE = {"exchange": "NSE", "symbol": "RELIANCE"}
IDEA_NSE = {"exchange": "NSE", "symbol": "IDEA"}
NHPC_NSE = {"exchange": "NSE", "symbol": "NHPC"}
NATURALGAS_MCX = {"exchange": "MCX", "symbol": "NATURALGAS23JUN25325CE"}

# OpenAlgo common subscription modes
MODE_LTP = 1    # Last Traded Price (maps to touchline)
MODE_QUOTE = 2  # Quote (maps to touchline in Flattrade)
MODE_FULL = 3   # Full market depth (maps to depth in Flattrade)
MODE_ORDER_UPDATES = 4  # Order updates subscription

async def connect_and_authenticate(url, api_key):
    """Connect to the WebSocket server and authenticate"""
    try:
        print(f"Attempting to connect to WebSocket server at {url}...")
        
        # Increase connection timeout from 10 to 15 seconds
        try:
            websocket = await asyncio.wait_for(
                websockets.connect(url, ping_interval=30, ping_timeout=10, close_timeout=5),
                timeout=15.0
            )
            print("✓ WebSocket connection established")
        except asyncio.TimeoutError:
            print("✗ Connection timeout: The server did not respond in time")
            return None
        except Exception as conn_error:
            print(f"✗ Connection failed: {str(conn_error)}")
            return None
        
        # Authenticate with API key
        auth_message = {
            "action": "authenticate",
            "api_key": api_key,
            "timestamp": int(time.time())
        }
        
        print("Sending authentication request...")
        print(f"Auth message: {json.dumps(auth_message, indent=2)}")
        
        try:
            await websocket.send(json.dumps(auth_message))
            print("✓ Authentication request sent")
            
            # Increase authentication response timeout from 15 to 30 seconds
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=30.0)
                print("✓ Received authentication response")
                print(f"Raw response: {response}")
                
                try:
                    auth_response = json.loads(response)
                    print(f"Parsed response: {json.dumps(auth_response, indent=2)}")
                    
                    if auth_response.get("status") == "success":
                        print("✓ Authentication successful")
                        return websocket
                    else:
                        error_msg = auth_response.get("message", "Unknown error")
                        print(f"✗ Authentication failed: {error_msg}")
                        await websocket.close()
                        return None
                        
                except json.JSONDecodeError as je:
                    print(f"✗ Failed to parse authentication response: {je}")
                    print(f"Raw response: {response}")
                    await websocket.close()
                    return None
                    
            except asyncio.TimeoutError:
                print("✗ Authentication timeout: No response from server")
                await websocket.close()
                return None
                
        except Exception as auth_error:
            print(f"✗ Error during authentication: {str(auth_error)}")
            await websocket.close()
            return None
            
    except Exception as e:
        print(f"✗ Unexpected error during connection: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

async def subscribe_market_data(websocket, symbol_info, mode):
    """Subscribe to market data for a specific symbol"""
    if not websocket:
        print("Error: WebSocket connection is not established")
        return False
        
    try:
        # Build a subscription message for market data
        sub_message = {
            "action": "subscribe",
            "symbol": symbol_info["symbol"],
            "exchange": symbol_info["exchange"],
            "mode": mode,
            "depth": 5
        }
        print(f"Sending subscription for {symbol_info['symbol']} (mode {mode}): {json.dumps(sub_message, indent=2)}")
        
        await websocket.send(json.dumps(sub_message))
        response = await websocket.recv()
        subscribe_response = json.loads(response)
        
        print(f"Subscription response for {symbol_info['symbol']} mode {mode}: {subscribe_response}")
        
        return True
    except Exception as e:
        print(f"Subscription error: {e}")
        return False

async def subscribe_order_updates(websocket, account_id=None):
    """Subscribe to order updates"""
    if not websocket:
        print("Error: WebSocket connection is not established")
        return False
        
    try:
        # Build the order updates subscription message.
        sub_message = {
            "action": "subscribe",
            "mode": MODE_ORDER_UPDATES,
            "symbols": [
                {"symbol": "ORDER_UPDATES", "exchange": "NSE"}
            ]
        }
        if account_id:
            sub_message["account_id"] = account_id
            print(f"Subscribing to order updates for account: {account_id}")
        else:
            print("Subscribing to order updates using internal account id")
        
        print(f"Sending order update subscription: {json.dumps(sub_message, indent=2)}")
        await websocket.send(json.dumps(sub_message))
        response = await websocket.recv()
        print(f"Order update subscription response: {response}")
        
        return True
    except Exception as e:
        print(f"Subscription error: {e}")
        return False

def format_order_update(order_data):
    """Format order update data for better readability"""
    if not isinstance(order_data, dict):
        return str(order_data)
        
    # Extract important fields
    order_id = order_data.get('norenordno', 'N/A')
    status = order_data.get('status', 'UNKNOWN')
    symbol = order_data.get('tsym', 'N/A')
    exchange = order_data.get('exch', 'N/A')
    transaction_type = order_data.get('trantype', '').upper()
    order_type = order_data.get('prctyp', '').upper()
    product = order_data.get('prd', '').upper()
    quantity = order_data.get('qty', 0)
    filled_quantity = order_data.get('fillshares', 0)
    price = order_data.get('prc', 0.0)
    average_price = order_data.get('avgprc', 0.0)
    trigger_price = order_data.get('trgprc', 0.0)
    order_time = order_data.get('norentm', 'N/A')
    
    # Calculate filled percentage
    filled_pct = (float(filled_quantity) / float(quantity)) * 100 if quantity and float(quantity) > 0 else 0
    
    # Format the output
    lines = [
        f"\n{'='*60}",
        f"ORDER UPDATE [ID: {order_id}]",
        f"{'='*60}",
        f"Symbol:     {exchange}:{symbol}",
        f"Status:     {status}",
        f"Type:       {transaction_type} | {order_type} | {product}",
        f"Qty:        {filled_quantity}/{quantity} ({filled_pct:.1f}% filled)",
        f"Price:      {price} (Avg: {average_price})",
        f"Trigger:    {trigger_price}" if trigger_price else "",
        f"Time:       {order_time}",
        f"{'='*60}"
    ]
    
    # Remove any empty lines and join with newlines
    return '\n'.join(line for line in lines if line.strip())

async def receive_and_print_data(websocket, duration=30):
    """
    Receive and print market data or order updates for the specified duration
    
    Args:
        websocket: WebSocket connection
        duration: Duration in seconds to receive data
    """
    start_time = time.time()
    end_time = start_time + duration
    
    print(f"\nReceiving data for {duration} seconds...")
    print("Press Ctrl+C to stop early\n")
    
    try:
        while time.time() < end_time:
            try:
                # Set a timeout slightly longer than the remaining duration
                remaining = max(0.1, end_time - time.time())
                message = await asyncio.wait_for(websocket.recv(), timeout=min(5, remaining))
                
                # Parse the JSON message
                try:
                    data = json.loads(message)
                    
                    # Check if this is an order update message
                    if data.get('type') == 'order_update':
                        print("\n" + "="*60)
                        print("ORDER UPDATE RECEIVED:")
                        print("="*60)
                        print(format_order_update(data.get('data', data)))
                        print("="*60 + "\n")
                    else:
                        # For non-order messages, pretty print the JSON
                        print(f"\n{'-'*60}")
                        print(f"MESSAGE TYPE: {data.get('type', 'unknown')}")
                        print(f"{'-'*60}")
                        print(json.dumps(data, indent=2))
                        print(f"{'-'*60}")
                        
                except json.JSONDecodeError:
                    print(f"\nReceived non-JSON message: {message}")
                
                # Small sleep to prevent high CPU usage
                await asyncio.sleep(0.01)
                
            except asyncio.TimeoutError:
                # This is expected when we reach the end of the duration
                continue
                
    except asyncio.CancelledError:
        print("\nData reception cancelled by user")
    except Exception as e:
        print(f"\nError receiving data: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\nFinished receiving data")

async def run_test_suite():
    """
    Run all subscription tests with a single WebSocket connection
    """
    websocket = None
    
    try:
        # Connect once at the start
        websocket = await connect_and_authenticate(WS_URL, API_KEY)
        if not websocket:
            print("Failed to establish WebSocket connection")
            return
        
        # Test LTP subscription (mode 1)
        print("\n" + "="*50)
        print("TESTING LTP SUBSCRIPTION (MODE 1)")
        print("="*50)
        for symbol_info in [RELIANCE_NSE, IDEA_NSE, NATURALGAS_MCX]:
            await subscribe_market_data(websocket, symbol_info, MODE_LTP)
        await receive_and_print_data(websocket, duration=5)
        
        # Test Quote subscription (mode 2)
        print("\n" + "="*50)
        print("TESTING QUOTE SUBSCRIPTION (MODE 2)")
        print("="*50)
        for symbol_info in [RELIANCE_NSE, NHPC_NSE, NATURALGAS_MCX]:
            await subscribe_market_data(websocket, symbol_info, MODE_QUOTE)
        await receive_and_print_data(websocket, duration=5)
        
        # Test Depth subscription (mode 3)
        print("\n" + "="*50)
        print("TESTING DEPTH SUBSCRIPTION (MODE 3)")
        print("="*50)
        for symbol_info in [RELIANCE_NSE, NATURALGAS_MCX]:
            await subscribe_market_data(websocket, symbol_info, MODE_FULL)
        await receive_and_print_data(websocket, duration=5)
            
        # Test Order Updates subscription (mode 4) without an external account id
        print("\n" + "="*50)
        print("TESTING ORDER UPDATES SUBSCRIPTION (MODE 4)")
        print("="*50)
        await subscribe_order_updates(websocket)  # account_id omitted so internal id is used
        print("Successfully subscribed to order updates. Waiting for order events...")
        print("Place/cancel orders in your Flattrade account to see updates here.")
        print("Press Ctrl+C to stop.")
        await receive_and_print_data(websocket, duration=30)
        
    except Exception as e:
        print(f"\nError during test suite: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Close the connection when done with all tests
        if websocket:
            await websocket.close()
            print("\nClosed WebSocket connection")

async def run_single_test(test_type):
    websocket = await connect_and_authenticate(WS_URL, API_KEY)
    if not websocket:
        print("Failed to establish WebSocket connection")
        return
    try:
        if test_type in ["1", "ltp"]:
            print("\n" + "="*50)
            print("TESTING LTP SUBSCRIPTION (MODE 1)")
            print("="*50)
            for symbol_info in [RELIANCE_NSE, IDEA_NSE]:
                await subscribe_market_data(websocket, symbol_info, MODE_LTP)
            await receive_and_print_data(websocket, duration=30)
        elif test_type in ["2", "quote"]:
            print("\n" + "="*50)
            print("TESTING QUOTE SUBSCRIPTION (MODE 2)")
            print("="*50)
            for symbol_info in [RELIANCE_NSE, NHPC_NSE]:
                await subscribe_market_data(websocket, symbol_info, MODE_QUOTE)
            await receive_and_print_data(websocket, duration=30)
        elif test_type in ["3", "depth", "full"]:
            print("\n" + "="*50)
            print("TESTING DEPTH SUBSCRIPTION (MODE 3)")
            print("="*50)
            for symbol_info in [RELIANCE_NSE, NATURALGAS_MCX]:
                await subscribe_market_data(websocket, symbol_info, MODE_FULL)
            await receive_and_print_data(websocket, duration=30)
        elif test_type in ["4", "orders"]:
            print("\n" + "="*50)
            print("TESTING ORDER UPDATES SUBSCRIPTION (MODE 4)")
            print("="*50)
            await subscribe_order_updates(websocket)
            print("\n" + "-"*50)
            print("Successfully subscribed to order updates. Waiting for order events...")
            print("Place/cancel orders in your Flattrade account to see updates here.")
            print("Press Ctrl+C to stop.")
            print("-"*50 + "\n")
            await receive_and_print_data(websocket, duration=30)
        else:
            print("\n" + "!"*60)
            print(f"ERROR: Unknown test type: {test_type}")
            print("\nAvailable test types:")
            print("  1/ltp      - LTP subscription")
            print("  2/quote    - Quote subscription")
            print("  3/depth    - Market depth subscription")
            print("  4/orders   - Order updates (uses internal account id)")
            print("  (no args)  - Run all market data tests")
            print("\nExample: python test_websocket.py 4")
            print("!"*60 + "\n")
            return
    except asyncio.CancelledError:
        print("\nTest cancelled by user")
    except Exception as e:
        print(f"\nError during test: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await websocket.close()

def main():
    print("="*60)
    print("OpenAlgo WebSocket Client Test")
    print("-"*60)
    print(f"Connecting to: {WS_URL}")
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-8:]}")
    print("="*60 + "\n")
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        async def run_single():
            await run_single_test(test_type)
        try:
            asyncio.run(asyncio.wait_for(run_single(), timeout=60))
        except asyncio.TimeoutError:
            print("\nTest timed out after 60 seconds, exiting.")
    else:
        async def run_all():
            await run_test_suite()
        try:
            asyncio.run(asyncio.wait_for(run_all(), timeout=60))
        except asyncio.TimeoutError:
            print("\nTest suite timed out after 60 seconds, exiting.")

if __name__ == "__main__":
    main()