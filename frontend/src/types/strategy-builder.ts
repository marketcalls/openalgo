// Strategy Builder Types — F&O multi-leg strategy construction

export type BuilderExchange = 'NFO' | 'BFO' | 'CDS' | 'BCD' | 'MCX'

export type StrikeType = 'ATM' | 'ITM' | 'OTM' | 'specific' | 'premium_near'

export interface BuilderLeg {
  id: string // client-side UUID
  leg_type: 'option' | 'future'
  action: 'BUY' | 'SELL'
  option_type: 'CE' | 'PE' | null // null for futures
  strike_type: StrikeType
  offset: string // ATM, ITM1-ITM20, OTM1-OTM20
  expiry_type: 'current_week' | 'next_week' | 'current_month' | 'next_month'
  product_type: 'MIS' | 'NRML'
  quantity_lots: number
  order_type: 'MARKET' | 'LIMIT'
  // Per-leg risk (when risk_mode = 'per_leg')
  stoploss_type?: string | null
  stoploss_value?: number | null
  target_type?: string | null
  target_value?: number | null
}

export interface PresetDefinition {
  id: string
  name: string
  description: string
  category: 'neutral' | 'bullish' | 'bearish'
  legs: Omit<BuilderLeg, 'id'>[]
}

export type BuilderStep = 'basics' | 'legs' | 'risk' | 'review'

export interface BuilderBasics {
  name: string
  exchange: BuilderExchange
  underlying: string
  expiry_type: 'current_week' | 'next_week' | 'current_month' | 'next_month'
  product_type: 'MIS' | 'NRML'
  is_intraday: boolean
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
}

export interface BuilderRiskConfig {
  risk_mode: 'per_leg' | 'combined'
  // Combined risk (when risk_mode = 'combined')
  combined_stoploss_type: string | null
  combined_stoploss_value: number | null
  combined_target_type: string | null
  combined_target_value: number | null
  combined_trailstop_type: string | null
  combined_trailstop_value: number | null
  // Strategy-level defaults
  default_stoploss_type: string | null
  default_stoploss_value: number | null
  default_target_type: string | null
  default_target_value: number | null
  default_trailstop_type: string | null
  default_trailstop_value: number | null
  default_breakeven_type: string | null
  default_breakeven_threshold: number | null
}

export interface BuilderState {
  step: BuilderStep
  basics: BuilderBasics
  legs: BuilderLeg[]
  riskConfig: BuilderRiskConfig
  riskMode: 'per_leg' | 'combined'
  preset: string | null
}

export const DEFAULT_BUILDER_BASICS: BuilderBasics = {
  name: '',
  exchange: 'NFO',
  underlying: 'NIFTY',
  expiry_type: 'current_week',
  product_type: 'MIS',
  is_intraday: true,
  trading_mode: 'BOTH',
}

export const DEFAULT_RISK_CONFIG: BuilderRiskConfig = {
  risk_mode: 'combined',
  combined_stoploss_type: null,
  combined_stoploss_value: null,
  combined_target_type: null,
  combined_target_value: null,
  combined_trailstop_type: null,
  combined_trailstop_value: null,
  default_stoploss_type: null,
  default_stoploss_value: null,
  default_target_type: null,
  default_target_value: null,
  default_trailstop_type: null,
  default_trailstop_value: null,
  default_breakeven_type: null,
  default_breakeven_threshold: null,
}
