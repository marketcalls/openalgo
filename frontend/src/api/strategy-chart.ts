import { webClient } from './client'

export interface StrategyChartPoint {
  time: number
  // Missing when the broker doesn't return intraday history for the
  // underlying (e.g., Zerodha index 1m candles). The combined_premium
  // series is still valid; the chart hides the underlying curve.
  underlying?: number
  net_premium: number
  combined_premium: number
}

export interface StrategyChartData {
  underlying: string
  underlying_ltp: number
  interval: string
  tag: 'credit' | 'debit' | 'flat'
  entry_net_premium: number
  entry_abs_premium: number
  legs_used: number
  underlying_available: boolean
  series: StrategyChartPoint[]
}

export interface StrategyChartResponse {
  status: 'success' | 'error'
  message?: string
  data?: StrategyChartData
}

export interface StrategyChartLegInput {
  symbol: string
  exchange: string
  side: 'BUY' | 'SELL'
  segment: 'OPTION' | 'FUTURE'
  active: boolean
  price: number
}

export interface StrategyChartRequest {
  underlying: string
  exchange: string
  legs: StrategyChartLegInput[]
  interval: string
  days: number
}

export interface IntervalsData {
  seconds: string[]
  minutes: string[]
  hours: string[]
  days?: string[]
}

export interface IntervalsResponse {
  status: 'success' | 'error'
  message?: string
  data?: IntervalsData
}

export interface OIPoint {
  time: number
  value: number
}

export interface MultiStrikeOILeg {
  symbol: string
  exchange: string
  side: 'BUY' | 'SELL'
  strike?: number
  option_type?: 'CE' | 'PE'
  expiry?: string
  has_oi: boolean
  series: OIPoint[]
}

export interface MultiStrikeOIData {
  underlying: string
  underlying_ltp: number
  interval: string
  underlying_available: boolean
  underlying_series: OIPoint[]
  legs: MultiStrikeOILeg[]
}

export interface MultiStrikeOIResponse {
  status: 'success' | 'error'
  message?: string
  data?: MultiStrikeOIData
}

// Let 4xx responses resolve instead of throw — the backend returns structured
// `{status: "error", message: "..."}` bodies for user-fixable states (empty
// history window, missing OI, etc). Throwing swallows those and the toast
// falls back to a generic message.
const allow4xx = { validateStatus: (s: number) => s < 500 }

export const strategyChartApi = {
  getStrategyChart: async (params: StrategyChartRequest): Promise<StrategyChartResponse> => {
    const response = await webClient.post<StrategyChartResponse>(
      '/strategybuilder/api/strategy-chart',
      params,
      allow4xx
    )
    return response.data
  },

  getMultiStrikeOI: async (params: StrategyChartRequest): Promise<MultiStrikeOIResponse> => {
    const response = await webClient.post<MultiStrikeOIResponse>(
      '/strategybuilder/api/multi-strike-oi',
      params,
      allow4xx
    )
    return response.data
  },

  getIntervals: async (): Promise<IntervalsResponse> => {
    const response = await webClient.get<IntervalsResponse>(
      '/strategybuilder/api/intervals',
      allow4xx
    )
    return response.data
  },
}
