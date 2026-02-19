# Strategy Hub UI — Architecture & Implementation Reference

**Status:** Implemented (rms branch)

**Goal:** Unified Strategy Hub at `/strategy` — a single page that replaces 5 separate strategy pages. Manage, configure, monitor, and analyze all webhook strategies with live P&L via SocketIO.

**Scope:** Webhook strategies at `/strategy`. Chartink (`/chartink`) can extend the same components later.

**Tech Stack:** React 19, TypeScript, Vite, shadcn/ui (new-york), TanStack Query v5, Zustand, Socket.IO Client, Recharts, Tailwind CSS 4, lucide-react

---

## Before vs After

### Before (5 pages, 4 routes)

| Page | Route | Purpose |
|------|-------|---------|
| `StrategyIndex` | `/strategy` | Grid of strategy cards with links |
| `NewStrategy` | `/strategy/new` | Create form (separate page) |
| `ViewStrategy` | `/strategy/:id` | Config + webhook URL + symbols (read-only) |
| `ConfigureSymbols` | `/strategy/:id/configure` | Add/delete symbol mappings |
| `StrategyDashboard` | `/strategy/dashboard` | Live monitoring (drawers for orders/trades/P&L) |

### After (1 page, 1 route)

| Page | Route | Purpose |
|------|-------|---------|
| `StrategyHub` | `/strategy` | Everything — create, configure, monitor, analyze |

Each strategy renders as an expandable card with 5 inline tabs:

```
┌─────────────────────────────────────────────────────────────────┐
│  Strategy Hub           ● Connected    [+ New Strategy] [↻]     │
│  3 Active  │  5 Positions  │  Total P&L: +₹12,450.00           │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ● NIFTY Intraday  [Active]  TradingView · LONG · 2 pos        │
│  ▼  P&L: +₹5,200  WR: 67%  PF: 1.82                           │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │ Overview │ Positions │ Orders │ Trades │ P&L              │  │
│  │                                                           │  │
│  │  [Active tab content renders here]                        │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ○ BANKNIFTY Options  [Paused]  Amibroker · BOTH · 4 pos       │
│  ►  P&L: +₹7,250  (collapsed, click to expand)                 │
│                                                                  │
│  ○ Swing Equity  [Inactive]  Python · SHORT · 0 pos            │
│  ►  (collapsed)                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
frontend/src/
├── pages/strategy/
│   ├── StrategyHub.tsx              # Main page (replaces all 5 old pages)
│   └── index.ts                     # Barrel export
├── api/
│   └── strategy-dashboard.ts       # REST API (11 methods, all with ?type=webhook)
├── types/
│   └── strategy-dashboard.ts       # All TypeScript interfaces (~326 lines)
├── stores/
│   └── strategyDashboardStore.ts   # Zustand store for real-time state
├── hooks/
│   └── useStrategySocket.ts        # SocketIO hook for strategy rooms
└── components/strategy-dashboard/
    ├── DashboardHeader.tsx          # Summary cards + New Strategy button
    ├── StrategyCard.tsx             # Collapsible card with 5-tab interface
    ├── OverviewTab.tsx              # Strategy config + webhook + symbol CRUD
    ├── PositionTable.tsx            # Live position table
    ├── PositionRow.tsx              # Memoized row with flash animation
    ├── OrdersPanel.tsx              # Inline orders table (was in drawer)
    ├── TradesPanel.tsx              # Inline trades table with P&L footer
    ├── PnlPanel.tsx                 # P&L analytics (cards + chart + metrics)
    ├── CreateStrategyDialog.tsx     # New strategy dialog
    ├── StatusBadge.tsx              # Color-coded exit/state badges
    ├── RiskBadges.tsx               # SL/TGT/TSL/BE inline badges
    ├── EquityCurveChart.tsx         # Recharts equity curve
    ├── ExitBreakdownTable.tsx       # Exit reason aggregation table
    ├── MetricsGrid.tsx              # Risk metrics card grid
    ├── RiskConfigDrawer.tsx         # Risk config side panel (Sheet)
    ├── OrdersDrawer.tsx             # Legacy — still used externally
    ├── TradesDrawer.tsx             # Legacy — still used externally
    ├── PnLDrawer.tsx                # Legacy — still used externally
    └── EmptyState.tsx               # No strategies / no positions state
```

