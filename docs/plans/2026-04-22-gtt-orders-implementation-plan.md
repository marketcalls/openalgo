# GTT (Good Till Triggered) Orders — Phased Implementation Plan

**Status:** Draft
**Owner:** Rajandran R
**Created:** 2026-04-22
**Companion doc:** Product Design Report (conversation artifact)
**Reference broker spec:** `zerodha-api-docs/06-gtt.md`

---

## 0. Legend

- **Goal** — what this phase achieves end-to-end.
- **Prereqs** — must-haves from earlier phases.
- **Tasks** — numbered deliverables (tick-list ready).
- **Files** — new (N) vs edited (E).
- **Acceptance** — hard gates; phase is not done until every item passes.
- **Exit** — the state the codebase is left in.

Phases ship independently. Each phase ends in a mergeable state; nothing half-built persists across phases.

---

## Phase 0 — Decisions & Alignment (no code)

**Goal:** lock the handful of design choices that otherwise cause re-work in later phases.

### Decisions to close

| # | Question | Default proposal |
|---|----------|------------------|
| 0.1 | Which brokers get GTT in v1? | Zerodha (ref). Fyers, Upstox, Angel as Phase 6 candidates. All others ship "not supported" stub. |
| 0.2 | OCO margin mode in sandbox | `max` (block margin for the larger leg only). Make configurable via `SandboxConfig.gtt_oco_margin_mode = max \| sum`. |
| 0.3 | Semi-auto (Action Center) routing | Allow **place** queue; disallow **modify/cancel** queue (stale queued actions + triggered GTTs cause anomalies). |
| 0.4 | Default expiry | 365 days from placement (Zerodha parity). Accept optional `expires_at` in request. |
| 0.5 | Sandbox GTT out-of-market-hours behaviour | Skip evaluation outside market hours (mirrors existing `execution_engine` behaviour). Still counts toward expiry. |
| 0.6 | Live-mode GTT cache | None. Every `gttorderbook` call hits the broker, same as live `orderbook`. |
| 0.7 | API naming | `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook` (lowercase, no separators — matches existing style). |
| 0.8 | ID naming | OpenAlgo uses `trigger_id` in JSON (broker-neutral); sandbox table column `gtt_id` (internal). |

### Exit

- This document marked **Approved** by Rajandran.
- Any "default proposal" overrides captured below:
  > *(leave blank until review)*

---

## Phase 1 — Foundation / Plumbing

**Goal:** land the data model, validation schemas, event vocabulary, and broker capability flag. Nothing user-visible; nothing functionally live.

**Prereqs:** Phase 0 closed.

### Tasks

1. **DB schema**
   - (N) `database/gtt_db.py` — SQLAlchemy ORM models `SandboxGTT`, `SandboxGTTLeg` (schema per design doc §5.1).
   - Indexes: `(user_id, gtt_status)`, `(symbol, exchange)`, `gtt_id` unique, FK `legs.gtt_id → gtt.gtt_id`.

2. **Hand-rolled migration**
   - (N) `upgrade/migrate_gtt.py` — idempotent `CREATE TABLE IF NOT EXISTS` pair + default row in `SandboxConfig` for `gtt_oco_margin_mode=max`.
   - (E) `upgrade/migrate_all.py` — append `("migrate_gtt.py", "GTT Order Support")` **after** `migrate_sandbox.py`.

3. **Marshmallow schemas**
   - (E) `restx_api/schemas.py` — add `PlaceGTTOrderSchema`, `ModifyGTTOrderSchema`, `CancelGTTOrderSchema`, `GTTOrderBookSchema`. Leg-count validation in `@post_load`.

4. **Event classes**
   - (E) `events/order_events.py` — add `GTTPlacedEvent`, `GTTFailedEvent`, `GTTModifiedEvent`, `GTTModifyFailedEvent`, `GTTCancelledEvent`, `GTTCancelFailedEvent`, `GTTTriggeredEvent`, `GTTExpiredEvent`.
   - (E) `events/__init__.py` — export + add to `__all__`.

5. **Broker capability registry**
   - (E) `broker/__init__.py` — dict `BROKER_GTT_SUPPORT = {"zerodha": True, ...False}` + helper `broker_gtt_supported(broker_name) -> bool`.

6. **Logging vocabulary**
   - No code change. Reserve `api_type` values: `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook`, `gtttriggered`, `gttexpired`. Document in `database/apilog_db.py` docstring.

