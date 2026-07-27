# GTT (Good Till Triggered) Orders — Phased Implementation Plan

**Status:** Phase 2 + early Phase 6 (Dhan) shipped; Phase 3 (sandbox) and Phases 4–5 in progress
**Owner:** Rajandran R
**Created:** 2026-04-22
**Companion doc:** Product Design Report (conversation artifact)
**Reference broker specs:** `zerodha-api-docs/06-gtt.md`, `dhan-api-v2-docs/05-forever-order.md`

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
| 0.5 | Sandbox GTT out-of-market-hours behaviour | No market-hours gate in the GTT monitor. Evaluation runs whenever the sandbox engine runs, and catch-up fires on startup regardless of session state. Rationale: `sandbox/execution_engine.py` and `sandbox/websocket_execution_engine.py` do **not** call `is_market_open()` today (only `position_manager.py:1138` does, for square-off). Adding a gate here would silently delay catch-up until the next session and diverge from regular-order semantics. Expiry clock is wall-clock, not session-based. |
| 0.6 | Live-mode GTT cache | None. Every `gttorderbook` call hits the broker, same as live `orderbook`. |
| 0.7 | API naming | `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook` (lowercase, no separators — matches existing style). |
| 0.8 | ID naming | OpenAlgo uses `trigger_id` in JSON (broker-neutral); sandbox table column `gtt_id` (internal). |
| 0.9 | Sandbox trigger-evaluation concurrency | **Atomic leg-level claim.** Three paths (polling engine, WebSocket engine, startup catch-up) can all observe the same crossed trigger. The existing `_process_order` duplicate guard (`execution_engine.py:217`) only dedupes after a trade row exists for a given `orderid` — it cannot catch the case where each path independently calls `order_manager.place_order()` and each generates a different `orderid`. All three paths must instead funnel through a single `gtt_manager.try_claim_trigger(leg_id)` helper that performs a **conditional UPDATE** on `sandbox_gtt_legs.leg_status` from `pending → triggering` (broker-agnostic CAS; works on SQLite + Postgres + MySQL). Only the path whose UPDATE returns `rowcount == 1` calls `place_order()`; others back off silently. |
| 0.10 | Action Center support in **analyze mode** | **YES** — `should_route_to_pending` is mode-agnostic; analyze-mode users with `order_mode = semi_auto` get the same approval gate. On approval the queued GTT is routed to the **sandbox** GTT engine, not the broker. The dispatch helper inside `approve_pending_order` calls the same `place_gtt_order_with_auth(...)` service used by direct REST callers; the service itself reads `get_analyze_mode()` and routes to live broker vs. sandbox engine. This gives analyze-mode parity for free with no separate semi-auto-sandbox code path. |
| 0.11 | Mode-binding for queued GTT | The queued order JSON includes a `_meta.openalgo_mode` field (`"live"` or `"analyze"`) captured at **queue time**. `approve_pending_order` re-reads the user's current mode and refuses with HTTP 409 if it has changed between queue and approve (rare but possible if the operator toggles `/auth/analyzer-toggle` mid-queue). Without this guard, a GTT queued in live mode could be approved while the user is in analyze, silently misrouting; or vice versa, exposing real funds to a sandbox-grade approval. |

### Exit

- This document marked **Approved** by Rajandran.
- Any "default proposal" overrides captured below:
  > *(leave blank until review)*

---

## Phase 1 — Foundation / Plumbing

**Goal:** land the data model, validation schemas, and event vocabulary. Nothing user-visible; nothing functionally live.

**Prereqs:** Phase 0 closed.

### Tasks

1. **DB schema**
   - (N) `database/gtt_db.py` — SQLAlchemy ORM models `SandboxGTT`, `SandboxGTTLeg` (schema per design doc §5.1).
   - `SandboxGTT.gtt_status` enum: `active`, `triggering`, `triggered`, `cancelled`, `expired`, `rejected`.
   - `SandboxGTTLeg.leg_status` enum: `pending`, `triggering`, `triggered`, `cancelled`. The `triggering` state is the atomic-claim target (Phase 0.9); a `triggering` row is writable by (a) the claim winner on success, (b) `_fire_leg` on failure reverting to `pending`, or (c) `reclaim_stranded_legs` reverting to `pending` after the claim timeout. Nothing else.
   - `SandboxGTTLeg.claimed_at` (`DateTime`, nullable) — set to `CURRENT_TIMESTAMP` on the claim UPDATE, cleared (set `NULL`) on revert or final transition. The stranded-leg reaper reads this column; without it, a crashed-mid-trigger leg would be stuck in `triggering` forever since evaluators only rescan `pending` rows.
   - Indexes: `(user_id, gtt_status)`, `(symbol, exchange)`, `gtt_id` unique, FK `legs.gtt_id → gtt.gtt_id`, and `(leg_status, claimed_at)` on legs — covers both the active-trigger scan and the reaper's stale-claim query.

