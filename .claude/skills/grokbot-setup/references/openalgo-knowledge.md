# OpenAlgo knowledge base for Grok Bot

The one file to read first for any OpenAlgo question. It is a map with the key
facts, not a replacement for the sources: when a detail matters (a parameter,
a response field, a limit), open the cited doc and use that.

Sources, read Oct 17, 2026: the repo (`README.md`, `CLAUDE.md`, `docs/`,
`.sample.env`, `.claude/skills/`), docs.openalgo.in, openalgo.in,
openalgo.in/charts, openalgo.in/script, and the installed `openalgo` SDK 2.0.5 in
`/workspace/pyenv`. Grok Bot's working notes in `/workspace/reference/`
(`openalgo-overview.md`, `openalgo-api.md`, `openalgo-symbols.md`,
`openalgo-indicators.md`, `openalgo-claude-skills.md`) carry longer detail.

## Contents

1. Where to look things up
2. What OpenAlgo is
3. Architecture and runtime
4. Product surfaces
5. Modes: Live, Sandbox (Analyze), Auto, Semi-Auto
6. REST API catalog
7. Python SDK quick reference
8. WebSocket protocol
9. Symbols and exchanges (Indian and crypto)
10. Order constants, lot sizes, quantity units
11. `openalgo.ta` indicators
12. OpenScript essentials
13. openalgo-charts and chart indicators
14. Flow JSON essentials
15. Integrations: TradingView, ChartInk, Amibroker, MCP, Telegram, WhatsApp
16. The other `.claude` skills
17. CLAUDE.md invariants that matter to a bot
18. Known conflicts between docs and code

---

## 1. Where to look things up

| Need | Go to |
| --- | --- |
| Any repo doc | `docs/INDEX.md` first (a map, not a copy), then the one file it points to |
| Public docs index | https://docs.openalgo.in/llms.txt |
| Any docs.openalgo.in page as markdown | append `.md` to the URL, e.g. `https://docs.openalgo.in/connect-brokers/brokers/zerodha.md` |
| Ask the docs a question | `GET <page>.md?ask=<question>` (documented at the end of the docs pages) |
| OpenScript | https://openalgo.in/script/llms.txt; reference manual at `/script/reference/v1`; markdown at `/script/openscript-reference.md`; repo `docs/openscript.md` |
| openalgo-charts | https://openalgo.in/charts; repo `docs/custom-indicators.md`; skill `chart-indicator` |
| REST API | `docs/api/README.md` and one page per endpoint under `docs/api/` |
| SDK | `docs/prompt/openalgo python sdk.md` |
| Symbols, constants, lot sizes | `docs/prompt/symbol-format.md`, `crypto-symbol-format.md`, `order-constants.md`, `LotSize.md` |
| WebSocket | `docs/prompt/websockets-format.md`, `websockets-verbose-control.md`, `docs/api/websocket-streaming/` |
| Flow | `docs/prompt/flow-import-format.md`; skill `flow-builder` |
| Strategy module and RMS | `docs/prompt/strategy_rms_documentation.md`, `docs/api/strategy-services/` |
| Internal service layer (code edits only) | `docs/prompt/services_documentation.md` |
| Indicators (`ta`) | `docs/prompt/indicators/`; docs.openalgo.in `/trading-platform/python/indicators` |
| User guide (setup to integrations, 01-32) | `docs/userguide/README.md` |
| Design docs 00-56 (incl. 30 upgrade procedure) | `docs/design/` (mirrored at docs.openalgo.in `/developers/design-documentation`) |
| Upgrade and recovery | `upgrade/README.md`, `docs/design/30-upgrade-procedure/README.md` |
| Releases and changelog | `docs/releases/`, `docs/CHANGELOG.md` |

Rule: if a source and this file disagree, the source wins; if docs and the
installed package disagree, test against the package (section 18).

## 2. What OpenAlgo is

- Free, open source (AGPL-3.0), self-hosted trading platform: Python Flask
  backend, React 19 frontend. Single user, one broker session per instance.
- 36 broker plugin folders under `broker/` plus `dhan_sandbox` (37 codes in
  `VALID_BROKERS`); docs.openalgo.in counts 34 securities brokers, the Dhan
  sandbox plugin and Delta Exchange (crypto). Credentials per broker:
  [brokers.md](brokers.md).
- Several products in one instance, all sharing one broker session and one
  WebSocket feed: Unified API, Python Strategy Host, Flow, Strategy Module and
  RMS, Options and Portfolio tools, Charting Terminal, Scalping Terminal, AI
  Agent; plus the Sandbox engine and Telegram alerts.
- SDKs: Python (`openalgo`, pinned at 2.0.5 in `pyproject.toml`), and Node.js,
  Java, Rust, .NET, Go (README); docs site adds R and MATLAB.
- Requirements (README): Python 3.12+, 2 GB RAM (or 0.5 GB plus 2 GB swap),
  1 GB disk, 1 vCPU. Node only for frontend development; `frontend/dist/` is
  committed on `main`.
