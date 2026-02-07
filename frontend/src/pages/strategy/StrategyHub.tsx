import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { CreateStrategyDialog } from '@/components/strategy-dashboard/CreateStrategyDialog'
import { DashboardHeader } from '@/components/strategy-dashboard/DashboardHeader'
import { EmptyState } from '@/components/strategy-dashboard/EmptyState'
import { StrategyListCard } from '@/components/strategy-dashboard/StrategyListCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useStrategySocket } from '@/hooks/useStrategySocket'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'

export default function StrategyHub() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const [createDialogOpen, setCreateDialogOpen] = useState(false)

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

  // Handle ?expand=<id> — redirect to detail page
  useEffect(() => {
    const expandId = searchParams.get('expand')
    if (expandId && data) {
      const id = Number(expandId)
      if (id) {
        navigate(`/strategy/${id}`, { replace: true })
      }
    }
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

  // 4. Connect SocketIO to strategy rooms (for live P&L on list page)
  const strategyIds = useMemo(() => strategies.map((s) => s.id), [strategies])
  useStrategySocket(strategyIds)

  const handleRefresh = useCallback(() => {
    refetch()
  }, [refetch])

  const handleCreated = useCallback(
    (strategyId: number) => {
      navigate(`/strategy/${strategyId}`)
    },
    [navigate]
  )

  // Loading state
  if (isLoading) {
    return (
      <div className="space-y-6">
        <div className="space-y-4">
          <Skeleton className="h-8 w-64" />
          <Skeleton className="h-16 w-full" />
        </div>
        <div className="space-y-3">
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
          <Skeleton className="h-20" />
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
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 items-start">
          {strategies.map((strategy) => (
            <StrategyListCard key={strategy.id} strategy={strategy} />
          ))}
        </div>
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
