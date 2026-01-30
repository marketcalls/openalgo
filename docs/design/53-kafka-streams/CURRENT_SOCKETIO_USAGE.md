# Communication Framework for Orders, Execution & Notifications in OpenAlgo

## Overview

OpenAlgo uses **Flask-SocketIO** (with threading mode) for **ALL order notifications, execution updates, and system alerts**. This is completely separate from ZeroMQ which is only used for market data streaming.

---

## Communication Framework: Flask-SocketIO

### Location & Configuration

**File**: `extensions.py`

```python
from flask_socketio import SocketIO

socketio = SocketIO(
    cors_allowed_origins="*",
    async_mode="threading",  # Uses threading (not eventlet/gevent)
    ping_timeout=10,          # 10 seconds before connection timeout
    ping_interval=5,          # 5 seconds between pings
    logger=False,             # Disable verbose logging
    engineio_logger=False
)
```

### Technology Stack
- **Protocol**: Socket.IO over HTTP Long-Polling
- **Transport**: HTTP (WebSocket is disabled)
- **Mode**: Threading-based (no greenlets/eventlet)
- **CORS**: Open to all origins

---

## How Orders Work: Complete Flow

### 1. Order Placement (Frontend → Backend)

```
Frontend (React/HTML)
    ↓ HTTP POST
Flask REST API (/api/v1/placeorder)
    ↓
place_smart_order_service.py
    ↓
Broker API (Angel/Zerodha/etc.)
    ↓
Order Placed ✓
```

**Example API Call**:
```bash
curl -X POST http://localhost:5000/api/v1/placeorder \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "strategy": "my-strategy",
    "symbol": "SBIN-EQ",
    "action": "BUY",
    "exchange": "NSE",
    "pricetype": "MARKET",
    "product": "MIS",
    "quantity": "1"
  }'
```

---

### 2. Order Notification (Backend → Frontend)

**After successful order placement, notifications are sent via Socket.IO**

#### Implementation in `place_smart_order_service.py`

```python
from extensions import socketio

# After order is placed successfully
if res and res.status == 200:
    order_response_data = {
        "status": "success", 
        "orderid": order_id
    }
    
    # Emit Socket.IO event asynchronously
    socketio.start_background_task(
        socketio.emit,
        "order_event",  # Event name
        {               # Event data
            "symbol": order_data.get("symbol"),
            "action": order_data.get("action"),
            "orderid": order_id,
            "mode": "live"
        }
    )
```

---

### 3. Frontend Receives Notification

**File**: `frontend/src/hooks/useSocket.ts` (if React) or inline JavaScript

```javascript
// Connect to Socket.IO
const socket = io('http://localhost:5000');

// Listen for order events
socket.on('order_event', (data) => {
    console.log('Order placed:', data);
    // data = {
    //   symbol: "SBIN-EQ",
    //   action: "BUY",
    //   orderid: "ORD123456",
    //   mode: "live"
    // }
    
    // Show toast notification
    toast.success(`Order placed: ${data.symbol} ${data.action}`);
});
```

---

## Complete Message Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    FRONTEND (React/HTML)                     │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  1. User clicks "Place Order" button                  │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │ HTTP POST
                             │ /api/v1/placeorder
                             │
┌────────────────────────────▼────────────────────────────────┐
│               FLASK BACKEND (app.py)                         │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  2. REST API Endpoint receives order request          │  │
│  │     Route: /api/v1/placeorder                         │  │
│  │     Blueprint: orders_bp                              │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
                             │ Call service
                             │
┌────────────────────────────▼────────────────────────────────┐
│         PLACE ORDER SERVICE (place_smart_order_service.py)   │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  3. Validate order parameters                         │  │
│  │  4. Get auth token for user                           │  │
│  │  5. Call broker API to place order                    │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
                             │ HTTP API Call
                             │
┌────────────────────────────▼────────────────────────────────┐
│          BROKER API (Angel/Zerodha/Dhan/etc.)                │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  6. Order placed in exchange                          │  │
│  │  7. Returns order ID                                  │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
                             │ Success Response
                             │
┌────────────────────────────▼────────────────────────────────┐
│         PLACE ORDER SERVICE (Continued)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  8. Log order to database                             │  │
│  │  9. Send Telegram alert (if configured)              │  │
│  │  10. EMIT SOCKET.IO EVENT ← KEY STEP                 │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
                             │ Socket.IO Event
                             │ Event: "order_event"
                             │
┌────────────────────────────▼────────────────────────────────┐
│               SOCKET.IO SERVER (extensions.py)               │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  11. Broadcasts event to all connected clients        │  │
│  │      Transport: HTTP Long-Polling                     │  │
│  └───────────────────────┬───────────────────────────────┘  │
└────────────────────────────┼────────────────────────────────┘
                             │
                             │ HTTP Polling
                             │
┌────────────────────────────▼────────────────────────────────┐
│                    FRONTEND (Continued)                      │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  12. Socket.IO client receives event                  │  │
│  │  13. Shows toast notification                         │  │
│  │  14. Updates order list                               │  │
│  └───────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

