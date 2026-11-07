import type { CurveData } from '@/lib/pnlCurve'
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
  Segment,
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

/**
 * Response shape of GET /pnl/history (services/pnl_history_service.py::get_pnl_history).
 */
export interface PnlHistoryDailyRow {
  date: string
  realized_pnl: number
  trade_count: number
}

export interface PnlHistoryClosedTrade {
  symbol: string
  exchange: string
  product: string | null
  entry_action: string
  quantity: number
  entry_price: number
  entry_timestamp: string
  exit_price: number
  exit_timestamp: string
  realized_pnl: number
  // Strategy tag of the entry fill; null when untagged.
  strategy: string | null
}

export interface PnlHistoryOpenPosition {
  symbol: string
  exchange: string
  product: string | null
  action: string
  quantity: number
  average_price: number
  // holdings (equity) or positions (everything else)
  source: 'holdings' | 'positions'
  strategy: string | null
  // Live price and P&L on the open quantity; null when the position has no
  // live quote.
  ltp: number | null
  unrealized_pnl: number | null
}

export interface PnlHistoryData {
  start_date: string
  end_date: string
  total_realized_pnl: number
  trade_count: number
  daily: PnlHistoryDailyRow[]
  closed_trades: PnlHistoryClosedTrade[]
  open_positions: PnlHistoryOpenPosition[]
  total_unrealized_pnl: number | null
}

/** One leg of the strategy book (database/strategy_book_db.py), from GET /pnl/strategy-legs. */
export interface StrategyLeg {
  strategy: string
  symbol: string
  exchange: string
  product: string
  quantity: number
  average_price: number
  realized_pnl: number
  today_realized_pnl: number
  updated_at: string | null
}

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
   * Backfill the consolidated multi-day P&L ledger from an exported broker
   * tradebook CSV.
   *
   * A FormData body, not JSON. apiClient sets a default `Content-Type:
   * application/json` header on the axios instance - that default headers
   * object is already populated before axios's FormData detection runs, so
   * it is NOT auto-cleared the way it would be with no default header at
   * all. Confirmed live: without the override below, Flask never saw a
   * multipart body at all (request.form came back empty), so the `apikey`
   * schema check failed first with "Missing data for required field" -
   * nothing to do with the CSV itself. Setting Content-Type to `undefined`
   * on this one call clears the instance default so the browser can set
   * its own multipart boundary.
   */
  importPnlHistoryCsv: async (
    apiKey: string,
    file: File
  ): Promise<
    ApiResponse<{ imported: number; skipped_duplicate: number; skipped_invalid: number }>
  > => {
    const formData = new FormData()
    formData.append('apikey', apiKey)
    formData.append('file', file)
    const response = await apiClient.post<
      ApiResponse<{ imported: number; skipped_duplicate: number; skipped_invalid: number }>
    >('/pnl/import', formData, {
      headers: { 'Content-Type': undefined },
    })
    return response.data
  },

  /**
   * Realized P&L for a date range, from the consolidated multi-day P&L
   * ledger .
   * FIFO-matched fresh on every call - nothing is precomputed server-side.
   */
  getPnlHistory: async (
    apiKey: string,
    startDate: string,
    endDate: string,
    options?: { symbol?: string; segment?: Segment; strategy?: string }
  ): Promise<ApiResponse<PnlHistoryData>> => {
    const response = await apiClient.get<ApiResponse<PnlHistoryData>>('/pnl/history', {
      params: {
        apikey: apiKey,
        start_date: startDate,
        end_date: endDate,
        // undefined keys are dropped by axios's param serializer, not sent
        // as empty strings - important here since the schema's segment
        // field validates against a fixed OneOf and would reject "".
        symbol: options?.symbol || undefined,
        segment: options?.segment || undefined,
        strategy: options?.strategy || undefined,
      },
    })
    return response.data
  },

  /**
   * Daily realized and unrealized P&L per strategy for equity. basis "range_start" values lots carried into the
   * range from the close before it; "actual_cost" uses the fill price.
   */
  getPnlCurve: async (
    apiKey: string,
    startDate: string,
    endDate: string,
    basis: 'range_start' | 'actual_cost' = 'range_start',
    symbolContains?: string
  ): Promise<ApiResponse<CurveData & { segment: string }>> => {
    const response = await apiClient.get<ApiResponse<CurveData & { segment: string }>>(
      '/pnl/curve',
      {
        params: {
          apikey: apiKey,
          start_date: startDate,
          end_date: endDate,
          basis,
          symbol_contains: symbolContains || undefined,
        },
      }
    )
    return response.data
  },

  /**
   * Raw fills for a date range from the consolidated multi-day P&L ledger
   *  - no FIFO matching,
   * just the ledger rows. Backs TradeBook.tsx's historical view; the live
   * "today" view keeps using getTrades() above, since today's trades
   * aren't in the ledger yet (the daily capture job runs after close).
   */
  getPnlTrades: async (
    apiKey: string,
    startDate: string,
    endDate: string,
    options?: { symbol?: string; segment?: Segment; strategy?: string }
  ): Promise<ApiResponse<Trade[]>> => {
    const response = await apiClient.get<ApiResponse<Trade[]>>('/pnl/trades', {
      params: {
        apikey: apiKey,
        start_date: startDate,
        end_date: endDate,
        symbol: options?.symbol || undefined,
        segment: options?.segment || undefined,
        strategy: options?.strategy || undefined,
      },
    })
    return response.data
  },

  /**
   * Every currently tracked strategy leg for this account, from the strategy
   * book (database/strategy_book_db.py). Not date-ranged.
   */
  getStrategyLegs: async (
    apiKey: string,
    strategy?: string
  ): Promise<ApiResponse<StrategyLeg[]>> => {
    const response = await apiClient.get<ApiResponse<StrategyLeg[]>>('/pnl/strategy-legs', {
      params: { apikey: apiKey, strategy: strategy || undefined },
    })
    return response.data
  },

  /**
   * Tag one historical fill with a strategy, for CSV-imported history and fills
   * with no order id to join against the strategy book. `tradeId` is the row's
   * Trade.id, present on rows returned by getPnlTrades above.
   */
  setTradeStrategy: async (
    apiKey: string,
    tradeId: number,
    strategy: string
  ): Promise<ApiResponse<{ id: number; strategy: string; updated_ids?: number[] }>> => {
    const response = await apiClient.patch<
      ApiResponse<{ id: number; strategy: string; updated_ids?: number[] }>
    >(`/pnl/trades/${tradeId}/strategy`, { apikey: apiKey, strategy })
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
