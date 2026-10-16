// frontend/src/components/pnl/PnlSummary.tsx
/**
 * The headline numbers of the P&L page (fork-only): Net P&L split into realized
 * and unrealized, then the statistics. Always above the tabs, and a function of
 * the model only, so they follow the filters and the P&L type.
 */
import { useMemo } from 'react'
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { cumulative, currentDrawdown, drawdown, stats } from '@/lib/pnlCurve'
import type { PnlModel } from '@/lib/pnlModel'
import { cn } from '@/lib/utils'

function percent(value: number | null): string {
  return value === null ? '-' : `${(value * 100).toFixed(0)}%`
}

function ratio(value: number | null): string {
  return value === null ? '-' : value.toFixed(2)
}

const pnlClass = (value: number) => (value >= 0 ? 'text-green-600' : 'text-red-600')

interface Props {
  model: PnlModel
  formatCurrency: (value: number) => string
  pnlType: 'realized' | 'unrealized' | 'combined'
}

export function PnlSummary({ model, formatCurrency, pnlType }: Props) {
  const { series } = model
  const summary = useMemo(() => stats(series.dates, series.total), [series])
  const maxDd = useMemo(() => drawdown(series.dates, cumulative(series.total)).max, [series])
  const nowDd = useMemo(() => currentDrawdown(series.dates, cumulative(series.total)), [series])

  // The headline follows the chosen P&L type: realized booked, the open level,
  // or both. Without an equity curve the open level is the broker's live figure.
  const { realized, unrealized } = model.split
  const net =
    pnlType === 'realized'
      ? realized
      : pnlType === 'unrealized'
        ? (unrealized ?? 0)
        : realized + (unrealized ?? 0)
  const netLabel =
    pnlType === 'realized'
      ? 'Net realized P&L'
      : pnlType === 'unrealized'
        ? 'Unrealized P&L'
        : 'Net P&L (realized + unrealized)'

  return (
    <div className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>{netLabel}</CardDescription>
            <CardTitle className={cn('text-3xl', pnlClass(net))}>{formatCurrency(net)}</CardTitle>
            <div className="mt-1 flex flex-wrap gap-x-6 gap-y-1 text-sm">
              <span>
                <span className="text-muted-foreground">Realized </span>
                <span className={cn('font-medium', pnlClass(realized))}>
                  {formatCurrency(realized)}
                </span>
              </span>
              <span>
                <span className="text-muted-foreground">Unrealized </span>
                {unrealized === null ? (
                  <span className="text-muted-foreground">not available</span>
                ) : (
                  <span className={cn('font-medium', pnlClass(unrealized))}>
                    {formatCurrency(unrealized)}
                  </span>
                )}
              </span>
            </div>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Max drawdown</CardDescription>
            <CardTitle className="text-3xl">{formatCurrency(maxDd.depth)}</CardTitle>
            <p className="text-xs text-muted-foreground">
              {maxDd.troughDate
                ? `${maxDd.peakDate ?? 'start'} to ${maxDd.troughDate}; ${
                    maxDd.recoveryDate
                      ? `recovered ${maxDd.recoveryDate} (${maxDd.days} days)`
                      : `not recovered (${maxDd.days} days so far)`
                  }`
                : 'The curve never fell below a previous high'}
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Current drawdown</CardDescription>
            <CardTitle className={cn('text-3xl', nowDd.atHigh ? 'text-green-600' : 'text-red-600')}>
              {formatCurrency(nowDd.depth)}
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              {nowDd.atHigh
                ? 'At a new high'
                : `Below the ${formatCurrency(nowDd.peakValue)} peak${
                    nowDd.peakDate ? ` of ${nowDd.peakDate}` : ''
                  }, ${nowDd.daysSincePeak} day${nowDd.daysSincePeak === 1 ? '' : 's'} ago`}
            </p>
          </CardHeader>
        </Card>
      </div>
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Win days</CardDescription>
            <CardTitle className="text-2xl">{percent(summary.winRate)}</CardTitle>
            <p className="text-xs text-muted-foreground">
              {summary.winDays} up, {summary.lossDays} down, of {summary.activeDays} days
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Profit factor</CardDescription>
            <CardTitle className="text-2xl">{ratio(summary.profitFactor)}</CardTitle>
            <p className="text-xs text-muted-foreground">Winning days over losing days</p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Average win / loss day</CardDescription>
            <CardTitle className="text-lg">
              <span className="text-green-600">
                {summary.avgWinDay === null ? '-' : formatCurrency(summary.avgWinDay)}
              </span>
              {' / '}
              <span className="text-red-600">
                {summary.avgLossDay === null ? '-' : formatCurrency(summary.avgLossDay)}
              </span>
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              Longest streak {summary.longestWinStreak} up / {summary.longestLossStreak} down
            </p>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardDescription>Best / worst day</CardDescription>
            <CardTitle className="text-lg">
              <span className="text-green-600">
                {summary.bestDay ? formatCurrency(summary.bestDay.value) : '-'}
              </span>
              {' / '}
              <span className="text-red-600">
                {summary.worstDay ? formatCurrency(summary.worstDay.value) : '-'}
              </span>
            </CardTitle>
            <p className="text-xs text-muted-foreground">
              {summary.bestDay?.date} / {summary.worstDay?.date}
            </p>
          </CardHeader>
        </Card>
      </div>
    </div>
  )
}
