# OpenAlgo Current-State PRD

This document describes OpenAlgo as it exists in the current source tree. It is not a roadmap. Requirements are grounded in `DISCOVERY_MAP.md` and checked against the BDD suite in `docs/bdd`.

## Product Overview And Purpose

OpenAlgo is a self-hosted trading application for retail algo traders. It exposes a Flask and Flask-RESTX backend, a React frontend when `frontend/dist` exists, broker plugins, REST APIs, webhook automation, a Flow workflow builder, Python strategy hosting, analyzer/sandbox mode, market data APIs, and a separate WebSocket proxy. The documented HTTP surface is 57 RESTX `/api/v1` endpoints, 452 Flask blueprint routes, and 1 app-level route, for 510 documented HTTP endpoints. Discovery source: `DISCOVERY_MAP.md` sections `Discovery Summary`, `Entry Points And Runtime`, `RESTX API V1`, and `Flask Blueprint Route Inventory`.

The product purpose is to let a local trader connect a broker session, issue normalized trading and market-data requests, run automation workflows, test behavior in analyzer mode, and monitor operational state from one self-hosted installation.

## Target Users And Primary Use Cases

- Retail algo trader: connects a broker, manages an API key, places regular, smart, basket, split, options, and GTT orders, reviews orders in semi-auto mode, and monitors orders, positions, holdings, funds, and margin.
- Strategy user: routes external webhook signals from Chartink, Strategy webhooks, TradingView JSON, GoCharting JSON, Flow, or Python Strategy into OpenAlgo order flows.
- Market data consumer: requests quotes, multiquotes, depth, history, option chains, option symbols, and WebSocket subscriptions for live market data.
- Sandbox user: turns on analyzer mode, routes supported calls to sandbox services, reviews sandbox orders, trades, positions, holdings, funds, daily PnL, and configuration.
- Local operator: configures environment, session security, broker credentials, notifications, health, traffic logs, latency logs, security controls, and optional Remote MCP.

## Functional Requirements

### Runtime, Setup, And Configuration

- FR-001: The application must validate environment variables before normal app imports complete. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-002: The application must require `APP_KEY` to exist and be at least 32 characters before startup proceeds. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Security And Auth`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-003: The application must configure session cookie security from `HOST_SERVER`, using secure cookies for HTTPS hosts and local exceptions for local HTTP. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-004: The React route set must register before REST and UI blueprints when `frontend/dist` is available. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Conditional Surfaces`; BDD coverage gap: see `CONFLICTS.md`.
- FR-005: `/api/v1` must be CSRF-exempt after RESTX registration, while selected webhook, callback, logout, and health routes are also explicitly exempted. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Security And Auth`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-006: The app must wait up to 30 seconds for database initialization before request handling and remove scoped SQLAlchemy sessions during teardown. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`; BDD coverage gap: see `CONFLICTS.md`.
- FR-007: The WebSocket proxy must start from the app unless Docker or standalone proxy configuration indicates a separate process. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Conditional Surfaces`; BDD: `docs/bdd/websocket_streaming.feature`.

### Authentication, Sessions, And API Keys

- FR-008: Setup status must be exposed before login, and setup must be submitted through the setup route. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-009: Users must log in through session routes, and protected web routes must read the authenticated session. Trace: `DISCOVERY_MAP.md` `Security And Auth`, `Flask Blueprint Route Inventory`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-010: Login can require TOTP, and 2FA status must be exposed. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-011: Session status must reflect expiry policy, and expired sessions must revoke broker tokens during request handling. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Security And Auth`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-012: Logout must clear the session and is included in CSRF exemptions. Trace: `DISCOVERY_MAP.md` `Entry Points And Runtime`, `Flask Blueprint Route Inventory`; BDD: `docs/bdd/auth_and_setup.feature`.
- FR-013: `API_KEY_PEPPER` must be required, API keys must be Argon2-hashed with the pepper, and encrypted key retrieval must exist for internal UI and integrations. Trace: `DISCOVERY_MAP.md` `Security And Auth`; BDD: `docs/bdd/auth_and_setup.feature`, `docs/bdd/broker_sessions.feature`.
- FR-014: API key verification must cache valid and invalid outcomes, track invalid attempts, and map a verified API key to the active broker session. Trace: `DISCOVERY_MAP.md` `Security And Auth`; BDD: `docs/bdd/broker_sessions.feature`, `docs/bdd/orders_and_action_center.feature`.

### Broker Sessions And Broker Plugins

