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
  risk_monitoring?: string
  auto_squareoff_time?: string | null
  default_exit_execution?: string
  // Risk defaults
  default_stoploss_type?: string | null
  default_stoploss_value?: number | null
  default_target_type?: string | null
  default_target_value?: number | null
  default_trailstop_type?: string | null
  default_trailstop_value?: number | null
  default_breakeven_type?: string | null
  default_breakeven_threshold?: number | null
  // Daily circuit breaker configuration
  daily_stoploss_type?: string
  daily_stoploss_value?: number
  daily_target_type?: string
  daily_target_value?: number
  daily_trailstop_type?: string
  daily_trailstop_value?: number
  created_at: string
  updated_at: string
}

// Circuit breaker Socket.IO event types

export interface CircuitBreakerEvent {
  strategy_id?: number
  strategy_type?: string
  action: 'tripped' | 'daily_reset'
  reason?: string
  daily_pnl?: number
  trading_date?: string
}

export interface StrategyPnlUpdate {
  strategy_id: number
  strategy_type: string
  total_unrealized_pnl: number
  position_count: number
  daily_realized_pnl: number
  daily_total_pnl: number
  circuit_breaker_active: boolean
  circuit_breaker_reason: string
}

export interface CircuitBreakerStatus {
  isTripped: boolean
  reason: string
  dailyRealizedPnl: number
  dailyTotalPnl: number
  totalUnrealizedPnl: number
  positionCount: number
  lastUpdate: number
}

export type CircuitBreakerReason = 'daily_stoploss' | 'daily_target' | 'daily_trailstop'

export interface StrategySymbolMapping {
  id: number
  strategy_id?: number
  symbol: string
  exchange: string
  quantity: number
  product_type: 'MIS' | 'CNC' | 'NRML'
  // Options config
  order_mode?: string
  underlying?: string | null
  underlying_exchange?: string | null
  expiry_type?: string | null
  offset?: string | null
  option_type?: string | null
  risk_mode?: string | null
  preset?: string | null
  legs_config?: string | null
  // Per-symbol risk overrides
  stoploss_type?: string | null
  stoploss_value?: number | null
  target_type?: string | null
  target_value?: number | null
  trailstop_type?: string | null
  trailstop_value?: number | null
  breakeven_type?: string | null
  breakeven_threshold?: number | null
  exit_execution?: string | null
  // Combined risk (multi-leg)
  combined_stoploss_type?: string | null
  combined_stoploss_value?: number | null
  combined_target_type?: string | null
  combined_target_value?: number | null
  combined_trailstop_type?: string | null
  combined_trailstop_value?: number | null
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

export type OrderMode = 'equity' | 'futures' | 'single_option' | 'multi_leg'
export type ExpiryType = 'current_week' | 'next_week' | 'current_month' | 'next_month'

export const ORDER_MODES: { value: OrderMode; label: string }[] = [
  { value: 'equity', label: 'Equity' },
  { value: 'futures', label: 'Futures' },
  { value: 'single_option', label: 'Single Option' },
  { value: 'multi_leg', label: 'Multi Leg' },
]

export const EXPIRY_TYPES: { value: ExpiryType; label: string }[] = [
  { value: 'current_week', label: 'Current Week' },
  { value: 'next_week', label: 'Next Week' },
  { value: 'current_month', label: 'Current Month' },
  { value: 'next_month', label: 'Next Month' },
]

export const OFFSET_VALUES = [
  'ATM',
  ...Array.from({ length: 40 }, (_, i) => `ITM${i + 1}`),
  ...Array.from({ length: 40 }, (_, i) => `OTM${i + 1}`),
]

export const OPTION_TYPES = ['CE', 'PE'] as const

export interface AddSymbolRequest {
  symbol: string
  exchange: string
  quantity: number
  product_type: string
  order_mode?: OrderMode
  underlying?: string
  underlying_exchange?: string
  expiry_type?: ExpiryType
  offset?: string
  option_type?: string
  risk_mode?: string
  preset?: string
  legs_config?: string
}

export interface BulkSymbolRequest {
  csv_data: string
}

export interface SymbolSearchResult {
  symbol: string
  name: string
  exchange: string
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
