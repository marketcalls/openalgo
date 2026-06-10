# claudebroker.md — Guide to Integrating a New Broker into OpenAlgo

This is a context/prompt file for Claude (and humans) to build a **new broker
plugin rapidly and confidently**. It captures the contract, the reference files
to read, the exact conventions, and the small nuances that are easy to miss.
Worked example throughout: the **Arrow** broker (`broker/arrow/`).

> Golden rule: OpenAlgo has a **common symbol format, common API, and common
> WebSocket format**. Your only job per file is to translate the broker's
> specific shapes into those common contracts (and back). Copy a reference
> broker, then adapt the broker-specific bits.

---

## 0. Before you start — knowledge to pursue

Read these first (they define the "common format" you must conform to):

| Topic | File(s) |
| --- | --- |
| Symbol format (EQ/FUT/CE/PE, indices, exchange codes) | `docs/prompt/symbol-format.md` |
| Order constants (product, pricetype, action, exchanges) | `docs/prompt/order-constants.md` |
| Lot size conventions | `docs/prompt/LotSize.md` |
| Common API request/response per endpoint | `docs/api/**` (esp. `account-services/`, `market-data/`, `order-management/`) |
| WebSocket streaming format | `docs/prompt/websockets-format.md`, `docs/api/websocket-streaming/*` |
| Services layer contract | `docs/prompt/services_documentation.md` |
| Rate limits | `docs/api/rate-limiting.md` |
| Existing broker-integration notes | `docs/broker-integration-guide.md` |
| Runtime constraints (eventlet, NullPool, FD hygiene) | root `CLAUDE.md` |

**Inspect the LIVE `db/openalgo.db` `symtoken` table of a working broker** (e.g.
connect zerodha once). This is the single most useful reference — it shows the
exact column values your master contract must reproduce (see §5).
**Do this BEFORE wiping symtoken with your new broker's data** — the old
broker's rows are your ground truth for NCO symbol format, MCX_INDEX names,
expiry formatting and the index symbol set. Once you overwrite the table, that
reference is gone.

### The broker's official SDK is your second source of truth

When the broker's docs omit literal details (JSON field names, binary byte
offsets, enum codes, endpoint routes), **download their official Python SDK
from PyPI and read its source** — it encodes what the server actually accepts:

```bash
pip download <broker-sdk-package> --no-deps -d /tmp/sdk && cd /tmp/sdk && unzip -o *.whl
# then read: routes/constants (endpoint paths, enum codes), the request
# plumbing (json vs form body), and any _parse_*_packet binary parsers
```

For Arrow this single trick resolved: the websocket binary offsets (docs don't
publish them), the margin request field names + product enum (C/I/M), the
basket-margin endpoint shape, and the quote modes/exchange enum. Reading the
SDK is *minutes*; guessing wrong costs *hours* of cryptic 400s.

### Reference brokers — pick the closest auth model

- **`broker/zerodha/`** — checksum auth (redirect → request_token → SHA256 →
  access token), CSV instrument master, token-based binary WebSocket. Best
  all-round template.
- **`broker/upstox/`** — pure OAuth2 (authorization_code grant), gzip-JSON
  master, protobuf WebSocket.
- **`broker/fyers/`** — dual WebSocket for **5-level and 50-level depth** (TBT
  socket). Read this if your broker offers depth > 5.

---

## 1. Required directory layout

```
broker/<name>/
  __init__.py
  plugin.json                         # metadata (supported_exchanges drives capabilities)
  api/__init__.py
  api/baseurl.py                      # (optional) hosts + auth-header builder (DRY)
  api/auth_api.py                     # authenticate_broker(request_token|code)
  api/order_api.py                    # place/modify/cancel/book/positions/holdings
  api/data.py                         # class BrokerData (quotes/depth/history)
  api/funds.py                        # get_margin_data(auth)
  mapping/__init__.py
  mapping/transform_data.py           # OpenAlgo order -> broker payload + enum maps
  mapping/order_data.py               # broker JSON -> OpenAlgo normalized rows
  mapping/exchange.py                 # (optional) exchange/index translation (shared)
  database/__init__.py
  database/master_contract_db.py      # master_contract_download() + SymToken
  streaming/__init__.py               # exports <Name>WebSocketAdapter
  streaming/<name>_adapter.py         # class <Name>WebSocketAdapter(BaseBrokerWebSocketAdapter)
  streaming/<name>_websocket.py       # sync websocket-client thread
  streaming/<name>_mapping.py         # exchange + capability registries
```

---

## 2. The broker contract (function names services import)

