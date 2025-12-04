# 20. Complete API Reference

## Overview

This document provides a complete reference of all REST API endpoints and WebSocket/ZMQ architecture. The Rust desktop application must implement all 35+ endpoints with exact request/response format compatibility.

---

## REST API Base URL

```
http://{host}:{port}/api/v1/
```

Default: `http://127.0.0.1:5000/api/v1/`

---

## Complete Endpoint List

### Order Management (9 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/placeorder` | POST | Place a standard order |
| `/placesmartorder` | POST | Place smart order with position sizing |
| `/modifyorder` | POST | Modify pending order |
| `/cancelorder` | POST | Cancel a specific order |
| `/cancelallorder` | POST | Cancel all pending orders |
| `/closeposition` | POST | Close a specific position |
| `/basketorder` | POST | Place multi-leg basket orders |
| `/splitorder` | POST | Split large orders |
| `/orderstatus` | POST | Get status of specific order |

### Options Trading (5 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/optionsorder` | POST | Place options order (strike-based) |
| `/optionsmultiorder` | POST | Place multiple options orders |
| `/optionsymbol` | POST | Get option trading symbol |
| `/optionchain` | POST | Get full options chain |
| `/optiongreeks` | POST | Get options Greeks (Delta, Gamma, etc.) |

### Account Data (6 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/orderbook` | POST | Get order history |
| `/tradebook` | POST | Get executed trades |
| `/positionbook` | POST | Get open positions |
| `/openposition` | POST | Get specific position |
| `/holdings` | POST | Get long-term holdings |
| `/funds` | POST | Get account funds/margin |

### Market Data (8 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/quotes` | POST | Get LTP and OHLC for single symbol |
| `/multiquotes` | POST | Get quotes for multiple symbols |
| `/depth` | POST | Get market depth (L2 data) |
| `/history` | POST | Get historical candles |
| `/intervals` | POST | Get supported timeframe intervals |
| `/ticker/{symbol}` | GET | Get real-time ticker data |
| `/expiry` | POST | Get expiry dates for F&O |
| `/syntheticfuture` | POST | Get synthetic futures price |

### Symbol & Search (4 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/symbol` | POST | Get broker-specific symbol |
| `/search` | POST | Search symbols |
| `/instruments` | POST | Get all instruments |
| `/margin` | POST | Get margin requirements |

### Sandbox/Analyzer (2 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/analyzer` | GET | Get analyzer mode status |
| `/analyzer/toggle` | POST | Toggle analyzer mode on/off |

### Telegram Bot (6 endpoints)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/telegram/config` | GET/POST | Get/set Telegram config |
| `/telegram/start` | POST | Start Telegram bot |
| `/telegram/stop` | POST | Stop Telegram bot |
| `/telegram/webhook` | POST | Handle Telegram webhooks |
| `/telegram/users` | GET | Get registered users |
| `/telegram/broadcast` | POST | Broadcast message to users |
| `/telegram/notify` | POST | Send notification |

### Utility (1 endpoint)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ping` | GET | Health check endpoint |

---

## Detailed API Schemas

### Place Order

**Endpoint**: `POST /api/v1/placeorder`

**Request**:
```json
{
  "apikey": "your_32_char_api_key",
  "strategy": "Strategy Name",
  "symbol": "RELIANCE",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "10",
  "price": "0",
  "trigger_price": "0",
  "disclosed_quantity": "0"
}
```

**Response (Success)**:
```json
{
  "status": "success",
  "orderid": "230901000012345"
}
```

**Response (Error)**:
```json
{
  "status": "error",
  "message": "Invalid API key"
}
```

### Smart Order

**Endpoint**: `POST /api/v1/placesmartorder`

**Request**:
```json
{
  "apikey": "your_api_key",
  "strategy": "Strategy Name",
  "symbol": "RELIANCE",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "10",
  "position_size": "10",
  "price": "0",
  "trigger_price": "0",
  "disclosed_quantity": "0"
}
```

**Smart Order Logic**:
- `position_size = 0`: Close position (exit)
- `position_size > current`: Buy difference
- `position_size < current`: Sell difference
- `position_size = current`: No action

### Options Order

**Endpoint**: `POST /api/v1/optionsorder`

**Request**:
```json
{
  "apikey": "your_api_key",
  "strategy": "Options Strategy",
  "symbol": "NIFTY",
  "exchange": "NFO",
  "action": "BUY",
  "strike": "20000",
  "option_type": "CE",
  "expiry": "25DEC2025",
  "product": "MIS",
  "pricetype": "MARKET",
  "quantity": "50",
  "price": "0",
  "trigger_price": "0"
}
```

