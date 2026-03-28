import type {
  AgentVote,
  AlertItem,
  Bias,
  Candle,
  CommandCenterResponse,
  DepthLevel,
  InstitutionalComponent,
  InstitutionalScoreResponse,
  LearningMetric,
  ModelPrediction,
  OILevel,
  PortfolioRisk,
  RiskMetric,
  ScannerRow,
  Signal,
  TimeframeCell,
  Timeframe,
} from '@/types/dashboard'

// Mock Data for all 12 dashboard panels

const now = Date.now()
const minuteMs = 60_000

function makeCandles(count: number, basePrice: number): Candle[] {
  const candles: Candle[] = []
  let price = basePrice
  for (let i = 0; i < count; i++) {
    const open = price
    const change = (Math.random() - 0.48) * basePrice * 0.008
    const close = open + change
    const high = Math.max(open, close) + Math.random() * basePrice * 0.003
    const low = Math.min(open, close) - Math.random() * basePrice * 0.003
    candles.push({
      time: now - (count - i) * minuteMs * 5,
      open: +open.toFixed(2),
      high: +high.toFixed(2),
      low: +low.toFixed(2),
      close: +close.toFixed(2),
      volume: Math.floor(50000 + Math.random() * 200000),
    })
    price = close
  }
  return candles
}

// Panel 1: Command Center
export const mockCommandCenter: CommandCenterResponse = {
  symbol: 'NIFTY',
  signal: 'BUY' as Signal,
  confidence: 82,
  bias: 'bullish' as Bias,
  entry: 24350.5,
  target: 24520.0,
  stopLoss: 24280.0,
  riskReward: 2.4,
  reasoning: 'Strong institutional accumulation detected across multiple timeframes.',
  agentAgreement: 89,
  modelAgreement: 86,
  timestamp: now,
}

export const mockCommandCenterReasons: Array<{ text: string; strength: number }> = [
  { text: 'Institutional accumulation on 5m + 15m timeframes', strength: 92 },
  { text: 'All 9 agents aligned bullish (89% consensus)', strength: 89 },
  { text: 'Volume profile POC at 24340, price above', strength: 85 },
  { text: 'GEX positive: gamma squeeze potential above 24400', strength: 80 },
  { text: 'OI build-up: long build-up with rising OI', strength: 78 },
  { text: 'Wyckoff: Markup phase confirmed on 15m', strength: 75 },
  { text: 'FVG at 24310-24330 acting as support', strength: 70 },
]

export const mockHistoricalTrades = [
  { symbol: 'NIFTY', date: '2026-03-25', signal: 'BUY' as Signal, outcome: 'WIN' as const, returnPct: 1.2 },
  { symbol: 'RELIANCE', date: '2026-03-24', signal: 'BUY' as Signal, outcome: 'WIN' as const, returnPct: 0.8 },
  { symbol: 'BANKNIFTY', date: '2026-03-24', signal: 'SELL' as Signal, outcome: 'LOSS' as const, returnPct: -0.3 },
]

// Panel 2: Smart Chart
export const mockCandles: Candle[] = makeCandles(100, 24300)

// Panel 3: Timeframe Matrix
export const mockTimeframeCells: TimeframeCell[] = [
  { timeframe: '1m' as Timeframe, signal: 'BUY', strength: 72, bias: 'bullish', trendAngle: 35, keyLevel: 24350, volumeProfile: 'high' },
  { timeframe: '5m' as Timeframe, signal: 'BUY', strength: 85, bias: 'bullish', trendAngle: 42, keyLevel: 24340, volumeProfile: 'high' },
  { timeframe: '15m' as Timeframe, signal: 'BUY', strength: 78, bias: 'bullish', trendAngle: 28, keyLevel: 24320, volumeProfile: 'medium' },
  { timeframe: '1h' as Timeframe, signal: 'BUY', strength: 65, bias: 'bullish', trendAngle: 15, keyLevel: 24280, volumeProfile: 'medium' },
  { timeframe: '4h' as Timeframe, signal: 'HOLD', strength: 55, bias: 'neutral', trendAngle: 5, keyLevel: 24200, volumeProfile: 'low' },
]

