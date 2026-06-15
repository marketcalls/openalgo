# OpenAlgo Discovery Map

Phase 1 discovery map. This file documents behavior found in the current source tree only. It does not use secrets from `.env`.

## Discovery Summary

- Backend runtime: Flask app with Flask-RESTX, Flask-SocketIO, SQLAlchemy, APScheduler, DuckDB, ZeroMQ, and a separate asyncio WebSocket proxy. Entry point is `app.py:134`.
- Frontend runtime: React 19, Vite 8, TypeScript 5.9, served from `frontend/dist` by `blueprints/react_app.py` when available. React routes are registered before the REST/UI blueprints at `app.py:236`.
- API surface documented here: 57 RESTX `/api/v1` endpoints, 452 Flask blueprint routes, and 1 app-level route. Total documented HTTP endpoints: 510.
- Broker plugins: 33 broker plugin directories with `plugin.json`, matching `VALID_BROKERS` in `.sample.env:22`.
- Primary data stores: main `openalgo.db`, traffic `logs.db`, latency `latency.db`, health `health.db`, sandbox `sandbox.db`, and Historify `historify.duckdb`, configured in `.sample.env:54` through `.sample.env:61`.
- Security baseline: `APP_KEY` and `API_KEY_PEPPER` are required and placeholder-rotated, API keys are Argon2-hashed plus encrypted for retrieval, broker tokens are Fernet-encrypted, CSRF is enabled for session routes, and `/api/v1` is CSRF-exempt for external callers. Sources: `.sample.env:24`, `database/auth_db.py:36`, `database/auth_db.py:761`, `app.py:171`, `app.py:248`.

## Entry Points And Runtime

- Environment validation runs before the rest of the app imports by calling `load_and_check_env_variables()` at `app.py:1`.
- `create_app()` initializes Flask, SocketIO, the in-process EventBus subscribers, CSRF, rate limiting, CORS, CSP, and Socket.IO error handling at `app.py:134` through `app.py:164`.
- `APP_KEY` must be present and at least 32 characters before the app can start at `app.py:171` through `app.py:188`.
- Session cookie security follows `HOST_SERVER`: HTTPS hosts get secure cookies, local HTTP does not. Source: `app.py:189` through `app.py:224`.
- React is registered first when `frontend/dist` exists, before the REST and UI blueprints. Source: `app.py:236` through `app.py:245`.
- `/api/v1` is CSRF-exempt after RESTX registration at `app.py:245` through `app.py:248`.
- Remote MCP routes are registered only when `MCP_HTTP_ENABLED=True`; debug mode is refused and `MCP_PUBLIC_URL` is required. Source: `app.py:303` through `app.py:347`.
- Specific webhook and broker callback routes are CSRF-exempt after blueprint registration. Source: `app.py:388` through `app.py:411`.
- Requests wait up to 30 seconds for DB initialization through `app.db_ready` at `app.py:429` through `app.py:443`.
- Session expiry checks run before session-protected requests and revoke broker tokens on expiry. Source: `app.py:445` through `app.py:490`.
- The direct `/api/config/host` route returns `host_server` and `is_localhost`. Source: `app.py:578` through `app.py:590`.
- `setup_environment()` initializes broker auth discovery, broker capabilities, database tables, schedulers, sandbox/analyzer workers, scalping monitor, and bot autostart paths. Source: `app.py:595` through `app.py:824`.
- SQLAlchemy scoped sessions are removed on teardown for many database modules to prevent file descriptor leaks. Source: `app.py:855` through `app.py:897`.
- The WebSocket proxy is started by the app unless Docker or a standalone proxy mode is detected. Under eventlet/gunicorn it is a child process, and under the development server it is a real OS thread. Sources: `app.py:899` through `app.py:918`, `websocket_proxy/app_integration.py:158`.
- Direct Flask startup uses `FLASK_HOST_IP`, `FLASK_PORT`, and `FLASK_DEBUG`; debug mode on non-loopback is refused unless `FLASK_DEBUG_ALLOW_EXTERNAL` is true. Source: `app.py:921` through `app.py:1027`.

## Setup And Versions

- Python requires `>=3.12`; the project version is `2.0.1.3`. Source: `pyproject.toml:1` through `pyproject.toml:5`.
- Key backend packages include Flask `3.1.3`, Flask-RESTX `1.3.2`, Flask-SocketIO `5.6.1`, httpx `0.28.1`, websockets `15.0.1`, openalgo SDK `2.0.1`, and pytest `9.0.3`. Source: `pyproject.toml:37` through `pyproject.toml:144`.
- Frontend requires Node `>=20.20.0 || >=22.22.0 || >=24.13.0`. Source: `frontend/package.json:6`.
- Frontend scripts include Vite dev/build, Vitest, and Playwright e2e. Source: `frontend/package.json:9` through `frontend/package.json:24`.
- Frontend dependencies include React `^19.2.3`, React Router `^7.15.0`, TanStack Query, XYFlow, Plotly, lightweight-charts, Socket.IO client, Tailwind CSS 4, and Zustand. Source: `frontend/package.json:26` through `frontend/package.json:71`.

## Data Stores

- Main SQLAlchemy modules use `DATABASE_URL`, defaulting to `sqlite:///db/openalgo.db` in `.sample.env:54`.
- Traffic logs use `LOGS_DATABASE_URL`, default `sqlite:///db/logs.db`; the traffic database also stores IP ban state and caches ban verdicts for 60 seconds. Sources: `.sample.env:58`, `database/traffic_db.py:28` through `database/traffic_db.py:58`.
- Latency logs use `LATENCY_DATABASE_URL`, default `sqlite:///db/latency.db`. Source: `.sample.env:57`.
- Health metrics use `HEALTH_DATABASE_URL`, default `sqlite:///db/health.db`, and store FD, memory, DB, WebSocket, and thread metrics. Sources: `.sample.env:59`, `database/health_db.py:1` through `database/health_db.py:80`.
- Sandbox/analyzer trading state uses `SANDBOX_DATABASE_URL`, default `sqlite:///db/sandbox.db`. Source: `.sample.env:60`, `database/sandbox_db.py:35` through `database/sandbox_db.py:49`.
- Historify uses a DuckDB file for columnar historical data. The sample env names `HISTORIFY_DATABASE_URL` at `.sample.env:61`, while the implementation reads `HISTORIFY_DATABASE_PATH` at `database/historify_db.py:27`. This mismatch is in the review queue.
- SQLite engines use `NullPool`, not `StaticPool`, to prevent long-lived file descriptors and shared-cursor corruption. Source: `database/engine_factory.py:1` through `database/engine_factory.py:58`.
- Historify creates `market_data`, `watchlist`, `data_catalog`, download job tables, symbol metadata, schedules, schedule executions, and indexes. Source: `database/historify_db.py:94` through `database/historify_db.py:260`.

## Security And Auth

- `.sample.env` documents placeholder rotation for `APP_KEY`, `API_KEY_PEPPER`, and `FERNET_SALT`; these values must not be committed after rotation. Source: `.sample.env:24` through `.sample.env:52`.
- `API_KEY_PEPPER` is required at import time and must be at least 32 characters. Source: `database/auth_db.py:36` through `database/auth_db.py:52`.
- Broker auth tokens and feed tokens are encrypted with Fernet derived from `API_KEY_PEPPER` and per-install `FERNET_SALT`. Source: `database/auth_db.py:55` through `database/auth_db.py:99`.
- API keys are Argon2-hashed with the pepper and also encrypted so the UI and internal integrations can retrieve the plaintext key when needed. Source: `database/auth_db.py:761` through `database/auth_db.py:803`.
- API key verification caches valid and invalid outcomes, uses a SHA256 cache key, and tracks invalid attempts. Source: `database/auth_db.py:834` through `database/auth_db.py:909`.
- Broker name lookup verifies the API key and reads the active broker auth row. Source: `database/auth_db.py:917` through `database/auth_db.py:939`.
- Order mode is stored per user API key and supports `auto` and `semi_auto`. Source: `database/auth_db.py:1011` through `database/auth_db.py:1067`.
- Flask-Limiter uses moving-window limits with memory storage. Source: `limiter.py:1` through `limiter.py:7`.
- Default rate limits in `.sample.env` include login, reset, API, order, smart order, webhook, and strategy limits. Source: `.sample.env:175` through `.sample.env:185`.
- CORS is environment-controlled and applies to `/api/*`. Source: `cors.py:8` through `cors.py:56`.
- CSP and hardening headers are environment-controlled and set `X-Frame-Options`, `X-Content-Type-Options`, `X-XSS-Protection`, Referrer-Policy, and Permissions-Policy. Source: `csp.py:9` through `csp.py:186`.
- IP middleware checks banned IPs before Flask when initialized and only trusts forwarded headers when `TRUST_PROXY_HEADERS` is true. Sources: `utils/security_middleware.py:20` through `utils/security_middleware.py:132`, `utils/ip_helper.py:9` through `utils/ip_helper.py:135`.
- Session expiry defaults to 03:00 IST and can be disabled for crypto. Source: `.sample.env:189` through `.sample.env:197`.
- Master contract smart download cutoffs use IST for Indian brokers and UTC for crypto brokers. Source: `utils/auth_utils.py:35` through `utils/auth_utils.py:136`.