- FR-015: Broker selection and broker login must associate a broker with the authenticated user session. Trace: `DISCOVERY_MAP.md` `Broker Plugins`, `Flask Blueprint Route Inventory`; BDD: `docs/bdd/broker_sessions.feature`.
- FR-016: Broker callback routes must delegate broker-specific auth handling to plugin auth modules. Trace: `DISCOVERY_MAP.md` `Broker Plugins`; BDD: `docs/bdd/broker_sessions.feature`.
- FR-017: Broker credential and capability APIs must expose broker-specific credential requirements and capability metadata derived from plugin configuration. Trace: `DISCOVERY_MAP.md` `Broker Plugins`; BDD: `docs/bdd/broker_sessions.feature`.
- FR-018: Broker capability metadata must load from every `broker/*/plugin.json`, and broker auth modules must lazy-load from `broker.{broker}.api.auth_api`. Trace: `DISCOVERY_MAP.md` `Broker Plugins`; BDD: `docs/bdd/broker_sessions.feature`.
- FR-019: Order, data, and GTT services must dynamically import broker-specific modules based on the active broker. Trace: `DISCOVERY_MAP.md` `Broker Plugins`, `Order Execution, Analyzer Mode, And Action Center`, `Market Data And History`, `GTT Orders`; BDD: `docs/bdd/orders_and_action_center.feature`, `docs/bdd/market_data.feature`, `docs/bdd/gtt_orders.feature`.

### REST API Surface

- FR-020: RESTX namespaces must be registered under `/api/v1`. Trace: `DISCOVERY_MAP.md` `RESTX API V1`; BDD: `docs/bdd/market_data.feature`, `docs/bdd/orders_and_action_center.feature`, `docs/bdd/gtt_orders.feature`.
- FR-021: Order, smart order, GTT, history, and option request schemas must validate required fields and supported values before service execution. Trace: `DISCOVERY_MAP.md` `RESTX API V1`; BDD: `docs/bdd/orders_and_action_center.feature`, `docs/bdd/gtt_orders.feature`, `docs/bdd/market_data.feature`.
- FR-022: The REST API must expose account, order, market data, option service, analyzer, notification, and utility endpoints listed in the RESTX inventory. Trace: `DISCOVERY_MAP.md` `RESTX Endpoint Inventory`; BDD coverage gap: see `CONFLICTS.md`.

### Order Lifecycle And Action Center

- FR-023: Regular order placement must validate request data, use API key authentication, resolve broker auth, and call the broker order module in live mode. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-024: Live order placement must publish success and failure events for order outcomes. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`, `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-025: Analyzer mode must route regular order placement to sandbox order placement instead of broker order APIs. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`, `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`, `docs/bdd/orders_and_action_center.feature`.
- FR-026: Smart orders must route to sandbox smart order logic in analyzer mode and broker smart order APIs in live mode. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-027: Basket orders must sort BUY orders before SELL orders, run analyzer baskets through sandbox with quote prefetch, and execute live baskets in concurrent batches of 10 with a one-second delay between batches. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-028: Split orders must cap child orders at 100, use `ORDER_RATE_LIMIT` as the live delay, and prefetch quotes for sandbox split execution. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-029: Semi-auto routing must queue eligible order types to the Action Center when the API key mode is `semi_auto`. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-030: Action Center approval and approve-all must mark pending orders approved and attempt execution immediately. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-031: Pending order execution must dispatch approved pending orders to place order, smart order, basket order, split order, or options order services and update broker order status if possible. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/orders_and_action_center.feature`.
- FR-032: Close, cancel, cancel-all, modify, modify-GTT, and cancel-GTT operations must be blocked in semi-auto mode by service logic unless analyzer mode is enabled. Trace: `DISCOVERY_MAP.md` `Order Execution, Analyzer Mode, And Action Center`; BDD: `docs/bdd/gtt_orders.feature`.

### Positions, Holdings, Funds, And Margin

- FR-033: The API surface must include positionbook, openposition, holdings, funds, and margin endpoints under `/api/v1`. Trace: `DISCOVERY_MAP.md` `RESTX Endpoint Inventory`; BDD coverage gap: see `CONFLICTS.md`.
- FR-034: The web surface must include orderbook, tradebook, positions, holdings, close-position, close-all, cancel-all, cancel-order, and modify-order routes. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD coverage gap: see `CONFLICTS.md`.
- FR-035: Analyzer-mode account and trading calls must route through sandbox services after API key verification. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.

