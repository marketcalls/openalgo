# Broker Integration — Testing Guide (Common)

A **broker-agnostic** end-to-end test plan for validating any broker integration
in OpenAlgo. Use it when adding a new broker or regression-testing an existing
one. It expands the high-level checklist in
[`docs/broker-integration-guide.md` §18](../broker-integration-guide.md#18-testing-checklist)
into concrete, runnable steps.

**Reference docs**
- Integration internals & registration points: [`docs/broker-integration-guide.md`](../broker-integration-guide.md)
- Symbol format & index symbols: [`docs/prompt/symbol-format.md`](../prompt/symbol-format.md)
- Order constants: [`docs/prompt/order-constants.md`](../prompt/order-constants.md)

> **How to use:** Replace `<broker>` with the broker id (e.g. `zerodha`,
> `tradesmart`). Fill the **Test Symbol Matrix** (§0.5) once per broker, then
> work through the sections. Skip any exchange/segment the broker does not list
> in its `plugin.json` `supported_exchanges`. Record broker-specific deviations
> in §10 ("Broker-Specific Quirks").

---

## 0. Prerequisites & Setup

### 0.1 Environment (`.env`)
Set per the broker's auth pattern (see `broker-integration-guide.md §13`):
```ini
BROKER_API_KEY    = '<api_key>'         # compound 'a:::b' for some brokers (dhan/flattrade/tradesmart/5paisa)
BROKER_API_SECRET = '<api_secret>'
REDIRECT_URL      = 'http://127.0.0.1:5000/<broker>/callback'   # must match broker portal exactly
VALID_BROKERS     = '...,<broker>,...'
# XTS brokers only:
BROKER_API_KEY_MARKET    = '<market_key>'
BROKER_API_SECRET_MARKET = '<market_secret>'
```

### 0.2 Start the app
```bash
cd openalgo
uv run app.py
# UI:        http://127.0.0.1:5000
# Swagger:   http://127.0.0.1:5000/api/docs
# API logs:  http://127.0.0.1:5000/analyzer
# WS test:   http://127.0.0.1:5000/websocket/test
```

### 0.3 API test variables
```bash
API_KEY="<openalgo_apikey_from_/apikey>"
BASE_URL="http://127.0.0.1:5000"
```

### 0.4 Pre-flight
- [ ] `uv run python -m py_compile broker/<broker>/**/*.py` passes
- [ ] `uv run ruff check broker/<broker>/` passes
- [ ] Adapter resolves via factory:
  `uv run python -c "from dotenv import load_dotenv; load_dotenv(); import websocket_proxy; from websocket_proxy.broker_factory import _get_adapter_class; print(_get_adapter_class('<broker>').__name__)"`
- [ ] No raw HTTP clients in REST paths:
  `grep -rnE 'httpx\.Client\(|requests\.(get|post)|urllib|aiohttp' broker/<broker>/`
  (only the master-contract bulk file download may use `requests`)
- [ ] App starts, no errors in `log/errors.jsonl`, UI loads

### 0.5 Test Symbol Matrix (fill once per broker)
Resolve current contract symbols via `/api/v1/search` or `/api/v1/expiry`.
Only include segments the broker supports.

| Segment | Exchange | Symbol (fill in) |
|---|---|---|
| Equity (orders) | NSE | `YESBANK` _(default)_ |
| Equity | BSE | |
| Index | NSE_INDEX | `NIFTY` |
| Index | BSE_INDEX | `SENSEX` |
| Index future | NFO | `NIFTY<DDMMMYY>FUT` |
| Index option | NFO | `NIFTY<DDMMMYY><STRIKE>CE` |
| Stock option | NFO | |
| BSE F&O | BFO | `SENSEX<DDMMMYY><STRIKE>CE` |
| Currency | CDS | `USDINR<DDMMMYY>FUT` |
| Commodity | MCX | `CRUDEOIL<DDMMMYY>FUT` |

> ⚠️ Live order tests place **real orders**. Use **qty = 1**, prefer a low-price
> equity (e.g. `YESBANK`), keep LIMIT prices away from LTP to avoid fills, and
> cancel promptly. Use the **Analyzer (sandbox)** toggle for dry runs that never
> reach the broker.

---

## 1. Authentication

Identify the broker's pattern (`broker-integration-guide.md §13`): A) OAuth
redirect, B) TOTP/credential, C) XTS key, D) OAuth consent, E) OTP.

