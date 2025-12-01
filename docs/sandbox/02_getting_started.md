# Getting Started with Sandbox Mode

## Quick Start Guide

This guide will help you enable sandbox mode and place your first trade in under 5 minutes.

## Prerequisites

1. **OpenAlgo Installation**: Ensure OpenAlgo is installed and running
2. **Broker API Configured**: Valid broker API credentials for quotes
3. **Database Initialized**: Run migrations if upgrading

## Step 1: Enable Sandbox Mode

### Via Web UI

1. Log in to OpenAlgo
2. Navigate to **Settings**
3. Find **API Analyzer Mode** toggle
4. Click to enable (toggle should turn green)
5. Confirmation message appears: "Analyzer mode enabled"

### Via API

```python
import requests

url = "http://127.0.0.1:5000/api/v1/analyzer"
headers = {"Content-Type": "application/json"}

payload = {
    "apikey": "your_api_key_here",
    "mode": True
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "message": "Analyzer mode enabled successfully",
    "mode": "analyze"
}
```

## Step 2: Verify Background Threads

When sandbox mode is enabled, two background threads automatically start:

### Check Thread Status

```python
from sandbox.execution_thread import is_execution_engine_running
from sandbox.squareoff_thread import is_squareoff_scheduler_running

print(f"Execution Engine: {is_execution_engine_running()}")  # Should be True
print(f"Square-off Scheduler: {is_squareoff_scheduler_running()}")  # Should be True
```

### View Logs

Check application logs for confirmation:

```
[INFO] Analyzer mode is ON - starting background threads
[INFO] Execution engine thread started successfully
[INFO] Square-off scheduler started successfully
[INFO] Scheduling MIS square-off jobs (IST timezone):
[INFO]   NSE_BSE: 15:15 IST (Job ID: squareoff_NSE_BSE)
[INFO]   CDS_BCD: 16:45 IST (Job ID: squareoff_CDS_BCD)
[INFO]   MCX: 23:30 IST (Job ID: squareoff_MCX)
[INFO]   NCDEX: 17:00 IST (Job ID: squareoff_NCDEX)
[INFO]   Backup check: Every 1 minute (Job ID: squareoff_backup)
```

## Step 3: Check Your Funds

Before placing orders, verify your sandbox capital:

```python
import requests

url = "http://127.0.0.1:5000/api/v1/funds"
headers = {"Content-Type": "application/json"}

payload = {
    "apikey": "your_api_key_here"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "data": {
        "availablecash": 10000000.00,
        "collateral": 0.00,
        "m2munrealized": 0.00,
        "m2mrealized": 0.00,
        "utiliseddebits": 0.00,
        "grossexposure": 0.00,
        "totalpnl": 0.00,
        "last_reset": "2025-10-02 00:00:00",
        "reset_count": 0
    },
    "mode": "analyze"
}
```

## Step 4: Place Your First Order

### Market Order Example

```python
import requests

url = "http://127.0.0.1:5000/api/v1/placeorder"
headers = {"Content-Type": "application/json"}

payload = {
    "apikey": "your_api_key_here",
    "strategy": "Test Strategy",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "orderid": "SB-20251002-101530-abc12345",
    "message": "Order placed successfully",
    "mode": "analyze"
}
```

### Limit Order Example

