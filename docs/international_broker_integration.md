# International Broker Integration Guide
## Integrating Alpaca, Binance, and Other Non-Indian Brokers

---

## Executive Summary

**Is OpenAlgo tightly coupled with Indian exchanges?**

**Yes, currently.** OpenAlgo's architecture is primarily designed around Indian stock market exchanges (NSE, BSE, MCX, NFO, etc.) and Indian brokers. However, the application is **modular enough** to support international brokers like Alpaca and Binance with proper adaptation.

**Key Challenges:**
- **Symbol Format**: Indian format (e.g., `SBIN-EQ`) vs US/Crypto format (e.g., `AAPL`, `BTCUSDT`)
- **Exchange Structure**: Fixed Indian exchanges vs US exchanges (NYSE, NASDAQ) / Crypto pairs
- **Product Types**: Indian-specific (CNC, MIS, NRML) vs US (Cash, Margin) / Crypto (Spot, Futures)
- **Trading Hours**: IST timezone vs UTC/US timezones
- **Order Types**: Different terminology and execution logic
- **Master Contract**: Indian symbol database vs international symbol systems

---

## Current Architecture Overview

### 1. Broker Integration Pattern

OpenAlgo follows a **standardized broker integration pattern** with 5 core components:

```
broker/
├── {broker_name}/
│   ├── api/
│   │   ├── auth_api.py          # Authentication & session management
│   │   ├── order_api.py         # Order placement/modification/cancellation
│   │   ├── data.py              # Quotes, historical data, market info
│   │   └── funds.py             # Account balance & margins
│   ├── mapping/
│   │   ├── transform_data.py    # OpenAlgo ↔ Broker format conversion
│   │   └── order_data.py        # Order-specific transformations
│   ├── streaming/
│   │   ├── {broker}_adapter.py  # WebSocket adapter
│   │   └── {broker}_websocket.py # Broker-specific WebSocket client
│   └── database/
│       └── master_contract_db.py # Symbol database download/update
```

### 2. API Routing Mechanism

All API requests follow this flow:

```
Client Request
    ↓
/api/v1/{endpoint} (e.g., /placeorder)
    ↓
Validation Layer (schemas.py, constants.py)
    ↓
Service Layer (place_order_service.py)
    ↓
Dynamic Broker Import (importlib)
    ↓
broker.{broker_name}.api.order_api.place_order_api()
    ↓
Transform Data (OpenAlgo → Broker format)
    ↓
Broker API Call
    ↓
Response Transform (Broker → OpenAlgo format)
    ↓
Return to Client
```

**Key Code Reference:** `services/place_order_service.py:166-177`
```python
broker_module = import_broker_module(broker)  # Dynamic import
res, response_data, order_id = broker_module.place_order_api(order_data, auth_token)
```

### 3. Symbol Mapping System

OpenAlgo uses a **master contract database** per broker:

- **Database Table**: `symbol` (stores broker-specific symbols)
- **Fields**: `symbol`, `brsymbol`, `token`, `exchange`, `brexchange`, `lotsize`
- **Format**: Indian-style symbols (e.g., `SBIN-EQ`, `NIFTY24DECFUT`)
- **Lookup**: O(1) in-memory cache with 100,000+ symbols

**Example (Zerodha):**
```python
# OpenAlgo symbol → Broker symbol
get_br_symbol("SBIN-EQ", "NSE")  # Returns "SBIN" for Zerodha
```

### 4. Supported Indian Exchanges

**Hardcoded in `utils/constants.py`:**
```python
VALID_EXCHANGES = ['NSE', 'BSE', 'NFO', 'MCX', 'CDS', 'BCD', 'BFO', 'NCO']
VALID_PRODUCT_TYPES = ['CNC', 'MIS', 'NRML']
```

---

## International Broker Differences

### Alpaca (US Stock Market)

