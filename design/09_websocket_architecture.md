# WebSocket Architecture

OpenAlgo implements a dual-channel WebSocket architecture with Flask-SocketIO for UI integration and a native WebSocket proxy for high-performance market data streaming, connected via ZeroMQ message bus.

## Architecture Overview

```
+------------------+     +------------------+     +------------------+
|   Web Browser    |     | Trading Client   |     |  Python Script   |
|   (Socket.IO)    |     |   (WebSocket)    |     |   (WebSocket)    |
+--------+---------+     +--------+---------+     +--------+---------+
         |                        |                        |
         v                        v                        v
+------------------+     +----------------------------------------+
| Flask-SocketIO   |     |         WebSocket Proxy Server         |
| Port 5000        |     |              Port 8765                 |
| (UI Events)      |     |         (Market Data Streaming)        |
+--------+---------+     +-------------------+--------------------+
         |                                   |
         |                                   v
         |               +----------------------------------------+
         |               |           ZeroMQ Message Bus            |
         |               |              Port 5555                  |
         |               +-------------------+--------------------+
         |                                   |
         |                                   v
         |               +----------------------------------------+
         |               |         Broker Adapter Factory          |
         |               +-------------------+--------------------+
         |                                   |
         v                                   v
+--------+---------+     +------------------+---------------------+
|   REST API       |     |              Broker Adapters           |
| (Order Execution)|     | Angel | Zerodha | Upstox | Dhan | ...  |
+------------------+     +----------------------------------------+
                                            |
                                            v
                         +----------------------------------------+
                         |        External Broker WebSockets       |
                         +----------------------------------------+
```

## Dual WebSocket Channels

### Channel 1: Flask-SocketIO (Port 5000)

UI integration and event-driven communication:

```python
# extensions.py
from flask_socketio import SocketIO

socketio = SocketIO(
    cors_allowed_origins='*',
    async_mode='threading',
    ping_timeout=10,
    ping_interval=5,
    logger=False,
    engineio_logger=False
)
```

**Configuration:**
- Threading mode (not eventlet) to avoid greenlet errors
- CORS enabled for all origins
- Ping/pong heartbeat: 5-second interval, 10-second timeout

### Channel 2: Native WebSocket Proxy (Port 8765)

High-performance market data streaming:

```python
# websocket_proxy/server.py
import asyncio
import websockets

class WebSocketProxy:
    async def start_server(self):
        server = await websockets.serve(
            self.handle_client,
            host=os.getenv('WEBSOCKET_HOST', '127.0.0.1'),
            port=int(os.getenv('WEBSOCKET_PORT', 8765))
        )
```

## ZeroMQ Message Bus

Internal communication between broker adapters and WebSocket proxy:

### Publisher (Broker Adapters)

```python
# websocket_proxy/base_adapter.py
import zmq

class BaseBrokerWebSocketAdapter:
    def __init__(self):
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.SNDHWM, 1000)  # High water mark
        self.socket.setsockopt(zmq.LINGER, 1000)  # 1 second linger
        self.socket.bind(f"tcp://*:{ZMQ_PORT}")

    def publish_market_data(self, topic: str, data: dict):
        """Publish market data to ZeroMQ subscribers"""
        self.socket.send_multipart([
            topic.encode('utf-8'),
            json.dumps(data).encode('utf-8')
        ])
```

### Subscriber (WebSocket Proxy)

```python
# websocket_proxy/server.py
class WebSocketProxy:
    def __init__(self):
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all
```

## Data Flow

```
Broker WebSocket
       |
       v
+------------------+
| Broker Adapter   |
| (Transform Data) |
+--------+---------+
         |
         v
+------------------+
| ZeroMQ Publisher |
| Topic: broker_   |
| exchange_symbol_ |
| mode             |
+--------+---------+
         |
         v
+------------------+
| ZeroMQ Subscriber|
| (WebSocket Proxy)|
+--------+---------+
         |
         v
+------------------+
| Subscription     |
| Index Lookup     |
| O(1) routing     |
+--------+---------+
         |
         v
+------------------+
| WebSocket Clients|
| (Broadcast)      |
+------------------+
```

## Topic Format

Market data topics follow a standardized format:

```
BROKER_EXCHANGE_SYMBOL_MODE
```

**Examples:**
- `zerodha_NSE_RELIANCE_QUOTE`
- `angel_NFO_NIFTY24DEC19500CE_LTP`
- `dhan_NSE_INDEX_NIFTY_50_DEPTH`

**Special Cases:**
```python
# NSE_INDEX and BSE_INDEX have underscores
if parts[0] == "NSE" and parts[1] == "INDEX":
    exchange = "NSE_INDEX"
    symbol = parts[2]
    mode_str = parts[3]
```

## Subscription Modes

| Mode | Value | Data Included | Throttle |
|------|-------|---------------|----------|
| LTP | 1 | Last traded price only | 50ms |
| Quote | 2 | Bid/ask, OHLC, volume | None |
| Depth | 3 | Full market depth (5/20/30 levels) | None |

