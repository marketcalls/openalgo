# PRD Traceability Appendix

This appendix maps major PRD requirement groups to the discovery-map sections and BDD files that exercise them.

| PRD area | Requirement IDs | Discovery map sections | BDD coverage |
|---|---|---|---|
| Runtime, setup, configuration | FR-001 to FR-007 | `Discovery Summary`, `Entry Points And Runtime`, `Conditional Surfaces` | `docs/bdd/auth_and_setup.feature`, `docs/bdd/websocket_streaming.feature` |
| Authentication, sessions, API keys | FR-008 to FR-014 | `Security And Auth`, `Flask Blueprint Route Inventory` | `docs/bdd/auth_and_setup.feature`, `docs/bdd/broker_sessions.feature`, `docs/bdd/orders_and_action_center.feature` |
| Broker sessions and plugins | FR-015 to FR-019 | `Broker Plugins`, `Broker Matrix`, `GTT Orders` | `docs/bdd/broker_sessions.feature`, `docs/bdd/orders_and_action_center.feature`, `docs/bdd/market_data.feature`, `docs/bdd/gtt_orders.feature` |
| REST API surface | FR-020 to FR-022 | `RESTX API V1`, `RESTX Endpoint Inventory`, `Request Schema Notes` | `docs/bdd/orders_and_action_center.feature`, `docs/bdd/gtt_orders.feature`, `docs/bdd/market_data.feature`, partial only |
| Order lifecycle and Action Center | FR-023 to FR-032 | `Order Execution, Analyzer Mode, And Action Center`, `Events, Logs, Notifications, And Observability` | `docs/bdd/orders_and_action_center.feature`, `docs/bdd/sandbox_analyzer.feature`, `docs/bdd/gtt_orders.feature`, `docs/bdd/notifications_observability.feature` |
| Positions, holdings, funds, margin | FR-033 to FR-035 | `RESTX Endpoint Inventory`, `Flask Blueprint Route Inventory`, `Analyzer And Sandbox` | `docs/bdd/sandbox_analyzer.feature`, partial only |
| GTT orders | FR-036 to FR-039 | `GTT Orders` | `docs/bdd/gtt_orders.feature` |
| Market data, history, options | FR-040 to FR-047 | `Market Data And History`, `Data Stores`, `RESTX Endpoint Inventory`, `Flask Blueprint Route Inventory` | `docs/bdd/market_data.feature`, `docs/bdd/historify_and_tools.feature`, partial for depth |
| WebSocket streaming | FR-048 to FR-054 | `WebSocket Streaming`, `Conditional Surfaces` | `docs/bdd/websocket_streaming.feature` |
| Analyzer and sandbox mode | FR-055 to FR-059 | `Analyzer And Sandbox`, `Order Execution, Analyzer Mode, And Action Center`, `GTT Orders` | `docs/bdd/sandbox_analyzer.feature`, `docs/bdd/orders_and_action_center.feature`, `docs/bdd/gtt_orders.feature` |
| Automation, Flow, Python Strategy | FR-060 to FR-070 | `Automation Surfaces`, `Flask Blueprint Route Inventory` | `docs/bdd/automation_webhooks.feature`, `docs/bdd/flow_workflows.feature` |
| Notifications, observability, admin, Historify | FR-071 to FR-080 | `Events, Logs, Notifications, And Observability`, `Data Stores`, `Flask Blueprint Route Inventory`, `Security And Auth` | `docs/bdd/notifications_observability.feature`, `docs/bdd/admin_and_security.feature`, `docs/bdd/historify_and_tools.feature` |
| Broker matrix | Broker support section | `Broker Plugins`, `Broker Matrix` | Generic broker behavior in `docs/bdd/broker_sessions.feature`; individual broker rows are not scenario-covered |
| Operational modes | Operational modes section | `Order Execution, Analyzer Mode, And Action Center`, `GTT Orders`, `Analyzer And Sandbox` | `docs/bdd/orders_and_action_center.feature`, `docs/bdd/sandbox_analyzer.feature`, `docs/bdd/gtt_orders.feature` |
| Security posture | Security model section | `Security And Auth`, `Entry Points And Runtime` | `docs/bdd/auth_and_setup.feature`, `docs/bdd/admin_and_security.feature` |
| Performance limits | Performance section | `Security And Auth`, `Order Execution, Analyzer Mode, And Action Center`, `Market Data And History`, `WebSocket Streaming`, `Automation Surfaces`, `Events, Logs, Notifications, And Observability` | Covered where behavior appears in related BDD files; numeric limits are mostly discovery-only |