- Disclaimer in README: educational; test in Analyzer Mode first.

## 3. Architecture and runtime

| Item | Value |
| --- | --- |
| Web app, REST, UI | `127.0.0.1:5000` (`FLASK_PORT`, `HOST_SERVER`) |
| WebSocket proxy | `ws://127.0.0.1:8765` (`WEBSOCKET_PORT`); production `wss://<domain>/ws` |
| ZeroMQ internal bus | `127.0.0.1:5555`; proxy SUB binds, broker adapters PUB connect; never expose |
| Market data path | broker adapter (pooled, `MAX_SYMBOLS_PER_WEBSOCKET` 1000 x `MAX_WEBSOCKET_CONNECTIONS` 3) -> ZMQ 5555 -> proxy 8765 -> clients |
| Databases | SQLite: `db/openalgo.db`, `logs.db`, `latency.db`, `health.db`, `sandbox.db`; DuckDB: `db/historify.duckdb` |
| Request chain | TrafficLogger -> SecurityMiddleware -> CSP -> Flask (CSRF, session) -> API key auth -> service -> broker |
| Production server | gunicorn, one worker, eventlet by default; gthread opt-in via `OPENALGO_WORKER_CLASS='gthread'` (64 threads) |
| Dev server | `uv run app.py` (Flask-SocketIO, plain threading); on the box run it under `script` for a TTY |
| Session expiry | Indian brokers about 3:00 AM IST (`SESSION_EXPIRY_TIME='03:00'`); crypto uses `DISABLE_SESSION_EXPIRY='true'` |
| Secrets | `APP_KEY` (sessions, CSRF), `API_KEY_PEPPER` (password and API key hashing, Fernet KDF input), `FERNET_SALT` (Fernet KDF salt); pepper and salt never change after the account exists |
| Security stack | Argon2 passwords, Fernet plus PBKDF2 token encryption, TOTP 2FA, rate limits, manual IP ban (security page, route `/logs/security`), CSP/CORS/CSRF, ORM only |
| Rate limits (`.sample.env`) | `API_RATE_LIMIT` 100/s, `ORDER_RATE_LIMIT` 10/s, `SMART_ORDER_RATE_LIMIT` 10/s, `WEBHOOK_RATE_LIMIT` 100/min, `STRATEGY_RATE_LIMIT` 200/min, login 5/min and 25/hour |
| Logs | console; `LOG_TO_FILE` writes to `log/`; errors in `log/errors.jsonl` |
| Health | `GET /auth/app-info` (name, version); `POST /api/v1/ping` (needs API key and a live broker session) |

Tech stack (README): Flask 3, SQLAlchemy 2, Flask-SocketIO, ZeroMQ,
Argon2-CFFI, cryptography, Agno and LiteLLM (agent); React 19, TypeScript,
Vite, Tailwind 4, shadcn/ui, TanStack Query, Zustand, CodeMirror, xyflow,
Lightweight Charts and Plotly. Diagram: `docs/architecture-diagram.png`.

## 4. Product surfaces

| Surface | Route | Key facts |
| --- | --- | --- |
| Unified Broker API | `/api/v1/` | One contract for TradingView, Amibroker, ChartInk, Excel, Sheets, Python, Go, Node, .NET, MetaTrader, GoCharting, N8N |
| Python Strategy Host | `/python` | In-browser editor; IST start and stop schedules; each script an isolated subprocess with live logs |
| Flow | `/flow` | No-code node graph (xyflow): market data -> indicators -> conditions -> orders; webhook triggers; JSON import and export (section 14). Node count: 61 on docs.openalgo.in, 53 on openalgo.in |
| Strategy Module and RMS | `/strategy` | Multi-leg options strategies with risk rules from `services/risk/`; kinds `batch` (all legs together) and `signal` (one leg per alert); created only in the browser wizard; driven over `/api/v1/strategy/*` or a webhook token |
| Options and Portfolio tools | `/tools` | 18 tools (registry `frontend/src/lib/tools.ts`): Option Chain, Greeks, OI Tracker, Max Pain, Vol Surface, GEX, IV Smile, Straddle, Arbitrage, Strategy Builder, Portfolio and SIP Backtesters, Portfolio Analyzer and more. README says 12 |
| Charting Terminal | `/trading` | Built on `openalgo-charts`; line-based chart trading, order dock; up to 7 saved layouts, grids up to 4x2; Scripts, Backtest and Strategies panels for OpenScript; custom JS indicators load at runtime |
| Scalping Terminal | `/scalping` | Keyboard-driven index options scalping; NRML/MIS only, never CNC; server-side stop, target, trail |
| AI Agent | `/agent` | Chat over market data, charts, payoffs and `ta` indicators; every order waits for explicit approval; LiteLLM providers, ChatGPT subscription OAuth, or Ollama |
| Sandbox (API Analyzer) | `/analyzer`, `/sandbox`, `/sandbox/mypnl`, `/logs/sandbox` | 1 Crore sandbox capital, real prices, MARKET/LIMIT/SL/SL-M, margin with leverage, auto square-off, separate `sandbox.db` |
| Action Center | `/action-center` | Semi-Auto mode queue: review, approve, modify, reject; bulk approve; audit trail in IST |
| Historify | `/historify` | DuckDB market-data warehouse; SDK `history(..., source='db')` reads it; CSV and Parquet export |
| Monitors | `/logs/latency`, `/logs/traffic`, `/logs/live`, `/pnl-tracker`, `/health` | Latency, traffic and live logs, P&L tracker, health (thresholds in `.env`) |
| Settings and tools | `/apikey`, `/broker`, `/logs/security`, `/telegram`, `/whatsapp`, `/playground`, `/platforms`, `/master-contract`, `/search` | API key, broker connect, security log and IP ban (README calls it `/security`), alerts, API playground, platform guides, master contract status, symbol search |

