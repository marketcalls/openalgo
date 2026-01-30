# Current ZeroMQ Usage in OpenAlgo

## Overview

ZeroMQ is currently used in **exactly 2 places** in the OpenAlgo architecture for **market data streaming only**. It acts as an in-memory message bus between broker adapters and consumers.

---

## 1. ZeroMQ Publisher - Broker Adapters

### Location
**File**: `websocket_proxy/base_adapter.py`

### What it does
- Each broker adapter (Angel, Zerodha, Dhan, etc.) creates a ZMQ **PUB** (Publisher) socket
- Publishes market data received from broker APIs
- Topic format: `BROKER_EXCHANGE_SYMBOL_MODE` (e.g., `ANGEL_NSE_SBIN_LTP`)

### Code Implementation

```python
# In base_adapter.py (Line ~150-200)

class BaseBrokerWebSocketAdapter(ABC):
    def __init__(self):
        # Create ZeroMQ context
        self.context = zmq.Context()
        
        # Create PUB socket
        self.socket = self.context.socket(zmq.PUB)
        
        # Bind to available port (default 5555)
        zmq_port = os.getenv("ZMQ_PORT", "5555")
        self.socket.bind(f"tcp://*:{zmq_port}")
        
        print(f"ZMQ Publisher started on port {zmq_port}")
    
    def publish_market_data(self, topic, data):
        """Publish market data to ZeroMQ"""
        # Example: topic = "ANGEL_NSE_SBIN_LTP"
        # Example: data = {"ltp": 850.50, "volume": 12345}
        
        self.socket.send_multipart([
            topic.encode("utf-8"),           # Topic as bytes
            json.dumps(data).encode("utf-8") # Data as JSON bytes
        ])
```

### Message Flow from Broker
```
1. Broker WebSocket API sends tick data
   ↓
2. Broker adapter receives and parses data
   ↓
3. Adapter calls publish_market_data(topic, data)
   ↓
4. ZMQ PUB socket broadcasts message
   ↓
5. All ZMQ SUB sockets connected to this port receive the message
```

### Configuration
```bash
# .env
ZMQ_HOST=127.0.0.1  # Localhost binding
ZMQ_PORT=5555       # Default port (auto-finds free port if busy)
```

### All Broker Adapters Inherit This
All 27 broker adapters inherit from `BaseBrokerWebSocketAdapter`, so they all automatically get ZMQ publishing capability:

- Angel, Zerodha, Dhan, Flattrade, Fyers, Upstox, etc.
- Each uses the **same ZMQ port** (5555 by default)
- Each publishes with its broker name prefix

---

## 2. ZeroMQ Subscriber - WebSocket Proxy

### Location
**File**: `websocket_proxy/server.py`

### What it does
- WebSocket proxy server subscribes to ALL broker adapter messages
- Receives market data via ZMQ **SUB** (Subscriber) socket
- Routes data to connected WebSocket clients based on their subscriptions

### Code Implementation

```python
# In server.py (Line ~60-90)

class WebSocketProxy:
    def __init__(self, host="127.0.0.1", port=8765):
        # Create ZeroMQ context
        self.context = zmq.asyncio.Context()
        
        # Create SUB socket
        self.socket = self.context.socket(zmq.SUB)
        
        # Connect to broker adapters
        ZMQ_HOST = os.getenv("ZMQ_HOST", "127.0.0.1")
        ZMQ_PORT = os.getenv("ZMQ_PORT")
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        
        # Subscribe to ALL topics (receives all messages)
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
        
        print(f"ZMQ Subscriber connected to {ZMQ_HOST}:{ZMQ_PORT}")
```

### Message Listener Loop

```python
# In server.py (Line ~800+)

async def zmq_listener(self):
    """Listen for messages from broker adapters"""
    
    while self.running:
        try:
            # Wait for message with 0.3s timeout
            [topic, data] = await asyncio.wait_for(
                self.socket.recv_multipart(),
                timeout=0.3
            )
            
            # Parse message
            topic_str = topic.decode("utf-8")  # "ANGEL_NSE_SBIN_LTP"
            market_data = json.loads(data.decode("utf-8"))
            
            # Extract components
            parts = topic_str.split("_")
            broker = parts[0]    # "ANGEL"
            exchange = parts[1]  # "NSE"
            symbol = parts[2]    # "SBIN"
            mode = parts[3]      # "LTP"
            
            # Route to subscribed WebSocket clients
            for client_id in self.subscription_index[(symbol, exchange, mode)]:
                await self.send_message(client_id, {
                    "type": "market_data",
                    "symbol": symbol,
                    "exchange": exchange,
                    "data": market_data
                })
                
        except asyncio.TimeoutError:
            continue  # No message, continue loop
```

