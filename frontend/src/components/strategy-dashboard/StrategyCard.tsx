import {
  Check,
  ChevronDown,
  ChevronUp,
  Copy,
  Loader2,
  Power,
  Settings,
  X,
} from 'lucide-react'
import { useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { PositionTable } from './PositionTable'
import { OrdersPanel } from './OrdersPanel'
import { TradesPanel } from './TradesPanel'
import { PnlPanel } from './PnlPanel'
import { OverviewTab } from './OverviewTab'
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface StrategyCardProps {
  strategy: DashboardStrategy
  isExpanded: boolean
  flashMap: Map<number, 'profit' | 'loss'>
  onToggleExpand: () => void
  onOpenRiskConfig: (strategyId: number) => void
  onRefresh: () => void
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

function getTopBarColor(strategy: DashboardStrategy): string {
  if (strategy.risk_monitoring === 'active') return 'border-t-green-500'
  if (strategy.risk_monitoring === 'paused') return 'border-t-amber-500'
  return 'border-t-gray-300 dark:border-t-gray-700'
}

export function StrategyCard({
  strategy,
  isExpanded,
  flashMap,
  onToggleExpand,
  onOpenRiskConfig,
  onRefresh,
}: StrategyCardProps) {
  const [toggling, setToggling] = useState(false)
  const [closingAll, setClosingAll] = useState(false)
  const [webhookCopied, setWebhookCopied] = useState(false)
  // Track which tabs have been activated for lazy loading
  const loadedTabs = useRef(new Set<string>(['positions']))
  const [activeTab, setActiveTab] = useState('positions')

  const activePositions = strategy.positions.filter(
    (p) => p.position_state === 'active' || p.position_state === 'exiting'
  )

  const handleToggleRisk = async () => {
    setToggling(true)
    try {
      if (strategy.risk_monitoring === 'active') {
        const res = await strategyDashboardApi.deactivateRisk(strategy.id)
        if (res.status === 'success') {
          showToast.success('Risk monitoring deactivated', 'strategyRisk')
        } else {
          showToast.error(res.message || 'Failed to deactivate', 'strategyRisk')
        }
      } else {
        const res = await strategyDashboardApi.activateRisk(strategy.id)
        if (res.status === 'success') {
          showToast.success('Risk monitoring activated', 'strategyRisk')
        } else {
          showToast.error(res.message || 'Failed to activate', 'strategyRisk')
        }
      }
    } catch {
      showToast.error('Failed to toggle risk monitoring', 'strategyRisk')
    } finally {
      setToggling(false)
    }
  }

  const handleCloseAll = async () => {
    setClosingAll(true)
    try {
      const res = await strategyDashboardApi.closeAllPositions(strategy.id)
      if (res.status === 'success') {
        showToast.success('Close orders placed for all positions', 'strategyRisk')
      } else {
        showToast.error(res.message || 'Failed to close all', 'strategyRisk')
      }
    } catch {
      showToast.error('Failed to close all positions', 'strategyRisk')
    } finally {
      setClosingAll(false)
    }
  }

  const handleClosePosition = async (positionId: number): Promise<void> => {
    try {
      const res = await strategyDashboardApi.closePosition(strategy.id, positionId)
      if (res.status === 'success') {
        showToast.success('Close order placed', 'strategyRisk')
      } else {
        showToast.error(res.message || 'Failed to close position', 'strategyRisk')
      }
    } catch {
      showToast.error('Failed to close position', 'strategyRisk')
    }
  }

  const webhookUrl = strategy.webhook_id
    ? `${window.location.origin}/strategy/webhook/${strategy.webhook_id}`
    : ''

  const handleCopyWebhook = (e: React.MouseEvent) => {
    e.stopPropagation()
    if (!webhookUrl) return
    navigator.clipboard.writeText(webhookUrl).then(() => {
      setWebhookCopied(true)
      showToast.success('Webhook URL copied', 'clipboard')
      setTimeout(() => setWebhookCopied(false), 2000)
    }).catch(() => {
      showToast.error('Failed to copy', 'clipboard')
    })
  }

  const handleTabChange = (value: string) => {
    setActiveTab(value)
    loadedTabs.current.add(value)
  }

  return (
    <Card className={`border-t-2 ${getTopBarColor(strategy)}`}>
      <Collapsible open={isExpanded} onOpenChange={onToggleExpand}>
        {/* Header — always visible */}
        <CollapsibleTrigger asChild>
          <div className="flex items-center justify-between p-4 cursor-pointer hover:bg-muted/50 transition-colors">
            <div className="flex items-center gap-3 min-w-0">
              {/* Status dot */}
              <div className="relative flex-shrink-0">
                <div
                  className={`h-2.5 w-2.5 rounded-full ${
                    strategy.risk_monitoring === 'active'
                      ? 'bg-green-500'
                      : strategy.risk_monitoring === 'paused'
                        ? 'bg-amber-500'
                        : 'bg-gray-400'
                  }`}
                />
                {strategy.risk_monitoring === 'active' && (
                  <div className="absolute inset-0 h-2.5 w-2.5 rounded-full bg-green-500 animate-ping opacity-75" />
                )}
              </div>

              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-lg truncate">{strategy.name}</h3>
                  {!strategy.is_active && (
                    <Badge variant="secondary" className="text-xs">Inactive</Badge>
                  )}
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>{strategy.platform}</span>
                  <span>·</span>
                  <span>{strategy.trading_mode}</span>
                  <span>·</span>
                  <span>{strategy.is_intraday ? 'Intraday' : 'Positional'}</span>
                  <span>·</span>
                  <span>{activePositions.length} positions</span>
                  <span>·</span>
                  <span>{strategy.trade_count_today} trades today</span>
                </div>
                {webhookUrl && (
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground mt-0.5">
                    <span className="font-mono truncate max-w-[300px]">{webhookUrl}</span>
                    <button
                      type="button"
                      onClick={handleCopyWebhook}
                      className="inline-flex items-center justify-center h-5 w-5 rounded hover:bg-muted flex-shrink-0"
                      title="Copy webhook URL"
                    >
                      {webhookCopied ? (
                        <Check className="h-3 w-3 text-green-500" />
                      ) : (
                        <Copy className="h-3 w-3" />
                      )}
                    </button>
                  </div>
                )}
              </div>
            </div>

            <div className="flex items-center gap-4 flex-shrink-0">
              {/* Live P&L */}
              <div className="text-right">
                <p
                  className={`text-lg font-bold font-mono tabular-nums ${
                    strategy.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
                  }`}
                >
                  {strategy.total_pnl >= 0 ? '+' : ''}
                  {currencyFormat.format(strategy.total_pnl)}
                </p>
                {strategy.win_rate !== null && (
                  <p className="text-xs text-muted-foreground">
                    WR: {strategy.win_rate.toFixed(1)}%
                    {strategy.profit_factor !== null && ` · PF: ${strategy.profit_factor.toFixed(2)}`}
                  </p>
                )}
              </div>

              {isExpanded ? (
                <ChevronUp className="h-5 w-5 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-5 w-5 text-muted-foreground" />
              )}
            </div>
          </div>
        </CollapsibleTrigger>

        {/* Expanded content — tabbed interface */}
        <CollapsibleContent>
          <CardContent className="pt-0">
            <Tabs value={activeTab} onValueChange={handleTabChange}>
              <TabsList className="grid w-full grid-cols-5">
                <TabsTrigger value="overview">Overview</TabsTrigger>
                <TabsTrigger value="positions">
                  Positions{activePositions.length > 0 ? ` (${activePositions.length})` : ''}
                </TabsTrigger>
                <TabsTrigger value="orders">
                  Orders{strategy.order_count > 0 ? ` (${strategy.order_count})` : ''}
                </TabsTrigger>
                <TabsTrigger value="trades">
                  Trades{strategy.trade_count_today > 0 ? ` (${strategy.trade_count_today})` : ''}
                </TabsTrigger>
                <TabsTrigger value="pnl">P&L</TabsTrigger>
              </TabsList>

              {/* Overview Tab */}
              <TabsContent value="overview" className="mt-4">
                {loadedTabs.current.has('overview') && (
                  <OverviewTab strategy={strategy} onRefresh={onRefresh} />
                )}
              </TabsContent>

              {/* Positions Tab */}
              <TabsContent value="positions" className="mt-4 space-y-4">
                <PositionTable
                  positions={strategy.positions}
                  flashMap={flashMap}
                  riskMonitoring={strategy.risk_monitoring}
                  onClosePosition={handleClosePosition}
                />

                {/* Action Bar */}
                <div className="flex flex-wrap items-center gap-2 pt-2 border-t">
                  {/* Close All */}
                  {activePositions.length > 0 && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="destructive" size="sm" disabled={closingAll}>
                          {closingAll ? (
                            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                          ) : (
                            <X className="h-4 w-4 mr-1" />
                          )}
                          Close All
                        </Button>
                      </AlertDialogTrigger>
                      <AlertDialogContent>
                        <AlertDialogHeader>
                          <AlertDialogTitle>Close All Positions</AlertDialogTitle>
                          <AlertDialogDescription>
                            Close all {activePositions.length} position(s) for "{strategy.name}" at MARKET?
                            This will place immediate exit orders.
                          </AlertDialogDescription>
                        </AlertDialogHeader>
                        <AlertDialogFooter>
                          <AlertDialogCancel>Cancel</AlertDialogCancel>
                          <AlertDialogAction
                            onClick={handleCloseAll}
                            className="bg-red-600 hover:bg-red-700"
                          >
                            Close All
                          </AlertDialogAction>
                        </AlertDialogFooter>
                      </AlertDialogContent>
                    </AlertDialog>
                  )}

                  <div className="flex-1" />

                  {/* Risk Config */}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => onOpenRiskConfig(strategy.id)}
                  >
                    <Settings className="h-4 w-4 mr-1" />
                    Risk Config
                  </Button>

                  {/* Activate/Deactivate */}
                  <Button
                    variant={strategy.risk_monitoring === 'active' ? 'outline' : 'default'}
                    size="sm"
                    onClick={handleToggleRisk}
                    disabled={toggling}
                  >
                    {toggling ? (
                      <Loader2 className="h-4 w-4 mr-1 animate-spin" />
                    ) : (
                      <Power className="h-4 w-4 mr-1" />
                    )}
                    {strategy.risk_monitoring === 'active' ? 'Deactivate' : 'Activate'}
                  </Button>
                </div>
              </TabsContent>

              {/* Orders Tab */}
              <TabsContent value="orders" className="mt-4">
                {loadedTabs.current.has('orders') && (
                  <OrdersPanel strategyId={strategy.id} strategyName={strategy.name} />
                )}
              </TabsContent>

              {/* Trades Tab */}
              <TabsContent value="trades" className="mt-4">
                {loadedTabs.current.has('trades') && (
                  <TradesPanel strategyId={strategy.id} strategyName={strategy.name} />
                )}
              </TabsContent>

              {/* P&L Tab */}
              <TabsContent value="pnl" className="mt-4">
                {loadedTabs.current.has('pnl') && (
                  <PnlPanel strategyId={strategy.id} strategyName={strategy.name} />
                )}
              </TabsContent>
            </Tabs>
          </CardContent>
        </CollapsibleContent>
      </Collapsible>
    </Card>
  )
}
