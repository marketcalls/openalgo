// Strategy Analysis Types — ported from VAYU with OpenAlgo integration

// ─── Fibonacci ───
export interface FibLevel {
  label: string
  ratio: number
  price: number
}

export interface FibonacciData {
  trend: 'uptrend' | 'downtrend'
  swing_high: { price: number; index: number } | null
  swing_low: { price: number; index: number } | null
  current_price: number
  retracements: FibLevel[]
  extensions: FibLevel[]
  nearest_retracement: FibLevel | null
  trade_levels: StrategyTradeLevels | null
}

// ─── Harmonic ───
export interface HarmonicPoint {
  price: number
  index: number
}

export interface HarmonicPattern {
  pattern: string
  bullish: boolean
  points: Record<string, HarmonicPoint>
  ratios: Record<string, number>
  description: string
  completion?: number
}

export interface HarmonicData {
  patterns: HarmonicPattern[]
  count: number
  trade_levels: StrategyTradeLevels | null
}

// ─── Elliott Wave ───
export interface WavePoint {
  wave: string
  price: number
  index: number
}

export interface ImpulseWave {
  bullish: boolean
  degree: string
  valid: boolean
  waves: WavePoint[]
  violations: string[]
}

export interface CorrectiveWave {
  bullish: boolean
  waves: WavePoint[]
  ratios: {
    B_retrace_A: number
    C_to_A: number
  }
}

export interface ElliottWaveData {
  current_phase: string
  impulse_waves: ImpulseWave[]
  corrective_waves: CorrectiveWave[]
  trade_levels: StrategyTradeLevels | null
}

// ─── Smart Money ───
export interface OrderBlock {
  bullish: boolean
  high: number
  low: number
  open: number
  close: number
  impulse_size: number
  mitigated: boolean
  source?: string
}

export interface FairValueGap {
  bullish: boolean
  top: number
  bottom: number
  gap_size: number
  filled: boolean
}

export interface StructureBreak {
  bullish: boolean
  signal: string
  description: string
}

export interface LiquiditySweep {
  bullish: boolean
  level_price: number
  description: string
}

export interface SmartMoneyData {
  bias: string
  from_scratch?: SmartMoneyEngine
  library?: SmartMoneyEngine
  summary: {
    active_obs: number
    unfilled_fvgs: number
    total_sweeps: number
    total_breaks: number
  }
  trade_levels: StrategyTradeLevels | null
}

export interface SmartMoneyEngine {
  bias: string
  active_order_blocks: OrderBlock[]
  unfilled_fvgs: FairValueGap[]
  structure_breaks: StructureBreak[]
  liquidity_sweeps: LiquiditySweep[]
  summary: {
    active_obs: number
    unfilled_fvgs: number
    total_sweeps: number
    total_breaks: number
  }
}

// ─── Hedge Fund ───
export interface MeanReversion {
  current_zscore: number | null
  current_mean: number | null
  half_life_bars: number | null
}

export interface MomentumFactor {
  scores: Record<string, number>
  composite: number | null
  signal: string | null
}

export interface VolatilityRegime {
  regime: string
  parkinson_vol: number
  vol_percentile: number
  position_sizing: string
}

export interface RiskMetrics {
  sharpe_ratio?: number
  sortino_ratio?: number
  calmar_ratio?: number
  max_drawdown_pct?: number
  annual_return_pct?: number
  var_95?: number
  omega_ratio?: number
  stability?: number
  win_rate_pct?: number
  profit_factor?: number
  cagr_pct?: number
  best_day_pct?: number
  worst_day_pct?: number
}

export interface HedgeStrategyData {
  from_scratch: {
    mean_reversion: MeanReversion
    momentum: MomentumFactor
    volatility_regime: VolatilityRegime
    risk_metrics: RiskMetrics
    suggestions: string[]
  }
  library?: {
    empyrical_metrics: RiskMetrics
    quantstats_metrics: RiskMetrics
  }
  trade_levels: StrategyTradeLevels | null
}

// ─── Strategy Trade Levels (shared) ───
export interface StrategyTarget {
  label: string
  price: number
  rr_ratio: number
  source: string
}

export interface StrategyTradeLevels {
  direction: 'bullish' | 'bearish' | 'neutral'
  entry: { low: number; high: number; mid: number; source: string }
  stop_loss: { price: number; source: string; distance_pct: number }
  targets: StrategyTarget[]
  confidence: number
  reasoning: string[]
}

// ─── Strategy Decision ───
export interface ConfluenceVote {
  module: string
  vote: number // -1, 0, +1
  detail: string
}

export interface ConfluenceData {
  score: number
  bullish_count: number
  bearish_count: number
  neutral_count: number
  votes: ConfluenceVote[]
}

