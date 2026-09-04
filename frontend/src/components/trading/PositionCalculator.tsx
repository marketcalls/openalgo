// components/trading/PositionCalculator.tsx
// Intraday position size calculator that appears before order placement.
// Auto-fills symbol, LTP, capital, and intraday leverage multiplier.
// Computes: Max Quantity = FLOOR((Capital x Effective Leverage) / Price)
// The multiplier applies ONLY to the Intraday trade type; Overnight and GTT
// trades size at 1x (cash only). The user can flip BUY/SELL, choose an order
// type (Market executes now at LTP; Limit fills when the market reaches the
// chosen price), pick Intraday/Overnight/GTT, and set optional Stop Loss,
// Target Price and Trailing Stop Loss. All values are returned to the caller
// on confirm; the order placement happens after the dialog closes.

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
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { QuoteHeader } from './QuoteHeader'

export type TradeType = 'INTRADAY' | 'OVERNIGHT' | 'GTT'
export type OrderKind = 'MARKET' | 'LIMIT'

export interface PositionCalculatorOutcome {
  quantity: number
  action: 'BUY' | 'SELL'
  product: 'MIS' | 'NRML' | 'CNC'
  tradeType: TradeType
  orderType: OrderKind
  /** Limit price when orderType === 'LIMIT'; undefined for market orders. */
  price?: number
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

const ORDER_TYPES: { value: OrderKind; label: string; hint: string }[] = [
  { value: 'MARKET', label: 'Market', hint: 'current price' },
  { value: 'LIMIT', label: 'Limit', hint: 'your price' },
]

/** Box-shadow used for "raised" 3D tiles (light source top-left). */
const RAISED =
  'shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_-1px_0_rgba(0,0,0,0.4)_inset,0_4px_8px_-2px_rgba(0,0,0,0.6)]'
/** Box-shadow used for the active/pressed 3D tile. */
const PRESSED =
  'shadow-[0_-1px_0_rgba(0,0,0,0.5)_inset,0_1px_0_rgba(255,255,255,0.06)_inset,0_2px_6px_rgba(0,0,0,0.5)] translate-y-[1px]'

function Tile({
  active,
  activeClass,
  onClick,
  children,
  className,
}: {
  active: boolean
  activeClass: string
  onClick: () => void
  children: React.ReactNode
  className?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        'relative rounded-lg px-2 py-1.5 text-xs font-bold tracking-wide transition-all duration-150 select-none',
        active ? cn(PRESSED, activeClass, 'text-white') : cn(RAISED, 'bg-muted/60 text-muted-foreground'),
        className
      )}
    >
      {children}
    </button>
  )
}

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

  // Action, trade-type and order-type state, reset when the dialog opens.
  const [action, setAction] = useState<'BUY' | 'SELL'>(side)
  const [tradeType, setTradeType] = useState<TradeType>(initialTradeType)
  const [orderType, setOrderType] = useState<OrderKind>('MARKET')
  const [limitPrice, setLimitPrice] = useState<string>('')

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
    setOrderType('MARKET')
    setLimitPrice('')
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

  // Leverage gate: the intraday multiplier applies ONLY intraday. Overnight
  // and GTT trades are cash-only (1x).
  const isIntraday = tradeType === 'INTRADAY'
  const effectiveLeverage = isIntraday ? leverage : 1

  // Price basis for sizing: a limit order reserves cash at the limit price
  // (worst case for a buy); a market order sizes against the live LTP.
  const orderPriceBasis = useMemo(() => {
    if (orderType === 'LIMIT') {
      const p = parseFloat(limitPrice)
      if (p > 0) return p
    }
    return currentPrice
  }, [orderType, limitPrice, currentPrice])

  // Compute max quantity: FLOOR((Capital x Effective Leverage) / Price)
  const maxQuantity = useMemo(() => {
    if (!capital || !effectiveLeverage || !orderPriceBasis || orderPriceBasis <= 0) return 0
    return Math.floor((capital * effectiveLeverage) / orderPriceBasis)
  }, [capital, effectiveLeverage, orderPriceBasis])

  // Set quantity to max when computed; when the sizing inputs (trade type,
  // order type, limit price) change, clamp so quantity never overshoots.
  useEffect(() => {
    if (!open || maxQuantity <= 0) return
    setQuantity((q) => (q <= 0 ? maxQuantity : Math.min(q, maxQuantity)))
  }, [open, maxQuantity])

  const handleMaxClick = useCallback(() => {
    setQuantity(maxQuantity)
  }, [maxQuantity])

  const selectTradeType = useCallback((t: TradeType) => {
    setTradeType(t)
    setQuantity(0)
  }, [])

  const selectOrderType = useCallback((o: OrderKind) => {
    setOrderType(o)
    setQuantity(0)
  }, [])

  // Product follows the trade type; GTT keeps the overnight product but marks
  // the order as valid-till-triggered on confirm.
  const product = useMemo(() => defaultProductFor(exchange, tradeType), [exchange, tradeType])

  const isBuy = action === 'BUY'

  const limitParsed = parseFloat(limitPrice)
  const limitPriceValid = orderType !== 'LIMIT' || (limitPriceValidForSide(limitParsed, isBuy, currentPrice))
  const canConfirm = quantity > 0 && !loading && limitPriceValid

  // A buy limit below LTP (or sell limit above) is the only layout in which
  // the market can cross the price; everything else fills immediately, so the
  // helper exists to explain what a valid limit is rather than to block.
  function limitPriceValidForSide(p: number, buy: boolean, ltp: number | null): boolean {
    if (!(p > 0)) return false
    if (ltp == null || ltp <= 0) return true
    return buy ? p < ltp : p > ltp
  }

  const handleConfirm = useCallback(() => {
    if (!canConfirm) return
    const outcome: PositionCalculatorOutcome = {
      quantity,
      action,
      product,
      tradeType,
      orderType,
      ...(orderType === 'LIMIT' && limitPriceValid ? { price: parseFloat(limitPrice) } : {}),
      gtt: tradeType === 'GTT',
      ...(stoploss ? { stoploss: parseFloat(stoploss) } : {}),
      ...(target ? { target: parseFloat(target) } : {}),
      ...(trailingStoploss ? { trailingStoploss: parseFloat(trailingStoploss) } : {}),
    }
    onConfirm(outcome)
    onOpenChange(false)
  }, [
    canConfirm,
    quantity,
    action,
    product,
    tradeType,
    orderType,
    limitPriceValid,
    limitPrice,
    stoploss,
    target,
    trailingStoploss,
    onConfirm,
    onOpenChange,
  ])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' && canConfirm) {
        handleConfirm()
      }
    },
    [canConfirm, handleConfirm]
  )

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-md"
        aria-describedby={undefined}
        onKeyDown={handleKeyDown}
      >
        <div className="pointer-events-none absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent" />

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
          {/* 3D Buy / Sell toggle */}
          <div className="flex gap-1.5 p-1 rounded-xl bg-gradient-to-b from-black/40 to-black/20 ring-1 ring-white/10">
            {(['BUY', 'SELL'] as const).map((s) => {
              const active = action === s
              return (
                <Tile
                  key={s}
                  active={active}
                  activeClass={
                    s === 'BUY'
                      ? 'bg-gradient-to-b from-emerald-500 to-emerald-700 ring-1 ring-emerald-300/40'
                      : 'bg-gradient-to-b from-rose-500 to-rose-700 ring-1 ring-rose-300/40'
                  }
                  onClick={() => setAction(s)}
                  className="px-4 py-1.5"
                >
                  {s}
                </Tile>
              )
            })}
          </div>
        </DialogHeader>

        <div className="space-y-4">
          {/* Order type: Market / Limit */}
          <div className="p-3 rounded-2xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 ring-1 ring-white/10 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.8)]">
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">
              Order Type
            </Label>
            <div className="mt-2 grid grid-cols-2 gap-2">
              {ORDER_TYPES.map((o) => {
                const active = orderType === o.value
                return (
                  <Tile
                    key={o.value}
                    active={active}
                    activeClass="bg-gradient-to-b from-sky-500 to-sky-700 ring-1 ring-sky-300/40"
                    onClick={() => selectOrderType(o.value)}
                    className="flex flex-col items-start px-3 py-2 rounded-xl"
                  >
                    <span className="text-sm">{o.label}</span>
                    <span
                      className={cn(
                        'text-[10px] font-medium',
                        active ? 'text-white/80' : 'text-muted-foreground'
                      )}
                    >
                      {o.hint}
                    </span>
                  </Tile>
                )
              })}
            </div>
            <div className="mt-2 rounded-lg bg-black/30 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground ring-1 ring-white/5">
              {orderType === 'MARKET'
                ? 'Executes immediately at the current market price.'
                : 'Scheduled order: fills when the market trades at your price.'}
            </div>
          </div>

          {/* Trade Type: Intraday / Overnight / GTT */}
          <div>
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">
              Trade Type
            </Label>
            <div className="mt-2 grid grid-cols-3 gap-2">
              {TRADE_TYPES.map((t) => {
                const active = tradeType === t.value
                return (
                  <Tile
                    key={t.value}
                    active={active}
                    activeClass="bg-gradient-to-b from-indigo-500 to-indigo-700 ring-1 ring-indigo-300/40"
                    onClick={() => selectTradeType(t.value)}
                    className="rounded-xl py-2"
                  >
                    {t.label}
                  </Tile>
                )
              })}
            </div>
          </div>

          {/* Symbol, exchange and product */}
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

          {/* Limit price */}
          {orderType === 'LIMIT' && (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm text-muted-foreground">Limit Price</Label>
                {currentPrice && (
                  <span className="text-xs text-muted-foreground">
                    LTP: {currentPrice.toFixed(2)}
                  </span>
                )}
              </div>
              <Input
                type="number"
                value={limitPrice}
                onChange={(e) => setLimitPrice(e.target.value)}
                placeholder={currentPrice ? `e.g. ${currentPrice.toFixed(2)}` : 'Price'}
                min={0}
                step={0.05}
              />
              {limitPrice && !limitPriceValid && currentPrice && (
                <p className="text-[11px] text-amber-400">
                  {isBuy
                    ? 'A buy limit above the market fills immediately. Set a price below LTP to schedule.'
                    : 'A sell limit below the market fills immediately. Set a price above LTP to schedule.'}
                </p>
              )}
            </div>
          )}

          {/* Leverage (Intraday only) */}
          <div className="flex items-center justify-between p-3 rounded-xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 ring-1 ring-white/10">
            <Label className="text-sm text-muted-foreground">
              {isIntraday ? 'Intraday Leverage' : 'Leverage (not applicable)'}
            </Label>
            <div className="flex items-center gap-2">
              {loading ? (
                <div className="h-5 w-12 bg-muted rounded animate-pulse" />
              ) : isIntraday && leverage != null ? (
                <span className="text-lg font-bold text-cyan-400">{leverage}x</span>
              ) : (
                <span className="text-sm text-muted-foreground">{isIntraday ? 'N/A' : '1x'}</span>
              )}
              {leverageError && isIntraday && (
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
          <div className="relative overflow-hidden p-4 rounded-2xl bg-gradient-to-br from-zinc-900 via-zinc-950 to-black ring-1 ring-white/10 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.9)]">
            <div
              className={cn(
                'pointer-events-none absolute -right-8 -top-8 h-28 w-28 rounded-full blur-3xl opacity-40',
                isBuy ? 'bg-emerald-600' : 'bg-rose-600'
              )}
            />
            <Label className="text-xs uppercase tracking-wider text-muted-foreground">
              Max Quantity
            </Label>
            <div className="relative mt-1 text-2xl font-bold">
              {loading ? (
                <div className="h-8 w-20 bg-muted rounded animate-pulse" />
              ) : (
                <span className={isBuy ? 'text-emerald-400' : 'text-rose-400'}>
                  {maxQuantity.toLocaleString()}
                </span>
              )}
            </div>
            {!isIntraday && leverage != null && leverage > 1 && (
              <p className="relative mt-1 text-[10px] text-muted-foreground">
                {tradeType} trades size at cash value (no {leverage}x leverage)
              </p>
            )}
          </div>

          {/* Quantity Input */}
          <div className="space-y-2">
            <div className="flex items-center justify-between">
              <Label className="text-sm">Quantity</Label>
              {lotSize > 1 && <span className="text-xs text-muted-foreground">Lot size: {lotSize}</span>}
            </div>
            <div className="flex gap-2">
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
          <div className="space-y-3 p-3 rounded-2xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 ring-1 ring-white/10">
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
                  placeholder={orderPriceBasis ? `e.g. ${orderPriceBasis.toFixed(2)}` : 'Price'}
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
                  placeholder={orderPriceBasis ? `e.g. ${orderPriceBasis.toFixed(2)}` : 'Price'}
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
                <div
                  className={cn(
                    'w-9 h-5 rounded-full p-0.5 ring-1 transition-colors cursor-pointer',
                    tradeType === 'GTT'
                      ? 'bg-gradient-to-b from-indigo-500 to-indigo-700 ring-indigo-300/40'
                      : 'bg-muted ring-white/10'
                  )}
                  onClick={() => setTradeType(tradeType === 'GTT' ? 'OVERNIGHT' : 'GTT')}
                >
                  <div
                    className={cn(
                      'h-4 w-4 rounded-full bg-white shadow transition-transform',
                      tradeType === 'GTT' ? 'translate-x-4' : 'translate-x-0'
                    )}
                  />
                </div>
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
            disabled={!canConfirm}
            className={cn(
              'font-semibold shadow-[0_8px_20px_-8px_rgba(0,0,0,0.8)]',
              isBuy
                ? 'bg-gradient-to-b from-emerald-500 to-emerald-700 hover:from-emerald-400 hover:to-emerald-600 text-white ring-1 ring-emerald-300/40'
                : 'bg-gradient-to-b from-rose-500 to-rose-700 hover:from-rose-400 hover:to-rose-600 text-white ring-1 ring-rose-300/40'
            )}
          >
            {isBuy ? 'BUY' : 'SELL'} {quantity.toLocaleString()} · {product}
            {orderType === 'MARKET' ? ' · Market' : ' · Limit'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}