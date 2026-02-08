import { webClient } from './client'

export interface IVDataPoint {
  time: number
  iv: number | null
  delta: number | null
  gamma: number | null
  theta: number | null
  vega: number | null
  option_price: number
  underlying_price: number
}

export interface IVSeries {
  symbol: string
  option_type: 'CE' | 'PE'
  strike: number
  iv_data: IVDataPoint[]
}

export interface IVChartData {
  underlying: string
  underlying_ltp: number
  atm_strike: number
  ce_symbol: string
  pe_symbol: string
  interval: string
  series: IVSeries[]
}

export interface IVChartResponse {
  status: 'success' | 'error'
  message?: string
  data?: IVChartData
}

export interface DefaultSymbolsData {
  ce_symbol: string
  pe_symbol: string
  atm_strike: number
  exchange: string
  underlying_ltp: number
}

export interface DefaultSymbolsResponse {
  status: 'success' | 'error'
  message?: string
  data?: DefaultSymbolsData
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

export interface UnderlyingsResponse {
  status: 'success' | 'error'
  underlyings: string[]
}

export interface ExpiriesResponse {
  status: 'success' | 'error'
  expiries: string[]
}

export const ivChartApi = {
  getIVData: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
    interval: string
    days?: number
  }): Promise<IVChartResponse> => {
    const response = await webClient.post<IVChartResponse>('/ivchart/api/iv-data', params)
    return response.data
  },

  getDefaultSymbols: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<DefaultSymbolsResponse> => {
    const response = await webClient.post<DefaultSymbolsResponse>(
      '/ivchart/api/default-symbols',
      params
    )
    return response.data
  },

  getIntervals: async (): Promise<IntervalsResponse> => {
    const response = await webClient.get<IntervalsResponse>('/ivchart/api/intervals')
    return response.data
  },

  getUnderlyings: async (exchange: string): Promise<UnderlyingsResponse> => {
    const response = await webClient.get<UnderlyingsResponse>(
      `/search/api/underlyings?exchange=${exchange}`
    )
    return response.data
  },

  getExpiries: async (exchange: string, underlying: string): Promise<ExpiriesResponse> => {
    const response = await webClient.get<ExpiriesResponse>(
      `/search/api/expiries?exchange=${exchange}&underlying=${underlying}`
    )
    return response.data
  },
}
