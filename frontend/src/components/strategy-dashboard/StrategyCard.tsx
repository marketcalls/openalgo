import { useCallback, useEffect, useState } from 'react'
import {
  ChevronDownIcon,
  ChevronUpIcon,
  PowerIcon,
  XSquareIcon,
  ShieldIcon,
  ShieldOffIcon,
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { dashboardApi } from '@/api/strategy-dashboard'
import { strategyApi } from '@/api/strategy'
import { showToast } from '@/utils/toast'
import type { Strategy, StrategySymbolMapping } from '@/types/strategy'
import type { DashboardPosition, RiskConfig } from '@/types/strategy-dashboard'
import { OverviewTab } from './OverviewTab'
import { PositionTable } from './PositionTable'
import { OrdersPanel } from './OrdersPanel'
import { TradesPanel } from './TradesPanel'
import { PnlPanel } from './PnlPanel'
import { RiskMonitorTab } from './RiskMonitorTab'
import { RiskConfigDrawer } from './RiskConfigDrawer'

interface StrategyCardProps {
  strategy: Strategy
  strategyType: string
  dashboardData?: {
    active_positions: number
    total_unrealized_pnl: number
  }
}

function pnlColor(v: number) {
  return v > 0 ? 'text-green-600' : v < 0 ? 'text-red-600' : 'text-muted-foreground'
}

export function StrategyCard({ strategy, strategyType, dashboardData }: StrategyCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [positions, setPositions] = useState<DashboardPosition[]>([])
  const [mappings, setMappings] = useState<StrategySymbolMapping[]>([])
  const [riskConfig, setRiskConfig] = useState<RiskConfig | null>(null)
  const [riskDrawerOpen, setRiskDrawerOpen] = useState(false)
  const [isActive, setIsActive] = useState(strategy.is_active)
  const [riskMonitoring, setRiskMonitoring] = useState<'active' | 'paused'>('active')

  const loadPositions = useCallback(() => {
    dashboardApi
      .getPositions(strategy.id, strategyType)
      .then(setPositions)
      .catch(() => {})
  }, [strategy.id, strategyType])

  useEffect(() => {
    if (expanded) {
      loadPositions()
      strategyApi
        .getStrategy(strategy.id)
        .then((data) => setMappings(data.mappings || []))
        .catch(() => {})
      dashboardApi
        .getRiskConfig(strategy.id, strategyType)
        .then((config) => {
          setRiskConfig(config)
          setRiskMonitoring(config.risk_monitoring)
        })
        .catch(() => {})
    }
  }, [expanded, strategy.id, strategyType, loadPositions])

  const handleToggle = async () => {
    try {
      const result = await strategyApi.toggleStrategy(strategy.id)
      setIsActive(result.data?.is_active ?? !isActive)
      showToast.success(result.data?.is_active ? 'Strategy activated' : 'Strategy deactivated')
    } catch {
      showToast.error('Failed to toggle strategy')
    }
  }

  const handleCloseAll = async () => {
    try {
      const result = await dashboardApi.closeAllPositions(strategy.id, strategyType)
      showToast.success(`Closed ${result.closed}/${result.total} positions`)
      loadPositions()
    } catch {
      showToast.error('Failed to close positions')
    }
  }

  const handleToggleRisk = async () => {
    try {
      if (riskMonitoring === 'active') {
        await dashboardApi.deactivateRisk(strategy.id, strategyType)
        setRiskMonitoring('paused')
        showToast.success('Risk monitoring paused')
      } else {
        await dashboardApi.activateRisk(strategy.id, strategyType)
        setRiskMonitoring('active')
        showToast.success('Risk monitoring activated')
      }
    } catch {
      showToast.error('Failed to toggle risk monitoring')
    }
  }

  const activeCount = dashboardData?.active_positions || positions.filter((p) => p.position_state === 'active').length
  const unrealizedPnl = dashboardData?.total_unrealized_pnl || 0

  return (
    <Card>
      {/* Card Header */}
      <CardHeader
        className="cursor-pointer py-3 px-4"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-semibold">{strategy.name}</h3>
                <Badge variant="outline" className="text-[10px] capitalize">
                  {strategy.platform}
                </Badge>
                {strategyType === 'chartink' && (
                  <Badge variant="secondary" className="text-[10px]">
                    Chartink
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-3 mt-0.5 text-xs text-muted-foreground">
                <span>{activeCount} position{activeCount !== 1 ? 's' : ''}</span>
                {unrealizedPnl !== 0 && (
                  <span className={pnlColor(unrealizedPnl)}>
                    {unrealizedPnl > 0 ? '+' : ''}{unrealizedPnl.toFixed(2)}
                  </span>
                )}
              </div>
            </div>
          </div>
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            {/* Risk monitoring toggle */}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handleToggleRisk}
              title={riskMonitoring === 'active' ? 'Pause risk monitoring' : 'Activate risk monitoring'}
            >
              {riskMonitoring === 'active' ? (
                <ShieldIcon className="h-4 w-4 text-green-600" />
              ) : (
                <ShieldOffIcon className="h-4 w-4 text-amber-500" />
              )}
            </Button>
            {/* Active toggle */}
            <Button
              variant="ghost"
              size="icon"
              className="h-7 w-7"
              onClick={handleToggle}
              title={isActive ? 'Deactivate strategy' : 'Activate strategy'}
            >
              <PowerIcon className={`h-4 w-4 ${isActive ? 'text-green-600' : 'text-muted-foreground'}`} />
            </Button>
            {/* Close all positions */}
            {activeCount > 0 && (
              <Button
                variant="ghost"
                size="icon"
                className="h-7 w-7"
                onClick={handleCloseAll}
                title="Close all positions"
              >
                <XSquareIcon className="h-4 w-4 text-red-500" />
              </Button>
            )}
            {/* Expand */}
            <div className="cursor-pointer" onClick={() => setExpanded(!expanded)}>
              {expanded ? (
                <ChevronUpIcon className="h-4 w-4" />
              ) : (
                <ChevronDownIcon className="h-4 w-4" />
              )}
            </div>
          </div>
        </div>
      </CardHeader>

      {/* Expanded Content */}
      {expanded && (
        <CardContent className="pt-0 px-4 pb-4">
          <Tabs defaultValue="positions" className="w-full">
            <TabsList className="w-full justify-start h-8">
              <TabsTrigger value="overview" className="text-xs">Overview</TabsTrigger>
              <TabsTrigger value="positions" className="text-xs">
                Positions {activeCount > 0 && `(${activeCount})`}
              </TabsTrigger>
              <TabsTrigger value="orders" className="text-xs">Orders</TabsTrigger>
              <TabsTrigger value="trades" className="text-xs">Trades</TabsTrigger>
              <TabsTrigger value="pnl" className="text-xs">P&L</TabsTrigger>
              <TabsTrigger value="risk" className="text-xs">Risk</TabsTrigger>
            </TabsList>
            <TabsContent value="overview" className="mt-3">
              <OverviewTab
                strategy={strategy}
                mappings={mappings}
                strategyType={strategyType}
                riskConfig={riskConfig}
                onOpenRiskConfig={() => setRiskDrawerOpen(true)}
              />
            </TabsContent>
            <TabsContent value="positions" className="mt-3">
              <PositionTable
                strategyId={strategy.id}
                strategyType={strategyType}
                positions={positions}
                onRefresh={loadPositions}
              />
            </TabsContent>
            <TabsContent value="orders" className="mt-3">
              <OrdersPanel strategyId={strategy.id} strategyType={strategyType} />
            </TabsContent>
            <TabsContent value="trades" className="mt-3">
              <TradesPanel strategyId={strategy.id} strategyType={strategyType} />
            </TabsContent>
            <TabsContent value="pnl" className="mt-3">
              <PnlPanel strategyId={strategy.id} strategyType={strategyType} />
            </TabsContent>
            <TabsContent value="risk" className="mt-3">
              <RiskMonitorTab
                strategyId={strategy.id}
                strategyType={strategyType}
                positions={positions}
              />
            </TabsContent>
          </Tabs>
        </CardContent>
      )}

      {/* Risk Config Drawer */}
      <RiskConfigDrawer
        open={riskDrawerOpen}
        onClose={() => setRiskDrawerOpen(false)}
        strategyId={strategy.id}
        strategyType={strategyType}
      />
    </Card>
  )
}
