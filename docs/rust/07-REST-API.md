# OpenAlgo Desktop - REST API Specification

## Overview

This document defines the complete REST API for OpenAlgo Desktop, maintaining 100% compatibility with the existing Python/Flask API. The embedded HTTP server (using `axum`) exposes these endpoints for external integration with TradingView, ChartInk, and custom trading systems.

---

## API Configuration

### Server Settings
```rust
pub struct ApiServerConfig {
    pub host: String,           // Default: "127.0.0.1"
    pub port: u16,              // Default: 5000
    pub rate_limit_api: u32,    // Default: 10 per second
    pub rate_limit_order: u32,  // Default: 10 per second
    pub rate_limit_smart: u32,  // Default: 2 per second
    pub rate_limit_greeks: u32, // Default: 30 per minute
}
```

### Authentication
All API endpoints require the `apikey` field in the request body (POST) or query parameter (GET).

```rust
pub fn verify_api_key(api_key: &str) -> Result<UserId, ApiError> {
    // Validate API key against database
    // Returns user_id if valid, ApiError::Unauthorized if invalid
}
```

---

## API Endpoints Summary

| Category | Endpoint | Method | Rate Limit | Description |
|----------|----------|--------|------------|-------------|
| **Order Management** | | | | |
| | `/api/v1/placeorder` | POST | 10/s | Place a regular order |
| | `/api/v1/placesmartorder` | POST | 2/s | Place a position-sized order |
| | `/api/v1/modifyorder` | POST | 10/s | Modify an existing order |
| | `/api/v1/cancelorder` | POST | 10/s | Cancel a pending order |
| | `/api/v1/cancelallorder` | POST | 10/s | Cancel all orders for a strategy |
| | `/api/v1/closeposition` | POST | 10/s | Close all positions for a strategy |
| | `/api/v1/basketorder` | POST | 10/s | Place multiple orders |
| | `/api/v1/splitorder` | POST | 10/s | Split large order into chunks |
| **Options Trading** | | | | |
| | `/api/v1/optionsorder` | POST | 10/s | Place order by offset (ATM/ITM/OTM) |
| | `/api/v1/optionsmultiorder` | POST | 10/s | Place multi-leg options orders |
| | `/api/v1/optionsymbol` | POST | 10/s | Resolve option symbol from offset |
| | `/api/v1/optionchain` | POST | 10/s | Get option chain with quotes |
| | `/api/v1/optiongreeks` | POST | 30/min | Calculate option Greeks |
| | `/api/v1/syntheticfuture` | POST | 10/s | Calculate synthetic future price |
| **Account Data** | | | | |
| | `/api/v1/orderbook` | POST | 10/s | Get all orders |
| | `/api/v1/tradebook` | POST | 10/s | Get executed trades |
| | `/api/v1/positionbook` | POST | 10/s | Get open positions |
| | `/api/v1/holdings` | POST | 10/s | Get holdings (delivery) |
| | `/api/v1/funds` | POST | 10/s | Get available funds/margins |
| | `/api/v1/orderstatus` | POST | 10/s | Get specific order status |
| | `/api/v1/openposition` | POST | 10/s | Get specific position |
| **Market Data** | | | | |
| | `/api/v1/quotes` | POST | 10/s | Get real-time quote |
| | `/api/v1/multiquotes` | POST | 10/s | Get quotes for multiple symbols |
| | `/api/v1/depth` | POST | 10/s | Get market depth (Level 5) |
| | `/api/v1/history` | POST | 10/s | Get historical OHLCV data |
| | `/api/v1/ticker` | POST | 10/s | Get chart data (TradingView format) |
| **Symbol/Instrument** | | | | |
| | `/api/v1/symbol` | POST | 10/s | Get symbol token |
| | `/api/v1/search` | POST | 10/s | Search symbols |
| | `/api/v1/instruments` | GET | 10/s | Download all instruments |
| | `/api/v1/expiry` | POST | 10/s | Get expiry dates |
| | `/api/v1/intervals` | POST | 10/s | Get supported intervals |
| **Utilities** | | | | |
| | `/api/v1/margin` | POST | 50/s | Calculate margin requirement |
| | `/api/v1/ping` | POST | 10/s | Health check |
| | `/api/v1/analyzer` | POST | 10/s | Get sandbox mode status |
| | `/api/v1/analyzer/toggle` | POST | 10/s | Toggle sandbox mode |

