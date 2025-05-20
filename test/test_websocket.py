#!/usr/bin/env python
"""
WebSocket Client Test Script for OpenAlgo

This script demonstrates how to connect to the OpenAlgo WebSocket server
and subscribe to different types of market data (LTP, Quote, Depth).
"""

import asyncio
import json
import websockets
import sys

# Configuration
WS_URL = "ws://localhost:8765"  # Update if your server is on a different host/port
API_KEY = "918d504f250e6f7d6b533b245a46009d3f3b8cad8e6314c8b45ae8a35b972d8a"  # Your OpenAlgo API key

# Test symbols
RELIANCE_NSE = {"exchange": "MCX", "symbol": "GOLDPETAL30MAY25FUT"}
NIFTY_INDEX = {"exchange": "MCX", "symbol": "GOLD05JUN25FUT"}
BANKNIFTY_INDEX = {"exchange": "MCX", "symbol": "SILVER04JUL25FUT"}

# Subscription mode
SUBSCRIPTION_MODES = {
    "LTP": 1,      # Last Traded Price (mode 1)
    "Quote": 2,    # Bid/Ask quote (mode 2)
    "Depth": 3     # Full market depth (mode 3 - Snap Quote with Best Five data)
}

async def connect_and_authenticate(url, api_key):
    """Connect to the WebSocket server and authenticate"""
    try:
        websocket = await websockets.connect(url)
        
        # Authenticate with API key
        auth_message = {
            "action": "authenticate",
            "api_key": api_key
        }
        
        await websocket.send(json.dumps(auth_message))
        response = await websocket.recv()
        auth_response = json.loads(response)
        
        if auth_response.get("status") == "success":
            print(f"Successfully authenticated: {auth_response}")
            return websocket
        else:
            print(f"Authentication failed: {auth_response}")
            await websocket.close()
            return None
            
    except Exception as e:
        print(f"Connection error: {e}")
        return None

async def subscribe_to_data(websocket, symbols, mode="LTP"):
    """Subscribe to market data for the given symbols and mode"""
    if not websocket:
        return
        
    try:
        # Send individual subscription for each symbol
        for symbol_info in symbols:
            subscribe_message = {
                "action": "subscribe",
                "symbol": symbol_info["symbol"],
                "exchange": symbol_info["exchange"],
                "mode": mode,
                "depth": 5  # Default depth level
            }
            
            await websocket.send(json.dumps(subscribe_message))
            response = await websocket.recv()
            subscribe_response = json.loads(response)
            
            print(f"Subscription response for {symbol_info['symbol']} {mode}: {subscribe_response}")
        
        # Return after processing all symbols
        return True
    except Exception as e:
        print(f"Subscription error: {e}")
        return False

