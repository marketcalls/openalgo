# Kill Switch — Implementation Plan

**Status:** Design — not yet built
**Author:** Rajandran R (marketcalls)
**Date:** 2026-04-24
**Target release:** TBD (post-2.0.0.5)

---

## 1. Goals & Non-Goals

### 1.1 Goals

A single, unmissable red-button kill switch that:

1. **Blocks every new order** originating from any path (REST API, TradingView / GoCharting / Chartink webhooks, Flow visual builder, hosted Python strategies, MCP server, Telegram) in both **live** and **sandbox / analyzer** modes.
2. **Cancels every pending order** currently working at both the live broker **and** the sandbox.
3. **Closes every open position** both live **and** in the sandbox — "clean slate everywhere".
4. **Halts every running hosted Python strategy process** (SIGTERM → wait → `taskkill` fallback on Windows).
5. **Aborts every in-flight Flow execution** and rejects new webhook-triggered flow runs.
6. **Notifies the user** via Telegram and an in-app SocketIO banner.
7. **Is operable from Telegram** (`/killswitch on|off|status`) as an escape hatch when the UI is unreachable.
8. **Cannot be accidentally deactivated** — requires explicit confirmation + 60-second hold-open after activation.
9. **Is auditable** — who / when / why / counts of actions taken.

### 1.2 Non-Goals (v1)

- Automatic triggers (daily loss, MTM drawdown, latency spikes). Defer to v2.
- Per-strategy / per-broker granularity — single global switch in v1.
- Scheduled activation windows. Defer to v2.
- Auto-resume of paused strategies on deactivation — **explicit manual restart required**.
- Hardware-key two-factor on deactivation. Defer.

### 1.3 Modes of Operation

| Mode | Behavior |
|---|---|
| **Inactive (default)** | All paths operate normally |
| **Active** | Cleanup actions fire once; all order paths blocked; strategy/flow runners halted; UI + Telegram show active state |
| **Deactivated → Inactive** | Order paths unblocked. Python strategies and Flows **stay stopped** — user must manually re-run each. No auto-resume. |

---

## 2. User Stories

- **US-1**: As a trader, when I realize I've lost control of a strategy, I press a red button in the dashboard header and within 10 seconds my entire book is flat and no new orders can land.
- **US-2**: As a trader locked out of the dashboard (laptop dead, phone only), I send `/killswitch on` to the OpenAlgo Telegram bot and achieve the same outcome.
- **US-3**: As a trader I want to see, in my Telegram summary, exactly how many orders were cancelled, positions were closed, and strategies were halted — across live and sandbox.
- **US-4**: After the kill switch is active, if a TradingView alert fires a webhook, it gets a clear `403 KILL_SWITCH_ACTIVE` response. TradingView retries cease.
- **US-5**: Before I can deactivate, I must type `UNLOCK` and wait out the 60-second hold, so a fat-finger press can't undo the lock.
- **US-6**: After I deactivate, my Python strategies are still stopped — I restart them one-by-one after confirming each is safe to resume.

---

## 3. Architecture

### 3.1 Single Choke Point

Every order path in OpenAlgo converges at the service-function level, *above* the branch between live broker and sandbox. Put the gate there — one check, both modes covered.

```
┌─────────────────────────────────────────────────────────────────────┐
│  REST API  │  Webhook (TV / GC / Chartink)  │  Flow  │  Py Strategy │
│  MCP Server │  Telegram bot (future ordering)                       │
└───────┬────────┬───────────────────────┬────────┬────────────────────┘
        │        │                       │        │
        ▼        ▼                       ▼        ▼
  ┌────────────────────────────────────────────────────────┐
  │  Service-layer functions (single choke point)          │
  │  place_order_service.py        basket_order_service.py │
  │  place_smart_order_service.py  order_router_service.py │
  │  modify_order_service.py       sandbox_service.py      │
  │  cancel_order_service.py                               │
  └──────────────────────┬─────────────────────────────────┘
                         │
               ┌─────────▼──────────┐
               │  KILL SWITCH GATE  │  ← this commit adds this
               └─────────┬──────────┘
                   │          │
          active? ─┤          ├─ inactive?
                   │          │
               REJECT         ▼
               (403)   ┌──────────────┐
                       │ analyze_mode │
                       └──┬────────┬──┘
                          │        │
                        live    sandbox
                          │        │
                          ▼        ▼
                      broker    sandbox engine
```

