---
name: broker-integration
description: Integrate a new Indian broker into OpenAlgo, or modify an existing broker plugin. Use when wiring up a broker's auth/login, orders, quotes, depth, history, funds, margin, symbol master, or WebSocket streaming; when a broker does not appear in the login dropdown or fails to load; or when debugging broker-specific symbol, exchange-code, price-scaling, or order-field mapping.
---

# Integrating a broker into OpenAlgo

> **Golden rule:** OpenAlgo has a **common symbol format, common API, and common
> WebSocket format**. Your only job per file is to translate the broker's
> specific shapes into those common contracts (and back). Copy the closest
> reference broker, then adapt the broker-specific bits.

39 broker plugins already exist. Almost every problem you will hit has been solved in
one of them — the skill is knowing **which one to copy**, and which details are
genuinely broker-specific.

## Where broker code sits in the stack

```
restx_api/<endpoint>.py     Marshmallow schema validation + per-IP rate limit. Thin.
  services/<x>_service.py   Auth resolution, analyze-mode branch, event emission.
                            Returns (success: bool, response_data: dict, status_code: int)
    broker/<name>/api/*     <- YOU ARE HERE. The only place broker specifics live.
```

Two consequences worth internalizing:

- **You never emit events.** `events/` and `utils/event_bus.py` are a
  services-layer concern (order placed, cancelled, GTT triggered). Broker
  modules do not import them. The two exceptions in the tree
  (`broker/iiflcapital/streaming/iiflcapital_order_adapter.py` and
  `broker/nuvama/streaming/nuvama_order_adapter.py`) are non-WebSocket
  order-update streams, not the REST path — do not copy that pattern by default.
- **Analyze mode never reaches you.** `get_analyze_mode()` in the service
  short-circuits to `sandbox_service` before any broker call. So "it works in
  analyzer" proves nothing about your integration.

## Step 1 — identify the broker's family, then copy that broker

This is the highest-leverage decision. Indian brokers cluster into four auth
families, and picking the right template saves days:

| Family | Members already in the tree | Auth shape | Copy |
| --- | --- | --- | --- |
| **OAuth2 / checksum redirect** | zerodha, upstox, fyers, dhan, arrow, groww, paytm, aliceblue, definedge, rupeezy, nuvama, pocketful, iiflcapital, hdfcsky, hdfcsecurities | Redirect to broker, get `request_token`/`code` back on callback, exchange it (often SHA256 checksum of `api_key + token + secret`) | **`broker/zerodha/`** |
| **Noren / Finvasia** | shoonya, flattrade, tradesmart, zebu | Shared upstream codebase. Near-identical endpoints, `jData=`/`jKey=` form bodies, susurl/scrip-master CSVs per exchange | **`broker/shoonya/`** or `broker/flattrade/` |
| **Symphony XTS** | fivepaisaxts, jainamxts, compositedge, rmoney, iifl, ibulls, wisdom | Dual credentials: interactive + market-data. `BROKER_API_KEY_MARKET` / `_SECRET_MARKET` | **`broker/fivepaisaxts/`** |
| **Direct login + TOTP** | angel, mstock, motilal, kotak, firstock, samco, nubra, tradejini, fivepaisa, sahi, indmoney | User submits clientcode/password/TOTP in a form; no redirect | **`broker/angel/`** |

Special cases: **`broker/fyers/`** if the broker offers depth beyond 5 levels
(dual WebSocket, 50-level TBT socket). **`broker/deltaexchange/`** is the only
`broker_type: "crypto"` plugin and the only one with `leverage_config: true` —
ignore it for Indian equity brokers. `broker/dhan_sandbox/` mirrors dhan
against Dhan's sandbox.

If the broker is a white-label of one of the above (very common — many Indian
brokers resell Noren or XTS), the family template is often 90% correct as-is.
Check the API docs for tell-tale endpoint paths (`/NorenWClientTP/`,
`/interactive/user/session`) before assuming it is bespoke.

## Step 2 — read the common contracts before writing anything

These define the format you must conform to. Do not infer them from a
reference broker's code — read the specs:

| Topic | File |
| --- | --- |
| Symbol format (EQ/FUT/CE/PE, indices, exchange codes) | `docs/prompt/symbol-format.md` |
| Order constants (product, pricetype, action, exchanges) | `docs/prompt/order-constants.md` |
| Lot size conventions | `docs/prompt/LotSize.md` |
| Common API request/response per endpoint | `docs/api/**` (esp. `account-services/`, `market-data/`, `order-management/`) |
| WebSocket streaming format | `docs/prompt/websockets-format.md`, `docs/api/websocket-streaming/*` |
| Services layer contract | `docs/prompt/services_documentation.md` |
| Rate limits | `docs/api/rate-limiting.md` |
| Long-form integration notes | `docs/broker-integration-guide.md` |
| Runtime constraints (eventlet, NullPool, FD hygiene) | root `CLAUDE.md` |

**Inspect the LIVE `db/openalgo.db` `symtoken` table of a working broker** (e.g.
connect zerodha once). This is the single most useful reference — it shows the
exact column values your master contract must reproduce.
**Do this BEFORE wiping symtoken with your new broker's data** — the old
broker's rows are your ground truth for NCO symbol format, MCX_INDEX names,
expiry formatting and the index symbol set. Once you overwrite the table, that
reference is gone.

### Calibrate against the plugins that already exist

Before deciding what is normal for a broker — batch caps, rate limits, depth
levels, which capabilities OpenAlgo even has a contract for — read
**`references/cross-broker-reference.md`**. It records how the existing
plugins actually behave, measured from the tree, so you are not guessing at
defaults or reinventing a decision someone already made.

If you have no reachable documentation for your broker, read its **family**
sibling in the tree — a Noren white-label behaves essentially like
`broker/flattrade/`, an XTS white-label like `broker/fivepaisaxts/`.

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

## Step 3 — the module contract

Services do `importlib.import_module(f"broker.{broker}.api.<module>")` and call
**fixed names** — these ARE the contract. Verified against `services/*.py`:

| Service | Module | Function | Returns |
| --- | --- | --- | --- |
| login | `api.auth_api` | `authenticate_broker(...)` | `(auth_token, error)` — arity varies, see below |
| place | `api.order_api` | `place_order_api(data, auth)` | `(response, response_data, orderid)`; `response.status == 200` = success |
| smart | `api.order_api` | `place_smartorder_api(data, auth)` | same shape |
| modify | `api.order_api` | `modify_order(data, auth)` | `(dict, status_code)` |
| cancel | `api.order_api` | `cancel_order(orderid, auth)` | `(dict, status_code)` |
| cancel all | `api.order_api` | `cancel_all_orders_api(data, auth)` | `(canceled[], failed[])` |
| close | `api.order_api` | `close_all_positions(api_key, auth)` | `(dict, status_code)` |
| orderbook | `api.order_api` + `mapping.order_data` | `get_order_book(auth)`; `map_order_data`, `calculate_order_statistics`, `transform_order_data` | raw -> normalized |
| tradebook | `api.order_api` + `mapping.order_data` | `get_trade_book(auth)`; `map_trade_data`, `transform_tradebook_data` | |
| positions | `api.order_api` + `mapping.order_data` | `get_positions(auth)`; `map_position_data`, `transform_positions_data` | |
| holdings | `api.order_api` + `mapping.order_data` | `get_holdings(auth)`; `map_portfolio_data`, `calculate_portfolio_statistics`, `transform_holdings_data` | |
| (internal) | `api.order_api` | `get_open_position(symbol, exchange, product, auth)` | net qty as **str** (used by smart order) |
| funds | `api.funds` | `get_margin_data(auth)` | dict |
| quotes | `api.data` | `BrokerData(auth).get_quotes(symbol, exchange)` | dict |
| depth | `api.data` | `BrokerData(auth).get_depth(symbol, exchange)` | dict (5 levels) |
| history | `api.data` | `BrokerData(auth).get_history(symbol, exchange, interval, start, end)` | **pandas DataFrame** |
| multiquotes | `api.data` | `BrokerData(auth).get_multiquotes(symbols)` | list — **optional**, see below |
| intervals | `api.data` | `BrokerData(auth).timeframe_map` (attribute) | dict |
| master | `database.master_contract_db` | `master_contract_download()` | emits socketio event |
| margin | `api.margin_api` | `calculate_margin_api(positions, auth)` | `(response, data)`; `data.data` = `{total_margin_required, span_margin, exposure_margin}` (+ optional `total_charges`) |
| GTT | `api.gtt_api` | `place_gtt_order`, `modify_gtt_order`, `cancel_gtt_order`, `get_gtt_book` | **optional** — angel, dhan, fyers, pocketful, rupeezy, upstox and zerodha have one; the capability gate returns **501** when absent |