| Aspect | Indian Brokers | Alpaca |
|--------|---------------|--------|
| **Exchanges** | NSE, BSE, NFO | NYSE, NASDAQ, AMEX, ARCA, OTC |
| **Symbol Format** | `SBIN-EQ` | `AAPL`, `TSLA` (plain ticker) |
| **Product Types** | CNC, MIS, NRML | Cash, Margin, Day Trade |
| **Order Types** | MARKET, LIMIT, SL, SL-M | market, limit, stop, stop_limit, trailing_stop |
| **Timezone** | IST (GMT+5:30) | America/New_York (ET) |
| **Authentication** | Token-based | API Key + Secret Key |
| **Market Hours** | 9:15 AM - 3:30 PM IST | 9:30 AM - 4:00 PM ET |
| **WebSocket** | Broker-specific | Alpaca Data Stream API v2 |
| **Historical Data** | Broker API | Alpaca Bars API (1Min to 1Day) |

### Binance (Cryptocurrency)

| Aspect | Indian Brokers | Binance |
|--------|---------------|---------|
| **Exchanges** | NSE, BSE, NFO | SPOT, FUTURES, MARGIN, OPTIONS |
| **Symbol Format** | `SBIN-EQ` | `BTCUSDT`, `ETHUSDT` (pairs) |
| **Product Types** | CNC, MIS, NRML | SPOT, MARGIN, ISOLATED_MARGIN, FUTURES |
| **Order Types** | MARKET, LIMIT, SL, SL-M | MARKET, LIMIT, STOP_LOSS, STOP_LOSS_LIMIT, TAKE_PROFIT |
| **Timezone** | IST | UTC (24/7 trading) |
| **Authentication** | Token-based | API Key + Secret Key + HMAC SHA256 Signature |
| **Market Hours** | 9:15 AM - 3:30 PM IST | 24/7 (no holidays) |
| **WebSocket** | Broker-specific | Binance WebSocket Streams |
| **Historical Data** | Broker API | Klines/Candlestick API |

---

## Integration Steps for Alpaca

### Step 1: Create Broker Directory Structure

```bash
mkdir -p broker/alpaca/{api,mapping,streaming,database}
touch broker/alpaca/__init__.py
touch broker/alpaca/api/{__init__.py,auth_api.py,order_api.py,data.py,funds.py}
touch broker/alpaca/mapping/{transform_data.py,order_data.py}
touch broker/alpaca/streaming/{alpaca_adapter.py,alpaca_websocket.py}
touch broker/alpaca/database/master_contract_db.py
```

### Step 2: Implement Authentication (`auth_api.py`)

```python
# broker/alpaca/api/auth_api.py
import os
from alpaca.trading.client import TradingClient
from database.auth_db import upsert_broker_token
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate(api_key: str, secret_key: str, user_id: str, is_paper: bool = True):
    """
    Authenticate with Alpaca API

    Args:
        api_key: Alpaca API Key
        secret_key: Alpaca Secret Key
        user_id: OpenAlgo user ID
        is_paper: True for paper trading, False for live

    Returns:
        dict: {'status': 'success', 'message': 'Authenticated'}
    """
    try:
        # Initialize Alpaca client
        client = TradingClient(
            api_key=api_key,
            secret_key=secret_key,
            paper=is_paper
        )

        # Test connection by fetching account
        account = client.get_account()

        # Store credentials in database
        upsert_broker_token(
            user_id=user_id,
            broker='alpaca',
            api_key=api_key,
            api_secret=secret_key,
            auth_token=None,  # Alpaca doesn't use auth tokens
            broker_id=account.account_number
        )

        logger.info(f"Alpaca authentication successful for user {user_id}")
        return {
            'status': 'success',
            'message': f'Authenticated with Alpaca ({account.account_number})'
        }

    except Exception as e:
        logger.error(f"Alpaca authentication failed: {e}")
        return {
            'status': 'error',
            'message': f'Authentication failed: {str(e)}'
        }
```

