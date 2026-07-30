import { apiClient } from './client'

/** One holding in the portfolio being tested. */
export interface PortfolioHolding {
  symbol: string
  exchange: string
  /** Percentage or fraction — only the ratio between holdings matters. */
  weight: number
}

export type RebalanceRule = 'never' | 'monthly' | 'quarterly' | 'yearly'
/** 'db' reads the local Historify store; 'api' asks the broker. */
export type PriceSource = 'db' | 'api'

export interface BacktestRequest {
  apikey: string
  holdings: PortfolioHolding[]
  start_date: string
  end_date: string
  benchmark?: string | null
  benchmark_exchange?: string
  rebalance?: RebalanceRule
  drift_band?: number
  cost_bps?: number
  slippage?: number
  initial_capital?: number
  risk_free_rate?: number
  source?: PriceSource
}

export interface CurvePoint {
  date: string
  value: number
}

/**
 * Per-holding P&L. `contribution_pct` is this holding's share of the portfolio
 * return, so the column sums to the total — which is what makes it an
 * attribution rather than a list of individual performances. It differs from
 * `symbol_return` whenever the weight is not 100%.
 */
export interface PortfolioItem {
  symbol: string
  weight_target: number
  weight_final: number
  invested: number
  price_pnl: number
  costs: number
  net_pnl: number
  contribution_pct: number
  symbol_return: number
}

/** Anything the engine could not compute honestly comes back null, not 0. */
export interface PortfolioMetrics {
  cagr: number | null
  volatility: number | null
  sharpe: number | null
  sortino: number | null
  calmar: number | null
  max_drawdown: number | null
  win_rate: number | null
  best_day: number | null
  worst_day: number | null
  value_at_risk: number | null
  cvar: number | null
  ulcer_index: number | null
  recovery_factor: number | null
  tail_ratio: number | null
  skew: number | null
  kurtosis: number | null
  alpha?: number | null
  beta?: number | null
  information_ratio?: number | null
  benchmark_cagr?: number | null
  excess_cagr?: number | null
  up_capture?: number | null
  down_capture?: number | null
}

export interface BacktestResponse {
  status: 'success' | 'error'
  message?: string
  meta: {
    symbols: string[]
    target_weights: Record<string, number>
    rule: RebalanceRule
    drift_band: number
    cost_bps: number
    slippage: number
    initial_capital: number
    sessions: number
    source: PriceSource
    start: string
    end: string
    benchmark: string | null
    risk_free_rate: number
    /** 'price' — broker history excludes dividends, so returns understate. */
    total_return_basis: string
    /** symbol -> [[date, return]] where a move looked like an unadjusted split. */
    data_warnings: Record<string, [string, number][]>
  }
  equity: CurvePoint[]
  benchmark_equity: CurvePoint[]
  metrics: PortfolioMetrics
  items: PortfolioItem[]
  correlation: {
    symbols: string[]
    /** Square matrix; null where two holdings barely overlap. */
    matrix: (number | null)[][]
    average_pairwise: number | null
  }
  diversification: {
    hhi: number
    effective_holdings: number
    largest_weight: number
    holdings: number
    diversification_ratio: number | null
  }
  rebalancing: {
    rule: RebalanceRule
    drift_band: number
    count: number
    cost_drag: number
    turnover_total: number
    dates: string[]
  }
}

/**
 * Run one backtest. A single call returns every tab's data because they are
 * all views of one simulation — fetching per tab would re-run it and risk two
 * tabs disagreeing about the same portfolio.
 */
export async function runPortfolioBacktest(
  req: BacktestRequest
): Promise<BacktestResponse> {
  const { data } = await apiClient.post<BacktestResponse>('/portfolio/backtest', req)
  return data
}
