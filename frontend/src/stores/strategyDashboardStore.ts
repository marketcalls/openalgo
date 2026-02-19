import { create } from 'zustand'
import type {
  DashboardOrder,
  DashboardPosition,
  DashboardStrategy,
  DashboardSummary,
  OverviewData,
  PositionGroupData,
  RiskEvent,
} from '@/types/strategy-dashboard'

export interface CBStatus {
  status: 'active' | 'tripped' | 'cleared'
  reason?: string
}

interface StrategyDashboardStore {
  // State
  overview: OverviewData | null
  strategies: Map<number, DashboardStrategy>
  positions: Map<number, DashboardPosition[]>
  summary: Map<number, DashboardSummary>
  riskEvents: Map<number, RiskEvent[]>
  positionGroups: Map<number, PositionGroupData[]>
  circuitBreakerStatus: Map<number, CBStatus>
  orders: Map<number, DashboardOrder[]>

  // Actions
  setDashboardData: (data: OverviewData) => void
  setStrategies: (strategies: DashboardStrategy[]) => void
  setPositions: (strategyId: number, positions: DashboardPosition[]) => void
  updatePosition: (strategyId: number, position: DashboardPosition) => void
  removePosition: (strategyId: number, positionId: number) => void
  setSummary: (strategyId: number, summary: DashboardSummary) => void
  addRiskEvent: (strategyId: number, event: RiskEvent) => void
  setRiskEvents: (strategyId: number, events: RiskEvent[]) => void
  setPositionGroups: (strategyId: number, groups: PositionGroupData[]) => void
  updateGroup: (strategyId: number, group: PositionGroupData) => void
  updateCircuitBreaker: (strategyId: number, status: CBStatus) => void
  updateOrder: (strategyId: number, order: DashboardOrder) => void
  reset: () => void
}

const initialState = {
  overview: null as OverviewData | null,
  strategies: new Map<number, DashboardStrategy>(),
  positions: new Map<number, DashboardPosition[]>(),
  summary: new Map<number, DashboardSummary>(),
  riskEvents: new Map<number, RiskEvent[]>(),
  positionGroups: new Map<number, PositionGroupData[]>(),
  circuitBreakerStatus: new Map<number, CBStatus>(),
  orders: new Map<number, DashboardOrder[]>(),
}

export const useStrategyDashboardStore = create<StrategyDashboardStore>()((set) => ({
  ...initialState,

  setDashboardData: (data) => set({ overview: data }),

  setStrategies: (strategies) =>
    set(() => {
      const map = new Map<number, DashboardStrategy>()
      for (const s of strategies) map.set(s.id, s)
      return { strategies: map }
    }),

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

  setPositionGroups: (strategyId, groups) =>
    set((state) => {
      const next = new Map(state.positionGroups)
      next.set(strategyId, groups)
      return { positionGroups: next }
    }),

  updateGroup: (strategyId, group) =>
    set((state) => {
      const next = new Map(state.positionGroups)
      const current = next.get(strategyId) || []
      const idx = current.findIndex((g) => g.id === group.id)
      if (idx >= 0) {
        const updated = [...current]
        updated[idx] = group
        next.set(strategyId, updated)
      } else {
        next.set(strategyId, [...current, group])
      }
      return { positionGroups: next }
    }),

  updateCircuitBreaker: (strategyId, status) =>
    set((state) => {
      const next = new Map(state.circuitBreakerStatus)
      next.set(strategyId, status)
      return { circuitBreakerStatus: next }
    }),

  updateOrder: (strategyId, order) =>
    set((state) => {
      const next = new Map(state.orders)
      const current = next.get(strategyId) || []
      const idx = current.findIndex((o) => o.id === order.id)
      if (idx >= 0) {
        const updated = [...current]
        updated[idx] = order
        next.set(strategyId, updated)
      } else {
        next.set(strategyId, [...current, order])
      }
      return { orders: next }
    }),

  reset: () => set(initialState),
}))
