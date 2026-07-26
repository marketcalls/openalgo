# Data layer and account-data normalization

## Part 1 — `BrokerData`: quotes / depth / history

- `__init__(self, auth_token)` sets `self.timeframe_map` (OpenAlgo interval ->
  broker interval). intervals_service reads its keys.
- `get_quotes` -> `{ask,bid,high,low,ltp,open,prev_close,volume,oi}`.
- `get_depth` -> `{asks[5]{price,quantity}, bids[5]{...}, high,low,ltp,ltq,oi,
  open,prev_close,totalbuyqty,totalsellqty,volume}`. The required method name is
  **`get_depth`** (alias `get_market_depth` if needed).
- `get_history` -> **pandas DataFrame** with columns
  `[timestamp, open, high, low, close, volume, oi]`, `timestamp` = **epoch
  seconds**. The service returns it via `df.to_dict(orient="records")` — so YOUR
  epoch convention is what ships.

### NUANCE — some brokers have NO REST quote API (WebSocket-sourced quotes)

`broker/aliceblue/` is the case to study. There is no REST quote endpoint at
all, so `get_quotes` and `get_depth` are served from the streaming feed:

1. get (or force-create) a WebSocket connection
2. `subscribe([instrument], is_depth=False)` — `is_depth=True` for depth
3. **`time.sleep(2.0)`** waiting for a tick to arrive
4. read the cached quote for `(exchange, token)`
5. `unsubscribe(...)` in a `finally`

Consequences to design around before choosing this shape:

- **Every quote costs ~2 seconds.** Batch paths matter enormously here; a
  per-symbol loop over an option chain is unusable.
- **Quotes only exist when ticks flow.** Outside market hours, or on an
  illiquid instrument that has not traded, there is no tick and the call fails
  rather than returning a stale close.
- **Retry means reconnect.** AliceBlue retries with
  `get_websocket(force_new=True)`, which cleanly disconnects the old socket
  before creating a new one — close-before-reconnect applies to this path too,
  not just the streaming adapter.
- **FD discipline is mandatory.** Subscribe/unsubscribe must be paired in a
  `finally`, or every quote leaks a dangling subscription. Run the `fd-audit`
  skill on any code shaped like this.

Only adopt this when the broker genuinely has no REST quote API. If REST exists,
use it.

### NUANCE — depth may return FEWER than 5 levels; pad it

OpenAlgo's contract is exactly 5 bid and 5 ask levels. Brokers return fewer on
illiquid instruments (a far OTM option may have 1-2 levels) and sometimes on
indices. The plugins split on this:

- `broker/fyers/`, `broker/kotak/` — **pad** to 5 with zero entries:
  `while len(bids) < 5: bids.append({"price": 0, "quantity": 0})`
- `broker/zerodha/`, `broker/dhan/` — only truncate (`[:5]`)

Truncation alone handles more-than-5 but not fewer-than-5, and a 2-element
array where consumers expect 5 breaks the UI and any indexed access. **Do
both**: slice to 5, then pad to 5.

### NUANCE — the quote key may be a composite, not a bare token

`broker/kotak/` queries with `f"{kotak_exchange}|{psymbol}"`, where the stored
`token` is Kotak's `pSymbol` and `brexchange` holds **segment** codes
(`nse_cm`, `nse_fo`, `bse_cm`) rather than exchange names. So the quote key is
assembled from two `SymToken` columns, not one. Check what the quote endpoint
actually keys on before assuming `token` alone is enough — and store whatever it
needs in the master contract.

### NUANCE — price scaling

Many brokers send prices as scaled integers (e.g. paise = x100). De-scale in
quotes/depth/history (divide). Volume/OI are raw. Confirm the scale per segment.

### History is its own reference

`get_history` is the most repeatedly-wrong part of an integration — timestamps,
chunk limits, separate intraday/daily endpoints, the missing current-day candle,
and inclusive/exclusive date boundaries all differ per broker and all fail
silently. See **`references/history-data.md`** before writing it.

The one-line version: intraday is true UTC epoch of the IST candle; **daily
shifts +5:30**; and check what the broker already returns first, because some
(fyers) hand back epoch directly and converting again double-shifts every daily
candle. Only guard on the timeframes the broker actually serves — of the five
majors only upstox supports W/M, so a `("D","W","M")` check is wrong elsewhere.

### NUANCE — index exchange translation

If the broker uses one `INDEX` pseudo-exchange, translate OpenAlgo
`NSE_INDEX`/`BSE_INDEX` -> the broker's index exchange on every quote/depth call,
and to the parent cash exchange for history. Keep a shared `mapping/exchange.py`.

### NUANCE — the quote API has its OWN symbol vocabulary for indices

**Assume this is true until proven otherwise — it is the single most recurring
quote bug in the tree**, hit independently by at least Arrow and Kotak with
different symptoms. The symbol stored in `brsymbol` is frequently not what the
quote endpoint accepts for an index.

`broker/kotak/` keeps an explicit candidate map because Neo's
`/quotes/neosymbol` wants a descriptive name the master contract does not
store — and one index needs four spellings:

```python
"NIFTY":      ["Nifty 50"],
"BANKNIFTY":  ["Nifty Bank"],
"FINNIFTY":   ["Nifty Fin Service"],
"MIDCPNIFTY": ["Nifty Mid Select", "Nifty Midcap Sel",
               "Nifty Midcap Select", "NIFTY MID SELECT"],
"INDIAVIX":   ["India VIX"],
```

