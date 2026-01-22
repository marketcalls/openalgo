# 19 - PlaceOrder Call Flow

## Overview

The PlaceOrder API is the core order execution endpoint in OpenAlgo. It handles order validation, authentication, broker routing, and response processing through multiple layers.

## Complete Flow Diagram

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        PlaceOrder Complete Flow                               │
└──────────────────────────────────────────────────────────────────────────────┘

  Client Request (JSON)
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 1: REST API Endpoint                                                  │
│  POST /api/v1/placeorder                                                     │
│                                                                              │
│  ┌─────────────────┐                                                         │
│  │ Rate Limiting   │──> 10 per second (default)                             │
│  └────────┬────────┘                                                         │
│           │                                                                  │
│           ▼                                                                  │
│  ┌─────────────────┐                                                         │
│  │ Extract apikey  │                                                         │
│  │ from request    │                                                         │
│  └────────┬────────┘                                                         │
└───────────┼──────────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  Layer 2: Service Layer (place_order_service.py)                             │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Step 1: Order Routing Check                                         │    │
│  │                                                                      │    │
│  │  should_route_to_pending(api_key, 'placeorder')                     │    │
│  │         │                                                            │    │
│  │    ┌────┴────┐                                                       │    │
│  │    │         │                                                       │    │
│  │  semi_auto  auto                                                     │    │
│  │    │         │                                                       │    │
│  │    ▼         ▼                                                       │    │
│  │  Queue to  Continue                                                  │    │
│  │  Action    with flow                                                 │    │
│  │  Center                                                              │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Step 2: Order Validation                                            │    │
│  │                                                                      │    │
│  │  validate_order_data(data)                                          │    │
│  │  - Check mandatory fields                                            │    │
│  │  - Validate exchange (NSE, NFO, MCX, etc.)                          │    │
│  │  - Validate action (BUY, SELL)                                      │    │
│  │  - Validate pricetype (MARKET, LIMIT, SL, SL-M)                     │    │
│  │  - Validate product (CNC, MIS, NRML)                                │    │
│  │  - Schema validation (quantity > 0, price >= 0)                     │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  Step 3: Analyzer Mode Check                                         │    │
│  │                                                                      │    │
│  │  if get_analyze_mode() == True:                                     │    │
│  │      → Route to sandbox_place_order()                               │    │
│  │      → Virtual trading with ₹1 Crore capital                        │    │
│  │  else:                                                              │    │
│  │      → Continue to live broker                                      │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 3: Authentication (auth_db.py)                                        │
│                                                                              │
│  get_auth_token_broker(api_key)                                              │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  1. Check invalid key cache (5-min TTL)                              │    │
│  │     └─ Fast rejection of known bad keys                             │    │
│  │                                                                      │    │
│  │  2. Check verified key cache (10-hour TTL)                           │    │
│  │     └─ Fast path for legitimate requests                            │    │
│  │                                                                      │    │
│  │  3. Database lookup with Argon2 verification                         │    │
│  │     └─ api_key + API_KEY_PEPPER → hash compare                      │    │
│  │                                                                      │    │
│  │  4. Decrypt auth token (Fernet)                                      │    │
│  │     └─ Get broker name, verify not revoked                          │    │
│  │                                                                      │    │
│  │  Returns: (auth_token, broker_name) or (None, None)                  │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 4: Broker Module (Dynamic Import)                                     │
│                                                                              │
│  import_broker_module(broker_name)                                           │
│  → broker.{name}.api.order_api                                               │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │  broker_module.place_order_api(order_data, auth_token)               │    │
│  │                                                                      │    │
│  │  A. Transform Data                                                   │    │
│  │     OpenAlgo Format → Broker Format                                  │    │
│  │                                                                      │    │
│  │     Input:                          Output:                          │    │
│  │     {"symbol": "SBIN",              {"tradingsymbol": "SBIN-EQ",    │    │
│  │      "exchange": "NSE",              "exchange": "NSE",              │    │
│  │      "action": "BUY",                "transaction_type": "BUY",      │    │
│  │      "quantity": 100,                "quantity": 100,                │    │
│  │      "pricetype": "MARKET",          "order_type": "MARKET",         │    │
│  │      "product": "MIS"}               "product": "MIS"}               │    │
│  │                                                                      │    │
│  │  B. Symbol Mapping                                                   │    │
│  │     get_br_symbol(symbol, exchange)                                  │    │
│  │     "SBIN" → "SBIN-EQ" (Zerodha)                                    │    │
│  │     "NIFTY21JAN2521500CE" → broker-specific format                  │    │
│  │                                                                      │    │
│  │  C. HTTP Request to Broker API                                       │    │
│  │     POST https://api.broker.com/orders                              │    │
│  │     Headers: Authorization, API keys                                 │    │
│  │                                                                      │    │
│  │  D. Response Processing                                              │    │
│  │     Parse response, extract order_id                                 │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
└──────────────────────────────────────────────────────────────────────────────┘
            │
            ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│  Layer 5: Response Handling                                                  │
