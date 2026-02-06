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
  getPositions: async (
    strategyId: number,
    strategyType = 'webhook',
    includeClosed = false
  ): Promise<StrategyPosition[]> => {
    const params = new URLSearchParams({ type: strategyType })
    if (includeClosed) params.set('include_closed', 'true')
    const response = await webClient.get<{ positions: StrategyPosition[] }>(
      `/strategy/api/strategy/${strategyId}/positions?${params}`
    )
    return response.data.positions || []
  },

  // Strategy orders
  getOrders: async (strategyId: number, strategyType = 'webhook'): Promise<StrategyOrder[]> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.get<{ orders: StrategyOrder[] }>(
      `/strategy/api/strategy/${strategyId}/orders?${params}`
    )
    return response.data.orders || []
  },

  // Strategy trades
  getTrades: async (strategyId: number, strategyType = 'webhook'): Promise<StrategyTrade[]> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.get<{ trades: StrategyTrade[] }>(
      `/strategy/api/strategy/${strategyId}/trades?${params}`
    )
    return response.data.trades || []
  },

  // P&L analytics
  getPnL: async (strategyId: number, strategyType = 'webhook'): Promise<PnLResponse> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.get<PnLResponse>(
      `/strategy/api/strategy/${strategyId}/pnl?${params}`
    )
    return response.data
  },

  // Risk configuration
  updateRiskConfig: async (
    strategyId: number,
    config: RiskConfigUpdate,
    strategyType = 'webhook'
  ): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.put<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk?${params}`,
      config
    )
    return response.data
  },

  // Activate/deactivate risk monitoring
  activateRisk: async (strategyId: number, strategyType = 'webhook'): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk/activate?${params}`
    )
    return response.data
  },

  deactivateRisk: async (strategyId: number, strategyType = 'webhook'): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/risk/deactivate?${params}`
    )
    return response.data
  },

  // Manual close
  closePosition: async (
    strategyId: number,
    positionId: number,
    strategyType = 'webhook'
  ): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/position/${positionId}/close?${params}`
    )
    return response.data
  },

  closeAllPositions: async (strategyId: number, strategyType = 'webhook'): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/positions/close-all?${params}`
    )
    return response.data
  },

  // Manual entry
  manualEntry: async (
    strategyId: number,
    data: { mapping_id: number; action: string; quantity: number }
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/manual-entry`,
      data
    )
    return response.data
  },

  // Delete closed position
  deletePosition: async (
    strategyId: number,
    positionId: number,
    strategyType = 'webhook'
  ): Promise<ApiResponse<void>> => {
    const params = new URLSearchParams({ type: strategyType })
    const response = await webClient.delete<ApiResponse<void>>(
      `/strategy/api/strategy/${strategyId}/position/${positionId}?${params}`
    )
    return response.data
  },
}
