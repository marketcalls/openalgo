# PRD Conflicts And Coverage Gaps

This file lists places where the PRD had to avoid silently choosing between Discovery Map, BDD, and code-level evidence. Items marked as coverage gaps are not direct contradictions, but they are claims the PRD must make even though the BDD suite does not exercise them exhaustively.

## Open Items

1. REST and blueprint endpoint inventory is broader than BDD coverage.
   - Evidence: `DISCOVERY_MAP.md` lists 57 RESTX endpoints, 452 Flask blueprint routes, and 1 app-level route in `Discovery Summary`, `RESTX Endpoint Inventory`, and `Flask Blueprint Route Inventory`; `docs/bdd` contains 56 scenarios across 12 feature files.
   - Impact: PRD FR-022 covers endpoint groups that are not individually scenario-covered.
   - Question: Should BDD stay representative, or should endpoint-level scenarios be added for every public endpoint?

2. Broker matrix is not individually covered by BDD scenarios.
   - Evidence: `DISCOVERY_MAP.md` `Broker Matrix` lists 33 brokers; `docs/bdd/broker_sessions.feature` covers generic broker session and capability behavior, not one scenario per broker.
   - Impact: The PRD can document the 33-broker matrix from discovery, but BDD does not prove every broker row behavior.
   - Question: Should broker support be treated as inventory documentation, or should broker-specific BDD scenarios be added?

3. Positions, holdings, funds, margin, and depth have REST endpoints in discovery but partial BDD coverage.
   - Evidence: `DISCOVERY_MAP.md` `RESTX Endpoint Inventory` lists `/api/v1/positionbook`, `/api/v1/openposition`, `/api/v1/holdings`, `/api/v1/funds`, `/api/v1/margin`, and `/api/v1/depth`; `docs/bdd/sandbox_analyzer.feature` mentions sandbox positions, holdings, and funds, but no dedicated live account or depth scenarios exist.
   - Impact: PRD FR-033, FR-034, FR-035, and FR-044 are discovery-backed but only partially BDD-covered.
   - Question: Should the BDD suite add account-state and depth feature files?

4. WebSocket BDD source comments mix HTTP helper routes with WebSocket proxy actions.
   - Evidence: `DISCOVERY_MAP.md` `WebSocket Streaming` documents WebSocket actions from `websocket_proxy/server.py`; `docs/bdd/websocket_streaming.feature` scenarios cite `blueprints/websocket_example.py` helper routes alongside proxy lines.
   - Impact: PRD WebSocket requirements use the proxy behavior as authoritative and treat helper routes as example and diagnostics routes.
   - Question: Should BDD source comments be adjusted to cite only proxy action handlers where the scenario is about WebSocket messages?

5. TradingView JSON and GoCharting JSON behavior is route-backed in discovery but only lightly described.
   - Evidence: `DISCOVERY_MAP.md` route inventory lists `blueprints/tv_json.py:22` and `blueprints/gc_json.py:22`; `docs/bdd/automation_webhooks.feature` says these routes can call OpenAlgo order placement behavior.
   - Impact: PRD FR-063 states these are automation entry points but does not claim a full payload contract.
   - Question: Should the discovery map be expanded with route internals for TradingView JSON and GoCharting JSON before a fuller PRD requirement is written?

6. Remote MCP has source routes but conditional runtime registration.
   - Evidence: `DISCOVERY_MAP.md` `Conditional Surfaces` says MCP routes register only when `MCP_HTTP_ENABLED=True`; `docs/bdd/admin_and_security.feature` assumes Remote MCP is enabled for the kill-switch scenario.
   - Impact: PRD treats Remote MCP as opt-in and does not count it as always active at runtime.
   - Question: Should BDD include disabled-mode scenarios for Remote MCP?

7. Historify database env var naming is inconsistent.
   - Evidence: `DISCOVERY_MAP.md` `Data Stores` and `Unverified` note that `.sample.env` names `HISTORIFY_DATABASE_URL`, while implementation reads `HISTORIFY_DATABASE_PATH`.
   - Impact: PRD avoids declaring one Historify env var authoritative.
   - Question: Which env var name should public documentation use?

8. Analyzer GTT tables exist, but analyzer GTT services return 501.
   - Evidence: `DISCOVERY_MAP.md` `GTT Orders` and `Unverified` say sandbox GTT tables exist and GTT services return 501 in analyzer mode; `docs/bdd/gtt_orders.feature` covers analyzer modify GTT unsupported but not every analyzer GTT operation.
   - Impact: PRD states analyzer GTT service behavior as unsupported.
   - Question: Should BDD include analyzer place, cancel, and orderbook GTT unsupported scenarios?
