# Strategy v2 — Implementation Plan

**Status:** Design — not yet built
**Author:** Rajandran R (marketcalls)
**Date:** 2026-05-06
**Target release:** TBD (post-2.0.1.0)
**Supersedes (in part):** `2026-02-06-strategy-risk-management-prd.md`
**Related:** `2026-04-24-kill-switch-implementation-plan.md` (kill switch is account-wide; this engine respects it)

---

## 0. TL;DR

The current `/strategy` feature is a **thin webhook → single-order router** with no per-strategy attribution, no leg concept, no real-time risk management, and no live P&L. The user has asked for a Tradetron/Algotest/Streak-style **strategy execution engine** that:

- Receives external signals (TradingView / Python / Amibroker / any HTTP webhook) on the existing webhook URL contract.
- Manages multi-leg portfolios (Cash / Futures / Options) with leg-level and strategy-level risk controls.
- Tracks strategy-scoped orderbook, tradebook, and positions in the **same JSON shape** as the global `/orderbook`, `/tradebook`, `/positionbook` endpoints.
- Runs an RMS engine driven by `services/market_data_service.py` ticks, evaluating SL / target / trail rules per leg and per strategy, with tick-size correctness, pts/% unit support, and X/Y ratchet trailing.
- Supports many concurrent strategies under one user (single-user platform — concurrency is across strategies, not users).
- Operates identically in **live** and **sandbox** modes via a `BrokerAdapter` interface.
- Is event-driven end to end (broker WS → market_data_service → engine → Socket.IO to UI), with polling only as a documented fallback when broker WS is unavailable.

Architectural decision: **hybrid rewrite**. Keep the webhook URL contract (external integrations don't break). Rewrite everything below it as a v2 subsystem alongside v1, with a migration step that converts v1 strategies into 1-leg v2 strategies.

---

## 1. Goals & Non-Goals

### 1.1 Goals

1. **Webhook URL preserved + optional security upgrade** — existing `POST /strategy/webhook/<uuid>` URLs continue to work unchanged for the URL contract. New layer adds **body-secret** (TradingView-compatible — TV cannot set custom HTTP headers) and **HMAC-SHA256 header signing** (Python/Amibroker-grade). Each strategy picks its signing method; URL-only stays the default for backward compatibility. Optional replay-protection window and IP allowlist on top.
2. **Multi-leg strategies** — a strategy is composed of N legs. Each leg is `CASH | FUT | OPT`. Legs may carry different expiries (diagonals), strike criteria (ATM / ITM / OTM / premium / delta), and per-leg risk parameters.
3. **Strategy-scoped reporting** — strategy_orders / strategy_trades / strategy_positions tables, returning the same JSON schema as `/api/v1/orderbook`, `/api/v1/tradebook`, `/api/v1/positionbook`. Frontend reuses existing OrderBookTable / TradeBookTable / PositionBookTable React components.
4. **Real-time RMS engine** — driven by `market_data_service.subscribe_critical()`; evaluates leg-level (target, SL, trail X/Y, momentum — `pts` or `%` per parameter) and strategy-level (overall SL, overall target, profit lock, trail to entry — **abs ₹ only**, no `%` since strategy capital is not tracked) rules per tick with tick-size-correct order prices.
5. **No `placesmartorder` in the strategy engine.** Entries use `place_order` (CASH/FUT), `place_options_order` / `place_options_multiorder` (OPT), or `basket_order` (multi-leg CASH/FUT). Exits always use `place_order` or `basket_order` with explicit symbols read from `strategy_positions` (no re-resolution).
6. **Account-level RMS** — hard cap on concurrent runs, cumulative daily loss in **abs ₹**, and post-loss cooldown across all active strategies. No capital-deployment cap (no capital tracking).
7. **Live and sandbox parity** — same engine, same RMS, same DB shape, same UI. Mode flag on `strategy_runs` selects the `BrokerAdapter` implementation. Sandbox uses `services/sandbox_service.py` and `db/sandbox.db`. Sandbox fills at LTP **with zero slippage** (no slippage model needed).
8. **Event-driven everywhere; poll only as fallback.** Market data, broker order updates, position changes, and UI updates all push. When a broker WS channel is unavailable or stale, automatic poll-fallback engages with explicit health visibility (mirrors `market_data_service.is_trade_management_safe()`).
9. **IST timestamps in user-visible payloads, UTC in DB.** Reuse existing `/orderbook` and `/tradebook` formats (`'08-May-2026 14:30:45'` and `'14:30:45'`).
10. **Auditability.** Every state transition and every RMS decision writes a `strategy_events` row; UI replays the timeline.
11. **Idempotency.** State machine + DB constraints prevent duplicate runs, duplicate exits on the same tick, and duplicate placement on webhook retries.
12. **Dead-code cleanup at the end.** v1 internals are removed once migration is complete (Phase 8). Tracker included in this plan.

### 1.2 Non-Goals (v2 scope)

- **Multi-user / multi-tenant.** OpenAlgo remains single-user per deployment.
- **Backtesting / historical replay.** Sandbox is forward-test only. Historical replay deferred.
- **Strategy marketplace / sharing.** Strategies are local-only.
- **ML-driven strike selection or signal generation.** Strike criteria are deterministic (ATM/ITM/OTM/premium/delta thresholds).
- **Holdings (CNC) tracking at strategy level.** Holdings are multi-day equity positions in DEMAT — they don't map cleanly to a strategy lifecycle. Strategies track orders/trades/positions only.
- **Hardware MFA on strategy actions.** Out of scope.
- **Per-strategy capital allocation, capital tracking, or capital UI.** Strategies do not carry a capital-allocation field; broker margin remains shared at the account level. All RMS thresholds (overall SL/target/lock, daily loss cap) are expressed in **abs ₹** only. Per-leg SL/target/trail can still use `pts` or `%` since `%` there is relative to the leg's own entry price.
- **Sandbox slippage model.** Sandbox fills execute at the live LTP with zero slippage. Simple and predictable; matches the user's testing intent.
- **Webhook duplicate signals.** While a strategy is `ARMED|ENTERING|IN_TRADE|EXITING`, additional webhooks for the same strategy are **rejected** with `409 ALREADY_RUNNING`. No queueing.
- **Auto-resume of strategies after kill-switch deactivation.** Same rule as kill switch — manual restart only.

### 1.3 Modes of Operation

| Mode | Behavior |
|---|---|
| **Live** | Orders placed via real broker; positions are real money; sandbox unaffected. |
| **Sandbox (analyzer)** | Orders placed via `services/sandbox_service.py`; uses real-time LTPs from `market_data_service` for fill simulation; `db/sandbox.db` holds virtual positions; live broker untouched. |

Mode is set at strategy creation and **immutable for any given run**. Switching mode requires a new run.

---

## 2. User Stories

- **US-1**: As a trader, I create an iron condor strategy on NIFTY with weekly expiry, set per-leg SL/target/trail (mixing pts and % units), set overall SL of -₹5,000 and overall target of +₹10,000 with profit-lock at +₹6,000 / floor +₹4,000. I send a TradingView webhook to enter; the engine resolves all four legs to live option symbols, places via `place_options_multiorder` (BUY-first), and starts monitoring.
- **US-2**: As a trader, I run 5 strategies concurrently. The dashboard shows live aggregate MTM across all 5, with per-strategy P&L. The engine subscribes once per unique symbol via `market_data_service` (no duplicate broker subscriptions).
- **US-3**: As a trader, when one of my strategies hits its overall SL, all 4 legs of that strategy exit via `basket_order`, the run transitions IN_TRADE → EXITING → CLOSED, and an event is logged with reason=`OVERALL_SL`. My other 4 strategies are unaffected.
- **US-4**: As a trader, my account has `max_daily_loss=-₹10,000`. After two losing strategies cumulatively breach that, the account locks out — new webhooks return `429 ACCOUNT_LOCKED` with reason. I manually clear the lockout from the dashboard.
- **US-5**: As a trader, I create a 10-stock cash momentum strategy. The engine places all 10 entries via one `basket_order` call, monitors each stock's leg-level SL/target, and on signal-EXIT closes all 10 via one `basket_order`.
- **US-6**: As a trader, my broker's order-update WS goes down mid-trade. The order channel marks STALE, the engine engages REST polling on `/orderbook` for open orders, and the UI shows "Order channel: degraded — polling fallback active". When WS reconnects, polling pauses automatically.
- **US-7**: As a trader, I sandbox-test a new strategy. It runs identically to live — same entry orchestration, same RMS, same UI — but with virtual fills from `sandbox_service`. The strategy detail page shows a clear `[SANDBOX]` badge. P&L is segregated from live in account dashboards.
- **US-8**: As a trader, I click "Close Leg 3" on the strategy detail page. The engine places one `place_order` exit for leg 3 only (using the cached symbol), the leg's row updates, the run stays IN_TRADE for the other three legs.
- **US-9**: As a trader, I open a closed strategy run. I see the full event timeline: signal received → resolved → 4 entry fills → 7 trail advances on leg 2 → leg 1 SL hit → overall target hit → 3-leg basket exit → CLOSED. Each event has timestamp in IST, with the trigger price and resulting state.
- **US-10**: As a trader, my v1 strategy (single-symbol Chartink alert) keeps working after upgrade. Migration converted it to a 1-leg CASH strategy in v2 schema; webhook URL unchanged.

---

## 3. Architecture

### 3.1 Subsystem layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  External signals (TradingView / Python / Amibroker / any HTTP)     │
│         │                                                           │
│         ▼  POST /strategy/webhook/<uuid>                            │
│  ┌────────────────────────────────────────────────────────────┐     │
│  │  blueprints/strategy.py (webhook route — thin trigger)     │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/ingestion_service.py                    │     │
│  │  - validates webhook signal                                │     │
│  │  - account_rms.preflight() (concurrency, daily loss cap)   │     │
│  │  - creates strategy_run row                                │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/leg_resolver_service.py                 │     │
│  │  - CASH: explicit symbol                                   │     │
│  │  - FUT:  underlying + expiry → symbol                      │     │
│  │  - OPT:  underlying + expiry + strike_criteria → symbol    │     │
│  │    (uses option_chain_service / quotes for live LTP)       │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/execution_service.py                    │     │
│  │  - splits legs by segment                                  │     │
│  │  - CASH/FUT (multi):  basket_order_service                 │     │
│  │  - CASH/FUT (single): place_order_service                  │     │
│  │  - OPT (multi):       options_multiorder_service           │     │
│  │  - OPT (single):      place_options_order_service          │     │
│  │  - writes strategy_orders rows tagged with run_id          │     │
│  │  - delegates to BrokerAdapter (live | sandbox)             │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/rms_engine.py (long-lived registry)     │     │
│  │  ┌──────────────────────────────────────────────────────┐  │     │
│  │  │  Tick callback (subscribe_critical via               │  │     │
│  │  │  market_data_service.SubscriberPriority.CRITICAL)    │  │     │
│  │  └──────────────────────────────────────────────────────┘  │     │
│  │  Per tick:                                                 │     │
│  │    1. is_trade_management_safe()? else pause               │     │
│  │    2. compute leg/strategy MTM, peak, drawdown             │     │
│  │    3. evaluate strategy-level rules (overall SL/T/lock)    │     │
│  │    4. evaluate leg-level rules (SL/T/trail X-Y/momentum)   │     │
│  │    5. if exit: state ← EXITING; place exits                │     │
│  │    6. write strategy_pnl_snapshots (debounced ~1Hz)        │     │
│  │    7. write strategy_events on every decision              │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/realtime_broadcaster.py                 │     │
│  │  - subscribes LOW priority to market_data_service          │     │
│  │  - debounces per-run to 5Hz                                │     │
│  │  - emits Socket.IO: strategy_pnl_tick / leg_update /       │     │
│  │                     state_change / event / health          │     │
│  └─────────────────────┬──────────────────────────────────────┘     │
│                        │                                            │
│  ┌─────────────────────▼──────────────────────────────────────┐     │
│  │  services/strategy/order_update_channel.py                 │     │
│  │  - subscribes broker order-update WS where supported       │     │
│  │  - reconciles fills → strategy_trades + strategy_positions │     │
│  │  - poll fallback when WS stale (mirrors                    │     │
│  │    market_data_service.is_trade_management_safe pattern)   │     │
│  └────────────────────────────────────────────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘
```

### 3.2 Concurrency model

- **Single dispatcher thread** for the engine. Eventlet single worker; no per-run thread.
- Engine holds an in-memory `active_runs: dict[run_id, RunState]` and a reverse index `symbol_to_runs: dict[symbol_key, set[run_id]]`.
- `market_data_service.subscribe_critical(filter_symbols=union_of_all_legs)` delivers ticks; engine fans out per-tick to affected runs serially. Each evaluation is microseconds — even 50 active runs × 500 ticks/sec is comfortable.
- Per-run state (peak_mtm, profit_locked latch, leg trail levels, last_anchor) lives in memory; persisted to DB on every change; rehydrated on startup from DB rows where `state IN ('ARMED','IN_TRADE','EXITING')`.
- **Exception fence per run**: any exception in `_evaluate_run` is caught, logged to `strategy_events` with type=`ENGINE_ERROR`, run marked `ERRORED`, stops monitoring. One bad strategy never poisons the dispatcher.

### 3.3 State machines

**Strategy run state machine:**

```
        DRAFT          (UI-only, never persisted as a run)
           │
           │ user activates strategy
           ▼
        ARMED          (waiting for entry signal)
           │
           │ webhook arrives, ingestion + leg resolver succeed
           ▼
       ENTERING        (entry orders submitted, awaiting all fills)
           │
           │ all legs filled
           ▼
       IN_TRADE        (RMS active)
           │
           │ exit trigger (any reason)
           ▼
       EXITING         (exit orders submitted; engine stops monitoring new triggers)
           │
           │ all legs flat (net_qty=0 across all legs)
           ▼
        CLOSED         (terminal)

       Failure paths:
        ENTERING ──► ENTRY_FAILED  (broker rejected entries)
        EXITING  ──► EXIT_FAILED   (broker rejected/partial exit; needs operator)
        any      ──► ERRORED       (engine exception)
        any      ──► STOPPED       (user manual abort)
```

**Per-leg state (within a run):**

```
   PENDING_ENTRY ─► OPEN ─► EXITING_LEG ─► CLOSED
                    │
                    └─► ENTRY_REJECTED (rare; broker rejected this leg only)
```

A run can have some legs CLOSED while others remain OPEN — run state stays IN_TRADE until **all** legs are closed.

---

## 4. Database schema

### 4.1 New tables (additive to `db/openalgo.db`)

All tables prefixed `strategy_` to namespace cleanly. v1 tables (`strategies`, `strategy_symbol_mappings`) **remain in place** through Phases 0–7; deleted in Phase 8.

#### 4.1.1 `strategies_v2`

```sql
CREATE TABLE strategies_v2 (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  name              VARCHAR(80) NOT NULL,
  webhook_id        VARCHAR(36) NOT NULL UNIQUE,             -- UUID; the URL secret (always required)
  user_id           VARCHAR(255) NOT NULL,
  platform          VARCHAR(50),                             -- 'tradingview'|'amibroker'|'python'|'manual'
  underlying        VARCHAR(50),                             -- 'NIFTY','BANKNIFTY' (NULL for pure CASH)
  underlying_exchange VARCHAR(15),                           -- 'NSE_INDEX' for index underlyings
  is_intraday       BOOLEAN DEFAULT 1,
  start_time        VARCHAR(5)  NOT NULL,                    -- 'HH:MM' IST
  end_time          VARCHAR(5)  NOT NULL,
  squareoff_time    VARCHAR(5),                              -- intraday only
  state             VARCHAR(15) NOT NULL DEFAULT 'DRAFT',
  is_active         BOOLEAN DEFAULT 0,                       -- master enable
  mode              VARCHAR(10) NOT NULL DEFAULT 'live',     -- 'live' | 'sandbox'

  -- Webhook security (see §8.4). Never displayed in UI lists; revealed once on creation/rotation.
  webhook_signing_method  VARCHAR(20) NOT NULL DEFAULT 'NONE',
                                                            -- 'NONE'|'BODY_SECRET'|'HMAC_SHA256'|'BOTH'
  webhook_secret          VARCHAR(64),                      -- pre-shared body token (for BODY_SECRET / TradingView)
  webhook_hmac_key        VARCHAR(128),                     -- HMAC-SHA256 shared key (Python / Amibroker)
  webhook_replay_window_seconds INTEGER DEFAULT 0,           -- 0 = disabled; >0 = require body 'ts' within window
  webhook_ip_allowlist    TEXT,                             -- JSON array of CIDRs; NULL = no IP filter

  created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- UTC
  updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- UTC
  CHECK (state IN ('DRAFT','ARMED','DISABLED','ARCHIVED')),
  CHECK (mode IN ('live','sandbox')),
  CHECK (webhook_signing_method IN ('NONE','BODY_SECRET','HMAC_SHA256','BOTH'))
);

CREATE INDEX idx_strategies_v2_user      ON strategies_v2(user_id);
CREATE INDEX idx_strategies_v2_webhook   ON strategies_v2(webhook_id);
CREATE INDEX idx_strategies_v2_active    ON strategies_v2(is_active);
```

#### 4.1.2 `strategy_legs`

Segment-aware via conditional NULLs + CHECK constraints. One leg-resolver, three branches.

```sql
CREATE TABLE strategy_legs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL REFERENCES strategies_v2(id) ON DELETE CASCADE,
  leg_index         INTEGER NOT NULL,                        -- 1, 2, 3...
  segment           VARCHAR(5) NOT NULL,                     -- 'CASH' | 'FUT' | 'OPT'
  position          VARCHAR(1) NOT NULL,                     -- 'B' | 'S'
  product           VARCHAR(10) NOT NULL,                    -- 'MIS'|'CNC'|'NRML'

  -- CASH-only
  symbol_cash       VARCHAR(50),                             -- e.g. 'INFY'
  qty               INTEGER,                                 -- raw shares

  -- FUT + OPT
  expiry_type       VARCHAR(20),                             -- 'CURRENT_WEEK'|'NEXT_WEEK'|'CURRENT_MONTH'|'NEXT_MONTH'
  lots              INTEGER,                                 -- multiplied by lot_size at order time

  -- OPT-only
  option_type       VARCHAR(2),                              -- 'CE' | 'PE'
  strike_criteria   VARCHAR(20),                             -- 'ATM'|'STRIKE_OFFSET'|'PREMIUM'|'DELTA'
  strike_value      DECIMAL(12,4),                           -- offset (int) for STRIKE_OFFSET, premium target etc.

  -- Per-leg risk (each pair stored independently — pts or pct)
  target_enabled    BOOLEAN DEFAULT 0,
  target_value      DECIMAL(12,4),
  target_unit       VARCHAR(3),                              -- 'pts' | 'pct'

  sl_enabled        BOOLEAN DEFAULT 0,
  sl_value          DECIMAL(12,4),
  sl_unit           VARCHAR(3),

  trail_enabled     BOOLEAN DEFAULT 0,
  trail_x           DECIMAL(12,4),                           -- favorable-move trigger
  trail_y           DECIMAL(12,4),                           -- amount to advance SL
  trail_unit        VARCHAR(3),                              -- shared by X and Y

  momentum_enabled  BOOLEAN DEFAULT 0,
  momentum_value    DECIMAL(12,4),
  momentum_unit     VARCHAR(3),
  momentum_config   TEXT,                                    -- json blob for advanced momentum

  -- Cached at arm-time (avoids hot-path DB lookups)
  resolved_symbol   VARCHAR(50),
  resolved_exchange VARCHAR(15),
  lot_size_cache    INTEGER,
  tick_size_cache   DECIMAL(12,4),
  freeze_qty_cache  INTEGER,
  resolved_at       TIMESTAMP,                               -- UTC

  created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- UTC
  updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- UTC

  CHECK (segment IN ('CASH','FUT','OPT')),
  CHECK (position IN ('B','S')),
  CHECK (
    (segment = 'CASH' AND symbol_cash IS NOT NULL AND qty IS NOT NULL)
    OR (segment = 'FUT' AND lots IS NOT NULL AND expiry_type IS NOT NULL)
    OR (segment = 'OPT' AND lots IS NOT NULL AND expiry_type IS NOT NULL
        AND option_type IS NOT NULL AND strike_criteria IS NOT NULL)
  )
);