Services do `importlib.import_module(f"broker.{broker}.api.<module>")` and call
**fixed names** — these ARE the contract. Confirm in
`services/place_order_service.py`, `services/quotes_service.py`, etc.

| Service | Module | Function | Returns |
| --- | --- | --- | --- |
| login | `api.auth_api` | `authenticate_broker(request_token)` | `(auth_token, error)` 2-tuple |
| place | `api.order_api` | `place_order_api(data, auth)` | `(response, response_data, orderid)`, `response.status==200` = success |
| smart | `api.order_api` | `place_smartorder_api(data, auth)` | same shape |
| modify | `api.order_api` | `modify_order(data, auth)` | `(dict, status_code)` |
| cancel | `api.order_api` | `cancel_order(orderid, auth)` | `(dict, status_code)` |
| cancel all | `api.order_api` | `cancel_all_orders_api(data, auth)` | `(canceled[], failed[])` |
| close | `api.order_api` | `close_all_positions(api_key, auth)` | `(dict, status_code)` |
| orderbook | `api.order_api` + `mapping.order_data` | `get_order_book(auth)`; `map_order_data`, `calculate_order_statistics`, `transform_order_data` | raw → normalized |
| tradebook | `api.order_api` + `mapping.order_data` | `get_trade_book(auth)`; `map_trade_data`, `transform_tradebook_data` | |
| positions | `api.order_api` + `mapping.order_data` | `get_positions(auth)`; `map_position_data`, `transform_positions_data` | |
| holdings | `api.order_api` + `mapping.order_data` | `get_holdings(auth)`; `map_portfolio_data`, `calculate_portfolio_statistics`, `transform_holdings_data` | |
| (internal) | `api.order_api` | `get_open_position(symbol, exchange, product, auth)` | net qty as **str** (used by smart order) |
| funds | `api.funds` | `get_margin_data(auth)` | dict (keys below) |
| quotes | `api.data` | `BrokerData(auth).get_quotes(symbol, exchange)` | dict |
| depth | `api.data` | `BrokerData(auth).get_depth(symbol, exchange)` | dict (5 levels) |
| history | `api.data` | `BrokerData(auth).get_history(symbol, exchange, interval, start, end)` | **pandas DataFrame** |
| multiquotes | `api.data` | `BrokerData(auth).get_multiquotes(symbols)` (optional) | list |
| intervals | `api.data` | `BrokerData(auth).timeframe_map` (attribute) | dict |
| master | `database.master_contract_db` | `master_contract_download()` | emits socketio event |
| margin | `api.margin_api` | `calculate_margin_api(positions, auth)` | `(response, data)`; `data.data` = `{total_margin_required, span_margin, exposure_margin}` (+ optional `total_charges`) |

`auth` is always the decrypted broker token string (last positional arg).

For margin, **copy `broker/dhan/api/margin_api.py`** — it is the reference
pattern: route ONE position to the broker's single-order calculator (detailed
charge breakdown) and 2+ positions to the basket/multi calculator so the
broker nets spread/hedge benefits (an Arrow NIFTY short straddle priced at
~207k via basket vs ~337k as a naive per-leg sum — never sum legs yourself if
a basket endpoint exists). Include Dhan's two guards: a JSON-decode guard
(non-JSON broker reply → 502) and `_normalise_success_response` (broker sends
an error payload with HTTP 200 → convert to a 400 response object, because
`margin_service` trusts HTTP 200).

---

## 3. Login & authentication (trust-critical)

1. **Function name MUST be `authenticate_broker`** — hardcoded in
   `utils/plugin_loader.py` (`getattr(module, "authenticate_broker")`).
2. **One positional arg** (the request_token / oauth code), **returns a 2-tuple
   `(auth_token, error_message)`** — success = `(token, None)`, failure =
   `(None, "msg")`. Unpacked in `blueprints/brlogin.py`.
3. Read creds from env via `os.getenv("BROKER_API_KEY")` / `BROKER_API_SECRET`.
4. **Use the shared pooled HTTP client** `utils/httpx_client.get_httpx_client()`.
5. The **callback route is `/<broker>/callback`** (`brlogin.py:broker_callback`),
   broker taken from the URL path. The broker name is also parsed from
   `REDIRECT_URL` (regex `/([^/]+)/callback$`) in `blueprints/auth.py`.
6. **Token storage is automatic**: `handle_auth_success` → `upsert_auth` stores
   the token **encrypted** (Fernet) in the `Auth` table. The token is NEVER put
   in the Flask cookie. `get_auth_token(user)` is the single source of truth.
7. **Master contract auto-downloads** post-login via a background thread
   (`utils/auth_utils.async_master_contract_download` → your
   `master_contract_download()` → `master_contract_cache_hook`).

