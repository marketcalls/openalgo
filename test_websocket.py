import asyncio
import json
import os
import sys
import time
import websockets

# Configuration
WS_URL = "ws://localhost:8765"  # Update if your server is on a different host/port
API_KEY = "5d6fc9aa26e147554f253a5336e6cefd662eb960af55c231600fa75e068feab0"  # Your OpenAlgo API key

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
        
        # Add connection timeout
        try:
            websocket = await asyncio.wait_for(
                websockets.connect(url, ping_interval=30, ping_timeout=10, close_timeout=5),
                timeout=10.0
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
            
            # Wait for authentication response with timeout
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=10.0)
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

async def subscribe_to_data(websocket, symbols=None, mode=MODE_QUOTE, account_id=None):
    """
    Subscribe to market data or order updates
    
    Args:
        websocket: WebSocket connection
        symbols: List of symbol info dicts (for market data)
        mode: Subscription mode (1=LTP, 2=Quote, 3=Full/Depth, 4=Order Updates)
        account_id: Required for order updates (mode=4)
    """
    if not websocket:
        print("Error: WebSocket connection is not established")
        return False
        
    try:
        if mode == MODE_ORDER_UPDATES:
            if not account_id:
                error_msg = "Error: account_id is required for order updates"
                print(error_msg)
                return False
            
            # For order updates, we don't need symbols as we subscribe to all order updates for the account
            print(f"\nPreparing to subscribe to order updates for account: {account_id}")
            
            # Create order update subscription message in the format expected by the WebSocket server
            # The server expects an 'action' field and handles the Flattrade protocol internally
            subscribe_message = {
                "action": "subscribe",
                "mode": mode,  # MODE_ORDER_UPDATES = 4
                "account_id": account_id,
                "symbols": [
                    {
                        "symbol": "ORDER_UPDATES",  # Dummy symbol for order updates
                        "exchange": "NSE"
                    }
                ]
            }
            
            print(f"Sending subscription message: {json.dumps(subscribe_message, indent=2)}")
            
            try:
                await websocket.send(json.dumps(subscribe_message))
                print("Subscription message sent. Waiting for acknowledgment...")
                
                # Wait for subscription acknowledgment with a timeout
                try:
                    response = await asyncio.wait_for(websocket.recv(), timeout=10)
                    print(f"Received response: {response}")
                    
                    try:
                        response_data = json.loads(response)
                        print(f"Parsed response: {json.dumps(response_data, indent=2)}")
                        
                        if response_data.get('status') == 'success':
                            print(f"✓ Successfully subscribed to order updates for account: {account_id}")
                            return True
                        else:
                            error_msg = response_data.get('emsg', 'Unknown error')
                            print(f"✗ Failed to subscribe to order updates: {error_msg}")
                            return False
                            
                    except json.JSONDecodeError as je:
                        print(f"✗ Failed to parse JSON response: {je}")
                        print(f"Raw response: {response}")
                        return False
                        
                except asyncio.TimeoutError:
                    print("✗ Timeout waiting for subscription acknowledgment")
                    return False
                    
            except Exception as send_error:
                print(f"✗ Error sending subscription message: {send_error}")
                return False
                
            return True
            
        # Handle market data subscriptions (modes 1-3)
        if not symbols:
            print("Error: symbols are required for market data subscriptions")
            return False
            
        # Send individual subscription for each symbol
        for symbol_info in symbols:
            # Map mode to string for logging
            mode_str = {1: "LTP", 2: "Quote", 3: "Depth"}.get(mode, str(mode))
                
            subscribe_message = {
                "action": "subscribe",
                "symbol": symbol_info["symbol"],
                "exchange": symbol_info["exchange"],
                "mode": mode,  # Send numeric mode
                "depth": 5  # Default depth level
            }
            
            await websocket.send(json.dumps(subscribe_message))
            response = await websocket.recv()
            subscribe_response = json.loads(response)
            
            print(f"Subscription response for {symbol_info['symbol']} mode {mode}: {subscribe_response}")
        
        # Return after processing all symbols
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

