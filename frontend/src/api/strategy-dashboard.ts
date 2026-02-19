import type {
  CircuitBreakerConfig,
  DailyPnL,
  DashboardOrder,
  DashboardPosition,
  DashboardSummary,
  DashboardTrade,
  MarketStatus,
  OverviewData,
  RiskConfig,
  RiskEvent,
} from '@/types/strategy-dashboard'
import { webClient } from './client'

const BASE = '/strategy/api'

interface ApiResponse<T> {
  status: 'success' | 'error'
  message?: string
  data: T
}

export const dashboardApi = {
  // ── Overview ──────────────────────────────────────────────────────────
  getDashboard: async (): Promise<OverviewData> => {
    const res = await webClient.get<ApiResponse<OverviewData>>(`${BASE}/overview`)
    return res.data.data
  },

  // ── Positions ─────────────────────────────────────────────────────────
  getPositions: async (
    strategyId: number,
    type = 'webhook',
    opts?: { includeClosed?: boolean; limit?: number; offset?: number }
  ): Promise<DashboardPosition[]> => {
    const params = new URLSearchParams({ type })
    if (opts?.includeClosed) params.set('include_closed', 'true')
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.offset) params.set('offset', String(opts.offset))
    const res = await webClient.get<ApiResponse<DashboardPosition[]>>(
      `${BASE}/strategy/${strategyId}/positions?${params}`
    )
    return res.data.data
  },

  // ── Orders ────────────────────────────────────────────────────────────
  getOrders: async (
    strategyId: number,
    type = 'webhook',
    opts?: { limit?: number; offset?: number }
  ): Promise<DashboardOrder[]> => {
    const params = new URLSearchParams({ type })
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.offset) params.set('offset', String(opts.offset))
    const res = await webClient.get<ApiResponse<DashboardOrder[]>>(
      `${BASE}/strategy/${strategyId}/orders?${params}`
    )
    return res.data.data
  },

  // ── Trades ────────────────────────────────────────────────────────────
  getTrades: async (
    strategyId: number,
    type = 'webhook',
    opts?: { limit?: number; offset?: number }
  ): Promise<DashboardTrade[]> => {
    const params = new URLSearchParams({ type })
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.offset) params.set('offset', String(opts.offset))
    const res = await webClient.get<ApiResponse<DashboardTrade[]>>(
      `${BASE}/strategy/${strategyId}/trades?${params}`
    )
    return res.data.data
  },

  // ── P&L ───────────────────────────────────────────────────────────────
  getPnL: async (
    strategyId: number,
    type = 'webhook'
  ): Promise<{ summary: DashboardSummary; daily: DailyPnL[] }> => {
    const res = await webClient.get<
      ApiResponse<{ summary: DashboardSummary; daily: DailyPnL[] }>
    >(`${BASE}/strategy/${strategyId}/pnl?type=${type}`)
    return res.data.data
  },

  // ── Risk Config ───────────────────────────────────────────────────────
  getRiskConfig: async (strategyId: number, type = 'webhook'): Promise<RiskConfig> => {
    const res = await webClient.get<ApiResponse<RiskConfig>>(
      `${BASE}/strategy/${strategyId}/risk-config?type=${type}`
    )
    return res.data.data
  },

  updateRiskConfig: async (
    strategyId: number,
    type: string,
    data: Partial<RiskConfig>
  ): Promise<void> => {
    await webClient.put(`${BASE}/strategy/${strategyId}/risk-config`, { ...data, type })
  },

  // ── Risk Monitoring ───────────────────────────────────────────────────
  activateRisk: async (strategyId: number, type = 'webhook'): Promise<void> => {
    await webClient.post(`${BASE}/strategy/${strategyId}/risk/activate`, { type })
  },

  deactivateRisk: async (strategyId: number, type = 'webhook'): Promise<void> => {
    await webClient.post(`${BASE}/strategy/${strategyId}/risk/deactivate`, { type })
  },

  // ── Position Actions ──────────────────────────────────────────────────
  closePosition: async (
    strategyId: number,
    positionId: number,
    type = 'webhook'
  ): Promise<{ orderid: string }> => {
    const res = await webClient.post<ApiResponse<never> & { orderid?: string }>(
      `${BASE}/strategy/${strategyId}/position/${positionId}/close`,
      { type }
    )
    return { orderid: res.data.orderid || '' }
  },

  closeAllPositions: async (
    strategyId: number,
    type = 'webhook'
  ): Promise<{ closed: number; total: number }> => {
    const res = await webClient.post<{ closed: number; total: number }>(
      `${BASE}/strategy/${strategyId}/close-all`,
      { type }
    )
    return res.data
  },

  deletePosition: async (
    strategyId: number,
    positionId: number,
    type = 'webhook'
  ): Promise<void> => {
    await webClient.delete(
      `${BASE}/strategy/${strategyId}/position/${positionId}?type=${type}`
    )
  },

  // ── Clone ─────────────────────────────────────────────────────────────
  cloneStrategy: async (
    strategyId: number,
    type = 'webhook'
  ): Promise<{ strategy_id: number; webhook_id: string }> => {
    const res = await webClient.post<
      ApiResponse<{ strategy_id: number; webhook_id: string }>
    >(`${BASE}/strategy/${strategyId}/clone`, { type })
    return res.data.data
  },

  // ── Market Status ─────────────────────────────────────────────────────
  getMarketStatus: async (): Promise<MarketStatus> => {
    const res = await webClient.get<ApiResponse<MarketStatus>>(`${BASE}/market-status`)
    return res.data.data
  },

  // ── Risk Events ───────────────────────────────────────────────────────
  getRiskEvents: async (
    strategyId: number,
    type = 'webhook',
    opts?: { limit?: number; offset?: number }
  ): Promise<RiskEvent[]> => {
    const params = new URLSearchParams({ type })
    if (opts?.limit) params.set('limit', String(opts.limit))
    if (opts?.offset) params.set('offset', String(opts.offset))
    const res = await webClient.get<ApiResponse<RiskEvent[]>>(
      `${BASE}/strategy/${strategyId}/risk-events?${params}`
    )
    return res.data.data
  },

  // ── Group Actions ─────────────────────────────────────────────────────
  closePositionGroup: async (
    strategyId: number,
    groupId: string,
    type = 'webhook'
  ): Promise<{ closed: number; total: number }> => {
    const res = await webClient.post<{ closed: number; total: number }>(
      `${BASE}/strategy/${strategyId}/group/${groupId}/close`,
      { type }
    )
    return res.data
  },

  // ── Circuit Breaker ───────────────────────────────────────────────────
  updateCircuitBreaker: async (
    strategyId: number,
    type: string,
    config: CircuitBreakerConfig
  ): Promise<void> => {
    await webClient.put(`${BASE}/strategy/${strategyId}/circuit-breaker`, {
      ...config,
      type,
    })
  },
}