A new page needs three registrations (CLAUDE.md): route in `App.tsx`,
`blueprints/react_app.py` view, `frontend/src/config/navigation.ts` entry.

## 5. Modes: Live, Sandbox (Analyze), Auto, Semi-Auto

- **Live**: orders go to the broker. Needs the broker-registered static IP for
  API orders (SEBI, from April 1, 2026). The box has none.
- **Sandbox** (UI and API name: analyzer / Analyze mode): orders, positions,
  funds and GTTs are simulated in `db/sandbox.db`; prices still come from the
  connected broker. Application-wide, not per API key. Toggle in the UI or via
  `POST /api/v1/analyzer/toggle` (`client.analyzertoggle(mode=True)`); always
  read status first (`client.analyzerstatus()`). Responses carry
  `"mode": "analyze"`. MIS auto square-off: NSE/BSE/NFO/BFO 15:15, CDS/BCD
  16:45, MCX 23:30, NCDEX 17:00 IST.
- **Auto vs Semi-Auto** (order mode): Semi-Auto queues every order in the
  Action Center for approval; the analyzer toggle API is blocked in Semi-Auto.
- Words a trader sees: **Live** and **Sandbox** (or analyzer mode). Never
  "paper trading" or "arm/armed".

## 6. REST API catalog

All under `/api/v1`. JSON body with `apikey` (or `X-API-KEY` header). Responses
`{"status": "success"|"error", ...}` with `message` on error. Status codes: 200,
400 (validation), 401, 403 (bad key or blocked by mode), 404, 429 (rate limit),
500. Each endpoint page in `docs/api/` is authoritative.

| Group | Endpoints (POST unless noted) | Key params |
| --- | --- | --- |
| Orders | `placeorder`, `placesmartorder`, `basketorder`, `splitorder`, `modifyorder`, `cancelorder`, `cancelallorder`, `closeposition` | `strategy, symbol, exchange, action, quantity, pricetype, product, price, trigger_price, disclosed_quantity`; smart adds `position_size` (target net position); split adds `splitsize`; modify needs `orderid` |
| Options orders | `optionsorder`, `optionsmultiorder` | `underlying` + index exchange, `expiry_date` like `25AUG26`, `offset` ATM/ITMn/OTMn, `option_type`, `strike_int`; multi takes `legs[]` (BUY legs placed first) |
| GTT | `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook` | `trigger_type` SINGLE or OCO, `triggerprice_sl`, `triggerprice_tg`, `stoploss`, `target`; CNC/NRML only; Zerodha or Dhan (else 501); modify is a full replacement |
| Order info | `orderstatus`, `openposition` | `orderid`; `symbol, exchange, product` |
| Account | `funds`, `margin`, `orderbook`, `tradebook`, `positionbook`, `holdings` | `margin` takes `positions[]` |
| Market data | `quotes`, `multiquotes`, `depth`, `history`, `intervals`, GET `ticker/<symbol>` | `history`: `symbol, exchange, interval, start_date, end_date` (YYYY-MM-DD) |
| Symbols | `symbol`, `search`, `expiry`, GET `instruments` | `expiry` needs `instrumenttype` futures or options |
| Options analytics | `optionsymbol`, `optionchain`, `syntheticfuture`, `optiongreeks`, `multioptiongreeks` | chain: `strike_count`, `with_greeks`; Greeks Black-76 off the forward; multi max 50 symbols |
| Calendar | `market/holidays`, `market/timings` | `year`; `date` |
| Analyzer | `analyzer`, `analyzer/toggle`, `pnl/symbols` | `mode` true/false |
| Chart prefs | GET/POST `chart` | |
| Utility | `ping` | returns `pong` and broker; 403 without broker session |
| Strategy module | `strategy/list, status, start, stop, close_all, close_leg, runs, orders, events` | `start` needs `mode` sandbox or live (never defaulted; live 409 unless enabled in UI); `stop_pending` does not mean flat |
| Messaging | `telegram/*` (config, start, stop, webhook, users, broadcast, notify, stats, preferences), `whatsapp/notify` | |

