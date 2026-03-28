// ============================================================
// AAUM Intelligence Types — Zod schemas + inferred TypeScript
// Single source of truth. Zod validates at API boundary.
// Must match Pydantic models in AAUM api/v5/router.py.
// ============================================================
import { z } from 'zod'

// --- Enums ---
export const TradeActionSchema = z.enum(['BUY', 'SELL', 'HOLD', 'NO_ACTION'])
export const MarketRegimeSchema = z.enum(['bull', 'bear', 'neutral', 'volatile'])
export const RiskDecisionSchema = z.enum(['APPROVE', 'MODIFY', 'REJECT', 'NO_ACTION'])
export const LayerSignalSchema = z.enum(['bullish', 'bearish', 'neutral'])

export type TradeAction = z.infer<typeof TradeActionSchema>
export type MarketRegime = z.infer<typeof MarketRegimeSchema>
export type RiskDecision = z.infer<typeof RiskDecisionSchema>
export type LayerSignal = z.infer<typeof LayerSignalSchema>

// --- Equity Signal (Panel 3) ---
const EquitySignalSchema = z.object({
  entry_price: z.number(),
  stop_loss: z.number(),
  target_1: z.number(),
  target_2: z.number().nullable().default(null),
  target_3: z.number().nullable().default(null),
  rr_ratio: z.number(),
  atr_14: z.number(),
  position_size_pct: z.number(),
  quantity: z.number(),
  lot_size: z.number().nullable().default(null),
})
export type EquitySignal = z.infer<typeof EquitySignalSchema>

// --- Options Strategy (Panel 4) ---
const OptionLegSchema = z.object({
  action: z.enum(['BUY', 'SELL']),
  strike: z.number(),
  option_type: z.enum(['CE', 'PE']),
  premium: z.number(),
  quantity: z.number(),
})
const OptionsGreeksSchema = z.object({
  delta: z.number().default(0),
  gamma: z.number().default(0),
  theta: z.number().default(0),
  vega: z.number().default(0),
})
const OptionsStrategySchema = z.object({
  strategy_name: z.string(),
  legs: z.array(OptionLegSchema).default([]),
  greeks: OptionsGreeksSchema,
  pop: z.number().default(0),
  max_profit: z.number().default(0),
  max_loss: z.number().default(0),
  breakeven: z.array(z.number()).default([]),
})
export type OptionsStrategy = z.infer<typeof OptionsStrategySchema>

// --- 12-Layer Confluence Map (Panel 5) ---
const LayerResultSchema = z.object({
  layer_number: z.number(),
  layer_name: z.string(),
  signal: LayerSignalSchema,
  confidence: z.number(),
  reasoning: z.string().default(''),
  entry: z.number().optional(),
  stop_loss: z.number().optional(),
  target: z.number().optional(),
})
export type LayerResult = z.infer<typeof LayerResultSchema>

// --- Agent Debate (Panel 6) ---
const AgentOutputSchema = z.object({
  agent_name: z.string(),
  action: TradeActionSchema,
  confidence: z.number(),
  reasoning: z.string().default(''),
  key_metrics: z.record(z.string(), z.union([z.number(), z.string()])).default({}),
})
const AgentDebateSchema = z.object({
  bulls: z.array(AgentOutputSchema),
  bears: z.array(AgentOutputSchema),
  neutral: z.array(AgentOutputSchema),
  conviction_pct: z.number(),
  verdict: TradeActionSchema,
})
export type AgentDebate = z.infer<typeof AgentDebateSchema>

// --- Portfolio (Panel 7) ---
const PortfolioPositionSchema = z.object({
  symbol: z.string(),
  exchange: z.string(),
  quantity: z.number(),
  avg_price: z.number(),
  ltp: z.number(),
  pnl: z.number(),
})
const PortfolioStatusSchema = z.object({
  positions: z.array(PortfolioPositionSchema).default([]),
  total_pnl: z.number().default(0),
})
export type PortfolioStatus = z.infer<typeof PortfolioStatusSchema>

// --- Full Analysis Response ---
export const AnalysisResultSchema = z.object({
  symbol: z.string(),
  action: TradeActionSchema,
  confidence: z.number().min(0).max(100),
  confluence: z.number().min(0).max(100),
  total_layers: z.number().default(12),
  regime: MarketRegimeSchema,

  equity_signal: EquitySignalSchema,
  options_strategy: OptionsStrategySchema,
  layers: z.array(LayerResultSchema),
  agent_debate: AgentDebateSchema,
  portfolio: PortfolioStatusSchema,

  survival_score: z.number().min(0).max(100).default(50),
  risk_decision: RiskDecisionSchema,
  veto_reason: z.string().nullable().default(null),

  // Extended intelligence (Phase 2 panels)
  alpha_factors: z.record(z.string(), z.unknown()).default({}),
  factor_decomposition: z.record(z.string(), z.unknown()).default({}),
  vlrt: z.record(z.string(), z.unknown()).default({}),
  vpin: z.record(z.string(), z.unknown()).default({}),
  street_safety: z.record(z.string(), z.unknown()).default({}),
  transaction_cost: z.record(z.string(), z.unknown()).default({}),
  survival: z.record(z.string(), z.unknown()).default({}),

  analysis_id: z.string(),
  timestamp: z.string(),
})
export type AnalysisResult = z.infer<typeof AnalysisResultSchema>

// --- Execute Response ---
export interface ExecuteResult {
  status: 'success' | 'error'
  order_ids: string[]
  message: string
}

// --- Health Response ---
export interface HealthResult {
  status: 'healthy' | 'degraded' | 'offline'
  aaum_version: string
  ollama_status: 'connected' | 'disconnected'
  last_analysis: string | null
}
