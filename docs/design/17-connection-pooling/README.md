# 17 - Connection Pooling

## Overview

OpenAlgo implements connection pooling for WebSocket symbol subscriptions to optimize performance and manage broker API limits. The system uses `ConnectionPool` with a `SharedZmqPublisher` singleton to handle multiple WebSocket connections per broker, aggregating data through ZeroMQ for unified distribution.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Connection Pooling Architecture                        │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      ConnectionPool (per broker/user)                        │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Configuration:                                                      │   │
│  │  MAX_SYMBOLS_PER_WEBSOCKET = 1000 (default)                         │   │
│  │  MAX_WEBSOCKET_CONNECTIONS = 3 (default)                            │   │
│  │  Total capacity: 3000 symbols per user                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │  Adapter 0    │  │  Adapter 1    │  │  Adapter 2    │                   │
│  │  1000 symbols │  │  1000 symbols │  │  1000 symbols │                   │
│  │               │  │               │  │               │                   │
│  │  SBIN, INFY,  │  │  TCS, WIPRO,  │  │  NIFTY opts,  │                   │
│  │  RELIANCE...  │  │  HDFC...      │  │  BANKNIFTY... │                   │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘                   │
│          │                  │                  │                            │
│          └──────────────────┼──────────────────┘                            │
│                             │                                                │
│                             ▼                                                │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                   SharedZmqPublisher (Singleton)                     │   │
│  │                   Binds to ZMQ_PORT (default: 5555)                  │   │
│  │                   Thread-safe publish with _publish_lock             │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
                                     │
                                     │ ZeroMQ PUB/SUB
                                     ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                      WebSocketProxy (server.py)                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  ZeroMQ SUB socket connects to ZMQ_PORT                             │   │
│  │  Routes data to WebSocket clients (port 8765)                       │   │
│  │  O(1) subscription lookup via subscription_index                    │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Configuration

```bash
# .env
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
ZMQ_PORT=5555
```

## Core Components

### 1. SharedZmqPublisher (Singleton)

**Location:** `websocket_proxy/connection_manager.py`

Ensures all adapter connections publish to the same ZeroMQ socket:

```python
class SharedZmqPublisher:
    """
    Shared ZeroMQ publisher that can be used by multiple adapter instances.
    Ensures all connections publish to the same ZeroMQ socket, so the WebSocketProxy
    receives data from all connections on a single port.
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern to ensure only one shared publisher exists"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.PUB)
        self.socket.setsockopt(zmq.LINGER, 1000)
        self.socket.setsockopt(zmq.SNDHWM, 1000)
        self.zmq_port = None
        self._bound = False
        self._publish_lock = threading.Lock()

    def bind(self, port: int | None = None) -> int:
        """Bind to ZMQ port. If already bound, returns existing port."""
        # Auto-finds available port starting from ZMQ_PORT env var
        pass

    def publish(self, topic: str, data: dict):
        """Thread-safe publishing to ZeroMQ subscribers."""
        with self._publish_lock:
            self.socket.send_multipart([
                topic.encode("utf-8"),
                json.dumps(data).encode("utf-8")
            ])

    def cleanup(self):
        """Clean up ZeroMQ resources"""
        pass
```

### 2. ConnectionPool

**Location:** `websocket_proxy/connection_manager.py`

Manages multiple WebSocket connections for a single broker/user:

