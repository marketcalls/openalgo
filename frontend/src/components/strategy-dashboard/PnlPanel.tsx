import { RefreshCw, ShieldAlert, TrendingDown, TrendingUp } from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { EquityCurveChart } from './EquityCurveChart'
import { ExitBreakdownTable } from './ExitBreakdownTable'
import { MetricsGrid } from './MetricsGrid'

interface PnlPanelProps {
  strategyId: number
  strategyName: string
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

export function PnlPanel({ strategyId, strategyName }: PnlPanelProps) {
  const { data, isLoading, refetch } = useQuery({
    queryKey: ['strategy-pnl', strategyId],
    queryFn: () => strategyDashboardApi.getPnL(strategyId),
  })

  if (isLoading) {
    return (
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
        </div>
        <Skeleton className="h-[250px]" />
        <Skeleton className="h-40" />
      </div>
    )
  }

  if (!data) {
    return (
      <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
        <ShieldAlert className="h-10 w-10 mb-3 opacity-40" />
        <p className="text-sm">Start trading {strategyName} to see analytics</p>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      {/* Refresh button */}
      <div className="flex justify-end">
        <Button variant="ghost" size="icon" className="h-7 w-7" onClick={() => refetch()}>
          <RefreshCw className="h-3.5 w-3.5" />
        </Button>
      </div>

      {/* P&L Summary Cards */}
      <div className="grid grid-cols-3 gap-3">
        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3" />
              Total P&L
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={`text-lg font-bold font-mono tabular-nums ${
                data.pnl.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {data.pnl.total_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(data.pnl.total_pnl)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground">Realized</CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={`text-lg font-bold font-mono tabular-nums ${
                data.pnl.realized_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {data.pnl.realized_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(data.pnl.realized_pnl)}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-1">
            <CardTitle className="text-xs text-muted-foreground flex items-center gap-1">
              {data.pnl.unrealized_pnl >= 0 ? (
                <TrendingUp className="h-3 w-3 text-green-500" />
              ) : (
                <TrendingDown className="h-3 w-3 text-red-500" />
              )}
              Unrealized
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p
              className={`text-lg font-bold font-mono tabular-nums ${
                data.pnl.unrealized_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {data.pnl.unrealized_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(data.pnl.unrealized_pnl)}
            </p>
          </CardContent>
        </Card>
      </div>

      {/* Equity Curve */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent>
          <EquityCurveChart data={data.daily_pnl} />
        </CardContent>
      </Card>

      {/* Metrics Grid */}
      <MetricsGrid metrics={data.risk_metrics} totalPnl={data.pnl.total_pnl} />

      {/* Exit Breakdown */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Exit Breakdown</CardTitle>
        </CardHeader>
        <CardContent>
          <ExitBreakdownTable data={data.exit_breakdown} />
        </CardContent>
      </Card>
    </div>
  )
}
