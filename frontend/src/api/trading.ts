import type {
  ApiResponse,
  GttOrder,
  Holding,
  MarginData,
  Order,
  OrderStats,
  PlaceOrderRequest,
  PortfolioStats,
  Position,
  Trade,
} from '@/types/trading'
import { apiClient, webClient } from './client'

export interface QuotesData {
  ask: number
  bid: number
  high: number
  low: number
  ltp: number
  oi: number
  open: number
  prev_close: number
  volume: number
}

export interface DepthLevel {
  price: number
  quantity: number
}

/** One strategy's share of a broker position or holding. `strategy` is "Unattributed" for the remainder no leg explains. */
export interface StrategySlice {
  strategy: string
  quantity: number
  average_price: number
  /** Realized today by this strategy on this contract (positions only); a flat slice carries just this. */
  today_realized_pnl: number
  attributed: boolean
}

/** A broker row (position or holding) split into strategy slices (services/strategy_attribution.py). */
export interface AttributedRow {
  symbol: string
  exchange: string
  product: string
  quantity: number
  average_price: number
  slices: StrategySlice[]
  mismatch: boolean
  mismatch_reason: string | null
  /** For a flat row only: the one strategy the book still shows holding it, owner of any unexplained realized P&L. */
  leftover_owner: string | null
  /** Positions with m2m requested only: today's M2M (services/position_m2m.py). */
  m2m_available?: boolean
  m2m_reason?: string | null
  /** M2M independent of the live price; m2m = m2m_fixed + quantity * LTP. */
  m2m_fixed?: number | null
  m2m?: number | null
  overnight_quantity?: number
  prev_close?: number | null
  /** The broker's own P&L on this carried row is already the day's M2M (Kotak). */
  pnl_equals_m2m?: boolean
}

export interface StrategyAttribution {
  kind: 'positions' | 'holdings'
  rows: AttributedRow[]
  strategies: string[]
  /** Set when M2M was requested but today's trades or previous closes could not be fetched. */
  m2m_error?: string | null
}

export const UNATTRIBUTED = 'Unattributed'

export interface DepthData {
  asks: DepthLevel[]
  bids: DepthLevel[]
  high: number
  low: number
  ltp: number
  ltq: number
  oi: number
  open: number
  prev_close: number
  totalbuyqty: number
  totalsellqty: number
  volume: number
}

export interface MultiQuotesSymbol {
  symbol: string
  exchange: string
}

export interface MultiQuotesResult {
  symbol: string
  exchange: string
  data: QuotesData
}

// MultiQuotes API has a different response structure (results at root, not in data)
export interface MultiQuotesApiResponse {
  status: 'success' | 'error'
  results?: MultiQuotesResult[]
  message?: string
}

export interface BasketOrderItem {
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  pricetype: 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
  product: 'CNC' | 'NRML' | 'MIS'
  price?: number
  trigger_price?: number
  disclosed_quantity?: number
}

export interface BasketOrderResult {
  symbol: string
  status: 'success' | 'error'
  orderid?: string
  message?: string
}

export interface BasketOrderResponse {
  status: 'success' | 'error'
  message?: string
  results?: BasketOrderResult[]
  mode?: 'live' | 'analyze'
}

