# Flow Node Reference

Complete reference for all 50+ nodes available in the Flow visual workflow builder.

## Node Categories

| Category | Count | Purpose |
|----------|-------|---------|
| [Triggers](#trigger-nodes) | 4 | Start workflow execution |
| [Actions](#action-nodes) | 10 | Execute trading operations |
| [Conditions](#condition-nodes) | 8 | Control flow with branching |
| [Data](#data-nodes) | 16 | Fetch market & account data |
| [Streaming](#streaming-nodes) | 4 | Real-time data subscriptions |
| [Utility](#utility-nodes) | 7 | Helper operations |

---

## Trigger Nodes

Trigger nodes start workflow execution. Every workflow must have at least one trigger.

### Start

Schedule-based workflow execution.

| Field | Type | Description |
|-------|------|-------------|
| scheduleType | `once` \| `daily` \| `weekly` \| `interval` | Execution frequency |
| time | string | Time in HH:MM format (IST) |
| days | string[] | Days of week for weekly schedule |
| intervalMinutes | number | Minutes between executions |

**Example:**
```
Schedule: Daily at 09:15 IST
Days: Mon, Tue, Wed, Thu, Fri
```

### Webhook Trigger

External HTTP webhook trigger.

| Field | Type | Description |
|-------|------|-------------|
| (auto) | - | Webhook URL and secret auto-generated |

**Webhook URL:** `POST /flow/webhook/<token>`

**Payload Format:**
```json
{
  "secret": "your_webhook_secret",
  "symbol": "RELIANCE",
  "action": "BUY"
}
```

### Price Alert

Trigger when price crosses threshold.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | NSE, NFO, BSE, etc. |
| field | string | ltp, open, high, low, close |
| operator | string | >, <, ==, >=, <= |
| value | number | Threshold value |

### HTTP Request

Trigger from external API response.

| Field | Type | Description |
|-------|------|-------------|
| url | string | API endpoint URL |
| method | string | GET, POST |
| headers | object | Request headers |
| body | string | Request body (POST) |

---

## Action Nodes

Action nodes execute trading operations.

### Place Order

Place a regular order.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | NSE, NFO, BSE, MCX, CDS, BFO |
| action | string | BUY, SELL |
| quantity | number | Order quantity |
| product | string | MIS, CNC, NRML |
| priceType | string | MARKET, LIMIT, SL, SL-M |
| price | number | Limit price (if LIMIT/SL) |
| triggerPrice | number | Trigger price (if SL/SL-M) |
| outputVariable | string | Store order result |

**Output:**
```json
{
  "status": "success",
  "orderid": "123456789"
}
```

### Smart Order

Position-aware order placement.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| action | string | BUY, SELL |
| quantity | number | Order quantity |
| positionSize | number | Target position size |
| product | string | MIS, CNC, NRML |
| priceType | string | MARKET, LIMIT |

**Behavior:**
- If `positionSize=10` and current position is 5, places order for 5
- If `positionSize=0`, closes existing position
- Handles long/short position transitions

### Options Order

Single-leg options trade.

| Field | Type | Description |
|-------|------|-------------|
| underlying | string | NIFTY, BANKNIFTY, etc. |
| expiry | string | Expiry date |
| strike | number | Strike price |
| optionType | string | CE, PE |
| action | string | BUY, SELL |
| quantity | number | Lot quantity |
| product | string | MIS, NRML |

### Options Multi-Order

Multi-leg options strategies.

| Field | Type | Description |
|-------|------|-------------|
| strategy | string | STRADDLE, STRANGLE, SPREAD, IRON_CONDOR |
| underlying | string | NIFTY, BANKNIFTY |
| expiry | string | Expiry date |
| atmStrike | number | ATM strike price |
| quantity | number | Lot quantity |
| action | string | BUY, SELL |

**Strategies:**
- **STRADDLE**: Same strike CE + PE
- **STRANGLE**: OTM CE + OTM PE
- **SPREAD**: Two strikes, same type
- **IRON_CONDOR**: Four legs

### Basket Order

Multiple orders in single execution.

| Field | Type | Description |
|-------|------|-------------|
| orders | array | Array of order objects |

**Order Object:**
```json
{
  "symbol": "SBIN",
  "exchange": "NSE",
  "action": "BUY",
  "quantity": 100
}
```

### Split Order

Large order splitting.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| action | string | BUY, SELL |
| totalQuantity | number | Total quantity |
| splitSize | number | Quantity per order |
| delayMs | number | Delay between orders (ms) |

### Modify Order

Modify existing order.

| Field | Type | Description |
|-------|------|-------------|
| orderId | string | Order ID to modify |
| quantity | number | New quantity |
| price | number | New price |
| triggerPrice | number | New trigger price |

### Cancel Order

Cancel specific order.

| Field | Type | Description |
|-------|------|-------------|
| orderId | string | Order ID to cancel |

### Cancel All Orders

Cancel all open orders.

| Field | Type | Description |
|-------|------|-------------|
| (none) | - | Cancels all pending orders |

### Close Positions

Square off all open positions.

| Field | Type | Description |
|-------|------|-------------|
| product | string | MIS, NRML, or ALL |

---

## Condition Nodes

Condition nodes control workflow branching with true/false outputs.

### Price Condition

Check price against threshold.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| field | string | ltp, open, high, low, close, volume |
| operator | string | >, <, ==, >=, <=, != |
| value | number | Comparison value |

**Outputs:**
- **true**: Condition met
- **false**: Condition not met

### Position Check

Check if position exists.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| checkType | string | exists, quantity_gt, quantity_lt |
| quantity | number | Quantity threshold |

### Fund Check

Check available funds.

| Field | Type | Description |
|-------|------|-------------|
| field | string | available_cash, used_margin, total |
| operator | string | >, <, == |
| value | number | Comparison value |

### Time Window

Check if within time range.

| Field | Type | Description |
|-------|------|-------------|
| startTime | string | Start time (HH:MM) |
| endTime | string | End time (HH:MM) |
| days | string[] | Days of week |

**Example:**
```
Start: 09:15, End: 15:15
Days: Mon, Tue, Wed, Thu, Fri
```

### Time Condition

Check specific time.

| Field | Type | Description |
|-------|------|-------------|
| time | string | Target time (HH:MM) |
| operator | string | before, after, at |

### AND Gate

Logical AND of multiple inputs.

| Field | Type | Description |
|-------|------|-------------|
| (inputs) | - | Connect multiple condition outputs |

**Behavior:** Returns true only if ALL inputs are true.

### OR Gate

Logical OR of multiple inputs.

| Field | Type | Description |
|-------|------|-------------|
| (inputs) | - | Connect multiple condition outputs |

**Behavior:** Returns true if ANY input is true.

### NOT Gate

Logical NOT (inversion).

| Field | Type | Description |
|-------|------|-------------|
| (input) | - | Single condition input |

**Behavior:** Inverts true ↔ false.

---

## Data Nodes

Data nodes fetch market and account information.

### Get Quote

Fetch current quote for symbol.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store result |

**Output:**
```json
{
  "ltp": 625.50,
  "open": 620.00,
  "high": 628.00,
  "low": 618.50,
  "close": 622.00,
  "volume": 1500000
}
```

### Get Depth

Fetch market depth.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store result |

**Output:**
```json
{
  "buy": [
    {"price": 625.45, "quantity": 1000, "orders": 5}
  ],
  "sell": [
    {"price": 625.50, "quantity": 800, "orders": 3}
  ]
}
```

### History

Fetch historical OHLCV data.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| interval | string | 1m, 5m, 15m, 30m, 1h, D |
| startDate | string | Start date (YYYY-MM-DD) |
| endDate | string | End date (YYYY-MM-DD) |
| outputVariable | string | Store result |

### Symbol

Get symbol information.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store result |

**Output:**
```json
{
  "symbol": "RELIANCE",
  "token": "2885",
  "lotSize": 1,
  "tickSize": 0.05
}
```

### Option Symbol

Resolve option symbol from parameters.

| Field | Type | Description |
|-------|------|-------------|
| underlying | string | NIFTY, BANKNIFTY |
| expiry | string | Expiry date |
| strike | number | Strike price |
| optionType | string | CE, PE |
| outputVariable | string | Store resolved symbol |

### Expiry Dates

Get available expiry dates.

| Field | Type | Description |
|-------|------|-------------|
| underlying | string | NIFTY, BANKNIFTY |
| outputVariable | string | Store expiry list |

### Option Chain

Fetch option chain data.

| Field | Type | Description |
|-------|------|-------------|
| underlying | string | NIFTY, BANKNIFTY |
| expiry | string | Expiry date |
| outputVariable | string | Store option chain |

### Open Position

Get position for specific symbol.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store position |

### Order Book

Get all orders.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store orders |

### Trade Book

Get all executed trades.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store trades |

### Position Book

Get all open positions.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store positions |

### Holdings

Get delivery holdings.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store holdings |

### Funds

Get account funds.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store funds |

**Output:**
```json
{
  "availablecash": 100000,
  "collateral": 50000,
  "m2mrealized": 500,
  "m2munrealized": -200
}
```

### Intervals

Get supported intervals for broker.

| Field | Type | Description |
|-------|------|-------------|
| outputVariable | string | Store intervals |

### Holidays

Get market holidays.

| Field | Type | Description |
|-------|------|-------------|
| year | number | Year |
| outputVariable | string | Store holidays |

### Timings

Get market timings.

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange |
| outputVariable | string | Store timings |

---

## Streaming Nodes

Streaming nodes subscribe to real-time WebSocket data.

### Subscribe LTP

Subscribe to real-time LTP updates.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store streaming data |

### Subscribe Quote

Subscribe to real-time quote updates.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store streaming data |

### Subscribe Depth

Subscribe to real-time depth updates.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| outputVariable | string | Store streaming data |

### Unsubscribe

Unsubscribe from streaming data.

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |

---

## Utility Nodes

Utility nodes provide helper operations.

### Variable

Set, get, or calculate variables.

| Field | Type | Description |
|-------|------|-------------|
| operation | string | set, get, add, subtract, multiply, divide, parse_json |
| variableName | string | Variable name |
| value | any | Value for set/math operations |
| sourceVariable | string | Source for math operations |

**Operations:**
- **set**: `variableName = value`
- **get**: Read variable value
- **add**: `variableName = sourceVariable + value`
- **subtract**: `variableName = sourceVariable - value`
- **multiply**: `variableName = sourceVariable * value`
- **divide**: `variableName = sourceVariable / value`
- **parse_json**: Parse JSON string to object

### Delay

Wait for specified duration.

| Field | Type | Description |
|-------|------|-------------|
| seconds | number | Seconds to wait |

### Wait Until

Wait until specific time.

| Field | Type | Description |
|-------|------|-------------|
| time | string | Target time (HH:MM) |

### Log

Log message to execution logs.

| Field | Type | Description |
|-------|------|-------------|
| message | string | Log message |
| level | string | info, warn, error |

**Supports interpolation:** `"LTP is {{quote.ltp}}"`

### Telegram Alert

Send Telegram notification.

| Field | Type | Description |
|-------|------|-------------|
| message | string | Alert message |
| chatId | string | Telegram chat ID (optional) |

**Requires:** Telegram bot configured in OpenAlgo settings.

### Math Expression

Evaluate mathematical expression.

| Field | Type | Description |
|-------|------|-------------|
| expression | string | Math expression |
| outputVariable | string | Store result |

**Example:** `"{{quote.ltp}} * 1.02"` → 2% above LTP

### Group

Visual grouping of nodes (no execution).

| Field | Type | Description |
|-------|------|-------------|
| label | string | Group label |

---

## Variable Interpolation

All text fields support `{{variable}}` interpolation:

### Built-in Variables

| Variable | Description |
|----------|-------------|
| `{{timestamp}}` | ISO timestamp |
| `{{date}}` | Current date |
| `{{time}}` | Current time |
| `{{hour}}` | Current hour |
| `{{minute}}` | Current minute |
| `{{weekday}}` | Day name |

### Accessing Node Outputs

```
{{quote.ltp}}           → LTP from quote
{{position.quantity}}   → Position quantity
{{order.orderid}}       → Order ID from result
{{funds.availablecash}} → Available cash
```

### Webhook Data

```
{{webhook.symbol}}      → Symbol from webhook payload
{{webhook.action}}      → Action from webhook payload
{{webhook.quantity}}    → Quantity from webhook payload
```
