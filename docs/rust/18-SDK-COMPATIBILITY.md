# 18. SDK Compatibility

## Overview

OpenAlgo has a mature ecosystem of SDKs and integrations built on top of the REST API and WebSocket endpoints. The Rust desktop application **MUST** maintain 100% API compatibility to ensure all existing SDKs, plugins, and integrations continue to work without modification.

## Existing SDK Ecosystem

### 1. Python SDK
- **Repository**: OpenAlgo Python SDK
- **Purpose**: Algorithmic trading, backtesting, automation scripts
- **Usage**: Import as `openalgo` package

### 2. Go SDK
- **Repository**: OpenAlgo Go SDK
- **Purpose**: High-performance trading applications
- **Usage**: Import as Go module

### 3. Node.js SDK
- **Repository**: OpenAlgo Node SDK
- **Purpose**: Web applications, Discord/Telegram bots
- **Usage**: npm package

### 4. Excel Add-in
- **Repository**: OpenAlgo Excel Add-in
- **Purpose**: Trading from spreadsheets, portfolio tracking
- **Usage**: Excel VBA integration

### 5. Amibroker Plugin
- **Repository**: OpenAlgo Amibroker Plugin
- **Purpose**: Amibroker AFL strategy execution
- **Usage**: DLL plugin for Amibroker

---

## API Compatibility Requirements

### REST API Endpoints

The Rust implementation MUST expose identical endpoints:

```
Base URL: http://{host}:{port}/api/v1/
```

| Endpoint | Method | Python SDK Function | Description |
|----------|--------|---------------------|-------------|
| `/placeorder` | POST | `place_order()` | Place standard order |
| `/placesmartorder` | POST | `place_smart_order()` | Smart order with position sizing |
| `/basketorder` | POST | `place_basket_order()` | Multi-leg basket orders |
| `/splitorder` | POST | `split_order()` | Split large orders |
| `/modifyorder` | POST | `modify_order()` | Modify pending order |
| `/cancelorder` | POST | `cancel_order()` | Cancel pending order |
| `/cancelallorder` | POST | `cancel_all_orders()` | Cancel all pending orders |
| `/closeposition` | POST | `close_position()` | Close specific position |
| `/orderbook` | POST | `get_order_book()` | Get order history |
| `/tradebook` | POST | `get_trade_book()` | Get executed trades |
| `/positionbook` | POST | `get_positions()` | Get open positions |
| `/holdings` | POST | `get_holdings()` | Get long-term holdings |
| `/funds` | POST | `get_funds()` | Get account funds/margin |
| `/quotes` | POST | `get_quotes()` | Get real-time quotes |
| `/depth` | POST | `get_depth()` | Get market depth (L2) |
| `/history` | POST | `get_history()` | Get historical candles |
| `/intervals` | POST | `get_intervals()` | Get supported intervals |
| `/optionchain` | POST | `get_option_chain()` | Get options chain |

### Request/Response Format

**CRITICAL**: All request/response schemas must match exactly.

#### Example: Place Order Request

```json
{
  "apikey": "your_api_key",
  "strategy": "Python Strategy",
  "symbol": "RELIANCE",
  "action": "BUY",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "10"
}
```

#### Example: Place Order Response

```json
{
  "status": "success",
  "orderid": "230901000012345"
}
```

#### Error Response Format

```json
{
  "status": "error",
  "message": "Invalid API key"
}
```

---

## WebSocket Compatibility

### Connection URL

```
ws://{websocket_host}:{websocket_port}
```

Default: `ws://127.0.0.1:8765`

### Message Format

```json
{
  "type": "ltp",
  "data": {
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "ltp": 2456.75,
    "timestamp": 1693555200000
  }
}
```

### Subscription Message

```json
{
  "action": "subscribe",
  "symbols": ["NSE:RELIANCE", "NSE:TCS"]
}
```

### Unsubscription Message

```json
{
  "action": "unsubscribe",
  "symbols": ["NSE:RELIANCE"]
}
```

---

## Rust API Implementation

