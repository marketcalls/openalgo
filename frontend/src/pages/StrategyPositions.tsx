import {
  BarChart2,
  ChevronDown,
  ChevronRight,
  CircleDot,
  ExternalLink,
  RefreshCw,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import StrategyPnLChart from '@/components/StrategyPnLChart'
import { Switch } from '@/components/ui/switch'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { createManualStrategyLeg, createStrategyOverride, deleteStrategyState, getStrategyStates, manualExitLeg } from '@/api/strategy-state'
import { tradingApi } from '@/api/trading'
import { useAlertStore } from '@/stores/alertStore'
import { useAuthStore } from '@/stores/authStore'
import { useLivePrice } from '@/hooks/useLivePrice'
import type { LegPairConfig, LegState, LegStatus, StrategyState, TradeHistoryRecord, ExitType, OverrideType } from '@/types/strategy-state'
import type { Position } from '@/types/trading'


// Status badge colors
const statusColors: Record<string, string> = {
  RUNNING: 'bg-green-500',
  PAUSED: 'bg-yellow-500',
  COMPLETED: 'bg-gray-400',
  ERROR: 'bg-red-500',
}

// ---- Strategy health (heartbeat-based) ----
type StrategyHealth = 'alive' | 'stale' | 'dead' | 'unknown'

const HEALTH_STALE_SECONDS = 30   // heartbeat older than 30s → stale
const HEALTH_DEAD_SECONDS  = 60   // heartbeat older than 60s → dead/crashed

function getStrategyHealth(strategy: StrategyState): StrategyHealth {
  // Completed strategies are neither alive nor dead — not applicable
  if (strategy.status === 'COMPLETED') return 'unknown'
  if (!strategy.last_heartbeat) return 'unknown'

  const lastBeat = new Date(strategy.last_heartbeat).getTime()
  // Guard against malformed/unparseable timestamp strings
  if (Number.isNaN(lastBeat)) return 'unknown'

  const nowMs   = Date.now()
  const ageSecs = (nowMs - lastBeat) / 1000

  if (ageSecs < HEALTH_STALE_SECONDS) return 'alive'
  if (ageSecs < HEALTH_DEAD_SECONDS)  return 'stale'
  return 'dead'
}

function formatHeartbeatAge(lastHeartbeat: string | null): string {
  if (!lastHeartbeat) return 'never'
  const ageSecs = (Date.now() - new Date(lastHeartbeat).getTime()) / 1000
  if (ageSecs < 5)   return 'just now'
  if (ageSecs < 60)  return `${Math.floor(ageSecs)}s ago`
  if (ageSecs < 3600) return `${Math.floor(ageSecs / 60)}m ago`
  return `${Math.floor(ageSecs / 3600)}h ago`
}

const healthConfig: Record<StrategyHealth, { label: string; dot: string; badge: string; title: string }> = {
  alive:   { label: 'Live',     dot: 'bg-green-400',  badge: 'border-green-500 text-green-600 dark:text-green-400',  title: 'Strategy is running — heartbeat is current' },
  stale:   { label: 'Stale',    dot: 'bg-yellow-400', badge: 'border-yellow-500 text-yellow-600 dark:text-yellow-400', title: 'No heartbeat for 30–60s — script may be slow or stuck' },
  dead:    { label: 'No Signal',dot: 'bg-red-500',    badge: 'border-red-500 text-red-600 dark:text-red-400',        title: 'No heartbeat for >60s — script is likely crashed or stopped' },
  unknown: { label: 'Unknown',  dot: 'bg-gray-400',   badge: 'border-gray-400 text-gray-500',                        title: 'No heartbeat data available' },
}

function HealthBadge({ strategy }: { strategy: StrategyState }) {
  const health = getStrategyHealth(strategy)
  if (health === 'unknown') return null

  const cfg = healthConfig[health]
  const ageText = formatHeartbeatAge(strategy.last_heartbeat)
  const isAlive = health === 'alive'

  const pidText = strategy.pid ? `PID: ${strategy.pid}` : 'PID: unknown'
  const tooltipText = `${cfg.title}\nLast heartbeat: ${ageText}\n${pidText}`

  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium ${cfg.badge}`}
      title={tooltipText}
    >
      {/* Pulsing dot for alive, static for others */}
      <span className="relative flex h-2 w-2 items-center justify-center">
        {isAlive && (
          <span className={`absolute inline-flex h-full w-full animate-ping rounded-full ${cfg.dot} opacity-60`} />
        )}
        <span className={`relative inline-flex h-2 w-2 rounded-full ${cfg.dot}`} />
      </span>
      {cfg.label}
      <span className="opacity-60">· {ageText}</span>
    </span>
  )
}

// Leg status colors
const legStatusColors: Record<LegStatus, string> = {
  IDLE: 'bg-gray-400',
  PENDING_ENTRY: 'bg-blue-400',
  IN_POSITION: 'bg-green-500',
  PENDING_EXIT: 'bg-orange-400',
  EXITED_WAITING_REENTRY: 'bg-yellow-500',
  EXITED_WAITING_REEXECUTE: 'bg-purple-500',
  DONE: 'bg-gray-500',
}

// Exit type colors
const exitTypeColors: Record<ExitType, string> = {
  SL_HIT: 'bg-red-500',
  FIXED_SL: 'bg-red-500',
  TRAIL_SL: 'bg-orange-500',
  TARGET_HIT: 'bg-green-500',
  TARGET: 'bg-green-500',
  HEDGE_SL_EXIT: 'bg-red-400',
  HEDGE_TARGET_EXIT: 'bg-green-400',
  STRATEGY_DONE: 'bg-gray-500',
  AUTO_BUYBACK: 'bg-blue-500',
  MANUAL_EXIT: 'bg-purple-500',
  EXIT: 'bg-gray-400',
}

// Format currency in Indian format
function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const formatted = new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(value))
  return value < 0 ? `-${formatted}` : formatted
}

// Resolve a value that may be a plain number OR a {source, parsedValue} object
// (the Python strategy persists some numeric fields in that wrapped format).
function resolveNum(value: unknown): number | null {
  if (value === null || value === undefined) return null
  if (typeof value === 'number') return value
  if (typeof value === 'object' && 'parsedValue' in (value as object)) {
    const pv = (value as { parsedValue: unknown }).parsedValue
    return typeof pv === 'number' ? pv : null
  }
  return null
}

// Format price
function formatPrice(value: unknown): string {
  const num = resolveNum(value)
  if (num === null) return '—'
  return num.toFixed(2)
}

function computePlannedEntryPrice(leg: LegState): number | null {
  if (leg.wait_trigger_price) {
    return leg.wait_trigger_price;
  }
  const baseline = leg.wait_baseline_price
  const pct = leg.wait_trade_percent

  if (baseline === null || baseline === undefined) return null
  if (pct === null || pct === undefined) return null
  if (!leg.side) return null

  // BUY: enter when LTP >= baseline * (1 + pct)
  // SELL: enter when LTP <= baseline * (1 - pct)
  if (leg.side === 'BUY') return baseline * (1 + pct)
  if (leg.side === 'SELL') return baseline * (1 - pct)

  return null
}

// Format datetime
function formatDateTime(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  const date = new Date(isoString)
  return date.toLocaleString('en-IN', {
    day: '2-digit',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
    timeZone: 'Asia/Kolkata',
  })
}

// Format time only for today, date + time for older entries
function formatTime(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  const date = new Date(isoString)

  // Get today's date in IST
  const nowIST = new Date(new Date().toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const todayStart = new Date(nowIST.getFullYear(), nowIST.getMonth(), nowIST.getDate())

  // Get the entry date in IST
  const entryIST = new Date(date.toLocaleString('en-US', { timeZone: 'Asia/Kolkata' }))
  const entryStart = new Date(entryIST.getFullYear(), entryIST.getMonth(), entryIST.getDate())

  // Check if it's today
  const isToday = todayStart.getTime() === entryStart.getTime()

  if (isToday) {
    // Today: show time only
    return date.toLocaleTimeString('en-IN', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Kolkata',
    })
  } else {
    // Older: show date + time
    return date.toLocaleString('en-IN', {
      day: '2-digit',
      month: 'short',
      hour: '2-digit',
      minute: '2-digit',
      timeZone: 'Asia/Kolkata',
    })
  }
}

// P&L display component
function PnLDisplay({ value, showIcon = true }: { value: number | null | undefined; showIcon?: boolean }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">-</span>
  const isPositive = value >= 0
  const color = isPositive ? 'text-green-600' : 'text-red-600'
  return (
    <span className={`font-medium ${color} flex items-center gap-1`}>
      {showIcon && (isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />)}
      {formatCurrency(value)}
    </span>
  )
}

function computeUnrealizedPnlForLeg(leg: LegState, ltp: number | undefined): number | null {
  const entry = leg.entry_price
  const qty = leg.quantity
  const side = leg.side

  if (ltp === null || ltp === undefined) return null
  if (entry === null || entry === undefined || qty === null || qty === undefined || !side) return null

  if (side === 'BUY') return (ltp - entry) * qty
  if (side === 'SELL') return (entry - ltp) * qty

  return null
}

function sumTradeHistoryPnl(trades: TradeHistoryRecord[] | null | undefined): number {
  if (!trades || trades.length === 0) return 0
  return trades.reduce((sum, t) => sum + (t.pnl || 0), 0)
}

// Compute consolidated stats for a DONE leg from trade history.
// Falls back to the leg object itself when no trade_history records exist
// (this happens when trade_history was lost due to the stale in-memory
// overwrite bug — the legs dict is always the ground truth for entry data).
function getDoneLegStats(
  legKey: string,
  tradeHistory: TradeHistoryRecord[] | null | undefined,
  leg?: LegState,
) {
  const legTrades = (tradeHistory ?? []).filter((t) => t.leg_key === legKey)
  if (legTrades.length === 0) {
    // No trade_history records — fall back to leg data for what we have.
    // exit_price is not stored on the leg object so it remains unknown.
    return {
      avgEntryPrice: leg ? resolveNum(leg.entry_price) : null,
      avgExitPrice: null,
      firstEntryTime: leg?.entry_time ?? null,
      lastExitTime: null,
      slHits: 0,
      targetHits: 0,
      totalBrokerage: resolveNum(leg?.total_brokerage) ?? 0,
    }
  }

  // Qty-weighted average entry price: Σ(entry_price × qty) / Σ(qty)
  const totalEntryQty = legTrades.reduce((sum, t) => sum + (t.quantity ?? 0), 0)
  const avgEntryPrice = totalEntryQty > 0
    ? legTrades.reduce((sum, t) => sum + (resolveNum(t.entry_price) ?? 0) * (t.quantity ?? 0), 0) / totalEntryQty
    : null

  // Qty-weighted average exit price (only trades with a valid exit_price)
  const exitTrades = legTrades.filter((t) => resolveNum(t.exit_price) !== null)
  const totalExitQty = exitTrades.reduce((sum, t) => sum + (t.quantity ?? 0), 0)
  const avgExitPrice = totalExitQty > 0
    ? exitTrades.reduce((sum, t) => sum + (resolveNum(t.exit_price)! * (t.quantity ?? 0)), 0) / totalExitQty
    : null

  // First entry time: min(entry_time)
  const entryTimes = legTrades.map((t) => t.entry_time).filter(Boolean) as string[]
  const firstEntryTime = entryTimes.length > 0
    ? entryTimes.reduce((min, t) => t < min ? t : min)
    : null

  // Last exit time: max(exit_time)
  const exitTimes = legTrades.map((t) => t.exit_time).filter(Boolean) as string[]
  const lastExitTime = exitTimes.length > 0
    ? exitTimes.reduce((max, t) => t > max ? t : max)
    : null

  // SL hits and Target hits counts
  const slHits = legTrades.filter((t) => t.exit_type === 'SL_HIT' || t.exit_type === 'FIXED_SL' || t.exit_type === 'TRAIL_SL').length
  const targetHits = legTrades.filter((t) => t.exit_type === 'TARGET_HIT' || t.exit_type === 'TARGET').length

  // Total brokerage cost
  const totalBrokerage = legTrades.reduce((sum, t) => sum + (resolveNum(t.total_brokerage) ?? 0), 0)

  return { avgEntryPrice, avgExitPrice, firstEntryTime, lastExitTime, slHits, targetHits, totalBrokerage }
}

// Editable Price Cell for SL/Target inline editing
function EditablePriceCell({
  value,
  instanceId,
  legKey,
  overrideType,
  leg,
  onSuccess,
}: {
  value: number | null | undefined
  instanceId: string
  legKey: string
  overrideType: OverrideType
  leg: LegState
  onSuccess: () => void
}) {
  const [isEditing, setIsEditing] = useState(false)
  const [editValue, setEditValue] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const inputRef = React.useRef<HTMLInputElement>(null)

  // Only allow editing for IN_POSITION status
  const canEdit = leg.status === 'IN_POSITION'

  const handleStartEdit = () => {
    if (!canEdit) return
    setEditValue(value?.toString() ?? '')
    setIsEditing(true)
  }

  // Focus input when editing starts
  React.useEffect(() => {
    if (isEditing && inputRef.current) {
      inputRef.current.focus()
      inputRef.current.select()
    }
  }, [isEditing])

  const validateValue = (newValue: number): string | null => {
    if (Number.isNaN(newValue) || newValue < 0) {
      return 'Value must be a non-negative number'
    }

    const entryPrice = leg.entry_price
    if (!entryPrice) return null // Can't validate without entry price

    const side = leg.side

    if (overrideType === 'sl_price') {
      // For SELL: SL should be above entry price (loss when price goes up)
      // For BUY: SL should be below entry price (loss when price goes down)
      if (side === 'SELL' && newValue <= entryPrice) {
        return `SL for SELL must be above entry price (${entryPrice.toFixed(2)})`
      }
      if (side === 'BUY' && newValue >= entryPrice) {
        return `SL for BUY must be below entry price (${entryPrice.toFixed(2)})`
      }
    }

    if (overrideType === 'target_price') {
      // For SELL: Target should be below entry price (profit when price goes down)
      // For BUY: Target should be above entry price (profit when price goes up)
      if (side === 'SELL' && newValue >= entryPrice) {
        return `Target for SELL must be below entry price (${entryPrice.toFixed(2)})`
      }
      if (side === 'BUY' && newValue <= entryPrice) {
        return `Target for BUY must be above entry price (${entryPrice.toFixed(2)})`
      }
    }

    return null
  }

  const handleSubmit = async () => {
    const newValue = Number.parseFloat(editValue)

    // Validate
    const error = validateValue(newValue)
    if (error) {
      toast.error(error)
      return
    }

    // Don't submit if value hasn't changed
    if (value !== null && value !== undefined && Math.abs(newValue - value) < 0.01) {
      setIsEditing(false)
      return
    }

    setIsSubmitting(true)
    try {
      const result = await createStrategyOverride(instanceId, legKey, overrideType, newValue)
      toast.success(result.message)
      setIsEditing(false)
      onSuccess()
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to update')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      handleSubmit()
    } else if (e.key === 'Escape') {
      setIsEditing(false)
    }
  }

  const handleBlur = () => {
    // Cancel on blur (only save on Enter)
    setIsEditing(false)
  }

  if (isEditing) {
    return (
      <Input
        ref={inputRef}
        type="number"
        step="0.05"
        value={editValue}
        onChange={(e) => setEditValue(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={handleBlur}
        disabled={isSubmitting}
        className="h-7 w-20 text-right text-sm px-1"
      />
    )
  }

  return (
    <span
      onClick={handleStartEdit}
      onKeyDown={(e) => e.key === 'Enter' && handleStartEdit()}
      tabIndex={canEdit ? 0 : undefined}
      role={canEdit ? 'button' : undefined}
      className={canEdit
        ? 'cursor-pointer hover:bg-muted px-1 py-0.5 rounded transition-colors'
        : ''
      }
      title={canEdit ? 'Click to edit' : undefined}
    >
      {formatPrice(value)}
    </span>
  )
}

// Current Positions Table
function CurrentPositionsTable({
  legs,
  instanceId,
  onRefresh,
  liveLtpByLegKey,
  onExitLeg,
}: {
  legs: Record<string, LegState> | null | undefined
  instanceId: string
  onRefresh: () => void
  liveLtpByLegKey?: Record<string, number | undefined>
  onExitLeg: (legKey: string, leg: LegState) => void
}) {
  if (!legs) {
    return <p className="text-muted-foreground text-sm py-4">No positions found</p>
  }

  const legEntries = Object.entries(legs)

  // Separate open positions vs pending/planned (waiting-to-enter) positions.
  // Exited trades should be represented in Trade History (trade_history), not here.
  const openPositions = legEntries.filter(([_, leg]) =>
    ['IN_POSITION', 'PENDING_EXIT'].includes(leg.status)
  )

  const pendingPlannedPositions = legEntries.filter(([_, leg]) =>
    ['IDLE', 'PENDING_ENTRY', 'EXITED_WAITING_REENTRY', 'EXITED_WAITING_REEXECUTE'].includes(leg.status)
  )

  if (legEntries.length === 0) {
    return <p className="text-muted-foreground text-sm py-4">No positions found</p>
  }

  return (
    <div className="space-y-4">
      {/* Open Positions */}
      {openPositions.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <CircleDot className="h-4 w-4 text-green-500" />
            Open Positions ({openPositions.length})
          </h4>
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Leg</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Entry</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">SL</TableHead>
                  <TableHead className="text-right">Target</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Gross P&L</TableHead>
                  <TableHead className="text-right">Brokerage</TableHead>
                  <TableHead className="text-right">Net P&L</TableHead>
                  <TableHead className="text-right">Reentry</TableHead>
                  <TableHead className="text-center">Action</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {openPositions.map(([legKey, leg]) => (
                  <TableRow key={legKey}>
                    <TableCell className="font-medium">
                      <div className="flex flex-col">
                        <span>{leg.leg_pair_name || legKey}</span>
                        {leg.is_main_leg && (
                          <span className="text-xs text-muted-foreground">Main</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{leg.symbol}</TableCell>
                    <TableCell>
                      {leg.side ? (
                        <Badge variant={leg.side === 'SELL' ? 'destructive' : 'default'}>
                          {leg.side}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">{leg.quantity}</TableCell>
                    <TableCell className="text-right">
                      <div className="flex flex-col">
                        <span>{formatPrice(leg.entry_price)}</span>
                        <span className="text-xs text-muted-foreground">{formatTime(leg.entry_time)}</span>
                      </div>
                    </TableCell>
                    <TableCell className="text-right">
                      {liveLtpByLegKey?.[legKey] === null || liveLtpByLegKey?.[legKey] === undefined
                        ? '-'
                        : formatPrice(liveLtpByLegKey?.[legKey])}
                    </TableCell>
                    <TableCell className="text-right">
                      <EditablePriceCell
                        value={leg.sl_price}
                        instanceId={instanceId}
                        legKey={legKey}
                        overrideType="sl_price"
                        leg={leg}
                        onSuccess={onRefresh}
                      />
                    </TableCell>
                    <TableCell className="text-right">
                      <EditablePriceCell
                        value={leg.target_price}
                        instanceId={instanceId}
                        legKey={legKey}
                        overrideType="target_price"
                        leg={leg}
                        onSuccess={onRefresh}
                      />
                    </TableCell>
                    <TableCell>
                      <Badge className={legStatusColors[leg.status]} variant="secondary">
                        {leg.status.replace(/_/g, ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      <PnLDisplay value={computeUnrealizedPnlForLeg(leg, liveLtpByLegKey?.[legKey])} />
                    </TableCell>
                    <TableCell className="text-right">
                      {(leg.total_brokerage ?? 0) > 0 ? (
                        <div className="flex flex-col items-end">
                          <span className="text-red-500 text-sm">−{formatCurrency(leg.total_brokerage ?? 0)}</span>
                          <span className="text-xs text-muted-foreground">
                            E:{formatCurrency(leg.entry_brokerage ?? 0)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-muted-foreground text-sm">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      {(() => {
                        const grossPnl = computeUnrealizedPnlForLeg(leg, liveLtpByLegKey?.[legKey])
                        const brokerage = leg.total_brokerage ?? 0
                        return <PnLDisplay value={grossPnl !== null ? grossPnl - brokerage : null} />
                      })()}
                    </TableCell>
                    <TableCell className="text-right">
                      {(leg.reentry_limit === null || leg.reentry_limit === undefined)
                        ? '-'
                        : `${leg.reentry_count ?? 0}/${leg.reentry_limit}`}
                    </TableCell>
                    <TableCell className="text-center">
                      {leg.status === 'IN_POSITION' && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => onExitLeg(legKey, leg)}
                          className="h-7 px-2 text-xs"
                        >
                          Exit
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Pending / Planned Trades */}
      {pendingPlannedPositions.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <CircleDot className="h-4 w-4 text-yellow-500" />
            Pending / Planned Trades ({pendingPlannedPositions.length})
          </h4>
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Leg</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">Planned Entry</TableHead>
                  <TableHead className="text-right">Planned SL</TableHead>
                  <TableHead className="text-right">Planned Target</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Reentry</TableHead>
                  <TableHead className="text-right">Reexec</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {pendingPlannedPositions.map(([legKey, leg]) => (
                  <TableRow key={legKey}>
                    <TableCell className="font-medium">
                      <div className="flex flex-col">
                        <span>{leg.leg_pair_name || legKey}</span>
                        {leg.is_main_leg && (
                          <span className="text-xs text-muted-foreground">Main</span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-xs">{leg.symbol}</TableCell>
                    <TableCell>
                      {leg.side ? (
                        <Badge variant={leg.side === 'SELL' ? 'destructive' : 'default'}>
                          {leg.side}
                        </Badge>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">{leg.quantity}</TableCell>
                    <TableCell className="text-right">
                      {liveLtpByLegKey?.[legKey] === null || liveLtpByLegKey?.[legKey] === undefined
                        ? '-'
                        : formatPrice(liveLtpByLegKey?.[legKey])}
                    </TableCell>
                    <TableCell className="text-right">{formatPrice(computePlannedEntryPrice(leg))}</TableCell>
                    <TableCell className="text-right">{formatPrice(leg.sl_price)}</TableCell>
                    <TableCell className="text-right">{formatPrice(leg.target_price)}</TableCell>
                    <TableCell>
                      <Badge className={legStatusColors[leg.status] || 'bg-gray-400'} variant="secondary">
                        {leg.status.replace(/_/g, ' ')}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-right">
                      {(leg.reentry_limit === null || leg.reentry_limit === undefined)
                        ? '-'
                        : `${leg.reentry_count ?? 0}/${leg.reentry_limit}`}
                    </TableCell>
                    <TableCell className="text-right">
                      {(leg.reexecute_limit === null || leg.reexecute_limit === undefined)
                        ? '-'
                        : `${leg.reexecute_count ?? 0}/${leg.reexecute_limit}`}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

    </div>
  )
}

// Done Legs Table (standalone — used in the Done Legs tab)
function DoneLegsTable({
  legs,
  tradeHistory,
}: {
  legs: Record<string, LegState> | null | undefined
  tradeHistory?: TradeHistoryRecord[] | null
}) {
  const donePositions = Object.entries(legs ?? {}).filter(([_, leg]) => leg.status === 'DONE')

  if (donePositions.length === 0) {
    return <p className="text-muted-foreground text-sm py-4">No done legs</p>
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <div className="max-h-[50vh] overflow-y-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Leg</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Avg Entry</TableHead>
              <TableHead className="text-right">Avg Exit</TableHead>
              <TableHead className="text-right">First Entry</TableHead>
              <TableHead className="text-right">Last Exit</TableHead>
              <TableHead className="text-right">SL Hits</TableHead>
              <TableHead className="text-right">Target Hits</TableHead>
              <TableHead className="text-right">Brokerage</TableHead>
              <TableHead className="text-right">Total P&L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {donePositions.map(([legKey, leg]) => {
              const stats = getDoneLegStats(legKey, tradeHistory, leg)
              return (
                <TableRow key={legKey}>
                  <TableCell className="font-medium">
                    <div className="flex flex-col">
                      <span>{leg.leg_pair_name || legKey}</span>
                      {leg.is_main_leg && (
                        <span className="text-xs text-muted-foreground">Main</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{leg.symbol}</TableCell>
                  <TableCell>
                    {leg.side ? (
                      <Badge variant={leg.side === 'SELL' ? 'destructive' : 'default'}>
                        {leg.side}
                      </Badge>
                    ) : (
                      <span className="text-muted-foreground">—</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">{leg.quantity}</TableCell>
                  <TableCell className="text-right">{formatPrice(stats.avgEntryPrice)}</TableCell>
                  <TableCell className="text-right">{formatPrice(stats.avgExitPrice)}</TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">{formatTime(stats.firstEntryTime)}</TableCell>
                  <TableCell className="text-right text-xs text-muted-foreground">{formatTime(stats.lastExitTime)}</TableCell>
                  <TableCell className="text-right">
                    {stats.slHits > 0
                      ? <span className="text-red-500 font-medium">{stats.slHits}</span>
                      : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {stats.targetHits > 0
                      ? <span className="text-green-500 font-medium">{stats.targetHits}</span>
                      : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    {stats.totalBrokerage > 0
                      ? <span className="text-red-500 text-sm">−{formatCurrency(stats.totalBrokerage)}</span>
                      : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex justify-end">
                      <PnLDisplay value={resolveNum(leg.total_pnl) ?? resolveNum(leg.realized_pnl)} />
                    </div>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// Trade History Table
function TradeHistoryTable({ trades }: { trades: TradeHistoryRecord[] | null | undefined }) {
  if (!trades || trades.length === 0) {
    return <p className="text-muted-foreground text-sm py-4">No trade history</p>
  }

  return (
    <div className="rounded-md border overflow-x-auto">
      <div className="max-h-[50vh] overflow-y-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>Leg</TableHead>
              <TableHead>Symbol</TableHead>
              <TableHead>Side</TableHead>
              <TableHead className="text-right">Qty</TableHead>
              <TableHead className="text-right">Entry</TableHead>
              <TableHead className="text-right">Exit</TableHead>
              <TableHead className="text-right">SL</TableHead>
              <TableHead className="text-right">Target</TableHead>
              <TableHead>Exit Type</TableHead>
              <TableHead className="text-right">Gross P&L</TableHead>
              <TableHead className="text-right">Brokerage</TableHead>
              <TableHead className="text-right">Net P&L</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {trades.map((trade) => {
              const tradeBrokerage = trade.total_brokerage ?? 0
              const tradeNetPnl = trade.pnl - tradeBrokerage
              return (
              <TableRow key={trade.trade_id}>
                <TableCell>{trade.trade_id}</TableCell>
                <TableCell className="font-medium">
                  <div className="flex flex-col">
                    <span>{trade.leg_pair_name || trade.leg_key}</span>
                    {trade.is_main_leg && (
                      <span className="text-xs text-muted-foreground">Main</span>
                    )}
                  </div>
                </TableCell>
                <TableCell className="font-mono text-xs">{trade.symbol}</TableCell>
                <TableCell>
                  <Badge variant={trade.side === 'SELL' ? 'destructive' : 'default'}>
                    {trade.side}
                  </Badge>
                </TableCell>
                <TableCell className="text-right">{trade.quantity}</TableCell>
                <TableCell className="text-right">
                  <div className="flex flex-col">
                    <span>{formatPrice(trade.entry_price)}</span>
                    <span className="text-xs text-muted-foreground">{formatTime(trade.entry_time)}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right">
                  <div className="flex flex-col">
                    <span>{formatPrice(trade.exit_price)}</span>
                    <span className="text-xs text-muted-foreground">{formatTime(trade.exit_time)}</span>
                  </div>
                </TableCell>
                <TableCell className="text-right">{formatPrice(trade.sl_price)}</TableCell>
                <TableCell className="text-right">{formatPrice(trade.target_price)}</TableCell>
                <TableCell>
                  {trade.exit_type && (
                    <Badge className={exitTypeColors[trade.exit_type]} variant="secondary">
                      {trade.exit_type.replace(/_/g, ' ')}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <PnLDisplay value={trade.pnl} />
                </TableCell>
                <TableCell className="text-right">
                  {tradeBrokerage > 0 ? (
                    <div className="flex flex-col items-end">
                      <span className="text-red-500 text-sm">−{formatCurrency(tradeBrokerage)}</span>
                      {(trade.entry_brokerage ?? 0) > 0 && (
                        <span className="text-xs text-muted-foreground">
                          E:{formatCurrency(trade.entry_brokerage ?? 0)} X:{formatCurrency(trade.exit_brokerage ?? 0)}
                        </span>
                      )}
                    </div>
                  ) : (
                    <span className="text-muted-foreground text-sm">—</span>
                  )}
                </TableCell>
                <TableCell className="text-right">
                  <PnLDisplay value={tradeBrokerage > 0 ? tradeNetPnl : trade.pnl} />
                </TableCell>
              </TableRow>
              )
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  )
}

// Strategy Accordion Item
/**
 * StrategyTabs — renders the Positions / Trade History / P&L Curve tabs for a strategy card.
 * StrategyPnLChart is only mounted (and therefore only fetches data) when the user
 * explicitly clicks the "📈 P&L Curve" tab — never on page load.
 */
function StrategyTabs({
  strategy,
  onRefresh,
  liveLtpByLegKey,
  onExitLeg,
}: {
  strategy: StrategyState
  onRefresh: () => void
  liveLtpByLegKey: Record<string, number | undefined>
  onExitLeg: (instanceId: string, legKey: string, leg: LegState) => void
}) {
  const [activeTab, setActiveTab] = useState('positions')

  const doneLegsCount = Object.values(strategy.legs ?? {}).filter((leg) => leg.status === 'DONE').length
  const positionsCount = Object.values(strategy.legs ?? {}).filter((leg) => leg.status !== 'DONE').length
  const tradeHistoryCount = strategy.trade_history?.length ?? 0

  return (
    <Tabs value={activeTab} onValueChange={setActiveTab}>
      <TabsList className="mb-3">
        <TabsTrigger value="positions">
          📊 Positions{positionsCount > 0 && (
            <span className="ml-1.5 rounded-full bg-gray-500 px-1.5 py-0.5 text-xs text-white leading-none">
              {positionsCount}
            </span>
          )}
        </TabsTrigger>
        <TabsTrigger value="done-legs">
          ✅ Done Legs{doneLegsCount > 0 && (
            <span className="ml-1.5 rounded-full bg-gray-500 px-1.5 py-0.5 text-xs text-white leading-none">
              {doneLegsCount}
            </span>
          )}
        </TabsTrigger>
        <TabsTrigger value="trade-history">
          📜 Trade History{tradeHistoryCount > 0 && (
            <span className="ml-1.5 rounded-full bg-gray-500 px-1.5 py-0.5 text-xs text-white leading-none">
              {tradeHistoryCount}
            </span>
          )}
        </TabsTrigger>
        <TabsTrigger value="pnl-curve">📈 P&L Curve</TabsTrigger>
      </TabsList>

      <TabsContent value="positions">
        <CurrentPositionsTable
          legs={strategy.legs}
          instanceId={strategy.instance_id}
          onRefresh={onRefresh}
          liveLtpByLegKey={liveLtpByLegKey}
          onExitLeg={(legKey, leg) => onExitLeg(strategy.instance_id, legKey, leg)}
        />
      </TabsContent>

      <TabsContent value="done-legs">
        <DoneLegsTable
          legs={strategy.legs}
          tradeHistory={strategy.trade_history}
        />
      </TabsContent>

      <TabsContent value="trade-history">
        <TradeHistoryTable trades={strategy.trade_history} />
      </TabsContent>

      <TabsContent value="pnl-curve">
        {/* Only mount StrategyPnLChart when tab is active — avoids API call on page load */}
        {activeTab === 'pnl-curve' && (
          <StrategyPnLChart
            instanceId={strategy.instance_id}
            strategyName={strategy.strategy_name}
          />
        )}
      </TabsContent>
    </Tabs>
  )
}

function StrategyAccordionItem({
  strategy,
  onDelete,
  onRefresh,
  liveLtpByLegKey,
  onAddManualLeg,
  onExitLeg,
  expandAll,
}: {
  strategy: StrategyState
  onDelete: (instanceId: string, strategyName: string) => void
  onRefresh: () => void
  liveLtpByLegKey: Record<string, number | undefined>
  onAddManualLeg: (strategy: StrategyState) => void
  onExitLeg: (instanceId: string, legKey: string, leg: LegState) => void
  expandAll: boolean
}) {
  const [isOpen, setIsOpen] = useState(expandAll)
  const [isLegPnlOpen, setIsLegPnlOpen] = useState(false)
  const [isConfigOpen, setIsConfigOpen] = useState(false)
  const config = strategy.config

  // React to expandAll prop changes
  useEffect(() => {
    setIsOpen(expandAll)
  }, [expandAll])

  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation() // Prevent accordion toggle
    onDelete(strategy.instance_id, strategy.strategy_name)
  }

  const legs = strategy.legs || {}
  const realizedPnl = useMemo(() => sumTradeHistoryPnl(strategy.trade_history), [strategy.trade_history])

  const unrealizedPnl = useMemo(() => {
    let total = 0
    for (const [legKey, leg] of Object.entries(legs)) {
      if (!['IN_POSITION', 'PENDING_EXIT'].includes(leg.status)) continue
      const pnl = computeUnrealizedPnlForLeg(leg, liveLtpByLegKey?.[legKey])
      if (pnl !== null) total += pnl
    }
    return total
  }, [legs, liveLtpByLegKey])

  const totalPnl = realizedPnl + unrealizedPnl

  // Total brokerage: sum from closed trades + entry brokerage from open legs
  const totalBrokerage = useMemo(() => {
    const closedBrokerage = (strategy.trade_history ?? []).reduce(
      (sum, t) => sum + (t.total_brokerage ?? 0),
      0
    )
    const openBrokerage = Object.values(legs)
      .filter((leg) => ['IN_POSITION', 'PENDING_EXIT'].includes(leg.status))
      .reduce((sum, leg) => sum + (leg.total_brokerage ?? 0), 0)
    return closedBrokerage + openBrokerage
  }, [strategy.trade_history, legs])

  const netPnl = totalPnl - totalBrokerage

  return (
    <Collapsible open={isOpen} onOpenChange={setIsOpen}>
      <Card className="mb-4">
        <CollapsibleTrigger asChild>
          <CardHeader className="cursor-pointer hover:bg-muted/50 transition-colors">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-3">
                {isOpen ? (
                  <ChevronDown className="h-5 w-5 text-muted-foreground" />
                ) : (
                  <ChevronRight className="h-5 w-5 text-muted-foreground" />
                )}
                <div>
                  <CardTitle className="text-lg">{strategy.strategy_name}</CardTitle>
                  <p className="text-sm text-muted-foreground mt-1">
                    {config && (
                      <>
                        {config.underlying} | Expiry: {config.expiry_date} |
                        Lots: {config.lots} × {config.lot_size}
                      </>
                    )}
                    {!config && `Instance: ${strategy.instance_id}`}
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <p className="text-sm text-muted-foreground">Total P&L</p>
                  <PnLDisplay value={totalPnl} />
                </div>
                <Badge className={statusColors[strategy.status] || 'bg-gray-400'}>
                  {strategy.status}
                </Badge>
                <HealthBadge strategy={strategy} />
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={strategy.status === 'COMPLETED'}
                    onClick={(e) => {
                      e.stopPropagation()
                      onAddManualLeg(strategy)
                    }}
                    title={strategy.status === 'COMPLETED' ? 'Cannot add positions to completed strategies' : 'Add a manual position'}
                  >
                    Add Position
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground hover:text-destructive"
                    onClick={handleDeleteClick}
                    title="Delete strategy state"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>
            </div>
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="pt-0 space-y-6">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-7 gap-4 p-4 bg-muted/30 rounded-lg">
              <div>
                <p className="text-xs text-muted-foreground">Open Positions</p>
                <p className="text-lg font-semibold">
                  {Object.values(strategy.legs || {}).filter((leg) =>
                    ['IN_POSITION', 'PENDING_EXIT'].includes(leg.status)
                  ).length}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Pending / Planned</p>
                <p className="text-lg font-semibold">
                  {Object.values(strategy.legs || {}).filter((leg) =>
                    ['IDLE', 'PENDING_ENTRY', 'EXITED_WAITING_REENTRY', 'EXITED_WAITING_REEXECUTE'].includes(leg.status)
                  ).length}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Total Trades</p>
                <p className="text-lg font-semibold">{strategy.trade_history?.length ?? 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Realized P&L</p>
                <PnLDisplay value={realizedPnl} showIcon={false} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Unrealized P&L</p>
                <PnLDisplay value={unrealizedPnl} showIcon={false} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Total Brokerage</p>
                {totalBrokerage > 0 ? (
                  <p className="text-lg font-semibold text-red-500">−{formatCurrency(totalBrokerage)}</p>
                ) : (
                  <p className="text-lg font-semibold text-muted-foreground">—</p>
                )}
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Net P&L</p>
                <PnLDisplay value={totalBrokerage > 0 ? netPnl : totalPnl} showIcon={false} />
              </div>
            </div>

            {/* Strategy Config (collapsed by default) */}
            {config && (
              <Collapsible open={isConfigOpen} onOpenChange={setIsConfigOpen}>
                <div className="flex items-center justify-between mb-2">
                  <h3 className="text-md font-semibold">Strategy Configuration</h3>
                  <CollapsibleTrigger asChild>
                    <Button variant="ghost" size="sm" className="h-8 px-2">
                      {isConfigOpen ? (
                        <ChevronDown className="h-4 w-4 mr-2" />
                      ) : (
                        <ChevronRight className="h-4 w-4 mr-2" />
                      )}
                      {isConfigOpen ? 'Hide' : 'Show'}
                    </Button>
                  </CollapsibleTrigger>
                </div>
                <CollapsibleContent>
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 text-sm border rounded-md p-4 bg-muted/20">
                    {/* Basic Settings */}
                    <div className="space-y-2">
                      <p className="font-semibold text-xs uppercase text-muted-foreground">Basic Settings</p>
                      {config.underlying && <p><span className="text-muted-foreground">Underlying:</span> <span className="font-medium">{config.underlying}</span></p>}
                      {config.expiry_date && <p><span className="text-muted-foreground">Expiry:</span> <span className="font-medium">{config.expiry_date}</span></p>}
                      {config.lots !== undefined && <p><span className="text-muted-foreground">Lots:</span> <span className="font-medium">{config.lots}</span></p>}
                      {config.lot_size !== undefined && <p><span className="text-muted-foreground">Lot Size:</span> <span className="font-medium">{config.lot_size}</span></p>}
                      {config.quantity !== undefined && <p><span className="text-muted-foreground">Quantity:</span> <span className="font-medium">{config.quantity}</span></p>}
                    </div>

                    {/* Execution Settings */}
                    <div className="space-y-2">
                      <p className="font-semibold text-xs uppercase text-muted-foreground">Execution</p>
                      {config.exchange && <p><span className="text-muted-foreground">Exchange:</span> <span className="font-medium">{config.exchange}</span></p>}
                      {config.product && <p><span className="text-muted-foreground">Product:</span> <span className="font-medium">{config.product}</span></p>}
                      {config.price_type && <p><span className="text-muted-foreground">Price Type:</span> <span className="font-medium">{config.price_type}</span></p>}
                      {config.poll_interval !== undefined && <p><span className="text-muted-foreground">Poll Interval:</span> <span className="font-medium">{config.poll_interval}s</span></p>}
                      {config.entry_time && <p><span className="text-muted-foreground">Entry Time:</span> <span className="font-medium">{config.entry_time}</span></p>}
                      {config.exit_time && <p><span className="text-muted-foreground">Exit Time:</span> <span className="font-medium">{config.exit_time}</span></p>}
                    </div>

                    {/* Risk Management */}
                    <div className="space-y-2">
                      <p className="font-semibold text-xs uppercase text-muted-foreground">Risk Management</p>
                      {config.sl_percent !== undefined && config.sl_percent !== null && <p><span className="text-muted-foreground">SL %:</span> <span className="font-medium">{(config.sl_percent * 100).toFixed(1)}%</span></p>}
                      {config.target_percent !== undefined && config.target_percent !== null && <p><span className="text-muted-foreground">Target %:</span> <span className="font-medium">{(config.target_percent * 100).toFixed(1)}%</span></p>}
                      {config.reentry_limit !== undefined && config.reentry_limit !== null && <p><span className="text-muted-foreground">Re-entry Limit:</span> <span className="font-medium">{config.reentry_limit}</span></p>}
                      {config.reexecute_limit !== undefined && config.reexecute_limit !== null && <p><span className="text-muted-foreground">Re-execute Limit:</span> <span className="font-medium">{config.reexecute_limit}</span></p>}
                    </div>

                    {/* Leg Pair Configs */}
                    {config.leg_pair_configs && Object.keys(config.leg_pair_configs).length > 0 && (
                      <div className="space-y-2 md:col-span-2 lg:col-span-3">
                        <p className="font-semibold text-xs uppercase text-muted-foreground">Leg Configurations</p>
                        <div className="grid gap-3 md:grid-cols-2">
                          {Object.values(config.leg_pair_configs).map((legConfig: LegPairConfig) => (
                            <div key={legConfig.name} className="border rounded p-3 bg-background/50">
                              <p className="font-medium mb-2">{legConfig.name}</p>
                              <div className="space-y-1 text-xs">
                                {legConfig.main_leg && <p><span className="text-muted-foreground">Main Leg:</span> <span className="font-medium">{legConfig.main_leg}</span></p>}
                                {legConfig.sl_percent !== undefined && legConfig.sl_percent !== null && <p><span className="text-muted-foreground">SL %:</span> <span className="font-medium">{(legConfig.sl_percent * 100).toFixed(1)}%</span></p>}
                                {legConfig.target_percent !== undefined && legConfig.target_percent !== null && <p><span className="text-muted-foreground">Target %:</span> <span className="font-medium">{(legConfig.target_percent * 100).toFixed(1)}%</span></p>}
                                {legConfig.trail_activation_percent !== undefined && legConfig.trail_activation_percent !== null && <p><span className="text-muted-foreground">Trail Activation %:</span> <span className="font-medium">{(legConfig.trail_activation_percent * 100).toFixed(1)}%</span></p>}
                                {legConfig.trail_sl_percent !== undefined && legConfig.trail_sl_percent !== null && <p><span className="text-muted-foreground">Trail SL %:</span> <span className="font-medium">{(legConfig.trail_sl_percent * 100).toFixed(1)}%</span></p>}
                                {legConfig.reentry_limit !== undefined && legConfig.reentry_limit !== null && <p><span className="text-muted-foreground">Re-entry Limit:</span> <span className="font-medium">{legConfig.reentry_limit}</span></p>}
                                {legConfig.reexecute_limit !== undefined && legConfig.reexecute_limit !== null && <p><span className="text-muted-foreground">Re-execute Limit:</span> <span className="font-medium">{legConfig.reexecute_limit}</span></p>}
                                {legConfig.ce_sell_offset && <p><span className="text-muted-foreground">CE Sell Offset:</span> <span className="font-medium">{legConfig.ce_sell_offset}</span></p>}
                                {legConfig.ce_buy_offset && <p><span className="text-muted-foreground">CE Buy Offset:</span> <span className="font-medium">{legConfig.ce_buy_offset}</span></p>}
                                {legConfig.pe_sell_offset && <p><span className="text-muted-foreground">PE Sell Offset:</span> <span className="font-medium">{legConfig.pe_sell_offset}</span></p>}
                                {legConfig.pe_buy_offset && <p><span className="text-muted-foreground">PE Buy Offset:</span> <span className="font-medium">{legConfig.pe_buy_offset}</span></p>}
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                </CollapsibleContent>
              </Collapsible>
            )}

            {/* Leg P&L Breakdown (collapsed by default) */}
            <Collapsible open={isLegPnlOpen} onOpenChange={setIsLegPnlOpen}>
              <div className="flex items-center justify-between">
                <h3 className="text-md font-semibold">Leg P&L</h3>
                <CollapsibleTrigger asChild>
                  <Button variant="ghost" size="sm" className="h-8 px-2">
                    {isLegPnlOpen ? (
                      <ChevronDown className="h-4 w-4 mr-2" />
                    ) : (
                      <ChevronRight className="h-4 w-4 mr-2" />
                    )}
                    {isLegPnlOpen ? 'Hide' : 'Show'}
                  </Button>
                </CollapsibleTrigger>
              </div>
              <CollapsibleContent>
                <div className="rounded-md border overflow-x-auto mt-2">
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Leg</TableHead>
                        <TableHead>Symbol</TableHead>
                        <TableHead>Status</TableHead>
                        <TableHead className="text-right">Realized P&L</TableHead>
                        <TableHead className="text-right">Unrealized P&L</TableHead>
                        <TableHead className="text-right">Gross P&L</TableHead>
                        <TableHead className="text-right">Brokerage</TableHead>
                        <TableHead className="text-right">Net P&L</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {Object.entries(legs).map(([legKey, leg]) => {
                        const unreal = ['IN_POSITION', 'PENDING_EXIT'].includes(leg.status)
                          ? computeUnrealizedPnlForLeg(leg, liveLtpByLegKey?.[legKey])
                          : 0
                        const realized = leg.realized_pnl ?? 0
                        const grossTotal = (leg.total_pnl ?? null) !== null && leg.total_pnl !== undefined
                          ? leg.total_pnl
                          : unreal === null
                            ? null
                            : realized + unreal
                        const legBrokerage = leg.total_brokerage ?? 0
                        const netTotal = grossTotal !== null ? grossTotal - legBrokerage : null

                        return (
                          <TableRow key={legKey}>
                            <TableCell className="font-medium">
                              <div className="flex flex-col">
                                <span>{leg.leg_pair_name || legKey}</span>
                                {leg.is_main_leg && (
                                  <span className="text-xs text-muted-foreground">Main</span>
                                )}
                              </div>
                            </TableCell>
                            <TableCell className="font-mono text-xs">{leg.symbol}</TableCell>
                            <TableCell>
                              <Badge className={legStatusColors[leg.status] || 'bg-gray-400'} variant="secondary">
                                {leg.status.replace(/_/g, ' ')}
                              </Badge>
                            </TableCell>
                            <TableCell className="text-right">
                              <PnLDisplay value={leg.realized_pnl} showIcon={false} />
                            </TableCell>
                            <TableCell className="text-right">
                              <PnLDisplay value={unreal} showIcon={false} />
                            </TableCell>
                            <TableCell className="text-right">
                              <PnLDisplay value={grossTotal} showIcon={false} />
                            </TableCell>
                            <TableCell className="text-right">
                              {legBrokerage > 0 ? (
                                <span className="text-red-500 text-sm">−{formatCurrency(legBrokerage)}</span>
                              ) : (
                                <span className="text-muted-foreground text-sm">—</span>
                              )}
                            </TableCell>
                            <TableCell className="text-right">
                              <PnLDisplay value={netTotal} showIcon={false} />
                            </TableCell>
                          </TableRow>
                        )
                      })}
                    </TableBody>
                  </Table>
                </div>
              </CollapsibleContent>
            </Collapsible>

            {/* Last Updated */}
            {strategy.last_updated && (
              <p className="text-xs text-muted-foreground">
                Last updated: {formatDateTime(strategy.last_updated)}
                {strategy.orchestrator && ` | Cycles: ${strategy.orchestrator.cycle_count}`}
              </p>
            )}

            {/* Positions / Trade History / P&L Curve Tabs */}
            <StrategyTabs
              strategy={strategy}
              onRefresh={onRefresh}
              liveLtpByLegKey={liveLtpByLegKey}
              onExitLeg={onExitLeg}
            />
          </CardContent>
        </CollapsibleContent>
      </Card>
    </Collapsible>
  )
}

// Main Component
export default function StrategyPositions() {
  const [strategies, setStrategies] = useState<StrategyState[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const { apiKey } = useAuthStore()
  const [manualDialogOpen, setManualDialogOpen] = useState(false)
  const [manualDialogStrategy, setManualDialogStrategy] = useState<StrategyState | null>(null)
  const [manualPositions, setManualPositions] = useState<Position[]>([])
  const [manualLoading, setManualLoading] = useState(false)
  const [manualError, setManualError] = useState<string | null>(null)
  const [manualSelectedKey, setManualSelectedKey] = useState<string>('')
  const [manualLegPairName, setManualLegPairName] = useState('')
  const [manualIsMainLeg, setManualIsMainLeg] = useState(true)
  const [manualSlPercent, setManualSlPercent] = useState('')
  const [manualTargetPercent, setManualTargetPercent] = useState('')
  const [manualReentryLimit, setManualReentryLimit] = useState('')
  const [manualReexecuteLimit, setManualReexecuteLimit] = useState('')
  const [manualSubmitting, setManualSubmitting] = useState(false)

  // New Manual Trade State
  const [manualMode, setManualMode] = useState<'TRACK' | 'NEW'>('TRACK')
  const [manualNewSymbol, setManualNewSymbol] = useState('')
  const [manualNewExchange, setManualNewExchange] = useState('NFO')
  const [manualNewProduct, setManualNewProduct] = useState('NRML')
  const [manualNewQty, setManualNewQty] = useState('')
  const [manualNewSide, setManualNewSide] = useState<'BUY' | 'SELL'>('SELL')
  const [manualWaitPercent, setManualWaitPercent] = useState('')
  const [manualWaitBaseline, setManualWaitBaseline] = useState('')

  const AUTO_REFRESH_ENABLED_KEY = 'strategy_positions_auto_refresh_enabled'
  const AUTO_REFRESH_SECONDS_KEY = 'strategy_positions_auto_refresh_seconds'
  const EXPAND_ALL_KEY = 'strategy_positions_expand_all'

  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)
  const [autoRefreshSeconds, setAutoRefreshSeconds] = useState(10)
  const [expandAll, setExpandAll] = useState(false)
  const isRefreshingRef = useRef(false)
  // Track previous health per instance_id to detect transitions
  const prevHealthRef = useRef<Map<string, StrategyHealth>>(new Map())
  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean
    instanceId: string
    strategyName: string
  }>({ open: false, instanceId: '', strategyName: '' })
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')
  const [deleteAllDialogOpen, setDeleteAllDialogOpen] = useState(false)
  const [isDeletingAll, setIsDeletingAll] = useState(false)

  // Exit dialog state
  const [exitDialog, setExitDialog] = useState<{
    open: boolean
    instanceId: string
    legKey: string
    leg: LegState | null
  }>({ open: false, instanceId: '', legKey: '', leg: null })
  const [exitPrice, setExitPrice] = useState('')
  const [exitStatus, setExitStatus] = useState<'SL_HIT' | 'TARGET_HIT' | null>('SL_HIT')
  const [exitAtMarket, setExitAtMarket] = useState(false)
  const [isExiting, setIsExiting] = useState(false)

  const fetchData = async (showToast = false) => {
    try {
      const data = await getStrategyStates()
      setStrategies(data)

      // ---- Health transition toasts + sound ----
      const prevMap = prevHealthRef.current
      const { shouldPlaySound, shouldShowToast } = useAlertStore.getState()
      let playSound = false

      for (const strategy of data) {
        const newHealth = getStrategyHealth(strategy)
        const oldHealth = prevMap.get(strategy.instance_id)
        const name = strategy.strategy_name

        if (oldHealth !== undefined && oldHealth !== newHealth) {
          if (newHealth === 'dead') {
            if (shouldShowToast('pythonStrategy')) {
              toast.error(`⚠️ ${name} — No heartbeat detected`, {
                description: `Script may have crashed or stopped. Last seen: ${formatHeartbeatAge(strategy.last_heartbeat)}${strategy.pid ? ` (PID: ${strategy.pid})` : ''}`,
                duration: 10000,
              })
            }
            // Flag sound — played once after the loop even if multiple strategies go dead
            if (shouldPlaySound()) playSound = true
          } else if (newHealth === 'stale' && oldHealth === 'alive') {
            if (shouldShowToast('pythonStrategy')) {
              toast.warning(`🟡 ${name} — Heartbeat is stale`, {
                description: `No update for ${formatHeartbeatAge(strategy.last_heartbeat)} — script may be slow or stuck`,
                duration: 6000,
              })
            }
          } else if (newHealth === 'alive' && (oldHealth === 'dead' || oldHealth === 'stale')) {
            if (shouldShowToast('pythonStrategy')) {
              toast.success(`✅ ${name} — Script is back online`, {
                description: `Heartbeat resumed${strategy.pid ? ` (PID: ${strategy.pid})` : ''}`,
                duration: 5000,
              })
            }
          }
        }

        prevMap.set(strategy.instance_id, newHealth)
      }

      // Play alert sound once for dead transitions (respects global sound toggle)
      if (playSound) {
        const audio = new Audio('/sounds/alert.mp3')
        audio.play().catch(() => {/* autoplay blocked — silently ignore */})
      }

      // Prune stale instance_ids so the Map doesn't grow unboundedly
      const activeIds = new Set(data.map((s) => s.instance_id))
      for (const id of prevMap.keys()) {
        if (!activeIds.has(id)) prevMap.delete(id)
      }

      if (showToast) {
        toast.success('Data refreshed')
      }
    } catch (error) {
      console.error('Error fetching strategy states:', error)
      toast.error('Failed to fetch strategy positions')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
      isRefreshingRef.current = false
    }
  }

  const handleDeleteRequest = (instanceId: string, strategyName: string) => {
    setDeleteConfirmText('') // Reset confirmation text
    setDeleteDialog({ open: true, instanceId, strategyName })
  }

  const handleDeleteConfirm = async () => {
    if (!deleteDialog.instanceId) return

    setIsDeleting(true)
    try {
      await deleteStrategyState(deleteDialog.instanceId)
      toast.success(`Strategy "${deleteDialog.strategyName}" deleted successfully`)
      // Remove from local state
      setStrategies(prev => prev.filter(s => s.instance_id !== deleteDialog.instanceId))
    } catch (error) {
      console.error('Error deleting strategy:', error)
      toast.error('Failed to delete strategy')
    } finally {
      setIsDeleting(false)
      setDeleteDialog({ open: false, instanceId: '', strategyName: '' })
      setDeleteConfirmText('')
    }
  }

  const isDeleteConfirmValid = deleteConfirmText === deleteDialog.strategyName

  const handleDeleteAll = async () => {
    setIsDeletingAll(true)
    let successCount = 0
    let failCount = 0
    for (const strategy of strategies) {
      try {
        await deleteStrategyState(strategy.instance_id)
        successCount++
      } catch (error) {
        console.error('Error deleting strategy:', error)
        failCount++
      }
    }
    setIsDeletingAll(false)
    setDeleteAllDialogOpen(false)
    if (successCount > 0) {
      toast.success(`Deleted ${successCount} strateg${successCount > 1 ? 'ies' : 'y'} successfully`)
    }
    if (failCount > 0) {
      toast.error(`Failed to delete ${failCount} strateg${failCount > 1 ? 'ies' : 'y'}`)
    }
    setStrategies([])
    fetchData(false)
  }

  const handleExitRequest = (instanceId: string, legKey: string, leg: LegState) => {
    setExitDialog({ open: true, instanceId, legKey, leg })
    setExitPrice('')
    setExitStatus('SL_HIT')
    setExitAtMarket(false)
  }

  const handleExitAtMarketChange = (checked: boolean) => {
    setExitAtMarket(checked)
    // Reset exit status when switching modes
    if (checked) {
      setExitStatus(null) // Optional for market exits
    } else {
      setExitStatus('SL_HIT') // Required for manual exits
    }
  }

  const handleExitConfirm = async () => {
    if (!exitDialog.instanceId || !exitDialog.legKey || !exitDialog.leg) return

    // Validation for manual price exit
    if (!exitAtMarket) {
      const price = parseFloat(exitPrice)
      if (isNaN(price) || price <= 0) {
        toast.error('Please enter a valid exit price')
        return
      }

      if (!exitStatus) {
        toast.error('Please select an exit status')
        return
      }

      // Validate exit price based on side and status
      const entryPrice = exitDialog.leg.entry_price
      const side = exitDialog.leg.side

      if (entryPrice && side) {
        if (exitStatus === 'TARGET_HIT') {
          if (side === 'BUY' && price <= entryPrice) {
            toast.error(`For BUY positions with TARGET_HIT, exit price must be greater than entry price (${entryPrice.toFixed(2)})`)
            return
          }
          if (side === 'SELL' && price >= entryPrice) {
            toast.error(`For SELL positions with TARGET_HIT, exit price must be less than entry price (${entryPrice.toFixed(2)})`)
            return
          }
        } else if (exitStatus === 'SL_HIT') {
          if (side === 'BUY' && price >= entryPrice) {
            toast.error(`For BUY positions with SL_HIT, exit price must be less than entry price (${entryPrice.toFixed(2)})`)
            return
          }
          if (side === 'SELL' && price <= entryPrice) {
            toast.error(`For SELL positions with SL_HIT, exit price must be greater than entry price (${entryPrice.toFixed(2)})`)
            return
          }
        }
      }
    }

    setIsExiting(true)
    try {
      const price = exitAtMarket ? null : parseFloat(exitPrice)
      const result = await manualExitLeg(exitDialog.instanceId, exitDialog.legKey, price, exitStatus, exitAtMarket)
      toast.success(result.message)
      setExitDialog({ open: false, instanceId: '', legKey: '', leg: null })
      setExitPrice('')
      setExitAtMarket(false)

      // Refresh data immediately after successful exit
      await fetchData(false)
    } catch (error) {
      console.error('Error exiting position:', error)
      toast.error(error instanceof Error ? error.message : 'Failed to exit position')
    } finally {
      setIsExiting(false)
    }
  }

  // Load auto-refresh prefs
  useEffect(() => {
    try {
      const savedEnabled = window.localStorage.getItem(AUTO_REFRESH_ENABLED_KEY)
      if (savedEnabled !== null) {
        setAutoRefreshEnabled(savedEnabled === '1' || savedEnabled === 'true')
      }

      const savedSeconds = window.localStorage.getItem(AUTO_REFRESH_SECONDS_KEY)
      if (savedSeconds) {
        const parsed = Number.parseInt(savedSeconds, 10)
        if (!Number.isNaN(parsed)) {
          // Clamp to 5–300 seconds
          const clamped = Math.min(300, Math.max(5, parsed))
          setAutoRefreshSeconds(clamped)
        }
      }

      // Load expand all preference (default to false = collapsed)
      const savedExpandAll = window.localStorage.getItem(EXPAND_ALL_KEY)
      if (savedExpandAll !== null) {
        setExpandAll(savedExpandAll === '1')
      }
    } catch (e) {
      console.error('Error loading strategy positions auto-refresh preferences:', e)
    }

    fetchData()
  }, [])

  // Persist auto-refresh prefs
  useEffect(() => {
    try {
      window.localStorage.setItem(AUTO_REFRESH_ENABLED_KEY, autoRefreshEnabled ? '1' : '0')
      window.localStorage.setItem(AUTO_REFRESH_SECONDS_KEY, String(autoRefreshSeconds))
    } catch (e) {
      console.error('Error saving strategy positions auto-refresh preferences:', e)
    }
  }, [autoRefreshEnabled, autoRefreshSeconds])

  // Persist expand all preference
  useEffect(() => {
    try {
      window.localStorage.setItem(EXPAND_ALL_KEY, expandAll ? '1' : '0')
    } catch (e) {
      console.error('Error saving strategy positions expand all preference:', e)
    }
  }, [expandAll])

  // Auto-refresh timer (silent)
  useEffect(() => {
    if (!autoRefreshEnabled) return

    // Avoid extremely low / invalid values
    const intervalSeconds = Math.min(300, Math.max(5, autoRefreshSeconds))

    const id = window.setInterval(() => {
      // Don't overlap requests
      if (isRefreshingRef.current) return
      isRefreshingRef.current = true
      setIsRefreshing(true)
      fetchData(false)
    }, intervalSeconds * 1000)

    return () => window.clearInterval(id)
  }, [autoRefreshEnabled, autoRefreshSeconds])

  // ---- Live prices (single subscription for all strategies) ----
  type StrategyLegPriceItem = {
    instanceId: string
    legKey: string
    symbol: string
    exchange: string
    // Baseline LTP for initial render (matches /positions behavior)
    ltp?: number
    // Required for useLivePrice to enable live updates
    quantity?: number
    average_price?: number
  }

  const allLegPriceItems: StrategyLegPriceItem[] = useMemo(() => {
    const items: StrategyLegPriceItem[] = []

    for (const strategy of strategies) {
      // Determine exchange from config or infer from underlying
      let optionExchange = strategy.config?.exchange || 'NFO'

      // Infer exchange from underlying if not explicitly set
      if (!strategy.config?.exchange && strategy.state_data) {
        const underlying = strategy.state_data.underlying || strategy.config?.underlying
        if (underlying === 'SENSEX' || underlying === 'BANKEX' || underlying === 'SENSEX50') {
          optionExchange = 'BFO'
        } else if (underlying === 'NIFTY' || underlying === 'BANKNIFTY' || underlying === 'FINNIFTY' || underlying === 'MIDCPNIFTY') {
          optionExchange = 'NFO'
        }
      }

      const legs = strategy.legs || {}

      for (const [legKey, leg] of Object.entries(legs)) {
        if (!['IN_POSITION', 'PENDING_EXIT', 'PENDING_ENTRY', 'IDLE', 'EXITED_WAITING_REENTRY', 'EXITED_WAITING_REEXECUTE'].includes(leg.status)) continue

        const raw = (leg.symbol || '').trim()
        if (!raw) continue

        // Strategy may persist either `NFO:NIFTY...` or only `NIFTY...`
        if (raw.includes(':')) {
          const [exchange, symbol] = raw.split(':', 2)
          if (!symbol) continue
          items.push({
            instanceId: strategy.instance_id,
            legKey,
            symbol,
            exchange: exchange || optionExchange,
            ltp: (leg as any).current_ltp ?? (leg as any).entry_price,
            quantity: leg.quantity,
            average_price: leg.entry_price ?? undefined,
          })
        } else {
          items.push({
            instanceId: strategy.instance_id,
            legKey,
            symbol: raw,
            exchange: optionExchange,
            ltp: (leg as any).current_ltp ?? (leg as any).entry_price,
            quantity: leg.quantity,
            average_price: leg.entry_price ?? undefined,
          })
        }
      }
    }

    return items
  }, [strategies])

  const { data: allOpenLegsWithLivePrice } = useLivePrice(allLegPriceItems, {
    enabled: allLegPriceItems.length > 0,
    useMultiQuotesFallback: true,
    staleThreshold: 5000,
    multiQuotesRefreshInterval: 30000,
    pauseWhenHidden: true,
  })

  const liveLtpByInstanceAndLegKey = useMemo(() => {
    const map: Record<string, Record<string, number | undefined>> = {}
    for (const item of allOpenLegsWithLivePrice) {
      if (!map[item.instanceId]) map[item.instanceId] = {}
      map[item.instanceId][item.legKey] = item.ltp
    }
    return map
  }, [allOpenLegsWithLivePrice])

  const handleRefresh = () => {
    isRefreshingRef.current = true
    setIsRefreshing(true)
    fetchData(true)
  }

  const resetManualDialog = () => {
    setManualPositions([])
    setManualSelectedKey('')
    setManualLegPairName('')
    setManualIsMainLeg(true)
    setManualSlPercent('')
    setManualTargetPercent('')
    setManualReentryLimit('')
    setManualReexecuteLimit('')
    setManualError(null)
    setManualSubmitting(false)
    setManualMode('TRACK')
    setManualNewSymbol('')
    setManualNewQty('')
    setManualWaitPercent('')
    setManualWaitBaseline('')
    setManualNewSide('SELL')
    setManualNewProduct('NRML')
  }

  const handleOpenManualDialog = async (strategy: StrategyState) => {
    if (!apiKey) {
      toast.error('API key not available')
      return
    }
    setManualDialogStrategy(strategy)
    setManualDialogOpen(true)
    setManualLoading(true)
    setManualError(null)
    try {
      const response = await tradingApi.getPositions(apiKey)
      if (response.status !== 'success' || !response.data) {
        throw new Error(response.message || 'Failed to load positions')
      }
      const openPositions = response.data.filter(position => position.quantity !== 0)
      setManualPositions(openPositions)
      if (openPositions.length === 0) {
        setManualSelectedKey('')
      }
    } catch (error) {
      setManualError(error instanceof Error ? error.message : 'Failed to load positions')
    } finally {
      setManualLoading(false)
    }
  }

  const handleManualSubmit = async () => {
    if (!manualDialogStrategy) return
    const slPercent = manualSlPercent.trim() === '' ? null : Number.parseFloat(manualSlPercent)
    const targetPercent = manualTargetPercent.trim() === '' ? null : Number.parseFloat(manualTargetPercent)
    const reentryLimit = manualReentryLimit.trim() === '' ? null : Number.parseInt(manualReentryLimit, 10)
    const reexecuteLimit = manualReexecuteLimit.trim() === '' ? null : Number.parseInt(manualReexecuteLimit, 10)

    if (slPercent !== null && (Number.isNaN(slPercent) || slPercent <= 0)) {
      toast.error('SL percent must be a positive number')
      return
    }

    if (targetPercent !== null && (Number.isNaN(targetPercent) || targetPercent <= 0)) {
      toast.error('Target percent must be a positive number')
      return
    }

    if (reentryLimit !== null && (Number.isNaN(reentryLimit) || reentryLimit < 0)) {
      toast.error('Re-entry limit must be a non-negative number')
      return
    }

    if (reexecuteLimit !== null && (Number.isNaN(reexecuteLimit) || reexecuteLimit < 0)) {
      toast.error('Re-execute limit must be a non-negative number')
      return
    }

    // Validation: If Main Leg is not selected, check if leg pair has at least one main leg
    if (!manualIsMainLeg && manualLegPairName.trim()) {
      const legPairName = manualLegPairName.trim()
      const strategy = manualDialogStrategy
      const existingMainLeg = strategy?.legs && Object.values(strategy.legs).some(
        leg => leg.leg_pair_name === legPairName && leg.is_main_leg === true
      )
      if (!existingMainLeg) {
        toast.error(`Leg Pair '${legPairName}' must have at least one Main Leg trade. Please mark this as Main Leg or add a Main Leg trade first.`)
        return
      }
    }

    let payload: any = {
      leg_key: `MANUAL_${Date.now()}`,
      sl_percent: slPercent,
      target_percent: targetPercent,
      leg_pair_name: manualLegPairName.trim() ? manualLegPairName.trim() : null,
      reentry_limit: reentryLimit,
      reexecute_limit: reexecuteLimit,
      mode: manualMode,
    }

    if (manualMode === 'TRACK') {
      const selected = manualPositions.find(position =>
        `${position.exchange}:${position.symbol}:${position.product}:${position.quantity}` === manualSelectedKey
      )
      if (!selected) {
        toast.error('Select a position')
        return
      }
      payload = {
        ...payload,
        symbol: selected.symbol,
        exchange: selected.exchange,
        product: selected.product,
        quantity: Math.abs(selected.quantity),
        side: selected.quantity > 0 ? 'BUY' : 'SELL',
        entry_price: selected.average_price,
        is_main_leg: manualIsMainLeg,
      }
    } else {
      // NEW Mode
      if (!manualNewSymbol.trim()) {
        toast.error('Symbol is required')
        return
      }
      const qty = parseInt(manualNewQty)
      if (isNaN(qty) || qty <= 0) {
        toast.error('Invalid quantity')
        return
      }

      const waitPct = manualWaitPercent.trim() ? parseFloat(manualWaitPercent) : null
      const waitBase = manualWaitBaseline.trim() ? parseFloat(manualWaitBaseline) : null

      if (waitPct !== null && (isNaN(waitPct) || waitPct <= 0)) {
        toast.error('Invalid wait percentage')
        return
      }
      if (waitPct !== null && waitBase === null) {
        toast.error('Baseline price is required for Wait Entry')
        return
      }

      payload = {
        ...payload,
        symbol: manualNewSymbol.toUpperCase(),
        exchange: manualNewExchange,
        product: manualNewProduct,
        quantity: qty,
        side: manualNewSide,
        is_main_leg: manualIsMainLeg,
        wait_trade_percent: waitPct,
        wait_baseline_price: waitBase,
      }
    }

    setManualSubmitting(true)
    try {
      const response = await createManualStrategyLeg(manualDialogStrategy.instance_id, payload)
      toast.success(response.message)
      setManualDialogOpen(false)
      resetManualDialog()
      fetchData(false)
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Failed to add manual position')
    } finally {
      setManualSubmitting(false)
    }
  }

  const sortedStrategies = useMemo(() => {
    // Sort to keep UI stable even if backend response order changes.
    // Primary: strategy_name (case-insensitive)
    // Tie-breaker: created_at (oldest first)
    // Final: instance_id (stable)
    return [...strategies].sort((a, b) => {
      const nameA = (a.strategy_name || '').toLocaleLowerCase()
      const nameB = (b.strategy_name || '').toLocaleLowerCase()

      if (nameA < nameB) return -1
      if (nameA > nameB) return 1

      const timeA = a.created_at ? new Date(a.created_at).getTime() : Number.POSITIVE_INFINITY
      const timeB = b.created_at ? new Date(b.created_at).getTime() : Number.POSITIVE_INFINITY

      if (timeA !== timeB) return timeA - timeB

      // Stable fallback for identical name+created_at
      return (a.instance_id || '').localeCompare(b.instance_id || '')
    })
  }, [strategies])

  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl">
      {/* Header - Sticky */}
      <div className="sticky top-[56px] z-10 bg-background pb-6 mb-6 border-b">
        <div className="flex items-start justify-between gap-4 pt-6">
          <div>
            <h1 className="text-2xl font-bold">Strategy Positions</h1>
            <p className="text-muted-foreground">
              View positions and trade history for Python strategies
            </p>
          </div>

          <div className="flex flex-col items-end gap-2">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Expand all</Label>
                <Switch checked={expandAll} onCheckedChange={setExpandAll} />
              </div>

              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Auto refresh</Label>
                <Switch checked={autoRefreshEnabled} onCheckedChange={setAutoRefreshEnabled} />
              </div>

              <div className="flex items-center gap-2">
                <Label className="text-xs text-muted-foreground">Every (s)</Label>
                <Input
                  type="number"
                  min={5}
                  max={300}
                  step={1}
                  value={autoRefreshSeconds}
                  onChange={(e) => {
                    const raw = Number.parseInt(e.target.value, 10)
                    if (Number.isNaN(raw)) return
                    const clamped = Math.min(300, Math.max(5, raw))
                    setAutoRefreshSeconds(clamped)
                  }}
                  className="h-8 w-20"
                  disabled={!autoRefreshEnabled}
                />
              </div>

              <Button
                variant="outline"
                size="sm"
                onClick={handleRefresh}
                disabled={isRefreshing}
              >
                <RefreshCw className={`h-4 w-4 mr-2 ${isRefreshing ? 'animate-spin' : ''}`} />
                Refresh
              </Button>
              <Link to="/strategy-dashboard">
                <Button variant="outline" size="sm" className="gap-1.5">
                  <BarChart2 className="h-4 w-4" />
                  Eagle Eye
                  <ExternalLink className="h-3 w-3 opacity-60" />
                </Button>
              </Link>
              {strategies.length > 0 && (
                <Button
                  variant="outline"
                  size="sm"
                  className="border-red-500 text-red-600 hover:bg-red-50 dark:text-red-400 dark:hover:bg-red-950"
                  onClick={() => setDeleteAllDialogOpen(true)}
                >
                  <Trash2 className="h-4 w-4 mr-2" />
                  Delete All
                </Button>
              )}
            </div>

            <p className="text-[11px] text-muted-foreground">
              Range: 5–300 seconds (saved locally)
            </p>
          </div>
        </div>
      </div>

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : sortedStrategies.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No strategy states found</p>
            <p className="text-sm text-muted-foreground mt-2">
              Strategy positions will appear here when you run Python strategies with state persistence.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div>
          {sortedStrategies.map((strategy) => (
            <StrategyAccordionItem
              key={strategy.instance_id}
              strategy={strategy}
              onDelete={handleDeleteRequest}
              onRefresh={() => fetchData(false)}
              liveLtpByLegKey={liveLtpByInstanceAndLegKey[strategy.instance_id] || {}}
              onAddManualLeg={handleOpenManualDialog}
              onExitLeg={handleExitRequest}
              expandAll={expandAll}
            />
          ))}
        </div>
      )}

      <Dialog
        open={manualDialogOpen}
        onOpenChange={(open) => {
          setManualDialogOpen(open)
          if (!open) {
            resetManualDialog()
            setManualDialogStrategy(null)
          }
        }}
      >
        <DialogContent className="sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>Add Position to Strategy</DialogTitle>
            <DialogDescription>
              Select a live broker position to track in {manualDialogStrategy?.strategy_name || 'this strategy'}.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <Tabs value={manualMode} onValueChange={(v) => setManualMode(v as any)}>
              <TabsList className="grid w-full grid-cols-2">
                <TabsTrigger value="TRACK">Track Existing</TabsTrigger>
                <TabsTrigger value="NEW">New Trade</TabsTrigger>
              </TabsList>

              <TabsContent value="TRACK" className="pt-4 space-y-4">
                {manualLoading ? (
                  <p className="text-sm text-muted-foreground">Loading positions...</p>
                ) : manualError ? (
                  <p className="text-sm text-destructive">{manualError}</p>
                ) : manualPositions.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No open positions available.</p>
                ) : (
                  <div className="space-y-2">
                    <Label>Position</Label>
                    <Select value={manualSelectedKey} onValueChange={setManualSelectedKey}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select position" />
                      </SelectTrigger>
                      <SelectContent>
                        {manualPositions.map((position) => {
                          const key = `${position.exchange}:${position.symbol}:${position.product}:${position.quantity}`
                          const side = position.quantity > 0 ? 'BUY' : 'SELL'
                          return (
                            <SelectItem key={key} value={key}>
                              {position.exchange}:{position.symbol} • {side} {Math.abs(position.quantity)} @ {formatPrice(position.average_price)}
                            </SelectItem>
                          )
                        })}
                      </SelectContent>
                    </Select>
                  </div>
                )}
              </TabsContent>

              <TabsContent value="NEW" className="pt-4 space-y-4">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label>Symbol</Label>
                    <Input
                      placeholder="e.g. SENSEX24FEB75000PE"
                      value={manualNewSymbol}
                      onChange={(e) => setManualNewSymbol(e.target.value.toUpperCase())}
                    />
                  </div>
                  <div className="space-y-2">
                    <Label>Exchange</Label>
                    <Select value={manualNewExchange} onValueChange={setManualNewExchange}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="NFO">NFO</SelectItem>
                        <SelectItem value="BFO">BFO</SelectItem>
                        <SelectItem value="MCX">MCX</SelectItem>
                        <SelectItem value="CDS">CDS</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-4">
                  <div className="space-y-2">
                    <Label>Product</Label>
                    <Select value={manualNewProduct} onValueChange={setManualNewProduct}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="NRML">NRML</SelectItem>
                        <SelectItem value="MIS">MIS</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="space-y-2">
                    <Label>Qty</Label>
                    <Input placeholder="Qty" value={manualNewQty} onChange={(e) => setManualNewQty(e.target.value)} type="number" />
                  </div>
                  <div className="space-y-2">
                    <Label>Side</Label>
                    <Select value={manualNewSide} onValueChange={(v) => setManualNewSide(v as any)}>
                      <SelectTrigger><SelectValue /></SelectTrigger>
                      <SelectContent>
                        <SelectItem value="SELL">SELL</SelectItem>
                        <SelectItem value="BUY">BUY</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                <div className="rounded-md border p-4 space-y-3 bg-muted/20">
                  <Label className="font-medium text-xs uppercase text-muted-foreground">Execution Condition</Label>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="space-y-2">
                      <Label className="text-xs">Wait Trigger %</Label>
                      <Input
                        placeholder="Immediate if empty"
                        value={manualWaitPercent}
                        onChange={(e) => setManualWaitPercent(e.target.value)}
                        type="number"
                        step="0.1"
                      />
                    </div>
                    <div className="space-y-2">
                      <Label className="text-xs">Baseline Price</Label>
                      <Input
                        placeholder="Required for wait"
                        value={manualWaitBaseline}
                        onChange={(e) => setManualWaitBaseline(e.target.value)}
                        type="number"
                      />
                    </div>
                  </div>
                </div>
              </TabsContent>
            </Tabs>

            <div className="space-y-4 pt-2 border-t">
              <div className="grid gap-4 md:grid-cols-2">
                <div className="grid grid-cols-2 gap-4">
                  <div className="space-y-2">
                    <Label htmlFor="manual-reentry-limit">Re-entry Limit</Label>
                    <Input
                      id="manual-reentry-limit"
                      type="number"
                      placeholder="e.g. 1"
                      min="0"
                      step="1"
                      value={manualReentryLimit}
                      onChange={(e) => setManualReentryLimit(e.target.value)}
                    />
                  </div>

                  <div className="space-y-2">
                    <Label htmlFor="manual-reexecute-limit">Re-exec Limit</Label>
                    <Input
                      id="manual-reexecute-limit"
                      type="number"
                      placeholder="e.g. 1"
                      min="0"
                      step="1"
                      value={manualReexecuteLimit}
                      onChange={(e) => setManualReexecuteLimit(e.target.value)}
                    />
                  </div>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="manual-leg-name">Leg Pair Name</Label>
                  <Input
                    id="manual-leg-name"
                    placeholder="Hedge Pair"
                    value={manualLegPairName}
                    onChange={(event) => setManualLegPairName(event.target.value)}
                  />
                </div>
                <div className="flex items-center gap-3 pt-6">
                  <Switch
                    checked={manualIsMainLeg}
                    onCheckedChange={setManualIsMainLeg}
                    id="manual-is-main-leg"
                  />
                  <Label htmlFor="manual-is-main-leg">Main Leg</Label>
                </div>
              </div>
              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label htmlFor="manual-sl-percent">SL Percent</Label>
                  <Input
                    id="manual-sl-percent"
                    placeholder="0.05"
                    value={manualSlPercent}
                    onChange={(event) => setManualSlPercent(event.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="manual-target-percent">Target Percent</Label>
                  <Input
                    id="manual-target-percent"
                    placeholder="0.1"
                    value={manualTargetPercent}
                    onChange={(event) => setManualTargetPercent(event.target.value)}
                  />
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setManualDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleManualSubmit}
              disabled={manualSubmitting || (manualMode === 'TRACK' && (manualLoading || manualPositions.length === 0))}
            >
              {manualSubmitting ? 'Adding...' : 'Add Position'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog
        open={deleteDialog.open}
        onOpenChange={(open) => {
          if (!isDeleting) {
            setDeleteDialog(prev => ({ ...prev, open }))
            if (!open) setDeleteConfirmText('')
          }
        }}
      >
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Strategy State?</AlertDialogTitle>
            <AlertDialogDescription asChild>
              <div className="space-y-4">
                <p>
                  Are you sure you want to delete the strategy state for{' '}
                  <strong>{deleteDialog.strategyName}</strong>? This action cannot be undone and will
                  remove all position data and trade history for this strategy.
                </p>
                <div className="space-y-2">
                  <p className="text-sm">
                    To confirm, type <strong className="text-foreground">{deleteDialog.strategyName}</strong> below:
                  </p>
                  <input
                    type="text"
                    value={deleteConfirmText}
                    onChange={(e) => setDeleteConfirmText(e.target.value)}
                    placeholder="Type strategy name to confirm"
                    className="w-full px-3 py-2 text-sm border rounded-md bg-background text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
                    disabled={isDeleting}
                    autoComplete="off"
                  />
                </div>
              </div>
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeleting}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteConfirm}
              disabled={isDeleting || !isDeleteConfirmValid}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeleting ? 'Deleting...' : 'Delete'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Exit Position Dialog */}
      <Dialog open={exitDialog.open} onOpenChange={(open) => {
        if (!isExiting) {
          setExitDialog(prev => ({ ...prev, open }))
          if (!open) {
            setExitPrice('')
            setExitStatus('SL_HIT')
          }
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Exit Position</DialogTitle>
            <DialogDescription>
              Exit position for {exitDialog.leg?.symbol} ({exitDialog.leg?.side} {exitDialog.leg?.quantity})
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <div className="flex items-center space-x-2">
                <Checkbox
                  id="exit-at-market"
                  checked={exitAtMarket}
                  onCheckedChange={handleExitAtMarketChange}
                  disabled={isExiting}
                />
                <Label htmlFor="exit-at-market" className="text-sm font-medium cursor-pointer">
                  Exit at market price
                </Label>
              </div>
              {exitAtMarket && (
                <p className="text-xs text-amber-600 dark:text-amber-400 flex items-start gap-1">
                  <span className="mt-0.5">⚠️</span>
                  <span>A MARKET order will be placed to exit this position. The actual fill price will be used.</span>
                </p>
              )}
            </div>

            <div className="space-y-2">
              <Label htmlFor="exit-price">Exit Price {!exitAtMarket && '*'}</Label>
              <Input
                id="exit-price"
                type="number"
                step="0.05"
                placeholder={exitAtMarket ? "Will use market price" : "Enter exit price"}
                value={exitPrice}
                onChange={(e) => setExitPrice(e.target.value)}
                disabled={isExiting || exitAtMarket}
              />
              {exitDialog.leg?.entry_price && (
                <p className="text-xs text-muted-foreground">
                  Entry Price: {formatPrice(exitDialog.leg.entry_price)}
                </p>
              )}
              {!exitAtMarket && (
                <p className="text-xs text-muted-foreground">
                  Use this to mark positions exited outside OpenAlgo
                </p>
              )}
            </div>

            {!exitAtMarket && (
              <div className="space-y-2">
                <Label htmlFor="exit-status">Exit Status *</Label>
                <Select value={exitStatus || 'SL_HIT'} onValueChange={(v) => setExitStatus(v as 'SL_HIT' | 'TARGET_HIT')} disabled={isExiting}>
                  <SelectTrigger id="exit-status">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SL_HIT">SL Hit</SelectItem>
                    <SelectItem value="TARGET_HIT">Target Hit</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-xs text-muted-foreground">
                  Select the exit reason for this position
                </p>
              </div>
            )}

            {exitAtMarket && (
              <div className="space-y-2">
                <p className="text-sm text-muted-foreground">
                  Exit status will be marked as <span className="font-medium">Manual Exit</span>
                </p>
              </div>
            )}
          </div>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setExitDialog({ open: false, instanceId: '', legKey: '', leg: null })} disabled={isExiting}>
              Cancel
            </Button>
            <Button onClick={handleExitConfirm} disabled={isExiting || (!exitAtMarket && !exitPrice)}>
              {isExiting ? 'Exiting...' : exitAtMarket ? 'Exit at Market' : 'Exit Position'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete All Confirmation Dialog */}
      <AlertDialog open={deleteAllDialogOpen} onOpenChange={(open) => {
        if (!isDeletingAll) setDeleteAllDialogOpen(open)
      }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete All Strategy States?</AlertDialogTitle>
            <AlertDialogDescription>
              This will permanently delete all {strategies.length} strateg{strategies.length === 1 ? 'y' : 'ies'} state{strategies.length === 1 ? '' : 's'}, including all position data and trade history. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isDeletingAll}>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={handleDeleteAll}
              disabled={isDeletingAll}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
            >
              {isDeletingAll ? 'Deleting...' : 'Delete All'}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
