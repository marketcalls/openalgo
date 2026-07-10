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
   - That template does not exist in the current tree, so the legacy route is unavailable. The React `/pnltracker` page is the supported surface.

4. Two Telegram REST routes are registered placeholders.
   - The webhook validates its secret and update ID, then acknowledges without dispatching the update.
   - Broadcast returns zero successful and zero failed deliveries without fan-out.
   - Documentation must preserve these limitations until the handlers implement delivery.

5. Remote MCP is conditional.
   - Static discovery includes its routes, but runtime registration occurs only with `MCP_HTTP_ENABLED=True`, debug disabled, and `MCP_PUBLIC_URL` configured.
   - Endpoint totals are static source-tree totals, not a guarantee that Remote MCP appears in the default runtime URL map.

## Deliberate Product Decisions

- RESTX Swagger is disabled with `doc=False`. `/api/docs` is intentionally absent and must not be treated as a broken route.
- `services/options_multiorder_service.py` and `services/place_gtt_order_service.py` can queue `optionsmultiorder` and `placegttorder` rows in semi-auto mode, but `services/pending_order_execution_service.py` dispatches neither type. Approval therefore returns `Unknown order type` and rejects broker execution. Documentation must not claim those types are Action Center-supported until the executor is extended or routing is blocked.
- `mcp/mcpserver.py::check_holiday` is registered as an MCP tool but calls the absent `/api/v1/checkholiday` route. The internal `services.market_calendar_service.check_holiday()` function exists; the public REST contract does not. MCP/user documentation omits this tool until its implementation uses a supported path or service.
- Analyzer GTT place, modify, cancel, and orderbook return 501 even though sandbox GTT tables exist.
- Blueprint-route BDD coverage is representative. The complete 57-method RESTX inventory and all 34 broker plugins have explicit scenario-outline rows.

## Resolved During This Sweep

- Added a complete RESTX method/path inventory in `docs/bdd/rest_api_inventory.feature`.
- Added a 34-plugin broker inventory in `docs/bdd/broker_plugin_inventory.feature`.
- Added live account, margin, open-position, and REST depth behavior in `docs/bdd/account_and_depth.feature`.
- Corrected WebSocket source attribution and documented the ZeroMQ bind/connect topology.
- Expanded analyzer GTT unsupported coverage to place, modify, cancel, and orderbook.
- Added session lifecycle, scalping, analytics-tool, Telegram placeholder, startup, and traffic-log behaviors.