```python
class ConnectionPool:
    """
    Manages multiple WebSocket connections for a single broker/user.

    Automatically creates new connections when symbol limits are reached,
    up to the configured maximum. Distributes subscriptions across connections
    and aggregates data through a shared ZeroMQ publisher.
    """

    def __init__(
        self,
        adapter_class: type,
        broker_name: str,
        user_id: str,
        max_symbols_per_connection: int | None = None,
        max_connections: int | None = None,
    ):
        self.adapter_class = adapter_class
        self.broker_name = broker_name
        self.user_id = user_id
        self.max_symbols = max_symbols_per_connection or get_max_symbols_per_websocket()
        self.max_connections = max_connections or get_max_websocket_connections()

        self.lock = threading.RLock()

        # Connection tracking
        self.adapters: list[Any] = []  # List of adapter instances
        self.adapter_symbol_counts: list[int] = []  # Symbols per adapter

        # Subscription tracking: (symbol, exchange, mode) -> adapter_index
        self.subscription_map: dict[tuple[str, str, int], int] = {}

        # Shared ZeroMQ publisher (singleton)
        self.shared_publisher = SharedZmqPublisher()

        # Peak usage tracking (for logging)
        self.peak_total_symbols = 0
        self.peak_connections_used = 0
```

### Key Methods

```python
def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5) -> dict:
    """
    Subscribe to market data, automatically using connection with capacity.

    Returns:
        {
            "status": "success",
            "connection": 1,  # Which connection (1-indexed)
            "total_connections": 2,
            "symbols_on_connection": 500
        }
    """
    sub_key = (symbol, exchange, mode)

    with self.lock:
        # Check if already subscribed
        if sub_key in self.subscription_map:
            return {"status": "success", "message": f"Already subscribed"}

        # Get adapter with capacity (creates new if needed)
        adapter_idx, adapter = self._get_adapter_with_capacity()

        # Subscribe and track
        result = adapter.subscribe(symbol, exchange, mode, depth_level)

        if result.get("status") == "success":
            self.subscription_map[sub_key] = adapter_idx
            self.adapter_symbol_counts[adapter_idx] += 1

        return result

def _get_adapter_with_capacity(self) -> tuple[int, Any]:
    """Get an adapter with available capacity, or create a new one."""
    # Find existing adapter with capacity
    for idx, count in enumerate(self.adapter_symbol_counts):
        if count < self.max_symbols:
            return idx, self.adapters[idx]

    # Check if we can create a new adapter
    if len(self.adapters) >= self.max_connections:
        raise RuntimeError(
            f"Maximum capacity reached: {self.max_connections} connections × "
            f"{self.max_symbols} symbols = {self.max_connections * self.max_symbols}"
        )

    # Create new adapter with shared publisher
    adapter = self._create_adapter()
    adapter.initialize(self.broker_name, self.user_id)
    adapter.connect()

    self.adapters.append(adapter)
    self.adapter_symbol_counts.append(0)

    return len(self.adapters) - 1, adapter
```

### 3. Thread-Local Context for Pooled Adapters

```python
# Thread-local storage for pooled adapter creation context
_pooled_creation_context = threading.local()

def is_pooled_creation() -> bool:
    """Check if we're currently creating an adapter within a ConnectionPool"""
    return getattr(_pooled_creation_context, "active", False)

def get_shared_publisher_for_pooled_creation():
    """Get the shared publisher during pooled adapter creation"""
    return getattr(_pooled_creation_context, "shared_publisher", None)
```

This allows `BaseBrokerWebSocketAdapter` to detect when it's being created within a `ConnectionPool` and skip its own ZMQ socket creation.

## Connection Balancing Flow

```
New Symbol Subscribe Request
              │
              ▼
┌─────────────────────────┐
│ Check subscription_map  │
│ (symbol, exchange, mode)│
└───────────┬─────────────┘
            │
    ┌───────┴───────┐
    │               │
 Found          Not Found
    │               │
    ▼               ▼
┌──────────┐   ┌─────────────────────┐
│ Return   │   │ _get_adapter_with   │
│ "already │   │ _capacity()         │
│ subscribed" │ └──────────┬──────────┘
└──────────┘              │
                  ┌───────┴───────┐
                  │               │
              Adapter           No Adapter
              Found             With Capacity
                  │               │
                  ▼               ▼
           ┌──────────┐    ┌─────────────────────┐
           │ Subscribe│    │ Adapters < max?     │
           │ to adapter│   └──────────┬──────────┘
           └──────────┘              │
                              ┌───────┴───────┐
                              │               │
                             Yes              No
                              │               │
                              ▼               ▼
                       ┌──────────┐    ┌──────────┐
                       │ Create   │    │ Error:   │
                       │ new      │    │ MAX_     │
                       │ adapter  │    │ CAPACITY │
                       └──────────┘    │ REACHED  │
                                       └──────────┘
```

