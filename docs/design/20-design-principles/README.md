# 20 - Design Principles

## Overview

OpenAlgo follows specific design patterns and architectural principles to maintain code quality, extensibility, and reliability across the trading platform.

## Core Design Principles

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          OpenAlgo Design Principles                          │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Broker         │  │  Separation     │  │  Async          │             │
│  │  Agnostic       │  │  of Concerns    │  │  Operations     │             │
│  │                 │  │                 │  │                 │             │
│  │  Single API for │  │  API → Service  │  │  Non-blocking   │             │
│  │  24+ brokers    │  │  → Broker       │  │  logging/alerts │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │  Plugin         │  │  Fail-Safe      │  │  Security       │             │
│  │  Architecture   │  │  Operations     │  │  First          │             │
│  │                 │  │                 │  │                 │             │
│  │  Dynamic broker │  │  Graceful       │  │  Encryption at  │             │
│  │  loading        │  │  degradation    │  │  rest & transit │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## 1. Broker-Agnostic API

### Principle
One unified API that works with all 24+ supported brokers.

### Implementation

```python
# All brokers implement the same interface
def place_order_api(data, auth):
    """Every broker module implements this signature"""
    pass

# Dynamic module loading
def import_broker_module(broker_name):
    module_path = f'broker.{broker_name}.api.order_api'
    return importlib.import_module(module_path)
```

### Benefits
- Users switch brokers without code changes
- Consistent response formats
- Single learning curve

## 2. Layered Architecture

### Layer Structure

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: REST API (restx_api/)                                  │
│  - Request validation                                            │
│  - Rate limiting                                                 │
│  - Swagger documentation                                         │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Service Layer (services/)                              │
│  - Business logic                                                │
│  - Order routing                                                 │
│  - Mode handling (live/analyzer)                                 │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Broker Layer (broker/)                                 │
│  - API integration                                               │
│  - Symbol mapping                                                │
│  - Data transformation                                           │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: Database Layer (database/)                             │
│  - Data persistence                                              │
│  - Caching                                                       │
│  - Query optimization                                            │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Dual Authentication Pattern

### Support Both API Key and Direct Auth

```python
def service_function(data, api_key=None, auth_token=None, broker=None):
    """
    Case 1: External API call (api_key provided)
    Case 2: Internal call (auth_token + broker provided)
    """
    if api_key:
        auth_token, broker = get_auth_token_broker(api_key)

    if not auth_token:
        return error_response()

    return broker_module.execute(auth_token)
```

## 4. Analyzer Mode Routing

### Transparent Sandbox Integration

```python
def process_order(data, api_key):
    if get_analyze_mode():
        # Route to sandbox (virtual trading)
        return sandbox_place_order(api_key, data)
    else:
        # Route to live broker
        return live_place_order(api_key, data)
```

### Benefits
- Same API for both modes
- Risk-free testing
- Isolated virtual capital

## 5. Async Non-Blocking Operations

### Never Block the Request Thread

```python
# Async logging
executor.submit(async_log_order, 'placeorder', data, response)

# Background socket events
socketio.start_background_task(socketio.emit, 'order_event', data)

# Background Telegram alerts
socketio.start_background_task(send_telegram_alert, order_data)
```

### Operations Made Async
- Order logging
- Socket.IO events
- Telegram notifications
- Database writes (non-critical)

## 6. Plugin Architecture

### Dynamic Broker Loading

```
broker/
├── zerodha/
│   ├── api/
│   │   ├── auth_api.py
│   │   ├── order_api.py
│   │   └── data.py
│   ├── mapping/
│   │   └── transform_data.py
│   └── plugin.json
├── dhan/
│   └── ... (same structure)
└── angel/
    └── ... (same structure)
```

### Plugin Discovery

```python
def load_broker_auth_functions(broker_directory):
    """Dynamically imports all broker modules"""
    for broker in os.listdir(broker_directory):
        module = import_module(f'broker.{broker}.api.auth_api')
        yield broker, module
```

## 7. Consistent Response Format

### Standard Response Structure

```python
# Success Response
{
    "status": "success",
    "message": "Order placed successfully",
    "orderid": "123456789",
    "data": {...}  # Optional
}

# Error Response
{
    "status": "error",
    "message": "Insufficient margin"
}
```

### HTTP Status Codes

| Status | Meaning |
|--------|---------|
| 200 | Success |
| 400 | Validation error |
| 403 | Authentication failed |
| 404 | Resource not found |
| 429 | Rate limit exceeded |
| 500 | Server error |

## 8. Caching Strategy

### Multi-Level Caching

```
┌─────────────────────────────────────────────────────────────────┐
│                    Caching Architecture                          │
├─────────────────────────────────────────────────────────────────┤
│  Level 1: In-Memory (TTL Cache)                                  │
│  - API key verification (10 hours)                               │
│  - Settings (1 hour)                                             │
│  - Strategies (5-10 minutes)                                     │
├─────────────────────────────────────────────────────────────────┤
│  Level 2: Database (SQLite/PostgreSQL)                           │
│  - Persistent data                                               │
│  - Transaction logs                                              │
├─────────────────────────────────────────────────────────────────┤
│  Level 3: DuckDB (Columnar)                                      │
│  - Historical market data                                        │
│  - Analytics queries                                             │
└─────────────────────────────────────────────────────────────────┘
```

## 9. Security Layers

### Defense in Depth

```
┌─────────────────────────────────────────────────────────────────┐
│  Layer 1: IP-based Security                                      │
│  - IP bans for abuse                                             │
│  - Rate limiting                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Layer 2: Authentication                                         │
│  - API key verification (Argon2 + pepper)                        │
│  - Session validation                                            │
├─────────────────────────────────────────────────────────────────┤
│  Layer 3: Encryption                                             │
│  - Auth tokens (Fernet)                                          │
│  - API keys (Argon2 hash + Fernet)                               │
├─────────────────────────────────────────────────────────────────┤
│  Layer 4: Data Isolation                                         │
│  - 5 separate databases                                          │
│  - Sandbox isolation                                             │
└─────────────────────────────────────────────────────────────────┘
```

## 10. Error Handling

### Graceful Degradation

```python
try:
    result = broker_api.place_order(data)
except ConnectionError:
    return {"status": "error", "message": "Broker unavailable"}
except ValidationError as e:
    return {"status": "error", "message": str(e)}
except Exception as e:
    logger.error(f"Unexpected error: {e}")
    return {"status": "error", "message": "Internal error"}
```

## 11. Singleton Pattern

### Thread-Safe Singleton

```python
class MarketDataService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance
```

### Used For
- Market data service
- WebSocket connections
- HTTP client pools

## 12. Data Transformation

### Broker Mapping Pattern

```python
# OpenAlgo → Broker format
def transform_data(data):
    return {
        "tradingsymbol": get_broker_symbol(data['symbol']),
        "transaction_type": data['action'],
        "order_type": map_price_type(data['pricetype']),
        # ... more mappings
    }

# Broker → OpenAlgo format
def transform_response(response):
    return {
        "orderid": response['data']['order_id'],
        "status": "success" if response['status'] == True else "error"
    }
```

## Key Files Reference

| Pattern | Implementation |
|---------|----------------|
| Plugin loader | `utils/plugin_loader.py` |
| Service layer | `services/*.py` |
| Broker interface | `broker/*/api/*.py` |
| Data transform | `broker/*/mapping/*.py` |
| Database layer | `database/*.py` |
| Constants | `utils/constants.py` |
