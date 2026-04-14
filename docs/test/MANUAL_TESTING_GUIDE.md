# OpenAlgo v2.0 - Comprehensive Manual Testing Guide

A systematic testing procedure to ensure quality and catch bugs effectively.

---

## Quick Start for Testers

```bash
# 1. Setup
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
cp .sample.env .env
# Edit .env with your broker credentials

# 2. Install & Build
pip install uv
uv sync
cd frontend && npm install && npm run build && cd ..

# 3. Run
uv run app.py

# 4. Access
open http://127.0.0.1:5000
```

---

## Table of Contents

1. [Authentication & Security](#1-authentication--security)
2. [Broker Integration](#2-broker-integration)
3. [Market Data](#3-market-data)
4. [Trading Operations](#4-trading-operations)
5. [P&L Calculations](#5-pnl-calculations)
6. [Sandbox Mode](#6-sandbox-mode)
7. [WebSocket & Real-time](#7-websocket--real-time)
8. [Strategies & Webhooks](#8-strategies--webhooks)
9. [Telegram Bot](#9-telegram-bot)
10. [API Testing](#10-api-testing)
11. [UI/UX Testing](#11-uiux-testing)
12. [Platform Compatibility](#12-platform-compatibility)
13. [Deployment](#13-deployment)
14. [Bug-Catching Scenarios](#14-bug-catching-scenarios)

---

## 1. Authentication & Security

### 1.1 First-Time Setup
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Fresh install setup | 1. Delete `db/` folder 2. Start app 3. Go to `/` | Redirect to `/setup` | [ ] |
| Create admin | Fill username, email, password | Account created, redirect to `/login` | [ ] |
| Weak password | Use "123456" as password | Error: Password too weak | [ ] |
| Setup re-access | Try `/setup` after account exists | Redirect to `/login` | [ ] |

### 1.2 Login Flow
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Valid login | Enter correct credentials | Redirect to `/broker` or `/dashboard` | [ ] |
| Wrong password | Enter incorrect password | Error message, no redirect | [ ] |
| Non-existent user | Enter unknown username | Generic error (no user enumeration) | [ ] |
| Case sensitivity | Login with different case username | Should work (case-insensitive) | [ ] |
| Session persistence | Login, refresh page | Stay logged in | [ ] |
| Logout | Click logout | Redirect to `/login`, session cleared | [ ] |

### 1.3 Password Reset
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Request reset | Enter valid email | Success message | [ ] |
| Email received | Check inbox | Reset email with link | [ ] |
| Valid reset link | Click link, enter new password | Password changed | [ ] |
| Expired link | Use link after 24 hours | Error: Link expired | [ ] |
| Reused link | Use same link twice | Error: Link already used | [ ] |

### 1.4 Rate Limiting
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Login rate limit | 6 rapid failed logins | 429 error, redirect to `/rate-limited` | [ ] |
| API rate limit | 60+ API calls/minute | 429 response | [ ] |
| Rate limit recovery | Wait 60 seconds | Access restored | [ ] |

### 1.5 Security Headers
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| CSRF token | Inspect POST form | `X-CSRFToken` header present | [ ] |
| Cookie flags | Inspect session cookie | HttpOnly=true, SameSite=Lax | [ ] |
| XSS attempt | Enter `<script>alert(1)</script>` in inputs | Script not executed | [ ] |

---

## 2. Broker Integration

### 2.1 OAuth Brokers

**Zerodha:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Initiate OAuth | Select Zerodha, click Connect | Redirect to Kite login | [ ] |
| Complete OAuth | Login to Kite | Redirect back with token | [ ] |
| Invalid API key | Set wrong `BROKER_API_KEY` | Clear error message | [ ] |

**Upstox:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Initiate OAuth | Select Upstox, click Connect | Redirect to Upstox login | [ ] |
| Complete OAuth | Complete login | Token received | [ ] |

**Fyers:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Initiate OAuth | Select Fyers, click Connect | Redirect to Fyers | [ ] |
| Complete OAuth | Complete login | Token received | [ ] |

**Dhan:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Initiate OAuth | Select Dhan, click Connect | Redirect to Dhan | [ ] |
| Complete OAuth | Complete login | Token received | [ ] |

### 2.2 TOTP Brokers

**Angel One:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| TOTP page | Select Angel One | Show TOTP input form | [ ] |
| Valid TOTP | Enter correct TOTP | Authentication success | [ ] |
| Invalid TOTP | Enter wrong TOTP | Error message | [ ] |
| Expired TOTP | Wait 30s, use same TOTP | Error: TOTP expired | [ ] |

### 2.3 Master Contracts
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Auto download | Login to broker | Contracts downloaded | [ ] |
| Search after download | Search "RELIANCE" | Results appear | [ ] |
| F&O symbols | Search "NIFTY" in NFO | Options chain available | [ ] |
| Manual refresh | Click refresh contracts | Updated contracts | [ ] |

---

## 3. Market Data

### 3.1 Symbol Search
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Equity search | Search "RELIANCE" | NSE:RELIANCE in results | [ ] |
| Index search | Search "NIFTY 50" | Index symbol found | [ ] |
| F&O search | Search "BANKNIFTY" | Options/futures found | [ ] |
| Partial search | Search "REL" | RELIANCE, RELAXO, etc. | [ ] |
| No results | Search "XYZABC123" | "No results" message | [ ] |
| Special chars | Search "L&T" | L&T found | [ ] |

### 3.2 LTP (Last Traded Price)
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Equity LTP | Get LTP for RELIANCE | Current price returned | [ ] |
| Index LTP | Get LTP for NIFTY 50 | Index value returned | [ ] |
| F&O LTP | Get LTP for NIFTY futures | Futures price returned | [ ] |
| Invalid symbol | Get LTP for "INVALID" | Error: Symbol not found | [ ] |
| After hours | Get LTP outside market | Last close price | [ ] |

### 3.3 Quotes
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Full quote | Get quote for INFY | OHLC, volume, prev close | [ ] |
| Quote fields | Verify all fields | open, high, low, close, volume, ltp | [ ] |
| Index quote | Get quote for NIFTY 50 | Index data returned | [ ] |

### 3.4 Market Depth
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| 5-level depth | Get depth for TCS | 5 bid + 5 ask levels | [ ] |
| Depth data | Verify fields | price, quantity, orders per level | [ ] |
| Total bid/ask | Sum quantities | Matches total_bid/total_ask | [ ] |

### 3.5 Historical Data
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| 1-min candles | Fetch intraday 1-min | OHLCV for each minute | [ ] |
| 5-min candles | Fetch intraday 5-min | Correct aggregation | [ ] |
| Daily candles | Fetch daily data | One candle per day | [ ] |
| Date range | Fetch specific range | Only requested dates | [ ] |
| Large range | Fetch 1 year daily | All data returned | [ ] |
| Invalid interval | Request "2-min" | Error: Invalid interval | [ ] |
| Future date | Request tomorrow's data | Error or empty response | [ ] |

---

## 4. Trading Operations

### 4.1 Order Placement

**Market Orders:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| BUY market | Place BUY MARKET order | Order executed | [ ] |
| SELL market | Place SELL MARKET order | Order executed | [ ] |
| F&O market | Place F&O market order | Order executed | [ ] |

**Limit Orders:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| BUY limit | Place BUY LIMIT order | Pending order created | [ ] |
| SELL limit | Place SELL LIMIT order | Pending order created | [ ] |
| Price validation | Limit price > 52w high | Warning or rejection | [ ] |

**Stop Loss Orders:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| SL order | Place SL order | Order with trigger | [ ] |
| SL-M order | Place SL-M order | Order with trigger | [ ] |
| Invalid trigger | Trigger > LTP for BUY SL | Error message | [ ] |

**Product Types:**
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| MIS order | Place MIS order | Intraday position | [ ] |
| CNC order | Place CNC order | Delivery position | [ ] |
| NRML order | Place NRML F&O order | Position created | [ ] |

### 4.2 Order Book
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| View orders | Open orderbook | All orders displayed | [ ] |
| Filter open | Filter by "Open" | Only pending orders | [ ] |
| Filter complete | Filter by "Complete" | Only executed orders | [ ] |
| Sort by time | Sort descending | Latest first | [ ] |
| Export CSV | Click export | CSV downloaded | [ ] |
| Refresh | Click refresh | Updated data | [ ] |

### 4.3 Order Modification
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Modify quantity | Change qty of pending order | Quantity updated | [ ] |
| Modify price | Change price | Price updated | [ ] |
| Modify trigger | Change trigger price | Trigger updated | [ ] |
| Modify executed | Try modify completed order | Error: Cannot modify | [ ] |

### 4.4 Order Cancellation
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Cancel single | Cancel one pending order | Order cancelled | [ ] |
| Cancel all | Click "Cancel All" | All pending cancelled | [ ] |
| Cancel executed | Try cancel completed | Error: Cannot cancel | [ ] |

### 4.5 Positions
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| View positions | Open positions page | All positions shown | [ ] |
| Position P&L | Check unrealized P&L | Correct calculation | [ ] |
| Close position | Click close on position | Position closed | [ ] |
| Close all | Click "Close All" | All positions closed | [ ] |
| Export | Export to CSV | CSV downloaded | [ ] |

### 4.6 Holdings
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| View holdings | Open holdings page | Delivery holdings shown | [ ] |
| P&L calculation | Check P&L | (CMP - Avg) * Qty | [ ] |
| Current value | Check value | CMP * Qty | [ ] |

### 4.7 Trade Book
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| View trades | Open tradebook | All trades shown | [ ] |
| Trade details | Check a trade | Symbol, price, qty, time | [ ] |
| Export | Export to CSV | CSV downloaded | [ ] |

---

## 5. P&L Calculations

### 5.1 Intraday P&L
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Buy then sell | Buy 10, Sell 10 at higher | Positive P&L | [ ] |
| Sell then buy | Short 10, Cover at lower | Positive P&L | [ ] |
| Partial close | Buy 10, Sell 5 | Realized + Unrealized | [ ] |
| Multiple trades | Multiple buy/sell | Cumulative P&L | [ ] |

### 5.2 P&L Tracker
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Open tracker | Go to `/pnl-tracker` | Chart displayed | [ ] |
| Real-time update | Trade while open | Chart updates | [ ] |
| Date range | Change date range | Historical data shown | [ ] |
| Screenshot | Take screenshot | Image saved | [ ] |

### 5.3 P&L Formulas
| Calculation | Formula | Verify |
|-------------|---------|--------|
| Unrealized P&L | (LTP - Avg Price) * Qty | [ ] |
| Realized P&L | (Sell Price - Buy Price) * Qty | [ ] |
| Total P&L | Realized + Unrealized | [ ] |
| Day P&L | Sum of today's realized P&L | [ ] |

---

## 6. Sandbox Mode

### 6.1 Configuration
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Access config | Go to `/sandbox` | Config page shown | [ ] |
| Set capital | Set 50,00,000 | Saved successfully | [ ] |
| Square-off times | Set NSE 15:15 | Time saved | [ ] |
| Reset day | Set Sunday 00:00 | Schedule saved | [ ] |

### 6.2 Sandbox Trading
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Enable sandbox | Toggle to Analyzer mode | Mode switched | [ ] |
| Place order | Place sandbox order | Virtual execution | [ ] |
| Check funds | View sandbox funds | Margin deducted | [ ] |
| Check positions | View sandbox positions | Position created | [ ] |
| Real broker | Verify real broker unaffected | No real orders | [ ] |

### 6.3 Auto Square-Off
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| MIS square-off | Place MIS, wait for time | Position closed | [ ] |
| Pending cancel | Pending order at square-off | Order cancelled | [ ] |
| CNC unaffected | CNC position at square-off | Position remains | [ ] |

### 6.4 Sandbox Reset
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Manual reset | Click reset button | Funds restored | [ ] |
| Auto reset | Wait for scheduled reset | Funds restored | [ ] |
| Positions cleared | After reset | No positions | [ ] |

### 6.5 Sandbox P&L History
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| View history | Go to `/sandbox/mypnl` | Historical P&L shown | [ ] |
| Daily breakdown | Check daily entries | Correct P&L per day | [ ] |
| Chart | View P&L chart | Chart renders | [ ] |

---

## 7. WebSocket & Real-time

### 7.1 WebSocket Connection
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Connect | Go to `/websocket/test` | Connected status | [ ] |
| Reconnect | Stop/start server | Auto reconnect | [ ] |
| Multiple tabs | Open in 2 tabs | Both connected | [ ] |

### 7.2 Market Data Streaming
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Subscribe LTP | Subscribe to RELIANCE | LTP updates | [ ] |
| Subscribe Quote | Subscribe quote mode | Full quote updates | [ ] |
| Subscribe Depth | Subscribe depth mode | Depth updates | [ ] |
| Multi-symbol | Subscribe 5 symbols | All update | [ ] |
| Unsubscribe | Unsubscribe symbol | Updates stop | [ ] |

### 7.3 Real-time UI Updates
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Order status | Place order | Status updates live | [ ] |
| Position P&L | Open position | P&L updates live | [ ] |
| Orderbook refresh | Place order | Orderbook auto-updates | [ ] |

---

## 8. Strategies & Webhooks

### 8.1 Webhook Strategies
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Create strategy | Go to `/strategy/new` | Strategy created | [ ] |
| Add symbol | Add symbol mapping | Symbol added | [ ] |
| Enable strategy | Toggle enable | Strategy active | [ ] |
| Webhook URL | Copy webhook URL | URL copied | [ ] |

### 8.2 TradingView Webhooks
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Config page | Go to `/tradingview` | Config shown | [ ] |
| Copy webhook | Copy URL | URL in clipboard | [ ] |
| Send webhook | POST to URL | Order placed | [ ] |
| Invalid payload | Send bad JSON | Error response | [ ] |

### 8.3 Python Strategies
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Create strategy | Go to `/python/new` | Editor shown | [ ] |
| Write code | Enter Python code | Syntax highlighted | [ ] |
| Save strategy | Click save | Strategy saved | [ ] |
| Start strategy | Click start | Process started | [ ] |
| View logs | Click logs | Logs displayed | [ ] |
| Stop strategy | Click stop | Process stopped | [ ] |
| Schedule | Set start/stop times | Schedule saved | [ ] |

### 8.4 External Webhook Testing
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| ngrok test | Start ngrok, send webhook | Order placed | [ ] |
| DevTunnel test | Start tunnel, send webhook | Order placed | [ ] |
| Cloudflare test | Start CF tunnel, send webhook | Order placed | [ ] |

---

## 9. Telegram Bot

### 9.1 Configuration
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Config page | Go to `/telegram/config` | Config form shown | [ ] |
| Set bot token | Enter token | Token saved | [ ] |
| Set chat ID | Enter chat ID | ID saved | [ ] |
| Test connection | Click test | Success message | [ ] |

### 9.2 Notifications
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Order notification | Place order | Telegram message | [ ] |
| Trade notification | Order executed | Telegram message | [ ] |
| Format check | View message | Proper formatting | [ ] |

### 9.3 Bot Commands
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| /start | Send /start | Welcome message | [ ] |
| /orderbook | Send command | Orderbook summary | [ ] |
| /positions | Send command | Positions summary | [ ] |
| /holdings | Send command | Holdings summary | [ ] |
| /funds | Send command | Funds summary | [ ] |

---

## 10. API Testing

### 10.1 Playground
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Access | Go to `/playground` | Playground loads | [ ] |
| API key display | Check sidebar | API key shown | [ ] |
| Send request | Select endpoint, send | Response shown | [ ] |
| Syntax highlight | View response | Colored JSON | [ ] |
| Copy cURL | Click cURL | Command copied | [ ] |

### 10.2 API Endpoints

**Orders:**
| Endpoint | Test | Status |
|----------|------|--------|
| `POST /api/v1/placeorder` | Place order | [ ] |
| `POST /api/v1/placesmartorder` | Smart order | [ ] |
| `POST /api/v1/modifyorder` | Modify order | [ ] |
| `POST /api/v1/cancelorder` | Cancel order | [ ] |
| `POST /api/v1/cancelallorder` | Cancel all | [ ] |
| `POST /api/v1/closeposition` | Close position | [ ] |

**Data:**
| Endpoint | Test | Status |
|----------|------|--------|
| `POST /api/v1/quotes` | Get quotes | [ ] |
| `POST /api/v1/depth` | Get depth | [ ] |
| `POST /api/v1/history` | Get history | [ ] |
| `POST /api/v1/intervals` | Get intervals | [ ] |

**Portfolio:**
| Endpoint | Test | Status |
|----------|------|--------|
| `POST /api/v1/orderbook` | Get orders | [ ] |
| `POST /api/v1/tradebook` | Get trades | [ ] |
| `POST /api/v1/positionbook` | Get positions | [ ] |
| `POST /api/v1/holdings` | Get holdings | [ ] |
| `POST /api/v1/funds` | Get funds | [ ] |

### 10.3 API Error Handling
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Invalid API key | Send with bad key | 401 Unauthorized | [ ] |
| Missing params | Omit required field | 400 Bad Request | [ ] |
| Invalid symbol | Use "INVALID" | Error message | [ ] |
| Rate exceeded | 60+ requests/min | 429 Rate Limited | [ ] |

---

## 11. UI/UX Testing

### 11.1 Responsive Design
| Screen | Test | Status |
|--------|------|--------|
| Desktop 1920x1080 | Full layout | [ ] |
| Laptop 1366x768 | Adjusted layout | [ ] |
| Tablet 768px | Collapsible sidebar | [ ] |
| Mobile 375px | Mobile layout | [ ] |

### 11.2 Theme Testing
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Light theme | Select light | Light colors | [ ] |
| Dark theme | Select dark | Dark colors | [ ] |
| System theme | Set system | Matches OS | [ ] |
| Persist theme | Refresh page | Theme retained | [ ] |

### 11.3 Form Validation
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Empty submit | Submit empty form | Error messages | [ ] |
| Invalid email | Enter "notanemail" | Validation error | [ ] |
| Required field | Leave required empty | Field highlighted | [ ] |

### 11.4 Error Pages
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| 404 page | Go to `/nonexistent` | 404 page shown | [ ] |
| 500 page | Trigger server error | 500 page shown | [ ] |
| Rate limit page | Trigger rate limit | 429 page shown | [ ] |

### 11.5 Accessibility
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Keyboard nav | Tab through page | All interactive focusable | [ ] |
| Focus visible | Tab to button | Focus ring visible | [ ] |
| Screen reader | Use VoiceOver/NVDA | Content readable | [ ] |

---

## 12. Platform Compatibility

### 12.1 Python Versions
| Version | Install | Run | Basic Flow | Status |
|---------|---------|-----|------------|--------|
| 3.11 | [ ] | [ ] | [ ] | |
| 3.12 | [ ] | [ ] | [ ] | |
| 3.13 | [ ] | [ ] | [ ] | |
| 3.14 | [ ] | [ ] | [ ] | |

### 12.2 Operating Systems
| OS | Install | Run | Full Test | Status |
|----|---------|-----|-----------|--------|
| macOS 14+ | [ ] | [ ] | [ ] | |
| Windows 11 | [ ] | [ ] | [ ] | |
| Windows 10 | [ ] | [ ] | [ ] | |
| Ubuntu 24.04 | [ ] | [ ] | [ ] | |
| Ubuntu 22.04 | [ ] | [ ] | [ ] | |

### 12.3 Browsers
| Browser | Load | Features | WebSocket | Status |
|---------|------|----------|-----------|--------|
| Chrome | [ ] | [ ] | [ ] | |
| Firefox | [ ] | [ ] | [ ] | |
| Safari | [ ] | [ ] | [ ] | |
| Edge | [ ] | [ ] | [ ] | |

---

## 13. Deployment

### 13.1 Docker
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Build image | `docker build -t openalgo .` | Image built | [ ] |
| Run container | `docker run -p 5000:5000 openalgo` | App accessible | [ ] |
| Volume mount | Mount db folder | Data persists | [ ] |
| docker-compose | `docker-compose up` | All services up | [ ] |

### 13.2 Production Mode
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Debug off | Set `FLASK_DEBUG=False` | No debug info | [ ] |
| Error pages | Trigger error | No stack trace | [ ] |
| Static files | Check CSS/JS | All load correctly | [ ] |

### 13.3 HTTPS
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| SSL cert | Configure cert | HTTPS works | [ ] |
| Secure cookies | Check cookies | Secure flag set | [ ] |
| WSS | WebSocket over SSL | WSS connects | [ ] |

### 13.4 Reverse Proxy
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| nginx proxy | Configure nginx | Routes work | [ ] |
| WebSocket proxy | Proxy WS | Real-time works | [ ] |
| Static files | Proxy static | Assets load | [ ] |

---

## 14. Bug-Catching Scenarios

### 14.1 Race Conditions
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Double click order | Rapidly click Place Order | Only one order | [ ] |
| Concurrent modify | Modify same order in 2 tabs | One succeeds | [ ] |
| Parallel API calls | 10 simultaneous orders | All processed correctly | [ ] |

### 14.2 Edge Cases - Orders
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Zero quantity | Order with qty=0 | Error: Invalid quantity | [ ] |
| Negative quantity | Order with qty=-1 | Error: Invalid quantity | [ ] |
| Huge quantity | Order with qty=999999999 | Error or freeze qty split | [ ] |
| Zero price | Limit order price=0 | Error: Invalid price | [ ] |
| Negative price | Limit order price=-100 | Error: Invalid price | [ ] |
| Missing symbol | Order without symbol | Error: Symbol required | [ ] |
| Invalid exchange | Order with exchange="XYZ" | Error: Invalid exchange | [ ] |

### 14.3 Edge Cases - Data
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Empty symbol | Search with empty string | No crash, empty results | [ ] |
| Special chars | Search "A&B<>\"'" | Escaped, no XSS | [ ] |
| Unicode | Search "टाटा" | Handled gracefully | [ ] |
| Very long input | 10000 char symbol | Truncated or error | [ ] |
| SQL injection | Search "'; DROP TABLE--" | No SQL error | [ ] |

### 14.4 Session Edge Cases
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Expired session | Wait for expiry, act | Redirect to login | [ ] |
| Stale CSRF | Use old CSRF token | Error: Invalid token | [ ] |
| Concurrent logout | Logout in 2 tabs | Both logged out | [ ] |
| Session hijack | Copy cookie to incognito | Session invalid | [ ] |

### 14.5 Network Issues
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Slow network | Throttle to 2G | Timeout handling | [ ] |
| Network offline | Disable network | Offline message | [ ] |
| Intermittent | Toggle network during action | Graceful recovery | [ ] |
| Broker timeout | Broker API slow | Timeout message | [ ] |

### 14.6 Browser Edge Cases
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Back button | Login → Dashboard → Back | Handled correctly | [ ] |
| Refresh during action | Refresh while ordering | No duplicate order | [ ] |
| Multiple tabs | Trade in multiple tabs | Consistent state | [ ] |
| Incognito mode | Full flow in incognito | Works correctly | [ ] |
| Clear cookies | Clear during session | Redirect to login | [ ] |

### 14.7 Data Integrity
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| P&L accuracy | Manual calculate vs shown | Match exactly | [ ] |
| Position qty | After partial close | Correct remaining | [ ] |
| Avg price | After multiple buys | Weighted average | [ ] |
| Margin calc | Check used margin | Matches expected | [ ] |

### 14.8 Timezone Issues
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| IST display | Check timestamps | IST timezone | [ ] |
| Square-off time | Verify 15:15 IST | Correct execution | [ ] |
| Historical dates | Request specific date | Correct data | [ ] |

### 14.9 Concurrent Users
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Same account 2 browsers | Login both | Both work | [ ] |
| Trade from both | Place orders | Both execute | [ ] |
| Modify same order | Concurrent modify | One wins | [ ] |

### 14.10 Memory/Performance
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Long session | Keep open 8 hours | No memory leak | [ ] |
| Many WebSocket subs | Subscribe 50 symbols | Stable | [ ] |
| Large orderbook | 500+ orders | Page loads | [ ] |
| Large history | 10000 candles | Renders | [ ] |

### 14.11 Sandbox-Specific
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Switch modes | Toggle Live/Sandbox | Correct data shown | [ ] |
| Sandbox isolation | Order in sandbox | No real execution | [ ] |
| Fund calculation | After trades | Correct balance | [ ] |
| Reset timing | Verify reset schedule | Executes on time | [ ] |

### 14.12 Integration Errors
| Test | Steps | Expected | Status |
|------|-------|----------|--------|
| Broker down | Broker API unavailable | Clear error message | [ ] |
| Token expired | Use expired broker token | Re-auth prompt | [ ] |
| Rate limited by broker | Many broker calls | Handle gracefully | [ ] |
| Invalid response | Broker returns HTML | Parse error handled | [ ] |

---

## Test Execution Checklist

### Pre-Test
- [ ] Fresh environment setup
- [ ] .env configured correctly
- [ ] Database cleared (if needed)
- [ ] Frontend built
- [ ] Application running

### During Test
- [ ] Note exact steps to reproduce issues
- [ ] Capture screenshots for bugs
- [ ] Check browser console for errors
- [ ] Check server logs for errors

### Post-Test
- [ ] Document all findings
- [ ] Categorize by severity
- [ ] Create issues for bugs
- [ ] Update test status

---

## Bug Report Template

```markdown
## Bug Title
[Short description]

## Environment
- OS:
- Python:
- Browser:
- Broker:

## Steps to Reproduce
1.
2.
3.

## Expected Behavior
[What should happen]

## Actual Behavior
[What actually happens]

## Screenshots
[If applicable]

## Logs
```
[Relevant log output]
```

## Severity
- [ ] Critical (App crash, data loss)
- [ ] High (Feature broken)
- [ ] Medium (Feature impaired)
- [ ] Low (Minor issue)
```

---

## Appendix: OpenAlgo Symbol Format

### Exchange Codes
| Code | Description |
|------|-------------|
| `NSE` | National Stock Exchange equities |
| `BSE` | Bombay Stock Exchange equities |
| `NFO` | NSE Futures and Options |
| `BFO` | BSE Futures and Options |
| `CDS` | NSE Currency Derivatives |
| `BCD` | BSE Currency Derivatives |
| `MCX` | Multi Commodity Exchange |
| `NSE_INDEX` | NSE Indices |
| `BSE_INDEX` | BSE Indices |

### Equity Symbols
**Format:** `[Base Symbol]`

| Exchange | Symbol | Description |
|----------|--------|-------------|
| NSE | `RELIANCE` | Reliance Industries |
| NSE | `INFY` | Infosys |
| NSE | `TCS` | Tata Consultancy Services |
| NSE | `SBIN` | State Bank of India |
| BSE | `TATAMOTORS` | Tata Motors |

### Index Symbols
| Exchange | Symbol | Description |
|----------|--------|-------------|
| NSE_INDEX | `NIFTY` | Nifty 50 Index |
| NSE_INDEX | `BANKNIFTY` | Bank Nifty Index |
| NSE_INDEX | `FINNIFTY` | Fin Nifty Index |
| NSE_INDEX | `MIDCPNIFTY` | Midcap Nifty Index |
| NSE_INDEX | `NIFTYNXT50` | Nifty Next 50 Index |
| NSE_INDEX | `INDIAVIX` | India VIX |
| BSE_INDEX | `SENSEX` | Sensex Index |
| BSE_INDEX | `BANKEX` | Bankex Index |
| BSE_INDEX | `SENSEX50` | Sensex 50 Index |

### Future Symbols
**Format:** `[Base Symbol][Expiration Date]FUT`

| Exchange | Symbol | Description |
|----------|--------|-------------|
| NFO | `BANKNIFTY27JAN26FUT` | Bank Nifty Jan 2026 Future |
| NFO | `NIFTY27JAN26FUT` | Nifty Jan 2026 Future |
| NFO | `RELIANCE27FEB26FUT` | Reliance Feb 2026 Future |
| BFO | `SENSEX27JAN26FUT` | Sensex Jan 2026 Future |
| CDS | `USDINR27JAN26FUT` | USD/INR Jan 2026 Future |
| MCX | `CRUDEOILM17JAN26FUT` | Crude Oil Jan 2026 Future |
| MCX | `GOLD05FEB26FUT` | Gold Feb 2026 Future |

### Options Symbols
**Format:** `[Base Symbol][Expiration Date][Strike Price][CE/PE]`

| Exchange | Symbol | Description |
|----------|--------|-------------|
| NFO | `NIFTY27JAN2624000CE` | Nifty 24000 Call Jan 2026 (Monthly) |
| NFO | `NIFTY13JAN2624000CE` | Nifty 24000 Call Jan 2026 (Weekly) |
| NFO | `NIFTY27JAN2624000PE` | Nifty 24000 Put Jan 2026 (Monthly) |
| NFO | `BANKNIFTY27JAN2652000CE` | Bank Nifty 52000 Call Jan 2026 (Monthly) |
| NFO | `BANKNIFTY13JAN2652000CE` | Bank Nifty 52000 Call Jan 2026 (Weekly) |
| NFO | `RELIANCE27FEB263200CE` | Reliance 3200 Call Feb 2026 |
| CDS | `USDINR27JAN2684CE` | USD/INR 84 Call Jan 2026 |
| MCX | `CRUDEOIL17JAN266750CE` | Crude Oil 6750 Call Jan 2026 |
| MCX | `GOLD05FEB2680000PE` | Gold 80000 Put Feb 2026 |

### Test Payloads

**Equity Order:**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NSE",
  "symbol": "RELIANCE",
  "action": "BUY",
  "product": "MIS",
  "pricetype": "MARKET",
  "quantity": "1"
}
```

**Index Future Order (NIFTY):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NFO",
  "symbol": "NIFTY27JAN26FUT",
  "action": "BUY",
  "product": "NRML",
  "pricetype": "MARKET",
  "quantity": "65"
}
```

**Index Future Order (BANKNIFTY):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NFO",
  "symbol": "BANKNIFTY27JAN26FUT",
  "action": "BUY",
  "product": "NRML",
  "pricetype": "MARKET",
  "quantity": "30"
}
```

**Index Options Order (NIFTY Monthly):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NFO",
  "symbol": "NIFTY27JAN2624000CE",
  "action": "BUY",
  "product": "NRML",
  "pricetype": "MARKET",
  "quantity": "65"
}
```

**Index Options Order (NIFTY Weekly):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NFO",
  "symbol": "NIFTY13JAN2624000CE",
  "action": "BUY",
  "product": "NRML",
  "pricetype": "MARKET",
  "quantity": "65"
}
```

**Index Options Order (BANKNIFTY):**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "Test",
  "exchange": "NFO",
  "symbol": "BANKNIFTY27JAN2652000CE",
  "action": "BUY",
  "product": "NRML",
  "pricetype": "MARKET",
  "quantity": "30"
}
```

**Quotes Request:**
```json
{
  "apikey": "YOUR_API_KEY",
  "symbol": "RELIANCE",
  "exchange": "NSE"
}
```

**Index Quotes Request:**
```json
{
  "apikey": "YOUR_API_KEY",
  "symbol": "NIFTY",
  "exchange": "NSE_INDEX"
}
```

**Historical Data Request:**
```json
{
  "apikey": "YOUR_API_KEY",
  "symbol": "RELIANCE",
  "exchange": "NSE",
  "interval": "5m",
  "start_date": "2025-01-01",
  "end_date": "2025-01-13"
}
```

**Market Depth Request:**
```json
{
  "apikey": "YOUR_API_KEY",
  "symbol": "INFY",
  "exchange": "NSE"
}
```

**TradingView Webhook Payload:**
```json
{
  "apikey": "YOUR_API_KEY",
  "strategy": "TV_Strategy",
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "exchange": "NSE",
  "pricetype": "MARKET",
  "product": "MIS",
  "quantity": "1"
}
```

---

## Sign-Off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Tester | | | |
| Dev Lead | | | |
| QA Lead | | | |

---

*Document Version: 2.0.0*
*Last Updated: January 2025*
