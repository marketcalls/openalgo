# BDD Coverage

This directory contains Gherkin scenarios for current OpenAlgo behavior. Each scenario has a source comment immediately above it with at least one route file and line number, plus service citations where needed.

## Inventory

| File | Domain | Scenarios |
|---|---|---:|
| `auth_and_setup.feature` | Setup, login, 2FA, logout | 5 |
| `broker_sessions.feature` | Broker login, callbacks, credentials | 4 |
| `orders_and_action_center.feature` | Order placement and semi-auto approval | 6 |
| `gtt_orders.feature` | GTT place, modify, cancel, orderbook | 4 |
| `market_data.feature` | Quotes, history, options, instruments | 5 |
| `websocket_streaming.feature` | WebSocket examples and proxy behavior | 5 |
| `sandbox_analyzer.feature` | Analyzer mode and sandbox state | 5 |
| `automation_webhooks.feature` | Chartink, Strategy, TradingView, GoCharting, Python Strategy | 5 |
| `flow_workflows.feature` | Flow CRUD, activation, execution, webhook, monitor | 5 |
| `notifications_observability.feature` | Telegram, WhatsApp, health, notifications | 4 |
| `admin_and_security.feature` | Admin system, CSP, OAuth/MCP kill switch | 4 |
| `historify_and_tools.feature` | Historify and options tools | 4 |

Total feature files: 12.

Total scenarios: 56.

## Notes

- These scenarios document behavior for review and test planning. They are not wired to step definitions in this repository.
- Ambiguities and mismatches found during discovery are tracked in `REVIEW_QUEUE.md`.