// Panel 4: Institutional Score
export const mockInstitutionalScore: InstitutionalScoreResponse = {
  symbol: 'NIFTY',
  overallScore: 76,
  components: [
    { name: 'Depth Pressure', score: 82, weight: 0.2, signal: 'BUY', description: 'Bid-heavy depth' },
    { name: 'Volume Profile', score: 78, weight: 0.2, signal: 'BUY', description: 'POC at support' },
    { name: 'OI Intelligence', score: 71, weight: 0.15, signal: 'BUY', description: 'Long build-up' },
    { name: 'Liquidity Map', score: 68, weight: 0.15, signal: 'HOLD', description: 'Pools above' },
    { name: 'Wyckoff Phase', score: 80, weight: 0.15, signal: 'BUY', description: 'Markup' },
    { name: 'AMD Phase', score: 74, weight: 0.15, signal: 'BUY', description: 'Accumulation' },
  ] as InstitutionalComponent[],
  trend: 'accumulating',
  darkPoolActivity: 72,
  blockTradeCount: 14,
  lastUpdated: now,
}

// Panel 5: Agent Consensus
export const mockAgentVotes: AgentVote[] = [
  { agentId: 'rakesh', agentName: 'Rakesh', signal: 'BUY', confidence: 88, reasoning: 'Bullish trend + momentum', timestamp: now },
  { agentId: 'graham', agentName: 'Graham', signal: 'BUY', confidence: 72, reasoning: 'Value zone identified', timestamp: now },
  { agentId: 'momentum', agentName: 'Momentum', signal: 'BUY', confidence: 91, reasoning: 'Strong momentum across TFs', timestamp: now },
  { agentId: 'quant', agentName: 'Quant', signal: 'BUY', confidence: 84, reasoning: 'Statistical edge detected', timestamp: now },
  { agentId: 'rajan', agentName: 'Rajan', signal: 'HOLD', confidence: 62, reasoning: 'Macro uncertainty', timestamp: now },
  { agentId: 'pulse', agentName: 'Pulse', signal: 'BUY', confidence: 79, reasoning: 'Sentiment positive', timestamp: now },
  { agentId: 'rotation', agentName: 'Rotation', signal: 'BUY', confidence: 76, reasoning: 'Sector rotation in', timestamp: now },
  { agentId: 'deriv', agentName: 'Deriv', signal: 'BUY', confidence: 85, reasoning: 'Bullish OI structure', timestamp: now },
  { agentId: 'risk', agentName: 'Risk', signal: 'BUY', confidence: 68, reasoning: 'Risk within limits', timestamp: now },
]

// Panel 6: Model Predictions
export const mockModelPredictions: ModelPrediction[] = [
  { modelId: 'xgb', modelName: 'XGBoost', signal: 'BUY', probability: 0.78, horizonMinutes: 30, features: ['momentum', 'volume'], lastTrained: now - 86400000 },
  { modelId: 'lgbm', modelName: 'LightGBM', signal: 'BUY', probability: 0.82, horizonMinutes: 30, features: ['orderflow', 'OI'], lastTrained: now - 86400000 },
  { modelId: 'rf', modelName: 'RandomForest', signal: 'BUY', probability: 0.71, horizonMinutes: 60, features: ['price_action'], lastTrained: now - 86400000 },
  { modelId: 'catboost', modelName: 'CatBoost', signal: 'BUY', probability: 0.84, horizonMinutes: 30, features: ['microstructure'], lastTrained: now - 86400000 },
  { modelId: 'lstm', modelName: 'LSTM', signal: 'SELL', probability: 0.56, horizonMinutes: 120, features: ['sequence'], lastTrained: now - 172800000 },
  { modelId: 'cnn', modelName: 'CNN', signal: 'BUY', probability: 0.68, horizonMinutes: 60, features: ['chart_pattern'], lastTrained: now - 172800000 },
  { modelId: 'transformer', modelName: 'Transformer', signal: 'BUY', probability: 0.76, horizonMinutes: 30, features: ['attention'], lastTrained: now - 86400000 },
]

