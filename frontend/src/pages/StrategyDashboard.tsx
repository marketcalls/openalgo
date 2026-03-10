/**
 * Strategy Dashboard — Bloomberg Terminal–style eagle-eye view
 *
 * Zone 1 · Portfolio KPI strip  (aggregate across all strategies)
 * Zone 2 · Strategy Matrix      (one row per strategy, sortable/filterable)
 * Zone 3 · Open Legs Feed       (all active legs across all strategies, paginated)
 * Zone 4 · Closed Trades Feed   (trade history across all strategies, paginated)
 */

import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart2,
  CheckCircle2,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  ChevronsUpDown,
  CircleDot,
  ExternalLink,
  Filter,
  Minus,
  PauseCircle,
  RefreshCw,
  Target,
  TrendingUp,
  XCircle,
  Zap,
} from 'lucide-react'
import StrategyPnLChart from '@/components/StrategyPnLChart'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { getStrategyStates } from '@/api/strategy-state'
import type { StrategyState, TradeHistoryRecord } from '@/types/strategy-state'

// ─────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────
const HEALTH_STALE_SECS = 30
const HEALTH_DEAD_SECS = 60
const AUTO_REFRESH_OPTIONS = [5, 10, 15, 30, 60]
const PAGE_SIZE = 25

// ─────────────────────────────────────────────
// Formatters
// ─────────────────────────────────────────────
function formatINR(value: number | null | undefined, compact = false): string {
  if (value === null || value === undefined) return '—'
  const abs = Math.abs(value)
  if (compact && abs >= 1_00_000) {
    if (abs >= 1_00_00_000) return `${value < 0 ? '-' : ''}₹${(abs / 1_00_00_000).toFixed(2)}Cr`
    return `${value < 0 ? '-' : ''}₹${(abs / 1_00_000).toFixed(2)}L`
  }
  const formatted = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(abs)
  return value < 0 ? `-${formatted}` : formatted
}

function formatTime(iso: string | null | undefined, timeOnly = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (timeOnly) {
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })
  }
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

/**
 * Smart time formatter used in table cells:
 * - Today's entries → "14:32" (time only, less noise)
 * - Past days       → "12 Mar, 14:32" (date + time so the user knows it's older)
 */
function formatSmartTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  const formatter = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Kolkata' })
  const isToday = formatter.format(d) === formatter.format(new Date())
  if (isToday) {
    return d.toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Kolkata' })
  }
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short',
    hour: '2-digit', minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

function heartbeatAge(iso: string | null | undefined): string {
  if (!iso) return 'never'
  const secs = (Date.now() - new Date(iso).getTime()) / 1000
  if (secs < 5) return 'now'
  if (secs < 60) return `${Math.floor(secs)}s`
  if (secs < 3600) return `${Math.floor(secs / 60)}m`
  return `${Math.floor(secs / 3600)}h`
}

function pnlColor(v: number | null | undefined): string {
  if (v === null || v === undefined) return 'text-muted-foreground'
  if (v > 0) return 'text-emerald-500 dark:text-emerald-400'
  if (v < 0) return 'text-red-500 dark:text-red-400'
  return 'text-muted-foreground'
}

function pnlBg(v: number, intensity = 1): string {
  if (v > 0) return `rgba(16,185,129,${Math.min(0.08 * intensity, 0.18)})`
  if (v < 0) return `rgba(239,68,68,${Math.min(0.08 * intensity, 0.18)})`
  return 'transparent'
}

function resolveNum(v: unknown): number | null {
  if (v === null || v === undefined) return null
  if (typeof v === 'number') return v
  if (typeof v === 'object' && 'parsedValue' in (v as object)) {
    const pv = (v as { parsedValue: unknown }).parsedValue
    return typeof pv === 'number' ? pv : null
  }
  return null
}

// ─────────────────────────────────────────────
// Health helpers
// ─────────────────────────────────────────────
type Health = 'alive' | 'stale' | 'dead' | 'unknown'

function getHealth(s: StrategyState): Health {
  if (s.status === 'COMPLETED') return 'unknown'
  if (!s.last_heartbeat) return 'unknown'
  const age = (Date.now() - new Date(s.last_heartbeat).getTime()) / 1000
  if (Number.isNaN(age)) return 'unknown'
  if (age < HEALTH_STALE_SECS) return 'alive'
  if (age < HEALTH_DEAD_SECS) return 'stale'
  return 'dead'
}

const healthDot: Record<Health, string> = {
  alive: 'bg-emerald-400',
  stale: 'bg-yellow-400',
  dead: 'bg-red-500',
  unknown: 'bg-gray-400',
}

const healthLabel: Record<Health, string> = {
  alive: 'Live',
  stale: 'Stale',
  dead: 'No Signal',
  unknown: '—',
}

// ─────────────────────────────────────────────
// Per-strategy derived metrics
// ─────────────────────────────────────────────
interface StrategyMetrics {
  strategy: StrategyState
  realizedPnL: number
  unrealizedPnL: number
  totalPnL: number
  totalBrokerage: number
  netPnL: number
  openLegs: number
  totalLegs: number
  totalTrades: number
  closedTradeCount: number  // for win rate context
  slHits: number
  targetHits: number
  winRate: number | null       // % of CLOSED trades with positive P&L
  avgClosedTradePnL: number | null
  maxDrawdown: number          // always a number (0 if no drawdown detected)
  cycleCount: number
  runningMins: number | null
  health: Health
  underlying: string
  expiry: string
  openLots: number  // sum of qty/lot_size for IN_POSITION legs
}

