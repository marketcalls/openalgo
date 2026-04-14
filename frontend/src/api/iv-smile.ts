import { webClient } from './client'

export interface IVSmileChainItem {
  strike: number
  ce_iv: number | null
  pe_iv: number | null
}

export interface IVSmileDataResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  spot_price?: number
  atm_strike?: number
  atm_iv?: number | null
  skew?: number | null
  expiry_date?: string
  chain?: IVSmileChainItem[]
}

export interface UnderlyingsResponse {
  status: 'success' | 'error'
  underlyings: string[]
}

export interface ExpiriesResponse {
  status: 'success' | 'error'
  expiries: string[]
}

export const ivSmileApi = {
  getIVSmileData: async (params: {
    underlying: string
    exchange: string
    expiry_date: string
  }): Promise<IVSmileDataResponse> => {
    const response = await webClient.post<IVSmileDataResponse>(
      '/ivsmile/api/iv-smile-data',
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
