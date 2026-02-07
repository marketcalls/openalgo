import { webClient } from './client'

export interface OIChainItem {
  strike: number
  ce_oi: number
  pe_oi: number
}

export interface OIDataResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  spot_price?: number
  futures_price?: number | null
  lot_size?: number
  pcr_oi?: number
  pcr_volume?: number
  total_ce_oi?: number
  total_pe_oi?: number
  atm_strike?: number
  expiry_date?: string
  chain?: OIChainItem[]
}

export interface PainDataItem {
  strike: number
  ce_pain: number
  pe_pain: number
  total_pain: number
  total_pain_cr: number
}

export interface MaxPainResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  spot_price?: number
  futures_price?: number | null
  atm_strike?: number
  max_pain_strike?: number
  lot_size?: number
  pcr_oi?: number
  pcr_volume?: number
  expiry_date?: string
  pain_data?: PainDataItem[]
}

export interface UnderlyingsResponse {
  status: 'success' | 'error'
  underlyings: string[]
}

export interface ExpiriesResponse {
  status: 'success' | 'error'
  expiries: string[]
}

export const oiTrackerApi = {
  getOIData: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<OIDataResponse> => {
    const response = await webClient.post<OIDataResponse>('/oitracker/api/oi-data', params)
    return response.data
  },

  getMaxPain: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<MaxPainResponse> => {
    const response = await webClient.post<MaxPainResponse>('/oitracker/api/maxpain', params)
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