2. **Hand-rolled migration**
   - (N) `upgrade/migrate_gtt.py` — idempotent `CREATE TABLE IF NOT EXISTS` pair + default row in `SandboxConfig` for `gtt_oco_margin_mode=max`.
   - (E) `upgrade/migrate_all.py` — append `("migrate_gtt.py", "GTT Order Support")` **after** `migrate_sandbox.py`.

3. **Marshmallow schemas**
   - (E) `restx_api/schemas.py` — add `PlaceGTTOrderSchema`, `ModifyGTTOrderSchema`, `CancelGTTOrderSchema`, `GTTOrderBookSchema`. Leg-count validation in `@post_load`.

4. **Event classes**
   - (E) `events/order_events.py` — add `GTTPlacedEvent`, `GTTFailedEvent`, `GTTModifiedEvent`, `GTTModifyFailedEvent`, `GTTCancelledEvent`, `GTTCancelFailedEvent`, `GTTTriggeredEvent`, `GTTExpiredEvent`.
   - (E) `events/__init__.py` — export + add to `__all__`.

5. **Broker capability detection**
   - No explicit registry. Follow the existing regular-order pattern: services call `importlib.import_module("broker.<name>.api.gtt_api")` and a `None` result means "this broker does not ship GTT yet" → service returns `501 {"status":"error","message":"GTT orders are not supported for broker '<name>' yet"}`. Module presence *is* the capability test.

6. **Logging vocabulary**
   - No code change. Reserve `api_type` values: `placegttorder`, `modifygttorder`, `cancelgttorder`, `gttorderbook`, `gtttriggered`, `gttexpired`. Document in `database/apilog_db.py` docstring.

### Files touched

- **New:** `database/gtt_db.py`, `upgrade/migrate_gtt.py`
- **Edited:** `upgrade/migrate_all.py`, `restx_api/schemas.py`, `events/order_events.py`, `events/__init__.py`

### Acceptance

- `python upgrade/migrate_all.py` runs twice on a fresh DB with no errors; tables exist after first run, no-op on second.
- Unit tests for schemas: single-leg accepts 1-leg list; two-leg requires 2 legs with opposite-direction triggers relative to `last_price`; crypto quantity float-accepted.
- `from events import GTTPlacedEvent` imports; publishing a dummy event doesn't explode the bus.
- Calling `importlib.import_module("broker.zerodha.api.gtt_api")` succeeds; calling it for a broker without a `gtt_api.py` raises `ImportError` and the service returns 501.

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