## 7. Python SDK quick reference

Install on the box with uv (`uv add openalgo`); the docs say pip. All methods
are keyword-only. Installed 2.0.5 client methods: placeorder, placesmartorder,
optionsorder, optionsmultiorder, basketorder, splitorder, modifyorder,
cancelorder, cancelallorder, closeposition, orderstatus, openposition,
placegttorder, modifygttorder, cancelgttorder, gttorderbook, funds, margin,
orderbook, tradebook, positionbook, holdings, quotes, multiquotes, depth,
history, intervals, symbol, search, expiry, instruments, holidays, timings,
optionsymbol, optionchain, optiongreeks, syntheticfuture, analyzerstatus,
analyzertoggle, telegram, whatsapp, strategylist, strategystatus,
strategystart, strategystop, strategycloseall, strategycloseleg, strategyruns,
strategyorders, strategyevents, connect, disconnect, subscribe_/unsubscribe_
ltp, quote, depth, orders, get_ltp, get_quotes, get_depth, get_orders.

```python
from openalgo import api, ta
client = api(api_key=KEY, host="http://127.0.0.1:5000", ws_url="ws://127.0.0.1:8765")

client.quotes(symbol="RELIANCE", exchange="NSE")                  # data: open high low ltp ask bid prev_close volume
df = client.history(symbol="SBIN", exchange="NSE", interval="5m",
                    start_date="2026-10-01", end_date="2026-10-16")  # pandas DataFrame, IST tz-aware index
client.intervals()                                                # broker-specific, e.g. 1m 3m 5m 10m 15m 30m 1h D
client.placeorder(strategy="Python", symbol="INFY", exchange="NSE",
                  action="BUY", quantity=1, price_type="MARKET", product="MIS")
client.optionsorder(strategy="Opt", underlying="NIFTY", exchange="NSE_INDEX",
                    expiry_date="25AUG26", offset="ATM", option_type="CE",
                    action="BUY", quantity=65, price_type="MARKET", product="NRML")
client.optionchain(underlying="NIFTY", exchange="NSE_INDEX", expiry_date="25AUG26", strike_count=10)
client.analyzerstatus(); client.analyzertoggle(mode=True)          # Sandbox on
```

Response notes: `openposition` returns quantity as a signed string;
`funds`/`positionbook` values are strings; `history` and `instruments` return
DataFrames; `expiry` returns `25-AUG-26` style dates while inputs use `25AUG26`.
Missing in 2.0.5: no `ping` and no `multioptiongreeks` method (call REST).
Strategy webhook class: `from openalgo import Strategy; Strategy(host_url,
webhook_token='oaws_...')` with `.start(mode)`, `.stop()`, `.long_entry()`,
`.long_exit()`, `.short_entry()`, `.short_exit()`; check `result`
(`ok`, `rejected_dedupe`, `rejected_cooling_off`, `rejected_live_disabled`,
`rejected_invalid_action`).

Running a script on the box:
`uv run --env-file /workspace/pyenv/.env python script.py` with
`os.environ["OPENALGO_API_KEY"]` and `OPENALGO_HOST`.

## 8. WebSocket protocol

- Connect `ws://127.0.0.1:8765`, first message
  `{"action": "authenticate", "api_key": "<key>"}`.
- Subscribe: `{"action": "subscribe", "symbols": [{"symbol": "RELIANCE",
  "exchange": "NSE"}], "mode": "LTP"}`; modes `1/LTP`, `2/Quote`, `3/Depth`
  (case-insensitive); Depth takes `"depth": 5|20|30|50` as the broker allows.
  Per-symbol `mode` wins over top-level; neither defaults to Quote.
- Messages `type: "market_data"` with `symbol, exchange, mode, broker, data`:
  LTP `{ltp, timestamp}`; Quote adds `change, change_percent, volume, open,
  high, low, close, last_trade_quantity, avg_trade_price`; Depth
  `depth: {buy: [{price, quantity, orders}], sell: [...]}`. Timestamps epoch ms.
- Acks: `type: subscribe|unsubscribe`, `status` success or partial, per-symbol
  results; unsubscribe takes optional `request_id`.
- Order updates: `{"action": "subscribe_orders"}` -> `type: "order_update"`
  with `orderid, symbol, exchange, action, quantity, price, trigger_price,
  pricetype, product, order_status, filled_quantity, pending_quantity,
  average_price, rejection_reason, mode` (`live` or `analyze`). Push feeds for
  Zerodha, Dhan, Fyers, Upstox, AliceBlue, Definedge, IndMoney, Angel One,
  Nubra, Arrow, IIFL Capital, Kotak; Groww is polled (`ORDER_POLL_INTERVAL`).
- Server pings every 20 s (`WS_PING_INTERVAL`, `WS_PING_TIMEOUT`);
  unauthenticated sockets closed after `WS_AUTH_GRACE_SECONDS` (15). After any
  reconnect the client must authenticate and subscribe again.
