# 27 - Service Layer

## Overview

The services layer contains the core business logic of OpenAlgo, acting as an intermediary between API endpoints and broker/database operations.

## Architecture Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Service Layer Architecture                            │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────────┐
│  REST API Layer (restx_api/)                                                 │
│  - Request validation                                                        │
│  - Rate limiting                                                             │
│  - Response formatting                                                       │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Service Layer (services/)                           │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ Order Services  │  │ Data Services   │  │ Account Services│             │
│  │                 │  │                 │  │                 │             │
│  │ - place_order   │  │ - quotes        │  │ - funds         │             │
│  │ - cancel_order  │  │ - depth         │  │ - holdings      │             │
│  │ - modify_order  │  │ - history       │  │ - positions     │             │
│  │ - smart_order   │  │ - instruments   │  │ - margin        │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐             │
│  │ Flow Services   │  │ WebSocket       │  │ Alert Services  │             │
│  │                 │  │ Services        │  │                 │             │
│  │ - executor      │  │                 │  │ - telegram      │             │
│  │ - scheduler     │  │ - market_data   │  │ - email         │             │
│  │ - price_monitor │  │ - websocket     │  │                 │             │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘             │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Broker Layer (broker/) & Database Layer (database/)                         │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Service Categories

### 1. Order Management Services

| Service | File | Purpose |
|---------|------|---------|
| Place Order | `place_order_service.py` | Execute orders |
| Cancel Order | `cancel_order_service.py` | Cancel pending orders |
| Modify Order | `modify_order_service.py` | Modify order params |
| Smart Order | `place_smart_order_service.py` | Position-aware orders |
| Options Order | `place_options_order_service.py` | Options trading |
| Split Order | `split_order_service.py` | Large order splitting |
| Basket Order | `basket_order_service.py` | Multiple orders |

### 2. Data Retrieval Services

| Service | File | Purpose |
|---------|------|---------|
| Order Book | `orderbook_service.py` | Get orders |
| Trade Book | `tradebook_service.py` | Get trades |
| Position Book | `positionbook_service.py` | Get positions |
| Holdings | `holdings_service.py` | Get holdings |
| Funds | `funds_service.py` | Get account balance |
| Margin | `margin_service.py` | Calculate margin |

### 3. Market Data Services

| Service | File | Purpose |
|---------|------|---------|
| Quotes | `quotes_service.py` | Real-time quotes |
| Depth | `depth_service.py` | Market depth |
| History | `history_service.py` | Historical OHLC |
| Option Chain | `option_chain_service.py` | Option strikes |
| Option Greeks | `option_greeks_service.py` | Greeks calculation |

### 4. WebSocket Services

| Service | File | Purpose |
|---------|------|---------|
| Market Data | `market_data_service.py` | Singleton data cache |
| WebSocket | `websocket_service.py` | WS management |
| WebSocket Client | `websocket_client.py` | WS client |

### 5. Flow Automation Services

| Service | File | Purpose |
|---------|------|---------|
| Flow Executor | `flow_executor_service.py` | Execute workflows |
| Flow Scheduler | `flow_scheduler_service.py` | Schedule flows |
| Price Monitor | `flow_price_monitor_service.py` | Price triggers |

## Common Patterns

### Pattern 1: Dual Authentication Support

```python
def place_order(data, api_key=None, auth_token=None, broker=None):
    """
    Supports both API key and direct auth token calls
    """
    if api_key:
        auth_token, broker = get_auth_token_broker(api_key)

    if not auth_token:
        return False, {"status": "error"}, 403

    return execute_order(data, auth_token, broker)
```

### Pattern 2: Analyzer Mode Routing

```python
def service_function(data, api_key):
    if get_analyze_mode():
        # Route to sandbox
        return sandbox_service(api_key, data)
    else:
        # Route to live broker
        return live_service(api_key, data)
```

### Pattern 3: Dynamic Broker Import

```python
def import_broker_module(broker_name):
    module_path = f'broker.{broker_name}.api.order_api'
    return importlib.import_module(module_path)
```

### Pattern 4: Async Operations

```python
# Non-blocking socket events
socketio.start_background_task(socketio.emit, 'event', data)

# Non-blocking logging
executor.submit(async_log_order, type, data, response)

# Non-blocking alerts
socketio.start_background_task(send_telegram_alert, data)
```

## Market Data Service (Singleton)

### Key Features

```python
class MarketDataService:
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self.market_data_cache = {}
        self.subscribers = {}
        self.health_status = {}
        self.metrics = {
            'cache_hits': 0,
            'cache_misses': 0,
            'validation_errors': 0
        }
```

### Data Validation

- Circuit breaker checks (large price changes)
- LTP validation
- Stale data detection
- Health monitoring

### Priority Subscribers

| Priority | Use Case |
|----------|----------|
| CRITICAL | Stop-loss/target triggers |
| HIGH | Order execution |
| NORMAL | UI display |
| LOW | Analytics |

## Response Format

### Standard Tuple Return

```python
Tuple[bool, Dict[str, Any], int]
# (success, response_data, http_status_code)
```

### Response Structure

```python
# Success
{
    "status": "success",
    "message": "Order placed",
    "orderid": "123456",
    "data": {...}
}

# Error
{
    "status": "error",
    "message": "Insufficient margin"
}
```

## Error Handling

### Consistent Error Responses

```python
try:
    result = broker_api.execute(data)
    return True, result, 200
except BrokerError as e:
    logger.error(f"Broker error: {e}")
    return False, {"status": "error", "message": str(e)}, 500
except ValidationError as e:
    return False, {"status": "error", "message": str(e)}, 400
except Exception as e:
    logger.exception("Unexpected error")
    return False, {"status": "error", "message": "Internal error"}, 500
```

## Service Layer Benefits

### Separation of Concerns

- API layer handles HTTP
- Service layer handles business logic
- Broker layer handles integration

### Testability

- Services can be unit tested
- Mock broker modules for testing
- Isolated from HTTP layer

### Reusability

- Same service for multiple endpoints
- Shared validation logic
- Common error handling

## Key Files Reference

| Category | Files |
|----------|-------|
| Order Services | `place_order_service.py`, `cancel_order_service.py`, `modify_order_service.py` |
| Data Services | `orderbook_service.py`, `tradebook_service.py`, `positionbook_service.py` |
| Market Data | `market_data_service.py`, `websocket_service.py`, `quotes_service.py` |
| Flow | `flow_executor_service.py`, `flow_scheduler_service.py` |
| Alerts | `telegram_alert_service.py`, `telegram_bot_service.py` |
| Sandbox | `sandbox_service.py`, `analyzer_service.py` |
