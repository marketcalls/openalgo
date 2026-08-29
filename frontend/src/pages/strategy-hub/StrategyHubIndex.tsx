import { Play, Radio, RefreshCw, Square } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { type StrategyHubEntry, type StrategyHubStatus, strategyHubApi } from '@/api/strategy-hub'
import { useSocketContext } from '@/components/socket/SocketProvider'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { showToast } from '@/utils/toast'

const STATUS_BADGE_VARIANT: Record<StrategyHubStatus, 'default' | 'secondary' | 'destructive'> = {
  online: 'default',
  stale: 'secondary',
  offline: 'destructive',
}

const STATUS_LABEL: Record<StrategyHubStatus, string> = {
  online: 'Online',
  stale: 'Stale',
  offline: 'Offline',
}

// Known metric keys emitted by lean_trading_engine's runner — rendered with
// friendly labels; any other key in the metrics payload falls back to a
// generic "key: value" row so custom strategy metrics still show up.
const METRIC_LABELS: Record<string, string> = {
  active_trades: 'Active trades',
  portfolio_value: 'Portfolio value',
  daily_pnl: 'Daily P&L',
  risk_halted: 'Risk halted',
}

function formatMetricValue(key: string, value: unknown): string {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  if (typeof value === 'number') {
    if (key === 'portfolio_value' || key === 'daily_pnl') {
      return value.toLocaleString('en-IN', { style: 'currency', currency: 'INR' })
    }
    return value.toLocaleString('en-IN')
  }
  return String(value)
}

function StrategyMetrics({ metrics }: { metrics: Record<string, unknown> }) {
  const entries = Object.entries(metrics || {})
  if (entries.length === 0) {
    return <p className="text-xs text-muted-foreground">No metrics reported yet.</p>
  }
  return (
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
      {entries.map(([key, value]) => (
        <div key={key} className="flex justify-between gap-2">
          <span className="text-muted-foreground">{METRIC_LABELS[key] || key}</span>
          <span className="font-medium truncate">{formatMetricValue(key, value)}</span>
        </div>
      ))}
    </div>
  )
}

export default function StrategyHubIndex() {
  const [strategies, setStrategies] = useState<Record<string, StrategyHubEntry>>({})
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const { socket } = useSocketContext()
  const hasLoadedOnce = useRef(false)

  const fetchStrategies = useCallback(async () => {
    try {
      const data = await strategyHubApi.getStrategies()
      const byId: Record<string, StrategyHubEntry> = {}
      for (const entry of data) byId[entry.strategy_id] = entry
      setStrategies(byId)
    } catch {
      if (!hasLoadedOnce.current) {
        showToast.error('Failed to load Strategy Hub', 'strategy')
      }
    } finally {
      hasLoadedOnce.current = true
      setLoading(false)
    }
  }, [])

  // Fetch once on mount for the initial page load. All subsequent updates
  // arrive over SocketIO (strategy_hub_update) below — deliberately no
  // polling/auto-refresh interval, since re-fetching on a timer causes
  // flickering cards even when nothing changed.
  useEffect(() => {
    fetchStrategies()
  }, [fetchStrategies])

  // Real-time push from blueprints/strategy_zmq_listener.py — one strategy's
  // state per event, merged into the existing map.
  useEffect(() => {
    if (!socket) return

    const handleUpdate = (payload: { strategy_id: string; strategy: StrategyHubEntry }) => {
      setStrategies((prev) => ({ ...prev, [payload.strategy_id]: payload.strategy }))
    }

    socket.on('strategy_hub_update', handleUpdate)
    return () => {
      socket.off('strategy_hub_update', handleUpdate)
    }
  }, [socket])

  const handleStart = async (strategyId: string) => {
    try {
      setActionLoading(`start-${strategyId}`)
      const response = await strategyHubApi.startStrategy(strategyId)
      showToast[response.status === 'success' ? 'success' : 'error'](
        response.message || `Start requested for ${strategyId}`,
        'strategy'
      )
    } catch {
      showToast.error('Failed to send start command', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const handleStop = async (strategyId: string) => {
    try {
      setActionLoading(`stop-${strategyId}`)
      const response = await strategyHubApi.stopStrategy(strategyId)
      showToast[response.status === 'success' ? 'success' : 'error'](
        response.message || `Stop requested for ${strategyId}`,
        'strategy'
      )
    } catch {
      showToast.error('Failed to send stop command', 'strategy')
    } finally {
      setActionLoading(null)
    }
  }

  const entries = Object.values(strategies).sort((a, b) =>
    a.strategy_id.localeCompare(b.strategy_id)
  )

  return (
    <div className="container mx-auto py-6 max-w-5xl space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Radio className="h-6 w-6" />
            Strategy Hub
          </h1>
          <p className="text-muted-foreground">
            Live state of lean_trading_engine strategy runners, pushed over ZeroMQ and relayed here
            in real time. No auto-refresh — cards update only when a strategy reports.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => fetchStrategies()}>
          <RefreshCw className="h-4 w-4 mr-2" />
          Refresh
        </Button>
      </div>

      {loading ? (
        <p className="text-sm text-muted-foreground">Loading strategies...</p>
      ) : entries.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center space-y-2">
            <p className="text-sm text-muted-foreground">No strategies discovered yet.</p>
            <p className="text-xs text-muted-foreground">
              Start a lean_trading_engine runner (or any strategy configured with a zmq_config.json
              pointing at this OpenAlgo instance) and it will appear here within a few seconds of
              announcing itself, or the next periodic port scan.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {entries.map((strategy) => (
            <Card key={strategy.strategy_id}>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base truncate">{strategy.strategy_id}</CardTitle>
                <Badge variant={STATUS_BADGE_VARIANT[strategy.status]}>
                  {STATUS_LABEL[strategy.status]}
                </Badge>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="text-xs text-muted-foreground space-y-0.5">
                  <p>
                    {strategy.host}
                    {strategy.zmq_port ? `:${strategy.zmq_port}` : ''}
                    {strategy.unit_name ? ` · ${strategy.unit_name}` : ''}
                  </p>
                  <p>Last seen: {new Date(strategy.last_seen).toLocaleTimeString()}</p>
                </div>

                <StrategyMetrics metrics={strategy.metrics} />

                {strategy.last_command && (
                  <p
                    className={`text-xs ${strategy.last_command.success ? 'text-muted-foreground' : 'text-destructive'}`}
                  >
                    Last command: {strategy.last_command.command} — {strategy.last_command.message}
                  </p>
                )}

                <div className="flex gap-2 pt-1">
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={actionLoading === `start-${strategy.strategy_id}`}
                    onClick={() => handleStart(strategy.strategy_id)}
                  >
                    <Play className="h-4 w-4 mr-1" />
                    Start
                  </Button>
                  <Button
                    size="sm"
                    variant="destructive"
                    disabled={actionLoading === `stop-${strategy.strategy_id}`}
                    onClick={() => handleStop(strategy.strategy_id)}
                  >
                    <Square className="h-4 w-4 mr-1" />
                    Stop
                  </Button>
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
