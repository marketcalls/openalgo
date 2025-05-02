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
API_KEY = "7c943a439ef0da4f3b8301730c84c7a84d5427c108db39378ca9415ee8db33bf"  # Your OpenAlgo API key

# Test symbols
RELIANCE_NSE = {"exchange": "NSE", "symbol": "RELIANCE"}
NIFTY_INDEX = {"exchange": "NSE", "symbol": "IDEA"}
BANKNIFTY_INDEX = {"exchange": "NSE", "symbol": "NHPC"}

# Subscription mode
SUBSCRIPTION_MODES = {
    "LTP": "LTP",   # Last Traded Price
    "Quote": "Quote",  # Bid/Ask quote
    "Depth": "Depth"   # Full market depth
}

async def connect_and_authenticate(url, api_key):
    """Connect to the WebSocket server and authenticate"""
    try:
        websocket = await websockets.connect(url)
        
        # Authenticate with API key
        auth_message = {
            "type": "auth",
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
        subscribe_message = {
            "type": "subscribe",
            "symbols": symbols,
            "mode": mode
        }
        
        await websocket.send(json.dumps(subscribe_message))
        response = await websocket.recv()
        subscribe_response = json.loads(response)
        
        print(f"Subscription response for {mode}: {subscribe_response}")
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
                    
                    if mode == "LTP":
                        print(f"LTP {symbol_info}: {data.get('ltp', 'N/A')} | LTQ: {data.get('ltq', 'N/A')} | Time: {data.get('timestamp', 'N/A')}")
                    elif mode == "Quote":
                        print(f"Quote {symbol_info}: Bid: {data.get('bid', 'N/A')} | Ask: {data.get('ask', 'N/A')} | BidQty: {data.get('bid_qty', 'N/A')} | AskQty: {data.get('ask_qty', 'N/A')}")
                    elif mode == "Depth":
                        print(f"Depth {symbol_info}: Top 5 Levels Received | Bid0: {data.get('bid', [])[0] if data.get('bid') and len(data.get('bid')) > 0 else 'N/A'} | Ask0: {data.get('ask', [])[0] if data.get('ask') and len(data.get('ask')) > 0 else 'N/A'}")
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
