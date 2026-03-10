# Angel One Broker Integration Guide
## Complete Setup for OpenAlgo + Angel One (Angel Broking)

---

## 📋 Prerequisites

- Active Angel One Account at https://www.angel-one.com
- Mobile/Email verified
- PAN linked to account
- Bank account linked
- Internet connectivity

---

## 🔐 Step 1: Get Angel One API Credentials

### Option A: Official Angel API (OAuth2)

1. **Contact Angel Support**:
   - Email: developer@angelbroking.com
   - Request: "API Access for OpenAlgo"
   - Provide: Your registered mobile number, PAN, trading account number

2. **Receive Credentials**:
   - Client ID
   - Client Secret
   - Auth URL
   - Token URL

### Option B: SmartAPI (Recommended - Self-Service)

1. **Login to SmartAPI Portal**:
   - Go to: https://smartlogin.angelbroking.com
   - Login with your credentials

2. **Generate API Keys**:
   - Dashboard → API Profile
   - Click "Generate New API Key"
   - Note down:
     - API Key
     - Auth Token
     - Client Code

---

## ⚙️ Step 2: Configure OpenAlgo

1. **Edit `.env` file**:
   ```bash
   # Broker: Angel
   VALID_BROKERS=angel
   
   # Angel API Credentials
   ANGEL_API_KEY=your-api-key
   ANGEL_CLIENT_CODE=your-client-code
   ANGEL_PASSWORD=your-trading-password
   
   # Angel Server
   ANGEL_API_BASE_URL=https://smartapi.angelbroking.com/rest/secure
   ```

2. **Create API Profile (if not exists)**:
   - Go to Angel One app
   - Settings → API Management
   - Create Profile with permissions:
     - ✅ Orders
     - ✅ Holdings
     - ✅ Positions
     - ✅ Quotes
     - ✅ Funds

3. **Restart OpenAlgo**:
   ```bash
   python app.py
   ```

---

## 🔗 Step 3: Broker Login in OpenAlgo

1. **Open OpenAlgo Dashboard**:
   - Navigate to: http://127.0.0.1:5000

2. **Connect Angel Broker**:
   - Go to: Connections → Angel One
   - Paste API Key
   - Click "Authenticate"

3. **Two-Factor Authentication**:
   - Check your phone for OTP
   - Or use TOTP app if configured
   - Enter OTP in OpenAlgo
   - Successfully connected ✅

---

## ✅ Step 4: Verify Connection

### Test API Connectivity

```python
import requests

API_KEY = "your-openalgo-api-key"
ANGEL_TOKEN = "received-from-angel"

# Check account funds
response = requests.post(
    "http://127.0.0.1:5000/api/v1/get_funds",
    json={
        "apikey": API_KEY,
        "broker": "angel"
    }
)

print(response.json())
# Expected: {"status": "success", "balance": 500000, "used_margin": 0, ...}
```

### Health Check

```bash
curl http://127.0.0.1:5000/api/v1/health \
  -H "X-BROKER: angel" \
  -H "X-API-KEY: your-api-key"
```

---

## 🚀 Step 5: Place Your First Trade

### Python Example

```python
import requests
from decimal import Decimal

API_KEY = "your-openalgo-api-key"

# Place a BUY order
order_payload = {
    "apikey": API_KEY,
    "broker": "angel",
    "symbol": "NSE:SBIN-EQ",
    "quantity": 1,
    "price": 550.00,
    "order_type": "LIMIT",
    "side": "BUY",
    "product_type": "MIS"  # MIS or CNC
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/place_order",
    json=order_payload
)

order_response = response.json()
print(f"Order ID: {order_response['order_id']}")
print(f"Status: {order_response['status']}")
```

### Supported Product Types

| Product | Description | Holding | Margin |
|---------|-------------|---------|--------|
| MIS | Intra-day | Till 3:30 PM | 4-10x |
| CNC | Delivery | Till settlement | None |
| NRML | Options/Futures | Till expiry | 2-5x |

---

## 📊 Symbol Mapping

Angel uses specific symbol codes. Mapping handled automatically:

| Symbol Format | Angel Code | Example |
|---------------|-----------|---------|
| NSE:SBIN-EQ | SBIN-EQ | Equity |
| NFO:NIFTY24JAN24000CE | NIFTY24JAN24000CE | Options |
| NFO:NIFTY-FUT | NIFTY24JAN24000 | Futures |

---

## 🔔 Angel One Features Supported

### ✅ Implemented

- [x] Single Leg Orders (Buy/Sell)
- [x] Market + Limit Orders
- [x] Intra-day + Delivery
- [x] Position Tracking
- [x] Holdings View
- [x] Funds Inquiry
- [x] Order History
- [x] Trade History
- [x] Real-time Quotes
- [x] GTT Orders (Good Till Triggered)

### ⏳ Coming Soon

- [ ] Bracket Orders
- [ ] Cover Orders
- [ ] Multi-leg Options
- [ ] Basket Orders

---

## ⚠️ Important Notes

### Static IP Requirement (From April 1, 2026)

Angel now mandates static IP registration for high-frequency API access.

**Check Current IP**:
```bash
curl https://api.ipify.org
```

**Register in Angel Dashboard**:
1. Login to Angel One app
2. Settings → API Management → Security
3. Add "IP Whitelist"
4. Enter your static IP
5. Save ✅

### Rate Limits

- **Orders**: 10 per minute
- **Quotes**: 1 per second per symbol
- **Data**: 100 requests per minute

---

## 🔧 Troubleshooting

### "Authentication Failed"
```
Error: Invalid API Key or Password
Solution: Regenerate API Key in SmartAPI portal
         Verify password is correct
```

### "Connection Timeout"
```
Error: Could not connect to Angel servers
Solution: Check internet connectivity
         Verify Angel servers are up (status.angel-one.com)
```

### "Insufficient Margin"
```
Error: Cannot place order - insufficient margin
Solution: Check available margin in app
         Reduce order size
         Close existing positions
```

### "Symbol Not Found"
```
Error: NSE:INVALID-SYM not found
Solution: Use correct symbol (SBIN-EQ, not SBIN)
         Check market hours (9:15 AM - 3:30 PM IST)
```

### "GTT Order Not Supported"
```
Error: GTT orders not allowed for this symbol
Solution: Use standard limit orders
         GTT only available for NSE equity
```

---

## 📞 Support

- **Angel One Status**: https://status.angel-one.com
- **Angel Developer Docs**: https://smartapi.angelbroking.com/docs
- **OpenAlgo Docs**: https://docs.openalgo.in
- **Angel Support**: 1-800-50-50-50 (toll-free)

---

**Last Updated**: March 10, 2026  
**Status**: Production Ready ✅  
**Required for**: Trading with Angel One via OpenAlgo