### Step 3: Implement Symbol Mapping (`transform_data.py`)

**Key Challenge:** Convert OpenAlgo Indian-style format to Alpaca format

```python
# broker/alpaca/mapping/transform_data.py
from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transform OpenAlgo request to Alpaca format

    OpenAlgo Input:
    {
        "symbol": "AAPL-EQ",  # Need to handle this
        "exchange": "NYSE",   # Map to Alpaca exchange
        "action": "BUY",
        "quantity": 10,
        "pricetype": "LIMIT",
        "product": "CNC",
        "price": 150.50
    }

    Alpaca Output:
    {
        "symbol": "AAPL",
        "qty": 10,
        "side": "buy",
        "type": "limit",
        "time_in_force": "day",
        "limit_price": 150.50
    }
    """

    # Extract base symbol (remove -EQ suffix if present)
    symbol = data['symbol'].replace('-EQ', '')

    # Map action
    action_mapping = {
        'BUY': 'buy',
        'SELL': 'sell'
    }

    # Map price type
    pricetype_mapping = {
        'MARKET': 'market',
        'LIMIT': 'limit',
        'SL': 'stop',
        'SL-M': 'stop_limit'
    }

    # Map product type to time_in_force
    product_mapping = {
        'CNC': 'day',      # Delivery = day order
        'MIS': 'day',      # Intraday = day order
        'NRML': 'gtc'      # Normal = good till cancel
    }

    transformed = {
        "symbol": symbol,
        "qty": int(data['quantity']),
        "side": action_mapping.get(data['action'].upper(), 'buy'),
        "type": pricetype_mapping.get(data['pricetype'], 'market'),
        "time_in_force": product_mapping.get(data['product'], 'day')
    }

    # Add price fields based on order type
    if data['pricetype'] == 'LIMIT':
        transformed['limit_price'] = float(data.get('price', 0))
    elif data['pricetype'] == 'SL':
        transformed['stop_price'] = float(data.get('trigger_price', 0))
    elif data['pricetype'] == 'SL-M':
        transformed['stop_price'] = float(data.get('trigger_price', 0))
        transformed['limit_price'] = float(data.get('price', 0))

    return transformed
```

### Step 4: Implement Order API (`order_api.py`)

```python
# broker/alpaca/api/order_api.py
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from database.auth_db import get_auth_token
from broker.alpaca.mapping.transform_data import transform_data
from utils.logging import get_logger
from types import SimpleNamespace

logger = get_logger(__name__)

def get_alpaca_client(api_key: str, secret_key: str, is_paper: bool = True):
    """Create Alpaca trading client"""
    return TradingClient(
        api_key=api_key,
        secret_key=secret_key,
        paper=is_paper
    )

def place_order_api(data, auth_token):
    """
    Place order with Alpaca

    Args:
        data: OpenAlgo order data
        auth_token: Contains API key and secret (JSON string or dict)

    Returns:
        (response_object, response_data, order_id)
    """
    try:
        # Parse auth_token (contains API key and secret)
        import json
        if isinstance(auth_token, str):
            credentials = json.loads(auth_token)
        else:
            credentials = auth_token

        api_key = credentials.get('api_key')
        secret_key = credentials.get('api_secret')

        # Transform data to Alpaca format
        alpaca_order = transform_data(data)

        # Create Alpaca client
        client = get_alpaca_client(api_key, secret_key)

        # Create order request based on type
        if alpaca_order['type'] == 'market':
            order_request = MarketOrderRequest(
                symbol=alpaca_order['symbol'],
                qty=alpaca_order['qty'],
                side=OrderSide.BUY if alpaca_order['side'] == 'buy' else OrderSide.SELL,
                time_in_force=TimeInForce.DAY
            )
        elif alpaca_order['type'] == 'limit':
            order_request = LimitOrderRequest(
                symbol=alpaca_order['symbol'],
                qty=alpaca_order['qty'],
                side=OrderSide.BUY if alpaca_order['side'] == 'buy' else OrderSide.SELL,
                time_in_force=TimeInForce.DAY,
                limit_price=alpaca_order['limit_price']
            )
        # Add more order types as needed

        # Submit order
        order = client.submit_order(order_request)

        # Create response object
        response = SimpleNamespace(status=200)
        response_data = {
            'status': 'success',
            'orderid': order.id,
            'message': 'Order placed successfully'
        }

        logger.info(f"Alpaca order placed: {order.id}")
        return response, response_data, str(order.id)

    except Exception as e:
        logger.error(f"Error placing Alpaca order: {e}")
        response = SimpleNamespace(status=400)
        response_data = {
            'status': 'error',
            'message': str(e)
        }
        return response, response_data, None
```

