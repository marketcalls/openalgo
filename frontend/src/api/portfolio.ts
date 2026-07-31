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
  cost_model?: 'indian_equity' | 'flat_bps'
  brokerage_pct?: number
  cost_bps?: number
  cost_exchange?: string
  /** Per-charge overrides, keyed by charge id. Rates are fractions. */
  charges?: Record<string, { rate?: number; flat?: number; cap?: number }>
  /** Consumption tax on the taxable charges, as a fraction. */
  gst_rate?: number
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

/**
 * One scored dimension of portfolio health, with its working attached so the
 * grade can be argued with rather than merely believed.
 */
export interface HealthPillar {
  key: string
  label: string
  /** 0-100, or null when the pillar could not be measured. */
  score: number | null
  /** Its share of the total as designed. */
  weight: number
  /** Its share after renormalising around any unmeasured pillar. */
  effective_weight: number
  formula: string
  inputs: Record<string, unknown>
  comment: string
}

export interface PortfolioHealth {
  score: number | null
  grade: string | null
  pillars: HealthPillar[]
  /** Pillars dropped for want of data, rather than scored zero. */
  unmeasured: string[]
}

/** Series-level data: what a table of headline numbers cannot convey. */
export interface PortfolioSeries {
  drawdown: CurvePoint[]
  drawdown_episodes?: {
    start: string
    valley: string
    end: string
    days: number
    depth: number | null
  }[]
  rolling?: {
    window: number
    sharpe: CurvePoint[]
    volatility: CurvePoint[]
  }
  monthly_returns?: {
    years: string[]
    columns: string[]
    values: (number | null)[][]
  }
  /** Best/worst single month, typical up/down month, win rate by month and quarter. */
  seasonality?: {
    best_month: number | null
    worst_month: number | null
    avg_up_month: number | null
    avg_down_month: number | null
    win_months: number | null
    win_quarters: number | null
  }
  weekly_returns: CurvePoint[]
  /** Weekly returns as years x ISO weeks, for the heatmap. */
  weekly_grid?: {
    years: string[]
    weeks: number[]
    values: (number | null)[][]
  }
  /** Spread of returns at each holding period. */
  return_quantiles?: {
    period: string
    count: number
    min: number | null
    q1: number | null
    median: number | null
    q3: number | null
    max: number | null
    mean: number | null
    negative_share: number | null
  }[]
  /** Calendar-year returns, against the benchmark where there is one. */
  yearly_returns?: {
    year: string
    portfolio: number | null
    benchmark?: number | null
    difference?: number | null
    /** Straight from openstatz, so the verdict matches its tearsheet. */
    won?: boolean
    /** Omitted when the benchmark fell — a negative denominator is unreadable. */
    multiplier?: number | null
  }[]
}

/**
 * What the trading actually cost, itemised the way a contract note is.
 * STT dominates and brokerage is usually zero — which is why "zero brokerage"
 * does not make rebalancing free.
 */
export interface PortfolioCosts {
  model: string
  brokerage?: number
  stt?: number
  exchange_txn?: number
  sebi?: number
  gst?: number
  stamp_duty?: number
  slippage?: number
  total: number
  drag: number
  turnover: number
}

/** How the portfolio behaved across named historical stress windows. */
export interface PortfolioCrisis {
  periods: {
    key: string
    label: string
    note?: string
    start: string
    end: string
    scope?: 'india' | 'global'
    /** Calendar days and trading sessions the window actually covered. */
    days?: number
    sessions?: number
    portfolio: number | null
    benchmark: number | null
    excess: number | null
    coverage?: number
    partial?: boolean
  }[]
  summary: {
    count: number
    average_return: number
    hit_rate: number | null
    worst: number
    best: number
    by_scope?: Record<
      string,
      { count: number; average_return: number; hit_rate: number | null }
    >
  } | null
}

/** Weights over time, for the allocation chart. No cash band: long-only. */
export interface PortfolioAllocation {
  dates: string[]
  symbols: string[]
  series: Record<string, number[]>
  average: Record<string, number>
}

interface Band {
  p05: number
  p25: number
  median: number
  p75: number
  p95: number
}

/** The same allocation re-run over rolling sub-windows. */
export interface WalkForward {
  windows: {
    start: string
    end: string
    total_return: number
    cagr: number
    max_drawdown: number
    sessions: number
  }[]
  summary: {
    count: number
    window_years: number
    step_years: number
    best: number
    worst: number
    median: number
    positive_share: number
    spread: number
  } | null
  note: string | null
}

/** Block-bootstrap resampling: how much of the outcome was sequence luck. */
export interface MonteCarlo {
  paths: number
  block?: number
  seed?: number
  total_return?: Band
  cagr?: Band
  max_drawdown?: Band
  probability_of_loss?: number
  worst_drawdown_seen?: number
  note: string | null
}

