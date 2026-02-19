# Strategy Hub — Frontend UI Plan V2

**Date**: 2026-02-19
**Status**: Draft V2
**Previous Version**: 2026-02-06-strategy-dashboard-ui-plan.md (V1)

---

## Overview

StrategyHub is the single-page React dashboard for managing all trading strategies. V2 adds:
- **F&O Strategy Builder** — new page at `/strategy/builder`
- **Strategy Templates** — new page at `/strategy/templates`
- **Risk Monitor tab** — 6th tab in StrategyCard
- **Position groups** — bordered cards for combined P&L legs
- **Distance metrics** — 3 new columns in position table
- **Circuit breaker** — config card with 3 behavior modes
- **Market status** — indicator badge in header
- **Strategy cloning** — one-click duplicate
- **Per-leg P&L** — breakdown in trades/P&L panels

---

## Before / After (V1 → V2)

| V1 (5 old pages) | V2 (3 pages) |
|-------------------|--------------|
| `/strategy` (list) | `/strategy` — StrategyHub (collapsible cards, 6-tab) |
| `/strategy/<id>` (detail) | `/strategy/builder` — F&O Strategy Builder (NEW) |
| `/strategy/<id>/positions` | `/strategy/templates` — Templates Gallery (NEW) |
| `/strategy/<id>/orders` | *(removed — inline tabs)* |
| `/strategy/<id>/trades` | *(removed — inline tabs)* |

---

## File Structure

```
frontend/src/
├── pages/
│   └── strategy/
│       ├── StrategyHub.tsx              # Main dashboard page
│       ├── StrategyBuilder.tsx          # NEW: F&O strategy builder page
│       ├── StrategyTemplates.tsx        # NEW: Templates gallery page
│       └── index.ts                     # Barrel export
├── api/
│   ├── strategy-dashboard.ts           # Dashboard REST API (15+ methods)
│   ├── strategy-builder.ts             # NEW: Builder API
│   └── strategy-templates.ts           # NEW: Templates API
├── types/
│   ├── strategy-dashboard.ts           # Dashboard TypeScript interfaces
│   ├── strategy-builder.ts             # NEW: Builder types
│   └── strategy-templates.ts           # NEW: Template types
├── stores/
│   └── strategyDashboardStore.ts       # Zustand store (enhanced with risk events)
├── hooks/
│   ├── useStrategySocket.ts            # SocketIO hook for strategy rooms
│   └── useMarketStatus.ts             # NEW: Market status polling hook
└── components/
    ├── strategy-dashboard/
    │   ├── DashboardHeader.tsx          # Summary cards + MarketStatusIndicator
    │   ├── StrategyCard.tsx             # Collapsible card with 6-tab interface
    │   ├── OverviewTab.tsx              # Config + webhook + symbols + CB + clone
    │   ├── PositionTable.tsx            # Enhanced with groups + distance metrics
    │   ├── PositionRow.tsx              # Memoized row with 14 columns
    │   ├── PositionGroup.tsx            # NEW: Combined P&L group card
    │   ├── PositionGroupHeader.tsx      # NEW: Group header with combined P&L
    │   ├── RiskMonitorTab.tsx           # NEW: 6th tab — progress bars + events log
    │   ├── RiskProgressBar.tsx          # NEW: Threshold progress bar
    │   ├── RiskEventsLog.tsx            # NEW: Risk events audit log
    │   ├── CircuitBreakerCard.tsx       # NEW: CB config with behavior modes
    │   ├── CircuitBreakerBanner.tsx     # NEW: Red alert banner when tripped
    │   ├── MarketStatusIndicator.tsx    # NEW: Market phase badge
    │   ├── OrdersPanel.tsx              # Inline orders table
    │   ├── TradesPanel.tsx              # Enhanced with per-leg breakdown
    │   ├── PnlPanel.tsx                 # P&L analytics + leg breakdown
    │   ├── CreateStrategyDialog.tsx     # Enhanced with type selector
    │   ├── StatusBadge.tsx              # Color-coded exit/state badges
    │   ├── RiskBadges.tsx               # SL/TGT/TSL/BE inline badges
    │   ├── EquityCurveChart.tsx         # Recharts equity curve
    │   ├── ExitBreakdownTable.tsx       # Exit reason aggregation
    │   ├── MetricsGrid.tsx              # Risk metrics cards
    │   ├── RiskConfigDrawer.tsx         # Risk config side panel
    │   └── EmptyState.tsx               # No data states
    ├── strategy-builder/
    │   ├── BuilderStepper.tsx           # NEW: 4-step wizard navigation
    │   ├── BasicsStep.tsx               # NEW: Step 1 — strategy basics
    │   ├── LegCard.tsx                  # NEW: 9-parameter leg configuration
    │   ├── LegsStep.tsx                 # NEW: Step 2 — leg configuration
    │   ├── PresetSelector.tsx           # NEW: Preset template selector
    │   ├── RiskConfigStep.tsx           # NEW: Step 3 — risk configuration
    │   ├── ReviewStep.tsx               # NEW: Step 4 — review & save
    │   └── FrozenLegOverlay.tsx         # NEW: Diagonal stripes for filled legs
    └── strategy-templates/
        ├── TemplateCard.tsx             # NEW: Template display card
        ├── TemplateGrid.tsx             # NEW: Templates grid layout
        └── DeployDialog.tsx             # NEW: Template deploy customization
```

