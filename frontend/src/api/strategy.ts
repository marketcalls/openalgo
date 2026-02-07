import type {
  AddSymbolRequest,
  CreateStrategyRequest,
  Strategy,
  StrategySymbolMapping,
  SymbolSearchResult,
} from '@/types/strategy'
import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export const strategyApi = {
  /**
   * Get all strategies
   */
  getStrategies: async (): Promise<Strategy[]> => {
    const response = await webClient.get<{ strategies: Strategy[] }>('/strategy/api/strategies')
    return response.data.strategies || []
  },

  /**
   * Get a single strategy by ID
   */
  getStrategy: async (
    strategyId: number
  ): Promise<{ strategy: Strategy; mappings: StrategySymbolMapping[] }> => {
    const response = await webClient.get<{ strategy: Strategy; mappings: StrategySymbolMapping[] }>(
      `/strategy/api/strategy/${strategyId}`
    )
    return response.data
  },

  /**
   * Create a new strategy
   */
  createStrategy: async (
    data: CreateStrategyRequest
  ): Promise<ApiResponse<{ strategy_id: number }>> => {
    const response = await webClient.post<ApiResponse<{ strategy_id: number }>>(
      '/strategy/api/strategy',
      data
    )
    return response.data
  },

  /**
   * Toggle strategy active/inactive
   */
  toggleStrategy: async (strategyId: number): Promise<ApiResponse<{ is_active: boolean }>> => {
    const response = await webClient.post<ApiResponse<{ is_active: boolean }>>(
      `/strategy/api/strategy/${strategyId}/toggle`
    )
    return response.data
  },

  /**
   * Delete a strategy
   */
  deleteStrategy: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/strategy/${strategyId}/delete`)
    return response.data
  },

  /**
   * Add a symbol mapping to a strategy
   */
  addSymbolMapping: async (
    strategyId: number,
    data: AddSymbolRequest
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/${strategyId}/configure`,
      data
    )
    return response.data
  },

  /**
   * Add bulk symbol mappings
   */
  addBulkSymbols: async (
    strategyId: number,
    csvData: string
  ): Promise<ApiResponse<{ added: number; failed: number }>> => {
    const response = await webClient.post<ApiResponse<{ added: number; failed: number }>>(
      `/strategy/${strategyId}/configure`,
      { symbols: csvData } // Backend expects 'symbols' field
    )
    return response.data
  },

  /**
   * Delete a symbol mapping
   */
  deleteSymbolMapping: async (
    strategyId: number,
    mappingId: number
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/strategy/${strategyId}/symbol/${mappingId}/delete`
    )
    return response.data
  },

  /**
   * Search symbols (uses rich search API with instrumenttype, lotsize, etc.)
   */
  searchSymbols: async (query: string, exchange?: string): Promise<SymbolSearchResult[]> => {
    const params = new URLSearchParams({ q: query })
    if (exchange) params.append('exchange', exchange)
    const response = await webClient.get<{ results: SymbolSearchResult[] }>(
      `/search/api/search?${params.toString()}`
    )
    return response.data.results || []
  },

  /**
   * Get available underlyings for a derivative exchange
   */
  searchUnderlyings: async (exchange: string): Promise<string[]> => {
    const params = new URLSearchParams({ exchange })
    const response = await webClient.get<{ underlyings: string[] }>(
      `/search/api/underlyings?${params.toString()}`
    )
    return response.data.underlyings || []
  },

  /**
   * Get webhook URL for a strategy
   */
  getWebhookUrl: (webhookId: string): string => {
    const baseUrl = window.location.origin
    return `${baseUrl}/strategy/webhook/${webhookId}`
  },
}