### Step 5: Update Constants

```python
# utils/constants.py

# Add Alpaca exchanges
VALID_EXCHANGES = [
    'NSE', 'BSE', 'NFO', 'MCX', 'CDS', 'BCD', 'BFO', 'NCO',  # Indian
    'NYSE', 'NASDAQ', 'AMEX', 'ARCA', 'OTC'  # Alpaca/US
]

# Add Alpaca product types (map to existing or add new)
VALID_PRODUCT_TYPES = [
    'CNC', 'MIS', 'NRML',  # Indian
    'CASH', 'MARGIN'  # Alpaca (or reuse CNC/MIS)
]
```

### Step 6: Master Contract Database

**Option 1: Skip Master Contract** (Recommended for Alpaca)
```python
# broker/alpaca/database/master_contract_db.py

def get_master_contract():
    """
    Alpaca doesn't need master contract download.
    Symbols are simple tickers (AAPL, TSLA, etc.)
    """
    return {'status': 'success', 'message': 'Alpaca uses simple ticker symbols'}
```

**Option 2: Use Alpaca Assets API**
```python
def download_master_contract(api_key, secret_key):
    """Download all tradable assets from Alpaca"""
    from alpaca.trading.client import TradingClient

    client = TradingClient(api_key, secret_key, paper=True)
    assets = client.get_all_assets()

    # Store in database
    for asset in assets:
        if asset.tradable:
            # Insert into symbol table
            # symbol: AAPL-EQ (normalized)
            # brsymbol: AAPL (Alpaca format)
            # exchange: NYSE/NASDAQ
            pass
```

### Step 7: WebSocket Streaming

```python
# broker/alpaca/streaming/alpaca_adapter.py
from alpaca.data.live import StockDataStream
from websocket_adapters.base_adapter import BaseBrokerWebSocketAdapter
import logging

class AlpacaWebSocketAdapter(BaseBrokerWebSocketAdapter):
    """Alpaca WebSocket adapter for real-time market data"""

    def initialize(self, broker_name, user_id, auth_data=None):
        self.user_id = user_id
        self.broker_name = broker_name
        self.logger = logging.getLogger(f"{broker_name}_websocket")

        api_key = auth_data.get('api_key')
        secret_key = auth_data.get('api_secret')

        # Create Alpaca data stream
        self.stream = StockDataStream(api_key, secret_key)

        # Set up handlers
        async def trade_handler(data):
            # Transform to OpenAlgo format and publish to ZMQ
            self.on_data({
                'symbol': data.symbol,
                'ltp': data.price,
                'volume': data.size,
                'timestamp': data.timestamp
            })

        self.stream.subscribe_trades(trade_handler, '*')

    def connect(self):
        """Start WebSocket connection"""
        import asyncio
        asyncio.run(self.stream.run())

    # Implement other required methods...
```

---

## Integration Steps for Binance

### Key Differences from Alpaca:

1. **Symbol Format**: `BTCUSDT`, `ETHUSDT` (pair-based)
2. **Authentication**: HMAC SHA256 signature required for all requests
3. **Product Types**: SPOT, MARGIN, FUTURES
4. **24/7 Trading**: No market hours restriction
5. **WebSocket**: Multiple streams (trade, depth, kline, etc.)

