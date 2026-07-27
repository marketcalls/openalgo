# OpenAlgo Quick Test Checklist

A condensed checklist for rapid testing. Use the full guide for detailed steps.

---

## Pre-Flight Checks (5 min)

```bash
# Start fresh
cd openalgo
git pull
uv sync
cd frontend && npm run build && cd ..
uv run app.py
```

- [ ] App starts without errors
- [ ] Frontend loads at http://127.0.0.1:5000
- [ ] No console errors in browser

---

## Critical Path Testing (30 min)

### Authentication
- [ ] Login works
- [ ] Logout works
- [ ] Session persists on refresh

### Broker Connection
- [ ] Broker login completes
- [ ] Master contracts download
- [ ] Dashboard shows funds

### Basic Trading Flow
- [ ] Symbol search works
- [ ] Place market order
- [ ] Order appears in orderbook
- [ ] Position shows correctly
- [ ] Cancel/modify order works
- [ ] Close position works

### Sandbox Mode
- [ ] Toggle to Analyzer mode
- [ ] Place sandbox order
- [ ] Verify real broker unaffected
- [ ] Toggle back to Live mode

### Real-time Features
- [ ] WebSocket connects
- [ ] Price updates in real-time
- [ ] Order status updates live

---

## Feature Testing Matrix

### Core Features

| Feature | Works | Notes |
|---------|-------|-------|
| Login | [ ] | |
| Setup (first run) | [ ] | |
| Password Reset | [ ] | |
| Broker OAuth | [ ] | |
| Broker TOTP | [ ] | |
| Symbol Search | [ ] | |
| LTP | [ ] | |
| Quotes | [ ] | |
| Depth | [ ] | |
| Historical | [ ] | |
| Place Order | [ ] | |
| Modify Order | [ ] | |
| Cancel Order | [ ] | |
| Orderbook | [ ] | |
| Positions | [ ] | |
| Holdings | [ ] | |
| Tradebook | [ ] | |
| Funds | [ ] | |
| P&L Tracker | [ ] | |

### Sandbox Features

| Feature | Works | Notes |
|---------|-------|-------|
| Mode Toggle | [ ] | |
| Sandbox Orders | [ ] | |
| Sandbox Positions | [ ] | |
| Sandbox Funds | [ ] | |
| Auto Square-off | [ ] | |
| Manual Reset | [ ] | |
| P&L History | [ ] | |

### Strategy Features

| Feature | Works | Notes |
|---------|-------|-------|
| Webhook Strategy | [ ] | |
| Python Strategy | [ ] | |
| ChartInk Strategy | [ ] | |
| TradingView Webhook | [ ] | |
| GoCharting Webhook | [ ] | |

### Admin Features

| Feature | Works | Notes |
|---------|-------|-------|
| Admin Dashboard | [ ] | |
| Freeze Quantities | [ ] | |
| Market Holidays | [ ] | |
| Market Timings | [ ] | |
| Security Dashboard | [ ] | |
| Traffic Monitor | [ ] | |
| Latency Monitor | [ ] | |

### Telegram

| Feature | Works | Notes |
|---------|-------|-------|
| Bot Config | [ ] | |
| Notifications | [ ] | |
| Commands | [ ] | |

### UI/UX

| Feature | Works | Notes |
|---------|-------|-------|
| Light Theme | [ ] | |
| Dark Theme | [ ] | |
| Mobile Layout | [ ] | |
| All Nav Links | [ ] | |

---

## API Endpoints Quick Check

```bash
# Set your API key
API_KEY="your_api_key_here"
BASE_URL="http://127.0.0.1:5000"

# Test equity quotes
curl -X POST "$BASE_URL/api/v1/quotes" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","symbol":"RELIANCE","exchange":"NSE"}'

# Test index quotes
curl -X POST "$BASE_URL/api/v1/quotes" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","symbol":"NIFTY","exchange":"NSE_INDEX"}'

# Test market depth
curl -X POST "$BASE_URL/api/v1/depth" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","symbol":"INFY","exchange":"NSE"}'

# Test funds
curl -X POST "$BASE_URL/api/v1/funds" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'"}'

# Test positions
curl -X POST "$BASE_URL/api/v1/positionbook" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'"}'

# Test historical data
curl -X POST "$BASE_URL/api/v1/history" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","symbol":"RELIANCE","exchange":"NSE","interval":"5m","start_date":"2025-01-01","end_date":"2025-01-13"}'
```

- [ ] Equity quotes endpoint
- [ ] Index quotes endpoint
- [ ] Market depth endpoint
- [ ] Funds endpoint
- [ ] Positions endpoint
- [ ] Orderbook endpoint
- [ ] Historical data endpoint
- [ ] Place order endpoint

---

## OpenAlgo Symbol Format Quick Reference

