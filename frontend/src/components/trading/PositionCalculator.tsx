// components/trading/PositionCalculator.tsx
// Intraday position size calculator that appears before order placement.
// Auto-fills symbol, LTP, capital, and leverage multiplier.
// Computes: Max Quantity = FLOOR((Capital x Leverage) / LTP)
// User can flip BUY/SELL, pick Intraday/Overnight/GTT trade type, and set
// Stop Loss, Target Price and Trailing Stop Loss. All values are returned to
// the caller on confirm; the order placement happens after the dialog closes.

import { useCallback, useEffect, useMemo, useState } from 'react'
import { intradayLeverageApi } from '@/api/intradayLeverage'
import { tradingApi } from '@/api/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { QuoteHeader } from './QuoteHeader'

export type TradeType = 'INTRADAY' | 'OVERNIGHT' | 'GTT'

export interface PositionCalculatorOutcome {
  quantity: number
  action: 'BUY' | 'SELL'
  product: 'MIS' | 'NRML' | 'CNC'
  tradeType: TradeType
  stoploss?: number
  target?: number
  trailingStoploss?: number
  gtt?: boolean
}

export interface PositionCalculatorProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  symbol: string
  exchange: string
  side: 'BUY' | 'SELL'
  ltp: number | null
  lotSize?: number
  /** Default trade type for the session's default product. */
  tradeType?: TradeType
  onConfirm: (outcome: PositionCalculatorOutcome) => void
}

const FNO_EXCHANGES = new Set(['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX'])

function defaultProductFor(exchange: string, tradeType: TradeType): 'MIS' | 'NRML' | 'CNC' {
  if (tradeType === 'INTRADAY') return 'MIS'
  return FNO_EXCHANGES.has(exchange) ? 'NRML' : 'CNC'
}

const TRADE_TYPES: { value: TradeType; label: string }[] = [
  { value: 'INTRADAY', label: 'Intraday' },
  { value: 'OVERNIGHT', label: 'Overnight' },
  { value: 'GTT', label: 'GTT' },
]