---

## Data Architecture

### Three-Layer Data Flow (Unchanged from V1)

```
REST API (initial snapshot)
    │
    ▼
TanStack Query (cache, loading, error, refetch)
    │
    ▼
Zustand Store (live state, mutated by SocketIO at ~300ms intervals)
    │
    ▼
React Components (subscribe to Zustand slices)
```

### Zustand Store Enhancement (V2)

```typescript
interface StrategyDashboardStore {
  // V1 state (unchanged)
  strategies: Map<number, DashboardStrategy>
  positions: Map<number, DashboardPosition[]>
  summary: DashboardSummary

  // V2 additions
  riskEvents: Map<number, RiskEvent[]>         // per-strategy risk event log
  circuitBreakerStatus: Map<number, CBStatus>  // per-strategy CB status
  positionGroups: Map<string, PositionGroup>   // combined P&L groups

  // Actions
  setDashboardData: (strategies: DashboardStrategy[], summary: DashboardSummary) => void
  updatePosition: (update: PositionUpdatePayload) => void
  updateGroup: (update: GroupUpdatePayload) => void
  addRiskEvent: (strategyId: number, event: RiskEvent) => void
  updateCircuitBreaker: (strategyId: number, status: CBStatus) => void
}
```

---

## API Layer

**File:** `frontend/src/api/strategy-dashboard.ts`

### Dashboard API (Enhanced)

| Method | HTTP | Endpoint | Notes |
|--------|------|----------|-------|
| `getDashboard` | GET | `/strategy/api/dashboard` | V1 |
| `getPositions` | GET | `/strategy/api/strategy/:id/positions` | V1 |
| `getOrders` | GET | `/strategy/api/strategy/:id/orders` | V1 |
| `getTrades` | GET | `/strategy/api/strategy/:id/trades` | V1 |
| `getPnL` | GET | `/strategy/api/strategy/:id/pnl` | V1 — enhanced with leg_breakdown |
| `updateRiskConfig` | PUT | `/strategy/api/strategy/:id/risk` | V1 |
| `activateRisk` | POST | `/strategy/api/strategy/:id/risk/activate` | V1 |
| `deactivateRisk` | POST | `/strategy/api/strategy/:id/risk/deactivate` | V1 |
| `closePosition` | POST | `/strategy/api/strategy/:id/position/:pid/close` | V1 |
| `closeAllPositions` | POST | `/strategy/api/strategy/:id/positions/close-all` | V1 |
| `deletePosition` | DELETE | `/strategy/api/strategy/:id/position/:pid` | V1 |
| `cloneStrategy` | POST | `/strategy/api/strategy/:id/clone` | NEW |
| `getMarketStatus` | GET | `/strategy/api/market-status` | NEW |
| `getRiskEvents` | GET | `/strategy/api/strategy/:id/risk-events` | NEW |
| `closePositionGroup` | POST | `/strategy/api/strategy/:id/group/:gid/close` | NEW |
| `updateCircuitBreaker` | PUT | `/strategy/api/strategy/:id/circuit-breaker` | NEW |

