/**
 * Type contracts for the Strategy v2 backend.
 * Matches services/strategy/* + restx_api/strategy_v2_schemas.py.
 */

export type StrategyMode = 'live' | 'sandbox'
export type StrategyState =
  | 'DRAFT'
  | 'ARMED'
  | 'DISABLED'
  | 'ARCHIVED'
export type RunState =
  | 'ARMED'
  | 'ENTERING'
  | 'IN_TRADE'
  | 'EXITING'
  | 'CLOSED'
  | 'ENTRY_FAILED'
  | 'EXIT_FAILED'
  | 'ERRORED'
  | 'STOPPED'

export type SigningMethod = 'NONE' | 'BODY_SECRET' | 'HMAC_SHA256' | 'BOTH'

export type Segment = 'CASH' | 'FUT' | 'OPT'
export type Position = 'B' | 'S'
export type ProductType = 'MIS' | 'CNC' | 'NRML'
export type OptionType = 'CE' | 'PE'
export type ExpiryType = 'CURRENT_WEEK' | 'NEXT_WEEK' | 'CURRENT_MONTH' | 'NEXT_MONTH'
export type StrikeCriteria = 'ATM' | 'STRIKE_OFFSET' | 'PREMIUM' | 'DELTA'
export type RiskUnit = 'pts' | 'pct'

export interface StrategyV2 {
  id: number
  name: string
  webhook_id: string
  user_id: string
  platform: string | null
  underlying: string | null
  underlying_exchange: string | null
  is_intraday: boolean
  start_time: string
  end_time: string
  squareoff_time: string | null
  state: StrategyState
  is_active: boolean
  mode: StrategyMode
  webhook_signing_method: SigningMethod
  webhook_replay_window_seconds: number
  webhook_ip_allowlist: string[]
  created_at: string | null
  updated_at: string | null
}

export interface StrategyLeg {
  id: number
  leg_index: number
  segment: Segment
  position: Position
  product: ProductType

  // CASH-only
  symbol_cash: string | null
  qty: number | null

  // FUT + OPT
  expiry_type: ExpiryType | null
  lots: number | null

  // OPT-only
  option_type: OptionType | null
  strike_criteria: StrikeCriteria | null
  strike_value: number | null

  // Per-leg RMS (each pair pts or pct)
  target_enabled: boolean
  target_value: number | null
  target_unit: RiskUnit | null
  sl_enabled: boolean
  sl_value: number | null
  sl_unit: RiskUnit | null
  trail_enabled: boolean
  trail_x: number | null
  trail_y: number | null
  trail_unit: RiskUnit | null
  momentum_enabled: boolean
  momentum_value: number | null
  momentum_unit: RiskUnit | null

  // Cached at arm-time
  resolved_symbol: string | null
  resolved_exchange: string | null
  lot_size_cache: number | null
  tick_size_cache: number | null
}

export interface StrategyV2WithLegs {
  status: string
  strategy: StrategyV2
  legs: StrategyLeg[]
}

export interface StrategyV2CreatePayload {
  name: string
  platform?: string
  underlying?: string | null
  underlying_exchange?: string | null
  is_intraday?: boolean
  start_time: string
  end_time: string
  squareoff_time?: string | null
  mode?: StrategyMode
  webhook_signing_method?: SigningMethod
  webhook_replay_window_seconds?: number
  webhook_ip_allowlist?: string[] | null
}

export type StrategyV2UpdatePayload = Partial<StrategyV2CreatePayload> & {
  is_active?: boolean
}

export interface LegPayload {
  leg_index: number
  segment: Segment
  position: Position
  product: ProductType

  symbol_cash?: string | null
  qty?: number | null

  expiry_type?: ExpiryType | null
  lots?: number | null

  option_type?: OptionType | null
  strike_criteria?: StrikeCriteria | null
  strike_value?: number | null

  target_enabled?: boolean
  target_value?: number | null
  target_unit?: RiskUnit | null
  sl_enabled?: boolean
  sl_value?: number | null
  sl_unit?: RiskUnit | null
  trail_enabled?: boolean
  trail_x?: number | null
  trail_y?: number | null
  trail_unit?: RiskUnit | null
  momentum_enabled?: boolean
  momentum_value?: number | null
  momentum_unit?: RiskUnit | null
}

export interface WebhookRotateResponse {
  status: string
  strategy: StrategyV2 & {
    webhook_secret?: string
    webhook_hmac_key?: string
  }
  message: string
}

export interface WebhookTestResponse {
  status: 'success' | 'error'
  code?: string
  message?: string
  mode?: 'dry_run'
  signing_method?: SigningMethod
  strategy_id?: number
  errors?: unknown
}

export interface AuditVerifyResponse {
  status: 'ok' | 'tampered' | 'error'
  events_verified?: number
  first_bad_event_id?: number
  expected_row_hash?: string
  stored_row_hash?: string
  message?: string
}
