# Enhanced Market Data Service

## Overview

The Enhanced Market Data Service (`services/market_data_service.py`) is designed to provide reliable real-time market data for internal trade management operations. It serves as a centralized hub for:

- **OpenAlgo Flow**: Stoploss, target, and price monitoring
- **Watchlist Management**: Real-time price updates
- **Dashboard Displays**: Market data visualization
- **Future RMS Engine**: Risk management system integration

## Current Integration Status

> **Important**: As of the current implementation, the Market Data Service is **NOT connected** to the WebSocket proxy data flow. The WebSocket proxy (`websocket_proxy/server.py`) routes data directly from broker adapters to frontend clients via ZeroMQ, bypassing this service.

### Data Flow Architecture

```
Current Frontend Data Flow (Working):
┌──────────────┐    ┌─────────────────┐    ┌──────────┐    ┌──────────────────┐    ┌──────────┐
│ Broker WS    │───▶│ Broker Adapter  │───▶│ ZeroMQ   │───▶│ WebSocket Proxy  │───▶│ Frontend │
│ (Angel, etc) │    │ (angel_adapter) │    │ PUB/SUB  │    │ (server.py)      │    │ (React)  │
└──────────────┘    └─────────────────┘    └──────────┘    └──────────────────┘    └──────────┘

Intended Internal Data Flow (Not Yet Connected):
┌──────────────┐    ┌─────────────────┐    ┌────────────────────┐    ┌─────────────────────┐
│ Broker WS    │───▶│ Broker Adapter  │───▶│ MarketDataService  │───▶│ Trade Management    │
│ (Angel, etc) │    │ process_data()  │    │ (Singleton)        │    │ (Stoploss/Target)   │
└──────────────┘    └─────────────────┘    └────────────────────┘    └─────────────────────┘
```

### Integration TODO

To enable health monitoring for trade management, the broker adapter or WebSocket proxy must call:
```python
from services.market_data_service import get_market_data_service

service = get_market_data_service()
service.process_market_data(data)  # Updates health monitor
service.update_connection_status(connected=True, authenticated=True)
```

---

## Architecture

### Core Components

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          MarketDataService (Singleton)                       │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐  │
│  │ MarketDataValidator │  │ConnectionHealthMonitor│ │  Priority Subscriber │  │
│  │                     │  │                     │  │       System        │  │
│  │ - Price validation  │  │ - Connection status │  │                     │  │
│  │ - Stale data check  │  │ - Data freshness    │  │ - CRITICAL (trade)  │  │
│  │ - Circuit breaker   │  │ - Health callbacks  │  │ - HIGH (alerts)     │  │
│  │                     │  │ - Background thread │  │ - NORMAL (watchlist)│  │
│  └─────────────────────┘  └─────────────────────┘  │ - LOW (dashboard)   │  │
│                                                     └─────────────────────┘  │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                        Market Data Cache                             │    │
│  │  {                                                                   │    │
│  │    "NSE:RELIANCE": {                                                │    │
│  │      "symbol": "RELIANCE",                                          │    │
│  │      "exchange": "NSE",                                             │    │
│  │      "ltp": { "value": 2450.50, "timestamp": 1234567890 },         │    │
│  │      "quote": { "open": 2440, "high": 2460, "low": 2430, ... },    │    │
│  │      "depth": { "buy": [...], "sell": [...] },                      │    │
│  │      "last_update": 1234567890                                      │    │
│  │    }                                                                 │    │
│  │  }                                                                   │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Classes

### 1. SubscriberPriority (IntEnum)

Defines priority levels for subscribers. Lower number = higher priority.

| Priority | Value | Use Case |
|----------|-------|----------|
| `CRITICAL` | 1 | Trade management (stoploss, target) - processed first |
| `HIGH` | 2 | Price alerts, monitoring |
| `NORMAL` | 3 | Watchlist, general display |
| `LOW` | 4 | Dashboard, analytics |

### 2. ConnectionStatus (IntEnum)

Tracks WebSocket connection states.

| Status | Value | Description |
|--------|-------|-------------|
| `DISCONNECTED` | 0 | No connection |
| `CONNECTING` | 1 | Connection in progress |
| `CONNECTED` | 2 | Connected but not authenticated |
| `AUTHENTICATED` | 3 | Fully connected and authenticated |
| `STALE` | 4 | Connected but no data received recently |

### 3. HealthStatus (Dataclass)

Comprehensive health status of the service.

