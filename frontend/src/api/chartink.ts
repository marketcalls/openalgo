import type {
  AddChartinkSymbolRequest,
  ChartinkStrategy,
  ChartinkSymbolMapping,
  CreateChartinkStrategyRequest,
} from '@/types/chartink'
import type { SymbolSearchResult } from '@/types/strategy'
import type { ApiResponse } from '@/types/trading'
import { webClient } from './client'

export const chartinkApi = {
  /**
   * Get all Chartink strategies
   */
  getStrategies: async (): Promise<ChartinkStrategy[]> => {
    const response = await webClient.get<{ strategies: ChartinkStrategy[] }>(
      '/chartink/api/strategies'
    )
    return response.data.strategies || []
  },

  /**
   * Get a single Chartink strategy by ID
   */
  getStrategy: async (
    strategyId: number
  ): Promise<{ strategy: ChartinkStrategy; mappings: ChartinkSymbolMapping[] }> => {
    const response = await webClient.get<{
      strategy: ChartinkStrategy
      mappings: ChartinkSymbolMapping[]
    }>(`/chartink/api/strategy/${strategyId}`)
    return response.data
  },

  /**
   * Create a new Chartink strategy
   */
  createStrategy: async (
    data: CreateChartinkStrategyRequest
  ): Promise<ApiResponse<{ strategy_id: number }>> => {
    const response = await webClient.post<ApiResponse<{ strategy_id: number }>>(
      '/chartink/api/strategy',
      data
    )
    return response.data
  },

  /**
   * Toggle strategy active/inactive
   */
  toggleStrategy: async (strategyId: number): Promise<ApiResponse<{ is_active: boolean }>> => {
    const response = await webClient.post<ApiResponse<{ is_active: boolean }>>(
      `/chartink/api/strategy/${strategyId}/toggle`
    )
    return response.data
  },

  /**
   * Delete a strategy
   */
  deleteStrategy: async (strategyId: number): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(`/chartink/${strategyId}/delete`)
    return response.data
  },

  /**
   * Add a symbol mapping to a strategy
   */
  addSymbolMapping: async (
    strategyId: number,
    data: AddChartinkSymbolRequest
  ): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>(
      `/chartink/${strategyId}/configure`,
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
      `/chartink/${strategyId}/configure`,
      { symbols: csvData } // Backend expects 'symbols' field with CSV data
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
      `/chartink/${strategyId}/symbol/${mappingId}/delete`
    )
    return response.data
  },

  /**
   * Search symbols (limited to NSE/BSE)
   */
  searchSymbols: async (query: string, exchange?: 'NSE' | 'BSE'): Promise<SymbolSearchResult[]> => {
    const params = new URLSearchParams({ q: query })
    if (exchange) {
      params.append('exchange', exchange)
    }
    const response = await webClient.get<{ results: SymbolSearchResult[] }>(
      `/chartink/search?${params.toString()}`
    )
    return response.data.results || []
  },

  /**
   * Get webhook URL for a strategy
   */
  getWebhookUrl: (webhookId: string): string => {
    const baseUrl = window.location.origin
    return `${baseUrl}/chartink/webhook/${webhookId}`
  },
}