### Basket Order

**Endpoint**: `POST /api/v1/basketorder`

**Request**:
```json
{
  "apikey": "your_api_key",
  "strategy": "Basket Strategy",
  "orders": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "10",
      "pricetype": "MARKET",
      "product": "MIS"
    },
    {
      "symbol": "TCS",
      "exchange": "NSE",
      "action": "BUY",
      "quantity": "5",
      "pricetype": "MARKET",
      "product": "MIS"
    }
  ]
}
```

### Quotes

**Endpoint**: `POST /api/v1/quotes`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "ltp": 2456.75,
    "open": 2440.00,
    "high": 2470.50,
    "low": 2435.25,
    "close": 2445.00,
    "volume": 1234567,
    "timestamp": "2025-12-04T10:30:00+05:30"
  }
}
```

### Multi-Quotes

**Endpoint**: `POST /api/v1/multiquotes`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"},
    {"symbol": "INFY", "exchange": "NSE"}
  ]
}
```

### Market Depth

**Endpoint**: `POST /api/v1/depth`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "bids": [
      {"price": 2455.50, "quantity": 1000, "orders": 5},
      {"price": 2455.00, "quantity": 2500, "orders": 12}
    ],
    "asks": [
      {"price": 2456.00, "quantity": 800, "orders": 3},
      {"price": 2456.50, "quantity": 1500, "orders": 8}
    ],
    "totalbuyqty": 125000,
    "totalsellqty": 98000
  }
}
```

### History

**Endpoint**: `POST /api/v1/history`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "interval": "5m",
  "start": "2025-12-01",
  "end": "2025-12-04"
}
```

**Response**:
```json
{
  "status": "success",
  "data": [
    {
      "timestamp": "2025-12-01T09:15:00",
      "open": 2440.00,
      "high": 2445.50,
      "low": 2438.00,
      "close": 2443.25,
      "volume": 125000
    }
  ]
}
```

### Option Chain

**Endpoint**: `POST /api/v1/optionchain`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbol": "NIFTY",
  "exchange": "NFO",
  "expiry": "25DEC2025"
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "spot_price": 24500.50,
    "expiry": "25DEC2025",
    "chain": [
      {
        "strike": 24000,
        "ce": {
          "symbol": "NIFTY25DEC24000CE",
          "ltp": 520.50,
          "oi": 1250000,
          "volume": 45000,
          "iv": 15.2
        },
        "pe": {
          "symbol": "NIFTY25DEC24000PE",
          "ltp": 45.75,
          "oi": 980000,
          "volume": 32000,
          "iv": 16.8
        }
      }
    ]
  }
}
```

### Option Greeks

**Endpoint**: `POST /api/v1/optiongreeks`

**Request**:
```json
{
  "apikey": "your_api_key",
  "symbol": "NIFTY25DEC24000CE",
  "exchange": "NFO",
  "spot_price": "24500.50",
  "interest_rate": "0.07"
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "delta": 0.65,
    "gamma": 0.0012,
    "theta": -15.50,
    "vega": 45.30,
    "rho": 12.80,
    "iv": 15.2
  }
}
```

### Funds

**Endpoint**: `POST /api/v1/funds`

**Request**:
```json
{
  "apikey": "your_api_key"
}
```

**Response**:
```json
{
  "status": "success",
  "data": {
    "availablecash": 500000.00,
    "collateral": 150000.00,
    "m2mrealized": 5000.00,
    "m2munrealized": -2500.00,
    "utilizedmargin": 125000.00
  }
}
```

---

## WebSocket API

### Connection

**URL**: `ws://{websocket_host}:{websocket_port}`

Default: `ws://127.0.0.1:8765`

### Authentication

```json
{
  "action": "authenticate",
  "api_key": "your_32_char_api_key"
}
```

**Response**:
```json
{
  "type": "auth",
  "status": "success",
  "message": "Authentication successful",
  "broker": "angel",
  "user_id": "ABC123",
  "supported_features": {
    "ltp": true,
    "quote": true,
    "depth": true
  }
}
```

### Subscribe

```json
{
  "action": "subscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE"},
    {"symbol": "TCS", "exchange": "NSE"}
  ],
  "mode": "Quote"
}
```

**Mode Options**:
- `"LTP"` (mode=1): Last traded price only
- `"Quote"` (mode=2): LTP + OHLC + Volume
- `"Depth"` (mode=3): Full market depth

**Response**:
```json
{
  "type": "subscribe",
  "status": "success",
  "subscriptions": [
    {
      "symbol": "RELIANCE",
      "exchange": "NSE",
      "status": "success",
      "mode": "Quote",
      "depth": 5,
      "broker": "angel"
    }
  ],
  "message": "Subscription processing complete",
  "broker": "angel"
}
```

