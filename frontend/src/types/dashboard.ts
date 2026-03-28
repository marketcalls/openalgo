// ─────────────────────────────────────────────────────────────────────────────
// AAUM Institutional Trading Dashboard — Type Definitions
// ─────────────────────────────────────────────────────────────────────────────

// ── Primitive Enums / Unions ─────────────────────────────────────────────────

export type Signal = 'BUY' | 'SELL' | 'HOLD'
export type Bias = 'bullish' | 'bearish' | 'neutral'
export type Priority = 'critical' | 'high' | 'medium' | 'low'
export type Timeframe = '1m' | '3m' | '5m' | '15m' | '30m' | '1h' | '4h' | '1D'

// ── Market Data ──────────────────────────────────────────────────────────────

export interface TickData {
  symbol: string
  ltp: number
  open: number
  high: number
  low: number
  close: number
  volume: number
  change: number
  changePct: number
  timestamp: number
}

export interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
  volume: number
}

export interface DepthLevel {
  price: number
  qty: number
  orders: number
}

export interface VolumeNode {
  price: number
  volume: number
  buyVolume: number
  sellVolume: number
  delta: number
}

// ── GEX / Options Greeks ─────────────────────────────────────────────────────

export interface GexLevel {
  strike: number
  callGex: number
  putGex: number
  netGex: number
  flipZone: boolean
}

export interface OILevel {
  strike: number
  callOI: number
  putOI: number
  callOIChange: number
  putOIChange: number
  pcr: number
}

// ── Agent / Model Types ──────────────────────────────────────────────────────

export interface AgentVote {
  agentId: string
  agentName: string
  signal: Signal
  confidence: number
  reasoning: string
  timestamp: number
}

export interface ModelPrediction {
  modelId: string
  modelName: string
  signal: Signal
  probability: number
  horizonMinutes: number
  features: string[]
  lastTrained: number
}

// ── Alert Types ──────────────────────────────────────────────────────────────

export interface AlertItem {
  id: string
  type: 'danger' | 'warning' | 'info' | 'success'
  priority: Priority
  title: string
  message: string
  symbol?: string
  timestamp: number
  dismissed: boolean
}

// ── Scanner Types ────────────────────────────────────────────────────────────

export interface ScannerRow {
  symbol: string
  ltp: number
  changePct: number
  volume: number
  relativeVolume: number
  institutionalScore: number
  signal: Signal
  agentConsensus: Signal
  modelPrediction: Signal
  riskScore: number
  sector: string
  updatedAt: number
}

// ── Timeframe Matrix ─────────────────────────────────────────────────────────

export interface TimeframeCell {
  timeframe: Timeframe
  signal: Signal
  strength: number
  bias: Bias
  trendAngle: number
  keyLevel: number
  volumeProfile: 'high' | 'medium' | 'low'
}

// ── Self-Learning Types ──────────────────────────────────────────────────────

export interface LearningMetric {
  metricId: string
  label: string
  value: number
  previousValue: number
  unit: string
  trend: 'improving' | 'declining' | 'stable'
}

export interface BacktestResult {
  strategyId: string
  strategyName: string
  winRate: number
  profitFactor: number
  sharpeRatio: number
  maxDrawdown: number
  totalTrades: number
  period: string
}

// ── Risk Types ───────────────────────────────────────────────────────────────

export interface RiskMetric {
  label: string
  value: number
  max: number
  unit: string
  status: 'safe' | 'warning' | 'danger'
}

export interface PortfolioRisk {
  totalExposure: number
  maxLoss: number
  var95: number
  currentDrawdown: number
  leverage: number
  marginUsed: number
  marginAvailable: number
}

// ── Panel Props ──────────────────────────────────────────────────────────────

export interface CommandCenterProps {
  symbol: string
  signal: Signal
  confidence: number
  bias: Bias
  entry: number
  target: number
  stopLoss: number
  riskReward: number
  reasoning: string
  agentAgreement: number
  modelAgreement: number
  timestamp: number
}

export interface SmartChartProps {
  symbol: string
  timeframe: Timeframe
  candles: Candle[]
  volumeProfile: VolumeNode[]
  gexLevels: GexLevel[]
  supportLevels: number[]
  resistanceLevels: number[]
  annotations: ChartAnnotation[]
}