### Sample Transform Data (Binance)

```python
# broker/binance/mapping/transform_data.py

def transform_data(data):
    """
    Transform OpenAlgo to Binance format

    OpenAlgo Input:
    {
        "symbol": "BTC-USDT",  # Custom format
        "exchange": "SPOT",
        "action": "BUY",
        "quantity": 0.001,
        "pricetype": "LIMIT",
        "product": "SPOT",
        "price": 45000
    }

    Binance Output:
    {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "type": "LIMIT",
        "quantity": "0.001",
        "price": "45000",
        "timeInForce": "GTC"
    }
    """

    # Convert symbol format
    symbol = data['symbol'].replace('-', '')  # BTC-USDT → BTCUSDT

    # Map price type
    pricetype_mapping = {
        'MARKET': 'MARKET',
        'LIMIT': 'LIMIT',
        'SL': 'STOP_LOSS',
        'SL-M': 'STOP_LOSS_LIMIT'
    }

    transformed = {
        "symbol": symbol,
        "side": data['action'].upper(),
        "type": pricetype_mapping.get(data['pricetype'], 'LIMIT'),
        "quantity": str(data['quantity']),
        "timeInForce": "GTC"
    }

    if data['pricetype'] == 'LIMIT':
        transformed['price'] = str(data['price'])

    if data.get('trigger_price'):
        transformed['stopPrice'] = str(data['trigger_price'])

    return transformed
```

---

## Configuration Changes Required

### 1. Environment Variables (`.env`)

```bash
# Add for each broker
ALPACA_API_KEY=your_api_key
ALPACA_SECRET_KEY=your_secret_key
ALPACA_PAPER_TRADING=true

BINANCE_API_KEY=your_api_key
BINANCE_SECRET_KEY=your_secret_key
BINANCE_TESTNET=true
```

### 2. Database Schema Updates

**No changes needed!** Existing `auth` table already supports storing API keys and secrets:

```sql
-- auth table (existing)
CREATE TABLE auth (
    id INTEGER PRIMARY KEY,
    user_id TEXT,
    broker TEXT,
    api_key TEXT,
    api_secret TEXT,
    auth_token TEXT,
    -- ... other fields
);
```

### 3. Broker Registration

Add to supported brokers list in UI:

```python
# database/settings_db.py or similar
SUPPORTED_BROKERS = [
    # ... existing Indian brokers
    'alpaca',
    'binance',
    # ... more international brokers
]
```

---

## Testing Strategy

### 1. Paper Trading (Recommended)

Both Alpaca and Binance support sandbox/paper trading:

```python
# Alpaca
client = TradingClient(api_key, secret_key, paper=True)

# Binance
# Use testnet URLs
BINANCE_TESTNET_URL = 'https://testnet.binance.vision/api'
```

### 2. Analyzer Mode

Use OpenAlgo's built-in analyzer mode (no real orders placed):

```bash
# In .env
ANALYZER_MODE=true
```

### 3. Unit Tests

```python
# test/test_alpaca_integration.py
def test_alpaca_order_transformation():
    openalgo_data = {
        'symbol': 'AAPL-EQ',
        'exchange': 'NYSE',
        'action': 'BUY',
        'quantity': 10,
        'pricetype': 'LIMIT',
        'product': 'CNC',
        'price': 150.50
    }

    transformed = transform_data(openalgo_data)

    assert transformed['symbol'] == 'AAPL'
    assert transformed['qty'] == 10
    assert transformed['side'] == 'buy'
    assert transformed['type'] == 'limit'
```

---

## Challenges & Solutions

### Challenge 1: Symbol Format Incompatibility

**Problem**: OpenAlgo expects `SBIN-EQ`, Alpaca uses `AAPL`, Binance uses `BTCUSDT`

