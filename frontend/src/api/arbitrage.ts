import { webClient } from './client'

export interface ArbitrageLeg {
  symbol: string
  exchange: string
  expiry: string
  lotsize: number | null
  tick_size: number | null
}

export type ArbitragePairType = 'near-next' | 'near-third'

export interface ArbitragePair {
  id: string
  underlying: string
  exchange: string
  type: ArbitragePairType
  near: ArbitrageLeg
  far: ArbitrageLeg
}

export interface ArbitrageSymbol {
  symbol: string
  exchange: string
}

export interface ArbitrageUniverseData {
  pairs: ArbitragePair[]
  symbols: ArbitrageSymbol[]
  counts: {
    underlyings: number
    pairs: number
    symbols: number
  }
  generated_at: string
}

export interface ArbitrageUniverseResponse {
  status: 'success' | 'error'
  message?: string
  data?: ArbitrageUniverseData
}

export const arbitrageApi = {
  /**
   * Fetch the futures calendar-spread universe (near/next/third-month pairs)
   * for the requested exchanges. Session-authenticated (uses the server-side
   * API key); no apikey is sent in the request.
   */
  getUniverse: async (exchanges: string[] = ['NFO', 'MCX']): Promise<ArbitrageUniverseResponse> => {
    const response = await webClient.get<ArbitrageUniverseResponse>('/arbitrage/api/universe', {
      params: { exchanges: exchanges.join(',') },
    })
    return response.data
  },
}
