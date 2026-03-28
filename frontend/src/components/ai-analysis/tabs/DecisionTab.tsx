// frontend/src/components/ai-analysis/tabs/DecisionTab.tsx
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { LLMCommentary } from '@/components/ai-analysis'
import { ConfluenceMeter } from '@/components/ai-analysis/ConfluenceMeter'
import { VotingBreakdown } from '@/components/ai-analysis/VotingBreakdown'
import { EvidenceChain } from '@/components/ai-analysis/EvidenceChain'
import { useStrategyDecision } from '@/hooks/useStrategyAnalysis'
import { Loader2, AlertCircle } from 'lucide-react'
import type { AIAnalysisResult } from '@/types/ai-analysis'

interface DecisionTabProps {
  analysis: AIAnalysisResult
  symbol: string
  exchange: string
  interval: string
}

const SIGNAL_COLORS: Record<string, string> = {
  STRONG_BUY: '#16a34a',
  BUY: '#22c55e',
  HOLD: '#eab308',
  SELL: '#ef4444',
  STRONG_SELL: '#dc2626',
}

const ACTION_STYLES: Record<string, { bg: string; text: string }> = {
  BUY: { bg: 'bg-green-100', text: 'text-green-700' },
  STRONG_BUY: { bg: 'bg-green-200', text: 'text-green-800' },
  SELL: { bg: 'bg-red-100', text: 'text-red-700' },
  STRONG_SELL: { bg: 'bg-red-200', text: 'text-red-800' },
  HOLD: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
}

function fmt(n: number | null | undefined): string {
  return n != null
    ? n.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : 'N/A'
}

function fmtPct(n: number | null | undefined): string {
  return n != null ? `${n.toFixed(2)}%` : 'N/A'
}