## Client Connection Management

### State Management

```python
class WebSocketProxy:
    def __init__(self):
        self.clients = {}           # client_id -> websocket
        self.subscriptions = {}     # client_id -> set of subscriptions
        self.user_mapping = {}      # client_id -> user_id
        self.broker_adapters = {}   # user_id -> broker adapter
        self.subscription_index = defaultdict(set)  # (symbol, exchange, mode) -> set(client_ids)
```

### Connection Lifecycle

```python
async def handle_client(self, websocket, path):
    client_id = id(websocket)
    self.clients[client_id] = websocket

    try:
        async for message in websocket:
            await self.process_message(client_id, message)
    finally:
        await self.cleanup_client(client_id)
```

### Subscription Index (O(1) Lookup)

```python
# Optimized routing using subscription index
subscription_index: Dict[Tuple[str, str, int], Set[int]] = defaultdict(set)

# Adding subscription
sub_key = (symbol, exchange, mode)
subscription_index[sub_key].add(client_id)

# Fast lookup during broadcast
def get_subscribed_clients(symbol, exchange, mode):
    return subscription_index.get((symbol, exchange, mode), set())
```

## WebSocket Protocol

### Authentication

```json
{
    "action": "authenticate",
    "api_key": "your-openalgo-api-key"
}
```

**Response:**
```json
{
    "type": "auth_response",
    "status": "success",
    "message": "Authentication successful"
}
```

### Subscribe

```json
{
    "action": "subscribe",
    "symbols": [
        {"symbol": "RELIANCE", "exchange": "NSE"},
        {"symbol": "TCS", "exchange": "NSE"}
    ],
    "mode": "Quote"
}
```

### Unsubscribe

```json
{
    "action": "unsubscribe",
    "symbols": [
        {"symbol": "RELIANCE", "exchange": "NSE"}
    ]
}
```

### Market Data Response

```json
{
    "type": "market_data",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "mode": 2,
    "data": {
        "ltp": 2850.50,
        "open": 2820.00,
        "high": 2860.00,
        "low": 2815.00,
        "close": 2848.25,
        "volume": 1500000,
        "bid": 2850.45,
        "ask": 2850.55,
        "bid_qty": 500,
        "ask_qty": 750
    }
}
```

## Broker Adapter Pattern

### Base Adapter

```python
# websocket_proxy/base_adapter.py
from abc import ABC, abstractmethod

class BaseBrokerWebSocketAdapter(ABC):

    @abstractmethod
    def initialize(self, broker_name: str, user_id: str, auth_data: dict = None):
        """Initialize with broker credentials"""
        pass

    @abstractmethod
    def connect(self):
        """Establish connection to broker WebSocket"""
        pass

    @abstractmethod
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5):
        """Subscribe to market data"""
        pass

    @abstractmethod
    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2):
        """Unsubscribe from market data"""
        pass

    @abstractmethod
    def disconnect(self):
        """Disconnect from broker"""
        pass

    def publish_market_data(self, topic: str, data: dict):
        """Publish to ZeroMQ (implemented in base)"""
        pass
```

### Broker Factory

```python
# websocket_proxy/broker_factory.py
def create_broker_adapter(broker_name: str) -> BaseBrokerWebSocketAdapter:
    """Create broker-specific adapter dynamically"""

    # Import from broker-specific directory
    module_name = f"broker.{broker_name}.streaming.{broker_name}_adapter"
    class_name = f"{broker_name.capitalize()}WebSocketAdapter"

    module = importlib.import_module(module_name)
    adapter_class = getattr(module, class_name)
    return adapter_class()
```

### Example: Zerodha Adapter

```python
# broker/zerodha/streaming/zerodha_adapter.py
class ZerodhaWebSocketAdapter(BaseBrokerWebSocketAdapter):

    def connect(self):
        self.kws = KiteTicker(api_key, access_token)
        self.kws.on_ticks = self._handle_ticks
        self.kws.connect(threaded=True)

    def _handle_ticks(self, ticks: List[Dict]):
        for tick in ticks:
            transformed = self._transform_tick(tick)
            topic = self._generate_topic(symbol, exchange, mode)
            self.publish_market_data(topic, transformed)

    def _transform_tick(self, tick: dict) -> dict:
        """Transform Zerodha tick to standard format"""
        return {
            'ltp': tick.get('last_price'),
            'open': tick.get('ohlc', {}).get('open'),
            'high': tick.get('ohlc', {}).get('high'),
            'low': tick.get('ohlc', {}).get('low'),
            'close': tick.get('ohlc', {}).get('close'),
            'volume': tick.get('volume_traded')
        }
```

## Flask-SocketIO Events

### Market Namespace (/market)

