# WebSocket Usage Example: Subscribing to Stock Data

This document provides a simple example of how to use the OpenAlgo WebSocket API to subscribe and unsubscribe to Reliance LTP (Last Traded Price) data. The example shows both the server setup and client implementation.

## 1. Server Setup

Before running the example, make sure you have the WebSocket server running:

```bash
# Navigate to your project directory
cd /path/to/openalgo-py

# Start the WebSocket server
python -m openalgo.websocket.server
```

## 2. Client Example: Python with websockets

Here's a complete Python example for connecting to the WebSocket server, subscribing to Reliance LTP data, and handling the incoming data:

```python
import asyncio
import json
import websockets
import os

# Your OpenAlgo API Key - replace with your actual key
API_KEY = "your_openalgo_api_key_here"

# WebSocket server URL
WS_URL = "ws://localhost:8765"  # Update with your server address

async def subscribe_to_reliance_ltp():
    """Example of subscribing to Reliance LTP data and unsubscribing after 30 seconds"""
    
    async with websockets.connect(WS_URL) as websocket:
        # Step 1: Authenticate with API key
        auth_message = {
            "action": "authenticate",
            "api_key": API_KEY
        }
        await websocket.send(json.dumps(auth_message))
        response = await websocket.recv()
        auth_response = json.loads(response)
        
        if auth_response.get("status") != "success":
            print(f"Authentication failed: {auth_response}")
            return
            
        print("Authentication successful!")
        
        # Step 2: Subscribe to Reliance LTP data (Mode 1)
        subscribe_message = {
            "action": "subscribe",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "mode": 1  # Mode 1 = LTP
        }
        await websocket.send(json.dumps(subscribe_message))
        response = await websocket.recv()
        sub_response = json.loads(response)
        
        if sub_response.get("status") != "success":
            print(f"Subscription failed: {sub_response}")
            return
            
        print(f"Successfully subscribed to RELIANCE LTP data!")
        
        # Step 3: Handle incoming market data
        try:
            # Process messages for 30 seconds
            end_time = asyncio.get_event_loop().time() + 30
            while asyncio.get_event_loop().time() < end_time:
                try:
                    # Set a timeout for receiving messages
                    response = await asyncio.wait_for(websocket.recv(), timeout=1.0)
                    market_data = json.loads(response)
                    
                    # Process market data
                    if market_data.get("type") == "market_data":
                        ltp_data = market_data.get("data", {})
                        print(f"RELIANCE LTP: {ltp_data.get('ltp')}, Time: {ltp_data.get('timestamp')}")
                    else:
                        print(f"Received other message: {market_data}")
                        
                except asyncio.TimeoutError:
                    # No message received within timeout period
                    continue
        finally:
            # Step 4: Unsubscribe from the data feed
            unsubscribe_message = {
                "action": "unsubscribe",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "mode": 1
            }
            await websocket.send(json.dumps(unsubscribe_message))
            response = await websocket.recv()
            unsub_response = json.loads(response)
            
            if unsub_response.get("status") == "success":
                print("Successfully unsubscribed from RELIANCE LTP data")
            else:
                print(f"Unsubscribe failed: {unsub_response}")

# Run the example
if __name__ == "__main__":
    asyncio.run(subscribe_to_reliance_ltp())
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