**Solution**:
1. **Accept flexible input**: Allow users to enter `AAPL` or `AAPL-EQ`
2. **Smart parsing in `transform_data.py`**: Detect and convert formats
3. **Broker-specific symbol database**: Store mappings if needed

```python
def normalize_symbol(symbol, broker):
    """Normalize symbol based on broker"""
    if broker == 'alpaca':
        return symbol.replace('-EQ', '').replace('-', '')
    elif broker == 'binance':
        return symbol.replace('-', '').upper()
    else:  # Indian brokers
        return symbol
```

### Challenge 2: Exchange Validation

**Problem**: Hardcoded Indian exchanges in `VALID_EXCHANGES`

**Solution**:
1. **Extend constants**: Add international exchanges
2. **Broker-specific validation**: Check exchange validity based on broker

```python
def validate_exchange(exchange, broker):
    """Validate exchange based on broker"""
    indian_exchanges = ['NSE', 'BSE', 'NFO', 'MCX']
    us_exchanges = ['NYSE', 'NASDAQ', 'AMEX']
    crypto_exchanges = ['SPOT', 'FUTURES', 'MARGIN']

    if broker in ['zerodha', 'angel', 'dhan']:
        return exchange in indian_exchanges
    elif broker == 'alpaca':
        return exchange in us_exchanges
    elif broker == 'binance':
        return exchange in crypto_exchanges

    return False
```

### Challenge 3: Product Type Mapping

**Problem**: Indian product types (CNC, MIS, NRML) don't match US/Crypto

**Solution**:
1. **Semantic mapping**: Map based on intent (delivery vs intraday)
   - `CNC` → Alpaca `day` order → Binance `SPOT`
   - `MIS` → Alpaca `day` order → Binance `MARGIN`
   - `NRML` → Alpaca `gtc` order → Binance `FUTURES`

2. **Allow broker-specific product types**: Accept both formats

```python
# In transform_data.py
def map_product_type(product, broker):
    """Map OpenAlgo product to broker-specific product"""
    if broker == 'alpaca':
        mapping = {
            'CNC': 'day',
            'MIS': 'day',
            'NRML': 'gtc'
        }
    elif broker == 'binance':
        mapping = {
            'CNC': 'SPOT',
            'MIS': 'MARGIN',
            'NRML': 'FUTURES'
        }
    else:
        return product

    return mapping.get(product, product)
```

### Challenge 4: Timezone Handling

**Problem**: Indian brokers use IST, Alpaca uses ET, Binance uses UTC

**Solution**:
1. **Store all times in UTC** in database
2. **Convert to broker timezone** when making API calls
3. **Display in user's preferred timezone**

```python
from datetime import datetime
import pytz

def convert_to_broker_timezone(dt, broker):
    """Convert datetime to broker's timezone"""
    timezones = {
        'alpaca': 'America/New_York',
        'binance': 'UTC',
        'zerodha': 'Asia/Kolkata'
    }

    tz = pytz.timezone(timezones.get(broker, 'UTC'))
    return dt.astimezone(tz)
```

### Challenge 5: Authentication Flow

**Problem**: Indian brokers use OAuth/token-based, Alpaca/Binance use API Key + Secret

**Solution**:
1. **Unified auth interface**: Store different credential types in same table
2. **Broker-specific auth methods**: Handle OAuth vs API key differently

```python
# broker/alpaca/api/auth_api.py
def authenticate(data):
    """
    Alpaca uses API Key + Secret (no OAuth flow)
    """
    api_key = data.get('api_key')
    secret_key = data.get('secret_key')

    # Test connection
    client = TradingClient(api_key, secret_key, paper=True)
    account = client.get_account()

    # Store in database
    store_credentials(api_key=api_key, api_secret=secret_key)
```

---

## Recommended Implementation Order

1. **Phase 1: Core Integration (Week 1-2)**
   - ✅ Create broker directory structure
   - ✅ Implement `auth_api.py`
   - ✅ Implement `order_api.py` (basic MARKET orders only)
   - ✅ Implement `transform_data.py`
   - ✅ Test with paper trading accounts

