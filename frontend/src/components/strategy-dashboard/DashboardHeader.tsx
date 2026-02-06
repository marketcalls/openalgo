import { Plus, RefreshCw } from 'lucide-react'
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

      {/* Compact stat strip */}
      <Card>
        <CardContent className="py-3 px-4">
          <div className="flex items-center divide-x">
            <StatItem label="Active" value={summary.active_strategies} />
            <StatItem label="Paused" value={summary.paused_strategies} />
            <StatItem label="Positions" value={summary.open_positions} />
            <div className="flex-1 px-4">
              <p className="text-xs text-muted-foreground">Total P&L</p>
              <p
                className={`text-lg font-bold font-mono tabular-nums ${
                  summary.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
                }`}
              >
                {summary.total_pnl >= 0 ? '+' : ''}
                {currencyFormat.format(summary.total_pnl)}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}

function StatItem({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex-1 px-4 first:pl-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-lg font-bold tabular-nums">{value}</p>
    </div>
  )
}
