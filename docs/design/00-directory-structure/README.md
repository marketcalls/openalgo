# 00 - Directory Structure

## Architectural Boundaries

```text
openalgo/
|-- app.py                     Flask factory, registration, startup
|-- restx_api/                 External `/api/v1` resources and schemas
|-- blueprints/                Session UI APIs, webhooks, React route serving
|-- services/                  Business logic and mode routing
|-- broker/                    34 metadata-driven broker plugins
|-- websocket_proxy/           Standalone asyncio WebSocket server and adapters
|-- database/                  SQLAlchemy/DuckDB models and persistence helpers
|-- sandbox/                   Analyzer execution, positions, funds, settlement
|-- events/                    Typed EventBus payloads
|-- subscribers/               Logging, Socket.IO, Telegram, WhatsApp consumers
|-- frontend/                  React 19 + TypeScript + Vite application
|-- mcp/                       Local stdio MCP server
|-- docs/                      API, BDD, design, PRD, guides, audits
|-- test/                      Python tests, including sandbox tests
|-- examples/                  Python, Go, and Node.js integration examples
|-- collections/               Bruno and Postman request collections
|-- db/                        Runtime SQLite and DuckDB files (not source)
|-- log/                       Optional runtime log files (not source)
`-- strategies/                User strategy scripts and runtime content
```

## Request Layers

| Layer | Owns | Must not own |
|---|---|---|
| `restx_api/` | JSON/query parsing, Marshmallow validation, HTTP response | Broker-specific business rules |
| `blueprints/` | Session-authenticated app APIs, webhooks, feature routes | Reusable broker execution logic |
| `services/` | API-key verification, mode routing, normalized orchestration | Flask page rendering |
| `broker/<key>/` | Broker authentication, request mapping, data transforms, streaming | Cross-broker product policy |
| `database/` | Persistence models, migrations, queries, cache invalidation | HTTP contracts |
| `sandbox/` | Simulated execution and account state | Live broker calls |

## Backend Inventory

`restx_api/__init__.py` registers 57 v1 method/path pairs. `blueprints/` contains the larger session and feature surface for auth, admin, Flow, Historify, strategies, tools, messaging, monitoring, and the React application. Static route counts are maintained in `DISCOVERY_MAP.md`; public REST documentation is maintained in `docs/api`.

The service directory currently includes order, account, market-data, option, calendar, Flow, Historify, messaging, charting, analytics, arbitrage, custom straddle, and scalping risk services. Use `rg --files services` for the live inventory instead of copying a long file list into architecture documents.

## Broker Plugin Shape

Every configured broker has `broker/<key>/plugin.json`. Common optional subtrees are:

```text
broker/<key>/
|-- plugin.json
|-- api/
|   |-- auth_api.py
|   |-- order_api.py
|   |-- data.py
|   `-- funds.py
|-- mapping/
|-- database/
`-- streaming/
```

The loader imports modules lazily; not every broker implements every optional file. Live GTT modules currently exist for Dhan and Zerodha only.

## Frontend Shape

```text
frontend/src/
|-- App.tsx                    Lazy routes and auth gates
|-- app/providers.tsx          Query, theme, tooltip, Socket.IO providers
|-- api/                       Typed HTTP clients by feature
|-- pages/                     Top-level and grouped route pages
|-- components/                Layout, trading, tools, Flow, scalping, UI
|-- hooks/                     Market data, Socket.IO, visibility, risk helpers
|-- stores/                    Zustand auth, broker, session, theme, Flow state
|-- lib/                       MarketDataManager, plotting, math, helpers
|-- types/                     Feature contracts
`-- test/                      Vitest setup and accessibility helpers
```

## Persistence Shape

The deployment uses six primary configured stores: main `openalgo.db`, traffic `logs.db`, latency `latency.db`, health `health.db`, sandbox `sandbox.db`, and Historify `historify.duckdb`. Scalping tables use the main database URL. See [18 Database Structure](../18-database-structure/).

## Documentation Shape

| Directory | Purpose |
|---|---|
| `docs/api` | External REST and WebSocket contracts |
| `docs/bdd` | Gherkin specifications and inventories |
| `docs/design` | Implemented architecture |
| `docs/prd` | Current and subsystem product requirements |
| `docs/audit` | Point-in-time reviews |
| `docs/releases` | Release notes |
