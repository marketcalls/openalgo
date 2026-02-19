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
      "strike_selection": "OTM4",
      "strike_value": null,
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
    "trailstop_type": "points",
    "trailstop_value": 20,
    "breakeven_type": "points",
    "breakeven_value": 30
  },
  "per_leg_risk": null
}
```

**Validation rules:**
- `legs`: array of 1-6 leg objects
- Each leg: `leg_type` required (`option` | `futures`)
- If `leg_type=option`: `option_type` (CE|PE) and `strike_selection` (ATM|ITMn|OTMn) required
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

Toast notifications via SocketIO for: position opened, exit triggered, position closed, order rejected, risk paused/resumed, partial fill warning, breakeven activated.

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

---

## 16. Webhook Handler Changes

*(Unchanged from V1 — see original PRD Section 16)*

---

## 17. Concurrency, Data Integrity & Performance

*(Unchanged from V1 — see original PRD Section 17)*

---

## 18. Configuration

*(Unchanged from V1 — see original PRD Section 18)*

---

## 19. Database Migration

*(Unchanged from V1 — see original PRD Section 19)*

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
- SL/TGT/TSL/BE evaluation
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

- Strategy Builder page with 4-step wizard
- 9-parameter leg card component
- Preset selector (Straddle, Strangle, Iron Condor, Bull Call, Bear Put, Custom)
- Leg execution state visualization (frozen legs with diagonal stripes)
- Builder API endpoints (save, execute)
- Integration with `place_options_multiorder` service
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
| 6 | Strike selection | select | `ATM`, `ITM1`-`ITM10`, `OTM1`-`OTM10` (options only) |
| 7 | Strike value | read-only | Auto-resolved from ATM + offset (display only) |
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
            "strike_selection": "OTM4",
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
            "strike_selection": "OTM4",
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
            "strike_selection": "OTM6",
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
            "strike_selection": "OTM6",
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
   - Apply offset (OTM4 = ATM + 4 * tick_size for CE, ATM - 4 * tick_size for PE)
   - Get expiry date via `get_expiry_dates(symbol, exchange, instrumenttype)`
   - Resolve full symbol via `get_option_symbol(underlying, exchange, expiry_date, strike, offset, option_type)`
3. Place all legs via `place_options_multiorder(...)` or sequentially
4. Create `strategy_order` records for each leg
5. If combined risk mode: create `strategy_position_group` record
6. Emit `builder_leg_update` SocketIO events as each leg fills

### 23.5 Internal Service Usage

| Operation | Service | Function |
|-----------|---------|----------|
| Resolve expiry dates | `expiry_service` | `get_expiry_dates(symbol, exchange, instrumenttype)` |
| Resolve option symbol | `option_symbol_service` | `get_option_symbol(underlying, exchange, expiry_date, strike_int, offset, option_type)` |
| Get underlying LTP | `quotes_service` | `get_quotes(symbol, exchange)` |
| Get multiple LTPs | `multiquotes_service` | `get_multiquotes(symbols_dict)` |
| Place multi-leg order | `options_multiorder_service` | `place_options_multiorder(...)` |
| Place single leg | `options_order_service` | `place_options_order(...)` |
| Auto-split large orders | `split_order_service` | `split_order(...)` |
| Get symbol info | `symbol_service` | `get_symbol(symbol, exchange)` → returns tick_size, lotsize |

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