### Files touched

- **New:** `database/gtt_db.py`, `upgrade/migrate_gtt.py`
- **Edited:** `upgrade/migrate_all.py`, `restx_api/schemas.py`, `events/order_events.py`, `events/__init__.py`, `broker/__init__.py`

### Acceptance

- `python upgrade/migrate_all.py` runs twice on a fresh DB with no errors; tables exist after first run, no-op on second.
- Unit tests for schemas: single-leg accepts 1-leg list; two-leg requires 2 legs with opposite-direction triggers relative to `last_price`; crypto quantity float-accepted.
- `from events import GTTPlacedEvent` imports; publishing a dummy event doesn't explode the bus.
- `broker_gtt_supported("zerodha")` returns `True`; `broker_gtt_supported("unknown")` returns `False`.

### Exit

DB has GTT tables; validators + events exist as importable symbols; nothing else changed.

---

## Phase 2 — Live Path (Zerodha reference)

**Goal:** end-to-end live GTT: cURL → REST → service → Zerodha API → response. Only Zerodha. Analyze mode still errors out ("sandbox not ready").

**Prereqs:** Phase 1.

### Tasks

1. **Zerodha broker module**
   - (N) `broker/zerodha/mapping/gtt_data.py` — `transform_place_gtt(data)` builds Kite's `{type, condition, orders}` from OpenAlgo `{trigger_type, legs, symbol, exchange, last_price}`. Analogous `transform_modify_gtt`.
   - (N) `broker/zerodha/api/gtt_api.py`:
     - `place_gtt_order(data, auth)` → `POST /gtt/triggers` → `(res_obj, response_dict, trigger_id)`
     - `modify_gtt_order(data, auth)` → `PUT /gtt/triggers/{id}` → `(response_dict, status_code)`
     - `cancel_gtt_order(trigger_id, auth)` → `DELETE /gtt/triggers/{id}` → `(response_dict, status_code)`
     - `get_gtt_book(auth)` → `GET /gtt/triggers` → `(response_dict, status_code)`
   - Reuse `get_httpx_client()`, `X-Kite-Version: 3`, `Authorization: token ...`, `application/x-www-form-urlencoded`.

2. **Service layer**
   - (N) `services/place_gtt_order_service.py` — `place_gtt_order(...)` + `place_gtt_order_with_auth(...)` + `emit_analyzer_error(...)`. Branch: analyze → raise `NotImplementedError`-equivalent 501; live → broker dispatch. Event emission: `GTTPlacedEvent` / `GTTFailedEvent`.
   - (N) `services/modify_gtt_order_service.py`
   - (N) `services/cancel_gtt_order_service.py`
   - (N) `services/gtt_orderbook_service.py`
   - Constants: `API_TYPE = "placegttorder"` etc.

3. **REST endpoints**
   - (N) `restx_api/place_gtt_order.py`, `restx_api/modify_gtt_order.py`, `restx_api/cancel_gtt_order.py`, `restx_api/gtt_orderbook.py`. Each mirrors `place_order.py`: `@limiter.limit(ORDER_RATE_LIMIT)`, schema `.load()`, service call, tuple unpack, `make_response`.
   - (E) `restx_api/__init__.py` — import namespaces + `api.add_namespace(..., path="/placegttorder")` etc.

4. **Semi-auto / Action Center hook**
   - (E) `services/order_router_service.py` — extend `should_route_to_pending(api_key, api_type)` to recognise `placegttorder` (queue) and explicitly return `False` for `modifygttorder` / `cancelgttorder` (per Phase 0.3).

5. **Playground collection**
   - (N) `collections/openalgo/IN_stock/orders/place_gtt_order.bru` — single-leg + OCO example bodies.
   - (N) `collections/openalgo/IN_stock/orders/modify_gtt_order.bru`
   - (N) `collections/openalgo/IN_stock/orders/cancel_gtt_order.bru`
   - (N) `collections/openalgo/IN_stock/orders/gtt_orderbook.bru`
   - (E) `blueprints/playground.py` — `categorize_endpoint()` routes these to `"orders"`.

### Files touched

- **New:** 2 in `broker/zerodha/`, 4 in `services/`, 4 in `restx_api/`, 4 in `collections/openalgo/IN_stock/orders/`
- **Edited:** `restx_api/__init__.py`, `services/order_router_service.py`, `blueprints/playground.py`

### Acceptance