4. **Semi-auto / Action Center integration**

   GTT placement is opt-in routable through Action Center for users running in semi-automatic mode (`order_mode = semi_auto`). Modify and cancel are explicitly **not** queueable (Phase 0.3) — once a GTT is live at the broker, the semi-auto delay between queue and approve is incompatible with the GTT's own trigger timing. Both live and analyze modes flow through the same Action Center surface (Phase 0.10).

   **a. Routing decision (entry point)**
   - (E) `services/order_router_service.py:should_route_to_pending(api_key, api_type)` — extend to:
     - return `True` for `api_type == "placegttorder"` when the user's `order_mode` is `semi_auto`,
     - explicitly return `False` for `api_type == "modifygttorder"` and `api_type == "cancelgttorder"` regardless of mode (per Phase 0.3),
     - all other GTT calls (`gttorderbook` — read-only) bypass the queue.
   - The semi-auto branch creates the row via `database.action_center_db.create_pending_order(user_id, api_type, order_data_json)` and returns `(False, {"status": "queued", "queue_id": ..., "message": "Pending approval in Action Center"}, 202)` from `place_gtt_order_with_auth`. The REST endpoint surfaces this as HTTP 202 (Accepted) — no broker call yet.

   **b. Queue payload shape**

   The JSON written to `pending_orders.order_data` is the full validated `PlaceGTTOrderSchema.dump()` plus a `_meta` block carrying the mode-binding (Phase 0.11):
   ```json
   {
     "trigger_type": "single|oco",
     "symbol": "RELIANCE",
     "exchange": "NSE",
     "last_price": "1234.5",
     "expires_at": "2026-04-22T15:30:00+05:30",
     "legs": [
       {"action": "BUY", "quantity": "10", "trigger_price": "1240", "price": "1245", "product": "CNC"}
     ],
     "_meta": {
       "openalgo_mode": "live",
       "queued_at_ist": "...",
       "broker": "zerodha"
     }
   }
   ```
   `_meta.openalgo_mode` is the mode-binding value re-validated at approval time (see Phase 0.11).

   **c. Pretty-print parser**
   - (E) `services/action_center_service.py:parse_pending_order` — add a new `elif api_type == "placegttorder":` branch alongside the existing `optionsorder` / `basketorder` / `smartorder` branches. Mirrors the basket-order shape: a top-level summary plus a leg list. Returns:
     ```python
     {
         "type": "GTT",
         "trigger_type": order_data["trigger_type"].upper(),  # SINGLE or OCO
         "symbol": order_data["symbol"],
         "exchange": order_data["exchange"],
         "expires_at": order_data.get("expires_at", "365d default"),
         "legs": [
             {
                 "action": leg["action"],
                 "qty": leg["quantity"],
                 "trigger_price": leg["trigger_price"],
                 "limit_price": leg["price"],
                 "product": leg.get("product", "MIS"),
             }
             for leg in order_data["legs"]
         ],
         "raw_order_data": {k: v for k, v in order_data.items() if k not in ["apikey", "api_key"]},
     }
     ```
   This is what the React Action Center page renders for queued GTTs.

   **d. Approval dispatch**
   - (E) `database/action_center_db.py:approve_pending_order` — the existing dispatch lookup must learn about `placegttorder`:
     ```python
     api_type_to_service = {
         "placeorder":     place_order_service.place_order_with_auth,
         "basketorder":    basket_service.place_basket_order_with_auth,
         "smartorder":     smart_order_service.place_smart_order_with_auth,
         "placegttorder":  place_gtt_order_service.place_gtt_order_with_auth,  # NEW
     }
     ```
   - Before dispatch: re-read the user's current mode via `database.settings_db.get_analyze_mode()`. If it differs from `order_data["_meta"]["openalgo_mode"]`, return HTTP 409 with `{"error": "mode_mismatch", "queued_in": "live", "current_mode": "analyze"}` and leave the row in `pending` (operator can cancel and re-queue). Phase 0.11 rationale.
   - On dispatch: the service itself reads `get_analyze_mode()` and dispatches live → Zerodha broker, analyze → sandbox GTT engine. The Action Center wrapper does not need to know which path runs.
   - On success: existing `update_broker_status(pending_order_id, broker_order_id, broker_status)` is called with `broker_order_id = trigger_id` (live) or `sandbox_gtt_id` (analyze). The Action Center UI shows the `trigger_id` so the user can correlate it to the GTT book.

   **e. Audit trail**
   - On queue: `order_logs` row with `api_type = "placegttorder"`, `status = "pending_approval"`, `result_data = {"queue_id": ..., "openalgo_mode": ...}`.
   - On approve: same row pattern but `status = "approved"` and `broker_order_id` populated.
   - On reject: `status = "rejected"`, `rejected_reason` from operator.
   - Reuses existing `order_logs` schema — no new columns needed.

   **f. UI surface**
   - (E) `frontend/src/pages/ActionCenter.tsx` — extend the row renderer to recognise the new GTT shape returned by `parse_pending_order`. Mirrors the basket-order card pattern (summary + leg list).
   - (E) `frontend/src/components/pending-order-cards/` — add `GttPendingCard.tsx` alongside `BasketPendingCard.tsx`. Displays `trigger_type` badge (`SINGLE` / `OCO`), `symbol (exchange)`, `expires_at`, leg list with action / qty / trigger / limit, and the standard approve / reject buttons. Reuses `PendingOrderActions.tsx`.

   **g. Tests**
   - Sandbox-mode user, `order_mode = semi_auto`, calls `POST /api/v1/placegttorder` → response 202 with `queue_id`, `pending_orders` row created with `api_type = "placegttorder"`, no broker call, no `sandbox_gtt` row yet.
   - Operator hits `POST /action-center/approve/{id}` → `place_gtt_order_with_auth` runs in sandbox mode, `sandbox_gtt` row created, `pending_orders.status = "approved"`, `broker_order_id` set to the sandbox `gtt_id`.
   - Live-mode user with semi-auto on; mode toggled to analyze between queue and approve → approval returns 409 `mode_mismatch`, row stays `pending` (Phase 0.11).
   - `POST /api/v1/modifygttorder` and `POST /api/v1/cancelgttorder` from a semi-auto user → both bypass the queue (Phase 0.3) and dispatch directly to the broker / sandbox engine. Verified by absence of any `pending_orders` row.

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