### 3.2 Enforcement Decorator

New module: `utils/kill_switch.py`.

```python
# sketch — final implementation lives in utils/kill_switch.py
from functools import wraps
from database.settings_db import is_kill_switch_active

KILL_SWITCH_ERROR = {
    "status": "error",
    "code": "KILL_SWITCH_ACTIVE",
    "message": "Kill switch is active — new orders are blocked. "
               "Deactivate via dashboard or '/killswitch off' Telegram command.",
}

def enforce_kill_switch(op: str = "order"):
    """
    Decorator for order-placing service functions.
    op='order'  → blocked when kill switch is active
    op='cancel' → always allowed (needed during cleanup)
    """
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if op == "order" and is_kill_switch_active():
                return False, KILL_SWITCH_ERROR, 403
            return fn(*args, **kwargs)
        return wrapper
    return deco
```

### 3.3 Defense-in-Depth Layers

| Layer | Purpose |
|---|---|
| **Decorator on service functions** (primary) | Single source of truth; catches everything |
| **Check in Flow executor** (`execute_workflow` entry) | Aborts in-flight flows before they touch services |
| **Check in Python strategy launcher** (`start_strategy_process`) | Blocks new strategy starts; running ones are SIGTERMed separately |
| **Check in webhook blueprints** | Early-rejects with a 403 + structured body so upstream senders (TradingView) get immediate feedback instead of a timeout |

