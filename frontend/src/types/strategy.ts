// Strategy Types for Webhook-based Strategies

export interface Strategy {
  id: number
  name: string
  webhook_id: string
  platform: 'tradingview' | 'amibroker' | 'python' | 'metatrader' | 'excel' | 'others'
  is_active: boolean
  is_intraday: boolean
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
  start_time: string | null
  end_time: string | null
  squareoff_time: string | null
  created_at: string
  updated_at: string
}

export interface StrategySymbolMapping {
  id: number
  strategy_id: number
  symbol: string
  exchange: string
  quantity: number
  product_type: 'MIS' | 'CNC' | 'NRML'
  created_at: string
}

export interface CreateStrategyRequest {
  name: string
  platform: string
  strategy_type: 'intraday' | 'positional'
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
  start_time?: string
  end_time?: string
  squareoff_time?: string
}

export interface AddSymbolRequest {
  symbol: string
  exchange: string
  quantity: number
  product_type: string
}

export interface BulkSymbolRequest {
  csv_data: string
}

export interface SymbolSearchResult {
  symbol: string
  brsymbol: string
  name: string
  exchange: string
  token: string
  lotsize: number
}

export type Platform = 'tradingview' | 'amibroker' | 'python' | 'metatrader' | 'excel' | 'others'

export const PLATFORMS: { value: Platform; label: string }[] = [
  { value: 'tradingview', label: 'TradingView' },
  { value: 'amibroker', label: 'Amibroker' },
  { value: 'python', label: 'Python' },
  { value: 'metatrader', label: 'Metatrader' },
  { value: 'excel', label: 'Excel' },
  { value: 'others', label: 'Others' },
]

export const EXCHANGES = ['NSE', 'BSE', 'NFO', 'CDS', 'BFO', 'BCD', 'MCX', 'NCDEX'] as const
export type Exchange = (typeof EXCHANGES)[number]

export const EQUITY_EXCHANGES = ['NSE', 'BSE'] as const
export const DERIVATIVE_EXCHANGES = ['NFO', 'CDS', 'BFO', 'BCD', 'MCX', 'NCDEX'] as const

export function getProductTypes(exchange: string): string[] {
  if (EQUITY_EXCHANGES.includes(exchange as (typeof EQUITY_EXCHANGES)[number])) {
    return ['MIS', 'CNC']
  }
  return ['MIS', 'NRML']
}

export const TRADING_MODES = [
  {
    value: 'LONG',
    label: 'LONG Only',
    description: 'Only buy signals (BUY to open, SELL to close)',
  },
  {
    value: 'SHORT',
    label: 'SHORT Only',
    description: 'Only sell signals (SHORT to open, COVER to close)',
  },
  { value: 'BOTH', label: 'BOTH', description: 'Both long and short positions' },
] as const