Live GTT fully usable via REST + Playground on Zerodha. Other brokers: 501 from the ImportError path in services when no `broker/<name>/api/gtt_api.py` exists. Analyze mode: 501 from service layer.

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
     - **`try_claim_trigger(leg_id) -> bool`** — the single entry point all evaluators (polling, WebSocket, catch-up) must call before firing an order. Implementation: `UPDATE sandbox_gtt_legs SET leg_status='triggering', claimed_at=CURRENT_TIMESTAMP WHERE id=:leg_id AND leg_status='pending'`; return `session.execute(stmt).rowcount == 1` then `session.commit()`. Uses `CURRENT_TIMESTAMP` (SQL-standard, portable across SQLite / Postgres / MySQL) — `now()` is not available on SQLite which is the default sandbox DB. In Python this is expressed as `func.now()` in a SQLAlchemy `update()` construct, which compiles to `CURRENT_TIMESTAMP` on every dialect OpenAlgo supports. Winner proceeds to `_fire_leg(leg_id, execution_price)`; losers return `False` and skip silently.
     - **`_fire_leg(leg_id, execution_price)`** (internal, only called by claim winner) — wraps its work in `try/except/finally`. On the happy path: release leg's share of GTT margin, call `order_manager.place_order()` for the leg payload, persist the returned `orderid` to `leg.triggered_order_id`, flip `leg.leg_status` from `triggering → triggered`, then for `two-leg`: atomically claim-and-cancel sibling with `UPDATE … SET leg_status='cancelled' WHERE id=:sibling AND leg_status IN ('pending','triggering')` and release its margin per Phase 0.2 rule. Finally flip parent `gtt_status` from `active → triggered` (CAS) and publish `GTTTriggeredEvent`. If the sibling row returns `rowcount=0`, another path already claimed it — respect their outcome (log and continue). **On any exception from `place_order` or a non-success broker response**: revert leg with `UPDATE sandbox_gtt_legs SET leg_status='pending', claimed_at=NULL WHERE id=:leg_id AND leg_status='triggering'` (CAS back; guards against the reaper racing in), restore any margin adjustment made before the failure, and publish `GTTFailedEvent` carrying the broker error. The next evaluator tick will re-pick the leg.
     - **`reclaim_stranded_legs()`** — safety net for the crash-between-claim-and-completion case. Selects legs where `leg_status='triggering' AND claimed_at < CURRENT_TIMESTAMP - <claim_timeout>`; reverts each back to `pending` (CAS on `leg_status='triggering'` to avoid racing a live worker). The claim timeout is a new `SandboxConfig.gtt_claim_timeout_sec` entry with default **60** (≥ 2× the default 5 s polling interval; generous enough that a legitimate slow broker call completes before the reaper touches it). Called from two places: every poll tick of `execution_engine` (cheap — a single indexed query), and unconditionally at the start of `catch_up_gtts()` so a crashed process always self-heals on restart before the catch-up scan runs.
   - Trade-ID style for auto-fired orders: `ORDER-GTT-<ts>-<uuid8>` (distinguishable in `sandbox_trades`).

2. **Sandbox service wrapper**
   - (E) `services/sandbox_service.py` — add `sandbox_place_gtt_order`, `sandbox_modify_gtt_order`, `sandbox_cancel_gtt_order`, `sandbox_gtt_orderbook`. Each resolves `user_id` from `api_key` then calls `gtt_manager`.
   - (E) Phase-2 service files: remove the 501 branch; call `sandbox_service.sandbox_*` when `get_analyze_mode()`.

3. **Polling monitor**
   - (E) `sandbox/execution_engine.py`:
     - Inside `check_and_execute_pending_orders()`, after regular-order batch, first call `gtt_manager.reclaim_stranded_legs()` (one indexed query; cheap), then call new `_check_pending_gtts()`.
     - Query `SandboxGTT` join `SandboxGTTLeg` where `gtt_status='active'` AND `leg_status='pending'`.
     - Reuse `_fetch_quotes_batch()` (symbols from legs).
     - Evaluate: BUY leg `ltp >= trigger_price`; SELL leg `ltp <= trigger_price`.
     - **On trigger: call `gtt_manager.try_claim_trigger(leg.id)` — only proceed if it returns `True`.** The manager handles margin, the broker-side order, sibling cancellation, status transitions, event emission, and failure revert.
     - **No market-hours gate.** The polling engine today has no `is_market_open()` check; the GTT monitor must match that behaviour to avoid silent divergence from regular-order semantics.

4. **WebSocket monitor**
   - (E) `sandbox/websocket_execution_engine.py`:
     - Add `_pending_gtts_index: dict[str, list[int]]` (symbol → list of `leg_id`, not parent `gtt_id` — claims happen at the leg level).
     - On subscribe/startup: rebuild index from DB (symmetry with existing order index).
     - On tick: for each indexed leg, run the same BUY/SELL trigger logic as §3.3; on trigger, call `gtt_manager.try_claim_trigger(leg_id)` — only proceed if `True`.
     - Symbol refcounting already handles shared symbols.

5. **Catch-up**
   - (E) `sandbox/catch_up_processor.py` — `catch_up_gtts()` after master-contract download:
     - **Step 1 (always):** call `gtt_manager.reclaim_stranded_legs()` to revert any leg stranded in `triggering` by a prior crash — must run **before** the breach scan, otherwise stranded legs would be invisible to it.
     - **Step 2:** one multiquotes call for all unique GTT symbols; for every leg whose trigger is already breached, call `gtt_manager.try_claim_trigger(leg_id)` and fire on win.
     - Runs unconditionally on startup — explicitly **not** gated by market hours, because this is exactly the recovery path for off-hours restarts.

6. **Config**
   - (E) `database/sandbox_db.py` default-config seed — add `gtt_claim_timeout_sec = 60` to the `SandboxConfig` defaults so the reaper has a working threshold out of the box.

