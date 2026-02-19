# Strategy Risk Management & Position Tracking — PRD V2

**Date**: 2026-02-19
**Status**: Draft V2
**Scope**: Webhook + Chartink Strategies (V1) + F&O Strategy Builder + Risk Monitor
**Previous Version**: 2026-02-06-strategy-risk-management-prd.md (V1)

---

## Change Log (V1 → V2)

| Section | Change | Gap Addressed |
|---------|--------|---------------|
| 3 (Scope) | Added F&O Strategy Builder, Strategy Templates, Risk Monitor tab, Market Hours Intelligence, Strategy Cloning | GAP 1, 2, 5, 7, 14 |
| 5.2 (Schema) | Added `legs_config` structured validation rules | GAP 11 |
| 12 (Frontend) | Added Strategy Builder page, Templates page, Risk Monitor tab, Position Group visualization, Distance metrics columns, Progress bars, Market status indicator, Circuit breaker UI, Clone button | GAP 1-8, 11-15 |
| 14 (Services) | Added StrategyTemplateService, MarketStatusService | GAP 2, 7 |
| 15 (API) | Added builder, templates, clone, market-status, risk-events endpoints | GAP 1, 2, 7, 14 |
| 20 (Circuit Breaker) | Specified 3 behavior modes: alert_only, stop_entries, close_all_positions | GAP 8 |
| NEW §23 | F&O Strategy Builder — Backend & Frontend specification | GAP 1, 3, 11 |
| NEW §24 | Pre-built Strategy Templates | GAP 2 |
| NEW §25 | Risk Monitor & Threshold Visualization | GAP 5, 6 |
| NEW §26 | Leg-Level Distance Metrics | GAP 4 |
| NEW §27 | Position Group Visualization | GAP 15 |
| NEW §28 | Market Hours Intelligence | GAP 7 |
| NEW §29 | Strategy Cloning | GAP 14 |
| NEW §30 | Per-Leg P&L Breakdown | GAP 12 |
| NEW §31 | Risk Evaluation Logic — exact formulas matching AlgoMirror (combined premium, leg SL/TGT/TSL, combined max loss/profit/TSL, breakeven) | — |
| NEW §32 | Strategy Scheduling — configurable start/stop times, trading days, APScheduler pattern matching `/python` | — |
| 3 (Scope) | Added strategy scheduling, risk evaluation logic, breakeven stoploss to V2 scope | — |
| 5 (Schema) | Added schedule columns reference | — |
| 13 (Notifications) | Added schedule-related events | — |
| 14 (Services) | Added StrategySchedulerService | — |
| 15 (API) | Added schedule endpoints | — |
| 16 (Webhook) | Added schedule-aware webhook gating | — |
| 18 (Configuration) | Added schedule-related env vars | — |
| 22 (Files) | Added scheduling and risk evaluation files | — |
| OUT OF SCOPE (V2) | Technical Indicator Exit Mode (Supertrend), Multi-Account Support | GAP 9, 10 |

---

## 1. Problem Statement

*(Unchanged from V1 — see original PRD Section 1)*

Currently, OpenAlgo strategies (Webhook and Chartink) have no local order/position tracking — everything is delegated to broker APIs. There is no strategy-level stoploss, target, or trailing stop. A trader running multiple strategies on the same symbol has no way to manage or view positions per strategy.

---

## 2. Goals

*(Unchanged from V1 — see original PRD Section 2)*

1. Strategy-level risk management (SL, TGT, TSL, BE)
2. Strategy-level position tracking (local DB)
3. Live PnL updates (WebSocket + REST fallback)
4. Strategy-isolated exits
5. Persistence across restarts
6. Unified dashboard

---

## 3. Scope

### In Scope (V1)

- Webhook strategies (`blueprints/strategy.py`)
- Chartink strategies (`blueprints/chartink.py`)
- Strategy-level defaults with symbol-level overrides for SL/target/trailing stop/breakeven
- Percentage and Points as value modes
- Simple trailing stop (trail from peak price, only moves in favorable direction)
- Breakeven: move SL to entry when profit threshold hit
- Always MARKET exit orders on trigger
- Automatic order tracking (orders placed via webhooks)
- Manual position close (individual + all strategy positions + position group)
- Futures order mapping: single futures contract with auto-split
- Options order mapping: single option (ATM/ITM/OTM) and multi-leg (presets + custom)
- Combined P&L mode for multi-leg positions
- Per-leg and combined risk parameters
- Strategy-level daily PnL circuit breaker
- Real-time dashboard with SocketIO updates
- REST polling fallback for market data

### In Scope (V2 — New)

- **F&O Strategy Builder** — dedicated page (`/strategy/builder`) for multi-leg options/futures strategy creation with 4-step guided flow
- **Pre-built strategy templates** — Iron Condor, Straddle, Strangle, Bull Call Spread, Bear Put Spread, Custom — browse, customize, deploy
- **Risk Monitor tab** — 6th tab in StrategyCard with progress bars, distance metrics, risk events audit log
- **Market hours intelligence** — market status indicator badge, auto-pause risk monitoring outside trading hours
- **Strategy cloning** — duplicate strategy with all config and symbol mappings in one click
- **Leg execution state visualization** — frozen legs with diagonal stripes pattern when filled
- **Position group visualization** — bordered cards for combined P&L groups with group-level actions
- **Distance metrics columns** — SL Dist, TGT Dist, TSL Dist in position table (color-coded by zone)
- **Daily circuit breaker behavior modes** — 3 modes: `alert_only`, `stop_entries`, `close_all_positions`
- **Per-leg P&L breakdown** — trades and P&L panels show per-leg profitability
- **Risk evaluation logic** — exact formulas for combined premium, leg-level SL/TGT/TSL (price-based), combined max loss/profit/TSL (P&L-based AFL ratcheting), breakeven stoploss
- **Strategy scheduling** — configurable start/stop times and trading days (default Mon-Fri 09:15-15:30 IST), APScheduler-based, exchange-specific defaults, holiday enforcement, auto square-off at stop time

### Out of Scope (Future)

- Technical indicator exit mode (Supertrend) — deferred to V2+
- Multi-account support — deferred to V2+
- Basket/portfolio-level risk (cross-strategy)
- Broker-side GTT/CO orders
- Historical backtesting
- Options Greeks-based exits (delta, gamma, theta thresholds)

---

## 4. Design Decisions

*(Unchanged from V1 — see original PRD Section 4)*

Key decisions: Local DB tracking (not broker-dependent), WebSocket-first market data with REST fallback, AFL-style trailing stop ratcheting, strategy-level + symbol-level risk parameter resolution, always MARKET exit orders.

---

## 5. Database Schema

*(Sections 5.1-5.8 unchanged from V1 — see original PRD Section 5)*

Tables: `strategy_order`, `strategy_position`, `strategy_trade`, `strategy_daily_pnl`, `strategy_position_group`, `alert_log`

**V2 additions to existing Strategy/ChartinkStrategy tables:**
- Schedule columns: `schedule_enabled`, `schedule_start_time`, `schedule_stop_time`, `schedule_days`, `schedule_auto_entry`, `schedule_auto_exit` — see §32.2
- Risk columns from V1: `default_breakeven_type`, `default_breakeven_threshold` — see §31.10

### 5.2 Addition: `legs_config` Structured Validation (V2)

The `legs_config` JSON field in SymbolMapping must follow this schema for F&O strategies built via the Strategy Builder:

```json
{
  "preset": "iron_condor",
  "legs": [
    {
      "leg_id": 1,
      "leg_type": "option",
      "product_type": "NRML",
      "expiry_type": "current_week",
      "action": "SELL",
      "option_type": "CE",
      "strike_selection": "OTM",
      "strike_offset": 4,
      "strike_price": null,
      "premium_value": null,
      "lots": 1,
      "order_type": "MARKET"
    }
  ],
  "risk_mode": "combined",
  "combined_risk": {
    "stoploss_type": "points",
    "stoploss_value": 50,
    "target_type": "points",
    "target_value": 100,
    "trailstop_type": "percentage",
    "trailstop_value": 20
  },
  "per_leg_risk": null
}
```

**Validation rules:**
- `legs`: array of 1-6 leg objects
- Each leg: `leg_type` required (`option` | `futures`)
- If `leg_type=option`: `option_type` (CE|PE) and `strike_selection` required
- `strike_selection` values: `ATM`, `ITM`, `OTM`, `strike_price`, `premium_near`
- If `strike_selection=ITM` or `OTM`: `strike_offset` required (1-20)
- If `strike_selection=strike_price`: `strike_price` required (positive float)
- If `strike_selection=premium_near`: `premium_value` required (positive float)
- `action`: BUY | SELL
- `lots`: positive integer
- `risk_mode`: `per_leg` | `combined`
- If `risk_mode=combined`: `combined_risk` object required
- If `risk_mode=per_leg`: each leg must have its own risk params

### 5.9 Strategy Template Schema (V2 — New)

```sql
CREATE TABLE strategy_template (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              VARCHAR(100) NOT NULL,
    description       TEXT,
    category          VARCHAR(20) NOT NULL,        -- 'neutral', 'bullish', 'bearish', 'hedge'
    preset            VARCHAR(20) NOT NULL,        -- 'straddle', 'strangle', 'iron_condor', etc.
    default_underlying VARCHAR(50) DEFAULT 'NIFTY',
    default_exchange  VARCHAR(10) DEFAULT 'NFO',
    default_expiry_type VARCHAR(15) DEFAULT 'current_week',
    default_product_type VARCHAR(10) DEFAULT 'NRML',
    risk_mode         VARCHAR(10) DEFAULT 'combined',
    legs_config       JSON NOT NULL,               -- default leg configuration
    combined_risk     JSON,                        -- default combined risk params
    per_leg_risk      JSON,                        -- default per-leg risk params
    daily_circuit_breaker JSON,                    -- default daily CB params
    is_system         BOOLEAN DEFAULT FALSE,       -- system templates cannot be deleted
    is_active         BOOLEAN DEFAULT TRUE,
    created_by        VARCHAR(255),
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP
);
```

---

## 6. Risk Parameter Resolution

*(Unchanged from V1 — see original PRD Section 6)*

Resolution order: Symbol-level override → Strategy-level default → No risk (disabled).

---

## 7. Options Order Mapping

*(Unchanged from V1 — see original PRD Section 7)*

Sections 7.1-7.10 cover: option type, strike selection, expiry type, single option flow, multi-leg presets, custom multi-leg, combined P&L mode, per-leg risk, position group lifecycle, and execution via `place_options_multiorder`.

---

## 8. Exit Execution Mechanism

*(Unchanged from V1 — see original PRD Section 8)*

Pluggable exit mechanism with MARKET orders. Handles partial fills with retry logic.

---

## 9. Order Lifecycle

*(Unchanged from V1 — see original PRD Section 9)*

State machine: `pending` → `open` → `complete` / `rejected` / `cancelled`. Order status polling via `get_order_status()`.

---

## 10. Risk Engine Architecture

*(Unchanged from V1 — see original PRD Section 10)*

Components: StrategyRiskEngine (main loop), StrategyPositionTracker, StrategyPnLService. Dual-engine market data: WebSocket (CRITICAL priority) with REST polling fallback at 3-second intervals.

---

## 11. Real-Time Status Tracking & Order Status Updates

*(Unchanged from V1 — see original PRD Section 11)*

OrderStatusPoller: polls broker for fill confirmations. Position state machine: `pending_entry` → `active` → `exiting` → `closed`.

---

## 12. Frontend — Strategy Dashboard

*(Base V1 content unchanged — see original PRD Section 12)*

### V2 Additions to Frontend

#### 12.10 Strategy Builder Page (NEW)

Full page at `/strategy/builder` with 4-step wizard flow:
1. **Basics** — name, underlying, exchange, expiry type, product type
2. **Legs** — preset selector + 9-parameter leg cards (max 6 legs)
3. **Risk** — per-leg or combined risk config + circuit breaker
4. **Review & Save** — summary, save as strategy or template

See Section 23 for full specification.

#### 12.11 Strategy Templates Page (NEW)

Gallery page at `/strategy/templates` with category filters (Neutral, Bullish, Bearish, Hedge). Template cards with deploy button. See Section 24 for full specification.

#### 12.12 Risk Monitor Tab (NEW — 6th Tab)

Added as 6th tab in StrategyCard, containing:
- Per-position threshold progress bars (SL/TGT/TSL)
- Combined group threshold progress bars
- Daily circuit breaker progress bars
- Risk events audit log (scrollable, reverse chronological)
- WebSocket connection status badge

