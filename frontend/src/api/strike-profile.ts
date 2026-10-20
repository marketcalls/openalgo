import { webClient } from './client'

/** One strike of one expiry. Exposures are in rupees crore. */
export interface StrikeProfileCell {
  ce_oi: number
  pe_oi: number
  ce_gex: number
  pe_gex: number
  ce_dex: number
  pe_dex: number
  gex: number
  dex: number
  /** Open interest was present but its Greeks could not be computed. */
  unpriced: boolean
}

export interface StrikeProfileExpiry {
  expiry: string
  expiry_ts: number | null
  /** Calendar days to expiry, counted in IST. */
  dte: number | null
  years?: number
  forward?: number
  lot_size?: number | null
  available: boolean
  message?: string
  net_gex?: number
  net_dex?: number
  /** Aligned to `strikes`; null where this expiry does not list the strike. */
  cells: (StrikeProfileCell | null)[]
}

export interface StrikeProfileResponse {
  status: 'success' | 'error'
  message?: string
  underlying?: string
  exchange?: string
  spot_price?: number
  as_of?: number
  range_pct?: number | null
  strikes?: number[]
  flip?: number | null
  call_wall?: number | null
  put_wall?: number | null
  expiries?: StrikeProfileExpiry[]
}

export const strikeProfileApi = {
  getProfileData: async (params: {
    underlying: string
    exchange: string
    expiry_dates: string[]
    range_pct: number | null
  }): Promise<StrikeProfileResponse> => {
    const response = await webClient.post<StrikeProfileResponse>(
      '/strikeprofile/api/profile-data',
      params
    )
    return response.data
  },

  getUnderlyings: async (exchange: string) => {
    const response = await webClient.get<{ status: 'success' | 'error'; underlyings: string[] }>(
      `/search/api/underlyings?exchange=${exchange}`
    )
    return response.data
  },

  getExpiries: async (exchange: string, underlying: string) => {
    const response = await webClient.get<{ status: 'success' | 'error'; expiries: string[] }>(
      `/search/api/expiries?exchange=${exchange}&underlying=${underlying}&instrumenttype=options`
    )
    return response.data
  },
}
