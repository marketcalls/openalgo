# Strategy Dashboard UI — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an ultra-modern, real-time Strategy Risk Management dashboard — a completely new UI module that gives traders live visibility into strategy positions, P&L, risk triggers, and analytics.

**Architecture:** Single-page dashboard at `/strategy/dashboard` with collapsible strategy cards, live-updating position tables via SocketIO, slide-out drawers for orders/trades/analytics, and a dedicated Zustand store for real-time state. All data is push-based (no polling) — backend SocketIO events drive every LTP, P&L, SL, TGT, and TSL update.

**Tech Stack:** React 19, TypeScript, Vite, shadcn/ui (new-york), TanStack Query v5, Socket.IO Client, Zustand, Recharts (new dependency), Tailwind CSS 4, lucide-react

**PRD Reference:** `docs/plans/2026-02-06-strategy-risk-management-prd.md` — Sections 12, 14, 15

---

## Design Philosophy

**Modern Trading Terminal Aesthetic:**
- Dense but readable — font-mono tabular-nums for all numeric columns
- Real-time feel — color flash on value changes (green pulse on profit increase, red on loss)
- Dark mode first — designed to look stunning in dark theme, works in light
- Minimal chrome — data-dense cards, no wasted whitespace
- Progressive disclosure — summary → expand card → open drawer for deep dive
- Mobile responsive — summary cards stack, tables scroll horizontally

**Key UX Patterns:**
- **Optimistic updates** — clicking "Close" immediately shows "Exiting..." spinner
- **SocketIO-first** — REST only for initial snapshot, then pure push
- **Strategy rooms** — join SocketIO room per expanded strategy to minimize traffic
- **Stale data indicators** — amber border if data hasn't updated in 30s
- **Zero-config** — dashboard auto-discovers all strategies with `risk_monitoring != null`

---

## File Structure

```
frontend/src/
├── pages/strategy/
│   └── StrategyDashboard.tsx          # Main dashboard page
├── api/
│   └── strategy-dashboard.ts          # REST API layer for initial data
├── types/
│   └── strategy-dashboard.ts          # All TypeScript interfaces
├── stores/
│   └── strategyDashboardStore.ts      # Zustand store for real-time state
├── hooks/
│   └── useStrategySocket.ts           # SocketIO hook for strategy events
└── components/strategy-dashboard/
    ├── DashboardHeader.tsx            # Summary cards + page header
    ├── StrategyCard.tsx               # Collapsible strategy card
    ├── PositionTable.tsx              # Live position table
    ├── PositionRow.tsx                # Memoized row with flash animation
    ├── StatusBadge.tsx                # Color-coded exit/state badges
    ├── RiskBadges.tsx                 # SL/TGT/TSL/BE inline badges
    ├── OrdersDrawer.tsx               # Strategy orders side panel
    ├── TradesDrawer.tsx               # Strategy trades side panel
    ├── PnLDrawer.tsx                  # P&L analytics panel
    ├── EquityCurveChart.tsx           # Line + area chart (Recharts)
    ├── ExitBreakdownTable.tsx         # Exit reason aggregation
    ├── MetricsGrid.tsx                # Risk metrics card grid
    ├── RiskConfigDrawer.tsx           # Edit SL/TGT/TSL defaults
    └── EmptyState.tsx                 # No strategies / no positions state
```

**Modified existing files:**
- `frontend/src/App.tsx` — add route
- `frontend/src/hooks/useSocket.ts` — add strategy risk event handlers
- `frontend/src/stores/alertStore.ts` — add `strategyRisk` alert category

---

## Task 1: TypeScript Types & Interfaces

**Files:**
- Create: `frontend/src/types/strategy-dashboard.ts`

**What:** Define all TypeScript interfaces for the dashboard. This is the contract between backend API, SocketIO events, and React components.

**Types to define:**