Arrow's INDEX quotes accept: the **underlying name** for the 5
derivative indices (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`,
`NIFTYNXT50` — their display names are rejected) but the **UPPERCASED display
name** for everything else (`NIFTY IT`, `INDIA VIX`, `SMLCAP`). Probe a
handful of each class with a tiny script before assuming. Robust pattern
(see `broker/arrow/api/data.py` `_quote_index`): try candidates in order
(OpenAlgo symbol -> uppercased brsymbol -> raw brsymbol), treat 400 as
"try next", and **cache the verified name per token** so steady state costs
one request. The option tools (option chain / IV / OI tracker / max pain /
GEX) all start from the underlying index LTP — if index quotes fail, every
options tool fails with it.

### NUANCE — some exchanges may not exist on the quote REST API at all

Arrow's quote API serves NSE/BSE/NFO/BFO/MCX(as `MCXFO`!)/INDEX — and nothing
for currency (CDS) or NSE commodities (NCO), under ANY code (confirmed by the
SDK's Exchange enum having no such members). When that happens: keep a
`QUOTE_UNSUPPORTED_EXCHANGES` set, fail single quotes fast with a message that
points to websocket streaming (token-based, exchange-agnostic, still works),
and **skip those symbols in batch requests** — one unsupported symbol can 400
the entire batch. Also note the documented exchange code may be wrong even for
supported exchanges (docs said `MCX`, server wants `MCXFO`) — probe each one.

### NUANCE — rate limits vs per-request caps are TWO different limits

Don't conflate them. Arrow allows 10 req/sec (rate limit) AND at most **100
instruments per `/info/quotes` request** (hard server cap: 100 -> 200 OK,
101 -> HTTP 500 "unable to get quotes"). Loop any-size symbol sets in cap-sized
chunks throttled under the rate limit.

**Check the broker's docs for a stated cap before probing.** Many publish one.
`references/cross-broker-reference.md` carries the real `BATCH_SIZE` every
existing plugin uses (they range from 10 to 1000) — calibrate against that
rather than picking a number. Only binary-search live (1/10/50/100/101/150)
when the docs are silent, which is common; note Arrow returned HTTP 500 rather
than a clean 4xx when the cap was exceeded.

**The cap can differ per endpoint.** Zerodha documents `/quote` at 500
instruments but `/quote/ohlc` and `/quote/ltp` at 1000. If your broker splits
LTP/OHLC/full into separate endpoints, chunk each at its own cap instead of
applying the smallest one everywhere.

Rate limits are also **per category**, not global — Dhan allows 10 order
req/sec but only **1 quote req/sec**, which is a design constraint rather than a
tuning knob (it rules out per-symbol polling entirely). Order *modification* may
carry its own cap (Dhan: 25 per order), which smart-order retry loops can hit.

Pattern (zerodha/upstox/arrow):

- `get_multiquotes`: chunk at the broker's per-request cap with a delay between
  chunks (Arrow: 100/request, ~0.15s delay).
- `get_history`: throttle (small `time.sleep`) between date-chunks; chunk long
  ranges (broker caps the per-request range, often larger for daily).

The OpenAlgo `/api/v1/history` endpoint itself is rate-limited by
`API_RATE_LIMIT` (see `restx_api/history.py`) — that's separate (per-IP) and not
your concern in the broker module.

---

## Part 2 — Account-data normalization to common format (match docs exactly)

`mapping/order_data.py` converts raw broker JSON to the documented common
format. Output field names (verified against `docs/api/account-services/*`):

- orderbook (`transform_order_data`): `symbol, exchange, action, quantity,
  price, trigger_price, pricetype, product, orderid, order_status, timestamp`
  (`order_status` lowercased: open/complete/cancelled/rejected/trigger pending)
- tradebook (`transform_tradebook_data`): `symbol, exchange, product, action,
  quantity, average_price, trade_value, orderid, timestamp`
- positions (`transform_positions_data`): `symbol, exchange, product, quantity,
  pnl, average_price, ltp`
- holdings (`transform_holdings_data`): `symbol, exchange, quantity, product,
  average_price, pnl, pnlpercent`
- `calculate_order_statistics`: `total_buy_orders, total_sell_orders,
  total_completed_orders, total_open_orders, total_rejected_orders`
- `calculate_portfolio_statistics`: `totalholdingvalue, totalinvvalue,
  totalprofitandloss, totalpnlpercentage`
- funds (`get_margin_data`): `availablecash, collateral, m2munrealized,
  m2mrealized, utiliseddebits` (all 2-dp strings; `{}` on error)

`map_*` functions reverse broker codes to OpenAlgo (product/side/order-type) and
convert broker symbols to OpenAlgo via `get_oa_symbol(brsymbol, exchange)`. The
service calls `map_*` first (mutates in place) then `transform_*`.

### Order placement mapping (`mapping/transform_data.py`)

- product: OpenAlgo `CNC/NRML/MIS` -> broker codes
- pricetype: `MARKET/LIMIT/SL/SL-M` -> broker codes
- action: `BUY/SELL` -> broker codes

**A straight enum map is often not enough.** Many Indian brokers do not support
MARKET or SL-M natively, and several rewrite MARKET server-side under the SEBI
Market Price Protection regime — which quietly breaks stop orders. OpenAlgo's
contract still requires all four price types to work, so you emulate the
missing ones with crossing LIMIT / stop-limit orders using the shared
`utils/mpp_slab.py` slabs. This is a common source of silent production bugs
(orders that rest unfilled, or stops that fire instantly). See
**`references/order-type-emulation.md`** before writing the pricetype map.
- `place_order_api` MUST set `response.status = response.status_code` (services
  check `res.status == 200`).
- Smart order: per-symbol lock + short-TTL position cache (copy from zerodha).
