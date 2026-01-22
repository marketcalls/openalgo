# 17 - Connection Pooling

## Overview

OpenAlgo implements connection pooling for HTTP connections and WebSocket symbol subscriptions to optimize performance and manage broker API rate limits efficiently.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Connection Pooling Architecture                        │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      WebSocket Connection Pool                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  Configuration:                                                      │   │
│  │  MAX_SYMBOLS_PER_WEBSOCKET = 1000 (default)                         │   │
│  │  MAX_WEBSOCKET_CONNECTIONS = 3 (default)                            │   │
│  │  Total capacity: 3000 symbols per user                              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐                   │
│  │  Connection 1 │  │  Connection 2 │  │  Connection 3 │                   │
│  │  1000 symbols │  │  1000 symbols │  │  1000 symbols │                   │
│  │               │  │               │  │               │                   │
│  │  SBIN, INFY,  │  │  TCS, WIPRO,  │  │  NIFTY opts,  │                   │
│  │  RELIANCE...  │  │  HDFC...      │  │  BANKNIFTY... │                   │
│  └───────────────┘  └───────────────┘  └───────────────┘                   │
│         │                 │                    │                            │
│         └─────────────────┼────────────────────┘                            │
│                           │                                                  │
│                           ▼                                                  │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      Broker WebSocket Server                         │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                      HTTP Connection Pooling (requests)                      │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │  requests.Session() with connection pooling                          │   │
│  │                                                                      │   │
│  │  - Keep-alive connections                                           │   │
│  │  - Connection reuse                                                 │   │
│  │  - Automatic retry                                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## WebSocket Connection Pool

### Configuration

```bash
# .env
MAX_SYMBOLS_PER_WEBSOCKET=1000
MAX_WEBSOCKET_CONNECTIONS=3
```

### Pool Management

```python
class WebSocketPool:
    """Manages multiple WebSocket connections"""

    def __init__(self, max_symbols=1000, max_connections=3):
        self.max_symbols = max_symbols
        self.max_connections = max_connections
        self.connections = []
        self.symbol_map = {}  # symbol -> connection

    def subscribe(self, symbol):
        """Subscribe to symbol, creating new connection if needed"""
        # Find connection with capacity
        for conn in self.connections:
            if len(conn.symbols) < self.max_symbols:
                conn.subscribe(symbol)
                self.symbol_map[symbol] = conn
                return

        # Create new connection if under limit
        if len(self.connections) < self.max_connections:
            conn = self.create_connection()
            self.connections.append(conn)
            conn.subscribe(symbol)
            self.symbol_map[symbol] = conn
        else:
            raise PoolExhaustedError("Maximum connections reached")

    def unsubscribe(self, symbol):
        """Unsubscribe from symbol"""
        if symbol in self.symbol_map:
            conn = self.symbol_map[symbol]
            conn.unsubscribe(symbol)
            del self.symbol_map[symbol]
```

### Connection Balancing

```
┌─────────────────────────────────────────────────────────────────┐
│                    Symbol Distribution                           │
└─────────────────────────────────────────────────────────────────┘

New Symbol Subscribe Request
              │
              ▼
┌─────────────────────────┐
│ Find connection with    │
│ available capacity      │
└───────────┬─────────────┘
            │
    ┌───────┴───────┐
    │               │
   Found         Not Found
    │               │
    ▼               ▼
┌──────────┐   ┌─────────────────────┐
│ Subscribe│   │ Connections < max?  │
│ to conn  │   └──────────┬──────────┘
└──────────┘              │
                  ┌───────┴───────┐
                  │               │
                 Yes              No
                  │               │
                  ▼               ▼
           ┌──────────┐    ┌──────────┐
           │ Create   │    │ Error:   │
           │ new conn │    │ Pool     │
           └──────────┘    │ exhausted│
                           └──────────┘
```

## HTTP Connection Pool

### Using requests.Session

```python
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

class BrokerClient:
    def __init__(self):
        self.session = requests.Session()

        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504]
        )

        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=retry_strategy
        )

        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def get_quote(self, symbol):
        """Reuses connection from pool"""
        return self.session.get(
            f"https://api.broker.com/quote/{symbol}",
            timeout=10
        )
```

### Pool Settings

| Setting | Default | Description |
|---------|---------|-------------|
| pool_connections | 10 | Number of connection pools |
| pool_maxsize | 20 | Max connections per pool |
| max_retries | 3 | Retry attempts |
| backoff_factor | 0.5 | Delay between retries |

## Database Connection Pool

SQLAlchemy connection pooling configuration:

```python
from sqlalchemy import create_engine

engine = create_engine(
    'sqlite:///db/openalgo.db',
    pool_size=5,
    max_overflow=10,
    pool_timeout=30,
    pool_pre_ping=True
)
```

### Pool Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| pool_size | 5 | Permanent connections |
| max_overflow | 10 | Extra connections allowed |
| pool_timeout | 30 | Wait time for connection |
| pool_pre_ping | True | Verify connection before use |

## Benefits

### Performance

| Aspect | Without Pooling | With Pooling |
|--------|-----------------|--------------|
| Connection Time | ~100ms each | ~5ms (reused) |
| Memory Usage | High (new connections) | Optimized |
| Broker Rate Limits | Easy to exceed | Managed |

### Reliability

- Automatic reconnection
- Connection health checks
- Graceful degradation
- Error recovery

## Monitoring

### Pool Statistics

```python
def get_pool_stats():
    return {
        'websocket': {
            'connections': len(ws_pool.connections),
            'total_symbols': sum(len(c.symbols) for c in ws_pool.connections),
            'capacity_used': total_symbols / (max_symbols * max_connections)
        },
        'http': {
            'pool_size': session.adapters['https://'].poolmanager.num_pools,
            'active_connections': get_active_count()
        }
    }
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `websocket_proxy/server.py` | WebSocket pool management |
| `broker/*/api/data.py` | HTTP session management |
| `database/*.py` | SQLAlchemy pool config |
| `.env` | Pool configuration |
