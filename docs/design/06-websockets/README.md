# 06 - WebSockets Architecture

## Overview

OpenAlgo implements a unified WebSocket proxy server that handles real-time market data streaming from 24+ brokers. The architecture uses ZeroMQ for high-performance internal messaging and supports connection pooling for handling thousands of symbol subscriptions.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        WebSocket Architecture                                 │
└──────────────────────────────────────────────────────────────────────────────┘

  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐
  │ React Client  │  │ Python SDK   │  │ External Apps │
  │ useMarketData │  │ ltp_example  │  │               │
  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘
          │                  │                   │
          │  WebSocket Connection (ws://localhost:8765)
          └──────────────────┼───────────────────┘
                             │
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    WebSocket Proxy Server (:8765)                             │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    Connection Management                                │  │
│  │  clients: Dict[client_id, websocket]                                   │  │
│  │  subscriptions: Dict[client_id, Set[subscriptions]]                    │  │
│  │  user_mapping: Dict[client_id, user_id]                                │  │
│  │  broker_adapters: Dict[user_id, adapter]                               │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                               │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    Performance Optimizations                            │  │
│  │  subscription_index: Dict[(symbol,exchange,mode), Set[client_ids]]     │  │
│  │  last_message_time: Dict[(symbol,exchange,mode), timestamp]            │  │
│  │  message_throttle_interval: 50ms                                        │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
                             │
                             │ ZeroMQ (tcp://127.0.0.1:5555)
                             ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                    Broker Adapters (Connection Pool)                          │
│                                                                               │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐             │
│  │  Zerodha   │  │   Angel    │  │    Dhan    │  │   Fyers    │  ...        │
│  │  Adapter   │  │  Adapter   │  │  Adapter   │  │  Adapter   │             │
│  │            │  │            │  │            │  │            │             │
│  │ 3000 sym   │  │ 1000 sym   │  │ 1000 sym   │  │ 2000 sym   │             │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘             │
│        │               │               │               │                     │
│        └───────────────┴───────────────┴───────────────┘                     │
│                               │                                              │
│                               │ Broker WebSocket APIs                        │
│                               ▼                                              │
└──────────────────────────────────────────────────────────────────────────────┘
                               │
              ┌────────────────┴────────────────┐
              ▼                                 ▼
    ┌─────────────────┐               ┌─────────────────┐
    │ Zerodha Ticker  │               │  Angel Feed     │
    │ (Kite WebSocket)│               │  (Smart API)    │   ...
    └─────────────────┘               └─────────────────┘
```

## Core Components

### 1. WebSocket Proxy Server

**Location:** `websocket_proxy/server.py`

The central component that manages client connections, authentication, and message routing.

```python
class WebSocketProxy:
    """
    WebSocket Proxy Server that handles client connections and authentication,
    manages subscriptions, and routes market data from broker adapters to clients.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        self.host = host
        self.port = port

        # Client management
        self.clients = {}              # client_id -> websocket
        self.subscriptions = {}        # client_id -> set of subscriptions
        self.broker_adapters = {}      # user_id -> broker adapter
        self.user_mapping = {}         # client_id -> user_id
        self.user_broker_mapping = {}  # user_id -> broker_name

        # Performance: Subscription index for O(1) lookup
        self.subscription_index: Dict[Tuple[str, str, int], Set[int]] = defaultdict(set)

        # Performance: Message throttling (50ms minimum)
        self.last_message_time: Dict[Tuple[str, str, int], float] = {}
        self.message_throttle_interval = 0.05

        # ZeroMQ connection
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")
```

### 2. Broker Adapters

**Location:** `websocket_proxy/base_adapter.py`

Abstract base class for broker-specific WebSocket implementations:

```python
class BaseBrokerWebSocketAdapter(ABC):
    """
    Base class for all broker-specific WebSocket adapters that implements
    common functionality and defines the interface.
    """

    # Class variables for port management
    _bound_ports = set()
    _port_lock = threading.Lock()
    _shared_context = None

    def __init__(self, use_shared_zmq: bool = False, shared_publisher=None):
        # Initialize ZeroMQ publisher
        self.socket = self._create_socket()
        self.zmq_port = self._bind_to_available_port()

        # Subscription tracking
        self.subscriptions = {}
        self.connected = False

    @abstractmethod
    def connect(self, auth_token: str, feed_token: str = None):
        """Connect to broker WebSocket"""
        pass

    @abstractmethod
    def subscribe(self, symbols: list, mode: str = "LTP"):
        """Subscribe to symbols"""
        pass

    @abstractmethod
    def unsubscribe(self, symbols: list):
        """Unsubscribe from symbols"""
        pass
```

### 3. Connection Pooling

**Configuration:**
```python
# Environment variables
MAX_SYMBOLS_PER_WEBSOCKET = int(os.getenv('MAX_SYMBOLS_PER_WEBSOCKET', '1000'))
MAX_WEBSOCKET_CONNECTIONS = int(os.getenv('MAX_WEBSOCKET_CONNECTIONS', '3'))
ENABLE_CONNECTION_POOLING = os.getenv('ENABLE_CONNECTION_POOLING', 'true')

# Total capacity = 1000 × 3 = 3000 symbols per user
```

**Connection Pool Logic:**
```
When subscribing to symbols:
1. Check current connection's symbol count
2. If limit reached, create new connection
3. Route subscription to available connection
4. Max 3 connections × 1000 symbols = 3000 total
```

## Message Flow

### Client Authentication Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Authentication Flow                           │
└─────────────────────────────────────────────────────────────────┘

Client                  WebSocket Proxy               Database
  │                          │                           │
  │  1. Connect ws://        │                           │
  ├─────────────────────────►│                           │
  │                          │                           │
  │  2. Send: {action:       │                           │
  │     "authenticate",      │                           │
  │     api_key: "..."}      │                           │
  ├─────────────────────────►│                           │
  │                          │                           │
  │                          │  3. verify_api_key()      │
  │                          ├──────────────────────────►│
  │                          │                           │
  │                          │  4. Return user_id        │
  │                          │◄──────────────────────────┤
  │                          │                           │
  │                          │  5. Get broker from auth  │
  │                          ├──────────────────────────►│
  │                          │                           │
  │  6. {status: "success",  │◄──────────────────────────┤
  │     message: "Auth OK"}  │                           │
  │◄─────────────────────────┤                           │
  │                          │                           │
```

### Subscription Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Subscription Flow                             │
└─────────────────────────────────────────────────────────────────┘

Client                  WebSocket Proxy            Broker Adapter
  │                          │                          │
  │  1. {action: "subscribe",│                          │
  │     symbols: [{symbol:   │                          │
  │     "SBIN", exchange:    │                          │
  │     "NSE"}], mode: "LTP"}│                          │
  ├─────────────────────────►│                          │
  │                          │                          │
  │                          │  2. Get/create adapter   │
  │                          │     for user's broker    │
  │                          ├─────────────────────────►│
  │                          │                          │
  │                          │  3. Convert to broker    │
  │                          │     symbol format        │
  │                          │─────────────────────────►│
  │                          │                          │
  │                          │  4. Subscribe via        │
  │                          │     broker WebSocket     │
  │                          │                          ├─── Broker API
  │                          │                          │
  │  5. {status: "success"}  │                          │
  │◄─────────────────────────┤                          │
  │                          │                          │
```

### Data Streaming Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    Data Streaming Flow                           │
└─────────────────────────────────────────────────────────────────┘

Broker API            Broker Adapter          ZeroMQ             Proxy             Client
    │                      │                    │                  │                  │
    │  1. Market data      │                    │                  │                  │
    ├─────────────────────►│                    │                  │                  │
    │                      │                    │                  │                  │
    │                      │  2. Normalize to   │                  │                  │
    │                      │     OpenAlgo format│                  │                  │
    │                      │                    │                  │                  │
    │                      │  3. Publish        │                  │                  │
    │                      ├───────────────────►│                  │                  │
    │                      │                    │                  │                  │
    │                      │                    │  4. zmq_listener │                  │
    │                      │                    │     receives     │                  │
    │                      │                    ├─────────────────►│                  │
    │                      │                    │                  │                  │
    │                      │                    │                  │  5. Lookup       │
    │                      │                    │                  │  subscribed      │
    │                      │                    │                  │  clients         │
    │                      │                    │                  │                  │
    │                      │                    │                  │  6. Throttle     │
    │                      │                    │                  │  (50ms min)      │
    │                      │                    │                  │                  │
    │                      │                    │                  │  7. Send to      │
    │                      │                    │                  │  clients         │
    │                      │                    │                  ├─────────────────►│
    │                      │                    │                  │                  │
```

## Client Protocol

### Message Format

**Authentication:**
```json
{
  "action": "authenticate",
  "api_key": "your-api-key"
}
```

**Subscribe:**
```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "SBIN", "exchange": "NSE"},
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "NIFTY30JAN25FUT", "exchange": "NFO"}
  ],
  "mode": "LTP"  // LTP, QUOTE, or DEPTH
}
```

**Unsubscribe:**
```json
{
  "action": "unsubscribe",
  "symbols": [
    {"symbol": "SBIN", "exchange": "NSE"}
  ]
}
```

### Response Format

**Market Data (LTP):**
```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "ltp": 625.50,
  "timestamp": "2024-01-15T10:30:00+05:30"
}
```

**Market Data (QUOTE):**
```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "ltp": 625.50,
  "open": 620.00,
  "high": 628.00,
  "low": 618.50,
  "close": 622.00,
  "volume": 1500000,
  "timestamp": "2024-01-15T10:30:00+05:30"
}
```

**Market Data (DEPTH):**
```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "ltp": 625.50,
  "depth": {
    "buy": [
      {"price": 625.45, "quantity": 1000, "orders": 5},
      {"price": 625.40, "quantity": 2500, "orders": 8}
    ],
    "sell": [
      {"price": 625.50, "quantity": 800, "orders": 3},
      {"price": 625.55, "quantity": 1200, "orders": 4}
    ]
  }
}
```

## Performance Optimizations

### 1. Subscription Index (O(1) Lookup)

```python
# Instead of nested loops:
# for client_id, subs in subscriptions.items():
#     for sub in subs:
#         if matches(sub, message): ...

# Use pre-computed index:
self.subscription_index: Dict[Tuple[str, str, int], Set[int]] = defaultdict(set)

# Lookup is O(1):
key = (symbol, exchange, mode)
client_ids = self.subscription_index.get(key, set())
```

### 2. Message Throttling

```python
# Prevent spam by enforcing 50ms minimum between messages
self.message_throttle_interval = 0.05  # 50ms

current_time = time.time()
key = (symbol, exchange, mode)

if key in self.last_message_time:
    elapsed = current_time - self.last_message_time[key]
    if elapsed < self.message_throttle_interval:
        return  # Skip this message

self.last_message_time[key] = current_time
# Send message...
```

### 3. Mode Mapping Pre-computation

```python
# Pre-compute instead of string comparison each time
self.MODE_MAP = {"LTP": 1, "QUOTE": 2, "DEPTH": 3}
```

## Broker Adapter Structure

Each broker has a dedicated adapter in `broker/{broker_name}/streaming/`:

```
broker/zerodha/streaming/
├── zerodha_adapter.py         # Main adapter class
├── zerodha_websocket.py       # Kite WebSocket client
└── zerodha_mapping.py         # Data normalization

broker/angel/streaming/
├── angel_adapter.py
├── angel_websocket.py
└── angel_mapping.py
```

**Adapter Implementation Example:**
```python
class ZerodhaAdapter(BaseBrokerWebSocketAdapter):
    def connect(self, auth_token: str, feed_token: str = None):
        api_key, access_token = auth_token.split(':')
        self.kite_ws = KiteTicker(api_key, access_token)
        self.kite_ws.on_ticks = self._on_ticks
        self.kite_ws.connect()

    def subscribe(self, symbols: list, mode: str = "LTP"):
        tokens = [self._get_token(sym) for sym in symbols]
        kite_mode = self._map_mode(mode)
        self.kite_ws.subscribe(tokens)
        self.kite_ws.set_mode(kite_mode, tokens)

    def _on_ticks(self, ws, ticks):
        for tick in ticks:
            normalized = self._normalize_tick(tick)
            self._publish_to_zmq(normalized)
```

## Configuration

### Environment Variables

```bash
# WebSocket Server
WEBSOCKET_HOST=127.0.0.1
WEBSOCKET_PORT=8765

# ZeroMQ
ZMQ_HOST=127.0.0.1
ZMQ_PORT=5555

# Connection Pool
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
ENABLE_CONNECTION_POOLING=true
```

### Symbol Limits by Broker

| Broker | Max Symbols/Connection | Default Pool Size |
|--------|------------------------|-------------------|
| Zerodha | 3000 | 1 |
| Angel | 1000 | 3 |
| Dhan | 1000 | 3 |
| Fyers | 2000 | 2 |
| Others | 1000 | 3 |

## Frontend Integration

### React Hook (useMarketData)

```typescript
// hooks/useMarketData.ts
export function useMarketData(symbols: string[], mode: 'ltp' | 'quote' | 'depth') {
  const [prices, setPrices] = useState<Record<string, MarketData>>({})
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    // Get WebSocket config
    const config = await fetch('/api/websocket/config')
    const apiKey = await fetch('/api/websocket/apikey')

    // Connect
    wsRef.current = new WebSocket(config.url)

    wsRef.current.onopen = () => {
      // Authenticate
      wsRef.current.send(JSON.stringify({
        action: 'authenticate',
        api_key: apiKey
      }))
    }

    wsRef.current.onmessage = (event) => {
      const data = JSON.parse(event.data)
      if (data.status === 'authenticated') {
        // Subscribe to symbols
        wsRef.current.send(JSON.stringify({
          action: 'subscribe',
          symbols,
          mode
        }))
      } else if (data.ltp) {
        setPrices(prev => ({...prev, [data.symbol]: data}))
      }
    }

    return () => wsRef.current?.close()
  }, [symbols, mode])

  return prices
}
```

## websocket_proxy/ Directory Structure

```
websocket_proxy/
├── server.py              # WebSocketProxy class - main server
├── base_adapter.py        # BaseBrokerWebSocketAdapter ABC
├── broker_factory.py      # Creates broker-specific adapters
├── connection_manager.py  # Connection pool management
└── app_integration.py     # Flask app integration
```

### App Integration (app_integration.py)

The WebSocket server runs as a **daemon thread** inside the main Flask application:

```python
# Called from app.py on startup
start_websocket_proxy(app)

# Lifecycle:
# 1. Check if should start (skip in Flask debug parent process)
# 2. Start WebSocket server in daemon thread
# 3. Register cleanup handlers for SIGINT/SIGTERM
# 4. WebSocket runs on port 8765 alongside Flask on port 5000
```

**Key Points:**
- No separate service needed - WebSocket runs inside main process
- Single worker (`-w 1`) required for Gunicorn
- Thread automatically cleans up on application shutdown
- ZeroMQ context shared for message routing

## Key Files Reference

| File | Purpose |
|------|---------|
| `websocket_proxy/server.py` | Main WebSocket proxy server (port 8765) |
| `websocket_proxy/base_adapter.py` | Base class for broker adapters |
| `websocket_proxy/broker_factory.py` | Creates broker-specific adapters |
| `websocket_proxy/connection_manager.py` | Connection pool management |
| `websocket_proxy/app_integration.py` | Flask app integration (thread management) |
| `broker/*/streaming/*_adapter.py` | Broker-specific implementations |
| `frontend/src/hooks/useMarketData.ts` | React WebSocket hook |
