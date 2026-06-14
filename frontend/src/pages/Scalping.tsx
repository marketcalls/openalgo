import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { tradingApi } from '@/api/trading'
import { SetSLDialog } from '@/components/scalping/SetSLDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useMarketData } from '@/hooks/useMarketData'
import { useOrderEventRefresh } from '@/hooks/useOrderEventRefresh'
import { findLegSL, type SLState, useTrailingSL } from '@/hooks/useTrailingSL'
import { buildPositionRows } from '@/lib/scalpingRows'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import type {
  OptionChainRow,
  OptionType,
  ScalpingAction,
  ScalpingPositionRow,
  ScalpingProduct,
  SearchInstrument,
  Segment,
  SelectedLeg,
} from '@/types/scalping'
import { showToast } from '@/utils/toast'

const DEFAULT_STRIKE_COUNT = 10
const MAX_LOTS = 20
const ORDER_COOLDOWN_MS = 120 // min gap between two order fires (anti double-fire)
const ARMED_STORAGE_KEY = 'scalping.armed'

// Order/position events that should refresh the books (event-driven, no polling).
const BOOK_EVENTS = [
  'order_event',
  'analyzer_update',
  'close_position_event',
  'cancel_order_event',
  'modify_order_event',
] as const

// Which leg/product the Set-SL dialog is editing.
interface SLTarget {
  symbol: string
  exchange: string
  product: ScalpingProduct
  optionType: OptionType
}

// Display label for product (OpenAlgo value stays MIS/NRML on the wire).
function productLabel(p: string): string {
  return p === 'NRML' ? 'MARGIN' : p
}

// Read the persisted One-Click arm state (captured across reloads).
function loadArmed(): boolean {
  try {
    return localStorage.getItem(ARMED_STORAGE_KEY) === '1'
  } catch {
    return false
  }
}

// Pull the trader-friendly reason out of an API error (e.g. the broker/sandbox
// rejection message), falling back to the axios/network message.
function apiErrorMessage(e: unknown): string {
  const err = e as { response?: { data?: { message?: string } }; message?: string }
  return err.response?.data?.message || err.message || 'Order failed'
}

function buildLeg(
  row: OptionChainRow | undefined,
  type: 'ce' | 'pe',
  foExchange: string
): SelectedLeg | null {
  if (!row) return null
  const leg = row[type]
  if (!leg?.symbol) return null
  return {
    symbol: leg.symbol,
    exchange: foExchange,
    optionType: type.toUpperCase() as 'CE' | 'PE',
    strike: row.strike,
    lotsize: leg.lotsize ?? 0,
    tickSize: leg.tick_size ?? 0,
  }
}

interface TickerProps {
  title: string
  symbol?: string
  ltp?: number
  change?: number
  changePercent?: number
  open?: number
  high?: number
  low?: number
}

const pctInRange = (v: number, low: number, high: number) =>
  high > low ? Math.min(100, Math.max(0, ((v - low) / (high - low)) * 100)) : 50

// Horizontal Low→High range bar with markers for Open (○) and current LTP (▼).
function RangeBar({
  ltp,
  open,
  high,
  low,
}: {
  ltp?: number
  open?: number
  high?: number
  low?: number
}) {
  if (ltp == null || high == null || low == null || high <= low) {
    return <div className="my-3 h-px w-full bg-border" />
  }
  const ltpPct = pctInRange(ltp, low, high)
  const openPct = open != null ? pctInRange(open, low, high) : null
  return (
    <div className="my-1">
      <div className="flex justify-between font-mono text-[11px] text-muted-foreground">
        <span>L: {low.toFixed(2)}</span>
        <span>{high.toFixed(2)} :H</span>
      </div>
      <div className="relative my-2 h-1 rounded bg-muted">
        {openPct != null && (
          <span
            className="-translate-x-1/2 -translate-y-1/2 absolute top-1/2 h-2.5 w-2.5 rounded-full border-2 border-muted-foreground bg-background"
            style={{ left: `${openPct}%` }}
            title={`Open ${open?.toFixed(2)}`}
          />
        )}
        <span
          className="-translate-x-1/2 -top-1 absolute text-[10px] text-foreground"
          style={{ left: `${ltpPct}%` }}
          title={`LTP ${ltp.toFixed(2)}`}
        >
          ▲
        </span>
      </div>
    </div>
  )
}