export function DecisionTab({ analysis, symbol, exchange, interval }: DecisionTabProps) {
  const { data: decision, isLoading, error } = useStrategyDecision(symbol, exchange, interval)

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-muted-foreground">
        <Loader2 className="h-5 w-5 animate-spin" />
        Loading strategy decision...
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex items-center justify-center gap-2 py-16 text-sm text-destructive">
        <AlertCircle className="h-5 w-5" />
        Failed to load decision: {(error as Error).message}
      </div>
    )
  }

  if (!decision) {
    return (
      <div className="flex items-center justify-center py-16 text-sm text-muted-foreground">
        No decision data available. Run analysis first.
      </div>
    )
  }

  const actionStyle = ACTION_STYLES[decision.action?.toUpperCase()] ?? ACTION_STYLES.HOLD
  const actionColor = SIGNAL_COLORS[decision.action?.toUpperCase()] ?? '#eab308'

  return (
    <div className="space-y-4">
      {/* Decision Header */}
      <Card>
        <CardContent className="pt-4">
          <div className="flex items-center gap-3 flex-wrap">
            <Badge className={`${actionStyle.bg} ${actionStyle.text} text-base px-4 py-1.5 font-bold`}>
              {decision.action}
            </Badge>
            <span className="text-sm text-muted-foreground">{decision.strategy_label}</span>
            <span className="text-sm font-medium">
              {decision.symbol} @ {fmt(decision.current_price)}
            </span>
          </div>
        </CardContent>
      </Card>

      {/* Three-column grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Col 1: Trade Levels + Confluence + Position Sizing */}
        <div className="space-y-4">
          {/* Trade Levels */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Trade Levels</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-2 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Entry Zone</span>
                  <span className="font-medium">
                    {fmt(decision.entry.low)} - {fmt(decision.entry.high)}
                  </span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Entry Mid</span>
                  <span className="font-medium">{fmt(decision.entry.mid)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-red-500">Stop Loss</span>
                  <span className="font-medium text-red-500">
                    {fmt(decision.stop_loss.price)} ({fmtPct(decision.stop_loss.distance_pct)})
                  </span>
                </div>
                <hr className="my-1" />
                {decision.targets.map((t, i) => (
                  <div key={i} className="flex justify-between">
                    <span className="text-green-600">{t.label}</span>
                    <span className="font-medium text-green-600">
                      {fmt(t.price)} (R:R {t.rr_ratio.toFixed(1)})
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Confluence Meter */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Confluence</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col items-center">
              <ConfluenceMeter
                score={decision.confluence.score}
                bullishCount={decision.confluence.bullish_count}
                bearishCount={decision.confluence.bearish_count}
                neutralCount={decision.confluence.neutral_count}
                color={actionColor}
              />
              <div className="mt-3 w-full">
                <VotingBreakdown votes={decision.confluence.votes} />
              </div>
            </CardContent>
          </Card>

          {/* Position Sizing */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Position Sizing</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Shares</span>
                  <span className="font-medium">{decision.position_sizing.shares}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Risk Amount</span>
                  <span className="font-medium">{fmt(decision.position_sizing.risk_amount)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Stop Distance</span>
                  <span className="font-medium">{fmt(decision.position_sizing.stop_distance)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Vol Modifier</span>
                  <span className="font-medium">{decision.position_sizing.vol_modifier.toFixed(2)}x</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Col 2: Signal Overview + SMC Context + Wave & Fib Context */}
        <div className="space-y-4">
          {/* Signal Overview */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Signal Overview</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Signal</span>
                  <Badge
                    style={{
                      backgroundColor: SIGNAL_COLORS[decision.signal_summary.signal] ?? '#eab308',
                      color: '#fff',
                    }}
                    className="text-xs"
                  >
                    {decision.signal_summary.signal.replace('_', ' ')}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Score</span>
                  <span className="font-medium">{decision.signal_summary.score.toFixed(3)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Confidence</span>
                  <span className="font-medium">{decision.signal_summary.confidence.toFixed(1)}%</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Regime</span>
                  <span className="font-medium">{decision.signal_summary.regime.replace('_', ' ')}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Smart Money Context */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Smart Money Context</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Bias</span>
                  <Badge variant="outline" className="text-xs capitalize">
                    {decision.smc_context.bias}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Active OBs</span>
                  <span className="font-medium">{decision.smc_context.active_obs}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Unfilled FVGs</span>
                  <span className="font-medium">{decision.smc_context.unfilled_fvgs}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Last Break</span>
                  <span className="font-medium">{decision.smc_context.last_break ?? 'None'}</span>
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Wave & Fibonacci Context */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Wave & Fibonacci</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Elliott Phase</span>
                  <span className="font-medium">{decision.wave_context.elliott_phase.replace('_', ' ')}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Fib Trend</span>
                  <span className="font-medium capitalize">{decision.wave_context.fib_trend}</span>
                </div>
                {decision.wave_context.nearest_retracement && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Nearest Fib</span>
                    <span className="font-medium">
                      {decision.wave_context.nearest_retracement.label} @{' '}
                      {fmt(decision.wave_context.nearest_retracement.price)}
                    </span>
                  </div>
                )}
                {decision.wave_context.harmonic_patterns.length > 0 && (
                  <div>
                    <span className="text-muted-foreground text-xs">Harmonic Patterns</span>
                    <div className="flex gap-1 mt-1 flex-wrap">
                      {decision.wave_context.harmonic_patterns.map((p, i) => (
                        <Badge key={i} variant="outline" className="text-xs">
                          {p}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Col 3: Risk Metrics */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium">Risk Metrics</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Vol Regime</span>
                  <Badge variant="outline" className="text-xs capitalize">
                    {decision.risk_metrics.vol_regime}
                  </Badge>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Sharpe Ratio</span>
                  <span className="font-medium">{decision.risk_metrics.sharpe.toFixed(2)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Max Drawdown</span>
                  <span className="font-medium text-red-500">{fmtPct(decision.risk_metrics.max_dd)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">VaR (95%)</span>
                  <span className="font-medium">{fmtPct(decision.risk_metrics.var_95)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Historical Vol</span>
                  <span className="font-medium">{fmtPct(decision.risk_metrics.hv)}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Vol Percentile</span>
                  <span className="font-medium">{fmtPct(decision.risk_metrics.vol_percentile)}</span>
                </div>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Full-width: Evidence Chain */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">Evidence Chain</CardTitle>
        </CardHeader>
        <CardContent>
          <EvidenceChain reasoning={decision.reasoning} />
        </CardContent>
      </Card>

      {/* Full-width: LLM Commentary */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium">AI Explanation</CardTitle>
        </CardHeader>
        <CardContent>
          <LLMCommentary analysis={analysis} />
        </CardContent>
      </Card>
    </div>
  )
}