│                                                                              │
│  ┌────────────────────┐         ┌────────────────────┐                      │
│  │   Status 200       │         │   Status != 200    │                      │
│  │   (Success)        │         │   (Error)          │                      │
│  └─────────┬──────────┘         └─────────┬──────────┘                      │
│            │                              │                                  │
│            ▼                              ▼                                  │
│  ┌──────────────────┐          ┌──────────────────┐                         │
│  │ Extract order_id │          │ Extract error    │                         │
│  │ Emit SocketIO    │          │ message          │                         │
│  │ Log order async  │          │ Log failure      │                         │
│  │ Telegram alert   │          │ Return error     │                         │
│  └──────────────────┘          └──────────────────┘                         │
│                                                                              │
│  Success Response:              Error Response:                              │
│  {                              {                                            │
│    "status": "success",           "status": "error",                         │
│    "orderid": "123456789"         "message": "Insufficient margin"           │
│  }                              }                                            │
└──────────────────────────────────────────────────────────────────────────────┘
```

## Request Format

### Basic Order Request

```json
{
    "apikey": "your_api_key",
    "strategy": "MyStrategy",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 100,
    "product": "MIS",
    "pricetype": "MARKET"
}
```

### Limit Order

```json
{
    "apikey": "your_api_key",
    "strategy": "MyStrategy",
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "product": "CNC",
    "pricetype": "LIMIT",
    "price": 1650.00
}
```

### Stop-Loss Order

```json
{
    "apikey": "your_api_key",
    "strategy": "MyStrategy",
    "symbol": "NIFTY21JAN2521500CE",
    "exchange": "NFO",
    "action": "BUY",
    "quantity": 65,
    "product": "MIS",
    "pricetype": "SL",
    "price": 250.00,
    "trigger_price": 245.00
}
```

## Validation Rules

### Mandatory Fields

| Field | Type | Description |
|-------|------|-------------|
| apikey | string | OpenAlgo API key |
| strategy | string | Strategy identifier |
| symbol | string | Trading symbol |
| exchange | string | Exchange code |
| action | string | BUY or SELL |
| quantity | integer | Order quantity (≥1) |

### Valid Values

```
Exchanges: NSE, BSE, NFO, BFO, CDS, BCD, MCX, NCDEX, NSE_INDEX, BSE_INDEX

Actions: BUY, SELL (case-insensitive)

Price Types: MARKET, LIMIT, SL, SL-M

Products: CNC (delivery), MIS (intraday), NRML (F&O carryforward)
```

## Order Routing Modes

### Auto Mode (Default)

```
Request → Validate → Authenticate → Execute → Response
```

Orders are executed immediately without manual intervention.

### Semi-Auto Mode

```
Request → Validate → Queue to Action Center → Await Approval
                                                    │
                                              ┌─────┴─────┐
                                              │           │
                                          Approved    Rejected
                                              │           │
                                              ▼           ▼
                                          Execute     Discard
