import { apiClient } from './client'

/** One ranked-list entry. CPR/first-candle fields only ever arrive on
 * `intraday_boost` -- the server enriches that list alone before responding. */
export interface TfListItem {
  symbol: string
  ltp: number
  prev_close: number
  change_pct: number
  score: number
  cpr_width_pct?: number | null
  cpr_bias?: 'bullish' | 'bearish' | null
  first_candle_range_pct?: number | null
  /** Kaufman efficiency-ratio-based "steadiness since open" score, 0-100 --
   * 100 is a perfectly straight move, near 0 is pure chop. Only ever
   * populated on `intraday_boost`, refreshed every ~5 minutes server-side. */
  directional_score?: number | null
  directional_direction?: 'up' | 'down' | null
  /** Sign flips in the candle-to-candle move since the open -- the concrete
   * number behind "without hiccups." */
  directional_reversals?: number | null
}

export interface MarketPulseData {
  intraday_boost: TfListItem[]
  breakout_beacon: TfListItem[]
  high_powered_stocks: TfListItem[]
}

export interface MarketPulseResponse {
  status: 'success' | 'error'
  data?: MarketPulseData
  message?: string
}

/** Raw TradeFinder field names, passed through unmapped except `symbol`/CPR
 * which the backend adds. `param_3` is rfactor everywhere it appears. */
export interface SectorIndexItem {
  Symbol: string
  param_3: number
}

export interface SectorStockItem {
  Symbol: string
  symbol: string
  param_0: number
  param_1: number
  param_2: number
  param_3: number
  cpr_width_pct?: number | null
  cpr_bias?: 'bullish' | 'bearish' | null
}

export interface SectorScopeData {
  index: SectorIndexItem[]
  /** Keyed by `"<name>_r_factor"` -- strip that suffix before displaying. */
  sectors: Record<string, Record<string, SectorStockItem>>
}

export interface SectorScopeResponse {
  status: 'success' | 'error'
  data?: SectorScopeData
  message?: string
}

export interface JwtHealthResponse {
  status: 'success' | 'error'
  hasToken?: boolean
  expiresInSeconds?: number
  refreshing?: boolean
  message?: string
}

/** `[minute_of_day, rank]` pairs, already sorted by time. */
export type RankTimelinePoint = [number, number]

/** `[minute_of_day, ltp]` pairs, already sorted by time. */
export type PriceTimelinePoint = [number, number]

export interface BoostSnapshotsResponse {
  status: 'success' | 'error'
  date?: string
  list_type?: string
  count?: number
  symbols?: string[]
  /** Only present when `includeRanks` was set. Keyed by symbol, then by
   * `YYYY-MM-DD` -- a single-day request still nests one day deep. */
  ranks?: Record<string, Record<string, RankTimelinePoint[]>>
  /** Only present when `includePrices` was set. Same shape as `ranks`. */
  prices?: Record<string, Record<string, PriceTimelinePoint[]>>
  message?: string
}

export const tradefinderApi = {
  getMarketPulse: async (apiKey: string): Promise<MarketPulseResponse> => {
    const response = await apiClient.post<MarketPulseResponse>('/tfmarketpulse', {
      apikey: apiKey,
    })
    return response.data
  },

  getSectorScope: async (apiKey: string): Promise<SectorScopeResponse> => {
    const response = await apiClient.post<SectorScopeResponse>('/tfsectorscope', {
      apikey: apiKey,
    })
    return response.data
  },

  /** Cheap expiry check -- only kicks off the slow browser-based refresh
   * server-side when the token is actually close to expiring. Safe to poll
   * every minute or two, per the endpoint's own docstring. */
  getJwtHealth: async (apiKey: string): Promise<JwtHealthResponse> => {
    const response = await apiClient.post<JwtHealthResponse>('/tfjwtkeepalive', {
      apikey: apiKey,
      minSeconds: 1800,
    })
    return response.data
  },

  /** Today's rank (and optionally price) timeline for one list -- the
   * backtesting endpoint doubles as the only source of "how has this symbol's
   * rank/price moved today", since nothing else records that history. */
  getBoostSnapshots: async (
    apiKey: string,
    date: string,
    listType: string,
    opts: { includePrices?: boolean } = {}
  ): Promise<BoostSnapshotsResponse> => {
    const response = await apiClient.post<BoostSnapshotsResponse>('/boostsnapshots', {
      apikey: apiKey,
      date,
      lookbackDays: 1,
      list_type: listType,
      includeRanks: true,
      includePrices: opts.includePrices ?? false,
    })
    return response.data
  },
}