### Market Data Message

```json
{
  "type": "market_data",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "mode": 2,
  "broker": "angel",
  "data": {
    "ltp": 2456.75,
    "open": 2440.00,
    "high": 2470.50,
    "low": 2435.25,
    "close": 2445.00,
    "volume": 1234567,
    "timestamp": 1733300400000
  }
}
```

### Unsubscribe

```json
{
  "action": "unsubscribe",
  "symbols": [
    {"symbol": "RELIANCE", "exchange": "NSE", "mode": 2}
  ]
}
```

### Unsubscribe All

```json
{
  "action": "unsubscribe_all"
}
```

### Error Message

```json
{
  "status": "error",
  "code": "AUTHENTICATION_ERROR",
  "message": "Invalid API key"
}
```

---

## ZeroMQ Architecture

### Overview

ZeroMQ (ZMQ) is used for inter-process communication between broker WebSocket adapters and the WebSocket proxy server.

```
┌─────────────────┐     ZMQ PUB/SUB     ┌─────────────────┐
│ Broker Adapter  │ ─────────────────── │ WebSocket Proxy │
│ (Publisher)     │    tcp://*:5555     │ (Subscriber)    │
└─────────────────┘                     └─────────────────┘
        │                                       │
        │ Receives data                         │ Forwards to
        │ from broker API                       │ WebSocket clients
        ▼                                       ▼
┌─────────────────┐                     ┌─────────────────┐
│ Broker WebSocket│                     │ Client WebSocket│
│ (Angel, Zerodha)│                     │ (SDK, Browser)  │
└─────────────────┘                     └─────────────────┘
```

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `ZMQ_HOST` | `127.0.0.1` | ZMQ bind address |
| `ZMQ_PORT` | `5555` | ZMQ port |

### Topic Format

```
{BROKER}_{EXCHANGE}_{SYMBOL}_{MODE}
```

Examples:
- `angel_NSE_RELIANCE_LTP`
- `zerodha_NFO_NIFTY25DEC24000CE_QUOTE`
- `NSE_INDEX_NIFTY_50_LTP` (index special case)

### Message Format

**Publisher (Broker Adapter)**:
```python
socket.send_multipart([
    b"angel_NSE_RELIANCE_LTP",
    b'{"ltp": 2456.75, "timestamp": 1733300400000}'
])
```

**Subscriber (WebSocket Proxy)**:
```python
[topic, data] = socket.recv_multipart()
topic_str = topic.decode('utf-8')  # "angel_NSE_RELIANCE_LTP"
market_data = json.loads(data.decode('utf-8'))
```

### Rust Implementation

```rust
// src-tauri/src/streaming/zmq_publisher.rs

use zeromq::{Socket, PubSocket};

pub struct ZmqPublisher {
    socket: PubSocket,
    port: u16,
}

impl ZmqPublisher {
    pub async fn new(host: &str, port: u16) -> Result<Self, ZmqError> {
        let mut socket = PubSocket::new();
        socket.bind(&format!("tcp://{}:{}", host, port)).await?;

        Ok(Self { socket, port })
    }

    pub async fn publish(&self, topic: &str, data: &MarketData) -> Result<(), ZmqError> {
        let payload = serde_json::to_string(data)?;

        // Send multipart message: [topic, data]
        self.socket.send(
            vec![
                topic.as_bytes().to_vec().into(),
                payload.as_bytes().to_vec().into(),
            ]
        ).await?;

        Ok(())
    }
}

// src-tauri/src/streaming/zmq_subscriber.rs

use zeromq::{Socket, SubSocket};

pub struct ZmqSubscriber {
    socket: SubSocket,
}

impl ZmqSubscriber {
    pub async fn new(host: &str, port: u16) -> Result<Self, ZmqError> {
        let mut socket = SubSocket::new();
        socket.connect(&format!("tcp://{}:{}", host, port)).await?;

        // Subscribe to all topics
        socket.subscribe("").await?;

        Ok(Self { socket })
    }

    pub async fn receive(&mut self) -> Result<(String, MarketData), ZmqError> {
        let msg = self.socket.recv().await?;

        let topic = String::from_utf8(msg.get(0).unwrap().to_vec())?;
        let data: MarketData = serde_json::from_slice(msg.get(1).unwrap())?;

        Ok((topic, data))
    }
}
```

### Performance Optimizations

1. **Subscription Indexing**: O(1) lookup using `HashMap<(symbol, exchange, mode), HashSet<client_id>>`
2. **Message Throttling**: 50ms minimum interval for LTP updates
3. **Batch Message Sending**: Use `tokio::join!` for parallel client updates
4. **Pre-serialized Messages**: Serialize JSON once, send to all clients

