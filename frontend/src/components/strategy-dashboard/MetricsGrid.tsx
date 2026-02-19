import { Card, CardContent } from '@/components/ui/card'
import type { DashboardSummary } from '@/types/strategy-dashboard'

interface MetricCardProps {
  label: string
  value: string | number
  sub?: string
  color?: string
}

function MetricCard({ label, value, sub, color }: MetricCardProps) {
  return (
    <Card>
      <CardContent className="p-3">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-lg font-semibold ${color || ''}`}>{value}</p>
        {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
      </CardContent>
    </Card>
  )
}

export function MetricsGrid({ summary }: { summary: DashboardSummary }) {
  const pnlColor = (v: number) => (v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : '')

  return (
    <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
      <MetricCard
        label="Win Rate"
        value={`${summary.win_rate.toFixed(1)}%`}
        sub={`${summary.winning_trades}W / ${summary.losing_trades}L`}
      />
      <MetricCard
        label="Profit Factor"
        value={summary.profit_factor.toFixed(2)}
        color={summary.profit_factor > 1 ? 'text-green-600' : 'text-red-600'}
      />
      <MetricCard
        label="Expectancy"
        value={summary.expectancy.toFixed(2)}
        color={pnlColor(summary.expectancy)}
      />
      <MetricCard
        label="Risk:Reward"
        value={summary.risk_reward_ratio.toFixed(2)}
      />
      <MetricCard
        label="Avg Win"
        value={summary.avg_win.toFixed(2)}
        color="text-green-600"
      />
      <MetricCard
        label="Avg Loss"
        value={summary.avg_loss.toFixed(2)}
        color="text-red-600"
      />
      <MetricCard
        label="Best Streak"
        value={`${summary.max_consecutive_wins} wins`}
        color="text-green-600"
      />
      <MetricCard
        label="Worst Streak"
        value={`${summary.max_consecutive_losses} losses`}
        color="text-red-600"
      />
      <MetricCard
        label="Cumulative P&L"
        value={summary.cumulative_pnl.toFixed(2)}
        color={pnlColor(summary.cumulative_pnl)}
      />
      <MetricCard
        label="Max Drawdown"
        value={summary.max_drawdown.toFixed(2)}
        sub={`${summary.max_drawdown_pct.toFixed(1)}%`}
        color="text-red-600"
      />
      <MetricCard
        label="Total Trades"
        value={summary.total_trades}
      />
      <MetricCard
        label="Active Positions"
        value={summary.active_positions}
      />
    </div>
  )
}
