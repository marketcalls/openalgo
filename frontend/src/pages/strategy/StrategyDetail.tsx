import { useCallback, useEffect, useMemo } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { strategyApi } from '@/api/strategy'
import { StrategyDetailHeader } from '@/components/strategy-dashboard/detail/StrategyDetailHeader'
import { WebhookConfigSection } from '@/components/strategy-dashboard/detail/WebhookConfigSection'
import { SymbolMappingsSection } from '@/components/strategy-dashboard/detail/SymbolMappingsSection'
import { RiskConfigSection } from '@/components/strategy-dashboard/detail/RiskConfigSection'
import { LivePositionsSection } from '@/components/strategy-dashboard/detail/LivePositionsSection'
import { HistoryTabs } from '@/components/strategy-dashboard/detail/HistoryTabs'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { useStrategySocket } from '@/hooks/useStrategySocket'
import { useStrategyDashboardStore } from '@/stores/strategyDashboardStore'

export default function StrategyDetail() {
  const { strategyId: idParam } = useParams<{ strategyId: string }>()
  const strategyId = Number(idParam)
  const navigate = useNavigate()

  // 1. Fetch dashboard data for live P&L + positions
  const {
    data: dashData,
    isLoading: dashLoading,
    isError: dashError,
    refetch: refetchDash,
  } = useQuery({
    queryKey: ['strategy-dashboard'],
    queryFn: strategyDashboardApi.getDashboard,
    refetchInterval: false,
  })

  // 2. Fetch full strategy detail (with mappings)
  const {
    data: strategyDetail,
    isLoading: detailLoading,
    refetch: refetchDetail,
  } = useQuery({
    queryKey: ['strategy-detail', strategyId],
    queryFn: () => strategyApi.getStrategy(strategyId),
    enabled: !!strategyId,
  })

  // 3. Initialize Zustand store with dashboard data
  const setDashboardData = useStrategyDashboardStore((s) => s.setDashboardData)
  const reset = useStrategyDashboardStore((s) => s.reset)

  useEffect(() => {
    if (dashData) {
      setDashboardData(dashData.strategies, dashData.summary)
    }
  }, [dashData, setDashboardData])

  useEffect(() => {
    return () => reset()
  }, [reset])

  // 4. Read live state from Zustand
  const strategies = useStrategyDashboardStore((s) => s.strategies)
  const flashPositions = useStrategyDashboardStore((s) => s.flashPositions)
  const connectionStatus = useStrategyDashboardStore((s) => s.connectionStatus)
  const dashStrategy = strategies.find((s) => s.id === strategyId)

  // 5. SocketIO for live updates (single strategy)
  const socketIds = useMemo(() => (strategyId ? [strategyId] : []), [strategyId])
  useStrategySocket(socketIds)

  const handleRefresh = useCallback(() => {
    refetchDash()
    refetchDetail()
  }, [refetchDash, refetchDetail])

  const handleBack = useCallback(() => {
    navigate('/strategy')
  }, [navigate])

  // Loading
  if (dashLoading || detailLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-10 w-64" />
        <div className="grid grid-cols-2 gap-4">
          <Skeleton className="h-40" />
          <Skeleton className="h-40" />
        </div>
        <Skeleton className="h-60" />
        <Skeleton className="h-60" />
      </div>
    )
  }

  // Error / not found
  if (dashError || !dashStrategy) {
    return (
      <div className="space-y-6">
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>Strategy not found</AlertTitle>
          <AlertDescription className="flex items-center gap-2">
            Could not load strategy data.
            <Button variant="outline" size="sm" onClick={handleRefresh}>
              Retry
            </Button>
            <Button variant="outline" size="sm" onClick={handleBack}>
              Back to Strategy Hub
            </Button>
          </AlertDescription>
        </Alert>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <StrategyDetailHeader
        strategy={dashStrategy}
        connectionStatus={connectionStatus}
        onBack={handleBack}
        onRefresh={handleRefresh}
      />

      <WebhookConfigSection
        strategy={strategyDetail?.strategy ?? null}
        dashStrategy={dashStrategy}
      />

      <SymbolMappingsSection
        strategyId={strategyId}
        mappings={strategyDetail?.mappings ?? []}
        onRefresh={refetchDetail}
      />

      <RiskConfigSection strategy={dashStrategy} onSaved={handleRefresh} />

      <LivePositionsSection
        strategy={dashStrategy}
        mappings={strategyDetail?.mappings ?? []}
        flashMap={flashPositions}
        onRefresh={handleRefresh}
      />

      <HistoryTabs
        strategyId={strategyId}
        strategyName={dashStrategy.name}
      />
    </div>
  )
}