### 1.1 Login flow
1. Log into OpenAlgo → land on `/broker`.
2. Select `<broker>` → **Connect**.
3. Complete the broker login (redirect/consent, or TOTP/OTP form).
4. Callback returns to `/<broker>/callback` → token minted & stored.

| Check | Expected | Result |
|---|---|---|
| Broker appears in dropdown | visible (rebuild dist if on a feature branch) | [ ] |
| Login routes correctly (redirect URL / TOTP page) | per pattern | [ ] |
| Callback processes (`code`/`request_token`/form/`tokenId`/OTP) | no param dropped | [ ] |
| `authenticate_broker()` returns expected tuple shape | matches `brlogin.py` branch | [ ] |
| Token stored encrypted in `Auth` table; session set | `get_auth_token` works | [ ] |
| `feed_token`/`user_id` stored (if applicable) | XTS/angel/dhan etc. | [ ] |
| Master contract download auto-triggers | background thread starts | [ ] |
| Dashboard loads; `log/errors.jsonl` clean | | [ ] |

### 1.2 Token sanity (proves the stored token authenticates)
```bash
curl -s -X POST "$BASE_URL/api/v1/funds" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'"}'
```
- [ ] Returns `status: success`.

### 1.3 Re-login / daily rollover (if applicable)
- [ ] Token expiry handled (Indian brokers roll ~3 AM IST); re-login works.

---

## 2. Funds

```bash
curl -s -X POST "$BASE_URL/api/v1/funds" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'"}'
```
| Field | Result |
|---|---|
| `availablecash` | [ ] |
| `collateral` | [ ] |
| `m2munrealized` | [ ] |
| `m2mrealized` | [ ] |
| `utiliseddebits` | [ ] |

- [ ] All values are 2-dp strings; `{}` only on genuine error.
- [ ] Dashboard funds card matches API.
- [ ] Cross-check against the broker's own web/app funds page.

---

## 3. Master Contract Download & Symbol-Format Verification

### 3.1 Download
| Check | Expected | Result |
|---|---|---|
| All supported-exchange files download | per `plugin.json` | [ ] |
| `master_contract_status` flips to `success` | | [ ] |
| Symbols cached into memory | count logged | [ ] |
| No parse errors per segment | watch per-exchange column quirks | [ ] |
| Background session released | `db_session.remove()` in finally | [ ] |

### 3.2 Symbol-format verification (vs `symbol-format.md`)
```bash
curl -s -X POST "$BASE_URL/api/v1/search" -H "Content-Type: application/json" \
  -d '{"apikey":"'$API_KEY'","query":"YESBANK","exchange":"NSE"}'
```

**Equity** — base symbol, broker series suffix stripped:
| OpenAlgo symbol | instrumenttype | Result |
|---|---|---|
| `YESBANK`, `INFY`, `SBIN` | EQ | [ ] |
| **`BAJAJ-AUTO`** (hyphen kept) | EQ | [ ] |
| **`M&M`** (ampersand kept) | EQ | [ ] |

**Futures** `[Base][DDMMMYY]FUT` · **Options** `[Base][DDMMMYY][Strike][CE/PE]`:
| Example | instrumenttype | Result |
|---|---|---|
| `NIFTY<DDMMMYY>FUT` | FUT | [ ] |
| `NIFTY<DDMMMYY>25000CE` | CE | [ ] |
| decimal strike `…292.5CE` (decimal kept, `.0` dropped) | CE | [ ] |