- SDK: `client.connect()`, `subscribe_ltp(instruments, on_data_received=cb)`,
  `subscribe_orders(on_order_update=cb)`, `disconnect()`; `verbose=False|True|2`
  on `api()` controls logging.

## 9. Symbols and exchanges

Indian rules (`docs/prompt/symbol-format.md`):

- Uppercase, no separators; `(symbol, exchange)` identifies the contract.
- Equity: base symbol only (`INFY`, `SBIN`); broker `NHPC-EQ` becomes `NHPC`.
- Futures: `[Base][DDMMMYY]FUT` - `BANKNIFTY24APR24FUT`, `SENSEX24APR24FUT`
  (BFO), `USDINR10MAY24FUT` (CDS), `CRUDEOILM20MAY24FUT` (MCX).
- Options: `[Base][DDMMMYY][Strike][CE|PE]` - `NIFTY28MAR2420800CE`,
  `VEDL25APR24292.5CE` (decimal strike kept, trailing zeros dropped).
- NCO (NSE commodities, Zerodha): doc examples `ALUMINI26MAYFUT`,
  `COPPER26MAY1195CE` have no day; confirm with `search`/`symbol`.
- Index symbols are quote-only: `NSE_INDEX` (NIFTY, BANKNIFTY, FINNIFTY,
  MIDCPNIFTY, NIFTYNXT50, INDIAVIX, ...), `BSE_INDEX` (SENSEX, BANKEX, ...),
  `MCX_INDEX` (MCXBULLDEX, ...), `GLOBAL_INDEX` (Zerodha: US30, US500,
  GIFTNIFTY, ...).
- Option helpers (`optionsorder`, `optionchain`, `optionsymbol`,
  `syntheticfuture`) take the underlying with its index exchange (`NIFTY` +
  `NSE_INDEX`, `SENSEX` + `BSE_INDEX`); the contract resolves on NFO/BFO. MCX
  underlyings use MCX.

| Exchange | Segment |
| --- | --- |
| NSE, BSE | Equity |
| NFO, BFO | NSE, BSE F&O |
| CDS, BCD | NSE, BSE currency |
| MCX | Commodity F&O |
| NCDEX | Commodity (in order constants and Flow) |
| NCO | NSE commodities F&O (Zerodha) |
| NSE_INDEX, BSE_INDEX, MCX_INDEX, GLOBAL_INDEX | Indices, quote only |
| CRYPTO | Crypto (Delta Exchange; venue in `brexchange`) |

Crypto (`docs/prompt/crypto-symbol-format.md`): perpetual `BTCUSDFUT`
(`instrumenttype PERPFUT`, empty expiry; some comments still say `BTCUSD.P`);
dated future `BTC28FEB25FUT`; option `BTC28FEB2562000CE` (turbo and synthetic
map to CE/PE); spot `BTCINR`, `ETHUSDT`; MOVE, IRS, SPREAD, COMBO stay native.
Products are broker-declared; CNC/NRML/MIS do not apply. Price types MARKET,
LIMIT, SL, SL-M plus venue flags (`post_only`, `reduce_only`, IOC/FOK/GTC).
Strike and tick fields are Float today; do not rely on them for exact math.

Master contract (`SymToken`): `symbol, brsymbol, name, exchange, brexchange,
token, expiry, strike, lotsize, instrumenttype, tick_size` (+ `freeze_qty` in
API). Downloaded after each broker login.

## 10. Order constants, lot sizes, quantity units

- Product: `CNC` (delivery), `NRML` (F&O carry), `MIS` (intraday). GTT: CNC/NRML.
- Price type: `MARKET`, `LIMIT`, `SL`, `SL-M`. Action: `BUY`, `SELL`.
- Offsets: `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50`; option type `CE`/`PE`.
- Order status (lowercase): `open`, `trigger pending`, `complete`, `rejected`,
  `cancelled`, plus broker extras like `expired`.
- Lot sizes (`LotSize.md`, Apr-Jun 2026): NIFTY 65, BANKNIFTY 30, FINNIFTY 60,
  MIDCPNIFTY 120, NIFTYNXT50 25, RELIANCE 500, SBIN 750, INFY 400, TCS 175,
  HDFCBANK 550, ICICIBANK 700. The master contract (`client.symbol(...)
  ["data"]["lotsize"]`) is the source of truth.
- Units: `placeorder`, `basketorder`, `splitorder` take shares/units; SDK
  `optionsorder`/`optionsmultiorder` examples use units; Flow options nodes take
  lots; OpenScript F&O strategies state qty in units (multiple of lot size).

## 11. `openalgo.ta` indicators

`from openalgo import ta`; 127 public names; Rust core, no JIT warm-up. Inputs:
NumPy array, pandas Series or list; output matches the input type; multi-output
returns a tuple. Full signatures: `/workspace/reference/openalgo-indicators.md`
and `docs/prompt/indicators/`.

