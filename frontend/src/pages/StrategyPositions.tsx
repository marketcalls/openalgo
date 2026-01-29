import {
  ChevronDown,
  ChevronRight,
  CircleDot,
  RefreshCw,
  Trash2,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import React, { useEffect, useMemo, useState } from 'react'
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
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  const isPositive = value >= 0
  const color = isPositive ? 'text-green-600' : 'text-red-600'
  return (
    <span className={`font-medium ${color} flex items-center gap-1`}>
      {showIcon && (isPositive ? <TrendingUp className="h-3 w-3" /> : <TrendingDown className="h-3 w-3" />)}
      {formatCurrency(value)}
    </span>
  )
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
  
  // Separate open and idle positions.
  // Exited trades should be represented in Trade History (trade_history), not here.
  const openPositions = legEntries.filter(([_, leg]) =>
    ['IN_POSITION', 'PENDING_ENTRY', 'PENDING_EXIT'].includes(leg.status)
  )
  const idlePositions = legEntries.filter(([_, leg]) => leg.status === 'IDLE')

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
                    <TableCell className="text-right">{formatPrice(leg.entry_price)}</TableCell>
                    <TableCell className="text-right">
                      {formatPrice(liveLtpByLegKey?.[legKey] ?? leg.current_ltp ?? leg.entry_price)}
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
                      <PnLDisplay value={leg.unrealized_pnl} />
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

      {/* IDLE Positions (waiting to enter) */}
      {idlePositions.length > 0 && (
        <div>
          <h4 className="text-sm font-semibold mb-2 flex items-center gap-2">
            <CircleDot className="h-4 w-4 text-yellow-500" />
            IDLE Positions (Waiting to Enter) ({idlePositions.length})
          </h4>
          <div className="rounded-md border overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Leg</TableHead>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Qty</TableHead>
                  <TableHead className="text-right">Planned SL</TableHead>
                  <TableHead className="text-right">Planned Target</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="text-right">Reentry</TableHead>
                  <TableHead className="text-right">Reexec</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {idlePositions.map(([legKey, leg]) => (
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
                    <TableCell className="text-right">{formatPrice(leg.sl_price)}</TableCell>
                    <TableCell className="text-right">{formatPrice(leg.target_price)}</TableCell>
                    <TableCell>
                      <Badge className={legStatusColors[leg.status]} variant="secondary">
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
  )
}

// Strategy Accordion Item
function StrategyAccordionItem({ 
  strategy, 
  onDelete,
  onRefresh
}: { 
  strategy: StrategyState
  onDelete: (instanceId: string, strategyName: string) => void
  onRefresh: () => void
}) {
  // Use live LTP for open legs (WebSocket-first with REST fallback)
  type LegPriceItem = {
    legKey: string
    symbol: string
    exchange: string
    ltp?: number
  }

  const optionExchange = strategy.config?.exchange || 'NFO'

  const openLegPriceItems: LegPriceItem[] = useMemo(() => {
    const legs = strategy.legs || {}
    return Object.entries(legs)
      .filter(([_, leg]) => ['IN_POSITION', 'PENDING_ENTRY', 'PENDING_EXIT'].includes(leg.status))
      .map(([legKey, leg]) => {
        const raw = (leg.symbol || '').trim()
        if (!raw) {
          return {
            legKey,
            symbol: '',
            exchange: optionExchange,
          }
        }

        // Strategy may persist either `NFO:NIFTY...` or only `NIFTY...`
        if (raw.includes(':')) {
          const [exchange, symbol] = raw.split(':', 2)
          return {
            legKey,
            symbol,
            exchange: exchange || optionExchange,
          }
        }

        return {
          legKey,
          symbol: raw,
          exchange: optionExchange,
        }
      })
      .filter((i) => i.symbol.length > 0)
  }, [strategy.legs, optionExchange])

  const { data: openLegsWithLivePrice } = useLivePrice(openLegPriceItems, {
    enabled: openLegPriceItems.length > 0,
    useMultiQuotesFallback: true,
  })

  const liveLtpByLegKey = useMemo(() => {
    const map: Record<string, number | undefined> = {}
    for (const item of openLegsWithLivePrice) {
      map[item.legKey] = item.ltp
    }
    return map
  }, [openLegsWithLivePrice])
  const [isOpen, setIsOpen] = useState(true)
  const config = strategy.config
  
  const handleDeleteClick = (e: React.MouseEvent) => {
    e.stopPropagation() // Prevent accordion toggle
    onDelete(strategy.instance_id, strategy.strategy_name)
  }

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
                  <PnLDisplay value={strategy.summary?.total_pnl} />
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
                <p className="text-lg font-semibold">{strategy.summary?.open_positions_count ?? 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">IDLE Positions</p>
                <p className="text-lg font-semibold">{strategy.summary?.idle_positions_count ?? 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Total Trades</p>
                <p className="text-lg font-semibold">{strategy.summary?.total_trades ?? 0}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Realized P&L</p>
                <PnLDisplay value={strategy.summary?.total_realized_pnl} showIcon={false} />
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Unrealized P&L</p>
                <PnLDisplay value={strategy.summary?.total_unrealized_pnl} showIcon={false} />
              </div>
            </div>

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

  useEffect(() => {
    fetchData()
  }, [])

  const handleRefresh = () => {
    setIsRefreshing(true)
    fetchData(true)
  }

  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Strategy Positions</h1>
          <p className="text-muted-foreground">
            View positions and trade history for Python strategies
          </p>
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

      {/* Content */}
      {isLoading ? (
        <div className="flex items-center justify-center py-12">
          <RefreshCw className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      ) : strategies.length === 0 ? (
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
          {strategies.map((strategy) => (
            <StrategyAccordionItem 
              key={strategy.instance_id} 
              strategy={strategy} 
              onDelete={handleDeleteRequest}
              onRefresh={() => fetchData(false)}
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