**Deleted files (old pages):**
- `pages/strategy/StrategyIndex.tsx`
- `pages/strategy/NewStrategy.tsx`
- `pages/strategy/ViewStrategy.tsx`
- `pages/strategy/ConfigureSymbols.tsx`
- `pages/strategy/StrategyDashboard.tsx`

---

## Data Architecture

### Three-Layer Data Flow

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

1. **TanStack Query** fetches `strategyDashboardApi.getDashboard()` on mount → initial snapshot
2. **Zustand store** is seeded with REST data via `setDashboardData(strategies, summary)`
3. **SocketIO** (`useStrategySocket`) joins per-strategy rooms and pushes live updates:
   - `strategy_position_update` → updates LTP, P&L, SL/TGT/TSL, state
   - `strategy_pnl_update` → updates aggregate P&L per strategy
   - `strategy_exit_triggered` → toast notification
   - `strategy_circuit_breaker` → circuit breaker banner
4. **Components** read from Zustand (not TanStack Query) for all real-time values

### Why Zustand + TanStack Query?

TanStack Query is great for request-response data (cache, refetch, loading states). But SocketIO pushes 3+ updates/second — TanStack's cache isn't designed for that frequency. Zustand's synchronous `set()` handles high-frequency mutations. Components subscribe to slices and re-render only when their slice changes.

---

## API Layer

**File:** `frontend/src/api/strategy-dashboard.ts`

All methods (except `getDashboard`) accept a `strategyType` parameter defaulting to `'webhook'`, appended as `?type=webhook` query parameter. This allows the same API to be reused for Chartink strategies later.

| Method | HTTP | Endpoint | Notes |
|--------|------|----------|-------|
| `getDashboard` | GET | `/strategy/api/dashboard` | Aggregates all types |
| `getPositions` | GET | `/strategy/api/strategy/:id/positions?type=` | Optional `include_closed` |
| `getOrders` | GET | `/strategy/api/strategy/:id/orders?type=` | |
| `getTrades` | GET | `/strategy/api/strategy/:id/trades?type=` | |
| `getPnL` | GET | `/strategy/api/strategy/:id/pnl?type=` | Returns metrics + chart data |
| `updateRiskConfig` | PUT | `/strategy/api/strategy/:id/risk?type=` | |
| `activateRisk` | POST | `/strategy/api/strategy/:id/risk/activate?type=` | |
| `deactivateRisk` | POST | `/strategy/api/strategy/:id/risk/deactivate?type=` | |
| `closePosition` | POST | `/strategy/api/strategy/:id/position/:pid/close?type=` | |
| `closeAllPositions` | POST | `/strategy/api/strategy/:id/positions/close-all?type=` | |
| `deletePosition` | DELETE | `/strategy/api/strategy/:id/position/:pid?type=` | |

Strategy CRUD methods (create, toggle, delete, symbol mappings) use the separate `strategyApi` from `api/strategy.ts`.

---

## Component Details

### StrategyHub (Page)

**File:** `pages/strategy/StrategyHub.tsx`

The main page. Orchestrates:
- TanStack Query → Zustand store initialization
- `useStrategySocket(strategyIds)` for live updates
- `DashboardHeader` with summary cards
- List of `StrategyCard` components
- `RiskConfigDrawer` (page-level, opens on demand)
- `CreateStrategyDialog` (triggered by header button)
- Auto-expand via `?expand=<id>` URL param
- Loading skeleton, error state with retry

### StrategyCard

**File:** `components/strategy-dashboard/StrategyCard.tsx`

Collapsible card using shadcn `Collapsible`. Each card has:

**Header (always visible):**
- Status dot (green=active, amber=paused, gray=inactive) with pulse animation when active
- Strategy name + badges (platform, trading mode, intraday/positional)
- Active position count + trade count today
- Live P&L (color-coded, `font-mono tabular-nums`)
- Win rate + profit factor (when available)
- Chevron toggle

**Expanded content — 5-tab interface:**

| Tab | Component | Data Source | Loading |
|-----|-----------|-------------|---------|
| Overview | `OverviewTab` | `strategyApi.getStrategy()` + host config fetch | Skeleton |
| Positions | `PositionTable` + action bar | Zustand store (live) | Immediate |
| Orders | `OrdersPanel` | `useQuery(['strategy-orders', id])` | Skeleton |
| Trades | `TradesPanel` | `useQuery(['strategy-trades', id])` | Skeleton |
| P&L | `PnlPanel` | `useQuery(['strategy-pnl', id])` | Skeleton |

