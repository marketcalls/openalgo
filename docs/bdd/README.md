# BDD Coverage

These Gherkin files describe current OpenAlgo behavior for review, acceptance-test design, and regression planning. Each scenario or outline has an implementation source comment immediately above it. The files are documentation specifications; this repository does not contain Cucumber/Behave step definitions that execute them.

## Inventory

| File | Domain | Definitions |
|---|---|---:|
| `rest_api_inventory.feature` | All 74 registered REST v1 method/path pairs | 1 outline |
| `broker_plugin_inventory.feature` | All 38 broker plugins | 1 outline |
| `auth_and_setup.feature` | Setup, login, TOTP, route order, DB readiness, logout | 9 |
| `session_lifecycle.feature` | Multi-session cap, heartbeat, rollover, reconnect | 5 |
| `broker_sessions.feature` | Broker login, callbacks, credentials, capabilities | 12 |
| `orders_and_action_center.feature` | Order routing and semi-auto approval | 9 |
| `gtt_orders.feature` | Live capability gate and sandbox GTT lifecycle | 6 |
| `account_and_depth.feature` | Account collections, margin, open positions, depth | 5 |
| `market_data.feature` | Quotes, history, option chain, instruments | 5 |
| `websocket_streaming.feature` | Proxy protocol, subscriptions, ZMQ fan-in | 7 |
| `sandbox_analyzer.feature` | Analyzer mode and sandbox state | 5 |
| `automation_webhooks.feature` | Chartink, JSON webhooks, Python host | 5 |
| `flow_workflows.feature` | Flow CRUD, execution, webhook, scheduler, monitor | 6 |
| `scalping_and_tools.feature` | Scalping safety/risk plus current analytics tools | 10 |
| `notifications_observability.feature` | Telegram, WhatsApp, EventBus, health, traffic | 9 |
| `admin_and_security.feature` | Admin, IP security, CSP, Remote MCP controls | 4 |
| `historify_and_tools.feature` | Historify jobs/schedules and option tools | 4 |
| `strategy_module_rms.feature` | Multi-leg baskets, signal legs, durable ownership, aggregate-trigger versus execution truth, pending stops, recovery/P&L authority, broker-primary UI truth | 35 |

Verified on 2026-11-06 with the Gherkin parser (all 18 files parse):

- Feature files: 18
- Scenario definitions: 138
- Scenario outlines: 8
- Example rows across outlines: 136
- Expanded scenario cases: 266 (`138 - 8 + 136`)

The REST inventory outline is contract coverage, not proof that every endpoint succeeds against every broker. The broker outline proves configuration inventory only; broker-specific behavioral verification remains in broker tests and adapter integration checks.

## Maintenance Rules

1. Add or update a scenario whenever a public method/path, operational mode, persisted state transition, or safety invariant changes.
2. Keep route and service citations implementation-backed. A UI helper route is not evidence for WebSocket proxy behavior.
3. Add registered REST resources to `rest_api_inventory.feature` and `docs/api/README.md` in the same change.
4. Add or remove broker rows in `broker_plugin_inventory.feature` when `broker/*/plugin.json` changes.
5. Record genuine contradictions and intentionally unsupported behavior in `docs/prd/CONFLICTS.md`.