`auth` is always the decrypted broker token string (last positional arg).

There is one more optional surface: an **order-update stream** (real-time fills,
rejections, cancellations pushed to the client). 24 of 39 brokers have one
(22 push adapters, 2 polled); HDFC Sky and HDFC Securities deliberately have none.
It is registered separately in `services/order_update_service.py`, not in the
table above — see `references/order-updates.md`.

### NUANCE — `BrokerData.__init__` arity is introspected, not fixed

`services/quotes_service.py` inspects `BrokerData.__init__.__code__.co_argcount`
and passes `(auth_token, feed_token)` when the constructor takes two args,
otherwise `(auth_token)`. So a broker whose market-data API needs a **separate
feed token** simply declares `def __init__(self, auth_token, feed_token)` and
the service adapts. All the common templates (zerodha/dhan/fyers/flattrade/
angel/arrow) are single-arg — only add the second parameter if the broker truly
has a distinct feed credential.

### NUANCE — `get_multiquotes` is optional and silently degrades

The service does `hasattr(data_handler, "get_multiquotes")` and falls back to
looping `get_quotes` per symbol if absent. That fallback *works* but is brutally
slow for the options tools, which request 180+ symbols at once. Implement
`get_multiquotes` for any broker with a batch quote endpoint.

### NUANCE — margin: never sum legs when a basket endpoint exists

**Copy `broker/dhan/api/margin_api.py`** — it is the reference pattern: route ONE
position to the broker's single-order calculator (detailed charge breakdown) and
2+ positions to the basket/multi calculator so the broker nets spread/hedge
benefits (an Arrow NIFTY short straddle priced at ~207k via basket vs ~337k as a
naive per-leg sum). Include Dhan's two guards: a JSON-decode guard (non-JSON
broker reply -> 502) and `_normalise_success_response` (broker sends an error
payload with HTTP 200 -> convert to a 400 response object, because
`margin_service` trusts HTTP 200; any non-200 status works).

