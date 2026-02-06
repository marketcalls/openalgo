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

  // Flash tracking for value changes
  flashPositions: Map<number, 'profit' | 'loss'>

  // Actions — REST snapshot
  setDashboardData: (strategies: DashboardStrategy[], summary: DashboardSummary) => void

  // Actions — SocketIO live updates
  updatePositions: (strategyId: number, positions: PositionUpdatePayload[]) => void
  updateStrategyPnL: (payload: PnLUpdatePayload) => void
  addPosition: (strategyId: number, position: StrategyPosition) => void
  removePosition: (strategyId: number, positionId: number) => void

  // Actions — UI
  setConnectionStatus: (status: 'connected' | 'disconnected' | 'stale') => void
  clearFlash: (positionId: number) => void
  reset: () => void
}

const DEFAULT_SUMMARY: DashboardSummary = {
  active_strategies: 0,
  paused_strategies: 0,
  open_positions: 0,
  total_pnl: 0,
}

export const useStrategyDashboardStore = create<StrategyDashboardState>()((set, get) => ({
  strategies: [],
  summary: DEFAULT_SUMMARY,
  initialized: false,
  connectionStatus: 'disconnected',
  flashPositions: new Map(),

  setDashboardData: (strategies, summary) => {
    set({ strategies, summary, initialized: true })
  },

  updatePositions: (strategyId, positionUpdates) => {
    const state = get()
    const newFlash = new Map(state.flashPositions)

    const newStrategies = state.strategies.map((strategy) => {
      if (strategy.id !== strategyId) return strategy

      const updatedPositions = strategy.positions.map((pos) => {
        const update = positionUpdates.find((u) => u.position_id === pos.id)
        if (!update) return pos

        // Determine flash direction
        const prevPnl = pos.unrealized_pnl
        const newPnl = update.unrealized_pnl
        if (newPnl > prevPnl) {
          newFlash.set(pos.id, 'profit')
        } else if (newPnl < prevPnl) {
          newFlash.set(pos.id, 'loss')
        }

        return {
          ...pos,
          ltp: update.ltp,
          unrealized_pnl: update.unrealized_pnl,
          unrealized_pnl_pct: update.unrealized_pnl_pct,
          peak_price: update.peak_price,
          stoploss_price: update.stoploss_price,
          target_price: update.target_price,
          trailstop_price: update.trailstop_price,
          breakeven_activated: update.breakeven_activated,
          position_state: update.position_state,
          exit_reason: update.exit_reason ?? pos.exit_reason,
          exit_detail: update.exit_detail ?? pos.exit_detail,
        }
      })

      return { ...strategy, positions: updatedPositions }
    })

    set({ strategies: newStrategies, flashPositions: newFlash })

    // Auto-clear flash after 500ms
    for (const update of positionUpdates) {
      setTimeout(() => get().clearFlash(update.position_id), 500)
    }
  },

  updateStrategyPnL: (payload) => {
    const state = get()
    const newStrategies = state.strategies.map((strategy) => {
      if (strategy.id !== payload.strategy_id) return strategy
      return {
        ...strategy,
        unrealized_pnl: payload.total_unrealized_pnl,
        total_pnl: payload.daily_total_pnl,
      }
    })

    // Recompute summary
    const newSummary: DashboardSummary = {
      ...state.summary,
      total_pnl: newStrategies.reduce((sum, s) => sum + s.total_pnl, 0),
      open_positions: newStrategies.reduce(
        (sum, s) => sum + s.positions.filter((p) => p.position_state !== 'closed').length,
        0
      ),
    }

    set({ strategies: newStrategies, summary: newSummary })
  },

  addPosition: (strategyId, position) => {
    const state = get()
    const newStrategies = state.strategies.map((strategy) => {
      if (strategy.id !== strategyId) return strategy
      return {
        ...strategy,
        positions: [...strategy.positions, position],
      }
    })
    set({ strategies: newStrategies })
  },

  removePosition: (strategyId, positionId) => {
    const state = get()
    const newStrategies = state.strategies.map((strategy) => {
      if (strategy.id !== strategyId) return strategy
      return {
        ...strategy,
        positions: strategy.positions.filter((p) => p.id !== positionId),
      }
    })
    set({ strategies: newStrategies })
  },

  setConnectionStatus: (status) => {
    set({ connectionStatus: status })
  },

  clearFlash: (positionId) => {
    const state = get()
    const newFlash = new Map(state.flashPositions)
    newFlash.delete(positionId)
    set({ flashPositions: newFlash })
  },

  reset: () => {
    set({
      strategies: [],
      summary: DEFAULT_SUMMARY,
      initialized: false,
      connectionStatus: 'disconnected',
      flashPositions: new Map(),
    })
  },
}))
