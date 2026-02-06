import { ShieldAlert, TrendingDown, TrendingUp } from 'lucide-react'
import { useEffect, useState } from 'react'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import { EquityCurveChart } from './EquityCurveChart'
import { ExitBreakdownTable } from './ExitBreakdownTable'
import { MetricsGrid } from './MetricsGrid'
import type { PnLResponse } from '@/types/strategy-dashboard'

interface PnLDrawerProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  strategyId: number
  strategyName: string
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

export function PnLDrawer({
  open,
  onOpenChange,
  strategyId,
  strategyName,
}: PnLDrawerProps) {
  const [data, setData] = useState<PnLResponse | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (!open) return
    const fetchPnL = async () => {
      setLoading(true)
      try {
        const result = await strategyDashboardApi.getPnL(strategyId)
        setData(result)
      } catch {
        setData(null)
      } finally {
        setLoading(false)
      }
    }
    fetchPnL()
  }, [open, strategyId])

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full sm:max-w-[700px] lg:max-w-[800px] overflow-y-auto">
        <SheetHeader>
          <SheetTitle className="flex items-center gap-2">
            <ShieldAlert className="h-5 w-5" />
            P&L Analytics — {strategyName}
          </SheetTitle>
          <SheetDescription>
            Performance metrics and trade analytics
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-6">
          {loading ? (
            <div className="space-y-4">
              <div className="grid grid-cols-3 gap-3">
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
                <Skeleton className="h-20" />
              </div>
              <Skeleton className="h-[250px]" />
              <Skeleton className="h-40" />
            </div>
          ) : !data ? (
            <div className="flex flex-col items-center justify-center py-12 text-muted-foreground">
              <ShieldAlert className="h-10 w-10 mb-3 opacity-40" />
              <p className="text-sm">Start trading to see analytics</p>
            </div>
          ) : (
            <>
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
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}
