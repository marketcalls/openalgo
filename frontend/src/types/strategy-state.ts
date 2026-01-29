// Types for Strategy State / Positions viewer

export interface StrategyConfig {
  strategy_name: string
  lots: number
  lot_size: number
  sl_percent?: number
  reentry_limit?: number
  target_percent?: number
  reexecute_limit?: number
  underlying: string
  expiry_date: string
  /** Options exchange for the strategy (e.g., NFO, BFO). Persisted by python strategies as `exchange`. */
  exchange?: string
}

export type LegStatus =
  | 'IDLE'
  | 'PENDING_ENTRY'
  | 'IN_POSITION'
  | 'PENDING_EXIT'
  | 'EXITED_WAITING_REENTRY'
  | 'EXITED_WAITING_REEXECUTE'
  | 'DONE'

export interface LegState {
  leg_type: string // CE, PE
  status: LegStatus
  symbol: string
  entry_price: number | null
  entry_time: string | null
  sl_price: number | null
  target_price: number | null
  reentry_count: number
  reexecute_count: number
  quantity: number
  realized_pnl: number
  unrealized_pnl?: number
  total_pnl?: number
  leg_pair_name?: string
  side: 'SELL' | 'BUY'
  is_main_leg: boolean
  sl_percent?: number
  reentry_limit?: number
  target_percent?: number
  reexecute_limit?: number
  current_ltp?: number // TODO: Fetch via WebSocket/Quotes API
}

export type ExitType =
  | 'SL_HIT'
  | 'TARGET_HIT'
  | 'HEDGE_SL_EXIT'
  | 'HEDGE_TARGET_EXIT'
  | 'STRATEGY_DONE'

export interface TradeHistoryRecord {
  trade_id: number
  leg_key: string
  leg_pair_name?: string
  option_type: string // CE, PE
  side: 'SELL' | 'BUY'
  is_main_leg: boolean
  symbol: string
  quantity: number
  entry_time: string
  entry_price: number
  exit_time: string | null
  exit_price: number | null
  exit_type: ExitType | null
  sl_price: number | null
  target_price: number | null
  pnl: number
  reentry_count_at_exit?: number
  reexecute_count_at_exit?: number
}

export interface OrchestratorState {
  cycle_count: number
  start_time: string
  last_updated: string
}

export type StrategyStatus = 'RUNNING' | 'PAUSED' | 'COMPLETED' | 'ERROR'

export interface StrategySummary {
  total_realized_pnl: number
  total_unrealized_pnl: number
  total_pnl: number
  trade_history_pnl: number
  open_positions_count: number
  idle_positions_count: number
  total_trades: number
}

export interface StrategyState {
  id: number
  strategy_name: string
  instance_id: string
  user_id: string | null
  status: StrategyStatus
  last_heartbeat: string | null
  created_at: string | null
  last_updated: string | null
  completed_at: string | null
  version: number | null
  pid: number | null
  config: StrategyConfig | null
  legs: Record<string, LegState>
  trade_history: TradeHistoryRecord[]
  orchestrator: OrchestratorState | null
  summary: StrategySummary
}

export interface StrategyStateResponse {
  status: 'success' | 'error'
  message?: string
  data: StrategyState[]
}

// Override types for live SL/Target modifications
export type OverrideType = 'sl_price' | 'target_price'

export interface StrategyOverrideRequest {
  leg_key: string
  override_type: OverrideType
  new_value: number
}

export interface StrategyOverride {
  id: number
  instance_id: string
  leg_key: string
  override_type: OverrideType
  new_value: number
  applied: boolean
  created_at: string | null
}

export interface StrategyOverrideResponse {
  status: 'success' | 'error'
  message?: string
  data?: StrategyOverride
}
