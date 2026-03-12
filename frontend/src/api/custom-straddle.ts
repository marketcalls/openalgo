import { webClient } from './client'

export interface PnLDataPoint {
  time: number
  pnl: number
  spot: number
  atm_strike: number
  entry_strike: number
  ce_price: number
  pe_price: number
  straddle: number
  synthetic_future: number
  adjustments: number
}

export interface TradeEntry {
  time: number
  type: 'ENTRY' | 'ADJUSTMENT' | 'EXIT'
  strike: number
  old_strike?: number
  ce_price: number
  pe_price: number
  straddle: number
  exit_ce?: number
  exit_pe?: number
  exit_straddle?: number
  spot: number
  leg_pnl: number
  cumulative_pnl: number
}

export interface SimulationSummary {
  total_pnl: number
  total_adjustments: number
  max_pnl: number
  min_pnl: number
}

export interface CustomStraddleData {
  underlying: string
  underlying_ltp: number
  expiry_date: string
  interval: string
  days_to_expiry: number
  adjustment_points: number
  lot_size: number
  lots: number
  quantity: number
  pnl_series: PnLDataPoint[]
  trades: TradeEntry[]
  summary: SimulationSummary
}

export interface CustomStraddleResponse {
  status: 'success' | 'error'
  message?: string
  data?: CustomStraddleData
}

export interface IntervalsData {
  seconds: string[]
  minutes: string[]
  hours: string[]
}

export interface IntervalsResponse {
  status: 'success' | 'error'
  message?: string
  data?: IntervalsData
}

export const customStraddleApi = {
  simulate: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
    interval: string
    days?: number
    adjustment_points?: number
    lot_size?: number
    lots?: number
  }): Promise<CustomStraddleResponse> => {
    const response = await webClient.post<CustomStraddleResponse>(
      '/straddlepnl/api/simulate',
      params
    )
    return response.data
  },

  getIntervals: async (): Promise<IntervalsResponse> => {
    const response = await webClient.get<IntervalsResponse>('/straddlepnl/api/intervals')
    return response.data
  },

  getLotSize: async (underlying: string, exchange: string): Promise<{ status: string; lotsize: number | null }> => {
    const response = await webClient.get<{ status: string; lotsize: number | null }>(
      `/straddlepnl/api/lotsize?underlying=${underlying}&exchange=${exchange}`
    )
    return response.data
  },
}