See Section 25 for full specification.

#### 12.13 Position Group Visualization (NEW)

Positions with same `position_group_id` wrapped in bordered cards:
- Group header: name, leg count, combined P&L, compact progress bars
- Close Group button
- Left border colored by status (green/amber/red/gray)
- Expandable/collapsible

See Section 27 for full specification.

#### 12.14 Distance Metrics Columns (NEW)

Three new columns in PositionRow (columns 7, 9, 11):
- SL Dist: distance from LTP to stoploss price
- TGT Dist: distance from LTP to target price
- TSL Dist: distance from LTP to trailing stop price
- Color-coded: safe (>10%), warning (5-10%), danger (<5% with pulse animation)

See Section 26 for full specification.

#### 12.15 Circuit Breaker Card (NEW)

In OverviewTab: displays daily CB config, behavior mode dropdown (3 modes), current status. Red alert banner when tripped.

See Section 20.4.1 for behavior modes.

#### 12.16 Market Status Indicator (NEW)

Badge in DashboardHeader showing current market phase with color-coded icon.

See Section 28 for full specification.

#### 12.17 Clone Strategy Button (NEW)

In OverviewTab manage actions section. One-click clone with confirmation dialog.

See Section 29 for full specification.

#### 12.18 Enhanced CreateStrategyDialog (NEW)

Strategy type selector at top:
1. "Webhook Strategy" → existing form
2. "F&O Strategy Builder" → navigate to `/strategy/builder`
3. "From Template" → navigate to `/strategy/templates`

---

## 13. Notifications

*(Unchanged from V1 — see original PRD Section 13)*

Toast notifications via SocketIO for: position opened, exit triggered, position closed, order rejected, risk paused/resumed, partial fill warning, breakeven activated, schedule started/stopped/blocked.

### V2 Addition: Schedule Events

| Event | When | Toast Style |
|-------|------|-------------|
| `strategy_schedule_started` | Scheduled start fires | info |
| `strategy_schedule_stopped` | Scheduled stop fires (with auto square-off count) | info |
| `strategy_schedule_blocked` | Webhook entry rejected outside schedule | warning |
| `strategy_schedule_holiday` | Strategy paused for market holiday | warning |

See §32.14 for full event payloads.

---

## 14. Backend Services

*(Sections 14.1-14.6 unchanged from V1 — see original PRD Section 14)*

V1 Services:
1. StrategyRiskEngine
2. StrategyPositionTracker
3. OrderStatusPoller
4. StrategyPnLService
5. StrategyOptionsResolver
6. StrategyExitExecutor

### 14.7 StrategyTemplateService (V2 — New)

**File:** `services/strategy_template_service.py`

**Responsibilities:**
- CRUD operations for strategy templates
- System template initialization on first run (5 preset templates)
- Template deployment: create Strategy + SymbolMapping from template config
- Template validation: ensure `legs_config` matches schema
- Template categories: neutral, bullish, bearish, hedge

### 14.8 MarketStatusService (V2 — New)

**File:** `services/market_status_service.py`

**Responsibilities:**
- Wrap `market_calendar_service.get_timings()` for strategy dashboard
- Cache market status with 60-second refresh
- Determine current market phase: `pre_market`, `market_open`, `post_market`, `market_closed`, `holiday`
- Check holiday calendar and return holiday name
- Used by Risk Engine to auto-pause/resume monitoring

### 14.9 StrategySchedulerService (V2 — New)

**File:** `services/strategy_scheduler_service.py`

**Responsibilities:**
- Initialize APScheduler with IST timezone (matching `/python` pattern)
- Create/remove CronTrigger jobs per strategy (start + stop)
- Scheduled start: check `manually_stopped`, `schedule_days`, market holidays before activating
- Scheduled stop: auto square-off MIS positions, pause risk engine, reject webhook entries
- Daily trading day check (00:01 IST): stop scheduled strategies on non-trading days
- Market hours enforcer (every minute): resume paused strategies when trading day starts
- Restore schedules on application restart
- Integrate with StrategyRiskEngine for activate/pause on schedule events
- Webhook gating: entry signals blocked outside schedule, exit signals always accepted

See §32 for full specification.

---

## 15. Backend API Endpoints

*(Sections 15.1-15.9 unchanged from V1 — see original PRD Section 15)*

V1 Endpoints:
1. Dashboard overview
2. Strategy positions
3. Strategy orders
4. Strategy trades
5. Strategy P&L
6. Risk config CRUD
7. Risk activate/deactivate
8. Position close (individual + all)
9. Position delete

### 15.10 Strategy Builder (V2 — New)

```
POST /strategy/api/builder/save
Body: {
    "name": "Iron Condor Weekly",
    "underlying": "NIFTY",
    "underlying_exchange": "NSE_INDEX",
    "exchange": "NFO",
    "expiry_type": "current_week",
    "product_type": "NRML",
    "risk_mode": "combined",
    "preset": "iron_condor",
    "legs": [
        {
            "leg_type": "option",
            "product_type": "NRML",
            "expiry_type": "current_week",
            "action": "SELL",
            "option_type": "CE",
            "strike_selection": "OTM4",
            "lots": 1,
            "order_type": "MARKET"
        }
    ],
    "combined_risk": {
        "stoploss_type": "points",
        "stoploss_value": 50,
        "target_type": "points",
        "target_value": 100
    },
    "daily_circuit_breaker": {
        "daily_stoploss_type": "points",
        "daily_stoploss_value": 5000,
        "daily_cb_behavior": "close_all_positions"
    }
}
Response: { "status": "success", "strategy_id": 42 }
```

```
POST /strategy/api/builder/<id>/execute
Body: { "action": "BUY" }
Response: { "status": "success", "order_ids": [...] }
```

### 15.11 Strategy Templates (V2 — New)

```
GET    /strategy/api/templates               -- list all templates (filter by category)
GET    /strategy/api/templates/<id>          -- get template details
POST   /strategy/api/templates               -- create custom template (from builder)
POST   /strategy/api/templates/<id>/deploy   -- deploy template as new strategy
DELETE /strategy/api/templates/<id>          -- delete custom template (not system)
```

### 15.12 Strategy Cloning (V2 — New)

```
POST /strategy/api/strategy/<id>/clone
Response: {
    "status": "success",
    "new_strategy_id": 42,
    "new_name": "Iron Condor Weekly (Copy)"
}
```

### 15.13 Market Status (V2 — New)

```
GET /strategy/api/market-status
Response: {
    "phase": "market_open",
    "exchange": "NSE",
    "session_start": "09:15",
    "session_end": "15:30",
    "next_event": "market_close at 15:30 IST",
    "is_holiday": false,
    "holiday_name": null
}
```

### 15.14 Risk Events (V2 — New)

```
GET /strategy/api/strategy/<id>/risk-events?limit=20&offset=0
Response: {
    "events": [
        {
            "id": 1,
            "event_type": "stoploss_triggered",
            "severity": "critical",
            "symbol": "NIFTY..CE",
            "message": "Stoploss hit at ₹245. P&L: -₹975",
            "timestamp": "2026-02-19T14:32:15+05:30"
        }
    ],
    "total_count": 45
}
```

### 15.15 Position Group Actions (V2 — New)

```
POST /strategy/api/strategy/<id>/group/<gid>/close
Response: { "status": "success", "exit_order_ids": [...] }
```

### 15.16 Circuit Breaker Configuration (V2 — New)

```
PUT /strategy/api/strategy/<id>/circuit-breaker
Body: {
    "daily_stoploss_type": "points",
    "daily_stoploss_value": 5000,
    "daily_target_type": "points",
    "daily_target_value": 10000,
    "daily_trailstop_type": "points",
    "daily_trailstop_value": 2000,
    "daily_cb_behavior": "close_all_positions"
}
Response: { "status": "success" }
```

### 15.17 Strategy Schedule (V2 — New)

```
GET /api/v1/strategy/{id}/schedule
Response: {
    "status": "success",
    "data": {
        "start_time": "09:15",
        "stop_time": "15:30",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "auto_entry": true,
        "auto_exit": true,
        "current_state": "running",
        "next_start": null,
        "next_stop": "15:30 IST today"
    }
}
```

```
PUT /api/v1/strategy/{id}/schedule
Body: {
    "start_time": "09:15",
    "stop_time": "15:30",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "auto_entry": true,
    "auto_exit": true
}
Response: { "status": "success" }
```

See §32.13 for full specification.

---

## 16. Webhook Handler Changes

*(Sections 16.1-16.4 unchanged from V1 — see original PRD Section 16)*

### V2 Addition: Schedule-Aware Webhook Gating

Webhook entry signals are blocked when the strategy is outside its schedule window, manually stopped, or paused for a holiday. Exit/squareoff signals are always accepted.

```python
# In webhook handler (strategy.py / chartink.py):
def handle_webhook_signal(strategy, signal):
    if signal.action in ('SELL', 'squareoff', 'close'):
        # Exit signals always accepted regardless of schedule
        pass
    else:
        # Entry signals gated by schedule
        if not strategy_scheduler.is_within_schedule(strategy):
            return {"status": "error", "message": "Strategy outside schedule window"}, 403
        if strategy.manually_stopped:
            return {"status": "error", "message": "Strategy manually stopped"}, 403
```

See §32.10 for full webhook behavior matrix.

---

## 17. Concurrency, Data Integrity & Performance

*(Unchanged from V1 — see original PRD Section 17)*

---

## 18. Configuration

*(Sections 18.1-18.2 unchanged from V1 — see original PRD Section 18)*

### V2 Addition: Schedule & Risk Evaluation Environment Variables

```bash
# Strategy Scheduling
STRATEGY_DEFAULT_SCHEDULE_START=09:15        # Default start time (IST)
STRATEGY_DEFAULT_SCHEDULE_STOP=15:30         # Default stop time (IST)
STRATEGY_DEFAULT_SCHEDULE_DAYS=mon,tue,wed,thu,fri  # Default trading days
STRATEGY_SCHEDULE_ENFORCE_HOLIDAYS=true      # Block on market holidays
STRATEGY_DAILY_CHECK_TIME=00:01              # Daily trading day check time (IST)

# Exchange-Specific Schedule Defaults (used when creating strategies)
STRATEGY_SCHEDULE_NFO=09:15-15:30            # NSE F&O
STRATEGY_SCHEDULE_BFO=09:15-15:30            # BSE F&O
STRATEGY_SCHEDULE_CDS=09:00-17:00            # Currency
STRATEGY_SCHEDULE_BCD=09:00-17:00            # BSE Currency
STRATEGY_SCHEDULE_MCX=09:00-23:30            # Commodity
```

---

## 19. Database Migration

*(Sections 19.1-19.6 unchanged from V1 — see original PRD Section 19)*

### V2 Addition: Schedule Columns

The migration script must add these columns to both `strategies` and `chartink_strategies` tables (via `PRAGMA table_info` check, idempotent):

```sql
-- Strategy Scheduling (§32)
schedule_enabled       BOOLEAN DEFAULT TRUE
schedule_start_time    VARCHAR(5) DEFAULT '09:15'
schedule_stop_time     VARCHAR(5) DEFAULT '15:30'
schedule_days          TEXT DEFAULT '["mon","tue","wed","thu","fri"]'
schedule_auto_entry    BOOLEAN DEFAULT TRUE
schedule_auto_exit     BOOLEAN DEFAULT TRUE
```

These are added alongside the existing risk columns (`default_stoploss_type`, `default_breakeven_type`, etc.) in `migrate_strategy_risk.py`.

---

## 20. Strategy-Level Daily Circuit Breaker

*(Sections 20.1-20.4 unchanged from V1 — see original PRD Section 20)*

### 20.4.1 Circuit Breaker Behavior Modes (V2 — New)

Three configurable behavior modes when the daily circuit breaker trips:

| Mode | `daily_cb_behavior` | On Trip |
|------|---------------------|---------|
| `alert_only` | Toast + Telegram notification only | No automatic action; trader decides manually |
| `stop_entries` | Block new webhook entry signals | Existing positions stay open; exit signals still allowed |
| `close_all_positions` | Close all open positions immediately | Exit orders placed for all positions; entry signals blocked |

**Database column** (add to Strategy + ChartinkStrategy):

```sql
daily_cb_behavior VARCHAR(25) DEFAULT 'close_all_positions'
```

The behavior mode is configurable per strategy via the Circuit Breaker Card in the OverviewTab.

**Risk Engine handling per mode:**