**Index normalization** (exchange = `NSE_INDEX`/`BSE_INDEX`):
| OpenAlgo symbol | Exchange | Result |
|---|---|---|
| `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `NIFTYNXT50` | NSE_INDEX | [ ] |
| `SENSEX`, `BANKEX` | BSE_INDEX | [ ] |

| Invariant | Result |
|---|---|
| `instrumenttype` ∈ {EQ, FUT, CE, PE, INDEX} (indices may be EQ or INDEX per broker) | [ ] |
| `expiry` = `DD-MMM-YY` uppercase; empty for EQ/index | [ ] |
| `name` = underlying for FUT/CE/PE | [ ] |
| `brsymbol`/`brexchange` retain broker-native values | [ ] |
| No duplicate `(symbol, exchange)` | [ ] |
| Index symbol set matches `symbol-format.md` common lists | [ ] |

---

## 4. Order Management

> Vehicle: equity `YESBANK` on `NSE` for CNC/MIS. **NRML** is the F&O carry
> product — test it on a **future** (NFO/BFO/CDS/MCX), not cash equity. Keep
> qty = 1. Note any broker that emulates market orders (e.g. converts
> `MARKET`→`LIMIT`) in §10.

### 4.1 Place Order — price types × products
```bash
# MARKET
curl -s -X POST "$BASE_URL/api/v1/placeorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"MARKET","quantity":"1"}'
# LIMIT (price away from LTP)
curl -s -X POST "$BASE_URL/api/v1/placeorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"LIMIT","quantity":"1","price":"18"}'
# SL (Stop-Loss Limit)
curl -s -X POST "$BASE_URL/api/v1/placeorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"SL","quantity":"1","price":"30","trigger_price":"29.5"}'
# SL-M (Stop-Loss Market)
curl -s -X POST "$BASE_URL/api/v1/placeorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"SL-M","quantity":"1","trigger_price":"30"}'
```
| Price type | CNC | MIS | NRML (on a future) | Result |
|---|---|---|---|---|
| MARKET | [ ] | [ ] | [ ] | |
| LIMIT | [ ] | [ ] | [ ] | |
| SL | [ ] | [ ] | [ ] | |
| SL-M | [ ] | [ ] | [ ] | |

- [ ] Each success returns a real `orderid` (no `orderid: null` with `success`).
- [ ] Rejections surface the broker reason (check `log/openalgo_*.log` / `errors.jsonl`).
- [ ] Order appears in orderbook with correct symbol/qty/price/product/type.

### 4.2 Modify Order
```bash
curl -s -X POST "$BASE_URL/api/v1/modifyorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","orderid":"<ORDERID>","action":"BUY","product":"MIS","pricetype":"LIMIT","quantity":"2","price":"17"}'
```
- [ ] Quantity modify (1→2) reflects in orderbook.
- [ ] Limit price modify reflects in orderbook.

### 4.3 Cancel Order
```bash
curl -s -X POST "$BASE_URL/api/v1/cancelorder" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'","strategy":"test","orderid":"<ORDERID>"}'
```
- [ ] Order moves to `cancelled`.

### 4.4 Smart Order (position-aware)
```bash
# target +5
curl -s -X POST "$BASE_URL/api/v1/placesmartorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"MARKET","quantity":"5","position_size":"5"}'
# target 0 (square off)
curl -s -X POST "$BASE_URL/api/v1/placesmartorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE","action":"SELL","product":"MIS","pricetype":"MARKET","quantity":"0","position_size":"0"}'
```
- [ ] No position + target N → opens N.
- [ ] target == current → "No action needed".
- [ ] target 0 with open position → squares off to flat.

### 4.5 Cancel All / Close All
```bash
curl -s -X POST "$BASE_URL/api/v1/cancelallorder" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'","strategy":"test"}'
curl -s -X POST "$BASE_URL/api/v1/closeposition"  -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'","strategy":"test"}'
```
- [ ] Cancel-all clears OPEN/TRIGGER_PENDING; returns canceled/failed lists.
- [ ] Close-all squares off all net positions; empty → "No Open Positions Found".

### 4.6 Books / Status (common-format field check)
```bash
for ep in orderbook tradebook positionbook holdings; do
  curl -s -X POST "$BASE_URL/api/v1/$ep" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'"}'; echo; done
