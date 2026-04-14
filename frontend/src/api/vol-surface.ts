import { webClient } from './client'

export interface VolSurfaceExpiry {
  date: string
  dte: number
}

export interface VolSurfaceData {
  underlying: string
  underlying_ltp: number
  atm_strike: number
  strikes: number[]
  expiries: VolSurfaceExpiry[]
  surface: (number | null)[][]
}

export interface VolSurfaceResponse {
  status: 'success' | 'error'
  message?: string
  data?: VolSurfaceData
}

export const volSurfaceApi = {
  getSurfaceData: async (params: {
    underlying: string
    exchange: string
    expiry_dates: string[]
    strike_count?: number
  }): Promise<VolSurfaceResponse> => {
    const response = await webClient.post<VolSurfaceResponse>(
      '/volsurface/api/surface-data',
      params
    )
    return response.data
  },
}