---

## Request/Response Schemas

### Common Response Format

```rust
#[derive(Serialize)]
pub struct ApiResponse<T> {
    pub status: String,         // "success" or "error"
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    #[serde(flatten)]
    pub data: Option<T>,
}
```

---

## Order Management APIs

### 1. Place Order

**Endpoint**: `POST /api/v1/placeorder`

**Request Schema**:
```rust
#[derive(Deserialize, Validate)]
pub struct PlaceOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub exchange: Exchange,         // NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX
    pub symbol: String,
    #[validate(custom = "validate_action")]
    pub action: Action,             // BUY, SELL
    #[validate(range(min = 1))]
    pub quantity: u32,
    #[serde(default = "default_market")]
    pub pricetype: PriceType,       // MARKET, LIMIT, SL, SL-M
    #[serde(default = "default_mis")]
    pub product: Product,           // MIS, NRML, CNC
    #[serde(default)]
    pub price: f64,                 // For LIMIT orders
    #[serde(default)]
    pub trigger_price: f64,         // For SL/SL-M orders
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

**Response (Success)**:
```json
{
    "status": "success",
    "orderid": "240612000123456"
}
```

**Response (Error)**:
```json
{
    "status": "error",
    "message": "Invalid exchange. Must be one of: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX"
}
```

### 2. Place Smart Order

**Endpoint**: `POST /api/v1/placesmartorder`

Smart orders automatically adjust quantity based on target position size.

**Request Schema**:
```rust
#[derive(Deserialize, Validate)]
pub struct SmartOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub exchange: Exchange,
    pub symbol: String,
    pub action: Action,
    #[validate(range(min = 0))]
    pub quantity: u32,              // Additional quantity
    pub position_size: i32,         // Target position size (can be negative for short)
    #[serde(default = "default_market")]
    pub pricetype: PriceType,
    #[serde(default = "default_mis")]
    pub product: Product,
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub trigger_price: f64,
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

**Logic**:
- If current position < target: BUY difference
- If current position > target: SELL difference
- If current position == target: No action

### 3. Modify Order

**Endpoint**: `POST /api/v1/modifyorder`

**Request Schema**:
```rust
#[derive(Deserialize, Validate)]
pub struct ModifyOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub exchange: Exchange,
    pub symbol: String,
    pub orderid: String,
    pub action: Action,
    pub product: Product,
    pub pricetype: PriceType,
    #[validate(range(min = 0.0))]
    pub price: f64,
    #[validate(range(min = 1))]
    pub quantity: u32,
    #[validate(range(min = 0))]
    pub disclosed_quantity: u32,
    #[validate(range(min = 0.0))]
    pub trigger_price: f64,
}
```

### 4. Cancel Order

**Endpoint**: `POST /api/v1/cancelorder`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct CancelOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub orderid: String,
}
```

### 5. Cancel All Orders

**Endpoint**: `POST /api/v1/cancelallorder`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct CancelAllOrderRequest {
    pub apikey: String,
    pub strategy: String,
}
```

### 6. Close Position

**Endpoint**: `POST /api/v1/closeposition`