```
| Endpoint | Fields | Result |
|---|---|---|
| orderbook | symbol/exchange/action/quantity/price/trigger_price/pricetype/product/orderid/order_status/timestamp | [ ] |
| tradebook | symbol/exchange/product/action/quantity/average_price/trade_value/orderid/timestamp | [ ] |
| positionbook | symbol/exchange/product/quantity/pnl/average_price/ltp | [ ] |
| holdings | symbol/exchange/quantity/product/average_price/pnl/pnlpercent | [ ] |
| symbols mapped back to OpenAlgo format (e.g. `YESBANK`, not `YESBANK-EQ`) | | [ ] |
| openposition (net qty as str) | `/api/v1/openposition` | [ ] |
| orderstatus by id | `/api/v1/orderstatus` | [ ] |

### 4.7 Margin (if implemented)
```bash
curl -s -X POST "$BASE_URL/api/v1/margin" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","positions":[{"symbol":"YESBANK","exchange":"NSE","action":"BUY","product":"MIS","pricetype":"LIMIT","quantity":"1","price":"25"}]}'
```
- [ ] Single order returns `total_margin_required` (+ span/exposure if available).
- [ ] Multi-leg basket ≤ naive per-leg sum (hedge benefit) where a basket endpoint exists.
- [ ] Invalid symbol → clean 400.

### 4.8 Basket Order & Split Order — run in **Analyzer (sandbox)** mode

> These fan out into **multiple** real orders, so validate them with the
> **Analyzer toggle ON** (sandbox) first — verify the resulting child orders in
> the sandbox order book, then optionally do a tiny live run (qty 1) with the
> toggle OFF. Confirm the real broker is untouched while in sandbox.

**Basket order** (`/api/v1/basketorder`) — multiple distinct orders in one call:
```bash
curl -s -X POST "$BASE_URL/api/v1/basketorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","orders":[
   {"symbol":"YESBANK","exchange":"NSE","action":"BUY","quantity":"1","pricetype":"MARKET","product":"MIS"},
   {"symbol":"YESBANK","exchange":"NSE","action":"SELL","quantity":"1","pricetype":"LIMIT","product":"MIS","price":"40"}]}'
```
- [ ] Returns a per-order result list (status + orderid for each leg).
- [ ] Each leg appears in the (sandbox) order book with correct params.
- [ ] A malformed leg fails that leg cleanly without dropping the whole basket.

**Split order** (`/api/v1/splitorder`) — one order split into `splitsize` chunks:
```bash
curl -s -X POST "$BASE_URL/api/v1/splitorder" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","strategy":"test","symbol":"YESBANK","exchange":"NSE",
      "action":"SELL","quantity":"105","splitsize":"20","pricetype":"MARKET","product":"MIS"}'
