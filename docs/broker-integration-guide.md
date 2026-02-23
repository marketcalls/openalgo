# New Broker Integration Guide

This guide walks through every step required to add a new broker to OpenAlgo. It covers the directory structure, authentication patterns, order/data APIs, symbol mapping, WebSocket streaming, master contract database, rate limiting, and all registration points across the codebase.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Directory Structure](#2-directory-structure)
3. [Step 1: Create plugin.json](#3-step-1-create-pluginjson)
4. [Step 2: Implement Authentication (auth_api.py)](#4-step-2-implement-authentication-auth_apipy)
5. [Step 3: Register the Broker Callback in brlogin.py](#5-step-3-register-the-broker-callback-in-brloginpy)
6. [Step 4: Implement Order API (order_api.py)](#6-step-4-implement-order-api-order_apipy)
7. [Step 5: Implement Data API (data.py)](#7-step-5-implement-data-api-datapy)
8. [Step 6: Implement Funds API (funds.py)](#8-step-6-implement-funds-api-fundspy)
9. [Step 7: Implement Symbol Mapping (mapping/)](#9-step-7-implement-symbol-mapping-mapping)
10. [Step 8: Implement Master Contract Database](#10-step-8-implement-master-contract-database)
11. [Step 9: Implement WebSocket Streaming](#11-step-9-implement-websocket-streaming)
12. [Step 10: Register the Broker Across the Codebase](#12-step-10-register-the-broker-across-the-codebase)
13. [Authentication Patterns Reference](#13-authentication-patterns-reference)
14. [Rate Limiting](#14-rate-limiting)
15. [Token Storage and Session Management](#15-token-storage-and-session-management)
16. [Base URL Configuration (XTS Brokers)](#16-base-url-configuration-xts-brokers)
17. [Environment Variable Reference](#17-environment-variable-reference)
18. [Testing Checklist](#18-testing-checklist)
19. [Reference Implementations](#19-reference-implementations)

---

## 1. Architecture Overview

When a user logs in via a broker, the following sequence occurs:

```
User clicks "Connect Broker"
  → blueprints/brlogin.py routes to /<broker>/callback
  → broker/<broker>/api/auth_api.py::authenticate_broker() is called
  → auth token is returned
  → utils/auth_utils.py::handle_auth_success() stores token in DB + session
  → broker/<broker>/database/master_contract_db.py downloads symbol data (async)
  → User is redirected to dashboard
```

All brokers are **dynamically discovered** at startup by `utils/plugin_loader.py`, which scans `broker/*/api/auth_api.py` for an `authenticate_broker` function and registers it as `{broker_name}_auth`.

---

## 2. Directory Structure

Every broker must follow this standardized layout:

```
broker/
└── your_broker/
    ├── plugin.json                    # Broker metadata (required)
    ├── api/
    │   ├── __init__.py                # Empty file
    │   ├── auth_api.py                # Authentication logic (required)
    │   ├── order_api.py               # Place/modify/cancel orders (required)
    │   ├── data.py                    # Quotes, depth, historical data (required)
    │   └── funds.py                   # Account balance and margins (required)
    ├── mapping/
    │   ├── transform_data.py          # OpenAlgo ↔ broker format mapping (required)
    │   ├── order_data.py              # Order response mapping (required)
    │   └── margin_data.py             # Margin calculation data (optional)
    ├── database/
    │   └── master_contract_db.py      # Symbol/token database (required)
    └── streaming/
        ├── __init__.py                # Empty file
        ├── your_broker_adapter.py     # WebSocket adapter for unified proxy (required)
        ├── your_broker_websocket.py   # Low-level WebSocket client (required)
        └── your_broker_mapping.py     # Stream data normalization (required)
```

**Reference implementations:** `broker/zerodha/`, `broker/dhan/`, `broker/angel/`

---

## 3. Step 1: Create plugin.json

Create `broker/your_broker/plugin.json`:

```json
{
    "Plugin Name": "your_broker",
    "Plugin URI": "https://openalgo.in",
    "Description": "YourBroker OpenAlgo Plugin",
    "Version": "1.0",
    "Author": "Your Name",
    "Author URI": "https://openalgo.in"
}
```

**Important:** The `"Plugin Name"` value must exactly match the directory name (`broker/your_broker/`).

---

## 4. Step 2: Implement Authentication (auth_api.py)

Create `broker/your_broker/api/auth_api.py` with an `authenticate_broker()` function.

The plugin loader (`utils/plugin_loader.py`) discovers this function automatically at startup:

```python
# utils/plugin_loader.py (how discovery works)
module_name = f"broker.{broker_name}.api.auth_api"
auth_module = importlib.import_module(module_name)
auth_function = getattr(auth_module, "authenticate_broker", None)
# Registered as: app.broker_auth_functions[f"{broker_name}_auth"]
```

### Return Value Signatures

Different authentication patterns return different tuples. The callback handler in `brlogin.py` must match:

| Pattern | Return Signature | Brokers |
|---------|-----------------|---------|
| **OAuth2 (simple)** | `(auth_token, error_message)` | zerodha, fyers, flattrade, upstox, kotak, groww, indmoney, dhan_sandbox |
| **TOTP/Credential** | `(auth_token, error_message)` | aliceblue, firstock, shoonya, zebu, samco |
| **TOTP + feed token** | `(auth_token, feed_token, error_message)` | angel, mstock, nubra, paytm, motilal |
| **XTS (dual-auth)** | `(auth_token, feed_token, user_id, error_message)` | iifl, ibulls, fivepaisaxts, compositedge, jainamxts, wisdom, pocketful, definedge |
| **OAuth + user_id** | `(auth_token, user_id, error_message)` | dhan |

### Example: OAuth2 Pattern (Simplest)

```python
# broker/your_broker/api/auth_api.py

import os
from utils.httpx_client import get_httpx_client

def authenticate_broker(request_token):
    """
    Exchange the OAuth request_token/auth_code for an access token.

    Args:
        request_token: The authorization code from broker's OAuth callback

    Returns:
        tuple: (access_token, error_message)
            - On success: (token_string, None)
            - On failure: (None, "error description")
    """
    try:
        BROKER_API_KEY = os.getenv("BROKER_API_KEY")
        BROKER_API_SECRET = os.getenv("BROKER_API_SECRET")

        client = get_httpx_client()

        # Exchange request_token for access_token
        response = client.post(
            "https://api.yourbroker.com/session/token",
            json={
                "api_key": BROKER_API_KEY,
                "request_token": request_token,
                "api_secret": BROKER_API_SECRET,
            },
        )
        response.raise_for_status()
        data = response.json()

        access_token = data.get("access_token")
        if access_token:
            return access_token, None
        else:
            return None, "Authentication succeeded but no access token returned."

    except Exception as e:
        return None, f"An exception occurred: {str(e)}"
```

### Example: TOTP/Credential Pattern

```python
# For brokers that require userid + password + TOTP instead of OAuth

def authenticate_broker(clientcode, broker_pin, totp_code):
    """
    Authenticate using client credentials and TOTP.

    Returns:
        tuple: (auth_token, feed_token, error_message)
    """
    api_key = os.getenv("BROKER_API_KEY")
    client = get_httpx_client()

    payload = {
        "clientcode": clientcode,
        "password": broker_pin,
        "totp": totp_code,
    }

    response = client.post(
        "https://api.yourbroker.com/auth/login",
        json=payload,
        headers={"X-PrivateKey": api_key},
    )

    data = response.json()
    if data.get("status"):
        auth_token = data["data"]["jwtToken"]
        feed_token = data["data"].get("feedToken")
        return auth_token, feed_token, None
    else:
        return None, None, data.get("message", "Authentication failed")
```

### Example: XTS Dual-Auth Pattern (Interactive + Market Data)

XTS-based brokers require **two separate authentications** — one for order placement (interactive) and one for market data streaming:

```python
# broker/your_broker/api/auth_api.py

from broker.your_broker.baseurl import INTERACTIVE_URL, MARKET_DATA_URL

def authenticate_broker(request_token):
    """
    Authenticate with both interactive and market data endpoints.

    Returns:
        tuple: (auth_token, feed_token, user_id, error_message)
    """
    BROKER_API_KEY = os.getenv("BROKER_API_KEY")
    BROKER_API_SECRET = os.getenv("BROKER_API_SECRET")
    BROKER_API_KEY_MARKET = os.getenv("BROKER_API_KEY_MARKET")
    BROKER_API_SECRET_MARKET = os.getenv("BROKER_API_SECRET_MARKET")

    client = get_httpx_client()

    # Step 1: Interactive session (orders)
    response = client.post(
        f"{INTERACTIVE_URL}/user/session",
        json={"appKey": BROKER_API_KEY, "secretKey": BROKER_API_SECRET, "source": "WebAPI"},
    )
    result = response.json()
    auth_token = result["result"]["token"]

    # Step 2: Market data session (streaming)
    feed_response = client.post(
        f"{MARKET_DATA_URL}/auth/login",
        json={"appKey": BROKER_API_KEY_MARKET, "secretKey": BROKER_API_SECRET_MARKET, "source": "WebAPI"},
    )
    feed_result = feed_response.json()
    feed_token = feed_result["result"]["token"]
    user_id = feed_result["result"]["userID"]

    return auth_token, feed_token, user_id, None
```

**Important:** Always use `get_httpx_client()` from `utils/httpx_client.py` for connection pooling. Never create standalone `httpx.Client()` or `requests.Session()` instances.

---

## 5. Step 3: Register the Broker Callback in brlogin.py

Edit `blueprints/brlogin.py` to add your broker's callback handling in the `broker_callback()` function.

### For OAuth2 Brokers (redirect-based)

If your broker uses standard OAuth2 (redirect with `code` or `request_token` query parameter), the **generic handler at the bottom** already handles it:

```python
# blueprints/brlogin.py — already exists at the end of broker_callback()
else:
    code = request.args.get("code") or request.args.get("request_token")
    auth_token, error_message = auth_function(code)
    forward_url = "broker.html"
```

No changes needed if your broker follows this pattern and returns `(auth_token, error_message)`.

### For TOTP/Credential Brokers

If your broker requires username/password/TOTP entry, add a block:

```python
elif broker == "your_broker":
    if request.method == "GET":
        # Redirect to React TOTP page
        return redirect("/broker/your_broker/totp")

    elif request.method == "POST":
        userid = request.form.get("userid")
        password = request.form.get("password")
        totp_code = request.form.get("totp")

        auth_token, error_message = auth_function(userid, password, totp_code)
        forward_url = "broker.html"
```

### For Brokers Returning feed_token and/or user_id

If your `authenticate_broker` returns more than `(auth_token, error_message)`:

```python
elif broker == "your_broker":
    code = request.args.get("code")
    auth_token, feed_token, user_id, error_message = auth_function(code)
    forward_url = "broker.html"
```

Then also add your broker to the success handler list at the bottom of the function:

```python
# Around line 705 in brlogin.py
if broker in ["angel", "compositedge", "pocketful", "definedge", "dhan", "your_broker"]:
    return handle_auth_success(
        auth_token, session["user"], broker, feed_token=feed_token, user_id=user_id
    )
```

### For Brokers With Special Query Parameters

Some brokers use non-standard callback parameter names:

```python
elif broker == "your_broker":
    code = request.args.get("apisession")  # or whatever your broker calls it
    auth_token, error_message = auth_function(code)
    forward_url = "broker.html"
```

### For XTS Brokers (No OAuth Redirect)

XTS brokers authenticate using API key/secret directly (no redirect flow):

```python
elif broker == "your_broker":
    code = "your_broker"  # Placeholder — no request_token needed
    auth_token, feed_token, user_id, error_message = auth_function(code)
    forward_url = "broker.html"
```

### Post-Authentication Token Formatting

Some brokers require special token formatting before storage. Add formatting at the bottom of `broker_callback()`:

```python
if auth_token:
    session["broker"] = broker
    if broker == "zerodha":
        auth_token = f"{BROKER_API_KEY}:{auth_token}"  # Zerodha prefixes API key
    # Add your broker here if needed:
    # if broker == "your_broker":
    #     auth_token = f"Bearer {auth_token}"
```

---

## 6. Step 4: Implement Order API (order_api.py)

Create `broker/your_broker/api/order_api.py`. This module handles all order operations.

### Required Functions

```python
from database.auth_db import get_auth_token
from database.token_db import get_br_symbol, get_oa_symbol
from broker.your_broker.mapping.transform_data import (
    transform_data,
    transform_modify_order_data,
    map_product_type,
    reverse_map_product_type,
)

def get_api_response(endpoint, auth, method="GET", payload=None):
    """Make an authenticated API request to the broker."""
    client = get_httpx_client()
    headers = {"Authorization": f"Bearer {auth}"}
    # ... HTTP request logic
    return response.json()

def place_order_api(data, auth):
    """Place a new order. Returns (orderid, response_data, order_data)."""

def place_smartorder_api(data, auth):
    """Place a smart order (with position-aware logic)."""

def modify_order(data, auth):
    """Modify an existing order."""

def cancel_order(orderid, auth):
    """Cancel an order by ID."""

def close_all_orders(current_api_key):
    """Cancel all open/pending orders."""

def cancel_all_orders_api(data, auth):
    """Cancel all open orders."""

def get_order_book(auth):
    """Fetch all orders for the day."""

def get_trade_book(auth):
    """Fetch all executed trades."""

def get_positions(auth):
    """Fetch net positions."""

def get_holdings(auth):
    """Fetch holdings/portfolio."""
```

### API Response Helper Pattern

All brokers use a helper function for authenticated HTTP requests:

```python
def get_api_response(endpoint, auth, method="GET", payload=None):
    AUTH_TOKEN = auth
    base_url = "https://api.yourbroker.com"
    client = get_httpx_client()

    headers = {"Authorization": f"Bearer {AUTH_TOKEN}"}
    url = f"{base_url}{endpoint}"

    if method.upper() == "GET":
        response = client.get(url, headers=headers)
    elif method.upper() == "POST":
        response = client.post(url, headers=headers, json=payload)
    elif method.upper() == "PUT":
        response = client.put(url, headers=headers, json=payload)
    elif method.upper() == "DELETE":
        response = client.delete(url, headers=headers)

    return response.json()
```

---

## 7. Step 5: Implement Data API (data.py)

Create `broker/your_broker/api/data.py` for market data operations.

### Required Functions

```python
def get_quotes(symbol, exchange, auth):
    """Get real-time quotes (LTP, open, high, low, close, volume)."""
    # Returns dict with standardized fields

def get_market_depth(symbol, exchange, auth):
    """Get Level 2 market depth (bid/ask with quantities)."""

def get_history(symbol, exchange, interval, from_date, to_date, auth):
    """Get historical OHLCV candle data."""

def get_intervals():
    """Return list of supported chart intervals for this broker."""
    return ["1m", "3m", "5m", "15m", "30m", "1h", "1d"]
```

---

## 8. Step 6: Implement Funds API (funds.py)

Create `broker/your_broker/api/funds.py`:

```python
def get_margin_data(auth):
    """
    Fetch account funds/margin data.

    Returns:
        dict: Standardized margin data with keys:
            - availablecash: Available cash for trading
            - collateral: Collateral margin
            - m2munrealized: Mark-to-market unrealized P&L
            - m2mrealized: Mark-to-market realized P&L
            - utiliseddebits: Total utilized margin
    """
```

---

## 9. Step 7: Implement Symbol Mapping (mapping/)

### transform_data.py

This is the critical translation layer between OpenAlgo's unified format and the broker's API format.

```python
# broker/your_broker/mapping/transform_data.py

from database.token_db import get_br_symbol

def transform_data(data):
    """
    Transform OpenAlgo order request to broker-specific format.

    Input (OpenAlgo format):
        {
            "symbol": "SBIN",
            "exchange": "NSE",
            "action": "BUY",
            "pricetype": "MARKET",
            "product": "MIS",
            "quantity": 1,
            "price": "0",
            "trigger_price": "0",
            "disclosed_quantity": "0",
        }

    Returns:
        dict: Broker-specific order parameters
    """
    symbol = get_br_symbol(data["symbol"], data["exchange"])

    return {
        "tradingsymbol": symbol,
        "exchange": data["exchange"],
        "transaction_type": data["action"].upper(),
        "order_type": data["pricetype"],
        "quantity": data["quantity"],
        "product": map_product_type(data["product"]),
        "price": data.get("price", "0"),
        "trigger_price": data.get("trigger_price", "0"),
        "disclosed_quantity": data.get("disclosed_quantity", "0"),
        "validity": "DAY",
    }

def transform_modify_order_data(data):
    """Transform modify order request to broker format."""

def map_order_type(pricetype):
    """Map OpenAlgo price type to broker price type."""
    mapping = {"MARKET": "MARKET", "LIMIT": "LIMIT", "SL": "SL", "SL-M": "SL-M"}
    return mapping.get(pricetype, "MARKET")

def map_product_type(product):
    """Map OpenAlgo product type to broker product type."""
    mapping = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
    return mapping.get(product, "MIS")

def reverse_map_product_type(exchange, product):
    """Reverse map broker product type to OpenAlgo product type."""
    mapping = {"CNC": "CNC", "NRML": "NRML", "MIS": "MIS"}
    return mapping.get(product)
```

### order_data.py

Maps broker order response fields to OpenAlgo's standardized format:

```python
def map_order_data(order):
    """Map broker order data to OpenAlgo format."""
    return {
        "orderid": order.get("order_id"),
        "symbol": order.get("tradingsymbol"),
        "exchange": order.get("exchange"),
        "action": order.get("transaction_type"),
        "quantity": order.get("quantity"),
        "price": order.get("price"),
        "status": order.get("status"),
        # ... additional fields
    }
```

---

## 10. Step 8: Implement Master Contract Database

Create `broker/your_broker/database/master_contract_db.py`.

This module downloads the broker's instrument/symbol master file and populates the `symtoken` table, which maps OpenAlgo symbols to broker-specific symbols.

```python
import os
import pandas as pd
from sqlalchemy import create_engine, Column, Integer, String, Float, Sequence, Index
from sqlalchemy.orm import scoped_session, sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from database.auth_db import get_auth_token
from extensions import socketio
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
engine = create_engine(DATABASE_URL)
db_session = scoped_session(sessionmaker(autocommit=False, autoflush=False, bind=engine))
Base = declarative_base()
Base.query = db_session.query_property()

class SymToken(Base):
    __tablename__ = "symtoken"
    id = Column(Integer, Sequence("symtoken_id_seq"), primary_key=True)
    symbol = Column(String, nullable=False, index=True)
    brsymbol = Column(String, nullable=False, index=True)
    name = Column(String)
    exchange = Column(String, index=True)
    brexchange = Column(String, index=True)
    token = Column(String, index=True)
    expiry = Column(String)
    strike = Column(Float)
    lotsize = Column(Integer)
    instrumenttype = Column(String)
    tick_size = Column(Float)

    __table_args__ = (Index("idx_symbol_exchange", "symbol", "exchange"),)

def init_db():
    Base.metadata.create_all(bind=engine)

def delete_symtoken_table():
    SymToken.query.delete()
    db_session.commit()

def copy_from_dataframe(df):
    """Bulk insert from pandas DataFrame."""
    records = df.to_dict("records")
    db_session.bulk_insert_mappings(SymToken, records)
    db_session.commit()

def master_contract_download():
    """
    Download and process the broker's instrument master file.

    This function:
    1. Downloads the instrument list from the broker API
    2. Transforms it to match the SymToken schema
    3. Maps broker-specific symbols to OpenAlgo's standardized format
    4. Bulk inserts into the database
    5. Emits a SocketIO event when complete

    Returns:
        SocketIO emit result
    """
    try:
        init_db()
        delete_symtoken_table()

        # Download instruments from broker
        auth_token = get_auth_token()
        client = get_httpx_client()
        response = client.get(
            "https://api.yourbroker.com/instruments",
            headers={"Authorization": f"Bearer {auth_token}"},
        )

        # Parse and transform to DataFrame
        # ... broker-specific parsing logic ...
        # Map to standardized columns: symbol, brsymbol, name, exchange,
        # brexchange, token, expiry, strike, lotsize, instrumenttype, tick_size

        copy_from_dataframe(df)
        return socketio.emit("master_contract_download", {"status": "success"})

    except Exception as e:
        logger.error(f"Master contract download failed: {e}")
        return socketio.emit("master_contract_download", {"status": "error", "message": str(e)})
```

### Key Column Mappings

| SymToken Column | Description | Example |
|----------------|-------------|---------|
| `symbol` | OpenAlgo standardized symbol | `SBIN-EQ`, `NIFTY24JAN24000CE` |
| `brsymbol` | Broker's native symbol | `SBIN`, `NIFTY24JAN24000CE` |
| `name` | Human-readable name | `State Bank of India` |
| `exchange` | OpenAlgo exchange | `NSE`, `NFO`, `BSE`, `BFO`, `CDS`, `MCX` |
| `brexchange` | Broker's exchange code | Varies per broker |
| `token` | Broker's instrument token | `779` |
| `expiry` | Expiry date (derivatives) | `2024-01-25` |
| `strike` | Strike price (options) | `24000.0` |
| `lotsize` | Lot size | `50` |
| `instrumenttype` | Instrument type | `EQ`, `CE`, `PE`, `FUT` |
| `tick_size` | Minimum price movement | `0.05` |

---

## 11. Step 9: Implement WebSocket Streaming

Three files are needed in `broker/your_broker/streaming/`, plus the adapter must follow specific naming conventions for automatic discovery by the WebSocket proxy system.

### How the WebSocket Proxy Discovers Broker Adapters

The WebSocket proxy uses a **factory pattern** in `websocket_proxy/broker_factory.py`. When a user authenticates, the proxy calls `create_broker_adapter(broker_name)`, which:

1. Checks the `BROKER_ADAPTERS` registry (populated by `register_adapter()`)
2. If not found, attempts **dynamic import** using this naming convention:

```python
# websocket_proxy/broker_factory.py — _get_adapter_class()

# Primary path: broker-specific directory
module_name = f"broker.{broker_name}.streaming.{broker_name}_adapter"
class_name = f"{broker_name.capitalize()}WebSocketAdapter"

# Fallback path: websocket_proxy directory
module_name = f"websocket_proxy.{broker_name}_adapter"
```

**Critical naming requirements:**
- **Module file:** `broker/your_broker/streaming/your_broker_adapter.py`
- **Class name:** `Your_brokerWebSocketAdapter` (broker name with first letter capitalized + `WebSocketAdapter`)
- **Examples:**
  - `broker/angel/streaming/angel_adapter.py` → class `AngelWebSocketAdapter`
  - `broker/zerodha/streaming/zerodha_adapter.py` → class `ZerodhaWebSocketAdapter`
  - `broker/dhan/streaming/dhan_adapter.py` → class `DhanWebSocketAdapter`

### Architecture: Data Flow

```
Broker WebSocket API
  → your_broker_websocket.py (low-level client, receives raw ticks)
  → your_broker_mapping.py (normalizes data format)
  → your_broker_adapter.py (publishes to ZeroMQ via BaseBrokerWebSocketAdapter)
  → ZeroMQ PUB socket (port 5555)
  → websocket_proxy/server.py SUB socket (reads from ZeroMQ)
  → WebSocket clients (port 8765, broadcasts to React frontend / SDK)
```

### The Base Adapter Class (`websocket_proxy/base_adapter.py`)

Your adapter **must** extend `BaseBrokerWebSocketAdapter`, which provides:

- **ZeroMQ PUB socket** — automatically created and bound to a port
- **Connection pooling** — managed via `websocket_proxy/connection_manager.py`
- **Auth token helpers** — `get_auth_token_for_user()`, `get_fresh_auth_token()`, `clear_auth_cache_for_user()`
- **Stale token retry** — `handle_auth_error_and_retry()`, `is_auth_error()`
- **publish_market_data()** — publishes normalized tick data to ZeroMQ

**Abstract methods you must implement:**

```python
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter

class Your_brokerWebSocketAdapter(BaseBrokerWebSocketAdapter):

    def initialize(self, broker_name, user_id, auth_data=None):
        """
        Initialize connection with broker WebSocket API.
        Fetch auth token from DB, set up broker-specific client.

        Args:
            broker_name: The broker name (e.g., 'your_broker')
            user_id: The user's ID
            auth_data: Optional pre-fetched auth data

        Returns:
            dict: {"status": "success"} or {"status": "error", "message": "..."}
        """

    def connect(self):
        """
        Establish WebSocket connection to the broker.

        Returns:
            dict: {"status": "success"} or {"status": "error", "code": "...", "message": "..."}
        """

    def disconnect(self):
        """
        Disconnect from the broker's WebSocket.
        Must call self.cleanup_zmq() to release ZeroMQ resources.
        """

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        """
        Subscribe to market data.

        Args:
            symbol: Trading symbol (e.g., 'RELIANCE')
            exchange: Exchange code (e.g., 'NSE')
            mode: 1=LTP, 2=Quote, 3=Depth
            depth_level: Market depth levels (5, 20, or 30)

        Returns:
            dict: {"status": "success", "actual_depth": 5} or {"status": "error", "message": "..."}
        """

    def unsubscribe(self, symbol, exchange, mode=2):
        """
        Unsubscribe from market data.

        Returns:
            dict: {"status": "success"} or {"status": "error", "message": "..."}
        """
```

### Publishing Market Data (ZeroMQ Topic Format)

The adapter must publish data using `self.publish_market_data(topic, data)`. The topic format is:

```
{BROKER_NAME}_{EXCHANGE}_{SYMBOL}_{MODE}
```

Where MODE is `LTP`, `QUOTE`, or `DEPTH`. Examples:
- `angel_NSE_RELIANCE_LTP`
- `zerodha_NFO_NIFTY24JAN24000CE_QUOTE`

The proxy server (`websocket_proxy/server.py`) parses these topics in its `zmq_listener()` method and routes data to subscribed WebSocket clients.

### Full Adapter Example

```python
# broker/your_broker/streaming/your_broker_adapter.py

from database.auth_db import get_auth_token_broker
from database.token_db import get_token, get_brexchange
from websocket_proxy.base_adapter import BaseBrokerWebSocketAdapter
from broker.your_broker.streaming.your_broker_websocket import YourBrokerWebSocket
from broker.your_broker.streaming.your_broker_mapping import map_feed_data
from utils.logging import get_logger

logger = get_logger(__name__)

class Your_brokerWebSocketAdapter(BaseBrokerWebSocketAdapter):

    def __init__(self):
        super().__init__()
        self.broker_ws = None
        self.broker_name = "your_broker"

    def initialize(self, broker_name, user_id, auth_data=None):
        try:
            # Fetch auth credentials from database
            auth_token = self.get_auth_token_for_user(user_id)
            if not auth_token:
                return {"status": "error", "message": "No auth token found"}

            self.auth_token = auth_token
            self.user_id = user_id
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def connect(self):
        try:
            self.broker_ws = YourBrokerWebSocket(
                auth_token=self.auth_token,
                on_message_callback=self._on_tick_data,
            )
            self.broker_ws.connect()
            self.connected = True
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "code": "CONNECTION_FAILED", "message": str(e)}

    def disconnect(self):
        if self.broker_ws:
            self.broker_ws.disconnect()
        self.connected = False
        self.cleanup_zmq()  # IMPORTANT: release ZeroMQ resources

    def subscribe(self, symbol, exchange, mode=2, depth_level=5):
        try:
            token = get_token(symbol, exchange)
            if not token:
                return {"status": "error", "message": f"Token not found for {symbol}:{exchange}"}

            self.broker_ws.subscribe([token])
            self.subscriptions[f"{symbol}:{exchange}:{mode}"] = {
                "symbol": symbol, "exchange": exchange, "token": token, "mode": mode,
            }
            return {"status": "success", "actual_depth": depth_level}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def unsubscribe(self, symbol, exchange, mode=2):
        key = f"{symbol}:{exchange}:{mode}"
        sub = self.subscriptions.pop(key, None)
        if sub:
            self.broker_ws.unsubscribe([sub["token"]])
        return {"status": "success"}

    def _on_tick_data(self, raw_data):
        """Callback from broker WebSocket — normalize and publish."""
        try:
            normalized = map_feed_data(raw_data)
            if normalized:
                symbol = normalized.get("symbol")
                exchange = normalized.get("exchange")
                mode_str = {1: "LTP", 2: "QUOTE", 3: "DEPTH"}.get(normalized.get("mode", 2), "QUOTE")

                topic = f"{self.broker_name}_{exchange}_{symbol}_{mode_str}"
                self.publish_market_data(topic, normalized)
        except Exception as e:
            logger.error(f"Error processing tick: {e}")
```

### your_broker_websocket.py — Low-Level WebSocket Client

```python
# broker/your_broker/streaming/your_broker_websocket.py

import ssl
import json
import threading
import websocket

class YourBrokerWebSocket:
    def __init__(self, auth_token, on_message_callback):
        self.auth_token = auth_token
        self.on_message = on_message_callback
        self.ws = None

    def connect(self):
        self.ws = websocket.WebSocketApp(
            "wss://stream.yourbroker.com/ws",
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            on_open=self._on_open,
            header={"Authorization": f"Bearer {self.auth_token}"},
        )
        thread = threading.Thread(
            target=self.ws.run_forever,
            kwargs={"sslopt": {"cert_reqs": ssl.CERT_NONE}},
        )
        thread.daemon = True
        thread.start()

    def subscribe(self, tokens):
        """Subscribe to market data for given instrument tokens."""
        if self.ws:
            self.ws.send(json.dumps({"action": "subscribe", "tokens": tokens}))

    def unsubscribe(self, tokens):
        """Unsubscribe from market data."""
        if self.ws:
            self.ws.send(json.dumps({"action": "unsubscribe", "tokens": tokens}))

    def disconnect(self):
        if self.ws:
            self.ws.close()
```

### your_broker_mapping.py — Data Normalization

```python
# broker/your_broker/streaming/your_broker_mapping.py

def map_feed_data(raw_data):
    """
    Normalize broker-specific tick data to OpenAlgo's unified format.

    Returns:
        dict: {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "mode": 2,
            "ltp": 100.50,
            "open": 99.00,
            "high": 101.00,
            "low": 98.50,
            "close": 99.75,
            "volume": 1234567,
            "bid": 100.45,
            "ask": 100.55,
        }
    """
```

### Connection Pooling Support

The WebSocket proxy supports **connection pooling** via `websocket_proxy/connection_manager.py`. This handles broker symbol limits (e.g., Angel: 1000 symbols/connection) by automatically creating multiple WebSocket connections.

Configuration (from `.env`):
```env
MAX_SYMBOLS_PER_WEBSOCKET = '1000'    # Symbols per connection
MAX_WEBSOCKET_CONNECTIONS = '3'        # Max connections per broker
ENABLE_CONNECTION_POOLING = 'true'     # Enable/disable pooling
```

Your adapter doesn't need special code for pooling — the `_PooledAdapterWrapper` in `broker_factory.py` handles it automatically by wrapping your adapter class.

### Special Broker Behaviors in WebSocket Proxy

Some brokers have special handling in `websocket_proxy/server.py` (in `cleanup_client()`):

```python
# Flattrade and Shoonya keep connections alive when last client disconnects
if broker_name in ["flattrade", "shoonya"] and hasattr(adapter, "unsubscribe_all"):
    adapter.unsubscribe_all()  # Just unsubscribe, don't disconnect
else:
    adapter.disconnect()       # Full disconnect for all other brokers
```

If your broker has expensive reconnection overhead, consider implementing `unsubscribe_all()` and adding your broker to this list.

### WebSocket Proxy File Reference

| File | Purpose |
|------|---------|
| `websocket_proxy/server.py` | Main WebSocket proxy server (port 8765), ZeroMQ listener, client management |
| `websocket_proxy/broker_factory.py` | `BROKER_ADAPTERS` registry, `create_broker_adapter()` factory, dynamic import |
| `websocket_proxy/base_adapter.py` | `BaseBrokerWebSocketAdapter` ABC, ZeroMQ PUB socket, auth helpers |
| `websocket_proxy/connection_manager.py` | `ConnectionPool` for multi-connection symbol limit handling |
| `websocket_proxy/mapping.py` | `SymbolMapper`, `ExchangeMapper`, `BrokerCapabilityRegistry` base classes |
| `websocket_proxy/port_check.py` | Port availability checking utilities |
| `websocket_proxy/app_integration.py` | Flask app integration for starting WebSocket server |

---

## 12. Step 10: Register the Broker Across the Codebase

A new broker must be registered in **all** of the following locations:

### 12.1. `README.md` — Supported Brokers List

Add your broker to the "Supported Brokers" section (alphabetical order):

```markdown
## Supported Brokers (24+)

<details>
<summary>View All Supported Brokers</summary>

- ...
- YourBroker
- ...

</details>
```

**File:** `README.md` (lines 29-62)

### 12.2. `.sample.env` — VALID_BROKERS List

Add your broker name to the comma-separated `VALID_BROKERS` string:

```env
VALID_BROKERS = '...,your_broker,...'
```

**File:** `.sample.env` (line 22)

### 12.3. `start.sh` — Cloud/Docker VALID_BROKERS Default

The startup script has a default VALID_BROKERS list for cloud deployments:

```bash
VALID_BROKERS = '${VALID_BROKERS:-fivepaisa,...,your_broker,...,zerodha}'
```

**File:** `start.sh` (line 51)

### 12.4. `install/install.sh` — Installation Script

Two functions need updating:

**a) `validate_broker()` function** — add your broker to the valid list:

```bash
validate_broker() {
    local broker=$1
    local valid_brokers="fivepaisa,...,your_broker,...,zerodha"
    # ...
}
```

**File:** `install/install.sh` (line 113)

**b) `is_xts_broker()` function** — add here ONLY if your broker uses the XTS API:

```bash
is_xts_broker() {
    local broker=$1
    local xts_brokers="fivepaisaxts,compositedge,ibulls,iifl,jainamxts,wisdom"
    # Add your_broker here only if it uses XTS API
}
```

**File:** `install/install.sh` (line 123)

**c) Broker selection prompt** — add your broker to the displayed list:

```bash
log_message "\nValid brokers: fivepaisa,...,your_broker,...,zerodha" "$BLUE"
```

**File:** `install/install.sh` (line 358)

### 12.5. `install/install-multi.sh`

Same changes as `install.sh` — update `validate_broker()`, `is_xts_broker()`, and the broker selection prompt.

### 12.6. `install/install-docker.sh`

Same changes as above for Docker-based installation.

### 12.7. `install/install-docker-multi-custom-ssl.sh`

Same changes as above for multi-instance Docker with custom SSL.

### 12.8. `install/docker-run.sh` and `install/docker-run.bat`

These scripts have a default `VALID_BROKERS` list in their generated `.env` file. Add your broker there.

### 12.9. `websocket_proxy/broker_factory.py` — Adapter Registration

The broker factory dynamically imports and registers your streaming adapter. If you follow the naming convention, **no code changes needed** — it auto-discovers:

```python
# Auto-discovery uses these conventions:
# Module: broker.{broker_name}.streaming.{broker_name}_adapter
# Class:  {Broker_name}WebSocketAdapter  (first letter capitalized)

# Example for "your_broker":
#   Module: broker.your_broker.streaming.your_broker_adapter
#   Class:  Your_brokerWebSocketAdapter
```

If your class name doesn't follow this convention, you can **manually register** it in `broker_factory.py`:

```python
from broker.your_broker.streaming.your_broker_adapter import YourBrokerAdapter
register_adapter("your_broker", YourBrokerAdapter)
```

The factory also handles connection pooling automatically via `_PooledAdapterWrapper`. See [Step 9](#11-step-9-implement-websocket-streaming) for full details.

### 12.10. `blueprints/brlogin.py` — Callback Handler

As detailed in [Step 3](#5-step-3-register-the-broker-callback-in-brloginpy), add your broker's callback handling logic.

### 12.11. Frontend — React Broker Components (If TOTP Required)

If your broker requires TOTP/credential input (not OAuth redirect), you need a React component:

**File:** `frontend/src/pages/broker/` — Add a TOTP page component for your broker.

The route `/broker/your_broker/totp` must be handled by the React router.

### Summary Checklist: All Registration Points

| File | What to Update |
|------|---------------|
| `broker/your_broker/plugin.json` | Create new |
| `broker/your_broker/api/auth_api.py` | Create new (with `authenticate_broker`) |
| `broker/your_broker/api/order_api.py` | Create new |
| `broker/your_broker/api/data.py` | Create new |
| `broker/your_broker/api/funds.py` | Create new |
| `broker/your_broker/mapping/transform_data.py` | Create new |
| `broker/your_broker/mapping/order_data.py` | Create new |
| `broker/your_broker/database/master_contract_db.py` | Create new |
| `broker/your_broker/streaming/*` | Create 3 files |
| `README.md` → Supported Brokers | Append broker name (alphabetical) |
| `.sample.env` → VALID_BROKERS | Append broker name |
| `start.sh` → VALID_BROKERS default | Append broker name |
| `install/install.sh` → `validate_broker()` | Append broker name |
| `install/install.sh` → broker prompt | Append broker name |
| `install/install-multi.sh` | Same as install.sh |
| `install/install-docker.sh` | Same as install.sh |
| `install/install-docker-multi-custom-ssl.sh` | Same as install.sh |
| `install/docker-run.sh` | Append broker name |
| `install/docker-run.bat` | Append broker name |
| `websocket_proxy/broker_factory.py` | Auto-discovered if naming convention followed |
| `blueprints/brlogin.py` | Add callback handler |
| `frontend/` (if TOTP broker) | Add React TOTP page |

---

## 13. Authentication Patterns Reference

OpenAlgo supports five distinct authentication patterns:

### Pattern A: OAuth2 Redirect Flow

```
User → Broker Login Page → Redirect back with code/request_token
     → /<broker>/callback?code=XXX or ?request_token=XXX
     → auth_api.authenticate_broker(code) → (token, error)
```

**Brokers:** Zerodha, Fyers, Flattrade, Upstox, Paytm, Pocketful

**Login URL construction:** The `REDIRECT_URL` in `.env` is set to `https://domain/<broker>/callback`. The broker's developer portal is configured with this URL.

### Pattern B: TOTP/Credential Form

```
User → GET /<broker>/callback → Redirect to /broker/<broker>/totp (React page)
     → User enters userid + password + TOTP
     → POST /<broker>/callback with form data
     → auth_api.authenticate_broker(userid, password, totp) → (token, error)
```

**Brokers:** Angel, AliceBlue, Firstock, Shoonya, Zebu, Kotak, Samco, Motilal, Nubra, MStock

### Pattern C: XTS API Key Authentication (No Redirect)

```
User → Clicks connect → POST /<broker>/callback
     → auth_api.authenticate_broker("broker_name") → (token, feed_token, user_id, error)
     → Two API calls: interactive + market data
```

**Brokers:** IIFL, iBulls, FivePaisaXTS, CompositEdge, JainamXTS, Wisdom

### Pattern D: OAuth2 with Consent Flow (Dhan)

```
User → GET /dhan/initiate-oauth → generate_consent() → get_login_url()
     → Redirect to Dhan login → Callback with tokenId
     → GET /dhan/callback?tokenId=XXX → consume_consent(tokenId)
     → auth_api.authenticate_broker(tokenId) → (token, user_id, error)
```

### Pattern E: OTP-Based (Definedge)

```
User → GET /<broker>/callback → login_step1() sends OTP → Redirect to React TOTP page
     → User enters OTP → POST /<broker>/callback
     → authenticate_broker(otp_token, otp_code, api_secret) → (token, feed_token, user_id, error)
```

---

## 14. Rate Limiting

Rate limiting is configured globally using Flask-Limiter and applied to broker-related endpoints.

### Configuration (`limiter.py`)

```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri="memory://",
    strategy="moving-window",
)
```

### Rate Limit Categories

| Category | Default | Environment Variable | Applied To |
|----------|---------|---------------------|------------|
| Login (per min) | 5/minute | `LOGIN_RATE_LIMIT_MIN` | `brlogin.py` — `/<broker>/callback` |
| Login (per hour) | 25/hour | `LOGIN_RATE_LIMIT_HOUR` | `brlogin.py` — `/<broker>/callback` |
| API | 50/second | `API_RATE_LIMIT` | All `restx_api/` endpoints |
| Orders | 10/second | `ORDER_RATE_LIMIT` | Order placement/cancellation |
| Smart Orders | 2/second | `SMART_ORDER_RATE_LIMIT` | Multi-leg strategies |
| Webhooks | 100/minute | `WEBHOOK_RATE_LIMIT` | TradingView/Chartink webhooks |
| Strategy | 200/minute | `STRATEGY_RATE_LIMIT` | Strategy execution |

### Applying Rate Limits to New Endpoints

The broker callback already has rate limits applied:

```python
@brlogin_bp.route("/<broker>/callback", methods=["POST", "GET"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def broker_callback(broker):
    # ... your broker handler
```

If you add additional routes (e.g., `/dhan/initiate-oauth`), apply rate limits:

```python
@brlogin_bp.route("/your_broker/custom-route", methods=["GET", "POST"])
@limiter.limit(LOGIN_RATE_LIMIT_MIN)
@limiter.limit(LOGIN_RATE_LIMIT_HOUR)
def your_broker_custom_route():
    # ...
```

---

## 15. Token Storage and Session Management

After successful authentication, `handle_auth_success()` in `utils/auth_utils.py` handles:

1. **Session storage:**
   ```python
   session["logged_in"] = True
   session["AUTH_TOKEN"] = auth_token
   session["FEED_TOKEN"] = feed_token      # If available
   session["USER_ID"] = user_id            # If available
   session["broker"] = broker
   ```

2. **Database storage** via `database/auth_db.py::upsert_auth()`:
   - Stores `auth_token`, `broker`, `feed_token`, `user_id` per user
   - Uses encryption (pepper-based) for secure storage

3. **Master contract download** (async, in background thread):
   - Calls `broker/{broker}/database/master_contract_db.py::master_contract_download()`
   - Smart download: skips re-download if already done after cutoff time (default 8:00 AM IST)
   - Configurable via `MASTER_CONTRACT_CUTOFF_TIME` env variable

4. **Session expiry:**
   - All sessions expire at `SESSION_EXPIRY_TIME` (default: 03:00 IST)
   - Sessions are permanent with configurable lifetime

---

## 16. Base URL Configuration (XTS Brokers)

XTS-based brokers define base URLs in a separate file:

```python
# broker/your_broker/baseurl.py

INTERACTIVE_URL = "https://xts.yourbroker.com/interactive"
MARKET_DATA_URL = "https://xts.yourbroker.com/apimarketdata"
```

### Existing XTS Broker Base URLs

| Broker | Interactive URL | Market Data URL |
|--------|----------------|-----------------|
| IIFL | `https://ttblaze.iifl.com/interactive` | `https://ttblaze.iifl.com/apimarketdata` |
| CompositEdge | `https://xts.compositedge.com/interactive` | `https://xts.compositedge.com/apimarketdata` |
| FivePaisaXTS | `https://xtsmum.5paisa.com/interactive` | `https://xtsmum.5paisa.com/apimarketdata` |
| iBulls | `https://xts.ibullssecurities.com/interactive` | `https://xts.ibullssecurities.com/apibinarymarketdata` |
| JainamXTS | `https://jtrade.jainam.in:5000/interactive` | `https://jtrade.jainam.in:5000/apibinarymarketdata` |
| Wisdom | `https://trade.wisdomcapital.in/interactive` | `https://trade.wisdomcapital.in/apimarketdata` |

---

## 17. Environment Variable Reference

### Required for All Brokers

```env
BROKER_API_KEY = 'your_api_key'
BROKER_API_SECRET = 'your_api_secret'
REDIRECT_URL = 'http://127.0.0.1:5000/your_broker/callback'
```

### Additional for XTS Brokers

```env
BROKER_API_KEY_MARKET = 'your_market_data_api_key'
BROKER_API_SECRET_MARKET = 'your_market_data_api_secret'
```

### Special API Key Formats

Some brokers require compound API key formats:

| Broker | Format | Example |
|--------|--------|---------|
| **Dhan** | `client_id:::api_key` | `1234567890:::eyJhbGciOi...` |
| **Flattrade** | `client_id:::api_key` | `FT123456:::abc123def456` |
| **5paisa** | `user_key:::user_id:::client_id` | `abc123:::12345678:::5P12345678` |

These formats are validated at startup by `utils/env_check.py::load_and_check_env_variables()`.

---

## 18. Testing Checklist

### Manual Testing Steps

1. **Environment Configuration**
   - [ ] Add broker to `VALID_BROKERS` in `.env`
   - [ ] Set `REDIRECT_URL` to `http://127.0.0.1:5000/your_broker/callback`
   - [ ] Configure `BROKER_API_KEY` and `BROKER_API_SECRET`
   - [ ] For XTS: also set `BROKER_API_KEY_MARKET` and `BROKER_API_SECRET_MARKET`

2. **Authentication**
   - [ ] Login redirects correctly to broker
   - [ ] Callback processes successfully
   - [ ] Auth token stored in session and database
   - [ ] Master contract download triggers
   - [ ] Dashboard loads after login

3. **Order Operations**
   - [ ] Place market order
   - [ ] Place limit order
   - [ ] Place SL/SL-M order
   - [ ] Modify order
   - [ ] Cancel order
   - [ ] Cancel all orders

4. **Data Operations**
   - [ ] Get quotes (LTP)
   - [ ] Get market depth
   - [ ] Get historical data
   - [ ] Verify symbol mapping works correctly

5. **Position & Holdings**
   - [ ] Fetch positions
   - [ ] Fetch holdings
   - [ ] Fetch order book
   - [ ] Fetch trade book

6. **Funds**
   - [ ] Fetch margin/funds data

7. **WebSocket Streaming**
   - [ ] Real-time price updates via WebSocket proxy
   - [ ] Subscribe/unsubscribe working
   - [ ] Reconnection handling

8. **API Endpoints** (test at `/api/docs`)
   - [ ] All REST API endpoints work with the new broker

### Automated Tests

```bash
# Run existing test suite
uv run pytest test/ -v

# Run specific broker tests if available
uv run pytest test/test_broker.py -v
```

---

## 19. Reference Implementations

Study these implementations for the pattern closest to your broker:

| Pattern | Reference Broker | Key Files |
|---------|-----------------|-----------|
| **OAuth2 (simple)** | `broker/zerodha/` | Cleanest OAuth2 implementation |
| **OAuth2 + checksum** | `broker/fyers/` | SHA-256 checksum in auth |
| **TOTP credentials** | `broker/angel/` | Username + PIN + TOTP |
| **XTS dual-auth** | `broker/iifl/` | Interactive + market data auth |
| **OAuth + consent** | `broker/dhan/` | Multi-step consent flow |
| **OTP-based** | `broker/definedge/` | Server-generated OTP |
| **Encryption key** | `broker/aliceblue/` | Two-step key exchange |

### Quick Reference: File by File

| What You're Implementing | Look At |
|-------------------------|---------|
| auth_api.py | `broker/zerodha/api/auth_api.py` (simplest) |
| order_api.py | `broker/zerodha/api/order_api.py` |
| data.py | `broker/zerodha/api/data.py` |
| funds.py | `broker/zerodha/api/funds.py` |
| transform_data.py | `broker/zerodha/mapping/transform_data.py` |
| master_contract_db.py | `broker/zerodha/database/master_contract_db.py` |
| WebSocket adapter | `broker/zerodha/streaming/zerodha_adapter.py` |
| brlogin.py callback | `blueprints/brlogin.py` (see each broker's block) |
| plugin.json | `broker/zerodha/plugin.json` |

---

## Appendix: Complete List of Supported Brokers (29)

| # | Broker | Directory | Auth Pattern | Extra Credentials |
|---|--------|-----------|-------------|-------------------|
| 1 | 5paisa | `fivepaisa` | TOTP | Compound API key |
| 2 | 5paisa XTS | `fivepaisaxts` | XTS | MARKET keys |
| 3 | AliceBlue | `aliceblue` | Encryption Key | — |
| 4 | AngelOne | `angel` | TOTP | — |
| 5 | CompositEdge | `compositedge` | XTS/OAuth | MARKET keys |
| 6 | Definedge | `definedge` | OTP | — |
| 7 | Dhan | `dhan` | OAuth Consent | Compound API key |
| 8 | Dhan Sandbox | `dhan_sandbox` | Direct Token | — |
| 9 | Firstock | `firstock` | TOTP | — |
| 10 | Flattrade | `flattrade` | OAuth2 | Compound API key |
| 11 | Fyers | `fyers` | OAuth2 | — |
| 12 | Groww | `groww` | Direct Token | — |
| 13 | iBulls | `ibulls` | XTS | MARKET keys |
| 14 | IIFL | `iifl` | XTS | MARKET keys |
| 15 | IndMoney | `indmoney` | Direct Token | — |
| 16 | Jainam XTS | `jainamxts` | XTS | MARKET keys |
| 17 | Kotak | `kotak` | TOTP + MPIN | — |
| 18 | Motilal Oswal | `motilal` | TOTP + DOB | — |
| 19 | mStock | `mstock` | TOTP | — |
| 20 | Nubra | `nubra` | TOTP | — |
| 21 | Paytm | `paytm` | OAuth2 | — |
| 22 | Pocketful | `pocketful` | OAuth2 | — |
| 23 | Samco | `samco` | YOB verification | — |
| 24 | Shoonya | `shoonya` | TOTP | — |
| 25 | TradeJini | `tradejini` | TOTP | — |
| 26 | Upstox | `upstox` | OAuth2 | — |
| 27 | Wisdom Capital | `wisdom` | XTS | MARKET keys |
| 28 | Zebu | `zebu` | TOTP | — |
| 29 | Zerodha | `zerodha` | OAuth2 | — |