### Builder API (NEW)

**File:** `frontend/src/api/strategy-builder.ts`

| Method | HTTP | Endpoint |
|--------|------|----------|
| `saveStrategy` | POST | `/strategy/api/builder/save` |
| `executeStrategy` | POST | `/strategy/api/builder/:id/execute` |

### Templates API (NEW)

**File:** `frontend/src/api/strategy-templates.ts`

| Method | HTTP | Endpoint |
|--------|------|----------|
| `getTemplates` | GET | `/strategy/api/templates` |
| `getTemplate` | GET | `/strategy/api/templates/:id` |
| `createTemplate` | POST | `/strategy/api/templates` |
| `deployTemplate` | POST | `/strategy/api/templates/:id/deploy` |
| `deleteTemplate` | DELETE | `/strategy/api/templates/:id` |

---

## Component Details — StrategyCard (Enhanced)

### StrategyCard

**File:** `components/strategy-dashboard/StrategyCard.tsx`

**V2 Change:** 5 tabs → 6 tabs

**Expanded content — 6-tab interface:**

| Tab | Component | Data Source | Loading |
|-----|-----------|-------------|---------|
| Overview | `OverviewTab` | `strategyApi` + host config | Skeleton |
| Positions | `PositionTable` + action bar | Zustand store (live) | Immediate |
| Orders | `OrdersPanel` | `useQuery(['strategy-orders', id])` | Skeleton |
| Trades | `TradesPanel` | `useQuery(['strategy-trades', id])` | Skeleton |
| P&L | `PnlPanel` | `useQuery(['strategy-pnl', id])` | Skeleton |
| Risk Monitor | `RiskMonitorTab` | Zustand store (live) | Immediate |

---

## Component Details — Risk Monitor Tab (NEW)

### RiskMonitorTab

**File:** `components/strategy-dashboard/RiskMonitorTab.tsx`

**Layout:**
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

### RiskProgressBar

**File:** `components/strategy-dashboard/RiskProgressBar.tsx`

**Props:**
```typescript
interface RiskProgressBarProps {
  label: string
  currentValue: number
  thresholdValue: number
  type: 'stoploss' | 'target' | 'trailstop'
  isTriggered?: boolean
}
```

**Rendering:**
- Fill percentage: `Math.min(100, (currentValue / thresholdValue) * 100)`
- Color: green (0-50%) → amber (50-80%) → red (80-100%)
- When triggered: full red with "HIT!" badge, `animate-pulse`

---

## Component Details — Enhanced Position Table

### PositionTable (Enhanced)

**V2 changes:**
1. Positions with `position_group_id` grouped into `PositionGroup` cards
2. Ungrouped positions render as individual `PositionRow` components
3. Groups render before ungrouped positions

### PositionRow (Enhanced — 14 Columns)

| # | Column | Width | Source |
|---|--------|-------|--------|
| 1 | Symbol | auto | `position.symbol` |
| 2 | Qty | 60px | `position.quantity` (+green / -red) |
| 3 | Avg | 80px | `position.average_entry_price` |
| 4 | LTP | 80px | Live (Zustand) |
| 5 | P&L | 100px | Live (Zustand) |
| 6 | SL | 70px | Live (Zustand) |
| 7 | SL Dist | 90px | Computed, color-coded (NEW) |
| 8 | TGT | 70px | Live (Zustand) |
| 9 | TGT Dist | 90px | Computed, color-coded (NEW) |
| 10 | TSL | 70px | Live (Zustand) |
| 11 | TSL Dist | 90px | Computed, color-coded (NEW) |
| 12 | BE | 40px | Blue badge if activated |
| 13 | Status | 80px | `StatusBadge` |
| 14 | Action | 60px | Close button |

**Distance column color coding:**

| Zone | Range | Color | Animation |
|------|-------|-------|-----------|
| Safe | >10% | `text-muted-foreground` | None |
| Warning | 5-10% | `text-amber-500` | None |
| Danger | <5% | `text-destructive` | `animate-pulse`, font-bold |