```python
def _handle_circuit_breaker_trip(self, strategy, reason):
    behavior = strategy.daily_cb_behavior or 'close_all_positions'

    if behavior == 'alert_only':
        # Notify only — no position changes
        self._emit_circuit_breaker_event(strategy, reason, 'alert_only')
        self._send_telegram_notification(strategy, reason)

    elif behavior == 'stop_entries':
        # Block entries, allow exits
        strategy.circuit_breaker_active = True
        self._emit_circuit_breaker_event(strategy, reason, 'stop_entries')
        self._send_telegram_notification(strategy, reason)

    elif behavior == 'close_all_positions':
        # Close everything
        strategy.circuit_breaker_active = True
        self._close_all_strategy_positions(strategy)
        self._emit_circuit_breaker_event(strategy, reason, 'close_all_positions')
        self._send_telegram_notification(strategy, reason)
```

---

## 21. Key Constraints & Safety

*(Unchanged from V1 — see original PRD Section 21)*

---

## 22. Files to Create / Modify

*(V1 files unchanged — see original PRD Section 22)*

### V2 — Additional Files

| File | Purpose |
|------|---------|
| `services/strategy_template_service.py` | Template CRUD and deployment |
| `services/market_status_service.py` | Market phase determination |
| `database/strategy_template_db.py` | StrategyTemplate model |
| `blueprints/strategy_builder.py` | Builder API routes |
| `blueprints/strategy_templates.py` | Templates API routes |
| `frontend/src/pages/strategy/StrategyBuilder.tsx` | F&O strategy builder page |
| `frontend/src/pages/strategy/StrategyTemplates.tsx` | Templates gallery page |
| `frontend/src/components/strategy-dashboard/RiskMonitorTab.tsx` | Risk monitor tab with progress bars |
| `frontend/src/components/strategy-dashboard/RiskProgressBar.tsx` | Threshold progress bar component |
| `frontend/src/components/strategy-dashboard/RiskEventsLog.tsx` | Risk events audit log |
| `frontend/src/components/strategy-dashboard/PositionGroup.tsx` | Position group card |
| `frontend/src/components/strategy-dashboard/PositionGroupHeader.tsx` | Group header with combined P&L |
| `frontend/src/components/strategy-dashboard/CircuitBreakerCard.tsx` | CB config and status |
| `frontend/src/components/strategy-dashboard/CircuitBreakerBanner.tsx` | Red alert banner when CB tripped |
| `frontend/src/components/strategy-dashboard/MarketStatusIndicator.tsx` | Market phase badge |
| `frontend/src/components/strategy-builder/LegCard.tsx` | 9-parameter leg card |
| `frontend/src/components/strategy-builder/PresetSelector.tsx` | Preset template selector |
| `frontend/src/components/strategy-builder/RiskConfigStep.tsx` | Risk configuration step |
| `frontend/src/components/strategy-builder/ReviewStep.tsx` | Review and save step |
| `frontend/src/components/strategy-builder/FrozenLegOverlay.tsx` | Diagonal stripes for filled legs |
| `frontend/src/components/strategy-templates/TemplateCard.tsx` | Template display card |
| `frontend/src/components/strategy-templates/DeployDialog.tsx` | Template deploy customization |
| `frontend/src/api/strategy-builder.ts` | Builder API client |
| `frontend/src/api/strategy-templates.ts` | Templates API client |
| `frontend/src/hooks/useMarketStatus.ts` | Market status polling hook |
| `frontend/src/types/strategy-builder.ts` | Builder TypeScript interfaces |
| `frontend/src/types/strategy-templates.ts` | Template TypeScript interfaces |
| `services/strategy_scheduler_service.py` | APScheduler-based strategy scheduling (start/stop/enforce) |
| `frontend/src/components/strategy-builder/ScheduleConfig.tsx` | Schedule configuration UI (day toggles, time pickers) |
| `frontend/src/components/strategy-dashboard/ScheduleBadge.tsx` | Schedule status badge in StrategyCard header |
| `frontend/src/api/strategy-schedule.ts` | Schedule API client |
| `frontend/src/types/strategy-schedule.ts` | Schedule TypeScript interfaces |

### V2 — Modified Files (Additional)

| File | Change |
|------|--------|
| `database/strategy_db.py` | Add schedule columns to Strategy model |
| `database/chartink_db.py` | Add schedule columns to ChartinkStrategy model |
| `upgrade/migrate_strategy_risk.py` | Add schedule column migrations |
| `blueprints/strategy.py` | Add schedule-aware webhook gating |
| `blueprints/chartink.py` | Add schedule-aware webhook gating |
| `app.py` | Initialize StrategySchedulerService on startup, restore schedules |
| `services/strategy_risk_engine.py` | Integrate with scheduler for activate/pause on schedule events |

---

## Implementation Phases (Updated for V2)

### Phase 1: Core Infrastructure (V1)

- Database schema creation (strategy_order, strategy_position, strategy_trade, strategy_daily_pnl, strategy_position_group, alert_log)
- StrategyPositionTracker service
- StrategyPnLService
- OrderStatusPoller
- Webhook handler integration
- Basic REST API endpoints (dashboard, positions, orders, trades, P&L)

### Phase 2: Risk Engine (V1)

- StrategyRiskEngine (main monitoring loop)
- SL/TGT/TSL/BE evaluation (§31 risk evaluation logic — exact formulas)
- Leg-level SL/TGT/TSL (price-based, 3 types: percentage/points/premium) — §31.2-31.4
- Combined premium calculation — §31.1
- Combined max loss/profit (P&L-based) — §31.5-31.6
- Combined trailing stop (AFL-style ratcheting) — §31.7
- Breakeven stoploss (one-time SL move to entry) — §31.10
- Exit execution with retry logic
- WebSocket market data integration
- REST polling fallback
- Combined P&L mode for multi-leg
- Daily circuit breaker (basic — `close_all_positions` mode only)

### Phase 3: Frontend Dashboard (V1 + V2 Enhancements)

- StrategyHub page with collapsible StrategyCards
- 6-tab interface (Overview, Positions, Orders, Trades, P&L, **Risk Monitor**)
- SocketIO real-time updates
- Position table with **14 columns** (including distance metrics)
- **Position group visualization** (bordered cards)
- **Circuit breaker card** with 3 behavior modes
- **Market status indicator** badge
- **Clone strategy** button
- Toast notifications

### Phase 4: F&O Strategy Builder (V2)

- Strategy Builder page with 4-step wizard (includes schedule config in BasicsStep)
- 9-parameter leg card component
- 5 strike selection types: ATM, ITM (1-20), OTM (1-20), strike_price, premium_near — §23.7
- Preset selector (Straddle, Strangle, Iron Condor, Bull Call, Bear Put, Custom)
- Leg execution state visualization (frozen legs with diagonal stripes)
- Builder API endpoints (save, execute)
- Integration with `place_options_multiorder` / `place_options_order` — §23.6
- Freeze quantity routing via `symbol_service.get_symbol_info()` — §23.6
- Support for all 5 F&O exchanges: NFO, BFO, CDS, BCD, MCX — §23.8
- Symbol resolution via `get_option_symbol` and `get_expiry`

### Phase 5: Templates & Cloning (V2)

- StrategyTemplate database model
- StrategyTemplateService
- System template initialization (5 presets)
- Templates gallery page with category filters
- Deploy dialog with customization
- Template CRUD API endpoints
- Strategy cloning API and UI

### Phase 6: Risk Monitor & Market Intelligence (V2)

- Risk Monitor tab component
- Risk threshold progress bars (SL/TGT/TSL/Daily)
- Risk events audit log
- MarketStatusService
- Market hours auto-pause/resume
- **Circuit breaker behavior modes** (alert_only, stop_entries, close_all_positions)
- Per-leg P&L breakdown in trades/P&L panels
- Distance metrics computation (client-side)

### Phase 7: Strategy Scheduling (V2)

- StrategySchedulerService (APScheduler with IST timezone) — §32
- Schedule database columns on Strategy/ChartinkStrategy tables — §32.2
- CronTrigger jobs per strategy (start + stop) — §32.4
- Scheduled start with manually_stopped/holiday/day checks — §32.5
- Scheduled stop with auto square-off for MIS positions — §32.6
- Daily trading day check job (00:01 IST) — §32.8
- Market hours enforcer job (every minute) — §32.8
- Schedule-aware webhook gating (block entries outside window) — §32.10
- Exchange-specific default schedules (NFO, BFO, CDS, BCD, MCX) — §32.11
- Schedule config UI (day toggles, time pickers) in Strategy Builder — §32.12
- Schedule status badge in StrategyCard header — §32.12
- Schedule API endpoints (GET/PUT) — §32.13
- Schedule SocketIO events — §32.14
- Restore schedules on application restart

---

## 23. F&O Strategy Builder

### 23.1 Overview

A dedicated page (`/strategy/builder`) for creating and configuring F&O (Futures & Options) strategies with a step-by-step guided flow. Inspired by AlgoMirror's 9-parameter leg configuration system but adapted for OpenAlgo's React frontend and webhook-based execution model.

### 23.2 Builder Flow (4 Steps)

**Step 1 — Strategy Basics:**
- Strategy name (required, unique per user)
- Underlying (typeahead search via `/search/api/underlyings?exchange=NFO`)
- Exchange: NFO (NSE) or BFO (BSE)
- Expiry type: `current_week`, `next_week`, `current_month`, `next_month`
- Product type: NRML (overnight) or MIS (intraday)

**Step 2 — Leg Configuration:**
- Preset selector at top: Straddle, Strangle, Iron Condor, Bull Call Spread, Bear Put Spread, Custom
- Selecting a preset auto-populates legs (user can modify after)
- Each leg card has 9 parameters (AlgoMirror pattern):

| # | Parameter | Type | Values |
|---|-----------|------|--------|
| 1 | Leg type | select | `option`, `futures` |
| 2 | Product type | select | `NRML`, `MIS` |
| 3 | Expiry type | select | `current_week`, `next_week`, `current_month`, `next_month` |
| 4 | Action | toggle | `BUY`, `SELL` |
| 5 | Option type | toggle | `CE`, `PE` (options only) |
| 6 | Strike selection | select | See §23.7 Strike Selection Types (options only) |
| 7 | Strike value | dynamic | Auto-resolved or user-entered depending on selection type |
| 8 | Lots | number input | Positive integer, validated against lot size |
| 9 | Order type | read-only | `MARKET` (V1 only) |

- Add Leg button (max 6 legs per strategy)
- Remove Leg button (min 1 leg)
- Leg reordering via drag handle

**Step 3 — Risk Configuration:**
- Risk mode selector: Per-Leg | Combined P&L
- **Per-leg mode**: SL/TGT/TSL/BE config inputs on each leg card
- **Combined mode**: Single combined SL/TGT/TSL config panel
  - Value type: points or percentage
  - All thresholds optional
- Daily circuit breaker config (optional):
  - Daily stoploss value + type
  - Daily target value + type
  - Daily trailing stop value + type
  - Behavior mode: alert_only | stop_entries | close_all_positions

**Step 4 — Review & Save:**
- Summary card showing all configuration
- Legs visualization with resolved strike prices
- Risk summary
- Estimated margin (if broker provides margin API)
- Save button → Creates Strategy + SymbolMapping records with `legs_config` JSON
- "Save as Template" checkbox → Also saves to `strategy_template` table

### 23.3 Leg Execution State Visualization

When a strategy is executed (webhook trigger or manual execute), each leg transitions through states:

| State | Visual | Badge |
|-------|--------|-------|
| `pending` | Normal card | "Pending" amber badge |
| `ordered` | Normal card + spinner | "Ordering..." amber pulse |
| `filled` | Frozen card (diagonal stripes overlay) | "Filled" green badge with fill price |
| `rejected` | Red border | "Rejected" red badge |
| `partial` | Partial stripes | "Partial N/M" amber badge |

**Frozen Leg Pattern (AlgoMirror-style):**

When a leg is filled, the leg card gets a diagonal stripes CSS overlay:

```css
.leg-frozen {
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 5px,
    rgba(0,0,0,0.03) 5px,
    rgba(0,0,0,0.03) 10px
  );
  pointer-events: none;
}
```

Dark mode variant:
```css
.dark .leg-frozen {
  background: repeating-linear-gradient(
    -45deg,
    transparent,
    transparent 5px,
    rgba(255,255,255,0.03) 5px,
    rgba(255,255,255,0.03) 10px
  );
}
```

### 23.4 Backend: Strategy Builder API