## RESTX API V1

The RESTX API blueprint has prefix `/api/v1` at `restx_api/__init__.py:4` through `restx_api/__init__.py:11`. Namespaces are registered at `restx_api/__init__.py:60` through `restx_api/__init__.py:105`.

### RESTX Endpoint Inventory

| # | Method | Path | Source |
|---|---|---|---|
| 1 | POST | `/api/v1/analyzer` | `restx_api/analyzer.py:28` |
| 2 | POST | `/api/v1/analyzer/toggle` | `restx_api/analyzer.py:63` |
| 3 | POST | `/api/v1/basketorder` | `restx_api/basket_order.py:29` |
| 4 | POST | `/api/v1/cancelallorder` | `restx_api/cancel_all_order.py:28` |
| 5 | POST | `/api/v1/cancelgttorder` | `restx_api/cancel_gtt_order.py:25` |
| 6 | POST | `/api/v1/cancelorder` | `restx_api/cancel_order.py:28` |
| 7 | GET | `/api/v1/chart` | `restx_api/chart_api.py:28` |
| 8 | POST | `/api/v1/chart` | `restx_api/chart_api.py:56` |
| 9 | POST | `/api/v1/closeposition` | `restx_api/close_position.py:28` |
| 10 | POST | `/api/v1/depth` | `restx_api/depth.py:26` |
| 11 | POST | `/api/v1/expiry` | `restx_api/expiry.py:26` |
| 12 | POST | `/api/v1/funds` | `restx_api/funds.py:27` |
| 13 | POST | `/api/v1/gttorderbook` | `restx_api/gtt_orderbook.py:22` |
| 14 | POST | `/api/v1/history` | `restx_api/history.py:26` |
| 15 | POST | `/api/v1/holdings` | `restx_api/holdings.py:26` |
| 16 | GET | `/api/v1/instruments` | `restx_api/instruments.py:39` |
| 17 | POST | `/api/v1/intervals` | `restx_api/intervals.py:26` |
| 18 | POST | `/api/v1/margin` | `restx_api/margin.py:27` |
| 19 | POST | `/api/v1/market/holidays` | `restx_api/market_holidays.py:26` |
| 20 | POST | `/api/v1/market/timings` | `restx_api/market_timings.py:26` |
| 21 | POST | `/api/v1/modifygttorder` | `restx_api/modify_gtt_order.py:25` |
| 22 | POST | `/api/v1/modifyorder` | `restx_api/modify_order.py:28` |
| 23 | POST | `/api/v1/multioptiongreeks` | `restx_api/multi_option_greeks.py:28` |
| 24 | POST | `/api/v1/multiquotes` | `restx_api/multiquotes.py:26` |
| 25 | POST | `/api/v1/openposition` | `restx_api/openposition.py:28` |
| 26 | POST | `/api/v1/optionchain` | `restx_api/option_chain.py:86` |
| 27 | POST | `/api/v1/optiongreeks` | `restx_api/option_greeks.py:28` |
| 28 | POST | `/api/v1/optionsymbol` | `restx_api/option_symbol.py:57` |
| 29 | POST | `/api/v1/optionsmultiorder` | `restx_api/options_multiorder.py:129` |
| 30 | POST | `/api/v1/optionsorder` | `restx_api/options_order.py:104` |
| 31 | POST | `/api/v1/orderbook` | `restx_api/orderbook.py:26` |
| 32 | POST | `/api/v1/orderstatus` | `restx_api/orderstatus.py:28` |
| 33 | POST | `/api/v1/ping` | `restx_api/ping.py:26` |
| 34 | POST | `/api/v1/placegttorder` | `restx_api/place_gtt_order.py:25` |
| 35 | POST | `/api/v1/placeorder` | `restx_api/place_order.py:25` |
| 36 | POST | `/api/v1/placesmartorder` | `restx_api/place_smart_order.py:28` |
| 37 | POST | `/api/v1/pnl/symbols` | `restx_api/pnl_symbols.py:26` |
| 38 | POST | `/api/v1/positionbook` | `restx_api/positionbook.py:26` |
| 39 | POST | `/api/v1/quotes` | `restx_api/quotes.py:26` |
| 40 | POST | `/api/v1/search` | `restx_api/search.py:26` |
| 41 | POST | `/api/v1/splitorder` | `restx_api/split_order.py:28` |
| 42 | POST | `/api/v1/symbol` | `restx_api/symbol.py:26` |
| 43 | POST | `/api/v1/syntheticfuture` | `restx_api/synthetic_future.py:58` |
| 44 | GET | `/api/v1/telegram/config` | `restx_api/telegram_bot.py:110` |
| 45 | POST | `/api/v1/telegram/config` | `restx_api/telegram_bot.py:141` |
| 46 | POST | `/api/v1/telegram/start` | `restx_api/telegram_bot.py:198` |
| 47 | POST | `/api/v1/telegram/stop` | `restx_api/telegram_bot.py:251` |
| 48 | POST | `/api/v1/telegram/webhook` | `restx_api/telegram_bot.py:300` |
| 49 | GET | `/api/v1/telegram/users` | `restx_api/telegram_bot.py:353` |
| 50 | POST | `/api/v1/telegram/broadcast` | `restx_api/telegram_bot.py:390` |
| 51 | POST | `/api/v1/telegram/notify` | `restx_api/telegram_bot.py:450` |
| 52 | GET | `/api/v1/telegram/stats` | `restx_api/telegram_bot.py:539` |
| 53 | GET | `/api/v1/telegram/preferences` | `restx_api/telegram_bot.py:570` |
| 54 | POST | `/api/v1/telegram/preferences` | `restx_api/telegram_bot.py:599` |
| 55 | GET | `/api/v1/ticker/<string:symbol>` | `restx_api/ticker.py:139` |
| 56 | POST | `/api/v1/tradebook` | `restx_api/tradebook.py:26` |
| 57 | POST | `/api/v1/whatsapp/notify` | `restx_api/whatsapp_bot.py:92` |

### Request Schema Notes

- Regular order fields are validated by `OrderSchema` at `restx_api/schemas.py:22` through `restx_api/schemas.py:52`.
- Smart order fields add `position_size` at `restx_api/schemas.py:55` through `restx_api/schemas.py:84`.
- GTT schema validation supports `SINGLE` and `OCO`; OCO requires stop-loss and target trigger/limit fields and enforces stop-loss trigger below target trigger. Source: `restx_api/schemas.py:356` through `restx_api/schemas.py:425`.
- History supports intervals from seconds through year buckets and supports `source` as `api` or `db`. Source: `restx_api/data_schemas.py:58` through `restx_api/data_schemas.py:99`.
- `MultiOptionGreeksSchema` caps symbols at 50. Source: `restx_api/data_schemas.py:245` through `restx_api/data_schemas.py:257`.
- Valid exchanges, product types, price types, actions, and required fields are centralized in `utils/constants.py:52` through `utils/constants.py:152`.

## Broker Plugins

- Broker capabilities are loaded from every `broker/*/plugin.json` with `supported_exchanges`, `broker_name`, `broker_type`, and `leverage_config`. Source: `utils/plugin_loader.py:17` through `utils/plugin_loader.py:54`.
- Broker auth modules are lazy-loaded from `broker.{broker}.api.auth_api`. Source: `utils/plugin_loader.py:65` through `utils/plugin_loader.py:128`.
- Current broker count is 33. Current `VALID_BROKERS` is `.sample.env:22`.
- The old broker integration guide says 29 brokers at `docs/broker-integration-guide.md:1443`. Current code adds `arrow`, `deltaexchange`, `iiflcapital`, and `rmoney`.
- Live GTT broker modules exist only for Dhan and Zerodha: `broker/dhan/api/gtt_api.py`, `broker/zerodha/api/gtt_api.py`.

### Broker Matrix