// Panel 7: Danger Alerts
export const mockAlerts: AlertItem[] = [
  { id: 'a1', type: 'danger', priority: 'critical', title: 'Circuit Breaker Warning', message: 'Max drawdown approaching 2% limit.', symbol: 'NIFTY', timestamp: now - 120000, dismissed: false },
  { id: 'a2', type: 'warning', priority: 'high', title: 'GEX Flip Approaching', message: 'Price nearing GEX flip at 24400.', symbol: 'NIFTY', timestamp: now - 300000, dismissed: false },
  { id: 'a3', type: 'warning', priority: 'medium', title: 'Volume Divergence', message: 'Rising price with declining volume on 15m.', symbol: 'NIFTY', timestamp: now - 600000, dismissed: false },
  { id: 'a4', type: 'info', priority: 'low', title: 'Model Retrained', message: 'XGBoost retrained. Accuracy: 72%', timestamp: now - 1200000, dismissed: false },
  { id: 'a5', type: 'success', priority: 'low', title: 'Target 1 Hit', message: 'RELIANCE target 1 at 2850 achieved.', symbol: 'RELIANCE', timestamp: now - 1800000, dismissed: false },
]

// Panel 8: Stock Scanner
const symbols = [
  'RELIANCE', 'TCS', 'HDFCBANK', 'INFY', 'ICICIBANK', 'HINDUNILVR', 'ITC',
  'SBIN', 'BHARTIARTL', 'KOTAKBANK', 'LT', 'AXISBANK', 'BAJFINANCE',
  'MARUTI', 'TITAN', 'SUNPHARMA', 'TATAMOTORS', 'WIPRO', 'ULTRACEMCO', 'ADANIENT',
]
const sectors = ['Energy', 'IT', 'Banking', 'IT', 'Banking', 'FMCG', 'FMCG', 'Banking', 'Telecom', 'Banking', 'Infra', 'Banking', 'Finance', 'Auto', 'Consumer', 'Pharma', 'Auto', 'IT', 'Cement', 'Energy']
const sig5: Signal[] = ['BUY', 'BUY', 'SELL', 'BUY', 'HOLD']

export const mockScannerRows: ScannerRow[] = symbols.map((symbol, i) => ({
  symbol,
  ltp: +(1500 + Math.random() * 2000).toFixed(2),
  changePct: +((Math.random() - 0.4) * 5).toFixed(2),
  volume: Math.floor(1000000 + Math.random() * 5000000),
  relativeVolume: +(0.5 + Math.random() * 3).toFixed(2),
  institutionalScore: Math.floor(40 + Math.random() * 55),
  signal: sig5[i % 5],
  agentConsensus: sig5[(i + 1) % 5],
  modelPrediction: sig5[(i + 2) % 5],
  riskScore: Math.floor(20 + Math.random() * 60),
  sector: sectors[i],
  updatedAt: now - Math.floor(Math.random() * 60000),
}))

// Panel 9: Depth Heatmap
export const mockDepthBids: DepthLevel[] = [
  { price: 24348, qty: 2450, orders: 12 },
  { price: 24346, qty: 3200, orders: 18 },
  { price: 24344, qty: 1800, orders: 8 },
  { price: 24342, qty: 5100, orders: 25 },
  { price: 24340, qty: 4200, orders: 20 },
]

export const mockDepthAsks: DepthLevel[] = [
  { price: 24350, qty: 1900, orders: 10 },
  { price: 24352, qty: 2800, orders: 15 },
  { price: 24354, qty: 3600, orders: 19 },
  { price: 24356, qty: 1500, orders: 7 },
  { price: 24358, qty: 2100, orders: 11 },
]