---

## Socket.IO Event Types in OpenAlgo

### 1. Order Events

**Event Name**: `order_event`

**Emitted When**: Order placed, modified, or cancelled

**Data Format**:
```json
{
  "symbol": "SBIN-EQ",
  "action": "BUY",
  "orderid": "ORD123456",
  "mode": "live"
}
```

**Frontend Listener**:
```javascript
socket.on('order_event', (data) => {
    console.log('Order event:', data);
    updateOrderList(data);
});
```

---

### 2. Analyzer Updates (Sandbox Mode)

**Event Name**: `analyzer_update`

**Emitted When**: Order placed in sandbox/analyzer mode

**Data Format**:
```json
{
  "request": {
    "symbol": "RELIANCE-EQ",
    "action": "BUY",
    "quantity": "1",
    "api_type": "placesmartorder"
  },
  "response": {
    "mode": "analyze",
    "status": "success",
    "orderid": "SANDBOX_ORD_123"
  }
}
```

**Code Location**: `place_smart_order_service.py`
```python
# Emit analyzer update
socketio.start_background_task(
    socketio.emit,
    "analyzer_update",
    {
        "request": analyzer_request,
        "response": response_data
    }
)
```

---

### 3. Order Notifications

**Event Name**: `order_notification`

**Emitted When**: Position already matched (no action needed)

**Data Format**:
```json
{
  "symbol": "INFY-EQ",
  "status": "info",
  "message": "Positions Already Matched. No Action needed."
}
```

---

### 4. Master Contract Download

**Event Name**: `master_contract_download`

**Emitted When**: Master contract download completes

**Code Location**: `blueprints/master_contract_status.py`

```python
from extensions import socketio

socketio.emit('master_contract_download', {
    'broker': broker_name,
    'status': 'success',
    'message': 'Master contract downloaded successfully'
})
```

---

### 5. Password Change Notification

**Event Name**: `password_change`

**Emitted When**: User changes password

**Code Location**: `blueprints/auth.py`

```python
socketio.emit('password_change', {
    'user': username,
    'status': 'success',
    'message': 'Password changed successfully'
})
```

---

## Comparison: Socket.IO vs ZeroMQ

| Aspect | Socket.IO (Orders/Events) | ZeroMQ (Market Data) |
|--------|---------------------------|---------------------|
| **Purpose** | Order notifications, system alerts | Market data streaming |
| **Protocol** | HTTP Long-Polling | TCP PUB/SUB |
| **Direction** | Backend → Frontend | Broker Adapters → Consumers |
| **Latency** | 50-200ms (acceptable for notifications) | < 2ms (critical for trading) |
| **Reliability** | Guaranteed delivery (HTTP) | Best-effort (UDP-like) |
| **Message Types** | Order events, alerts, notifications | LTP, Quote, Depth |
| **Clients** | Web browsers (React/HTML) | Python SDK, WebSocket Proxy |
| **Transport** | HTTP (WebSocket disabled) | Raw TCP |
| **Scale** | 100s of clients | 1000s of messages/sec |

---

## Why Two Different Systems?

### Socket.IO for Orders & Notifications ✅

**Reasons**:
1. **Browser Compatibility**: Works in all browsers without special setup
2. **Reliability**: HTTP ensures message delivery
3. **Simplicity**: Easy to integrate with React/frontend
4. **Low Frequency**: Orders are infrequent (1-10 per minute)
5. **Bidirectional**: Frontend can send and receive messages

**Trade-offs**:
- ❌ Higher latency (50-200ms) - acceptable for notifications
- ❌ More overhead - HTTP headers, JSON serialization

---

### ZeroMQ for Market Data ✅

**Reasons**:
1. **Ultra-Low Latency**: < 2ms critical for real-time market data
2. **High Throughput**: 50K+ messages/sec
3. **Efficient**: Binary protocol, no HTTP overhead
4. **Topic-based**: Easy filtering by symbol/exchange
5. **One-way**: Broker → Clients (no bidirectional needed)

**Trade-offs**:
- ❌ No browser support - requires proxy
- ❌ No guaranteed delivery - messages lost if subscriber offline
- ❌ Local only - cannot cross servers

---

## Key Code Locations

### Socket.IO Configuration
- **File**: `extensions.py`
- **Initialization**: `socketio = SocketIO(...)`

### Socket.IO Usage in Services
- **File**: `services/place_smart_order_service.py`
- **Pattern**: `socketio.start_background_task(socketio.emit, event_name, data)`

### Socket.IO in Blueprints
- `blueprints/orders.py` - Order events
- `blueprints/auth.py` - Password changes
- `blueprints/master_contract_status.py` - Download events
- `blueprints/analyzer.py` - Analyzer updates

### Frontend Socket.IO Client
- **File**: `frontend/src/hooks/useSocket.ts` (if React)
- **Pattern**: `socket.on(event_name, callback)`

---

## Asynchronous Event Emission Pattern

### Why Background Tasks?