**Lazy tab loading:** Uses `useRef<Set<string>>` initialized with `['positions']`. Each tab's content only renders after first activation — prevents unnecessary API calls for tabs the user never opens.

**Action bar (Positions tab):**
- Close All Positions (AlertDialog confirm)
- Risk Config (opens RiskConfigDrawer)
- Activate/Deactivate risk monitoring

### OverviewTab

**File:** `components/strategy-dashboard/OverviewTab.tsx` (~812 lines — the largest component)

Combines everything from the old `ViewStrategy` + `ConfigureSymbols` pages:

1. **Two-column grid:**
   - **Left card — Strategy Details:** Status, type (Intraday/Positional), trading mode (LONG/SHORT/BOTH with icons), platform, trading hours (if intraday)
   - **Right card — Webhook Config:** URL with copy button, credentials collapsible (non-TradingView), TradingView alert format snippet

2. **Circuit Breaker Card** (if configured): Daily risk limits display + `CircuitBreakerBanner` component

3. **Symbol Mappings Card:**
   - Header: "Symbol Mappings (N)" + "Add Symbol" + "Bulk Import" buttons
   - Inline add form: Popover/Command symbol search + Exchange + Quantity + Product type
   - Bulk import: Dialog with CSV textarea
   - Table: Symbol, Exchange, Qty, Product, Delete action
   - Debounced symbol search (300ms) via `strategyApi.searchSymbols()`

4. **Manage Actions:** Activate/Deactivate strategy, Delete strategy (AlertDialog)

### OrdersPanel

**File:** `components/strategy-dashboard/OrdersPanel.tsx`

Standalone orders table (extracted from `OrdersDrawer`). Uses `useQuery` with key `['strategy-orders', strategyId]`.

- Stats row: total, buy/sell counts, complete/rejected badges
- Table columns: Time, Symbol, Action (colored Badge), Qty, Type, Status (icon + text), Avg Price, Entry/Exit
- Refresh button, skeleton loading, empty state

### TradesPanel

**File:** `components/strategy-dashboard/TradesPanel.tsx`

Standalone trades table with P&L footer. Uses `useQuery` with key `['strategy-trades', strategyId]`.

- Stats row: total, win/loss counts
- Table columns: Time, Symbol, Action, Qty, Price, Type, Exit Reason (StatusBadge), P&L (colored with TrendingUp/Down icon)
- Footer row: Total P&L
- Refresh button, skeleton loading, empty state

### PnlPanel

**File:** `components/strategy-dashboard/PnlPanel.tsx`

P&L analytics panel composing existing components. Uses `useQuery` with key `['strategy-pnl', strategyId]`.

Layout (vertical stack):
1. **P&L Summary Cards** — 3-column grid: Total P&L, Realized, Unrealized (all color-coded)
2. **Equity Curve Chart** — `EquityCurveChart` (Recharts ComposedChart)
3. **Metrics Grid** — `MetricsGrid` with `totalPnl` prop (bug fix)
4. **Exit Breakdown** — `ExitBreakdownTable` in a Card

### CreateStrategyDialog

**File:** `components/strategy-dashboard/CreateStrategyDialog.tsx`

Dialog for creating new strategies (extracted from `NewStrategy.tsx`).

- Form fields: Name (3-50 chars validation), Platform (Select), Strategy Type (Intraday/Positional), Trading Mode (LONG/SHORT/BOTH), Trading Hours (if intraday: start/end/squareoff)
- Final name preview: `platform_strategy_name`
- On submit: `strategyApi.createStrategy()` → `onCreated(strategyId)` → dashboard refetch

### DashboardHeader

**File:** `components/strategy-dashboard/DashboardHeader.tsx`

Page header with:
- Title: "Strategy Hub" (changed from "Strategy Dashboard")
- Connection status dot (green/amber/red) + label
- "New Strategy" button (when `onCreateStrategy` prop provided)
- Refresh button with spin animation
- 4 summary cards (2x2 mobile, 4-col desktop): Active strategies, Paused strategies, Open positions, Total P&L (color-coded)

---

## Key Design Decisions

### Inline Tabs vs Drawers

The old dashboard used right-side Sheet drawers for Orders/Trades/P&L. The new design uses inline tab panels because:
- Drawers obscure the live position table — traders lose ambient awareness
- Tab switching is faster than open/close drawer animations
- Lazy loading ensures no performance penalty — tabs fetch on first activation only
- RiskConfigDrawer stays as a drawer (complex form benefits from overlay pattern)

### Dialog vs Page for Create

