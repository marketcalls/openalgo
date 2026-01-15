# Options Order API Documentation

## Overview

The **Options Order API** (`/api/v1/optionsorder`) is a high-level endpoint that combines option symbol resolution with order placement in a single API call. It automatically:

1. Resolves the option symbol based on underlying and offset from ATM
2. Places the order with the resolved symbol
3. Works in both **Live Mode** (real broker orders) and **Analyze Mode** (sandbox/virtual orders)

This API simplifies options trading by eliminating the need to manually calculate strike prices and construct option symbols.

## Key Features

- **Automatic Symbol Resolution**: Calculates ATM from real-time LTP and resolves option symbol
- **Dual Mode Operation**: Works in both live trading and sandbox (analyze) mode
- **Full Order Support**: All order types (MARKET, LIMIT, SL, SL-M)
- **Product Support**: MIS (intraday) and NRML (overnight) for options
- **Strategy Tracking**: Associates orders with strategy names for analytics
- **Error Handling**: Comprehensive error messages for debugging

## Endpoint

```
POST /api/v1/optionsorder
```

## Request Parameters

| Parameter | Type | Required | Description | Example |
|-----------|------|----------|-------------|---------|
| `apikey` | string | Yes | OpenAlgo API key | `"abc123xyz"` |
| `strategy` | string | Yes | Strategy name for tracking | `"iron_condor"` |
| `underlying` | string | Yes | Underlying symbol | `"NIFTY"`, `"NIFTY28NOV24FUT"` |
| `exchange` | string | Yes | Exchange code | `"NSE_INDEX"`, `"NSE"`, `"NFO"` |
| `expiry_date` | string | No | Expiry in DDMMMYY format | `"28NOV24"` |
| `strike_int` | integer | Yes | Strike price interval | `50` (NIFTY), `100` (BANKNIFTY) |
| `offset` | string | Yes | Strike offset from ATM | `"ATM"`, `"ITM2"`, `"OTM5"` |
| `option_type` | string | Yes | Call or Put | `"CE"`, `"PE"` |
| `action` | string | Yes | Buy or Sell | `"BUY"`, `"SELL"` |
| `quantity` | integer | Yes | Order quantity | `75`, `150` |
| `pricetype` | string | No | Order type (default: MARKET) | `"MARKET"`, `"LIMIT"`, `"SL"`, `"SL-M"` |
| `product` | string | No | Product type (default: MIS) | `"MIS"`, `"NRML"` |
| `price` | float | No | Limit price (default: 0.0) | `50.0` |
| `trigger_price` | float | No | Trigger price for SL orders | `55.0` |
| `disclosed_quantity` | integer | No | Iceberg quantity | `0` |

### Parameter Notes

- **`expiry_date`**: Optional if underlying includes expiry (e.g., `NIFTY28NOV24FUT`)
- **`offset`**: Supports ATM, ITM1-ITM50, OTM1-OTM50
- **`product`**: Options only support MIS and NRML (CNC not supported)
- **`quantity`**: Must be a multiple of lot size (e.g., NIFTY = 25, BANKNIFTY = 15)

## Response Format

### Success Response (Live Mode) - 200

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

### Success Response (Analyze Mode) - 200

```json
{
  "status": "success",
  "orderid": "SB-1234567890",
  "symbol": "NIFTY28NOV2423500CE",
  "exchange": "NFO",
  "underlying": "NIFTY",
  "underlying_ltp": 23587.50,
  "offset": "ITM2",
  "option_type": "CE",
  "mode": "analyze"
}
```

### Error Responses

**400 - Validation Error**
```json
{
  "status": "error",
  "message": "Validation error",
  "errors": {
    "strike_int": ["Missing data for required field."]
  }
}
```

**403 - Invalid API Key**
```json
{
  "status": "error",
  "message": "Invalid openalgo apikey"
}
```

**404 - Symbol Not Found**
```json
{
  "status": "error",
  "message": "Option symbol NIFTY28NOV2425500CE not found in NFO. Symbol may not exist or master contract needs update."
}
```

**500 - Order Placement Failed**
```json
{
  "status": "error",
  "message": "Insufficient funds to place order"
}
```

## How It Works

```
Client Request
    ↓
[1] Validate Request
    ↓
[2] Resolve Option Symbol
    ├─ Fetch underlying LTP
    ├─ Calculate ATM strike
    ├─ Apply offset (ITM/OTM)
    └─ Find symbol in database
    ↓
[3] Check Analyze Mode
    ├─ ON → Route to Sandbox
    └─ OFF → Route to Live Broker
    ↓
[4] Place Order
    ├─ Sandbox: Virtual order in sandbox.db
    └─ Live: Real order via broker API
    ↓
[5] Return Response
    └─ OrderID + Symbol + Details
```

## Live vs Analyze Mode

