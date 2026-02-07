import {
  ArrowLeft,
  Loader2,
  Pause,
  Power,
  PowerOff,
  RefreshCw,
  Shield,
  ShieldOff,
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
          showToast.success('Risk monitoring paused', 'strategyRisk')
        } else {
          showToast.error(res.message || 'Failed to pause', 'strategyRisk')
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

  return (
    <div className="space-y-4">
      {/* Row 1: Back + Title + Info badges + P&L */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" onClick={onBack} className="h-8 w-8">
            <ArrowLeft className="h-4 w-4" />
          </Button>
          <h1 className="text-2xl font-bold tracking-tight">{strategy.name}</h1>
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

      {/* Row 2: Toggle buttons + Delete */}
      <div className="flex items-center gap-3 pl-11">
        {/* Strategy toggle — single button that shows state + acts as toggle */}
        <Button
          variant="outline"
          size="sm"
          onClick={handleToggle}
          disabled={toggling}
          className={
            strategy.is_active
              ? 'border-green-500 text-green-600 hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-950'
              : ''
          }
        >
          {toggling ? (
            <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
          ) : strategy.is_active ? (
            <Power className="h-4 w-4 mr-1.5" />
          ) : (
            <PowerOff className="h-4 w-4 mr-1.5" />
          )}
          {strategy.is_active ? 'Active' : 'Inactive'}
        </Button>

        {/* Risk monitor toggle — single button that shows state + acts as toggle */}
        <Button
          variant="outline"
          size="sm"
          onClick={handleToggleRisk}
          disabled={togglingRisk}
          className={
            strategy.risk_monitoring === 'active'
              ? 'border-green-500 text-green-600 hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-950'
              : strategy.risk_monitoring === 'paused'
                ? 'border-amber-500 text-amber-600 hover:bg-amber-50 dark:text-amber-400 dark:hover:bg-amber-950'
                : ''
          }
        >
          {togglingRisk ? (
            <Loader2 className="h-4 w-4 mr-1.5 animate-spin" />
          ) : strategy.risk_monitoring === 'active' ? (
            <Shield className="h-4 w-4 mr-1.5" />
          ) : strategy.risk_monitoring === 'paused' ? (
            <Pause className="h-4 w-4 mr-1.5" />
          ) : (
            <ShieldOff className="h-4 w-4 mr-1.5" />
          )}
          {strategy.risk_monitoring === 'active'
            ? 'Risk On'
            : strategy.risk_monitoring === 'paused'
              ? 'Risk Paused'
              : 'Risk Off'}
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
