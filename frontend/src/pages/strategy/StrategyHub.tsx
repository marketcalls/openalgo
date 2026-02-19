import { useEffect, useState } from 'react'
import { dashboardApi } from '@/api/strategy-dashboard'
import { strategyApi } from '@/api/strategy'
import { useStrategySocket } from '@/hooks/useStrategySocket'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'
import type { Strategy } from '@/types/strategy'
import type { OverviewData } from '@/types/strategy-dashboard'
import { DashboardHeader } from '@/components/strategy-dashboard/DashboardHeader'
import { StrategyCard } from '@/components/strategy-dashboard/StrategyCard'
import { EmptyState } from '@/components/strategy-dashboard/EmptyState'
import { CreateStrategyDialog } from '@/components/strategy-dashboard/CreateStrategyDialog'

export default function StrategyHub() {
  const [overview, setOverview] = useState<OverviewData | null>(null)
  const [strategies, setStrategies] = useState<Strategy[]>([])
  const [loading, setLoading] = useState(true)
  const [createOpen, setCreateOpen] = useState(false)

  const setDashboardData = useStrategyDashboardStore((s) => s.setDashboardData)

  // Initialize socket for real-time updates
  useStrategySocket()

  useEffect(() => {
    let cancelled = false

    const loadData = async () => {
      try {
        const [overviewData, strategyList] = await Promise.all([
          dashboardApi.getDashboard().catch(() => null),
          strategyApi.getStrategies().catch(() => []),
        ])

        if (!cancelled) {
          setOverview(overviewData)
          if (overviewData) setDashboardData(overviewData)
          setStrategies(strategyList)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadData()

    return () => {
      cancelled = true
    }
  }, [setDashboardData])

  // Build a lookup of dashboard data per strategy
  const dashboardLookup = new Map<number, { active_positions: number; total_unrealized_pnl: number }>()
  if (overview) {
    for (const s of overview.strategies) {
      dashboardLookup.set(s.strategy_id, {
        active_positions: s.active_positions,
        total_unrealized_pnl: s.total_unrealized_pnl,
      })
    }
  }

  if (loading) {
    return (
      <div className="p-6">
        <div className="animate-pulse space-y-4">
          <div className="h-8 w-48 bg-muted rounded" />
          <div className="grid grid-cols-3 gap-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-20 bg-muted rounded" />
            ))}
          </div>
          <div className="space-y-3">
            {[1, 2].map((i) => (
              <div key={i} className="h-16 bg-muted rounded" />
            ))}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-4">
      <DashboardHeader
        overview={overview}
        onCreateStrategy={() => setCreateOpen(true)}
      />

      {strategies.length === 0 ? (
        <EmptyState
          title="No strategies"
          description="Create your first strategy to get started with position tracking and risk management."
        />
      ) : (
        <div className="space-y-3">
          {strategies.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              strategyType="webhook"
              dashboardData={dashboardLookup.get(strategy.id)}
            />
          ))}
        </div>
      )}

      <CreateStrategyDialog open={createOpen} onClose={() => setCreateOpen(false)} />
    </div>
  )
}
