// Strategy Dashboard Types — matches backend models from strategy_position_db.py

export interface DashboardStrategy {
  id: number
  name: string
  webhook_id: string
  platform: string
  is_active: boolean
  is_intraday: boolean
  trading_mode: 'LONG' | 'SHORT' | 'BOTH'
  start_time: string | null
  end_time: string | null
  squareoff_time: string | null
  risk_monitoring: 'active' | 'paused'
  auto_squareoff_time: string | null
  daily_cb_behavior: 'alert_only' | 'stop_entries' | 'close_all_positions'
  schedule_enabled: boolean
  schedule_start_time: string | null
  schedule_stop_time: string | null
  schedule_days: string | null
  schedule_auto_entry: boolean
  schedule_auto_exit: boolean
  created_at: string
  updated_at: string | null
  // Dashboard aggregates
  active_positions: number
  total_unrealized_pnl: number
}

export interface DashboardPosition {
  id: number
  strategy_id: number
  strategy_type: string
  symbol: string
  exchange: string
  product_type: string
  action: 'BUY' | 'SELL'
  quantity: number
  intended_quantity: number
  average_entry_price: number
  ltp: number | null
  unrealized_pnl: number | null
  unrealized_pnl_pct: number | null
  peak_price: number | null
  position_state: 'pending_entry' | 'active' | 'exiting' | 'closed'
  stoploss_type: string | null
  stoploss_value: number | null
  stoploss_price: number | null
  target_type: string | null
  target_value: number | null
  target_price: number | null
  trailstop_type: string | null
  trailstop_value: number | null
  trailstop_price: number | null
  breakeven_type: string | null
  breakeven_threshold: number | null
  breakeven_activated: boolean
  position_group_id: string | null
  risk_mode: string | null
  realized_pnl: number | null
  exit_reason: string | null
  exit_detail: string | null
  exit_price: number | null
  closed_at: string | null
  created_at: string | null
}

export interface DashboardOrder {
  id: number
  strategy_id: number
  strategy_type: string
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  product_type: string
  price_type: string
  price: number
  order_status: string
  average_price: number | null
  filled_quantity: number | null
  is_entry: boolean
  exit_reason: string | null
  created_at: string | null
}

export interface DashboardTrade {
  id: number
  strategy_id: number
  strategy_type: string
  orderid: string
  symbol: string
  exchange: string
  action: 'BUY' | 'SELL'
  quantity: number
  price: number
  trade_type: 'entry' | 'exit'
  exit_reason: string | null
  pnl: number | null
  created_at: string | null
}

export interface DashboardSummary {
  active_positions: number
  total_unrealized_pnl: number
  today_realized_pnl: number
  today_total_pnl: number
  today_trades: number
  cumulative_pnl: number
  max_drawdown: number
  max_drawdown_pct: number
  win_rate: number
  profit_factor: number
  risk_reward_ratio: number
  expectancy: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  avg_win: number
  avg_loss: number
  max_consecutive_wins: number
  max_consecutive_losses: number
  exit_breakdown: Record<string, number>
}

export interface DailyPnL {
  date: string
  realized_pnl: number
  unrealized_pnl: number
  total_pnl: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  gross_profit: number
  gross_loss: number
  cumulative_pnl: number
  max_drawdown: number
  max_drawdown_pct: number
}

export interface RiskConfig {
  default_stoploss_type: string | null
  default_stoploss_value: number | null
  default_target_type: string | null
  default_target_value: number | null
  default_trailstop_type: string | null
  default_trailstop_value: number | null
  default_breakeven_type: string | null
  default_breakeven_threshold: number | null
  risk_monitoring: 'active' | 'paused'
  auto_squareoff_time: string | null
}

export interface RiskEvent {
  id: number
  alert_id: string
  alert_type: string
  symbol: string | null
  exchange: string | null
  trigger_reason: string | null
  trigger_price: number | null
  ltp_at_trigger: number | null
  pnl: number | null
  message: string | null
  priority: string | null
  created_at: string | null
}

export interface PositionGroupData {
  id: string
  strategy_id: number
  strategy_type: string
  expected_legs: number
  filled_legs: number
  group_status: string
  combined_pnl: number | null
}

export type MarketPhase = 'market_open' | 'pre_market' | 'market_closed' | 'weekend' | 'holiday'

export interface MarketStatus {
  phase: MarketPhase
  current_time: string
  is_trading_day: boolean
  exchanges: Record<string, { is_open: boolean; start_time: string; end_time: string }>
}

export interface CircuitBreakerConfig {
  daily_cb_behavior: 'alert_only' | 'stop_entries' | 'close_all_positions'
}

export interface DistanceMetrics {
  sl: { points: number; pct: number } | null
  tgt: { points: number; pct: number } | null
  tsl: { points: number; pct: number } | null
}

export interface OverviewData {
  total_active_positions: number
  total_unrealized_pnl: number
  strategies: Array<{
    strategy_id: number
    strategy_type: string
    active_positions: number
    total_unrealized_pnl: number
  }>
}