| Broker key | Plugin name | Type | Leverage config | Exchanges |
|---|---|---|---|---|
| aliceblue | aliceblue | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| angel | angel | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX, MCX_INDEX |
| arrow | arrow | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| compositedge | compositedge | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| definedge | DefinedGe Securities | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| deltaexchange | deltaexchange | crypto | true | CRYPTO |
| dhan | dhan | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| dhan_sandbox | dhan_sandbox | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| firstock | Firstock | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX |
| fivepaisa | fivepaisa | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fivepaisaxts | 5paisa (XTS) | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| flattrade | Flattrade | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| fyers | fyers | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| groww | groww | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| ibulls | IBulls | IN_stock | false | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| iifl | IIFL | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| iiflcapital | iiflcapital | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| indmoney | indmoney | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| jainamxts | jainamxts | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| kotak | Kotak | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| motilal | motilal | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| mstock | mstock | IN_stock | false | NSE, BSE, NFO, BFO, CDS, NSE_INDEX, BSE_INDEX |
| nubra | nubra | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| paytm | paytm | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| pocketful | pocketful | IN_stock | false | NSE, BSE, NFO, BFO, MCX, NSE_INDEX, BSE_INDEX |
| rmoney | RMoney | IN_stock | false | NSE, BSE, NFO, BFO, NSE_INDEX, BSE_INDEX |
| samco | samco | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| shoonya | Shoonya | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| tradejini | Tradejini | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX |
| upstox | upstox | IN_stock | false | NSE, BSE, NFO, BFO, CDS, BCD, MCX, NSE_INDEX, BSE_INDEX, GLOBAL_INDEX |
| wisdom | Wisdom Capital (XTS) | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX, BSE_INDEX |
| zebu | Zebu | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NSE_INDEX |
| zerodha | zerodha | IN_stock | false | NSE, BSE, NFO, BFO, CDS, MCX, NCO, NSE_INDEX, BSE_INDEX, MCX_INDEX, GLOBAL_INDEX |

## Order Execution, Analyzer Mode, And Action Center

- `placeorder` validates request data, queues to Action Center when eligible in semi-auto mode, resolves broker auth through the API key, and then calls a dynamically imported `broker.{broker}.api.order_api` module. Source: `services/place_order_service.py:26` through `services/place_order_service.py:338`.
- Live order placement publishes `OrderPlacedEvent` on success and `OrderFailedEvent` on validation, module, broker, or exception failure. Source: `services/place_order_service.py:183` through `services/place_order_service.py:257`.
- Analyzer mode sends order placement to `sandbox_place_order` instead of the broker and publishes analyzer-mode events. Source: `services/place_order_service.py:148` through `services/place_order_service.py:181`.
- Smart orders use `place_smartorder_api` in live mode and `sandbox_place_smart_order` in analyzer mode. Source: `services/place_smart_order_service.py:148` through `services/place_smart_order_service.py:341`.
- Basket orders sort BUY orders before SELL orders, run analyzer baskets through sandbox with batched quote prefetch, and run live baskets in concurrent batches of 10 with a one-second delay between batches. Source: `services/basket_order_service.py:184` through `services/basket_order_service.py:370`.
- Split orders cap at 100 child orders, use `ORDER_RATE_LIMIT` as delay in live mode, and prefetch one quote for sandbox split execution. Source: `services/split_order_service.py:23` through `services/split_order_service.py:414`.
- Semi-auto routing sends queueable order types to the Action Center when the user's API key mode is `semi_auto`. Source: `services/order_router_service.py:37` through `services/order_router_service.py:145`.
- Action Center stores pending orders with user ID, API type, serialized order data, status, approval/rejection fields, and broker execution fields. Source: `database/action_center_db.py:46` through `database/action_center_db.py:79`.
- Action Center approval marks a row approved and immediately attempts execution. Source: `blueprints/orders.py:992` through `blueprints/orders.py:1033`.
- Approved pending order execution dispatches to `placeorder`, `smartorder`, `basketorder`, `splitorder`, or `optionsorder`, then updates broker order status if possible. Source: `services/pending_order_execution_service.py:14` through `services/pending_order_execution_service.py:191`.
- Close, cancel, cancel-all, modify, and GTT modify/cancel operations are blocked in semi-auto mode by their service layers unless analyzer mode is enabled. Sources: `services/close_position_service.py:216`, `services/cancel_order_service.py:213`, `services/cancel_all_order_service.py:196`, `services/modify_order_service.py:208`, `services/modify_gtt_order_service.py:124`, `services/cancel_gtt_order_service.py:132`.

## GTT Orders

- GTT place, modify, cancel, and orderbook services import `broker.{broker}.api.gtt_api`; when that module is missing they return 501. Sources: `services/place_gtt_order_service.py:34`, `services/modify_gtt_order_service.py:32`, `services/cancel_gtt_order_service.py:32`, `services/gtt_orderbook_service.py:13`.
- Analyzer mode currently returns 501 with "Sandbox GTT support not yet implemented" for place, modify, cancel, and orderbook. Sources: `services/place_gtt_order_service.py:54`, `services/modify_gtt_order_service.py:51`, `services/cancel_gtt_order_service.py:50`, `services/gtt_orderbook_service.py:21`.
- Place GTT is queueable through Action Center in semi-auto mode. Source: `services/place_gtt_order_service.py:144` through `services/place_gtt_order_service.py:149`.
- Modify GTT and cancel GTT are blocked in semi-auto mode because stale queued actions are unsafe. Sources: `services/modify_gtt_order_service.py:124` through `services/modify_gtt_order_service.py:151`, `services/cancel_gtt_order_service.py:132` through `services/cancel_gtt_order_service.py:152`.
- Sandbox database tables for GTT exist and model active, triggered, cancelled, expired, and rejected parent states, plus pending, triggering, triggered, and cancelled leg states. Source: `database/sandbox_db.py:265` through `database/sandbox_db.py:393`.

## Market Data And History

- Quotes validate exchange and symbol against `VALID_EXCHANGES` and the master contract token cache before calling a broker data module. Source: `services/quotes_service.py:13` through `services/quotes_service.py:37`.
- `multiquotes` validates every item, returns errors for invalid symbols, and falls back to per-symbol quotes when a broker does not support native multiquotes. Source: `services/quotes_service.py:208` through `services/quotes_service.py:324`.
- History broker calls are rate-limited to about 3 requests per second and return `oi` even if the broker dataframe does not include it. Source: `services/history_service.py:15` through `services/history_service.py:138`.
- History `source=db` reads from Historify DuckDB and returns 404 when local data is missing. Source: `services/history_service.py:144` through `services/history_service.py:216`.
- Depth validates the symbol, resolves feed token and broker, and passes broker-specific user ID when supported. Source: `services/depth_service.py:59` through `services/depth_service.py:185`.
- Option symbol service prefers actual strikes from the symbol database and caches strike lists in memory. Source: `services/option_symbol_service.py:49` through `services/option_symbol_service.py:75`, `services/option_symbol_service.py:279` through `services/option_symbol_service.py:360`.
- Option chain maps underlying quote exchange, finds ATM from underlying LTP, selects strikes around ATM, fetches CE/PE quotes through multiquotes, and returns chain rows. Source: `services/option_chain_service.py:219` through `services/option_chain_service.py:503`.
- Crypto derivative support is modeled through `CRYPTO_EXCHANGES`, `CRYPTO_BROKERS`, `INSTRUMENT_PERPFUT`, and canonical option symbol construction. Source: `utils/constants.py:20` through `utils/constants.py:37`.

## WebSocket Streaming

- WebSocket proxy state tracks clients, subscriptions, adapters, user mappings, and an O(1) `subscription_index`. Source: `websocket_proxy/server.py:66` through `websocket_proxy/server.py:82`.
- The proxy connects a ZeroMQ SUB socket to `ZMQ_HOST:ZMQ_PORT` and subscribes to all topics. Source: `websocket_proxy/server.py:109` through `websocket_proxy/server.py:118`.
- WebSocket server uses `WS_MAX_QUEUE`, `WS_PING_INTERVAL`, and `WS_PING_TIMEOUT` and writes stats to `WS_PROXY_STATS_FILE` or `log/ws_proxy_stats.json`. Source: `websocket_proxy/server.py:175` through `websocket_proxy/server.py:197`, `websocket_proxy/server.py:345` through `websocket_proxy/server.py:376`.
- New WebSocket clients must authenticate within `WS_AUTH_GRACE_SECONDS`, default 15 seconds. Source: `websocket_proxy/server.py:542` through `websocket_proxy/server.py:600`.
- Client actions are `authenticate`, `subscribe`, `unsubscribe`, `unsubscribe_all`, `get_broker_info`, `get_supported_brokers`, and `ping`. Source: `websocket_proxy/server.py:691` through `websocket_proxy/server.py:730`.
- Authentication accepts `api_key` or `apikey`, verifies the API key, creates a broker adapter, handles token/cache refresh retries, and returns broker plus supported feature flags. Source: `websocket_proxy/server.py:794` through `websocket_proxy/server.py:1047`.
- Subscription accepts one symbol or a `symbols` array, normalizes mode to `LTP`, `Quote`, or `Depth`, stores depth levels, and returns per-symbol results. Source: `websocket_proxy/server.py:1136` through `websocket_proxy/server.py:1256`.
- ZMQ delivery parses topics, skips private order/position/margin feeds, fans out by subscription index, and forwards higher-detail modes to lower-detail subscribers. Source: `websocket_proxy/server.py:1671` through `websocket_proxy/server.py:1860`.
- Mode normalization accepts integers 1, 2, 3 and case-insensitive labels. Source: `websocket_proxy/mode_utils.py:1` through `websocket_proxy/mode_utils.py:72`.
- Connection pooling defaults to 1000 symbols per connection, 3 connections, and can be disabled. Sources: `websocket_proxy/base_adapter.py:15` through `websocket_proxy/base_adapter.py:32`, `websocket_proxy/connection_manager.py:42` through `websocket_proxy/connection_manager.py:54`.
- The frontend `MarketDataManager` is a shared singleton with ref-counted subscriptions, automatic reconnect, visibility pause/resume, and REST fallback through `/api/v1/multiquotes`. Source: `frontend/src/lib/MarketDataManager.ts:1` through `frontend/src/lib/MarketDataManager.ts:840`.