- `curl -X POST /api/v1/placegttorder` with valid body + valid Zerodha API key:
  - Creates a GTT on Zerodha dashboard (visually verified).
  - Returns `{status: success, trigger_id, mode: "live"}` in ≤ 2 s.
- `curl -X POST /api/v1/gttorderbook` returns the freshly created GTT.
- `curl -X POST /api/v1/modifygttorder` with new price → broker reflects change.
- `curl -X POST /api/v1/cancelgttorder` → broker reflects cancellation.
- Analyze mode on → all four endpoints return `501 {status: error, message: "Sandbox GTT support not yet implemented"}`. No crashes.
- Order log rows written for each call (visible in `/logs`).
- Playground lists new endpoints under "orders" category; body prefilled.

### Exit

Live GTT fully usable via REST + Playground on Zerodha. Other brokers: 501 from `broker_gtt_supported` check in services. Analyze mode: 501 from service layer.

---

## Phase 3 — Sandbox Parity

**Goal:** analyze-mode GTT behaves identically to live on Zerodha: placements persist, monitor fires on trigger, margin accounting reconciles.

**Prereqs:** Phase 2.

### Tasks

1. **Sandbox GTT manager**
   - (N) `sandbox/gtt_manager.py`
     - `place_gtt(gtt_data, user_id)` — validate, compute margin (sum for `single`, `max` or `sum` per config for `two-leg`), `fund_manager.block_margin`, persist rows, return `{status, trigger_id}`.
     - `modify_gtt(trigger_id, gtt_data, user_id)` — under `FundManager._lock`: release old margin, revalidate, block new margin, update rows.
     - `cancel_gtt(trigger_id, user_id)` — release margin, mark `cancelled`.
     - `list_gtts(user_id, status_filter=None)` — read rows.
   - Trade-ID style for auto-fired orders: `ORDER-GTT-<ts>-<uuid8>` (distinguishable in `sandbox_trades`).

2. **Sandbox service wrapper**
   - (E) `services/sandbox_service.py` — add `sandbox_place_gtt_order`, `sandbox_modify_gtt_order`, `sandbox_cancel_gtt_order`, `sandbox_gtt_orderbook`. Each resolves `user_id` from `api_key` then calls `gtt_manager`.
   - (E) Phase-2 service files: remove the 501 branch; call `sandbox_service.sandbox_*` when `get_analyze_mode()`.

3. **Polling monitor**
   - (E) `sandbox/execution_engine.py`:
     - Inside `check_and_execute_pending_orders()`, after regular-order batch, call new `_check_pending_gtts()`.
     - Query `SandboxGTT` join `SandboxGTTLeg` where `gtt_status='active'`.
     - Reuse `_fetch_quotes_batch()` (symbols from legs).
     - Evaluate: BUY leg `ltp >= trigger_price`; SELL leg `ltp <= trigger_price`.
     - On trigger: release GTT margin, call `order_manager.place_order()` with leg payload (which blocks its own margin), write `triggered_order_id` onto leg, if `two-leg` cancel sibling leg + release its (already released or separately held) margin per Phase 0.2 rule, mark parent `triggered`, publish `GTTTriggeredEvent`.
   - Out-of-market-hours short-circuit using the existing `is_market_open()` helper.

4. **WebSocket monitor**
   - (E) `sandbox/websocket_execution_engine.py`:
     - Add `_pending_gtts_index: dict[str, list[str]]` (symbol → list of `gtt_id`).
     - On subscribe/startup: rebuild index from DB (symmetry with existing order index).
     - On tick: evaluate GTTs for the ticking symbol via same trigger logic as §3.3.
     - Symbol refcounting already handles shared symbols.

5. **Catch-up**
   - (E) `sandbox/catch_up_processor.py` — `catch_up_gtts()` after master-contract download: one multiquotes call for all unique GTT symbols; fire any triggers already breached.

6. **Expiry watcher**
   - (E) `sandbox/execution_thread.py` — add APScheduler job (hourly) that flips `active` GTTs with `expires_at < now` to `expired`, releases margin, publishes `GTTExpiredEvent`.

7. **Margin reconciliation**
   - `fund_manager.reconcile_margin(user_id, auto_fix=True)` already exists. Add GTT's `margin_blocked` sum to its expected-used-margin calc so it doesn't false-flag.
   - (E) `sandbox/fund_manager.py`

### Files touched

