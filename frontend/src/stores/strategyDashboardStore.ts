import { create } from 'zustand'
import type {
  DashboardPosition,
  DashboardSummary,
  OverviewData,
  RiskEvent,
} from '@/types/strategy-dashboard'

interface StrategyDashboardStore {
  // State
  overview: OverviewData | null
  positions: Map<number, DashboardPosition[]>
  summary: Map<number, DashboardSummary>
  riskEvents: Map<number, RiskEvent[]>

  // Actions
  setOverview: (data: OverviewData) => void
  setPositions: (strategyId: number, positions: DashboardPosition[]) => void
  updatePosition: (strategyId: number, position: DashboardPosition) => void
  removePosition: (strategyId: number, positionId: number) => void
  setSummary: (strategyId: number, summary: DashboardSummary) => void
  addRiskEvent: (strategyId: number, event: RiskEvent) => void
  setRiskEvents: (strategyId: number, events: RiskEvent[]) => void
  reset: () => void
}

const initialState = {
  overview: null,
  positions: new Map<number, DashboardPosition[]>(),
  summary: new Map<number, DashboardSummary>(),
  riskEvents: new Map<number, RiskEvent[]>(),
}

export const useStrategyDashboardStore = create<StrategyDashboardStore>()((set) => ({
  ...initialState,

  setOverview: (data) => set({ overview: data }),

  setPositions: (strategyId, positions) =>
    set((state) => {
      const next = new Map(state.positions)
      next.set(strategyId, positions)
      return { positions: next }
    }),

  updatePosition: (strategyId, position) =>
    set((state) => {
      const next = new Map(state.positions)
      const current = next.get(strategyId) || []
      const idx = current.findIndex((p) => p.id === position.id)
      if (idx >= 0) {
        const updated = [...current]
        updated[idx] = position
        next.set(strategyId, updated)
      } else {
        next.set(strategyId, [...current, position])
      }
      return { positions: next }
    }),

  removePosition: (strategyId, positionId) =>
    set((state) => {
      const next = new Map(state.positions)
      const current = next.get(strategyId) || []
      next.set(
        strategyId,
        current.filter((p) => p.id !== positionId)
      )
      return { positions: next }
    }),

  setSummary: (strategyId, summary) =>
    set((state) => {
      const next = new Map(state.summary)
      next.set(strategyId, summary)
      return { summary: next }
    }),

  addRiskEvent: (strategyId, event) =>
    set((state) => {
      const next = new Map(state.riskEvents)
      const current = next.get(strategyId) || []
      next.set(strategyId, [event, ...current].slice(0, 100))
      return { riskEvents: next }
    }),

  setRiskEvents: (strategyId, events) =>
    set((state) => {
      const next = new Map(state.riskEvents)
      next.set(strategyId, events)
      return { riskEvents: next }
    }),

  reset: () => set(initialState),
}))