```

Orders require manual approval before execution.

## Analyzer Mode (Sandbox)

When `analyze_mode = True`:

```
┌─────────────────────────────────────────────────────────────────┐
│                    Sandbox Execution                             │
│                                                                  │
│  1. Initialize OrderManager(user_id)                            │
│  2. Check virtual funds (₹1 Crore default)                      │
│  3. Calculate margin requirements                                │
│  4. Simulate order execution                                     │
│  5. Update virtual positions                                     │
│  6. Log to analyzer_db                                          │
│  7. Return same response format as live                          │
└─────────────────────────────────────────────────────────────────┘
```

## Broker Integration

### Dynamic Module Loading

```python
def import_broker_module(broker_name):
    module_path = f'broker.{broker_name}.api.order_api'
    return importlib.import_module(module_path)
```

### Broker-Specific Implementation

Each broker implements:

```python
def place_order_api(data, auth):
    # 1. Transform data to broker format
    transformed = transform_data(data)

    # 2. Map symbol to broker format
    symbol = get_br_symbol(data['symbol'], data['exchange'])

    # 3. Make HTTP request to broker API
    response = client.post(BROKER_ORDER_URL, data=transformed)

    # 4. Parse response
    order_id = response.json()['data']['order_id']

    return (response, response_data, order_id)
```

## Error Handling

| Error | HTTP Code | Response |
|-------|-----------|----------|
| Missing field | 400 | `{"status": "error", "message": "Missing mandatory field(s): symbol"}` |
| Invalid exchange | 400 | `{"status": "error", "message": "Invalid exchange"}` |
| Invalid API key | 403 | `{"status": "error", "message": "Invalid openalgo apikey"}` |
| Broker not found | 404 | `{"status": "error", "message": "Broker module not found"}` |
| Broker API error | 500 | `{"status": "error", "message": "Failed to place order"}` |
| Rate limit | 429 | Rate limiter response |

## Async Operations

### Order Logging

```python
# Non-blocking log to database
executor.submit(async_log_order, 'placeorder', request_data, response)
```

### SocketIO Events

```python
# Real-time order event emission
socketio.emit('order_event', {
    'symbol': symbol,
    'action': action,
    'orderid': order_id,
    'exchange': exchange,
    'mode': 'live' or 'analyzer'
})
```

### Telegram Alerts

```python
# Background notification
socketio.start_background_task(
    telegram_alert_service.send_order_alert,
    'placeorder', order_data, response, api_key
)
```

## Security Layers

### API Key Verification

```
┌─────────────────────────────────────────┐
│ 1. Add pepper to provided API key       │
│    peppered = api_key + API_KEY_PEPPER  │
├─────────────────────────────────────────┤
│ 2. Check invalid cache (5-min TTL)      │
│    Fast rejection of bad keys           │
├─────────────────────────────────────────┤
│ 3. Check verified cache (10-hour TTL)   │
│    Fast path for good keys              │
├─────────────────────────────────────────┤
│ 4. Argon2 hash comparison               │
│    Full verification if cache miss      │
├─────────────────────────────────────────┤
│ 5. Decrypt auth token with Fernet       │
│    AES-128 CBC encryption               │
└─────────────────────────────────────────┘
```

### Request Sanitization

- API keys removed from logs
- Sensitive data encrypted at rest
- Rate limiting per endpoint

## Performance Optimizations

| Optimization | Description |
|--------------|-------------|
| Connection pooling | HTTP clients reuse connections |
| API key caching | Reduce Argon2 hashing overhead |
| Async logging | Non-blocking order logs |
| Thread pool | 10 worker threads for async ops |

## Key Files Reference

| File | Purpose |
|------|---------|
| `restx_api/place_order.py` | REST endpoint |
| `services/place_order_service.py` | Core logic |
| `services/order_router_service.py` | Semi-auto routing |
| `services/sandbox_service.py` | Analyzer mode |
| `database/auth_db.py` | Authentication |
| `broker/{name}/api/order_api.py` | Broker implementation |
| `broker/{name}/mapping/transform_data.py` | Data transformation |
| `database/apilog_db.py` | Order logging |