Closes all positions for a specific strategy.

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct ClosePositionRequest {
    pub apikey: String,
    pub strategy: String,
}
```

### 7. Basket Order

**Endpoint**: `POST /api/v1/basketorder`

Place multiple orders in a single request.

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct BasketOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub orders: Vec<BasketOrderItem>,
}

#[derive(Deserialize, Validate)]
pub struct BasketOrderItem {
    pub exchange: Exchange,
    pub symbol: String,
    pub action: Action,
    #[validate(range(min = 1))]
    pub quantity: u32,
    #[serde(default = "default_market")]
    pub pricetype: PriceType,
    #[serde(default = "default_mis")]
    pub product: Product,
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub trigger_price: f64,
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

**Response**:
```json
{
    "status": "success",
    "results": [
        {"symbol": "RELIANCE", "orderid": "123", "status": "success"},
        {"symbol": "TCS", "orderid": "124", "status": "success"},
        {"symbol": "INVALID", "status": "error", "message": "Symbol not found"}
    ]
}
```

### 8. Split Order

**Endpoint**: `POST /api/v1/splitorder`

Split a large order into smaller chunks.

**Request Schema**:
```rust
#[derive(Deserialize, Validate)]
pub struct SplitOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub exchange: Exchange,
    pub symbol: String,
    pub action: Action,
    #[validate(range(min = 1))]
    pub quantity: u32,          // Total quantity
    #[validate(range(min = 1))]
    pub splitsize: u32,         // Size of each split
    #[serde(default = "default_market")]
    pub pricetype: PriceType,
    #[serde(default = "default_mis")]
    pub product: Product,
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub trigger_price: f64,
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

---

## Options Trading APIs

### 1. Options Order

**Endpoint**: `POST /api/v1/optionsorder`

Place an options order by specifying offset from ATM.

**Request Schema**:
```rust
#[derive(Deserialize, Validate)]
pub struct OptionsOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub underlying: String,         // NIFTY, BANKNIFTY, RELIANCE, or NIFTY28NOV24FUT
    pub exchange: Exchange,         // NSE_INDEX, NSE, BSE_INDEX, BSE, NFO, BFO
    pub expiry_date: Option<String>, // DDMMMYY format, optional if underlying has expiry
    pub strike_int: Option<u32>,    // Strike interval (optional, uses DB if omitted)
    #[validate(custom = "validate_offset")]
    pub offset: String,             // ATM, ITM1-ITM50, OTM1-OTM50
    pub option_type: OptionType,    // CE, PE
    pub action: Action,
    #[validate(range(min = 1))]
    pub quantity: u32,
    #[serde(default = "default_market")]
    pub pricetype: PriceType,
    #[serde(default = "default_mis")]
    pub product: Product,           // MIS, NRML only for options
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub trigger_price: f64,
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

**Offset Validation**:
```rust
fn validate_offset(offset: &str) -> Result<(), ValidationError> {
    let upper = offset.to_uppercase();
    if upper == "ATM" {
        return Ok(());
    }

    // ITM1-ITM50 or OTM1-OTM50
    let re = Regex::new(r"^(ITM|OTM)([1-9]|[1-4][0-9]|50)$").unwrap();
    if re.is_match(&upper) {
        Ok(())
    } else {
        Err(ValidationError::new("Offset must be ATM, ITM1-ITM50, or OTM1-OTM50"))
    }
}
```

**Response**:
```json
{
    "status": "success",
    "orderid": "240123000001234",
    "symbol": "NIFTY28NOV2423500CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23587.50,
    "offset": "ITM2",
    "option_type": "CE"
}
```

### 2. Options Multi-Order

**Endpoint**: `POST /api/v1/optionsmultiorder`

Place multi-leg options strategies (spreads, straddles, etc.)

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OptionsMultiOrderRequest {
    pub apikey: String,
    pub strategy: String,
    pub underlying: String,
    pub exchange: Exchange,
    pub expiry_date: Option<String>,
    pub strike_int: Option<u32>,
    #[validate(length(min = 1, max = 20))]
    pub legs: Vec<OptionsLeg>,
}

#[derive(Deserialize)]
pub struct OptionsLeg {
    pub offset: String,
    pub option_type: OptionType,
    pub action: Action,
    pub quantity: u32,
    pub expiry_date: Option<String>,    // Per-leg expiry for calendar spreads
    #[serde(default = "default_market")]
    pub pricetype: PriceType,
    #[serde(default = "default_mis")]
    pub product: Product,
    #[serde(default)]
    pub price: f64,
    #[serde(default)]
    pub trigger_price: f64,
    #[serde(default)]
    pub disclosed_quantity: u32,
}
```

