import { webClient } from './client'

export interface GammaDensityStrike {
  strike: number
  ce_oi: number
  pe_oi: number
  iv: number | null
  density_intraday: number
  density_expiry: number
}

export interface ExpectedMoveBand {
  sigma_move: number
  one_sigma_low: number
  one_sigma_high: number
  two_sigma_low: number
  two_sigma_high: number
}

export interface GammaDensityResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  exchange?: string
  expiry_date?: string
  spot_price?: number
  forward_price?: number
  atm_strike?: number
  atm_iv?: number
  dte_days?: number
  interest_rate?: number
  peak_intraday_strike?: number | null
  peak_expiry_strike?: number | null
  sigma_move?: number
  one_sigma_low?: number
  one_sigma_high?: number
  two_sigma_low?: number
  two_sigma_high?: number
  intraday_band?: ExpectedMoveBand
  expiry_band?: ExpectedMoveBand
  chain?: GammaDensityStrike[]
}

export interface UnderlyingsResponse {
  status: 'success' | 'error'
  underlyings: string[]
}

export interface ExpiriesResponse {
  status: 'success' | 'error'
  expiries: string[]
}

export const gammaDensityApi = {
  getGammaDensity: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<GammaDensityResponse> => {
    const response = await webClient.post<GammaDensityResponse>(
      '/gammadensity/api/gamma-data',
      params
    )
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
