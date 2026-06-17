import type {
  ExpiryResponse,
  OptionChainResponse,
  ScalpingOrderRequest,
  ScalpingOrderResponse,
  ScalpingSLState,
  SearchInstrument,
  SLStatesResponse,
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

  // All F&O underlyings for an exchange (indices first), like /search/token.
  getAllUnderlyings: async (
    exchange: string,
    instrumenttype: 'options' | 'futures' = 'options'
  ): Promise<{ status: string; data: string[] }> => {
    const response = await webClient.get('/scalping/api/all_underlyings', {
      params: { exchange, instrumenttype },
    })
    return response.data
  },

  getExpiry: async (
    underlying: string,
    exchange: string,
    instrumenttype: 'options' | 'futures' = 'options'
  ): Promise<ExpiryResponse> => {
    const response = await webClient.get<ExpiryResponse>('/scalping/api/expiry', {
      params: { underlying, exchange, instrumenttype },
    })
    return response.data
  },

  search: async (
    exchange: string,
    query: string
  ): Promise<{ status: string; data: SearchInstrument[] }> => {
    const response = await webClient.get('/scalping/api/search', {
      params: { exchange, query },
    })
    return response.data
  },

  futures: async (
    underlying: string,
    exchange: string
  ): Promise<{
    status: string
    data: Array<{ symbol: string; expiry: string; lotsize: number }>
  }> => {
    const response = await webClient.get('/scalping/api/futures', {
      params: { underlying, exchange },
    })
    return response.data
  },

  getStrikes: async (
    underlying: string,
    exchange: string,
    expiry: string,
    strikeCount = 10
  ): Promise<OptionChainResponse> => {
    const response = await webClient.get<OptionChainResponse>('/scalping/api/strikes', {
      params: { underlying, exchange, expiry, strike_count: strikeCount },
    })
    return response.data
  },

  // Historical candles for the scalping charts. interval is an OpenAlgo interval
  // (1m/5m/15m); lookback scales 1m=1 day, 5m=3, 15m=9. Pass `date` (the trading
  // date learned on first load) so the periodic reconcile pulls a single day.
  getHistory: async (
    symbol: string,
    exchange: string,
    interval: string,
    date?: string
  ): Promise<{
    status: string
    symbol: string
    exchange: string
    interval: string
    date: string | null
    candles: Array<{
      time: number
      open: number
      high: number
      low: number
      close: number
      volume: number
    }>
    message?: string
  }> => {
    const params: Record<string, string> = { symbol, exchange, interval }
    if (date) params.date = date
    const response = await webClient.get('/scalping/api/history', { params })
    return response.data
  },

  placeOrder: async (req: ScalpingOrderRequest): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/order', req)
    return response.data
  },

  // Risk-reducing single-leg exit (trailing-SL). Bypasses the entry lot cap and
  // splits oversized exits on the server, so a >20-lot position can always flatten.
  closeLeg: async (req: ScalpingOrderRequest): Promise<ScalpingOrderResponse> => {
    const response = await webClient.post<ScalpingOrderResponse>('/scalping/api/close_leg', req)
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

  getTracked: async (): Promise<{
    status: string
    data: Array<{ symbol: string; exchange: string; product: string }>
  }> => {
    const response = await webClient.get('/scalping/api/tracked')
    return response.data
  },

  resetTracked: async (): Promise<{ status: string; cleared?: boolean }> => {
    const response = await webClient.delete('/scalping/api/tracked')
    return response.data
  },

  getSLStates: async (): Promise<SLStatesResponse> => {
    const response = await webClient.get<SLStatesResponse>('/scalping/api/sl')
    return response.data
  },

  saveSL: async (
    sl: Partial<ScalpingSLState> & Pick<ScalpingSLState, 'symbol' | 'exchange' | 'product'>
  ): Promise<{ status: string; data?: ScalpingSLState; message?: string }> => {
    const response = await webClient.post('/scalping/api/sl', sl)
    return response.data
  },

  deleteSL: async (
    symbol: string,
    exchange: string,
    product: string
  ): Promise<{ status: string; deleted?: boolean }> => {
    const response = await webClient.delete('/scalping/api/sl', {
      data: { symbol, exchange, product },
    })
    return response.data
  },
}