### 3. Option Symbol Lookup

**Endpoint**: `POST /api/v1/optionsymbol`

Resolve option symbol from underlying and offset.

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OptionSymbolRequest {
    pub apikey: String,
    pub underlying: String,
    pub exchange: Exchange,
    pub expiry_date: Option<String>,
    pub strike_int: Option<u32>,
    pub offset: String,
    pub option_type: OptionType,
}
```

**Response**:
```json
{
    "status": "success",
    "symbol": "NIFTY28NOV2423500CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "underlying_ltp": 23587.50,
    "strike": 23500,
    "offset": "ITM2",
    "option_type": "CE"
}
```

### 4. Option Chain

**Endpoint**: `POST /api/v1/optionchain`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OptionChainRequest {
    pub apikey: String,
    pub underlying: String,
    pub exchange: Exchange,
    pub expiry_date: String,            // DDMMMYY format (mandatory)
    pub strike_count: Option<u32>,      // Strikes above/below ATM (optional)
}
```

**Response**:
```json
{
    "status": "success",
    "underlying": "NIFTY",
    "underlying_ltp": 24250.50,
    "expiry_date": "30DEC25",
    "atm_strike": 24250.0,
    "chain": [
        {
            "strike": 24000.0,
            "ce": {
                "symbol": "NIFTY30DEC2524000CE",
                "label": "ITM5",
                "ltp": 320.50,
                "bid": 320.00,
                "ask": 321.00
            },
            "pe": {
                "symbol": "NIFTY30DEC2524000PE",
                "label": "OTM5",
                "ltp": 85.25,
                "bid": 85.00,
                "ask": 85.50
            }
        }
    ]
}
```

### 5. Option Greeks

**Endpoint**: `POST /api/v1/optiongreeks`

Calculate option Greeks using Black-76 model.

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OptionGreeksRequest {
    pub apikey: String,
    pub symbol: String,                 // Option symbol (e.g., NIFTY28NOV2424000CE)
    pub exchange: Exchange,             // NFO, BFO, CDS, MCX
    pub interest_rate: Option<f64>,     // Risk-free rate (annualized %)
    pub forward_price: Option<f64>,     // Custom forward price
    pub underlying_symbol: Option<String>,
    pub underlying_exchange: Option<String>,
    pub expiry_time: Option<String>,    // HH:MM format
}
```

**Response**:
```json
{
    "status": "success",
    "symbol": "NIFTY02DEC2524000CE",
    "exchange": "NFO",
    "underlying": "NIFTY",
    "strike": 24000,
    "option_type": "CE",
    "expiry_date": "02-Dec-2025",
    "days_to_expiry": 30.5,
    "forward_price": 24550.75,
    "option_price": 296.05,
    "interest_rate": 7.0,
    "implied_volatility": 15.25,
    "greeks": {
        "delta": 0.5234,
        "gamma": 0.000125,
        "theta": -4.9678,
        "vega": 30.7654,
        "rho": 0.001234
    }
}
```

### 6. Synthetic Future

**Endpoint**: `POST /api/v1/syntheticfuture`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct SyntheticFutureRequest {
    pub apikey: String,
    pub underlying: String,
    pub exchange: Exchange,
    pub expiry_date: String,        // DDMMMYY format
}
```

---

## Account Data APIs

### 1. Order Book

**Endpoint**: `POST /api/v1/orderbook`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "orderid": "240612000123456",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 100,
            "price": 2850.50,
            "pricetype": "LIMIT",
            "product": "MIS",
            "status": "OPEN",
            "filled_quantity": 0,
            "pending_quantity": 100,
            "order_timestamp": "2024-12-04 10:30:00"
        }
    ]
}
```

### 2. Trade Book

**Endpoint**: `POST /api/v1/tradebook`

**Request**: `{ "apikey": "..." }`

### 3. Position Book

**Endpoint**: `POST /api/v1/positionbook`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 100,
            "average_price": 2850.50,
            "ltp": 2860.00,
            "pnl": 950.00,
            "pnl_percent": 0.33
        }
    ]
}
```