### NUANCE — literal JSON field names (docs describe, servers validate)
Broker docs often *describe* auth fields without giving the literal JSON keys,
and casing matters. Arrow's token exchange requires exactly `appID`, `token`
(the request token) and `checkSum` (capital S) — sending `requestToken` /
`checksum` failed every login with "required validation for field token
failed". Two rules:
- Find a **verbatim request example** (docs curl block or the official SDK
  source) before writing the payload. Never infer key spelling from prose.
- Server error messages name the **server-side validator field**, which may
  differ from the request key (Arrow's margin API complains about
  `tradingSymbol` when the request field is actually `symbol`). Don't rename
  your request field to match the error string — find the real contract.

### NUANCE — the callback query-param name
The generic `brlogin.py` `else` branch only reads `request.args.get("code") or
request.args.get("request_token")`. If your broker returns a **differently
spelled** param (Arrow returns `request-token` with a HYPHEN), the token is
silently dropped. Fix: add an `elif broker == "<name>":` branch that reads all
plausible spellings. Arrow example (`brlogin.py`):
```python
elif broker == "arrow":
    code = (request.args.get("request-token") or request.args.get("request_token")
            or request.args.get("requestToken") or request.args.get("code"))
    auth_token, error_message = auth_function(code)
    forward_url = "broker.html"
```

### NUANCE — token rewriting
Zerodha stores `api_key:access_token` (rewritten in `brlogin.py:834`). Most
brokers (incl. Arrow) store the bare token and need NO rewrite. Only add a
rewrite branch if downstream API calls require a composite token.

### NUANCE — feed_token / user_id
Brokers returning a feed token and/or user_id (angel, dhan, pocketful, …) return
3/4-tuples and ARE listed in `brlogin.py`'s special list (~line 840). A simple
JWT/token broker uses the 2-tuple generic path.

---

## 4. .env + install wiring (don't forget these)

To make the broker selectable and installable, add the broker id to **every**
hardcoded broker list:

| File | What |
| --- | --- |
| `.sample.env` + `.env` | `VALID_BROKERS` |
| `install/install.sh` (2x), `install/install-docker.sh`, `install/install-multi.sh` (2x), `install/install-docker-multi-custom-ssl.sh`, `install/docker-run.sh`, `install/docker-run.bat`, `start.sh` | hardcoded `valid_brokers` lists |
| `install/README.md` | "supported list" block |
| `README.md` | "Supported Brokers" list |
| `frontend/src/pages/BrokerSelect.tsx` | `allBrokers[]` entry + `switch` login-URL `case` (rebuild with `npm run build`) |
| `websocket_proxy/__init__.py` | import + `register_adapter("<name>", <Name>WebSocketAdapter)` + `__all__` |

Runtime modules (`websocket_proxy/server.py`, `utils/env_check.py`,
`blueprints/broker_credentials.py`, `blueprints/admin.py`) **read `VALID_BROKERS`
from env** — no edit needed.

