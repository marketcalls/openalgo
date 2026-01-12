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

# Test quotes
curl -X POST "$BASE_URL/api/v1/quotes" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","symbol":"RELIANCE","exchange":"NSE"}'

# Test funds
curl -X POST "$BASE_URL/api/v1/funds" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'"}'

# Test positions
curl -X POST "$BASE_URL/api/v1/positionbook" \
  -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'"}'
```

- [ ] Quotes endpoint
- [ ] Funds endpoint
- [ ] Positions endpoint
- [ ] Orderbook endpoint
- [ ] Place order endpoint

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

