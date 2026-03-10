# OpenAlgo REST API Setup Guide
## Complete Integration Guide for Third-Party Applications

---

## 🎯 Overview

This guide helps you integrate OpenAlgo's REST API into your trading applications, whether you're using TradingView, Amibroker, Excel, Python, or custom applications.

---

## 📍 API Base URL

```
Base URL: http://127.0.0.1:5000/api/v1/
```

All API requests should be prefixed with this URL.

---

## 🔐 Authentication

### API Key Setup

1. **Generate API Key**:
   - Open OpenAlgo UI: http://127.0.0.1:5000
   - Navigate to: Settings → API Keys
   - Click "Generate New Key"
   - Copy the key (you won't see it again!)

2. **Using API Key**:
   ```json
   {
     "apikey": "your-api-key-here",
     "symbol": "NSE:SBIN-EQ",
     ...other parameters
   }
   ```

### Authentication Methods

**Method 1: Request Body (Recommended)**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/place_order \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "your-api-key",
    "symbol": "NSE:SBIN-EQ",
    "quantity": 1,
    "price": 500,
    "order_type": "LIMIT",
    "side": "BUY"
  }'
```

**Method 2: Header**
```bash
curl -X POST http://127.0.0.1:5000/api/v1/place_order \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: your-api-key" \
  -d '{...}'
```

---

## 🚀 Quick Start: Place an Order

### Python Example

```python
import requests
import json

API_URL = "http://127.0.0.1:5000/api/v1"
API_KEY = "your-api-key"

def place_order(symbol, quantity, price, order_type, side):
    payload = {
        "apikey": API_KEY,
        "symbol": symbol,
        "quantity": quantity,
        "price": price,
        "order_type": order_type,
        "side": side
    }
    
    response = requests.post(
        f"{API_URL}/place_order",
        json=payload
    )
    
    return response.json()

# Place a BUY order
result = place_order(
    symbol="NSE:SBIN-EQ",
    quantity=1,
    price=500,
    order_type="LIMIT",
    side="BUY"
)

print(result)
# Output: {'status': 'success', 'order_id': '12345', ...}
```

---

## 📚 Core Endpoints

### 1. Place Order

**POST** `/place_order`

```json
{
  "apikey": "string",
  "symbol": "NSE:SBIN-EQ",
  "quantity": 1,
  "price": 500.50,
  "order_type": "LIMIT",
  "side": "BUY",
  "execution_type": "REGULAR",
  "order_tag": "optional-tag"
}
```

**Response**:
```json
{
  "status": "success",
  "order_id": "12345",
  "symbol": "NSE:SBIN-EQ",
  "order_status": "PENDING"
}
```

### 2. Get Holdings

**GET** `/holdings?apikey=YOUR_KEY`

```json
{
  "status": "success",
  "holdings": [
    {
      "symbol": "NSE:SBIN-EQ",
      "quantity": 10,
      "average_price": 500.00,
      "current_price": 520.00,
      "pnl": 200.00
    }
  ]
}
```

### 3. Get Positions

**GET** `/positions?apikey=YOUR_KEY`

```json
{
  "status": "success",
  "positions": [
    {
      "symbol": "NSE:NIFTY-INDEX",
      "quantity": 1,
      "entry_price": 19500,
      "current_price": 19600,
      "pnl": 100
    }
  ]
}
```

### 4. Get Orders

**GET** `/orders?apikey=YOUR_KEY`

```json
{
  "status": "success",
  "orders": [
    {
      "order_id": "12345",
      "symbol": "NSE:SBIN-EQ",
      "quantity": 1,
      "price": 500,
      "order_status": "PENDING"
    }
  ]
}
```

### 5. Cancel Order

**POST** `/cancel_order`

```json
{
  "apikey": "YOUR_KEY",
  "order_id": "12345"
}
```

---

## 🎯 Symbol Format

All symbols follow this standardized format:

```
Exchange:Symbol-Type

Examples:
NSE:SBIN-EQ        # Equity
NFO:NIFTY24JAN24000CE  # Options (Call)
NFO:NIFTY24JAN24000PE  # Options (Put)
NSE:NIFTY-INDEX    # Index
MCX:CRUDEOIL-FUT   # Futures
```

---

## 💡 Order Types

| Type | Description | Example |
|------|-------------|---------|
| `LIMIT` | Price-based execution | Execute if price = ₹500 |
| `MARKET` | Immediate execution | Execute at current price |
| `STOP` | Limit after trigger | Stop at ₹490, sell at ₹489 |
| `STOP_LIMIT` | Combined stop+limit | Stop at ₹490, sell at ₹489 |

---

## 🔍 Error Handling

```python
response = requests.post(f"{API_URL}/place_order", json=payload)

if response.status_code == 200:
    data = response.json()
    if data['status'] == 'success':
        print(f"Order placed: {data['order_id']}")
    else:
        print(f"Order error: {data['message']}")
else:
    print(f"HTTP Error: {response.status_code}")
```

### Common Error Codes

| Code | Meaning | Solution |
|------|---------|----------|
| 401 | Invalid API key | Check API key in Settings |
| 400 | Invalid request | Check symbol format, quantities |
| 429 | Rate limited | Wait before retry |
| 500 | Server error | Check OpenAlgo is running |

---

## ⚡ Rate Limiting

- **Standard**: 100 requests/minute
- **Premium**: 1000 requests/minute

---

## 📝 Webhook Testing

Test your endpoint:

```bash
curl -X POST http://127.0.0.1:5000/api/v1/place_order \
  -H "Content-Type: application/json" \
  -d '{
    "apikey": "test-key",
    "symbol": "NSE:SBIN-EQ",
    "quantity": 1,
    "price": 500,
    "order_type": "LIMIT",
    "side": "BUY"
  }' | python -m json.tool
```

---

## 🚀 Integration Examples

### Excel Integration
Use `WEBSERVICE()` function with API endpoint.

### TradingView
Use Pine Script HTTP requests to OpenAlgo API.

### Python
Use `requests` library (see example above).

### Node.js
Use `axios` or `fetch` module.

---

## 📞 Troubleshooting

**"Connection refused"** → OpenAlgo not running
```bash
# Start OpenAlgo
python app.py
```

**"Invalid API key"** → Generate new key in Settings

**"Symbol not found"** → Check symbol format in Master Contract

---

## ✅ Verification Checklist

- [ ] OpenAlgo running on http://127.0.0.1:5000
- [ ] API Key generated and copied
- [ ] Can access `/orders` endpoint
- [ ] Can place test order successfully
- [ ] Can fetch holdings/positions
- [ ] Error handling implemented

---

**Last Updated**: March 10, 2026
**Version**: 1.0
**Status**: Production Ready ✅