- **New:** `sandbox/gtt_manager.py`
- **Edited:** `services/sandbox_service.py`, Phase-2 service files, `sandbox/execution_engine.py`, `sandbox/websocket_execution_engine.py`, `sandbox/catch_up_processor.py`, `sandbox/execution_thread.py`, `sandbox/fund_manager.py`

### Acceptance

- **Placement path:** analyze-mode `placegttorder` persists rows in `sandbox_gtt` + `sandbox_gtt_legs`; `used_margin` increases by the blocked amount; `available_balance` decreases symmetrically.
- **Trigger path (single-leg):** set trigger $1 from LTP in a test instrument; within one poll cycle (≤ 5 s) or immediately on the next WS tick, leg is marked `triggered`, a row appears in `sandbox_orders` with status eventually `complete`, GTT margin is released, order margin is blocked.
- **Trigger path (OCO):** same with two legs; only one fires, the other becomes `cancelled`, parent `triggered`, no double-margin.
- **Cancel path:** `cancelgttorder` → `gtt_status='cancelled'`, margin released.
- **Modify path:** `modifygttorder` → new trigger reflected; margin diff reconciled.
- **Restart test:** place GTT, stop app, move price past trigger externally (use a mock LTP), start app → catch-up fires the trigger on boot.
- **Expiry test:** manually set `expires_at = now()-1h` on an active GTT, wait one hour (or force the scheduler tick) → status flips to `expired`, margin released.
- **Reconciliation:** `reconcile_margin` reports 0 discrepancies after a mixed sequence of regular orders, GTT placements, triggers, and cancellations.

### Exit

Analyze ↔ live functional parity for GTT. Users can test GTT strategies entirely in sandbox.

---

## Phase 4 — Surface Polish

**Goal:** every non-REST surface exposes GTT — logs, socketio, telegram, toasts, React orderbook, Jinja fallback, SDK, Flow editor.

**Prereqs:** Phase 2 minimum; Phase 3 for analyze-mode surfaces.

### Task Group A — Subscribers & alerts

1. (E) `subscribers/log_subscriber.py` — `on_gtt_placed/modified/cancelled/triggered/expired/failed` handlers. Each submits `async_log_order(event.api_type, event.request_data, event.response_data)`.
2. (E) `subscribers/socketio_subscriber.py`:
   - Live mode: `socketio.emit("gtt_event", {...})` for placed/modified/cancelled; `socketio.emit("gtt_triggered", {...})` for triggers.
   - Analyze mode: piggyback on existing `analyzer_update` emitter.
3. (E) `subscribers/telegram_subscriber.py` — dispatches to `telegram_alert_service.send_gtt_alert(api_type, gtt_data, response, api_key)`.
4. (E) `services/telegram_alert_service.py` — add templates + `format_gtt_details()` per design §12.
5. (E) `subscribers/__init__.py` — register all GTT topics.

### Task Group B — React frontend

6. (E) `frontend/src/api/trading.ts` — client wrappers `placeGttOrder`, `modifyGttOrder`, `cancelGttOrder`, `getGttOrderbook` on `webClient`.
7. (E) `frontend/src/pages/OrderBook.tsx`:
   - Wrap existing table in `<Tabs defaultValue="orders">`.
   - New `<GttTab />` component renders columns per design §14.3.
   - Listen for `gtt_event` and `gtt_triggered` via `socketio`; auto-refresh.
   - Gate "+ Place GTT" button on `broker_gtt_supported` (exposed via an existing `/api/v1/session` or similar; add a small endpoint if absent).
8. (N) `frontend/src/components/orders/GttTab.tsx`
9. (N) `frontend/src/components/orders/PlaceGttModal.tsx` — single / two-leg sub-tabs, auto-filled `last_price` via a quote call on symbol blur.
10. (N) `frontend/src/components/orders/ModifyGttModal.tsx`
11. (E) `frontend/src/utils/toast.ts` consumers — new call sites use category `'orders'` (no new category).

### Task Group C — Jinja fallback

12. (N) `templates/gtt_orderbook.html` — mirrors `templates/orderbook.html`.
13. (E) `templates/orderbook.html` — tab links to `/orderbook` ↔ `/gtt_orderbook`.
14. (E) `blueprints/orders.py` — add `/gtt_orderbook` GET route (live/analyze branching identical to `/orderbook`).

### Task Group D — Python SDK

15. (E) `src/openalgo/orders.py` (or equivalent client module) — add `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook` methods with docstrings mirroring `placeorder` style.
16. Pre-request leg-count validation.
17. SDK version bump (minor).

