import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { CreateStrategyDialog } from '@/components/strategy-dashboard/CreateStrategyDialog'
import { DashboardHeader } from '@/components/strategy-dashboard/DashboardHeader'
import { EmptyState } from '@/components/strategy-dashboard/EmptyState'
import { RiskConfigDrawer } from '@/components/strategy-dashboard/RiskConfigDrawer'
import { StrategyCard } from '@/components/strategy-dashboard/StrategyCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useStrategySocket } from '@/hooks/useStrategySocket'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'

export default function StrategyHub() {
  const [searchParams] = useSearchParams()
  const [createDialogOpen, setCreateDialogOpen] = useState(false)
  const [riskConfigStrategyId, setRiskConfigStrategyId] = useState<number | null>(null)

  // 1. Fetch initial data via TanStack Query
  const { data, isLoading, isError, refetch } = useQuery({
    queryKey: ['strategy-dashboard'],
    queryFn: strategyDashboardApi.getDashboard,
    refetchInterval: false, // SocketIO handles live updates
  })

  // 2. Initialize Zustand store with REST data
  const setDashboardData = useStrategyDashboardStore((s) => s.setDashboardData)
  const reset = useStrategyDashboardStore((s) => s.reset)

  useEffect(() => {
    if (data) {
      setDashboardData(data.strategies, data.summary)
    }
  }, [data, setDashboardData])

  // Auto-expand strategy from URL param ?expand=<id>
  const toggleExpanded = useStrategyDashboardStore((s) => s.toggleExpanded)
  const expandedStrategies = useStrategyDashboardStore((s) => s.expandedStrategies)
  useEffect(() => {
    const expandId = searchParams.get('expand')
    if (expandId && data) {
      const id = Number(expandId)
      if (id && !expandedStrategies.has(id)) {
        toggleExpanded(id)
      }
    }
    // Only run once when data first loads
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data])

  // Cleanup store on unmount
  useEffect(() => {
    return () => reset()
  }, [reset])

  // 3. Read live state from Zustand
  const strategies = useStrategyDashboardStore((s) => s.strategies)
  const summary = useStrategyDashboardStore((s) => s.summary)
  const connectionStatus = useStrategyDashboardStore((s) => s.connectionStatus)
  const flashPositions = useStrategyDashboardStore((s) => s.flashPositions)

  // 4. Connect SocketIO to strategy rooms
  const strategyIds = useMemo(() => strategies.map((s) => s.id), [strategies])
  useStrategySocket(strategyIds)

  const handleRefresh = useCallback(() => {
    refetch()
  }, [refetch])

  const handleRiskConfigSaved = useCallback(() => {
    refetch()
  }, [refetch])

  const handleCreated = useCallback((_strategyId: number) => {
    refetch()
  }, [refetch])

  const riskConfigStrategy = riskConfigStrategyId
    ? strategies.find((s) => s.id === riskConfigStrategyId)
    : null

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          <Skeleton className="h-8 w-64" />
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </div>
        </div>
        <div className="space-y-4">
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
          <Skeleton className="h-28" />
        </div>
      </div>
    )
  }

  // Error state
  if (isError) {
    return (
      <div className="space-y-6">
        <h1 className="text-2xl font-bold tracking-tight">Strategy Hub</h1>
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Failed to load dashboard</AlertTitle>
          <AlertDescription className="flex items-center gap-2">
            Could not fetch strategy data. Check your connection and try again.
            <Button variant="outline" size="sm" onClick={handleRefresh}>
              Retry
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <DashboardHeader
        summary={summary}
        connectionStatus={connectionStatus}
        onRefresh={handleRefresh}
        onCreateStrategy={() => setCreateDialogOpen(true)}
      />

      {strategies.length === 0 ? (
        <EmptyState variant="no-strategies" />
      ) : (
        <div className="space-y-4">
          {strategies.map((strategy) => (
            <StrategyCard
              key={strategy.id}
              strategy={strategy}
              isExpanded={expandedStrategies.has(strategy.id)}
              flashMap={flashPositions}
              onToggleExpand={() => toggleExpanded(strategy.id)}
              onOpenRiskConfig={(id) => setRiskConfigStrategyId(id)}
              onRefresh={handleRefresh}
            />
          ))}
        </div>
      )}

      {/* Risk Config Drawer — page level */}
      {riskConfigStrategy && (
        <RiskConfigDrawer
          open={true}
          onOpenChange={(open) => !open && setRiskConfigStrategyId(null)}
          strategy={riskConfigStrategy}
          onSaved={handleRiskConfigSaved}
        />
      )}

      {/* Create Strategy Dialog */}
      <CreateStrategyDialog
        open={createDialogOpen}
        onOpenChange={setCreateDialogOpen}
        onCreated={handleCreated}
      />
    </div>
  )
}
