// Chartink Strategy Types

export interface ChartinkStrategy {
  id: number
  name: string
  webhook_id: string
  is_active: boolean
  is_intraday: boolean
  start_time: string | null
  end_time: string | null
  squareoff_time: string | null
  created_at: string
  updated_at: string
}

export interface ChartinkSymbolMapping {
  id: number
  strategy_id: number
  chartink_symbol: string
  exchange: 'NSE' | 'BSE'
  quantity: number
  product_type: 'MIS' | 'CNC'
  created_at: string
}

export interface CreateChartinkStrategyRequest {
  name: string
  strategy_type: 'intraday' | 'positional'
  start_time?: string
  end_time?: string
  squareoff_time?: string
}

export interface AddChartinkSymbolRequest {
  symbol: string // Backend expects 'symbol', stores as 'chartink_symbol'
  exchange: 'NSE' | 'BSE'
  quantity: number
  product_type: 'MIS' | 'CNC'
}

// Chartink only supports NSE and BSE
export const CHARTINK_EXCHANGES = ['NSE', 'BSE'] as const
export type ChartinkExchange = (typeof CHARTINK_EXCHANGES)[number]

// Chartink only supports MIS and CNC
export const CHARTINK_PRODUCTS = ['MIS', 'CNC'] as const
export type ChartinkProduct = (typeof CHARTINK_PRODUCTS)[number]