### Task Group E — Flow editor (4-place rule)

18. (E) `services/flow_openalgo_client.py` — methods `place_gtt`, `modify_gtt`, `cancel_gtt`, `get_gtt_orderbook`.
19. (E) `services/flow_executor_service.py`:
    - `NodeExecutor.execute_place_gtt / execute_modify_gtt / execute_cancel_gtt / execute_gtt_orderbook`.
    - `execute_node_chain` — four new `elif` branches (`placeGtt`, `modifyGtt`, `cancelGtt`, `gttOrderbook`).
20. (E) `frontend/src/lib/flow/constants.ts` — `DEFAULT_NODE_DATA` entries + `NODE_DEFINITIONS.ACTIONS` entries.
21. (N) `frontend/src/components/flow/nodes/PlaceGttNode.tsx`
22. (N) `frontend/src/components/flow/nodes/ModifyGttNode.tsx`
23. (N) `frontend/src/components/flow/nodes/CancelGttNode.tsx`
24. (N) `frontend/src/components/flow/nodes/GttOrderbookNode.tsx`
25. (E) `frontend/src/components/flow/nodes/index.ts` — register in `nodeTypes`.
26. (E) `frontend/src/components/flow/panels/ConfigPanel.tsx` — forms per node type; OCO renders two-leg sub-form.
27. (E) `frontend/src/types/flow.ts` — new `PlaceGttNodeData`, `ModifyGttNodeData`, `CancelGttNodeData`, `GttOrderbookNodeData`.

### Acceptance

- Place GTT in live mode → Telegram alert arrives within 5 s with formatted message.
- Trigger GTT in sandbox → React orderbook row transitions `active → triggered` without manual refresh.
- `pip install openalgo && python -c "from openalgo import api; api(...).placegttorder(...)"` — SDK smoke test passes.
- Build a Flow with Place GTT → (wait) → Cancel GTT (using `{{gttResult.trigger_id}}`) — workflow executes end-to-end in both live and analyze modes.
- Toast appears for each GTT lifecycle event; hidden when user disables 'orders' alert category.
- Jinja `/gtt_orderbook` route renders the same data under session-based auth.

### Exit

GTT has feature parity with regular orders across every existing OpenAlgo surface.

---

## Phase 5 — Documentation & QA

**Goal:** the GTT feature is documented, tested, and shippable.

**Prereqs:** Phase 4.

### Tasks

1. **API reference**
   - (N) `docs/api/order-management/placegttorder.md`
   - (N) `docs/api/order-management/modifygttorder.md`
   - (N) `docs/api/order-management/cancelgttorder.md`
   - (N) `docs/api/order-information/gttorderbook.md`
   - Template: endpoint URL block, sample JSON, cURL, response, request-body table, response-fields table, Notes.
2. **Concepts & how-to**
   - (N) `docs/api/order-management/gtt_concepts.md` — single vs OCO, status machine diagram, expiry rules, margin semantics, sandbox ↔ live parity notes, broker support matrix.
3. **Index updates**
   - (E) `docs/api/order-management/README.md`, `docs/api/order-information/README.md` — link the new files.
   - (E) root `README.md` — add GTT to feature list.
   - (E) `CLAUDE.md` — one-line pointer: "GTT events = `GTT*Event` in `events/order_events.py`; 4-place integration same as other order nodes."
4. **User guide**
   - (N) `docs/userguide/gtt-orders.md` — screenshots of the UI tab + Place GTT modal, sandbox walkthrough.
5. **Test plan**
   - (N) `docs/test/gtt-test-plan.md` — the matrix in the Acceptance column of each phase, formalised.
6. **Release notes**
   - (E) `docs/CHANGELOG.md` — new entry.

### Acceptance

- `docs/api/order-management/README.md` lists all four new endpoints.
- `mkdocs` (or whatever docs builder is in use) builds cleanly.
- Test plan executed manually on Zerodha sandbox broker account — all rows green.
- No dead links (`markdown-link-check` or equivalent).

### Exit

Docs + tests complete. Feature is ready to ship for Zerodha users.

---

## Phase 6 — Broker Fan-out

**Goal:** roll GTT to additional brokers. Each broker is one independent PR.

**Prereqs:** Phase 5.

### Template per broker