// Panel 10: OI Intelligence
export const mockOILevels: OILevel[] = [
  { strike: 24200, callOI: 850000, putOI: 1200000, callOIChange: -50000, putOIChange: 120000, pcr: 1.41 },
  { strike: 24300, callOI: 1100000, putOI: 980000, callOIChange: 80000, putOIChange: -30000, pcr: 0.89 },
  { strike: 24400, callOI: 1500000, putOI: 600000, callOIChange: 200000, putOIChange: -80000, pcr: 0.40 },
  { strike: 24500, callOI: 1800000, putOI: 350000, callOIChange: 150000, putOIChange: -20000, pcr: 0.19 },
]

export const mockPCRHistory = [
  { time: '09:15', value: 1.05 },
  { time: '09:30', value: 1.12 },
  { time: '09:45', value: 1.08 },
  { time: '10:00', value: 0.98 },
  { time: '10:15', value: 0.92 },
  { time: '10:30', value: 0.88 },
  { time: '10:45', value: 0.95 },
  { time: '11:00', value: 1.02 },
]

// Panel 11: Self-Learning
export const mockLearningMetrics: LearningMetric[] = [
  { metricId: 'accuracy', label: 'Today Accuracy', value: 74, previousValue: 71, unit: '%', trend: 'improving' },
  { metricId: 'sharpe', label: 'Sharpe Ratio', value: 1.82, previousValue: 1.65, unit: '', trend: 'improving' },
  { metricId: 'win_rate', label: 'Win Rate', value: 68, previousValue: 65, unit: '%', trend: 'improving' },
  { metricId: 'profit_factor', label: 'Profit Factor', value: 2.1, previousValue: 1.9, unit: 'x', trend: 'improving' },
]

export const mockWeightChanges = [
  { agent: 'Momentum', oldWeight: 1.0, newWeight: 1.5 },
  { agent: 'Graham', oldWeight: 1.2, newWeight: 0.9 },
  { agent: 'Deriv', oldWeight: 0.8, newWeight: 1.1 },
]

export const mockLessons = [
  { id: 'l1', text: 'GEX flip zones more reliable when volume > 2x average', timestamp: now - 3600000 },
  { id: 'l2', text: 'Wyckoff accumulation signals 15% more accurate on 15m than 5m', timestamp: now - 7200000 },
  { id: 'l3', text: 'Agent Rajan underperforms in trending markets - reduce weight', timestamp: now - 10800000 },
]

export const mockPatternMatches = [
  { symbol: 'RELIANCE', date: '2024-05-15', similarity: 78 },
  { symbol: 'NIFTY', date: '2024-11-22', similarity: 72 },
  { symbol: 'BANKNIFTY', date: '2025-01-10', similarity: 68 },
]

// Panel 12: Risk Meter
export const mockPortfolioRisk: PortfolioRisk = {
  totalExposure: 485000,
  maxLoss: 12500,
  var95: 8200,
  currentDrawdown: 1.2,
  leverage: 1.8,
  marginUsed: 185000,
  marginAvailable: 315000,
}

export const mockRiskMetrics: RiskMetric[] = [
  { label: 'Max Drawdown', value: 1.2, max: 3.0, unit: '%', status: 'safe' },
  { label: 'Portfolio Heat', value: 38, max: 100, unit: '%', status: 'safe' },
  { label: 'Leverage', value: 1.8, max: 4.0, unit: 'x', status: 'warning' },
  { label: 'Margin Used', value: 37, max: 100, unit: '%', status: 'safe' },
]

export const mockPositions = [
  { symbol: 'NIFTY', qty: 50, side: 'LONG' as const, entryPrice: 24310, ltp: 24350, mtm: 2000 },
  { symbol: 'RELIANCE', qty: 25, side: 'LONG' as const, entryPrice: 2835, ltp: 2852, mtm: 425 },
  { symbol: 'BANKNIFTY', qty: -25, side: 'SHORT' as const, entryPrice: 51200, ltp: 51150, mtm: 1250 },
]

export const mockTodayPnl = 3675