### NUANCE — the broker dropdown is EMPTY on feature branches (stale dist)
Flask serves the pre-built `frontend/dist/`, and CI rebuilds it **only on
`main`**. On your feature branch the committed dist predates your
`BrokerSelect.tsx` edit, so the login dropdown filters against a broker list
that doesn't contain your broker → it renders empty. This is not a backend
bug: run `cd frontend && npm install && npm run build` locally (the output is
gitignored — don't commit it; CI produces the canonical dist after merge),
then hard-refresh the browser.

Env keys: `BROKER_API_KEY`, `BROKER_API_SECRET`, `REDIRECT_URL`
(`http://127.0.0.1:5000/<broker>/callback` — must EXACTLY match the broker
portal's registered redirect). XTS brokers also use `BROKER_API_KEY_MARKET` /
`_SECRET_MARKET`.

---

## 5. Master contract (verify against the LIVE symtoken table)

`SymToken` columns (canonical, `database/symbol.py`): `id, symbol, brsymbol,
name, exchange, brexchange, token, expiry, strike, lotsize, instrumenttype,
tick_size, contract_value`. **Declare `contract_value`** in your model (left
NULL) so a fresh-install `create_all()` matches the shared table.

Entry point: **`master_contract_download()`** (no args) — fetch, parse,
`delete_symtoken_table()`, `copy_from_dataframe(df)`, then
`socketio.emit('master_contract_download', {...})`. Release the scoped session
in a `finally:` (`db_session.remove()`) — it runs in a background thread.

### NUANCES verified against the live zerodha symtoken (do NOT guess):
- **`instrumenttype` is ONLY `EQ` / `FUT` / `CE` / `PE`.** There is **no
  "INDEX"** type — **indices use `EQ`**; the `NSE_INDEX` / `BSE_INDEX` exchange
  is what distinguishes them.
- **`expiry` format = `DD-MMM-YY` uppercase** (e.g. `30-JUN-26`), empty string
  `''` for EQ/index. Use `pd.to_datetime(x).strftime("%d-%b-%y").upper()`. This
  drives expiry-dropdown logic elsewhere — get it exact.
- **Symbol construction** (OpenAlgo common format):
  - EQ: bare base symbol (strip broker suffix like `-EQ`; keep `brsymbol` = full broker tradingsymbol)
  - FUT: `f"{underlying}{DDMMMYY}FUT"` e.g. `NIFTY30JUN26FUT`
  - CE/PE: `f"{underlying}{DDMMMYY}{strike}{CE|PE}"` e.g. `NIFTY09JUN2623100CE`
    (strike preserves decimals: `187.5`, drops `.0` for whole numbers)
  - INDEX: the OpenAlgo index symbol (`NIFTY`, `BANKNIFTY`, `SENSEX`), `brsymbol`
    = broker index name (`NIFTY 50`), exchange `NSE_INDEX`/`BSE_INDEX`
- **`name` column**: underlying for FUT/CE/PE (e.g. `NIFTY`); company/full name
  for EQ; display name for index.
- **`brexchange`** = the raw broker exchange code (kept for quote/history calls);
  `exchange` = OpenAlgo code.
- **Indices**: split the broker's single index space into `NSE_INDEX` /
  `BSE_INDEX` by parent exchange. `GLOBAL_INDEX` is zerodha/upstox-only — omit it
  unless your broker truly has global index feeds.
- **NEVER hardcode market timings** in the broker folder. (Day-boundary strings
  like `00:00:00`/`23:59:59` for history `from`/`to` params are fine.)

### NUANCE — download the REAL instrument file before writing the parser
Code written from the docs alone WILL be wrong. Arrow's docs implied
`NSE`/`NFO`-style codes and "strike ×100"; the live CSV actually has:
- exchange-segment codes `NSECM/NSEFO/BSEFO/NSECD/NSECO/MCXFO/NSEIDX/...`
  (mapping by the documented names dropped **every non-index row**)
- strikes **unscaled** for equity/index derivatives but **×100000** for
  currency derivatives, whose ticks arrive in **paise** — scaling is
  per-segment, not global (cross-check `StrikePrice` against the strike
  embedded in `TradingSymbol` for one row per segment)
- futures flagged by `OptionType == "XX"`, not by an empty option-type
- index rows carrying display names ("Nifty 50") in the `Symbol` column
So: pull the live file with a stored token FIRST, print
`df[seg_col].value_counts()` + 3 sample rows per segment, and only then write
the mapping. Watch for renamed listings too (TATAMOTORS → TMPV post-demerger)
— a "missing" symbol may simply no longer exist.

### NUANCE — vectorize the processing (iterrows is 45x slower)
A per-row Python loop (`df.iterrows()` + dict building) took ~45s for Arrow's
221k rows; the same logic as whole-column pandas ops (mirroring zerodha's
implementation) takes ~1s. Read the CSV with `dtype=str` (kills mixed-type
DtypeWarning at the source) and convert numerics explicitly with
`pd.to_numeric(errors="coerce")`. Beware `-0.0` surviving `clip(lower=0)` —
add `+ 0.0` to normalize. Verify the vectorized output is **byte-identical**
to a known-good run before trusting it.

### NUANCE — auth-token resolution in the download thread
`master_contract_download()` runs in a background thread and several templates
resolve the user via `os.getenv("LOGIN_USERNAME")` — which is often **unset**,
yielding a `None` token and the cryptic httpx error "Header value must be str
or bytes, not <class 'NoneType'>". Resolve via LOGIN_USERNAME first, then fall
back to the single non-revoked row for your broker in the `Auth` table
(OpenAlgo is single-user), and raise a clear error if neither exists — never
let `None` reach a header.

---

## 6. Data layer (`BrokerData`) — quotes / depth / history

- `__init__(self, auth_token)` sets `self.timeframe_map` (OpenAlgo interval →
  broker interval). intervals_service reads its keys.
- `get_quotes` → `{ask,bid,high,low,ltp,open,prev_close,volume,oi}`.
- `get_depth` → `{asks[5]{price,quantity}, bids[5]{...}, high,low,ltp,ltq,oi,
  open,prev_close,totalbuyqty,totalsellqty,volume}`. The required method name is
  **`get_depth`** (alias `get_market_depth` if needed).
- `get_history` → **pandas DataFrame** with columns
  `[timestamp, open, high, low, close, volume, oi]`, `timestamp` = **epoch
  seconds**. The service returns it via `df.to_dict(orient="records")` — so YOUR
  epoch convention is what ships.

### NUANCE — price scaling
Many brokers send prices as scaled integers (e.g. paise = ×100). De-scale in
quotes/depth/history (divide). Volume/OI are raw. Confirm the scale per segment.

### NUANCE — history intraday vs daily timestamps (critical)
Match the zerodha convention so epochs are consistent across brokers:
- intraday (min/hour): true UTC epoch of the IST candle time
- **daily/weekly/monthly: shift +5:30** so the candle represents IST midnight
```python
df["timestamp"] = pd.to_datetime(df["timestamp"], format="ISO8601")
if timeframe in ("D", "W", "M"):
    df["timestamp"] = df["timestamp"] + pd.Timedelta(hours=5, minutes=30)
df["timestamp"] = df["timestamp"].astype("int64") // 10**9
```
(If the broker returns naive intraday timestamps, localize to IST first.)

### NUANCE — index exchange translation
If the broker uses one `INDEX` pseudo-exchange, translate OpenAlgo
`NSE_INDEX`/`BSE_INDEX` → the broker's index exchange on every quote/depth call,
and to the parent cash exchange for history. Keep a shared `mapping/exchange.py`.

### NUANCE — the quote API may have its OWN symbol vocabulary for indices
The symbol stored in `brsymbol` is not necessarily what the quote endpoint
accepts. Arrow's INDEX quotes accept: the **underlying name** for the 5
derivative indices (`NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`,
`NIFTYNXT50` — their display names are rejected) but the **UPPERCASED display
name** for everything else (`NIFTY IT`, `INDIA VIX`, `SMLCAP`). Probe a
handful of each class with a tiny script before assuming. Robust pattern
(see `broker/arrow/api/data.py` `_quote_index`): try candidates in order
(OpenAlgo symbol → uppercased brsymbol → raw brsymbol), treat 400 as
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
instruments per `/info/quotes` request** (hard server cap: 100 → 200 OK,
101 → HTTP 500 "unable to get quotes"). Find the cap empirically — binary
search batch sizes (1/10/50/100/101/150) against the live endpoint — and loop
any-size symbol sets in cap-sized chunks throttled under the rate limit.
Pattern (zerodha/upstox/arrow):
- `get_multiquotes`: chunk at the broker's per-request cap with a delay between
  chunks (Arrow: 100/request, ~0.15s delay).
- `get_history`: throttle (small `time.sleep`) between date-chunks; chunk long
  ranges (broker caps the per-request range, often larger for daily).
The OpenAlgo `/api/v1/history` endpoint itself is rate-limited by
`API_RATE_LIMIT` (see `restx_api/history.py`) — that's separate (per-IP) and not
your concern in the broker module.

---

## 7. Account-data normalization → common format (match docs exactly)

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
- product: OpenAlgo `CNC/NRML/MIS` → broker codes
- pricetype: `MARKET/LIMIT/SL/SL-M` → broker codes (some brokers disable plain
  market — emulate with a flag, e.g. Arrow `mpp:true`)
- action: `BUY/SELL` → broker codes
- `place_order_api` MUST set `response.status = response.status_code` (services
  check `res.status == 200`).
- Smart order: per-symbol lock + short-TTL position cache (copy from zerodha).

---

## 8. Streaming (the hardest part — copy zerodha/upstox closely)

3-layer pipeline: broker adapter → ZeroMQ bus → unified proxy (port 8765).

- Adapter subclasses **`websocket_proxy/base_adapter.BaseBrokerWebSocketAdapter`**;
  call `super().__init__()`. Implement `initialize(broker_name, user_id,
  auth_data=None)`, `connect()`, `subscribe(symbol, exchange, mode=2,
  depth_level=5)`, `unsubscribe(symbol, exchange, mode=2)`, `disconnect()`.
- Modes: **1=LTP, 2=Quote, 3=Depth**.
- Publish ticks with the inherited **`self.publish_market_data(topic, data)`** —
  do NOT create your own ZMQ socket. Topic = `f"{exchange}_{symbol}_{MODE}"`
  with MODE ∈ `LTP/QUOTE/DEPTH`.
- Register the class in `websocket_proxy/__init__.py` (`register_adapter`). The
  factory also has a dynamic-import fallback expecting module
  `broker.<name>.streaming.<name>_adapter` and class `<Name>WebSocketAdapter`.
- Capability registry (`<name>_mapping.py`): declare modes and
  `get_supported_depth_levels()` (default `[5]`). Return `actual_depth` from
  `subscribe()` so the proxy reports it. For depth > 5, follow the **fyers**
  pattern (a second TBT socket routed by `depth_level`).

### NUANCES (the eventlet/FD ones that cause real bugs):
- **Use sync `websocket-client` in a daemon thread — NEVER asyncio/`websockets`.**
  eventlet monkey-patching breaks asyncio under gunicorn.
- **Never `join()` daemon threads** (eventlet raises Timeout). Stop via a
  `threading.Event` and close the socket.
- **Close-before-reconnect**; reconnect with interruptible exponential backoff.
- **Re-read a fresh token on reconnect** (`get_auth_token(user_id,
  bypass_cache=True)`) — Indian broker tokens roll over ~3 AM IST. Bounded
  auth-refresh retry instead of dying on the first 403.
- **Keepalive**: `run_forever(ping_interval, ping_timeout)` + a data-stall
  health-check watchdog that forces reconnect after N seconds of silence.
- **FD hygiene**: call `self.cleanup_zmq()` in `disconnect()` (and `__del__`).
- **Token-based feeds**: indices stream like any instrument (token from the
  master contract) — no special casing needed.
- If your broker has a new two-segment index exchange, add it to the proxy's
  topic-split prefix set in `websocket_proxy/server.py` (NSE_INDEX/BSE_INDEX are
  already handled).
- Binary feeds: confirm framing (one packet per message vs length-prefixed
  multi-packet) and endianness against a LIVE capture before trusting offsets.

### NUANCE — binary offsets: never guess, and know the symptom of a wrong guess
If the docs don't publish byte offsets, get them from the **official SDK's
parser source** (see §0). A wrong offset doesn't crash — it produces
*plausible garbage*: Arrow's draft parser read bytes 13:17 as "close" in every
packet, but in 93-byte quote packets that field is **last traded quantity**,
so the UI showed "close ₹0.02" (LTQ=2). Also beware mode-dependent layouts:
the same offset means different things at different packet sizes (13:17 IS
close in the 17-byte LTPC packet). The broker may run TWO streams with
different protocols (Arrow: standard stream = big-endian/token-keyed, HFT
stream = little-endian/symbol-keyed) — make sure the docs page you're reading
matches the URL you connect to.

**Test the parser with synthetic packets** before going live: build byte
buffers with `struct.pack` placing known values at the documented offsets for
every packet size (ltp/ltpc/quote/full + legacy sizes), and assert each parsed
field. This catches off-by-N immediately and needs no market hours.

### NUANCE — tick-parsing hot path
The parser runs per tick; keep it allocation-light: module-level **precompiled
`struct.Struct`** objects with ONE `unpack_from` per packet region (not 15
separate `struct.unpack` calls), `iter_unpack` for repeated depth levels, and
**no lock acquisition per tick** (CPython dict reads are GIL-atomic; lock only
the writers). Arrow's parser does ~2.3µs per full-depth packet this way.
Emit the **same normalized key set as the zerodha adapter** (`open/high/low/
close`, `volume`, `average_price`, `last_quantity`, `total_buy_quantity`,
`total_sell_quantity`, `oi`, `depth.buy/sell` with `price/quantity/orders`) so
the proxy/UI see one shape across brokers.

---

## 9. HTTP connection pooling & FD hygiene (mandatory)

- **All REST via `utils/httpx_client.get_httpx_client()`** — a shared pooled
  HTTP/2 client. NEVER `httpx.Client()`/`requests`/`urllib` per call.
- The shared client has a default **120s timeout**; add an explicit `timeout=`
  for large/slow calls (e.g. the instrument-master download).
- DB engines via `database.engine_factory.create_db_engine()` (NullPool).
- Use `with db_session() as session:` for reads; `db_session.remove()` in a
  `finally` for background-thread work.
- After building, run a **focused FD audit** of your change (every DB session,
  socket, WS, ZMQ socket, file, thread): confirm each is closed on success,
  error, and reconnect.

---

## 9.5 The live-hardening pass (where the real bugs are)

Scaffolding from docs gets you ~70%. The remaining 30% — the part that decides
whether the broker *works* — only falls to **live probing**. Arrow's
integration had SIX such bugs (auth field names, exchange codes, strike
scaling, websocket offsets, index quote vocabulary, multiquote cap), and not
one was visible in the code review. Budget a deliberate hardening pass:

1. **Probe with throwaway scripts, fix, then codify.** Keep a scratch dir
   OUTSIDE the repo. Pull the stored token once and hit the live endpoint
   directly with httpx, varying one thing at a time:
   ```python
   from database.auth_db import Auth, get_auth_token
   row = Auth.query.filter_by(broker="<name>", is_revoked=False).first()
   token = get_auth_token(row.name)   # then httpx.post(...) with candidates
   ```
   Probe matrices that pay off: symbol spelling variants × exchange-code
   variants for one instrument per segment; batch sizes (binary search) for
   multi-instrument endpoints; one quote per exchange you claim to support.
2. **Read `log/errors.jsonl` first** when a UI page breaks. Five "different"
   broken tools (option chain, IV chart, OI tracker, max pain, GEX) were ONE
   root cause: index quotes 400ing. Fix the deepest shared failure, not the
   page.
3. **Don't edit broker files while a background download is running** — the
   dev server auto-reloads on save and kills in-flight threads (worst case:
   between `delete_symtoken_table()` and the re-insert). Wait for the
   `master_contract_status` table to flip to `success`, then edit.
4. **Verify like-for-like after refactors**: when you rewrite a working path
   for speed (e.g. vectorizing the master contract), diff the new output
   against the validated output row-by-row before swapping it in.
5. **Resolve every `TODO(<name>)` with live evidence, then delete it** —
   replace each with a comment stating what was verified and how ("verified
   live: 100 → 200 OK, 101 → 500"). The next person must be able to tell
   guesses from facts.

---

## 10. Verification checklist (run before declaring done)

```bash
# Compile + lint
uv run python -m py_compile broker/<name>/**/*.py
uv run ruff check broker/<name>/

# Import in NORMAL flow (websocket_proxy first to avoid the adapter
# circular-import that trips ALL brokers on direct-first import)
uv run python -c "from dotenv import load_dotenv; load_dotenv(); import websocket_proxy; \
from websocket_proxy.broker_factory import _get_adapter_class; \
print(_get_adapter_class('<name>').__name__)"

# FD/pooling audit
grep -rnE 'httpx\.Client\(|requests\.|urllib|aiohttp' broker/<name>/   # must be empty
```

Also verify against the live symtoken: `instrumenttype` ∈ {EQ,FUT,CE,PE},
indices = EQ, `expiry` = `DD-MMM-YY`, FUT/CE/PE symbols, daily vs intraday
history epochs.

---

## 11. Nuance cheat-sheet (the easy-to-miss list)

- [ ] `authenticate_broker` exact name; returns 2-tuple
- [ ] auth payload uses the broker's LITERAL JSON keys (verbatim curl/SDK, not prose)
- [ ] callback param spelling (hyphen/camelCase) handled in `brlogin.py`
- [ ] `place_order_api` sets `response.status`
- [ ] instrumenttype indices = **EQ** (no INDEX type)
- [ ] expiry `DD-MMM-YY` uppercase; empty for EQ/index
- [ ] `name` = underlying for derivatives
- [ ] `contract_value` column declared
- [ ] price de-scaling (paise ×100) in quotes/depth/history
- [ ] history **daily +5:30**, intraday no shift
- [ ] NSE_INDEX/BSE_INDEX translated to broker INDEX on quote/depth/history
- [ ] index quote symbol vocabulary probed live (candidate-fallback + per-token cache if it differs from brsymbol)
- [ ] quote-unsupported exchanges fail fast AND are skipped in batch requests
- [ ] multiquotes chunked at the broker's PER-REQUEST cap (found empirically) + throttled under the rate limit; history throttled
- [ ] margin: single → order calculator, multi-leg → basket calculator (Dhan pattern); never sum legs when a basket endpoint exists
- [ ] NO hardcoded market timings in broker folder
- [ ] streaming: sync websocket-client, no thread.join, cleanup_zmq, token refresh on reconnect, keepalive watchdog
- [ ] all REST via shared pooled httpx client; explicit timeout on big downloads; db_session.remove() in background threads
- [ ] broker id added to VALID_BROKERS + all install scripts + READMEs + BrokerSelect.tsx + websocket_proxy registration
- [ ] account-data output field names match `docs/api/account-services/*`

---

## 12. New-broker integration checklist (do in order)

### A. Research
- [ ] Read the broker's API docs; note auth model, hosts, enum codes, price scaling, instrument master source, websocket protocol, rate limits
- [ ] Read `docs/prompt/symbol-format.md`, `docs/prompt/order-constants.md`, `docs/api/**`, `docs/prompt/services_documentation.md`, root `CLAUDE.md`
- [ ] Connect a working broker (e.g. zerodha) once and inspect `db/openalgo.db` `symtoken`
- [ ] Pick the closest reference broker (zerodha / upstox / fyers)

### B. Scaffold `broker/<name>/`
- [ ] `plugin.json` with correct `supported_exchanges`, `broker_type`, `leverage_config`
- [ ] `api/baseurl.py` (hosts + auth-header builder) if helpful
- [ ] `api/auth_api.py` — `authenticate_broker()` returning `(token, error)`
- [ ] `mapping/transform_data.py` — order payload + product/pricetype/action maps
- [ ] `mapping/order_data.py` — all `map_*`/`transform_*`/`calculate_*` to common format
- [ ] `mapping/exchange.py` — exchange + index (NSE_INDEX/BSE_INDEX) translation
- [ ] `api/order_api.py` — place/smart/modify/cancel/cancel_all/close/books/positions/holdings/open_position
- [ ] `api/data.py` — `BrokerData` (`timeframe_map`, `get_quotes`, `get_depth`, `get_history`, `get_multiquotes`)
- [ ] `api/funds.py` — `get_margin_data`
- [ ] `database/master_contract_db.py` — `SymToken` (+`contract_value`) + `master_contract_download()`
- [ ] `streaming/<name>_mapping.py` — exchange + capability registries
- [ ] `streaming/<name>_websocket.py` — sync client (keepalive/reconnect/auth-refresh/binary parse)
- [ ] `streaming/<name>_adapter.py` — `<Name>WebSocketAdapter(BaseBrokerWebSocketAdapter)`
- [ ] `streaming/__init__.py` exports the adapter

### C. Wire into the platform
- [ ] `websocket_proxy/__init__.py` — import + `register_adapter` + `__all__`
- [ ] `.sample.env` + `.env` — add to `VALID_BROKERS`
- [ ] `install/install.sh`, `install-docker.sh`, `install-multi.sh`, `install-docker-multi-custom-ssl.sh`, `docker-run.sh`, `docker-run.bat`, `start.sh` — add to every `valid_brokers` list (some appear twice)
- [ ] `install/README.md` + `README.md` — add to supported-broker lists
- [ ] `frontend/src/pages/BrokerSelect.tsx` — `allBrokers[]` entry + login-URL `case` (then `npm run build`)
- [ ] `blueprints/brlogin.py` — add an `elif broker == "<name>"` branch ONLY if the callback param name differs or token rewrite / feed_token handling is needed

### D. Configure `.env`
- [ ] `BROKER_API_KEY`, `BROKER_API_SECRET`, `REDIRECT_URL=http://<host>/<name>/callback` (must match broker portal)

### E. Verify
- [ ] `uv run python -m py_compile broker/<name>/**/*.py`
- [ ] `uv run ruff check broker/<name>/`
- [ ] Import via `websocket_proxy` first; factory resolves `<name>`
- [ ] `grep -rnE 'httpx\.Client\(|requests\.|urllib|aiohttp' broker/<name>/` is empty
- [ ] Master-contract rows match live symtoken (instrumenttype, expiry, symbol, name)
- [ ] Daily vs intraday history epoch correct
- [ ] FD audit of the change passes (sessions/sockets/WS/ZMQ/threads/files released)

### F. Live test (needs credentials + SEBI static-IP whitelisting)
- [ ] Login → token stored → master contract downloads → symbols searchable
- [ ] Master contract validated offline BEFORE the in-app run: per-exchange row
      counts, sample symbols per segment vs `docs/prompt/symbol-format.md`,
      zero duplicate (symbol, exchange), all common index symbols present
- [ ] Quotes / depth for EQ, FUT, option on EVERY exchange in `plugin.json`
      (not just NSE — Arrow's MCX needed a different code and CDS/NCO turned
      out unsupported) + NSE_INDEX/BSE_INDEX
- [ ] Multiquotes at realistic size (180+ option symbols — what the GEX tool
      sends) and mixed exchanges incl. an index
- [ ] History intraday + daily (epoch convention) for EQ, FUT, index
- [ ] `/websocket/test` page: LTP, Quote (real OHLC/volume — a wrong close
      like 0.02 means a binary-offset bug) and Depth incl. indices; reconnect
      after a forced drop
- [ ] Options tools end-to-end: `/optionchain`, `/ivchart`, `/oitracker`,
      `/maxpain`, `/gex` — these exercise quotes + multiquotes + expiry
      parsing together and fail loudly on any index-quote or batch-cap bug
- [ ] Margin: single order (vs the docs' example numbers), multi-leg straddle
      (basket number must be LESS than the per-leg sum), invalid symbol → clean 400
- [ ] Place / modify / cancel / smart order; orderbook / positions / holdings / funds
- [ ] Resolve all `TODO(<name>)` markers using observed live responses (then
      delete them — see §9.5)
</content>