### Exchange Codes
| Code | Description |
|------|-------------|
| `NSE` | NSE Equities |
| `BSE` | BSE Equities |
| `NFO` | NSE F&O |
| `BFO` | BSE F&O |
| `CDS` | NSE Currency |
| `BCD` | BSE Currency |
| `MCX` | Commodities |
| `NSE_INDEX` | NSE Indices |
| `BSE_INDEX` | BSE Indices |

### Symbol Formats
```
Equity:   RELIANCE, INFY, TCS, SBIN
Index:    NIFTY, BANKNIFTY, SENSEX
Futures:  NIFTY27JAN26FUT, BANKNIFTY27JAN26FUT
Options (Monthly):  NIFTY27JAN2624000CE, BANKNIFTY27JAN2652000PE
Options (Weekly):   NIFTY13JAN2624000CE, BANKNIFTY13JAN2652000PE
Currency: USDINR27JAN26FUT, USDINR27JAN2684CE
MCX:      CRUDEOIL17JAN26FUT, GOLD05FEB26FUT
```

### Lot Sizes
| Symbol | Lot Size |
|--------|----------|
| NIFTY | 65 |
| BANKNIFTY | 30 |

### Test Symbols (Update expiry dates as needed)
| Type | Exchange | Symbol |
|------|----------|--------|
| Equity | NSE | `RELIANCE` |
| Equity | NSE | `INFY` |
| Index | NSE_INDEX | `NIFTY` |
| Index | NSE_INDEX | `BANKNIFTY` |
| Index | BSE_INDEX | `SENSEX` |
| Future | NFO | `NIFTY27JAN26FUT` |
| Future | NFO | `BANKNIFTY27JAN26FUT` |
| Option CE (Monthly) | NFO | `NIFTY27JAN2624000CE` |
| Option CE (Weekly) | NFO | `NIFTY13JAN2624000CE` |
| Option PE (Monthly) | NFO | `BANKNIFTY27JAN2652000PE` |
| Currency | CDS | `USDINR27JAN26FUT` |
| Commodity | MCX | `CRUDEOIL17JAN26FUT` |

---

## Platform Quick Check

### Python Versions
- [ ] 3.11: `python3.11 -m venv venv && source venv/bin/activate && pip install -r requirements.txt && python app.py`
- [ ] 3.12: `python3.12 -m venv venv && ...`
- [ ] 3.13: `python3.13 -m venv venv && ...`

### Operating Systems
- [ ] macOS
- [ ] Windows
- [ ] Ubuntu

### Browsers
- [ ] Chrome
- [ ] Firefox
- [ ] Safari
- [ ] Edge

### Docker
```bash
docker build -t openalgo .
docker run -p 5000:5000 openalgo
```
- [ ] Docker build succeeds
- [ ] Container runs
- [ ] App accessible

---

## Bug Quick Checks

### Double-Click Protection
- [ ] Rapidly click "Place Order" → Only 1 order

### Input Validation
- [ ] Quantity = 0 → Error
- [ ] Quantity = -1 → Error
- [ ] Price = 0 (limit) → Error
- [ ] Empty symbol → Error

### Session
- [ ] Expired session → Redirect to login
- [ ] Invalid CSRF → Error message

### Error Pages
- [ ] /nonexistent → 404 page
- [ ] Rate limit → 429 page

---

## Smoke Test Script

Run this sequence to verify basic functionality:

1. **Start App**
   ```bash
   uv run app.py
   ```

2. **Browser Tests**
   - Open http://127.0.0.1:5000
   - Login
   - Connect broker
   - Search "RELIANCE"
   - View quotes
   - Place test order (MIS, qty=1)
   - Check orderbook
   - Cancel order
   - Check positions
   - Logout

3. **API Tests**
   ```bash
   # From playground, test each category
   - Orders > Place Order
   - Data > Quotes
   - Portfolio > Orderbook
   - Portfolio > Funds
   ```

4. **WebSocket Test**
   - Go to /websocket/test
   - Subscribe to RELIANCE
   - Verify updates

5. **Sandbox Test**
   - Toggle to Analyzer
   - Place sandbox order
   - Verify in sandbox positions
   - Toggle back to Live

---

## Test Results Summary

| Category | Passed | Failed | Blocked |
|----------|--------|--------|---------|
| Auth | /5 | | |
| Broker | /5 | | |
| Trading | /10 | | |
| Data | /8 | | |
| Sandbox | /6 | | |
| WebSocket | /4 | | |
| Strategies | /5 | | |
| Telegram | /4 | | |
| API | /15 | | |
| UI/UX | /6 | | |
| **Total** | /68 | | |

**Tester:** _______________
**Date:** _______________
**Build:** _______________

---

## Critical Issues Found

| # | Issue | Severity | Status |
|---|-------|----------|--------|
| 1 | | | |
| 2 | | | |
| 3 | | | |

---

## Notes

_______________________________
_______________________________
_______________________________

