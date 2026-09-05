// components/trading/PositionCalculator.tsx
// Position size calculator that appears before order placement.
// Auto-fills symbol, LTP, capital, and intraday leverage multiplier.
// Computes: Max Quantity = FLOOR((Capital x Effective Leverage) / Price)
// The multiplier applies ONLY to the Intraday trade type; Overnight and GTT
// trades size at 1x (cash only). The user can flip BUY/SELL, choose a Price
// type (Market executes now at LTP; Limit fills when the market reaches the
// chosen price), pick Intraday/Overnight/GTT, set optional Stop Loss, Target
// Price and Trailing Stop Loss, and pop up the estimated broker charges for
// the current sizing. All values are returned to the caller on confirm; the
// order placement happens after the dialog closes.
//
// The dialog is draggable by its title bar; the last position is kept in
// localStorage so it reopens where it was left. For cash equity the user can
// also switch the routing venue between NSE and BSE — the sizing, quote and
// charges all follow the chosen exchange, and the confirm sends the order
// there.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { brokerageApi, BROKERAGE_BROKERS, type BrokerageEstimate } from '@/api/brokerage'
import { intradayLeverageApi } from '@/api/intradayLeverage'
import { tradingApi } from '@/api/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useLiveQuote } from '@/hooks/useLiveQuote'
import { cn, makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { XIcon } from 'lucide-react'

export type TradeType = 'INTRADAY' | 'OVERNIGHT' | 'GTT'
export type OrderKind = 'MARKET' | 'LIMIT'

export interface PositionCalculatorOutcome {
  quantity: number
  action: 'BUY' | 'SELL'
  product: 'MIS' | 'NRML' | 'CNC'
  tradeType: TradeType
  orderType: OrderKind
  /** Routing venue. For cash equity the user may switch NSE/BSE; everything
   *  else resolves to the instrument's native exchange. */
  exchange: string
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

/** The same scrip is listed on both cash exchanges, so routing is switchable. */
const CASH_EXCHANGES = new Set(['NSE', 'BSE'])
const isCashEquity = (ex: string) => CASH_EXCHANGES.has(ex)

function defaultProductFor(exchange: string, tradeType: TradeType): 'MIS' | 'NRML' | 'CNC' {
  if (tradeType === 'INTRADAY') return 'MIS'
  return FNO_EXCHANGES.has(exchange) ? 'NRML' : 'CNC'
}

const TRADE_TYPES: { value: TradeType; label: string }[] = [
  { value: 'INTRADAY', label: 'Intraday' },
  { value: 'OVERNIGHT', label: 'Overnight' },
  { value: 'GTT', label: 'GTT' },
]

const PRICE_TYPES: { value: OrderKind; label: string; hint: string }[] = [
  { value: 'MARKET', label: 'Market', hint: 'current price' },
  { value: 'LIMIT', label: 'Limit', hint: 'your price' },
]

const COMPONENT_LABELS: [keyof BrokerageEstimate['components'], string][] = [
  ['brokerage', 'Brokerage'],
  ['stt', 'STT'],
  ['exchange_txn', 'Exchange Txn'],
  ['sebi', 'SEBI'],
  ['ipft', 'IPFT'],
  ['clearing_charges', 'Clearing'],
  ['stamp_duty', 'Stamp Duty'],
  ['dp_charges', 'DP Charges'],
  ['gst', 'GST'],
]

function isBrokerageSupported(broker: string | null | undefined): boolean {
  return !!broker && BROKERAGE_BROKERS.has(broker.toLowerCase())
}

/** Box-shadow used for "raised" 3D tiles (light source top-left). */
const RAISED =
  'shadow-[0_1px_0_rgba(255,255,255,0.08)_inset,0_-1px_0_rgba(0,0,0,0.4)_inset,0_4px_8px_-2px_rgba(0,0,0,0.6)]'
/** Box-shadow used for the active/pressed 3D tile. */
const PRESSED =
  'shadow-[0_-1px_0_rgba(0,0,0,0.5)_inset,0_1px_0_rgba(255,255,255,0.06)_inset,0_2px_6px_rgba(0,0,0,0.5)] translate-y-[1px]'

/** Where the dialog's dragged offset is persisted, so it reopens where it was left. */
const CALC_POS_KEY = 'openalgo:position-calculator-pos'

interface CalcPos {
  x: number
  y: number
}

function loadCalcPos(): CalcPos {
  try {
    const raw = localStorage.getItem(CALC_POS_KEY)
    if (raw) {
      const parsed = JSON.parse(raw) as Partial<CalcPos>
      if (typeof parsed.x === 'number' && typeof parsed.y === 'number') {
        return { x: parsed.x, y: parsed.y }
      }
    }
  } catch {
    // Corrupt or unavailable storage — fall through to centered.
  }
  return { x: 0, y: 0 }
}

function saveCalcPos(pos: CalcPos) {
  try {
    localStorage.setItem(CALC_POS_KEY, JSON.stringify(pos))
  } catch {
    // Storage unavailable — geometry is a nicety, not a requirement.
  }
}

function Tile({
  active,
  activeClass,
  onClick,
  children,
  className,
  title,
}: {
  active: boolean
  activeClass: string
  onClick: () => void
  children: React.ReactNode
  className?: string
  title?: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={cn(
        'relative rounded-lg px-2 py-1.5 text-xs font-bold tracking-wide transition-all duration-150 select-none',
        active
          ? cn(PRESSED, activeClass, 'text-white')
          : cn(
              RAISED,
              'bg-muted/60 text-muted-foreground',
              'hover:-translate-y-px hover:text-white'
            ),
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
  const broker = useAuthStore((s) => s.user?.broker)
  const formatCurrency = useMemo(() => makeFormatCurrency(broker), [broker])

  const [capital, setCapital] = useState<number>(0)
  const [leverage, setLeverage] = useState<number | null>(null)
  const [quantity, setQuantity] = useState<number>(0)
  const [loading, setLoading] = useState(true)
  const [leverageError, setLeverageError] = useState(false)

  // Action, trade-type and price-type state, reset when the dialog opens.
  const [action, setAction] = useState<'BUY' | 'SELL'>(side)
  const [tradeType, setTradeType] = useState<TradeType>(initialTradeType)
  const [orderType, setOrderType] = useState<OrderKind>('MARKET')
  const [limitPrice, setLimitPrice] = useState<string>('')
  // Routing venue. Cash equity may switch NSE/BSE; everything else is fixed
  // to the instrument's exchange and shows no toggle.
  const [calcExchange, setCalcExchange] = useState(exchange)

  // Dragged offset, persisted across sessions so the dialog reopens where the
  // user left it. Clamped on drag so it cannot be lost off-screen.
  const [dragPos, setDragPos] = useState<CalcPos>(loadCalcPos)
  const dragStart = useRef<{
    pointerX: number
    pointerY: number
    posX: number
    posY: number
  } | null>(null)

  // Risk inputs (optional), revealed by the "Add Stop Loss / Target Price" row.
  const [riskOpen, setRiskOpen] = useState(false)
  const [stoploss, setStoploss] = useState<string>('')
  const [target, setTarget] = useState<string>('')
  const [trailingStoploss, setTrailingStoploss] = useState<string>('')

  // Brokerage estimate (only for Fyers / Zerodha / Dhan / Groww).
  const brokerageSupported = isBrokerageSupported(broker)
  const [brokerageOpen, setBrokerageOpen] = useState(false)
  const [brokerage, setBrokerage] = useState<BrokerageEstimate | null>(null)
  const [brokerageLoading, setBrokerageLoading] = useState(false)
  const [brokerageError, setBrokerageError] = useState<string | null>(null)

  // Live quote for current price
  const { data: liveQuote, isLoading: quoteLoading } = useLiveQuote(symbol, calcExchange, {
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
    setCalcExchange(exchange)
    setStoploss('')
    setTarget('')
    setTrailingStoploss('')
    setQuantity(0)
    setRiskOpen(false)
    setBrokerageOpen(false)
    setBrokerage(null)
    setBrokerageError(null)
  }, [open, side, initialTradeType, exchange])

  // Keep the dragged offset in storage so the dialog reopens where it was left.
  useEffect(() => {
    if (!open) return
    saveCalcPos(dragPos)
  }, [dragPos, open])

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
          intradayLeverageApi.getMultiplier(symbol, calcExchange),
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
  }, [open, apiKey, symbol, calcExchange])

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
  // price type, limit price) change, clamp so quantity never overshoots.
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

  const selectExchange = useCallback((ex: string) => {
    setCalcExchange(ex)
    setQuantity(0)
    setBrokerageOpen(false)
    setBrokerage(null)
    setBrokerageError(null)
  }, [])

  // Drag by the title bar. The offset is applied as a transform on an inner
  // wrapper so the Radix open/close animation on the content is untouched.
  const clampDragPos = useCallback((pos: CalcPos) => {
    const padX = 40
    const padY = 40
    const maxX = Math.max(padX, window.innerWidth / 2 - padX)
    const maxY = Math.max(padY, window.innerHeight / 2 - padY)
    return {
      x: Math.max(-maxX, Math.min(maxX, pos.x)),
      y: Math.max(-maxY, Math.min(maxY, pos.y)),
    }
  }, [])

  const onDragStart = useCallback(
    (e: React.PointerEvent<HTMLDivElement>) => {
      if (e.button !== 0) return
      e.preventDefault()
      dragStart.current = {
        pointerX: e.clientX,
        pointerY: e.clientY,
        posX: dragPos.x,
        posY: dragPos.y,
      }
      const onMove = (ev: PointerEvent) => {
        const start = dragStart.current
        if (!start) return
        setDragPos(
          clampDragPos({
            x: start.posX + ev.clientX - start.pointerX,
            y: start.posY + ev.clientY - start.pointerY,
          })
        )
      }
      const onUp = () => {
        dragStart.current = null
        window.removeEventListener('pointermove', onMove)
        window.removeEventListener('pointerup', onUp)
      }
      window.addEventListener('pointermove', onMove)
      window.addEventListener('pointerup', onUp)
    },
    [dragPos, clampDragPos]
  )

  // Product follows the trade type; GTT keeps the overnight product but marks
  // the order as valid-till-triggered on confirm.
  const product = useMemo(
    () => defaultProductFor(calcExchange, tradeType),
    [calcExchange, tradeType]
  )

  const isBuy = action === 'BUY'

  const limitParsed = parseFloat(limitPrice)
  const limitPriceValid =
    orderType !== 'LIMIT' || limitPriceValidForSide(limitParsed, isBuy, currentPrice)
  const canConfirm = quantity > 0 && !loading && limitPriceValid

  // A buy limit below LTP (or sell limit above) is the only layout in which
  // the market can cross the price; everything else fills immediately, so the
  // helper exists to explain what a valid limit is rather than to block.
  function limitPriceValidForSide(p: number, buy: boolean, ltp: number | null): boolean {
    if (!(p > 0)) return false
    if (ltp == null || ltp <= 0) return true
    return buy ? p < ltp : p > ltp
  }

  // Fetch the brokerage estimate whenever the sizing changes.
  useEffect(() => {
    if (!open || !brokerageSupported || quantity <= 0 || !orderPriceBasis || orderPriceBasis <= 0) {
      if (!open) setBrokerage(null)
      return
    }

    let cancelled = false
    setBrokerageLoading(true)
    setBrokerageError(null)

    const timer = setTimeout(async () => {
      try {
        const res = await brokerageApi.estimate({
          symbol,
          exchange: calcExchange,
          product,
          side: action,
          quantity,
          price: orderPriceBasis,
          ...(lotSize > 1 ? { lotSize } : {}),
        })
        if (cancelled) return
        if (res.status === 'success' && res.data) {
          setBrokerage(res.data)
        } else {
          setBrokerage(null)
          setBrokerageError('Unable to estimate')
        }
      } catch {
        if (!cancelled) {
          setBrokerage(null)
          setBrokerageError('Unable to estimate')
        }
      } finally {
        if (!cancelled) setBrokerageLoading(false)
      }
    }, 400)

    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [
    open,
    brokerageSupported,
    quantity,
    orderPriceBasis,
    symbol,
    calcExchange,
    product,
    action,
    lotSize,
  ])

  const handleConfirm = useCallback(() => {
    if (!canConfirm) return
    const outcome: PositionCalculatorOutcome = {
      quantity,
      action,
      product,
      tradeType,
      orderType,
      exchange: calcExchange,
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
    calcExchange,
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

  const brokerageTotal = brokerage?.total ?? null

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className="sm:max-w-lg gap-0 p-0 rounded-none border-0 bg-transparent shadow-none"
        aria-describedby={undefined}
        onKeyDown={handleKeyDown}
        showCloseButton={false}
      >
        {/* The drag offset is applied to this inner wrapper so the Radix
            open/close animation on the content keeps its own transform.
            The dialog's own frame (background, border, shadow) lives here
            too, so the whole card moves with the drag — never just the text
            inside a static shell. */}
        <div
          className="relative overflow-hidden rounded-lg border bg-background shadow-lg"
          style={{ transform: `translate(${dragPos.x}px, ${dragPos.y}px)` }}
        >
          <div className="pointer-events-none absolute inset-x-0 -top-px h-px bg-gradient-to-r from-transparent via-emerald-400/70 to-transparent" />

          <DialogHeader className="w-full px-6 pt-5 pb-0">
            <div className="flex items-start justify-between gap-3">
              {/* Stock name beside the current trading price. The title bar
                  is the drag handle — grab it to move the dialog around. */}
              <DialogTitle
                className="flex items-center gap-2.5 cursor-grab active:cursor-grabbing select-none touch-none"
                title="Drag to move"
                onPointerDown={onDragStart}
              >
                <span className="text-xl font-extrabold tracking-tight">{symbol}</span>
                <span
                  className={cn(
                    'text-base font-semibold font-mono tabular-nums',
                    currentPrice
                      ? isBuy
                        ? 'text-emerald-400'
                        : 'text-rose-400'
                      : 'text-muted-foreground'
                  )}
                >
                  {quoteLoading && !currentPrice ? '…' : formatCurrency(currentPrice ?? 0)}
                </span>
                <div className="flex flex-col items-start gap-1">
                  <Badge variant="secondary" className="text-[10px] px-1.5 py-0">
                    {calcExchange}
                  </Badge>
                  <Badge
                    variant="outline"
                    className="text-[10px] px-1.5 py-0 text-cyan-400 border-cyan-500/30"
                  >
                    {product}
                  </Badge>
                </div>
              </DialogTitle>
              <div className="flex items-center gap-2">
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
                <DialogClose className="ring-offset-background focus:ring-ring data-[state=open]:bg-accent data-[state=open]:text-muted-foreground rounded-xs opacity-70 transition-opacity hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-hidden disabled:pointer-events-none [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4">
                  <XIcon />
                  <span className="sr-only">Close</span>
                </DialogClose>
              </div>
            </div>

            {/* Routing venue, for cash equity only. The same scrip is listed
                on both NSE and BSE, so the user picks where to send it;
                derivatives are contract-specific and stay put. */}
            {isCashEquity(exchange) && (
              <div className="mt-2 flex items-center justify-between">
                <Label className="text-[10px] uppercase tracking-wider text-muted-foreground">
                  Exchange
                </Label>
                <div className="flex gap-1 p-1 rounded-lg bg-gradient-to-b from-black/40 to-black/20 ring-1 ring-white/10 shadow-[inset_0_1px_2px_rgba(0,0,0,0.5),0_1px_0_rgba(255,255,255,0.05)]">
                  {['NSE', 'BSE'].map((ex) => (
                    <Tile
                      key={ex}
                      active={calcExchange === ex}
                      activeClass="bg-gradient-to-b from-sky-500 to-sky-700 ring-1 ring-sky-300/40"
                      onClick={() => selectExchange(ex)}
                      className="px-3 py-1"
                    >
                      {ex}
                    </Tile>
                  ))}
                </div>
              </div>
            )}
          </DialogHeader>

          <div className="space-y-4 max-h-[68vh] overflow-y-auto px-6 py-4 pr-4">
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

            {/* Price: Market / Limit, as a compact segmented toggle */}
            <div className="p-3 rounded-2xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 ring-1 ring-white/10 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.8)]">
              <div className="flex items-center justify-between gap-2">
                <Label className="text-xs uppercase tracking-wider text-muted-foreground">
                  Price
                </Label>
                <div className="flex gap-1 p-1 rounded-lg bg-gradient-to-b from-black/40 to-black/20 ring-1 ring-white/10 shadow-[inset_0_1px_2px_rgba(0,0,0,0.5),0_1px_0_rgba(255,255,255,0.05)]">
                  {PRICE_TYPES.map((o) => {
                    const active = orderType === o.value
                    return (
                      <Tile
                        key={o.value}
                        active={active}
                        activeClass="bg-gradient-to-b from-sky-500 to-sky-700 ring-1 ring-sky-300/40"
                        onClick={() => selectOrderType(o.value)}
                        className="px-3 py-1"
                        title={o.hint}
                      >
                        {o.label}
                      </Tile>
                    )
                  })}
                </div>
              </div>
              {orderType === 'LIMIT' ? (
                <div className="mt-2 space-y-2">
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
              ) : (
                <div className="mt-2 rounded-lg bg-black/30 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground ring-1 ring-white/5">
                  Executes immediately at the current market price.
                </div>
              )}
            </div>

            {/* Capital */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-sm text-muted-foreground">Capital</Label>
                {capital > 0 && (
                  <span className="text-xs text-muted-foreground">
                    (Auto-detected from account)
                  </span>
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

            {/* Quantity + Leverage (just the number) */}
            <div className="p-3 rounded-2xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 ring-1 ring-white/10 shadow-[0_16px_32px_-16px_rgba(0,0,0,0.8)]">
              <div className="flex items-center justify-between">
                <Label className="text-sm">Quantity</Label>
                <div className="flex items-center gap-2">
                  {lotSize > 1 && (
                    <span className="text-[11px] text-muted-foreground">Lot · {lotSize}</span>
                  )}
                  <span className="text-[11px] text-muted-foreground">
                    Leverage{' '}
                    {loading ? (
                      '…'
                    ) : (
                      <span className="text-base font-bold text-cyan-400 tabular-nums">
                        {effectiveLeverage}x
                      </span>
                    )}
                  </span>
                  {leverageError && isIntraday && (
                    <Badge
                      variant="outline"
                      className="text-[9px] text-amber-400 border-amber-500/30"
                    >
                      Default
                    </Badge>
                  )}
                </div>
              </div>
              <div className="mt-2 flex gap-2">
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
              <div className="mt-2 flex items-center justify-between gap-2">
                <span className="text-[11px] text-muted-foreground">
                  Max Qty{' '}
                  {loading ? (
                    '…'
                  ) : (
                    <span
                      className={cn('font-semibold', isBuy ? 'text-emerald-400' : 'text-rose-400')}
                    >
                      {maxQuantity.toLocaleString()}
                    </span>
                  )}
                </span>

                {/* Brokerage chip - small section, details pop on click */}
                {brokerageSupported && (
                  <button
                    type="button"
                    onClick={() => setBrokerageOpen((v) => !v)}
                    className={cn(
                      'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-semibold ring-1 transition-colors',
                      brokerageOpen
                        ? 'bg-cyan-500/15 text-cyan-400 ring-cyan-500/30'
                        : 'bg-muted/60 text-muted-foreground ring-white/10 hover:text-cyan-400 hover:ring-cyan-500/30'
                    )}
                    disabled={brokerageLoading || (!brokerage && !!brokerageError)}
                    title={
                      brokerageError
                        ? brokerageError
                        : brokerage
                          ? `Estimated ${brokerage.segment} charges for this trade`
                          : undefined
                    }
                  >
                    Brokerage
                    {brokerageLoading ? (
                      <span className="h-3 w-8 bg-muted rounded animate-pulse" />
                    ) : brokerageTotal != null ? (
                      <span className="font-mono tabular-nums">
                        {formatCurrency(brokerageTotal)}
                      </span>
                    ) : brokerageError ? (
                      <span className="text-amber-400">—</span>
                    ) : null}
                  </button>
                )}
              </div>

              {/* Brokerage details popup */}
              {brokerageSupported && brokerageOpen && (
                <div className="mt-2 rounded-xl bg-black/30 p-3 ring-1 ring-white/5">
                  {brokerage ? (
                    <>
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          {brokerage.segment}
                        </span>
                        <Badge variant="outline" className="text-[9px] px-1.5 py-0">
                          Est. turnover {formatCurrency(brokerage.turnover)}
                        </Badge>
                      </div>
                      <div className="mt-2 space-y-1.5">
                        {COMPONENT_LABELS.map(([key, label]) => {
                          const value = brokerage.components[key]
                          if (value == null || value === 0) return null
                          return (
                            <div key={key} className="flex items-center justify-between text-xs">
                              <span className="text-muted-foreground">{label}</span>
                              <span className="font-mono tabular-nums">
                                {formatCurrency(value)}
                              </span>
                            </div>
                          )
                        })}
                      </div>
                      <div className="mt-2 flex items-center justify-between border-t border-white/10 pt-2">
                        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                          Total
                        </span>
                        <span className="text-sm font-bold font-mono tabular-nums text-cyan-400">
                          {formatCurrency(brokerage.total)}
                        </span>
                      </div>
                      <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground">
                        Estimated charges; actual figures levied by the broker may differ.
                        {brokerage.lot_size === 1 &&
                        brokerage.segment !== 'Equity Delivery' &&
                        brokerage.segment !== 'Equity Intraday'
                          ? ' Lot size 1 used - the figure scales with contract size.'
                          : ''}
                      </p>
                    </>
                  ) : brokerageLoading ? (
                    <div className="space-y-1.5">
                      <div className="h-2.5 w-2/3 bg-muted rounded animate-pulse" />
                      <div className="h-2.5 w-1/2 bg-muted rounded animate-pulse" />
                      <div className="h-2.5 w-3/4 bg-muted rounded animate-pulse" />
                    </div>
                  ) : (
                    <p className="text-[11px] text-muted-foreground">Unable to estimate charges.</p>
                  )}
                </div>
              )}
            </div>

            {/* Add Stop Loss / Target Price */}
            <div className="space-y-2">
              <button
                type="button"
                onClick={() => setRiskOpen((v) => !v)}
                className="flex w-full items-center justify-between rounded-xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 px-3 py-2.5 ring-1 ring-white/10 transition-colors hover:ring-white/20"
              >
                <span className="flex items-center gap-2">
                  <Label className="cursor-pointer text-sm">Add Stop Loss / Target Price</Label>
                  {(stoploss || target || trailingStoploss) && (
                    <Badge
                      variant="outline"
                      className="text-[9px] text-cyan-400 border-cyan-500/30"
                    >
                      {isBuy ? 'Below entry' : 'Above entry'}
                    </Badge>
                  )}
                </span>
                <span
                  className={cn(
                    'text-muted-foreground transition-transform duration-200',
                    riskOpen && 'rotate-180'
                  )}
                >
                  ▼
                </span>
              </button>
              {riskOpen && (
                <div className="space-y-3 rounded-2xl bg-gradient-to-b from-zinc-900/90 to-zinc-950/90 p-3 ring-1 ring-white/10">
                  <div className="grid grid-cols-2 gap-3">
                    <div className="space-y-1.5">
                      <Label className="text-xs text-muted-foreground">Stop Loss</Label>
                      <Input
                        type="number"
                        value={stoploss}
                        onChange={(e) => setStoploss(e.target.value)}
                        placeholder={
                          orderPriceBasis ? `e.g. ${orderPriceBasis.toFixed(2)}` : 'Price'
                        }
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
                        placeholder={
                          orderPriceBasis ? `e.g. ${orderPriceBasis.toFixed(2)}` : 'Price'
                        }
                        min={0}
                        step={0.05}
                      />
                    </div>
                  </div>
                  <div className="space-y-1.5">
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
                </div>
              )}
            </div>
          </div>

          <DialogFooter className="gap-2 px-6 pb-5 pt-0 sm:gap-0">
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
        </div>
      </DialogContent>
    </Dialog>
  )
}