| Category | Functions |
| --- | --- |
| Trend (20) | sma, ema, wma, dema, tema, hma, vwma, alma, kama, zlema, t3, frama, trima, mcginley, vidya, alligator, ma_envelopes, supertrend, ichimoku, ckstop |
| Momentum (15) | rsi, macd, stochastic, cci, williams_r, bop, elderray, fisher, crsi, mom, apo, rocp, rocr, rocr100, stochf |
| Volatility (15) | atr, bbands, keltner, donchian, chaikin, natr, ultimate_oscillator, true_range, massindex, bbpercent, bbwidth, chandelier_exit, hv, ulcerindex, starc |
| Volume (17) | obv, obv_smoothed, vwap, mfi, adl, cmf, emv, force_index, nvi, nvi_with_ema, pvi, pvi_with_signal, volosc, vroc, kvo, pvt, rvol |
| Oscillators (19 unique) | roc, cmo, trix, uo_oscillator, awesome_oscillator, accelerator_oscillator, ppo, po, dpo, aroon_oscillator, stochrsi, rvi, cho, chop, kst, tsi, vi, stc, gator_oscillator, coppock |
| Statistical (11) | linreg, lrslope, correlation, beta, variance, tsf, median, median_bands, mode, linregangle, linregintercept |
| Hybrid (11) | adx, aroon, pivot_points, psar, dmi, fractals, rwi, plus_dm, minus_dm, dx, adxr |
| Utility (19) | crossover, crossunder, cross, highest, lowest, change, roc, stdev, exrem, flip, valuewhen, rising, falling, midpoint, midprice, medprice, typprice, wclprice, avgprice |

Common signatures: `rsi(data, period=14)`; `macd(data, fast_period=12,
slow_period=26, signal_period=9)` -> (macd, signal, hist); `bbands(data,
period=20, std_dev=2.0)` -> (upper, middle, lower); `atr(high, low, close,
period=14)`; `supertrend(high, low, close, period=10, multiplier=3.0)` ->
(line, direction); `adx(high, low, close, period=14)` -> (+DI, -DI, ADX);
`stochastic(high, low, close, k_period=14, smooth_k=3, d_period=3)`.

Gotchas:
- `vwap`: package order is `vwap(high, low, close, volume, anchor='Session',
  source='hlc3', ...)`, docs show `source` before `anchor`. Always pass
  `source=` and `anchor=` by keyword.
- `sma/ema/wma/dema/tema/hma/zlema/vwma` have no default period.
- `adx` returns three values, ADX last. `pivot_points` returns
  `(pivot, r1, s1, r2, s2, r3, s3)`.
- `frama(high, low, period)` takes high and low, not close.
- `supertrend` direction: -1 = uptrend, 1 = downtrend. `psar` returns SAR only.
- `rvi` is the Relative Vigor Index (OHLC in). Relative Volatility Index is not
  on `ta`.
- The 13 signal helpers (crossover, crossunder, cross, highest, lowest, change,
  roc, stdev, rising, falling, exrem, flip, valuewhen) always return NumPy
  arrays: index with `[-1]` or wrap in `pd.Series(x, index=df.index)`.
