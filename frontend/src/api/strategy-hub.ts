import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export type StrategyHubStatus = 'online' | 'stale' | 'offline'
export type StrategyHubLogLevel = 'DEBUG' | 'INFO' | 'WARN' | 'ERROR'

export interface StrategyHubLog {
  id: string
  timestamp: string
  level: StrategyHubLogLevel
  source: string
  message: string
}

export interface StrategyHubLastCommand {
  command: string
  success: boolean
  message: string
  at: string
}

export interface StrategyHubEntry {
  strategy_id: string
  status: StrategyHubStatus
  host: string
  zmq_port: number | null
  unit_name: string | null
  metrics: Record<string, unknown>
  first_seen: string
  last_seen: string
  last_command: StrategyHubLastCommand | null
}

export const strategyHubApi = {
  getStrategies: async (): Promise<StrategyHubEntry[]> => {
    const response = await webClient.get<ApiResponse<StrategyHubEntry[]>>(
      '/strategy-hub/api/strategies'
    )
    return response.data.data || []
  },

  startStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy-hub/api/strategies/${strategyId}/start`
    )
    return response.data
  },

  stopStrategy: async (strategyId: string): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy-hub/api/strategies/${strategyId}/stop`
    )
    return response.data
  },

  getLogs: async (strategyId: string, limit = 500): Promise<StrategyHubLog[]> => {
    const response = await webClient.get<ApiResponse<StrategyHubLog[]>>(
      `/strategy-hub/api/strategies/${encodeURIComponent(strategyId)}/logs?limit=${limit}`
    )
    return response.data.data || []
  },
}