export interface ChartAnnotation {
  id: string
  type: 'signal' | 'level' | 'zone' | 'text'
  price: number
  time: number
  label: string
  color: string
}

export interface TimeframeMatrixProps {
  symbol: string
  cells: TimeframeCell[]
  overallBias: Bias
  confluenceScore: number
}

export interface InstitutionalScoreProps {
  symbol: string
  overallScore: number
  components: InstitutionalComponent[]
  trend: 'accumulating' | 'distributing' | 'neutral'
  darkPoolActivity: number
  blockTradeCount: number
  lastUpdated: number
}

export interface InstitutionalComponent {
  name: string
  score: number
  weight: number
  signal: Signal
  description: string
}

export interface AgentConsensusProps {
  symbol: string
  votes: AgentVote[]
  consensusSignal: Signal
  consensusConfidence: number
  agreementPct: number
  debateHighlights: string[]
}

export interface ModelPredictionsProps {
  symbol: string
  predictions: ModelPrediction[]
  ensembleSignal: Signal
  ensembleProbability: number
  modelAgreement: number
}

export interface DangerAlertsProps {
  alerts: AlertItem[]
  onDismiss: (id: string) => void
  onDismissAll: () => void
}

export interface StockScannerProps {
  rows: ScannerRow[]
  sortKey: string
  sortDir: 'asc' | 'desc'
  onSort: (key: string) => void
  onSelectSymbol: (symbol: string) => void
}

export interface DepthHeatmapProps {
  symbol: string
  bids: DepthLevel[]
  asks: DepthLevel[]
  ltp: number
  maxQty: number
}

export interface OIIntelligenceProps {
  symbol: string
  levels: OILevel[]
  maxPain: number
  pcr: number
  pcrTrend: Bias
  gexFlip: number
  netGex: number
  putWall: number
  callWall: number
}

export interface SelfLearningPanelProps {
  metrics: LearningMetric[]
  backtests: BacktestResult[]
  lastRetrainedAt: number
  nextRetrainAt: number
  isTraining: boolean
}

export interface RiskMeterProps {
  portfolio: PortfolioRisk
  metrics: RiskMetric[]
  overallStatus: 'safe' | 'warning' | 'danger'
  positionCount: number
}

// ── API Response Types ───────────────────────────────────────────────────────

export interface DashboardApiResponse<T> {
  status: 'success' | 'error'
  data: T
  timestamp: number
  error?: string
}

export interface CommandCenterResponse {
  symbol: string
  signal: Signal
  confidence: number
  bias: Bias
  entry: number
  target: number
  stopLoss: number
  riskReward: number
  reasoning: string
  agentAgreement: number
  modelAgreement: number
  timestamp: number
}

export interface InstitutionalScoreResponse {
  symbol: string
  overallScore: number
  components: InstitutionalComponent[]
  trend: 'accumulating' | 'distributing' | 'neutral'
  darkPoolActivity: number
  blockTradeCount: number
  lastUpdated: number
}

export interface AgentConsensusResponse {
  symbol: string
  votes: AgentVote[]
  consensusSignal: Signal
  consensusConfidence: number
  agreementPct: number
  debateHighlights: string[]
}

export interface ModelPredictionsResponse {
  symbol: string
  predictions: ModelPrediction[]
  ensembleSignal: Signal
  ensembleProbability: number
  modelAgreement: number
}

export interface OIIntelligenceResponse {
  symbol: string
  levels: OILevel[]
  maxPain: number
  pcr: number
  pcrTrend: Bias
  gexFlip: number
  netGex: number
  putWall: number
  callWall: number
}

export interface SelfLearningResponse {
  metrics: LearningMetric[]
  backtests: BacktestResult[]
  lastRetrainedAt: number
  nextRetrainAt: number
  isTraining: boolean
}

export interface RiskSnapshotResponse {
  portfolio: PortfolioRisk
  metrics: RiskMetric[]
  overallStatus: 'safe' | 'warning' | 'danger'
  positionCount: number
}

export interface StockScannerResponse {
  rows: ScannerRow[]
  total: number
  updatedAt: number
}

export interface TimeframeMatrixResponse {
  symbol: string
  cells: TimeframeCell[]
  overallBias: Bias
  confluenceScore: number
}
