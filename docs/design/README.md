# OpenAlgo Design Documentation

This directory describes the implemented architecture of OpenAlgo `2.0.1.4`. OpenAlgo is a self-hosted, single-user trading application with a Flask/Flask-RESTX backend, React 19 frontend, broker plugins, a separate WebSocket proxy, sandbox execution, hosted strategies, Flow automation, analytics tools, and optional local or remote MCP access.

The current plugin inventory contains 34 broker directories with `plugin.json`. Broker capabilities are metadata-driven; a plugin's presence does not imply every optional broker operation is supported.

## Documentation Policy

- Code and registered routes are authoritative when a design document conflicts with an example.
- The public REST contract lives in [`docs/api`](../api/README.md).
- Flask-RESTX Swagger/OpenAPI UI is intentionally disabled with `doc=False` in `restx_api/__init__.py`. Do not advertise or re-enable `/api/docs` as part of documentation maintenance.
- Current product requirements and known gaps live in [`docs/prd`](../prd/README.md).
- Acceptance behavior and inventories live in [`docs/bdd`](../bdd/README.md).

## Runtime And Core Architecture

| Module | Description |
|---|---|
| [00 Directory Structure](./00-directory-structure/) | Current repository boundaries and ownership |
| [01 Frontend](./01-frontend/) | React 19, Vite 8, routing, state, data access |
| [02 Backend](./02-backend/) | Flask factory, route layers, services, background work |
| [04 Cache Architecture](./04-cache-architecture/) | In-process caches and invalidation behavior |
| [17 Connection Pooling](./17-connection-pooling/) | HTTP and market-data connection reuse |
| [18 Database Structure](./18-database-structure/) | SQLite and DuckDB stores, `NullPool`, teardown |
| [20 Design Principles](./20-design-principles/) | Local conventions and architectural constraints |
| [27 Service Layer](./27-service-layer/) | Route-to-service-to-broker boundaries |
| [31 Utilities](./31-utils-functionalities/) | Shared auth, config, logging, networking helpers |
| [34 App Startup](./34-app-startup/) | Validation, registration, initialization, server startup |
| [53 Event Bus](./53-event-bus/) | Per-process async side-effect dispatch |

## Authentication And Security

| Module | Description |
|---|---|
| [03 Login And Broker Flow](./03-login-broker-flow/) | App auth, TOTP, broker selection, session resume |
| [05 Security Architecture](./05-security-architecture/) | Keys, encryption, CSRF, CORS, CSP, middleware |
| [23 IP Security](./23-ip-security/) | IP extraction, bans, proxy trust |
| [24 Browser Security](./24-browser-security/) | Cookies, CSRF, CSP, hardening headers |
| [40 Logout And Session Lifecycle](./40-logout-session/) | Daily expiry, heartbeat, reconnect, multi-session behavior |
| [47 SMTP Configuration](./47-smtp-config/) | Mail configuration and diagnostics |
| [48 Password Reset](./48-password-reset/) | Reset flow and password change revocation |
| [50 TOTP Configuration](./50-totp-configuration/) | Per-purpose two-factor policy |

## Trading, Data, And Automation

| Module | Description |
|---|---|
| [06 WebSockets](./06-websockets/) | Proxy protocol, ZMQ fan-in, adapters, subscriptions |
| [07 Sandbox](./07-sandbox/) | Analyzer execution engine and isolated state |
| [08 Historify](./08-historify/) | DuckDB historical-data subsystem |
| [09 REST API](./09-rest-api/) | Registered v1 architecture; Swagger intentionally disabled |
| [10 Flow](./10-flow-architecture/) | Visual workflow storage and execution |
| [13 Chartink](./13-chartink/) | Scanner automation |
| [14 TradingView And GoCharting](./14-tradingview-gocharting/) | JSON integration surfaces |
| [19 PlaceOrder Flow](./19-placeorder-flow/) | Validation, mode routing, Action Center, broker calls |
| [32 Master Contract](./32-master-contract/) | Broker instrument downloads and cache policy |
| [33 Broker Folder](./33-broker-folder/) | Plugin module convention |
| [38 Python Strategies](./38-python-strategies/) | Hosted-process model and logs |
| [39 Strategy Module](./39-strategy-module/) | Webhook strategy management |
| [42 Action Center](./42-action-center/) | Semi-auto order approval |
| [54 Scalping Terminal](./54-scalping-terminal/) | Keyboard trading, charts, persisted stops, risk monitor |

## UI, Tools, And Integrations

| Module | Description |
|---|---|
| [15 Basic UI And Analytics](./15-basic-ui/) | Current React pages and analytics tools |
| [37 API Key And Playground](./37-apikey-playground/) | API key management and WebSocket tester |
| [41 MCP Architecture](./41-mcp-architecture/) | Local stdio and opt-in remote OAuth transport |
| [43 Telegram Bot](./43-telegram-bot/) | Bot lifecycle, commands, automatic and explicit alerts |
| [43 Toast Notifications](./43-toast-notifications/) | Browser notification categories |
| [44 PnL Tracker](./44-pnl-tracker/) | Live P&L charting |
| [46 Search](./46-search/) | Contract and underlying search |
| [49 Themes](./49-themes/) | Theme and accent persistence |
| [51 Broker And System Config](./51-broker-system-config/) | Environment and broker configuration boundaries |
| [52 Broker Factory](./52-broker-factory/) | WebSocket adapter construction |

## Operations And Deployment

| Module | Description |
|---|---|
| [11 Docker](./11-docker/) | Container build and compose runtime |
| [12 Ubuntu Server](./12-ubuntu-server/) | Host deployment |
| [16 Centralized Logging](./16-centralized-logging/) | Python logs and file retention |
| [21 Admin Section](./21-admin-section/) | Runtime and Remote MCP administration |
| [22 Log Section](./22-log-section/) | Order and analyzer log views |
| [25 Latency Monitor](./25-latency-monitor/) | API timing data |
| [26 Traffic Logs](./26-traffic-logs/) | Request telemetry and ban support |
| [28 Environment Configuration](./28-environment-config/) | `.env` contract |
| [29 Ngrok Configuration](./29-ngrok-config/) | Tunnel management |
| [30 Upgrade Procedure](./30-upgrade-procedure/) | Upgrade and backup flow |
| [35 Development And Testing](./35-development-testing/) | Local checks and CI coverage |
| [36 Rate Limiting](./36-rate-limiting/) | Limiter configuration and endpoint classes |

See [TRACKER.md](./TRACKER.md) for the verification record for this sweep.
