import type {
  ExpiryResponse,
  OptionChainResponse,
  ScalpingOrderRequest,
  ScalpingOrderResponse,
  UnderlyingsResponse,
} from '@/types/scalping'
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

  placeOrder: async (req: ScalpingOrderRequest): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/order', req)
    return response.data
  },

  closeAll: async (): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/close_all', {})
    return response.data
  },

  cancelAll: async (): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/cancel_all', {})
    return response.data
  },
}