### GTT Orders

- FR-036: Place, modify, cancel, and orderbook GTT services must import `broker.{broker}.api.gtt_api`; missing modules must return 501. Trace: `DISCOVERY_MAP.md` `GTT Orders`; BDD: `docs/bdd/gtt_orders.feature`.
- FR-037: Analyzer mode must return 501 for place, modify, cancel, and orderbook GTT operations. Trace: `DISCOVERY_MAP.md` `GTT Orders`; BDD: `docs/bdd/gtt_orders.feature`.
- FR-038: Place GTT must be queueable through Action Center in semi-auto mode. Trace: `DISCOVERY_MAP.md` `GTT Orders`; BDD: `docs/bdd/gtt_orders.feature`.
- FR-039: Modify GTT and cancel GTT must be blocked in semi-auto mode because queued changes can be stale. Trace: `DISCOVERY_MAP.md` `GTT Orders`; BDD: `docs/bdd/gtt_orders.feature`.

### Market Data, History, And Options

- FR-040: Quote requests must validate exchange and symbol against supported exchanges and master contract cache before broker data access. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD: `docs/bdd/market_data.feature`.
- FR-041: Multiquotes must validate every requested item, return per-symbol errors for invalid items, and fall back to single-symbol quotes when native broker multiquotes are unavailable. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD: `docs/bdd/market_data.feature`.
- FR-042: History broker calls must be rate-limited to about three requests per second and must include `oi` in responses even when the broker dataframe omits it. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD: `docs/bdd/market_data.feature`.
- FR-043: History with `source=db` must read from Historify DuckDB and return 404 when local data is missing. Trace: `DISCOVERY_MAP.md` `Market Data And History`, `Data Stores`; BDD: `docs/bdd/market_data.feature`, `docs/bdd/historify_and_tools.feature`.
- FR-044: Depth must validate symbols, resolve feed token and broker, and pass broker-specific user ID when supported. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD coverage gap: see `CONFLICTS.md`.
- FR-045: Option chain must map underlying quote exchange, derive ATM from underlying LTP, select strikes, fetch CE and PE quotes through multiquotes, and return chain rows. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD: `docs/bdd/market_data.feature`.
- FR-046: Option symbol generation must use symbol database strike lists and in-memory strike caching. Trace: `DISCOVERY_MAP.md` `Market Data And History`; BDD: `docs/bdd/market_data.feature`.
- FR-047: Option analytics tool routes must expose IV and OI analytic views when option market data is available. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD: `docs/bdd/historify_and_tools.feature`.

### WebSocket Streaming

- FR-048: The WebSocket proxy must track clients, subscriptions, adapters, user mappings, and an O(1) subscription index. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-049: The proxy must subscribe to all ZeroMQ topics from the configured ZeroMQ host and port. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-050: WebSocket clients must authenticate within `WS_AUTH_GRACE_SECONDS`, default 15 seconds. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-051: Authentication messages must accept `api_key` or `apikey`, verify the key, create a broker adapter, and return broker identity plus feature flags. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-052: Subscription messages must accept one `symbol` or a `symbols` array, normalize mode to `LTP`, `Quote`, or `Depth`, store depth levels, and return per-symbol results. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-053: Delivery must parse ZeroMQ topics, skip private order, position, and margin feeds, fan out through the subscription index, and forward higher-detail modes to lower-detail subscribers. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.
- FR-054: The frontend market data manager must use shared ref-counted subscriptions, automatic reconnect, visibility pause/resume, and REST fallback through `/api/v1/multiquotes`. Trace: `DISCOVERY_MAP.md` `WebSocket Streaming`; BDD: `docs/bdd/websocket_streaming.feature`.

### Analyzer And Sandbox Mode

- FR-055: Analyzer mode must be stored as a setting and exposed through RESTX, auth routes, and `/settings/analyze-mode`. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.
- FR-056: Sandbox service must verify API keys before routing analyzer-mode trading and account calls to sandbox managers. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.
- FR-057: Sandbox tables must store sandbox orders, trades, positions, holdings, funds, daily PnL, config, GTT, and GTT legs. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.
- FR-058: Default sandbox config must include starting capital, reset rules, order and MTM intervals, exchange square-off times, leverage, and GTT config. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.
- FR-059: Analyzer logs must store API type, request JSON, response JSON, and created time asynchronously. Trace: `DISCOVERY_MAP.md` `Analyzer And Sandbox`; BDD: `docs/bdd/sandbox_analyzer.feature`.