7. **Expiry watcher**
   - (E) `sandbox/execution_thread.py` — add APScheduler job (hourly) that flips `active` GTTs with `expires_at < now` to `expired`, releases margin, publishes `GTTExpiredEvent`.

8. **Margin reconciliation**
   - `fund_manager.reconcile_margin(user_id, auto_fix=True)` already exists. Add GTT's `margin_blocked` sum to its expected-used-margin calc so it doesn't false-flag.
   - (E) `sandbox/fund_manager.py`

### Files touched

- **New:** `sandbox/gtt_manager.py`
- **Edited:** `services/sandbox_service.py`, Phase-2 service files, `sandbox/execution_engine.py`, `sandbox/websocket_execution_engine.py`, `sandbox/catch_up_processor.py`, `sandbox/execution_thread.py`, `sandbox/fund_manager.py`, `database/sandbox_db.py` (default-config seed)

### Acceptance

- **Placement path:** analyze-mode `placegttorder` persists rows in `sandbox_gtt` + `sandbox_gtt_legs`; `used_margin` increases by the blocked amount; `available_balance` decreases symmetrically.
- **Trigger path (single-leg):** set trigger $1 from LTP in a test instrument; within one poll cycle (≤ 5 s) or immediately on the next WS tick, leg is marked `triggered`, a row appears in `sandbox_orders` with status eventually `complete`, GTT margin is released, order margin is blocked.
- **Trigger path (OCO):** same with two legs; only one fires, the other becomes `cancelled`, parent `triggered`, no double-margin.
- **Cancel path:** `cancelgttorder` → `gtt_status='cancelled'`, margin released.
- **Modify path:** `modifygttorder` → new trigger reflected; margin diff reconciled.
- **Restart test:** place GTT, stop app, move price past trigger externally (use a mock LTP), start app → catch-up fires the trigger on boot.
- **Expiry test:** manually set `expires_at = now()-1h` on an active GTT, wait one hour (or force the scheduler tick) → status flips to `expired`, margin released.
- **Reconciliation:** `reconcile_margin` reports 0 discrepancies after a mixed sequence of regular orders, GTT placements, triggers, and cancellations.
- **Concurrent-path dedup (P1 coverage):** drive the polling engine, WebSocket engine, and catch-up processor to all observe a crossed trigger on the same leg within a 100 ms window. Assert exactly **one** `sandbox_orders` row is created for that leg, the leg transitions `pending → triggering → triggered` exactly once, and the two losing paths log the "claim lost" debug line without side effects. Cover this with a repeatable test (parallel threads invoking the claim helper on the same `leg_id`; expect exactly one `True`, all others `False`).
- **OCO sibling race:** same test setup but with a two-leg GTT where both trigger prices are breached simultaneously. Assert exactly one leg fires, the sibling transitions directly to `cancelled`, no duplicate orders, and margin is released exactly once.
- **Place-order failure revert:** mock `order_manager.place_order()` to raise mid-fire. Assert the leg reverts `triggering → pending`, `claimed_at` is cleared, margin is restored, and the next evaluator tick re-picks the leg and retries.
- **Broker-error revert:** mock `order_manager.place_order()` to return a non-success response. Same assertions as above plus a `GTTFailedEvent` is published.
- **Stranded-leg reclaim after crash:** force a leg into `leg_status='triggering'` with `claimed_at` set more than `gtt_claim_timeout_sec` in the past (simulates a worker crash mid-fire). Restart the app — catch-up's `reclaim_stranded_legs()` step must revert the leg to `pending` before the breach scan, and the leg must be re-evaluable by the next tick. Also test the live-process path: while the app is running, inject a stranded leg → next polling tick's reclaim call reverts it within one cycle.
- **Reclaim does not race a live worker:** inject a `triggering` leg with `claimed_at = now - 1s` (well under the 60s timeout) and run the reaper → leg must remain in `triggering` (the CAS predicate depends on the timestamp, not just the status).

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
   - Gate "+ Place GTT" button on a capability flag exposed via an existing `/api/v1/session` or similar — derive the flag server-side from `importlib.util.find_spec("broker.<name>.api.gtt_api") is not None`; add a small endpoint if absent.
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
3. (E) `docs/api/order-management/gtt_concepts.md` — update support matrix row. No registry flip needed: services detect capability by `importlib.import_module("broker.<name>.api.gtt_api")`.

### Per-broker acceptance

- Place / modify / cancel / book cycle verified against a live broker account.
- Broker-specific quirks documented in a `broker/<name>/README.md` or equivalent (e.g., "Broker X does not support OCO; `two-leg` requests return 501").

### Suggested order

1. ~~Dhan~~ — **shipped** (2026-04-29; see Change Log)
2. Fyers
3. Upstox
4. Angel One
5. 5Paisa / others

Parallelisable across contributors; no cross-dependency.

### Exit

GTT supported on all brokers that expose a GTT-equivalent API. Brokers without native support continue to return a clean 501.

---

## Risk & Mitigation Summary