export interface StrategyDecisionData {
  action: string
  strategy_label: string
  direction: string
  symbol: string
  current_price: number
  confluence: ConfluenceData
  entry: { low: number; high: number; mid: number; source: string }
  stop_loss: { price: number; source: string; distance_pct: number }
  targets: StrategyTarget[]
  position_sizing: {
    shares: number
    risk_amount: number
    stop_distance: number
    vol_modifier: number
  }
  signal_summary: {
    signal: string
    score: number
    confidence: number
    regime: string
  }
  smc_context: {
    bias: string
    active_obs: number
    unfilled_fvgs: number
    last_break: string | null
  }
  wave_context: {
    elliott_phase: string
    fib_trend: string
    nearest_retracement: { label: string; price: number } | null
    harmonic_patterns: string[]
  }
  risk_metrics: {
    vol_regime: string
    sharpe: number
    max_dd: number
    var_95: number
    hv: number
    vol_percentile: number
  }
  reasoning: string[]
}

// ─── Multi-Timeframe ───
export interface TimeframeSignal {
  signal: string
  score: number
  confidence: number
  regime: string
  error?: string
}

export interface MultiTimeframeConfluence {
  score: number
  signal: string
  confidence: number
  agreement_pct: number
  aligned_timeframes: string[]
  conflicting_timeframes: string[]
}

export interface MultiTimeframeData {
  symbol: string
  timeframes: Record<string, TimeframeSignal>
  confluence: MultiTimeframeConfluence
}

// ─── Candlestick Patterns ───
export interface CandlestickPattern {
  name: string
  bullish: boolean | null
  description?: string
  strength?: number
}

export interface PatternsData {
  from_scratch?: { patterns: CandlestickPattern[] }
  talib?: {
    patterns: CandlestickPattern[]
    full_scan: Array<{
      name: string
      bullish_signals: number
      bearish_signals: number
      bars_since_last: number | null
    }>
    total_scanned: number
  }
  patterns?: CandlestickPattern[] // fallback
}

// ─── Support & Resistance ───
export interface SupportResistanceData {
  support: number[]
  resistance: number[]
  pivots: Record<string, number>
}

// ─── News Sentiment (Stocksight-inspired) ───
export interface NewsArticle {
  title: string
  source: string
  url: string
  published: string
  sentiment: {
    compound: number
    pos: number
    neg: number
    neu: number
  }
  label: string
}

export interface SourceBreakdown {
  source: string
  count: number
  avg_sentiment: number
  label: string
}

export interface NewsSentimentData {
  symbol: string
  exchange: string
  total_articles: number
  overall_sentiment: {
    compound: number
    label: string
    bullish_count: number
    bearish_count: number
    neutral_count: number
  }
  source_breakdown: SourceBreakdown[]
  articles: NewsArticle[]
  timestamp: string
}

// ─── Daily Report ───
export interface DailyReportData {
  report_date: string
  report_time: string
  exchange: string
  symbols_analyzed: number
  market_summary: string
  market_overview: {
    status: string
    avg_score: number
    avg_confidence: number
    bullish_pct: number
    bearish_pct: number
    neutral_pct: number
    total_symbols: number
  }
  signal_distribution: Record<string, number>
  top_gainers: Array<{ symbol: string; price: number; change: number; change_pct: number; signal: string }>
  top_losers: Array<{ symbol: string; price: number; change: number; change_pct: number; signal: string }>
  sector_analysis: Array<{ group: string; count: number; symbols: string[] }>
  news_sentiment: { total_articles: number; avg_sentiment: number; label: string; top_sources: Record<string, number> }
  key_levels: Array<{ symbol: string; pivot: number | null; r1: number | null; s1: number | null; r2: number | null; s2: number | null }>
  scans: Array<{ symbol: string; price: number; change_pct: number; signal: string; confidence: number; score: number }>
}

// ─── Research Agent ───
export interface ResearchReportData {
  symbol: string
  exchange: string
  question: string
  timestamp: string
  steps_completed: number
  steps_failed: number
  steps: Array<{ step: number; task: string; status: string; error?: string | null }>
  report: {
    verdict: string
    verdict_detail: string
    confidence: number
    answer: string
    reasoning: string[]
    risks: string[]
    opportunities: string[]
    signals_summary: Array<{ module: string; signal: string; confidence: number }>
    trade_setup: { entry: Record<string, unknown>; stop_loss: Record<string, unknown>; targets: Array<Record<string, unknown>> } | null
  }
  findings: Record<string, unknown>
}

// ─── RL Agent ───
export interface RLSignalData {
  status: 'success' | 'no_model' | 'error'
  signal: 'BUY' | 'SELL' | 'HOLD'
  confidence: number
  algo: string
  symbol: string
  model_path?: string
  action_int?: number
  message?: string
}