```python
# blueprints/websocket_example.py
@socketio.on('connect', namespace='/market')
def handle_connect():
    """Client connected"""
    emit('connected', {'status': 'ok'})

@socketio.on('subscribe', namespace='/market')
def handle_subscribe(data):
    """Subscribe to market data via REST API"""
    symbols = data.get('symbols', [])
    mode = data.get('mode', 'Quote')
    # Proxies to WebSocket server

@socketio.on('get_ltp', namespace='/market')
def handle_get_ltp(data):
    """Poll current LTP"""
    symbol = data.get('symbol')
    exchange = data.get('exchange')
    # Returns cached LTP

@socketio.on('get_quote', namespace='/market')
def handle_get_quote(data):
    """Poll quote data"""
    pass

@socketio.on('get_depth', namespace='/market')
def handle_get_depth(data):
    """Poll market depth"""
    pass
```

## Performance Optimizations

### Message Throttling

```python
# LTP mode: 50ms minimum between updates
last_message_time = {}

async def should_send_update(symbol, exchange, mode):
    if mode != 1:  # LTP mode
        return True

    key = (symbol, exchange)
    now = time.time()
    last = last_message_time.get(key, 0)

    if now - last >= 0.05:  # 50ms
        last_message_time[key] = now
        return True
    return False
```

### Batch Broadcasting

```python
async def broadcast_to_clients(client_ids: Set[int], message: str):
    """Batch send to multiple clients"""
    tasks = []
    for client_id in client_ids:
        ws = self.clients.get(client_id)
        if ws:
            tasks.append(ws.send(message))

    await asyncio.gather(*tasks, return_exceptions=True)
```

### ZeroMQ High Water Mark

```python
# Prevent memory exhaustion on slow consumers
self.socket.setsockopt(zmq.SNDHWM, 1000)  # 1000 messages max buffer
self.socket.setsockopt(zmq.RCVHWM, 1000)
```

## Configuration

### Environment Variables

```bash
# WebSocket Server
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765
WEBSOCKET_URL=ws://127.0.0.1:8765

# ZeroMQ
ZMQ_HOST=127.0.0.1
ZMQ_PORT=5555
```

### Production Configuration

```bash
# Production with TLS
WEBSOCKET_URL=wss://yourdomain.com:8765
```

## Error Handling

### Connection Errors

```python
async def handle_client(self, websocket, path):
    try:
        async for message in websocket:
            await self.process_message(client_id, message)
    except websockets.exceptions.ConnectionClosed:
        logger.info(f"Client {client_id} disconnected")
    except Exception as e:
        logger.error(f"Error handling client: {e}")
    finally:
        await self.cleanup_client(client_id)
```

### Broker-Specific Cleanup

```python
async def cleanup_client(self, client_id):
    """Clean up when client disconnects"""
    user_id = self.user_mapping.get(client_id)
    adapter = self.broker_adapters.get(user_id)

    if adapter:
        broker_name = adapter.broker_name
        # Special handling for persistent connections
        if broker_name in ['flattrade', 'shoonya']:
            adapter.unsubscribe_all()  # Keep connection alive
        else:
            adapter.disconnect()  # Full disconnect
```

### Socket.IO Error Handler

```python
# utils/socketio_error_handler.py
def init_socketio_error_handling(socketio_instance):
    @socketio_instance.on_error_default
    def default_error_handler(e):
        if "Session is disconnected" in str(e):
            logger.debug(f"Socket.IO session disconnected")
            return False
        logger.error(f"Socket.IO error: {e}")
```

## Client SDK

### Python Client

```python
# services/websocket_client.py
class OpenAlgoWebSocketClient:
    """Singleton WebSocket client with auto-reconnection"""

    def __init__(self, api_key: str, ws_url: str = None):
        self.api_key = api_key
        self.ws_url = ws_url or os.getenv('WEBSOCKET_URL')
        self.ws = None
        self.callbacks = {}
        self.subscriptions = set()
        self.market_data_cache = {}
        self._reconnect_attempts = 0
        self._max_reconnects = 5

    async def connect(self):
        """Connect with exponential backoff"""
        pass

    async def subscribe(self, symbols: List[dict], mode: str = 'Quote'):
        """Subscribe to market data"""
        pass

    def on_tick(self, callback: Callable):
        """Register tick callback"""
        self.callbacks['tick'] = callback
```

## Performance Metrics

| Metric | Value |
|--------|-------|
| LTP Updates | 20/second (50ms throttle) |
| Quote/Depth Updates | Unlimited |
| Max Clients | 1000+ per adapter |
| Subscription Lookup | O(1) |
| ZeroMQ Buffer | 1000 messages |
| Reconnect Backoff | Exponential (max 5 attempts) |

## Related Documentation

- [Configuration](./07_configuration.md) - WebSocket configuration options
- [Broker Integration](./03_broker_integration.md) - Broker adapter details
- [API Layer](./02_api_layer.md) - REST API for market data
- [Utilities](./08_utilities.md) - Error handling utilities