### 4. Holdings

**Endpoint**: `POST /api/v1/holdings`

**Request**: `{ "apikey": "..." }`

### 5. Funds

**Endpoint**: `POST /api/v1/funds`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "data": {
        "available_balance": 500000.00,
        "used_margin": 150000.00,
        "total_balance": 650000.00,
        "realized_pnl": 25000.00,
        "unrealized_pnl": 5000.00
    }
}
```

### 6. Order Status

**Endpoint**: `POST /api/v1/orderstatus`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OrderStatusRequest {
    pub apikey: String,
    pub strategy: String,
    pub orderid: String,
}
```

### 7. Open Position

**Endpoint**: `POST /api/v1/openposition`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct OpenPositionRequest {
    pub apikey: String,
    pub strategy: String,
    pub symbol: String,
    pub exchange: Exchange,
    pub product: Product,
}
```

---

## Market Data APIs

### 1. Quotes

**Endpoint**: `POST /api/v1/quotes`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct QuotesRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: Exchange,
}
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "ltp": 2850.50,
        "open": 2840.00,
        "high": 2865.00,
        "low": 2835.00,
        "close": 2848.25,
        "volume": 1500000,
        "bid": 2850.45,
        "ask": 2850.55,
        "bid_qty": 500,
        "ask_qty": 750,
        "oi": 0,
        "prev_oi": 0
    }
}
```

### 2. Multi-Quotes

**Endpoint**: `POST /api/v1/multiquotes`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct MultiQuotesRequest {
    pub apikey: String,
    pub symbols: Vec<SymbolExchangePair>,
}

#[derive(Deserialize)]
pub struct SymbolExchangePair {
    pub symbol: String,
    pub exchange: String,
}
```

### 3. Market Depth

**Endpoint**: `POST /api/v1/depth`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct DepthRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: Exchange,
}
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "symbol": "RELIANCE",
        "exchange": "NSE",
        "bids": [
            {"price": 2850.45, "quantity": 500},
            {"price": 2850.40, "quantity": 300},
            {"price": 2850.35, "quantity": 200},
            {"price": 2850.30, "quantity": 400},
            {"price": 2850.25, "quantity": 600}
        ],
        "asks": [
            {"price": 2850.55, "quantity": 750},
            {"price": 2850.60, "quantity": 400},
            {"price": 2850.65, "quantity": 300},
            {"price": 2850.70, "quantity": 500},
            {"price": 2850.75, "quantity": 200}
        ]
    }
}
```

### 4. Historical Data

**Endpoint**: `POST /api/v1/history`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct HistoryRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: Exchange,
    pub interval: Interval,     // 1s, 5s, 10s, 15s, 30s, 45s,
                                // 1m, 2m, 3m, 5m, 10m, 15m, 20m, 30m,
                                // 1h, 2h, 3h, 4h, D, W, M
    pub start_date: NaiveDate,  // YYYY-MM-DD
    pub end_date: NaiveDate,    // YYYY-MM-DD
}
```

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "datetime": "2024-12-04 09:15:00",
            "open": 2840.00,
            "high": 2845.00,
            "low": 2838.00,
            "close": 2843.50,
            "volume": 15000,
            "oi": 125000
        }
    ]
}
```

### 5. Ticker (TradingView Format)

**Endpoint**: `POST /api/v1/ticker`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct TickerRequest {
    pub apikey: String,
    pub symbol: String,         // exchange:symbol format
    pub interval: String,       // 1m, 5m, 15m, 30m, 1h, 4h, D, W, M
    pub from: String,           // YYYY-MM-DD or timestamp
    pub to: String,             // YYYY-MM-DD or timestamp
    #[serde(default = "default_true")]
    pub adjusted: bool,
    #[serde(default = "default_asc")]
    pub sort: String,
}
```

---

## Symbol/Instrument APIs

### 1. Symbol Lookup

**Endpoint**: `POST /api/v1/symbol`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct SymbolRequest {
    pub apikey: String,
    pub symbol: String,
    pub exchange: Exchange,
}
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "symbol": "RELIANCE",
        "token": "2885",
        "exchange": "NSE",
        "lot_size": 1,
        "tick_size": 0.05,
        "instrument_type": "EQ"
    }
}
```