```
- [ ] Splits into the expected child orders (e.g. 105 / 20 → 5×20 + 1×5 = 6 orders).
- [ ] Each child order placed; total quantity == requested quantity.
- [ ] Returns per-split result list.

| Operation | Analyzer (sandbox) | Live (qty 1) | Result |
|---|---|---|---|
| Basket order | [ ] | [ ] | |
| Split order | [ ] | [ ] | |
| Real broker unaffected while in sandbox | [ ] | — | |

---

## 5. Market Data Feed — all supported segments

### 5.1 Quotes (`/api/v1/quotes`) — run per segment from §0.5
- [ ] Returns `ltp, open, high, low, prev_close, volume, bid, ask, oi`.
- [ ] Sane values; OI present for F&O.
- [ ] Index quotes resolve (`NSE_INDEX`/`BSE_INDEX` → parent exchange).
- [ ] Quote-unsupported exchanges fail fast with a clear message (not a hang).

| Segment | quotes | Notes |
|---|---|---|
| NSE / BSE equity | [ ] | |
| NFO fut / opt | [ ] | |
| BFO | [ ] | |
| CDS / MCX | [ ] | |
| NSE_INDEX / BSE_INDEX | [ ] | |

### 5.2 Depth (`/api/v1/depth`)
- [ ] `bids[5]` + `asks[5]` with `price/quantity/orders`.
- [ ] `totalbuyqty, totalsellqty, ltp, ltq, oi, volume, open, high, low, prev_close`.
- [ ] Tested across all supported segments.

### 5.3 Intervals (`/api/v1/intervals`)
- [ ] Returns the broker's supported interval keys.

### 5.4 Historical (`/api/v1/history`) — intraday & daily
```bash
curl -s -X POST "$BASE_URL/api/v1/history" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","symbol":"YESBANK","exchange":"NSE","interval":"5m","start_date":"2026-06-15","end_date":"2026-06-18"}'
curl -s -X POST "$BASE_URL/api/v1/history" -H "Content-Type: application/json" \
 -d '{"apikey":"'$API_KEY'","symbol":"YESBANK","exchange":"NSE","interval":"D","start_date":"2026-01-01","end_date":"2026-06-18"}'
