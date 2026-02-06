import {
  ArrowLeft,
  Loader2,
  Power,
  RefreshCw,
  Trash2,
} from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { showToast } from '@/utils/toast'
import { strategyApi } from '@/api/strategy'
import { strategyDashboardApi } from '@/api/strategy-dashboard'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
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
import type { DashboardStrategy } from '@/types/strategy-dashboard'

interface StrategyDetailHeaderProps {
  strategy: DashboardStrategy
  connectionStatus: 'connected' | 'disconnected' | 'stale'
  onBack: () => void
  onRefresh: () => void
}

const currencyFormat = new Intl.NumberFormat('en-IN', {
  style: 'currency',
  currency: 'INR',
  maximumFractionDigits: 2,
})

export function StrategyDetailHeader({
  strategy,
  connectionStatus,
  onBack,
  onRefresh,
}: StrategyDetailHeaderProps) {
  const navigate = useNavigate()
  const [toggling, setToggling] = useState(false)
  const [togglingRisk, setTogglingRisk] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [refreshing, setRefreshing] = useState(false)

  const handleToggle = async () => {
    try {
      setToggling(true)
      const response = await strategyApi.toggleStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success(
          response.data?.is_active ? 'Strategy activated' : 'Strategy deactivated',
          'strategy'
        )
        onRefresh()
      } else {
        showToast.error(response.message || 'Failed to toggle', 'strategy')
      }
    } catch {
      showToast.error('Failed to toggle strategy', 'strategy')
    } finally {
      setToggling(false)
    }
  }

  const handleToggleRisk = async () => {
    setTogglingRisk(true)
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
      onRefresh()
    } catch {
      showToast.error('Failed to toggle risk monitoring', 'strategyRisk')
    } finally {
      setTogglingRisk(false)
    }
  }

  const handleDelete = async () => {
    try {
      setDeleting(true)
      const response = await strategyApi.deleteStrategy(strategy.id)
      if (response.status === 'success') {
        showToast.success('Strategy deleted', 'strategy')
        navigate('/strategy')
      } else {
        showToast.error(response.message || 'Failed to delete', 'strategy')
      }
    } catch {
      showToast.error('Failed to delete strategy', 'strategy')
    } finally {
      setDeleting(false)
      setDeleteDialogOpen(false)
    }
  }

  const handleRefreshClick = () => {
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
    <div className="space-y-3">
      {/* Back + Title row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack} className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <div className="flex items-center gap-3">
            {/* Status dot */}
            <div className="relative flex-shrink-0">
              <div
                className={`h-3 w-3 rounded-full ${
                  strategy.risk_monitoring === 'active'
                    ? 'bg-green-500'
                    : strategy.risk_monitoring === 'paused'
                      ? 'bg-amber-500'
                      : 'bg-gray-400'
                }`}
              />
              {strategy.risk_monitoring === 'active' && (
                <div className="absolute inset-0 h-3 w-3 rounded-full bg-green-500 animate-ping opacity-75" />
              )}
            </div>
            <h1 className="text-2xl font-bold tracking-tight">{strategy.name}</h1>
          </div>
          <div className="flex items-center gap-1.5">
            <Badge variant="outline" className="text-xs">
              {strategy.platform}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {strategy.trading_mode}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {strategy.is_intraday ? 'Intraday' : 'Positional'}
            </Badge>
            {!strategy.is_active && (
              <Badge variant="secondary" className="text-xs">
                Inactive
              </Badge>
            )}
          </div>
          <div className="flex items-center gap-1.5 ml-2">
            <div className={`h-2 w-2 rounded-full ${statusDot}`} />
            <span className="text-xs text-muted-foreground capitalize">{connectionStatus}</span>
          </div>
        </div>

        <div className="flex items-center gap-4">
          {/* Live P&L */}
          <div className="text-right">
            <p
              className={`text-xl font-bold font-mono tabular-nums ${
                strategy.total_pnl >= 0 ? 'text-green-600' : 'text-red-600'
              }`}
            >
              {strategy.total_pnl >= 0 ? '+' : ''}
              {currencyFormat.format(strategy.total_pnl)}
            </p>
            {strategy.win_rate !== null && (
              <p className="text-xs text-muted-foreground">
                WR: {strategy.win_rate.toFixed(1)}%
                {strategy.profit_factor !== null &&
                  ` · PF: ${strategy.profit_factor.toFixed(2)}`}
              </p>
            )}
          </div>

          <Button variant="outline" size="sm" onClick={handleRefreshClick} disabled={refreshing}>
            <RefreshCw className={`h-4 w-4 mr-1 ${refreshing ? 'animate-spin' : ''}`} />
            Refresh
          </Button>
        </div>
      </div>

      {/* Action buttons */}
      <div className="flex items-center gap-2 pl-11">
        <Button
          variant={strategy.is_active ? 'outline' : 'default'}
          size="sm"
          onClick={handleToggle}
          disabled={toggling}
        >
          {toggling ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Power className="h-4 w-4 mr-1" />
          )}
          {strategy.is_active ? 'Deactivate Strategy' : 'Activate Strategy'}
        </Button>

        <Button
          variant={strategy.risk_monitoring === 'active' ? 'outline' : 'default'}
          size="sm"
          onClick={handleToggleRisk}
          disabled={togglingRisk}
        >
          {togglingRisk ? (
            <Loader2 className="h-4 w-4 mr-1 animate-spin" />
          ) : (
            <Power className="h-4 w-4 mr-1" />
          )}
          {strategy.risk_monitoring === 'active' ? 'Pause Risk Monitor' : 'Activate Risk Monitor'}
        </Button>

        <div className="flex-1" />

        <AlertDialog open={deleteDialogOpen} onOpenChange={setDeleteDialogOpen}>
          <AlertDialogTrigger asChild>
            <Button variant="destructive" size="sm">
              <Trash2 className="h-4 w-4 mr-1" />
              Delete
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Delete Strategy</AlertDialogTitle>
              <AlertDialogDescription>
                Are you sure you want to delete &quot;{strategy.name}&quot;? This action cannot be
                undone. All symbol mappings will also be deleted.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction
                onClick={handleDelete}
                disabled={deleting}
                className="bg-red-600 hover:bg-red-700"
              >
                {deleting ? 'Deleting...' : 'Delete Strategy'}
              </AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </div>
    </div>
  )
}