| Risk | Mitigation | Phase |
|------|------------|-------|
| Multiple evaluator paths (polling / WebSocket / catch-up) double-firing the same GTT | **Do not rely on the post-fact trade-dedup at `execution_engine.py:217`** — it only catches duplicates after a trade row exists on the same `orderid`, but each GTT path would generate its own `orderid` via `place_order()` and slip past the guard. Instead, every evaluator funnels through `gtt_manager.try_claim_trigger(leg_id)`, which CAS-flips `leg_status` from `pending → triggering` in a single conditional UPDATE. Only the winning path calls `_fire_leg()`. OCO sibling cancellation uses the same CAS pattern on the sibling leg. | 0.9, 3 |
| Leg stranded in `triggering` forever after a crash or an unhandled `place_order` exception (evaluators only re-scan `pending` legs) | Two layers: (1) `_fire_leg` wraps its work in `try/except/finally` that CAS-reverts `triggering → pending` and restores margin on any failure; (2) `gtt_manager.reclaim_stranded_legs()` is a reaper that periodically reverts any `triggering` row older than `SandboxConfig.gtt_claim_timeout_sec` (default 60 s). Called from every polling tick and unconditionally at the start of `catch_up_gtts()` so a crashed process self-heals on restart before its breach scan runs. Reaper predicate includes the `claimed_at` check so it cannot race a live worker. | 3 |
| Worker crashes **after** broker-side order is placed but **before** the leg transitions to `triggered` — reaper reverts leg to `pending`, next tick would place a duplicate order | Known corner case. Mitigation path for v1.x: pre-assign a UUID correlation id on the leg (`pending_order_correlation`) and pass it to `order_manager.place_order()` which writes it to `sandbox_orders.correlation_id`. The reaper then checks: if a `sandbox_orders` row with this correlation exists, finalize the leg to `triggered` with that orderid; otherwise revert. Tracked as a follow-up; out of scope for v1. | Post-v1 |
| Portable SQL across SQLite / Postgres / MySQL | All CAS UPDATEs use `CURRENT_TIMESTAMP` (SQL-standard), not `now()`. In Python, expressed as `func.now()` in SQLAlchemy `update()` which compiles correctly on every dialect. | 0.9, 3 |
| OCO double-margin when broker charges sum vs. our `max` default | Configurable `gtt_oco_margin_mode` in `SandboxConfig`. | 0, 3 |
| GTT modify arrives after GTT already triggered | Service-layer pre-check: re-read status before dispatch; return `{status: error, message: "GTT already triggered"}` 409. | 2 |
| Broker GTT expires silently; OpenAlgo shows stale `active` | Nightly reconciliation job pulls `gttorderbook` from broker in live mode, diffs against last-seen state, logs & emits events for state changes. (Optional Phase 6 enhancement.) | 6+ |
| Semi-auto queue collides with GTT triggers | Disallow semi-auto for modify/cancel (Phase 0.3). | 2 |
| Operator toggles mode between queue and approve in Action Center | `_meta.openalgo_mode` captured at queue time, re-validated at approval (Phase 0.11). 409 + leave row pending if changed; operator cancels and re-queues. | 0.11, 2 |
| Approval lag exceeds GTT expiry window | Pre-check inside `approve_pending_order` GTT branch: if `now > order_data["expires_at"]`, refuse with HTTP 410 `gtt_already_expired` and auto-cancel the row (status = `expired`). Logged as `gtt_approve_expired` event. | 2 |
| Order-logs table bloat | No new schema; reuses `order_logs`. If volume becomes a concern, apply the same retention policy as regular orders. | — |

---

## Cross-Phase File Index