```typescript
// ── Position & Risk State ──────────────────────────

export type PositionState = 'pending_entry' | 'active' | 'exiting' | 'closed'

export type ExitReason =
  | 'stoploss' | 'target' | 'trailstop' | 'breakeven_sl'
  | 'combined_sl' | 'combined_target' | 'combined_trailstop'
  | 'manual' | 'squareoff' | 'auto_squareoff' | 'rejected'

export type RiskMonitoringState = 'active' | 'paused' | null

export interface StrategyPosition {
  id: number
  strategy_id: number
  strategy_type: string
  symbol: string
  exchange: string
  product_type: 'MIS' | 'CNC' | 'NRML'
  action: 'BUY' | 'SELL'
  quantity: number
  average_entry_price: number
  ltp: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  realized_pnl: number
  stoploss_price: number | null
  target_price: number | null
  trailstop_price: number | null
  peak_price: number | null
  breakeven_activated: boolean
  position_state: PositionState
  exit_reason: ExitReason | null
  exit_detail: string | null
  exit_price: number | null
  group_id: number | null
  opened_at: string
  closed_at: string | null
}

// ── Strategy Dashboard ─────────────────────────────

export interface DashboardStrategy {
  id: number
  name: string
  webhook_id: string
  platform: string
  trading_mode: string
  is_active: boolean
  is_intraday: boolean
  risk_monitoring: RiskMonitoringState
  auto_squareoff_time: string | null

  // Risk defaults
  default_stoploss_type: string | null
  default_stoploss_value: number | null
  default_target_type: string | null
  default_target_value: number | null
  default_trailstop_type: string | null
  default_trailstop_value: number | null
  default_breakeven_type: string | null
  default_breakeven_threshold: number | null
  default_exit_execution: string

  // Live aggregated (updated via SocketIO)
  positions: StrategyPosition[]
  total_pnl: number
  realized_pnl: number
  unrealized_pnl: number
  trade_count_today: number
  order_count: number
  win_rate: number | null
  profit_factor: number | null
}

export interface DashboardSummary {
  active_strategies: number
  paused_strategies: number
  open_positions: number
  total_pnl: number
}

export interface DashboardResponse {
  strategies: DashboardStrategy[]
  summary: DashboardSummary
}

// ── Orders & Trades ────────────────────────────────

export interface StrategyOrder {
  id: number
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number | null
  trigger_price: number | null
  price_type: string
  product_type: string
  order_status: string
  average_price: number | null
  filled_quantity: number | null
  exit_reason: ExitReason | null
  created_at: string
  updated_at: string
}

export interface StrategyTrade {
  id: number
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  trade_value: number
  product_type: string
  trade_type: 'entry' | 'exit'
  exit_reason: ExitReason | null
  pnl: number | null
  created_at: string
}

// ── P&L Analytics ──────────────────────────────────

export interface RiskMetrics {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  average_win: number
  average_loss: number
  risk_reward_ratio: number
  profit_factor: number
  expectancy: number
  best_trade: number
  worst_trade: number
  max_consecutive_wins: number
  max_consecutive_losses: number
  max_drawdown: number
  max_drawdown_pct: number
  current_drawdown: number
  current_drawdown_pct: number
  best_day: number
  worst_day: number
  average_daily_pnl: number
  days_active: number
}

export interface ExitBreakdownEntry {
  exit_reason: string
  count: number
  total_pnl: number
  avg_pnl: number
}

export interface DailyPnLEntry {
  date: string
  total_pnl: number
  cumulative_pnl: number
  drawdown: number
}

export interface PnLResponse {
  pnl: {
    total_pnl: number
    realized_pnl: number
    unrealized_pnl: number
  }
  risk_metrics: RiskMetrics
  exit_breakdown: ExitBreakdownEntry[]
  daily_pnl: DailyPnLEntry[]
}

// ── SocketIO Event Payloads ────────────────────────

export interface PositionUpdatePayload {
  position_id: number
  strategy_id: number
  symbol: string
  exchange: string
  ltp: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  stoploss_price: number | null
  target_price: number | null
  trailstop_price: number | null
  peak_price: number | null
  breakeven_activated: boolean
  position_state: PositionState
  exit_reason: ExitReason | null
  exit_detail: string | null
}

export interface PnLUpdatePayload {
  strategy_id: number
  total_pnl: number
  realized_pnl: number
  unrealized_pnl: number
  open_positions: number
  closed_positions: number
}

export interface ExitTriggeredPayload {
  strategy_id: number
  position_id: number
  symbol: string
  exit_reason: ExitReason
  exit_detail: string
  trigger_price: number
}

// ── Risk Configuration ─────────────────────────────

export interface RiskConfigUpdate {
  default_stoploss_type?: string | null
  default_stoploss_value?: number | null
  default_target_type?: string | null
  default_target_value?: number | null
  default_trailstop_type?: string | null
  default_trailstop_value?: number | null
  default_breakeven_type?: string | null
  default_breakeven_threshold?: number | null
  default_exit_execution?: string
  auto_squareoff_time?: string | null
  risk_monitoring?: string
}
```

**Verification:** `cd frontend && npx tsc --noEmit` — no type errors.

---

## Task 2: API Layer

**Files:**
- Create: `frontend/src/api/strategy-dashboard.ts`

**What:** REST API functions for initial data load and mutations. Follows existing `webClient` pattern with CSRF handling.

**Endpoints to implement:**