---

## Component Details — Position Groups (NEW)

### PositionGroup

**File:** `components/strategy-dashboard/PositionGroup.tsx`

**Props:**
```typescript
interface PositionGroupProps {
  group: PositionGroupData
  positions: DashboardPosition[]
  strategyId: number
  onCloseGroup: (groupId: string) => Promise<void>
  onClosePosition: (positionId: number) => Promise<void>
}
```

### PositionGroupHeader

**File:** `components/strategy-dashboard/PositionGroupHeader.tsx`

- Left: Group name + leg count + status badge
- Center: Combined P&L (large, color-coded) + compact progress bars
- Right: "Close Group" button + expand/collapse chevron
- Left border: 2px colored by status (green/amber/red/gray)

---

## Component Details — Daily Circuit Breaker (NEW)

### CircuitBreakerCard

**File:** `components/strategy-dashboard/CircuitBreakerCard.tsx`

```
+---------------------------------------------------------------+
| DAILY CIRCUIT BREAKER                          [Edit] [Save]    |
+---------------------------------------------------------------+
| Daily Stoploss:   ₹5,000 (points)                              |
| Daily Target:     ₹10,000 (points)                             |
| Daily Trail SL:   20% from daily peak                           |
| Behavior:         [Close All Positions ▼]                       |
+---------------------------------------------------------------+
| Status: [Active] / [TRIPPED - Daily SL hit at 14:32 IST]       |
+---------------------------------------------------------------+
```

**Behavior dropdown (3 modes):**
- `alert_only`: Toast + Telegram only, no automatic action
- `stop_entries`: Block new webhook entries, keep existing positions
- `close_all_positions`: Close all strategy positions immediately

### CircuitBreakerBanner

**File:** `components/strategy-dashboard/CircuitBreakerBanner.tsx`

Red alert banner below strategy card header when tripped. Background: `bg-destructive/10` with `border-destructive` 4px left border.

---

## Component Details — Market Status (NEW)

### MarketStatusIndicator

**File:** `components/strategy-dashboard/MarketStatusIndicator.tsx`

Badge in DashboardHeader:

| Phase | Color | Icon | Animation |
|-------|-------|------|-----------|
| `market_open` | Green | Circle (filled) | `animate-pulse` |
| `pre_market` | Amber | Clock | None |
| `post_market` | Amber | Clock | None |
| `market_closed` | Gray | Moon | None |
| `holiday` | Red | Calendar | None |

### useMarketStatus Hook

**File:** `frontend/src/hooks/useMarketStatus.ts`

```typescript
function useMarketStatus(): MarketStatus | null {
  // TanStack Query with 60s refetch interval
  // GET /strategy/api/market-status
}
```

---

## Component Details — Enhanced CreateStrategyDialog

### CreateStrategyDialog (Enhanced)

**V2 addition:** Strategy type selector at the top:

```
+-----------------------------------------------+
| CREATE NEW STRATEGY                             |
+-----------------------------------------------+
|                                                 |
| +-------------------------------------------+  |
| | [Webhook icon]                             |  |
| | Webhook Strategy                           |  |
| | For equity and signal-based trading        |  |
| +-------------------------------------------+  |
|                                                 |
| +-------------------------------------------+  |
| | [Options icon]                             |  |
| | F&O Strategy Builder                       |  |
| | For multi-leg options and futures           |  |
| +-------------------------------------------+  |
|                                                 |
| +-------------------------------------------+  |
| | [Template icon]                            |  |
| | From Template                              |  |
| | Start with a pre-built strategy            |  |
| +-------------------------------------------+  |
+-----------------------------------------------+
```

**Routing:**
1. "Webhook Strategy" → Expand into existing form (name, platform, etc.)
2. "F&O Strategy Builder" → Navigate to `/strategy/builder`
3. "From Template" → Navigate to `/strategy/templates`

---

## Component Details — Strategy Builder Page (NEW)

### StrategyBuilder

**File:** `pages/strategy/StrategyBuilder.tsx`

**Route:** `/strategy/builder` (and `/strategy/builder/:id` for editing)

**Layout:** 4-step wizard with stepper navigation