export const tradingApi = {
  /**
   * Get real-time quotes for a symbol
   */
  getQuotes: async (
    apiKey: string,
    symbol: string,
    exchange: string
  ): Promise<ApiResponse<QuotesData>> => {
    const response = await apiClient.post<ApiResponse<QuotesData>>('/quotes', {
      apikey: apiKey,
      symbol,
      exchange,
    })
    return response.data
  },

  /**
   * Get real-time quotes for multiple symbols
   */
  getMultiQuotes: async (
    apiKey: string,
    symbols: MultiQuotesSymbol[]
  ): Promise<MultiQuotesApiResponse> => {
    const response = await apiClient.post<MultiQuotesApiResponse>('/multiquotes', {
      apikey: apiKey,
      symbols,
    })
    return response.data
  },

  /**
   * Get market depth for a symbol (5-level order book)
   */
  getDepth: async (
    apiKey: string,
    symbol: string,
    exchange: string
  ): Promise<ApiResponse<DepthData>> => {
    const response = await apiClient.post<ApiResponse<DepthData>>('/depth', {
      apikey: apiKey,
      symbol,
      exchange,
    })
    return response.data
  },

  /**
   * Get margin/funds data
   */
  getFunds: async (apiKey: string): Promise<ApiResponse<MarginData>> => {
    const response = await apiClient.post<ApiResponse<MarginData>>('/funds', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Get positions
   */
  getPositions: async (apiKey: string): Promise<ApiResponse<Position[]>> => {
    const response = await apiClient.post<ApiResponse<Position[]>>('/positionbook', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Get order book
   */
  getOrders: async (
    apiKey: string
  ): Promise<ApiResponse<{ orders: Order[]; statistics: OrderStats }>> => {
    const response = await apiClient.post<ApiResponse<{ orders: Order[]; statistics: OrderStats }>>(
      '/orderbook',
      {
        apikey: apiKey,
      }
    )
    return response.data
  },

  /**
   * Get trade book
   */
  getTrades: async (apiKey: string): Promise<ApiResponse<Trade[]>> => {
    const response = await apiClient.post<ApiResponse<Trade[]>>('/tradebook', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Live positions or holdings split into per-strategy slices (POST /pnl/attribution,
   * services/strategy_attribution.py). Whatever no strategy leg explains comes
   * back as an "Unattributed" slice. Fails (503) when the strategy book is
   * unavailable - callers should treat that as "no strategy view", not "all
   * unattributed".
   */
  getStrategyAttribution: async (
    apiKey: string,
    kind: 'positions' | 'holdings',
    m2m = false
  ): Promise<ApiResponse<StrategyAttribution>> => {
    const response = await apiClient.post<ApiResponse<StrategyAttribution>>('/pnl/attribution', {
      apikey: apiKey,
      kind,
      m2m,
    })
    return response.data
  },

  /**
   * Get holdings
   */
  getHoldings: async (
    apiKey: string
  ): Promise<ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>> => {
    const response = await apiClient.post<
      ApiResponse<{ holdings: Holding[]; statistics: PortfolioStats }>
    >('/holdings', {
      apikey: apiKey,
    })
    return response.data
  },

  /**
   * Place order
   */
  placeOrder: async (order: PlaceOrderRequest): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await apiClient.post<ApiResponse<{ orderid: string }>>('/placeorder', order)
    return response.data
  },

  /**
   * Place a basket of orders in one call. Each item is independent — the
   * backend returns a per-order `results[]` so partial success is possible.
   */
  placeBasketOrder: async (
    apiKey: string,
    strategy: string,
    orders: BasketOrderItem[]
  ): Promise<BasketOrderResponse> => {
    const response = await apiClient.post<BasketOrderResponse>('/basketorder', {
      apikey: apiKey,
      strategy,
      orders,
    })
    return response.data
  },

  /**
   * Modify order (uses session auth with CSRF)
   */
  modifyOrder: async (
    orderid: string,
    orderData: {
      symbol: string
      exchange: string
      action: string
      product: string
      pricetype: string
      quantity: number
      price?: number
      trigger_price?: number
      disclosed_quantity?: number
    }
  ): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await webClient.post<ApiResponse<{ orderid: string }>>('/modify_order', {
      orderid,
      ...orderData,
    })
    return response.data
  },

  /**
   * Cancel order (uses session auth with CSRF)
   */
  cancelOrder: async (orderid: string): Promise<ApiResponse<{ orderid: string }>> => {
    const response = await webClient.post<ApiResponse<{ orderid: string }>>('/cancel_order', {
      orderid,
    })
    return response.data
  },

  /**
   * Close a specific position (uses session auth with CSRF)
   */
  closePosition: async (
    symbol: string,
    exchange: string,
    product: string
  ): Promise<ApiResponse<void>> => {
    // Uses the web route which handles session-based auth with CSRF
    const response = await webClient.post<ApiResponse<void>>('/close_position', {
      symbol,
      exchange,
      product,
    })
    return response.data
  },

  /**
   * Close all positions (uses session auth with CSRF)
   */
  closeAllPositions: async (): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>('/close_all_positions', {})
    return response.data
  },

  /**
   * Cancel all orders (uses session auth with CSRF)
   */
  cancelAllOrders: async (): Promise<ApiResponse<void>> => {
    const response = await webClient.post<ApiResponse<void>>('/cancel_all_orders', {})
    return response.data
  },

  /**
   * Get the GTT (Good Till Triggered) order book — active triggers + recent history.
   */
  getGttOrderbook: async (
    apiKey: string,
    status: 'active' | 'all' = 'active'
  ): Promise<ApiResponse<GttOrder[]>> => {
    const response = await apiClient.post<ApiResponse<GttOrder[]>>('/gttorderbook', {
      apikey: apiKey,
      status,
    })
    return response.data
  },

  /**
   * Cancel an active GTT trigger (uses session auth with CSRF).
   */
  cancelGttOrder: async (triggerId: string): Promise<ApiResponse<{ trigger_id: string }>> => {
    const response = await webClient.post<ApiResponse<{ trigger_id: string }>>(
      '/cancel_gtt_order',
      { trigger_id: triggerId }
    )
    return response.data
  },

  /**
   * Modify an active GTT trigger (uses session auth with CSRF).
   * Flat replacement body — same shape as PlaceGTTOrder plus trigger_id.
   * last_price is fetched server-side from the broker's quotes endpoint.
   */
  modifyGttOrder: async (
    triggerId: string,
    payload: {
      symbol: string
      exchange: string
      trigger_type: 'SINGLE' | 'OCO'
      action: 'BUY' | 'SELL' | string
      product: string
      quantity: number
      pricetype: string
      price: number
      triggerprice_sl: number
      triggerprice_tg: number
      stoploss?: number | null
      target?: number | null
      strategy?: string
    }
  ): Promise<ApiResponse<{ trigger_id: string }>> => {
    const response = await webClient.post<ApiResponse<{ trigger_id: string }>>(
      '/modify_gtt_order',
      { trigger_id: triggerId, ...payload }
    )
    return response.data
  },
}
