import { useEffect, useState } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { dashboardApi } from '@/api/strategy-dashboard'
import type { DailyPnL, DashboardSummary } from '@/types/strategy-dashboard'
import { MetricsGrid } from './MetricsGrid'
import { EquityCurveChart } from './EquityCurveChart'
import { ExitBreakdownTable } from './ExitBreakdownTable'

interface PnlPanelProps {
  strategyId: number
  strategyType: string
}

export function PnlPanel({ strategyId, strategyType }: PnlPanelProps) {
  const [summary, setSummary] = useState<DashboardSummary | null>(null)
  const [daily, setDaily] = useState<DailyPnL[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    dashboardApi
      .getPnL(strategyId, strategyType)
      .then((data) => {
        if (!cancelled) {
          setSummary(data.summary)
          setDaily(data.daily)
        }
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [strategyId, strategyType])

  if (loading) {
    return <div className="py-8 text-center text-sm text-muted-foreground">Loading P&L data...</div>
  }

  if (!summary) {
    return <div className="py-8 text-center text-sm text-muted-foreground">No P&L data available</div>
  }

  return (
    <div className="space-y-4">
      <MetricsGrid summary={summary} />

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Equity Curve</CardTitle>
        </CardHeader>
        <CardContent>
          <EquityCurveChart data={daily} />
        </CardContent>
      </Card>

      {Object.keys(summary.exit_breakdown).length > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Exit Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            <ExitBreakdownTable breakdown={summary.exit_breakdown} />
          </CardContent>
        </Card>
      )}
    </div>
  )
}