```
+---------------------------------------------------------------+
| F&O Strategy Builder                           [Back to Hub]    |
| ● Basics ─── ○ Legs ─── ○ Risk ─── ○ Review                   |
+---------------------------------------------------------------+
|                                                                 |
| [Current step content renders here]                             |
|                                                                 |
+---------------------------------------------------------------+
| [← Previous]                                      [Next →]     |
+---------------------------------------------------------------+
```

### BasicsStep (NEW)

**File:** `components/strategy-builder/BasicsStep.tsx`

Fields:
- Strategy name (text input, required)
- Exchange (select: NFO, BFO, CDS, BCD, MCX — all F&O exchanges)
- Underlying (typeahead search via `/search/api/underlyings?exchange=<selected>`)
- Expiry type (select: current_week, next_week, current_month, next_month — weekly only for NFO/BFO index options)
- Product type (NRML/MIS toggle)

When exchange changes: reset underlying, refetch underlyings list, update available expiry types.

### LegCard (NEW)

**File:** `components/strategy-builder/LegCard.tsx`

9-parameter leg configuration card:

```
+---------------------------------------------------------------+
| Leg 1                                           [✕ Remove]     |
+---------------------------------------------------------------+
| Type: [Option ▼]  Product: [NRML ▼]  Expiry: [Current Week ▼] |
| Action: [BUY] [SELL]    Option: [CE] [PE]                      |
| Strike: [ATM ▼]  Value: 25,950 (auto)   Lots: [1]             |
| Order: MARKET                                                   |
+---------------------------------------------------------------+
```

**Strike selection dropdown options (5 types):**
- ATM — strike value auto-resolved (read-only)
- ITM 1 through ITM 20 — offset dropdown, value auto-resolved (read-only)
- OTM 1 through OTM 20 — offset dropdown, value auto-resolved (read-only)
- Specific Strike — value input field enabled (user enters exact strike)
- Premium Near — premium input field enabled (user enters target premium ₹)

Strike value field dynamically changes behavior based on selection type.
See PRD §23.7 for resolution logic.

**Frozen state (after execution):**
- Diagonal stripes overlay (CSS `repeating-linear-gradient`)
- All inputs disabled
- Green "Filled @ ₹245" badge
- `pointer-events: none`

**FrozenLegOverlay CSS:**
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

### PresetSelector (NEW)

**File:** `components/strategy-builder/PresetSelector.tsx`

Grid of preset cards:

| Preset | Description | Legs |
|--------|-------------|------|
| Straddle | Sell ATM CE + PE | 2 |
| Strangle | Sell OTM CE + PE | 2 |
| Iron Condor | 4-leg neutral | 4 |
| Bull Call Spread | Bullish, defined risk | 2 |
| Bear Put Spread | Bearish, defined risk | 2 |
| Custom | Build your own | 0 |

### RiskConfigStep (NEW)

**File:** `components/strategy-builder/RiskConfigStep.tsx`

- Risk mode toggle: Per-Leg | Combined P&L
- Per-leg mode: SL/TGT/TSL/BE inputs appear on each LegCard
- Combined mode: Single panel with combined risk inputs
- Daily circuit breaker section (collapsible)

### ReviewStep (NEW)

**File:** `components/strategy-builder/ReviewStep.tsx`

- Strategy summary card
- Legs table with resolved strikes
- Risk configuration summary
- "Save as Template" checkbox
- Save button (primary) + Cancel button

---

## Component Details — Templates Page (NEW)

### StrategyTemplates

**File:** `pages/strategy/StrategyTemplates.tsx`

**Route:** `/strategy/templates`

```
+---------------------------------------------------------------+
| Strategy Templates                    [Back to Hub] [+ Custom]  |
+---------------------------------------------------------------+
| Filter: [All ▼] [Neutral] [Bullish] [Bearish] [Hedge]         |
+---------------------------------------------------------------+
|                                                                 |
| +-------------------+  +-------------------+                   |
| | ATM Straddle      |  | OTM Strangle      |                   |
| | Neutral · 2 legs  |  | Neutral · 2 legs  |                   |
| | SELL ATM CE+PE    |  | SELL OTM2 CE+PE   |                   |
| | [Deploy]          |  | [Deploy]          |                   |
| +-------------------+  +-------------------+                   |
|                                                                 |
| +-------------------+  +-------------------+                   |
| | Iron Condor       |  | Bull Call Spread   |                   |
| | Neutral · 4 legs  |  | Bullish · 2 legs  |                   |
| | 4-leg protection  |  | BUY ATM + SELL OTM|                   |
| | [Deploy]          |  | [Deploy]          |                   |
| +-------------------+  +-------------------+                   |
+---------------------------------------------------------------+
```

