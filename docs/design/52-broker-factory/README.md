# Broker Factory Implementation

This document describes the broker factory design that enables OpenAlgo to work with any of the 24+ supported brokers while maintaining a single common interface for the WebSocket proxy system. OpenAlgo allows one user to connect to one broker at a time, and the broker factory ensures consistent implementation across all supported brokers.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    WebSocket Proxy Server                    │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │                   Broker Factory                        │ │
│  │  create_broker_adapter(broker_name) → Adapter Instance  │ │
│  └──────────────────────────┬─────────────────────────────┘ │
│                             │                                │
│     ┌───────────────────────┼───────────────────────┐       │
│     ▼                       ▼                       ▼       │
│  ┌──────────┐        ┌──────────┐           ┌──────────┐   │
│  │ Zerodha  │        │  Angel   │           │   Dhan   │   │
│  │ Adapter  │        │ Adapter  │    ...    │ Adapter  │   │
│  └────┬─────┘        └────┬─────┘           └────┬─────┘   │
│       │                   │                      │          │
│       └───────────────────┼──────────────────────┘          │
│                           │                                  │
│                           ▼                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Base Broker WebSocket Adapter              │ │
│  │  • initialize()  • connect()  • subscribe()            │ │
│  │  • disconnect()  • unsubscribe()  • on_data()          │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## Broker Factory

The factory creates appropriate WebSocket adapters based on broker name:

```python
# websocket_proxy/broker_factory.py
import importlib
import logging
from typing import Dict, Type

from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

logger = logging.getLogger(__name__)

# Registry of all supported broker adapters
BROKER_ADAPTERS: Dict[str, Type[BaseBrokerWebSocketAdapter]] = {}

def register_adapter(broker_name: str, adapter_class: Type[BaseBrokerWebSocketAdapter]):
    """Register a broker adapter class"""
    BROKER_ADAPTERS[broker_name.lower()] = adapter_class
    logger.info(f"Registered adapter for broker: {broker_name}")

def create_broker_adapter(broker_name: str) -> BaseBrokerWebSocketAdapter:
    """Create an instance of the appropriate broker adapter"""
    broker_name = broker_name.lower()

    # Check if adapter is registered
    if broker_name in BROKER_ADAPTERS:
        logger.info(f"Creating adapter for broker: {broker_name}")
        return BROKER_ADAPTERS[broker_name]()

    # Try dynamic import if not registered
    try:
        module_name = f"broker.{broker_name}.streaming.{broker_name}_adapter"
        class_name = f"{broker_name.capitalize()}WebSocketAdapter"

        module = importlib.import_module(module_name)
        adapter_class = getattr(module, class_name)

        register_adapter(broker_name, adapter_class)
        return adapter_class()

    except (ImportError, AttributeError) as e:
        logger.error(f"Failed to load adapter for broker {broker_name}: {e}")
        raise ValueError(f"Unsupported broker: {broker_name}")
```

## Base Adapter Interface

All broker adapters implement this common interface:

```python
# websocket_proxy/base_adapter.py
from abc import ABC, abstractmethod
from typing import Dict, Optional
import zmq
import logging

class BaseBrokerWebSocketAdapter(ABC):
    """Abstract base class for all broker WebSocket adapters"""

    def __init__(self):
        self.connected = False
        self.subscriptions: Dict[str, dict] = {}
        self.logger = logging.getLogger(self.__class__.__name__)
        self.socket: Optional[zmq.Socket] = None

    @abstractmethod
    def initialize(self, broker_name: str, user_id: str, auth_data: dict = None):
        """Initialize connection parameters"""
        pass

    @abstractmethod
    def connect(self):
        """Establish WebSocket connection to broker"""
        pass

    @abstractmethod
    def disconnect(self):
        """Close WebSocket connection"""
        pass

    @abstractmethod
    def subscribe(self, symbol: str, exchange: str, mode: int = 2, depth_level: int = 5):
        """Subscribe to market data

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE', 'NFO')
            mode: 1=LTP, 2=Quote, 4=Depth
            depth_level: 5, 20, or 30 levels
        """
        pass

    @abstractmethod
    def unsubscribe(self, symbol: str, exchange: str, mode: int = 2):
        """Unsubscribe from market data"""
        pass

    def on_open(self, ws):
        """Handle connection open"""
        self.connected = True
        self.logger.info("WebSocket connected")
        self._resubscribe_all()

    def on_close(self, ws, code=None, reason=None):
        """Handle connection close"""
        self.connected = False
        self.logger.info(f"WebSocket closed: {code} - {reason}")

    def on_error(self, ws, error):
        """Handle connection error"""
        self.logger.error(f"WebSocket error: {error}")

    def _resubscribe_all(self):
        """Resubscribe to all symbols after reconnection"""
        for sub_id, sub_info in self.subscriptions.items():
            self.subscribe(
                sub_info['symbol'],
                sub_info['exchange'],
                sub_info['mode']
            )
```