2. **Phase 2: Extended Features (Week 3-4)**
   - ✅ Add `data.py` (quotes, historical data)
   - ✅ Add `funds.py` (account balance)
   - ✅ Support all order types (LIMIT, STOP, etc.)
   - ✅ Implement order modification and cancellation

3. **Phase 3: Advanced Features (Week 5-6)**
   - ✅ WebSocket streaming (`alpaca_adapter.py`)
   - ✅ Master contract database (if needed)
   - ✅ Position management
   - ✅ Trade book and order book

4. **Phase 4: Testing & Refinement (Week 7-8)**
   - ✅ Comprehensive testing
   - ✅ Error handling improvements
   - ✅ Documentation
   - ✅ UI updates for broker-specific features

---

## Sample Code: Full Working Example

### Complete Alpaca Integration Skeleton

```python
# broker/alpaca/__init__.py
"""Alpaca broker integration for US stock markets"""

# broker/alpaca/api/auth_api.py
from alpaca.trading.client import TradingClient
from database.auth_db import upsert_broker_token
from utils.logging import get_logger

logger = get_logger(__name__)

def authenticate(api_key: str, secret_key: str, user_id: str, is_paper: bool = True):
    try:
        client = TradingClient(api_key, secret_key, paper=is_paper)
        account = client.get_account()

        upsert_broker_token(
            user_id=user_id,
            broker='alpaca',
            api_key=api_key,
            api_secret=secret_key,
            broker_id=account.account_number
        )

        return {'status': 'success', 'message': 'Authenticated'}
    except Exception as e:
        return {'status': 'error', 'message': str(e)}

# broker/alpaca/api/order_api.py
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
from broker.alpaca.mapping.transform_data import transform_data
from types import SimpleNamespace
from utils.logging import get_logger

logger = get_logger(__name__)

def place_order_api(data, auth_token):
    import json
    credentials = json.loads(auth_token) if isinstance(auth_token, str) else auth_token

    client = TradingClient(
        credentials['api_key'],
        credentials['api_secret'],
        paper=True
    )

    alpaca_order = transform_data(data)

    # Create order request
    if alpaca_order['type'] == 'market':
        request = MarketOrderRequest(
            symbol=alpaca_order['symbol'],
            qty=alpaca_order['qty'],
            side=OrderSide.BUY if alpaca_order['side'] == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY
        )
    else:  # limit
        request = LimitOrderRequest(
            symbol=alpaca_order['symbol'],
            qty=alpaca_order['qty'],
            side=OrderSide.BUY if alpaca_order['side'] == 'buy' else OrderSide.SELL,
            time_in_force=TimeInForce.DAY,
            limit_price=alpaca_order['limit_price']
        )

    order = client.submit_order(request)

    response = SimpleNamespace(status=200)
    return response, {'status': 'success'}, str(order.id)

# broker/alpaca/mapping/transform_data.py
def transform_data(data):
    symbol = data['symbol'].replace('-EQ', '').replace('-', '')

    action_map = {'BUY': 'buy', 'SELL': 'sell'}
    type_map = {'MARKET': 'market', 'LIMIT': 'limit'}

    transformed = {
        "symbol": symbol,
        "qty": int(data['quantity']),
        "side": action_map[data['action'].upper()],
        "type": type_map.get(data['pricetype'], 'market')
    }

    if data['pricetype'] == 'LIMIT':
        transformed['limit_price'] = float(data['price'])

    return transformed

# broker/alpaca/api/funds.py
def get_margin_data(auth_token):
    import json
    credentials = json.loads(auth_token)

    client = TradingClient(credentials['api_key'], credentials['api_secret'], paper=True)
    account = client.get_account()

    return {
        'availablecash': float(account.cash),
        'collateral': float(account.equity),
        'buyingpower': float(account.buying_power)
    }

# broker/alpaca/api/data.py
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

def get_quotes(symbol, exchange, auth_token):
    import json
    credentials = json.loads(auth_token)

    client = StockHistoricalDataClient(credentials['api_key'], credentials['api_secret'])
    request = StockLatestQuoteRequest(symbol_or_symbols=symbol)
    quote = client.get_stock_latest_quote(request)[symbol]

    return {
        'symbol': symbol,
        'ltp': float(quote.bid_price),
        'open': 0,  # Fetch from bars if needed
        'high': 0,
        'low': 0,
        'close': 0
    }
```