| Surface | New files | Edited files |
|---------|-----------|--------------|
| DB | `database/gtt_db.py`, `upgrade/migrate_gtt.py` | `upgrade/migrate_all.py` |
| REST | `restx_api/{place,modify,cancel}_gtt_order.py`, `restx_api/gtt_orderbook.py` | `restx_api/__init__.py`, `restx_api/schemas.py` |
| Services | `services/{place,modify,cancel}_gtt_order_service.py`, `services/gtt_orderbook_service.py` | `services/sandbox_service.py`, `services/order_router_service.py`, `services/telegram_alert_service.py`, `services/flow_openalgo_client.py`, `services/flow_executor_service.py` |
| Broker (Zerodha) | `broker/zerodha/api/gtt_api.py`, `broker/zerodha/mapping/gtt_data.py` | — |
| Broker (Dhan) | `broker/dhan/api/gtt_api.py`, `broker/dhan/mapping/gtt_data.py` | — |
| Events | — | `events/order_events.py`, `events/__init__.py` |
| Subscribers | — | `subscribers/__init__.py`, `subscribers/log_subscriber.py`, `subscribers/socketio_subscriber.py`, `subscribers/telegram_subscriber.py` |
| Sandbox | `sandbox/gtt_manager.py` | `sandbox/execution_engine.py`, `sandbox/websocket_execution_engine.py`, `sandbox/catch_up_processor.py`, `sandbox/execution_thread.py`, `sandbox/fund_manager.py` |
| Blueprints | — | `blueprints/orders.py`, `blueprints/playground.py` |
| Frontend (React) | `components/orders/{GttTab,PlaceGttModal,ModifyGttModal}.tsx`, `components/flow/nodes/{PlaceGtt,ModifyGtt,CancelGtt,GttOrderbook}Node.tsx` | `pages/OrderBook.tsx`, `api/trading.ts`, `lib/flow/constants.ts`, `components/flow/nodes/index.ts`, `components/flow/panels/ConfigPanel.tsx`, `types/flow.ts` |
| Jinja | `templates/gtt_orderbook.html` | `templates/orderbook.html` |
| Playground | 4 `.bru` files under `collections/openalgo/IN_stock/orders/` | `blueprints/playground.py` |
| SDK | — | `src/openalgo/orders.py` (or client module) |
| Docs | `docs/api/order-management/{placegttorder,modifygttorder,cancelgttorder,gttorderbook}.md` + (Phase 5 pending) `docs/userguide/gtt-orders.md`, `docs/test/gtt-test-plan.md`. (Gitbook-ready paste copies live outside the repo at `../gitbook/`.) | `docs/api/README.md`, root `README.md`, `CLAUDE.md`, `docs/CHANGELOG.md` |

---

## Change Log