```python
payload = {
    "apikey": "your_api_key_here",
    "strategy": "Test Strategy",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 50,
    "price": 590.50,
    "pricetype": "LIMIT",
    "product": "MIS"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

### Stop-Loss Order Example

```python
payload = {
    "apikey": "your_api_key_here",
    "strategy": "Test Strategy",
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 25,
    "price": 1450.00,        # Limit price
    "trigger_price": 1455.00, # Trigger price
    "pricetype": "SL",
    "product": "MIS"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## Step 5: Check Order Status

### View Orderbook

```python
url = "http://127.0.0.1:5000/api/v1/orderbook"

payload = {
    "apikey": "your_api_key_here"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "data": {
        "orders": [
            {
                "orderid": "SB-20251002-101530-abc12345",
                "symbol": "RELIANCE",
                "exchange": "NSE",
                "action": "BUY",
                "quantity": 10,
                "filled_quantity": 10,
                "pending_quantity": 0,
                "order_status": "complete",
                "average_price": 2892.50,
                "price_type": "MARKET",
                "product": "MIS",
                "order_timestamp": "2025-10-02 10:15:30"
            }
        ]
    },
    "mode": "analyze"
}
```

### Check Specific Order

```python
url = "http://127.0.0.1:5000/api/v1/orderstatus"

payload = {
    "apikey": "your_api_key_here",
    "orderid": "SB-20251002-101530-abc12345"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

## Step 6: View Your Position

```python
url = "http://127.0.0.1:5000/api/v1/positionbook"

payload = {
    "apikey": "your_api_key_here"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "data": [
        {
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "product": "MIS",
            "quantity": 10,
            "average_price": 2892.50,
            "ltp": 2895.75,
            "pnl": 32.50,
            "pnl_percent": 0.1123
        }
    },
    "mode": "analyze"
}
```

## Step 7: Close Your Position

```python
url = "http://127.0.0.1:5000/api/v1/closeposition"

payload = {
    "apikey": "your_api_key_here",
    "symbol": "RELIANCE",
    "exchange": "NSE",
    "product": "MIS"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "orderid": "SB-20251002-103045-def67890",
    "message": "Position closed successfully",
    "mode": "analyze"
}
```

## Step 8: View Tradebook

```python
url = "http://127.0.0.1:5000/api/v1/tradebook"

payload = {
    "apikey": "your_api_key_here"
}

response = requests.post(url, json=payload, headers=headers)
print(response.json())
```

**Expected Response**:
```json
{
    "status": "success",
    "data": [
        {
            "tradeid": "TRADE-20251002-101530-abc123",
            "orderid": "SB-20251002-101530-abc12345",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "BUY",
            "quantity": 10,
            "price": 2892.50,
            "trade_value": 28925.00,
            "product": "MIS",
            "trade_timestamp": "02-Oct-2025 10:15:30"
        },
        {
            "tradeid": "TRADE-20251002-103045-def678",
            "orderid": "SB-20251002-103045-def67890",
            "symbol": "RELIANCE",
            "exchange": "NSE",
            "action": "SELL",
            "quantity": 10,
            "price": 2895.75,
            "trade_value": 28957.50,
            "product": "MIS",
            "trade_timestamp": "02-Oct-2025 10:30:45"
        }
    ],
    "mode": "analyze"
}
```

## Common First-Time Issues

### Issue 1: Orders Not Executing

**Symptom**: LIMIT/SL orders remain "open" indefinitely

**Solution**: Check execution engine is running
```python
from sandbox.execution_thread import is_execution_engine_running
print(is_execution_engine_running())  # Should be True
```

### Issue 2: Insufficient Funds Error

**Symptom**: Order rejected with "Insufficient funds"

**Solution**: Check margin requirements and available balance
```python
# Get funds
url = "http://127.0.0.1:5000/api/v1/funds"
response = requests.post(url, json={"apikey": "your_key"})
print(f"Available: ₹{response.json()['data']['availablecash']}")
```

### Issue 3: Symbol Not Found

**Symptom**: Order rejected with "Symbol not found"

**Solution**: Ensure symbol master is updated
```bash
# Download latest symbols
python utils/master_contract_download.py
```

### Issue 4: Authentication Errors for Quotes

**Symptom**: Logs show "Failed to fetch quote: Authentication failed"

**Solution**: Configure broker API credentials
```python
# Check if API key is configured
from database.auth_db import ApiKeys
api_key = ApiKeys.query.first()
if not api_key:
    print("No API key configured. Add broker credentials.")
```

## Configuration Changes

### Access Sandbox Settings

Navigate to: `http://127.0.0.1:5000/sandbox`

Or programmatically:
```python
from database.sandbox_db import get_all_configs
configs = get_all_configs()
print(configs)
```

### Common Configuration Changes

**Change Starting Capital**:
```python
from database.sandbox_db import set_config
set_config('starting_capital', '5000000.00')  # ₹50 Lakhs
```

**Change Square-off Time**:
```python
set_config('nse_bse_square_off_time', '15:20')  # 3:20 PM
```

**Change Leverage**:
```python
set_config('equity_mis_leverage', '10')  # 10x leverage
```

## Testing Scenarios

### Test 1: Market Order Execution
```python
# Place market order - should execute immediately
payload = {
    "apikey": "your_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "pricetype": "MARKET",
    "product": "MIS"
}
```

### Test 2: Limit Order Execution
```python
# Place limit order below LTP - should execute when price drops
# Current LTP = 600, Limit = 595
payload = {
    "apikey": "your_key",
    "symbol": "SBIN",
    "exchange": "NSE",
    "action": "BUY",
    "quantity": 10,
    "price": 595.00,
    "pricetype": "LIMIT",
    "product": "MIS"
}
```

### Test 3: Stop-Loss Execution
```python
# Place SL order - triggers at 1455, executes at LTP
payload = {
    "apikey": "your_key",
    "symbol": "INFY",
    "exchange": "NSE",
    "action": "SELL",
    "quantity": 5,
    "price": 1450.00,
    "trigger_price": 1455.00,
    "pricetype": "SL",
    "product": "MIS"
}
```

### Test 4: Position Netting
```python
# Buy 100 shares
# Then sell 50 shares
# Net position should be 50 long
```

### Test 5: Auto Square-off
```python
# Place MIS order before square-off time
# Position should automatically close at 15:15 IST
```

## Next Steps

Now that you've completed your first trades, explore:

1. **[Order Management](03_order_management.md)**: Learn about all order types
2. **[Margin System](04_margin_system.md)**: Understand margin calculations
3. **[Position Management](05_position_management.md)**: Master position tracking
4. **[Auto Square-Off](06_auto_squareoff.md)**: Configure auto square-off

## Quick Reference

### API Endpoints
- **Place Order**: `/api/v1/placeorder`
- **Cancel Order**: `/api/v1/cancelorder`
- **Modify Order**: `/api/v1/modifyorder`
- **Orderbook**: `/api/v1/orderbook`
- **Order Status**: `/api/v1/orderstatus`
- **Positions**: `/api/v1/positionbook`
- **Close Position**: `/api/v1/closeposition`
- **Tradebook**: `/api/v1/tradebook`
- **Funds**: `/api/v1/funds`
- **Holdings**: `/api/v1/holdings`

### Response Indicators
All sandbox responses include: `"mode": "analyze"`

---

**Previous**: [Overview](01_overview.md) | **Next**: [Order Management](03_order_management.md)
