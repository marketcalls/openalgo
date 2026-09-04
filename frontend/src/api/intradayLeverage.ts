// api/intradayLeverage.ts
// Client for per-symbol intraday leverage multipliers.

import { webClient } from './client'

export interface IntradayLeverage {
  symbol: string
  exchange: string
  multiplier: number | null
  message?: string
}

export interface IntradayLeverageResponse {
  status: string
  data: IntradayLeverage
}

export interface IntradayLeverageBatchResponse {
  status: string
  data: IntradayLeverage[]
}

export const intradayLeverageApi = {
  /**
   * Get intraday leverage multiplier for a single symbol.
   */
  getMultiplier: async (symbol: string, exchange = 'NSE'): Promise<IntradayLeverageResponse> => {
    const response = await webClient.get<IntradayLeverageResponse>(
      `/intraday-leverage/api/${encodeURIComponent(symbol)}`,
      { params: { exchange } }
    )
    return response.data
  },

  /**
   * Get leverage multipliers for multiple symbols (up to 100).
   */
  getBulk: async (symbols: string[], exchange = 'NSE'): Promise<IntradayLeverageBatchResponse> => {
    const response = await webClient.post<IntradayLeverageBatchResponse>(
      '/intraday-leverage/api/batch',
      { symbols, exchange }
    )
    return response.data
  },
}
