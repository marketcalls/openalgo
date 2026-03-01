// Backtest Types

export interface BacktestConfig {
  symbols: string[]
  exchange: string
  start_date: string
  end_date: string
  interval: string
  initial_capital: number
  slippage_pct: number
  commission_per_order: number
  commission_pct: number
}

export interface BacktestMetrics {
  final_capital: number
  total_return_pct: number
  cagr: number
  sharpe_ratio: number
  sortino_ratio: number
  max_drawdown_pct: number
  calmar_ratio: number
  win_rate: number
  profit_factor: number
  total_trades: number
  winning_trades: number
  losing_trades: number
  avg_win: number
  avg_loss: number
  max_win: number
  max_loss: number
  expectancy: number
  avg_holding_bars: number
  total_commission: number
  total_slippage: number
}

export interface BacktestTrade {
  trade_num: number
  symbol: string
  exchange: string
  action: 'LONG' | 'SHORT'
  quantity: number
  entry_price: number
  exit_price: number
  entry_time: string
  exit_time: string
  pnl: number
  pnl_pct: number
  commission: number
  slippage_cost: number
  net_pnl: number
  bars_held: number
  product: string
  strategy_tag: string
}

export interface EquityPoint {
  timestamp: number
  equity: number
  drawdown: number
}

export interface BacktestListItem {
  backtest_id: string
  name: string
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'
  symbols: string[]
  interval: string
  start_date: string
  end_date: string
  initial_capital: number
  total_return_pct: number | null
  sharpe_ratio: number | null
  max_drawdown_pct: number | null
  total_trades: number
  win_rate: number | null
  duration_ms: number | null
  created_at: string | null
  error_message: string | null
}

export interface BacktestResult {
  backtest_id: string
  name: string
  config: BacktestConfig
  metrics: BacktestMetrics
  equity_curve: EquityPoint[]
  monthly_returns: Record<string, number>
  trades: BacktestTrade[]
  duration_ms: number | null
  created_at: string | null
  completed_at: string | null
}

export interface BacktestRunRequest {
  name?: string
  strategy_id?: string
  strategy_code: string
  symbols: string[] | string
  exchange?: string
  start_date: string
  end_date: string
  interval: string
  initial_capital?: number
  slippage_pct?: number
  commission_per_order?: number
  commission_pct?: number
  data_source?: string
}

export interface BacktestProgress {
  backtest_id: string
  progress: number
  message: string
  status?: string
  heartbeat?: boolean
}

export interface DataAvailability {
  available: boolean
  details: Record<string, {
    has_data: boolean
    record_count: number
    first_timestamp?: number
    last_timestamp?: number
  }>
}

export const INTERVAL_OPTIONS = [
  { value: '1m', label: '1 Minute' },
  { value: '5m', label: '5 Minutes' },
  { value: '15m', label: '15 Minutes' },
  { value: '30m', label: '30 Minutes' },
  { value: '1h', label: '1 Hour' },
  { value: 'D', label: 'Daily' },
] as const

export const EXCHANGE_OPTIONS = [
  { value: 'NSE', label: 'NSE' },
  { value: 'BSE', label: 'BSE' },
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
  { value: 'MCX', label: 'MCX' },
  { value: 'CDS', label: 'CDS' },
] as const

export const STATUS_COLORS: Record<string, string> = {
  completed: 'bg-green-500',
  running: 'bg-blue-500',
  pending: 'bg-yellow-500',
  failed: 'bg-red-500',
  cancelled: 'bg-gray-500',
}

export const STATUS_LABELS: Record<string, string> = {
  completed: 'Completed',
  running: 'Running',
  pending: 'Pending',
  failed: 'Failed',
  cancelled: 'Cancelled',
}