```typescript
import { webClient } from './client'
import type {
  DashboardResponse,
  StrategyPosition,
  StrategyOrder,
  StrategyTrade,
  PnLResponse,
  RiskConfigUpdate,
} from '@/types/strategy-dashboard'
import type { ApiResponse } from '@/types/trading'

export const strategyDashboardApi = {
  // Dashboard snapshot (initial load)
  getDashboard: async (): Promise<DashboardResponse> => {
    const response = await webClient.get<DashboardResponse>('/strategy/api/dashboard')
    return response.data
  },

  // Strategy positions
  getPositions: async (strategyId: number, includeClosed = false): Promise<StrategyPosition[]> => {
    const params = includeClosed ? '?include_closed=true' : ''
    const response = await webClient.get<{ positions: StrategyPosition[] }>(
      `/strategy/api/strategy/${strategyId}/positions${params}`
    )
    return response.data.positions || []
  },

  // Strategy orders
  getOrders: async (strategyId: number): Promise<StrategyOrder[]> => {
    const response = await webClient.get<{ orders: StrategyOrder[] }>(
      `/strategy/api/strategy/${strategyId}/orders`
    )
    return response.data.orders || []
  },

  // Strategy trades
  getTrades: async (strategyId: number): Promise<StrategyTrade[]> => {
    const response = await webClient.get<{ trades: StrategyTrade[] }>(
      `/strategy/api/strategy/${strategyId}/trades`
    )
    return response.data.trades || []
  },

  // P&L analytics
  getPnL: async (strategyId: number): Promise<PnLResponse> => {
    const response = await webClient.get<PnLResponse>(
      `/strategy/api/strategy/${strategyId}/pnl`
    )
    return response.data
  },

  // Risk configuration
  updateRiskConfig: async (strategyId: number, config: RiskConfigUpdate): Promise<ApiResponse<void>> => {
    const response = await webClient.put<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk`,
      config
    )
    return response.data
  },

  // Activate/deactivate risk monitoring
  activateRisk: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk/activate`
    )
    return response.data
  },

  deactivateRisk: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk/deactivate`
    )
    return response.data
  },

  // Manual close
  closePosition: async (strategyId: number, positionId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/position/${positionId}/close`
    )
    return response.data
  },

  closeAllPositions: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/positions/close-all`
    )
    return response.data
  },

  // Delete closed position
  deletePosition: async (strategyId: number, positionId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.delete<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/position/${positionId}`
    )
    return response.data
  },
}
```

**Verification:** TypeScript compiles, import resolves.

---

## Task 3: Zustand Store for Real-Time State

**Files:**
- Create: `frontend/src/stores/strategyDashboardStore.ts`

**What:** Zustand store that holds the live dashboard state. REST provides initial snapshot; SocketIO events mutate state in real-time. React components subscribe to slices.

**Design rationale:** TanStack Query manages REST fetches (cache, refetch, loading states). Zustand holds the **live** state that gets mutated by SocketIO events every 300ms. Components read from Zustand for real-time values.

```typescript
import { create } from 'zustand'
import type {
  DashboardStrategy,
  DashboardSummary,
  PositionUpdatePayload,
  PnLUpdatePayload,
  StrategyPosition,
} from '@/types/strategy-dashboard'

interface StrategyDashboardState {
  // Data
  strategies: DashboardStrategy[]
  summary: DashboardSummary
  initialized: boolean
  connectionStatus: 'connected' | 'disconnected' | 'stale'

  // Expanded strategy cards (UI state)
  expandedStrategies: Set<number>

  // Flash tracking for value changes
  flashPositions: Map<number, 'profit' | 'loss'>

  // Actions — REST snapshot
  setDashboardData: (strategies: DashboardStrategy[], summary: DashboardSummary) => void

  // Actions — SocketIO live updates
  updatePosition: (payload: PositionUpdatePayload) => void
  updateStrategyPnL: (payload: PnLUpdatePayload) => void
  addPosition: (strategyId: number, position: StrategyPosition) => void
  removePosition: (strategyId: number, positionId: number) => void

  // Actions — UI
  toggleExpanded: (strategyId: number) => void
  setConnectionStatus: (status: 'connected' | 'disconnected' | 'stale') => void
  clearFlash: (positionId: number) => void
}
```

**Key implementation details:**
- `updatePosition()` — finds position by ID across all strategies, updates LTP/PnL/SL/TGT/TSL, triggers flash animation via `flashPositions` Map, recomputes strategy summary
- `updateStrategyPnL()` — updates aggregate PnL per strategy and recalculates `summary.total_pnl`
- Flash map entries auto-clear after 500ms via `setTimeout` in `clearFlash()`
- `expandedStrategies` tracks which strategy cards are open (persisted to sessionStorage)
- All updates are immutable — new arrays/objects to trigger React re-renders

**Verification:** Store creates, actions mutate state correctly.

---

## Task 4: SocketIO Hook for Strategy Events

**Files:**
- Create: `frontend/src/hooks/useStrategySocket.ts`
- Modify: `frontend/src/stores/alertStore.ts` — add `strategyRisk` category

**What:** Custom hook that connects to strategy SocketIO rooms, receives events, and dispatches to Zustand store. Also fires toast notifications for user-facing events.

**Hook design:**

```typescript
import { useEffect, useRef } from 'react'
import { io, type Socket } from 'socket.io-client'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'
import { useAlertStore } from '@/stores/alertStore'
import type { PositionUpdatePayload, PnLUpdatePayload, ExitTriggeredPayload } from '@/types/strategy-dashboard'

export function useStrategySocket(strategyIds: number[]) {
  const socketRef = useRef<Socket | null>(null)
  const store = useStrategyDashboardStore()

  useEffect(() => {
    // Connect (reuse existing socket pattern — polling transport)
    const socket = io(/* same as useSocket.ts */)
    socketRef.current = socket

    // Join strategy rooms
    strategyIds.forEach(id => socket.emit('join', `strategy_${id}`))

    // Silent data events → Zustand store
    socket.on('strategy_position_update', (data: PositionUpdatePayload) => {
      store.updatePosition(data)
    })

    socket.on('strategy_pnl_update', (data: PnLUpdatePayload) => {
      store.updateStrategyPnL(data)
    })

    // User-facing toast events
    socket.on('strategy_exit_triggered', (data: ExitTriggeredPayload) => {
      // Show toast with exit reason badge color
      // Play alert sound via alertStore
    })

    socket.on('strategy_position_opened', (data) => { /* info toast */ })
    socket.on('strategy_position_closed', (data) => { /* success/error toast by PnL */ })
    socket.on('strategy_order_rejected', (data) => { /* error toast */ })
    socket.on('strategy_risk_paused', (data) => {
      store.setConnectionStatus('stale')
      // warning toast
    })
    socket.on('strategy_risk_resumed', (data) => {
      store.setConnectionStatus('connected')
    })

    // Cleanup: leave rooms, disconnect
    return () => {
      strategyIds.forEach(id => socket.emit('leave', `strategy_${id}`))
      socket.disconnect()
    }
  }, [strategyIds.join(',')])

  return { socket: socketRef.current }
}
```

**Alert category addition** to `alertStore.ts`:
- Add `strategyRisk: boolean` to `AlertCategories` interface
- Add `strategyRisk: true` to `DEFAULT_STATE.categories`

**Verification:** Hook connects, receives mock events, store updates.

---

## Task 5: Install Recharts Dependency

**Files:**
- Modify: `frontend/package.json`

**What:** Install Recharts for the equity curve and drawdown charts in the P&L drawer. Recharts is the standard React charting library — lightweight, composable, works with shadcn/ui dark mode.

**Command:**
```bash
cd frontend && npm install recharts
```

**Why Recharts over alternatives:**
- Already a React-native library (no wrapper needed)
- Composable: `<LineChart>`, `<AreaChart>`, `<ResponsiveContainer>` etc.
- Dark mode support via CSS variables
- Lightweight (~45KB gzip)
- The codebase already uses `lightweight-charts` for candlestick/historify, but Recharts is better suited for statistical line/area charts

**Verification:** `npm ls recharts` shows installed version.

---

## Task 6: StatusBadge + RiskBadges Components

**Files:**
- Create: `frontend/src/components/strategy-dashboard/StatusBadge.tsx`
- Create: `frontend/src/components/strategy-dashboard/RiskBadges.tsx`

**What:** Small, reusable components for the position table. These are the visual building blocks.

### StatusBadge.tsx

Maps `position_state` + `exit_reason` to a color-coded badge:

| State | Badge Text | Color | Animation |
|-------|-----------|-------|-----------|
| `active` + risk=active | `Monitoring` | blue | — |
| `active` + risk=paused | `Paused` | amber | — |
| `exiting` | `Exiting...` | amber | pulse |
| `closed` + `stoploss` | `SL` | red | — |
| `closed` + `target` | `TGT` | green | — |
| `closed` + `trailstop` | `TSL` | amber | — |
| `closed` + `breakeven_sl` | `BE-SL` | blue | — |
| `closed` + `combined_sl` | `C-SL` | red | — |
| `closed` + `combined_target` | `C-TGT` | green | — |
| `closed` + `combined_trailstop` | `C-TSL` | amber | — |
| `closed` + `manual` | `Manual` | gray | — |
| `closed` + `squareoff` | `SQ-OFF` | gray | — |
| `closed` + `rejected` | `Failed` | red | pulse |

Uses shadcn `Badge` component with custom className for each color variant. The `pulse` animation uses Tailwind's `animate-pulse` class.

### RiskBadges.tsx

Inline display of SL/TGT/TSL/BE for the position row:

```tsx
interface RiskBadgesProps {
  stoploss: number | null
  target: number | null
  trailstop: number | null
  breakeven: boolean
}
```

- SL: red monospace text, or `—` if null
- TGT: green monospace text, or `—` if null
- TSL: amber monospace text, or `—` if null
- BE: blue "BE" micro-badge when `breakeven === true`

**Verification:** Render both components with various props, visual check.

---

## Task 7: PositionRow (Memoized) + PositionTable

**Files:**
- Create: `frontend/src/components/strategy-dashboard/PositionRow.tsx`
- Create: `frontend/src/components/strategy-dashboard/PositionTable.tsx`

**What:** The core data display. PositionRow is `React.memo`'d for performance — only re-renders when its specific position data changes. PositionTable wraps rows in a shadcn Table.

### PositionRow.tsx

```tsx
const PositionRow = React.memo(function PositionRow({
  position,
  flash,
  onClose,
  riskMonitoring,
}: {
  position: StrategyPosition
  flash: 'profit' | 'loss' | null
  onClose: (positionId: number) => void
  riskMonitoring: RiskMonitoringState
}) {
  // ...
})
```

**Columns:**
| Column | Formatting | Notes |
|--------|-----------|-------|
| Symbol | `font-medium` | Left-aligned |
| Qty | `+100` green / `-50` red | `tabular-nums` |
| Avg | `₹800.00` | `font-mono tabular-nums` |
| LTP | `₹812.50` | `font-mono tabular-nums`, flash overlay |
| P&L | `+₹1,250` / `-₹800` | green/red, arrow icon |
| SL | `784.00` | red `font-mono`, from RiskBadges |
| TGT | `840.00` | green `font-mono`, from RiskBadges |
| TSL | `792.00` / `—` | amber `font-mono`, from RiskBadges |
| Status | Badge | From StatusBadge |
| Action | Close button | Disabled when qty=0 or state=exiting |

**Flash animation:**
- When `flash` prop is set, row gets a 500ms overlay:
  - `'profit'` → `bg-green-500/10` fade
  - `'loss'` → `bg-red-500/10` fade
- CSS transition: `transition-colors duration-500`

**Close button:**
- Shows `X` icon when active
- Shows `Loader2` spinner with `animate-spin` when state=`exiting`
- Disabled when `quantity === 0`
- Wrapped in AlertDialog for confirmation: "Close SBIN position at MARKET?"

### PositionTable.tsx

```tsx
function PositionTable({
  positions,
  flashMap,
  riskMonitoring,
  onClosePosition,
}: Props)
```

- Uses shadcn `Table`, `TableHeader`, `TableBody`, `TableRow`, `TableHead`, `TableCell`
- Responsive: wraps in `<div className="relative w-full overflow-x-auto">`
- Empty state: "No open positions" with subtle icon
- Sorts: active positions first, then by opened_at desc

**Verification:** Render table with mock positions, verify flash animation, close button states.

---

## Task 8: StrategyCard Component

**Files:**
- Create: `frontend/src/components/strategy-dashboard/StrategyCard.tsx`

**What:** The main repeating unit on the dashboard. Each strategy gets a collapsible card with header summary, position table, and action buttons.

**Layout:**
```
┌─ 2px colored top bar (green=active, amber=paused, gray=inactive) ─┐
│                                                                     │
│  [●] Nifty Momentum           P&L: +₹1,150    [Deactivate ▼]      │
│  TradingView · LONG · Intraday   2 positions · 4 trades today     │
│                                                                     │
│  ─── Position Table (when expanded) ─────────────────────────────  │
│  Symbol  Qty   Avg      LTP      P&L     SL   TGT  TSL  Status   │
│  SBIN    +100  800.00   812.50   +1,250  784  840  792  Monitor   │
│  INFY    +50   1520.00  1498.00  -1,100  1490 1596 —    Monitor   │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                     │
│  [Close All]   [Orders 8]   [Trades 4]   [P&L]   [Risk Config]    │
└─────────────────────────────────────────────────────────────────────┘
```

**Key behaviors:**
- **Collapsed state (default):** Shows header with strategy name, P&L summary line, status dot
- **Expanded state:** Click card header to expand — shows position table + action buttons
- **Expand/collapse animation:** Uses shadcn `Collapsible` with smooth height transition
- **Top bar color:** 2px top border — green (#22c55e) for active risk monitoring, amber (#f59e0b) for paused, gray for no risk monitoring
- **Status dot:** Animated pulse when active (like a heartbeat indicator)

**Header elements:**
- Strategy name (bold, `text-lg`)
- Platform + mode + type badges (small, `text-muted-foreground`)
- Live P&L value (large, color-coded, `tabular-nums`)
- Activate/Deactivate button (uses AlertDialog confirmation)
- Position count + trade count today (summary line)
- Win rate + profit factor (if available, small badges)

**Action bar (below position table):**
- `[Close All Positions]` — red variant, AlertDialog confirmation: "Close all N positions at MARKET?"
- `[Orders N]` — opens OrdersDrawer
- `[Trades N]` — opens TradesDrawer
- `[P&L]` — opens PnLDrawer
- `[Risk Config]` — opens RiskConfigDrawer (gear icon)

**Verification:** Render with mock data, test expand/collapse, action buttons open drawers.

---

## Task 9: DashboardHeader Component

**Files:**
- Create: `frontend/src/components/strategy-dashboard/DashboardHeader.tsx`

**What:** Page header with summary stat cards and controls.

**Layout:**
```
Strategy Dashboard                              [Refresh] [Export CSV]

┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Active: 3   │ │   Paused: 1  │ │   Open: 8    │ │  Total P&L   │
│  strategies   │ │  strategies  │ │  positions   │ │  +₹4,250 ▲   │
└──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘
```

**Summary cards:**
- 4 cards in a responsive grid: `grid grid-cols-2 md:grid-cols-4 gap-4`
- Each card: shadcn `Card` with icon, label (muted), value (bold, `text-2xl tabular-nums`)
- Total P&L card: color-coded green/red, larger font, with trend arrow icon
- Cards use `--profit` / `--loss` CSS variables for theming consistency

**Controls:**
- Refresh button: `RefreshCw` icon, rotates on click, re-fetches dashboard data
- Connection status indicator: small dot next to title (green=connected, amber=stale, red=disconnected)

**Responsive:**
- Mobile: 2x2 grid for cards, header stacks vertically
- Desktop: 4-column grid, header inline

**Verification:** Render with summary data, verify responsive layout.

---

## Task 10: OrdersDrawer + TradesDrawer

**Files:**
- Create: `frontend/src/components/strategy-dashboard/OrdersDrawer.tsx`
- Create: `frontend/src/components/strategy-dashboard/TradesDrawer.tsx`

**What:** Slide-out panels showing strategy-specific order book and trade book. Uses shadcn `Sheet` component (right-side panel).

### OrdersDrawer.tsx

- Opens as `Sheet` from right side, `w-full sm:w-[600px]`
- Header: "Orders — Strategy Name" with order count
- Stats row: Buy/Sell/Completed/Open/Rejected counts in mini badges
- Table columns: Time, Symbol, Action (BUY green/SELL red), Qty, Price, Type, Product, Status, OrderID
- Fetches from `strategyDashboardApi.getOrders(strategyId)` using TanStack Query
- Loading: Skeleton rows
- Empty: "No orders yet" illustration

### TradesDrawer.tsx

- Same Sheet pattern as OrdersDrawer
- Header: "Trades — Strategy Name" with trade count
- Table columns: Time, Symbol, Action, Qty, Price, Trade Value, Type (entry/exit), Exit Reason (badge), P&L
- P&L column: green/red with `font-mono tabular-nums`
- Exit reason: uses StatusBadge component for consistent styling
- Summary row at bottom: Total P&L, Winning/Losing trade counts

**Verification:** Open both drawers with mock data, verify table rendering.

---

## Task 11: PnLDrawer + EquityCurveChart + MetricsGrid + ExitBreakdownTable

**Files:**
- Create: `frontend/src/components/strategy-dashboard/PnLDrawer.tsx`
- Create: `frontend/src/components/strategy-dashboard/EquityCurveChart.tsx`
- Create: `frontend/src/components/strategy-dashboard/MetricsGrid.tsx`
- Create: `frontend/src/components/strategy-dashboard/ExitBreakdownTable.tsx`

**What:** The analytics deep-dive panel. This is the most content-rich drawer.

### PnLDrawer.tsx

- Opens as `Sheet` from right side, `w-full sm:w-[700px] lg:w-[800px]`
- Scrollable content area
- Sections (top to bottom):
  1. **P&L Summary Cards** — Total P&L, Realized, Unrealized (3 mini-cards)
  2. **Equity Curve Chart** — line chart of cumulative P&L over time
  3. **Metrics Grid** — 6x3 grid of risk metrics
  4. **Trade Statistics** — detailed trade stats
  5. **Exit Breakdown Table** — grouped by exit reason
- Fetches from `strategyDashboardApi.getPnL(strategyId)` using TanStack Query
- Loading: Skeleton placeholders for chart and metrics

### EquityCurveChart.tsx

Uses **Recharts** `ComposedChart`:
- **Line** for cumulative P&L (primary color, smooth curve)
- **Area** for drawdown (red, below zero axis, semi-transparent)
- **ResponsiveContainer** for auto-sizing
- **Tooltip** with formatted values (₹ currency)
- **XAxis** with date labels
- **YAxis** with currency formatting
- Dark mode: uses `hsl(var(--foreground))` for axis labels, `hsl(var(--muted))` for grid
- Chart height: 250px

```tsx
<ResponsiveContainer width="100%" height={250}>
  <ComposedChart data={dailyPnl}>
    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
    <XAxis dataKey="date" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
    <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" tickFormatter={formatCurrency} />
    <Tooltip content={<CustomTooltip />} />
    <Area dataKey="drawdown" fill="hsl(var(--loss))" fillOpacity={0.15} stroke="hsl(var(--loss))" strokeWidth={1} />
    <Line dataKey="cumulative_pnl" stroke="hsl(var(--profit))" strokeWidth={2} dot={false} />
  </ComposedChart>
</ResponsiveContainer>
```

### MetricsGrid.tsx

A grid of metric cards:
```
┌─────────────┐ ┌─────────────┐ ┌──────────────┐
│ Total P&L    │ │ Win Rate     │ │ Profit Factor│
│ +₹18,755     │ │ 63.3%        │ │ 2.68         │
└─────────────┘ └─────────────┘ └──────────────┘
┌─────────────┐ ┌─────────────┐ ┌──────────────┐
│ Max Drawdown │ │ Risk:Reward  │ │ Expectancy   │
│ -₹3,200(4.2%)│ │ 1:1.79       │ │ +₹485/trade  │
└─────────────┘ └─────────────┘ └──────────────┘
```

- 3-column grid: `grid grid-cols-2 sm:grid-cols-3 gap-3`
- Each metric: label (muted, small) + value (bold, mono, color-coded where applicable)
- P&L values: green/red
- Percentages: neutral unless negative (then red)
- Separate "Trade Statistics" section below with 2-column layout for detailed stats

### ExitBreakdownTable.tsx

Simple table:
| Exit Type | Count | Total P&L | Avg P&L |
|-----------|-------|-----------|---------|
| Target | 18 | +₹22,500 | +₹1,250 |
| Trailing Stop | 5 | +₹4,100 | +₹820 |
| Stoploss | 12 | -₹8,400 | -₹700 |

- Uses shadcn Table
- P&L columns: green/red color coding
- Exit type: uses StatusBadge variant for icon consistency

**Verification:** Open PnLDrawer with mock data, verify chart renders, metrics display correctly.

---

## Task 12: RiskConfigDrawer

**Files:**
- Create: `frontend/src/components/strategy-dashboard/RiskConfigDrawer.tsx`

**What:** Edit strategy risk defaults inline from the dashboard. Opens as a Sheet with a form.

**Form fields:**
```
Risk Configuration — Nifty Momentum

Stoploss
  Type:  [Percentage ▼]  [Points]  [None]
  Value: [2.0] %

Target
  Type:  [Percentage ▼]  [Points]  [None]
  Value: [5.0] %

Trailing Stop
  Type:  [Percentage ▼]  [Points]  [None]
  Value: [1.0] %

Breakeven
  Type:  [Percentage ▼]  [Points]  [None]
  Threshold: [1.5] %

Exit Execution: [Market ▼]
Auto Square-Off: [15:15]

[Save Changes]  [Cancel]
```

**Behavior:**
- Pre-populates from strategy's current risk defaults
- Type selectors are radio-style button groups (shadcn Tabs)
- Value input: numeric with `step="0.01"`, disabled when type=None
- Save calls `strategyDashboardApi.updateRiskConfig()` then refreshes dashboard
- Toast on success/error
- Form validation: value required when type is set, value > 0

**Verification:** Open drawer, edit values, save, verify API call and toast.

---

## Task 13: EmptyState Component

**Files:**
- Create: `frontend/src/components/strategy-dashboard/EmptyState.tsx`

**What:** Beautiful empty states for when there's no data.

**Variants:**
1. **No strategies with risk monitoring** — "No strategies are being monitored. Enable risk monitoring on a strategy to see it here." + link to `/strategy`
2. **No open positions** (within a strategy card) — "No open positions. Waiting for webhook signals..." + subtle animated pulse dots
3. **No trades yet** (in TradesDrawer) — "No trades recorded yet"
4. **No P&L data** (in PnLDrawer) — "Start trading to see analytics"

Each variant: centered layout, lucide icon, title, description, optional action button.

**Verification:** Render all variants.

---

## Task 14: Main Dashboard Page

**Files:**
- Create: `frontend/src/pages/strategy/StrategyDashboard.tsx`
- Modify: `frontend/src/App.tsx` — add route

**What:** The main page that assembles all components. This is the entry point.

**Page structure:**
```tsx
export default function StrategyDashboard() {
  // 1. Fetch initial data via TanStack Query
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['strategy-dashboard'],
    queryFn: strategyDashboardApi.getDashboard,
    refetchInterval: false, // SocketIO handles live updates
  })

  // 2. Initialize Zustand store with REST data
  useEffect(() => {
    if (data) {
      store.setDashboardData(data.strategies, data.summary)
    }
  }, [data])

  // 3. Connect SocketIO to strategy rooms
  const strategyIds = store.strategies.map(s => s.id)
  useStrategySocket(strategyIds)

  // 4. Read live state from Zustand (not TanStack Query)
  const { strategies, summary, expandedStrategies, flashPositions } = useStrategyDashboardStore()

  return (
    <div className="space-y-6">
      <DashboardHeader summary={summary} onRefresh={refetch} />

      {strategies.length === 0 ? (
        <EmptyState variant="no-strategies" />
      ) : (
        <div className="space-y-4">
          {strategies.map(strategy => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              isExpanded={expandedStrategies.has(strategy.id)}
              flashMap={flashPositions}
              onToggleExpand={() => store.toggleExpanded(strategy.id)}
            />
          ))}
        </div>
      )}
    </div>
  )
}
```

**Route addition in App.tsx:**
```tsx
// Add lazy import
const StrategyDashboard = lazy(() => import('@/pages/strategy/StrategyDashboard'))

// Add route inside <Layout> (after existing strategy routes)
<Route path="/strategy/dashboard" element={<StrategyDashboard />} />
```

**Loading state:**
- Full-page skeleton: header skeleton + 3 card skeletons (matching the Skeleton pattern from StrategyIndex)

**Error state:**
- If dashboard API fails: Alert component with retry button

**Verification:**
```bash
cd frontend && npm run build   # TypeScript compiles
cd frontend && npm run dev     # Navigate to /strategy/dashboard
```

---

## Task 15: Alert Store & Socket Integration

**Files:**
- Modify: `frontend/src/stores/alertStore.ts` — add `strategyRisk` category
- Modify: `frontend/src/hooks/useSocket.ts` — add strategy risk event handlers for global toasts

**What:** Even when not on the dashboard page, strategy risk events (exit triggers, rejections) should show global toasts. The dashboard-specific useStrategySocket handles room-based data, but useSocket (global) handles toast-worthy events.

**Changes to alertStore.ts:**
- Add `strategyRisk: boolean` to `AlertCategories` interface (after `strategy`)
- Add `strategyRisk: true` to `DEFAULT_STATE.categories`

**Changes to useSocket.ts:**
- Add listeners for:
  - `strategy_exit_triggered` → toast with exit reason (sound: yes)
  - `strategy_order_rejected` → error toast (sound: yes)
  - `strategy_position_opened` → info toast (sound: yes)
  - `strategy_position_closed` → success/error toast based on P&L (sound: yes)
- All use `showCategoryToast(type, message, 'strategyRisk')`

**Verification:** Enable/disable strategyRisk category in Profile page, verify toasts respect setting.

---

## Dependency Order

```
Task 1 (Types) → Task 2 (API) → Task 3 (Store) → Task 4 (Socket Hook)
                                                         ↓
Task 5 (Recharts) ─────────────────────────────────────────
                                                         ↓
Task 6 (Badges) → Task 7 (PositionRow + Table) → Task 8 (StrategyCard)
                                                         ↓
Task 9 (Header) ─────────────────────────────────────────↓
                                                         ↓
Task 10 (Orders/Trades Drawers) ─────────────────────────↓
                                                         ↓
Task 11 (PnL Drawer + Charts + Metrics) ─────────────────↓
                                                         ↓
Task 12 (Risk Config Drawer) ────────────────────────────↓
                                                         ↓
Task 13 (Empty States) ─────────────────────────────────→↓
                                                         ↓
                                               Task 14 (Dashboard Page)
                                                         ↓
                                               Task 15 (Global Alerts)
```

Tasks 1→2→3→4 must be sequential (each depends on previous).
Task 5 (npm install) is independent — can run anytime.
Tasks 6→7→8 are the core display pipeline.
Tasks 9, 10, 11, 12, 13 can be developed in parallel after Task 8.
Task 14 assembles everything.
Task 15 adds polish.

---

## Key Design Decisions

### Why Zustand + TanStack Query (not one or the other)?

**TanStack Query** handles: initial REST fetch, cache management, loading/error states, refetch on window focus. It's great for request-response data.

**Zustand** handles: real-time SocketIO mutations at 300ms intervals. TanStack Query's cache isn't designed for 3+ updates/second — Zustand's synchronous `set()` is. Components subscribe to Zustand slices and re-render only when their slice changes.

**Data flow:** REST → TanStack Query → Zustand (initial) → SocketIO → Zustand (live) → React

### Why React.memo on PositionRow?

With 10 strategies × 5 positions = 50 rows, and SocketIO updates at 300ms, naive rendering would cause 50 re-renders per update. `React.memo` + unique position IDs ensure only the changed row re-renders. The flash map uses a separate Map structure so only the position that just changed gets the flash effect.

### Why Sheet (side panel) instead of modals for drawers?

Sheets keep the dashboard visible behind the panel — traders can glance at live positions while reviewing orders/trades. Modals would block the entire view, which is bad for a trading dashboard where you need ambient awareness of live data.

### Why not reuse existing OrderBook/TradeBook pages?

The existing pages pull from the broker API and show all orders/trades globally. The strategy drawers show **only** strategy-specific data from our local `StrategyOrder`/`StrategyTrade` tables — no broker API call needed, faster load, strategy-isolated view.

---

## Verification Plan

### After Tasks 1-4 (Foundation):
```bash
cd frontend && npx tsc --noEmit  # Zero type errors
```

### After Task 8 (Core Display):
```bash
cd frontend && npm run dev
# Navigate to /strategy/dashboard
# Verify: strategy cards render with mock data
# Verify: expand/collapse animation
# Verify: position table renders
```

### After Task 11 (Analytics):
```bash
# Open P&L drawer
# Verify: equity curve chart renders
# Verify: metrics grid displays
# Verify: exit breakdown table renders
```

### After Task 14 (Full Dashboard):
```bash
cd frontend && npm run build  # Production build succeeds
cd frontend && npm run dev    # Full page works end-to-end
```

### End-to-end with backend:
```bash
# Terminal 1: uv run app.py
# Terminal 2: cd frontend && npm run dev
# Navigate to http://localhost:5173/strategy/dashboard
# Verify: dashboard loads with real strategy data
# Verify: SocketIO connection established
# Verify: live P&L updates visible
```