**Save endpoint:**
```
POST /strategy/api/builder/save
Body: {
    "name": "Iron Condor Weekly",
    "underlying": "NIFTY",
    "underlying_exchange": "NSE_INDEX",
    "exchange": "NFO",
    "expiry_type": "current_week",
    "product_type": "NRML",
    "risk_mode": "combined",
    "preset": "iron_condor",
    "legs": [
        {
            "leg_id": 1,
            "leg_type": "option",
            "product_type": "NRML",
            "expiry_type": "current_week",
            "action": "SELL",
            "option_type": "CE",
            "strike_selection": "OTM",
            "strike_offset": 4,
            "strike_price": null,
            "premium_value": null,
            "lots": 1,
            "order_type": "MARKET"
        },
        {
            "leg_id": 2,
            "leg_type": "option",
            "product_type": "NRML",
            "expiry_type": "current_week",
            "action": "SELL",
            "option_type": "PE",
            "strike_selection": "OTM",
            "strike_offset": 4,
            "strike_price": null,
            "premium_value": null,
            "lots": 1,
            "order_type": "MARKET"
        },
        {
            "leg_id": 3,
            "leg_type": "option",
            "product_type": "NRML",
            "expiry_type": "current_week",
            "action": "BUY",
            "option_type": "CE",
            "strike_selection": "OTM",
            "strike_offset": 6,
            "strike_price": null,
            "premium_value": null,
            "lots": 1,
            "order_type": "MARKET"
        },
        {
            "leg_id": 4,
            "leg_type": "option",
            "product_type": "NRML",
            "expiry_type": "current_week",
            "action": "BUY",
            "option_type": "PE",
            "strike_selection": "OTM",
            "strike_offset": 6,
            "strike_price": null,
            "premium_value": null,
            "lots": 1,
            "order_type": "MARKET"
        }
    ],
    "combined_risk": {
        "stoploss_type": "points",
        "stoploss_value": 50,
        "target_type": "points",
        "target_value": 100,
        "trailstop_type": "points",
        "trailstop_value": 20
    },
    "daily_circuit_breaker": {
        "daily_stoploss_type": "points",
        "daily_stoploss_value": 5000,
        "daily_cb_behavior": "close_all_positions"
    }
}
Response: { "status": "success", "strategy_id": 42 }
```

**Execute endpoint:**
```
POST /strategy/api/builder/<id>/execute
Body: { "action": "BUY" }
Response: { "status": "success", "order_ids": ["ord_1", "ord_2", "ord_3", "ord_4"] }
```

**Backend flow on execute:**
1. Load strategy + symbol mapping with `legs_config`
2. For each leg, resolve the concrete option symbol:
   - Get ATM strike from underlying LTP via `get_quotes(underlying, quote_exchange)`
   - Resolve strike based on `strike_selection` type (see §23.7):
     - ATM: `round(spot / strike_step) * strike_step`
     - ITM/OTM: `ATM ± (offset × strike_step)` (direction depends on CE/PE)
     - Specific: use `strike_price` directly
     - Premium Near: scan ±20 strikes, match closest premium to `premium_value`
   - Get expiry date via `get_expiry_dates(symbol, exchange, instrumenttype)`
   - Resolve full symbol via `get_option_symbol(underlying, exchange, expiry_date, strike, offset, option_type)`
3. Get `freeze_qty` via `get_symbol_info(underlying, exchange)` → `data.freeze_qty`
4. Place all legs via `place_options_multiorder(...)` with `splitsize = freeze_qty` per leg (see §23.6):
   - Service resolves option symbols internally from offset
   - Service handles freeze_qty splitting per leg automatically
   - BUY legs execute first, then SELL legs (margin efficiency)
   - Underlying LTP fetched once and reused across all legs
5. Create `strategy_order` records for each leg (and each split sub-order)
6. If combined risk mode: create `strategy_position_group` record
7. Emit `builder_leg_update` SocketIO events as each leg fills

### 23.5 Internal Service Usage

| Operation | Service | Function |
|-----------|---------|----------|
| Resolve expiry dates | `expiry_service` | `get_expiry_dates(symbol, exchange, instrumenttype)` |
| Resolve option symbol | `option_symbol_service` | `get_option_symbol(underlying, exchange, expiry_date, strike_int, offset, option_type)` |
| Get underlying LTP | `quotes_service` | `get_quotes(symbol, exchange)` |
| Get multiple LTPs | `multiquotes_service` | `get_multiquotes(symbols_dict)` |
| Place multi-leg options | `options_multiorder_service` | `place_options_multiorder(...)` — resolves symbols, handles splitsize per leg, BUY-first execution |
| Place single-leg option | `options_order_service` | `place_options_order(...)` — resolves symbol, handles splitsize |
| Place equity/futures order | `place_order_service` | `place_order(...)` — when qty ≤ freeze_qty |
| Split equity/futures order | `split_order_service` | `split_order(...)` — when qty > freeze_qty |
| Get symbol info + freeze_qty | `symbol_service` | `get_symbol_info(symbol, exchange)` → returns lotsize, tick_size, freeze_qty |

### 23.6 Freeze Quantity & Order Routing

All strategy order placement (entries AND exits) must respect the exchange freeze quantity limit. OpenAlgo is a single-user application — freeze quantity comes from the `qty_freeze` database via `symbol_service.get_symbol_info()`.

**Rule:** If the total order quantity exceeds the freeze limit, pass `splitsize = freeze_qty` so the order is automatically split into sub-orders each ≤ `freeze_qty`.

#### Order Routing by Instrument Type

| Instrument | Service | Freeze Handling |
|-----------|---------|-----------------|
| **Multi-leg options** (Strategy Builder, presets) | `place_options_multiorder(...)` | Pass `splitsize = freeze_qty` per leg — service handles splitting internally |
| **Single-leg option** (single option webhook) | `place_options_order(...)` | Pass `splitsize = freeze_qty` — service handles splitting internally |
| **Equity / Futures** | `place_order(...)` if qty ≤ freeze_qty, else `split_order(...)` with `splitsize = freeze_qty` | Manual routing needed |

#### Multi-Leg Options (via `place_options_multiorder`)

For F&O strategies built via the Strategy Builder, use `place_options_multiorder` which:
- Resolves option symbols from offset (ATM/ITM/OTM) for each leg
- Fetches underlying LTP **once** and reuses across all legs
- Executes **BUY legs first, then SELL legs** (margin efficiency)
- Handles `splitsize` per leg internally (max 100 splits per leg)
- Rate-limits between orders (default 100ms, configurable via `ORDER_RATE_LIMIT`)
- Emits a single summary SocketIO event (per-leg events suppressed)

```python
from services.place_options_multiorder_service import place_options_multiorder
from services.symbol_service import get_symbol_info

def execute_strategy_legs(strategy, legs_config, auth_token, broker):
    """
    Execute all legs of a multi-leg F&O strategy.
    Uses place_options_multiorder which handles freeze qty splitting internally.
    """
    # Get freeze_qty for the underlying
    success, symbol_data, _ = get_symbol_info(strategy.underlying, strategy.exchange)
    freeze_qty = symbol_data['data'].get('freeze_qty', 0) if success else 0

    # Build multiorder request — pass splitsize per leg
    multiorder_data = {
        'underlying': strategy.underlying,
        'exchange': strategy.exchange,
        'strategy': strategy.name,
        'legs': []
    }

    for leg in legs_config['legs']:
        leg_data = {
            'offset': f"{leg['strike_selection']}{leg.get('strike_offset', '')}",  # e.g. "OTM4"
            'option_type': leg['option_type'],
            'action': leg['action'],
            'quantity': leg['lots'] * lot_size,
            'product': leg.get('product_type', 'NRML'),
            'pricetype': 'MARKET',
            'splitsize': freeze_qty if freeze_qty > 0 else 0,  # Auto-split per leg
        }
        multiorder_data['legs'].append(leg_data)

    return place_options_multiorder(
        multiorder_data, auth_token=auth_token, broker=broker
    )
```

#### Single-Leg Option (via `place_options_order`)

For single-leg option strategies (webhook-triggered), use `place_options_order`:

```python
from services.place_options_order_service import place_options_order

options_data = {
    'underlying': underlying,
    'exchange': exchange,
    'offset': 'ATM',
    'option_type': 'CE',
    'action': 'BUY',
    'quantity': total_qty,
    'product': 'NRML',
    'pricetype': 'MARKET',
    'splitsize': freeze_qty,  # Auto-split if qty > freeze_qty
}
place_options_order(options_data, auth_token=auth_token, broker=broker)
```

#### Equity / Futures (via `place_order` or `split_order`)

For non-options instruments, route manually:

```python
from services.place_order_service import place_order
from services.split_order_service import split_order
from services.symbol_service import get_symbol_info

def place_strategy_equity_order(symbol, exchange, action, quantity, product,
                                strategy_name, pricetype='MARKET',
                                auth_token=None, broker=None):
    """
    Order placement for equity/futures.
    Routes to place_order or split_order based on freeze_qty.
    """
    success, symbol_data, _ = get_symbol_info(symbol, exchange)
    freeze_qty = symbol_data['data'].get('freeze_qty', 0) if success else 0

    if freeze_qty > 0 and quantity > freeze_qty:
        split_data = {
            'strategy': strategy_name,
            'exchange': exchange,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'splitsize': freeze_qty,
            'pricetype': pricetype,
            'product': product,
        }
        return split_order(split_data, auth_token=auth_token, broker=broker)
    else:
        order_data = {
            'strategy': strategy_name,
            'exchange': exchange,
            'symbol': symbol,
            'action': action,
            'quantity': quantity,
            'pricetype': pricetype,
            'product': product,
        }
        return place_order(order_data, auth_token=auth_token, broker=broker)
```

#### Exit Orders (Risk Engine)

When the risk engine triggers exits (SL/TGT/TSL/CB), the same routing applies:
- **Options positions**: Use `place_options_order` with `splitsize = freeze_qty` for single exits, or `place_options_multiorder` for group exits
- **Equity/Futures positions**: Use `place_order` / `split_order` routing

**This routing applies to ALL strategy order placements:**
- Strategy Builder leg execution (§23.4) → `place_options_multiorder`
- Webhook-triggered option entries (§16) → `place_options_order` or `place_options_multiorder`
- Webhook-triggered equity/futures entries (§16) → `place_order` / `split_order`
- Risk engine exit orders — SL/TGT/TSL triggers (§8) → `place_options_order` (options) or `place_order`/`split_order` (equity/futures)
- Manual position close → same routing by instrument type
- Circuit breaker `close_all_positions` mode (§20.4.1) → same routing
- Position group close (§27.4) → `place_options_multiorder` for options groups

### 23.7 Strike Selection Types