CREATE INDEX idx_strategy_legs_strategy ON strategy_legs(strategy_id);
```

#### 4.1.3 `strategy_risk_config`

One row per strategy; overall (strategy-level) RMS settings.

```sql
CREATE TABLE strategy_risk_config (
  strategy_id       INTEGER PRIMARY KEY REFERENCES strategies_v2(id) ON DELETE CASCADE,

  -- Overall settings are abs ₹ only (no capital tracking → no % reference)
  overall_sl_enabled     BOOLEAN DEFAULT 0,
  overall_sl_abs         DECIMAL(16,4),                      -- ₹: positive number; engine treats as -|x|

  overall_target_enabled BOOLEAN DEFAULT 0,
  overall_target_abs     DECIMAL(16,4),                      -- ₹

  lock_profit_enabled    BOOLEAN DEFAULT 0,
  lock_at_abs            DECIMAL(16,4),                      -- ₹: when peak ≥ this, arm
  lock_min_abs           DECIMAL(16,4),                      -- ₹: floor to protect

  -- Per-leg ratchet to break-even — uses pts or % of leg's own entry (no capital ref)
  trail_to_entry_enabled    BOOLEAN DEFAULT 0,
  trail_to_entry_threshold  DECIMAL(12,4) DEFAULT 0,         -- pts or % in favor before SL → entry
  trail_to_entry_unit       VARCHAR(3) DEFAULT 'pct',        -- 'pts' | 'pct'

  updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 4.1.4 `strategy_runs`

One row per execution lifecycle.

```sql
CREATE TABLE strategy_runs (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL REFERENCES strategies_v2(id),
  state             VARCHAR(20) NOT NULL,
  mode              VARCHAR(10) NOT NULL,                    -- snapshotted from strategy at run-create
  signal_payload    TEXT,                                    -- json: original webhook body
  signal_source     VARCHAR(20),                             -- 'webhook'|'manual'|'scheduled'

  triggered_at      TIMESTAMP NOT NULL,                      -- UTC; signal arrival
  entered_at        TIMESTAMP,                               -- UTC; first leg fill
  exited_at         TIMESTAMP,                               -- UTC; all legs closed
  exit_reason       VARCHAR(30),                             -- TARGET|SL|TRAIL|OVERALL_TARGET|OVERALL_SL|PROFIT_LOCK|SQUAREOFF|MANUAL|WEBHOOK_EXIT|ENGINE_ERROR

  -- live state (in-memory primarily, persisted on every change)
  peak_mtm          DECIMAL(16,4) DEFAULT 0,
  trough_mtm        DECIMAL(16,4) DEFAULT 0,
  profit_locked     BOOLEAN DEFAULT 0,                       -- latched once peak ≥ lock_at
  realized_pnl      DECIMAL(16,4) DEFAULT 0,
  max_unrealized_pnl DECIMAL(16,4) DEFAULT 0,
  max_drawdown      DECIMAL(16,4) DEFAULT 0,

  CHECK (state IN ('ARMED','ENTERING','IN_TRADE','EXITING','CLOSED','ENTRY_FAILED','EXIT_FAILED','ERRORED','STOPPED')),
  CHECK (mode IN ('live','sandbox'))
);

CREATE INDEX idx_strategy_runs_strategy ON strategy_runs(strategy_id);
CREATE INDEX idx_strategy_runs_state    ON strategy_runs(state);
-- Critical: prevents two ARMED/IN_TRADE runs for the same strategy simultaneously
CREATE UNIQUE INDEX idx_strategy_runs_active
    ON strategy_runs(strategy_id)
    WHERE state IN ('ARMED','ENTERING','IN_TRADE','EXITING');
```

#### 4.1.5 `strategy_orders`

Same schema as `/orderbook` response row + strategy attribution.

```sql
CREATE TABLE strategy_orders (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL,
  run_id            INTEGER NOT NULL REFERENCES strategy_runs(id),
  leg_id            INTEGER REFERENCES strategy_legs(id),

  -- Columns named identically to /orderbook response row:
  action            VARCHAR(10) NOT NULL,                    -- 'BUY' | 'SELL'
  symbol            VARCHAR(50) NOT NULL,
  exchange          VARCHAR(15) NOT NULL,
  orderid           VARCHAR(50),                             -- broker_orderid (NULL until placed)
  product           VARCHAR(10) NOT NULL,
  quantity          VARCHAR(20) NOT NULL,
  price             DECIMAL(12,4) DEFAULT 0,
  pricetype         VARCHAR(10) NOT NULL,                    -- MARKET|LIMIT|SL|SL-M
  order_status      VARCHAR(20) DEFAULT 'pending',           -- pending|open|complete|cancelled|rejected|trigger_pending
  trigger_price     DECIMAL(12,4) DEFAULT 0,
  timestamp         VARCHAR(30),                             -- IST string from broker, '08-May-2026 14:30:45'

  -- Strategy-only metadata (not in /orderbook output):
  source            VARCHAR(30) NOT NULL,                    -- entry|exit_overall_sl|exit_overall_target|exit_leg_sl|exit_leg_target|exit_trail|squareoff|manual_close_all|manual_close_leg
  mode              VARCHAR(10) NOT NULL,
  rms_event_id      INTEGER REFERENCES strategy_events(id),
  placed_at         TIMESTAMP,                               -- UTC; engine clock
  last_status_update_at TIMESTAMP,                           -- UTC

  CHECK (mode IN ('live','sandbox'))
);

CREATE INDEX idx_strategy_orders_run    ON strategy_orders(run_id);
CREATE INDEX idx_strategy_orders_strat  ON strategy_orders(strategy_id);
CREATE INDEX idx_strategy_orders_status ON strategy_orders(order_status);
```

#### 4.1.6 `strategy_trades`

Same schema as `/tradebook` row + attribution.

```sql
CREATE TABLE strategy_trades (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id          INTEGER NOT NULL REFERENCES strategy_orders(id),
  strategy_id       INTEGER NOT NULL,
  run_id            INTEGER NOT NULL,
  leg_id            INTEGER,

  action            VARCHAR(10) NOT NULL,
  symbol            VARCHAR(50) NOT NULL,
  exchange          VARCHAR(15) NOT NULL,
  orderid           VARCHAR(50),
  product           VARCHAR(10),
  quantity          DECIMAL(12,2) NOT NULL,
  average_price     DECIMAL(12,4) NOT NULL,
  trade_value       DECIMAL(16,4) NOT NULL,                  -- average_price * quantity
  timestamp         VARCHAR(30),                             -- IST 'HH:MM:SS' from broker
  broker_tradeid    VARCHAR(50),

  traded_at         TIMESTAMP                                -- UTC; engine clock
);

CREATE INDEX idx_strategy_trades_run  ON strategy_trades(run_id);
CREATE INDEX idx_strategy_trades_leg  ON strategy_trades(leg_id);
```

#### 4.1.7 `strategy_positions`

Net position per leg per run, derived from orders + trades. Same shape as `/positionbook` row + attribution + RMS state.

```sql
CREATE TABLE strategy_positions (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL,
  run_id            INTEGER NOT NULL,
  leg_id            INTEGER NOT NULL,

  -- /positionbook columns
  symbol            VARCHAR(50) NOT NULL,
  exchange          VARCHAR(15) NOT NULL,
  product           VARCHAR(10) NOT NULL,
  quantity          VARCHAR(20),                             -- net qty as string (negative=short); /positionbook style
  average_price     VARCHAR(20),
  ltp               VARCHAR(20),                             -- updated on every tick
  pnl               VARCHAR(20),                             -- string; same style as global

  -- Engine-internal (decimals for math)
  net_qty           INTEGER NOT NULL DEFAULT 0,
  avg_entry         DECIMAL(12,4),
  ltp_decimal       DECIMAL(12,4),
  unrealized_pnl    DECIMAL(16,4) DEFAULT 0,
  realized_pnl     DECIMAL(16,4) DEFAULT 0,

  -- RMS live state (per-position trail/target)
  current_sl_price       DECIMAL(12,4),                      -- effective SL after trail advances
  current_target_price   DECIMAL(12,4),
  last_trail_anchor      DECIMAL(12,4),
  trail_advances_count   INTEGER DEFAULT 0,
  peak_favorable_price   DECIMAL(12,4),
  trail_to_entry_armed   BOOLEAN DEFAULT 0,                  -- once true, SL pinned ≥ entry for longs

  leg_state         VARCHAR(20) DEFAULT 'PENDING_ENTRY',     -- PENDING_ENTRY|OPEN|EXITING_LEG|CLOSED|ENTRY_REJECTED
  updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,     -- UTC

  CHECK (leg_state IN ('PENDING_ENTRY','OPEN','EXITING_LEG','CLOSED','ENTRY_REJECTED')),
  UNIQUE (run_id, leg_id)
);

CREATE INDEX idx_strategy_positions_run    ON strategy_positions(run_id);
CREATE INDEX idx_strategy_positions_symbol ON strategy_positions(symbol, exchange);
```

#### 4.1.8 `strategy_events`

Append-only audit log of every state-affecting decision. This is what powers the run-detail timeline.

```sql
CREATE TABLE strategy_events (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL,
  run_id            INTEGER,
  leg_id            INTEGER,
  ts                TIMESTAMP NOT NULL,                      -- UTC
  type              VARCHAR(40) NOT NULL,
  payload           TEXT,                                    -- json blob

  CHECK (type IN (
    'SIGNAL_RECEIVED','SIGNAL_REJECTED','RUN_STARTED',
    'LEG_RESOLVED','LEG_PLACED','LEG_FILLED','LEG_REJECTED',
    'TICK_PROCESSED_SUMMARY',
    'TRAIL_ADVANCED','LEG_SL_HIT','LEG_TARGET_HIT',
    'OVERALL_SL_HIT','OVERALL_TARGET_HIT','PROFIT_LOCK_ARMED','PROFIT_LOCK_FLOOR_HIT',
    'TRAIL_TO_ENTRY_ARMED',
    'EXIT_TRIGGERED','EXIT_PARTIAL_FAILURE',
    'STATE_CHANGE','RUN_CLOSED','ENGINE_ERROR',
    'SQUAREOFF_FIRED','MANUAL_CLOSE_ALL','MANUAL_CLOSE_LEG',
    'FEED_PAUSED','FEED_RESUMED','ORDER_CHANNEL_DEGRADED','ORDER_CHANNEL_RESTORED',
    'ACCOUNT_LOCKED','ACCOUNT_UNLOCKED'
  ))
);

CREATE INDEX idx_strategy_events_run ON strategy_events(run_id);
CREATE INDEX idx_strategy_events_ts  ON strategy_events(ts);
```

#### 4.1.9 `strategy_pnl_snapshots`

Append-only time-series for P&L charts. 1Hz during IN_TRADE; off otherwise.

```sql
CREATE TABLE strategy_pnl_snapshots (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  strategy_id       INTEGER NOT NULL,
  run_id            INTEGER NOT NULL,
  ts                TIMESTAMP NOT NULL,                      -- UTC
  agg_mtm           DECIMAL(16,4) NOT NULL,
  peak_mtm          DECIMAL(16,4) NOT NULL,
  drawdown          DECIMAL(16,4) NOT NULL,
  leg_mtms          TEXT                                     -- json: {leg_id: mtm, ...}
);

CREATE INDEX idx_strategy_pnl_run ON strategy_pnl_snapshots(run_id, ts);
```

#### 4.1.10 `account_risk_config`

One row per user (single-user platform).

```sql
CREATE TABLE account_risk_config (
  user_id                       VARCHAR(255) PRIMARY KEY,
  max_concurrent_runs           INTEGER DEFAULT 5,
  max_daily_loss_abs            DECIMAL(16,2),               -- e.g., -10000.00 (negative or store positive + sign)
  cooldown_after_loss_minutes   INTEGER DEFAULT 0,
  max_runs_per_strategy_per_day INTEGER DEFAULT 50,
  min_seconds_between_runs      INTEGER DEFAULT 0,
  is_locked_out                 BOOLEAN DEFAULT 0,
  lockout_until                 TIMESTAMP,                   -- UTC
  lockout_reason                VARCHAR(80),
  updated_at                    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Note: no max_capital_deployed and no max_daily_loss_pct — strategies don't carry capital allocation.
```

#### 4.1.11 `account_state` (derived; could be a view)

Maintained by the engine; denormalized for fast preflight checks.

```sql
CREATE TABLE account_state (
  user_id                  VARCHAR(255) PRIMARY KEY,
  active_run_count         INTEGER DEFAULT 0,
  realized_pnl_today_live  DECIMAL(16,4) DEFAULT 0,
  realized_pnl_today_sandbox DECIMAL(16,4) DEFAULT 0,
  unrealized_pnl_aggregate DECIMAL(16,4) DEFAULT 0,
  updated_at               TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 4.2 Indexes & query patterns

Hot-path queries the engine runs:

| Query | Index used |
|---|---|
| Find runs to dispatch tick to | in-memory `symbol_to_runs`; no DB hit |
| Webhook → existing ARMED/IN_TRADE run check | unique `idx_strategy_runs_active` |
| Strategy-scoped orderbook tab | `idx_strategy_orders_run` |
| Strategy-scoped tradebook tab | `idx_strategy_trades_run` |
| Strategy-scoped positionbook tab | `idx_strategy_positions_run` |
| Run timeline | `idx_strategy_events_run` + `idx_strategy_events_ts` |
| Run P&L chart | `idx_strategy_pnl_run` |
| Account preflight | `account_state` PK lookup |

All tables use the existing **NullPool + scoped_session** pattern from CLAUDE.md (no `StaticPool`).

---

## 5. Service layer

New directory: `services/strategy/`. Modules:

```
services/strategy/
  __init__.py
  ingestion_service.py       # webhook → validate → run-create → handoff to execution
  leg_resolver_service.py    # CASH/FUT/OPT → concrete symbol; tick_size + lot_size cache
  execution_service.py       # entry orchestrator: routes by segment composition
  exit_service.py            # close_all / close_leg / cancel_pending
  rms_engine.py              # tick callback, run registry, rule evaluation, state transitions
  realtime_broadcaster.py    # Socket.IO emitter (debounced 5Hz)
  order_update_channel.py    # broker WS order updates + poll fallback
  account_rms.py             # preflight + per-tick aggregate cap
  state_machine.py           # validates transitions, persists, emits events
  squareoff_scheduler.py     # APScheduler cron per strategy (Asia/Kolkata)
  broker_adapter.py          # BrokerAdapter interface + Live + Sandbox impls
  position_tracker.py        # consumes order-update events → strategy_trades + strategy_positions
  pnl_calculator.py          # MTM + peak/drawdown helpers
  serializers.py             # rows → /orderbook /tradebook /positionbook JSON shape
```

New utility:

```
utils/ist_time.py            # IST display formatting + UTC ↔ IST conversion
utils/price_utils.py         # round_to_tick(price, tick_size, mode='favorable', side)
```

(Both in `utils/`, **not** in `services/` — keeps services-importing-services circular-import risk away.)

### 5.1 BrokerAdapter interface

```python
# services/strategy/broker_adapter.py
class BrokerAdapter(ABC):
    """Single abstraction over live broker and sandbox.
    Strategy engine uses only these methods — never imports place_order_service etc. directly."""

    @abstractmethod
    def place_order(self, order_data: dict) -> tuple[bool, dict, int]: ...

    @abstractmethod
    def place_options_order(self, options_data: dict) -> tuple[bool, dict, int]: ...

    @abstractmethod
    def place_options_multiorder(self, multiorder_data: dict) -> tuple[bool, dict, int]: ...

    @abstractmethod
    def basket_order(self, basket_data: dict) -> tuple[bool, dict, int]: ...

    @abstractmethod
    def cancel_order(self, orderid: str) -> tuple[bool, dict, int]: ...

    @abstractmethod
    def get_order_status(self, orderid: str) -> tuple[bool, dict, int]: ...


class LiveBrokerAdapter(BrokerAdapter):
    """Routes to services.place_order_service, etc. — real broker."""
    ...

class SandboxBrokerAdapter(BrokerAdapter):
    """Routes to services.sandbox_service — virtual fills using market_data_service LTPs."""
    ...
```

The engine selects an adapter at run-create time based on `strategy_runs.mode`. Same interface, identical behavior to the engine — only the bottom layer differs.

### 5.2 Service routing matrix (for `execution_service`)

| Entry shape | Service via BrokerAdapter |
|---|---|
| 1 leg CASH | `place_order` |
| N legs CASH | `basket_order` |
| 1 leg FUT | `place_order` |
| N legs FUT | `basket_order` |
| 1 leg OPT | `place_options_order` |
| N legs OPT | `place_options_multiorder` (BUY-first preserved) |
| Mixed CASH+FUT | `basket_order` |
| Mixed CASH/FUT + OPT | sequence: `basket_order` for non-OPT, then `place_options_multiorder` for OPT |

| Exit shape | Service via BrokerAdapter |
|---|---|
| 1 leg | `place_order` (explicit symbol from `strategy_positions`) |
| N legs (close-all) | `basket_order` |
| Cancel pending order | `cancel_order` (called before exit basket if open SL/limit orders exist) |

**`place_smart_order_service` is not in this list — the strategy engine never calls it.** Existing callers (legacy v1 webhook fallback, manual smart-order endpoint) keep using it; the engine doesn't.

### 5.3 Event-bus integration — pub/sub for cross-cutting concerns

OpenAlgo already has a mature in-process event bus (`utils/event_bus.py`) with the `EventBus` singleton, dataclass events in `events/`, and three centralized subscriber modules (`subscribers/log_subscriber.py`, `subscribers/socketio_subscriber.py`, `subscribers/telegram_subscriber.py`) wired up in `subscribers/__init__.py:setup_subscribers()`. Strategy v2 plugs into this — does **not** build a parallel notification layer.

#### 5.3.1 What goes through the bus, what doesn't

| Concern | Channel | Reason |
|---|---|---|
| Market ticks → RMS evaluation | **Direct** (`market_data_service.subscribe_critical`) | 500-2000/sec; 10-worker thread pool would saturate and starve other topics |
| Live P&L tick to UI | **Direct Socket.IO** (debounced 5Hz) | Same throughput concern |
| Strategy state transitions | **Bus** | 1-10/min; perfect fit for fan-out (audit + UI + Telegram) |
| RMS rule fires (SL/Target/Trail) | **Bus** | Few per run; needs audit + UI + alert fan-out |
| Run started / closed / failed | **Bus** | One-shot per signal |
| Order placed (entry/exit) | **Reuse existing `OrderPlacedEvent`** from `place_order_service` etc. | Engine subscribes for attribution |
| Broker order status updates | **Bus** (new `BrokerOrderUpdateEvent` from `order_update_channel`) | Engine subscribes; updates `strategy_trades` + `strategy_positions` |
| Webhook signal received / rejected | **Bus** | Audit + (optional) Telegram |
| Account locked / unlocked | **Bus** | UI banner + Telegram + audit |

Rule of thumb: **anything that's < 100/sec and benefits from fan-out goes through the bus; high-throughput direct paths stay direct.**

#### 5.3.2 New event types — `events/strategy_events.py` and `events/account_events.py`

```python
# events/strategy_events.py
@dataclass
class StrategySignalReceivedEvent(Event):
    topic: str = "strategy.signal_received"
    strategy_id: int = 0; webhook_id: str = ""; payload: dict = field(default_factory=dict)
    source_ip: str = ""; signing_method: str = ""

@dataclass
class StrategySignalRejectedEvent(Event):
    topic: str = "strategy.signal_rejected"
    strategy_id: int = 0; webhook_id: str = ""; reason: str = ""; source_ip: str = ""

@dataclass
class StrategyRunStartedEvent(Event):
    topic: str = "strategy.run_started"
    strategy_id: int = 0; run_id: int = 0; mode: str = "live"; signal_payload: dict = field(default_factory=dict)

@dataclass
class StrategyStateChangedEvent(Event):
    topic: str = "strategy.state_changed"
    strategy_id: int = 0; run_id: int = 0; old_state: str = ""; new_state: str = ""; reason: str = ""

@dataclass
class StrategyLegResolvedEvent(Event):
    topic: str = "strategy.leg_resolved"
    strategy_id: int = 0; run_id: int = 0; leg_id: int = 0
    resolved_symbol: str = ""; resolved_exchange: str = ""; tick_size: float = 0; lot_size: int = 0

@dataclass
class StrategyLegFilledEvent(Event):
    topic: str = "strategy.leg_filled"
    strategy_id: int = 0; run_id: int = 0; leg_id: int = 0
    avg_price: float = 0; qty: int = 0; orderid: str = ""

@dataclass
class StrategyRmsTriggeredEvent(Event):
    topic: str = "strategy.rms_triggered"
    strategy_id: int = 0; run_id: int = 0; leg_id: int = 0   # 0 for strategy-level rules
    rule: str = ""              # 'LEG_SL'|'LEG_TARGET'|'TRAIL'|'OVERALL_SL'|'OVERALL_TARGET'|'PROFIT_LOCK'|'TRAIL_TO_ENTRY'
    ltp: float = 0; threshold: float = 0; new_sl: float = 0   # new_sl populated for trail advances

@dataclass
class StrategyTrailAdvancedEvent(Event):
    topic: str = "strategy.trail_advanced"
    strategy_id: int = 0; run_id: int = 0; leg_id: int = 0
    advances: int = 0; new_sl: float = 0; ltp: float = 0

@dataclass
class StrategyExitTriggeredEvent(Event):
    topic: str = "strategy.exit_triggered"
    strategy_id: int = 0; run_id: int = 0; reason: str = ""
    legs_exited: int = 0; exit_orders: list = field(default_factory=list)

@dataclass
class StrategyEnterFailedEvent(Event):
    topic: str = "strategy.enter_failed"
    strategy_id: int = 0; run_id: int = 0; details: dict = field(default_factory=dict)

@dataclass
class StrategyExitFailedEvent(Event):
    topic: str = "strategy.exit_failed"
    strategy_id: int = 0; run_id: int = 0; details: dict = field(default_factory=dict)

@dataclass
class StrategyRunClosedEvent(Event):
    topic: str = "strategy.run_closed"
    strategy_id: int = 0; run_id: int = 0; exit_reason: str = ""
    realized_pnl: float = 0; max_unrealized_pnl: float = 0; max_drawdown: float = 0

@dataclass
class StrategyEngineErrorEvent(Event):
    topic: str = "strategy.engine_error"
    strategy_id: int = 0; run_id: int = 0; error_type: str = ""; message: str = ""; traceback: str = ""

@dataclass
class WebhookSecretRotatedEvent(Event):
    topic: str = "strategy.webhook_secret_rotated"
    strategy_id: int = 0; method: str = ""

# events/account_events.py
@dataclass
class AccountLockedEvent(Event):
    topic: str = "account.locked"
    user_id: str = ""; reason: str = ""; until_ts_utc: int = 0; cumulative_loss: float = 0

@dataclass
class AccountUnlockedEvent(Event):
    topic: str = "account.unlocked"
    user_id: str = ""; cleared_by: str = ""    # 'manual' | 'auto_next_session'

@dataclass
class BrokerOrderUpdateEvent(Event):
    """Bridge from order_update_channel (broker WS or poll fallback) to engine."""
    topic: str = "broker.order_update"
    orderid: str = ""; status: str = ""        # open|complete|cancelled|rejected|trigger_pending
    filled_qty: int = 0; average_price: float = 0; raw: dict = field(default_factory=dict)
```

Add to `events/__init__.py` exports.

#### 5.3.3 New subscriber modules — `subscribers/strategy_*.py`

```
subscribers/
  log_subscriber.py              # existing; extend with on_strategy_* (one method per topic)
  socketio_subscriber.py         # existing; extend with on_strategy_* (room-scoped emits)
  telegram_subscriber.py         # existing; extend with on_strategy_run_closed, on_account_locked, on_strategy_exit_failed, on_strategy_engine_error
  strategy_audit_subscriber.py   # NEW — listens to all strategy.* + account.* topics; appends rows to strategy_events audit table
```

`strategy_audit_subscriber` is the **single source of truth for the audit log**. The engine never writes `strategy_events` directly — it publishes events; the subscriber writes the row. This eliminates a class of "forgot to log" bugs and keeps the engine pure.

#### 5.3.4 Wiring — `subscribers/__init__.py:setup_subscribers()` additions

```python
# In setup_subscribers(), after existing wiring:
from subscribers import strategy_audit_subscriber

STRATEGY_TOPICS = [
    "strategy.signal_received","strategy.signal_rejected",
    "strategy.run_started","strategy.state_changed",
    "strategy.leg_resolved","strategy.leg_filled",
    "strategy.rms_triggered","strategy.trail_advanced",
    "strategy.exit_triggered","strategy.enter_failed","strategy.exit_failed",
    "strategy.run_closed","strategy.engine_error",
    "strategy.webhook_secret_rotated",
]
ACCOUNT_TOPICS = ["account.locked","account.unlocked"]

# Audit subscriber catches everything strategy/account → writes strategy_events row
for topic in STRATEGY_TOPICS + ACCOUNT_TOPICS:
    bus.subscribe(topic, strategy_audit_subscriber.on_event, f"audit:{topic}")

# Per-topic socketio + log subscribers
bus.subscribe("strategy.run_started",    socketio_subscriber.on_strategy_run_started, ...)
bus.subscribe("strategy.state_changed",  socketio_subscriber.on_strategy_state_changed, ...)
bus.subscribe("strategy.rms_triggered",  socketio_subscriber.on_strategy_rms_triggered, ...)
bus.subscribe("strategy.run_closed",     socketio_subscriber.on_strategy_run_closed, ...)
bus.subscribe("account.locked",          socketio_subscriber.on_account_locked, ...)
bus.subscribe("account.unlocked",        socketio_subscriber.on_account_unlocked, ...)
# Telegram for the loud events only
bus.subscribe("strategy.run_closed",     telegram_subscriber.on_strategy_run_closed, ...)
bus.subscribe("strategy.exit_failed",    telegram_subscriber.on_strategy_exit_failed, ...)
bus.subscribe("strategy.engine_error",   telegram_subscriber.on_strategy_engine_error, ...)
bus.subscribe("account.locked",          telegram_subscriber.on_account_locked, ...)
# Engine subscribes itself
bus.subscribe("broker.order_update",     rms_engine.on_broker_order_update, "engine:broker_update")
bus.subscribe("order.placed",            rms_engine.on_order_placed_for_strategy, "engine:order_placed")
bus.subscribe("order.cancelled",         rms_engine.on_order_cancelled_for_strategy, "engine:order_cancelled")
bus.subscribe("order.failed",            rms_engine.on_order_failed_for_strategy, "engine:order_failed")
```

#### 5.3.5 Engine reuses existing order-pipeline events

When `BrokerAdapter.place_order()` calls into `place_order_service.place_order()`, the existing `OrderPlacedEvent` / `OrderFailedEvent` already fires. Strategy engine subscribes and reconciles its `strategy_orders` row by `orderid`. No duplicate publishing.

This is what "fully event-driven" means here: every state change (order placed, order filled, run state changed, RMS triggered, account locked) propagates through the bus; subscribers handle audit + UI + Telegram in parallel; the engine's hot path stays pure tick-evaluation.

#### 5.3.6 Reliability of event-driven side effects

`bus.publish()` returns immediately; subscriber callbacks run in the 10-worker thread pool. Two failure modes:

1. **Subscriber exception** — `EventBus._safe_call` catches and logs to `log/errors.jsonl`. The publish is never blocked; other subscribers proceed.
2. **App crash between publish and audit-row insert** — possible. Mitigation: the audit subscriber inserts synchronously in its callback, so the gap is sub-millisecond. For *load-bearing* events (`strategy.run_closed`, `strategy.exit_triggered`), the engine **also** writes a final state row to `strategy_runs.exit_reason` synchronously **before** publishing — so even if the audit write loses, the run-level outcome is durable.

Subscriber ordering across the same event is **not guaranteed** (thread-pool dispatch). If two subscribers must run in order (e.g., audit-write before socket-emit), wrap them in a single composite subscriber. In practice, ordering doesn't matter for our topics — UI and audit can race.

---

## 6. RMS engine — detailed mechanics

### 6.1 Tick processing pipeline (per tick, per affected run)

```
0. Account-level safety check
   if account_state.is_locked_out:
       continue                              # locked; skip RMS for new exits but still allow squareoff

1. Data freshness gate
   if not market_data_service.is_trade_management_safe():
       emit FEED_PAUSED event (once on transition); return

2. Compute leg state
   for each leg in run:
       leg.ltp  = ticker[leg.symbol_key]
       leg.mtm  = (leg.ltp - leg.avg_entry) * leg.net_qty * direction_sign
       leg.pct  = (leg.ltp - leg.avg_entry) / leg.avg_entry * direction_sign

3. Compute strategy aggregate
   run.aggregate_mtm = sum(leg.mtm)
   run.peak_mtm     = max(run.peak_mtm, run.aggregate_mtm)        # ratchet up
   run.drawdown     = run.peak_mtm - run.aggregate_mtm

4. Strategy-level hard exits (highest priority)
   if overall_sl_hit(run):    exit_strategy(run, OVERALL_SL); return
   if overall_target_hit(run): exit_strategy(run, OVERALL_TARGET); return

5. Profit-lock arming + floor
   if not run.profit_locked and run.peak_mtm >= lock_at:
       run.profit_locked = True
       emit PROFIT_LOCK_ARMED
   if run.profit_locked and run.aggregate_mtm <= lock_min:
       exit_strategy(run, PROFIT_LOCK); return

6. Trail-to-entry (per leg, one-way ratchet)
   for each leg with sl_enabled:
       if leg.unrealized_pct >= threshold:
           leg.trail_to_entry_armed = True
           leg.current_sl_price = max(leg.current_sl_price, leg.avg_entry)  # snap to tick
           emit TRAIL_TO_ENTRY_ARMED (once)

7. Per-leg trail SL (X/Y ratchet)
   for each leg with trail_enabled:
       favorable = (leg.ltp - leg.last_trail_anchor) * dir_sign
       if favorable >= x_delta:
           n = floor(favorable / x_delta)
           new_sl = current_sl + n * y_delta * dir_sign
           new_sl = round_to_tick(new_sl, leg.tick_size_cache, 'favorable', side)
           if new_sl is in favor of current_sl:
               leg.current_sl_price = new_sl
               leg.last_trail_anchor += n * x_delta * dir_sign
               leg.trail_advances_count += n
               emit TRAIL_ADVANCED

8. Per-leg hard exits (after trail update so most recent SL wins)
   for each leg:
       if leg.ltp crosses leg.current_sl_price (in adverse direction):
           close_leg(leg, LEG_SL_HIT)
       elif leg.ltp crosses leg.current_target_price (in favor):
           close_leg(leg, LEG_TARGET_HIT)

9. Persist run state (peak, drawdown, locks)
   db.update_run(run)                                  # synchronous; durability for run-level outcome

10. PnL tick to UI (debounced ~5Hz; realtime_broadcaster does the emit directly)

11. Append pnl_snapshot row (debounced 1Hz; one DB write per second per active run)

NOTE on side effects:
   - State transitions in steps 4-8 do NOT directly call socketio.emit, write to
     strategy_events, or send Telegram. They call:
        bus.publish(StrategyRmsTriggeredEvent(...))
        bus.publish(StrategyTrailAdvancedEvent(...))
        bus.publish(StrategyStateChangedEvent(...))
     etc. The audit subscriber writes strategy_events; the socketio subscriber emits
     room-scoped UI updates; the telegram subscriber sends alerts. All in parallel
     via the 10-worker thread pool.
   - Tick-rate UI updates (pnl_tick, leg_update with ltp/sl_distance) are NOT routed
     through the bus — too high frequency. realtime_broadcaster emits directly to
     Socket.IO (debounced 5Hz) using its own LOW-priority subscription on
     market_data_service.
```

### 6.2 Failure & recovery

| Failure | Engine response |
|---|---|
| Tick feed stale | `FEED_PAUSED` event; skip evaluation; no RMS triggers fire on stale data. Resume on `FEED_RESUMED`. |
| Broker rejects exit | Mark run `EXIT_FAILED`, log `EXIT_PARTIAL_FAILURE` event with response details, alert via Telegram, retry with exponential backoff up to N times. After N, operator must ack. |
| Partial exit fill | Fill-watcher reconciles; if leg net_qty != 0 after timeout (configurable, default 60s), mark run `EXIT_FAILED`. |
| App restart mid-trade | Startup hydrator: read `strategy_runs WHERE state IN ('ARMED','ENTERING','IN_TRADE','EXITING')`; rehydrate engine state from `strategy_pnl_snapshots` (most recent peak); resubscribe via `market_data_service`; replay missed broker order updates by polling once. |
| Tick storm | Engine evaluation is per-symbol-affected-run; debounced broadcast for UI. RMS evaluation is intentionally **not** debounced — correctness over throughput. |
| Two webhooks for same strategy simultaneously | Unique partial index `idx_strategy_runs_active` prevents two ARMED/IN_TRADE rows; second webhook gets `409 ALREADY_RUNNING` (or queued, configurable). |

### 6.3 Idempotency

| Action | Guard |
|---|---|
| Place entry | DB state `ARMED → ENTERING` (atomic UPDATE WHERE state='ARMED'); duplicate entry attempts no-op |
| Place exit | DB state `IN_TRADE → EXITING`; duplicate exit attempts no-op |
| Webhook retry | `signal_payload` includes optional `signal_id`; duplicate `signal_id` for same strategy in last 60s is rejected |
| Trail recompute | One-way ratchet check — new SL must be in favor of old |
| Account lockout | Boolean flag on `account_state`; engine consults before any new run; existing IN_TRADE runs continue to RMS-exit until flat |

---

## 7. Frontend

### 7.1 Pages (under `/strategy/v2/` initially; swap routes once stable)

```
frontend/src/pages/strategy/v2/
  StrategyList.tsx          # all strategies; columns: name, mode, state, today's MTM, run count, win rate
  StrategyBuilder.tsx       # leg builder mirroring Images 1, 3, 4, 5
  StrategyDetail.tsx        # tabs: Overview, Legs, Runs, Orders, Trades, Positions, P&L Chart, Risk Config, Events Timeline
  StrategyMonitor.tsx       # live IN_TRADE view; ticks via Socket.IO
  AccountRiskConfig.tsx     # account_risk_config form
```

### 7.2 Reused components

These existing components are reused with a strategy-scoped data source prop:

- `OrderBookTable` — points at `/strategy/api/v2/run/<run_id>/orderbook`
- `TradeBookTable` — points at `/strategy/api/v2/run/<run_id>/tradebook`
- `PositionBookTable` — points at `/strategy/api/v2/run/<run_id>/positionbook`

Zero new table components.

### 7.3 API hooks

`frontend/src/api/strategy_v2.ts` (new file alongside legacy `strategy.ts`):

```typescript
strategyV2Api.getStrategies()                                // list
strategyV2Api.getStrategy(id)                                // detail with legs + risk_config
strategyV2Api.createStrategy(data)
strategyV2Api.updateStrategy(id, data)
strategyV2Api.deleteStrategy(id)
strategyV2Api.toggleStrategy(id)                             // is_active
strategyV2Api.addLeg(strategyId, leg)
strategyV2Api.updateLeg(legId, leg)
strategyV2Api.removeLeg(legId)
strategyV2Api.updateRiskConfig(strategyId, config)
strategyV2Api.getRuns(strategyId)
strategyV2Api.getRun(runId)                                  // includes events timeline
strategyV2Api.getRunOrderbook(runId)
strategyV2Api.getRunTradebook(runId)
strategyV2Api.getRunPositionbook(runId)
strategyV2Api.getRunPnlSnapshots(runId, fromTs?, toTs?)
strategyV2Api.closeAllPositions(runId)
strategyV2Api.closeLeg(runId, legId)
strategyV2Api.cancelPendingOrders(runId)
strategyV2Api.getAccountRiskConfig()
strategyV2Api.updateAccountRiskConfig(data)
strategyV2Api.unlockAccount()
strategyV2Api.getWebhookUrl(webhookId)                       // unchanged contract
```

### 7.4 Socket.IO events

Server emits, room-scoped (`room=f"strategy_{strategy_id}"`). Two distinct emit paths:

- **Bus-driven emits** (originating from `subscribers/socketio_subscriber.py` reacting to `strategy.*` / `account.*` events): used for state transitions, RMS triggers, run lifecycle, account events. Best-effort, eventually consistent.
- **Direct emits** (originating from `services/strategy/realtime_broadcaster.py`, debounced 5Hz off market_data_service): used for tick-rate UI updates that would saturate the bus.

| Event | When | Source | Payload |
|---|---|---|---|
| `strategy_state_change` | Run state transition | bus (StrategyStateChangedEvent) | `{strategy_id, run_id, old_state, new_state, reason, ts_utc, ts_ist}` |
| `strategy_pnl_tick` | Per tick (debounced 5Hz) | direct (broadcaster) | `{strategy_id, run_id, agg_mtm, peak, drawdown, leg_mtms[], ts_utc, ts_ist}` |
| `strategy_leg_update` | Per tick (debounced 5Hz) | direct (broadcaster) | `{leg_id, ltp, sl_level, target_level, trail_advances, sl_distance_pts, sl_distance_pct, target_distance_pts, target_distance_pct, next_trail_at_pts, ts_utc, ts_ist}` |
| `strategy_order_event` | Order placed/filled/rejected | bus (OrderPlaced/Failed/Cancelled + StrategyLegFilled) | `{order_id, status, filled_qty, avg_price, source, ts_utc, ts_ist}` |
| `strategy_rms_triggered` | RMS rule fired | bus (StrategyRmsTriggeredEvent) | `{rule, leg_id?, ltp, threshold, ts_utc, ts_ist}` |
| `strategy_trail_advanced` | Trail advance | bus (StrategyTrailAdvancedEvent) | `{leg_id, advances, new_sl, ltp, ts_utc, ts_ist}` |
| `strategy_event` | Audit row inserted | bus (audit subscriber re-emits) | `{event_id, type, payload, ts_utc, ts_ist}` |
| `strategy_health` | Feed/order-channel state | direct (health watcher) | `{feed_safe, order_channel_safe, reason, ts_utc, ts_ist}` |
| `account_locked` | Account RMS trips | bus (AccountLockedEvent) | `{reason, until_ts_utc, until_ts_ist}` |
| `account_unlocked` | User clears lockout | bus (AccountUnlockedEvent) | `{cleared_by, ts_utc, ts_ist}` |

Every event carries **both** `ts_utc` (epoch ms) and `ts_ist` (display string) — clients render `ts_ist` directly without timezone math.

---

## 8. Real-time + WebSocket fallback

### 8.1 Two streams, two health states

1. **Market data stream** — already handled by `market_data_service`. `is_trade_management_safe()` is the single source of truth for tick freshness. Engine consults it at the top of every tick callback.
2. **Order update stream** — broker-side WS where supported (Zerodha postback, Dhan order WS, Angel order socket). New module: `services/strategy/order_update_channel.py`. Mirrors the market_data_service pattern:

```python
class OrderUpdateChannel:
    last_update_ts: float
    health_status: CONNECTED|STALE|DISCONNECTED
    def on_broker_order_update(payload):
        last_update_ts = now()
        normalize → strategy_trades insert → strategy_positions update → emit socket.io
    def _health_loop():
        if connected and (now - last_update_ts > MAX_GAP):
            mark STALE; engage_poll_fallback()
    def engage_poll_fallback():
        # Poll /orderbook every N sec for OPEN strategy_orders
        # Restore WS-only mode on first real WS message
```

### 8.2 Poll fallback semantics

- **When**: order channel is STALE, or broker has no WS support.
- **Cadence**: every 5s for runs in IN_TRADE/EXITING state, only fetching orders the engine cares about (filter by `strategy_orders.orderid` IN (...) WHERE order_status IN ('open','trigger_pending')).
- **Pause-on-resume**: on first real WS message, mark CONNECTED and stop polling. No double-processing because each order_id is reconciled idempotently.
- **Visibility**: `strategy_health.order_channel_safe = false` emitted to UI; banner displays "Order channel: degraded — polling fallback active".

### 8.3 No polling for things we already have events for

- Market data: WS-only, fallback to nothing (engine pauses RMS — it's not safe to poll for trade management).
- Position state: derived from `strategy_trades` → no broker poll needed at all for strategy-scoped positions.
- Strategy state: in-memory + DB → no polling.

### 8.4 Webhook security

External signal sources have very different capabilities. **TradingView is the constraining client**: its alert dialog allows URL + body only, no custom headers. Python and Amibroker can do anything. The design supports both without forcing the strict path on TV users.

#### 8.4.1 Three signing methods (per strategy)

| Method | URL | Body | Header | Compatible with |
|---|---|---|---|---|
| `NONE` | `/<uuid>` | any JSON | none | TV / Python / Amibroker / curl. Default for v1 migrations. URL-only secret. |
| `BODY_SECRET` | `/<uuid>` | must include matching `webhook_secret` field | none | **TradingView**, Python, Amibroker, curl |
| `HMAC_SHA256` | `/<uuid>` | any JSON | `X-OpenAlgo-Signature: hmac-sha256=<hex>` over raw body | Python, Amibroker, curl. Not TradingView. |
| `BOTH` | `/<uuid>` | body-secret OR HMAC accepted | (HMAC optional) | Best of both — TV via body-secret, Python via HMAC |

Each strategy chooses one. UI dropdown with explanatory copy:

> **TradingView users:** select `BODY_SECRET` — paste the secret into your alert message JSON.
> **Python / Amibroker users:** select `HMAC_SHA256` for stronger security; sample code snippets shown after creation.
> **Mixed:** select `BOTH` if you want different signal sources to use different methods on the same strategy.

#### 8.4.2 Body-secret format (TradingView-compatible)

Strategy stores `webhook_secret` (cryptographically random, 32-byte hex). User pastes it into the TradingView alert message:

```json
{
  "webhook_secret": "1f9c4a8b2e3d4f5061728394a5b6c7d8",
  "action": "BUY",
  "signal_id": "{{strategy.order.action}}_{{strategy.order.id}}_{{time}}"
}
```

Server validation (constant-time comparison):

```python
import hmac
def verify_body_secret(body_json, expected_secret) -> bool:
    received = body_json.get("webhook_secret", "")
    return hmac.compare_digest(received, expected_secret)
```

The `webhook_secret` is **not** included in the signal payload passed to the engine — strip it after verification.

#### 8.4.3 HMAC-SHA256 format (Python / Amibroker)

Strategy stores `webhook_hmac_key` (32-byte). Client computes:

```python
import hmac, hashlib, json, requests
body = json.dumps({"action": "BUY", "signal_id": "...", "ts": int(time.time())})
sig = hmac.new(HMAC_KEY.encode(), body.encode(), hashlib.sha256).hexdigest()
requests.post(URL, data=body,
              headers={"X-OpenAlgo-Signature": f"hmac-sha256={sig}",
                       "Content-Type": "application/json"})
```

Server verifies:

```python
import hmac, hashlib
def verify_hmac(raw_body: bytes, header_value: str, key: str) -> bool:
    if not header_value or not header_value.startswith("hmac-sha256="):
        return False
    received = header_value.split("=", 1)[1]
    expected = hmac.new(key.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(received, expected)
```

**Critical**: HMAC is computed over the **raw request body bytes**, not the parsed JSON. The Flask handler must capture `request.get_data()` before any JSON parsing.

#### 8.4.4 Replay protection (optional)

If `webhook_replay_window_seconds > 0`, body must include a `ts` field (Unix epoch seconds, IST or UTC — both work since we compare as offsets). Server rejects when `abs(now - ts) > window`.

```python
def verify_replay(body_json, window_seconds: int) -> tuple[bool, str]:
    if window_seconds <= 0:
        return True, ""
    ts = body_json.get("ts")
    if not isinstance(ts, (int, float)):
        return False, "Missing or invalid 'ts'"
    drift = abs(time.time() - float(ts))
    if drift > window_seconds:
        return False, f"Timestamp out of window ({drift:.0f}s > {window_seconds}s)"
    return True, ""
```

TradingView supports `{{time}}` substitution which yields ISO-8601 — recommend Python/Amibroker use Unix epoch directly. Window default 0 (off). Recommended 300s for HMAC users; not recommended for TV (clock-drift confusion).

#### 8.4.5 IP allowlist (optional)

`webhook_ip_allowlist` is a JSON array of CIDRs. If non-empty, the request's `X-Forwarded-For` (behind proxy) or `request.remote_addr` (direct) must match one CIDR. Recommended for production deployments behind nginx.

TradingView publishes its alert source IPs — users can paste them into the allowlist. If TV changes IPs, alerts start failing until the user updates; ship a Telegram notification on first failure to make this visible.

#### 8.4.6 Validation order in the webhook handler

```python
@bp.route("/webhook/<webhook_id>", methods=["POST"])
def webhook(webhook_id):
    raw_body = request.get_data()              # Capture bytes BEFORE JSON parse
    strategy = lookup_by_webhook_id(webhook_id)
    if not strategy:
        return {"status":"error","code":"UNKNOWN_WEBHOOK"}, 404

    # 1. IP allowlist (cheapest, no body parse needed)
    if not ip_allowed(request, strategy.webhook_ip_allowlist):
        log_event(strategy, "SIGNAL_REJECTED", reason="IP not allowlisted")
        return {"status":"error","code":"IP_NOT_ALLOWED"}, 403

    # 2. Parse JSON
    try:
        body = json.loads(raw_body)
    except Exception:
        return {"status":"error","code":"BAD_JSON"}, 400

    # 3. Signature check (method-specific)
    method = strategy.webhook_signing_method
    if method == "BODY_SECRET":
        if not verify_body_secret(body, strategy.webhook_secret):
            return {"status":"error","code":"INVALID_SECRET"}, 403
    elif method == "HMAC_SHA256":
        sig_hdr = request.headers.get("X-OpenAlgo-Signature", "")
        if not verify_hmac(raw_body, sig_hdr, strategy.webhook_hmac_key):
            return {"status":"error","code":"INVALID_SIGNATURE"}, 403
    elif method == "BOTH":
        ok = verify_body_secret(body, strategy.webhook_secret) or \
             verify_hmac(raw_body, request.headers.get("X-OpenAlgo-Signature",""),
                         strategy.webhook_hmac_key)
        if not ok:
            return {"status":"error","code":"INVALID_AUTH"}, 403
    # else NONE — only URL secret was required

    # 4. Replay protection
    ok, msg = verify_replay(body, strategy.webhook_replay_window_seconds)
    if not ok:
        return {"status":"error","code":"REPLAY_PROTECTION","message":msg}, 403

    # 5. Strip signing fields and hand to ingestion
    body.pop("webhook_secret", None)
    body.pop("ts", None)
    return ingestion_service.handle_signal(strategy, body)
```

Order matters: IP first (cheap), JSON parse, signature (constant-time), replay last. All rejections write a `SIGNAL_REJECTED` event with the reason for audit.

#### 8.4.7 Secret lifecycle

- **Generation** at strategy creation: `secrets.token_hex(16)` for body-secret, `secrets.token_hex(32)` for HMAC key.
- **Display once** on creation/rotation in a one-time modal — copy-to-clipboard with "I've saved this" confirmation. Stored hashed? **No** — both ends need the plaintext to validate. Store as VARCHAR; protect via DB file permissions and `APP_KEY`-derived encryption-at-rest if a future hardening pass requires.
- **Rotation** via `POST /strategy/api/v2/strategy/<id>/webhook/rotate` — issues new secret/key, invalidates old. UI surfaces the new value once.
- **Audit**: every secret rotation writes a `WEBHOOK_KEY_ROTATED` event.

#### 8.4.8 Rate limiting (defense layer)

Existing `flask-limiter` rate limit on the webhook route stays — `100/min` per `webhook_id`. A leaked URL alone gets only 100 attempts/min to brute-force the body-secret or HMAC, and at 32-byte entropy that's astronomically infeasible.

#### 8.4.9 What we deliberately do NOT do

- **No mTLS** — overkill for a single-user platform; certificate management is operational pain.
- **No JWT** — TV can't sign JWTs dynamically. Body-secret + HMAC covers both clients.
- **No nonce / one-time-token** — would require a DB write per webhook arrival; replay window is sufficient.
- **No challenge-response** — webhooks are fire-and-forget; multi-step handshakes don't fit TV's model.

#### 8.4.10 TradingView setup helper

`StrategyBuilder.tsx` shows, after creation, a copy-pasteable JSON template tuned to the chosen signing method:

```jsonc
// For BODY_SECRET method:
{
  "webhook_secret": "<auto-filled>",
  "action": "{{strategy.order.action}}",     // BUY / SELL
  "symbol": "{{ticker}}",                    // optional, mostly ignored — strategy already knows
  "signal_id": "{{strategy.order.id}}_{{time}}"  // optional, helps idempotency
}
```

Plus a "Test webhook" button that sends a sample payload to the same URL and shows the engine's response (rejected or accepted-as-DRY-RUN). Lets users verify their TV alert config before committing.

### 8.5 Security hardening

Beyond §8.4 signing methods, additional layers shipped in Phase 1:

| Layer | What | Where |
|---|---|---|
| **Encryption-at-rest for secrets** | `webhook_secret` and `webhook_hmac_key` are encrypted using a Fernet key derived from `APP_KEY` (existing platform secret). Plaintext appears only in memory at strategy creation, rotation, and verification time. | `utils/secret_box.py` (new); used by `strategies_v2` ORM accessors |
| **Adaptive ban on signature failures** | Per-`webhook_id` counter: 5 failed signature attempts within 60s triggers a 15-minute ban (returns `429`). Resets on first success. | `services/strategy/webhook_guard.py` (new) |
| **Per-webhook rate limit (in addition to global)** | `flask-limiter` rule `100/min` per `webhook_id`. Already in v1; carry forward. | webhook route decorator |
| **Constant-time comparisons** | All signature comparisons use `hmac.compare_digest` (no early-exit timing leak). | `webhook_guard.py` |
| **Replay protection** | Optional `webhook_replay_window_seconds`; body must include `ts`. | §8.4.4 |
| **IP allowlist** | Optional `webhook_ip_allowlist` CIDR match. | §8.4.5 |
| **Audit-log integrity (lightweight)** | Each `strategy_events` row stores `prev_hash` (SHA-256 of previous row's payload + hash). Tampering with a single row breaks the chain. Verifier endpoint: `GET /strategy/api/v2/audit/verify/<run_id>`. | `subscribers/strategy_audit_subscriber.py` |
| **Strict input validation** | Marshmallow schemas for all `/strategy/api/v2/*` endpoints. Reject any unknown fields (`unknown=RAISE`). | `restx_api/strategy_v2_schemas.py` (new) |
| **CSRF on UI mutation** | Existing OpenAlgo CSRF middleware applies; no additional config needed. | (already in middleware) |
| **Telegram alert on persistent signature failures** | When adaptive ban triggers, fire Telegram message (`strategy.webhook_banned` event). | `subscribers/telegram_subscriber.py` extension |
| **Logging segregation** | All `signal_rejected` / `webhook_banned` events also append to a dedicated security log file via the `strategy_security` logger. Rotated daily. | `utils/logging.py` setup |
| **No secrets in logs** | The shared `SensitiveDataFilter` already redacts `webhook_secret`, `webhook_hmac_key`, `apikey`. Verify the strategy v2 log subscriber inherits it. | `utils/logging.py` |
| **Rotation requires confirmation** | Webhook secret rotation is a destructive action — UI requires the user to type the strategy name to confirm; backend requires a `confirm: <strategy_id>` body field. | rotate endpoint |
| **DB file permissions** | `db/openalgo.db` retains existing `0600` (owner-only) on Unix. Sandbox parity. Document for Docker volumes. | install scripts |

### 8.6 Realtime guarantees — what "as realtime as possible" means

| Path | Source → engine latency | Engine → user latency | Mechanism |
|---|---|---|---|
| Market tick → RMS evaluation | Broker WS → ZMQ → `market_data_service` cache: ~5-15ms | Engine math → state mutate: < 1ms | Direct callback via `subscribe_critical` (CRITICAL priority — runs before display subscribers) |
| Market tick → UI live numbers | Same as above | + 200ms debounce (5Hz) | `realtime_broadcaster` direct Socket.IO (bypasses event bus) |
| Order placed → UI | place_order_service → `OrderPlacedEvent` published: < 1ms | Subscriber socketio.emit: ~5-10ms (thread pool) | Existing `OrderPlacedEvent` reused; Phase 1 adds strategy-attribution subscriber |
| Order filled (broker push) → UI | Broker WS → `order_update_channel` → `BrokerOrderUpdateEvent`: ~10-20ms | Engine reconciles + `StrategyLegFilledEvent` published: < 1ms; subscriber emit: ~5-10ms | New event-driven path; **no polling on the happy path** |
| Order filled (broker no-WS / poll fallback) | REST `/orderbook` poll every 5s | Same downstream | Documented degraded mode; UI banner shows "Order channel: degraded" |
| State transition → audit + UI + Telegram | `bus.publish` returns: < 100µs | Subscriber fan-out: ~5-20ms (thread pool) | EventBus thread pool (10 workers) |
| RMS rule fires → exit order placed | Engine evaluation: < 1ms | BrokerAdapter call: 50-300ms (broker latency) | Synchronous critical path (engine waits for broker confirmation before transitioning to EXITING) |

**Hot-path optimizations:**
- Run state in memory; persisted on every change but read from memory in tick loop.
- Symbol→runs reverse index in memory; O(1) lookup per tick.
- Tick-size, lot-size, freeze-qty cached on leg row; no DB lookup in hot path.
- `market_data_service.get_ltp_value()` reads from a single dict under one lock — sub-microsecond.
- Subscriber thread pool sized at 10 (existing); event throughput bounded by RMS rule rate (1-100/min/run), not tick rate.

**What's NOT realtime:**
- Strategy-list aggregate "today's MTM" — recomputed on a 1-second timer (cheap; reads in-memory state). Not a tick-rate concern.
- P&L chart — appended at 1Hz from RMS engine; chart polls via TanStack Query at 5s cadence for closed runs (no live ticks needed).

**No polling anywhere on the happy path** for: market data, order placement results, order fills, state transitions, audit log, P&L updates, account lockout state. The only documented poll is the order-update REST fallback when broker WS is unavailable, with explicit health visibility to the user.

---

## 9. Account-level RMS

### 9.1 Preflight (webhook ingestion)

Before creating a run:

```python
def preflight_check(strategy_id, user_id) -> tuple[bool, str]:
    cfg = account_risk_config(user_id)
    state = account_state(user_id)

    # Duplicate-signal guard — strategy already running for this signal
    if has_active_run(strategy_id):
        return False, "ALREADY_RUNNING (state ARMED|ENTERING|IN_TRADE|EXITING)"

    if state.is_locked_out and now < cfg.lockout_until:
        return False, f"Account locked: {cfg.lockout_reason}"
    if state.active_run_count >= cfg.max_concurrent_runs:
        return False, f"max_concurrent_runs ({cfg.max_concurrent_runs}) reached"
    if cfg.max_daily_loss_abs and state.realized_pnl_today_live <= cfg.max_daily_loss_abs:
        return False, "Daily loss cap reached (abs ₹)"
    if too_soon_since_last_run(strategy_id, cfg.min_seconds_between_runs):
        return False, "Debounce: too soon since last run"
    if runs_today(strategy_id) >= cfg.max_runs_per_strategy_per_day:
        return False, "Per-strategy daily run cap reached"
    return True, ""
```

Every rejection emits `SIGNAL_REJECTED` event.

### 9.2 Per-tick aggregate cap

Engine maintains `account_state.unrealized_pnl_aggregate` updated each tick. If `realized_pnl_today + unrealized_aggregate <= -max_daily_loss_abs`, **flatten ALL active runs and lock out for the day**. Lockout fires `account_locked` Socket.IO event; logged as `ACCOUNT_LOCKED` event.

### 9.3 Manual lockout clear

`POST /strategy/api/v2/account/unlock` — sets `is_locked_out=false`, `lockout_until=NULL`. Idempotent.

---

## 10. Migration plan

### 10.1 Pre-migration state

- v1 tables (`strategies`, `strategy_symbol_mappings`) and v1 `blueprints/strategy.py` keep functioning unchanged.
- v2 tables created additively in Phase 0.
- v2 webhook handler **lives at the same URL** `POST /strategy/webhook/<uuid>` but dispatches to v2 engine if `webhook_id` exists in `strategies_v2`, else falls through to v1 behavior. Single route, dual lookup.

### 10.2 Migration script: `upgrade/migrate_strategy_v2.py`

Idempotent. Runs once during upgrade.

```
For each row in v1 strategies:
  if a v2 strategy with same webhook_id exists: skip
  else:
    create strategies_v2 row with same webhook_id, name, user_id, platform, times
    set is_active = old is_active
    set is_intraday = old is_intraday
    set mode = 'live'
    for each v1 strategy_symbol_mapping:
      create strategy_legs row:
        segment = inferred from exchange (NSE/BSE → CASH; NFO/BFO/MCX/CDS → FUT or OPT based on symbol)
        leg_index = sequential
        per-leg risk = none (v1 had none)
    create strategy_risk_config row with all rules disabled

Log conversion summary (count converted, count skipped).
```

Wired into `upgrade/migrate_all.py`.

### 10.3 Cutover

- **Phase 7** flips the webhook router default to v2 when both v1 and v2 rows exist (v2 wins). v1 rows that haven't been migrated still route to v1.
- After Phase 7 is stable in production for ≥1 week, **Phase 8** runs `upgrade/finalize_strategy_v1_removal.py` which:
  - Asserts every v1 row has a matching v2 row.
  - Drops v1 tables.
  - Removes v1 code paths from `blueprints/strategy.py`.

### 10.4 Rollback

Up to Phase 7: revert v2 commits; v1 still in place; webhooks still route to v1. No data loss.

After Phase 8: rollback requires re-running migration in reverse from a backup. **Take a `db/openalgo.db` snapshot before Phase 8.**

---

## 11. Phase plan

Each phase is mergeable on its own and leaves the system in a working state. Frontend ships behind a feature flag (`STRATEGY_V2_ENABLED`) until Phase 7.

### Phase 0 — Foundation (DB + utilities)

**Deliverables:**
- All v2 DB tables created via `database/strategy_v2_db.py` + `init_db()` hook.
- `utils/ist_time.py` with `to_ist`, `fmt_orderbook`, `fmt_tradebook`, `now_utc`.
- `utils/price_utils.py` with `round_to_tick(price, tick_size, mode, side)`.
- State machine module (`services/strategy/state_machine.py`) with transition table + atomic DB updates.
- Migration script skeleton (`upgrade/migrate_strategy_v2.py`).
- BrokerAdapter interface (`services/strategy/broker_adapter.py`) with no implementations yet.
- Unit tests for ist_time, price_utils, state_machine.

**Exit criteria:**
- `uv run pytest test/strategy/test_state_machine.py test/strategy/test_ist_time.py test/strategy/test_price_utils.py` passes.
- `uv run app.py` starts; new tables exist in `db/openalgo.db`.

### Phase 1 — Leg builder + entry execution

**Deliverables:**
- `services/strategy/leg_resolver_service.py` for all three segments. Caches `lot_size`, `tick_size`, `freeze_qty` on the leg row.
- `services/strategy/execution_service.py` with the routing matrix (`basket_order` for multi-leg CASH/FUT, `place_options_multiorder` for OPT, etc.).
- `LiveBrokerAdapter` (full impl).
- `SandboxBrokerAdapter` (full impl, routing to `services/sandbox_service`).
- `services/strategy/ingestion_service.py` for webhook validation and run creation.
- Webhook route handler updated in `blueprints/strategy.py` to dispatch to v2 engine when `webhook_id` matches a v2 strategy.
- Frontend: `StrategyBuilder.tsx` with segment-aware leg builder (Cash/Futures/Options tabs, matching Images 1/3/4).
- API endpoints for strategy CRUD + leg CRUD.

**Exit criteria:**
- Create a 1-leg CASH strategy in UI → fire webhook → run goes ARMED → ENTERING → IN_TRADE; broker order placed; `strategy_orders` row written.
- Same for 1-leg FUT and 1-leg OPT (using `place_options_order`).
- Multi-leg basket entry tested for CASH × 3 stocks.
- Sandbox mode tested for one strategy of each segment.

### Phase 2 — Strategy-scoped reporting

**Deliverables:**
- `services/strategy/serializers.py` — `to_orderbook_format`, `to_tradebook_format`, `to_positionbook_format`.
- API endpoints `/strategy/api/v2/run/<id>/orderbook`, `/tradebook`, `/positionbook`, `/events`, `/pnl_snapshots`.
- `services/strategy/position_tracker.py` — listens to BrokerAdapter order/fill callbacks, writes `strategy_trades` rows, recomputes `strategy_positions`.
- Frontend: `StrategyDetail.tsx` with Overview / Orders / Trades / Positions / Events tabs reusing existing OrderBookTable etc.

**Exit criteria:**
- Strategy run shows correct orderbook/tradebook/positions in UI, all in same shape as global views.
- Events timeline visible.

### Phase 3 — Per-leg RMS

**Deliverables:**
- `services/strategy/rms_engine.py` skeleton with tick callback and run registry.
- Per-leg rule evaluators: target, SL, X/Y trail (with floor-division ratchet), simple momentum.
- Tick-size snapping at every price-write boundary using `utils/price_utils.round_to_tick`.
- Unit + integration tests with synthetic ticks.
- `services/strategy/exit_service.py` with `close_leg(run_id, leg_id, reason)`.
- Socket.IO events: `strategy_leg_update`, `strategy_event`.
- Frontend: live leg view in `StrategyMonitor.tsx`.

**Exit criteria:**
- Long-leg SL triggers correctly on synthetic tick crossing SL price.
- Short-leg SL triggers correctly.
- Trail X/Y advances exactly N times for N×X favorable movement.
- Trail one-way ratchet verified (price retracement does not lower SL).
- Tick-size snapping verified for 0.05, 0.10, 0.25 instruments.
- pts and pct units interchangeable per parameter.

### Phase 4 — Strategy-level RMS

**Deliverables:**
- Overall SL / overall target evaluators.
- Profit-lock (peak ratchet + arm latch + floor exit).
- Trail-to-entry (per-leg one-way SL ratchet to break-even).
- `exit_strategy(run_id, reason)` — basket exit of all open legs, cancel pending orders first.
- Squareoff scheduler (`services/strategy/squareoff_scheduler.py`) using APScheduler with `Asia/Kolkata` tz.
- Frontend: `AccountRiskConfig.tsx`-like form for `strategy_risk_config`.

**Exit criteria:**
- Overall SL exits all 4 legs of an iron condor synthetically.
- Profit lock arms at +₹6000 peak, exits when retracement hits +₹4000 floor.
- Trail-to-entry pins long-leg SL to entry price after favorable move.
- Squareoff fires at configured IST time; flat positions; run CLOSED.

### Phase 4.5 — Account-level RMS

**Deliverables:**
- `services/strategy/account_rms.py` with preflight + per-tick aggregate cap.
- `account_risk_config` and `account_state` tables populated and maintained.
- Preflight rejection at webhook ingestion with `SIGNAL_REJECTED` event.
- Per-tick aggregate flatten on cumulative loss breach.
- `POST /strategy/api/v2/account/unlock` endpoint.
- Socket.IO events: `account_locked`, `account_unlocked`.
- Frontend: `AccountRiskConfig.tsx`.

**Exit criteria:**
- Configure max_concurrent_runs=2; create 3 strategies; 3rd webhook rejected with reason.
- Configure max_daily_loss_abs=-₹1000 (test value); two failing sandbox strategies cumulatively breach; account locks; new webhooks rejected.
- Manual unlock works; events logged.

### Phase 5 — Real-time UI

**Deliverables:**
- `services/strategy/realtime_broadcaster.py` — LOW-priority subscriber; debounced 5Hz emission per active run.
- Socket.IO room scoping (`strategy_{id}`).
- `StrategyMonitor.tsx` with live aggregate MTM, peak, drawdown, per-leg LTP, SL/target/trail levels, "next trail at" hint.
- P&L sparkline chart fed by `strategy_pnl_snapshots`.
- Health banner using `strategy_health` events.

**Exit criteria:**
- Live IN_TRADE run shows updates ≤ 1s latency from broker tick.
- Browser tab idle for 5 minutes — reconnect resubscribes correctly.
- Stale feed shows banner; resume clears banner.

### Phase 6 — Sandbox parity sweep

**Deliverables:**
- End-to-end sandbox tests for each segment (CASH/FUT/OPT/multi-leg).
- Sandbox slippage model (1-tick default, configurable per-strategy).
- Sandbox-only fields on UI: `[SANDBOX]` badge in lists, banner on detail page, separate aggregate in dashboards.
- Cross-mode reporting: live-only by default, toggle to include sandbox.

**Exit criteria:**
- Sandbox strategy lifecycle (signal → entry → RMS → exit) is functionally identical to live, only the broker adapter differs.
- UI clearly distinguishes sandbox runs from live; no chance of confusion.

### Phase 7 — Migration + UI swap

**Deliverables:**
- Run `upgrade/migrate_strategy_v2.py` — convert all v1 strategies to v2 1-leg strategies.
- Webhook router prefers v2 when both rows exist.
- Default frontend route `/strategy` points to v2 list page.
- Legacy v1 page accessible at `/strategy/v1/list` for verification.
- Documentation update: `docs/userguide/strategy-builder/` (replaces v1 sections).

**Exit criteria:**
- All existing v1 strategies show up in v2 list with correct conversions.
- Webhook URLs unchanged; existing TradingView/Amibroker integrations continue working.
- Production canary: run for 1 week with both paths active; v2 traffic > v1 traffic; no regressions.

### Phase 8 — Dead code removal + finalization

**Deliverables:**
- DB snapshot taken (`db/openalgo.db.bak.YYYY-MM-DD`).
- `upgrade/finalize_strategy_v1_removal.py` — asserts migration completeness, drops v1 tables.
- Remove v1 code from `blueprints/strategy.py` (webhook handler internals, v1 CRUD routes, order processor thread, queue model).
- Remove v1 tables: `strategies`, `strategy_symbol_mappings`.
- Remove v1 frontend code from `frontend/src/pages/strategy/` (v1 components).
- Remove v1 API client (`frontend/src/api/strategy.ts` v1 methods; rename `strategy_v2.ts` → `strategy.ts`).
- Remove `_strategy_webhook_cache`, `_user_strategies_cache` from `database/strategy_db.py` (whole file deletes).
- Remove the local `VALID_EXCHANGES` from `blueprints/strategy.py:69` (already centralized in `utils/constants.VALID_EXCHANGES`).
- Update `docs/plans/2026-02-06-strategy-risk-management-prd.md` status to "superseded by 2026-05-06-strategy-v2-implementation-plan.md".
- Final regression suite.

**Exit criteria:**
- No references to v1 strategy tables or v1 blueprint internals anywhere in repo.
- All tests pass.
- Docs reflect v2 only.
- Dead code tracker (Section 13) all marked done.

---

## 12. Phase tracker

Tick boxes as you finish. Move blockers up to "Open issues" with a one-line note.

### Phase 0 — Foundation
- [ ] `database/strategy_v2_db.py` with all tables + indexes (includes prev_hash column on strategy_events)
- [ ] `init_db()` registers strategy v2 init alongside existing inits in `app.py`
- [ ] `utils/ist_time.py` with full surface (to_ist, fmt_orderbook, fmt_tradebook, now_utc)
- [ ] `utils/price_utils.py` with `round_to_tick`
- [ ] `utils/secret_box.py` — Fernet wrapper keyed off APP_KEY for encrypting webhook secrets/keys at rest
- [ ] `services/strategy/state_machine.py` with transitions, atomic update helper (publishes `StrategyStateChangedEvent`)
- [ ] `services/strategy/broker_adapter.py` interface (no impls yet)
- [ ] **`events/strategy_events.py` with all 13 event types**
- [ ] **`events/account_events.py` with 3 event types (Locked, Unlocked, BrokerOrderUpdate)**
- [ ] **Update `events/__init__.py` exports**
- [ ] **`subscribers/strategy_audit_subscriber.py` — listens to all `strategy.*` and `account.*` topics, writes `strategy_events` rows with `prev_hash` chain**
- [ ] **Extend `subscribers/socketio_subscriber.py` with `on_strategy_*` and `on_account_*` handlers (room-scoped emits)**
- [ ] **Extend `subscribers/log_subscriber.py` with strategy/account topic handlers**
- [ ] **Extend `subscribers/telegram_subscriber.py` with `on_strategy_run_closed`, `on_strategy_exit_failed`, `on_strategy_engine_error`, `on_account_locked`, `on_strategy_webhook_banned`**
- [ ] **Wire all of the above in `subscribers/__init__.py:setup_subscribers()`**
- [ ] **Audit-chain verifier endpoint `GET /strategy/api/v2/audit/verify/<run_id>`**
- [ ] `upgrade/migrate_strategy_v2.py` skeleton (no actual conversion logic yet)
- [ ] Unit tests: ist_time, price_utils, state_machine, secret_box, audit chain integrity
- [ ] All Phase 0 code review comments addressed
- [ ] Merged to main

### Phase 1 — Leg builder + entry execution + webhook security
- [ ] `services/strategy/leg_resolver_service.py` — CASH branch
- [ ] `services/strategy/leg_resolver_service.py` — FUT branch (expiry resolution from `expiry_service`)
- [ ] `services/strategy/leg_resolver_service.py` — OPT branch (uses `option_chain_service` + `option_symbol_service`)
- [ ] Tick-size + lot-size + freeze_qty cached on leg row at arm-time
- [ ] `services/strategy/execution_service.py` segment-routing matrix
- [ ] `LiveBrokerAdapter` full impl
- [ ] `SandboxBrokerAdapter` full impl (uses `sandbox_service`; **zero slippage**, fills at LTP)
- [ ] `services/strategy/ingestion_service.py` webhook validation + run creation
- [ ] **Webhook security: `BODY_SECRET` verification (constant-time compare)**
- [ ] **Webhook security: `HMAC_SHA256` verification over raw bytes**
- [ ] **Webhook security: `BOTH` mode (accept either)**
- [ ] **Webhook security: replay-window check (`ts` field)**
- [ ] **Webhook security: optional IP allowlist (CIDR match)**
- [ ] **Webhook security: `SIGNAL_REJECTED` events on every rejection with reason**
- [ ] **Webhook security: secret/key generation at strategy creation (`secrets.token_hex`)**
- [ ] **Webhook security: rotation endpoint `POST /strategy/api/v2/strategy/<id>/webhook/rotate`**
- [ ] **Duplicate-signal guard: `409 ALREADY_RUNNING` when state ∈ {ARMED,ENTERING,IN_TRADE,EXITING}**
- [ ] `blueprints/strategy.py` webhook route dispatches v2 when `webhook_id` matches
- [ ] API: GET/POST/PUT/DELETE `/strategy/api/v2/strategy[/<id>]`
- [ ] API: POST/PUT/DELETE `/strategy/api/v2/strategy/<id>/legs[/<id>]`
- [ ] API: POST `/strategy/api/v2/strategy/<id>/toggle`
- [ ] API: POST `/strategy/api/v2/strategy/<id>/webhook/test` (dry-run validation)
- [ ] Frontend: `StrategyList.tsx`
- [ ] Frontend: `StrategyBuilder.tsx` with Cash/Futures/Options leg builder
- [ ] **Frontend: Webhook security tab — signing method dropdown, one-time secret display modal, "copy template for TradingView" button**
- [ ] **Frontend: "Test webhook" button on detail page**
- [ ] Frontend: API client `strategy_v2.ts`
- [ ] E2E: 1-leg CASH live entry
- [ ] E2E: 1-leg OPT live entry
- [ ] E2E: 4-leg iron condor sandbox entry
- [ ] E2E: 10-stock CASH basket entry
- [ ] **E2E: TradingView simulated POST with `BODY_SECRET` accepted**
- [ ] **E2E: Python POST with `HMAC_SHA256` accepted**
- [ ] **E2E: Tampered body / wrong secret / expired ts all rejected with 403 + event row**
- [ ] **E2E: Duplicate webhook while IN_TRADE rejected with 409**

### Phase 2 — Strategy-scoped reporting
- [ ] `services/strategy/serializers.py`
- [ ] API: GET `/strategy/api/v2/run/<id>/orderbook` matches `/orderbook` shape
- [ ] API: GET `/strategy/api/v2/run/<id>/tradebook` matches `/tradebook` shape
- [ ] API: GET `/strategy/api/v2/run/<id>/positionbook` matches `/positionbook` shape
- [ ] API: GET `/strategy/api/v2/run/<id>/events`
- [ ] API: GET `/strategy/api/v2/strategy/<id>/runs`
- [ ] `services/strategy/position_tracker.py` — fill → trade → position
- [ ] Frontend: `StrategyDetail.tsx` Overview tab
- [ ] Frontend: Orders tab (reuses `OrderBookTable`)
- [ ] Frontend: Trades tab (reuses `TradeBookTable`)
- [ ] Frontend: Positions tab (reuses `PositionBookTable`)
- [ ] Frontend: Events Timeline tab

### Phase 3 — Per-leg RMS
- [ ] `services/strategy/rms_engine.py` skeleton + run registry + symbol→runs reverse index
- [ ] `subscribe_critical` registration on run IN_TRADE; unsubscribe on CLOSED
- [ ] Tick callback with `is_trade_management_safe` gate
- [ ] Leg target evaluator (pts + pct)
- [ ] Leg SL evaluator (pts + pct)
- [ ] Leg trail X/Y evaluator (floor-division ratchet, one-way)
- [ ] Leg simple-momentum evaluator
- [ ] Tick-size snapping at every price write
- [ ] `services/strategy/exit_service.py:close_leg(run_id, leg_id, reason)`
- [ ] Socket.IO `strategy_leg_update` + `strategy_event`
- [ ] Synthetic-tick test suite for trail correctness
- [ ] Frontend: `StrategyMonitor.tsx` per-leg live view

### Phase 4 — Strategy-level RMS
- [ ] Overall SL evaluator
- [ ] Overall target evaluator
- [ ] Profit lock (arm + floor exit)
- [ ] Trail-to-entry per-leg one-way ratchet
- [ ] `exit_strategy(run_id, reason)` — cancel pending → basket exit
- [ ] `services/strategy/squareoff_scheduler.py` with `Asia/Kolkata` tz
- [ ] Frontend: Strategy Risk Config form on `StrategyDetail.tsx`
- [ ] E2E: iron condor overall SL
- [ ] E2E: profit lock arm + floor exit
- [ ] E2E: scheduled squareoff

### Phase 4.5 — Account-level RMS
- [ ] `services/strategy/account_rms.py` preflight
- [ ] `services/strategy/account_rms.py` per-tick aggregate cap
- [ ] `account_state` maintenance (incremented on run create / decremented on close)
- [ ] API: GET/PUT `/strategy/api/v2/account/risk_config`
- [ ] API: POST `/strategy/api/v2/account/unlock`
- [ ] Webhook ingestion calls preflight before run-create
- [ ] Per-tick aggregate breach triggers all-runs flatten + lockout
- [ ] Frontend: `AccountRiskConfig.tsx`
- [ ] Frontend: lockout banner on Strategy List

### Phase 5 — Real-time UI
- [ ] `services/strategy/realtime_broadcaster.py` LOW-priority subscriber
- [ ] Per-run debounce ~5Hz
- [ ] Room-scoped Socket.IO emission (`room=f"strategy_{id}"`)
- [ ] `strategy_pnl_tick` payload includes both `ts_utc` and `ts_ist`
- [ ] `strategy_health` events (feed + order channel)
- [ ] Frontend: live aggregate MTM card with peak/drawdown
- [ ] Frontend: live leg cards with ltp/sl_distance/target_distance/next_trail_at
- [ ] Frontend: P&L sparkline (lightweight chart) fed by `strategy_pnl_snapshots`
- [ ] Frontend: health banner from `strategy_health`

### Phase 6 — Sandbox parity sweep
- [ ] Sandbox slippage config (per-strategy override; 1-tick default)
- [ ] `[SANDBOX]` badge on strategy list rows
- [ ] Sandbox banner on detail page
- [ ] Account dashboard: live-only by default, toggle for sandbox
- [ ] E2E sandbox tests covering all segments
- [ ] Engine code-path identical for live and sandbox (only adapter differs)

### Phase 7 — Migration + UI swap
- [ ] DB snapshot scripted: `db/openalgo.db.bak.{date}`
- [ ] `upgrade/migrate_strategy_v2.py` full conversion logic
- [ ] Migration wired into `upgrade/migrate_all.py`
- [ ] Webhook router prefers v2 when both rows exist (single route, dual lookup)
- [ ] Frontend default `/strategy` route → v2 list
- [ ] Legacy `/strategy/v1/list` accessible for verification
- [ ] User guide updated (`docs/userguide/strategy-builder/`)
- [ ] Production canary: 1 week dual-path; v2 traffic > v1 traffic; no regressions

### Phase 8 — Dead code removal
- [ ] Pre-removal full DB snapshot taken
- [ ] `upgrade/finalize_strategy_v1_removal.py` written and tested
- [ ] All Section 13 tracker rows marked DONE
- [ ] v1 tables dropped: `strategies`, `strategy_symbol_mappings`
- [ ] v1 webhook handler internals removed from `blueprints/strategy.py`
- [ ] v1 frontend pages and API methods deleted
- [ ] `database/strategy_db.py` whole file deleted (replaced by `strategy_v2_db.py`)
- [ ] Local `VALID_EXCHANGES` in `blueprints/strategy.py` removed (use `utils.constants`)
- [ ] PRD `2026-02-06-strategy-risk-management-prd.md` marked superseded
- [ ] Final regression suite passes
- [ ] Release notes drafted

---

## 13. Dead code tracker

Items to remove in Phase 8. Mark each DONE as it's removed.

| # | Path / item | Reason removed | Status |
|---|---|---|---|
| D1 | `database/strategy_db.py` (full file) | Replaced by `database/strategy_v2_db.py` | ☐ |
| D2 | Tables `strategies`, `strategy_symbol_mappings` in `db/openalgo.db` | Replaced by `strategies_v2`, `strategy_legs` | ☐ |
| D3 | `_strategy_webhook_cache` (TTL cache) | v2 has its own webhook lookup; consolidated | ☐ |
| D4 | `_user_strategies_cache` | v2 doesn't need it | ☐ |
| D5 | `blueprints/strategy.py` v1 webhook handler internals (lines ~869-1033) | Replaced by v2 ingestion service | ☐ |
| D6 | `blueprints/strategy.py` v1 order-processor thread (lines ~87-209) | Replaced by BrokerAdapter sync calls + queueing in execution_service | ☐ |
| D7 | `blueprints/strategy.py` v1 `queue_order` and queue model | Same | ☐ |
| D8 | `blueprints/strategy.py:69` local `VALID_EXCHANGES` | Already in `utils.constants.VALID_EXCHANGES` | ☐ |
| D9 | `blueprints/strategy.py` v1 HTML routes (`/`, `/new`, `/<id>`, `/<id>/configure`, `/<id>/symbol/<id>/delete`, `/search`) | Replaced by React pages | ☐ |
| D10 | `blueprints/strategy.py` v1 JSON API routes (`/api/strategies`, `/api/strategy[/<id>]`, `/api/strategy/<id>/toggle`) | Replaced by `/api/v2/*` | ☐ |
| D11 | `blueprints/strategy.py` v1 `squareoff_strategy` APScheduler hookup | Replaced by `services/strategy/squareoff_scheduler.py` | ☐ |
| D12 | `frontend/src/api/strategy.ts` v1 methods | Replaced by `strategy_v2.ts` (renamed to `strategy.ts` after Phase 8) | ☐ |
| D13 | `frontend/src/pages/strategy/v1/*.tsx` (any v1-only pages) | Replaced by `pages/strategy/v2/*` (path prefix removed after Phase 8) | ☐ |
| D14 | Inline templates referencing v1 only (e.g. `templates/strategy/*` if any) | Migrated to React | ☐ |
| D15 | v1-specific event types in `events/` (if any) | Replaced by `strategy_events` audit table | ☐ |
| D16 | Any `placesmartorder` references in strategy code (engine never calls it) | Engine uses explicit `place_order` instead | ☐ |
| D17 | Legacy `strategy_id` foreign keys in `db/openalgo.db` pointing to v1 `strategies.id` | None expected; verify with grep | ☐ |
| D18 | `docs/plans/2026-02-06-strategy-risk-management-prd.md` | Mark superseded; do **not** delete (historical record) | ☐ (mark) |
| D19 | Comments referencing "v1 webhook router" left around | Remove on touch-pass | ☐ |
| D20 | **Direct `socketio.emit()` calls inside `services/strategy/*` (engine code)** | Engine must publish events; emits originate from `subscribers/socketio_subscriber.py` only. Hot-path tick emits (`strategy_pnl_tick`, `strategy_leg_update`) are exempted — they originate from `realtime_broadcaster.py` which is a dedicated emitter, not the engine | ☐ (gate at Phase 8) |
| D21 | **Direct `strategy_events` INSERT statements outside the audit subscriber** | Audit subscriber is the single writer. Engine publishes events; subscriber persists | ☐ (gate at Phase 8) |
| D22 | **Direct `telegram_alert_service` calls inside engine** | Telegram fan-out is via `telegram_subscriber.py` only | ☐ (gate at Phase 8) |
| D23 | Any polling loop on `/orderbook`, `/tradebook`, `/positionbook` from strategy code | Allowed only inside `order_update_channel` poll fallback. Anywhere else = remove | ☐ |

**Discovery rule:** during Phase 8, run `grep -rn "from blueprints.strategy import"`, `grep -rn "from database.strategy_db import"`, `grep -rn "socketio.emit" services/strategy/`, and `grep -rn "INSERT INTO strategy_events"` — every result is a candidate for removal or rewrite. Add new entries to this tracker.

---

## 13.5 Event-bus, realtime & security tracker

Cross-cutting tracker that pulls together the new event-driven, realtime, and security commitments from §5.3, §8.4, §8.5, §8.6. Mark each DONE as it ships. Use this alongside the per-phase tracker — many of these items are split across phases (most foundation in Phase 0; most enforcement in Phase 1; one-time security audit before Phase 7 cutover).

### EB — Event bus integration

| # | Item | Phase | Status |
|---|---|---|---|
| EB1 | `events/strategy_events.py` with all 13 event types | 0 | ☐ |
| EB2 | `events/account_events.py` with `AccountLocked/Unlocked/BrokerOrderUpdate` events | 0 | ☐ |
| EB3 | `events/__init__.py` exports updated | 0 | ☐ |
| EB4 | `subscribers/strategy_audit_subscriber.py` writes `strategy_events` rows for every `strategy.*`/`account.*` topic | 0 | ☐ |
| EB5 | Audit subscriber computes `prev_hash` chain (SHA-256 of previous row's payload + hash) | 0 | ☐ |
| EB6 | `subscribers/socketio_subscriber.py` extended with `on_strategy_*` + `on_account_*` handlers | 0 | ☐ |
| EB7 | `subscribers/log_subscriber.py` extended with strategy/account handlers | 0 | ☐ |
| EB8 | `subscribers/telegram_subscriber.py` extended with run_closed/exit_failed/engine_error/account_locked/webhook_banned | 0 | ☐ |
| EB9 | `subscribers/__init__.py:setup_subscribers()` wires every new subscriber on every relevant topic | 0 | ☐ |
| EB10 | Engine subscribes to `broker.order_update`, `order.placed`, `order.cancelled`, `order.failed` for attribution | 1 | ☐ |
| EB11 | Engine code contains zero direct `socketio.emit` (except `realtime_broadcaster`) | 1-7 | ☐ |
| EB12 | Engine code contains zero direct `strategy_events` INSERTs (only via audit subscriber) | 1-7 | ☐ |
| EB13 | `order_update_channel` publishes `BrokerOrderUpdateEvent` for every broker WS message | 5 | ☐ |
| EB14 | `order_update_channel` publishes `BrokerOrderUpdateEvent` for every poll-fallback reconciliation | 5 | ☐ |
| EB15 | Audit-chain verifier endpoint `GET /strategy/api/v2/audit/verify/<run_id>` | 0 | ☐ |
| EB16 | Subscriber-failure isolation verified — one bad subscriber doesn't drop other subscribers' callbacks | 0 | ☐ |
| EB17 | Concurrency stress test: 50 active runs × 100 tick-driven state changes/sec; thread pool not saturated | 5 | ☐ |
| EB18 | Order-event reuse: engine subscribes to existing `OrderPlacedEvent` and reconciles `strategy_orders` by `orderid` | 1 | ☐ |

### RT — Realtime path

| # | Item | Phase | Status |
|---|---|---|---|
| RT1 | Tick path bypasses event bus — direct `subscribe_critical` callback | 3 | ☐ |
| RT2 | `realtime_broadcaster.py` debounces per-run at 5Hz for `strategy_pnl_tick` + `strategy_leg_update` | 5 | ☐ |
| RT3 | Engine reads from in-memory run-state cache in tick callback (no DB hit) | 3 | ☐ |
| RT4 | `tick_size_cache` / `lot_size_cache` / `freeze_qty_cache` resolved at arm-time, no symbol_service calls in tick loop | 1 | ☐ |
| RT5 | Symbol→runs reverse index in memory; O(1) tick fan-out to affected runs | 3 | ☐ |
| RT6 | `is_trade_management_safe` consulted at top of every tick callback | 3 | ☐ |
| RT7 | UI receives state-transition socket events within 50ms p99 of engine decision | 5 | ☐ |
| RT8 | UI receives tick updates within 200ms p99 (debounce floor) of broker tick | 5 | ☐ |
| RT9 | Order-update channel WS reconnection re-subscribes within 5s | 5 | ☐ |
| RT10 | Order-update poll fallback engages within 30s of WS staleness | 5 | ☐ |
| RT11 | No HTTP polling loops in `services/strategy/*` outside `order_update_channel` | 1-7 | ☐ |
| RT12 | App restart with N IN_TRADE runs rehydrates engine state from DB + reconnects subscriptions in < 10s | 3 | ☐ |
| RT13 | `account_state.unrealized_pnl_aggregate` updated each tick; per-tick aggregate cap evaluated | 4.5 | ☐ |
| RT14 | Frontend Socket.IO client joins per-strategy room on detail-page mount; leaves on unmount | 5 | ☐ |
| RT15 | Frontend reconnect resubscribes to room and replays missed audit events from `/strategy/api/v2/run/<id>/events` | 5 | ☐ |

### SC — Security

| # | Item | Phase | Status |
|---|---|---|---|
| SC1 | `utils/secret_box.py` — Fernet wrapper, key derived from APP_KEY | 0 | ☐ |
| SC2 | `webhook_secret` and `webhook_hmac_key` encrypted at rest via secret_box | 1 | ☐ |
| SC3 | `verify_body_secret` uses `hmac.compare_digest` | 1 | ☐ |
| SC4 | `verify_hmac` computed over raw `request.get_data()` (not parsed JSON); uses `hmac.compare_digest` | 1 | ☐ |
| SC5 | Replay protection: `webhook_replay_window_seconds` enforced when > 0 | 1 | ☐ |
| SC6 | IP allowlist: CIDR match supporting IPv4 + IPv6 + `X-Forwarded-For` behind proxy | 1 | ☐ |
| SC7 | `services/strategy/webhook_guard.py` — adaptive ban (5 failed signatures / 60s → 15-minute ban) | 1 | ☐ |
| SC8 | Per-`webhook_id` rate limit `100/min` (in addition to global flask-limiter) | 1 | ☐ |
| SC9 | Audit-log integrity chain (`prev_hash` SHA-256) + verifier endpoint | 0 | ☐ |
| SC10 | Marshmallow schemas with `unknown=RAISE` for all `/strategy/api/v2/*` endpoints | 1 | ☐ |
| SC11 | Existing `SensitiveDataFilter` redacts `webhook_secret`, `webhook_hmac_key` (verify) | 0 | ☐ |
| SC12 | Webhook secret rotation requires explicit confirmation in body + UI | 1 | ☐ |
| SC13 | Telegram alert on adaptive ban trigger (`strategy.webhook_banned` event) | 1 | ☐ |
| SC14 | `strategy_security` logger writes to dedicated daily-rotated file | 0 | ☐ |
| SC15 | One-time secret display modal at strategy creation/rotation; never re-shown | 1 | ☐ |
| SC16 | "Test webhook" endpoint requires authenticated session (not the public webhook URL) | 1 | ☐ |
| SC17 | CSRF token enforced on all `/strategy/api/v2/*` mutation endpoints (existing middleware) | 1 | ☐ |
| SC18 | Pre-Phase-7 security review pass: penetration-testing the webhook handler with malformed payloads | 7 | ☐ |
| SC19 | All adaptive bans, signature failures, IP rejections write `SIGNAL_REJECTED` events | 1 | ☐ |
| SC20 | Document threat model in `docs/userguide/strategy-builder/security.md` | 7 | ☐ |

---

## 14. Risks & open decisions

### 14.1 Risks

| Risk | Mitigation |
|---|---|
| Engine perf under tick storm with 50+ active runs | Synthetic load test in Phase 3; serial dispatch is microseconds-per-run; debounced broadcast caps Socket.IO load |
| Broker order-update WS coverage gaps | Polling fallback documented per-broker; surface health to UI; engine pauses RMS exits if order channel is dead |
| SQLite contention with high write rate from `strategy_pnl_snapshots` (1Hz × N runs) | Already proven under existing traffic_logger load; can move to a dedicated DB if needed |
| User confusion between live and sandbox runs | Hard visual segregation: badges, banners, separate aggregate lines in dashboards |
| Migration corrupts v1 strategies | Idempotent script; pre-Phase-7 DB snapshot; rollback plan documented |
| WebSocket-only design fails on flaky networks | Auto-fallback to poll for order updates; engine pauses RMS for market data on staleness; banners notify user |
| Strategy-scoped positions diverge from broker reality (user manually trades) | Documented: strategy positions are logical, not synced with broker. Global positionbook still authoritative. |
| Multiple webhooks for same strategy in fast succession | Unique partial index on `strategy_runs` + optional debounce; second webhook gets `409` |

### 14.2 Decisions resolved (2026-05-06)

1. **Webhook duplicate policy** — **RESOLVED: REJECT.** Duplicates are not queued. While a strategy is `ARMED|ENTERING|IN_TRADE|EXITING`, additional webhooks return `409 ALREADY_RUNNING` and write a `SIGNAL_REJECTED` event. Enforced by the `idx_strategy_runs_active` unique partial index plus an explicit ingestion guard.
2. **Strategy capital allocation** — **RESOLVED: NOT TRACKED.** No `capital_alloc` column, no UI, no `%`-of-capital calculations. Overall RMS thresholds are **abs ₹** only. Per-leg `%` remains supported because it's relative to the leg's own `avg_entry`, not capital.
3. **Sandbox slippage model** — **RESOLVED: ZERO SLIPPAGE.** Sandbox fills at the live LTP exactly. No slippage configuration. Simple, predictable, sufficient for forward-testing.
4. **HMAC webhook signing** — **RESOLVED: SHIP IN PHASE 1.** Four modes (`NONE`, `BODY_SECRET`, `HMAC_SHA256`, `BOTH`). TradingView uses `BODY_SECRET` (it cannot set custom headers); Python/Amibroker use `HMAC_SHA256`; legacy/migrated v1 strategies default to `NONE`. Optional replay window and IP allowlist on top. Full design in §8.4.

### 14.3 Decisions locked with defaults (revisit if data shows otherwise)

5. **Lockout cleanup mode** — **DEFAULT: manual unlock**, with an `auto_clear_at` config field on `account_risk_config` that can be set to e.g. `"09:00"` IST to auto-clear at next trading-day open. Implementation Phase 4.5; default off (manual). If user enables auto-clear, lockout schedules a one-shot APScheduler job in `Asia/Kolkata` tz at the next trading-day boundary (skipping weekends + market holidays via existing `market_calendar_db`).
6. **Cross-mode reporting** — **DEFAULT: segregated, live-first**. Dashboards show live aggregate by default; a dropdown toggle switches to "sandbox only" or "combined". `[SANDBOX]` badges keep individual runs visually distinct in lists. Implementation Phase 6.
7. **Dispatcher concurrency** — **DEFAULT: single dispatcher (eventlet green thread)**, sized for OpenAlgo's eventlet single-worker production model. Synthetic load test in Phase 5 (item RT8/EB17) — if p99 dispatch > 50ms with 50 active runs × 1000 ticks/sec, revisit with a per-symbol-shard pool design. Until that benchmark fails, single is the right answer.

---

## 15. Testing strategy

### 15.1 Unit tests

- `utils/ist_time.py` — epoch ms / s / datetime conversion edge cases.
- `utils/price_utils.py` — `round_to_tick` for various tick sizes (0.01, 0.05, 0.10, 0.25, 0.50), favorable-direction rules.
- `services/strategy/state_machine.py` — every valid transition + every rejected transition; idempotency under concurrent calls.
- `services/strategy/leg_resolver_service.py` — each segment branch with mock broker.
- RMS rule evaluators (one test per rule × pts and pct unit).
- X/Y trail ratchet edge cases (sub-tick movements, large jumps, retracement).
- **Webhook security helpers**: `verify_body_secret`, `verify_hmac`, `verify_replay`, IP-allowlist matcher.
  - Constant-time comparison (no early exit on mismatch).
  - HMAC computed over raw bytes — verify `request.get_data()` capture before JSON parsing.
  - Replay window boundary (exactly at limit, just over, far over, missing `ts`, non-numeric `ts`).
  - IP allowlist with mixed IPv4/IPv6, with/without `X-Forwarded-For`.
- **Duplicate-signal guard**: concurrent webhooks attempting to create a second active run; second receives `409`, only one run row exists.

### 15.2 Integration tests

Synthetic tick generators feeding the engine; verify full state transitions:

- Iron condor lifecycle: signal → entry × 4 → ticks → leg-2 SL → 3-leg continue → overall target → 3-leg exit basket → CLOSED.
- 10-stock cash momentum: signal → basket entry → individual leg SLs over time → squareoff at 15:15 IST → all flat.
- Profit lock + trail-to-entry combined.
- Sandbox vs live identical event sequences (mock broker for live).

### 15.3 E2E tests

- Run dev server; create strategy via UI; fire webhook via curl; observe state transitions in DB and Socket.IO; verify UI updates.
- Live broker E2E (Zerodha session) — single-leg CASH; manual confirm with broker dashboard.

### 15.4 Load test

- 50 concurrent active runs; synthetic 1000 ticks/sec across union of leg symbols; assert dispatch latency p99 < 50ms; UI broadcast at debounced 5Hz.

---

## 16. Operational concerns

### 16.1 Logging

- Every state transition: `INFO` log + `strategy_events` row + Socket.IO emit.
- Every RMS rule trigger: `INFO` log with run_id, leg_id, rule, ltp, threshold + `strategy_events` row.
- Engine errors: `logger.exception(...)` (auto-captures traceback to `log/errors.jsonl`) + `ENGINE_ERROR` event.
- No emoji in log lines or code (per project CLAUDE.md global rule).

### 16.2 Telegram alerts (reuse `services/telegram_alert_service.py`)

- Run started (optional, configurable)
- Run closed with reason + final P&L
- Account locked
- Engine error (always)
- Exit failed (always)

### 16.3 Kill switch interaction

When the kill switch (`2026-04-24-kill-switch-implementation-plan.md`) is active:

- All BrokerAdapter `place_order*` calls already gated at the underlying service layer (the kill switch decorator). Strategy engine receives the `403 KILL_SWITCH_ACTIVE` response and marks the affected run `EXIT_FAILED` if it was trying to exit, or `ENTRY_FAILED` if entering.
- Engine should pause new RMS-triggered exits while kill switch is active — they'll fail anyway. Mark all active runs as `STOPPED` and let the kill switch's own cleanup actions handle position flatten.
- After kill-switch deactivation, runs **stay STOPPED**; user must restart manually (same convention as Python strategies / Flow).

---

## 17. Documentation deliverables (Phase 7)

- `docs/userguide/strategy-builder/README.md` — overview
- `docs/userguide/strategy-builder/leg-builder.md` — segment-by-segment field reference
- `docs/userguide/strategy-builder/risk-management.md` — pts vs pct, trail X/Y semantics, overall rules
- `docs/userguide/strategy-builder/account-rms.md` — concurrency caps, daily loss
- `docs/userguide/strategy-builder/sandbox-vs-live.md`
- `docs/userguide/strategy-builder/migration-from-v1.md`
- `docs/api/strategy-v2-api.md` — full REST API reference
- `docs/api/strategy-v2-websocket-events.md` — Socket.IO event catalog

---

## 18. Glossary

- **Run**: one execution lifecycle of a strategy — from signal to all-flat. A strategy can have many runs over time.
- **Leg**: one component of a strategy. Cash strategies typically have 1-10 legs (stocks); options strategies 1-4 legs.
- **Tick**: one price update from `market_data_service`.
- **MTM**: mark-to-market unrealized P&L.
- **Peak MTM**: highest MTM seen this run; ratchet only.
- **Drawdown**: peak_mtm − current_mtm.
- **Profit lock**: once peak ≥ lock_at, exit if MTM falls back to lock_min.
- **Trail X/Y**: every X favorable points, advance SL by Y favorable points (floor-division ratchet).
- **Trail-to-entry**: per-leg, once leg moves favorably by threshold %/pts, pin SL ≥ entry price (no-loss trade).
- **Account RMS**: rules above strategy level (concurrency cap, daily loss, post-loss cooldown).
- **Sandbox**: forward-test mode using `sandbox_service` and `db/sandbox.db`; uses real LTPs, virtual fills.
- **BrokerAdapter**: thin abstraction selecting between live broker services and sandbox service. Engine never imports broker services directly.

---

## 19. Sign-off checklist (before Phase 0 starts)

- [x] User confirms hybrid approach (keep webhook URL, rewrite engine)
- [ ] User confirms phase plan and ordering
- [ ] User confirms migration approach (auto-convert v1 to 1-leg v2)
- [x] User confirms `placesmartorder` is **not** used in the strategy engine
- [x] **Webhook duplicate policy**: REJECT (no queueing) — see §14.2
- [x] **Strategy capital allocation**: NOT TRACKED — see §14.2
- [x] **Sandbox slippage model**: ZERO SLIPPAGE (fills at LTP) — see §14.2
- [x] **Webhook security**: HMAC + body-secret + replay window + IP allowlist, ship in Phase 1 — see §8.4 and §14.2
- [x] **Event-driven architecture**: integrate with existing `utils/event_bus.py`; new event types in `events/strategy_events.py` + `events/account_events.py`; new audit subscriber as single writer of `strategy_events` — see §5.3
- [x] **Realtime guarantees**: ticks bypass bus (direct `subscribe_critical`); state events go through bus (10-worker thread pool); UI debounce 5Hz on tick path — see §8.6
- [x] **Security hardening**: encryption-at-rest for webhook secrets (Fernet/APP_KEY), adaptive ban on signature failures, audit-chain hash, marshmallow strict schemas — see §8.5
- [x] **Decisions §14.3 locked with defaults**: manual lockout (with optional auto-clear time), segregated live/sandbox dashboards, single dispatcher
- [x] User confirms IST/UTC timestamp model (DB stores UTC, APIs return IST strings)
- [x] User confirms branch is `strategy` (already created)
- [ ] DB snapshot taken before Phase 0 init scripts run

---

**End of plan.**
