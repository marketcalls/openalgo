import { ShieldAlert, ShieldCheck, TrendingDown, TrendingUp } from 'lucide-react'
import type { CircuitBreakerStatus, Strategy } from '@/types/strategy'

const REASON_LABELS: Record<string, string> = {
  daily_stoploss: 'Daily Stoploss',
  daily_target: 'Daily Target',
  daily_trailstop: 'Daily Trailing Stop',
}

function formatCurrency(value: number): string {
  const sign = value >= 0 ? '' : '-'
  return `${sign}₹${Math.abs(value).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

function hasCircuitBreakerConfig(strategy: Strategy): boolean {
  return !!(
    strategy.daily_stoploss_value ||
    strategy.daily_target_value ||
    strategy.daily_trailstop_value
  )
}

interface CircuitBreakerBannerProps {
  status?: CircuitBreakerStatus
  strategy: Strategy
  compact?: boolean
}

export function CircuitBreakerBanner({
  status,
  strategy,
  compact = false,
}: CircuitBreakerBannerProps) {
  const hasConfig = hasCircuitBreakerConfig(strategy)

  // Don't render anything if no config and no live status
  if (!hasConfig && !status) return null

  // State 1: Tripped — Red/destructive alert
  if (status?.isTripped) {
    const reasonLabel = REASON_LABELS[status.reason] || status.reason || 'Circuit Breaker'

    if (compact) {
      return (
        <div className="flex items-center gap-2 rounded-md border border-destructive/50 bg-destructive/10 px-3 py-2 text-sm">
          <ShieldAlert className="h-4 w-4 shrink-0 text-destructive" />
          <span className="font-medium text-destructive">{reasonLabel}</span>
          <span className="ml-auto font-mono text-xs" style={{ color: 'hsl(var(--loss))' }}>
            {formatCurrency(status.dailyTotalPnl)}
          </span>
        </div>
      )
    }

    return (
      <div className="relative overflow-hidden rounded-lg border border-destructive/50 bg-destructive/10">
        {/* Left accent bar */}
        <div className="absolute left-0 top-0 bottom-0 w-1 bg-destructive" />
        <div className="pl-4 pr-4 py-3 space-y-1">
          <div className="flex items-center gap-2">
            <ShieldAlert className="h-4 w-4 text-destructive" />
            <span className="font-semibold text-sm text-destructive">Circuit Breaker Active</span>
          </div>
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{reasonLabel} hit</span>
            <span className="font-mono font-medium" style={{ color: 'hsl(var(--loss))' }}>
              {formatCurrency(status.dailyTotalPnl)}
            </span>
          </div>
          <p className="text-xs text-muted-foreground">New entries blocked</p>
        </div>
      </div>
    )
  }

  // State 2: Monitoring — Subtle info display (only when we have live P&L data)
  if (status && hasConfig) {
    const pnlColor =
      status.dailyTotalPnl >= 0 ? 'hsl(var(--profit))' : 'hsl(var(--loss))'
    const PnlIcon = status.dailyTotalPnl >= 0 ? TrendingUp : TrendingDown

    if (compact) {
      return (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" />
          <span>Daily P&L:</span>
          <span className="font-mono font-medium flex items-center gap-1" style={{ color: pnlColor }}>
            <PnlIcon className="h-3 w-3" />
            {formatCurrency(status.dailyTotalPnl)}
          </span>
          {status.positionCount > 0 && (
            <span className="text-xs">({status.positionCount} pos)</span>
          )}
        </div>
      )
    }

    return (
      <div className="flex items-center gap-3 text-sm text-muted-foreground">
        <ShieldCheck className="h-4 w-4 shrink-0" />
        <span>Daily P&L:</span>
        <span className="font-mono font-medium flex items-center gap-1" style={{ color: pnlColor }}>
          <PnlIcon className="h-3.5 w-3.5" />
          {formatCurrency(status.dailyTotalPnl)}
        </span>
        {status.positionCount > 0 && (
          <span className="text-xs">({status.positionCount} positions)</span>
        )}
      </div>
    )
  }

  // No live data yet but has config — show nothing (will appear once socket data arrives)
  return null
}

export { hasCircuitBreakerConfig }