The Strategy Builder supports 5 strike selection methods (matching AlgoMirror's capabilities):

| Type | `strike_selection` value | Additional fields | Resolution |
|------|-------------------------|-------------------|------------|
| **ATM** | `ATM` | — | `round(spot_price / strike_step) * strike_step` |
| **ITM** (1-20) | `ITM` | `strike_offset`: 1-20 | CE: `ATM - (offset × strike_step)` / PE: `ATM + (offset × strike_step)` |
| **OTM** (1-20) | `OTM` | `strike_offset`: 1-20 | CE: `ATM + (offset × strike_step)` / PE: `ATM - (offset × strike_step)` |
| **Specific Strike** | `strike_price` | `strike_price`: float | User-entered strike used directly |
| **Premium Near** | `premium_near` | `premium_value`: float | Search ±20 strikes for closest premium match to target |

**ITM/OTM direction logic:**
- **Call (CE)**: ITM = below spot (lower strikes), OTM = above spot (higher strikes)
- **Put (PE)**: ITM = above spot (higher strikes), OTM = below spot (lower strikes)

**Strike step sizes** (derived from the symbol database, not hardcoded):

| Underlying | Strike Step | Exchange |
|-----------|------------|---------|
| NIFTY | 50 | NFO |
| BANKNIFTY | 100 | NFO |
| FINNIFTY | 50 | NFO |
| MIDCPNIFTY | 25 | NFO |
| SENSEX | 100 | BFO |
| BANKEX | 100 | BFO |
| Stock options | Varies per stock | NFO/BFO |
| USDINR | 0.25 | CDS/BCD |
| CRUDEOIL | 50 | MCX |
| GOLD | 100 | MCX |
| SILVER | 500 | MCX |
| NATURALGAS | 5 | MCX |

> **Note:** Strike steps should be derived dynamically from the `SymToken` database (consecutive strikes for the same underlying), not hardcoded, to handle future changes and all underlyings automatically.

**Premium Near resolution algorithm:**
1. Get spot price → compute ATM strike
2. Scan strikes in range ATM ± (20 × strike_step)
3. For each strike, fetch LTP via `get_quotes(option_symbol, exchange)`
4. Find strike whose premium is closest to user's `premium_value`
5. Prefer strikes with premium ≤ target (avoid overpaying)
6. Return the matched strike

**`legs_config` storage for each strike type:**

```json
// ATM
{ "strike_selection": "ATM", "strike_offset": 0, "strike_price": null, "premium_value": null }

// OTM 5
{ "strike_selection": "OTM", "strike_offset": 5, "strike_price": null, "premium_value": null }

// ITM 3
{ "strike_selection": "ITM", "strike_offset": 3, "strike_price": null, "premium_value": null }

// Specific strike
{ "strike_selection": "strike_price", "strike_offset": 0, "strike_price": 25000.0, "premium_value": null }

// Premium near ₹150
{ "strike_selection": "premium_near", "strike_offset": 0, "strike_price": null, "premium_value": 150.0 }
```

**UI behavior per selection type:**
- **ATM**: Strike value field shows auto-resolved value (read-only)
- **ITM/OTM**: Offset dropdown (1-20), strike value auto-resolved (read-only)
- **Specific Strike**: Strike value input field (enabled, user types exact strike)
- **Premium Near**: Premium value input field (enabled, user types target premium in ₹)

### 23.8 Supported Exchanges

The Strategy Builder works across ALL futures and options exchanges supported by OpenAlgo:

| Exchange | Code | Instrument Types | Underlyings |
|----------|------|-----------------|-------------|
| NSE F&O | `NFO` | Index options, stock options, index futures, stock futures | NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, stock underlyings |
| BSE F&O | `BFO` | Index options, stock options, index futures, stock futures | SENSEX, BANKEX, SENSEX50, stock underlyings |
| NSE Currency | `CDS` | Currency futures, currency options | USDINR, EURINR, GBPINR, JPYINR |
| BSE Currency | `BCD` | Currency futures, currency options | USDINR, EURINR, GBPINR, JPYINR |
| MCX | `MCX` | Commodity futures, commodity options | CRUDEOIL, GOLD, SILVER, NATURALGAS, COPPER, etc. |

**Exchange-specific handling:**
- **Quote exchange resolution**: Index underlyings (NIFTY, BANKNIFTY, SENSEX, etc.) use `NSE_INDEX`/`BSE_INDEX` for quotes; stock/commodity underlyings use `NSE`/`BSE`/`MCX` — resolved via `_get_quote_exchange()` pattern
- **Expiry types**: Weekly expiry available for index options (NFO/BFO); monthly only for CDS/BCD/MCX
- **Lot sizes**: Vary by exchange and underlying — fetched from `symbol_service.get_symbol_info()`
- **Freeze quantities**: Exchange-specific — fetched from `qty_freeze` DB
- **Product types**: `NRML` (carry forward) and `MIS` (intraday) for all exchanges

**Builder exchange selector:**
```
Exchange: [NFO ▼]  ← dropdown with all 5 exchanges
```

When exchange changes:
1. Reset underlying to first available for that exchange
2. Fetch underlyings via `/search/api/underlyings?exchange=<selected>`
3. Update expiry type options (weekly available only for NFO/BFO index options)
4. Re-fetch lot size and strike step for new underlying

---

## 24. Pre-built Strategy Templates

### 24.1 Overview

A template system (`/strategy/templates`) providing ready-to-deploy F&O strategy configurations. Traders browse templates by category, customize parameters, and deploy as new strategies.

### 24.2 Database Schema

See Section 5.9 for `strategy_template` table schema.

### 24.3 System Templates (Pre-loaded)

These 5 templates are auto-created on first application run:

| Template | Category | Preset | Legs | Risk Mode | Default Risk |
|----------|----------|--------|------|-----------|-------------|
| ATM Straddle | neutral | `straddle` | SELL ATM CE + SELL ATM PE | combined | SL: 50% of premium |
| OTM Strangle | neutral | `strangle` | SELL OTM2 CE + SELL OTM2 PE | combined | SL: 50% of premium |
| Iron Condor | neutral | `iron_condor` | SELL OTM4 CE/PE + BUY OTM6 CE/PE | combined | SL: max spread width |
| Bull Call Spread | bullish | `bull_call_spread` | BUY ATM CE + SELL OTM2 CE | combined | SL: 50% of debit |
| Bear Put Spread | bearish | `bear_put_spread` | BUY ATM PE + SELL OTM2 PE | combined | SL: 50% of debit |

### 24.4 API Endpoints

See Section 15.11 for endpoint details.

### 24.5 Deploy Flow

1. User browses templates → selects one → detail panel opens
2. Template legs visualized with default configuration
3. User customizes:
   - Strategy name (pre-filled from template name)
   - Underlying (default from template, changeable)
   - Exchange (NFO/BFO)
   - Expiry type
   - Quantity (lots per leg)
   - Risk parameters (editable, pre-filled from template defaults)
4. Click "Deploy" → `POST /strategy/api/templates/<id>/deploy`
5. Backend creates new Strategy + SymbolMapping with customized config
6. Redirect to Strategy Hub with new strategy card auto-expanded

---

## 25. Risk Monitor & Threshold Visualization

### 25.1 Overview

A dedicated Risk Monitor tab (6th tab in StrategyCard) providing consolidated risk visibility with progress bars, distance metrics, and a risk events audit log. Data comes from Zustand store (already populated by SocketIO), so there is zero loading delay.

### 25.2 Risk Threshold Progress Bars

Visual progress bars showing proximity to each configured threshold:

| Threshold | Bar Color | Fill Direction | Formula |
|-----------|-----------|---------------|---------|
| Stoploss | Red gradient | Left to right | `abs(unrealized_pnl) / abs(sl_distance) × 100` |
| Target | Green gradient | Left to right | `unrealized_pnl / tgt_distance × 100` |
| Trailing Stop | Amber gradient | Left to right | `abs(ltp - trailstop_price) / abs(peak_price - trailstop_price) × 100` |
| Daily SL | Red gradient | Left to right | `abs(daily_pnl) / abs(daily_sl_value) × 100` |
| Daily Target | Green gradient | Left to right | `daily_pnl / daily_tgt_value × 100` |

**Color transitions:**
- 0-50%: green (safe zone)
- 50-80%: amber (warning zone)
- 80-100%: red (danger zone)

**"HIT!" indicator:** When threshold is triggered, bar shows full red fill with pulsing "HIT!" badge overlay using `animate-pulse`.

### 25.3 Layout

```
+---------------------------------------------------------------+
| RISK MONITOR                              [WS: Connected ●]    |
+---------------------------------------------------------------+
|                                                                 |
| Per-Position Thresholds                                         |
| +-----------------------------------------------------------+ |
| | NIFTY..4000CE  SL:[████████░░] 80%  TGT:[███░░░░░] 35%    | |
| | NIFTY..4000PE  SL:[████░░░░░░] 40%  TGT:[██░░░░░░] 22%    | |
| +-----------------------------------------------------------+ |
|                                                                 |
| Combined Group Thresholds                                       |
| +-----------------------------------------------------------+ |
| | Iron Condor    SL:[██████░░░░] 62%  TGT:[████░░░░] 45%    | |
| |                TSL:[███████░░░] 72% (peak: ₹4,200)         | |
| +-----------------------------------------------------------+ |
|                                                                 |
| Daily Circuit Breaker                                           |
| +-----------------------------------------------------------+ |
| | Daily SL: [████████████░░] 85%  (-₹4,250 / -₹5,000)       | |
| | Daily TGT: [██░░░░░░░░░░░░] 18% (+₹1,800 / +₹10,000)     | |
| +-----------------------------------------------------------+ |
|                                                                 |
| Risk Events                                                    |
| +-----------------------------------------------------------+ |
| | 14:35 [!] NIFTY..CE SL distance < 5% — DANGER ZONE        | |
| | 14:32 [i] Trail stop moved: ₹240 → ₹245                   | |
| | 14:28 [i] Breakeven activated for NIFTY..PE                | |
| | 14:15 [✓] All legs filled — combined monitoring active     | |
| +-----------------------------------------------------------+ |
+---------------------------------------------------------------+
```

### 25.4 Risk Events Log

Scrollable audit log within the Risk Monitor tab:
- Timestamp (IST, `font-mono`)
- Severity icon: info (blue circle), warning (amber triangle), critical (red octagon)
- Event message text
- Newest at top (reverse chronological)
- Max 20 events displayed, with "Load more" pagination
- WebSocket connection status badge in header

Data source: Zustand `riskEvents` Map, populated by `strategy_risk_event` SocketIO events.

### 25.5 API Endpoint

See Section 15.14 for risk events endpoint.

---

## 26. Leg-Level Distance Metrics

### 26.1 Overview

Three new columns in the position table showing real-time distance from current LTP to each risk threshold. These are computed client-side from position data already in Zustand store.

### 26.2 Column Definitions

| Column | Computation | Display Format |
|--------|-------------|----------------|
| SL Dist | `abs(ltp - stoploss_price)` | `12.5 pts (1.5%)` |
| TGT Dist | `abs(target_price - ltp)` | `28.0 pts (3.4%)` |
| TSL Dist | `abs(ltp - trailstop_price)` | `8.2 pts (1.0%)` |

### 26.3 Color Coding

| Zone | Percentage Range | Color | Animation |
|------|-----------------|-------|-----------|
| Safe | >10% | `text-muted-foreground` | None |
| Warning | 5-10% | `text-amber-500` | None |
| Danger | <5% | `text-destructive font-bold` | `animate-pulse` |

### 26.4 Direction-Aware Computation

```typescript
function computeDistanceMetrics(position: DashboardPosition): DistanceMetrics {
  const { ltp, stoploss_price, target_price, trailstop_price, action } = position
  const isLong = action === 'BUY'

  const compute = (ref: number | null, favorable: boolean) => {
    if (!ref || ref === 0 || ltp === 0) return { points: null, pct: null }
    const dist = favorable
      ? (isLong ? ref - ltp : ltp - ref)
      : (isLong ? ltp - ref : ref - ltp)
    return { points: Math.abs(dist), pct: (Math.abs(dist) / ltp) * 100 }
  }

  return {
    sl: compute(stoploss_price, false),   // SL is unfavorable direction
    tgt: compute(target_price, true),      // TGT is favorable direction
    tsl: compute(trailstop_price, false),  // TSL is unfavorable direction
  }
}

function getDistanceZone(pct: number | null): 'safe' | 'warning' | 'danger' {
  if (pct === null) return 'safe'
  if (pct > 10) return 'safe'
  if (pct >= 5) return 'warning'
  return 'danger'
}
```

---

## 27. Position Group Visualization

### 27.1 Overview

Positions with the same `position_group_id` (combined P&L mode) are visually grouped as bordered cards wrapping the individual leg rows. This makes multi-leg strategies (Iron Condor, Straddle, etc.) immediately recognizable.

### 27.2 Group Card Layout

```
+---------------------------------------------------------------+
| COMBINED GROUP: Iron Condor (4 legs)          [Close Group]    |
| Status: [Active]  Combined P&L: -₹2,500                       |
| Max Loss: [==========----] 50%  Trail Stop: ₹1,560            |
+---------------------------------------------------------------+
| Sym            | Action | Qty | Avg     | LTP   | P&L         |
|----------------|--------|-----|---------|-------|-------------|
| NIFTY..4000CE  | SELL   | 65  | ₹260   | ₹245  | +₹975       |
| NIFTY..4000PE  | SELL   | 65  | ₹195   | ₹180  | +₹975       |
| NIFTY..4200CE  | BUY    | 65  | ₹110   | ₹95   | -₹975       |
| NIFTY..4200PE  | BUY    | 65  | ₹78    | ₹68   | -₹650       |
+---------------------------------------------------------------+
```

### 27.3 Group Header Elements

- **Left border**: 2px colored by status
  - Green: active
  - Amber: exiting
  - Red: failed_exit
  - Gray: closed
- **Group name**: Derived from preset ("Iron Condor") or "Combined Group"
- **Leg count badge**: "(4 legs)"
- **Combined P&L**: Large font, color-coded (green positive, red negative)
- **Compact progress bars**: SL/TGT/TSL (inline, small)
- **Close Group button**: Closes all legs in the group
- **Expand/collapse chevron**: Toggle individual leg visibility

### 27.4 API Endpoint

See Section 15.15 for position group close endpoint.

### 27.5 Rendering Order

In PositionTable:
1. Grouped positions render first (one PositionGroup per group_id)
2. Ungrouped positions render after as individual PositionRow components
3. Within a group, legs ordered by leg_id

---

## 28. Market Hours Intelligence

### 28.1 Overview

Market status indicator badge in the DashboardHeader showing current market phase. Enables auto-pause of risk monitoring outside trading hours to avoid false triggers on stale data.

### 28.2 Market Phases

| Phase | Color | Icon | Description |
|-------|-------|------|-------------|
| `market_open` | Green | Pulsing dot | Trading session active (09:15-15:30 IST) |
| `pre_market` | Amber | Clock | Before market open (09:00-09:15 IST) |
| `post_market` | Amber | Clock | After market close (15:30-16:00 IST) |
| `market_closed` | Gray | Moon | Outside all sessions |
| `holiday` | Red | Calendar | Exchange holiday (name displayed) |

### 28.3 Backend Service

Uses existing `market_calendar_service.get_timings()` to determine current phase:

```python
class MarketStatusService:
    _cache = None
    _cache_time = None
    CACHE_TTL = 60  # seconds

    @classmethod
    def get_status(cls):
        if cls._cache and (time.time() - cls._cache_time) < cls.CACHE_TTL:
            return cls._cache

        timings = market_calendar_service.get_timings()
        now = datetime.now(IST)
        phase = cls._determine_phase(now, timings)

        cls._cache = {
            'phase': phase,
            'exchange': 'NSE',
            'session_start': '09:15',
            'session_end': '15:30',
            'next_event': cls._next_event(now, timings),
            'is_holiday': timings.get('is_holiday', False),
            'holiday_name': timings.get('holiday_name')
        }
        cls._cache_time = time.time()
        return cls._cache
```

### 28.4 Auto-Behavior

| Phase | Risk Engine | WebSocket | Webhooks |
|-------|------------|-----------|----------|
| `market_open` | Active | Full subscriptions | Accepted |
| `pre_market` | Standby | Reduced | Queued |
| `post_market` | Winding down | Active (for settlement) | Rejected |
| `market_closed` | Paused | Disconnected | Rejected |
| `holiday` | Paused | Disconnected | Rejected |

### 28.5 API Endpoint

See Section 15.13 for market status endpoint.

---

## 29. Strategy Cloning

### 29.1 Overview

One-click duplication of a strategy with all its configuration, symbol mappings, and risk parameters. Useful for running the same strategy with different parameters or on different underlyings.

### 29.2 API Endpoint

See Section 15.12 for clone endpoint.

### 29.3 Clone Behavior

1. Copies strategy record with name appended " (Copy)"
2. Copies all symbol mappings (including `legs_config`, risk params)
3. Copies daily circuit breaker config
4. Does **NOT** copy: positions, orders, trades, P&L history
5. New strategy starts in 'paused' risk monitoring state
6. Generates new webhook URL (unique webhook_id)
7. `is_active` set to True, but risk monitoring starts paused

### 29.4 Backend Implementation

```python
def clone_strategy(strategy_id, user_id):
    original = Strategy.query.get(strategy_id)
    if not original or original.user_id != user_id:
        return {'status': 'error', 'message': 'Strategy not found'}

    # Clone strategy record
    new_strategy = Strategy(
        name=f"{original.name} (Copy)",
        user_id=user_id,
        platform=original.platform,
        webhook_id=generate_webhook_id(),
        is_active=True,
        risk_enabled=False,  # Start paused
        # ... copy all config fields
        daily_cb_behavior=original.daily_cb_behavior,
    )
    db.session.add(new_strategy)
    db.session.flush()  # Get new_strategy.id

    # Clone symbol mappings
    for mapping in original.symbol_mappings:
        new_mapping = SymbolMapping(
            strategy_id=new_strategy.id,
            # ... copy all fields
        )
        db.session.add(new_mapping)

    db.session.commit()
    return {
        'status': 'success',
        'new_strategy_id': new_strategy.id,
        'new_name': new_strategy.name
    }
```

### 29.5 UI Integration

- Clone button in OverviewTab manage actions section
- Confirmation dialog: "Clone '{Strategy Name}'? This will create a new strategy with the same configuration."
- On success: Dashboard refetch, auto-expand new strategy card
- Toast notification: "Strategy cloned successfully"

---

## 30. Per-Leg P&L Breakdown

### 30.1 Overview

Enhanced trades and P&L panels showing P&L breakdown by individual legs for multi-leg strategies. Helps traders identify which legs are contributing to profits vs losses.

### 30.2 Trades Panel Enhancement

For multi-leg strategies, the TradesPanel groups trades by `position_group_id`:

```
+---------------------------------------------------------------+
| Iron Condor Entry — 14:32 IST                                  |
|---------------------------------------------------------------|
| Leg | Symbol          | Action | Qty | Price  | P&L           |
|-----|----------------|--------|-----|--------|---------------|
| 1   | NIFTY..4000CE  | SELL   | 65  | ₹260   | +₹975         |
| 2   | NIFTY..4000PE  | SELL   | 65  | ₹195   | +₹975         |
| 3   | NIFTY..4200CE  | BUY    | 65  | ₹110   | -₹975         |
| 4   | NIFTY..4200PE  | BUY    | 65  | ₹78    | -₹650         |
|                                       Combined: +₹325         |
+---------------------------------------------------------------+
```

### 30.3 P&L Panel Enhancement

The P&L endpoint response includes a `leg_breakdown` field:

```json
{
    "leg_breakdown": [
        {"symbol": "NIFTY24FEB25000CE", "action": "SELL", "total_pnl": 4200, "trade_count": 8},
        {"symbol": "NIFTY24FEB25000PE", "action": "SELL", "total_pnl": 3100, "trade_count": 8},
        {"symbol": "NIFTY24FEB25200CE", "action": "BUY", "total_pnl": -2800, "trade_count": 8},
        {"symbol": "NIFTY24FEB25200PE", "action": "BUY", "total_pnl": -1200, "trade_count": 8}
    ]
}
```

### 30.4 Visualization

Per-leg P&L shown as:
- Horizontal stacked bar chart (green for profitable legs, red for losing legs)
- Each bar labeled with symbol + action + P&L amount
- Combined total shown below the chart
- Sortable by P&L (ascending/descending)

---

## 31. Risk Evaluation Logic (AlgoMirror-Matching)

This section specifies the exact risk evaluation formulas and algorithms, matching AlgoMirror's implementation. The risk engine in OpenAlgo's V1 PRD (§10.2) provides the architectural framework; this section fills in the precise math.

### 31.1 Combined Premium (Net Premium) Calculation

For multi-leg strategies in combined P&L mode, the **net premium** is the capital-at-risk base for all percentage-based risk calculations.

```python
def calculate_combined_premium(positions):
    """
    Calculate net premium for a position group.

    BUY legs = debit (money paid)
    SELL legs = credit (money received)
    entry_value = abs(net_premium) = capital at risk
    """
    net_premium = 0.0

    for position in positions:
        premium = position.average_entry_price * position.quantity

        if position.action == 'BUY':
            net_premium += premium    # Debit (cost paid)
        else:  # SELL
            net_premium -= premium    # Credit (money received)

    entry_value = abs(net_premium)    # Always positive
    return net_premium, entry_value
```

**Examples:**

| Strategy | Legs | Net Premium | Entry Value |
|----------|------|-------------|-------------|
| Short Straddle | SELL CE @150×75 + SELL PE @120×75 | -11,250 + -9,000 = -20,250 | 20,250 |
| Bull Call Spread | BUY CE @200×75 + SELL CE @150×75 | +15,000 + -11,250 = +3,750 | 3,750 |
| Iron Condor | SELL OTM CE/PE + BUY OTM CE/PE | Depends on premiums | abs(net) |

**Semantics:**
- `net_premium > 0` → Net Debit strategy (trader paid money)
- `net_premium < 0` → Net Credit strategy (trader received money)
- `entry_value` is ALWAYS positive and used as the base for percentage calculations

### 31.2 Leg-Level Stoploss (Price-Based)

Leg-level stoploss is evaluated against the **option/futures LTP** (price-based), NOT against P&L.

**Value types:**

| Type | `stoploss_type` | SL Price Calculation (BUY leg) | SL Price Calculation (SELL leg) |
|------|-----------------|-------------------------------|--------------------------------|
| Percentage | `percentage` | `entry_price × (1 - sl_value/100)` | `entry_price × (1 + sl_value/100)` |
| Points | `points` | `entry_price - sl_value` | `entry_price + sl_value` |
| Premium (absolute) | `premium` | `sl_value` (direct price) | `sl_value` (direct price) |

**Trigger logic:**
```python
if action == 'BUY':
    sl_hit = ltp <= sl_price      # Price drops to/below SL
elif action == 'SELL':
    sl_hit = ltp >= sl_price      # Price rises to/above SL
```

**Example (SELL CE leg):**
- Entry: ₹150, SL type: percentage, SL value: 30
- SL price = 150 × (1 + 30/100) = ₹195
- Triggered when LTP ≥ ₹195

### 31.3 Leg-Level Target (Price-Based)

Same structure as stoploss but in the favorable direction.

| Type | `target_type` | Target Price (BUY leg) | Target Price (SELL leg) |
|------|--------------|----------------------|------------------------|
| Percentage | `percentage` | `entry_price × (1 + tgt_value/100)` | `entry_price × (1 - tgt_value/100)` |
| Points | `points` | `entry_price + tgt_value` | `entry_price - tgt_value` |
| Premium (absolute) | `premium` | `tgt_value` (direct price) | `tgt_value` (direct price) |

**Trigger logic:**
```python
if action == 'BUY':
    tgt_hit = ltp >= target_price   # Price rises to/above target
elif action == 'SELL':
    tgt_hit = ltp <= target_price   # Price drops to/below target
```

### 31.4 Leg-Level Trailing Stop (Price-Based)

Trails the LTP when the position is profitable. The trailing stop only moves in the favorable direction (ratchets).

**Value types:** `percentage`, `points`

```python
def update_leg_trailing_stop(position, ltp):
    """
    Price-based trailing stop per leg.
    Only activates when position is profitable.
    Ratchets: stop only moves in favorable direction.
    """
    current_pnl = calculate_leg_pnl(position, ltp)

    # Only trail when profitable
    if current_pnl <= 0:
        return

    leg = position.leg_config

    if leg['trailing_type'] == 'percentage':
        if position.action == 'BUY':
            new_stop = ltp * (1 - leg['trailing_value'] / 100)
        else:  # SELL
            new_stop = ltp * (1 + leg['trailing_value'] / 100)
    elif leg['trailing_type'] == 'points':
        if position.action == 'BUY':
            new_stop = ltp - leg['trailing_value']
        else:  # SELL
            new_stop = ltp + leg['trailing_value']

    # Ratchet: only move stop in favorable direction
    if position.action == 'BUY':
        # BUY: stop ratchets UP (higher = more favorable)
        if position.trailstop_price is None or new_stop > position.trailstop_price:
            position.trailstop_price = round_to_tick(new_stop, position.tick_size)
    else:  # SELL
        # SELL: stop ratchets DOWN (lower = more favorable)
        if position.trailstop_price is None or new_stop < position.trailstop_price:
            position.trailstop_price = round_to_tick(new_stop, position.tick_size)
```

**Trigger:** Same as SL trigger — `ltp <= trailstop_price` (BUY) or `ltp >= trailstop_price` (SELL).

### 31.5 Combined / Strategy-Level Max Loss (P&L-Based)

For combined-mode multi-leg strategies, max loss is evaluated against **combined P&L** across all legs (not individual prices).

**Value types:** `percentage`, `points`, `amount`

```python
def check_combined_max_loss(group, positions, config):
    """
    Combined max loss check.
    Percentage is relative to entry_value (combined premium).
    """
    combined_pnl = sum(p.unrealized_pnl for p in positions)
    _, entry_value = calculate_combined_premium(positions)

    if config['stoploss_type'] == 'percentage':
        sl_threshold = entry_value * (config['stoploss_value'] / 100)
    elif config['stoploss_type'] == 'points':
        sl_threshold = config['stoploss_value']
    elif config['stoploss_type'] == 'amount':
        sl_threshold = config['stoploss_value']

    # Loss threshold is negative
    if combined_pnl <= -abs(sl_threshold):
        return True, 'combined_sl'
    return False, None
```

### 31.6 Combined / Strategy-Level Max Profit (P&L-Based)

```python
def check_combined_max_profit(group, positions, config):
    combined_pnl = sum(p.unrealized_pnl for p in positions)
    _, entry_value = calculate_combined_premium(positions)

    if config['target_type'] == 'percentage':
        tgt_threshold = entry_value * (config['target_value'] / 100)
    elif config['target_type'] == 'points':
        tgt_threshold = config['target_value']
    elif config['target_type'] == 'amount':
        tgt_threshold = config['target_value']

    if combined_pnl >= abs(tgt_threshold):
        return True, 'combined_target'
    return False, None
```

### 31.7 Combined Trailing Stop (AFL-Style Ratcheting, P&L-Based)

The most critical risk mechanism for multi-leg strategies. This is a **P&L-based** trailing stop (not price-based), evaluated against the combined P&L of all legs.

**Value types:** `percentage`, `points`, `amount`

**Database fields on position group:**
- `entry_value`: abs(net premium) — base for percentage
- `initial_stop`: first stop level (negative number)
- `combined_peak_pnl`: highest combined P&L achieved (starts at 0)
- `current_stop`: current trailing stop level (ratchets up only)

```python
def check_combined_trailing_stop(group, positions, config):
    """
    AFL-style trailing stop for combined P&L.

    Algorithm:
    1. Calculate initial_stop from entry_value (always negative)
    2. Track peak_pnl (highest combined P&L ever)
    3. current_stop = initial_stop + peak_pnl (shifts up as peak rises)
    4. Ratchet: current_stop can only increase, never decrease
    5. Trigger: combined_pnl <= current_stop

    The stop is ALWAYS ACTIVE from entry (no waiting state).
    """
    combined_pnl = sum(p.unrealized_pnl for p in positions)
    _, entry_value = calculate_combined_premium(positions)

    # Near-zero safety guard (likely stale data)
    if abs(combined_pnl) < 1.0 and len(positions) > 0:
        return False, None

    # Step 1: Calculate initial stop
    trailing_type = config['trailstop_type']
    trailing_value = config['trailstop_value']

    if trailing_type == 'percentage':
        initial_stop = -(entry_value * (trailing_value / 100))
    elif trailing_type == 'points':
        initial_stop = -trailing_value
    elif trailing_type == 'amount':
        initial_stop = -trailing_value

    # Step 2: Initialize or recalculate if legs changed
    if group.initial_stop is None or abs(group.initial_stop - initial_stop) > 0.01:
        group.initial_stop = initial_stop
        group.entry_value = entry_value

    # Step 3: Track peak P&L
    current_peak = group.combined_peak_pnl or 0.0
    if combined_pnl > current_peak:
        group.combined_peak_pnl = combined_pnl
        current_peak = combined_pnl

    # Step 4: Calculate and ratchet stop
    new_stop = group.initial_stop + current_peak
    previous_stop = group.current_stop or group.initial_stop
    current_stop = max(new_stop, previous_stop)  # Ratchet up only
    group.current_stop = current_stop

    # Step 5: Check trigger
    if combined_pnl <= current_stop:
        return True, 'combined_tsl'
    return False, None
```

**Worked example (Short Straddle):**

```
Entry: SELL CE @150×75 + SELL PE @120×75
net_premium = -20,250 (credit)
entry_value = 20,250

Config: trailing_type='percentage', trailing_value=25%
initial_stop = -(20,250 × 0.25) = -5,062.50

Timeline:
  t1: combined_pnl = +2,000  → peak=2,000  → stop = -5,062 + 2,000 = -3,062
  t2: combined_pnl = +4,500  → peak=4,500  → stop = -5,062 + 4,500 = -562
  t3: combined_pnl = +3,000  → peak=4,500  → stop = max(-562, -562) = -562 (ratcheted)
  t4: combined_pnl = -600    → -600 <= -562 → TRIGGERED! Exit all legs.
```

### 31.8 Risk Stats Display

The Strategy Builder and Dashboard show real-time risk management stats per strategy:

**Per-Leg Stats (in PositionRow and LegCard):**

| Stat | Display | Source |
|------|---------|--------|
| Entry Price | `₹150.00` | `position.average_entry_price` |
| LTP | `₹142.50` | Live (WebSocket/Zustand) |
| Leg P&L | `+₹562` (green) / `-₹375` (red) | `(entry - ltp) × qty` for SELL, `(ltp - entry) × qty` for BUY |
| SL Price | `₹195.00` | Computed from entry + config |
| SL Distance | `52.5 pts (36.8%)` | `abs(ltp - sl_price)` |
| Target Price | `₹105.00` | Computed from entry + config |
| TGT Distance | `37.5 pts (26.3%)` | `abs(ltp - target_price)` |
| TSL Price | `₹148.20` | Ratcheted trailing stop |
| TSL Distance | `5.7 pts (4.0%)` | `abs(ltp - tsl_price)` |
| SL Hit | Red "SL" badge | `position.exit_detail == 'leg_sl'` |
| TGT Hit | Green "TGT" badge | `position.exit_detail == 'leg_target'` |
| TSL Hit | Amber "TSL" badge | `position.exit_detail == 'leg_tsl'` |

**Combined Group Stats (in PositionGroupHeader):**

| Stat | Display | Source |
|------|---------|--------|
| Net Premium | `₹20,250 CR` / `₹3,750 DR` | Combined premium formula |
| Combined P&L | `+₹2,450` / `-₹1,200` | Sum of all leg P&Ls |
| Max Loss Threshold | `-₹5,062 (25%)` | From config |
| Max Profit Target | `+₹10,125 (50%)` | From config |
| TSL Current Stop | `-₹562` | Ratcheted value |
| TSL Peak P&L | `₹4,500` | Highest combined P&L |
| SL Progress | `[████████░░] 80%` | `abs(combined_pnl) / abs(sl_threshold) × 100` |
| TGT Progress | `[███░░░░░░░] 30%` | `combined_pnl / tgt_threshold × 100` |
| Exit Reason | "C-SL" / "C-TGT" / "C-TSL" badge | `group.exit_reason` |

**Strategy-Level Summary (in StrategyCard header):**

| Stat | Display |
|------|---------|
| Active Positions | `4 legs active` |
| Total Strategy P&L | `+₹2,450` (color-coded) |
| Risk Status | "Monitoring" (blue) / "SL Hit" (red) / "TGT Hit" (green) |
| Daily P&L | `+₹8,200 / ₹10,000 target` |

### 31.9 Value Types Summary

| Context | Available Types | Notes |
|---------|----------------|-------|
| Leg-Level SL | `percentage`, `points`, `premium` | `premium` = absolute price level |
| Leg-Level Target | `percentage`, `points`, `premium` | `premium` = absolute price level |
| Leg-Level Trailing | `percentage`, `points` | Price-based ratcheting |
| Combined SL | `percentage`, `points`, `amount` | `percentage` relative to `entry_value` |
| Combined Target | `percentage`, `points`, `amount` | `percentage` relative to `entry_value` |
| Combined TSL | `percentage`, `points`, `amount` | P&L-based AFL ratcheting |
| Daily SL | `percentage`, `points` | Based on daily cumulative P&L |
| Daily Target | `percentage`, `points` | Based on daily cumulative P&L |
| Daily TSL | `percentage`, `points` | Based on daily cumulative P&L |
| Leg Breakeven | `percentage`, `points` | One-time SL move to entry |

### 31.10 Breakeven Stoploss (OpenAlgo-Only Feature)

AlgoMirror does NOT implement breakeven stops. This is an OpenAlgo addition.

**Concept:** When a position reaches a configured profit threshold, the stoploss is automatically moved to the entry price — locking in a "no-loss" floor. This is a **one-time, irreversible** action per position.

**Availability:**
- Equity positions
- Single option positions
- Individual legs in `per_leg` risk mode
- **NOT** available in combined P&L mode (combined stops handle group-level risk)

**Value types:** `percentage`, `points`

**Database fields:**
```
breakeven_type        VARCHAR(10)    -- 'percentage' or 'points', NULL = disabled
breakeven_threshold   FLOAT          -- profit threshold to trigger BE move
breakeven_activated   BOOLEAN DEFAULT FALSE  -- one-time flag
```

**Threshold calculation:**

```python
def breakeven_threshold_hit(position, ltp):
    """
    Check if LTP has moved favorably enough to activate breakeven.
    Threshold is measured from entry price.
    """
    entry = position.average_entry_price

    if position.breakeven_type == 'percentage':
        threshold_distance = entry * (position.breakeven_threshold / 100)
    elif position.breakeven_type == 'points':
        threshold_distance = position.breakeven_threshold

    if position.action == 'BUY':
        # Long: price must rise above entry + threshold
        return ltp >= entry + threshold_distance
    else:  # SELL
        # Short: price must fall below entry - threshold
        return ltp <= entry - threshold_distance
```

**Activation logic:**

```python
# In the risk engine tick loop (after peak_price update, before trail recalc):

if position.breakeven_type and not position.breakeven_activated:
    if breakeven_threshold_hit(position, ltp):
        position.stoploss_price = round_to_tick(
            position.average_entry_price, position.tick_size
        )
        position.breakeven_activated = True
        # Emit SocketIO: strategy_breakeven_activated
```

**Breakeven + Trailing Stop Interaction:**

After breakeven activates, the trailing stop continues independently. The **effective stop** is always the most protective (closest to LTP):

```python
def compute_effective_stop(position):
    """
    When both breakeven SL and trailing stop are active,
    the tighter (more protective) stop wins.
    """
    stops = []

    if position.stoploss_price is not None:
        stops.append(position.stoploss_price)
    if position.trailstop_price is not None:
        stops.append(position.trailstop_price)

    if not stops:
        return None

    if position.action == 'BUY':
        return max(stops)    # Higher stop = more protective for longs
    else:  # SELL
        return min(stops)    # Lower stop = more protective for shorts
```

**Worked examples:**

```
Example 1: Long equity — entry ₹800, SL ₹784, breakeven_type='percentage', threshold=1.5

  Initial state: SL = ₹784
  BE triggers when: LTP >= 800 × (1 + 1.5/100) = ₹812

  t1: LTP = ₹805 → No breakeven (805 < 812), SL stays at ₹784
  t2: LTP = ₹813 → Breakeven triggered! SL moved to ₹800 (entry price)
  t3: LTP = ₹790 → LTP <= ₹800 → SL hit → exit at ₹790
      exit_reason = 'stoploss', exit_detail = 'breakeven_sl'
      Outcome: ₹790 - ₹800 = -₹10 loss (instead of -₹16 without BE)

Example 2: Short option — entry ₹150, SL ₹195, breakeven_type='points', threshold=20

  Initial state: SL = ₹195
  BE triggers when: LTP <= 150 - 20 = ₹130

  t1: LTP = ₹140 → No breakeven (140 > 130), SL stays at ₹195
  t2: LTP = ₹128 → Breakeven triggered! SL moved to ₹150 (entry price)
  t3: LTP = ₹135 → Trailing stop at ₹133 (if configured)
      Effective SL = min(₹150, ₹133) = ₹133 (trail is tighter for SELL)
  t4: LTP = ₹134 → LTP >= ₹133? No (134 >= 133 → YES) → TSL hit
      exit_reason = 'trailstop', exit_detail = 'leg_tsl'
      Outcome: ₹150 - ₹134 = +₹16/unit profit
```

**Key semantics:**
- Breakeven is a **one-time** SL move — once activated, it doesn't revert
- `breakeven_activated = True` is persisted and never set back to False
- The SL price after breakeven = entry price (not entry ± some offset)
- If trailing stop eventually moves past entry (more protective), the trail takes over via `compute_effective_stop()`
- `exit_detail = 'breakeven_sl'` when the SL that was moved to entry triggers (distinguishes from regular `leg_sl`)

**UI elements:**

| Context | Display |
|---------|---------|
| LegCard config | Breakeven toggle + type selector (percentage/points) + threshold input |
| PositionRow | Blue "BE" badge when `breakeven_activated = True`; `—` if not configured |
| Risk Events log | `[i] Breakeven activated for NIFTY..PE` |
| Exit badge | "BE-SL" (blue) when `exit_detail == 'breakeven_sl'` |
| Toast notification | `strategy_breakeven_activated` event |
| P&L breakdown | Separate "Breakeven SL" row in exit breakdown table |

---

## 32. Strategy Scheduling

### 32.1 Overview

Strategy scheduling enables automatic start/stop of risk monitoring and webhook acceptance based on configurable time windows and trading days. This matches the pattern used in OpenAlgo's `/python` strategy hosting system (see `blueprints/python_strategy.py`).

**Default schedule:** Monday–Friday, 09:15–15:30 IST (NSE regular session).

Scheduling is **mandatory** — every strategy has an active schedule. Users can modify times and days but cannot fully disable scheduling.

### 32.2 Database Fields

Added to `Strategy` and `ChartinkStrategy` tables:

```sql
schedule_enabled       BOOLEAN DEFAULT TRUE     -- always TRUE (mandatory)
schedule_start_time    VARCHAR(5) DEFAULT '09:15'  -- HH:MM IST
schedule_stop_time     VARCHAR(5) DEFAULT '15:30'  -- HH:MM IST
schedule_days          TEXT DEFAULT '["mon","tue","wed","thu","fri"]'  -- JSON array
schedule_auto_entry    BOOLEAN DEFAULT TRUE     -- accept webhooks during schedule
schedule_auto_exit     BOOLEAN DEFAULT TRUE     -- auto square-off at stop_time
```

### 32.3 Schedule Configuration

```python
# Config stored per strategy
{
    "schedule_start_time": "09:15",     # HH:MM IST
    "schedule_stop_time":  "15:30",     # HH:MM IST
    "schedule_days": ["mon", "tue", "wed", "thu", "fri"],  # Any combination
    "schedule_auto_entry": True,        # Accept webhook entries during window
    "schedule_auto_exit":  True         # Auto square-off at stop_time
}
```

**Valid days:** `mon`, `tue`, `wed`, `thu`, `fri`, `sat`, `sun`

Allowing `sat` and `sun` supports special exchange sessions (e.g., Muhurat trading, special Saturday sessions for MCX).

### 32.4 Schedule Lifecycle

```
Strategy Created
  │
  ├─ Default schedule: Mon-Fri, 09:15-15:30 IST
  │
  ▼
APScheduler CronTrigger Jobs (2 per strategy):
  │
  ├─ START job: CronTrigger(hour=9, minute=15, day_of_week='mon,tue,wed,thu,fri')
  │   └─ scheduled_start_strategy(strategy_id)
  │       ├─ Check: manually_stopped? → skip
  │       ├─ Check: today in schedule_days? → skip if not
  │       ├─ Check: market holiday (weekday only)? → skip, store paused_reason
  │       └─ All checks passed → activate risk engine + accept webhooks
  │
  └─ STOP job: CronTrigger(hour=15, minute=30, day_of_week='mon,tue,wed,thu,fri')
      └─ scheduled_stop_strategy(strategy_id)
          ├─ If schedule_auto_exit: square off all open positions (MIS)
          ├─ Pause risk engine monitoring
          └─ Reject new webhook entries
```

### 32.5 Scheduled Start Behavior

When the start job fires:

1. **Check manually_stopped flag** — if user manually stopped the strategy, skip auto-start. User must manually start to resume.
2. **Check schedule_days** — verify today is in the schedule. If not, skip.
3. **Check market holidays** — on weekdays, check holiday calendar. On weekends, trust the user's explicit day selection.
4. **Activate:**
   - Set `risk_monitoring = 'active'`
   - Risk engine subscribes to market data for all strategy positions
   - Webhooks for this strategy are accepted
   - Emit SocketIO: `strategy_schedule_started`

### 32.6 Scheduled Stop Behavior

When the stop job fires:

1. **Always fires** — safety measure to prevent strategies from running after hours
2. **Auto square-off** (if `schedule_auto_exit = True`):
   - Exit all open MIS positions via `placeorder` (MARKET)
   - `exit_reason = 'squareoff'`, `exit_detail = 'auto_squareoff_schedule'`
   - CNC and NRML positions are NOT auto-squared-off
3. **Pause risk engine** — unsubscribe from market data, stop monitoring
4. **Reject webhooks** — new entry signals return HTTP 403 with schedule info
5. Emit SocketIO: `strategy_schedule_stopped`

### 32.7 Manual Start/Stop Interaction

| Action | During Schedule | Outside Schedule |
|--------|----------------|------------------|
| Manual Start | Starts immediately | Arms for next scheduled window; returns "armed" status with next start time |
| Manual Stop | Stops immediately + sets `manually_stopped` flag | Sets `manually_stopped` flag |
| Manual Start after Manual Stop | Clears `manually_stopped`, starts if within window | Clears flag, arms for next window |

**Key rule:** Manual stop is permanent until manual start. The scheduler will NOT auto-start a manually stopped strategy. This matches `/python` behavior exactly.

### 32.8 Background Enforcement Jobs

Two global APScheduler jobs (matching `/python` pattern):

**1. Daily Trading Day Check** — runs at 00:01 IST:
```python
# Stops all scheduled strategies on non-trading days
# Prevents Friday strategies from running through the weekend
def daily_trading_day_check():
    for strategy in active_strategies:
        if not strategy.is_scheduled:
            continue
        if today not in strategy.schedule_days:
            continue
        if is_market_holiday() and today.weekday() < 5:
            stop_strategy_monitoring(strategy)
            strategy.paused_reason = 'holiday'
```

**2. Market Hours Enforcer** — runs every minute:
```python
# Resumes paused strategies when trading day starts
# Only enforces trading days (weekends/holidays), NOT specific hours
# The per-strategy CronTrigger handles hour-based start/stop
def market_hours_enforcer():
    if is_trading_day():
        for strategy in paused_strategies:
            if strategy.paused_reason in ('weekend', 'holiday'):
                if is_within_schedule_time(strategy):
                    resume_strategy_monitoring(strategy)
```

### 32.9 Strategy Status States

| Status | Meaning | Badge Color | Auto-Start? |
|--------|---------|-------------|-------------|
| `running` | Risk engine active, webhooks accepted | Green | N/A |
| `scheduled` | Armed, will auto-start at scheduled time | Blue | Yes |
| `manually_stopped` | User stopped, won't auto-start | Gray | No |
| `paused` | Market holiday or weekend | Amber | Yes (next trading day) |
| `error` | Strategy error (e.g., order rejected) | Red | Depends |

### 32.10 Webhook Behavior by Schedule State

| Strategy State | Webhook Entry Signal | Webhook Exit Signal |
|----------------|---------------------|---------------------|
| Within schedule window | Accepted, processed normally | Accepted |
| Outside schedule window | Rejected (HTTP 403) | Accepted (always allow exits) |
| Manually stopped | Rejected (HTTP 403) | Accepted |
| Paused (holiday) | Rejected (HTTP 403) | Accepted |

**Important:** Exit/squareoff signals are ALWAYS accepted regardless of schedule state. Only entry signals are blocked.

### 32.11 Exchange-Specific Default Schedules

Different exchanges have different trading hours. The default schedule adapts to the primary exchange:

| Exchange | Default Start | Default Stop | Default Days |
|----------|--------------|-------------|--------------|
| NFO (NSE F&O) | 09:15 | 15:30 | Mon–Fri |
| BFO (BSE F&O) | 09:15 | 15:30 | Mon–Fri |
| CDS (Currency) | 09:00 | 17:00 | Mon–Fri |
| BCD (BSE Currency) | 09:00 | 17:00 | Mon–Fri |
| MCX (Commodity) | 09:00 | 23:30 | Mon–Fri |
| NSE (Equity) | 09:15 | 15:30 | Mon–Fri |
| BSE (Equity) | 09:15 | 15:30 | Mon–Fri |

When creating a strategy with a specific exchange, the UI pre-fills the default schedule for that exchange. Users can always override.

### 32.12 UI Components

**Schedule Configuration (in Strategy Builder — BasicsStep):**

```
┌─────────────────────────────────────────────────┐
│ Schedule                                        │
│                                                 │
│ Trading Days                                    │
│ [Mon✓] [Tue✓] [Wed✓] [Thu✓] [Fri✓] [Sat] [Sun] │
│                                                 │
│ Start Time          Stop Time                   │
│ ┌──────────┐       ┌──────────┐                 │
│ │ 09:15    │       │ 15:30    │                 │
│ └──────────┘       └──────────┘                 │
│                                                 │
│ ☑ Auto square-off MIS at stop time              │
│ ☑ Block webhook entries outside schedule         │
└─────────────────────────────────────────────────┘
```

**Schedule Status (in StrategyCard header):**

```
┌───────────────────────────────────────────────────┐
│ Iron Condor NIFTY    [Running ●]   09:15-15:30    │
│                      Mon-Fri       Next: Today    │
└───────────────────────────────────────────────────┘
```

**Schedule Badge States:**

| State | Display | Color |
|-------|---------|-------|
| Running within schedule | `Running ●` + schedule times | Green |
| Armed, waiting for start | `Scheduled` + next start time | Blue |
| Manually stopped | `Stopped` + "Click Start to resume" | Gray |
| Paused (holiday) | `Holiday` + holiday name | Amber |
| Outside schedule hours | `Off hours` + next start time | Gray |

### 32.13 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `PUT` | `/api/v1/strategy/{id}/schedule` | Update schedule config |
| `GET` | `/api/v1/strategy/{id}/schedule` | Get current schedule + status |

**PUT request body:**
```json
{
    "start_time": "09:15",
    "stop_time": "15:30",
    "days": ["mon", "tue", "wed", "thu", "fri"],
    "auto_entry": true,
    "auto_exit": true
}
```

**GET response:**
```json
{
    "status": "success",
    "data": {
        "start_time": "09:15",
        "stop_time": "15:30",
        "days": ["mon", "tue", "wed", "thu", "fri"],
        "auto_entry": true,
        "auto_exit": true,
        "current_state": "running",
        "next_start": null,
        "next_stop": "15:30 IST today"
    }
}
```

### 32.14 SocketIO Events

| Event | When | Payload |
|-------|------|---------|
| `strategy_schedule_started` | Scheduled start fires | `{strategy_id, start_time}` |
| `strategy_schedule_stopped` | Scheduled stop fires | `{strategy_id, stop_time, positions_closed: N}` |
| `strategy_schedule_blocked` | Entry blocked outside schedule | `{strategy_id, reason, next_start}` |
| `strategy_schedule_holiday` | Strategy paused for holiday | `{strategy_id, holiday_name}` |

---

## Appendix A: Gap Analysis Reference

| Gap ID | Gap Description | Priority | Resolution Section |
|--------|----------------|----------|-------------------|
| GAP 1 | No dedicated F&O Strategy Builder page | P0 | §23 |
| GAP 2 | No pre-built strategy templates | P2 | §24 |
| GAP 3 | No leg execution state visualization (frozen legs) | P1 | §23.3 |
| GAP 4 | Missing leg-level SL/TP distance metrics | P1 | §26 |
| GAP 5 | No dedicated Risk Monitor view | P0 | §25 |
| GAP 6 | No risk threshold progress bars | P0 | §25.2 |
| GAP 7 | No market hours intelligence | P2 | §28 |
| GAP 8 | Daily circuit breaker under-specified (needs 3 behavior modes) | P1 | §20.4.1 |
| GAP 9 | No technical indicator exit mode (Supertrend) | V2+ | Out of scope |
| GAP 10 | No multi-account support | V2+ | Out of scope |
| GAP 11 | Symbol mapping UI for F&O too complex | P1 | §23.2 (simplified via builder) |
| GAP 12 | No strategy P&L breakdown by leg | P1 | §30 |
| GAP 13 | Missing webhook deduplication details | P2 | V1 PRD §16 (adequate) |
| GAP 14 | No strategy cloning | P2 | §29 |
| GAP 15 | Position group visualization missing | P0 | §27 |

### Additional V2 Features (Beyond Gap Analysis)

| Feature | Description | Section |
|---------|-------------|---------|
| Risk Evaluation Logic | Exact formulas matching AlgoMirror — combined premium, leg SL/TGT/TSL (price-based), combined max loss/profit/TSL (P&L-based), breakeven stoploss | §31 |
| Strategy Scheduling | Configurable start/stop times and trading days, APScheduler, exchange-specific defaults, holiday enforcement, webhook gating | §32 |
| Freeze Qty Order Routing | Options use `place_options_multiorder`/`place_options_order` with splitsize; equity/futures use `place_order`/`split_order` | §23.6 |
| Extended Strike Selection | 5 types: ATM, ITM 1-20, OTM 1-20, specific strike, premium near | §23.7 |
| Multi-Exchange Support | NFO, BFO, CDS, BCD, MCX with exchange-specific strike steps and expiry types | §23.8 |
| Breakeven Stoploss | OpenAlgo-only: one-time SL move to entry on profit threshold, with trail interaction | §31.10 |
