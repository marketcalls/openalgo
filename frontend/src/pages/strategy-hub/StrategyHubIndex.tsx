import { ChevronDown, Copy, Pause, Play, Radio, RefreshCw, Square, Terminal, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { type StrategyHubEntry, type StrategyHubLog, type StrategyHubLogLevel, type StrategyHubStatus, strategyHubApi } from '@/api/strategy-hub'
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

const LOG_LEVELS: Array<'ALL' | StrategyHubLogLevel> = ['ALL', 'DEBUG', 'INFO', 'WARN', 'ERROR']
const LOG_COLORS: Record<StrategyHubLogLevel, string> = {
  DEBUG: 'text-slate-400', INFO: 'text-sky-300', WARN: 'text-amber-300', ERROR: 'text-rose-300',
}

function StrategyLogs({
  logs,
  loading,
  onClear,
}: { logs: StrategyHubLog[]; loading: boolean; onClear: () => void }) {
  const [level, setLevel] = useState<'ALL' | StrategyHubLogLevel>('ALL')
  const [query, setQuery] = useState('')
  const [paused, setPaused] = useState(false)
  const [pausedLogs, setPausedLogs] = useState<StrategyHubLog[]>([])
  const [open, setOpen] = useState(true)
  const shownLogs = paused ? pausedLogs : logs
  const filtered = shownLogs.filter((log) =>
    (level === 'ALL' || log.level === level) &&
    (!query || `${log.source} ${log.message}`.toLowerCase().includes(query.toLowerCase()))
  )

  const toggle = () => setOpen((value) => !value)
  const togglePaused = () => {
    if (paused) setPaused(false)
    else { setPausedLogs(logs); setPaused(true) }
  }
  const copyLogs = () => navigator.clipboard?.writeText(filtered.map((log) => `${log.timestamp} [${log.level}] ${log.message}`).join('\n'))

  return (
    <div className="rounded-lg border bg-slate-950/95 text-slate-100 overflow-hidden">
      <button type="button" onClick={toggle} className="w-full flex items-center justify-between px-3 py-2 text-left hover:bg-slate-900">
        <span className="flex items-center gap-2 text-xs font-medium"><Terminal className="h-3.5 w-3.5 text-cyan-300" /> Runner logs <span className="text-slate-500">{logs.length}</span></span>
        <ChevronDown className={`h-4 w-4 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open && (
        <div className="border-t border-slate-800">
          <div className="flex flex-wrap items-center gap-1.5 p-2 border-b border-slate-800">
            {LOG_LEVELS.map((item) => (
              <button key={item} type="button" onClick={() => setLevel(item)} className={`rounded px-2 py-1 text-[10px] ${level === item ? 'bg-cyan-400/20 text-cyan-200' : 'text-slate-400 hover:text-slate-200'}`}>{item}</button>
            ))}
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter logs" className="ml-auto min-w-24 flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1 text-[11px] outline-none placeholder:text-slate-600" />
            <Button variant="ghost" size="icon-sm" onClick={togglePaused} title={paused ? 'Resume live logs' : 'Pause live logs'} className="text-slate-300 hover:bg-slate-800 hover:text-white">{paused ? <Play /> : <Pause />}</Button>
            <Button variant="ghost" size="icon-sm" onClick={copyLogs} title="Copy visible logs" className="text-slate-300 hover:bg-slate-800 hover:text-white"><Copy /></Button>
            <Button variant="ghost" size="icon-sm" onClick={onClear} title="Clear logs" className="text-slate-300 hover:bg-slate-800 hover:text-white"><Trash2 /></Button>
          </div>
          <div className="max-h-[34rem] min-h-64 overflow-y-auto p-4 font-mono text-xs leading-5">
            {loading ? <p className="text-slate-500">Loading logs...</p> : filtered.length === 0 ? <p className="text-slate-500">No matching logs.</p> : filtered.map((log) => (
              <div key={log.id} className="grid grid-cols-[auto_auto_minmax(6rem,14rem)_minmax(0,1fr)] gap-x-3 whitespace-pre-wrap break-words">
                <span className="text-slate-600">{new Date(log.timestamp).toLocaleTimeString()}</span>
                <span className={`w-12 ${LOG_COLORS[log.level]}`}>{log.level}</span>
                <span className="truncate text-slate-500" title={log.source}>{log.source}</span>
                <span className="min-w-0 text-slate-200">{log.message}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

export default function StrategyHubIndex() {
  const [strategies, setStrategies] = useState<Record<string, StrategyHubEntry>>({})
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState<string | null>(null)
  const [logsByStrategy, setLogsByStrategy] = useState<Record<string, StrategyHubLog[]>>({})
  const [logsOpen, setLogsOpen] = useState<Record<string, boolean>>({})
  const [logsLoading, setLogsLoading] = useState<Record<string, boolean>>({})
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
    const handleLog = (payload: { strategy_id: string; log: StrategyHubLog }) => {
      setLogsByStrategy((prev) => ({ ...prev, [payload.strategy_id]: [...(prev[payload.strategy_id] || []), payload.log].slice(-500) }))
    }

    socket.on('strategy_hub_update', handleUpdate)
    socket.on('strategy_hub_log', handleLog)
    return () => {
      socket.off('strategy_hub_update', handleUpdate)
      socket.off('strategy_hub_log', handleLog)
    }
  }, [socket])

  const toggleLogs = async (strategyId: string) => {
    const nextOpen = !logsOpen[strategyId]
    setLogsOpen((prev) => ({ ...prev, [strategyId]: nextOpen }))
    if (nextOpen && logsByStrategy[strategyId] === undefined) {
      setLogsLoading((prev) => ({ ...prev, [strategyId]: true }))
      try {
        const logs = await strategyHubApi.getLogs(strategyId)
        setLogsByStrategy((prev) => ({ ...prev, [strategyId]: logs }))
      } catch { showToast.error('Failed to load runner logs', 'strategy') }
      finally { setLogsLoading((prev) => ({ ...prev, [strategyId]: false })) }
    }
  }

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

  const clearLogs = (strategyId: string) => setLogsByStrategy((prev) => ({ ...prev, [strategyId]: [] }))

  const entries = Object.values(strategies).sort((a, b) =>
    a.strategy_id.localeCompare(b.strategy_id)
  )

  return (
    <div className="container mx-auto max-w-[1800px] space-y-6 px-4 py-6 sm:px-6 lg:px-8">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Radio className="h-6 w-6" />
            Strategy Hub
          </h1>
          <p className="max-w-4xl text-muted-foreground">
            Live state of lean_trading_engine strategy runners, pushed over ZeroMQ and relayed here
            in real time. No auto-refresh — cards update only when a strategy reports.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={() => fetchStrategies()} className="self-start lg:self-auto">
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
        <div className="grid gap-5">
          {entries.map((strategy) => (
            <Card key={strategy.strategy_id}>
              <CardHeader className="flex-row items-center justify-between">
                <CardTitle className="text-base truncate">{strategy.strategy_id}</CardTitle>
                <Badge variant={STATUS_BADGE_VARIANT[strategy.status]}>
                  {STATUS_LABEL[strategy.status]}
                </Badge>
              </CardHeader>
              <CardContent className="min-w-0 space-y-4">
                <div className="text-xs text-muted-foreground space-y-0.5">
                  <p>
                    {strategy.host}
                    {strategy.zmq_port ? `:${strategy.zmq_port}` : ''}
                    {strategy.unit_name ? ` · ${strategy.unit_name}` : ''}
                  </p>
                  <p>Last seen: {new Date(strategy.last_seen).toLocaleTimeString()}</p>
                </div>

                <StrategyMetrics metrics={strategy.metrics} />

                <div>
                  {!logsOpen[strategy.strategy_id] && (
                    <Button variant="outline" size="sm" onClick={() => toggleLogs(strategy.strategy_id)} className="w-full justify-between">
                      <span className="flex items-center gap-2"><Terminal className="h-4 w-4" /> Runner logs <span className="text-muted-foreground">{logsByStrategy[strategy.strategy_id]?.length || 0}</span></span>
                      <ChevronDown className="h-4 w-4" />
                    </Button>
                  )}
                  {logsOpen[strategy.strategy_id] && <StrategyLogs logs={logsByStrategy[strategy.strategy_id] || []} loading={Boolean(logsLoading[strategy.strategy_id])} onClear={() => clearLogs(strategy.strategy_id)} />}
                </div>

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