### Live Mode
- **Enabled When**: Analyze Mode toggle is OFF in OpenAlgo settings
- **Behavior**: Places real orders with your connected broker
- **Order ID**: Broker's order ID (e.g., `"240123000001234"`)
- **Response**: No `"mode"` field in response
- **Database**: Orders logged to `apilog` database
- **Execution**: Real market execution, subject to broker's systems

### Analyze Mode (Sandbox)
- **Enabled When**: Analyze Mode toggle is ON in OpenAlgo settings
- **Behavior**: Places virtual orders in sandbox environment
- **Order ID**: Sandbox ID with `SB-` prefix (e.g., `"SB-1234567890"`)
- **Response**: Includes `"mode": "analyze"` field
- **Database**: Orders stored in `sandbox.db` database
- **Execution**: Simulated execution with real market data
- **Features**:
  - Virtual capital management
  - Realistic margin calculations
  - Auto square-off for MIS
  - Real-time P&L tracking

### Toggling Between Modes

The system automatically detects which mode is active. No changes needed in API requests.

```python
# Same API call works in both modes
response = requests.post("http://127.0.0.1:5000/api/v1/optionsorder", json=payload)

# Response indicates the mode
if response.json().get('mode') == 'analyze':
    print("Order placed in sandbox")
else:
    print("Order placed with live broker")
```

## Examples

### Example 1: Buy NIFTY ATM Call (MARKET Order)

**Request:**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/optionsorder \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your_api_key",
    "strategy": "nifty_weekly",
    "underlying": "NIFTY",
    "exchange": "NSE_INDEX",
    "expiry_date": "28NOV24",
    "strike_int": 50,
    "offset": "ATM",
    "option_type": "CE",
    "action": "BUY",
    "quantity": 75,
    "pricetype": "MARKET",
    "product": "MIS"
  }'
```

**Scenario:**
- NIFTY LTP: 23,987.50
- ATM Strike: 24,000
- Resolved Symbol: `NIFTY28NOV2424000CE`
- Action: Buy 75 qty (3 lots)

### Example 2: Sell BANKNIFTY ITM2 Put (NRML)

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "banknifty_short_put",
  "underlying": "BANKNIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28NOV24",
  "strike_int": 100,
  "offset": "ITM2",
  "option_type": "PE",
  "action": "SELL",
  "quantity": 30,
  "pricetype": "MARKET",
  "product": "NRML"
}
```

**Scenario:**
- BANKNIFTY LTP: 51,287.50
- ATM Strike: 51,300
- ITM2 for PE = 51,500 (ATM + 2 × 100)
- Resolved Symbol: `BANKNIFTY28NOV2451500PE`
- Action: Sell 30 qty (2 lots)

### Example 3: Buy with LIMIT Order

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "nifty_scalping",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28NOV24",
  "strike_int": 50,
  "offset": "OTM1",
  "option_type": "CE",
  "action": "BUY",
  "quantity": 75,
  "pricetype": "LIMIT",
  "product": "MIS",
  "price": 50.0
}
```

**Note**: Order will only execute if option premium reaches or goes below 50.0

### Example 4: Stop Loss Order

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "protective_stop",
  "underlying": "NIFTY",
  "exchange": "NSE_INDEX",
  "expiry_date": "28NOV24",
  "strike_int": 50,
  "offset": "ATM",
  "option_type": "PE",
  "action": "SELL",
  "quantity": 75,
  "pricetype": "SL",
  "product": "MIS",
  "price": 100.0,
  "trigger_price": 105.0
}
```

**Logic**: When option premium hits 105.0, a LIMIT order at 100.0 is triggered

### Example 5: Iron Condor (4 Legs)

```python
import requests

def place_iron_condor(api_key, underlying, expiry, strike_int):
    """
    Iron Condor:
    - Sell OTM1 Call
    - Sell OTM1 Put
    - Buy OTM3 Call
    - Buy OTM3 Put
    """
    base_payload = {
        "apikey": api_key,
        "strategy": "iron_condor",
        "underlying": underlying,
        "exchange": "NSE_INDEX",
        "expiry_date": expiry,
        "strike_int": strike_int,
        "pricetype": "MARKET",
        "product": "MIS",
        "quantity": 75
    }

    legs = [
        {"offset": "OTM1", "option_type": "CE", "action": "SELL"},
        {"offset": "OTM1", "option_type": "PE", "action": "SELL"},
        {"offset": "OTM3", "option_type": "CE", "action": "BUY"},
        {"offset": "OTM3", "option_type": "PE", "action": "BUY"}
    ]

    order_ids = []
    for leg in legs:
        payload = {**base_payload, **leg}
        response = requests.post(
            "http://127.0.0.1:5000/api/v1/optionsorder",
            json=payload
        )
        if response.json().get('status') == 'success':
            order_ids.append(response.json().get('orderid'))
        else:
            print(f"Failed: {response.json().get('message')}")
            break

    return order_ids

# Usage
orders = place_iron_condor("your_api_key", "NIFTY", "28NOV24", 50)
print(f"Placed {len(orders)} orders: {orders}")
```