Strategy creation moved from a full page (`/strategy/new`) to a Dialog because:
- It's a short form (5-6 fields) — doesn't need a full page
- User stays in context (can see existing strategies behind the dialog)
- Follows the pattern used by Flow editor for creating new flows

### React.memo on PositionRow

With 10 strategies × 5 positions = 50 rows and SocketIO updates at 300ms, naive rendering causes 50 re-renders per update. `React.memo` ensures only the changed row re-renders. Flash animation uses a separate Map so only the updated position gets the visual effect.

### Lazy Tab Loading

```typescript
const loadedTabs = useRef(new Set<string>(['positions']))
const [activeTab, setActiveTab] = useState('positions')

const handleTabChange = (value: string) => {
  setActiveTab(value)
  loadedTabs.current.add(value)
}

// In render:
<TabsContent value="orders">
  {loadedTabs.current.has('orders') && (
    <OrdersPanel strategyId={strategy.id} strategyName={strategy.name} />
  )}
</TabsContent>
```

This ensures Orders/Trades/P&L only fetch their data when the user first clicks their tab. Positions tab is pre-loaded (most common view).

---

## Bug Fixes Applied

### 1. MetricsGrid Total P&L

**File:** `MetricsGrid.tsx`

**Bug:** `metrics.best_trade + metrics.worst_trade` displayed as "Total P&L" — mathematically wrong.

**Fix:** Added `totalPnl?: number` prop. Callers pass the actual total P&L from the API response.

### 2. PositionRow Closing State

**File:** `PositionRow.tsx`

**Bug:** `setClosing(true)` on click but never reset to false. `onClose` was fire-and-forget.

**Fix:** Changed `onClose` signature to `(positionId: number) => Promise<void>`. Uses `.finally(() => setClosing(false))`. Close button disabled during closing, shows spinner.

### 3. API Missing ?type= Parameter

**File:** `strategy-dashboard.ts`

**Bug:** Backend expects `?type=webhook` but frontend never sent it.

**Fix:** Added `strategyType = 'webhook'` default parameter to all methods, using `URLSearchParams` for clean construction.

---

## SocketIO Events

| Event | Direction | Payload | Action |
|-------|-----------|---------|--------|
| `join` | Client → Server | `strategy_{id}` | Subscribe to room |
| `leave` | Client → Server | `strategy_{id}` | Unsubscribe |
| `strategy_position_update` | Server → Client | `PositionUpdatePayload` | Update position in Zustand |
| `strategy_pnl_update` | Server → Client | `PnLUpdatePayload` | Update aggregate P&L |
| `strategy_exit_triggered` | Server → Client | `ExitTriggeredPayload` | Toast notification |
| `strategy_position_opened` | Server → Client | Position data | Info toast |
| `strategy_position_closed` | Server → Client | Position + P&L | Success/error toast |
| `strategy_order_rejected` | Server → Client | Order data | Error toast |
| `strategy_circuit_breaker` | Server → Client | CB event | Banner display/clear |

---

## Daily Circuit Breaker Integration

### DashboardStrategy Fields

```typescript
daily_stoploss_type?: string    // "points" only in V1
daily_stoploss_value?: number
daily_target_type?: string
daily_target_value?: number
daily_trailstop_type?: string
daily_trailstop_value?: number
```

### Enhanced PnL Update Event

```typescript
interface StrategyPnlUpdate {
  strategy_id: number
  strategy_type: string
  total_unrealized_pnl: number
  position_count: number
  daily_realized_pnl: number
  daily_total_pnl: number
  circuit_breaker_active: boolean
  circuit_breaker_reason: string
}
```

### Circuit Breaker Alert

When tripped: Red banner with `AlertTriangle` icon below strategy header, above positions table. Stays visible until daily reset (09:00 IST). Shows reason and daily P&L at trip time.

---

## Route Configuration

**File:** `App.tsx`

```tsx
// Single lazy import
const StrategyHub = lazy(() => import('@/pages/strategy/StrategyHub'))

// Single route (replaces 5 old routes)
<Route path="/strategy" element={<StrategyHub />} />
```

Old routes removed: `/strategy/new`, `/strategy/:strategyId`, `/strategy/:strategyId/configure`, `/strategy/dashboard`

---

## Verification

```bash
cd frontend && npx tsc --noEmit      # Type check passes
cd frontend && npm run lint           # No new lint warnings
cd frontend && npm test               # 48/48 tests pass
cd frontend && npm run build          # Production build succeeds
```