```python
@dataclass
class HealthStatus:
    status: str                    # 'healthy' or 'unhealthy'
    connected: bool                # WebSocket connected
    authenticated: bool            # WebSocket authenticated
    last_data_timestamp: float     # Unix timestamp of last data
    last_data_age_seconds: float   # Age of last received data
    data_flow_healthy: bool        # Data flowing within threshold
    cache_size: int                # Number of symbols in cache
    total_subscribers: int         # Total subscriber count
    critical_subscribers: int      # CRITICAL priority subscribers
    total_updates_processed: int   # Total updates processed
    validation_errors: int         # Data validation failures
    stale_data_events: int         # Times data became stale
    reconnect_count: int           # Number of reconnections
    uptime_seconds: float          # Service uptime
    message: str                   # Status message
```

### 4. ValidationResult (Dataclass)

Result of market data validation.

```python
@dataclass
class ValidationResult:
    valid: bool              # Whether data is valid
    error: str               # Error message if invalid
    warnings: List[str]      # Warning messages (e.g., stale data)
```

### 5. MarketDataValidator

Validates incoming market data for reliability.

**Configuration:**
- `MAX_PRICE_CHANGE_PERCENT = 20.0` - Circuit breaker threshold
- `MAX_DATA_AGE_SECONDS = 60` - Stale data threshold

**Methods:**

| Method | Description |
|--------|-------------|
| `validate(data)` | Validates market data, returns `ValidationResult` |
| `clear_price_history(symbol_key)` | Clears price history for validation |

**Validation Checks:**
1. Required fields present (symbol, exchange, LTP)
2. LTP is valid number > 0
3. Data timestamp not too old
4. Price change within circuit breaker limit

### 6. ConnectionHealthMonitor

Monitors WebSocket connection health with background thread.

**Configuration:**
- `MAX_DATA_GAP_SECONDS = 30` - Max time without data before stale
- `HEALTH_CHECK_INTERVAL = 5` - Health check frequency (seconds)

**Callbacks:**
- `on_connection_lost` - Called when connection drops
- `on_connection_restored` - Called when connection restored
- `on_data_stale` - Called when data becomes stale

**Methods:**

| Method | Description |
|--------|-------------|
| `record_data_received()` | Record that data was received |
| `set_connected(connected, authenticated)` | Update connection status |
| `get_health()` | Get current health status dict |
| `is_data_fresh(max_age_seconds)` | Check if data is fresh |
| `stop()` | Stop the health monitor thread |

### 7. MarketDataService (Singleton)

Main service class for managing market data.

---

## API Reference

### Getting the Service Instance

```python
from services.market_data_service import get_market_data_service

service = get_market_data_service()
```

Or use convenience functions:
```python
from services.market_data_service import (
    get_ltp,
    get_ltp_value,
    get_quote,
    get_market_depth,
    subscribe_critical,
    is_trade_management_safe,
    get_health_status
)
```

### Processing Market Data

```python
# Process incoming market data from WebSocket
data = {
    'symbol': 'RELIANCE',
    'exchange': 'NSE',
    'mode': 1,  # 1=LTP, 2=Quote, 3=Depth
    'data': {
        'ltp': 2450.50,
        'timestamp': 1234567890,
        'volume': 1000000
    }
}
success = service.process_market_data(data)
```

### Retrieving Market Data

```python
# Get LTP data
ltp_data = service.get_ltp('RELIANCE', 'NSE')
# Returns: {'value': 2450.50, 'timestamp': 1234567890, 'volume': 1000000}

# Get just the LTP value
ltp_value = service.get_ltp_value('RELIANCE', 'NSE')
# Returns: 2450.50

# Get quote data
quote = service.get_quote('RELIANCE', 'NSE')
# Returns: {'open': 2440, 'high': 2460, 'low': 2430, 'close': 2445, ...}

# Get market depth
depth = service.get_market_depth('RELIANCE', 'NSE')
# Returns: {'buy': [...], 'sell': [...], 'ltp': 2450.50}

# Get all data for a symbol
all_data = service.get_all_data('RELIANCE', 'NSE')

# Get multiple LTPs
symbols = [
    {'symbol': 'RELIANCE', 'exchange': 'NSE'},
    {'symbol': 'TCS', 'exchange': 'NSE'}
]
ltps = service.get_multiple_ltps(symbols)
```

### Subscribing to Updates

#### Priority-Based Subscription (Recommended)

```python
from services.market_data_service import SubscriberPriority

# Subscribe with specific priority
def my_callback(data):
    print(f"Received: {data}")

subscriber_id = service.subscribe_with_priority(
    priority=SubscriberPriority.HIGH,
    event_type='ltp',  # 'ltp', 'quote', 'depth', or 'all'
    callback=my_callback,
    filter_symbols={'NSE:RELIANCE', 'NSE:TCS'},  # Optional filter
    name='my_price_alert'
)

# Unsubscribe
service.unsubscribe_priority(subscriber_id)
```