### Axum Router Setup

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
        .route("/basketorder", post(orders::basket_order))
        .route("/splitorder", post(orders::split_order))
        .route("/modifyorder", post(orders::modify_order))
        .route("/cancelorder", post(orders::cancel_order))
        .route("/cancelallorder", post(orders::cancel_all_orders))
        .route("/closeposition", post(orders::close_position))

        // Account Data
        .route("/orderbook", post(account::order_book))
        .route("/tradebook", post(account::trade_book))
        .route("/positionbook", post(account::positions))
        .route("/holdings", post(account::holdings))
        .route("/funds", post(account::funds))

        // Market Data
        .route("/quotes", post(market::quotes))
        .route("/depth", post(market::depth))
        .route("/history", post(market::history))
        .route("/intervals", post(market::intervals))
        .route("/optionchain", post(market::option_chain))
}

pub fn build_api_router(state: AppState) -> Router {
    Router::new()
        .nest("/api/v1", api_v1_routes())
        .with_state(state)
}
```

### Request Schema Compatibility

```rust
// src-tauri/src/api/schemas/order.rs

use serde::{Deserialize, Serialize};

/// Place Order Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct PlaceOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub symbol: String,
    pub action: String,
    pub exchange: String,
    pub pricetype: String,
    pub product: String,
    pub quantity: String,
    #[serde(default)]
    pub price: String,
    #[serde(default)]
    pub trigger_price: String,
    #[serde(default)]
    pub disclosed_quantity: String,
}

/// Smart Order Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct SmartOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub symbol: String,
    pub action: String,
    pub exchange: String,
    pub pricetype: String,
    pub product: String,
    pub quantity: String,
    pub position_size: String,
    #[serde(default)]
    pub price: String,
    #[serde(default)]
    pub trigger_price: String,
    #[serde(default)]
    pub disclosed_quantity: String,
}

/// Basket Order Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct BasketOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub orders: Vec<BasketOrderItem>,
}

#[derive(Debug, Deserialize)]
pub struct BasketOrderItem {
    pub symbol: String,
    pub exchange: String,
    pub action: String,
    pub quantity: String,
    pub pricetype: String,
    pub product: String,
    #[serde(default)]
    pub price: String,
    #[serde(default)]
    pub trigger_price: String,
}

/// Order Response - MUST match Python SDK exactly
#[derive(Debug, Serialize)]
pub struct OrderResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub orderid: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

impl OrderResponse {
    pub fn success(orderid: String) -> Self {
        Self {
            status: "success".to_string(),
            orderid: Some(orderid),
            message: None,
        }
    }

    pub fn error(message: String) -> Self {
        Self {
            status: "error".to_string(),
            orderid: None,
            message: Some(message),
        }
    }
}
```

### Market Data Schema Compatibility

```rust
// src-tauri/src/api/schemas/market.rs

/// Quotes Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct QuotesRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: String,
}

/// Quotes Response - MUST match Python SDK exactly
#[derive(Debug, Serialize)]
pub struct QuotesResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<QuotesData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct QuotesData {
    pub ltp: f64,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
}

/// History Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct HistoryRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: String,
    pub interval: String,
    pub start: String,       // Format: YYYY-MM-DD
    pub end: String,         // Format: YYYY-MM-DD
}

/// History Response - MUST match Python SDK exactly
#[derive(Debug, Serialize)]
pub struct HistoryResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Vec<CandleData>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct CandleData {
    pub timestamp: String,
    pub open: f64,
    pub high: f64,
    pub low: f64,
    pub close: f64,
    pub volume: i64,
}

/// Depth Request - MUST match Python SDK exactly
#[derive(Debug, Deserialize)]
pub struct DepthRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: String,
}