### Automation, Flow, And Python Strategy

- FR-060: Chartink webhooks must parse scan-name action keywords, validate strategy state and intraday windows, map symbols, and queue regular or smart orders. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/automation_webhooks.feature`.
- FR-061: Chartink and Strategy queues must process one smart order per second and up to ten regular orders per second. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/automation_webhooks.feature`.
- FR-062: Strategy webhooks must validate strategy mode, trading hours, symbol mappings, and API key presence before queueing order payloads. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/automation_webhooks.feature`.
- FR-063: TradingView JSON and GoCharting JSON routes must exist as automation entry points. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD: `docs/bdd/automation_webhooks.feature`.
- FR-064: Flow must support workflow CRUD, activation, webhook management, manual execution, import, export, and monitor status under `/flow`. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-065: Flow must store graph JSON, webhook token, webhook secret, webhook auth type, active flag, scheduler job ID, encrypted API key, and execution records. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-066: Flow webhook authentication must support configured secret validation using constant-time comparison. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-067: Flow execution must enforce one lock per workflow, max depth 100, max visit count 500, execution records, variable interpolation, condition routing, and node-chain execution. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-068: Flow schedules must use APScheduler with SQLAlchemy job storage, coalescing, `max_instances=1`, and `misfire_grace_time=60`. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-069: Flow price alerts must poll every 5 seconds and trigger workflows in a daemon thread when conditions match. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/flow_workflows.feature`.
- FR-070: Python Strategy routes must support strategy CRUD, start, stop, schedule, unschedule, delete, logs, status, contract checks, and API views. Trace: `DISCOVERY_MAP.md` `Automation Surfaces`; BDD: `docs/bdd/automation_webhooks.feature`.

### Notifications, Observability, Admin, And Historify

- FR-071: EventBus must dispatch subscriber callbacks asynchronously through a shared 10-worker thread pool. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-072: App creation must register subscribers for order, GTT, basket, split, options, multi-order, analyzer, and sandbox events. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-073: Socket.IO subscribers must emit live order events and analyzer updates. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-074: Telegram and WhatsApp subscribers must notify successful order-related events and skip failure and analyzer-error notification. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-075: Telegram and WhatsApp RESTX notification APIs must support direct notification requests. Trace: `DISCOVERY_MAP.md` `RESTX API V1`, `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-076: Traffic logging must store client IP, method, path, status, duration, host, error, and user ID in a separate traffic database. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD coverage gap: see `CONFLICTS.md`.
- FR-077: Health monitoring must store file descriptor, memory, database, WebSocket, and thread metrics with pass, warn, and fail statuses. Trace: `DISCOVERY_MAP.md` `Events, Logs, Notifications, And Observability`; BDD: `docs/bdd/notifications_observability.feature`.
- FR-078: Admin routes must expose runtime system details, diagnostics, OAuth client controls, MCP audit, MCP kill switch, and MCP settings. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`; BDD: `docs/bdd/admin_and_security.feature`.
- FR-079: Security routes must expose IP ban, unban, host ban, 404 tracker clearing, security data, security stats, settings, login activity, and active sessions. Trace: `DISCOVERY_MAP.md` `Flask Blueprint Route Inventory`, `Security And Auth`; BDD: `docs/bdd/admin_and_security.feature`.
- FR-080: Historify must store market data, watchlist, data catalog, download jobs, symbol metadata, schedules, schedule executions, and indexes in DuckDB. Trace: `DISCOVERY_MAP.md` `Data Stores`, `Flask Blueprint Route Inventory`; BDD: `docs/bdd/historify_and_tools.feature`.

## Broker Support

Current broker count is 33. Broker support is plugin-based and loaded from `broker/*/plugin.json`. Live GTT modules were found only for Dhan and Zerodha. Trace: `DISCOVERY_MAP.md` `Broker Plugins`; BDD: `docs/bdd/broker_sessions.feature`, `docs/bdd/gtt_orders.feature`.

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

## Market Data And WebSocket Capabilities

Market data is available through RESTX endpoints for quotes, multiquotes, depth, history, option symbols, option chain, option greeks, multi option greeks, instruments, search, symbol lookup, intervals, expiry, market timings, and market holidays. REST history supports `source=api` and `source=db`; local history reads from Historify DuckDB. Multiquotes returns per-symbol validation errors and can fall back to single quotes.