async def receive_and_print_data(websocket, duration=30):
    """Receive and print market data for the specified duration"""
    if not websocket:
        return
        
    print(f"\nReceiving market data for {duration} seconds...\n")
    try:
        end_time = asyncio.get_event_loop().time() + duration
        
        while asyncio.get_event_loop().time() < end_time:
            try:
                response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                data = json.loads(response)
                
                # Format the output based on the data type
                if "type" in data and data["type"] == "market_data":
                    symbol_info = f"{data.get('exchange', '')}:{data.get('symbol', '')}"
                    mode = data.get("mode", "")
                    market_data = data.get("data", {})
                    
                    if mode == 1:  # LTP
                        print(f"LTP {symbol_info}: {market_data.get('ltp', 'N/A')} | Time: {market_data.get('timestamp', 'N/A')}")
                    elif mode == 2:  # Quote
                        print(f"Quote {symbol_info}: Open: {market_data.get('open', 'N/A')} | High: {market_data.get('high', 'N/A')} | "
                              f"Low: {market_data.get('low', 'N/A')} | Close: {market_data.get('close', 'N/A')} | "
                              f"LTP: {market_data.get('ltp', 'N/A')}")
                    elif mode == 3:  # Depth (Snap Quote)
                        depth = market_data.get('depth', {'buy': [], 'sell': []})
                        buy_depth = depth.get('buy', [])
                        sell_depth = depth.get('sell', [])
                        
                        print(f"\nDepth {symbol_info} - LTP: {market_data.get('ltp', 'N/A')}")
                        
                        # Print all buy depth levels
                        print("\nBUY DEPTH:")
                        print("-" * 40)
                        print(f"{'Level':<6} {'Price':<10} {'Quantity':<10} {'Orders':<10}")
                        print("-" * 40)
                        
                        if buy_depth:
                            for i, level in enumerate(buy_depth):
                                print(f"{i+1:<6} {level.get('price', 'N/A'):<10} {level.get('quantity', 'N/A'):<10} {level.get('orders', 'N/A'):<10}")
                        else:
                            print("No buy depth data available")
                            
                        # Print all sell depth levels
                        print("\nSELL DEPTH:")
                        print("-" * 40)
                        print(f"{'Level':<6} {'Price':<10} {'Quantity':<10} {'Orders':<10}")
                        print("-" * 40)
                        
                        if sell_depth:
                            for i, level in enumerate(sell_depth):
                                print(f"{i+1:<6} {level.get('price', 'N/A'):<10} {level.get('quantity', 'N/A'):<10} {level.get('orders', 'N/A'):<10}")
                        else:
                            print("No sell depth data available")
                            
                        print("-" * 40)
                    else:
                        print(f"Market Data: {data}")
                else:
                    print(f"Received: {data}")
            except asyncio.TimeoutError:
                # This is expected due to the timeout
                pass
                
    except Exception as e:
        print(f"Error receiving data: {e}")
    finally:
        # Even if there's an error, we try to unsubscribe and close properly
        try:
            await websocket.send(json.dumps({"type": "unsubscribe_all"}))
            print("\nUnsubscribed from all symbols")
        except:
            pass

async def test_ltp_subscribe():
    """Test LTP subscription"""
    print("\n===== TESTING LTP SUBSCRIPTION =====")
    websocket = await connect_and_authenticate(WS_URL, API_KEY)
    
    if websocket:
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, NIFTY_INDEX], mode=SUBSCRIPTION_MODES["LTP"])
        if success:
            await receive_and_print_data(websocket, duration=10)
        await websocket.close()

async def test_quote_subscribe():
    """Test Quote subscription"""
    print("\n===== TESTING QUOTE SUBSCRIPTION =====")
    websocket = await connect_and_authenticate(WS_URL, API_KEY)
    
    if websocket:
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, BANKNIFTY_INDEX], mode=SUBSCRIPTION_MODES["Quote"])
        if success:
            await receive_and_print_data(websocket, duration=10)
        await websocket.close()

async def test_depth_subscribe():
    """Test Depth subscription"""
    print("\n===== TESTING DEPTH SUBSCRIPTION =====")
    websocket = await connect_and_authenticate(WS_URL, API_KEY)
    
    if websocket:
        success = await subscribe_to_data(websocket, [RELIANCE_NSE], mode=SUBSCRIPTION_MODES["Depth"])
        if success:
            await receive_and_print_data(websocket, duration=10)
        await websocket.close()

async def run_all_tests():
    """Run all subscription tests one by one"""
    await test_ltp_subscribe()
    await test_quote_subscribe()
    await test_depth_subscribe()

def main():
    """Main function to run the WebSocket tests"""
    print("OpenAlgo WebSocket Client Test")
    print(f"Connecting to: {WS_URL}")
    print(f"API Key: {API_KEY[:8]}...{API_KEY[-8:]}")
    
    # Check command line arguments for specific tests
    if len(sys.argv) > 1:
        test_type = sys.argv[1].lower()
        if test_type == "ltp":
            asyncio.run(test_ltp_subscribe())
        elif test_type == "quote":
            asyncio.run(test_quote_subscribe())
        elif test_type == "depth":
            asyncio.run(test_depth_subscribe())
        else:
            print(f"Unknown test type: {test_type}")
            print("Available test types: ltp, quote, depth")
    else:
        # Run all tests by default
        asyncio.run(run_all_tests())

if __name__ == "__main__":
    main()