/// Depth Response - MUST match Python SDK exactly
#[derive(Debug, Serialize)]
pub struct DepthResponse {
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<DepthData>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct DepthData {
    pub bids: Vec<DepthLevel>,
    pub asks: Vec<DepthLevel>,
    pub totalbuyqty: i64,
    pub totalsellqty: i64,
}

#[derive(Debug, Serialize)]
pub struct DepthLevel {
    pub price: f64,
    pub quantity: i64,
    pub orders: i32,
}
```

---

## SDK Usage Examples

### Python SDK

```python
from openalgo import api

# Initialize client
client = api("http://localhost:5000", "your_api_key")

# Place order
response = client.place_order(
    symbol="RELIANCE",
    exchange="NSE",
    action="BUY",
    quantity=10,
    pricetype="MARKET",
    product="MIS"
)
print(response)  # {'status': 'success', 'orderid': '230901000012345'}

# Get positions
positions = client.get_positions()
for pos in positions['data']:
    print(f"{pos['symbol']}: {pos['netqty']} @ {pos['avgprice']}")

# Subscribe to WebSocket
def on_tick(data):
    print(f"LTP: {data['ltp']}")

client.subscribe(["NSE:RELIANCE", "NSE:TCS"], on_tick)
```

### Go SDK

```go
package main

import (
    "fmt"
    "github.com/openalgo/go-sdk"
)

func main() {
    client := openalgo.NewClient("http://localhost:5000", "your_api_key")

    // Place order
    order := openalgo.PlaceOrderRequest{
        Symbol:    "RELIANCE",
        Exchange:  "NSE",
        Action:    "BUY",
        Quantity:  10,
        PriceType: "MARKET",
        Product:   "MIS",
    }

    resp, err := client.PlaceOrder(order)
    if err != nil {
        log.Fatal(err)
    }
    fmt.Printf("Order ID: %s\n", resp.OrderID)
}
```

### Node.js SDK

```javascript
const OpenAlgo = require('openalgo');

const client = new OpenAlgo({
  baseUrl: 'http://localhost:5000',
  apiKey: 'your_api_key'
});

// Place order
const response = await client.placeOrder({
  symbol: 'RELIANCE',
  exchange: 'NSE',
  action: 'BUY',
  quantity: 10,
  pricetype: 'MARKET',
  product: 'MIS'
});

console.log(response);

// WebSocket subscription
client.subscribe(['NSE:RELIANCE'], (tick) => {
  console.log(`LTP: ${tick.ltp}`);
});
```

### Excel VBA

```vba
Sub PlaceOrder()
    Dim http As Object
    Set http = CreateObject("MSXML2.XMLHTTP")

    Dim url As String
    url = "http://localhost:5000/api/v1/placeorder"