---

## Rate Limiting per Endpoint

| Endpoint Category | Limit |
|-------------------|-------|
| Login | 5/min, 25/hour |
| Password Reset | 15/hour |
| API (general) | 50/sec |
| Order Placement | 10/sec |
| Smart Order | 2/sec |
| Webhook | 100/min |
| Strategy Management | 200/min |
| Security Dashboard | 60/min |

---

## Error Codes

| Code | Description |
|------|-------------|
| `AUTHENTICATION_ERROR` | Invalid or missing API key |
| `NOT_AUTHENTICATED` | WebSocket not authenticated |
| `BROKER_ERROR` | Broker adapter error |
| `BROKER_CONNECTION_ERROR` | Failed to connect to broker |
| `BROKER_INIT_ERROR` | Failed to initialize broker |
| `INVALID_ACTION` | Unknown action type |
| `INVALID_JSON` | Malformed JSON |
| `INVALID_PARAMETERS` | Missing or invalid parameters |
| `SERVER_ERROR` | Internal server error |
| `RATE_LIMIT_EXCEEDED` | Too many requests |
| `SYMBOL_NOT_FOUND` | Symbol not in master contract |
| `EXCHANGE_INVALID` | Invalid exchange code |
| `INSUFFICIENT_FUNDS` | Not enough margin |

---

## HTTP Status Codes

| Status | Description |
|--------|-------------|
| 200 | Success |
| 400 | Bad Request (validation error) |
| 401 | Unauthorized (invalid API key) |
| 403 | Forbidden (IP banned) |
| 404 | Not Found |
| 429 | Too Many Requests (rate limited) |
| 500 | Internal Server Error |

---

## Rust Axum Router Implementation

```rust
// src-tauri/src/api/router.rs

use axum::{
    routing::{get, post},
    Router,
};

pub fn api_v1_routes() -> Router<AppState> {
    Router::new()
        // Order Management
        .route("/placeorder", post(orders::place_order))
        .route("/placesmartorder", post(orders::place_smart_order))
        .route("/modifyorder", post(orders::modify_order))
        .route("/cancelorder", post(orders::cancel_order))
        .route("/cancelallorder", post(orders::cancel_all_orders))
        .route("/closeposition", post(orders::close_position))
        .route("/basketorder", post(orders::basket_order))
        .route("/splitorder", post(orders::split_order))
        .route("/orderstatus", post(orders::order_status))

        // Options Trading
        .route("/optionsorder", post(options::place_order))
        .route("/optionsmultiorder", post(options::multi_order))
        .route("/optionsymbol", post(options::get_symbol))
        .route("/optionchain", post(options::get_chain))
        .route("/optiongreeks", post(options::get_greeks))

        // Account Data
        .route("/orderbook", post(account::order_book))
        .route("/tradebook", post(account::trade_book))
        .route("/positionbook", post(account::positions))
        .route("/openposition", post(account::open_position))
        .route("/holdings", post(account::holdings))
        .route("/funds", post(account::funds))

        // Market Data
        .route("/quotes", post(market::quotes))
        .route("/multiquotes", post(market::multi_quotes))
        .route("/depth", post(market::depth))
        .route("/history", post(market::history))
        .route("/intervals", post(market::intervals))
        .route("/ticker/:symbol", get(market::ticker))
        .route("/expiry", post(market::expiry))
        .route("/syntheticfuture", post(market::synthetic_future))

        // Symbol & Search
        .route("/symbol", post(symbols::get_symbol))
        .route("/search", post(symbols::search))
        .route("/instruments", post(symbols::instruments))
        .route("/margin", post(symbols::margin))

        // Sandbox/Analyzer
        .route("/analyzer", get(analyzer::get_mode))
        .route("/analyzer/toggle", post(analyzer::toggle_mode))

        // Telegram Bot
        .route("/telegram/config", get(telegram::get_config).post(telegram::set_config))
        .route("/telegram/start", post(telegram::start))
        .route("/telegram/stop", post(telegram::stop))
        .route("/telegram/webhook", post(telegram::webhook))
        .route("/telegram/users", get(telegram::get_users))
        .route("/telegram/broadcast", post(telegram::broadcast))
        .route("/telegram/notify", post(telegram::notify))

        // Utility
        .route("/ping", get(utility::ping))
}

pub fn build_router(state: AppState) -> Router {
    Router::new()
        .nest("/api/v1", api_v1_routes())
        .with_state(state)
        .layer(middleware_stack())
}
```