function Ticker({ title, symbol, ltp, change, changePercent, open, high, low }: TickerProps) {
  const isUp = (changePercent ?? change ?? 0) >= 0
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="font-mono text-xs text-muted-foreground">{symbol ?? '—'}</div>
        <RangeBar ltp={ltp} open={open} high={high} low={low} />
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-2xl font-semibold tabular-nums">
            {ltp != null ? ltp.toFixed(2) : '—'}
          </span>
          {(change != null || changePercent != null) && (
            <span className={`font-mono text-sm ${isUp ? 'text-green-600' : 'text-red-600'}`}>
              {isUp ? '+' : ''}
              {change != null ? change.toFixed(2) : ''}
              {changePercent != null ? ` (${changePercent.toFixed(2)}%)` : ''}
            </span>
          )}
        </div>
        {open != null && (
          <div className="mt-1 font-mono text-[11px] text-muted-foreground">
            O {open.toFixed(2)}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Scalping() {
  const apiKey = useAuthStore((s) => s.apiKey)
  const appMode = useThemeStore((s) => s.appMode) // 'live' | 'analyzer'
  const queryClient = useQueryClient()

  // Segment & exchange. OPTIONS = dual-leg (CE/PE); FUTURES/EQUITY = single instrument.
  const [exchange, setExchange] = useState<'NSE' | 'BSE'>('NSE')
  const [segment, setSegment] = useState<Segment>('OPTIONS')
  const isSingle = segment !== 'OPTIONS'

  const [underlying, setUnderlying] = useState<string>('')
  const [expiry, setExpiry] = useState<string>('')
  const [ceStrike, setCeStrike] = useState<string>('')
  const [peStrike, setPeStrike] = useState<string>('')

  // Single-instrument (equity/futures) selection via search-as-you-type.
  const [searchQuery, setSearchQuery] = useState('')
  const [instrument, setInstrument] = useState<SearchInstrument | null>(null)
  const [equityShares, setEquityShares] = useState(1)

  // Order-entry controls. The One-Click arm state is captured/persisted across reloads.
  const [armed, setArmed] = useState<boolean>(loadArmed)
  const [lots, setLots] = useState(1)
  const [product, setProduct] = useState<ScalpingProduct>('NRML')
  const [lastLatencyMs, setLastLatencyMs] = useState<number | null>(null)

  // Global predefined SL / Target — when enabled, auto-attached to every new entry.
  // Value is in points or percent of entry (default points).
  const [predefSlOn, setPredefSlOn] = useState(false)
  const [predefSlValue, setPredefSlValue] = useState('')
  const [predefSlUnit, setPredefSlUnit] = useState<'PTS' | 'PCT'>('PTS')
  const [predefTgtOn, setPredefTgtOn] = useState(false)
  const [predefTgtValue, setPredefTgtValue] = useState('')
  const [predefTgtUnit, setPredefTgtUnit] = useState<'PTS' | 'PCT'>('PTS')

  useEffect(() => {
    try {
      localStorage.setItem(ARMED_STORAGE_KEY, armed ? '1' : '0')
    } catch {
      // ignore storage failures (private mode, etc.)
    }
  }, [armed])

  // Segment/exchange change: pick a sensible default product and reset the
  // single-instrument selection (equity is MIS-only; derivatives default NRML).
  // biome-ignore lint/correctness/useExhaustiveDependencies: reset only on segment/exchange change
  useEffect(() => {
    setProduct(segment === 'EQUITY' ? 'MIS' : 'NRML')
    setInstrument(null)
    setSearchQuery('')
  }, [segment, exchange])

  // Exchange the single-instrument search runs on: equity on NSE/BSE, futures on
  // the matching F&O exchange (NFO/BFO).
  const searchExchange = segment === 'EQUITY' ? exchange : exchange === 'NSE' ? 'NFO' : 'BFO'
  const { data: searchResp } = useQuery({
    queryKey: ['scalping', 'search', searchExchange, searchQuery, segment],
    queryFn: () => scalpingApi.search(searchExchange, searchQuery),
    enabled: isSingle && searchQuery.trim().length >= 2,
  })
  const searchResults = (searchResp?.data ?? []).filter((r) =>
    segment === 'FUTURES' ? r.symbol.endsWith('FUT') : !r.symbol.endsWith('FUT')
  )

  // Underlyings (options), filtered to the selected exchange's index family.
  const { data: underlyingsResp } = useQuery({
    queryKey: ['scalping', 'underlyings'],
    queryFn: () => scalpingApi.getUnderlyings(),
  })
  const indexFamily = exchange === 'NSE' ? 'NSE_INDEX' : 'BSE_INDEX'
  const underlyings = (underlyingsResp?.data ?? []).filter((u) => u.index_exchange === indexFamily)
  const underlyingCfg = underlyings.find((u) => u.underlying === underlying)

  // Expiry (depends on underlying)
  const { data: expiryResp } = useQuery({
    queryKey: ['scalping', 'expiry', underlying],
    queryFn: () => scalpingApi.getExpiry(underlying),
    enabled: !!underlying,
  })
  const expiries = expiryResp?.data ?? []

  // Default selection on load: NIFTY → nearest (current-week) expiry → ATM strikes.
  // ATM is applied once the chain loads (effect further below).
  useEffect(() => {
    if (!underlying && underlyings.length > 0) {
      const hasNifty = underlyings.some((u) => u.underlying === 'NIFTY')
      setUnderlying(hasNifty ? 'NIFTY' : underlyings[0].underlying)
    }
  }, [underlyings, underlying])

  useEffect(() => {
    if (underlying && !expiry && expiries.length > 0) {
      setExpiry(expiries[0]) // nearest future expiry (service returns ascending)
    }
  }, [expiries, underlying, expiry])

  // Strikes / chain (depends on underlying + expiry)
  const { data: chainResp } = useQuery({
    queryKey: ['scalping', 'strikes', underlying, expiry],
    queryFn: () => scalpingApi.getStrikes(underlying, expiry, DEFAULT_STRIKE_COUNT),
    enabled: !!underlying && !!expiry,
  })
  const chain = useMemo(() => chainResp?.chain ?? [], [chainResp])
  const foExchange = chainResp?.fo_exchange ?? underlyingCfg?.fo_exchange ?? ''
  const indexExchange = chainResp?.index_exchange ?? underlyingCfg?.index_exchange ?? ''

  // Default the CE/PE strike to ATM when the chain loads — but preserve a valid
  // manual selection (only reset to ATM if the current pick isn't in this chain,
  // e.g. on first load or after the expiry/underlying changed).
  useEffect(() => {
    if (chainResp?.atm_strike == null || chain.length === 0) return
    const atm = String(chainResp.atm_strike)
    const strikes = new Set(chain.map((r) => String(r.strike)))
    setCeStrike((prev) => (prev && strikes.has(prev) ? prev : atm))
    setPeStrike((prev) => (prev && strikes.has(prev) ? prev : atm))
  }, [chainResp, chain])

  // Stable leg identities (only change when strike/exchange/chain actually change)
  // so the SL evaluation effect isn't re-triggered by unrelated re-renders.
  const ceLeg = useMemo(
    () =>
      buildLeg(
        chain.find((r) => String(r.strike) === ceStrike),
        'ce',
        foExchange
      ),
    [chain, ceStrike, foExchange]
  )
  const peLeg = useMemo(
    () =>
      buildLeg(
        chain.find((r) => String(r.strike) === peStrike),
        'pe',
        foExchange
      ),
    [chain, peStrike, foExchange]
  )

  // Single instrument (equity/futures) as a leg the order/SL infra can consume.
  const singleLeg: SelectedLeg | null = useMemo(
    () =>
      instrument
        ? {
            symbol: instrument.symbol,
            exchange: instrument.exchange,
            optionType: 'CE', // unused for non-options; kept for the shared leg shape
            strike: 0,
            lotsize: instrument.lotsize || 1,
            tickSize: 0,
          }
        : null,
    [instrument]
  )

  // Books (positions / orders / trades). Event-driven — fetched once, then
  // refreshed on broker order events (useOrderEventRefresh below). No polling.
  const { data: posResp } = useQuery({
    queryKey: ['scalping', 'positions'],
    queryFn: () => tradingApi.getPositions(apiKey ?? ''),
    enabled: !!apiKey,
  })
  const { data: ordResp } = useQuery({
    queryKey: ['scalping', 'orders'],
    queryFn: () => tradingApi.getOrders(apiKey ?? ''),
    enabled: !!apiKey,
  })
  const { data: trdResp } = useQuery({
    queryKey: ['scalping', 'trades'],
    queryFn: () => tradingApi.getTrades(apiKey ?? ''),
    enabled: !!apiKey,
  })
  // The scalping list: instruments this terminal has traded (scopes the book to
  // the scalping strategy, since broker positions carry no strategy tag).
  const { data: trackedResp } = useQuery({
    queryKey: ['scalping', 'tracked'],
    queryFn: () => scalpingApi.getTracked(),
  })
  const positions = posResp?.data ?? []
  const orders = ordResp?.data?.orders ?? []
  const trades = trdResp?.data ?? []
  const trackedKeys = useMemo(
    () => new Set((trackedResp?.data ?? []).map((t) => `${t.exchange}:${t.symbol}:${t.product}`)),
    [trackedResp]
  )
  // Order Book / Trade Book scoped to the scalping list (only this terminal's orders).
  const scopedOrders = useMemo(
    () =>
      orders.filter((o) =>
        trackedKeys.has(`${o.exchange}:${o.symbol}:${(o.product || '').toUpperCase()}`)
      ),
    [orders, trackedKeys]
  )
  const scopedTrades = useMemo(
    () =>
      trades.filter((t) =>
        trackedKeys.has(`${t.exchange}:${t.symbol}:${(t.product || '').toUpperCase()}`)
      ),
    [trades, trackedKeys]
  )

  const refreshBooks = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['scalping', 'positions'] })
    queryClient.invalidateQueries({ queryKey: ['scalping', 'orders'] })
    queryClient.invalidateQueries({ queryKey: ['scalping', 'trades'] })
    queryClient.invalidateQueries({ queryKey: ['scalping', 'tracked'] })
  }, [queryClient])

  // Refresh the books on order/position events instead of polling.
  useOrderEventRefresh(refreshBooks, { events: [...BOOK_EVENTS] })

  // Subscribe the live feed for underlying (Quote, for %chg), CE/PE legs, AND
  // every symbol in the position book — so book LTP and P&L update in realtime.
  const symbols = useMemo(() => {
    const seen = new Set<string>()
    const list: Array<{ symbol: string; exchange: string }> = []
    const add = (symbol: string, exchange: string) => {
      const k = `${exchange}:${symbol}`
      if (!symbol || !exchange || seen.has(k)) return
      seen.add(k)
      list.push({ symbol, exchange })
    }
    if (underlying && indexExchange) add(underlying, indexExchange)
    if (ceLeg) add(ceLeg.symbol, ceLeg.exchange)
    if (peLeg) add(peLeg.symbol, peLeg.exchange)
    if (singleLeg) add(singleLeg.symbol, singleLeg.exchange)
    for (const p of positions) add(p.symbol, p.exchange)
    for (const t of trades) add(t.symbol, t.exchange)
    return list
  }, [underlying, indexExchange, ceLeg, peLeg, singleLeg, positions, trades])

  const {
    data: marketData,
    isConnected,
    isAuthenticated,
    isFallbackMode,
  } = useMarketData({
    symbols,
    mode: 'Quote',
    enabled: symbols.length > 0,
  })

  const underlyingTick = marketData.get(`${indexExchange}:${underlying}`)?.data
  const ceTick = ceLeg ? marketData.get(`${ceLeg.exchange}:${ceLeg.symbol}`)?.data : undefined
  const peTick = peLeg ? marketData.get(`${peLeg.exchange}:${peLeg.symbol}`)?.data : undefined
  const singleTick = singleLeg
    ? marketData.get(`${singleLeg.exchange}:${singleLeg.symbol}`)?.data
    : undefined

  // Realtime LTP resolver for the position book (live WS, falls back to REST ltp).
  const liveLtp = useCallback(
    (symbol: string, exchange: string): number | undefined =>
      marketData.get(`${exchange}:${symbol}`)?.data?.ltp,
    [marketData]
  )

  // Latest live data + predefined config for the (stable) order handler.
  const marketDataRef = useRef(marketData)
  marketDataRef.current = marketData
  const predefRef = useRef({
    slOn: predefSlOn,
    slValue: predefSlValue,
    slUnit: predefSlUnit,
    tgtOn: predefTgtOn,
    tgtValue: predefTgtValue,
    tgtUnit: predefTgtUnit,
  })
  predefRef.current = {
    slOn: predefSlOn,
    slValue: predefSlValue,
    slUnit: predefSlUnit,
    tgtOn: predefTgtOn,
    tgtValue: predefTgtValue,
    tgtUnit: predefTgtUnit,
  }

  // Latest positions for the SL engine to size/direct exits from (avoids stale closure).
  const positionsRef = useRef(positions)
  positionsRef.current = positions
  const resolvePosition = useCallback((symbol: string, exchange: string, prod: string): number => {
    const p = positionsRef.current.find(
      (pos) => pos.symbol === symbol && pos.exchange === exchange && pos.product === prod
    )
    return p ? p.quantity : 0
  }, [])

  // Browser-driven trailing stop-loss engine. It subscribes the live feed for
  // every active SL itself (so restored/background SLs are monitored), and sizes
  // exits from the live position.
  const { slMap, setSL, clearSL } = useTrailingSL({
    onAfterExit: refreshBooks,
    resolvePosition,
  })

  // Position book: derived 1cliq-style rows from positions + today's trades + SL,
  // with realtime LTP from the live feed (recomputes on each tick).
  const positionRows = useMemo(
    () => buildPositionRows(positions, trades, slMap, liveLtp, trackedKeys),
    [positions, trades, slMap, liveLtp, trackedKeys]
  )
  // Summary reflects the displayed rows (scalping book), not raw account totals.
  const netQty = positionRows.reduce((a, r) => a + r.netQty, 0)
  const mtm = positionRows.reduce((a, r) => a + r.totalPnl, 0)

  // Set-SL dialog targets one (symbol, exchange, product) leg at a time. The
  // product is carried on the target so a per-row SL edits the correct MIS/NRML SL.
  const [slDialogTarget, setSlDialogTarget] = useState<SLTarget | null>(null)
  const slDialogOpen = slDialogTarget !== null
  const slDialogTick = slDialogTarget
    ? marketData.get(`${slDialogTarget.exchange}:${slDialogTarget.symbol}`)?.data
    : undefined
  const slDialogPos = slDialogTarget
    ? positions.find(
        (p) =>
          p.symbol === slDialogTarget.symbol &&
          p.exchange === slDialogTarget.exchange &&
          p.product === slDialogTarget.product
      )
    : undefined
  const slDialogEntry = slDialogPos?.average_price ?? slDialogTick?.ltp ?? 0
  // A stop-loss is only meaningful for an actual open position — qty is 0 when
  // flat, which blocks the dialog's Save (prevents an SL that would open a fresh
  // naked position on "exit").
  const slDialogQty = slDialogPos ? Math.abs(slDialogPos.quantity) : 0
  // Side is derived from the actual open position: a short (qty < 0) stops out
  // when price RISES, a long when price FALLS — the SL engine needs this right.
  const slDialogSide: ScalpingAction = slDialogPos && slDialogPos.quantity < 0 ? 'SELL' : 'BUY'
  const slDialogLeg: SelectedLeg | null = slDialogTarget
    ? {
        symbol: slDialogTarget.symbol,
        exchange: slDialogTarget.exchange,
        optionType: slDialogTarget.optionType,
        strike: 0,
        lotsize: 0,
        tickSize: 0,
      }
    : null
  const slDialogExisting = slDialogTarget
    ? findLegSL(slMap, slDialogTarget.symbol, slDialogTarget.exchange, slDialogTarget.product)
    : undefined

  const ceSL = ceLeg ? findLegSL(slMap, ceLeg.symbol, ceLeg.exchange, product) : undefined
  const peSL = peLeg ? findLegSL(slMap, peLeg.symbol, peLeg.exchange, product) : undefined

  // Open the SL dialog for a selected CE/PE leg (uses the current product selector).
  const openLegSL = (leg: SelectedLeg | null) => {
    if (leg) setSlDialogTarget({ ...leg, product })
  }

  // Latest order-entry state for the (stable) keyboard handler — avoids stale closures.
  const stateRef = useRef({
    armed,
    lots,
    product,
    ceLeg,
    peLeg,
    singleLeg,
    appMode,
    segment,
    equityShares,
  })
  stateRef.current = {
    armed,
    lots,
    product,
    ceLeg,
    peLeg,
    singleLeg,
    appMode,
    segment,
    equityShares,
  }

  // Min gap between two order fires. Bounds the rate (prevents accidental
  // double-taps and held-key bursts) while still allowing deliberate fast
  // scalping. Held-key auto-repeat is additionally filtered via e.repeat below.
  const lastFireRef = useRef(0)

  // After an entry, auto-attach the global predefined SL / Target (points or %
  // of the fill LTP) so the websocket SL engine manages the exit.
  const attachPredefinedSL = useCallback(
    (leg: SelectedLeg, action: ScalpingAction, quantity: number, prod: ScalpingProduct) => {
      const cfg = predefRef.current
      if (!cfg.slOn && !cfg.tgtOn) return
      const ltp = marketDataRef.current.get(`${leg.exchange}:${leg.symbol}`)?.data?.ltp
      if (!ltp || ltp <= 0) return
      const toPts = (val: string, unit: 'PTS' | 'PCT') => {
        const n = Number(val)
        if (!Number.isFinite(n) || n <= 0) return 0
        return unit === 'PCT' ? (ltp * n) / 100 : n
      }
      const slPts = cfg.slOn ? toPts(cfg.slValue, cfg.slUnit) : 0
      const tgtPts = cfg.tgtOn ? toPts(cfg.tgtValue, cfg.tgtUnit) : 0
      if (slPts <= 0 && tgtPts <= 0) return
      const isBuy = action === 'BUY'
      // No-SL sentinel that never triggers (target-only): below for long, far above for short.
      const initialSl =
        slPts > 0 ? (isBuy ? ltp - slPts : ltp + slPts) : isBuy ? 0 : Number.MAX_SAFE_INTEGER
      const target = tgtPts > 0 ? (isBuy ? ltp + tgtPts : ltp - tgtPts) : 0
      setSL({
        symbol: leg.symbol,
        exchange: leg.exchange,
        product: prod,
        side: action,
        entry: ltp,
        quantity,
        initialSl,
        trailingEnabled: false,
        trailingStep: 0,
        highestPrice: ltp,
        lowestPrice: ltp,
        currentSl: initialSl,
        target,
        active: true,
      })
    },
    [setSL]
  )

  const submitOrder = useCallback(
    async (leg: SelectedLeg | null, action: ScalpingAction) => {
      const s = stateRef.current
      if (!s.armed) {
        showToast.error('One-Click is disarmed — enable it to trade', 'orders')
        return
      }
      if (!leg) {
        showToast.error('No instrument selected', 'orders')
        return
      }
      if (!leg.lotsize) {
        showToast.error('Lot/contract size unavailable for this instrument', 'orders')
        return
      }
      const now = Date.now()
      if (now - lastFireRef.current < ORDER_COOLDOWN_MS) return
      lastFireRef.current = now
      // Equity trades in whole shares (no lots); derivatives in lots * lot size.
      const isEquity = s.segment === 'EQUITY'
      const quantity = isEquity ? s.equityShares : s.lots * leg.lotsize
      const sentLots = isEquity ? undefined : s.lots
      if (quantity <= 0) {
        showToast.error('Quantity must be positive', 'orders')
        return
      }
      const t0 = performance.now()
      // Order placement notifications (success AND broker/sandbox rejection) are
      // shown ONCE by the global SocketProvider — order_event in live mode,
      // analyzer_update in analyzer mode. We don't toast success here (latency is
      // in the header). We only toast an error in LIVE mode, where the backend
      // emits no socket event on failure, or on a transport error (no response).
      try {
        const res = await scalpingApi.placeOrder({
          symbol: leg.symbol,
          exchange: leg.exchange,
          action,
          quantity,
          product: s.product,
          lots: sentLots,
        })
        setLastLatencyMs(Math.round(performance.now() - t0))
        if (res.status === 'success') {
          attachPredefinedSL(leg, action, quantity, s.product)
          refreshBooks()
        } else if (s.appMode === 'live') {
          showToast.error(res.message ?? 'Order failed', 'orders')
        }
      } catch (e) {
        setLastLatencyMs(Math.round(performance.now() - t0))
        const handledGlobally = s.appMode === 'analyzer' && !!(e as { response?: unknown }).response
        if (!handledGlobally) showToast.error(apiErrorMessage(e), 'orders')
      }
    },
    [refreshBooks, attachPredefinedSL]
  )

  // Note: close-all / cancel-all (F6/F7) and the trailing-SL auto-exit are
  // intentionally NOT gated by `armed`. "Armed" guards only NEW risk-increasing
  // entries; risk-reducing actions (flatten, cancel, stop-loss) must always work
  // even when one-click is off — disarming must never disable your stops.
  // Success/rejection toasts for close-all and cancel-all are shown globally by
  // SocketProvider (close_position_event / cancel_order_event / analyzer_update).
  // We only surface an error here when the global handler won't (live mode or a
  // transport error), to avoid duplicate notifications.
  const doCloseAll = useCallback(async () => {
    try {
      const res = await scalpingApi.closeAll()
      if (res.status !== 'success' && appMode === 'live') {
        showToast.error(res.message ?? 'Close all failed', 'orders')
      }
    } catch (e) {
      const handledGlobally = appMode === 'analyzer' && !!(e as { response?: unknown }).response
      if (!handledGlobally) showToast.error(apiErrorMessage(e), 'orders')
    }
    refreshBooks()
  }, [refreshBooks, appMode])

  const doCancelAll = useCallback(async () => {
    try {
      const res = await scalpingApi.cancelAll()
      if (res.status !== 'success' && appMode === 'live') {
        showToast.error(res.message ?? 'Cancel all failed', 'orders')
      }
    } catch (e) {
      const handledGlobally = appMode === 'analyzer' && !!(e as { response?: unknown }).response
      if (!handledGlobally) showToast.error(apiErrorMessage(e), 'orders')
    }
    refreshBooks()
  }, [refreshBooks, appMode])

  // Close a single position-book row (risk-reducing, opposite side, live net qty).
  const doCloseRow = useCallback(
    async (row: ScalpingPositionRow) => {
      if (row.netQty === 0) return
      const action: ScalpingAction = row.netQty > 0 ? 'SELL' : 'BUY'
      try {
        const res = await scalpingApi.closeLeg({
          symbol: row.symbol,
          exchange: row.exchange,
          action,
          quantity: Math.abs(row.netQty),
          product: row.product,
        })
        if (res.status !== 'success' && appMode === 'live') {
          showToast.error(res.message ?? 'Close failed', 'orders')
        }
      } catch (e) {
        const handledGlobally = appMode === 'analyzer' && !!(e as { response?: unknown }).response
        if (!handledGlobally) showToast.error(apiErrorMessage(e), 'orders')
      }
      refreshBooks()
    },
    [refreshBooks, appMode]
  )

  // Global keyboard handler: arrows fire orders, F6 close-all, F7 cancel-all.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      // Ignore OS key auto-repeat from a held key — otherwise one held arrow
      // would fire a continuous stream of market orders.
      if (e.repeat) return
      const t = e.target as HTMLElement | null
      if (
        t &&
        (t.tagName === 'INPUT' ||
          t.tagName === 'TEXTAREA' ||
          t.isContentEditable ||
          t.getAttribute('role') === 'combobox')
      ) {
        return
      }
      const s = stateRef.current
      // Single-instrument (equity/futures): ↑/→ Buy, ↓/← Sell on the one instrument.
      if (s.segment !== 'OPTIONS') {
        switch (e.key) {
          case 'ArrowUp':
          case 'ArrowRight':
            e.preventDefault()
            submitOrder(s.singleLeg, 'BUY')
            return
          case 'ArrowDown':
          case 'ArrowLeft':
            e.preventDefault()
            submitOrder(s.singleLeg, 'SELL')
            return
          case 'F6':
            e.preventDefault()
            doCloseAll()
            return
          case 'F7':
            e.preventDefault()
            doCancelAll()
            return
          default:
            return
        }
      }
      switch (e.key) {
        case 'ArrowUp':
          e.preventDefault()
          submitOrder(s.ceLeg, 'BUY')
          break
        case 'ArrowDown':
          e.preventDefault()
          submitOrder(s.ceLeg, 'SELL')
          break
        case 'ArrowRight':
          e.preventDefault()
          submitOrder(s.peLeg, 'BUY')
          break
        case 'ArrowLeft':
          e.preventDefault()
          submitOrder(s.peLeg, 'SELL')
          break
        case 'F6':
          e.preventDefault()
          doCloseAll()
          break
        case 'F7':
          e.preventDefault()
          doCancelAll()
          break
        default:
          break
      }
    },
    [submitOrder, doCloseAll, doCancelAll]
  )

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [handleKeyDown])

  const wsBadge = isFallbackMode
    ? { label: 'Polling (REST)', variant: 'secondary' as const }
    : isAuthenticated
      ? { label: 'Live', variant: 'default' as const }
      : isConnected
        ? { label: 'Connecting…', variant: 'secondary' as const }
        : { label: 'Disconnected', variant: 'destructive' as const }

  return (
    <div className="space-y-4 p-4">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Scalping Terminal</h1>
        <div className="flex items-center gap-3">
          {lastLatencyMs != null && (
            <span className="font-mono text-xs text-muted-foreground">order {lastLatencyMs}ms</span>
          )}
          <Badge variant={armed ? 'destructive' : 'secondary'}>
            One-Click {armed ? 'ARMED' : 'off'}
          </Badge>
          <Badge variant={wsBadge.variant}>{wsBadge.label}</Badge>
        </div>
      </div>

      {/* Feed-status banner — a stale/lost feed mid-position is dangerous. The
          shared WebSocket manager auto-resubscribes active legs on reconnect. */}
      {!isAuthenticated && (
        <div className="rounded-md border border-red-500/50 bg-red-500/10 px-4 py-2 text-sm text-red-700 dark:text-red-400">
          {isFallbackMode
            ? 'Live feed lost — using slower REST polling. Prices may lag; trade with caution.'
            : isConnected
              ? 'Reconnecting to the live market-data feed… active legs will resubscribe automatically.'
              : 'Market-data feed disconnected — prices are stale. Reconnecting…'}
        </div>
      )}

      {/* Selection controls */}
      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 md:grid-cols-4">
          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Exchange</label>
            <Select value={exchange} onValueChange={(v) => setExchange(v as 'NSE' | 'BSE')}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="NSE">NSE</SelectItem>
                <SelectItem value="BSE">BSE</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <label className="text-sm text-muted-foreground">Segment</label>
            <Select value={segment} onValueChange={(v) => setSegment(v as Segment)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="OPTIONS">Options</SelectItem>
                <SelectItem value="FUTURES">Futures</SelectItem>
                <SelectItem value="EQUITY">Equity</SelectItem>
              </SelectContent>
            </Select>
          </div>

          {!isSingle && (
            <>
              <div className="space-y-1">
                <label className="text-sm text-muted-foreground">Underlying</label>
                <Select
                  value={underlying}
                  onValueChange={(v) => {
                    setUnderlying(v)
                    setExpiry('')
                    setCeStrike('')
                    setPeStrike('')
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select underlying" />
                  </SelectTrigger>
                  <SelectContent>
                    {underlyings.map((u) => (
                      <SelectItem key={u.underlying} value={u.underlying}>
                        {u.underlying}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <label className="text-sm text-muted-foreground">Expiry</label>
                <Select value={expiry} onValueChange={setExpiry} disabled={!underlying}>
                  <SelectTrigger>
                    <SelectValue placeholder="Select expiry" />
                  </SelectTrigger>
                  <SelectContent>
                    {expiries.map((e) => (
                      <SelectItem key={e} value={e}>
                        {e}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <label className="text-sm text-muted-foreground">Call Strike</label>
                <Select value={ceStrike} onValueChange={setCeStrike} disabled={chain.length === 0}>
                  <SelectTrigger>
                    <SelectValue placeholder="CE strike" />
                  </SelectTrigger>
                  <SelectContent>
                    {chain.map((r) => (
                      <SelectItem key={`ce-${r.strike}`} value={String(r.strike)}>
                        {r.strike} {r.ce.label ? `(${r.ce.label})` : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="space-y-1">
                <label className="text-sm text-muted-foreground">Put Strike</label>
                <Select value={peStrike} onValueChange={setPeStrike} disabled={chain.length === 0}>
                  <SelectTrigger>
                    <SelectValue placeholder="PE strike" />
                  </SelectTrigger>
                  <SelectContent>
                    {chain.map((r) => (
                      <SelectItem key={`pe-${r.strike}`} value={String(r.strike)}>
                        {r.strike} {r.pe.label ? `(${r.pe.label})` : ''}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </>
          )}

          {isSingle && (
            <div className="relative space-y-1 md:col-span-2">
              <label className="text-sm text-muted-foreground">
                {segment === 'EQUITY' ? 'Equity Symbol' : 'Futures Contract'}
              </label>
              <Input
                value={instrument ? instrument.symbol : searchQuery}
                placeholder={
                  segment === 'EQUITY' ? 'Search e.g. RELIANCE' : 'Search e.g. NIFTY FUT'
                }
                onChange={(e) => {
                  setInstrument(null)
                  setSearchQuery(e.target.value)
                }}
              />
              {!instrument && searchResults.length > 0 && (
                <div className="absolute z-10 mt-1 max-h-60 w-full overflow-auto rounded-md border bg-popover shadow-md">
                  {searchResults.slice(0, 25).map((r) => (
                    <button
                      type="button"
                      key={`${r.exchange}:${r.symbol}`}
                      className="block w-full px-3 py-1.5 text-left font-mono text-sm hover:bg-muted"
                      onClick={() => {
                        setInstrument(r)
                        setSearchQuery('')
                      }}
                    >
                      {r.symbol}
                      {r.name ? <span className="text-muted-foreground"> · {r.name}</span> : null}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Live tickers */}
      {isSingle ? (
        <div className="grid grid-cols-1 gap-4">
          <Ticker
            title={segment === 'EQUITY' ? 'Equity' : 'Futures'}
            symbol={singleLeg?.symbol}
            ltp={singleTick?.ltp}
            change={singleTick?.change}
            changePercent={singleTick?.change_percent}
            open={singleTick?.open}
            high={singleTick?.high}
            low={singleTick?.low}
          />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Ticker
            title="Call (CE)"
            symbol={ceLeg?.symbol}
            ltp={ceTick?.ltp}
            change={ceTick?.change}
            changePercent={ceTick?.change_percent}
            open={ceTick?.open}
            high={ceTick?.high}
            low={ceTick?.low}
          />
          <Ticker
            title={underlying || 'Underlying'}
            symbol={underlying}
            ltp={underlyingTick?.ltp}
            change={underlyingTick?.change}
            changePercent={underlyingTick?.change_percent}
            open={underlyingTick?.open}
            high={underlyingTick?.high}
            low={underlyingTick?.low}
          />
          <Ticker
            title="Put (PE)"
            symbol={peLeg?.symbol}
            ltp={peTick?.ltp}
            change={peTick?.change}
            changePercent={peTick?.change_percent}
            open={peTick?.open}
            high={peTick?.high}
            low={peTick?.low}
          />
        </div>
      )}

      {/* Order entry */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap items-center gap-6">
            <label className="flex items-center gap-2">
              <Switch checked={armed} onCheckedChange={setArmed} />
              <span className="text-sm font-medium">One-Click</span>
            </label>

            {segment === 'EQUITY' ? (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Qty</span>
                <Input
                  type="number"
                  inputMode="numeric"
                  min={1}
                  value={equityShares}
                  onChange={(e) => setEquityShares(Math.max(1, Number(e.target.value) || 1))}
                  className="w-24"
                />
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <span className="text-sm text-muted-foreground">Lots</span>
                <Select value={String(lots)} onValueChange={(v) => setLots(Number(v))}>
                  <SelectTrigger className="w-20">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {Array.from({ length: MAX_LOTS }, (_, i) => i + 1).map((n) => (
                      <SelectItem key={n} value={String(n)}>
                        {n}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            )}

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Product</span>
              <Select value={product} onValueChange={(v) => setProduct(v as ScalpingProduct)}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="MIS">MIS</SelectItem>
                  {segment !== 'EQUITY' && <SelectItem value="NRML">NRML</SelectItem>}
                </SelectContent>
              </Select>
            </div>

            {/* Global predefined SL — auto-attached to every entry when enabled */}
            <div className="flex items-center gap-1.5" title="Auto stop-loss on every entry">
              <Checkbox checked={predefSlOn} onCheckedChange={(v) => setPredefSlOn(v === true)} />
              <span className="text-sm text-muted-foreground">SL</span>
              <Input
                type="number"
                inputMode="decimal"
                disabled={!predefSlOn}
                value={predefSlValue}
                onChange={(e) => setPredefSlValue(e.target.value)}
                placeholder="0"
                className="w-16"
              />
              <Select
                value={predefSlUnit}
                onValueChange={(v) => setPredefSlUnit(v as 'PTS' | 'PCT')}
              >
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PTS">Pts</SelectItem>
                  <SelectItem value="PCT">%</SelectItem>
                </SelectContent>
              </Select>
            </div>

            {/* Global predefined Target — auto take-profit on every entry */}
            <div className="flex items-center gap-1.5" title="Auto target on every entry">
              <Checkbox checked={predefTgtOn} onCheckedChange={(v) => setPredefTgtOn(v === true)} />
              <span className="text-sm text-muted-foreground">Target</span>
              <Input
                type="number"
                inputMode="decimal"
                disabled={!predefTgtOn}
                value={predefTgtValue}
                onChange={(e) => setPredefTgtValue(e.target.value)}
                placeholder="0"
                className="w-16"
              />
              <Select
                value={predefTgtUnit}
                onValueChange={(v) => setPredefTgtUnit(v as 'PTS' | 'PCT')}
              >
                <SelectTrigger className="w-20">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="PTS">Pts</SelectItem>
                  <SelectItem value="PCT">%</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div
              className="ml-auto flex items-center gap-6 font-mono"
              title="Sum across the position-book rows below (open + today's closed trades)"
            >
              <span>
                Net Qty: <span className="font-semibold">{netQty}</span>
              </span>
              <span>
                MTM:{' '}
                <span className={`font-semibold ${mtm >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                  {mtm.toFixed(2)}
                </span>
              </span>
            </div>
          </div>

          {isSingle ? (
            <div className="grid grid-cols-2 gap-3">
              <Button
                className="bg-green-600 hover:bg-green-700"
                disabled={!singleLeg}
                onClick={() => submitOrder(singleLeg, 'BUY')}
              >
                ↑ Buy {segment === 'EQUITY' ? 'Stock' : ''}
              </Button>
              <Button
                className="bg-red-600 hover:bg-red-700"
                disabled={!singleLeg}
                onClick={() => submitOrder(singleLeg, 'SELL')}
              >
                ↓ Sell {segment === 'EQUITY' ? 'Stock' : ''}
              </Button>
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
              <Button
                className="bg-green-600 hover:bg-green-700"
                onClick={() => submitOrder(ceLeg, 'BUY')}
              >
                ↑ Buy Call
              </Button>
              <Button
                className="bg-red-600 hover:bg-red-700"
                onClick={() => submitOrder(ceLeg, 'SELL')}
              >
                ↓ Sell Call
              </Button>
              <Button
                className="bg-green-600 hover:bg-green-700"
                onClick={() => submitOrder(peLeg, 'BUY')}
              >
                → Buy Put
              </Button>
              <Button
                className="bg-red-600 hover:bg-red-700"
                onClick={() => submitOrder(peLeg, 'SELL')}
              >
                ← Sell Put
              </Button>
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            {isSingle ? (
              <Button variant="outline" disabled={!singleLeg} onClick={() => openLegSL(singleLeg)}>
                {singleLeg && findLegSL(slMap, singleLeg.symbol, singleLeg.exchange, product)
                  ? 'Edit SL'
                  : 'Set SL'}
              </Button>
            ) : (
              <>
                <Button variant="outline" disabled={!ceLeg} onClick={() => openLegSL(ceLeg)}>
                  {ceSL ? 'Edit Call SL' : 'Set Call SL'}
                </Button>
                <Button variant="outline" disabled={!peLeg} onClick={() => openLegSL(peLeg)}>
                  {peSL ? 'Edit Put SL' : 'Set Put SL'}
                </Button>
              </>
            )}
            <Button
              variant="outline"
              onClick={doCloseAll}
              title="Closes only the scalping strategy's positions (freeze-safe), not the whole account"
            >
              Close All Positions / F6
            </Button>
            <Button variant="outline" onClick={doCancelAll} title="Cancels all open orders">
              Cancel All Orders / F7
            </Button>
          </div>

          <span className="text-xs text-muted-foreground">
            {isSingle
              ? 'Keys: ↑/→ Buy · ↓/← Sell · F6 close · F7 cancel'
              : 'Keys: ↑ Buy Call · ↓ Sell Call · → Buy Put · ← Sell Put · F6 close · F7 cancel'}
          </span>
        </CardContent>
      </Card>

      {/* Books */}
      <Tabs defaultValue="positions">
        <TabsList>
          <TabsTrigger value="positions">Positions</TabsTrigger>
          <TabsTrigger value="orders">Order Book</TabsTrigger>
          <TabsTrigger value="trades">Trade Book</TabsTrigger>
        </TabsList>

        <TabsContent value="positions">
          <div className="overflow-x-auto">
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Symbol</TableHead>
                  <TableHead>Product</TableHead>
                  <TableHead>Side</TableHead>
                  <TableHead className="text-right">Net Qty</TableHead>
                  <TableHead className="text-right">LTP</TableHead>
                  <TableHead className="text-right">SL</TableHead>
                  <TableHead>SL</TableHead>
                  <TableHead className="text-right">R. P&amp;L</TableHead>
                  <TableHead className="text-right">UR. P&amp;L</TableHead>
                  <TableHead className="text-right">P&amp;L</TableHead>
                  <TableHead>Action</TableHead>
                  <TableHead className="text-right">Avg Price</TableHead>
                  <TableHead className="text-right">Buy Qty</TableHead>
                  <TableHead className="text-right">Buy Price</TableHead>
                  <TableHead className="text-right">Sell Price</TableHead>
                  <TableHead className="text-right">Sell Qty</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {positionRows.map((r) => {
                  const open = r.netQty !== 0
                  return (
                    <TableRow key={`${r.exchange}:${r.symbol}:${r.product}`}>
                      <TableCell className="font-mono text-sm">{r.symbol}</TableCell>
                      <TableCell>{productLabel(r.product)}</TableCell>
                      <TableCell
                        className={
                          r.side === 'BUY'
                            ? 'text-green-600'
                            : r.side === 'SELL'
                              ? 'text-red-600'
                              : 'text-muted-foreground'
                        }
                      >
                        {r.side}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.netQty}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.ltp ? r.ltp.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.sl != null ? r.sl.toFixed(2) : '-'}
                      </TableCell>
                      <TableCell>
                        {open ? (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() =>
                              setSlDialogTarget({
                                symbol: r.symbol,
                                exchange: r.exchange,
                                product: r.product,
                                optionType: r.symbol.endsWith('PE') ? 'PE' : 'CE',
                              })
                            }
                          >
                            {r.sl != null ? 'Edit' : 'Set'}
                          </Button>
                        ) : (
                          '-'
                        )}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono tabular-nums ${r.realizedPnl >= 0 ? 'text-green-600' : 'text-red-600'}`}
                      >
                        {r.realizedPnl.toFixed(2)}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono tabular-nums ${r.unrealizedPnl >= 0 ? 'text-green-600' : 'text-red-600'}`}
                      >
                        {r.unrealizedPnl.toFixed(2)}
                      </TableCell>
                      <TableCell
                        className={`text-right font-mono tabular-nums font-semibold ${r.totalPnl >= 0 ? 'text-green-600' : 'text-red-600'}`}
                      >
                        {r.totalPnl.toFixed(2)}
                      </TableCell>
                      <TableCell>
                        {open ? (
                          <Button variant="outline" size="sm" onClick={() => doCloseRow(r)}>
                            Close
                          </Button>
                        ) : (
                          '-'
                        )}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.avgPrice ? r.avgPrice.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.buyQty}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.buyAvg ? r.buyAvg.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.sellAvg ? r.sellAvg.toFixed(2) : '—'}
                      </TableCell>
                      <TableCell className="text-right font-mono tabular-nums">
                        {r.sellQty}
                      </TableCell>
                    </TableRow>
                  )
                })}
                {positionRows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={16} className="text-center text-muted-foreground">
                      No positions or trades today
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
        </TabsContent>

        <TabsContent value="orders">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Order ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scopedOrders.map((o) => (
                <TableRow key={o.orderid}>
                  <TableCell className="font-mono text-sm">{o.symbol}</TableCell>
                  <TableCell className={o.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                    {o.action}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{o.quantity}</TableCell>
                  <TableCell>{o.pricetype}</TableCell>
                  <TableCell>{o.order_status}</TableCell>
                  <TableCell className="font-mono text-xs">{o.orderid}</TableCell>
                </TableRow>
              ))}
              {scopedOrders.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    No orders
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>

        <TabsContent value="trades">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Side</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Avg Price</TableHead>
                <TableHead>Order ID</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scopedTrades.map((t) => (
                <TableRow key={`${t.orderid}-${t.timestamp}`}>
                  <TableCell className="font-mono text-sm">{t.symbol}</TableCell>
                  <TableCell className={t.action === 'BUY' ? 'text-green-600' : 'text-red-600'}>
                    {t.action}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{t.quantity}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {t.average_price?.toFixed(2)}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{t.orderid}</TableCell>
                </TableRow>
              ))}
              {scopedTrades.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-muted-foreground">
                    No trades
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </TabsContent>
      </Tabs>

      <SetSLDialog
        open={slDialogOpen}
        onOpenChange={(o) => {
          if (!o) setSlDialogTarget(null)
        }}
        leg={slDialogLeg}
        product={product}
        side={slDialogSide}
        entryPrice={slDialogEntry}
        quantity={slDialogQty}
        ltp={slDialogTick?.ltp}
        existing={slDialogExisting}
        onSave={(sl: SLState) => setSL(sl)}
        onClear={
          slDialogExisting && slDialogTarget
            ? () =>
                clearSL(slDialogTarget.symbol, slDialogTarget.exchange, slDialogExisting.product)
            : undefined
        }
      />
    </div>
  )
}