function computeMetrics(s: StrategyState): StrategyMetrics {
  const legs = Object.values(s.legs ?? {})
  const openLegList = legs.filter(l => l.status === 'IN_POSITION')
  const openLegs = openLegList.length
  const totalLegs = legs.length

  const lotSize = s.config?.lot_size ?? 1
  // Total lots currently in position = sum(qty / lot_size) for each IN_POSITION leg
  const openLots = openLegList.reduce((sum, l) => sum + Math.round((l.quantity ?? 0) / lotSize), 0)

  const realizedPnL = s.summary?.total_realized_pnl ?? 0
  const unrealizedPnL = s.summary?.total_unrealized_pnl ?? 0
  const totalPnL = s.summary?.total_pnl ?? (realizedPnL + unrealizedPnL)

  // Brokerage: deduplicate — trade_history brokerage is the ground truth for closed legs
  const historyBrokerage = (s.trade_history ?? []).reduce((sum, t) => sum + (resolveNum(t.total_brokerage) ?? 0), 0)
  const openLegBrokerage = openLegList.reduce((sum, l) => sum + (resolveNum(l.total_brokerage) ?? 0), 0)
  const totalBrokerage = historyBrokerage + openLegBrokerage

  const netPnL = totalPnL - totalBrokerage

  const history = s.trade_history ?? []
  // Win rate is only meaningful for CLOSED trades (exit_price is not null)
  const closedTrades = history.filter(t => t.exit_price !== null)
  const closedTradeCount = closedTrades.length
  const slHits = history.filter(t => t.exit_type === 'SL_HIT' || t.exit_type === 'FIXED_SL' || t.exit_type === 'TRAIL_SL').length
  const targetHits = history.filter(t => t.exit_type === 'TARGET_HIT' || t.exit_type === 'TARGET').length
  const profitTrades = closedTrades.filter(t => (t.pnl ?? 0) > 0).length
  const winRate = closedTradeCount > 0 ? (profitTrades / closedTradeCount) * 100 : null

  // Avg P&L per closed trade (excludes open legs)
  const avgClosedTradePnL = closedTradeCount > 0
    ? closedTrades.reduce((sum, t) => sum + (t.pnl ?? 0), 0) / closedTradeCount
    : null

  // Max Drawdown: largest peak-to-trough drop in cumulative closed-trade P&L
  let maxDrawdown = 0
  const sortedClosedTrades = history
    .filter(t => t.exit_price !== null)
    .sort((a, b) => (a.exit_time ?? '').localeCompare(b.exit_time ?? ''))

  if (sortedClosedTrades.length >= 1) {
    let peak = 0
    let cumPnL = 0
    for (const t of sortedClosedTrades) {
      cumPnL += t.pnl ?? 0
      if (cumPnL > peak) peak = cumPnL
      const dd = peak - cumPnL
      if (dd > maxDrawdown) maxDrawdown = dd
    }
  }

  const cycleCount = s.orchestrator?.cycle_count ?? 0

  let runningMins: number | null = null
  if (s.orchestrator?.start_time) {
    runningMins = (Date.now() - new Date(s.orchestrator.start_time).getTime()) / 60000
  }

  return {
    strategy: s,
    realizedPnL,
    unrealizedPnL,
    totalPnL,
    totalBrokerage,
    netPnL,
    openLegs,
    totalLegs,
    totalTrades: history.length,
    closedTradeCount,
    slHits,
    targetHits,
    winRate,
    avgClosedTradePnL,
    maxDrawdown,
    cycleCount,
    runningMins,
    health: getHealth(s),
    underlying: s.config?.underlying ?? s.state_data?.underlying ?? '—',
    expiry: s.config?.expiry_date ?? '—',
    openLots,
  }
}

// ─────────────────────────────────────────────
// Flat open leg row (all primitive fields for clean sorting)
// ─────────────────────────────────────────────
interface FlatOpenLegRow {
  instanceId: string
  strategyName: string
  legKey: string
  symbol: string
  legType: string       // CE / PE / etc.
  isMainLeg: boolean
  side: 'BUY' | 'SELL'
  // Signed qty: positive for BUY, negative for SELL
  signedQty: number
  entryPrice: number | null
  ltp: number | null
  pnl: number | null
  slPrice: number | null
  targetPrice: number | null
  reentryCount: number
  reentryLimit: number | null
  entryTime: string | null
}

interface ClosedTradeRow extends TradeHistoryRecord {
  instanceId: string
  strategyName: string
}

// ─────────────────────────────────────────────
// Generic sort hook
// ─────────────────────────────────────────────
type SortDir = 'asc' | 'desc' | null

function useSortable<T>(items: T[]) {
  const [sortKey, setSortKey] = useState<keyof T | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)

  const toggle = (key: keyof T) => {
    if (sortKey === key) {
      if (sortDir === 'asc') {
        setSortDir('desc')
      } else if (sortDir === 'desc') {
        setSortKey(null)
        setSortDir(null)
      } else {
        setSortDir('asc')
      }
    } else {
      setSortKey(key)
      setSortDir('asc')
    }
  }

  const sorted = useMemo(() => {
    if (!sortKey || !sortDir) return items
    return [...items].sort((a, b) => {
      const av = a[sortKey]
      const bv = b[sortKey]
      if (av === null || av === undefined) return 1
      if (bv === null || bv === undefined) return -1
      const cmp = av < bv ? -1 : av > bv ? 1 : 0
      return sortDir === 'asc' ? cmp : -cmp
    })
  }, [items, sortKey, sortDir])

  return { sorted, sortKey, sortDir, toggle }
}

