import { apiClient } from './client'

/** How often the SIP invests. */
export type SipFrequency = 'weekly' | 'fortnightly' | 'monthly' | 'quarterly'
/** 'db' reads the local Historify store; 'api' asks the broker. */
export type PriceSource = 'db' | 'api'

export interface SipBacktestRequest {
  apikey: string
  symbol: string
  exchange: string
  /** The date the SIP starts. The first installment lands on or after it. */
  start_date: string
  end_date: string
  /** Installment before any step-up. */
  amount: number
  frequency?: SipFrequency
  /** Target day for monthly and quarterly SIPs, 1–28. */
  day_of_month?: number
  /** Annual increase applied on each anniversary of the first installment. */
  step_up_percent?: number
  brokerage_percent?: number
  brokerage_flat?: number
  benchmark?: string | null
  benchmark_exchange?: string
  source?: PriceSource
  /**
   * Heatmaps and rolling windows re-run the simulation hundreds of times.
   * Turn off for a fast summary.
   */
  include_grids?: boolean
}

export interface CurvePoint {
  date: string
  value: number
}

/**
 * The numbers at the top of the page.
 *
 * `xirr` rather than CAGR: money paid in month 60 has not compounded for five
 * years, so a single annualised figure would overstate the return. `xirr` is
 * null when it is genuinely undefined — an all-loss series never crosses zero.
 */
export interface SipHeadline {
  invested: number | null
  final_value: number | null
  gain: number | null
  multiple: number | null
  xirr: number | null
  absolute_return: number | null
  installments: number
  units: number | null
  average_cost: number | null
  average_price: number | null
  /** Negative means each unit cost less than the average price over the same
   *  dates — the rupee-cost-averaging effect, quantified. */
  cost_advantage: number | null
  charges: number | null
  start: string
  end: string
  years: number | null
}

/** How long the holding was worth less than the money paid into it. */
export interface SipUnderwater {
  sessions_below: number
  sessions_total: number
  share_below: number | null
  longest_streak_sessions: number
  longest_streak_ended: string | null
  worst_shortfall: number | null
  ever_underwater: boolean
}

export interface SipDrawdown {
  max_drawdown: number | null
  trough_date: string | null
  recovery_sessions: number | null
  recovered: boolean
  curve: CurvePoint[]
}

export interface RollingWindow {
  years: number
  windows: number
  points: { start: string; end: string; xirr: number | null }[]
  best: number | null
  worst: number | null
  median: number | null
  positive_share: number | null
}

export interface SipHeatmap {
  rows: string[]
  columns: string[]
  values: (number | null)[][]
}

export interface MonthlyHeatmap {
  years: string[]
  columns: string[]
  values: (number | null)[][]
}

export interface SipDateHeatmap {
  days: number[]
  values: (number | null)[]
  best_day: number | null
  worst_day: number | null
  spread: number | null
}

export interface FrequencyRow {
  frequency: SipFrequency
  amount_per_installment: number | null
  installments: number
  invested: number | null
  final_value: number | null
  xirr: number | null
  average_cost: number | null
  charges: number | null
}

export interface YearlyRow {
  year: number
  invested_during_year: number | null
  invested_to_date: number | null
  value: number | null
  gain: number | null
  change: number | null
}

/** The same total money deployed on day one. */
export interface LumpsumComparison {
  invested: number | null
  final_value: number | null
  xirr: number | null
  entry_price: number | null
  entry_date: string
  sip_final_value: number | null
  difference: number | null
  sip_won: boolean
}

export interface BenchmarkComparison {
  symbol: string
  exchange: string
  headline?: SipHeadline
  xirr?: number | null
  excess_xirr?: number | null
  beat_benchmark?: boolean
  curve?: CurvePoint[]
  error?: string
}

export interface Installment {
  /** What the user asked for. */
  requested: string
  /** The trading session it actually landed on — they differ across holidays. */
  executed: string
  amount: number
}

export interface ChargeSummary {
  total: number
  per_installment: number
  /** Share of everything paid in that went to charges rather than units. */
  drag: number | null
  /** Itemised across all installments: stt, exchange_txn, sebi, stamp_duty, tax. */
  breakdown: Record<string, number>
  model: string
  exchange: string
}

export interface SipBacktestResponse {
  status: string
  request: {
    symbol: string
    exchange: string
    start_date: string
    end_date: string
    amount: number
    frequency: SipFrequency
    day_of_month: number
    step_up_percent: number
    source: string
  }
  headline: SipHeadline
  underwater: SipUnderwater
  drawdown: SipDrawdown
  yearly: YearlyRow[]
  monthly_heatmap: MonthlyHeatmap
  lumpsum: LumpsumComparison | null
  frequency_comparison: FrequencyRow[]
  curves: { value: CurvePoint[]; invested: CurvePoint[] }
  installments: Installment[]
  warnings: string[]
  charges?: ChargeSummary
  rolling_xirr?: RollingWindow[]
  start_date_heatmap?: SipHeatmap
  sip_date_heatmap?: SipDateHeatmap | null
  benchmark?: BenchmarkComparison
}

export async function runSipBacktest(request: SipBacktestRequest): Promise<SipBacktestResponse> {
  const { data } = await apiClient.post<SipBacktestResponse>('/sip/backtest', request)
  return data
}

export async function listSipFrequencies(): Promise<{ value: SipFrequency; label: string }[]> {
  const { data } = await apiClient.get<{
    data: { value: SipFrequency; label: string }[]
  }>('/sip/frequencies')
  return data.data
}