```
| Check | Result |
|---|---|
| Intraday OHLCV+oi, ascending timestamps | [ ] |
| Daily OHLCV+oi | [ ] |
| Intraday epoch = true candle time (no shift) | [ ] |
| **Daily epoch shifted +5:30** (IST midnight, cross-broker convention) | [ ] |
| Today's daily candle appended from quote (intraday-of-day) | [ ] |
| Tested across all supported segments (EQ, FUT, index) | [ ] |

### 5.5 Multiquotes (`/api/v1/multiquotes`)
- [ ] Realistic size (180+ option symbols — what GEX sends) succeeds.
- [ ] Mixed exchanges incl. an index work.
- [ ] Chunked under the broker's per-request cap + rate limit (no batch-wide failure).

---

## 6. Options Tools — NFO & BFO (`/tools`)

These exercise index LTP + expiry parsing + multiquotes together and fail loudly
on any index-quote or batch-cap bug. Test each underlying the broker supports.

| Tool | NFO: NIFTY | NFO: BANKNIFTY | BFO: SENSEX | BFO: BANKEX |
|---|---|---|---|---|
| Option Chain (`/optionchain`) | [ ] | [ ] | [ ] | [ ] |
| IV Smile / IV Chart | [ ] | [ ] | [ ] | [ ] |
| Max Pain | [ ] | [ ] | [ ] | [ ] |
| OI Tracker | [ ] | [ ] | [ ] | [ ] |
| GEX | [ ] | [ ] | [ ] | [ ] |
| Straddle Chart | [ ] | [ ] | [ ] | [ ] |
| Strategy Builder | [ ] | [ ] | [ ] | [ ] |

API building blocks:
```bash
curl -s -X POST "$BASE_URL/api/v1/expiry"      -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'","symbol":"NIFTY","exchange":"NFO","instrumenttype":"options"}'
curl -s -X POST "$BASE_URL/api/v1/optionchain" -H "Content-Type: application/json" -d '{"apikey":"'$API_KEY'","symbol":"NIFTY","exchange":"NFO","expiry":"<DD-MMM-YY>","strikecount":10}'
```
- [ ] Underlying index LTP resolves; expiry dropdown populated.
- [ ] Strikes + CE/PE legs load with correct OpenAlgo symbols.
- [ ] Greeks/IV compute without NaN/zero-LTP errors.
- [ ] No `errors.jsonl` entries (esp. index-quote 400s).

---

## 7. WebSocket Streaming — all segments (`/websocket/test`)

Modes: **LTP (1)**, **Quote (2)**, **Depth (3)**.

| Segment | LTP | Quote | Depth |
|---|---|---|---|
| NSE / BSE equity | [ ] | [ ] | [ ] |
| NFO fut / opt | [ ] | [ ] | [ ] |
| BFO | [ ] | [ ] | [ ] |
| CDS / MCX | [ ] | [ ] | [ ] |
| NSE_INDEX / BSE_INDEX | [ ] | [ ] | [ ] |

| Behaviour | Result |
|---|---|
| WS connects + authenticates | [ ] |
| LTP updates live | [ ] |
| Quote shows **real** OHLC/volume (a wrong `close` like 0.02 = binary-offset bug) | [ ] |
| Depth shows 5 buy + 5 sell levels (price/qty/orders) | [ ] |
| Index streams (token-based) tick | [ ] |
| Unsubscribe stops updates | [ ] |
| Reconnect after forced drop; fresh token on daily roll | [ ] |
| Heartbeat keeps connection alive | [ ] |
| Multiple clients on same symbol (ref-counting) | [ ] |

---

## 8. Cross-Cutting / Regression

- [ ] **Analyzer (sandbox) mode**: place sandbox order, **basket order (§4.8)**, and **split order (§4.8)** → verify child orders in sandbox → real broker unaffected → toggle back to Live.
- [ ] **Input validation**: qty 0/-1 → error; LIMIT price 0 → error; empty symbol → error.
- [ ] **Double-click protection**: rapid Place Order → only 1 order.
- [ ] **FD hygiene** (after a soak): no growth in open sockets/sessions; WS reconnects don't leak; `db_session.remove()` honored in background threads.
- [ ] **Rate limits**: bulk data calls respect the broker's per-min/per-sec caps (no broker-side throttle errors).

### Automated
```bash
uv run pytest test/ -v          # full suite
uv run pytest test/test_broker.py -v   # if broker tests exist
```
- [ ] Suite passes (or no new failures vs baseline).

---

## 9. Results Summary

| Section | Passed | Failed | Blocked / N/A |
|---|---|---|---|
| 0. Pre-flight | | | |
| 1. Authentication | | | |
| 2. Funds | | | |
| 3. Master contract + symbols | | | |
| 4. Order management | | | |
| 5. Market data | | | |
| 6. Option tools | | | |
| 7. WebSocket | | | |
| 8. Cross-cutting | | | |
| **Total** | | | |

**Broker:** ___________  **Tester:** ___________  **Date:** ___________  **Build/commit:** ___________

---

## 10. Broker-Specific Quirks (fill per broker)

Record deviations a tester would otherwise misread as bugs (auth field casing,
callback param spelling, market-order emulation, rate limits, unsupported
exchanges, per-request caps, special symbol handling, etc.).

| # | Area | Quirk | Expected behaviour |
|---|---|---|---|
| 1 | | | |
| 2 | | | |

### Example — TradeSmart (Noren v2)
- **Market orders**: `MKT`/`SL-MKT` are **rejected for API orders** (`ALGO_CHK`);
  OpenAlgo auto-converts `MARKET`→`LIMIT` and `SL-M`→`SL` at a protected price —
  so a "MARKET" order shows as `LIMIT` in the broker book (expected).
- **Login URL**: backend redirects to
  `https://v2api.tradesmartonline.in/OAuthlogin/authorize/oauth?client_id=<API_KEY>`
  (Noren v2 pattern, like shoonya/zebu) + manual `code`/`access_token` fallback on
  `/tradesmart/callback`.
- **`BROKER_API_KEY`** = `CLIENT_ID:::API_KEY`; token stored as `uid:::access_token`.
- **Rate limit**: 120 req/min per user; token valid one trading day.
- **Master contract**: from `https://v2api.tradesmartonline.in/<EXCH>_symbols.txt.zip`;
  the **BFO** file names its strike column `Strike` (others use `StrikePrice`).

### Issues found
| # | Section | Symbol/Endpoint | Issue | Severity | Status |
|---|---|---|---|---|---|
| 1 | | | | | |
| 2 | | | | | |