#### Critical Subscription (Trade Management)

```python
# For stoploss/target monitoring - highest priority
def trade_management_callback(data):
    symbol = data.get('symbol')
    ltp = data.get('data', {}).get('ltp')
    # Check stoploss/target conditions

subscriber_id = service.subscribe_critical(
    callback=trade_management_callback,
    filter_symbols={'NSE:RELIANCE'},
    name='stoploss_monitor'
)
```

#### Legacy Subscription (Backward Compatibility)

```python
subscriber_id = service.subscribe_to_updates(
    event_type='ltp',
    callback=my_callback,
    filter_symbols={'NSE:RELIANCE'}
)

service.unsubscribe_from_updates(subscriber_id)
```

### Health & Safety Checks

```python
# Check if data is fresh enough for trade management
is_fresh = service.is_data_fresh(
    symbol='RELIANCE',
    exchange='NSE',
    max_age_seconds=30
)

# Check if trade management operations are safe
is_safe, reason = service.is_trade_management_safe()
if not is_safe:
    print(f"Trade management paused: {reason}")

# Get comprehensive health status
health = service.get_health_status()
print(f"Status: {health.status}")
print(f"Data age: {health.last_data_age_seconds}s")
print(f"Critical subscribers: {health.critical_subscribers}")
```

### Connection Status Updates

```python
# Update connection status (called by websocket integration)
service.update_connection_status(connected=True, authenticated=True)
```

### Cache Management

```python
# Clear cache for specific symbol
service.clear_cache(symbol='RELIANCE', exchange='NSE')

# Clear entire cache
service.clear_cache()

# Get cache metrics
metrics = service.get_cache_metrics()
print(f"Cache hit rate: {metrics['hit_rate']}%")
```

---

## Convenience Functions

The module provides these convenience functions that use the singleton instance:

```python
from services.market_data_service import (
    get_market_data_service,   # Get singleton instance
    get_ltp,                   # Get LTP data
    get_ltp_value,             # Get just LTP value
    get_quote,                 # Get quote data
    get_market_depth,          # Get depth data
    subscribe_to_market_updates,  # Legacy subscribe
    subscribe_critical,        # Critical priority subscribe
    unsubscribe_from_market_updates,  # Unsubscribe
    is_data_fresh,             # Check data freshness
    is_trade_management_safe,  # Check trade safety
    get_health_status          # Get health status
)
```

---

## Data Modes

| Mode | Value | Description | Data Fields |
|------|-------|-------------|-------------|
| LTP | 1 | Last Traded Price only | `ltp`, `timestamp`, `volume` |
| Quote | 2 | OHLC + LTP | `open`, `high`, `low`, `close`, `ltp`, `volume`, `change`, `change_percent` |
| Depth | 3 | Market Depth | `buy[]`, `sell[]`, `ltp`, `timestamp` |

---

## Safety Features

### 1. Data Validation

- **Required Fields Check**: Symbol, exchange, LTP must be present
- **Type Validation**: LTP must be a valid number > 0
- **Stale Data Warning**: Warns if data timestamp is old
- **Circuit Breaker**: Warns on large price changes (>20%)

### 2. Connection Health Monitoring

- Background thread checks health every 5 seconds
- Marks connection as `STALE` if no data for 30 seconds
- Fires callbacks on connection events

### 3. Trade Management Safety

```python
# Automatic pause on connection issues
is_safe, reason = is_trade_management_safe()

# Possible reasons for unsafe:
# - "Connection lost - trade management paused for safety"
# - "Data is stale - trade management paused for safety"
# - "Connection unhealthy: DISCONNECTED"
# - "Data flow inactive for 45.2s"
```

### 4. Priority Processing

Critical subscribers (trade management) are always processed first, ensuring stoploss/target triggers respond before display updates.

---

## Metrics

```python
metrics = service.get_cache_metrics()
```

| Metric | Description |
|--------|-------------|
| `total_symbols` | Number of symbols in cache |
| `total_updates` | Total updates processed |
| `cache_hits` | Successful cache lookups |
| `cache_misses` | Failed cache lookups |
| `hit_rate` | Cache hit percentage |
| `validation_errors` | Data validation failures |
| `stale_data_events` | Times data became stale |
| `total_subscribers` | All subscribers count |
| `critical_subscribers` | CRITICAL priority count |

---

## Background Threads

### 1. Health Check Thread