// ─────────────────────────────────────────────
// Pagination component
// ─────────────────────────────────────────────
function Pagination({
  page, total, pageSize, onChange,
}: {
  page: number
  total: number
  pageSize: number
  onChange: (p: number) => void
}) {
  const totalPages = Math.ceil(total / pageSize)
  if (totalPages <= 1) return null
  const start = page * pageSize + 1
  const end = Math.min((page + 1) * pageSize, total)
  return (
    <div className="flex items-center gap-2 px-4 py-2 border-t bg-muted/20 text-xs text-muted-foreground">
      <span>{start}–{end} of {total}</span>
      <div className="flex items-center gap-1 ml-auto">
        <Button
          size="sm" variant="ghost"
          className="h-6 w-6 p-0"
          disabled={page === 0}
          onClick={() => onChange(page - 1)}
        >
          <ChevronLeft className="h-3 w-3" />
        </Button>
        <span className="px-1 text-[10px]">Page {page + 1} / {totalPages}</span>
        <Button
          size="sm" variant="ghost"
          className="h-6 w-6 p-0"
          disabled={page >= totalPages - 1}
          onClick={() => onChange(page + 1)}
        >
          <ChevronRight className="h-3 w-3" />
        </Button>
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────
// Sub-components
// ─────────────────────────────────────────────

function SortIcon({ active, dir }: { active: boolean; dir: SortDir }) {
  if (!active || !dir) return <ChevronsUpDown className="h-3 w-3 opacity-30 ml-0.5" />
  return dir === 'asc'
    ? <ChevronUp className="h-3 w-3 opacity-70 ml-0.5" />
    : <ChevronDown className="h-3 w-3 opacity-70 ml-0.5" />
}

function Th({
  label, sortKey, currentKey, dir, onSort, className = '', title,
}: {
  label: string
  sortKey?: string
  currentKey?: string | null
  dir?: SortDir
  onSort?: () => void
  className?: string
  title?: string
}) {
  const active = !!sortKey && sortKey === currentKey
  return (
    <th
      title={title}
      className={`px-3 py-2 text-left text-[10px] font-semibold uppercase tracking-widest text-muted-foreground whitespace-nowrap select-none ${sortKey ? 'cursor-pointer hover:text-foreground' : ''} ${className}`}
      onClick={onSort}
    >
      <span className="inline-flex items-center gap-0.5">
        {label}
        {sortKey && <SortIcon active={active} dir={active ? (dir ?? null) : null} />}
      </span>
    </th>
  )
}

function PnLCell({ value, compact = false }: { value: number | null | undefined; compact?: boolean }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground text-sm">—</span>
  const cls = pnlColor(value)
  const Icon = value > 0 ? ArrowUpRight : value < 0 ? ArrowDownRight : Minus
  return (
    <span className={`inline-flex items-center gap-0.5 font-mono text-sm font-semibold ${cls}`}>
      <Icon className="h-3 w-3 shrink-0" />
      {formatINR(value, compact)}
    </span>
  )
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    RUNNING: 'border-emerald-500 text-emerald-600 dark:text-emerald-400 bg-emerald-500/10',
    PAUSED: 'border-yellow-500 text-yellow-600 dark:text-yellow-400 bg-yellow-500/10',
    COMPLETED: 'border-gray-400 text-gray-500 bg-gray-400/10',
    ERROR: 'border-red-500 text-red-600 dark:text-red-400 bg-red-500/10',
  }
  const StatusIcon: Record<string, React.ReactNode> = {
    RUNNING: <Activity className="h-3 w-3" />,
    PAUSED: <PauseCircle className="h-3 w-3" />,
    COMPLETED: <CheckCircle2 className="h-3 w-3" />,
    ERROR: <XCircle className="h-3 w-3" />,
  }
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px] font-semibold ${map[status] ?? 'border-gray-400 text-gray-500'}`}>
      {StatusIcon[status]}
      {status}
    </span>
  )
}

function HealthDot({ health }: { health: Health }) {
  const isAlive = health === 'alive'
  return (
    <span className="inline-flex items-center gap-1">
      <span className="relative flex h-2 w-2">
        {isAlive && <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${healthDot[health]} opacity-60`} />}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${healthDot[health]}`} />
      </span>
      <span className="text-[10px] text-muted-foreground">{healthLabel[health]}</span>
    </span>
  )
}

/**
 * WinRateBar — shows a visual bar + pct + trade count for context.
 * Win % = (profitable closed trades / total closed trades) × 100.
 * It only counts trades where exit_price is recorded (closed trades).
 * Open positions are NOT included — a strategy can have 100% win rate
 * on closed trades while still having negative unrealized P&L on open legs.
 */
function getWinRateColor(pct: number): { text: string; bg: string } {
  if (pct >= 60) return { text: 'text-emerald-500', bg: 'bg-emerald-500' }
  if (pct >= 40) return { text: 'text-yellow-500', bg: 'bg-yellow-400' }
  return { text: 'text-red-500', bg: 'bg-red-500' }
}

function WinRateBar({ rate, closedCount }: { rate: number | null; closedCount: number }) {
  if (rate === null || closedCount === 0) {
    return <span className="text-muted-foreground text-sm">— <span className="text-[10px]">(no closed trades)</span></span>
  }
  const pct = Math.round(rate)
  const winCount = Math.round((rate / 100) * closedCount)
  const { text: textColor, bg: color } = getWinRateColor(pct)
  return (
    <span
      className="inline-flex items-center gap-1.5"
      title={`${winCount} profitable out of ${closedCount} closed trades`}
    >
      <span className="h-1.5 w-12 rounded-full bg-muted overflow-hidden">
        <span className={`block h-full rounded-full ${color}`} style={{ width: `${pct}%` }} />
      </span>
      <span className={`text-sm font-mono font-semibold ${textColor}`}>{pct}%</span>
      <span className="text-[10px] text-muted-foreground">({winCount}/{closedCount})</span>
    </span>
  )
}

// ─────────────────────────────────────────────
// KPI Card
// ─────────────────────────────────────────────
function KpiCard({
  label, value, sub, icon: Icon, valueColor, trend,
}: {
  label: string
  value: string
  sub?: string
  icon: React.ElementType
  valueColor?: string
  trend?: 'up' | 'down' | 'neutral'
}) {
  const trendColor = trend === 'up' ? 'text-emerald-500' : trend === 'down' ? 'text-red-500' : 'text-muted-foreground'
  return (
    <div className="rounded-lg border bg-card px-4 py-3 flex flex-col gap-1 min-w-0">
      <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">
        <Icon className="h-3 w-3 shrink-0" />
        {label}
      </div>
      <div className={`font-mono text-lg font-bold leading-tight truncate ${valueColor ?? ''}`}>
        {value}
      </div>
      {sub && <div className={`text-[10px] ${trendColor}`}>{sub}</div>}
    </div>
  )
}

// ─────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────
export default function StrategyDashboard() {
  const [strategies, setStrategies] = useState<StrategyState[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
  const [autoRefresh, setAutoRefresh] = useState<number>(10)
  const [statusFilter, setStatusFilter] = useState<string>('ALL')
  const [healthFilter, setHealthFilter] = useState<string>('ALL')
  const [search, setSearch] = useState('')
  const [selectedInstanceId, setSelectedInstanceId] = useState<string | null>(null)
  const [activeTab, setActiveTab] = useState('open-legs')
  const [legsPage, setLegsPage] = useState(0)
  const [tradesPage, setTradesPage] = useState(0)
  const [isPnLModalOpen, setIsPnLModalOpen] = useState(false)
  const [selectedStrategyForPnL, setSelectedStrategyForPnL] = useState<{ instanceId: string; name: string } | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const fetchData = useCallback(async () => {
    try {
      const data = await getStrategyStates()
      setStrategies(data)
      setLastRefresh(new Date())
      setError(null)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch strategies')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { fetchData() }, [fetchData])

  useEffect(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    if (autoRefresh > 0) {
      timerRef.current = setInterval(fetchData, autoRefresh * 1000)
    }
    return () => { if (timerRef.current) clearInterval(timerRef.current) }
  }, [autoRefresh, fetchData])

  // ── Derived metrics per strategy
  const allMetrics = useMemo(() => strategies.map(computeMetrics), [strategies])

  // ── Portfolio aggregates
  const portfolio = useMemo(() => {
    const running = allMetrics.filter(m => m.strategy.status === 'RUNNING').length
    const paused = allMetrics.filter(m => m.strategy.status === 'PAUSED').length
    const completed = allMetrics.filter(m => m.strategy.status === 'COMPLETED').length
    const errored = allMetrics.filter(m => m.strategy.status === 'ERROR').length
    const aliveCount = allMetrics.filter(m => m.health === 'alive').length
    const totalPnL = allMetrics.reduce((s, m) => s + m.totalPnL, 0)
    const realizedPnL = allMetrics.reduce((s, m) => s + m.realizedPnL, 0)
    const unrealizedPnL = allMetrics.reduce((s, m) => s + m.unrealizedPnL, 0)
    const totalBrokerage = allMetrics.reduce((s, m) => s + m.totalBrokerage, 0)
    const netPnL = totalPnL - totalBrokerage
    const openLegs = allMetrics.reduce((s, m) => s + m.openLegs, 0)
    const totalTrades = allMetrics.reduce((s, m) => s + m.totalTrades, 0)
    const slHits = allMetrics.reduce((s, m) => s + m.slHits, 0)
    const targetHits = allMetrics.reduce((s, m) => s + m.targetHits, 0)
    const allClosed = strategies.flatMap(s => (s.trade_history ?? []).filter(t => t.exit_price !== null))
    const winTrades = allClosed.filter(t => (t.pnl ?? 0) > 0).length
    const portfolioWinRate = allClosed.length > 0 ? (winTrades / allClosed.length) * 100 : null
    const portfolioClosedCount = allClosed.length

    return {
      total: allMetrics.length,
      running, paused, completed, errored, aliveCount,
      totalPnL, realizedPnL, unrealizedPnL, totalBrokerage, netPnL,
      openLegs, totalTrades, slHits, targetHits, portfolioWinRate, portfolioClosedCount,
    }
  }, [allMetrics, strategies])

  // ── Filtered + flattened strategy rows for the matrix
  const strategyRows = useMemo(() => {
    return allMetrics
      .filter(m => {
        if (statusFilter !== 'ALL' && m.strategy.status !== statusFilter) return false
        if (healthFilter !== 'ALL' && m.health !== healthFilter) return false
        if (search) {
          const q = search.toLowerCase()
          if (
            !m.strategy.strategy_name.toLowerCase().includes(q) &&
            !m.underlying.toLowerCase().includes(q)
          ) return false
        }
        return true
      })
      .map(m => ({
        ...m,
        id: m.strategy.id,
        name: m.strategy.strategy_name,
        status: m.strategy.status,
        instanceId: m.strategy.instance_id,
      }))
  }, [allMetrics, statusFilter, healthFilter, search])

  const { sorted: sortedStrategies, sortKey: sKey, sortDir: sDir, toggle: sToggle } =
    useSortable(strategyRows)

  // ── Flat open leg rows (all active/pending legs, across all strategies)
  const openLegRows = useMemo<FlatOpenLegRow[]>(() => {
    const rows: FlatOpenLegRow[] = []
    for (const s of strategies) {
      if (selectedInstanceId && s.instance_id !== selectedInstanceId) continue
      for (const [legKey, leg] of Object.entries(s.legs ?? {})) {
        if (
          leg.status !== 'IN_POSITION' &&
          leg.status !== 'PENDING_ENTRY' &&
          leg.status !== 'PENDING_EXIT'
        ) continue

        const entryPrice = resolveNum(leg.entry_price)
        const ltp = leg.current_ltp ?? null
        let pnl: number | null = null
        if (entryPrice !== null && ltp !== null && leg.quantity) {
          pnl = leg.side === 'BUY'
            ? (ltp - entryPrice) * leg.quantity
            : (entryPrice - ltp) * leg.quantity
        }
        if (pnl === null && leg.unrealized_pnl !== undefined) pnl = leg.unrealized_pnl

        // Signed qty: positive for BUY, negative for SELL
        const signedQty = leg.side === 'SELL'
          ? -(leg.quantity ?? 0)
          : (leg.quantity ?? 0)

        rows.push({
          instanceId: s.instance_id,
          strategyName: s.strategy_name,
          legKey,
          symbol: leg.symbol ?? '—',
          legType: leg.leg_type ?? '—',
          isMainLeg: leg.is_main_leg ?? false,
          side: leg.side,
          signedQty,
          entryPrice,
          ltp,
          pnl,
          slPrice: resolveNum(leg.sl_price),
          targetPrice: resolveNum(leg.target_price),
          reentryCount: leg.reentry_count ?? 0,
          reentryLimit: leg.reentry_limit ?? null,
          entryTime: leg.entry_time ?? null,
        })
      }
    }
    return rows
  }, [strategies, selectedInstanceId])

  // ── Closed trade rows
  const closedTradeRows = useMemo<ClosedTradeRow[]>(() => {
    const rows: ClosedTradeRow[] = []
    for (const s of strategies) {
      if (selectedInstanceId && s.instance_id !== selectedInstanceId) continue
      for (const t of s.trade_history ?? []) {
        if (t.exit_price === null) continue
        rows.push({ ...t, instanceId: s.instance_id, strategyName: s.strategy_name })
      }
    }
    return rows.sort((a, b) => {
      if (!a.exit_time) return 1
      if (!b.exit_time) return -1
      return b.exit_time.localeCompare(a.exit_time)
    })
  }, [strategies, selectedInstanceId])

  const { sorted: sortedLegs, sortKey: lKey, sortDir: lDir, toggle: lToggle } = useSortable(openLegRows)
  const { sorted: sortedTrades, sortKey: tKey, sortDir: tDir, toggle: tToggle } = useSortable(closedTradeRows)

  // Reset pages when filter changes
  useEffect(() => { setLegsPage(0) }, [selectedInstanceId, openLegRows])
  useEffect(() => { setTradesPage(0) }, [selectedInstanceId, closedTradeRows])

  const pagedLegs = useMemo(
    () => sortedLegs.slice(legsPage * PAGE_SIZE, (legsPage + 1) * PAGE_SIZE),
    [sortedLegs, legsPage]
  )
  const pagedTrades = useMemo(
    () => sortedTrades.slice(tradesPage * PAGE_SIZE, (tradesPage + 1) * PAGE_SIZE),
    [sortedTrades, tradesPage]
  )

  const exitTypeColor: Record<string, string> = {
    SL_HIT: 'text-red-500',
    FIXED_SL: 'text-red-500',
    TRAIL_SL: 'text-orange-400',
    TARGET_HIT: 'text-emerald-500',
    TARGET: 'text-emerald-500',
    MANUAL_EXIT: 'text-purple-400',
    STRATEGY_DONE: 'text-muted-foreground',
    AUTO_BUYBACK: 'text-blue-400',
    HEDGE_SL_EXIT: 'text-red-400',
    HEDGE_TARGET_EXIT: 'text-emerald-400',
    EXIT: 'text-muted-foreground',
  }

  // ── Loading / Error states
  if (loading) {
    return (
      <div className="flex h-96 items-center justify-center text-muted-foreground text-sm">
        <RefreshCw className="h-4 w-4 animate-spin mr-2" /> Loading strategy data…
      </div>
    )
  }

  if (error) {
    return (
      <div className="flex h-96 items-center justify-center gap-2 text-red-500">
        <AlertTriangle className="h-5 w-5" />
        <span>{error}</span>
        <Button size="sm" variant="outline" onClick={fetchData}>Retry</Button>
      </div>
    )
  }

  return (
    <div className="space-y-4 p-4 md:p-6">
      {/* ─── Page header ─── */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold tracking-tight flex items-center gap-2">
            <BarChart2 className="h-5 w-5 text-primary" />
            Strategy Dashboard
          </h1>
          <p className="text-sm text-muted-foreground mt-0.5">
            Eagle-eye view across all strategies · Last updated{' '}
            {lastRefresh ? lastRefresh.toLocaleTimeString('en-IN', { timeZone: 'Asia/Kolkata' }) : '—'}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-sm text-muted-foreground">Auto-refresh:</span>
          <Select value={String(autoRefresh)} onValueChange={v => setAutoRefresh(Number(v))}>
            <SelectTrigger className="h-8 w-20 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="0">Off</SelectItem>
              {AUTO_REFRESH_OPTIONS.map(s => (
                <SelectItem key={s} value={String(s)}>{s}s</SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button
            size="sm" variant="outline" onClick={fetchData}
            className="h-8 px-3 text-sm gap-1.5"
            title="Fetch latest data from the server right now"
          >
            <RefreshCw className="h-3.5 w-3.5" /> Refresh Now
          </Button>
          <Link to="/strategy-positions">
            <Button size="sm" variant="outline" className="h-8 px-3 text-sm gap-1.5">
              <ExternalLink className="h-3.5 w-3.5" /> Detail View
            </Button>
          </Link>
        </div>
      </div>

      {/* ─── Zone 1: Portfolio KPI Strip ─── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        <KpiCard
          label="Total P&L"
          value={formatINR(portfolio.totalPnL, true)}
          sub={portfolio.totalPnL >= 0 ? '▲ Gross (realized + unrealized)' : '▼ Gross (realized + unrealized)'}
          icon={TrendingUp}
          valueColor={pnlColor(portfolio.totalPnL)}
          trend={portfolio.totalPnL > 0 ? 'up' : portfolio.totalPnL < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Net P&L"
          value={formatINR(portfolio.netPnL, true)}
          sub={`After ₹${Math.abs(portfolio.totalBrokerage).toFixed(0)} brokerage`}
          icon={Zap}
          valueColor={pnlColor(portfolio.netPnL)}
          trend={portfolio.netPnL > 0 ? 'up' : portfolio.netPnL < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Realized"
          value={formatINR(portfolio.realizedPnL, true)}
          sub="Booked / closed trade P&L"
          icon={CheckCircle2}
          valueColor={pnlColor(portfolio.realizedPnL)}
          trend={portfolio.realizedPnL > 0 ? 'up' : portfolio.realizedPnL < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Unrealized"
          value={formatINR(portfolio.unrealizedPnL, true)}
          sub={`${portfolio.openLegs} open leg${portfolio.openLegs !== 1 ? 's' : ''}`}
          icon={CircleDot}
          valueColor={pnlColor(portfolio.unrealizedPnL)}
          trend={portfolio.unrealizedPnL > 0 ? 'up' : portfolio.unrealizedPnL < 0 ? 'down' : 'neutral'}
        />
        <KpiCard
          label="Win Rate"
          value={portfolio.portfolioWinRate !== null ? `${Math.round(portfolio.portfolioWinRate)}%` : '—'}
          sub={`Tgt:${portfolio.targetHits} SL:${portfolio.slHits} of ${portfolio.portfolioClosedCount} closed`}
          icon={Target}
          valueColor={
            portfolio.portfolioWinRate !== null
              ? getWinRateColor(Math.round(portfolio.portfolioWinRate)).text
              : ''
          }
        />
        <KpiCard
          label="Strategies"
          value={`${portfolio.running}R · ${portfolio.paused}P · ${portfolio.completed}C`}
          sub={`${portfolio.aliveCount} alive · ${portfolio.errored} error`}
          icon={Activity}
          valueColor="text-foreground"
        />
      </div>

      {/* ─── Zone 2: Strategy Matrix ─── */}
      <div className="rounded-lg border bg-card overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 px-4 py-2.5 border-b bg-muted/30">
          <span className="text-sm font-semibold text-muted-foreground flex items-center gap-1">
            <Filter className="h-3.5 w-3.5" /> Strategy Matrix
          </span>
          <div className="flex-1" />
          <Input
            placeholder="Search strategy / underlying…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="h-8 w-48 text-sm"
          />
          <Select value={statusFilter} onValueChange={setStatusFilter}>
            <SelectTrigger className="h-8 w-32 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Status</SelectItem>
              <SelectItem value="RUNNING">Running</SelectItem>
              <SelectItem value="PAUSED">Paused</SelectItem>
              <SelectItem value="COMPLETED">Completed</SelectItem>
              <SelectItem value="ERROR">Error</SelectItem>
            </SelectContent>
          </Select>
          <Select value={healthFilter} onValueChange={setHealthFilter}>
            <SelectTrigger className="h-8 w-32 text-sm">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="ALL">All Health</SelectItem>
              <SelectItem value="alive">Live</SelectItem>
              <SelectItem value="stale">Stale</SelectItem>
              <SelectItem value="dead">No Signal</SelectItem>
            </SelectContent>
          </Select>
          {selectedInstanceId && (
            <Button size="sm" variant="secondary" className="h-8 text-sm" onClick={() => setSelectedInstanceId(null)}>
              Clear filter
            </Button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead className="border-b bg-muted/20">
              <tr>
                <Th label="Strategy" sortKey="name" currentKey={sKey} dir={sDir} onSort={() => sToggle('name')} className="pl-4 min-w-[140px]" />
                <Th label="P&L Curve" />
                <Th label="Status" />
                <Th label="Health" />
                <Th label="Underlying" sortKey="underlying" currentKey={sKey} dir={sDir} onSort={() => sToggle('underlying')} />
                <Th label="Expiry" sortKey="expiry" currentKey={sKey} dir={sDir} onSort={() => sToggle('expiry')} />
                <Th
                  label="Open Lots"
                  sortKey="openLots" currentKey={sKey} dir={sDir} onSort={() => sToggle('openLots')}
                  title="Sum of (qty ÷ lot_size) for all IN_POSITION legs"
                />
                <Th label="Realized P&L" sortKey="realizedPnL" currentKey={sKey} dir={sDir} onSort={() => sToggle('realizedPnL')} />
                <Th label="Unrealized P&L" sortKey="unrealizedPnL" currentKey={sKey} dir={sDir} onSort={() => sToggle('unrealizedPnL')} />
                <Th label="Total P&L" sortKey="totalPnL" currentKey={sKey} dir={sDir} onSort={() => sToggle('totalPnL')} />
                <Th label="Net P&L" sortKey="netPnL" currentKey={sKey} dir={sDir} onSort={() => sToggle('netPnL')} />
                <Th label="Brokerage" sortKey="totalBrokerage" currentKey={sKey} dir={sDir} onSort={() => sToggle('totalBrokerage')} />
                <Th
                  label="Win % (closed)"
                  sortKey="winRate" currentKey={sKey} dir={sDir} onSort={() => sToggle('winRate')}
                  title="% of CLOSED trades with positive P&L. Open positions are excluded — a strategy can have 100% win rate on closed trades while still holding a losing open position."
                />
                <Th
                  label="Avg Closed P&L"
                  sortKey="avgClosedTradePnL" currentKey={sKey} dir={sDir} onSort={() => sToggle('avgClosedTradePnL')}
                  title="Average P&L per closed trade (exit_price recorded). Does not include open leg MTM."
                />
                <Th
                  label="Max Drawdown"
                  sortKey="maxDrawdown" currentKey={sKey} dir={sDir} onSort={() => sToggle('maxDrawdown')}
                  title="Largest peak-to-trough drop in cumulative closed-trade P&L sequence."
                />
                <Th label="Open/Total Legs" sortKey="openLegs" currentKey={sKey} dir={sDir} onSort={() => sToggle('openLegs')} />
                <Th label="Trades" sortKey="totalTrades" currentKey={sKey} dir={sDir} onSort={() => sToggle('totalTrades')} />
                <Th label="SL/Tgt Hits" title="SL hits / Target hits" />
                <Th label="Cycles" sortKey="cycleCount" currentKey={sKey} dir={sDir} onSort={() => sToggle('cycleCount')} />
                <Th label="Runtime" sortKey="runningMins" currentKey={sKey} dir={sDir} onSort={() => sToggle('runningMins')} />
                <Th label="Heartbeat" />
              </tr>
            </thead>
            <tbody>
              {sortedStrategies.length === 0 && (
                <tr>
                  <td colSpan={21} className="px-4 py-8 text-center text-muted-foreground text-sm">
                    No strategies match the current filters
                  </td>
                </tr>
              )}
              {sortedStrategies.map(m => {
                const isSelected = selectedInstanceId === m.instanceId
                return (
                  <tr
                    key={m.instanceId}
                    className={`border-b border-border/50 hover:bg-muted/30 cursor-pointer transition-colors ${isSelected ? 'border-l-2 border-l-primary bg-primary/5' : ''}`}
                    style={isSelected ? undefined : { background: pnlBg(m.totalPnL, 1) }}
                    onClick={() => setSelectedInstanceId(isSelected ? null : m.instanceId)}
                  >
                    <td className="px-3 py-2 pl-4 font-medium text-foreground whitespace-nowrap max-w-[180px] truncate">
                      <span title={m.strategy.strategy_name}>{m.strategy.strategy_name}</span>
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      {(m.strategy.status === 'RUNNING' || m.strategy.status === 'PAUSED') && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-7 w-7 p-0"
                          onClick={(e) => {
                            e.stopPropagation()
                            setSelectedStrategyForPnL({ instanceId: m.instanceId, name: m.strategy.strategy_name })
                            setIsPnLModalOpen(true)
                          }}
                          title="View P&L Curve"
                        >
                          <BarChart2 className="h-4 w-4" />
                        </Button>
                      )}
                    </td>
                    <td className="px-3 py-2 whitespace-nowrap"><StatusBadge status={m.strategy.status} /></td>
                    <td className="px-3 py-2 whitespace-nowrap"><HealthDot health={m.health} /></td>
                    <td className="px-3 py-2 font-mono font-semibold text-foreground">{m.underlying}</td>
                    <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">{m.expiry}</td>
                    <td className="px-3 py-2 font-mono text-center">
                      {m.openLots > 0
                        ? <span className="text-emerald-500 font-semibold">{m.openLots}</span>
                        : <span className="text-muted-foreground">0</span>}
                    </td>
                    <td className="px-3 py-2"><PnLCell value={m.realizedPnL} /></td>
                    <td className="px-3 py-2"><PnLCell value={m.unrealizedPnL} /></td>
                    <td className="px-3 py-2"><PnLCell value={m.totalPnL} /></td>
                    <td className="px-3 py-2 font-semibold"><PnLCell value={m.netPnL} /></td>
                    <td className="px-3 py-2 text-muted-foreground font-mono">
                      {m.totalBrokerage > 0 ? `₹${m.totalBrokerage.toFixed(0)}` : '—'}
                    </td>
                    <td className="px-3 py-2">
                      <WinRateBar rate={m.winRate} closedCount={m.closedTradeCount} />
                    </td>
                    <td className="px-3 py-2"><PnLCell value={m.avgClosedTradePnL} /></td>
                    <td className="px-3 py-2">
                      {m.maxDrawdown > 0
                        ? <span className="text-red-500 font-mono text-sm">₹{m.maxDrawdown.toFixed(0)}</span>
                        : <span className="text-muted-foreground text-sm">₹0</span>}
                    </td>
                    <td className="px-3 py-2 text-center">
                      <span className={`font-mono font-semibold ${m.openLegs > 0 ? 'text-emerald-500' : 'text-muted-foreground'}`}>
                        {m.openLegs}/{m.totalLegs}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-center font-mono">{m.totalTrades}</td>
                    <td className="px-3 py-2 whitespace-nowrap">
                      <span className="text-red-400 font-mono">{m.slHits}</span>
                      <span className="text-muted-foreground mx-0.5">/</span>
                      <span className="text-emerald-400 font-mono">{m.targetHits}</span>
                    </td>
                    <td className="px-3 py-2 text-center font-mono text-muted-foreground">{m.cycleCount || '—'}</td>
                    <td className="px-3 py-2 text-center font-mono text-muted-foreground whitespace-nowrap">
                      {m.runningMins !== null
                        ? m.runningMins >= 60
                          ? `${Math.floor(m.runningMins / 60)}h ${Math.floor(m.runningMins % 60)}m`
                          : `${Math.floor(m.runningMins)}m`
                        : '—'}
                    </td>
                    <td className="px-3 py-2 text-muted-foreground font-mono whitespace-nowrap">
                      {heartbeatAge(m.strategy.last_heartbeat)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>

        <div className="px-4 py-2 border-t bg-muted/20 text-[10px] text-muted-foreground flex items-center justify-between">
          <span>
            {sortedStrategies.length} of {allMetrics.length} strategies
            {selectedInstanceId && <span className="ml-2 text-primary font-semibold">· 1 strategy selected — click row again to clear</span>}
          </span>
          <span>Click a row to filter open legs and trades below</span>
        </div>
      </div>

      {/* ─── Zone 3 & 4: Legs + Trade History + Health tabs ─── */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="h-9 text-sm">
          <TabsTrigger value="open-legs" className="h-8 text-sm px-3">
            Open Legs
            {openLegRows.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 h-4 px-1.5 text-[10px]">{openLegRows.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="trade-history" className="h-8 text-sm px-3">
            Trade History
            {closedTradeRows.length > 0 && (
              <Badge variant="secondary" className="ml-1.5 h-4 px-1.5 text-[10px]">{closedTradeRows.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="strategy-health" className="h-8 text-sm px-3">
            Health Monitor
          </TabsTrigger>
        </TabsList>

        {/* ── Open Legs ── */}
        <TabsContent value="open-legs" className="mt-2">
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead className="border-b bg-muted/20">
                  <tr>
                    <Th label="Strategy" sortKey="strategyName" currentKey={lKey} dir={lDir} onSort={() => lToggle('strategyName')} className="pl-4 min-w-[120px]" />
                    <Th label="Symbol" sortKey="symbol" currentKey={lKey} dir={lDir} onSort={() => lToggle('symbol')} />
                    <Th
                      label="Qty"
                      sortKey="signedQty" currentKey={lKey} dir={lDir} onSort={() => lToggle('signedQty')}
                      title="Positive = BUY position, Negative = SELL (short) position"
                    />
                    <Th label="Entry" sortKey="entryPrice" currentKey={lKey} dir={lDir} onSort={() => lToggle('entryPrice')} />
                    <Th label="LTP" sortKey="ltp" currentKey={lKey} dir={lDir} onSort={() => lToggle('ltp')} />
                    <Th label="Unrealized P&L" sortKey="pnl" currentKey={lKey} dir={lDir} onSort={() => lToggle('pnl')} />
                    <Th label="SL" sortKey="slPrice" currentKey={lKey} dir={lDir} onSort={() => lToggle('slPrice')} />
                    <Th label="Target" sortKey="targetPrice" currentKey={lKey} dir={lDir} onSort={() => lToggle('targetPrice')} />
                    <Th label="Re-entries" sortKey="reentryCount" currentKey={lKey} dir={lDir} onSort={() => lToggle('reentryCount')} />
                    <Th label="Entry Time" sortKey="entryTime" currentKey={lKey} dir={lDir} onSort={() => lToggle('entryTime')} />
                  </tr>
                </thead>
                <tbody>
                  {pagedLegs.length === 0 && (
                    <tr>
                      <td colSpan={10} className="px-4 py-8 text-center text-muted-foreground text-sm">
                        No open legs{selectedInstanceId ? ' for selected strategy' : ''}
                      </td>
                    </tr>
                  )}
                  {pagedLegs.map(row => (
                    <tr
                      key={`${row.instanceId}-${row.legKey}`}
                      className="border-b border-border/50 hover:bg-muted/20 transition-colors"
                      style={{ background: row.pnl !== null ? pnlBg(row.pnl, 0.8) : undefined }}
                    >
                      <td className="px-3 py-1.5 pl-4 font-medium text-foreground whitespace-nowrap max-w-[160px] truncate">
                        {row.strategyName}
                      </td>
                      <td className="px-3 py-1.5 font-mono font-semibold text-foreground whitespace-nowrap">
                        {row.symbol}
                      </td>
                      {/* Signed qty: negative number shown in red for SELL short positions */}
                      <td className="px-3 py-1.5 font-mono text-center font-semibold">
                        <span className={row.signedQty < 0 ? 'text-red-500' : 'text-emerald-500'}>
                          {row.signedQty > 0 ? `+${row.signedQty}` : row.signedQty}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 font-mono">
                        {row.entryPrice !== null ? row.entryPrice.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-muted-foreground">
                        {row.ltp !== null ? row.ltp.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-1.5">
                        <PnLCell value={row.pnl} />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-red-400">
                        {row.slPrice !== null ? row.slPrice.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-emerald-400">
                        {row.targetPrice !== null ? row.targetPrice.toFixed(2) : '—'}
                      </td>
                      <td className="px-3 py-1.5 text-center font-mono text-muted-foreground">
                        {row.reentryCount}/{row.reentryLimit ?? '∞'}
                      </td>
                      <td className="px-3 py-1.5 font-mono text-muted-foreground whitespace-nowrap">
                        {formatSmartTime(row.entryTime)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={legsPage} total={sortedLegs.length} pageSize={PAGE_SIZE} onChange={setLegsPage} />
            <div className="px-4 py-1.5 border-t bg-muted/20 text-[10px] text-muted-foreground">
              {openLegRows.length} open leg{openLegRows.length !== 1 ? 's' : ''}
              {selectedInstanceId ? ' (filtered to selected strategy)' : ' across all strategies'}
              · Qty: <span className="text-emerald-500">+N = BUY</span>, <span className="text-red-500">−N = SELL short</span>
              · Unrealized P&L from last known LTP
            </div>
          </div>
        </TabsContent>

        {/* ── Trade History ── */}
        <TabsContent value="trade-history" className="mt-2">
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead className="border-b bg-muted/20">
                  <tr>
                    <Th label="Strategy" sortKey="strategyName" currentKey={tKey} dir={tDir} onSort={() => tToggle('strategyName')} className="pl-4 min-w-[120px]" />
                    <Th label="Symbol" sortKey="symbol" currentKey={tKey} dir={tDir} onSort={() => tToggle('symbol')} />
                    <Th label="Type" sortKey="option_type" currentKey={tKey} dir={tDir} onSort={() => tToggle('option_type')} />
                    <Th label="Side" sortKey="side" currentKey={tKey} dir={tDir} onSort={() => tToggle('side')} />
                    <Th label="Qty" sortKey="quantity" currentKey={tKey} dir={tDir} onSort={() => tToggle('quantity')} />
                    <Th label="Entry" sortKey="entry_price" currentKey={tKey} dir={tDir} onSort={() => tToggle('entry_price')} />
                    <Th label="Exit" sortKey="exit_price" currentKey={tKey} dir={tDir} onSort={() => tToggle('exit_price')} />
                    <Th label="P&L" sortKey="pnl" currentKey={tKey} dir={tDir} onSort={() => tToggle('pnl')} />
                    <Th label="Exit Type" sortKey="exit_type" currentKey={tKey} dir={tDir} onSort={() => tToggle('exit_type')} />
                    <Th label="SL" sortKey="sl_price" currentKey={tKey} dir={tDir} onSort={() => tToggle('sl_price')} />
                    <Th label="Target" sortKey="target_price" currentKey={tKey} dir={tDir} onSort={() => tToggle('target_price')} />
                    <Th label="Re-entries" sortKey="reentry_count_at_exit" currentKey={tKey} dir={tDir} onSort={() => tToggle('reentry_count_at_exit')} />
                    <Th label="Brokerage" sortKey="total_brokerage" currentKey={tKey} dir={tDir} onSort={() => tToggle('total_brokerage')} />
                    <Th label="Entry Time" sortKey="entry_time" currentKey={tKey} dir={tDir} onSort={() => tToggle('entry_time')} />
                    <Th label="Exit Time" sortKey="exit_time" currentKey={tKey} dir={tDir} onSort={() => tToggle('exit_time')} />
                  </tr>
                </thead>
                <tbody>
                  {pagedTrades.length === 0 && (
                    <tr>
                      <td colSpan={15} className="px-4 py-8 text-center text-muted-foreground text-sm">
                        No closed trades{selectedInstanceId ? ' for selected strategy' : ''}
                      </td>
                    </tr>
                  )}
                  {pagedTrades.map(t => {
                    const exitColor = exitTypeColor[t.exit_type ?? ''] ?? 'text-muted-foreground'
                    const entryPrice = resolveNum(t.entry_price)
                    const exitPrice = resolveNum(t.exit_price)
                    const slPrice = resolveNum(t.sl_price)
                    const targetPrice = resolveNum(t.target_price)
                    return (
                      <tr
                        key={`${t.instanceId}-${t.trade_id}`}
                        className="border-b border-border/50 hover:bg-muted/20 transition-colors"
                        style={{ background: pnlBg(t.pnl ?? 0, 0.7) }}
                      >
                        <td className="px-3 py-1.5 pl-4 font-medium text-foreground whitespace-nowrap max-w-[160px] truncate">
                          {t.strategyName}
                        </td>
                        <td className="px-3 py-1.5 font-mono font-semibold whitespace-nowrap">{t.symbol}</td>
                        <td className="px-3 py-1.5 text-muted-foreground">{t.option_type}</td>
                        <td className="px-3 py-1.5">
                          <span className={`font-semibold ${t.side === 'BUY' ? 'text-emerald-500' : 'text-red-500'}`}>
                            {t.side}
                          </span>
                        </td>
                        <td className="px-3 py-1.5 font-mono text-center">{t.quantity}</td>
                        <td className="px-3 py-1.5 font-mono">{entryPrice !== null ? entryPrice.toFixed(2) : '—'}</td>
                        <td className="px-3 py-1.5 font-mono">{exitPrice !== null ? exitPrice.toFixed(2) : '—'}</td>
                        <td className="px-3 py-1.5 font-semibold"><PnLCell value={t.pnl} /></td>
                        <td className="px-3 py-1.5">
                          <span className={`font-semibold text-[11px] ${exitColor}`}>{t.exit_type ?? '—'}</span>
                        </td>
                        <td className="px-3 py-1.5 font-mono text-red-400">
                          {slPrice !== null ? slPrice.toFixed(2) : '—'}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-emerald-400">
                          {targetPrice !== null ? targetPrice.toFixed(2) : '—'}
                        </td>
                        <td className="px-3 py-1.5 text-center font-mono text-muted-foreground">
                          {t.reentry_count_at_exit ?? 0}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-muted-foreground">
                          {t.total_brokerage ? `₹${resolveNum(t.total_brokerage)?.toFixed(0)}` : '—'}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-muted-foreground whitespace-nowrap">
                          {formatSmartTime(t.entry_time)}
                        </td>
                        <td className="px-3 py-1.5 font-mono text-muted-foreground whitespace-nowrap">
                          {formatSmartTime(t.exit_time)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <Pagination page={tradesPage} total={sortedTrades.length} pageSize={PAGE_SIZE} onChange={setTradesPage} />
            <div className="px-4 py-1.5 border-t bg-muted/20 text-[10px] text-muted-foreground">
              {closedTradeRows.length} closed trade{closedTradeRows.length !== 1 ? 's' : ''}
              {selectedInstanceId ? ' (filtered)' : ' across all strategies'}
              · Sorted by exit time (latest first) by default
            </div>
          </div>
        </TabsContent>

        {/* ── Health Monitor ── */}
        <TabsContent value="strategy-health" className="mt-2">
          <div className="rounded-lg border bg-card overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm border-collapse">
                <thead className="border-b bg-muted/20">
                  <tr>
                    <Th label="Strategy" className="pl-4 min-w-[140px]" />
                    <Th label="Instance ID" />
                    <Th label="Status" />
                    <Th label="Health" />
                    <Th label="PID" />
                    <Th label="Last Heartbeat" />
                    <Th label="Started At" />
                    <Th label="Last Updated" />
                    <Th label="Completed At" />
                    <Th label="Cycles" />
                    <Th label="Version" />
                  </tr>
                </thead>
                <tbody>
                  {allMetrics.map(m => (
                    <tr key={m.strategy.instance_id} className="border-b border-border/50 hover:bg-muted/20">
                      <td className="px-3 py-2 pl-4 font-medium whitespace-nowrap">{m.strategy.strategy_name}</td>
                      <td className="px-3 py-2 font-mono text-muted-foreground text-[11px] whitespace-nowrap max-w-[140px] truncate" title={m.strategy.instance_id}>
                        {m.strategy.instance_id}
                      </td>
                      <td className="px-3 py-2"><StatusBadge status={m.strategy.status} /></td>
                      <td className="px-3 py-2"><HealthDot health={m.health} /></td>
                      <td className="px-3 py-2 font-mono text-muted-foreground">{m.strategy.pid ?? '—'}</td>
                      <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">
                        {formatTime(m.strategy.last_heartbeat)}
                        {m.strategy.last_heartbeat && (
                          <span className="ml-1 text-[10px] opacity-60">({heartbeatAge(m.strategy.last_heartbeat)} ago)</span>
                        )}
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">
                        {formatTime(m.strategy.orchestrator?.start_time ?? m.strategy.created_at)}
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">
                        {formatTime(m.strategy.last_updated)}
                      </td>
                      <td className="px-3 py-2 font-mono text-muted-foreground whitespace-nowrap">
                        {formatTime(m.strategy.completed_at)}
                      </td>
                      <td className="px-3 py-2 font-mono text-center text-muted-foreground">
                        {m.strategy.orchestrator?.cycle_count ?? '—'}
                      </td>
                      <td className="px-3 py-2 font-mono text-center text-muted-foreground">
                        {m.strategy.version ?? '—'}
                      </td>
                    </tr>
                  ))}
                  {allMetrics.length === 0 && (
                    <tr>
                      <td colSpan={11} className="px-4 py-8 text-center text-muted-foreground text-sm">No strategies found</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </TabsContent>
      </Tabs>

      {/* ─── P&L Curve Modal ─── */}
      <Dialog open={isPnLModalOpen} onOpenChange={setIsPnLModalOpen}>
        <DialogContent 
          className="max-h-[90vh] overflow-y-auto p-0"
          style={{ width: '80vw', maxWidth: '80vw' }}
        >
          <DialogHeader className="px-6 pt-6 pb-4 border-b">
            <DialogTitle className="text-lg">
              {selectedStrategyForPnL?.name ? `${selectedStrategyForPnL.name} — P&L Curve` : 'Strategy P&L Curve'}
            </DialogTitle>
          </DialogHeader>
          <div className="p-6">
            {selectedStrategyForPnL && (
              <StrategyPnLChart
                instanceId={selectedStrategyForPnL.instanceId}
                strategyName={selectedStrategyForPnL.name}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  )
}
