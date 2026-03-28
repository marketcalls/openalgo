import { useState } from 'react'
import { useHedgeStrategy } from '@/hooks/useStrategyAnalysis'
import { StrategyTradeSetup } from './StrategyTradeSetup'
import { Badge } from '@/components/ui/badge'
import { Loader2, AlertCircle, Lightbulb } from 'lucide-react'
import type { RiskMetrics } from '@/types/strategy-analysis'

interface HedgeFundPanelProps {
  symbol: string
  exchange: string
  interval: string
}

type RiskEngine = 'from_scratch' | 'empyrical' | 'quantstats'

function zScoreColor(z: number | null): string {
  if (z === null) return 'text-muted-foreground'
  if (z >= 2) return 'text-red-600'
  if (z <= -2) return 'text-green-600'
  return 'text-yellow-600'
}

function zScoreBg(z: number | null): string {
  if (z === null) return 'bg-muted'
  if (z >= 2) return 'bg-red-50'
  if (z <= -2) return 'bg-green-50'
  return 'bg-yellow-50'
}

function regimeBadgeColor(regime: string): string {
  const r = regime.toLowerCase()
  if (r.includes('low')) return 'bg-green-100 text-green-700'
  if (r.includes('high') || r.includes('extreme')) return 'bg-red-100 text-red-700'
  return 'bg-yellow-100 text-yellow-700'
}

function formatMetric(value: number | undefined, suffix = '', decimals = 2): string {
  if (value === undefined || value === null) return '—'
  return value.toFixed(decimals) + suffix
}

function MetricRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between items-center px-2 py-0.5 text-xs">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-mono font-medium">{value}</span>
    </div>
  )
}

function RiskMetricsDisplay({ metrics }: { metrics: RiskMetrics }) {
  return (
    <div className="space-y-0.5">
      <MetricRow label="Sharpe Ratio" value={formatMetric(metrics.sharpe_ratio)} />
      <MetricRow label="Sortino Ratio" value={formatMetric(metrics.sortino_ratio)} />
      <MetricRow label="Calmar Ratio" value={formatMetric(metrics.calmar_ratio)} />
      <MetricRow label="Max Drawdown" value={formatMetric(metrics.max_drawdown_pct, '%')} />
      <MetricRow label="Annual Return" value={formatMetric(metrics.annual_return_pct, '%')} />
      <MetricRow label="VaR 95%" value={formatMetric(metrics.var_95, '%')} />
      <MetricRow label="Omega Ratio" value={formatMetric(metrics.omega_ratio)} />
      <MetricRow label="Stability" value={formatMetric(metrics.stability)} />
      <MetricRow label="Win Rate" value={formatMetric(metrics.win_rate_pct, '%')} />
      <MetricRow label="Profit Factor" value={formatMetric(metrics.profit_factor)} />
      <MetricRow label="CAGR" value={formatMetric(metrics.cagr_pct, '%')} />
      <MetricRow label="Best Day" value={formatMetric(metrics.best_day_pct, '%')} />
      <MetricRow label="Worst Day" value={formatMetric(metrics.worst_day_pct, '%')} />
    </div>
  )
}

