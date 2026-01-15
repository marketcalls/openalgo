# Websockets

## OpenAlgo WebSocket Protocol Documentation

### Overview

The OpenAlgo WebSocket protocol allows clients to receive **real-time market data** using a standardized and broker-agnostic interface. It supports data streaming for **LTP (Last Traded Price)**, **Quotes (OHLC + Volume)**, and **Market Depth** (up to 50 levels depending on broker capability).

The protocol ensures efficient, scalable, and secure communication between client applications (such as trading bots, dashboards, or analytics tools) and the OpenAlgo platform. Authentication is handled using the OpenAlgo API key, and subscriptions are maintained per session.

### Version

* Protocol Version: 1.0
* Last Updated: May 28, 2025
* Platform: OpenAlgo Trading Framework

### WebSocket URL

```
ws://<host>:8765
```

Replace `<host>` with the IP/domain of your OpenAlgo instance. For local development setups, use thee hostname as`127.0.0.1`

```
ws://127.0.0.1:8765
```

In the production ubuntu server if your host is <https://yourdomain.com> then&#x20;

WebSocket url will be

```
wss://yourdomain.com/ws
```

In the production ubuntu server if your host is <https://sub.yourdomain.com> then&#x20;

WebSocket url will be

```
wss://sub.yourdomain.com/ws
```

### Authentication

All WebSocket sessions must begin with API key authentication:

```json
{
  "action": "authenticate", 
  "api_key": "YOUR_OPENALGO_API_KEY"
}
```

On success, the server confirms authentication. On failure, the connection is closed or an error message is returned.

### Data Modes

Clients can subscribe to different types of market data using the `mode` parameter. Each mode corresponds to a specific level of detail:

| Mode | Description    | Details                                    |
| ---- | -------------- | ------------------------------------------ |
| 1    | **LTP Mode**   | Last traded price and timestamp only       |
| 2    | **Quote Mode** | Includes OHLC, LTP, volume, change, etc.   |
| 3    | **Depth Mode** | Includes buy/sell order book (5–50 levels) |

> Note: Mode 3 supports optional parameter `depth_level` to define the number of depth levels requested (e.g., 5, 20, 30, 50). Actual support depends on the broker.

### Subscription Format

#### Basic Subscription

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 1
}
```

#### Depth Subscription (with levels)

```json
{
  "action": "subscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 3,
  "depth_level": 5
}
```

### Unsubscription

To unsubscribe from a stream:

```json
{
  "action": "unsubscribe",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2
}
```

### Error Handling

If a client requests a depth level not supported by their broker:

```json
{
  "type": "error",
  "code": "UNSUPPORTED_DEPTH_LEVEL",
  "message": "Depth level 50 is not supported by broker Angel for exchange NSE",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "requested_mode": 3,
  "requested_depth": 50,
  "supported_depths": [5, 20]
}
```

### Market Data Format

#### LTP (Mode 1)

```json
{
  "type": "market_data",
  "mode": 1,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "timestamp": "2025-05-28T10:30:45.123Z"
  }
}
```

#### Quote (Mode 2)

```json
{
  "type": "market_data",
  "mode": 2,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "change": 6.0,
    "change_percent": 0.42,
    "volume": 100000,
    "open": 1415.0,
    "high": 1432.5,
    "low": 1408.0,
    "close": 1418.0,
    "last_trade_quantity": 50,
    "avg_trade_price": 1419.35,
    "timestamp": "2025-05-28T10:30:45.123Z"
  }
}
```

#### Depth (Mode 3 with depth\_level = 5)

```json
{
  "type": "market_data",
  "mode": 3,
  "depth_level": 5,
  "topic": "RELIANCE.NSE",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 1424.0,
    "depth": {
      "buy": [
        {"price": 1423.9, "quantity": 50, "orders": 3},
        {"price": 1423.5, "quantity": 35, "orders": 2},
        {"price": 1423.0, "quantity": 42, "orders": 4},
        {"price": 1422.5, "quantity": 28, "orders": 1},
        {"price": 1422.0, "quantity": 33, "orders": 5}
      ],
      "sell": [
        {"price": 1424.1, "quantity": 47, "orders": 2},
        {"price": 1424.5, "quantity": 39, "orders": 3},
        {"price": 1425.0, "quantity": 41, "orders": 4},
        {"price": 1425.5, "quantity": 32, "orders": 2},
        {"price": 1426.0, "quantity": 30, "orders": 1}
      ]
    },
    "timestamp": "2025-05-28T10:30:45.123Z",
    "broker_supported": true
  }
}
```

### Heartbeat and Reconnection

* Server sends `ping` messages every 30 seconds.
* Clients must respond with `pong` or will be disconnected.
* Upon reconnection, clients must re-authenticate and re-subscribe to streams.
* Proxy may automatically restore prior subscriptions if supported by broker.

### Security & Compliance

* All clients must authenticate with an API key.
* Unauthorized or malformed requests are rejected.
* Rate limits may apply to prevent abuse.
* TLS encryption recommended for production deployments.

The OpenAlgo WebSocket feed provides a reliable and structured method for receiving real-time trading data. Proper mode selection and parsing allow efficient integration into trading algorithms and monitoring systems.

# Websockets (Verbose Control)

The `verbose` parameter manages SDK-level logging for WebSocket feed operations (LTP, Quote, Depth).\
This helps developers toggle between silent mode, basic logs, or full debug-level market data streaming.

***

### **Verbose Levels**

| Level      | Value          | Description                                        |
| ---------- | -------------- | -------------------------------------------------- |
| **Silent** | `False` or `0` | Errors only (default)                              |
| **Basic**  | `True` or `1`  | Connection, authentication, subscription logs      |
| **Debug**  | `2`            | All market data updates, including LTP/Quote/Depth |

***

### **Usage**

```python
from openalgo import api