async def run_test_suite(account_id=None):
    """
    Run all subscription tests with a single WebSocket connection
    
    Args:
        account_id: Optional account ID for testing order updates. If None, will try to get from BROKER_API_KEY
    """
    websocket = None
    
    # If account_id is not provided but we're not in a specific test mode, try to get from env
    if account_id is None and len(sys.argv) <= 1:  # Only for full test suite
        account_id = get_account_id()
    
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
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, IDEA_NSE, NATURALGAS_MCX], 
                                        mode=MODE_LTP)
        if success:
            await receive_and_print_data(websocket, duration=5)
        
        # Test Quote subscription (mode 2)
        print("\n" + "="*50)
        print("TESTING QUOTE SUBSCRIPTION (MODE 2)")
        print("="*50)
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, NHPC_NSE, NATURALGAS_MCX], 
                                        mode=MODE_QUOTE)
        if success:
            await receive_and_print_data(websocket, duration=5)
        
        # Test Depth subscription (mode 3)
        print("\n" + "="*50)
        print("TESTING DEPTH SUBSCRIPTION (MODE 3)")
        print("="*50)
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, NATURALGAS_MCX], 
                                        mode=MODE_FULL)
        if success:
            await receive_and_print_data(websocket, duration=5)
            
        # Test Order Updates subscription (mode 4) if account_id is available
        if account_id:
            print("\n" + "="*50)
            print(f"TESTING ORDER UPDATES SUBSCRIPTION (MODE 4) for account: {account_id}")
            print("="*50)
            success = await subscribe_to_data(websocket, mode=MODE_ORDER_UPDATES, 
                                            account_id=account_id)
            if success:
                print("Successfully subscribed to order updates. Waiting for order events...")
                print("Place/cancel orders in your Flattrade account to see updates here.")
                print("Press Ctrl+C to stop.")
                await receive_and_print_data(websocket, duration=300)  # 5 minutes for order updates
        else:
            print("\n" + "-"*50)
            print("Skipping order updates test - no account_id provided")
            print("To test order updates, make sure BROKER_API_KEY is set in your .env file")
            print("with format: BROKER_API_KEY=your_api_key|your_account_id")
            print("-"*50)
            
    except Exception as e:
        print(f"\nError during test suite: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Close the connection when done with all tests
        if websocket:
            await websocket.close()
            print("\nClosed WebSocket connection")

def get_account_id():
    """Get account ID from BROKER_API_KEY environment variable"""
    broker_api_key = os.getenv('BROKER_API_KEY')
    if not broker_api_key:
        print("\n" + "!"*60)
        print("ERROR: BROKER_API_KEY environment variable not set")
        print("Please set BROKER_API_KEY in your .env file")
        print("Example: BROKER_API_KEY=your_api_key|your_account_id")
        print("!"*60 + "\n")
        return None
    # Extract account ID from BROKER_API_KEY (format: api_key|account_id)
    parts = broker_api_key.split('|')
    if len(parts) >= 2:
        return parts[1]  # Return the account ID part
    return parts[0]  # Fallback to the whole key if no pipe separator

def main():
    """Main function to run the WebSocket tests"""
    print("="*60)
    print("OpenAlgo WebSocket Client Test")
    print("-"*60)
    print(f"Connecting to: {WS_URL}")
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-8:]}")
    print("="*60 + "\n")
    


    # Check if we're running a specific test or all tests
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        
        # Get account ID from environment variables for order updates
        account_id = get_account_id() if test_type in ["4", "orders"] else None
        
        async def run_single_test():
            websocket = await connect_and_authenticate(WS_URL, API_KEY)
            if not websocket:
                print("Failed to establish WebSocket connection")
                return
                
            try:
                if test_type == "1" or test_type == "ltp":
                    print("\n" + "="*50)
                    print("TESTING LTP SUBSCRIPTION (MODE 1)")
                    print("="*50)
                    await subscribe_to_data(websocket, [RELIANCE_NSE, IDEA_NSE], MODE_LTP)
                    await receive_and_print_data(websocket, duration=30)
                elif test_type == "2" or test_type == "quote":
                    print("\n" + "="*50)
                    print("TESTING QUOTE SUBSCRIPTION (MODE 2)")
                    print("="*50)
                    await subscribe_to_data(websocket, [RELIANCE_NSE, NHPC_NSE], MODE_QUOTE)
                    await receive_and_print_data(websocket, duration=30)
                elif test_type == "3" or test_type == "depth" or test_type == "full":
                    print("\n" + "="*50)
                    print("TESTING DEPTH SUBSCRIPTION (MODE 3)")
                    print("="*50)
                    await subscribe_to_data(websocket, [RELIANCE_NSE, NATURALGAS_MCX], MODE_FULL)
                    await receive_and_print_data(websocket, duration=30)
                elif test_type == "4" or test_type == "orders":
                    print("\n" + "="*50)
                    print(f"TESTING ORDER UPDATES SUBSCRIPTION (MODE 4)")
                    print(f"Using account ID from BROKER_API_KEY: {account_id}")
                    print("="*50)
                    await subscribe_to_data(websocket, mode=MODE_ORDER_UPDATES, account_id=account_id)
                    print("\n" + "-"*50)
                    print("Successfully subscribed to order updates. Waiting for order events...")
                    print("Place/cancel orders in your Flattrade account to see updates here.")
                    print("Press Ctrl+C to stop.")
                    print("-"*50 + "\n")
                    await receive_and_print_data(websocket, duration=300)  # 5 minutes for order updates
                else:
                    print("\n" + "!"*60)
                    print(f"ERROR: Unknown test type: {test_type}")
                    print("\nAvailable test types:")
                    print("  1/ltp      - LTP subscription")
                    print("  2/quote    - Quote subscription")
                    print("  3/depth    - Market depth subscription")
                    print("  4/orders   - Order updates (uses BROKER_API_KEY)")
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
                
        asyncio.run(run_single_test())
    else:
        # Run all tests if no specific test is specified
        print("\n" + "="*50)
        print("RUNNING ALL MARKET DATA TESTS")
        print("="*50)
        print("Note: To test order updates, run: python test_websocket.py 4")
        print("      Make sure BROKER_API_KEY is set in your .env file")
        print("      Format: BROKER_API_KEY=your_api_key|your_account_id")
        print("      The account ID will be automatically extracted from BROKER_API_KEY")
        print("="*50 + "\n")
        asyncio.run(run_test_suite())

if __name__ == "__main__":
    main()