import { Activity, BarChart3, Pause, Plus, RefreshCw, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import type { DashboardSummary } from '@/types/strategy-dashboard'

interface DashboardHeaderProps {
  summary: DashboardSummary
  connectionStatus: 'connected' | 'disconnected' | 'stale'
  onRefresh: () => void
  onCreateStrategy?: () => void
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

export function DashboardHeader({
  summary,
  connectionStatus,
  onRefresh,
  onCreateStrategy,
}: DashboardHeaderProps) {
  const [refreshing, setRefreshing] = useState(false)

  const handleRefresh = async () => {
    setRefreshing(true)
    onRefresh()
    // Spin for at least 500ms for visual feedback
    setTimeout(() => setRefreshing(false), 500)
  }

  const statusDot = connectionStatus === 'connected'
    ? 'bg-green-500'
    : connectionStatus === 'stale'
      ? 'bg-amber-500'
      : 'bg-red-500'

  return (
    <div className="space-y-4">
      {/* Title row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold tracking-tight">Strategy Hub</h1>
          <div className="flex items-center gap-1.5">
            <div className={`h-2 w-2 rounded-full ${statusDot}`} />
            <span className="text-xs text-muted-foreground capitalize">
              {connectionStatus}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {onCreateStrategy && (
            <Button onClick={onCreateStrategy}>
              <Plus className="h-4 w-4 mr-1" />
              New Strategy
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-1 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Activity className="h-3.5 w-3.5" />
              Active
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CardTitle className="text-2xl tabular-nums">
              {summary.active_strategies}
            </CardTitle>
            <p className="text-xs text-muted-foreground">strategies</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <Pause className="h-3.5 w-3.5" />
              Paused
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CardTitle className="text-2xl tabular-nums">
              {summary.paused_strategies}
            </CardTitle>
            <p className="text-xs text-muted-foreground">strategies</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <BarChart3 className="h-3.5 w-3.5" />
              Open
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CardTitle className="text-2xl tabular-nums">
              {summary.open_positions}
            </CardTitle>
            <p className="text-xs text-muted-foreground">positions</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-1.5">
              <TrendingUp className="h-3.5 w-3.5" />
              Total P&L
            </CardDescription>
          </CardHeader>
          <CardContent>
            <CardTitle
              className={`text-2xl font-mono tabular-nums ${
                summary.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {summary.total_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(summary.total_pnl)}
            </CardTitle>
            <p className="text-xs text-muted-foreground">all strategies</p>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
