# API Reference - Sandbox Mode

## Overview

When sandbox mode (Analyzer Mode) is enabled, all trading API endpoints automatically route to the sandbox environment. This document covers all sandbox-specific endpoints and the modified behavior of standard trading APIs.

**Base URL**: `http://127.0.0.1:5000`
**API Version**: v1
**Authentication**: API Key in request payload

## Table of Contents

1. [Analyzer Control](#analyzer-control)
2. [Order Management](#order-management)
3. [Position Management](#position-management)
4. [Fund Management](#fund-management)
5. [Holdings](#holdings)
6. [Tradebook](#tradebook)
7. [Sandbox Configuration](#sandbox-configuration)
8. [Sandbox Status](#sandbox-status)

---

## Analyzer Control

### Enable/Disable Analyzer Mode

Toggle analyzer mode on/off.

**Endpoint**: `POST /api/v1/analyzer`

**Request**:
```python
import requests

url = "http://127.0.0.1:5000/api/v1/analyzer"
payload = {
    "apikey": "your_api_key",
    "mode": True  # True = Enable, False = Disable
}

response = requests.post(url, json=payload)
```

**Response (Enable)**:
```json
{
    "status": "success",
    "message": "Analyzer mode enabled",
    "mode": "analyze"
}
```

**Response (Disable)**:
```json
{
    "status": "success",
    "message": "Analyzer mode disabled. Switched to live mode.",
    "mode": "live"
}
```

**Behavior**:
- Enabling starts execution engine and square-off scheduler threads
- Disabling stops both threads
- UI theme changes (Garden theme when enabled)

---

## Order Management

All standard order endpoints work in sandbox mode with simulated execution.

### Place Order

Place a new sandbox order.

**Endpoint**: `POST /api/v1/placeorder`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/placeorder"
payload = {
    "apikey": "your_api_key",
    "strategy": "Test Strategy",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
}

response = requests.post(url, json=payload)
```

**Parameters**:

| Parameter | Type | Required | Description | Values |
|-----------|------|----------|-------------|--------|
| apikey | string | Yes | User API key | - |
| strategy | string | No | Strategy name for grouping | Any string |
| symbol | string | Yes | Trading symbol | "RELIANCE", "SBIN", etc. |
| exchange | string | Yes | Exchange | NSE, BSE, NFO, etc. |
| action | string | Yes | Buy or Sell | BUY, SELL |
| quantity | integer | Yes | Order quantity | > 0 |
| pricetype | string | Yes | Order type | MARKET, LIMIT, SL, SL-M |
| product | string | Yes | Product type | MIS, CNC, NRML |
| price | float | Conditional | Limit price | Required for LIMIT, SL |
| triggerprice | float | Conditional | Trigger price | Required for SL, SL-M |

**Response**:
```json
{
    "status": "success",
    "orderid": "SB-20251002-151030-abc12345",
    "mode": "analyze"
}
```

**Error Response**:
```json
{
    "status": "error",
    "message": "Insufficient funds. Required: ₹24,000.00, Available: ₹10,000.00",
    "mode": "analyze"
}
```

### Modify Order

Modify an existing pending order.

**Endpoint**: `POST /api/v1/modifyorder`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/modifyorder"
payload = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-151030-abc12345",
    "quantity": 20,           # Optional
    "price": 1250.00,         # Optional
    "triggerprice": 1245.00   # Optional
}

response = requests.post(url, json=payload)
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| apikey | string | Yes | User API key |
| orderid | string | Yes | Order ID to modify |
| quantity | integer | No | New quantity |
| price | float | No | New limit price |
| triggerprice | float | No | New trigger price |

**Response**:
```json
{
    "status": "success",
    "message": "Order modified successfully",
    "orderid": "SB-20251002-151030-abc12345",
    "mode": "analyze"
}
```

**Limitations**:
- Can only modify open orders
- Cannot modify completed/cancelled/rejected orders

### Cancel Order

Cancel a pending order.

**Endpoint**: `POST /api/v1/cancelorder`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/cancelorder"
payload = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-151030-abc12345"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "message": "Order cancelled successfully",
    "orderid": "SB-20251002-151030-abc12345",
    "mode": "analyze"
}
```

**Behavior**:
- Releases blocked margin
- Updates available balance
- Cannot cancel completed orders

### Cancel All Orders

Cancel all pending orders for the user.

**Endpoint**: `POST /api/v1/cancelallorder`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/cancelallorder"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "message": "5 orders cancelled successfully",
    "mode": "analyze"
}
```

### Get Orderbook

Retrieve all orders for the user.

**Endpoint**: `POST /api/v1/orderbook`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/orderbook"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "orderid": "SB-20251002-151030-abc123",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 0.00,
            "triggerprice": 0.00,
            "pricetype": "MARKET",
            "product": "MIS",
            "status": "complete",
            "averageprice": 1187.50,
            "filledqty": 10,
            "pendingqty": 0,
            "ordertimestamp": "2025-10-02 15:10:30"
        }
    ],
    "mode": "analyze"
}
```

### Get Order Status

Get status of a specific order.

**Endpoint**: `POST /api/v1/orderstatus`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/orderstatus"
payload = {
    "apikey": "your_api_key",
    "orderid": "SB-20251002-151030-abc123"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "orderid": "SB-20251002-151030-abc123",
        "status": "complete",
        "averageprice": 1187.50,
        "filledqty": 10,
        "pendingqty": 0
    },
    "mode": "analyze"
}
```

---

## Position Management

### Get Positionbook

Retrieve all positions (open and closed).

**Endpoint**: `POST /api/v1/positionbook`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/positionbook"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 10,
            "averageprice": 1187.50,
            "ltp": 1195.00,
            "pnl": 75.00,
            "pnlpercent": 0.63
        }
    ],
    "mode": "analyze"
}
```

**Position Fields**:

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| product | string | Product type (MIS, CNC, NRML) |
| quantity | integer | Net quantity (+long, -short, 0=closed) |
| averageprice | float | Average entry price |
| ltp | float | Last traded price |
| pnl | float | Current P&L (₹) |
| pnlpercent | float | P&L percentage |

### Close Position

Close a specific position or all positions.

**Endpoint**: `POST /api/v1/closeposition`

**Request (Single Position)**:
```python
url = "http://127.0.0.1:5000/api/v1/closeposition"
payload = {
    "apikey": "your_api_key",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
}

response = requests.post(url, json=payload)
```

**Request (All Positions)**:
```python
payload = {
    "apikey": "your_api_key"
    # Omit symbol/exchange/product to close all
}
```

**Response**:
```json
{
    "status": "success",
    "message": "Position closed successfully. P&L: ₹75.00",
    "mode": "analyze"
}
```

**Behavior**:
- Places reverse MARKET order
- Releases blocked margin
- Updates realized P&L
- Sets position quantity to 0

---

## Fund Management

### Get Funds

Retrieve user fund details.

**Endpoint**: `POST /api/v1/funds`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/funds"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "availablecash": 9976000.00,
        "utiliseddebits": 24000.00,
        "realizedpnl": 0.00,
        "unrealizedpnl": 75.00,
        "totalpnl": 75.00
    },
    "mode": "analyze"
}
```

**Fund Fields**:

| Field | Type | Description |
|-------|------|-------------|
| availablecash | float | Available balance for trading |
| utiliseddebits | float | Margin blocked in positions |
| realizedpnl | float | P&L from closed positions |
| unrealizedpnl | float | P&L from open positions |
| totalpnl | float | Total P&L (realized + unrealized) |

### Reset Funds

Manually reset funds to starting capital (admin only).

**Endpoint**: `POST /api/v1/resetfunds`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/resetfunds"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "message": "Funds reset successfully",
    "availablecash": 10000000.00,
    "mode": "analyze"
}
```

**Behavior**:
- Resets to configured starting capital
- Clears all positions, orders, trades
- Increments reset counter

---

## Holdings

### Get Holdings

Retrieve T+1 settled CNC holdings.

**Endpoint**: `POST /api/v1/holdings`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/holdings"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "TCS",
            "exchange": "NSE",
            "quantity": 5,
            "averageprice": 3650.00,
            "ltp": 3680.00,
            "pnl": 150.00,
            "pnlpercent": 0.82,
            "settlementdate": "2025-10-03"
        }
    ],
    "mode": "analyze"
}
```

**Holding Fields**:

| Field | Type | Description |
|-------|------|-------------|
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| quantity | integer | Holdings quantity |
| averageprice | float | Average buy price |
| ltp | float | Current LTP |
| pnl | float | Unrealized P&L |
| pnlpercent | float | P&L percentage |
| settlementdate | string | T+1 settlement date |

**Note**: Only CNC positions settle to holdings at midnight (00:00 IST).

---

## Tradebook

### Get Tradebook

Retrieve all executed trades.

**Endpoint**: `POST /api/v1/tradebook`

**Request**:
```python
url = "http://127.0.0.1:5000/api/v1/tradebook"
payload = {
    "apikey": "your_api_key"
}

response = requests.post(url, json=payload)
```

**Response**:
```json
{
    "status": "success",
    "data": [
        {
            "tradeid": "TR-20251002-151035-xyz789",
            "orderid": "SB-20251002-151030-abc123",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 1187.50,
            "product": "MIS",
            "strategy": "Test Strategy",
            "tradetimestamp": "2025-10-02 15:10:35"
        }
    ],
    "mode": "analyze"
}
```

**Trade Fields**:

| Field | Type | Description |
|-------|------|-------------|
| tradeid | string | Unique trade ID |
| orderid | string | Parent order ID |
| symbol | string | Trading symbol |
| exchange | string | Exchange |
| action | string | BUY or SELL |
| quantity | integer | Trade quantity |
| price | float | Execution price |
| product | string | Product type |
| strategy | string | Strategy name |
| tradetimestamp | string | Execution timestamp (IST) |

---

## Sandbox Configuration

### Update Config

Update sandbox configuration settings.

**Endpoint**: `POST /sandbox/update`

**Request**:
```python
url = "http://127.0.0.1:5000/sandbox/update"
payload = {
    "config_key": "equity_mis_leverage",
    "config_value": "8"
}

response = requests.post(url, json=payload)
```

**Parameters**:

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| config_key | string | Yes | Configuration key |
| config_value | string | Yes | Configuration value |

**Response**:
```json
{
    "status": "success",
    "message": "Configuration updated successfully"
}
```

**Available Config Keys**:
- `starting_capital`
- `reset_day`
- `reset_time`
- `order_check_interval`
- `mtm_update_interval`
- `nse_bse_square_off_time`
- `cds_bcd_square_off_time`
- `mcx_square_off_time`
- `ncdex_square_off_time`
- `equity_mis_leverage`
- `equity_cnc_leverage`
- `futures_leverage`
- `option_buy_leverage`
- `option_sell_leverage`
- `order_rate_limit`
- `api_rate_limit`
- `smart_order_rate_limit`
- `smart_order_delay`

### Get All Configs

Retrieve all configuration values.

**Endpoint**: `GET /sandbox/config`

**Request**:
```python
url = "http://127.0.0.1:5000/sandbox/config"
response = requests.get(url)
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "starting_capital": {
            "value": "10000000.00",
            "description": "Starting sandbox capital in INR (₹1 Crore)"
        },
        "equity_mis_leverage": {
            "value": "5",
            "description": "Leverage multiplier for equity MIS (NSE/BSE) - Range: 1-50x"
        }
        // ... other configs
    }
}
```

---

## Sandbox Status

### Get Execution Status

Check if execution engine thread is running.

**Endpoint**: `GET /sandbox/execution-status`

**Request**:
```python
url = "http://127.0.0.1:5000/sandbox/execution-status"
response = requests.get(url)
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "is_running": true,
        "last_check": "2025-10-02 15:15:30",
        "orders_checked": 125,
        "orders_executed": 98
    }
}
```

### Get Square-Off Status

Check square-off scheduler status.

**Endpoint**: `GET /sandbox/squareoff-status`

**Request**:
```python
url = "http://127.0.0.1:5000/sandbox/squareoff-status"
response = requests.get(url)
```

**Response**:
```json
{
    "status": "success",
    "data": {
        "is_running": true,
        "scheduled_jobs": [
            {
                "exchange": "NSE/BSE",
                "square_off_time": "15:15",
                "next_run": "2025-10-03 15:15:00"
            },
            {
                "exchange": "T+1 Settlement",
                "square_off_time": "00:00",
                "next_run": "2025-10-03 00:00:00"
            }
        ]
    }
}
```

### Reload Square-Off Schedule

Reload square-off scheduler after config changes.

**Endpoint**: `POST /sandbox/reload-squareoff`

**Request**:
```python
url = "http://127.0.0.1:5000/sandbox/reload-squareoff"
response = requests.post(url)
```

**Response**:
```json
{
    "status": "success",
    "message": "Square-off schedule reloaded successfully"
}
```

---

## Error Handling

All endpoints return consistent error structures:

### Error Response Format

```json
{
    "status": "error",
    "message": "Error description here",
    "mode": "analyze"
}
```

### Common Error Codes

| HTTP Code | Error | Description |
|-----------|-------|-------------|
| 400 | Bad Request | Invalid parameters |
| 401 | Unauthorized | Invalid API key |
| 403 | Forbidden | Insufficient permissions |
| 404 | Not Found | Resource not found |
| 429 | Too Many Requests | Rate limit exceeded |
| 500 | Internal Server Error | Server error |

### Error Examples

**Insufficient Funds**:
```json
{
    "status": "error",
    "message": "Insufficient funds. Required: ₹24,000.00, Available: ₹10,000.00",
    "mode": "analyze"
}
```

**Invalid Symbol**:
```json
{
    "status": "error",
    "message": "Symbol not found: INVALID",
    "mode": "analyze"
}
```

**Order Not Found**:
```json
{
    "status": "error",
    "message": "Order not found: SB-20251002-151030-invalid",
    "mode": "analyze"
}
```

---

## Rate Limiting

Sandbox mode enforces configurable rate limits:

### Default Limits

- **Order Rate**: 10 orders per second
- **API Rate**: 50 calls per second
- **Smart Order Rate**: 2 orders per second

### Rate Limit Headers

Responses include rate limit information:

```http
X-RateLimit-Limit: 10
X-RateLimit-Remaining: 7
X-RateLimit-Reset: 1696253431
```

### Rate Limit Exceeded

```json
{
    "status": "error",
    "message": "Rate limit exceeded. Try again in 1 second.",
    "retry_after": 1,
    "mode": "analyze"
}
```

---

## Code Examples

### Complete Order Flow

```python
import requests

base_url = "http://127.0.0.1:5000"
api_key = "your_api_key"

# 1. Enable analyzer mode
response = requests.post(f"{base_url}/api/v1/analyzer", json={
    "apikey": api_key,
    "mode": True
})
print("Analyzer enabled:", response.json())

# 2. Check funds
response = requests.post(f"{base_url}/api/v1/funds", json={
    "apikey": api_key
})
funds = response.json()["data"]
print(f"Available: ₹{funds['availablecash']:,.2f}")

# 3. Place order
response = requests.post(f"{base_url}/api/v1/placeorder", json={
    "apikey": api_key,
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
})
order = response.json()
print("Order placed:", order["orderid"])

# 4. Wait for execution
import time
time.sleep(6)  # Wait for execution engine

# 5. Check position
response = requests.post(f"{base_url}/api/v1/positionbook", json={
    "apikey": api_key
})
positions = response.json()["data"]
print("Position P&L:", positions[0]["pnl"])

# 6. Close position
response = requests.post(f"{base_url}/api/v1/closeposition", json={
    "apikey": api_key,
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
})
print("Position closed:", response.json()["message"])
```

---

**Previous**: [Configuration](09_configuration.md) | **Next**: [Troubleshooting](11_troubleshooting.md)