## Analyzer And Sandbox

- Analyzer mode is stored as a setting and exposed through RESTX, auth routes, and `/settings/analyze-mode`. Sources: `database/settings_db.py:82`, `restx_api/analyzer.py:28`, `blueprints/settings.py:17`.
- Sandbox service routes analyzer-mode trading and account calls to sandbox managers after verifying the API key. Source: `services/sandbox_service.py:25` through `services/sandbox_service.py:420`.
- Sandbox database tables include sandbox orders, trades, positions, holdings, funds, daily PnL, config, GTT, and GTT legs. Source: `database/sandbox_db.py:54` through `database/sandbox_db.py:393`.
- Default sandbox config includes starting capital, reset rules, order and MTM intervals, exchange square-off times, leverage, and GTT config. Source: `database/sandbox_db.py:406` through `database/sandbox_db.py:510`.
- Analyzer logs are stored asynchronously in `analyzer_logs`, with API type, request JSON, response JSON, and created time. Source: `database/analyzer_db.py:36` through `database/analyzer_db.py:115`.
- Live order logs are stored in `order_logs`; analyzer-mode logs use `analyzer_logs`. Source: `subscribers/log_subscriber.py:1` through `subscribers/log_subscriber.py:41`.

## Automation Surfaces

- Chartink webhooks parse scan-name action keywords, validate strategy state and intraday windows, map symbols, then queue `/api/v1/placeorder` or `/api/v1/placesmartorder`. Source: `blueprints/chartink.py:785` through `blueprints/chartink.py:950`.
- Chartink smart-order queue is processed one per second, regular queue up to ten per second. Source: `blueprints/chartink.py:67` through `blueprints/chartink.py:176`.
- Strategy webhooks validate strategy mode, trading hours, symbol mappings, API key presence, and queue order payloads. Source: `blueprints/strategy.py:869` through `blueprints/strategy.py:1033`.
- Strategy order queues use the same one smart order per second and ten regular orders per second pattern. Source: `blueprints/strategy.py:87` through `blueprints/strategy.py:209`.
- Flow CRUD, activation, webhook, import/export, and monitor routes live under `/flow`. Source: `blueprints/flow.py:31` through `blueprints/flow.py:693`.
- Flow stores workflow graph JSON, webhook token, webhook secret, webhook auth type, active flag, scheduler job ID, encrypted API key, and executions. Source: `database/flow_db.py:78` through `database/flow_db.py:120`.
- Flow API keys are encrypted at rest and decrypted for webhook execution. Source: `database/flow_db.py:57` through `database/flow_db.py:75`.
- Flow webhook authentication supports a `secret` in payload or URL query depending on `webhook_auth_type`, with constant-time comparison. Source: `blueprints/flow.py:524` through `blueprints/flow.py:585`.
- Flow execution uses one lock per workflow, a max depth of 100, a max visit count of 500, execution records, variable interpolation, condition routing, and many node types. Source: `services/flow_executor_service.py:26` through `services/flow_executor_service.py:40`, `services/flow_executor_service.py:2037` through `services/flow_executor_service.py:2334`.
- Flow scheduled execution uses APScheduler with a SQLAlchemy job store table `flow_apscheduler_jobs`, coalescing enabled, `max_instances=1`, and `misfire_grace_time=60`. Source: `services/flow_scheduler_service.py:39` through `services/flow_scheduler_service.py:269`.
- Flow price alerts are polled every 5 seconds and trigger workflows in a daemon thread when a condition is met. Source: `services/flow_price_monitor_service.py:38` through `services/flow_price_monitor_service.py:287`.
- Python Strategy routes support strategy CRUD, start, stop, schedule, unschedule, delete, logs, status, contract checks, and API views. Source: `blueprints/python_strategy.py:1555` through `blueprints/python_strategy.py:2651`.

## Events, Logs, Notifications, And Observability

- The in-process EventBus dispatches subscriber callbacks asynchronously through a shared 10-worker thread pool. Source: `utils/event_bus.py:25` through `utils/event_bus.py:70`.
- All EventBus subscribers are registered during app creation. Source: `app.py:141` through `app.py:144`.
- Subscriber registration wires order, GTT, basket, split, options, multi-order, analyzer, and sandbox engine events to logging, Socket.IO, Telegram, and WhatsApp as appropriate. Source: `subscribers/__init__.py:19` through `subscribers/__init__.py:126`.
- Socket.IO emits live order events as `order_event`, `modify_order_event`, `cancel_order_event`, `close_position_event`, and analyzer-mode updates as `analyzer_update`. Source: `subscribers/socketio_subscriber.py:15` through `subscribers/socketio_subscriber.py:247`.
- Telegram and WhatsApp subscribers notify successful order-related events and intentionally skip failure and analyzer-error notification. Sources: `subscribers/telegram_subscriber.py:26` through `subscribers/telegram_subscriber.py:83`, `subscribers/whatsapp_subscriber.py:23` through `subscribers/whatsapp_subscriber.py:78`.
- Traffic logging uses a separate `logs.db` and stores client IP, method, path, status, duration, host, error, and user ID. Source: `database/traffic_db.py:61` through `database/traffic_db.py:90`.
- Health monitoring stores FD, memory, DB, WebSocket, and thread health metrics with pass, warn, and fail statuses. Source: `database/health_db.py:1` through `database/health_db.py:80`.

## Flask Blueprint Route Inventory

The following inventory is static source discovery of `@blueprint.route` decorators. Count: 452 routes.