### 2. Search Symbols

**Endpoint**: `POST /api/v1/search`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct SearchRequest {
    pub apikey: String,
    pub query: String,
    pub exchange: Option<String>,   // Optional filter
}
```

### 3. Download Instruments

**Endpoint**: `GET /api/v1/instruments`

**Query Parameters**:
- `apikey` (required): API key
- `exchange` (optional): Filter by exchange
- `format` (optional): `json` or `csv` (default: json)

### 4. Get Expiry Dates

**Endpoint**: `POST /api/v1/expiry`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct ExpiryRequest {
    pub apikey: String,
    pub symbol: String,             // Underlying symbol
    pub exchange: Exchange,         // NFO, BFO, MCX, CDS
    pub instrumenttype: String,     // "futures" or "options"
}
```

### 5. Get Intervals

**Endpoint**: `POST /api/v1/intervals`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "intervals": [
        "1s", "5s", "10s", "15s", "30s", "45s",
        "1m", "2m", "3m", "5m", "10m", "15m", "20m", "30m",
        "1h", "2h", "3h", "4h",
        "D", "W", "M"
    ]
}
```

---

## Utility APIs

### 1. Margin Calculator

**Endpoint**: `POST /api/v1/margin`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct MarginRequest {
    pub apikey: String,
    pub positions: Vec<MarginPosition>,
}

#[derive(Deserialize)]
pub struct MarginPosition {
    pub symbol: String,
    pub exchange: Exchange,
    pub action: Action,
    pub quantity: String,       // String for API compatibility
    pub product: Product,
    pub pricetype: PriceType,
    #[serde(default = "default_zero_str")]
    pub price: String,
    #[serde(default = "default_zero_str")]
    pub trigger_price: String,
}
```

### 2. Ping (Health Check)

**Endpoint**: `POST /api/v1/ping`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "message": "pong",
    "version": "1.0.0",
    "broker": "angelone"
}
```

### 3. Analyzer Status

**Endpoint**: `POST /api/v1/analyzer`

**Request**: `{ "apikey": "..." }`

**Response**:
```json
{
    "status": "success",
    "mode": "live",
    "analyze_mode": false,
    "statistics": {
        "total_orders": 150,
        "pending_orders": 5,
        "completed_orders": 140,
        "cancelled_orders": 5
    }
}
```

### 4. Toggle Analyzer Mode

**Endpoint**: `POST /api/v1/analyzer/toggle`

**Request Schema**:
```rust
#[derive(Deserialize)]
pub struct AnalyzerToggleRequest {
    pub apikey: String,
    pub mode: bool,         // true = sandbox, false = live
}
```

---

## Enums and Types

```rust
#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "UPPERCASE")]
pub enum Exchange {
    Nse,
    Bse,
    Nfo,
    Bfo,
    Cds,
    Bcd,
    Mcx,
    Ncdex,
    #[serde(rename = "NSE_INDEX")]
    NseIndex,
    #[serde(rename = "BSE_INDEX")]
    BseIndex,
}

#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "UPPERCASE")]
pub enum Action {
    Buy,
    Sell,
}

#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "UPPERCASE")]
pub enum PriceType {
    Market,
    Limit,
    Sl,
    #[serde(rename = "SL-M")]
    SlM,
}

#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "UPPERCASE")]
pub enum Product {
    Mis,
    Nrml,
    Cnc,
}

#[derive(Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "UPPERCASE")]
pub enum OptionType {
    Ce,
    Pe,
}