export function HedgeFundPanel({ symbol, exchange, interval }: HedgeFundPanelProps) {
  const { data, isLoading, error } = useHedgeStrategy(symbol, exchange, interval)
  const [riskEngine, setRiskEngine] = useState<RiskEngine>('from_scratch')

  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Running hedge fund analytics...
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center gap-2 py-8 text-sm text-red-500">
        <AlertCircle className="h-4 w-4" />
        Failed to load hedge fund data
      </div>
    )
  }

  const { from_scratch, library } = data
  const { mean_reversion, momentum, volatility_regime } = from_scratch
  const hasLibrary = !!library

  const activeRiskMetrics: RiskMetrics =
    riskEngine === 'empyrical' && library?.empyrical_metrics
      ? library.empyrical_metrics
      : riskEngine === 'quantstats' && library?.quantstats_metrics
        ? library.quantstats_metrics
        : from_scratch.risk_metrics

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold">Hedge Fund Analytics</h3>
      </div>

      {/* Suggestions */}
      {from_scratch.suggestions.length > 0 && (
        <div className="space-y-1 rounded border border-blue-200 bg-blue-50 p-2">
          <p className="text-xs font-medium text-blue-700 flex items-center gap-1">
            <Lightbulb className="h-3 w-3" /> Suggestions
          </p>
          {from_scratch.suggestions.map((s, i) => (
            <p key={i} className="text-xs text-blue-600">
              {s}
            </p>
          ))}
        </div>
      )}

      {/* Mean Reversion */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-2">Mean Reversion</p>
        <div className="grid grid-cols-3 gap-2">
          <div className={`text-center rounded p-2 ${zScoreBg(mean_reversion.current_zscore)}`}>
            <p className="text-[10px] text-muted-foreground uppercase">Z-Score</p>
            <p className={`text-lg font-bold font-mono ${zScoreColor(mean_reversion.current_zscore)}`}>
              {mean_reversion.current_zscore !== null
                ? mean_reversion.current_zscore.toFixed(2)
                : '—'}
            </p>
          </div>
          <div className="text-center rounded bg-muted/50 p-2">
            <p className="text-[10px] text-muted-foreground uppercase">Mean Price</p>
            <p className="text-sm font-bold font-mono">
              {mean_reversion.current_mean !== null
                ? mean_reversion.current_mean.toFixed(2)
                : '—'}
            </p>
          </div>
          <div className="text-center rounded bg-muted/50 p-2">
            <p className="text-[10px] text-muted-foreground uppercase">Half-Life</p>
            <p className="text-sm font-bold font-mono">
              {mean_reversion.half_life_bars !== null
                ? `${mean_reversion.half_life_bars} bars`
                : '—'}
            </p>
          </div>
        </div>
      </div>

      {/* Momentum Factor */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-2">Momentum Factor</p>
        {Object.keys(momentum.scores).length > 0 && (
          <div className="space-y-1 mb-2">
            {Object.entries(momentum.scores).map(([period, ret]) => (
              <div key={period} className="flex justify-between items-center px-2 py-0.5 text-xs">
                <span className="text-muted-foreground">{period}</span>
                <span
                  className={`font-mono font-medium ${
                    ret > 0 ? 'text-green-600' : ret < 0 ? 'text-red-600' : 'text-muted-foreground'
                  }`}
                >
                  {ret > 0 ? '+' : ''}
                  {(ret * 100).toFixed(2)}%
                </span>
              </div>
            ))}
          </div>
        )}
        <div className="flex items-center gap-3 px-2 text-xs">
          <span className="text-muted-foreground">
            Composite:{' '}
            <span className="font-mono font-medium">
              {momentum.composite !== null ? momentum.composite.toFixed(3) : '—'}
            </span>
          </span>
          {momentum.signal && (
            <Badge
              variant="outline"
              className={
                momentum.signal.toLowerCase().includes('bull')
                  ? 'border-green-300 text-green-700'
                  : momentum.signal.toLowerCase().includes('bear')
                    ? 'border-red-300 text-red-700'
                    : ''
              }
            >
              {momentum.signal}
            </Badge>
          )}
        </div>
      </div>

      {/* Volatility Regime */}
      <div>
        <p className="text-xs font-medium text-muted-foreground mb-2">Volatility Regime</p>
        <div className="grid grid-cols-2 gap-2">
          <div className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/50 text-xs">
            <span className="text-muted-foreground">Regime</span>
            <Badge className={regimeBadgeColor(volatility_regime.regime)}>
              {volatility_regime.regime}
            </Badge>
          </div>
          <div className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/50 text-xs">
            <span className="text-muted-foreground">HV (Parkinson)</span>
            <span className="font-mono font-medium">
              {(volatility_regime.parkinson_vol * 100).toFixed(1)}%
            </span>
          </div>
          <div className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/50 text-xs">
            <span className="text-muted-foreground">Vol Percentile</span>
            <span className="font-mono font-medium">
              {volatility_regime.vol_percentile.toFixed(0)}%
            </span>
          </div>
          <div className="flex items-center justify-between px-2 py-1.5 rounded bg-muted/50 text-xs">
            <span className="text-muted-foreground">Position Sizing</span>
            <span className="font-mono font-medium capitalize">
              {volatility_regime.position_sizing}
            </span>
          </div>
        </div>
      </div>

      {/* Risk Metrics */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <p className="text-xs font-medium text-muted-foreground">Risk Metrics</p>
        </div>

        {/* Engine toggle */}
        {hasLibrary && (
          <div className="flex gap-1 bg-muted rounded-lg p-0.5 mb-2">
            <button
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                riskEngine === 'from_scratch'
                  ? 'bg-background shadow text-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setRiskEngine('from_scratch')}
            >
              From Scratch
            </button>
            <button
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                riskEngine === 'empyrical'
                  ? 'bg-background shadow text-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setRiskEngine('empyrical')}
            >
              Empyrical
            </button>
            <button
              className={`flex-1 text-xs py-1.5 rounded-md transition-colors ${
                riskEngine === 'quantstats'
                  ? 'bg-background shadow text-foreground font-medium'
                  : 'text-muted-foreground hover:text-foreground'
              }`}
              onClick={() => setRiskEngine('quantstats')}
            >
              QuantStats
            </button>
          </div>
        )}

        <div className="rounded border p-2">
          <RiskMetricsDisplay metrics={activeRiskMetrics} />
        </div>
      </div>

      {/* Trade Setup */}
      <StrategyTradeSetup levels={data.trade_levels} />
    </div>
  )
}