    Dim payload As String
    payload = "{""apikey"":""your_api_key"",""strategy"":""Excel""," & _
              """symbol"":""RELIANCE"",""exchange"":""NSE""," & _
              """action"":""BUY"",""quantity"":""10""," & _
              """pricetype"":""MARKET"",""product"":""MIS""}"

    http.Open "POST", url, False
    http.setRequestHeader "Content-Type", "application/json"
    http.send payload

    MsgBox http.responseText
End Sub
```

### Amibroker AFL

```afl
// OpenAlgo Integration
api_key = ParamStr("API Key", "your_api_key");
host = ParamStr("Host", "http://localhost:5000");

// Place order via HTTP
function PlaceOrder(symbol, action, qty) {
    url = host + "/api/v1/placeorder";
    payload = "{\"apikey\":\"" + api_key + "\"," +
              "\"strategy\":\"Amibroker\"," +
              "\"symbol\":\"" + symbol + "\"," +
              "\"exchange\":\"NSE\"," +
              "\"action\":\"" + action + "\"," +
              "\"quantity\":\"" + NumToStr(qty, 0) + "\"," +
              "\"pricetype\":\"MARKET\"," +
              "\"product\":\"MIS\"}";

    response = InternetPostRequest(url, payload);
    return response;
}

// Trading logic
Buy = Cross(MA(C, 10), MA(C, 50));
Sell = Cross(MA(C, 50), MA(C, 10));

if (Buy) {
    PlaceOrder(Name(), "BUY", 10);
}
if (Sell) {
    PlaceOrder(Name(), "SELL", 10);
}
```

---

## Testing SDK Compatibility

### Integration Test Suite

```rust
// tests/sdk_compatibility.rs

#[tokio::test]
async fn test_python_sdk_place_order_format() {
    let app = create_test_app().await;

    // Exact payload format from Python SDK
    let payload = json!({
        "apikey": "test_api_key",
        "strategy": "Python Strategy",
        "symbol": "RELIANCE",
        "action": "BUY",
        "exchange": "NSE",
        "pricetype": "MARKET",
        "product": "MIS",
        "quantity": "10"
    });

    let response = app.post("/api/v1/placeorder")
        .json(&payload)
        .await;

    assert_eq!(response.status(), 200);

    let body: serde_json::Value = response.json().await;
    assert_eq!(body["status"], "success");
    assert!(body["orderid"].is_string());
}

#[tokio::test]
async fn test_python_sdk_error_format() {
    let app = create_test_app().await;

    // Invalid API key
    let payload = json!({
        "apikey": "invalid_key",
        "strategy": "Test",
        "symbol": "RELIANCE",
        "action": "BUY",
        "exchange": "NSE",
        "pricetype": "MARKET",
        "product": "MIS",
        "quantity": "10"
    });

    let response = app.post("/api/v1/placeorder")
        .json(&payload)
        .await;

    assert_eq!(response.status(), 401);

    let body: serde_json::Value = response.json().await;
    assert_eq!(body["status"], "error");
    assert!(body["message"].is_string());
}

#[tokio::test]
async fn test_websocket_message_format() {
    let (mut tx, mut rx) = connect_websocket().await;

    // Subscribe message format
    tx.send(json!({
        "action": "subscribe",
        "symbols": ["NSE:RELIANCE"]
    }).to_string()).await.unwrap();

    // Receive tick
    let msg = rx.next().await.unwrap();
    let tick: serde_json::Value = serde_json::from_str(&msg).unwrap();

    assert_eq!(tick["type"], "ltp");
    assert!(tick["data"]["symbol"].is_string());
    assert!(tick["data"]["ltp"].is_number());
}
```

### Compatibility Test Matrix

Run these tests against both Python and Rust implementations:

```rust
#[test_matrix(
    endpoint = ["/placeorder", "/placesmartorder", "/basketorder"],
    sdk = ["python", "go", "node"]
)]
async fn test_order_endpoint_compatibility(endpoint: &str, sdk: &str) {
    let payload = get_test_payload(sdk, endpoint);

    let python_response = python_api.post(endpoint, payload.clone()).await;
    let rust_response = rust_api.post(endpoint, payload).await;

    assert_eq!(
        python_response.status_code(),
        rust_response.status_code(),
        "Status code mismatch for {} with {} SDK",
        endpoint, sdk
    );

    let python_body: Value = python_response.json().await;
    let rust_body: Value = rust_response.json().await;

    // Compare response structure (not values)
    assert_same_structure(&python_body, &rust_body);
}
```

---

## Migration Guide

### For SDK Users

When migrating from Python OpenAlgo to Rust Desktop:

1. **No SDK changes required** - All existing SDKs work with the Rust implementation
2. **Update base URL if needed** - Default ports remain the same (5000 for HTTP, 8765 for WebSocket)
3. **API key format unchanged** - Same 32-character hex API keys
4. **WebSocket protocol identical** - Same message format and subscription model

### Configuration Changes

| Setting | Python OpenAlgo | Rust Desktop |
|---------|-----------------|--------------|
| HTTP Port | `.env: FLASK_PORT=5000` | Settings UI or `network.http_port=5000` |
| WS Port | `.env: WEBSOCKET_PORT=8765` | Settings UI or `network.websocket_port=8765` |
| Host | `.env: FLASK_HOST_IP=127.0.0.1` | Settings UI or `network.http_host=127.0.0.1` |

### Breaking Changes

**NONE** - The Rust implementation maintains 100% backward compatibility.

---

## Versioning Strategy

### API Version

- Current: `v1`
- Path: `/api/v1/*`
- Future versions will use `/api/v2/*` while maintaining `/api/v1/*`

### SDK Version Compatibility

| SDK Version | OpenAlgo Python | OpenAlgo Rust |
|-------------|-----------------|---------------|
| 1.x | Compatible | Compatible |
| 2.x | Compatible | Compatible |

### Deprecation Policy

1. New API versions announced 6 months in advance
2. Old versions supported for 12 months after deprecation
3. SDK updates provided before deprecation
4. Migration guides published for breaking changes
