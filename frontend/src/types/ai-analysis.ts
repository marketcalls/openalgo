// frontend/src/types/ai-analysis.ts

/** Signal types from VAYU engine */
export type SignalType = 'STRONG_BUY' | 'BUY' | 'HOLD' | 'SELL' | 'STRONG_SELL'

/** Market regime classification */
export type MarketRegime = 'TRENDING_UP' | 'TRENDING_DOWN' | 'RANGING' | 'VOLATILE'

/** Sub-signal scores from the weighted engine */
export interface SubScores {
  supertrend?: number
  rsi?: number
  macd?: number
  ema_cross?: number
  bollinger?: number
  adx_strength?: number
}

/** Latest indicator values */
export interface IndicatorValues {
  rsi_14?: number
  rsi_7?: number
  macd?: number
  macd_signal?: number
  macd_hist?: number
  ema_9?: number
  ema_21?: number
  sma_50?: number
  sma_200?: number
  adx_14?: number
  bb_high?: number
  bb_low?: number
  bb_pband?: number
  supertrend?: number
  supertrend_dir?: number
  atr_14?: number
  stoch_k?: number
  stoch_d?: number
  obv?: number
  vwap?: number
}

/** Advanced signals from SMC, candlestick, harmonic, etc. */
export interface AdvancedSignals {
  smc: Record<string, boolean>
  candlestick: string[]
  cpr: Record<string, number>
  fibonacci: { long: number; short: number }
  harmonic: { bullish: number; bearish: number }
  divergence: { rsi_bullish: number; rsi_bearish: number }
  volume: { exhaustion: number; vwap_bb_confluence: number }
  ml_confidence: { buy: number; sell: number }
}

/** Full analysis result from /api/v1/agent/analyze */
export interface AIAnalysisResult {
  symbol: string
  exchange: string
  interval: string
  signal: SignalType
  confidence: number
  score: number
  regime: MarketRegime
  sub_scores: SubScores
  indicators: IndicatorValues
  data_points: number
  advanced?: AdvancedSignals
  trade_setup?: TradeSetupData
  candles?: CandleData[]
  chart_overlays?: ChartOverlays
  decision?: TradingDecision
}

/** Trade setup with entry, SL, targets */
export interface TradeSetupData {
  action: string
  entry: number
  stop_loss: number
  target_1: number
  target_2: number
  target_3: number
  sl_distance: number
  sl_percent: number
  risk_reward_1: number
  risk_reward_2: number
  risk_reward_3: number
  suggested_qty: number
  risk_amount: number
  reason: string
}

/** OHLCV candle for chart */
export interface CandleData {
  time: number
  open: number
  high: number
  low: number
  close: number
}

/** Chart overlay line (EMA, SMA, Supertrend) */
export interface ChartOverlayLine {
  id: string
  label: string
  color: string
  data: { time: number; value: number }[]
}

/** Chart overlay band (Bollinger) */
export interface ChartOverlayBand {
  id: string
  label: string
  color: string
  data: { time: number; upper: number; lower: number }[]
}

/** Chart overlay level (CPR, Entry/SL/Target) */
export interface ChartOverlayLevel {
  price: number
  color: string
  label: string
}

/** All chart overlays from backend */
export interface ChartOverlays {
  lines: ChartOverlayLine[]
  bands: ChartOverlayBand[]
  markers: unknown[]
  levels: ChartOverlayLevel[]
}

/** Trading decision from decision engine */
export interface TradingDecision {
  action: string
  confidence_label: string
  entry: number
  stop_loss: number
  target: number
  quantity: number
  risk_amount: number
  risk_reward: number
  reason: string
  risk_warning: string
  supporting_signals: string[]
  opposing_signals: string[]
  score: number
}

export interface AIDecisionRecord {
  id: number
  timestamp: string
  symbol: string
  exchange: string
  interval: string
  signal: SignalType
  confidence: number
  score: number
  regime: string
  sub_scores: SubScores
  action_taken: string | null
  order_id: string | null
  reason: string | null
}

/** Scan result for one symbol from /api/v1/agent/scan */
export interface ScanResult {
  symbol: string
  signal: SignalType | null
  confidence: number
  score: number
  regime: MarketRegime | null
  error: string | null
  trade_setup?: {
    entry: number
    stop_loss: number
    target_1: number
    risk_reward_1: number
  }
}

/** AI agent status from /api/v1/agent/status */
export interface AIAgentStatus {
  agent: string
  version: string
  engine: string
  indicators: number
  signals: number
}

/** API response wrapper (matches OpenAlgo pattern) */
export interface AIAnalysisResponse {
  status: 'success' | 'error'
  message?: string
  data?: AIAnalysisResult
}

export interface AIScanResponse {
  status: 'success' | 'error'
  message?: string
  data?: ScanResult[]
}

export interface AIStatusResponse {
  status: 'success' | 'error'
  data?: AIAgentStatus
}

export interface AIDecisionHistoryResponse {
  status: 'success' | 'error'
  message?: string
  data?: AIDecisionRecord[]
}

/** Signal display config */
export const SIGNAL_CONFIG: Record<SignalType, { label: string; color: string; bgColor: string }> = {
  STRONG_BUY: { label: 'Strong Buy', color: 'text-green-700', bgColor: 'bg-green-100' },
  BUY: { label: 'Buy', color: 'text-green-600', bgColor: 'bg-green-50' },
  HOLD: { label: 'Hold', color: 'text-yellow-600', bgColor: 'bg-yellow-50' },
  SELL: { label: 'Sell', color: 'text-red-600', bgColor: 'bg-red-50' },
  STRONG_SELL: { label: 'Strong Sell', color: 'text-red-700', bgColor: 'bg-red-100' },
}

export const REGIME_CONFIG: Record<MarketRegime, { label: string; icon: string }> = {
  TRENDING_UP: { label: 'Trending Up', icon: 'TrendingUp' },
  TRENDING_DOWN: { label: 'Trending Down', icon: 'TrendingDown' },
  RANGING: { label: 'Ranging', icon: 'Minus' },
  VOLATILE: { label: 'Volatile', icon: 'Zap' },
}