| Date | Author | Change |
|------|--------|--------|
| 2026-04-22 | Claude (Opus 4.7) | Initial draft. |
| 2026-04-22 | Claude (Opus 4.7) | Addressed cubic-dev-ai review. **P1:** introduced leg-level atomic-claim (`try_claim_trigger`) as the single fire path for polling, WebSocket, and catch-up evaluators; added `triggering` intermediate state on `SandboxGTTLeg.leg_status` and `SandboxGTT.gtt_status`; added concurrent-path and OCO sibling-race acceptance tests; rewrote the corresponding Risk row. **P2:** removed the inaccurate "mirrors existing `execution_engine` behaviour" claim — sandbox engine does not call `is_market_open()`, so the GTT monitor explicitly does not gate on market hours (catch-up especially must not, per the original off-hours-restart recovery intent). |
| 2026-04-22 | Claude (Opus 4.7) | Addressed second cubic-dev-ai review. **P1 (portability):** replaced `now()` in the claim UPDATE with `CURRENT_TIMESTAMP` (SQL-standard; `now()` fails on SQLite, which is the default sandbox DB). **P1 (stranded-leg reclaim):** added `_fire_leg` try/except/finally that CAS-reverts on any failure, plus a `reclaim_stranded_legs()` reaper gated on a new `SandboxConfig.gtt_claim_timeout_sec` (default 60 s) called from every polling tick and at the start of catch-up. Added `claimed_at` column to `SandboxGTTLeg`, expanded the `(leg_status, claimed_at)` index, added four acceptance tests (place-order exception revert, broker-error revert, post-crash reclaim, reclaim-does-not-race-live-worker), and two new Risk rows (stranded-triggering recovery; post-`place_order` crash corner case flagged as a post-v1 follow-up with a correlation-id mitigation sketch). |
| 2026-04-24 | Claude (Opus 4.7) | Removed the `BROKER_GTT_SUPPORT` registry and `broker_gtt_supported()` helper. Rationale: GTT is broadly available across Indian brokers, and OpenAlgo's existing regular-order convention detects capability purely by module presence (`importlib.import_module("broker.<name>.api.order_api")`). Matching that pattern means one fewer place to touch when onboarding a new broker, and an ImportError from `import_broker_gtt_module` already yields a clean 501 with the message `GTT orders are not supported for broker '<name>' yet`. Updated Phase 1 Task 5 (capability detection), Phase 1 acceptance, Phase 2 exit, Phase 4 frontend gate, Phase 6 per-broker template, and the Cross-Phase File Index accordingly. |
| 2026-04-29 | Claude (Opus 4.7) | **Schema field rename — `trigger_price` → `triggerprice_sl` + `triggerprice_tg`.** The original single `trigger_price` field was ambiguous for OCO; replaced with explicit stoploss-side and target-side trigger fields. SINGLE accepts exactly one of the two as the trigger; OCO requires both alongside `stoploss` (sl-leg limit) and `target` (tg-leg limit). The schema's `_validate_gtt_place_request` populates an internal `trigger_price` alias for backward compat with broker mappers. Empty strings are coerced to `null` / `0` in `@pre_load`. Affected: `restx_api/schemas.py` (`PlaceGTTOrderSchema`, `ModifyGTTOrderSchema`), broker mappers (`broker/zerodha/mapping/gtt_data.py`, `broker/dhan/mapping/gtt_data.py`), services, blueprints (UI modify route forwards new fields), frontend `GttTab.tsx` (modify dialog inputs, `openModify` derivation, `saveModify` validation), `frontend/src/api/trading.ts` types, Bruno samples. |
| 2026-04-29 | Claude (Opus 4.7) | **Removed `mode` from GTT success responses.** Place/modify/cancel responses no longer include `"mode": "live"`. Event payloads also dropped the field. Affected: all four GTT service files. |
| 2026-04-29 | Claude (Opus 4.7) | **Tightened `product` validation — MIS rejected for GTT.** GTTs can sit for days/weeks, so an intraday-squared product makes no sense. `PlaceGTTOrderSchema` and `ModifyGTTOrderSchema` now constrain `product` to `["NRML", "CNC"]` with a custom error message: *"GTT supports only CNC (delivery) or NRML (overnight F&O); MIS is intraday-only."* Schema-level rejection happens before any broker call. |
| 2026-04-29 | Claude (Opus 4.7) | **Phase 6 — Dhan GTT (Forever Orders) integrated** ahead of original "fan-out" sequencing. Added `broker/dhan/api/gtt_api.py` and `broker/dhan/mapping/gtt_data.py`. Bruno samples added. Notable broker-specific quirks absorbed in the broker layer (callers see clean broker-neutral behaviour): (a) Dhan's published GET endpoint `/v2/forever/all` returns 404 — the SDK's `/v2/forever/orders` is what actually works. (b) Dhan's AWS ELB returns spurious 301 redirects (`Location: https://api.dhan.co:443/v2/`) on HTTP/2 POST/PUT/DELETE to `/v2/forever/orders`; mitigated with a dedicated `httpx.Client(http2=False)` for all Dhan GTT calls. (c) Dhan stores SINGLE GTTs internally as `STOP_LOSS_LEG` / `TARGET_LEG` / `ENTRY_LEG` depending on action+trigger relative to LTP at place-time; modify endpoint requires the actual stored `legName`, so `modify_gtt_order` does a `/v2/forever/orders` lookup before each PUT and uses the resolved tag. (d) `transform_modify_gtt` now dispatches by `trigger_type` (not `leg_name`) for SINGLE so any Dhan tag still resolves to the SINGLE field set. (e) SINGLE-only safety net in modify: coerce `pricetype=LIMIT` with `price=0` to `pricetype=MARKET` (Dhan rejects the LIMIT+0 combo with DH-905). (f) `map_gtt_book` infers per-leg pricetype from the price field (Dhan's GET response doesn't include LIMIT/MARKET) and exposes Dhan's `legName` as `leg_name` for diagnostics. |
| 2026-04-29 | Claude (Opus 4.7) | **Phase 2 — Zerodha MARKET → MPP-protected LIMIT auto-conversion.** Kite GTT only accepts `order_type=LIMIT`. The Zerodha GTT API layer now intercepts `pricetype=MARKET` and applies the existing `utils/mpp_slab.calculate_protected_price()` helper using LTP (for SINGLE) or each leg's trigger (for OCO), forcing `pricetype=LIMIT` before relaying to Kite. Tick-size and instrument type are pulled from `SymToken` via `get_symbol_info()`, with a fallback to symbol-suffix detection. Mirrors the flattrade/shoonya MARKET-protection pattern, scoped to GTT only — regular Zerodha orders still send native MARKET. |
| 2026-04-29 | Claude (Opus 4.7) | **GTT orderbook now active-only at the broker mapper.** Triggered/cancelled/expired/rejected/disabled/deleted GTTs are filtered out before the response leaves the broker layer, so the orderbook (UI + API) shows only triggers that can still fire. Both `broker/zerodha/mapping/gtt_data.py` and `broker/dhan/mapping/gtt_data.py` updated. |
| 2026-04-29 | Claude (Opus 4.7) | **Broker mappers self-sufficient for SINGLE trigger resolution.** Added `_resolve_single_trigger(data)` to both Zerodha and Dhan mappers — falls back to `triggerprice_sl` / `triggerprice_tg` when the legacy `trigger_price` alias isn't pre-populated by the schema (e.g., when the UI modify route bypasses `ModifyGTTOrderSchema`). Fixes a `KeyError: 'trigger_price'` that surfaced on UI-driven modifies. |
| 2026-04-29 | Claude (Opus 4.7) | **API documentation — `docs/api/gtt-orders/` created.** Four new docs (placegttorder, modifygttorder, cancelgttorder, gttorderbook) added with intent-led structure: *"Use SINGLE when…"* / *"Use OCO when…"*, a directional rule for picking `triggerprice_sl` vs `triggerprice_tg` (below LTP vs above LTP), an explicit naming-semantics callout (in SINGLE the suffix is just a directional hint; in OCO it's a real role), and intent-driven sample headings (*"Buy IDEA if it dips to 9.55, place LIMIT order at 9.50"* etc.). Broker-specific callouts removed — broker quirks remain absorbed in the broker layer per OpenAlgo's broker-agnostic API contract. `docs/api/README.md` updated with a GTT section linking the four endpoints. |