export function PositionCalculator({
  open,
  onOpenChange,
  symbol,
  exchange,
  side,
  ltp: initialLtp,
  lotSize = 1,
  tradeType: initialTradeType = 'INTRADAY',
  onConfirm,
}: PositionCalculatorProps) {
  const apiKey = useAuthStore((s) => s.apiKey)

  const [capital, setCapital] = useState<number>(0)
  const [leverage, setLeverage] = useState<number | null>(null)
  const [quantity, setQuantity] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [leverageError, setLeverageError] = useState(false)

  // Action + trade-type state, reset when the dialog opens for a new intent.
  const [action, setAction] = useState<'BUY' | 'SELL'>(side)
  const [tradeType, setTradeType] = useState<TradeType>(initialTradeType)

  // Risk inputs (optional)
  const [stoploss, setStoploss] = useState<string>('')
  const [target, setTarget] = useState<string>('')
  const [trailingStoploss, setTrailingStoploss] = useState<string>('')

  // Live quote for current price
  const { data: liveQuote, isLoading: quoteLoading } = useLiveQuote(symbol, exchange, {
    enabled: open && !!symbol,
  })

  // Use live LTP from WebSocket, fallback to prop
  const currentPrice = useMemo(() => {
    if (liveQuote?.ltp && liveQuote.ltp > 0) return liveQuote.ltp
    if (initialLtp && initialLtp > 0) return initialLtp
    return null
  }, [liveQuote?.ltp, initialLtp])

  // Reset state each time the dialog opens with a fresh intent.
  useEffect(() => {
    if (!open) return
    setAction(side)
    setTradeType(initialTradeType)
    setStoploss('')
    setTarget('')
    setTrailingStoploss('')
    setQuantity(0)
  }, [open, side, initialTradeType])

  // Fetch capital and leverage on open
  useEffect(() => {
    if (!open || !apiKey) return

    let cancelled = false
    setLoading(true)
    setLeverageError(false)

    const fetchData = async () => {
      try {
        const [fundsRes, leverageRes] = await Promise.all([
          tradingApi.getFunds(apiKey),
          intradayLeverageApi.getMultiplier(symbol, exchange),
        ])

        if (cancelled) return

        if (fundsRes.status === 'success' && fundsRes.data) {
          setCapital(fundsRes.data.availablecash || 0)
        }

        if (leverageRes.status === 'success' && leverageRes.data) {
          const mult = leverageRes.data.multiplier
          if (mult != null && mult > 0) {
            setLeverage(mult)
          } else {
            setLeverage(1)
            setLeverageError(true)
          }
        } else {
          setLeverage(1)
          setLeverageError(true)
        }
      } catch {
        if (!cancelled) {
          setLeverage(1)
          setLeverageError(true)
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    fetchData()
    return () => {
      cancelled = true
    }
  }, [open, apiKey, symbol, exchange])

  // Compute max quantity
  const maxQuantity = useMemo(() => {
    if (!capital || !leverage || !currentPrice || currentPrice <= 0) return 0
    return Math.floor((capital * leverage) / currentPrice)
  }, [capital, leverage, currentPrice])

  // Set quantity to max when computed
  useEffect(() => {
    if (open && maxQuantity > 0 && quantity === 0) {
      setQuantity(maxQuantity)
    }
  }, [open, maxQuantity, quantity])

  const handleMaxClick = useCallback(() => {
    setQuantity(maxQuantity)
  }, [maxQuantity])

  // Product follows the trade type; GTT keeps the overnight product but marks
  // the order as valid-till-triggered on confirm.
  const product = useMemo(() => defaultProductFor(exchange, tradeType), [exchange, tradeType])

  const isBuy = action === 'BUY'

  const handleConfirm = useCallback(() => {
    if (quantity <= 0) return
    const outcome: PositionCalculatorOutcome = {
      quantity,
      action,
      product,
      tradeType,
      gtt: tradeType === 'GTT',
      ...(stoploss ? { stoploss: parseFloat(stoploss) } : {}),
      ...(target ? { target: parseFloat(target) } : {}),
      ...(trailingStoploss ? { trailingStoploss: parseFloat(trailingStoploss) } : {}),
    }
    onConfirm(outcome)
    onOpenChange(false)
  }, [quantity, action, product, tradeType, stoploss, target, trailingStoploss, onConfirm, onOpenChange])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && quantity > 0) {
        handleConfirm()
      }
    },
    [quantity, handleConfirm]
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md" aria-describedby={undefined}>
        <DialogHeader className="flex flex-row items-center justify-between">
          <DialogTitle className="flex items-center gap-2">
            Position Calculator
            <Badge
              className={cn(
                'text-[10px] px-1.5 py-0',
                isBuy
                  ? 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30'
                  : 'bg-rose-500/20 text-rose-400 border-rose-500/30'
              )}
            >
              {action}
            </Badge>
          </DialogTitle>
          <div className="flex rounded-lg border border-border overflow-hidden">
            <button
              type="button"
              onClick={() => setAction('BUY')}
              className={cn(
                'px-3 py-1 text-xs font-semibold transition-colors',
                isBuy ? 'bg-emerald-600 text-white' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              BUY
            </button>
            <button
              type="button"
              onClick={() => setAction('SELL')}
              className={cn(
                'px-3 py-1 text-xs font-semibold transition-colors',
                !isBuy ? 'bg-rose-600 text-white' : 'text-muted-foreground hover:text-foreground'
              )}
            >
              SELL
            </button>
          </div>
        </DialogHeader>

        <div className="space-y-4">
          {/* Trade Type: Intraday / Overnight / GTT */}
          <div className="grid grid-cols-3 rounded-lg border border-border overflow-hidden">
            {TRADE_TYPES.map((t) => (
              <button
                key={t.value}
                type="button"
                onClick={() => setTradeType(t.value)}
                className={cn(
                  'px-2 py-1.5 text-xs font-semibold transition-colors',
                  tradeType === t.value
                    ? 'bg-primary text-primary-foreground'
                    : 'text-muted-foreground hover:text-foreground'
                )}
              >
                {t.label}
              </button>
            ))}
          </div>

          {/* Symbol and Exchange */}
          <div className="flex items-center gap-2">
            <span className="text-lg font-bold">{symbol}</span>
            <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
              {exchange}
            </Badge>
            <Badge variant="outline" className="text-[10px] px-1.5 py-0 text-cyan-400 border-cyan-500/30">
              {product}
            </Badge>
          </div>

          {/* Live Quote */}
          <QuoteHeader
            exchange={exchange}
            ltp={currentPrice ?? undefined}
            bidPrice={liveQuote?.bidPrice}
            askPrice={liveQuote?.askPrice}
            bidSize={liveQuote?.bidSize}
            askSize={liveQuote?.askSize}
            isLoading={quoteLoading && !currentPrice}
          />

          {/* Leverage */}
          <div className="flex items-center justify-between p-3 bg-muted/30 rounded-lg">
            <Label className="text-sm text-muted-foreground">Intraday Leverage</Label>
            <div className="flex items-center gap-2">
              {loading ? (
                <div className="h-5 w-12 bg-muted rounded animate-pulse" />
              ) : leverage != null ? (
                <span className="text-lg font-bold text-cyan-400">{leverage}x</span>
              ) : (
                <span className="text-sm text-muted-foreground">N/A</span>
              )}
              {leverageError && (
                <Badge variant="outline" className="text-[9px] text-amber-400 border-amber-500/30">
                  Default 1x
                </Badge>
              )}
            </div>
          </div>

          {/* Capital */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-sm text-muted-foreground">Available Capital</Label>
              {capital > 0 && (
                <span className="text-xs text-muted-foreground">(Auto-detected from account)</span>
              )}
            </div>
            {loading ? (
              <div className="h-10 bg-muted rounded animate-pulse" />
            ) : (
              <div className="relative">
                <span className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground text-sm">
                  &#8377;
                </span>
                <Input
                  type="number"
                  value={capital || ''}
                  onChange={(e) => setCapital(Math.max(0, parseFloat(e.target.value) || 0))}
                  className="pl-7"
                  min={0}
                  step={1000}
                />
              </div>
            )}
          </div>

          {/* Max Quantity Result (formula hidden) */}
          <div className="p-3 bg-muted/30 rounded-lg space-y-1">
            <Label className="text-sm text-muted-foreground">Max Quantity</Label>
            <div className="text-2xl font-bold">
              {loading ? (
                <div className="h-8 w-20 bg-muted rounded animate-pulse" />
              ) : (
                <span className={isBuy ? 'text-emerald-400' : 'text-rose-400'}>
                  {maxQuantity.toLocaleString()}
                </span>
              )}
            </div>
          </div>

          {/* Quantity Input */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-sm">Quantity</Label>
              {lotSize > 1 && <span className="text-xs text-muted-foreground">Lot size: {lotSize}</span>}
            </div>
            <div className="flex gap-2" onKeyDown={handleKeyDown}>
              <Input
                type="number"
                value={quantity || ''}
                onChange={(e) => setQuantity(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="flex-1"
                min={1}
                step={lotSize > 1 ? lotSize : 1}
              />
              <Button
                variant="outline"
                size="sm"
                onClick={handleMaxClick}
                disabled={maxQuantity <= 0}
                className="px-3"
              >
                Max
              </Button>
            </div>
          </div>

          {/* Risk section: Stop Loss, Target, Trailing SL */}
          <div className="space-y-3 p-3 bg-muted/30 rounded-lg">
            <div className="flex items-center justify-between">
              <Label className="text-sm text-muted-foreground">Risk Management</Label>
              {(stoploss || target || trailingStoploss) && (
                <Badge variant="outline" className="text-[9px] text-cyan-400 border-cyan-500/30">
                  {isBuy ? 'Below entry' : 'Above entry'}
                </Badge>
              )}
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Stop Loss</Label>
                <Input
                  type="number"
                  value={stoploss}
                  onChange={(e) => setStoploss(e.target.value)}
                  placeholder={currentPrice ? `e.g. ${currentPrice.toFixed(2)}` : 'Price'}
                  min={0}
                  step={0.05}
                />
              </div>
              <div className="space-y-1.5">
                <Label className="text-xs text-muted-foreground">Target Price</Label>
                <Input
                  type="number"
                  value={target}
                  onChange={(e) => setTarget(e.target.value)}
                  placeholder={currentPrice ? `e.g. ${currentPrice.toFixed(2)}` : 'Price'}
                  min={0}
                  step={0.05}
                />
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex-1 space-y-1.5">
                <Label className="text-xs text-muted-foreground">Trailing Stop Loss</Label>
                <Input
                  type="number"
                  value={trailingStoploss}
                  onChange={(e) => setTrailingStoploss(e.target.value)}
                  placeholder="Points e.g. 20"
                  min={0}
                  step={0.05}
                />
              </div>
              <div className="flex items-center gap-2 pt-5">
                <Label className="text-xs text-muted-foreground">GTT</Label>
                <Switch
                  checked={tradeType === 'GTT'}
                  onCheckedChange={(val) => setTradeType(val ? 'GTT' : 'OVERNIGHT')}
                />
              </div>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2 sm:gap-0">
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            onClick={handleConfirm}
            disabled={quantity <= 0 || loading}
            className={cn(
              'font-semibold',
              isBuy
                ? 'bg-emerald-600 hover:bg-emerald-700 text-white'
                : 'bg-rose-600 hover:bg-rose-700 text-white'
            )}
          >
            {isBuy ? 'BUY' : 'SELL'} {quantity.toLocaleString()} · {product}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}