Read which figure the basket endpoint returns. Flattrade's `marginused` is
pre-hedge, and `marginusedtrade` is post-hedge but includes margin the account
already uses, so subtract `Limits.marginused` (#2156, #2436). Kotak's
`reqdMrgn` adds existing usage to each leg; report `ordMrgn`. A leg that is
unknown or failed (an unsupported exchange such as NSE_INDEX included) fails
the whole basket with the leg named: dropping it reports another basket's
margin. MARKET and SL-M legs are priced as order emulation prices them (off the
trigger for SL-M, on the SymToken tick, never a limit at price 0). Re-raise
`BrokerBusyError` from any catch-all (#2439). After a refactor, confirm
`calculate_margin_api` still exists: losing it made every Flattrade `/margin`
call "not implemented".

### Symbol translation helpers you must use

Import from `database.token_db` (re-exported from `token_db_enhanced`) — never
hand-roll symbol lookups:

| Helper | Direction |
| --- | --- |
| `get_token(symbol, exchange)` | OpenAlgo symbol -> broker instrument token |
| `get_symbol(token, exchange)` | token -> OpenAlgo symbol |
| `get_br_symbol(symbol, exchange)` | OpenAlgo symbol -> broker tradingsymbol |
| `get_oa_symbol(brsymbol, exchange)` | broker tradingsymbol -> OpenAlgo symbol |
| `get_brexchange(symbol, exchange)` | OpenAlgo exchange -> broker exchange code |
| `get_symbol_info(symbol, exchange)` | full `SymToken` row (lotsize, tick_size, expiry, ...) |
| `get_tokens_bulk(pairs)` | batch token lookup — use in `get_multiquotes` |

## Step 4 — required directory layout

```
broker/<name>/
  __init__.py
  plugin.json                         # metadata; see below
  api/__init__.py
  api/baseurl.py                      # (optional) hosts + auth-header builder (DRY)
  api/auth_api.py                     # authenticate_broker(...)
  api/order_api.py                    # place/modify/cancel/book/positions/holdings
  api/data.py                         # class BrokerData (quotes/depth/history)
  api/funds.py                        # get_margin_data(auth)
  api/margin_api.py                   # (optional) calculate_margin_api
  api/gtt_api.py                      # (optional) GTT support
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

`plugin.json` fields that actually do something: `supported_exchanges` (drives
capability checks and what you must live-test), `broker_type` (`IN_stock` for
all 38 Indian brokers, `crypto` for deltaexchange), `leverage_config` (false for
every Indian broker in the tree).

## Shared `utils/` a broker plugin depends on

Never hand-roll these — the shared helper is the contract, and bypassing it is
how FD leaks, unredacted secrets and rate-limit breaches get introduced. Usage
counts across the 39 existing plugins:

| Module | Uses | What you must take from it |
| --- | --- | --- |
| `utils.logging` | ~361 | `logger = get_logger(__name__)` in every module; errors use `logger.exception()`. Its `SensitiveDataFilter` masks known credential patterns, and a bare `print()` or `logging.getLogger()` bypasses it, but it is a backstop, not the control: never log a token, key or secret, any slice of one (prefix, suffix, `[:20]`), a login reply or connect URL carrying one, or header values. Log the length, the type or the header names. A JainamXTS token's first and last four characters passed the filter (#2313). `test/test_xts_credential_logging.py` is the guard; extend it to your broker. |
| `utils.httpx_client` | ~210 files | `get_httpx_client()` — the shared pooled HTTP/2 client. Never construct a per-call client. Always pass an explicit `timeout=`. |
| `utils.mpp_slab` | ~25 files | Market Price Protection slabs for emulating MARKET/SL-M. See `references/order-type-emulation.md`. |
| `utils.config` | ~5 | `get_broker_api_key()`, `get_broker_api_secret()`, `get_host_server()`, rate-limit getters. Prefer these over raw `os.getenv` so composite `:::` keys and defaults resolve consistently. |
| `utils.constants` | 2 | `EXCHANGE_NSE`, `EXCHANGE_NFO`, ... — canonical exchange codes. Use them instead of string literals. |
| `utils.plugin_loader` | — | Discovers `broker/*/plugin.json` at startup and requires the exact name `authenticate_broker`. You do not call it; it calls you. |
| `utils.runtime` | — | `gthread_active()`, `is_monkey_patched()`. Never test `"eventlet" in sys.modules` or import eventlet to find out. |
| `utils.broker_backpressure` | — | `check_queue_wait`, `BrokerBusyError`, `busy_response`, `cap_server_delay`: the gthread refusal path, see Step 5b. |
| `utils.smart_order_guard` | — | `SymbolLocks` and `PositionBookCache` for smart orders; never a hand-rolled lock dict or position cache. |
| `utils.position_read` | — | `read_position_book` and `refuse_smart_order_on_read_failure`: a failed position read places nothing. |
| `utils.shared_executors`, `utils.lazy`, `utils.thread_safe_cache`, `utils.real_threading` | — | `get_executor(name, n)`, `LazyInit`, `LockedTTLCache`, `wait_for`: see Step 5b. |

`utils.event_bus` exists but is a **services-layer** concern — broker modules do
not publish events.

## You do not touch `restx_api/`

No broker plugin references `restx_api/`, and a new broker must not add one.
That layer is broker-agnostic: each file is a thin Marshmallow-validated,
rate-limited Flask-RESTX resource that calls a service, which then dispatches to
whichever broker is configured. Adding an endpoint there for one broker's
special feature would break the "common API across all brokers" contract.

If a broker offers something OpenAlgo has no endpoint for (GTT on a third
broker, bracket orders, 20-level depth), the change is: service layer first,
then `restx_api/` — as a capability available to every broker, not a one-off.
See the capability list in `references/cross-broker-reference.md`.

## Step 5 — HTTP pooling and FD hygiene (mandatory, applies throughout)

- **All REST via `utils/httpx_client.get_httpx_client()`** — a shared pooled
  HTTP/2 client. NEVER `httpx.Client()` / `requests` / `urllib` / `aiohttp` per call.
- The shared client has a default **120s timeout**; add an explicit `timeout=`
  for large/slow calls (e.g. the instrument-master download).
- DB engines via `database.engine_factory.create_db_engine()` (NullPool).
- Use `with db_session() as session:` for reads; `db_session.remove()` in a
  `finally` for background-thread work.
- After building, run the **`fd-audit`** skill on your change.

## Step 5b — correct under eventlet, gthread and the dev server

Production runs eventlet by default and gthread (64 real request threads) when
an install opts in; `uv run app.py` is neither. Under gthread anything that
sleeps or waits holds a request thread. Gate trader-visible behaviour on
`utils.runtime.gthread_active()` and keep eventlet and the dev server exactly
as before. None of this shows on Windows: run `test/test_gthread_*.py` on Linux
(root `CLAUDE.md`).

- **A pacer refuses instead of sleeping.** Before booking a slot, call
  `check_queue_wait(wait, kind)` (`"order"` for writes); it raises
  `BrokerBusyError` and books nothing. A `Retry-After` beyond
  `cap_server_delay` ends the retry. Order writes get their own clock where the
  broker caps them separately (Upstox, TradeSmart, IIFL, IndMoney, then
  AliceBlue, Flattrade, Dhan, Fyers, Angel, Definedge).
- **A refusal reaches the caller as busy (429), never as data.** Let
  `BrokerBusyError` through every generic `except`. A refused positions read is
  never a flat position (the smart order returns `busy_response` and sends
  nothing); a refused order-book read is never "nothing to cancel"; close-all
  says how many positions were left open; quote, depth and history raise rather
  than return zeros or an empty frame (Upstox, IndMoney, Motilal, Tradejini,
  Pocketful, Nubra, IIFL).
- **Requests that wait on a feed for a quote are capped**: a bounded
  semaphore, re-entrant per thread, refused after the data queue wait or
  answered from REST (Motilal, Pocketful, Nubra, Tradejini, mStock).
- **Fan out through `utils.shared_executors.get_executor(name, n)`** under
  gthread, never a `ThreadPoolExecutor` per call; keep the per-call pool under
  eventlet, where the health monitor's thread thresholds expect it. No task
  submits to the pool it runs on.
- **asyncio only on the dev server**:
  `USE_ASYNC = not (runtime.is_monkey_patched() or runtime.gthread_active())`,
  checked at call time, and the async path still goes through the pacer
  (Shoonya, Zebu, Flattrade, Definedge).
- **A client built lazily is built once under a lock** (`utils.lazy.LazyInit`;
  Dhan's GTT client was built twice under concurrent first use).
- **No `Model.query` in broker code**: `with db_session() as session:` and
  materialise rows before it closes. A pooled thread never reaches the app
  teardown that would have closed it (Delta Exchange).
- **A request waiting on an Event a real thread sets** uses
  `utils.real_threading.wait_for`, never `Event.wait()` (HDFC Securities and
  HDFC Sky snapshot feeds).
- **Caches are `LockedTTLCache` with a size cap**, never an unbounded dict.
- **Import every module on a headless Linux Python.** An editor auto-import
  (`from turtle import position`) needs tkinter, which servers lack, and broke
  the order books of six XTS brokers.

## Detailed references — load the one for the phase you are in

| Phase | Read |
| --- | --- |
| Calibration: batch caps, rate limits, depth, capability gaps | `references/cross-broker-reference.md` |
| Auth, login callback, `.env` + install wiring | `references/auth-and-login.md` |
| Instrument master, `SymToken`, symbol construction | `references/master-contract.md` |
| Quotes / depth + account-data normalization | `references/data-and-account.md` |
| Historical data — timestamps, chunking, boundaries | `references/history-data.md` |
| Rate limiting — pacing strategy, 429 handling | `references/rate-limiting.md` |
| MARKET / SL-M emulation when the broker lacks them | `references/order-type-emulation.md` |
| Market-data WebSocket adapter, binary parsing, ZMQ | `references/streaming.md` |
| Account-level order/trade update stream | `references/order-updates.md` |
| Live-hardening pass, verification, cheat-sheet | `references/hardening-and-verification.md` |

## Build order

1. **Research** — API docs, pick the family template, read the common contracts, inspect a live `symtoken`, download the broker SDK.
2. **`plugin.json` + `api/auth_api.py`** — get login working end-to-end first. Nothing else can be tested until a token is stored.
3. **Platform wiring** — `VALID_BROKERS` in `.sample.env` and the `start.sh` fallback (installers take it from `.sample.env`), `utils/broker_login.py` (how the login starts and how its answer is checked), `utils/broker_keys.BROKER_NAMES`, `utils/broker_setup_guide.py` (its Broker Configuration fields and sign-in sentence; Select Broker lists brokers from the server, so there is no frontend list), `websocket_proxy/__init__.py`, `brlogin.py` branch that ends in `_complete_login(...)`, and `BrokerTOTP.tsx` for a form broker. See `references/auth-and-login.md`, which also covers the state a broker must return, account checks from the broker's own answer, the refusal codes and the tests a login needs. Without this the broker will not even appear on Select Broker, or its login answer is refused.
4. **`database/master_contract_db.py`**: symbols must exist before quotes/orders can be tested. Validate offline against the live symtoken reference, then run the **Nifty 500 check** until it prints `NIFTY 500 COMPLETE` (see below). A missing constituent is fixed in the master contract, never worked around in a consumer.
5. **`mapping/` + `api/data.py`** — quotes, depth, history.
6. **`api/order_api.py` + `mapping/order_data.py`** — orders and books.
7. **`api/funds.py`, `api/margin_api.py`** — funds and margin.
8. **`streaming/`** — market data first (the hardest part), then the optional order-update adapter.
9. **Live-hardening pass** — see `references/hardening-and-verification.md`. Budget real time for this; it is where the actual bugs are.

## What "done" does not mean

- **Analyze mode passing proves nothing.** It routes to the sandbox and never calls your code.
- **A clean code review proves little.** All six Arrow bugs survived review; every one needed a live probe.
- **NSE working proves nothing about the other exchanges.** Test every exchange listed in your `plugin.json` — that list is a promise.
- **A symbol search that finds HFCL proves nothing about its symbol.** Search matches substrings, so it shows HFCL-BE for "HFCL". Only an exact lookup of NSE's own list does: the Nifty 500 check below.

## The Nifty 500 check (required for every broker)

OpenAlgo's NSE equity symbol is the exchange's base symbol, which is exactly the
`Symbol` column of NSE's index constituent list. Every broker plugin must store
all 500 constituents under that symbol on `NSE`, each exactly once:

```bash
# After the broker's master contract download (log in first): checks the live symtoken
uv run python .claude/skills/broker-integration/scripts/check_nifty500.py

# Before anything is written: check the plugin's processed rows
#   process_<broker>_csv(path)[["symbol", "brsymbol", "exchange"]].to_csv("rows.csv", index=False)
uv run python .claude/skills/broker-integration/scripts/check_nifty500.py --rows-csv rows.csv
```

It downloads NSE's `ind_nifty500list.csv` (or takes `--nifty-csv` for a saved
copy), skips rows NSE marks as placeholders (ISIN beginning `DUM`, such as
`DUMMYHEG`) and prints `NIFTY 500 COMPLETE` with exit code 0. Anything else is
a master contract defect to fix before the broker ships: for each missing
constituent it prints what the master contract holds instead. The usual cause
is a series suffix kept in the OpenAlgo symbol (see `references/master-contract.md`,
"series suffixes"). Zerodha failed it with 495 of 500 until HFCL-BE, STLTECH-BE,
EMBASSY-RR, BIRET-RR and BAGMANE-RR were given their base symbols.
