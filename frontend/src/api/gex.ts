import { webClient } from './client'

export interface GEXChainItem {
  strike: number
  ce_oi: number
  pe_oi: number
  ce_gamma: number
  pe_gamma: number
  ce_gex: number
  pe_gex: number
  net_gex: number
}

export interface GEXDataResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  spot_price?: number
  futures_price?: number | null
  lot_size?: number
  atm_strike?: number
  expiry_date?: string
  pcr_oi?: number
  total_ce_oi?: number
  total_pe_oi?: number
  total_ce_gex?: number
  total_pe_gex?: number
  total_net_gex?: number
  chain?: GEXChainItem[]
}

export interface UnderlyingsResponse {
  status: 'success' | 'error'
  underlyings: string[]
}

export interface ExpiriesResponse {
  status: 'success' | 'error'
  expiries: string[]
}

export const gexApi = {
  getGEXData: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<GEXDataResponse> => {
    const response = await webClient.post<GEXDataResponse>('/gex/api/gex-data', params)
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
