// frontend/src/api/ai-analysis.ts
import { apiClient } from './client'
import type {
  AIAnalysisResponse,
  AIScanResponse,
  AIStatusResponse,
} from '@/types/ai-analysis'

export const aiAnalysisApi = {
  /** Run AI technical analysis on a single symbol */
  analyzeSymbol: async (
    apiKey: string,
    symbol: string,
    exchange: string = 'NSE',
    interval: string = '1d',
  ): Promise<AIAnalysisResponse> => {
    const response = await apiClient.post<AIAnalysisResponse>('/agent/analyze', {
      apikey: apiKey,
      symbol,
      exchange,
      interval,
    })
    return response.data
  },

  /** Scan multiple symbols and return signals */
  scanSymbols: async (
    apiKey: string,
    symbols: string[],
    exchange: string = 'NSE',
    interval: string = '1d',
  ): Promise<AIScanResponse> => {
    const response = await apiClient.post<AIScanResponse>('/agent/scan', {
      apikey: apiKey,
      symbols,
      exchange,
      interval,
    })
    return response.data
  },

  /** Check AI agent status */
  getStatus: async (): Promise<AIStatusResponse> => {
    const response = await apiClient.get<AIStatusResponse>('/agent/status')
    return response.data
  },
}
