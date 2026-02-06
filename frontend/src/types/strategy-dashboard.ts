// ── Position & Risk State ──────────────────────────

export type PositionState = 'pending_entry' | 'active' | 'exiting' | 'closed'

export type ExitReason =
  | 'stoploss'
  | 'target'
  | 'trailstop'
  | 'breakeven_sl'
  | 'combined_sl'
  | 'combined_target'
  | 'combined_tsl'
  | 'manual'
  | 'squareoff'
  | 'auto_squareoff'
  | 'rejected'

export type RiskMonitoringState = 'active' | 'paused' | null

export interface StrategyPosition {
  id: number
  strategy_id: number
  strategy_type: string
  symbol: string
  exchange: string
  product_type: 'MIS' | 'CNC' | 'NRML'
  action: 'BUY' | 'SELL'
  quantity: number
  average_entry_price: number
  ltp: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  realized_pnl: number
  stoploss_price: number | null
  target_price: number | null
  trailstop_price: number | null
  peak_price: number | null
  breakeven_activated: boolean
  position_state: PositionState
  exit_reason: ExitReason | null
  exit_detail: string | null
  exit_price: number | null
  group_id: string | null // UUID linking legs in combined P&L mode
  opened_at: string
  closed_at: string | null
}

// ── Position Group (Combined P&L) ──────────────────

export interface PositionGroup {
  id: string // UUID
  strategy_id: number
  strategy_type: string
  expected_legs: number
  filled_legs: number
  group_status: 'filling' | 'active' | 'exiting' | 'closed' | 'failed_exit'
  combined_pnl: number
  combined_peak_pnl: number
  entry_value: number // abs(Σ signed_entry_price × qty) — capital at risk
  initial_stop: number | null // TSL initial level (never changes after init)
  current_stop: number | null // ratcheted stop (only moves up, never down)
  exit_triggered: boolean // prevents duplicate exit attempts
}

// ── Strategy Dashboard ─────────────────────────────

export interface DashboardStrategy {
  id: number
  name: string
  webhook_id: string
  platform: string
  trading_mode: string
  is_active: boolean
  is_intraday: boolean
  risk_monitoring: RiskMonitoringState
  auto_squareoff_time: string | null

  // Risk defaults
  default_stoploss_type: string | null
  default_stoploss_value: number | null
  default_target_type: string | null
  default_target_value: number | null
  default_trailstop_type: string | null
  default_trailstop_value: number | null
  default_breakeven_type: string | null
  default_breakeven_threshold: number | null
  default_exit_execution: string

  // Daily circuit breaker config
  daily_stoploss_type?: string
  daily_stoploss_value?: number
  daily_target_type?: string
  daily_target_value?: number
  daily_trailstop_type?: string
  daily_trailstop_value?: number

  // Live aggregated (updated via SocketIO)
  positions: StrategyPosition[]
  total_pnl: number
  realized_pnl: number
  unrealized_pnl: number
  trade_count_today: number
  order_count: number
  win_rate: number | null
  profit_factor: number | null
}

export interface DashboardSummary {
  active_strategies: number
  paused_strategies: number
  open_positions: number
  total_pnl: number
}

export interface DashboardResponse {
  strategies: DashboardStrategy[]
  summary: DashboardSummary
}

// ── Orders & Trades ────────────────────────────────

export interface StrategyOrder {
  id: number
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number | null
  trigger_price: number | null
  price_type: string
  product_type: string
  order_status: string
  average_price: number | null
  filled_quantity: number | null
  exit_reason: ExitReason | null
  created_at: string
  updated_at: string
}

export interface StrategyTrade {
  id: number
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  trade_value: number
  product_type: string
  trade_type: 'entry' | 'exit'
  exit_reason: ExitReason | null
  pnl: number | null
  created_at: string
}

// ── P&L Analytics ──────────────────────────────────

export interface RiskMetrics {
  total_trades: number
  winning_trades: number
  losing_trades: number
  win_rate: number
  average_win: number
  average_loss: number
  risk_reward_ratio: number
  profit_factor: number
  expectancy: number
  best_trade: number
  worst_trade: number
  max_consecutive_wins: number
  max_consecutive_losses: number
  max_drawdown: number
  max_drawdown_pct: number
  current_drawdown: number
  current_drawdown_pct: number
  best_day: number
  worst_day: number
  average_daily_pnl: number
  days_active: number
}

export interface ExitBreakdownEntry {
  exit_reason: string
  count: number
  total_pnl: number
  avg_pnl: number
}

export interface DailyPnLEntry {
  date: string
  total_pnl: number
  cumulative_pnl: number
  drawdown: number
}

export interface PnLResponse {
  pnl: {
    total_pnl: number
    realized_pnl: number
    unrealized_pnl: number
  }
  risk_metrics: RiskMetrics
  exit_breakdown: ExitBreakdownEntry[]
  daily_pnl: DailyPnLEntry[]
}

// ── SocketIO Event Payloads ────────────────────────

export interface PositionUpdatePayload {
  position_id: number
  strategy_id: number
  symbol: string
  exchange: string
  ltp: number
  unrealized_pnl: number
  unrealized_pnl_pct: number
  stoploss_price: number | null
  target_price: number | null
  trailstop_price: number | null
  peak_price: number | null
  breakeven_activated: boolean
  position_state: PositionState
  exit_reason: ExitReason | null
  exit_detail: string | null
}

export interface StrategyPositionUpdatePayload {
  strategy_id: number
  strategy_type: string
  positions: PositionUpdatePayload[]
}

export interface PnLUpdatePayload {
  strategy_id: number
  strategy_type: string
  total_unrealized_pnl: number
  position_count: number
  daily_realized_pnl: number
  daily_total_pnl: number
  circuit_breaker_active: boolean
  circuit_breaker_reason: string
}

export interface ExitTriggeredPayload {
  strategy_id: number
  strategy_type: string
  symbol: string
  exchange: string
  exit_reason: ExitReason
  exit_detail: string
  trigger_ltp: number
}

export interface PositionOpenedPayload {
  strategy_id: number
  strategy_type: string
  position_id: number
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  average_entry_price: number
  stoploss_price: number | null
  target_price: number | null
  trailstop_price: number | null
}

export interface PositionClosedPayload {
  strategy_id: number
  strategy_type: string
  position_id: number
  symbol: string
  exchange: string
  exit_reason: string
  exit_detail: string
  pnl: number
  exit_price: number | null
}

export interface OrderRejectedPayload {
  strategy_id: number
  strategy_type: string
  position_id: number
  symbol: string
  exchange: string
  exit_reason: string
  reason: string
}

export interface CircuitBreakerPayload {
  strategy_id?: number
  strategy_type?: string
  action: 'tripped' | 'daily_reset'
  reason?: string
  daily_pnl?: number
  trading_date?: string
}

// ── Risk Configuration ─────────────────────────────

export interface RiskConfigUpdate {
  default_stoploss_type?: string | null
  default_stoploss_value?: number | null
  default_target_type?: string | null
  default_target_value?: number | null
  default_trailstop_type?: string | null
  default_trailstop_value?: number | null
  default_breakeven_type?: string | null
  default_breakeven_threshold?: number | null
  default_exit_execution?: string
  auto_squareoff_time?: string | null
  risk_monitoring?: string
  // Daily circuit breaker
  daily_stoploss_type?: string | null
  daily_stoploss_value?: number | null
  daily_target_type?: string | null
  daily_target_value?: number | null
  daily_trailstop_type?: string | null
  daily_trailstop_value?: number | null
}
