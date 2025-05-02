# WebSocket Usage Example: Subscribing to Stock Data

This document provides a simple example of how to use the OpenAlgo WebSocket API to subscribe and unsubscribe to market data. The examples cover different subscription modes (LTP, Quote, Depth) and show both the server setup and client implementation.

> **Note about price format**: Different brokers use different price formats. For example, Angel broker sends prices in paise (1/100th of a rupee), which the OpenAlgo WebSocket adapter automatically converts to rupees by dividing by 100. All prices received from the OpenAlgo WebSocket API are normalized to standard formats, regardless of the underlying broker.

> **Cross-platform compatibility**: The WebSocket proxy implementation includes specific optimizations for Windows environments, ensuring reliable operation across all platforms.

## 1. Server Setup

Before running the example, make sure you have the WebSocket server running. The WebSocket server is integrated with the main Flask application and starts automatically when you run the app:

```bash
# Navigate to your project directory
cd /path/to/web-openalgo

# Start the Flask application with the WebSocket server
python -m openalgo.app
```

Alternatively, you can run the WebSocket server directly for testing:

```bash
# Run the standalone WebSocket server
python -m openalgo.test_websocket
```

## 2. Client Example: Python with websockets

Here's a complete Python example from the test_websocket.py file, demonstrating how to connect to the WebSocket server, subscribe to different market data modes, and handle the incoming data:

```python
import asyncio
import json
import websockets
import sys

# Configuration
WS_URL = "ws://localhost:8765"  # Update if your server is on a different host/port
API_KEY = "7c943a439ef0da4f3b8301730c84c7a84d5427c108db39378ca9415ee8db33bf"  # Your OpenAlgo API key

# Test symbols
RELIANCE_NSE = {"exchange": "NSE", "symbol": "RELIANCE"}
IDEA_NSE = {"exchange": "NSE", "symbol": "IDEA"}
NHPC_NSE = {"exchange": "NSE", "symbol": "NHPC"}

# Subscription mode
SUBSCRIPTION_MODES = {
    "LTP": 1,      # Last Traded Price (mode 1)
    "Quote": 2,    # Bid/Ask quote (mode 2)
    "Depth": 4     # Full market depth (mode 4)
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

async def subscribe_to_data(websocket, symbols, mode=1):
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
            
            print(f"Subscription response for {symbol_info['symbol']} mode {mode}: {subscribe_response}")
        
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
                    elif mode == 4:  # Depth
                        depth = market_data.get('depth', {'buy': [], 'sell': []})
                        buy_depth = depth.get('buy', [])
                        sell_depth = depth.get('sell', [])
                        
                        buy_info = f"Buy[0]: Price={buy_depth[0].get('price', 'N/A')}, Qty={buy_depth[0].get('quantity', 'N/A')}" if buy_depth else "No buy depth"
                        sell_info = f"Sell[0]: Price={sell_depth[0].get('price', 'N/A')}, Qty={sell_depth[0].get('quantity', 'N/A')}" if sell_depth else "No sell depth"
                        
                        print(f"Depth {symbol_info}: {buy_info} | {sell_info}")
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
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, IDEA_NSE], mode=SUBSCRIPTION_MODES["LTP"])
        if success:
            await receive_and_print_data(websocket, duration=10)
        await websocket.close()

async def test_quote_subscribe():
    """Test Quote subscription"""
    print("\n===== TESTING QUOTE SUBSCRIPTION =====")
    websocket = await connect_and_authenticate(WS_URL, API_KEY)
    
    if websocket:
        success = await subscribe_to_data(websocket, [RELIANCE_NSE, NHPC_NSE], mode=SUBSCRIPTION_MODES["Quote"])
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
```

## 3. Client Example: JavaScript with WebSocket

Here's a JavaScript example that can be used in a browser or Node.js application:

```javascript
// Your OpenAlgo API Key - replace with your actual key
const API_KEY = "your_openalgo_api_key_here";

// WebSocket server URL
const WS_URL = "ws://localhost:8765"; // Update with your server address

// Create WebSocket connection
const socket = new WebSocket(WS_URL);

// Connection opened
socket.addEventListener('open', (event) => {
    console.log('Connected to WebSocket server');
    
    // Step 1: Authenticate with API key
    const authMessage = {
        action: "authenticate",
        api_key: API_KEY
    };
    socket.send(JSON.stringify(authMessage));
});

// Process messages from server
socket.addEventListener('message', (event) => {
    const message = JSON.parse(event.data);
    
    // Handle authentication response
    if (message.action === "authenticate") {
        if (message.status === "success") {
            console.log("Authentication successful!");
            
            // Step 2: Subscribe to Reliance LTP data
            const subscribeMessage = {
                action: "subscribe",
                symbol: "RELIANCE",
                exchange: "NSE",
                mode: 1 // Mode 1 = LTP
            };
            socket.send(JSON.stringify(subscribeMessage));
        } else {
            console.error("Authentication failed:", message);
        }
    }
    // Handle subscription response
    else if (message.action === "subscribe") {
        if (message.status === "success") {
            console.log("Successfully subscribed to RELIANCE LTP data!");
        } else {
            console.error("Subscription failed:", message);
        }
    }
    // Handle unsubscription response
    else if (message.action === "unsubscribe") {
        if (message.status === "success") {
            console.log("Successfully unsubscribed from RELIANCE LTP data");
            socket.close();
        } else {
            console.error("Unsubscribe failed:", message);
        }
    }
    // Handle market data
    else if (message.type === "market_data") {
        const ltpData = message.data || {};
        console.log(`RELIANCE LTP: ${ltpData.ltp}, Time: ${ltpData.timestamp}`);
    }
});

// Handle errors
socket.addEventListener('error', (event) => {
    console.error('WebSocket error:', event);
});

// Handle socket closing
socket.addEventListener('close', (event) => {
    console.log('Disconnected from WebSocket server');
});

// Unsubscribe and close after 30 seconds
setTimeout(() => {
    if (socket.readyState === WebSocket.OPEN) {
        console.log("Unsubscribing after 30 seconds...");
        const unsubscribeMessage = {
            action: "unsubscribe",
            symbol: "RELIANCE",
            exchange: "NSE",
            mode: 1
        };
        socket.send(JSON.stringify(unsubscribeMessage));
    }
}, 30000);
```

## 4. Expected Output

When running the example, you should see output similar to:

```
Authentication successful!
Successfully subscribed to RELIANCE LTP data!
RELIANCE LTP: 2847.35, Time: 2025-04-17T14:30:12.456
RELIANCE LTP: 2847.45, Time: 2025-04-17T14:30:13.789
RELIANCE LTP: 2847.40, Time: 2025-04-17T14:30:14.123
...
Successfully unsubscribed from RELIANCE LTP data
```

## 5. Testing with Different Modes and Depth Levels

To test with different subscription modes or depth levels, modify the mode parameter in the subscribe message:

```python
# For Quote data (Mode 2)
subscribe_message = {
    "action": "subscribe",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "mode": 2  # Mode 2 = Quote
}

# For Market Depth data (Mode 4) with 5 levels
subscribe_message = {
    "action": "subscribe",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "mode": 4,  # Mode 4 = Depth
    "depth_level": 5
}

# For Market Depth data (Mode 4) with 20 levels
subscribe_message = {
    "action": "subscribe",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "mode": 4,  # Mode 4 = Depth
    "depth_level": 20
}
```

## 6. Troubleshooting

If you encounter issues:

1. **Authentication Errors**: Verify your API key is correct and active
2. **Connection Errors**: Ensure the WebSocket server is running and the URL is correct
3. **Subscription Errors**: Check if the symbol and exchange are valid
4. **No Data Received**: Verify that the broker's market is open and the requested symbol is actively trading

For more detailed information, refer to the main [websocket.md](websocket.md) documentation.

### 6.1 Connection Issues

If you're unable to connect to the WebSocket server:

1. **Check if the server is running** - run `netstat -an | findstr 8765` (Windows) or `netstat -an | grep 8765` (Linux/Mac) to see if the port is open
2. **Port conflicts** - the server may automatically choose a different port if 8765 is in use; check the console output for messages like "Port 8765 is in use, using port 8766 instead"
3. **Windows-specific issues** - ensure you're running a recent version of Python (3.8+) as earlier versions may have asyncio compatibility issues
4. **Firewall settings** - check if your firewall is blocking the connection

### 6.2 Advanced Usage

#### 6.2.1 Multiple Symbol Subscription

To subscribe to multiple symbols at once, simply send multiple subscription messages:

```javascript
// Subscribe to Reliance
socket.send(JSON.stringify({
    action: "subscribe",
    symbol: "RELIANCE",
    exchange: "NSE",
    mode: 1
}));

// Subscribe to Infosys
socket.send(JSON.stringify({
    action: "subscribe",
    symbol: "INFY",
    exchange: "NSE",
    mode: 1
}));
```

#### 6.2.2 Cross-Platform Compatibility Notes

The WebSocket proxy has been specifically optimized to work on all platforms, with special considerations for Windows:

1. **Windows Event Loop Policy**: When running on Windows, the system automatically sets the appropriate event loop policy:
   ```python
   if platform.system() == 'Windows':
       asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
   ```

2. **Signal Handling**: The implementation uses platform-specific signal handling with a fallback for Windows platforms.

3. **Port Management**: The system checks for port availability and will automatically select an alternative port if the default port (8765) is already in use - this is particularly useful in development scenarios with Flask debug mode.

4. **ZeroMQ Compatibility**: The implementation ensures ZeroMQ works correctly across platforms.