---

## Dependencies

### Alpaca

```bash
pip install alpaca-py
```

Or add to `requirements.txt`:
```
alpaca-py>=0.28.0
```

### Binance

```bash
pip install python-binance
```

Or add to `requirements.txt`:
```
python-binance>=1.0.19
```

---

## Summary Checklist

### For Alpaca Integration:

- [ ] Install `alpaca-py` package
- [ ] Create `broker/alpaca/` directory structure
- [ ] Implement `auth_api.py` (API Key + Secret authentication)
- [ ] Implement `transform_data.py` (symbol format conversion)
- [ ] Implement `order_api.py` (place, modify, cancel orders)
- [ ] Implement `data.py` (quotes, historical data)
- [ ] Implement `funds.py` (account balance)
- [ ] Update `utils/constants.py` (add NYSE, NASDAQ exchanges)
- [ ] Test with Alpaca Paper Trading account
- [ ] Add WebSocket streaming (optional, Phase 3)

### For Binance Integration:

- [ ] Install `python-binance` package
- [ ] Create `broker/binance/` directory structure
- [ ] Implement HMAC SHA256 signature authentication
- [ ] Implement `transform_data.py` (pair-based symbol conversion)
- [ ] Implement `order_api.py` (SPOT, MARGIN, FUTURES support)
- [ ] Implement `data.py` (klines, ticker, depth)
- [ ] Implement `funds.py` (account balance for SPOT/FUTURES)
- [ ] Update `utils/constants.py` (add SPOT, FUTURES exchanges)
- [ ] Test with Binance Testnet
- [ ] Add WebSocket streaming (trade, depth, kline)

---

## Conclusion

**Is OpenAlgo tightly coupled with Indian exchanges?**

Yes, but the architecture is **extensible**. The main tight coupling points are:

1. **Symbol format** (Indian-style `SBIN-EQ`)
2. **Exchange names** (NSE, BSE, etc.)
3. **Product types** (CNC, MIS, NRML)

**Can it support Alpaca and Binance?**

Yes, absolutely! By:

1. **Following the broker integration pattern** (5 core files per broker)
2. **Implementing proper symbol transformation** in `transform_data.py`
3. **Extending validation constants** for international exchanges
4. **Mapping product types semantically** (CNC → Cash, MIS → Margin, etc.)

**Estimated Effort:**

- **Alpaca**: 2-3 weeks (simpler, similar to Indian brokers)
- **Binance**: 3-4 weeks (crypto-specific complexities)

**Recommended Approach:**

1. Start with Alpaca (easier, stock market similar to Indian brokers)
2. Use Alpaca Paper Trading for testing
3. Follow the implementation skeleton provided above
4. Once Alpaca works, replicate pattern for Binance

---

## Additional Resources

- **Alpaca API Docs**: https://docs.alpaca.markets/
- **Binance API Docs**: https://binance-docs.github.io/apidocs/spot/en/
- **OpenAlgo API Docs**: https://docs.openalgo.in/
- **OpenAlgo Broker Factory**: `docs/broker_factory.md`
- **OpenAlgo Architecture**: `docs/architecture-diagram.png`

---

**Document Version**: 1.0
**Last Updated**: 2025-10-05
**Author**: OpenAlgo Development Team
**License**: AGPL v3.0