The decorator alone is sufficient for correctness; the earlier checks exist to cut wasted work (e.g., don't evaluate a 50-node flow that will error at leaf level).

---

## 4. Data Model

### 4.1 Extend `Settings` in `database/settings_db.py`

Reuse the existing `Settings` table and TTL-cache pattern that already handles `analyze_mode`.

**New columns:**

| Column | Type | Default | Purpose |
|---|---|---|---|
| `kill_switch_active` | `Boolean` | `False` | Master flag |
| `kill_switch_activated_at` | `DateTime` (UTC) | `None` | When most recent activation happened |
| `kill_switch_activated_by` | `String(50)` | `None` | Source: `ui` \| `api` \| `telegram` \| `auto:<trigger>` |
| `kill_switch_reason` | `String(500)` | `None` | Free-text note captured at activation |
| `kill_switch_min_unlock_at` | `DateTime` (UTC) | `None` | `kill_switch_activated_at + 60s` — deactivation rejected before this |

### 4.2 New Table: `kill_switch_audit`

Separate audit log so the main `Settings` row stays lean.

```
Table: kill_switch_audit
------------------------
id                     INTEGER PK AUTO
event_at               TIMESTAMP (UTC)
event_type             TEXT  -- 'activated' | 'deactivated' | 'cleanup_summary'
actor_type             TEXT  -- 'ui' | 'api' | 'telegram' | 'auto'
actor_id               TEXT  -- username / api-key-hash / telegram-chat-id / trigger-name
reason                 TEXT
live_orders_cancelled  INTEGER
live_positions_closed  INTEGER
sandbox_orders_cancelled  INTEGER
sandbox_positions_closed  INTEGER
strategies_stopped     INTEGER
flows_aborted          INTEGER
notes                  TEXT  -- JSON blob with per-strategy IDs, broker errors, etc.
```

### 4.3 Caching

Follow the exact pattern from `analyze_mode` (`database/settings_db.py:79-105`):

- Module-level `_settings_cache` dict with 1-hour TTL
- New cache key: `"kill_switch_active"` (hot-path read)
- Invalidate on every `set_kill_switch(...)`
- Separate invalidation on any write via a SocketIO broadcast so multi-process deployments (not a v1 concern but future-proofing) stay consistent

### 4.4 Service API in `database/settings_db.py`

```python
def is_kill_switch_active() -> bool: ...         # hot path, cached
def get_kill_switch_state() -> dict: ...         # full record (activated_at, by, reason, min_unlock_at)
def set_kill_switch(active: bool, actor_type: str,
                    actor_id: str, reason: str | None) -> dict: ...
def record_kill_switch_audit(...) -> None: ...   # append to audit table
def get_kill_switch_audit(limit: int = 50) -> list[dict]: ...
```

---

## 5. REST API Endpoints (new)

All endpoints gated by existing `@check_session_validity` for UI calls and API-key auth for programmatic calls. Must NOT be gated by the kill switch itself.

### 5.1 `POST /api/v1/killswitch/activate`

**Request:**
```json
{
  "apikey": "<key>",
  "reason": "manual UI click",
  "actor_type": "ui"       // optional; defaults to 'api' for apikey-auth calls
}
```

**Response (200):**
```json
{
  "status": "success",
  "kill_switch_active": true,
  "activated_at": "2026-04-24T10:30:15Z",
  "min_unlock_at": "2026-04-24T10:31:15Z",
  "cleanup_summary": {
    "live_orders_cancelled": 8,
    "live_orders_failed": 0,
    "live_positions_closed": 3,
    "sandbox_orders_cancelled": 2,
    "sandbox_positions_closed": 1,
    "strategies_stopped": 2,
    "flows_aborted": 1
  }
}
```

Idempotent: calling `activate` while already active returns current state with `"already_active": true` and does **not** re-run cleanup.

### 5.2 `POST /api/v1/killswitch/deactivate`

**Request:**
```json
{
  "apikey": "<key>",
  "confirmation": "UNLOCK"      // required; case-sensitive
}
```

**Validations:**
- `kill_switch_active` must be `true` → else 400 `ALREADY_INACTIVE`
- `now()` must be `>= kill_switch_min_unlock_at` → else 423 `MIN_UNLOCK_NOT_REACHED` with `retry_after_seconds` in body
- `confirmation == "UNLOCK"` → else 400 `CONFIRMATION_MISMATCH`

**Response (200):**
```json
{
  "status": "success",
  "kill_switch_active": false,
  "deactivated_at": "2026-04-24T10:35:02Z",
  "note": "Python strategies and Flow workflows remain stopped. Restart each manually."
}
```

### 5.3 `GET /api/v1/killswitch/status`

Returns full state (active flag, activated_at, by, reason, min_unlock_at, time-remaining-before-unlock). Not rate-limited. Not gated.

### 5.4 `GET /api/v1/killswitch/audit?limit=50`

Paginated audit log. Admin-only (api-key must belong to the single user).

---

## 6. Service Layer — Exact Files to Change

### 6.1 Add `@enforce_kill_switch("order")` decorator to:

| File | Function | Line |
|---|---|---|
| `services/place_order_service.py` | `place_order` | 260 |
| `services/place_smart_order_service.py` | `place_smart_order` | 281 |
| `services/modify_order_service.py` | `modify_order` | 182 |
| `services/basket_order_service.py` | `place_basket_order` | 373 |
| `services/split_order_service.py` | `place_split_order` | (confirm line) |
| `services/options_order_service.py` | `place_options_order` | (confirm line) |
| `services/options_multi_order_service.py` | `place_options_multi_order` | (confirm line) |
| `services/order_router_service.py` | `queue_order` | 75 |

### 6.2 Explicitly DO NOT gate

These stay fully operational while active — they're part of the cleanup path:

- `services/cancel_order_service.py::cancel_order` (line 175)
- `services/cancel_all_order_service.py::cancel_all_orders`
- `services/close_position_service.py::close_position`

Add an `@enforce_kill_switch("cancel")` (no-op decorator) for documentation consistency so `grep enforce_kill_switch` shows every touched file.

### 6.3 New internal-only service: `services/kill_switch_service.py`

Orchestrates the cleanup sequence. Not exposed directly — only the REST endpoint and Telegram command call it.

```python
def activate_kill_switch(actor_type: str, actor_id: str,
                         reason: str | None) -> dict:
    """
    1. Flip DB flag + set timestamps (wrapped in a transaction)
    2. Invalidate cache
    3. Emit SocketIO 'kill_switch_activated'
    4. Run cleanup in parallel via eventlet.spawn:
       a. cancel_all_live_orders()
       b. close_all_live_positions()
       c. cancel_all_sandbox_orders()
       d. close_all_sandbox_positions()
       e. stop_all_python_strategies()
       f. abort_all_active_flows()
    5. Collect counts / errors into a cleanup_summary dict
    6. Write audit row
    7. Send Telegram alert with summary
    8. Return summary to caller
    """
```

---

## 7. Cleanup — Live Mode

### 7.1 Cancel all live orders

Call existing `services/cancel_all_order_service.py::cancel_all_orders` passing `strategy=None` (or iterate over all distinct strategies from today's orderbook). Capture per-strategy results.

Handle partial failures gracefully:
- If a broker rejects `cancelallorder` (e.g., rate limit or session expiry), log the error, continue, and surface the count in `live_orders_failed`.

### 7.2 Close all live positions

Call existing `services/close_position_service.py::close_position` for every distinct strategy that has open positions. Use `get_position_book()` as the source of truth.

**Edge cases:**
- Positions in `CNC` with T+1 holdings are NOT closable intraday — don't error, note them in `cleanup_summary.notes`.
- Bracket / Cover orders may require a different cancel path — check `broker/<name>/api/order_api.py::close_position` per broker and use the broker-native path when available.

### 7.3 Freeze broker session rotation

If a Zerodha-like daily token refresh is mid-run when the switch activates, block the refresh until deactivation. Simple: every broker auth refresh already reads `is_kill_switch_active()` and defers if true. (Defer implementation to v1.5 — not load-bearing for correctness.)

---

## 8. Cleanup — Sandbox Mode

Sandbox uses its own DB (`db/sandbox.db`) and service layer (`services/sandbox_service.py`). **Run cleanup unconditionally** — regardless of whether `analyze_mode` is on or off — because the user may flip into sandbox mode between activation and deactivation.

### 8.1 Cancel sandbox pending orders

```sql
UPDATE sandbox_orders
SET status = 'cancelled',
    remarks = 'Cancelled by kill switch at 2026-04-24T...'
WHERE status IN ('open', 'pending', 'trigger_pending');
```

Iterate via the ORM (not raw SQL) so SocketIO `order_update` events fire and the UI reflects the change live.

### 8.2 Close sandbox positions

Reuse the existing **auto square-off** code path in `services/sandbox_service.py` (the one that runs at exchange close). Expose it as `services/sandbox_service.py::force_square_off_all()`.

Emit `analyzer_update` SocketIO events so the sandbox UI updates.

---

## 9. Python Strategy Manager

File: `blueprints/python_strategy.py`.

### 9.1 Halt currently running strategies

Iterate `RUNNING_STRATEGIES` (line 60) and call `stop_strategy_process(strategy_id)` (line 603) for each. Collect success/failure counts.

**Important**: do **not** mark the strategy as "disabled" — only as "stopped". The `is_running` flag in `STRATEGY_CONFIGS` goes `False` but the strategy record stays intact. On deactivation, strategies do not auto-resume (per requirement).

### 9.2 Block new launches

Modify `start_strategy_process(strategy_id)` (line 420) to check `is_kill_switch_active()` at the top. If active, return `(False, "KILL_SWITCH_ACTIVE")` without spawning.

### 9.3 Scheduled launches

The IST-based scheduler that starts strategies at preset times must also respect the flag. Add the check inside the scheduler's tick.

### 9.4 UI surfacing

React frontend:
- Strategy list page — when kill switch is active, show a red banner at top and disable every "Start" button with a tooltip *"Kill switch active — cannot start strategies"*.
- Show a ghost "(stopped by kill switch at 10:30)" annotation per previously-running strategy.

---

## 10. Flow Executor

File: `services/flow_executor_service.py`.

### 10.1 Abort in-flight executions

The current `execute_workflow(workflow_id, webhook_data, api_key)` (line 2117) acquires a per-workflow lock. Add at the **top** of the function:

```python
if is_kill_switch_active():
    return {"status": "error", "code": "KILL_SWITCH_ACTIVE",
            "message": "Kill switch is active — workflow execution aborted."}
```

For flows **already** executing at activation moment: they will naturally hit the gate at the next node that calls an order-placing service — blocked at the service layer.

### 10.2 New webhook triggers

Each of the Flow webhook routes (registered per workflow) should call `is_kill_switch_active()` before even invoking the executor to avoid wasting work and to return a fast 403 to the sender.

### 10.3 Workflow "active/inactive" state

Flows have an `is_active` flag per workflow. When the kill switch is deactivated, flows **stay at their current `is_active`** — no auto-activation. If the user disabled a flow before the kill switch, it stays disabled after.

---

## 11. Webhook Blueprints — Early Rejection

Add the check at the top of each webhook handler so upstream senders (TradingView, GoCharting, Chartink) get fast 403s instead of timing out against the service layer.

| File | Route | Line |
|---|---|---|
| `blueprints/tv_json.py` | `/tradingview/` | 20 |
| `blueprints/gc_json.py` | `/gocharting/` | 20 |
| `blueprints/chartink.py` | `/chartink/webhook/<id>` | 785 |

Standard response body:
```json
{"status": "error", "code": "KILL_SWITCH_ACTIVE",
 "message": "OpenAlgo kill switch is active. Orders are not being accepted."}
```
HTTP status: **403 Forbidden**.

---

## 12. Telegram Bot Integration

File: `services/telegram_bot_service.py`.

### 12.1 New commands

| Command | Behavior |
|---|---|
| `/killswitch on [<reason>]` | Activates. Reason is optional free-text. |
| `/killswitch off` | Begins deactivation flow (inline keyboard asks for `UNLOCK` confirmation, respects min-unlock window) |
| `/killswitch status` | Shows current state, when activated, by whom, reason, time-remaining-before-unlock |
| `/killswitch audit` | Last 5 activation/deactivation entries |

### 12.2 Deactivation UX in Telegram

Since typing `UNLOCK` is cumbersome on mobile, use an inline keyboard:

```
Kill switch is ACTIVE.
Activated at 10:30 IST by UI. Reason: "manual test".
To unlock, tap the button below.

[🔓 Confirm UNLOCK]    [Cancel]
```

Callback query handler enforces the 60-second min-unlock window.

### 12.3 Cleanup summary push

On activation, push to the user:

```
🛑 KILL SWITCH ACTIVATED
Triggered by: Telegram (@username)
Reason: panic test

Cleanup summary:
• Live orders cancelled: 8 (0 failed)
• Live positions closed: 3
• Sandbox orders cancelled: 2
• Sandbox positions closed: 1
• Python strategies stopped: 2
• Flows aborted: 1

Min unlock at: 10:31:15 IST.
Reply /killswitch off to deactivate.
```

### 12.4 Config gating

The Telegram command is only active for the single registered Telegram user (look-up via existing `telegram_bot_service.py` user-binding). Unregistered chats get *"Not authorized"* — same pattern as existing commands.

---

## 13. SocketIO Events

Add to `utils/socketio_events.py` (or wherever events are registered):

| Event | Emitted when | Payload |
|---|---|---|
| `kill_switch_activated` | Activation starts, before cleanup | `{"activated_at", "activated_by", "reason"}` |
| `kill_switch_cleanup_progress` | Per cleanup step completion | `{"step", "count", "total_steps", "errors"}` |
| `kill_switch_cleanup_complete` | All cleanup done | `{"cleanup_summary": {...}}` |
| `kill_switch_deactivated` | After successful deactivation | `{"deactivated_at", "deactivated_by"}` |

**UI consumers:**
- Dashboard red-banner component subscribes to `kill_switch_activated` / `kill_switch_deactivated`.
- Strategy page listens for `kill_switch_activated` to update Start button states.
- Notification/toast center shows cleanup-progress toasts.

---

## 14. React Frontend Changes

### 14.1 Red-button header component

New component: `frontend/src/components/KillSwitchButton.tsx`.

- Always visible in the main app header (right side, next to analyzer-mode toggle)
- **Inactive state**: red outline button, text "Kill Switch"
- **Active state**: solid red, pulsing, text "KILL SWITCH ACTIVE — UNLOCK"
- Click inactive → confirmation modal:
  - Big warning text
  - Optional reason field
  - "Activate" (red, disabled for 2 seconds after modal opens to prevent misclick) + "Cancel"
- Click active → deactivation modal:
  - Shows when activated, by, reason
  - Countdown timer if still within 60-second hold
  - `UNLOCK` text input (case-sensitive)
  - "Deactivate" button enabled only after countdown hits 0 AND input matches
  - Notice: "Python strategies and Flow workflows will NOT auto-resume. Restart each manually."

### 14.2 Global banner

`frontend/src/components/KillSwitchBanner.tsx` — persistent red strip at the top of every page while active, shows `"KILL SWITCH ACTIVE since HH:MM — new orders blocked — [Unlock]"`.

### 14.3 Order-placement forms — disable while active

Every form/dialog that places orders (manual order entry, strategy builder execute, basket builder, historify watchlist order-from-chain, etc.) must:

- Read the kill-switch state from a new `useKillSwitch()` hook (TanStack Query that subscribes to the SocketIO event)
- When active, disable the submit button and show a tooltip/inline alert with the reason

Affected pages (non-exhaustive):
- `/orders/place`
- `/orders/smart`
- `/orders/basket`
- `/orders/split`
- `/strategybuilder` (execute action)
- `/strategybuilder/portfolio` (execute)
- `/optionchain` (click-to-trade)
- `/chartink` (any manual trigger)

### 14.4 Settings page — audit log viewer

New page at `/settings/kill-switch` — shows the last 50 activation/deactivation events from `kill_switch_audit`.

---

## 15. Sequence Diagrams

### 15.1 Activation

```
User            UI              API                    Service           DB / Cache     SocketIO    Telegram
  │              │                │                       │                   │            │           │
  ├─click────────>│                │                       │                   │            │           │
  │   "Kill"     │                │                       │                   │            │           │
  │              │─confirm modal──│                       │                   │            │           │
  │              │                │                       │                   │            │           │
  │─UNLOCK type─>│                │                       │                   │            │           │
  │              │──POST activate─>                       │                   │            │           │
  │              │                ├─activate_kill_switch─>│                   │            │           │
  │              │                │                       ├─set flag──────────>│           │           │
  │              │                │                       ├─invalidate cache──>│           │           │
  │              │                │                       ├─emit ksa event────────────────>│           │
  │              │                │                       │                   │            ├─broadcast>│
  │              │                │                       │                   │            │           │
  │              │                │                       ├─parallel cleanup:                          │
  │              │                │                       │   cancel live orders                       │
  │              │                │                       │   close live positions                     │
  │              │                │                       │   cancel sandbox orders                    │
  │              │                │                       │   close sandbox positions                  │
  │              │                │                       │   stop python strategies                   │
  │              │                │                       │   abort flows                              │
  │              │                │                       │                   │            │           │
  │              │                │                       ├─audit row─────────>│           │           │
  │              │                │                       ├─send TG summary───────────────────────────>│
  │              │                │                       ├─emit complete─────────────────>│           │
  │              │                │<──cleanup_summary──────│                   │            │           │
  │              │<─200 + summary─│                       │                   │            │           │
  │<─toast + UI──│                │                       │                   │            │           │
  │  banner      │                │                       │                   │            │           │
```

### 15.2 Deactivation

```
User            UI              API                    DB / Cache     SocketIO
  │              │                │                       │             │
  ├─click────────>│                │                       │             │
  │   "Unlock"   │                │                       │             │
  │              │─check min_unlock (countdown visible)    │             │
  │              │                │                       │             │
  │─type UNLOCK─>│                │                       │             │
  │              │──POST deactiv──>                       │             │
  │              │                ├─validate window───────>│             │
  │              │                ├─validate confirm──────>│             │
  │              │                ├─clear flag────────────>│             │
  │              │                ├─invalidate cache──────>│             │
  │              │                ├─emit ks_deactivated───────────────>│
  │              │                ├─audit row─────────────>│             │
  │              │                ├─send TG note──────────────────────>
  │              │<─200───────────│                       │             │
  │<─banner gone─│                │                       │             │
```

---

## 16. Concurrency & Crash Safety

### 16.1 Flag is authoritative in the DB

The in-memory cache is a read optimization, not the source of truth. Every service-function check reads through `is_kill_switch_active()` which falls back to DB on cache miss.

### 16.2 Activation transaction

`activate_kill_switch()` writes the flag in a transaction with the timestamps. Failure at any step BEFORE the DB write returns `500` and leaves the flag untouched. Failure AFTER the DB write is logged to the audit table with partial cleanup counts — the flag stays `true`.

### 16.3 Worker process crash mid-activation

Because the flag is persisted in `db/openalgo.db`, a Gunicorn worker crash (or host reboot) mid-activation leaves the flag as whatever was last committed. On process startup, `is_kill_switch_active()` re-reads from DB. User sees the active state correctly on next page load.

### 16.4 Concurrent activate calls

Use a `SELECT ... FOR UPDATE` (or SQLAlchemy-level `with_for_update()`) when reading the Settings row inside `activate_kill_switch()`. Second concurrent call sees already-active → returns `already_active=true` without re-running cleanup.

### 16.5 Cleanup idempotency

All six cleanup steps are idempotent:
- `cancelallorder` on an empty book → no-op
- `close_position` with no positions → no-op
- `stop_strategy_process` on a stopped strategy → no-op

Safe to re-run if needed.

---

## 17. Security & Authorization

- Kill-switch endpoints require **session auth** (for UI) or **API-key auth** (for programmatic) — identical to every other order API.
- **Deactivation** requires the `UNLOCK` confirmation string — prevents scripted/accidental deactivation.
- **Telegram deactivation** bound to the single registered Telegram chat — an attacker who guesses the bot token still needs to be the registered user to issue the command.
- **Audit trail** every activation/deactivation — irrevocable record of who did what.
- **Rate limit** `/api/v1/killswitch/activate` to 5/min to prevent a botched script from hammering it.
- No API key has *more* power than the single user's session — OpenAlgo's single-user deployment model means we don't need role-based access control for v1.

---

## 18. Telegram Security Considerations

The Telegram bot already operates on the assumption that the user's chat ID is registered in their OpenAlgo instance. The kill switch commands inherit that trust model:

- Unregistered chats → "Not authorized"
- Registered chat → full kill-switch control
- **No Telegram-initiated second factor** (deliberate — the whole point of Telegram control is that the dashboard may be unreachable)

---

## 19. Testing Plan

### 19.1 Unit tests (`test/test_kill_switch.py`)

- `test_is_kill_switch_active_defaults_false`
- `test_set_kill_switch_persists_to_db`
- `test_cache_invalidation_on_set`
- `test_enforce_decorator_rejects_when_active`
- `test_enforce_decorator_allows_cancel_op`
- `test_deactivate_before_min_unlock_fails`
- `test_deactivate_wrong_confirmation_fails`
- `test_activate_is_idempotent`

### 19.2 Integration tests

- Full end-to-end REST call → flag set → subsequent `placeorder` returns 403.
- Flow executor aborts in-flight workflow when flag flips.
- Python strategy process tree: start a dummy strategy, flip flag, assert process is SIGTERMed within 5s.
- Sandbox: pre-populate `sandbox.db` with 3 open orders + 2 positions, trigger kill switch, assert all cancelled/closed.

### 19.3 Manual QA checklist

- [ ] Activate from UI → red banner appears, Telegram summary received
- [ ] Activate from Telegram (`/killswitch on`) → UI banner updates via SocketIO
- [ ] Attempt order from Swagger (`/api/v1/placeorder`) → 403 with `KILL_SWITCH_ACTIVE`
- [ ] TradingView webhook fires → 403 returned, no order reaches broker
- [ ] Chartink scanner alert → 403, rejection logged
- [ ] Start a Python strategy → blocked with clear error
- [ ] Launch a flow via UI → blocked
- [ ] `cancelorder` manually → still works
- [ ] Deactivate before 60s → rejected with retry_after
- [ ] Deactivate with wrong confirmation → rejected
- [ ] Deactivate correctly after 60s → banner clears, UI unblocked
- [ ] **After deactivation**: previously-stopped strategies stay stopped (not auto-started)
- [ ] **After deactivation**: previously-aborted flows stay `is_active=false` if they were disabled
- [ ] Audit log shows both activation and deactivation
- [ ] Flip analyzer ON while kill switch active → analyzer toggle succeeds, but no new sandbox orders accepted
- [ ] Simulate broker auth failure during cleanup → partial counts logged, no crash
- [ ] Kill Gunicorn worker mid-activation → after restart, flag still active, state visible

### 19.4 Load / stress

- 1000 REST `/placeorder` calls/sec while kill switch is active — all return 403 in <20ms (cache hit path only).
- Activate while 50 concurrent flows are running — all should either abort cleanly or hit the service gate.

---

## 20. Rollout Plan

### Phase 1 — core (this plan)

1. Database migration for `Settings` new columns + `kill_switch_audit` table
2. `utils/kill_switch.py` with decorator
3. `services/kill_switch_service.py` orchestrator
4. REST endpoints (`activate`, `deactivate`, `status`, `audit`)
5. Decorator applied to every order-placing service
6. Webhook blueprint early rejection
7. Flow executor + Python strategy launcher checks
8. Sandbox cleanup hook
9. Telegram `/killswitch` commands
10. React banner + button + form-disable hook
11. Audit log viewer page
12. Unit + integration tests
13. QA pass against the manual checklist
14. Release as `v2.0.1.0` with a prominent changelog entry

### Phase 2 — v2 ideas (not this plan)

- Automatic triggers: daily-loss, MTM drawdown, latency
- Per-strategy granularity
- Scheduled kill-switch windows (e.g., auto-activate after 3:20 PM)
- Hardware 2FA on deactivation (WebAuthn)
- Separate "soft mode" that blocks orders but doesn't close positions

---

## 21. Migration Notes

- Existing deployments will get the new columns via a lightweight `ALTER TABLE` on startup (following the pattern in other DB modules) — default `kill_switch_active=False` so existing behavior is unchanged.
- No backward-compat shims needed — new endpoint paths, new Telegram command, new UI component.
- `frontend/dist/` rebuild handled automatically by CI.

---

## 22. Open Questions

1. Should we add a **"Test mode"** where activation runs cleanup but doesn't actually block new orders? Useful to verify the cleanup logic without interrupting trading. → Tentatively no for v1; add if requested.
2. Do we want an **email fallback** alongside Telegram for activation notifications? → Defer unless the user explicitly asks.
3. For **multi-broker setups**, should the per-broker cleanup errors block overall "success" reporting? → No — report partial success with per-broker detail in the summary.
4. Should deactivation require **both** UI confirmation *and* Telegram confirmation? → No for v1 (each channel is self-contained and the 60-second hold already guards against fat-finger).

---

## 23. Acceptance Criteria

The kill switch is considered shipped when:

1. Every manual QA checklist item passes in both analyzer-off and analyzer-on states.
2. Unit test coverage of `kill_switch_service.py` ≥ 85%.
3. End-to-end test for each entry path (REST, TV webhook, GC webhook, Chartink webhook, Flow, Python strategy, MCP) passes the "403 returned when active" assertion.
4. A fresh activation-from-UI round trip (click → banner visible → TG message received → all positions flat → all orders cancelled) completes in **≤ 10 seconds** against a stub broker.
5. Documentation: one new userguide module (`docs/userguide/31-kill-switch/README.md`) with screenshots — this is a **user-visible feature** and deserves first-class docs, not just a design note.

---

## 24. References

- Current `analyze_mode` implementation as the flag pattern reference: `database/settings_db.py:79-105`
- Action Center as the existing "approval gate" reference: `services/order_router_service.py:32-75`, `database/action_center_db.py`
- Existing stop mechanism for Python strategies: `blueprints/python_strategy.py:603`
- Sandbox service entry: `services/sandbox_service.py` (auto square-off path)
- Telegram bot extension surface: `services/telegram_bot_service.py:1113` (existing `cmd_orderbook` is the nearest pattern)
