# BDD Coverage

These Gherkin files describe current OpenAlgo behavior for review, acceptance-test design, and regression planning. Each scenario or outline has an implementation source comment immediately above it. The files are documentation specifications; this repository does not contain Cucumber/Behave step definitions that execute them.

## Inventory

| File | Domain | Definitions |
|---|---|---:|
| `rest_api_inventory.feature` | All 57 registered REST v1 method/path pairs | 1 outline |
| `broker_plugin_inventory.feature` | All 36 broker plugins | 1 outline |
| `auth_and_setup.feature` | Setup, login, TOTP, route order, DB readiness, logout | 7 |
| `session_lifecycle.feature` | Multi-session cap, heartbeat, rollover, reconnect | 5 |
| `broker_sessions.feature` | Broker login, callbacks, credentials, capabilities | 4 |
| `orders_and_action_center.feature` | Order routing and semi-auto approval | 6 |
| `gtt_orders.feature` | Live GTT support and analyzer limitations | 5 |
| `account_and_depth.feature` | Account collections, margin, open positions, depth | 5 |
| `market_data.feature` | Quotes, history, option chain, instruments | 5 |
| `websocket_streaming.feature` | Proxy protocol, subscriptions, ZMQ fan-in | 6 |
| `sandbox_analyzer.feature` | Analyzer mode and sandbox state | 5 |
| `automation_webhooks.feature` | Chartink, JSON webhooks, Python host | 4 |
| `flow_workflows.feature` | Flow CRUD, execution, webhook, scheduler, monitor | 5 |
| `scalping_and_tools.feature` | Scalping safety/risk plus current analytics tools | 8 |
| `notifications_observability.feature` | Telegram, WhatsApp, EventBus, health, traffic | 8 |
| `admin_and_security.feature` | Admin, IP security, CSP, Remote MCP controls | 4 |
| `historify_and_tools.feature` | Historify jobs/schedules and option tools | 4 |
| `strategy_module_rms.feature` | Multi-leg baskets, signal legs, durable ownership, aggregate-trigger versus execution truth, pending stops, recovery/P&L authority, broker-primary UI truth | 35 |

Current totals:

- Feature files: 18
- Scenario definitions: 120
- Scenario outlines: 6
- Example rows across outlines: 106
- Expanded scenario cases: 220 (`120 - 6 + 106`)

The REST inventory outline is contract coverage, not proof that every endpoint succeeds against every broker. The broker outline proves configuration inventory only; broker-specific behavioral verification remains in broker tests and adapter integration checks.

## Maintenance Rules

1. Add or update a scenario whenever a public method/path, operational mode, persisted state transition, or safety invariant changes.
2. Keep route and service citations implementation-backed. A UI helper route is not evidence for WebSocket proxy behavior.
3. Add registered REST resources to `rest_api_inventory.feature` and `docs/api/README.md` in the same change.
4. Add or remove broker rows in `broker_plugin_inventory.feature` when `broker/*/plugin.json` changes.
5. Record genuine contradictions and intentionally unsupported behavior in `docs/prd/CONFLICTS.md`.
