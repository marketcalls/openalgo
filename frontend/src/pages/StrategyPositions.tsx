import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  RefreshCw,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import React, { useEffect, useMemo, useRef, useState } from 'react'
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
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from '@/components/ui/collapsible'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { createStrategyOverride, deleteStrategyState, getStrategyStates } from '@/api/strategy-state'
import { useLivePrice } from '@/hooks/useLivePrice'
import type { LegState, LegStatus, StrategyState, TradeHistoryRecord, ExitType, OverrideType } from '@/types/strategy-state'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'

// Status badge colors
const statusColors: Record<string, string> = {
  RUNNING: 'bg-green-500',
  PAUSED: 'bg-yellow-500',
  COMPLETED: 'bg-gray-400',
  ERROR: 'bg-red-500',
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
  TARGET_HIT: 'bg-green-500',
  HEDGE_SL_EXIT: 'bg-red-400',
  HEDGE_TARGET_EXIT: 'bg-green-400',
  STRATEGY_DONE: 'bg-gray-500',
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

// Format price
function formatPrice(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return value.toFixed(2)
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
  })
}

// Format time only
function formatTime(isoString: string | null | undefined): string {
  if (!isoString) return '—'
  const date = new Date(isoString)
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
  })
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
}: {
  legs: Record<string, LegState> | null | undefined
  instanceId: string
  onRefresh: () => void
  liveLtpByLegKey?: Record<string, number | undefined>
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

  const donePositions = legEntries.filter(([_, leg]) => leg.status === 'DONE')

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
                  <TableHead className="text-right">Unreal P&L</TableHead>
                  <TableHead className="text-right">Reentry</TableHead>
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
                      {leg.reentry_count ?? 0}/{leg.reentry_limit ?? '∞'}
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
                      {leg.reentry_count ?? 0}/{leg.reentry_limit ?? '∞'}
                    </TableCell>
                    <TableCell className="text-right">
                      {leg.reexecute_count ?? 0}/{leg.reexecute_limit ?? '∞'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        </div>
      )}

      {/* Done Legs */}
      {donePositions.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <CircleDot className="h-4 w-4 text-gray-500" />
            Done Legs ({donePositions.length})
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
                  <TableHead className="text-right">Realized P&L</TableHead>
                  <TableHead className="text-right">Total P&L</TableHead>
                  <TableHead>Status</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {donePositions.map(([legKey, leg]) => (
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
                      <PnLDisplay value={leg.realized_pnl} />
                    </TableCell>
                    <TableCell className="text-right">
                      <PnLDisplay value={leg.total_pnl ?? leg.realized_pnl} />
                    </TableCell>
                    <TableCell>
                      <Badge className={legStatusColors[leg.status] || 'bg-gray-400'} variant="secondary">
                        {leg.status.replace(/_/g, ' ')}
                      </Badge>
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
            <TableHead className="text-right">P&L</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {trades.map((trade) => (
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
            </TableRow>
          ))}
        </TableBody>
      </Table>
      </div>
    </div>
  )
}

// Strategy Accordion Item
function StrategyAccordionItem({
  strategy,
  onDelete,
  onRefresh,
  liveLtpByLegKey,
}: {
  strategy: StrategyState
  onDelete: (instanceId: string, strategyName: string) => void
  onRefresh: () => void
  liveLtpByLegKey: Record<string, number | undefined>
}) {
  const [isOpen, setIsOpen] = useState(true)
  const [isLegPnlOpen, setIsLegPnlOpen] = useState(false)
  const config = strategy.config

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
          </CardHeader>
        </CollapsibleTrigger>
        <CollapsibleContent>
          <CardContent className="pt-0 space-y-6">
            {/* Summary Stats */}
            <div className="grid grid-cols-2 md:grid-cols-5 gap-4 p-4 bg-muted/30 rounded-lg">
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
            </div>

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
                        <TableHead className="text-right">Total P&L</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {Object.entries(legs).map(([legKey, leg]) => {
                        const unreal = ['IN_POSITION', 'PENDING_EXIT'].includes(leg.status)
                          ? computeUnrealizedPnlForLeg(leg, liveLtpByLegKey?.[legKey])
                          : 0
                        const realized = leg.realized_pnl ?? 0
                        const total = (leg.total_pnl ?? null) !== null && leg.total_pnl !== undefined
                          ? leg.total_pnl
                          : unreal === null
                            ? null
                            : realized + unreal

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
                              <PnLDisplay value={total} showIcon={false} />
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

            {/* Current Positions */}
            <div>
              <h3 className="text-md font-semibold mb-3">📊 Current Positions</h3>
              <CurrentPositionsTable
                legs={strategy.legs}
                instanceId={strategy.instance_id}
                onRefresh={onRefresh}
                liveLtpByLegKey={liveLtpByLegKey}
              />
            </div>

            {/* Trade History */}
            <div>
              <h3 className="text-md font-semibold mb-3">📜 Trade History</h3>
              <TradeHistoryTable trades={strategy.trade_history} />
            </div>
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

  const AUTO_REFRESH_ENABLED_KEY = 'strategy_positions_auto_refresh_enabled'
  const AUTO_REFRESH_SECONDS_KEY = 'strategy_positions_auto_refresh_seconds'

  const [autoRefreshEnabled, setAutoRefreshEnabled] = useState(true)
  const [autoRefreshSeconds, setAutoRefreshSeconds] = useState(10)
  const isRefreshingRef = useRef(false)
  const [deleteDialog, setDeleteDialog] = useState<{
    open: boolean
    instanceId: string
    strategyName: string
  }>({ open: false, instanceId: '', strategyName: '' })
  const [isDeleting, setIsDeleting] = useState(false)
  const [deleteConfirmText, setDeleteConfirmText] = useState('')

  const fetchData = async (showToast = false) => {
    try {
      const data = await getStrategyStates()
      setStrategies(data)
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
  }

  const allLegPriceItems: StrategyLegPriceItem[] = useMemo(() => {
    const items: StrategyLegPriceItem[] = []

    for (const strategy of strategies) {
      const optionExchange = strategy.config?.exchange || 'NFO'
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
          })
        } else {
          items.push({
            instanceId: strategy.instance_id,
            legKey,
            symbol: raw,
            exchange: optionExchange,
            ltp: (leg as any).current_ltp ?? (leg as any).entry_price,
          })
        }
      }
    }

    return items
  }, [strategies])

  const { data: allOpenLegsWithLivePrice } = useLivePrice(allLegPriceItems, {
    enabled: allLegPriceItems.length > 0,
    useMultiQuotesFallback: true,
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
      {/* Header */}
      <div className="flex items-start justify-between gap-4 mb-6">
        <div>
          <h1 className="text-2xl font-bold">Strategy Positions</h1>
          <p className="text-muted-foreground">
            View positions and trade history for Python strategies
          </p>
        </div>

        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-3">
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
          </div>

          <p className="text-[11px] text-muted-foreground">
            Range: 5–300 seconds (saved locally)
          </p>
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
            />
          ))}
        </div>
      )}

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
    </div>
  )
}
