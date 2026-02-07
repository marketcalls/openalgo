import { webClient } from './client'

export interface StraddleDataPoint {
  time: number
  spot: number
  atm_strike: number
  ce_price: number
  pe_price: number
  straddle: number
  synthetic_future: number
}

export interface StraddleChartData {
  underlying: string
  underlying_ltp: number
  expiry_date: string
  interval: string
  days_to_expiry: number
  series: StraddleDataPoint[]
}

export interface StraddleChartResponse {
  status: 'success' | 'error'
  message?: string
  data?: StraddleChartData
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

export const straddleChartApi = {
  getStraddleData: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
    interval: string
    days?: number
  }): Promise<StraddleChartResponse> => {
    const response = await webClient.post<StraddleChartResponse>(
      '/straddle/api/straddle-data',
      params
    )
    return response.data
  },

  getIntervals: async (): Promise<IntervalsResponse> => {
    const response = await webClient.get<IntervalsResponse>('/straddle/api/intervals')
    return response.data
  },
}