/** What the portfolio is made of, from data that actually exists. */
export interface PortfolioStructure {
  instrument_classes: Record<string, number>
  instrument_class_basis: string
  clusters: { id: number; members: string[]; weight: number; independent: boolean }[]
  threshold: number
  effective_bets: number
  largest_cluster_weight: number
  sector_note: string
}

/** The same allocation under every rebalancing rule. */
export interface RebalancingSweep {
  variants: {
    label: string
    rule: string
    drift_band: number
    total_return: number
    cagr: number
    volatility: number
    sharpe: number
    sortino: number
    max_drawdown: number
    calmar: number
    cost_drag: number
    turnover: number
    rebalances: number
  }[]
  curves: Record<string, CurvePoint[]>
  best_by_sharpe: string | null
  best_by_return: string | null
  sessions: number
  start: string
  end: string
}

/** Where the out- or under-performance came from. */
export interface PortfolioAttribution {
  available: boolean
  reason?: string
  portfolio_return?: number
  equal_weight_return?: number
  benchmark_return?: number
  excess_return?: number
  selection_effect?: number
  allocation_effect?: number
  cost_effect?: number
  holdings?: {
    symbol: string
    weight: number
    return: number
    vs_benchmark: number
    contribution: number
  }[]
  holdings_reason?: string | null
  method?: string
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
  walk_forward: WalkForward
  monte_carlo: MonteCarlo
  rebalancing_sweep: RebalancingSweep
  attribution: PortfolioAttribution
  /** Trailing return per holding, close to close. */
  asset_returns: {
    symbol: string
    last: number
    '1W': number | null
    '1M': number | null
    '3M': number | null
    '1Y': number | null
    '3Y': number | null
    '5Y': number | null
  }[]
  structure: PortfolioStructure
  allocation: PortfolioAllocation
  crisis: PortfolioCrisis
  costs: PortfolioCosts
  series: PortfolioSeries
  health: PortfolioHealth
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

export interface Benchmark {
  symbol: string
  exchange: string
  name: string | null
}

/**
 * Index symbols usable as a benchmark, read from the instrument master.
 *
 * Not hardcoded: which indices exist depends on which broker's master
 * contract was downloaded, and brokers differ on this (GLOBAL_INDEX rows
 * only appear for a broker that supports them).
 */
export async function listBenchmarks(apiKey: string): Promise<Benchmark[]> {
  const { data } = await apiClient.get<{ data: Benchmark[] }>('/portfolio/benchmarks', {
    params: { apikey: apiKey },
  })
  return data.data
}

/**
 * Download the full openstatz tearsheet as a self-contained HTML file.
 *
 * Returned as a blob rather than rendered in-app: it is a report a user keeps
 * and shares, roughly a megabyte with every chart embedded.
 */
export async function downloadTearsheet(req: BacktestRequest): Promise<void> {
  const { data } = await apiClient.post('/portfolio/tearsheet', req, {
    responseType: 'blob',
  })
  const url = URL.createObjectURL(new Blob([data], { type: 'text/html' }))
  const link = document.createElement('a')
  link.href = url
  link.download = 'portfolio-tearsheet.html'
  document.body.appendChild(link)
  link.click()
  link.remove()
  // Revoking immediately can cancel the download in some browsers; a tick is
  // enough for it to have started.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export interface HoldingRow {
  symbol: string
  exchange: string
  quantity: number
  average_price: number
  last_price: number
  invested: number
  current: number
  pnl: number
  /** Null when the broker reports no average price for this holding. */
  pnl_pct: number | null
  weight: number
  product: string
}

export interface HoldingsAnalysis {
  status: 'success' | 'error'
  message?: string
  summary: {
    holdings: HoldingRow[]
    weights: Record<string, number>
    /** Null when the feed carries no average price at all. */
    invested: number | null
    current: number
    pnl: number
    pnl_pct: number | null
    has_cost_basis?: boolean
    count: number
  }
  /** The full backtest report over the current weights, or null if unavailable. */
  analysis: BacktestResponse | null
  analysis_error: string | null
  /** Held, but on an exchange the backtester cannot price. */
  skipped: string[]
  meta: {
    lookback_days: number
    start: string
    end: string
    /** Says plainly that this is today's holdings run over past prices. */
    basis: string
  }
}

/** Analyse the portfolio actually held at the broker. */
export async function analyseHoldings(req: {
  apikey: string
  lookback_days?: number
  benchmark?: string | null
  risk_free_rate?: number
  source?: PriceSource
}): Promise<HoldingsAnalysis> {
  const { data } = await apiClient.post<HoldingsAnalysis>('/portfolio/holdings', req)
  return data
}