```text
blueprints/admin.py:112 GET /admin/api/stats api_stats
blueprints/admin.py:133 GET /admin/api/freeze api_freeze_list
blueprints/admin.py:159 POST /admin/api/freeze api_freeze_add
blueprints/admin.py:205 PUT /admin/api/freeze/<int:id> api_freeze_edit
blueprints/admin.py:243 DELETE /admin/api/freeze/<int:id> api_freeze_delete
blueprints/admin.py:265 POST /admin/api/freeze/upload api_freeze_upload
blueprints/admin.py:314 GET /admin/api/holidays api_holidays_list
blueprints/admin.py:371 POST /admin/api/holidays api_holiday_add
blueprints/admin.py:450 DELETE /admin/api/holidays/<int:id> api_holiday_delete
blueprints/admin.py:478 GET /admin/api/timings api_timings_list
blueprints/admin.py:519 PUT /admin/api/timings/<exchange> api_timings_edit
blueprints/admin.py:558 POST /admin/api/timings/check api_timings_check
blueprints/admin.py:789 GET /admin/api/errors api_errors_list
blueprints/admin.py:883 POST /admin/api/errors/client api_errors_client_report
blueprints/admin.py:942 GET /admin/api/errors/stats api_errors_stats
blueprints/admin.py:1039 GET /admin/api/errors/groups api_errors_groups
blueprints/admin.py:1447 GET /admin/api/system api_system_info
blueprints/admin.py:1622 POST /admin/api/system/diagnostics api_system_diagnostics
blueprints/admin.py:1809 GET /admin/api/system/report api_system_report
blueprints/admin.py:1926 GET /admin/api/oauth/clients api_oauth_clients_list
blueprints/admin.py:1970 POST /admin/api/oauth/clients/<client_id>/approve api_oauth_client_approve
blueprints/admin.py:2010 POST /admin/api/oauth/clients/<client_id>/revoke api_oauth_client_revoke
blueprints/admin.py:2065 GET /admin/api/mcp/audit api_mcp_audit
blueprints/admin.py:2165 POST /admin/api/mcp/kill-switch api_mcp_kill_switch
blueprints/admin.py:2294 GET /admin/api/mcp/settings api_mcp_settings_get
blueprints/admin.py:2306 PUT /admin/api/mcp/settings api_mcp_settings_put
blueprints/analyzer.py:182 GET /analyzer analyzer
blueprints/analyzer.py:226 GET /analyzer/api/data api_get_data
blueprints/analyzer.py:279 GET /analyzer/stats get_stats
blueprints/analyzer.py:307 GET /analyzer/requests get_requests
blueprints/analyzer.py:319 GET /analyzer/clear clear_logs
blueprints/analyzer.py:336 GET /analyzer/export export_requests
blueprints/apikey.py:47 GET,POST /apikey manage_api_key
blueprints/apikey.py:105 POST /apikey/mode update_api_key_mode
blueprints/auth.py:85 GET /auth/csrf-token get_csrf_token
blueprints/auth.py:92 GET /auth/broker-config get_broker_config
blueprints/auth.py:131 GET /auth/check-setup check_setup_required
blueprints/auth.py:253 GET,POST /auth/login login
blueprints/auth.py:358 POST /auth/login/totp login_totp
blueprints/auth.py:432 GET /auth/2fa/status two_factor_status
blueprints/auth.py:451 POST /auth/2fa/configure two_factor_configure
blueprints/auth.py:510 GET,POST /auth/broker broker_login
blueprints/auth.py:534 GET,POST /auth/reset-password reset_password
blueprints/auth.py:693 GET /auth/reset-password-email/<token> reset_password_email
blueprints/auth.py:727 GET,POST /auth/change change_password
blueprints/auth.py:791 POST /auth/smtp-config configure_smtp
blueprints/auth.py:856 POST /auth/test-smtp test_smtp
blueprints/auth.py:894 POST /auth/debug-smtp debug_smtp
blueprints/auth.py:921 GET /auth/session-status get_session_status
blueprints/auth.py:998 GET /auth/active-sessions active_sessions
blueprints/auth.py:1016 GET /auth/app-info get_app_info
blueprints/auth.py:1025 GET /auth/analyzer-mode get_analyzer_mode_status
blueprints/auth.py:1051 POST /auth/analyzer-toggle toggle_analyzer_mode_session
blueprints/auth.py:1114 GET /auth/dashboard-data get_dashboard_data
blueprints/auth.py:1190 GET,POST /auth/logout logout
blueprints/auth.py:1250 GET /auth/profile-data get_profile_data
blueprints/auth.py:1315 POST /auth/change-password change_password_api
blueprints/brlogin.py:39 POST,GET /<broker>/callback broker_callback
blueprints/brlogin.py:890 GET,POST /dhan/initiate-oauth dhan_initiate_oauth
blueprints/brlogin.py:969 POST /samco/generate-otp samco_generate_otp
blueprints/brlogin.py:990 POST /samco/generate-secret samco_generate_secret
blueprints/brlogin.py:1016 POST /samco/save-secret samco_save_secret
blueprints/brlogin.py:1039 GET /samco/ip-status samco_ip_status
blueprints/brlogin.py:1058 POST /samco/update-ip samco_update_ip
blueprints/broker_credentials.py:121 GET /api/broker/credentials get_credentials
blueprints/broker_credentials.py:183 POST /api/broker/credentials update_credentials
blueprints/broker_credentials.py:358 GET /api/broker/capabilities get_capabilities
blueprints/chartink.py:285 GET /chartink index
blueprints/chartink.py:299 GET,POST /chartink/new new_strategy
blueprints/chartink.py:368 GET /chartink/<int:strategy_id> view_strategy
blueprints/chartink.py:392 POST /chartink/<int:strategy_id>/delete delete_strategy_route
blueprints/chartink.py:425 GET,POST /chartink/<int:strategy_id>/configure configure_symbols
blueprints/chartink.py:544 POST /chartink/<int:strategy_id>/symbol/<int:mapping_id>/delete delete_symbol
blueprints/chartink.py:564 POST /chartink/<int:strategy_id>/toggle toggle_strategy_route
blueprints/chartink.py:591 GET /chartink/search search_symbols
blueprints/chartink.py:617 GET /chartink/api/strategies api_get_strategies
blueprints/chartink.py:647 GET /chartink/api/strategy/<int:strategy_id> api_get_strategy
blueprints/chartink.py:694 POST /chartink/api/strategy api_create_strategy
blueprints/chartink.py:761 POST /chartink/api/strategy/<int:strategy_id>/toggle api_toggle_strategy
blueprints/chartink.py:787 POST /chartink/webhook/<webhook_id> webhook
blueprints/core.py:20 POST /setup setup
blueprints/custom_straddle.py:24 POST /straddlepnl/api/simulate simulate
blueprints/custom_straddle.py:86 GET /straddlepnl/api/lotsize get_lotsize
blueprints/custom_straddle.py:119 GET /straddlepnl/api/intervals custom_straddle_intervals
blueprints/dashboard.py:17 GET /dashboard dashboard
blueprints/flow.py:33 GET /flow/api/workflows list_workflows
blueprints/flow.py:62 POST /flow/api/workflows create_workflow
blueprints/flow.py:100 GET /flow/api/workflows/<int:workflow_id> get_workflow
blueprints/flow.py:129 PUT /flow/api/workflows/<int:workflow_id> update_workflow
blueprints/flow.py:161 DELETE /flow/api/workflows/<int:workflow_id> delete_workflow
blueprints/flow.py:186 POST /flow/api/workflows/<int:workflow_id>/activate activate_workflow
blueprints/flow.py:263 POST /flow/api/workflows/<int:workflow_id>/deactivate deactivate_workflow
blueprints/flow.py:303 POST /flow/api/workflows/<int:workflow_id>/execute execute_workflow_now
blueprints/flow.py:326 GET /flow/api/workflows/<int:workflow_id>/executions get_workflow_executions
blueprints/flow.py:364 GET /flow/api/workflows/<int:workflow_id>/webhook get_webhook_info
blueprints/flow.py:400 POST /flow/api/workflows/<int:workflow_id>/webhook/enable enable_webhook
blueprints/flow.py:436 POST /flow/api/workflows/<int:workflow_id>/webhook/disable disable_webhook
blueprints/flow.py:448 POST /flow/api/workflows/<int:workflow_id>/webhook/regenerate regenerate_webhook
blueprints/flow.py:477 POST /flow/api/workflows/<int:workflow_id>/webhook/regenerate-secret regenerate_webhook_secret_route
blueprints/flow.py:492 POST /flow/api/workflows/<int:workflow_id>/webhook/auth-type set_webhook_auth
blueprints/flow.py:600 POST /flow/webhook/<token> trigger_webhook
blueprints/flow.py:614 POST /flow/webhook/<token>/<symbol> trigger_webhook_with_symbol
blueprints/flow.py:631 GET /flow/api/monitor/status get_monitor_status
blueprints/flow.py:644 GET /flow/api/workflows/<int:workflow_id>/export export_workflow
blueprints/flow.py:666 POST /flow/api/workflows/import import_workflow
blueprints/flow.py:693 GET /flow/api/index-symbols get_index_symbols_lot_sizes
blueprints/gc_json.py:22 GET,POST /gocharting gocharting_json
blueprints/gex.py:27 POST /gex/api/gex-data gex_data
blueprints/health.py:57 GET /health/status simple_health
blueprints/health.py:104 GET /health/check detailed_health_check
blueprints/health.py:259 GET /health/api/current get_current_metrics
blueprints/health.py:312 GET /health/api/history get_metrics_history
blueprints/health.py:340 GET /health/api/stats get_health_stats
blueprints/health.py:354 GET /health/api/alerts get_alerts
blueprints/health.py:383 POST /health/api/alerts/<int:alert_id>/acknowledge acknowledge_alert
blueprints/health.py:398 POST /health/api/alerts/<int:alert_id>/resolve resolve_alert
blueprints/health.py:418 GET /health/export export_metrics
blueprints/historify.py:29 GET /historify/api/watchlist get_watchlist
blueprints/historify.py:43 POST /historify/api/watchlist add_watchlist
blueprints/historify.py:62 DELETE /historify/api/watchlist remove_watchlist
blueprints/historify.py:80 POST /historify/api/watchlist/bulk/delete bulk_remove_watchlist
blueprints/historify.py:100 POST /historify/api/watchlist/bulk bulk_add_watchlist
blueprints/historify.py:122 POST /historify/api/download download_data
blueprints/historify.py:163 POST /historify/api/download/watchlist download_watchlist
blueprints/historify.py:202 GET /historify/api/data get_chart_data
blueprints/historify.py:228 GET /historify/api/catalog get_catalog
blueprints/historify.py:242 GET /historify/api/symbol-info get_symbol_info
blueprints/historify.py:265 POST /historify/api/export export_data
blueprints/historify.py:301 GET /historify/api/export/download download_export
blueprints/historify.py:363 POST /historify/api/export/preview get_export_preview
blueprints/historify.py:402 POST /historify/api/export/bulk bulk_export
blueprints/historify.py:554 GET /historify/api/export/bulk/download download_bulk_export
blueprints/historify.py:615 GET /historify/api/intervals get_intervals
blueprints/historify.py:642 GET /historify/api/historify-intervals get_historify_intervals
blueprints/historify.py:656 GET /historify/api/exchanges get_exchanges
blueprints/historify.py:670 GET /historify/api/stats get_stats
blueprints/historify.py:684 DELETE /historify/api/delete delete_data
blueprints/historify.py:703 POST /historify/api/delete/bulk bulk_delete_data
blueprints/historify.py:731 POST /historify/api/upload upload_data
blueprints/historify.py:810 GET /historify/api/sample/<format_type> download_sample
blueprints/historify.py:865 GET /historify/api/fno/underlyings get_fno_underlyings
blueprints/historify.py:881 GET /historify/api/fno/expiries get_fno_expiries
blueprints/historify.py:904 GET /historify/api/fno/chain get_fno_chain
blueprints/historify.py:937 GET /historify/api/fno/futures get_futures_chain
blueprints/historify.py:957 GET /historify/api/fno/options get_option_chain
blueprints/historify.py:991 GET /historify/api/jobs get_jobs
blueprints/historify.py:1008 POST /historify/api/jobs create_job
blueprints/historify.py:1056 GET /historify/api/jobs/<job_id> get_job_status
blueprints/historify.py:1070 POST /historify/api/jobs/<job_id>/cancel cancel_job
blueprints/historify.py:1084 POST /historify/api/jobs/<job_id>/pause pause_job
blueprints/historify.py:1098 POST /historify/api/jobs/<job_id>/resume resume_job_endpoint
blueprints/historify.py:1112 POST /historify/api/jobs/<job_id>/retry retry_job
blueprints/historify.py:1139 DELETE /historify/api/jobs/<job_id> delete_job
blueprints/historify.py:1158 GET /historify/api/catalog/grouped get_catalog_grouped
blueprints/historify.py:1176 GET /historify/api/catalog/metadata get_catalog_with_metadata
blueprints/historify.py:1190 POST /historify/api/metadata/enrich enrich_metadata
blueprints/historify.py:1215 GET /historify/api/schedules get_schedules
blueprints/historify.py:1238 POST /historify/api/schedules create_schedule
blueprints/historify.py:1332 GET /historify/api/schedules/<schedule_id> get_schedule
blueprints/historify.py:1358 PUT /historify/api/schedules/<schedule_id> update_schedule
blueprints/historify.py:1423 DELETE /historify/api/schedules/<schedule_id> delete_schedule
blueprints/historify.py:1443 POST /historify/api/schedules/<schedule_id>/enable enable_schedule
blueprints/historify.py:1463 POST /historify/api/schedules/<schedule_id>/disable disable_schedule
blueprints/historify.py:1483 POST /historify/api/schedules/<schedule_id>/pause pause_schedule
blueprints/historify.py:1503 POST /historify/api/schedules/<schedule_id>/resume resume_schedule
blueprints/historify.py:1523 POST /historify/api/schedules/<schedule_id>/trigger trigger_schedule
blueprints/historify.py:1543 GET /historify/api/schedules/<schedule_id>/executions get_schedule_executions
blueprints/ivchart.py:23 POST /ivchart/api/iv-data iv_data
blueprints/ivchart.py:72 POST /ivchart/api/default-symbols default_symbols
blueprints/ivchart.py:112 GET /ivchart/api/intervals intervals
blueprints/ivsmile.py:27 POST /ivsmile/api/iv-smile-data iv_smile_data
blueprints/latency.py:130 GET /latency latency_dashboard
blueprints/latency.py:178 GET /latency/api/logs get_logs
blueprints/latency.py:211 GET /latency/api/stats get_stats
blueprints/latency.py:231 GET /latency/api/broker/<broker>/stats get_broker_stats
blueprints/latency.py:250 GET /latency/export export_logs
blueprints/leverage.py:18 GET /leverage/api/current get_current
blueprints/leverage.py:28 POST /leverage/api/update update_leverage
blueprints/log.py:212 GET /logs view_logs
blueprints/log.py:260 GET /logs/export export_logs
blueprints/logging.py:14 GET /logging logging_dashboard
blueprints/master_contract_status.py:21 GET /api/master-contract/status get_master_contract_status
blueprints/master_contract_status.py:38 GET /api/master-contract/ready check_master_contract_ready
blueprints/master_contract_status.py:64 GET /api/cache/status get_cache_status
blueprints/master_contract_status.py:84 GET /api/cache/health get_cache_health
blueprints/master_contract_status.py:113 POST /api/cache/reload reload_cache
blueprints/master_contract_status.py:145 POST /api/cache/clear clear_cache
blueprints/master_contract_status.py:165 POST /api/master-contract/download force_master_contract_download
blueprints/master_contract_status.py:207 GET /api/master-contract/smart-status get_smart_download_status
blueprints/mcp_http.py:402 OPTIONS /mcp mcp_preflight
blueprints/mcp_http.py:412 POST /mcp mcp_dispatch
blueprints/mcp_http.py:673 GET /mcp mcp_sse
blueprints/mcp_http.py:718 GET /mcp/healthz healthz
blueprints/mcp_http.py:724 GET /mcp/.well-known/oauth-protected-resource mcp_resource_metadata_alias
blueprints/mcp_oauth.py:186 GET /.well-known/oauth-authorization-server discovery_authorization_server
blueprints/mcp_oauth.py:232 GET /.well-known/oauth-protected-resource discovery_protected_resource
blueprints/mcp_oauth.py:244 GET /.well-known/oauth-protected-resource/mcp discovery_protected_resource_for_path
blueprints/mcp_oauth.py:244 GET /.well-known/oauth-protected-resource/<path:resource_path> discovery_protected_resource_for_path
blueprints/mcp_oauth.py:262 GET /oauth/jwks.json jwks_endpoint
blueprints/mcp_oauth.py:282 POST /oauth/register register_client
blueprints/mcp_oauth.py:667 GET,POST /oauth/authorize authorize_endpoint
blueprints/mcp_oauth.py:886 POST /oauth/token token_endpoint
blueprints/mcp_oauth.py:1030 POST /oauth/revoke revoke_endpoint
blueprints/oiprofile.py:32 POST /oiprofile/api/profile-data profile_data
blueprints/oiprofile.py:101 GET /oiprofile/api/intervals intervals
blueprints/oitracker.py:28 POST /oitracker/api/oi-data oi_data
blueprints/oitracker.py:80 POST /oitracker/api/maxpain maxpain
blueprints/orders.py:159 GET /orderbook orderbook
blueprints/orders.py:201 GET /tradebook tradebook
blueprints/orders.py:241 GET /positions positions
blueprints/orders.py:281 GET /holdings holdings
blueprints/orders.py:325 GET /orderbook/export export_orderbook
blueprints/orders.py:386 GET /tradebook/export export_tradebook
blueprints/orders.py:446 GET /positions/export export_positions
blueprints/orders.py:506 POST /close_position close_position
blueprints/orders.py:651 POST /close_all_positions close_all_positions
blueprints/orders.py:696 POST /cancel_all_orders cancel_all_orders_ui
blueprints/orders.py:752 POST /cancel_order cancel_order_ui
blueprints/orders.py:795 POST /modify_gtt_order modify_gtt_order_ui
blueprints/orders.py:853 POST /cancel_gtt_order cancel_gtt_order_ui
blueprints/orders.py:890 POST /modify_order modify_order_ui
blueprints/orders.py:947 GET /action-center action_center
blueprints/orders.py:995 POST /action-center/approve/<int:order_id> approve_pending_order_route
blueprints/orders.py:1039 POST /action-center/reject/<int:order_id> reject_pending_order_route
blueprints/orders.py:1065 DELETE /action-center/delete/<int:order_id> delete_pending_order_route
blueprints/orders.py:1088 GET /action-center/count action_center_count
blueprints/orders.py:1102 POST /action-center/approve-all approve_all_pending_orders
blueprints/orders.py:1170 GET /action-center/api/data action_center_api_data
blueprints/platforms.py:16 GET /platforms index
blueprints/playground.py:289 GET /playground index
blueprints/playground.py:300 GET /playground/api-key get_api_key
blueprints/playground.py:312 GET /playground/collections get_collections
blueprints/playground.py:337 GET /playground/endpoints get_endpoints
blueprints/pnltracker.py:195 GET /pnltracker/legacy pnltracker
blueprints/pnltracker.py:201 GET /test_chart test_chart
blueprints/pnltracker.py:209 POST /pnltracker/api/pnl get_pnl_data
blueprints/python_strategy.py:1555 GET /python index
blueprints/python_strategy.py:1610 GET,POST /python/new new_strategy
blueprints/python_strategy.py:1761 POST /python/start/<strategy_id> start_strategy
blueprints/python_strategy.py:1868 POST /python/stop/<strategy_id> stop_strategy
blueprints/python_strategy.py:1907 POST /python/schedule/<strategy_id> schedule_strategy_route
blueprints/python_strategy.py:1954 POST /python/unschedule/<strategy_id> unschedule_strategy_route
blueprints/python_strategy.py:1967 POST /python/delete/<strategy_id> delete_strategy
blueprints/python_strategy.py:2009 GET /python/logs/<strategy_id> view_logs
blueprints/python_strategy.py:2060 POST /python/logs/<strategy_id>/clear clear_logs
blueprints/python_strategy.py:2132 POST /python/clear-error/<strategy_id> clear_error_state
blueprints/python_strategy.py:2172 GET /python/status status
blueprints/python_strategy.py:2207 POST /python/check-contracts check_contracts
blueprints/python_strategy.py:2282 GET /python/api/strategies api_get_strategies
blueprints/python_strategy.py:2327 GET /python/api/events api_strategy_events
blueprints/python_strategy.py:2375 GET /python/api/strategy/<strategy_id> api_get_strategy
blueprints/python_strategy.py:2421 GET /python/api/strategy/<strategy_id>/content api_get_strategy_content
blueprints/python_strategy.py:2463 GET /python/api/logs/<strategy_id> api_get_log_files
blueprints/python_strategy.py:2494 GET /python/api/logs/<strategy_id>/<log_name> api_get_log_content
blueprints/python_strategy.py:2550 GET /python/edit/<strategy_id> edit_strategy
blueprints/python_strategy.py:2603 GET /python/export/<strategy_id> export_strategy
blueprints/python_strategy.py:2651 POST /python/save/<strategy_id> save_strategy
blueprints/react_app.py:69 GET / react_index
blueprints/react_app.py:75 GET /login react_login
blueprints/react_app.py:81 GET /setup react_setup
blueprints/react_app.py:87 GET /reset-password react_reset_password
blueprints/react_app.py:93 GET /download react_download
blueprints/react_app.py:99 GET /faq react_faq
blueprints/react_app.py:105 GET /error react_error
blueprints/react_app.py:111 GET /rate-limited react_rate_limited
blueprints/react_app.py:117 GET /broker react_broker
blueprints/react_app.py:123 GET /broker/<broker>/totp react_broker_totp
blueprints/react_app.py:129 GET /dashboard react_dashboard
blueprints/react_app.py:135 GET /positions react_positions
blueprints/react_app.py:140 GET /orderbook react_orderbook
blueprints/react_app.py:145 GET /tradebook react_tradebook
blueprints/react_app.py:150 GET /holdings react_holdings
blueprints/react_app.py:156 GET /search/token react_search_token
blueprints/react_app.py:161 GET /search react_search
blueprints/react_app.py:170 GET /playground react_playground
blueprints/react_app.py:181 GET /platforms react_platforms
blueprints/react_app.py:187 GET /tradingview react_tradingview
blueprints/react_app.py:193 GET /gocharting react_gocharting
blueprints/react_app.py:199 GET /pnl-tracker react_pnltracker
blueprints/react_app.py:205 GET /tools react_tools
blueprints/react_app.py:211 GET /ivchart react_ivchart
blueprints/react_app.py:217 GET /oitracker react_oitracker
blueprints/react_app.py:223 GET /maxpain react_maxpain
blueprints/react_app.py:229 GET /straddle react_straddle
blueprints/react_app.py:235 GET /volsurface react_volsurface
blueprints/react_app.py:241 GET /gex react_gex
blueprints/react_app.py:247 GET /ivsmile react_ivsmile
blueprints/react_app.py:253 GET /oiprofile react_oiprofile
blueprints/react_app.py:259 GET /websocket/test react_websocket_test
blueprints/react_app.py:265 GET /websocket/test/20 react_websocket_test_20
blueprints/react_app.py:270 GET /websocket/test/30 react_websocket_test_30
blueprints/react_app.py:275 GET /websocket/test/50 react_websocket_test_50
blueprints/react_app.py:281 GET /sandbox react_sandbox
blueprints/react_app.py:287 GET /sandbox/mypnl react_sandbox_mypnl
blueprints/react_app.py:293 GET /analyzer react_analyzer
blueprints/react_app.py:305 GET /strategy react_strategy_index
blueprints/react_app.py:310 GET /strategy/new react_strategy_new
blueprints/react_app.py:315 GET /strategy/<int:strategy_id> react_strategy_view
blueprints/react_app.py:320 GET /strategy/<int:strategy_id>/configure react_strategy_configure
blueprints/react_app.py:327 GET /python react_python_index
blueprints/react_app.py:332 GET /python/new react_python_new
blueprints/react_app.py:337 GET /python/<strategy_id>/edit react_python_edit
blueprints/react_app.py:342 GET /python/<strategy_id>/logs react_python_logs
blueprints/react_app.py:349 GET /chartink react_chartink_index
blueprints/react_app.py:354 GET /chartink/new react_chartink_new
blueprints/react_app.py:359 GET /chartink/<int:strategy_id> react_chartink_view
blueprints/react_app.py:364 GET /chartink/<int:strategy_id>/configure react_chartink_configure
blueprints/react_app.py:375 GET /admin react_admin_index
blueprints/react_app.py:381 GET /admin/freeze react_admin_freeze
blueprints/react_app.py:387 GET /admin/holidays react_admin_holidays
blueprints/react_app.py:393 GET /admin/timings react_admin_timings
blueprints/react_app.py:399 GET /leverage react_leverage
blueprints/react_app.py:405 GET /telegram react_telegram_index
blueprints/react_app.py:411 GET /telegram/config react_telegram_config
blueprints/react_app.py:417 GET /telegram/users react_telegram_users
blueprints/react_app.py:423 GET /telegram/analytics react_telegram_analytics
blueprints/react_app.py:434 GET /security react_security
blueprints/react_app.py:440 GET /traffic react_traffic
blueprints/react_app.py:446 GET /latency react_latency
blueprints/react_app.py:457 GET /logs react_logs
blueprints/react_app.py:463 GET /logs/live react_logs_live
blueprints/react_app.py:469 GET /logs/sandbox react_logs_sandbox
blueprints/react_app.py:475 GET /logs/security react_logs_security
blueprints/react_app.py:481 GET /logs/traffic react_logs_traffic
blueprints/react_app.py:487 GET /logs/latency react_logs_latency
blueprints/react_app.py:493 GET /profile react_profile
blueprints/react_app.py:499 GET /action-center react_action_center
blueprints/react_app.py:505 GET /historify react_historify
blueprints/react_app.py:516 GET /flow react_flow_index
blueprints/react_app.py:522 GET /flow/editor/<int:workflow_id> react_flow_editor
blueprints/react_app.py:532 GET /assets/<path:filename> serve_assets
blueprints/react_app.py:569 GET /favicon.ico serve_favicon
blueprints/react_app.py:577 GET /logo.png serve_logo
blueprints/react_app.py:585 GET /apple-touch-icon.png serve_apple_touch_icon
blueprints/react_app.py:593 GET /images/<path:filename> serve_images
blueprints/react_app.py:602 GET /sounds/<path:filename> serve_sounds
blueprints/react_app.py:611 GET /docs/<path:filename> serve_docs
blueprints/sandbox.py:42 GET /sandbox sandbox_config
blueprints/sandbox.py:96 GET /sandbox/api/configs api_get_configs
blueprints/sandbox.py:197 POST /sandbox/update update_config
blueprints/sandbox.py:296 POST /sandbox/reset reset_config
blueprints/sandbox.py:411 POST /sandbox/reload-squareoff reload_squareoff
blueprints/sandbox.py:433 GET /sandbox/squareoff-status squareoff_status
blueprints/sandbox.py:455 GET /sandbox/mypnl/api/data api_my_pnl_data
blueprints/sandbox.py:625 GET /sandbox/mypnl my_pnl
blueprints/sandbox.py:1049 GET /sandbox/mypnl/export/daily export_daily_pnl
blueprints/sandbox.py:1081 GET /sandbox/mypnl/export/positions export_positions
blueprints/sandbox.py:1111 GET /sandbox/mypnl/export/holdings export_holdings
blueprints/sandbox.py:1141 GET /sandbox/mypnl/export/trades export_trades
blueprints/scalping.py:124 GET /scalping/api/underlyings underlyings
blueprints/scalping.py:139 GET /scalping/api/all_underlyings all_underlyings
blueprints/scalping.py:171 GET /scalping/api/expiry expiry
blueprints/scalping.py:304 GET /scalping/api/strikes strikes
blueprints/scalping.py:353 GET /scalping/api/search search
blueprints/scalping.py:376 GET /scalping/api/futures futures
blueprints/scalping.py:485 POST /scalping/api/order order
blueprints/scalping.py:636 POST /scalping/api/close_leg close_leg
blueprints/scalping.py:674 POST /scalping/api/close_all close_all
blueprints/scalping.py:737 POST /scalping/api/cancel_all cancel_all
blueprints/scalping.py:753 GET /scalping/api/tracked tracked
blueprints/scalping.py:762 DELETE /scalping/api/tracked reset_tracked
blueprints/scalping.py:771 GET /scalping/api/sl get_sl_states
blueprints/scalping.py:780 POST /scalping/api/sl upsert_sl
blueprints/scalping.py:839 DELETE /scalping/api/sl delete_sl
blueprints/search.py:20 GET /search/token token
blueprints/search.py:27 GET /search search
blueprints/search.py:135 GET /search/api/search api_search
blueprints/search.py:229 GET /search/api/expiries api_expiries
blueprints/search.py:242 GET /search/api/underlyings api_underlyings
blueprints/security.py:38 GET /security security_dashboard
blueprints/security.py:122 POST /security/ban ban_ip
blueprints/security.py:164 POST /security/unban unban_ip
blueprints/security.py:189 POST /security/ban-host ban_host
blueprints/security.py:265 POST /security/clear-404 clear_404_tracker
blueprints/security.py:292 GET /security/api/data security_data
blueprints/security.py:378 GET /security/stats security_stats
blueprints/security.py:412 POST /security/settings update_security_settings
blueprints/security.py:478 GET /security/api/login-activity login_activity
blueprints/security.py:495 POST /security/api/login-activity/clear clear_login_activity
blueprints/security.py:510 GET /security/api/active-sessions active_sessions_list
blueprints/settings.py:17 GET /settings/analyze-mode get_mode
blueprints/settings.py:28 POST /settings/analyze-mode/<int:mode> set_mode
blueprints/straddle_chart.py:23 POST /straddle/api/straddle-data straddle_data
blueprints/straddle_chart.py:72 GET /straddle/api/intervals straddle_intervals
blueprints/strategy.py:334 GET /strategy index
blueprints/strategy.py:357 GET,POST /strategy/new new_strategy
blueprints/strategy.py:443 GET /strategy/<int:strategy_id> view_strategy
blueprints/strategy.py:465 POST /strategy/toggle/<int:strategy_id> toggle_strategy_route
blueprints/strategy.py:497 POST /strategy/<int:strategy_id>/delete delete_strategy_route
blueprints/strategy.py:530 GET,POST /strategy/<int:strategy_id>/configure configure_symbols
blueprints/strategy.py:649 POST /strategy/<int:strategy_id>/symbol/<int:mapping_id>/delete delete_symbol
blueprints/strategy.py:671 GET /strategy/search search_symbols
blueprints/strategy.py:697 GET /strategy/api/strategies api_get_strategies
blueprints/strategy.py:729 GET /strategy/api/strategy/<int:strategy_id> api_get_strategy
blueprints/strategy.py:778 POST /strategy/api/strategy api_create_strategy
blueprints/strategy.py:845 POST /strategy/api/strategy/<int:strategy_id>/toggle api_toggle_strategy
blueprints/strategy.py:871 POST /strategy/webhook/<webhook_id> webhook
blueprints/strategy_chart.py:33 POST /strategybuilder/api/strategy-chart strategy_chart_data
blueprints/strategy_chart.py:92 POST /strategybuilder/api/multi-strike-oi multi_strike_oi_data
blueprints/strategy_chart.py:150 GET /strategybuilder/api/intervals strategy_chart_intervals
blueprints/strategy_portfolio.py:51 GET /api/strategy-portfolio list_strategies
blueprints/strategy_portfolio.py:66 GET /api/strategy-portfolio/<int:entry_id> get_strategy
blueprints/strategy_portfolio.py:76 POST /api/strategy-portfolio create_strategy
blueprints/strategy_portfolio.py:98 PUT /api/strategy-portfolio/<int:entry_id> update_strategy
blueprints/strategy_portfolio.py:123 DELETE /api/strategy-portfolio/<int:entry_id> delete_strategy
blueprints/system_permissions.py:240 GET /api/system/permissions get_permissions
blueprints/system_permissions.py:276 POST /api/system/permissions/fix fix_permissions
blueprints/telegram.py:58 POST /telegram/config configuration
blueprints/telegram.py:94 POST /telegram/bot/start start_bot
blueprints/telegram.py:165 POST /telegram/bot/stop stop_bot
blueprints/telegram.py:183 GET /telegram/bot/status bot_status
blueprints/telegram.py:204 POST /telegram/broadcast broadcast
blueprints/telegram.py:248 POST /telegram/user/<int:telegram_id>/unlink unlink_user
blueprints/telegram.py:265 POST /telegram/test-message send_test_message
blueprints/telegram.py:316 POST /telegram/send-message send_message
blueprints/telegram.py:392 GET /telegram/api/index api_index
blueprints/telegram.py:438 GET /telegram/api/config api_config
blueprints/telegram.py:464 GET /telegram/api/users api_users
blueprints/telegram.py:489 GET /telegram/api/analytics api_analytics
blueprints/traffic.py:76 GET /traffic traffic_dashboard
blueprints/traffic.py:100 GET /traffic/api/logs get_logs
blueprints/traffic.py:128 GET /traffic/api/stats get_stats
blueprints/traffic.py:194 GET /traffic/export export_logs
blueprints/tv_json.py:22 GET,POST /tradingview tradingview_json
blueprints/vol_surface.py:22 POST /volsurface/api/surface-data surface_data
blueprints/websocket_example.py:48 GET /websocket/dashboard websocket_dashboard
blueprints/websocket_example.py:55 GET /websocket/test websocket_test
blueprints/websocket_example.py:62 GET /api/websocket/status api_websocket_status
blueprints/websocket_example.py:80 GET /api/websocket/subscriptions api_websocket_subscriptions
blueprints/websocket_example.py:97 POST /api/websocket/subscribe api_websocket_subscribe
blueprints/websocket_example.py:116 POST /api/websocket/unsubscribe api_websocket_unsubscribe
blueprints/websocket_example.py:135 POST /api/websocket/unsubscribe-all api_websocket_unsubscribe_all
blueprints/websocket_example.py:150 GET /api/websocket/market-data api_websocket_market_data
blueprints/websocket_example.py:166 GET /api/websocket/apikey api_get_websocket_apikey
blueprints/websocket_example.py:187 GET /api/websocket/config api_get_websocket_config
blueprints/websocket_example.py:217 GET /api/websocket/health api_websocket_health
blueprints/websocket_example.py:276 GET /api/websocket/trade-safe api_trade_management_safe
blueprints/websocket_example.py:303 GET /api/websocket/metrics api_websocket_metrics
blueprints/whatsapp.py:51 GET /whatsapp/config get_config
blueprints/whatsapp.py:73 POST /whatsapp/config update_config
blueprints/whatsapp.py:100 POST /whatsapp/pair start_pair
blueprints/whatsapp.py:146 GET /whatsapp/pair/status pair_status
blueprints/whatsapp.py:153 POST /whatsapp/unlink unlink_device
blueprints/whatsapp.py:167 POST /whatsapp/bot/start start_bot
blueprints/whatsapp.py:182 POST /whatsapp/bot/stop stop_bot
blueprints/whatsapp.py:191 GET /whatsapp/bot/status bot_status
blueprints/whatsapp.py:220 GET /whatsapp/users list_users
blueprints/whatsapp.py:231 POST /whatsapp/user/<path:whatsapp_jid>/unlink unlink_user
blueprints/whatsapp.py:254 POST /whatsapp/broadcast broadcast
blueprints/whatsapp.py:288 POST /whatsapp/test-message test_message
blueprints/whatsapp.py:338 POST /whatsapp/send send_to_phone
blueprints/whatsapp.py:388 GET /whatsapp/stats stats
```

## Conditional Surfaces

- The React route set is registered only when `is_react_frontend_available()` returns true. Source: `app.py:236` through `app.py:241`.
- Remote MCP routes are present in source but registered only when `MCP_HTTP_ENABLED=True`. Source: `app.py:303` through `app.py:347`.
- The WebSocket proxy is automatically started unless Docker/standalone flags indicate a separate process. Source: `app.py:899` through `app.py:918`.

## Unverified

- Broker-specific response payload shape is not exhaustively verified for all 33 brokers. The services dynamically import broker modules and normalize only the wrapper-level response.
- The static route inventory lists all blueprint decorators in source. Runtime registration may omit Remote MCP unless enabled and may omit React routes when `frontend/dist` is absent.
- `HISTORIFY_DATABASE_URL` in `.sample.env` and `HISTORIFY_DATABASE_PATH` in `database/historify_db.py` need review before documenting a single env var as authoritative.
- Sandbox GTT tables exist, but all GTT services return 501 in analyzer mode. The current behavior is "not implemented" for analyzer GTT, not the sandbox table state machine.
- The old broker integration guide still says 29 supported brokers. The code and sample env show 33.