### DeployDialog (NEW)

**File:** `components/strategy-templates/DeployDialog.tsx`

Customization dialog before deploying a template:
- Strategy name (pre-filled: template name)
- Underlying (default from template)
- Expiry type
- Quantity (lots)
- Risk parameters (editable, pre-filled from template)
- Deploy button → Creates strategy, redirects to Hub

---

## Component Details — Strategy Cloning (NEW)

### Clone Strategy Button

**Location:** `OverviewTab.tsx` → Manage Actions section

```typescript
<Button variant="outline" onClick={() => handleClone(strategy.id)} disabled={isCloning}>
  {isCloning ? <Loader2 className="animate-spin" /> : <Copy className="h-4 w-4" />}
  Clone Strategy
</Button>
```

**Flow:**
1. Click → Confirmation dialog
2. POST `/strategy/api/strategy/:id/clone`
3. On success → Dashboard refetch, auto-expand new card

---

## SocketIO Events (Complete Reference)

### Toast/Notification Events

| Event | When | Toast Style | Audio |
|-------|------|-------------|-------|
| `strategy_position_opened` | New position fill | info | Yes |
| `strategy_exit_triggered` | SL/TGT/TSL fires | varies | Yes |
| `strategy_position_closed` | Position fully exited | success/error | Yes |
| `strategy_order_rejected` | Exit order rejected | error | Yes |
| `strategy_risk_paused` | Data stale | warning | Yes |
| `strategy_risk_resumed` | Connection recovered | info | No |
| `strategy_partial_fill_warning` | Partial fill | warning | Yes |
| `strategy_breakeven_activated` | BE threshold hit | info | No |

### Data Update Events (Silent)

| Event | When | Payload |
|-------|------|---------|
| `strategy_position_update` | Every LTP tick | Position LTP, P&L, SL, TGT, TSL |
| `strategy_group_update` | Every tick (combined) | Combined P&L, thresholds |
| `strategy_pnl_update` | Every tick | Strategy aggregate P&L |
| `strategy_order_placed` | Order placed | Order details |
| `strategy_order_filled` | Fill confirmed | Fill price, qty |
| `strategy_order_cancelled` | Cancelled | Order details |
| `strategy_circuit_breaker` | CB tripped/cleared | Status, reason |
| `strategy_risk_event` | Risk state change | Event type, message |
| `strategy_trailstop_moved` | TSL ratcheted | Old/new price |

### Builder Room Events

| Event | When | Payload |
|-------|------|---------|
| `builder_leg_update` | Leg status change | Leg execution info |
| `builder_execution_complete` | All legs done | Strategy ID, success |

---

## Route Configuration

**File:** `App.tsx`

```tsx
const StrategyHub = lazy(() => import('@/pages/strategy/StrategyHub'))
const StrategyBuilder = lazy(() => import('@/pages/strategy/StrategyBuilder'))
const StrategyTemplates = lazy(() => import('@/pages/strategy/StrategyTemplates'))

<Route path="/strategy" element={<StrategyHub />} />
<Route path="/strategy/builder" element={<StrategyBuilder />} />
<Route path="/strategy/builder/:id" element={<StrategyBuilder />} />
<Route path="/strategy/templates" element={<StrategyTemplates />} />
```

---

## Key Design Decisions

### Builder as Separate Page (NEW — V2)
The F&O Strategy Builder is a full page (`/strategy/builder`) because:
- 4-step guided flow needs substantial real estate
- Leg cards are visual elements needing horizontal space for 9 parameters each
- Execution tracking requires its own UI context
- Needs its own URL for direct linking and browser back navigation

