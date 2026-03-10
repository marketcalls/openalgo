# Zerodha Broker Integration Guide
## Step-by-Step Setup and Configuration for OpenAlgo + Zerodha

---

## 📋 Prerequisites

- Active Zerodha Account (Kite)
- Zerodha API Credentials (API Key & Secret)
- OpenAlgo installed and running

---

## 🔐 Step 1: Get Zerodha API Credentials

1. **Login to Zerodha Console**:
   - Go to: https://console.kite.trade
   - Login with your Zerodha credentials

2. **Create App**:
   - Click "Create App"
   - App Title: "OpenAlgo"
   - App Domain: `http://127.0.0.1:5000`
   - Redirect URL: `http://127.0.0.1:5000/zerodha_callback`

3. **Copy Credentials**:
   - API Key
   - API Secret
   - Client ID

---

## ⚙️ Step 2: Configure OpenAlgo

1. **Edit `.env` file**:
   ```bash
   # Broker: Zerodha
   VALID_BROKERS=zerodha
   
   # Zerodha API Credentials
   ZERODHA_API_KEY=your-api-key
   ZERODHA_API_SECRET=your-api-secret
   ZERODHA_CLIENT_ID=your-client-id
   
   # Zerodha Authentication
   ZERODHA_USERNAME=your-kite-username
   ZERODHA_PASSWORD=your-kite-password
   ```

2. **Restart OpenAlgo**:
   ```bash
   python app.py
   ```

---

## 🔗 Step 3: Broker Login

1. **Open OpenAlgo Dashboard**:
   - Navigate to: http://127.0.0.1:5000

2. **Broker Credentials**:
   - Go to: Broker → Zerodha
   - Enter API Key & Secret
   - Click "Connect"

3. **Authorization**:
   - You'll be redirected to Zerodha
   - Approve API access
   - Returned to OpenAlgo (connected ✅)

---

## 🚀 Step 4: Verify Connection

### Check Connection Status

```bash
curl http://127.0.0.1:5000/api/v1/health \
  -H "X-BROKER: zerodha" \
  -H "X-API-KEY: your-api-key"
```

**Expected Response**:
```json
{
  "status": "connected",
  "broker": "zerodha",
  "balance": 1000000.00,
  "used_margin": 0.00,
  "available_margin": 1000000.00
}
```

---

## 💼 Step 5: Place Your First Order

```python
import requests

API_KEY = "your-openalgo-api-key"
ZERODHA_TOKEN = "your-zerodha-token"

payload = {
    "apikey": API_KEY,
    "symbol": "NSE:TCS-EQ",
    "quantity": 1,
    "price": 3800.00,
    "order_type": "LIMIT",
    "side": "BUY",
    "broker": "zerodha"
}

response = requests.post(
    "http://127.0.0.1:5000/api/v1/place_order",
    json=payload
)

print(response.json())
```

---

## 📊 Symbol Mapping

Zerodha symbols are automatically converted:

| Symbol Format | Zerodha Format | Example |
|---------------|----------------|---------|
| NSE:SBIN-EQ | EQ token | NSE:2885377 |
| NFO:NIFTY-FUT | FUT token | NFO:12345 |
| NFO:[SYMBOL]CE | OPT token | NFO:67890 |

---

## ⚠️ Important: Static IP Requirement (From April 1, 2026)

Zerodha now requires **Static IP** for API access.

### Check Your Current IP

```bash
curl https://api.ipify.org
```

### Register Static IP

1. **Login to Zerodha Console**
2. Go to: API → Apps
3. Add your static IP address
4. Whitelist ✅

---

## 🔧 Troubleshooting

### "Connection Refused"
```
Error: Failed to connect to Zerodha
Solution: Verify API Key and Secret in .env
```

### "Invalid Token"
```
Error: Zerodha token expired
Solution: Re-authenticate in Broker Settings
```

### "IP Not Whitelisted"
```
Error: 403 Forbidden
Solution: Add your IP to Zerodha Console → API Security
```

### "Symbol Not Found"
```
Error: NSE:INVALID-SYM not found
Solution: Use correct symbol format (check Master Contract)
```

---

## ✅ Verification Checklist

- [ ] API credentials copied from Zerodha Console
- [ ] `.env` file configured correctly
- [ ] OpenAlgo restarted
- [ ] Broker connection established
- [ ] Health check passing
- [ ] Test order placed successfully
- [ ] Static IP registered (before April 1)

---

## 📞 Support

**Zerodha Documentation**: https://kite.trade/docs/  
**OpenAlgo Docs**: https://docs.openalgo.in  
**Zerodha Support**: https://support.zerodha.com

---

**Last Updated**: March 10, 2026  
**Status**: Production Ready ✅  
**Required for**: Trading with Zerodha via OpenAlgo