- `exrem`/`flip` keywords are `primary`, `secondary`; `valuewhen` keywords are
  `expr`, `array`, `n` (docs' descriptive names are not the real keywords).
- `aroon_oscillator` defaults to period 14, `aroon` to 25.
- Warm-up values are NaN.
- Flow's indicator node cannot use crossover/crossunder/cross, correlation,
  beta, exrem, flip, valuewhen, and (per its reference) median_bands,
  ulcerindex, vi.

## 12. OpenScript essentials

- OpenAlgo's own scripting language: write a study or strategy once, plot it
  on `/trading`, backtest in the browser (up to 100,000 bars), deploy to
  Sandbox then Live from the Strategies panel. Compiles to a versioned data
  program (no `eval`). Libraries: `npm install openalgo-script`,
  `pip install openscript` (runner). Stored under `strategies/openscript/` as
  `<name>.oscript` plus `.oscript.program.json`.
- File runs once per bar, oldest to newest. Structure: `version 1`, one
  `study(...)` or `strategy(...)`, optional `limits(...)`, statements.
- Indentation (spaces) forms blocks; no semicolons; `//` comments only;
  `and or not`; `cond ? a : b`; history `close[1]`; `/` by zero gives `none`;
  no `**`, use `pow()`; no implicit string conversion, use `text()`; write
  `not (close > open)`.
- `none` propagates and plots as a gap; `orElse()`, `isNone()`.
- Built-ins bare: `ema`, `sma`, `rsi`, `atr`, `crossUp`, `crossDown`,
  `highest`, `bollinger` -> [basis, upper, lower], `macd` -> [macd, signal,
  hist]. Stateful calls at top level (inside `if` warns OS8001).
- `var x = init` persists across bars; no shadowing (OS2002); `fn f(a, b = 20)
  => expr`; no recursion.
- Output: `plot()`, `fill()`, `level()`, `signal()`, `alert()`; `input()` at
  top level only. Strategies add `buy()`, `sell()`, `close()`, `pos.*`.
- `strategy()` options: `capital` 100000, `qty` 1, `qtyType`, `pyramiding` 1,
  `fillOn` nextOpen or close, `slippage`, `commission`, `commissionType`,
  `product` intraday or overnight.
- The server refuses to deploy scripts that call `exit()` or `order.bracket()`,
  read `session.*`/`date.*`, size in non-units, use `req.timeframe()` or
  `req.symbol()`, or draw. `kind="time"` inputs are read as UTC in backtest.

```
version 1
strategy("EMA cross", overlay = true, qty = 1)
fast = ema(close, 9)
slow = ema(close, 21)
if crossUp(fast, slow) and pos.isFlat
    buy()
if crossDown(fast, slow) and pos.isLong
    close()
```

Use the `openscript` skill to write, validate and install scripts.

## 13. openalgo-charts and chart indicators

- npm `openalgo-charts` (2.6.6 installed on the box): HTML5 canvas library,
  zero runtime dependencies, Apache-2.0, IST default timezone. 112 indicators,
  87 drawing tools, 13 chart types (candles, Heikin Ashi, Renko, Range, Point
  and Figure, Kagi, Line Break, ...), footprint, volume profile, TPO, bar
  replay, trading on chart (order tickets, position lines, depth ladder).
- Lazy modules: core, `/indicators`, `/draw`, `/widget` (full terminal via
  `createWidget`), `/profile`, `/transform`, `/trade`, `/webgl`, `/workspace`.
- Setup: sized container, `feed.getBars` returning
  `{time, open, high, low, close, volume}`, live updates via `subscribeBars`.
- Custom chart indicators: plain JavaScript descriptors in
  `strategies/indicators/*.js`, loaded at runtime (never bundled, not
  sandboxed, can override the 112 built-ins). Chart indicator ids are
  kebab-case (`supertrend`, `bollinger`, `cpr`, ...) and are a separate set
  from `openalgo.ta` and from OpenScript. Use the `chart-indicator` skill; it
  validates against the real library before installing.

## 14. Flow JSON essentials

- Import shape: exactly `{"name": "...", "nodes": [...], "edges": [...]}`; each
  node `{id, type, position: {x, y}, data: {}}`; no fences, comments or
  trailing commas.
- Node types (copy verbatim): Triggers `start, priceAlert, webhookTrigger,
  orderUpdateTrigger`; Actions `placeOrder, smartOrder, optionsOrder,
  optionsMultiOrder, basketOrder, splitOrder, modifyOrder, cancelOrder,
  cancelAllOrders, closePositions`; Conditions `positionCheck, fundCheck,
  priceCondition, varCondition, timeWindow, timeCondition, andGate, orGate,
  notGate`; Data `getQuote, multiQuotes, getDepth, history, indicator,
  priorPeriodOhlc, barOffset, strategyPnl, openPosition, getOrderStatus,
  orderBook, tradeBook, positionBook, holdings, funds, margin, symbol,
  optionSymbol, expiry, intervals, optionChain, syntheticFuture, holidays,
  timings, calendar`; Streaming `subscribeLtp, subscribeQuote, subscribeDepth,
  unsubscribe`; Utility `log, telegramAlert, whatsappAlert, variable,
  mathExpression, httpRequest, delay, waitUntil, group`.
- Variables `{{name.field}}`, webhook values `{{webhook.*}}`; condition nodes
  branch by `sourceHandle`; AND/OR gates need `targetHandle: "input-N"`.
- Pitfalls: indicator `params` is a JSON string; history nodes capped at 200
  bars; `interval` is free text; a failed node stops its branch; one-shot
  triggers deactivate the workflow; webhook URL exists only after save;
  options nodes take lots.
- Use the `flow-builder` skill: `uv run python
  .claude/skills/flow-builder/validate.py wf.json`.

## 15. Integrations

- **TradingView, ChartInk, GoCharting, Amibroker**: send JSON to
  `/api/v1/placeorder` (or smart/options endpoints) with the API key in the
  body; they cannot set headers. Webhooks need a public HTTPS URL (domain, or a
  tunnel such as `cloudflared tunnel --url http://localhost:5000` for testing);
  ChartInk needs a premium account and has its own strategy pages
  (`/chartink`). The box has no public inbound URL by default.
- **MCP**: local stdio server `mcp/mcpserver.py` (Claude Desktop, Cursor,
  Windsurf); remote MCP over OAuth via `blueprints/mcp_http.py` and
  `mcp_oauth.py`; tools in `docs/mcp-tool-reference.md`.
- **Telegram**: bot alerts for orders, positions, P&L; commands `/positions`,
  `/orders`, `/pnl`, `/status`, `/help`; SDK `client.telegram(username=...,
  message=...)`.
- **WhatsApp**: pair the device at `/whatsapp`; SDK `client.whatsapp(...)`.
- Other clients: Excel, Google Sheets, N8N, MetaTrader, Node, Go, Java, .NET,
  Rust SDKs; OpenAlgo CLI (Go).

## 16. The other `.claude` skills

| Skill | Use when |
| --- | --- |
| `chart-indicator` | Writing or porting a JavaScript indicator for `/trading`; validates with `validate.mjs` then `--install` |
| `openscript` | Writing or debugging an `.oscript` study or strategy; compiles and installs both files |
| `flow-builder` | Building or editing `/flow` workflow JSON; validates against the real importer |
| `broker-integration` | Adding or modifying a broker plugin (auth, orders, symbols, streaming) |
| `fd-audit` | After changes touching DB, WebSockets, threads, subprocesses, files or sockets |
| `security-audit` | Monthly or pre-release read-only audit (xlsx report) |
| `verify` | Before claiming a fix or control works: execute, do not reason |
| `version-bump` | Platform release (`utils/version.py` + `pyproject.toml`) vs SDK pin (dependency lists); never confuse the two |
| `grokbot-setup` | This skill: running OpenAlgo inside Grok Bot |

## 17. CLAUDE.md invariants that matter to a bot

- uv for everything (`uv run`, `uv sync`, `uv add`); Python 3.12+.
- Single user per deployment; server access equals full control.
- SEBI static IP mandate (April 1, 2026) for API orders; Delta Exchange
  enforces the same. Indian broker tokens expire about 3:00 AM IST.
- Trader-facing text: cause and next action, no status codes; "Live" and
  "Sandbox" only; no "arm/armed"; no icons or emojis anywhere.
- Docs live once in `docs/`; edit the source, never copy it elsewhere.
- Risk rules only in `services/risk/`; logging via `get_logger(__name__)`;
  ORM only; schema changes need an idempotent `upgrade/` migration registered
  in `migrate_all.py`.
- ZeroMQ: proxy binds, publishers connect, port never drifts; keep 5555 and
  8765 on 127.0.0.1.
- Production must stay correct under eventlet; no asyncio in request code.
- Conventional Commits; a changelog entry ships with every publish.
- Upgrades: `git pull`, `uv sync`, `cd upgrade && uv run migrate_all.py`; keep
  `.env` (never copy `.sample.env` over it); compare `ENV_CONFIG_VERSION`.

## 18. Known conflicts between docs and code

| Topic | Docs say | Package or code says | Do this |
| --- | --- | --- | --- |
| `ta.vwap` argument order | `source` then `anchor` | `anchor` then `source` | Pass both by keyword |
| `optionsorder` price type | `pricetype=` | SDK keyword `price_type=` | Use `price_type` in the SDK |
| NIFTY lot size | SDK examples use 75 | `LotSize.md` 65 (Apr-Jun 2026) | Read `lotsize` from `client.symbol()` |
| `ta` return types | some pages say ndarray (e.g. WMA) | Series in gives Series out | Trust runtime; only the 13 helpers return ndarray |
| `exrem`/`flip`/`valuewhen` keywords | `primary_signals`, `condition_array`, ... | `primary`, `secondary`, `expr`, `array` | Positional or package names |
| `obv_smoothed` BB tuple | (upper, middle, lower) | docstring says (obv, upper, lower) | Runtime confirms docs order |
| Flow indicator node | `median_bands`, `ulcerindex`, `vi` unusable | `ta` versions compute in Python | Avoid them in Flow; fine in Python |
| `multioptiongreeks`, `ping` | REST endpoints exist | No SDK 2.0.5 method | Call REST |
| `close_all_positions` | used in userguide 20 examples | not in SDK 2.0.5 (method is `closeposition`) | Use `closeposition(strategy=...)` |
| `API_RATE_LIMIT` default | `docs/api/README.md`: 50 per second | `.sample.env`: 100 per second | Read the user's `.env` |
| NCO symbols | DDMMMYY rule | examples `ALUMINI26MAYFUT` have no day | Confirm with `search`/`symbol` |
| Crypto perpetual suffix | some comments `BTCUSD.P` | served form `BTCUSDFUT` | Use `...FUT` |
| `/tools` count | README 12 | CLAUDE.md, docs site 18 | 18 (registry) |
| Flow node count | docs.openalgo.in 61 | openalgo.in 53 | Use the type list in section 14 |
| Broker count | README 35 + Delta | docs 34 + Dhan sandbox + Delta; `VALID_BROKERS` 37 codes | Use [brokers.md](brokers.md) |
| Login type labels | `BrokerSelect.tsx` marks Groww, AliceBlue, Zebu, Shoonya as `totp` | backend flow differs | Follow [brokers.md](brokers.md) |
| Placeholder secrets | `.sample.env`: auto-rotated on first run | install scripts rotate too | Set explicitly before `/setup` anyway |