# Silent mode (default) - no SDK output
client = api(api_key="...", host="...", ws_url="...", verbose=False)

# Basic logging - connection/subscription info
client = api(api_key="...", host="...", ws_url="...", verbose=True)

# Full debug - all data updates
client = api(api_key="...", host="...", ws_url="...", verbose=2)
```

***

## **Test Example**

```python
"""
Test verbose control in OpenAlgo WebSocket Feed
"""
from openalgo import api
import time

# Change this to test different levels: False, True, 1, 2
VERBOSE_LEVEL = True

client = api(
    api_key="your_api_key_here",
    host="http://127.0.0.1:5000",
    ws_url="ws://127.0.0.1:8765",
    verbose=VERBOSE_LEVEL
)

instruments_list = [
    {"exchange": "NSE_INDEX", "symbol": "NIFTY"},
    {"exchange": "NSE", "symbol": "INFY"}
]

def on_data_received(data):
    # User callback: always executed regardless of verbose mode
    print(f"MY CALLBACK: {data['symbol']} LTP: {data['data'].get('ltp')}")

print(f"\n=== Testing with verbose={VERBOSE_LEVEL} ===\n")

# Connect and subscribe
client.connect()
client.subscribe_quote(instruments_list, on_data_received=on_data_received)

# Poll few times
for i in range(5):
    print(f"\n--- Poll {i+1} ---")
    quotes = client.get_quotes()
    for exch, symbols in quotes.get('quote', {}).items():
        for sym, data in symbols.items():
            print(f"  {exch}:{sym} = {data.get('ltp')}")
    time.sleep(1)

# Cleanup
client.unsubscribe_quote(instruments_list)
client.disconnect()
```

***

## **Expected Output**

### **verbose=False (Silent)**

```
=== Testing with verbose=False ===

MY CALLBACK: NIFTY LTP: 26008.5

--- Poll 1 ---
  NSE_INDEX:NIFTY = 26008.5
  NSE:INFY = 1531.0
```

***

### **verbose=True (Basic)**

```
=== Testing with verbose=True ===

[WS]    Connected to ws://127.0.0.1:8765
[AUTH]  Authenticating with API key: bf1267a1...7cf9169f
[AUTH]  Success | Broker: upstox | User: rajandran
[SUB]   Subscribing NSE_INDEX:NIFTY Quote...
[SUB]   NSE_INDEX:NIFTY | Mode: Quote | Status: success
[SUB]   Subscribing NSE:INFY Quote...
[SUB]   NSE:INFY | Mode: Quote | Status: success
MY CALLBACK: NIFTY LTP: 26008.5

--- Poll 1 ---
  NSE_INDEX:NIFTY = 26008.5
  NSE:INFY = 1531.0
```

***

### **verbose=2 (Full Debug)**

```
=== Testing with verbose=2 ===

[WS]    Connected to ws://127.0.0.1:8765
[AUTH]  Authenticating with API key: bf1267a1...7cf9169f
[AUTH]  Success | Broker: upstox | User: rajandran
[AUTH]  Full response: {'type': 'auth', 'status': 'success', ...}
[SUB]   Subscribing NSE_INDEX:NIFTY Quote...
[SUB]   NSE_INDEX:NIFTY | Mode: Quote | Status: success
[SUB]   Full response: {'type': 'subscribe', ...}
[QUOTE] NSE_INDEX:NIFTY      | O: 25998.5    H: 26025.5    L: 25924.15   C: 26008.5    LTP: 26008.5
MY CALLBACK: NIFTY LTP: 26008.5
[QUOTE] NSE:INFY             | O: 1549.0     H: 1550.6     L: 1525.9     C: 1531.0     LTP: 1531.0

--- Poll 1 ---
  NSE_INDEX:NIFTY = 26008.5
  NSE:INFY = 1531.0
```

***

## **Log Categories**

| Tag          | Meaning                             |
| ------------ | ----------------------------------- |
| **\[WS]**    | WebSocket connection events         |
| **\[AUTH]**  | Authentication requests & responses |
| **\[SUB]**   | Subscription operations             |
| **\[UNSUB]** | Unsubscription logs                 |
| **\[LTP]**   | LTP updates *(verbose=2)*           |
| **\[QUOTE]** | Quote updates *(verbose=2)*         |
| **\[DEPTH]** | Market depth updates *(verbose=2)*  |
| **\[ERROR]** | Error messages *(always shown)*     |