## Broker-Specific Adapters

### Zerodha Adapter

```python
# broker/zerodha/streaming/zerodha_adapter.py
from kiteconnect import KiteTicker
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

class ZerodhaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Zerodha (Kite) WebSocket adapter - 3000 symbols/connection"""

    MAX_SYMBOLS = 3000

    def initialize(self, broker_name, user_id, auth_data=None):
        self.user_id = user_id
        self.broker_name = broker_name

        api_key = auth_data.get('api_key')
        access_token = auth_data.get('auth_token')

        self.ws_client = KiteTicker(api_key, access_token)
        self.ws_client.on_connect = self.on_open
        self.ws_client.on_close = self.on_close
        self.ws_client.on_error = self.on_error
        self.ws_client.on_ticks = self._on_ticks

    def _on_ticks(self, ws, ticks):
        """Process incoming tick data"""
        for tick in ticks:
            self._normalize_and_publish(tick)
```

### Angel Adapter

> **Note**: Angel broker sends prices in paise (1/100th of a rupee). The adapter normalizes values by dividing by 100.

```python
# broker/angel/streaming/angel_adapter.py
from broker.angel.streaming.smartWebSocketV2 import SmartWebSocketV2
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

class AngelWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Angel One WebSocket adapter - 1000 symbols/connection"""

    MAX_SYMBOLS = 1000
    PRICE_DIVISOR = 100  # Angel sends prices in paise

    def initialize(self, broker_name, user_id, auth_data=None):
        self.user_id = user_id
        self.broker_name = broker_name

        auth_token = auth_data.get('auth_token')
        feed_token = auth_data.get('feed_token')
        api_key = auth_data.get('api_key')

        self.ws_client = SmartWebSocketV2(
            auth_token, api_key, user_id, feed_token,
            max_retry_attempt=5
        )
        self.ws_client.on_open = self.on_open
        self.ws_client.on_data = self._on_data
        self.ws_client.on_error = self.on_error
        self.ws_client.on_close = self.on_close

    def _normalize_price(self, price):
        """Convert paise to rupees"""
        return price / self.PRICE_DIVISOR if price else 0
```

### Dhan Adapter

```python
# broker/dhan/streaming/dhan_adapter.py
from dhanhq import DhanFeed
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

class DhanWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Dhan WebSocket adapter - 1000 symbols/connection"""

    MAX_SYMBOLS = 1000

    def initialize(self, broker_name, user_id, auth_data=None):
        self.user_id = user_id
        self.broker_name = broker_name

        client_id = auth_data.get('client_id')
        access_token = auth_data.get('auth_token')

        self.ws_client = DhanFeed(client_id, access_token)
```

## Supported Brokers (24+)

