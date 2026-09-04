// api/brokerage.ts
// Client for the brokerage estimation endpoints. The backend resolves the
// trade segment from exchange/product/symbol and reads the tariff from
// data/broker_charges_comparison.csv (Fyers / Zerodha / Dhan / Groww only).

import { webClient } from './client'

export interface BrokerageEstimate {
  broker: string
  segment: string
  exchange: string
  charge_exchange: string
  side: 'BUY' | 'SELL'
  quantity: number
  price: number
  lot_size: number
  turnover: number
  components: Record<string, number>
  total: number
  notes: string[]
}

export interface BrokerageEstimateRequest {
  symbol: string
  exchange?: string
  product?: string
  side?: 'BUY' | 'SELL'
  quantity?: number
  price?: number
  instrumenttype?: string
  lotSize?: number
}

export interface BrokerageEstimateResponse {
  status: string
  data: BrokerageEstimate
}

export interface BrokerageBatchItem {
  status: string
  data?: BrokerageEstimate
  message?: string
}

export interface BrokerageBatchResponse {
  status: string
  data: BrokerageBatchItem[]
}

/** Brokers whose tariff sheet we carry. Used to gate UI surfaces (calculator,
 * order book) before a call so unsupported brokers never hit the endpoint. */
export const BROKERAGE_BROKERS = new Set(['fyers', 'zerodha', 'dhan', 'groww'])

export const brokerageApi = {
  /**
   * Estimate broker charges for a single trade.
   */
  estimate: async (payload: BrokerageEstimateRequest): Promise<BrokerageEstimateResponse> => {
    const response = await webClient.post<BrokerageEstimateResponse>(
      '/brokerage-charges/api/estimate',
      payload
    )
    return response.data
  },

  /**
   * Estimate broker charges for many orders (order book page). The response
   * results align 1:1 with the submitted order list.
   */
  estimateBatch: async (orders: BrokerageEstimateRequest[]): Promise<BrokerageBatchResponse> => {
    const response = await webClient.post<BrokerageBatchResponse>(
      '/brokerage-charges/api/estimate/batch',
      { orders }
    )
    return response.data
  },
}