# 33 - Broker Folder Explanations

## Overview

Each broker in OpenAlgo follows a standardized folder structure with consistent interfaces for authentication, order management, data retrieval, and symbol mapping.

## Broker Directory Structure

```
broker/
├── zerodha/                    # Example broker
│   ├── api/
│   │   ├── __init__.py
│   │   ├── auth_api.py         # Authentication
│   │   ├── order_api.py        # Order operations
│   │   ├── data.py             # Market data
│   │   └── funds.py            # Account funds
│   ├── mapping/
│   │   ├── __init__.py
│   │   ├── transform_data.py   # Data transformation
│   │   └── order_data.py       # Order field mapping
│   ├── database/
│   │   ├── __init__.py
│   │   └── master_contract_db.py
│   ├── streaming/
│   │   ├── __init__.py
│   │   └── websocket_adapter.py
│   └── plugin.json             # Broker metadata
├── dhan/
│   └── ... (same structure)
├── angel/
│   └── ... (same structure)
└── ... (29 brokers total)
```

## File Explanations

### 1. api/auth_api.py

Handles broker authentication/OAuth flow.

```python
# Required functions

def authenticate():
    """Generate login URL or handle OAuth"""
    pass

def get_auth_token():
    """Exchange code for access token"""
    pass

def revoke_token():
    """Revoke/logout from broker"""
    pass
```

### 2. api/order_api.py

Order management operations.

```python
# Required functions

def place_order_api(data, auth):
    """Place new order"""
    # Transform data to broker format
    # Make API call
    # Return (response, response_data, order_id)
    pass

def modify_order_api(data, auth):
    """Modify existing order"""
    pass

def cancel_order_api(order_id, auth):
    """Cancel order"""
    pass

def close_all_positions_api(data, auth):
    """Close all positions"""
    pass
```

### 3. api/data.py

Market data retrieval.

```python
# Required functions

def get_quotes(symbol, exchange, auth):
    """Get real-time quote"""
    pass

def get_depth(symbol, exchange, auth):
    """Get market depth (order book)"""
    pass

def get_history(symbol, exchange, interval, start, end, auth):
    """Get historical OHLC data"""
    pass

def get_option_chain(symbol, exchange, expiry, auth):
    """Get option chain data"""
    pass
```

### 4. api/funds.py

Account and fund information.

```python
# Required functions

def get_funds(auth):
    """Get account balance and margin"""
    pass

def get_orderbook(auth):
    """Get order book"""
    pass

def get_tradebook(auth):
    """Get trade book"""
    pass

def get_positions(auth):
    """Get open positions"""
    pass

def get_holdings(auth):
    """Get holdings"""
    pass
```

### 5. mapping/transform_data.py

Convert OpenAlgo format to broker format.

```python
def transform_data(data):
    """Transform order data to broker format"""
    return {
        "tradingsymbol": get_broker_symbol(data['symbol']),
        "exchange": data['exchange'],
        "transaction_type": data['action'],
        "order_type": map_price_type(data['pricetype']),
        "quantity": data['quantity'],
        "product": map_product(data['product']),
        "price": data.get('price', 0),
        "trigger_price": data.get('trigger_price', 0),
        "validity": "DAY"
    }

def transform_response(response):
    """Transform broker response to OpenAlgo format"""
    return {
        "orderid": response['data']['order_id'],
        "status": "success" if response['status'] else "error"
    }
```

### 6. database/master_contract_db.py

Symbol/token database management.

```python
def download_master_contract():
    """Download and store symbol mappings"""
    pass

def get_symbol(symbol, exchange):
    """Get broker symbol from OpenAlgo symbol"""
    pass

def get_token(symbol, exchange):
    """Get broker token for symbol"""
    pass
```

### 7. streaming/websocket_adapter.py

Real-time data streaming adapter.

```python
class BrokerWebSocketAdapter:
    def __init__(self, auth_token):
        self.auth_token = auth_token
        self.connection = None

    def connect(self):
        """Establish WebSocket connection"""
        pass

    def subscribe(self, symbols):
        """Subscribe to symbol updates"""
        pass

    def unsubscribe(self, symbols):
        """Unsubscribe from symbols"""
        pass

    def on_tick(self, callback):
        """Register tick callback"""
        pass
```

### 8. plugin.json

Broker metadata file. This is a simple metadata file (NOT configuration).

```json
{
    "Plugin Name": "zerodha",
    "Plugin URI": "https://openalgo.in",
    "Description": "Zerodha OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Rajandran R",
    "Author URI": "https://openalgo.in"
}
```

> **Important**: The `plugin.json` file is for **metadata only** - it identifies the plugin but does NOT contain configuration like API URLs or rate limits. Authentication methods, API endpoints, and WebSocket URLs are handled directly in the broker's Python code.

## Adding a New Broker

### Step 1: Create Directory Structure

```bash
mkdir -p broker/newbroker/{api,mapping,database,streaming}
touch broker/newbroker/{api,mapping,database,streaming}/__init__.py
```

### Step 2: Implement Required Files

1. `api/auth_api.py` - Authentication
2. `api/order_api.py` - Orders
3. `api/data.py` - Market data
4. `api/funds.py` - Account data
5. `mapping/transform_data.py` - Data mapping
6. `database/master_contract_db.py` - Symbol DB
7. `plugin.json` - Metadata

### Step 3: Register Broker

```bash
# .env
VALID_BROKERS=zerodha,dhan,angel,newbroker
```

## Field Mapping Examples

### Price Type Mapping

| OpenAlgo | Zerodha | Dhan | Angel |
|----------|---------|------|-------|
| MARKET | MARKET | MARKET | MARKET |
| LIMIT | LIMIT | LIMIT | LIMIT |
| SL | SL | SL | STOPLOSS_LIMIT |
| SL-M | SL-M | SL-M | STOPLOSS_MARKET |

### Product Type Mapping

| OpenAlgo | Zerodha | Dhan | Angel |
|----------|---------|------|-------|
| CNC | CNC | CNC | DELIVERY |
| MIS | MIS | INTRADAY | INTRADAY |
| NRML | NRML | MARGIN | CARRYFORWARD |

### Exchange Mapping

| OpenAlgo | Zerodha | Dhan | Angel |
|----------|---------|------|-------|
| NSE | NSE | NSE_EQ | NSE |
| NFO | NFO | NSE_FNO | NFO |
| BSE | BSE | BSE_EQ | BSE |
| MCX | MCX | MCX_COMM | MCX |

## Reference Implementations

### Best Examples

| Broker | Strength |
|--------|----------|
| zerodha | Complete OAuth2 implementation |
| dhan | Simple API key auth |
| angel | Full feature set |

### Code Reference

```python
# See broker/zerodha/ for complete example
# See broker/dhan/ for simpler implementation
# See broker/angel/ for alternative patterns
```

## Key Files Reference

| Component | File Pattern |
|-----------|--------------|
| Auth | `broker/*/api/auth_api.py` |
| Orders | `broker/*/api/order_api.py` |
| Data | `broker/*/api/data.py` |
| Funds | `broker/*/api/funds.py` |
| Mapping | `broker/*/mapping/transform_data.py` |
| Symbols | `broker/*/database/master_contract_db.py` |
| WebSocket | `broker/*/streaming/websocket_adapter.py` |
| Config | `broker/*/plugin.json` |