#[derive(Deserialize, Serialize, Clone)]
pub enum Interval {
    #[serde(rename = "1s")]
    Sec1,
    #[serde(rename = "5s")]
    Sec5,
    // ... other intervals
    #[serde(rename = "D")]
    Day,
    #[serde(rename = "W")]
    Week,
    #[serde(rename = "M")]
    Month,
}
```

---

## Error Codes

| Code | Status | Description |
|------|--------|-------------|
| 200 | OK | Request successful |
| 400 | Bad Request | Validation error, missing fields |
| 401 | Unauthorized | Invalid API key |
| 403 | Forbidden | Operation not allowed (e.g., semi-auto mode) |
| 404 | Not Found | Resource not found |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Error | Server error |

---

## Rate Limiting

Rate limits are enforced per API key using a sliding window algorithm.

```rust
pub struct RateLimiter {
    requests: HashMap<(String, String), VecDeque<Instant>>,
    limits: HashMap<String, (u32, Duration)>,  // endpoint -> (count, window)
}

impl RateLimiter {
    pub fn check(&mut self, api_key: &str, endpoint: &str) -> Result<(), RateLimitError> {
        let key = (api_key.to_string(), endpoint.to_string());
        let (limit, window) = self.limits.get(endpoint)
            .unwrap_or(&(10, Duration::from_secs(1)));

        // Clean old requests and check limit
        // ...
    }
}
```

---

## Rust Implementation Example

```rust
use axum::{
    routing::{get, post},
    Router, Json, Extension,
};

pub fn api_routes() -> Router {
    Router::new()
        // Order Management
        .route("/api/v1/placeorder", post(place_order))
        .route("/api/v1/placesmartorder", post(place_smart_order))
        .route("/api/v1/modifyorder", post(modify_order))
        .route("/api/v1/cancelorder", post(cancel_order))
        .route("/api/v1/cancelallorder", post(cancel_all_order))
        .route("/api/v1/closeposition", post(close_position))
        .route("/api/v1/basketorder", post(basket_order))
        .route("/api/v1/splitorder", post(split_order))
        // Options
        .route("/api/v1/optionsorder", post(options_order))
        .route("/api/v1/optionsmultiorder", post(options_multi_order))
        .route("/api/v1/optionsymbol", post(option_symbol))
        .route("/api/v1/optionchain", post(option_chain))
        .route("/api/v1/optiongreeks", post(option_greeks))
        .route("/api/v1/syntheticfuture", post(synthetic_future))
        // Account
        .route("/api/v1/orderbook", post(orderbook))
        .route("/api/v1/tradebook", post(tradebook))
        .route("/api/v1/positionbook", post(positionbook))
        .route("/api/v1/holdings", post(holdings))
        .route("/api/v1/funds", post(funds))
        .route("/api/v1/orderstatus", post(orderstatus))
        .route("/api/v1/openposition", post(openposition))
        // Market Data
        .route("/api/v1/quotes", post(quotes))
        .route("/api/v1/multiquotes", post(multiquotes))
        .route("/api/v1/depth", post(depth))
        .route("/api/v1/history", post(history))
        .route("/api/v1/ticker", post(ticker))
        // Symbol
        .route("/api/v1/symbol", post(symbol))
        .route("/api/v1/search", post(search))
        .route("/api/v1/instruments", get(instruments))
        .route("/api/v1/expiry", post(expiry))
        .route("/api/v1/intervals", post(intervals))
        // Utilities
        .route("/api/v1/margin", post(margin))
        .route("/api/v1/ping", post(ping))
        .route("/api/v1/analyzer", post(analyzer_status))
        .route("/api/v1/analyzer/toggle", post(analyzer_toggle))
        // Middleware
        .layer(Extension(rate_limiter))
        .layer(Extension(db_pool))
}
```

---

## Conclusion

This REST API specification provides complete compatibility with the existing Python/Flask implementation. The embedded `axum` server in the Tauri application will expose these same endpoints, enabling seamless integration with:

- TradingView webhooks
- ChartInk scanner
- Custom trading systems
- Python SDK
- Third-party applications

All request/response formats are preserved exactly as in the original implementation.