- Runs every 5 seconds
- Checks if data is stale (>30s without updates)
- Updates connection status to `STALE` if needed
- Fires `on_data_stale` callback

### 2. Cleanup Thread

- Runs every 5 minutes
- Removes market data older than 1 hour
- Cleans up user access tracking
- Clears price history for removed symbols

---

## Example: Trade Management Integration

```python
from services.market_data_service import (
    get_market_data_service,
    subscribe_critical,
    is_trade_management_safe,
    SubscriberPriority
)

class StoplossMonitor:
    def __init__(self):
        self.service = get_market_data_service()
        self.active_stoplosses = {}  # symbol_key -> stoploss_price
        self.subscriber_id = None

    def start_monitoring(self, positions):
        """Start monitoring positions for stoploss"""
        # Build filter set
        symbols_to_monitor = set()
        for pos in positions:
            symbol_key = f"{pos['exchange']}:{pos['symbol']}"
            symbols_to_monitor.add(symbol_key)
            self.active_stoplosses[symbol_key] = pos['stoploss_price']

        # Subscribe with CRITICAL priority
        self.subscriber_id = subscribe_critical(
            callback=self._check_stoploss,
            filter_symbols=symbols_to_monitor,
            name='stoploss_monitor'
        )

    def _check_stoploss(self, data):
        """Called for every LTP update (critical priority)"""
        # First check if trade management is safe
        is_safe, reason = is_trade_management_safe()
        if not is_safe:
            print(f"Skipping stoploss check: {reason}")
            return

        symbol = data.get('symbol')
        exchange = data.get('exchange')
        symbol_key = f"{exchange}:{symbol}"
        ltp = data.get('data', {}).get('ltp')

        if symbol_key in self.active_stoplosses:
            stoploss = self.active_stoplosses[symbol_key]
            if ltp <= stoploss:
                self._trigger_stoploss(symbol_key, ltp, stoploss)

    def _trigger_stoploss(self, symbol_key, ltp, stoploss):
        """Execute stoploss order"""
        print(f"STOPLOSS TRIGGERED: {symbol_key} at {ltp} (SL: {stoploss})")
        # Execute sell order...
        del self.active_stoplosses[symbol_key]

    def stop_monitoring(self):
        """Stop monitoring"""
        if self.subscriber_id:
            self.service.unsubscribe_priority(self.subscriber_id)
```

---

## Future Integration Points

### 1. Connect to WebSocket Proxy

```python
# In websocket_proxy/server.py - zmq_listener method
from services.market_data_service import get_market_data_service

async def zmq_listener(self):
    service = get_market_data_service()

    while self.running:
        message = await self.socket.recv_multipart()
        topic = message[0].decode()
        data = json.loads(message[1].decode())

        # Feed data to market data service for health tracking
        service.process_market_data(data)

        # Continue with existing broadcast logic...
```

### 2. Connect to Broker Adapter

```python
# In broker adapter's data callback
from services.market_data_service import get_market_data_service

def _on_data(self, message):
    # Process and normalize data...

    # Feed to market data service
    service = get_market_data_service()
    service.process_market_data({
        'symbol': symbol,
        'exchange': exchange,
        'mode': mode,
        'data': market_data
    })

    # Continue with ZeroMQ publish...
```

---

## Configuration Constants

| Constant | Value | Location | Description |
|----------|-------|----------|-------------|
| `MAX_PRICE_CHANGE_PERCENT` | 20.0 | MarketDataValidator | Circuit breaker threshold |
| `MAX_DATA_AGE_SECONDS` | 60 | MarketDataValidator | Stale data warning threshold |
| `MAX_DATA_GAP_SECONDS` | 30 | ConnectionHealthMonitor | Connection stale threshold |
| `HEALTH_CHECK_INTERVAL` | 5 | ConnectionHealthMonitor | Health check frequency |
| Cleanup interval | 300 | MarketDataService | Background cleanup (5 min) |
| Stale threshold | 3600 | MarketDataService | Cache cleanup (1 hour) |

---

## File Location

```
openalgo/
├── services/
│   └── market_data_service.py    # This service
├── websocket_proxy/
│   ├── server.py                 # WebSocket proxy (needs integration)
│   └── base_adapter.py           # Broker adapter base
└── broker/
    └── angel/
        └── streaming/
            └── angel_adapter.py  # Broker adapter (needs integration)
```

---

## Changelog

### Current Version
- Initial implementation with full feature set
- Priority-based subscriber system
- Connection health monitoring
- Data validation with circuit breaker
- Trade management safety checks
- **Pending**: Integration with WebSocket proxy data flow
