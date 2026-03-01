import type {
  BacktestListItem,
  BacktestResult,
  BacktestRunRequest,
  DataAvailability,
} from '@/types/backtest'
import { webClient } from './client'

interface ApiResponse<T = void> {
  status: string
  message?: string
  data?: T
}

export const backtestApi = {
  /**
   * Launch a new backtest run
   */
  run: async (request: BacktestRunRequest): Promise<{ backtest_id: string }> => {
    const response = await webClient.post<
      ApiResponse & { backtest_id: string }
    >('/backtest/api/run', request)
    return { backtest_id: response.data.backtest_id }
  },

  /**
   * Get status of a backtest run
   */
  getStatus: async (backtestId: string) => {
    const response = await webClient.get<ApiResponse<{
      backtest_id: string
      name: string
      status: string
      created_at: string | null
      started_at: string | null
      completed_at: string | null
      duration_ms: number | null
      error_message: string | null
    }>>(`/backtest/api/status/${backtestId}`)
    return response.data.data
  },

  /**
   * Get full results for a completed backtest
   */
  getResults: async (backtestId: string): Promise<BacktestResult> => {
    const response = await webClient.get<ApiResponse<BacktestResult>>(
      `/backtest/api/results/${backtestId}`
    )
    return response.data.data!
  },

  /**
   * List all backtests for the current user
   */
  list: async (limit = 50): Promise<BacktestListItem[]> => {
    const response = await webClient.get<ApiResponse<BacktestListItem[]>>(
      `/backtest/api/list?limit=${limit}`
    )
    return response.data.data || []
  },

  /**
   * Cancel a running backtest
   */
  cancel: async (backtestId: string): Promise<void> => {
    await webClient.post(`/backtest/api/cancel/${backtestId}`)
  },

  /**
   * Delete a backtest run
   */
  delete: async (backtestId: string): Promise<void> => {
    await webClient.delete(`/backtest/api/delete/${backtestId}`)
  },

  /**
   * Export backtest trades as CSV (returns download URL)
   */
  getExportUrl: (backtestId: string): string => {
    return `/backtest/api/export/${backtestId}`
  },

  /**
   * Check data availability for requested configuration
   */
  checkData: async (params: {
    symbols: string[]
    exchange: string
    interval: string
    start_date: string
    end_date: string
  }): Promise<DataAvailability> => {
    const response = await webClient.post<ApiResponse<DataAvailability>>(
      '/backtest/api/check-data',
      params
    )
    return response.data.data!
  },

  /**
   * Compare multiple backtests
   */
  compare: async (backtestIds: string[]): Promise<BacktestResult[]> => {
    const response = await webClient.post<ApiResponse<BacktestResult[]>>(
      '/backtest/api/compare',
      { backtest_ids: backtestIds }
    )
    return response.data.data || []
  },

  /**
   * Create an EventSource for live backtest progress
   */
  createProgressStream: (backtestId: string): EventSource => {
    return new EventSource(`/backtest/api/events/${backtestId}`)
  },
}