| Broker | Max Symbols | Depth Levels | Notes |
|--------|-------------|--------------|-------|
| Zerodha | 3000 | 5 | KiteTicker |
| Angel | 1000 | 5, 20 | Prices in paise |
| Dhan | 1000 | 5, 20 | DhanHQ SDK |
| Fyers | 2000 | 5 | Fyers API v3 |
| Upstox | 1500 | 5, 20 | Upstox API v2 |
| 5Paisa | 1000 | 5 | 5Paisa SDK |
| Kotak | 1000 | 5 | Neo API |
| IIFL | 1000 | 5 | IIFL Markets |
| Motilal | 1000 | 5 | Motilal API |
| Alice Blue | 1000 | 5 | Ant API |
| Finvasia | 1000 | 5 | NorenAPI |
| Flattrade | 1000 | 5 | Flattrade API |
| Firstock | 1000 | 5 | Firstock API |
| ICICI | 1000 | 5 | ICICIdirect |
| Compositedge | 1000 | 5 | Composite API |
| Mastertrust | 1000 | 5 | MT API |
| Mandot | 1000 | 5 | Mandot API |
| Paytm | 1000 | 5 | Paytm Money |
| Pocketful | 1000 | 5 | Pocketful API |
| Shoonya | 1000 | 5 | Shoonya API |
| Tradejini | 1000 | 5 | Tradejini API |
| Wisdom | 1000 | 5 | Wisdom Capital |
| Zebu | 1000 | 5 | Zebu API |
| Mstock | 1000 | 5 | Mstock API |

## Data Normalization

All adapters normalize broker data to OpenAlgo format:

```python
# Normalized LTP message
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2450.50,
    "timestamp": "2024-01-15T10:30:00+05:30"
}

# Normalized Quote message
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2450.50,
    "open": 2440.00,
    "high": 2460.00,
    "low": 2435.00,
    "close": 2448.00,
    "volume": 1500000,
    "timestamp": "2024-01-15T10:30:00+05:30"
}

# Normalized Depth message
{
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2450.50,
    "depth": {
        "buy": [
            {"price": 2450.45, "quantity": 1000, "orders": 5},
            {"price": 2450.40, "quantity": 2500, "orders": 8}
        ],
        "sell": [
            {"price": 2450.50, "quantity": 800, "orders": 3},
            {"price": 2450.55, "quantity": 1200, "orders": 4}
        ]
    }
}
```

## Connection Pooling

For brokers with low symbol limits, connection pooling is used:

```python
# Connection pool configuration
MAX_SYMBOLS_PER_WEBSOCKET = 1000
MAX_WEBSOCKET_CONNECTIONS = 3

# Total capacity: 1000 × 3 = 3000 symbols
```

```
┌─────────────────────────────────────────────────────────────┐
│                    Connection Pool (Angel)                   │
│                                                              │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐        │
│  │ Connection 1 │ │ Connection 2 │ │ Connection 3 │        │
│  │  1000 symbols│ │  1000 symbols│ │  1000 symbols│        │
│  └──────────────┘ └──────────────┘ └──────────────┘        │
│                                                              │
│  Total: 3000 symbols                                         │
└─────────────────────────────────────────────────────────────┘
```

## Usage in Application

```python
# Initialize WebSocket system
from websocket_proxy.broker_factory import create_broker_adapter
from database.auth_db import get_user_profile

def initialize_websocket(user_id):
    # Get user's active broker
    user_profile = get_user_profile(user_id)
    active_broker = user_profile.get('active_broker')

    # Create adapter using factory
    adapter = create_broker_adapter(active_broker)

    # Initialize with user credentials
    adapter.initialize(
        broker_name=active_broker,
        user_id=user_id
    )

    # Connect to broker WebSocket
    adapter.connect()

    return adapter
```

## Key Files

| File | Purpose |
|------|---------|
| `websocket_proxy/broker_factory.py` | Adapter factory |
| `websocket_proxy/base_adapter.py` | Abstract base class |
| `broker/*/streaming/*_adapter.py` | Broker implementations |
| `websocket_proxy/server.py` | Main proxy server |

## Adding a New Broker

1. Create adapter file: `broker/newbroker/streaming/newbroker_adapter.py`
2. Implement `BaseBrokerWebSocketAdapter` interface
3. Handle broker-specific data normalization
4. Register in factory (or rely on dynamic import)

```python
# broker/newbroker/streaming/newbroker_adapter.py
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

class NewbrokerWebSocketAdapter(BaseBrokerWebSocketAdapter):
    MAX_SYMBOLS = 1000

    def initialize(self, broker_name, user_id, auth_data=None):
        # Implementation
        pass

    def connect(self):
        # Implementation
        pass

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        # Implementation
        pass
```