## Pool Statistics

```python
def get_stats(self) -> dict:
    """Get pool statistics."""
    with self.lock:
        total_symbols = sum(self.adapter_symbol_counts)
        max_capacity = self.max_connections * self.max_symbols

        return {
            "broker": self.broker_name,
            "user_id": self.user_id,
            "active_connections": len(self.adapters),
            "max_connections": self.max_connections,
            "max_symbols_per_connection": self.max_symbols,
            "total_subscriptions": total_symbols,
            "max_capacity": max_capacity,
            "capacity_used_percent": (total_symbols / max_capacity * 100),
            "connections": [
                {
                    "index": idx + 1,
                    "symbols": count,
                    "capacity_percent": (count / self.max_symbols * 100),
                }
                for idx, count in enumerate(self.adapter_symbol_counts)
            ],
        }
```

## WebSocketProxy Integration

**Location:** `websocket_proxy/server.py`

The `WebSocketProxy` class receives data from all `ConnectionPool` instances via ZeroMQ:

```python
class WebSocketProxy:
    def __init__(self, host: str = "127.0.0.1", port: int = 8765):
        # ZeroMQ context for subscribing to broker adapters
        self.context = zmq.asyncio.Context()
        self.socket = self.context.socket(zmq.SUB)
        self.socket.connect(f"tcp://{ZMQ_HOST}:{ZMQ_PORT}")
        self.socket.setsockopt(zmq.SUBSCRIBE, b"")  # Subscribe to all topics

        # OPTIMIZATION: O(1) subscription lookup
        # Maps (symbol, exchange, mode) -> set of client_ids
        self.subscription_index: dict[tuple[str, str, int], set[int]] = defaultdict(set)

        # Message throttling (50ms minimum between LTP updates)
        self.last_message_time: dict[tuple[str, str, int], float] = {}
        self.message_throttle_interval = 0.05
```

## Benefits

### Performance

| Aspect | Without Pooling | With Pooling |
|--------|-----------------|--------------|
| Symbol Limit | ~1000 per broker | 3000+ per broker |
| Connection Time | Limited by broker | Automatic scaling |
| Memory Usage | Multiple ZMQ contexts | Single SharedZmqPublisher |
| Message Routing | Multiple endpoints | Unified ZMQ channel |

### Reliability

- Automatic connection creation when capacity is reached
- Shared ZeroMQ publisher ensures single point of data aggregation
- Thread-safe operations with `threading.RLock`
- Peak usage tracking for monitoring
- Graceful cleanup on disconnect

## Logging

The ConnectionPool provides detailed logging at key milestones:

```
[POOL] ========== CONNECTION POOL INITIALIZED ==========
[POOL] Broker: angel | User: user123
[POOL] Config: 1000 symbols/connection x 3 max connections = 3000 total capacity
[POOL] ==================================================
[POOL] Connection 1 started - first symbol: RELIANCE.NSE
[POOL] Connection 1: 100/1000 symbols (10% full) | Total: 100 symbols across 1 connection(s)
[POOL] Connection 1: 1000/1000 symbols (100% full) | Total: 1000 symbols across 1 connection(s)
[POOL] Creating NEW connection 2/3 for angel (previous connection full: 1000/1000 symbols)
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `websocket_proxy/connection_manager.py` | ConnectionPool and SharedZmqPublisher |
| `websocket_proxy/server.py` | WebSocketProxy with ZMQ subscription |
| `websocket_proxy/base_adapter.py` | BaseBrokerWebSocketAdapter base class |
| `websocket_proxy/broker_factory.py` | Adapter creation with pooling support |
| `.env` | Pool configuration variables |