### Risk Monitor as 6th Tab (NEW — V2)
Risk monitoring is a tab (not separate page) because:
- Data is already in Zustand from SocketIO — zero latency
- Traders flip quickly between Positions and Risk Monitor
- Co-located with the strategy it belongs to

### Position Groups as Nested Cards (NEW — V2)
Combined-mode positions use bordered cards because:
- Border + header makes group boundary unambiguous
- Natural place for combined P&L and "Close Group" action
- Expandable/collapsible reduces noise

### Inline Tabs vs Drawers (V1 — unchanged)
Tab panels beat drawers because drawers obscure live position data.

### React.memo on PositionRow (V1 — unchanged)
Prevents 50 re-renders per SocketIO update cycle.

### Lazy Tab Loading (V1 — unchanged)
Risk Monitor tab is NOT pre-loaded — activates on first click. Since data comes from Zustand (already populated), no loading delay.

---

## Exit Status Badge Reference

| `exit_detail` | Badge | Color |
|--------------|-------|-------|
| `leg_sl` | SL | red |
| `leg_target` | TGT | green |
| `leg_tsl` | TSL | amber |
| `breakeven_sl` | BE-SL | blue |
| `combined_sl` | C-SL | red |
| `combined_target` | C-TGT | green |
| `combined_tsl` | C-TSL | amber |
| `manual` | Manual | gray |
| `manual_all` | Manual | gray |
| `squareoff` | SQ-OFF | gray |

| `position_state` | Badge | Color | Animation |
|-----------------|-------|-------|-----------|
| `active` (monitoring) | Monitoring | blue | None |
| `active` (paused) | Paused | amber | None |
| `pending_entry` | Pending | amber | `animate-pulse` |
| `exiting` | Exiting... | amber | `animate-pulse` |
| `failed` | Failed | red | `animate-pulse` |

---

## Distance Metrics Computation (Client-Side)

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
    sl: compute(stoploss_price, false),
    tgt: compute(target_price, true),
    tsl: compute(trailstop_price, false),
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

## Preset Leg Definitions

```typescript
const PRESETS: Record<string, PresetDefinition> = {
  straddle: {
    name: 'Straddle',
    description: 'Sell ATM CE + ATM PE',
    legs: [
      { leg_type: 'option', offset: 'ATM', option_type: 'CE', action: 'SELL', product_type: 'NRML' },
      { leg_type: 'option', offset: 'ATM', option_type: 'PE', action: 'SELL', product_type: 'NRML' },
    ],
  },
  strangle: {
    name: 'Strangle',
    description: 'Sell OTM CE + OTM PE',
    legs: [
      { leg_type: 'option', offset: 'OTM2', option_type: 'CE', action: 'SELL', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM2', option_type: 'PE', action: 'SELL', product_type: 'NRML' },
    ],
  },
  iron_condor: {
    name: 'Iron Condor',
    description: '4-leg neutral strategy',
    legs: [
      { leg_type: 'option', offset: 'OTM4', option_type: 'CE', action: 'SELL', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM4', option_type: 'PE', action: 'SELL', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM6', option_type: 'CE', action: 'BUY', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM6', option_type: 'PE', action: 'BUY', product_type: 'NRML' },
    ],
  },
  bull_call_spread: {
    name: 'Bull Call Spread',
    description: 'Bullish with defined risk',
    legs: [
      { leg_type: 'option', offset: 'ATM', option_type: 'CE', action: 'BUY', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM2', option_type: 'CE', action: 'SELL', product_type: 'NRML' },
    ],
  },
  bear_put_spread: {
    name: 'Bear Put Spread',
    description: 'Bearish with defined risk',
    legs: [
      { leg_type: 'option', offset: 'ATM', option_type: 'PE', action: 'BUY', product_type: 'NRML' },
      { leg_type: 'option', offset: 'OTM2', option_type: 'PE', action: 'SELL', product_type: 'NRML' },
    ],
  },
}
```

---

## Verification

```bash
cd frontend && npx tsc --noEmit      # Type check passes
cd frontend && npm run lint           # No new lint warnings
cd frontend && npm test               # All tests pass
cd frontend && npm run build          # Production build succeeds
```