### Example 6: Using Underlying with Embedded Expiry

**Request:**
```json
{
  "apikey": "your_api_key",
  "strategy": "futures_options",
  "underlying": "NIFTY28NOV24FUT",
  "exchange": "NFO",
  "strike_int": 50,
  "offset": "OTM2",
  "option_type": "CE",
  "action": "BUY",
  "quantity": 75,
  "pricetype": "MARKET",
  "product": "MIS"
}
```

**Note**: Expiry date (28NOV24) is automatically extracted from underlying

## Strategy Patterns

### 1. Straddle (Buy ATM Call + Put)

```python
def buy_straddle(api_key, underlying, expiry, strike_int, quantity):
    for option_type in ["CE", "PE"]:
        payload = {
            "apikey": api_key,
            "strategy": "straddle",
            "underlying": underlying,
            "exchange": "NSE_INDEX",
            "expiry_date": expiry,
            "strike_int": strike_int,
            "offset": "ATM",
            "option_type": option_type,
            "action": "BUY",
            "quantity": quantity,
            "pricetype": "MARKET",
            "product": "MIS"
        }
        requests.post("http://127.0.0.1:5000/api/v1/optionsorder", json=payload)
```

### 2. Strangle (Buy OTM Call + Put)

```python
def buy_strangle(api_key, underlying, expiry, strike_int, quantity, otm_level=2):
    for option_type in ["CE", "PE"]:
        payload = {
            "apikey": api_key,
            "strategy": "strangle",
            "underlying": underlying,
            "exchange": "NSE_INDEX",
            "expiry_date": expiry,
            "strike_int": strike_int,
            "offset": f"OTM{otm_level}",
            "option_type": option_type,
            "action": "BUY",
            "quantity": quantity,
            "pricetype": "MARKET",
            "product": "MIS"
        }
        requests.post("http://127.0.0.1:5000/api/v1/optionsorder", json=payload)
```

### 3. Covered Call (Long Stock + Short Call)

```python
def covered_call(api_key, underlying, expiry, strike_int, quantity, otm_level=2):
    # Assuming stock is already owned
    # Sell OTM Call
    payload = {
        "apikey": api_key,
        "strategy": "covered_call",
        "underlying": underlying,
        "exchange": "NSE",
        "expiry_date": expiry,
        "strike_int": strike_int,
        "offset": f"OTM{otm_level}",
        "option_type": "CE",
        "action": "SELL",
        "quantity": quantity,
        "pricetype": "MARKET",
        "product": "NRML"
    }
    requests.post("http://127.0.0.1:5000/api/v1/optionsorder", json=payload)
```

## Error Codes

| Status Code | Description |
|-------------|-------------|
| 200 | Success - Order placed |
| 400 | Validation error or missing parameters |
| 403 | Authentication error - Invalid API key |
| 404 | Option symbol not found in database |
| 500 | Server error or order placement failed |

## Rate Limiting

- **Limit**: 10 requests per second (configurable via `ORDER_RATE_LIMIT` environment variable)
- **Scope**: Per API endpoint
- **Behavior**: Returns 429 status if limit exceeded

## Important Notes

1. **Analyze Mode Detection**: The API automatically detects whether Analyze Mode is ON or OFF. No changes needed in API requests.

2. **Order Validation**: Orders are validated in both live and analyze mode. Invalid orders are rejected immediately.

3. **Lot Size**: Ensure quantity is a multiple of the option's lot size:
   - NIFTY: 25
   - BANKNIFTY: 15
   - FINNIFTY: 25
   - MIDCPNIFTY: 50
   - Equity options: Varies (check contract specifications)

4. **Margin Requirements**:
   - **Live Mode**: Broker's margin requirements apply
   - **Analyze Mode**: Sandbox uses configurable leverage settings

5. **Symbol Resolution**: If the calculated option symbol doesn't exist in the master contract database, the order will fail with 404.

6. **Auto Square-off**: In Analyze Mode, MIS orders are automatically squared off at configured times (e.g., 3:15 PM for NSE).

## Testing in Sandbox

To test without risking real capital:

1. Enable **Analyze Mode** in OpenAlgo settings
2. Use the same API calls - they will route to sandbox automatically
3. Monitor virtual orders in the Sandbox dashboard
4. Check P&L and positions in sandbox environment
5. Disable Analyze Mode to switch back to live trading

## Related Endpoints

- `/api/v1/optionsymbol` - Get option symbol without placing order
- `/api/v1/placeorder` - Place order with known symbol
- `/api/v1/cancelorder` - Cancel an order
- `/api/v1/positionbook` - View open positions
- `/api/v1/orderbook` - View all orders

## Support

For issues:
- Check Analyze Mode status in settings
- Verify master contract data is updated
- Review API logs for detailed error messages
- Ensure underlying symbol and exchange are correct

---

**Version**: 1.0
**Last Updated**: October 2025