```python
# DON'T DO THIS (blocks the request)
socketio.emit('order_event', data)
response = {"status": "success"}
return response

# DO THIS (non-blocking)
socketio.start_background_task(
    socketio.emit,
    'order_event',
    data
)
response = {"status": "success"}
return response  # Returns immediately
```

**Benefits**:
1. ✅ API responds faster (doesn't wait for Socket.IO broadcast)
2. ✅ No blocking if Socket.IO client is slow
3. ✅ Better concurrency under load

---

## How Socket.IO Differs from WebSockets

### Socket.IO (Used in OpenAlgo)
```
Client ←→ Server
    ↓
HTTP Long-Polling (default)
- Client polls server every few seconds
- Server holds connection until data available
- Falls back if WebSocket unavailable
```

### WebSockets (NOT used for orders)
```
Client ←═══════════════════════════╗
         Persistent Connection      ║
Server ═════════════════════════════╝

- Single long-lived connection
- True bidirectional
- Lower latency
- OpenAlgo DOES use WebSocket for market data proxy (port 8765)
```

---

## Order Execution Flow: Step-by-Step

### Step 1: User Places Order
```javascript
// Frontend
fetch('/api/v1/placeorder', {
    method: 'POST',
    body: JSON.stringify({
        apikey: 'xxx',
        symbol: 'SBIN-EQ',
        action: 'BUY',
        quantity: '1'
    })
})
```

### Step 2: Backend Receives & Validates
```python
# orders_bp blueprint
@orders_bp.route('/api/v1/placeorder', methods=['POST'])
def place_order():
    data = request.get_json()
    api_key = data.get('apikey')
    
    # Call service
    success, response, status = place_smart_order(
        order_data=data,
        api_key=api_key
    )
    
    return jsonify(response), status
```

### Step 3: Service Places Order
```python
# place_smart_order_service.py
def place_smart_order_with_auth(order_data, auth_token, broker, ...):
    # Call broker API
    res, response_data, order_id = broker_module.place_smartorder_api(
        order_data, 
        auth_token
    )
    
    # If success, emit Socket.IO event
    if res and res.status == 200:
        socketio.start_background_task(
            socketio.emit,
            "order_event",
            {
                "symbol": order_data.get("symbol"),
                "action": order_data.get("action"),
                "orderid": order_id,
                "mode": "live"
            }
        )
    
    return True, response_data, 200
```

### Step 4: Frontend Receives Notification
```javascript
// Socket.IO client
socket.on('order_event', (data) => {
    // Update UI
    toast.success(`✓ ${data.action} order placed: ${data.symbol}`);
    
    // Refresh order list
    fetchOrderBook();
});
```

---

## Configuration in app.py

### Socket.IO Initialization

```python
from flask import Flask
from extensions import socketio

app = Flask(__name__)

# Register blueprints
app.register_blueprint(orders_bp)
app.register_blueprint(auth_bp)
# ... other blueprints

# Initialize Socket.IO with Flask app
socketio.init_app(app)

# Run app with Socket.IO
if __name__ == '__main__':
    socketio.run(
        app,
        host='0.0.0.0',
        port=5000,
        debug=False
    )
```

---

## Testing Socket.IO Events

### Test with Python Client

```python
import socketio

# Create Socket.IO client
sio = socketio.Client()

# Connect to server
sio.connect('http://localhost:5000')

# Listen for events
@sio.on('order_event')
def on_order_event(data):
    print(f"Order event received: {data}")

@sio.on('analyzer_update')
def on_analyzer_update(data):
    print(f"Analyzer update: {data}")

# Keep alive
sio.wait()
```

### Test with JavaScript (Browser Console)

```javascript
// Connect
const socket = io('http://localhost:5000');

// Listen for all events
socket.onAny((eventName, data) => {
    console.log(`Event: ${eventName}`, data);
});

// Specific listeners
socket.on('order_event', (data) => {
    console.log('Order:', data);
});

socket.on('analyzer_update', (data) => {
    console.log('Analyzer:', data);
});
```

---

## Summary

### Communication Framework for Orders & Notifications

**Technology**: Flask-SocketIO (HTTP Long-Polling)

**Used For**:
- ✅ Order placement notifications
- ✅ Order execution updates
- ✅ System alerts (password change, download complete)
- ✅ Analyzer mode updates (sandbox)
- ✅ General toast notifications

**NOT Used For**:
- ❌ Market data streaming (uses ZeroMQ)
- ❌ REST API calls (direct HTTP)
- ❌ WebSocket market data (separate WebSocket server on port 8765)

**Key Files**:
- `extensions.py` - Socket.IO initialization
- `services/place_smart_order_service.py` - Order event emissions
- `blueprints/*` - Various event emissions
- `frontend/src/hooks/useSocket.ts` - Frontend listener

**Performance**:
- Latency: 50-200ms (acceptable for notifications)
- Frequency: Low (1-10 events/minute)
- Reliability: High (HTTP guaranteed delivery)

---

**Document Version**: 1.0  
**Last Updated**: January 29, 2026  
**Status**: Current Architecture Documentation
