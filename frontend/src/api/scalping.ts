import type { ExpiryResponse, OptionChainResponse, UnderlyingsResponse } from '@/types/scalping'
import { webClient } from './client'

// Scalping terminal API. Endpoints are served by blueprints/scalping.py under
// the root path (not /api/v1), so we use webClient (session + CSRF aware).
export const scalpingApi = {
  getUnderlyings: async (): Promise<UnderlyingsResponse> => {
    const response = await webClient.get<UnderlyingsResponse>('/scalping/api/underlyings')
    return response.data
  },

  getExpiry: async (underlying: string): Promise<ExpiryResponse> => {
    const response = await webClient.get<ExpiryResponse>('/scalping/api/expiry', {
      params: { underlying },
    })
    return response.data
  },

  getStrikes: async (
    underlying: string,
    expiry: string,
    strikeCount = 10
  ): Promise<OptionChainResponse> => {
    const response = await webClient.get<OptionChainResponse>('/scalping/api/strikes', {
      params: { underlying, expiry, strike_count: strikeCount },
    })
    return response.data
  },
}