1. (N) `broker/<name>/api/gtt_api.py` — same four functions as Zerodha module, mapped to broker's native GTT / OCO / Price-Alert API.
2. (N) `broker/<name>/mapping/gtt_data.py` — request/response transform.
3. (E) `broker/__init__.py` — flip `BROKER_GTT_SUPPORT[<name>] = True`.
4. (E) `docs/api/order-management/gtt_concepts.md` — update support matrix row.

### Per-broker acceptance

- Place / modify / cancel / book cycle verified against a live broker account.
- Broker-specific quirks documented in a `broker/<name>/README.md` or equivalent (e.g., "Broker X does not support OCO; `two-leg` requests return 501").

### Suggested order

1. Fyers
2. Upstox
3. Angel One
4. Dhan
5. 5Paisa / others

Parallelisable across contributors; no cross-dependency.

### Exit

GTT supported on all brokers that expose a GTT-equivalent API. Brokers without native support continue to return a clean 501.

---

## Risk & Mitigation Summary

| Risk | Mitigation | Phase |
|------|------------|-------|
| Sandbox trigger races with tick volatility | Use same duplicate-trade guard as `execution_engine._process_order` (lines 214-233 pattern). | 3 |
| OCO double-margin when broker charges sum vs. our `max` default | Configurable `gtt_oco_margin_mode` in `SandboxConfig`. | 0, 3 |
| GTT modify arrives after GTT already triggered | Service-layer pre-check: re-read status before dispatch; return `{status: error, message: "GTT already triggered"}` 409. | 2 |
| Broker GTT expires silently; OpenAlgo shows stale `active` | Nightly reconciliation job pulls `gttorderbook` from broker in live mode, diffs against last-seen state, logs & emits events for state changes. (Optional Phase 6 enhancement.) | 6+ |
| Semi-auto queue collides with GTT triggers | Disallow semi-auto for modify/cancel (Phase 0.3). | 2 |
| Order-logs table bloat | No new schema; reuses `order_logs`. If volume becomes a concern, apply the same retention policy as regular orders. | — |

---

## Cross-Phase File Index

| Surface | New files | Edited files |
|---------|-----------|--------------|
| DB | `database/gtt_db.py`, `upgrade/migrate_gtt.py` | `upgrade/migrate_all.py` |
| REST | `restx_api/{place,modify,cancel}_gtt_order.py`, `restx_api/gtt_orderbook.py` | `restx_api/__init__.py`, `restx_api/schemas.py` |
| Services | `services/{place,modify,cancel}_gtt_order_service.py`, `services/gtt_orderbook_service.py` | `services/sandbox_service.py`, `services/order_router_service.py`, `services/telegram_alert_service.py`, `services/flow_openalgo_client.py`, `services/flow_executor_service.py` |
| Broker (Zerodha) | `broker/zerodha/api/gtt_api.py`, `broker/zerodha/mapping/gtt_data.py` | `broker/__init__.py` |
| Events | — | `events/order_events.py`, `events/__init__.py` |
| Subscribers | — | `subscribers/__init__.py`, `subscribers/log_subscriber.py`, `subscribers/socketio_subscriber.py`, `subscribers/telegram_subscriber.py` |
| Sandbox | `sandbox/gtt_manager.py` | `sandbox/execution_engine.py`, `sandbox/websocket_execution_engine.py`, `sandbox/catch_up_processor.py`, `sandbox/execution_thread.py`, `sandbox/fund_manager.py` |
| Blueprints | — | `blueprints/orders.py`, `blueprints/playground.py` |
| Frontend (React) | `components/orders/{GttTab,PlaceGttModal,ModifyGttModal}.tsx`, `components/flow/nodes/{PlaceGtt,ModifyGtt,CancelGtt,GttOrderbook}Node.tsx` | `pages/OrderBook.tsx`, `api/trading.ts`, `lib/flow/constants.ts`, `components/flow/nodes/index.ts`, `components/flow/panels/ConfigPanel.tsx`, `types/flow.ts` |
| Jinja | `templates/gtt_orderbook.html` | `templates/orderbook.html` |
| Playground | 4 `.bru` files under `collections/openalgo/IN_stock/orders/` | `blueprints/playground.py` |
| SDK | — | `src/openalgo/orders.py` (or client module) |
| Docs | 5 new md files under `docs/api/` + `docs/userguide/gtt-orders.md` + `docs/test/gtt-test-plan.md` | `docs/api/*/README.md`, root `README.md`, `CLAUDE.md`, `docs/CHANGELOG.md` |

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-04-22 | Claude (Opus 4.7) | Initial draft. |
