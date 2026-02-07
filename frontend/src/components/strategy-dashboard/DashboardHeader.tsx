import { Activity, IndianRupee, Plus, RefreshCw, ShieldCheck, TrendingUp } from 'lucide-react'
import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
    setTimeout(() => setRefreshing(false), 500)
  }

  const statusDot =
    connectionStatus === 'connected'
      ? 'bg-green-500'
      : connectionStatus === 'stale'
        ? 'bg-amber-500'
        : 'bg-red-500'

  return (
    <div className="space-y-6">
      {/* Header row — matches Python page layout */}
      <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-bold tracking-tight">Strategy Hub</h1>
            <div className="flex items-center gap-1.5">
              <div className={`h-2 w-2 rounded-full ${statusDot}`} />
              <span className="text-xs text-muted-foreground capitalize">
                {connectionStatus}
              </span>
            </div>
          </div>
          <p className="text-muted-foreground">Manage your webhook trading strategies</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-2 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
          {onCreateStrategy && (
            <Button onClick={onCreateStrategy}>
              <Plus className="h-4 w-4 mr-2" />
              New Strategy
            </Button>
          )}
        </div>
      </div>

      {/* Stats grid — 4 separate cards like Python page */}
      <div className="grid gap-4 grid-cols-2 md:grid-cols-4">
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Active</p>
                <p className="text-2xl font-bold text-green-500">{summary.active_strategies}</p>
              </div>
              <ShieldCheck className="h-8 w-8 text-green-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Paused</p>
                <p className="text-2xl font-bold text-amber-500">{summary.paused_strategies}</p>
              </div>
              <Activity className="h-8 w-8 text-amber-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Positions</p>
                <p className="text-2xl font-bold text-blue-500">{summary.open_positions}</p>
              </div>
              <TrendingUp className="h-8 w-8 text-blue-500" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="pt-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm text-muted-foreground">Total P&L</p>
                <p
                  className={`text-2xl font-bold font-mono tabular-nums ${
                    summary.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  {summary.total_pnl >= 0 ? '+' : ''}
                  {currencyFormat.format(summary.total_pnl)}
                </p>
              </div>
              <IndianRupee
                className={`h-8 w-8 ${summary.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}
              />
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
