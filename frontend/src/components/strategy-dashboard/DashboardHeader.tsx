import { ActivityIcon, TrendingUpIcon, WalletIcon } from 'lucide-react'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import type { OverviewData } from '@/types/strategy-dashboard'
import { MarketStatusIndicator } from './MarketStatusIndicator'

interface DashboardHeaderProps {
  overview: OverviewData | null
  todayPnl?: number
  onCreateStrategy: () => void
}

function pnlColor(v: number) {
  return v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : 'text-muted-foreground'
}

export function DashboardHeader({ overview, todayPnl, onCreateStrategy }: DashboardHeaderProps) {
  const totalPositions = overview?.total_active_positions || 0
  const totalUnrealized = overview?.total_unrealized_pnl || 0

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold">Strategy Hub</h1>
          <MarketStatusIndicator />
        </div>
        <Button onClick={onCreateStrategy}>Create Strategy</Button>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <ActivityIcon className="h-5 w-5 text-blue-500" />
            <div>
              <p className="text-xs text-muted-foreground">Active Positions</p>
              <p className="text-lg font-semibold">{totalPositions}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <WalletIcon className="h-5 w-5 text-purple-500" />
            <div>
              <p className="text-xs text-muted-foreground">Unrealized P&L</p>
              <p className={`text-lg font-semibold ${pnlColor(totalUnrealized)}`}>
                {totalUnrealized > 0 ? '+' : ''}{totalUnrealized.toFixed(2)}
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="flex items-center gap-3 p-4">
            <TrendingUpIcon className="h-5 w-5 text-green-500" />
            <div>
              <p className="text-xs text-muted-foreground">Today&apos;s P&L</p>
              <p className={`text-lg font-semibold ${pnlColor(todayPnl || 0)}`}>
                {(todayPnl || 0) > 0 ? '+' : ''}{(todayPnl || 0).toFixed(2)}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
