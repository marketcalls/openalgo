import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import type { RiskMetrics } from '@/types/strategy-dashboard'

interface MetricsGridProps {
  metrics: RiskMetrics
  totalPnl?: number
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

function MetricItem({
  label,
  value,
  color,
}: {
  label: string
  value: string
  color?: 'green' | 'red' | 'neutral'
}) {
  const colorClass =
    color === 'green'
      ? 'text-green-600'
      : color === 'red'
        ? 'text-red-600'
        : ''

  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`font-mono tabular-nums font-medium ${colorClass}`}>{value}</p>
    </div>
  )
}

function pnlColor(value: number): 'green' | 'red' | 'neutral' {
  if (value > 0) return 'green'
  if (value < 0) return 'red'
  return 'neutral'
}

export function MetricsGrid({ metrics, totalPnl }: MetricsGridProps) {
  return (
    <div className="space-y-4">
      {/* Key metrics */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Key Metrics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            <MetricItem
              label="Total P&L"
              value={currencyFormat.format(totalPnl ?? 0)}
              color={pnlColor(totalPnl ?? 0)}
            />
            <MetricItem
              label="Win Rate"
              value={`${metrics.win_rate.toFixed(1)}%`}
              color={metrics.win_rate >= 50 ? 'green' : 'red'}
            />
            <MetricItem
              label="Profit Factor"
              value={metrics.profit_factor ? metrics.profit_factor.toFixed(2) : '—'}
              color={metrics.profit_factor >= 1 ? 'green' : 'red'}
            />
            <MetricItem
              label="Max Drawdown"
              value={`${currencyFormat.format(metrics.max_drawdown)} (${metrics.max_drawdown_pct.toFixed(1)}%)`}
              color="red"
            />
            <MetricItem
              label="Risk:Reward"
              value={`1:${metrics.risk_reward_ratio.toFixed(2)}`}
            />
            <MetricItem
              label="Expectancy"
              value={`${currencyFormat.format(metrics.expectancy)}/trade`}
              color={pnlColor(metrics.expectancy)}
            />
          </div>
        </CardContent>
      </Card>

      {/* Trade Statistics */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Trade Statistics</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 gap-4">
            <MetricItem label="Total Trades" value={String(metrics.total_trades)} />
            <MetricItem
              label="Winning Trades"
              value={String(metrics.winning_trades)}
              color="green"
            />
            <MetricItem
              label="Losing Trades"
              value={String(metrics.losing_trades)}
              color="red"
            />
            <MetricItem
              label="Average Win"
              value={currencyFormat.format(metrics.average_win)}
              color="green"
            />
            <MetricItem
              label="Average Loss"
              value={currencyFormat.format(metrics.average_loss)}
              color="red"
            />
            <MetricItem
              label="Best Trade"
              value={currencyFormat.format(metrics.best_trade)}
              color="green"
            />
            <MetricItem
              label="Worst Trade"
              value={currencyFormat.format(metrics.worst_trade)}
              color="red"
            />
            <MetricItem
              label="Max Consec. Wins"
              value={String(metrics.max_consecutive_wins)}
            />
            <MetricItem
              label="Max Consec. Losses"
              value={String(metrics.max_consecutive_losses)}
            />
            <MetricItem
              label="Best Day"
              value={currencyFormat.format(metrics.best_day)}
              color="green"
            />
            <MetricItem
              label="Worst Day"
              value={currencyFormat.format(metrics.worst_day)}
              color="red"
            />
            <MetricItem
              label="Avg Daily P&L"
              value={currencyFormat.format(metrics.average_daily_pnl)}
              color={pnlColor(metrics.average_daily_pnl)}
            />
            <MetricItem
              label="Days Active"
              value={String(metrics.days_active)}
            />
            <MetricItem
              label="Current Drawdown"
              value={`${currencyFormat.format(metrics.current_drawdown)} (${metrics.current_drawdown_pct.toFixed(1)}%)`}
              color={metrics.current_drawdown < 0 ? 'red' : 'neutral'}
            />
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