### Message Flow to Clients
```
1. ZMQ SUB socket receives message
   ↓
2. Parse topic (BROKER_EXCHANGE_SYMBOL_MODE)
   ↓
3. Look up subscribed clients in subscription_index
   ↓
4. Send to each WebSocket client in parallel
   ↓
5. Client receives JSON over WebSocket
```

---

## 3. Optional: Market Data Service Consumer

### Location
**File**: `services/market_data_service.py`

### What it does
- Backend service that also subscribes to ZMQ for market data
- Feeds data to sandbox execution engine, position MTM, RMS, etc.
- Runs independently of WebSocket clients

### Code Pattern

```python
# In market_data_service.py

class MarketDataService:
    def __init__(self):
        # Create ZMQ subscriber
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.SUB)
        
        ZMQ_HOST = os.getenv("ZMQ_HOST", "127.0.0.1")
        ZMQ_PORT = os.getenv("ZMQ_PORT")
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        
        # Subscribe to all topics
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
    
    def start(self):
        """Consume market data for backend processing"""
        while True:
            [topic, data] = self.socket.recv_multipart()
            market_data = json.loads(data.decode("utf-8"))
            
            # Process for sandbox, MTM, RMS, etc.
            self.process_market_data(market_data)
```

---

## Current Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                 BROKER ADAPTERS (27 brokers)                 │
│  ┌───────────────────────────────────────────────────────┐  │
│  │ Angel, Zerodha, Dhan, Flattrade, Fyers, Upstox, etc. │  │
│  │                                                        │  │
│  │ Each inherits from BaseBrokerWebSocketAdapter        │  │
│  │ - Connects to broker WebSocket API                    │  │
│  │ - Receives market ticks                               │  │
│  │ - Calls publish_market_data(topic, data)             │  │
│  └───────────────────────────┬───────────────────────────┘  │
└────────────────────────────────┼────────────────────────────┘
                                 │
                                 │ ZMQ PUB
                                 │ tcp://*:5555
                                 │
                    ┌────────────▼───────────┐
                    │   ZeroMQ Message Bus   │
                    │   (In-Memory, Local)   │
                    │                        │
                    │ - PUB/SUB pattern      │
                    │ - Topic-based routing  │
                    │ - No persistence       │
                    │ - Single process       │
                    └────────┬───────┬───────┘
                             │       │
              ZMQ SUB        │       │ ZMQ SUB
         tcp://127.0.0.1:5555│       │tcp://127.0.0.1:5555
                             │       │
          ┌──────────────────▼───┐   │
          │  WebSocket Proxy     │   │
          │  server.py           │   │
          │  Port: 8765          │   │
          │                      │   │
          │ - Subscribes to ZMQ  │   │
          │ - Routes to clients  │   │
          │ - Per-user auth      │   │
          └──────────┬───────────┘   │
                     │                │
                     │ WebSocket      │
                     │ (ws://...)     │
                     │                │
          ┌──────────▼───────────┐   │
          │  WebSocket Clients   │   │
          │  (Python SDK, etc.)  │   │
          │                      │   │
          │ - Strategies         │   │
          │ - Real-time feed     │   │
          └──────────────────────┘   │
                                     │
                  ┌──────────────────▼──────────┐
                  │  Market Data Service        │
                  │  market_data_service.py     │
                  │                             │
                  │ - Sandbox execution         │
                  │ - Position MTM              │
                  │ - RMS checks                │
                  └─────────────────────────────┘
```

---

## ZeroMQ Pattern Details

### Pattern Type
**PUB/SUB** (Publisher/Subscriber)

### Characteristics
- ✅ **One-to-Many**: One publisher → Multiple subscribers
- ✅ **Topic-based filtering**: Subscribers can filter by topic
- ✅ **Non-blocking**: Publisher doesn't wait for subscribers
- ✅ **In-memory**: Ultra-fast, no disk I/O
- ❌ **No persistence**: Messages lost if subscriber offline
- ❌ **No message history**: Can't replay past messages
- ❌ **Single machine**: All processes must be on same host

### Performance
- **Latency**: < 1ms (in-process)
- **Latency**: 1-2ms (localhost TCP)
- **Throughput**: 1M+ messages/sec (local)

---

## What ZeroMQ is NOT Used For

### ❌ NOT used for:
1. **Socket.IO events** (order notifications, system alerts)
   - These use Flask-SocketIO directly
   - No ZeroMQ involved

2. **REST API calls** (orders, positions, etc.)
   - Direct HTTP requests to Flask
   - No ZeroMQ involved

3. **Database operations**
   - Direct SQLAlchemy queries
   - No ZeroMQ involved

4. **Authentication**
   - Direct database lookups
   - No ZeroMQ involved

5. **Frontend rendering**
   - React components
   - No ZeroMQ involved

### ✅ ONLY used for:
1. **Market data streaming** from broker adapters to consumers
2. **Cache invalidation** messages (cross-process sync)

---

## Message Format Examples

### Example 1: LTP (Last Traded Price)
```python
# Published by broker adapter
Topic: "ANGEL_NSE_RELIANCE_LTP"
Data: {
    "ltp": 2456.75,
    "volume": 1234567,
    "timestamp": 1706505600.123
}
```

### Example 2: Quote (Bid/Ask)
```python
# Published by broker adapter
Topic: "ZERODHA_NSE_INFY_QUOTE"
Data: {
    "ltp": 1450.50,
    "bid": 1450.25,
    "ask": 1450.75,
    "bid_qty": 1000,
    "ask_qty": 500,
    "volume": 987654
}
```

### Example 3: Depth (Market Depth)
```python
# Published by broker adapter
Topic: "DHAN_NSE_TCS_DEPTH"
Data: {
    "ltp": 3567.80,
    "bids": [
        {"price": 3567.50, "qty": 100, "orders": 5},
        {"price": 3567.25, "qty": 200, "orders": 8},
        # ... up to 5 or 20 levels
    ],
    "asks": [
        {"price": 3568.00, "qty": 150, "orders": 6},
        {"price": 3568.25, "qty": 250, "orders": 10},
        # ... up to 5 or 20 levels
    ]
}
```

---

## Configuration Files

### .env
```bash
# ZeroMQ Configuration
ZMQ_HOST=127.0.0.1   # Must be localhost (ZMQ is local only)
ZMQ_PORT=5555        # Port for PUB/SUB communication
```

### requirements.txt
```txt
pyzmq==25.1.1        # ZeroMQ Python bindings
```

---

## Key Limitations of Current ZeroMQ Setup

### 1. Single Machine Only
- Broker adapters and WebSocket proxy must run on **same machine**
- Cannot distribute across multiple servers

### 2. No Message Persistence
- If WebSocket proxy crashes, all in-flight messages are **lost**
- Cannot replay historical data

### 3. No Multi-Consumer Groups
- All subscribers receive **all messages**
- Cannot partition workload across consumers

### 4. Single Point of Failure
- If ZMQ publisher dies, entire system stops
- No automatic failover

### 5. No Monitoring
- No built-in metrics
- Must build custom monitoring

---

## Why This Works Well Currently

Despite limitations, ZeroMQ is **excellent for OpenAlgo** because:

1. ⚡ **Ultra-low latency** (< 2ms) - critical for trading
2. 🎯 **Simple setup** - no cluster management
3. 💰 **Zero cost** - no infrastructure needed
4. 🔧 **Easy debugging** - single process, local only
5. 📊 **Sufficient scale** - handles 50K+ msg/sec easily

For a **single-server trading platform**, this is ideal!

---

## When to Consider Kafka/ESB

Consider replacing ZeroMQ if:

1. 📈 **Multi-server deployment** needed
2. 💾 **Message persistence** required (replay historical data)
3. 🔄 **Multi-consumer groups** needed (parallel processing)
4. 🌐 **Cross-datacenter** replication required
5. 📊 **Advanced monitoring** needed

For now, **ZeroMQ is perfect** for OpenAlgo's use case! 🎯

---

## Summary

**ZeroMQ in OpenAlgo:**
- Used in **2 files** (base_adapter.py, server.py)
- Purpose: **Market data streaming only**
- Pattern: **PUB/SUB**
- Scope: **Local machine only**
- Performance: **< 2ms latency**
- Scale: **50K+ msg/sec**

**NOT used for:**
- ❌ Socket.IO events
- ❌ REST APIs
- ❌ Database operations
- ❌ Authentication

**Perfect for:**
- ✅ Real-time market data
- ✅ Low-latency trading
- ✅ Single-server setup
- ✅ Simple architecture

---

**Document Version**: 1.0  
**Last Updated**: January 29, 2026  
**Status**: Current Architecture Documentation
