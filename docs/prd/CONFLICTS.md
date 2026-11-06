# PRD Conflicts And Coverage Notes

This file records unresolved implementation/documentation conflicts and deliberate limits. Resolved audit items remain listed separately so they are not reintroduced by later edits.

## Open Items

1. Historify uses two environment variable names.
   - `.sample.env` and `blueprints/system_permissions.py` read `HISTORIFY_DATABASE_URL`.
   - `database/historify_db.py` reads `HISTORIFY_DATABASE_PATH`.
   - Public documentation must describe the mismatch until the implementation standardizes one name.

2. TradingView JSON and GoCharting JSON have registered automation routes but no fully specified payload contract in the current discovery set.
   - `blueprints/tv_json.py` and `blueprints/gc_json.py` are authoritative.
   - The PRD treats them as automation entry points without claiming that every payload variant is documented.

3. `/pnltracker/legacy` references an absent template.
   - `blueprints/pnltracker.py` renders `templates/pnltracker.html`.
   - That template does not exist in the current tree, so the legacy route is unavailable. The React `/pnl-tracker` page is the supported surface.

4. Two Telegram REST routes are registered placeholders.
   - The webhook validates its secret and update ID, then acknowledges without dispatching the update.
   - Broadcast returns zero successful and zero failed deliveries without fan-out.
   - Documentation must preserve these limitations until the handlers implement delivery.

5. Remote MCP is conditional.
   - Static discovery includes its routes, but runtime registration occurs only with `MCP_HTTP_ENABLED=True`, debug disabled, and `MCP_PUBLIC_URL` configured.
   - Endpoint totals are static source-tree totals, not a guarantee that Remote MCP appears in the default runtime URL map.

6. Broker-key masking differs from the zero-character rule in `CLAUDE.md`.
   - `blueprints/broker_config.py:_mask` and `blueprints/broker_credentials.py:mask_secret` return up to six API-key/market-key prefix characters plus a fixed mask; secrets receive only the mask and raw lengths are omitted.
   - The current design reference records the observed response. Reconciling the stronger invariant requires a separate code decision.

7. Action Center does not preserve every uncertain transport result as an unknown broker state.
   - PlaceOrder reports a possibly sent, unanswered write with HTTP 502 and an order-book reconciliation message.
   - `services/pending_order_execution_service.py:execute_approved_order` marks unsuccessful results `rejected` unless they follow the proven pre-send refusal path, and the approval route returns an execution-failed warning.
   - Do not treat that stored rejection alone as proof the broker rejected the order, or infer automatic safe retry. A restart-left `submitting` row is separately protected against automatic resend.

## Deliberate Product Decisions

- RESTX Swagger is disabled with `doc=False`. `/api/docs` is intentionally absent and must not be treated as a broken route.
- `mcp/mcpserver.py::check_holiday` is registered as an MCP tool but calls the absent `/api/v1/checkholiday` route. The internal `services.market_calendar_service.check_holiday()` function exists; the public REST contract does not. The MCP reference labels this declared tool unavailable until its implementation uses a supported path or service.
- Blueprint-route BDD coverage is representative. The complete 74-method RESTX inventory and all 38 broker plugins have explicit scenario-outline rows.

## Resolved During This Sweep

- Added Action Center dispatch and broker-result tracking for `optionsmultiorder` and `placegttorder`; unsupported GTT brokers still fail through the service's HTTP 501 capability gate.
- Added a complete RESTX method/path inventory in `docs/bdd/rest_api_inventory.feature`.
- Added a 38-plugin broker inventory in `docs/bdd/broker_plugin_inventory.feature`.
- Added live account, margin, open-position, and REST depth behavior in `docs/bdd/account_and_depth.feature`.
- Corrected WebSocket source attribution and documented the ZeroMQ bind/connect topology.
- Corrected analyzer GTT coverage: place, modify, cancel and orderbook use the sandbox GTT manager; HTTP 501 is the live missing-broker-module gate.
- Added session lifecycle, scalping, analytics-tool, Telegram placeholder, startup, and traffic-log behaviors.
