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
// Phase 9 — strategy-level segment selector. Drives which fields the
// builder shows and how the leg resolver looks up contracts.
//   CASH      — per-leg stock symbol on NSE/BSE (no underlying)
//   INDEX_FO  — futures/options on an index (NIFTY/BANKNIFTY/SENSEX)
//   STOCK_FO  — futures/options on a single stock (RELIANCE/INFY etc.)
export type StrategySegment = 'CASH' | 'INDEX_FO' | 'STOCK_FO'
// Phase 9 — per-leg exchange for CASH legs. Other segments derive their
// exchange from the strategy underlying_exchange at resolve time.
export type CashExchange =
  | 'NSE'
  | 'BSE'
  | 'NFO'
  | 'BFO'
  | 'CDS'
  | 'BCD'
  | 'MCX'
  | 'NCDEX'
  | 'NCO'
export type Position = 'B' | 'S'
export type ProductType = 'MIS' | 'CNC' | 'NRML'
export type OptionType = 'CE' | 'PE'
export type ExpiryType = 'CURRENT_WEEK' | 'NEXT_WEEK' | 'CURRENT_MONTH' | 'NEXT_MONTH'
export type StrikeCriteria = 'ATM' | 'STRIKE_OFFSET' | 'PREMIUM' | 'DELTA'
export type RiskUnit = 'pts' | 'pct'

// Phase 9.2 — per-row live snapshot embedded by GET /strategy
// (computed server-side from each strategy's active run + today's
// realized roll-up). Subsequent updates arrive over Socket.IO via
// strategy_pnl_tick (room-scoped per strategy_id).
export interface StrategyLiveSnapshot {
  active_run_id: number | null
  active_state: RunState | null
  agg_mtm: number
  peak_mtm: number
  drawdown: number
  realized_today: number
}

export interface StrategyV2 {
  id: number
  name: string
  webhook_id: string
  user_id: string
  platform: string | null
  segment: StrategySegment
  underlying: string | null
  underlying_exchange: string | null
  is_intraday: boolean
  start_time: string
  end_time: string | null
  squareoff_time: string | null
  exit_date: string | null         // YYYY-MM-DD (positional)
  run_forever: boolean             // positional, mutually exclusive with exit_date
  state: StrategyState
  is_active: boolean
  mode: StrategyMode
  // Optional — present on list responses, absent on single-strategy GETs.
  live?: StrategyLiveSnapshot
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
  exchange_cash: CashExchange | null
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
  segment?: StrategySegment
  underlying?: string | null
  underlying_exchange?: string | null
  is_intraday?: boolean
  start_time: string
  end_time?: string | null
  squareoff_time?: string | null
  exit_date?: string | null
  run_forever?: boolean
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
  exchange_cash?: CashExchange | null
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

// ----------------------------------------------------------------------------
// Phase 2 — runs / orderbook / tradebook / positionbook / events
// ----------------------------------------------------------------------------

export interface StrategyRun {
  id: number
  strategy_id: number
  state: RunState
  mode: StrategyMode
  exit_reason: string | null
  triggered_at: string | null
  entered_at: string | null
  exited_at: string | null
  peak_mtm: number
  trough_mtm: number
  profit_locked: boolean
  realized_pnl: number
  max_unrealized_pnl: number
  max_drawdown: number
  signal_source: string | null
}

export interface RunOrderRow {
  // Same shape as /orderbook row:
  action: string
  symbol: string
  exchange: string
  orderid: string
  product: string
  quantity: string
  price: number
  pricetype: string
  order_status: string
  trigger_price: number
  timestamp: string
  // Strategy-only:
  source: string
  mode: StrategyMode
  leg_id: number | null
  run_id: number
  rms_event_id: number | null
}

export interface RunOrderbookResponse {
  status: string
  data: {
    orders: RunOrderRow[]
    statistics: {
      total_buy_orders: number
      total_sell_orders: number
      total_completed_orders: number
      total_open_orders: number
      total_rejected_orders: number
    }
  }
}

export interface RunTradeRow {
  action: string
  symbol: string
  exchange: string
  orderid: string
  product: string
  quantity: number
  average_price: number
  trade_value: number
  timestamp: string
  leg_id: number | null
  run_id: number
  broker_tradeid: string
}

export interface RunPositionRow {
  symbol: string
  exchange: string
  product: string
  quantity: string
  average_price: string
  ltp: string
  pnl: string
  leg_id: number
  run_id: number
  net_qty: number
  avg_entry: number | null
  ltp_decimal: number | null
  unrealized_pnl: number
  realized_pnl: number
  current_sl_price: number | null
  current_target_price: number | null
  trail_advances_count: number
  leg_state: string
}

export interface RunEventRow {
  id: number
  type: string
  ts_utc: number
  ts_ist: string
  leg_id: number | null
  payload: unknown
  row_hash: string | null
}

export interface RunListResponse<T> {
  status: string
  data: T[]
}

// ----------------------------------------------------------------------------
// Phase 4 — strategy-level risk config (overall SL / target / lock / trail-to-entry)
// ----------------------------------------------------------------------------

export interface StrategyRiskConfig {
  strategy_id: number
  overall_sl_enabled: boolean
  overall_sl_abs: number | null

  overall_target_enabled: boolean
  overall_target_abs: number | null

  lock_profit_enabled: boolean
  lock_at_abs: number | null
  lock_min_abs: number | null

  trail_to_entry_enabled: boolean
  trail_to_entry_threshold: number
  trail_to_entry_unit: RiskUnit
}

export type RiskConfigPayload = Partial<Omit<StrategyRiskConfig, 'strategy_id'>>

// ----------------------------------------------------------------------------
// Phase 4.5 — account-level RMS
// ----------------------------------------------------------------------------

export interface AccountRiskConfig {
  user_id: string
  max_concurrent_runs: number | null
  max_daily_loss_abs: number | null
  cooldown_after_loss_minutes: number | null
  max_runs_per_strategy_per_day: number | null
  min_seconds_between_runs: number | null
  auto_clear_at: string | null
  is_locked_out: boolean
  lockout_reason: string | null
  lockout_until: string | null
}

export interface AccountState {
  user_id: string
  active_run_count: number
  realized_pnl_today_live: number
  realized_pnl_today_sandbox: number
  unrealized_pnl_aggregate: number
}

export interface AccountRiskConfigResponse {
  status: string
  config: AccountRiskConfig
  state: AccountState
}

export type AccountRiskConfigPayload = Partial<
  Pick<
    AccountRiskConfig,
    | 'max_concurrent_runs'
    | 'max_daily_loss_abs'
    | 'cooldown_after_loss_minutes'
    | 'max_runs_per_strategy_per_day'
    | 'min_seconds_between_runs'
    | 'auto_clear_at'
  >
>
