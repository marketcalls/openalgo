// ============================================================
// AAUM Intelligence — TypeScript Types + Zod Runtime Schemas
// Must match Pydantic models in AAUM backend exactly.
// Source: AAUM-OPENALGO-DEFINITIVE-DESIGN.md Section 8
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

// --- Panel 3: Equity Signal Card ---
export const EquitySignalSchema = z.object({
  entry_price: z.number(),
  stop_loss: z.number(),
  target_1: z.number(),
  target_2: z.number().nullable(),
  target_3: z.number().nullable(),
  rr_ratio: z.number(),
  atr_14: z.number(),
  position_size_pct: z.number(),
  quantity: z.number(),
  lot_size: z.number().nullable(),
})

export type EquitySignal = z.infer<typeof EquitySignalSchema>

// --- Panel 4: Options Strategy Card ---
export const OptionLegSchema = z.object({
  action: z.enum(['BUY', 'SELL']),
  strike: z.number(),
  option_type: z.enum(['CE', 'PE']),
  premium: z.number(),
  quantity: z.number(),
})

export const OptionsGreeksSchema = z.object({
  delta: z.number(),
  gamma: z.number(),
  theta: z.number(),
  vega: z.number(),
})

export const OptionsStrategySchema = z.object({
  strategy_name: z.string(),
  legs: z.array(OptionLegSchema),
  greeks: OptionsGreeksSchema,
  pop: z.number(),
  max_profit: z.number(),
  max_loss: z.number(),
  breakeven: z.array(z.number()),
})

export type OptionLeg = z.infer<typeof OptionLegSchema>
export type OptionsGreeks = z.infer<typeof OptionsGreeksSchema>
export type OptionsStrategy = z.infer<typeof OptionsStrategySchema>

// --- Panel 5: 12-Layer Confluence Map ---
export const LayerResultSchema = z.object({
  layer_number: z.number(),
  layer_name: z.string(),
  signal: LayerSignalSchema,
  confidence: z.number().min(0).max(100),
  reasoning: z.string().default('No reasoning provided'),
  entry: z.number().optional(),
  stop_loss: z.number().optional(),
  target: z.number().optional(),
})

export type LayerResult = z.infer<typeof LayerResultSchema>

// --- Panel 6: Agent Debate ---
export const AgentOutputSchema = z.object({
  agent_name: z.string(),
  action: TradeActionSchema,
  confidence: z.number(),
  reasoning: z.string(),
  key_metrics: z.record(z.string(), z.unknown()),
})

export const AgentDebateSchema = z.object({
  bulls: z.array(AgentOutputSchema),
  bears: z.array(AgentOutputSchema),
  neutral: z.array(AgentOutputSchema),
  conviction_pct: z.number(),
  verdict: TradeActionSchema,
})

export type AgentOutput = z.infer<typeof AgentOutputSchema>
export type AgentDebate = z.infer<typeof AgentDebateSchema>

// --- Panel 7: Portfolio ---
export const PortfolioPositionSchema = z.object({
  symbol: z.string(),
  exchange: z.string(),
  quantity: z.number(),
  avg_price: z.number(),
  ltp: z.number(),
  pnl: z.number(),
})

export const PortfolioStatusSchema = z.object({
  positions: z.array(PortfolioPositionSchema),
  total_pnl: z.number(),
})

export type PortfolioPosition = z.infer<typeof PortfolioPositionSchema>
export type PortfolioStatus = z.infer<typeof PortfolioStatusSchema>

// --- Full Analysis Response Schema (Zod — validates at API boundary) ---
export const AnalysisResultSchema = z.object({
  // Header / Verdict
  symbol: z.string(),
  action: TradeActionSchema,
  confidence: z.number().min(0).max(100),
  confluence: z.number().min(0).max(100),
  total_layers: z.number().default(12),
  regime: MarketRegimeSchema,

  // Panel data
  equity_signal: EquitySignalSchema,
  options_strategy: OptionsStrategySchema.nullable(),
  layers: z.array(LayerResultSchema),
  agent_debate: AgentDebateSchema.nullable(),
  portfolio: PortfolioStatusSchema.nullable(),

  // Risk
  survival_score: z.number().min(0).max(100),
  risk_decision: RiskDecisionSchema,
  veto_reason: z.string().nullable(),

  // Extended intelligence (rendered in Phase 2)
  alpha_factors: z.record(z.string(), z.unknown()).optional(),
  factor_decomposition: z.record(z.string(), z.unknown()).optional(),
  vlrt: z.record(z.string(), z.unknown()).optional(),
  vpin: z.record(z.string(), z.unknown()).optional(),
  street_safety: z.record(z.string(), z.unknown()).optional(),
  transaction_cost: z.record(z.string(), z.unknown()).optional(),
  survival: z.record(z.string(), z.unknown()).optional(),

  // Metadata
  analysis_id: z.string(),
  timestamp: z.string(),
})

export type AnalysisResult = z.infer<typeof AnalysisResultSchema>

// --- Execute Response (from POST /api/v1/aaum/execute) ---
export interface ExecuteResult {
  status: 'success' | 'error'
  order_ids: string[]
  message: string
}

// --- Health Response (from GET /api/v1/aaum/health) ---
export interface HealthEndpointStatus {
  reachable: boolean
  status_code: number | null
  url: string | null
  error?: string
}

export interface HealthResult {
  status: 'healthy' | 'degraded' | 'offline'
  configured_url: string
  backend: 'colab' | 'local' | 'remote' | 'mock'
  is_colab: boolean
  colab: HealthEndpointStatus
  local: HealthEndpointStatus
  // Legacy fields (kept for backward compat)
  aaum_version?: string
  ollama_status?: 'connected' | 'disconnected'
  last_analysis?: string | null
}

// --- Config Response (from POST /api/v1/aaum/config) ---
export interface ConfigResult {
  status: 'success' | 'error'
  message: string
  old_url?: string
  new_url?: string
}