The WebSocket proxy uses an action envelope with the documented actions `authenticate`, `subscribe`, `unsubscribe`, `unsubscribe_all`, `get_broker_info`, `get_supported_brokers`, and `ping`. Authentication accepts `api_key` or `apikey`. Subscription accepts one `symbol` or a `symbols` array, supports `LTP`, `Quote`, and `Depth` modes, and returns per-symbol results. Mode values also normalize from integers 1, 2, and 3. Delivery fans out public market data by subscription index and skips private order, position, and margin topics. Full broker adapter payload shapes are not exhaustively verified.

## Operational Modes

Live mode sends supported order and data requests to broker-specific modules resolved from the active broker session. Analyzer mode routes supported trading and account calls to sandbox managers after API key verification. Analyzer order placement, smart orders, basket orders, and split orders use sandbox paths. Analyzer GTT place, modify, cancel, and orderbook currently return 501. Semi-auto mode queues eligible order types into Action Center for approval; close, cancel, cancel-all, modify, modify-GTT, and cancel-GTT are blocked by their services in semi-auto live mode.

## Security Model And Posture

OpenAlgo is configured as a self-hosted application with session routes and API-key routes. `APP_KEY` and `API_KEY_PEPPER` are required configuration. API keys are hashed for verification and encrypted for internal retrieval. Broker auth tokens and feed tokens are encrypted. `/api/v1` is CSRF-exempt for external API clients, while session routes keep CSRF protection except for explicit webhook, callback, logout, and health exemptions. CORS, CSP, hardening headers, rate limits, IP ban checks, proxy-header trust, and session expiry are environment-controlled. This PRD does not document secrets, token values, or attack procedures.

## Performance Characteristics And Known Limits

- Request handling waits up to 30 seconds for database initialization.
- Flask-Limiter uses moving-window limits with memory storage and environment-defined limits.
- History broker calls are rate-limited to about three requests per second.
- Chartink and Strategy workers process one smart order per second and up to ten regular orders per second.
- Basket live execution runs concurrent batches of 10 with a one-second delay between batches.
- Split orders are capped at 100 child orders and use `ORDER_RATE_LIMIT` as delay.
- WebSocket connection pooling defaults to 1000 symbols per connection and 3 connections, and can be disabled.
- WebSocket clients have a default 15-second authentication grace period.
- WebSocket server queue and ping behavior are controlled by `WS_MAX_QUEUE`, `WS_PING_INTERVAL`, and `WS_PING_TIMEOUT`.
- EventBus uses a shared 10-worker thread pool.
- Flow execution enforces one lock per workflow, max depth 100, and max visit count 500.
- Flow scheduled jobs use `max_instances=1`, coalescing, and `misfire_grace_time=60`.
- Flow price alerts poll every 5 seconds.
- `MultiOptionGreeksSchema` caps symbols at 50.
- SQLite engines use `NullPool` to avoid long-lived file descriptors and shared-cursor corruption.

## Non-Functional Requirements

- Reliability: startup validation must prevent missing critical configuration; DB readiness gating must prevent early request handling; SQLAlchemy scoped sessions must be removed on teardown; the WebSocket proxy must run as a child process under eventlet/gunicorn and as an OS thread under the development server.
- Observability: order events, analyzer logs, traffic logs, latency logs, health metrics, Socket.IO updates, Telegram notifications, and WhatsApp notifications must remain event-driven and auditable from their configured stores or routes.
- Deployment: Python must be `>=3.12`; the frontend requires Node `>=20.20.0 || >=22.22.0 || >=24.13.0`; Remote MCP must remain opt-in through `MCP_HTTP_ENABLED=True` and requires non-debug mode plus `MCP_PUBLIC_URL`.
- Data ownership: the app stores primary operational state in local SQLite databases and local historical data in DuckDB according to configured paths.

## Out Of Scope And Known Gaps

- Broker-specific response payload shapes are not exhaustively verified for all 33 brokers.
- Static route inventory may differ from runtime registration when Remote MCP is disabled or `frontend/dist` is absent.
- `HISTORIFY_DATABASE_URL` in `.sample.env` and `HISTORIFY_DATABASE_PATH` in implementation need review before one env var is documented as authoritative.
- Sandbox GTT tables exist, but analyzer GTT services return 501.
- The old broker integration guide still says 29 brokers, while the code and sample env show 33.
- Full BDD coverage does not exist for every documented RESTX endpoint, blueprint route, broker row, or account endpoint. See `CONFLICTS.md`.
