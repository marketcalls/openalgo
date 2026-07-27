import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type ArbitragePair, arbitrageApi } from '@/api/arbitrage'
import { type BasketOrderItem, tradingApi } from '@/api/trading'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import { useMarketDataContextOptional } from '@/contexts/MarketDataContext'
import { MarketDataManager, type SymbolData } from '@/lib/MarketDataManager'
import { useAuthStore } from '@/stores/authStore'
import { showToast } from '@/utils/toast'

// Recompute the ranked table on a fixed cadence rather than on every tick so a
// large depth-subscription set (~hundreds of futures) does not thrash React.
const REFRESH_MS = 750
// A leg is considered "live" if its last tick arrived within this window.
const FRESH_MS = 6000

type Direction = 'SHORT_SPREAD' | 'LONG_SPREAD'

interface Quote {
  bid?: number
  ask?: number
  ltp?: number
  ts?: number
}

interface SpreadRow {
  pair: ArbitragePair
  near?: Quote
  far?: Quote
  nearMid?: number
  farMid?: number
  rawSpread?: number
  bestCredit?: number
  direction?: Direction
  spreadPct?: number
  fresh: boolean
  liquid: boolean
  hasData: boolean
}

function quoteKey(symbol: string, exchange: string): string {
  return `${exchange}:${symbol}`
}

function extractQuote(sd: SymbolData | undefined): Quote | undefined {
  if (!sd) return undefined
  const d = sd.data
  const rawBid = d.depth?.buy?.[0]?.price ?? d.bid_price
  const rawAsk = d.depth?.sell?.[0]?.price ?? d.ask_price
  return {
    bid: rawBid && rawBid > 0 ? rawBid : undefined,
    ask: rawAsk && rawAsk > 0 ? rawAsk : undefined,
    ltp: d.ltp && d.ltp > 0 ? d.ltp : undefined,
    ts: sd.lastUpdate,
  }
}

function midPrice(q?: Quote): number | undefined {
  if (!q) return undefined
  if (q.bid && q.ask) return (q.bid + q.ask) / 2
  return q.ltp
}

function roundToTick(price: number, tick?: number | null): number {
  if (!tick || tick <= 0) return Math.round(price * 100) / 100
  return Math.round(price / tick) * tick
}

function fmt(n: number | undefined, digits = 2): string {
  return n == null || Number.isNaN(n) ? '—' : n.toFixed(digits)
}

function computeRow(pair: ArbitragePair, quotes: Map<string, Quote>, now: number): SpreadRow {
  const near = quotes.get(quoteKey(pair.near.symbol, pair.near.exchange))
  const far = quotes.get(quoteKey(pair.far.symbol, pair.far.exchange))
  const nearMid = midPrice(near)
  const farMid = midPrice(far)

  // Executable credits (cash received) for the two ways to trade the spread.
  // SHORT spread: sell far @ bid, buy near @ ask.
  // LONG spread : buy far @ ask, sell near @ bid.
  let creditShort: number | undefined
  if (far?.bid != null && near?.ask != null) creditShort = far.bid - near.ask
  let creditLong: number | undefined
  if (near?.bid != null && far?.ask != null) creditLong = near.bid - far.ask

  let bestCredit: number | undefined
  let direction: Direction | undefined
  if (creditShort != null) {
    bestCredit = creditShort
    direction = 'SHORT_SPREAD'
  }
  if (creditLong != null && (bestCredit == null || creditLong > bestCredit)) {
    bestCredit = creditLong
    direction = 'LONG_SPREAD'
  }

  const spreadPct =
    bestCredit != null && nearMid && nearMid > 0 ? (bestCredit / nearMid) * 100 : undefined
  const rawSpread = farMid != null && nearMid != null ? farMid - nearMid : undefined

  const newest = Math.max(near?.ts ?? 0, far?.ts ?? 0)
  const fresh = newest > 0 && now - newest < FRESH_MS
  const liquid = Boolean(near?.bid && near?.ask && far?.bid && far?.ask)

  return {
    pair,
    near,
    far,
    nearMid,
    farMid,
    rawSpread,
    bestCredit,
    direction,
    spreadPct,
    fresh,
    liquid,
    hasData: spreadPct != null,
  }
}

function directionLabel(dir: Direction): string {
  return dir === 'SHORT_SPREAD' ? 'Sell far / Buy near' : 'Buy far / Sell near'
}

export default function Arbitrage() {
  const context = useMarketDataContextOptional()
  const managerRef = useRef<MarketDataManager>(context?.manager ?? MarketDataManager.getInstance())
  const { apiKey } = useAuthStore()

  const [pairs, setPairs] = useState<ArbitragePair[]>([])
  const [symbols, setSymbols] = useState<Array<{ symbol: string; exchange: string }>>([])
  const [loading, setLoading] = useState(true)
  const [universeError, setUniverseError] = useState<string | null>(null)
  const [generatedAt, setGeneratedAt] = useState<string>('')

  const [conn, setConn] = useState({
    isConnected: false,
    isAuthenticated: false,
    isFallbackMode: false,
  })
  const [allRows, setAllRows] = useState<SpreadRow[]>([])

  // Filters
  const [exchangeFilter, setExchangeFilter] = useState('ALL')
  const [typeFilter, setTypeFilter] = useState('ALL')
  const [minSpread, setMinSpread] = useState('')
  const [search, setSearch] = useState('')
  const [onlyLiquid, setOnlyLiquid] = useState(false)

  // Live tick store (ref to avoid re-rendering on every tick)
  const quotesRef = useRef<Map<string, Quote>>(new Map())
  const pairsRef = useRef<ArbitragePair[]>([])

  useEffect(() => {
    pairsRef.current = pairs
  }, [pairs])

  const loadUniverse = useCallback(async () => {
    setLoading(true)
    setUniverseError(null)
    try {
      const res = await arbitrageApi.getUniverse(['NFO', 'MCX'])
      if (res.status === 'success' && res.data) {
        setPairs(res.data.pairs)
        setSymbols(res.data.symbols)
        setGeneratedAt(res.data.generated_at)
      } else {
        setUniverseError(res.message || 'Failed to load arbitrage universe')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load arbitrage universe'
      setUniverseError(message)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUniverse()
  }, [loadUniverse])

  // Subscribe to all leg symbols in Depth mode for live bid/ask.
  // Re-subscribes only when the symbol set changes; managerRef/quotesRef are stable refs.
  useEffect(() => {
    if (symbols.length === 0) return

    const manager = managerRef.current
    manager.setAutoReconnect(true)
    manager.connect()

    const stateUnsub = manager.addStateListener((s) => {
      setConn({
        isConnected: s.isConnected,
        isAuthenticated: s.isAuthenticated,
        isFallbackMode: s.isFallbackMode,
      })
    })

    const unsubs: Array<() => void> = []
    for (const { symbol, exchange } of symbols) {
      const key = quoteKey(symbol, exchange)
      const unsub = manager.subscribe(symbol, exchange, 'Depth', (data: SymbolData) => {
        const q = extractQuote(data)
        if (q) quotesRef.current.set(key, q)
      })
      unsubs.push(unsub)
      const cached = manager.getCachedData(symbol, exchange)
      if (cached) {
        const q = extractQuote(cached)
        if (q) quotesRef.current.set(key, q)
      }
    }

    return () => {
      stateUnsub()
      unsubs.forEach((u) => u())
    }
  }, [symbols])

  // Throttled recompute of the ranked table.
  useEffect(() => {
    const id = setInterval(() => {
      const now = Date.now()
      const rows = pairsRef.current.map((p) => computeRow(p, quotesRef.current, now))
      rows.sort((a, b) => {
        if (a.spreadPct == null && b.spreadPct == null) return 0
        if (a.spreadPct == null) return 1
        if (b.spreadPct == null) return -1
        return b.spreadPct - a.spreadPct
      })
      setAllRows(rows)
    }, REFRESH_MS)
    return () => clearInterval(id)
  }, [])

  const exchanges = useMemo(() => Array.from(new Set(pairs.map((p) => p.exchange))).sort(), [pairs])

  const visibleRows = useMemo(() => {
    const min = minSpread.trim() === '' ? null : Number.parseFloat(minSpread)
    const q = search.trim().toUpperCase()
    return allRows.filter((r) => {
      if (exchangeFilter !== 'ALL' && r.pair.exchange !== exchangeFilter) return false
      if (typeFilter !== 'ALL' && r.pair.type !== typeFilter) return false
      if (onlyLiquid && !r.liquid) return false
      if (q && !r.pair.underlying.toUpperCase().includes(q)) return false
      if (min != null && !Number.isNaN(min)) {
        if (r.spreadPct == null || r.spreadPct < min) return false
      }
      return true
    })
  }, [allRows, exchangeFilter, typeFilter, minSpread, search, onlyLiquid])

  // ---- Trade dialog state ----
  const [tradeRow, setTradeRow] = useState<SpreadRow | null>(null)
  const [tradeDir, setTradeDir] = useState<Direction>('SHORT_SPREAD')
  const [lots, setLots] = useState('1')
  const [pricetype, setPricetype] = useState<'LIMIT' | 'MARKET'>('LIMIT')
  const [product, setProduct] = useState<'NRML' | 'MIS'>('NRML')
  const [nearPrice, setNearPrice] = useState('')
  const [farPrice, setFarPrice] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const defaultLegPrice = useCallback(
    (q: Quote | undefined, action: 'BUY' | 'SELL', tick?: number | null): string => {
      if (!q) return ''
      const raw = action === 'SELL' ? q.bid : q.ask
      const fallback = q.ltp
      const price = raw ?? fallback
      if (price == null) return ''
      return String(roundToTick(price, tick))
    },
    []
  )

  const prefillPrices = useCallback(
    (row: SpreadRow, dir: Direction) => {
      const near = quotesRef.current.get(quoteKey(row.pair.near.symbol, row.pair.near.exchange))
      const far = quotesRef.current.get(quoteKey(row.pair.far.symbol, row.pair.far.exchange))
      const farAction: 'BUY' | 'SELL' = dir === 'SHORT_SPREAD' ? 'SELL' : 'BUY'
      const nearAction: 'BUY' | 'SELL' = dir === 'SHORT_SPREAD' ? 'BUY' : 'SELL'
      setNearPrice(defaultLegPrice(near, nearAction, row.pair.near.tick_size))
      setFarPrice(defaultLegPrice(far, farAction, row.pair.far.tick_size))
    },
    [defaultLegPrice]
  )

  const openTrade = useCallback(
    (row: SpreadRow) => {
      const dir = row.direction ?? 'SHORT_SPREAD'
      setTradeRow(row)
      setTradeDir(dir)
      setLots('1')
      setPricetype('LIMIT')
      setProduct('NRML')
      prefillPrices(row, dir)
    },
    [prefillPrices]
  )

  const onChangeDir = useCallback(
    (dir: Direction) => {
      setTradeDir(dir)
      if (tradeRow) prefillPrices(tradeRow, dir)
    },
    [tradeRow, prefillPrices]
  )

  const submitTrade = useCallback(async () => {
    if (!tradeRow) return
    if (!apiKey) {
      showToast.error('API key not found. Generate one at /apikey')
      return
    }
    const lotsN = Number.parseInt(lots, 10)
    if (!Number.isInteger(lotsN) || lotsN < 1) {
      showToast.error('Lots must be a positive whole number')
      return
    }
    const { near, far } = tradeRow.pair
    const nearLot = near.lotsize ?? 0
    const farLot = far.lotsize ?? 0
    if (nearLot <= 0 || farLot <= 0) {
      showToast.error('Missing lot size for one of the legs')
      return
    }

    const farAction: 'BUY' | 'SELL' = tradeDir === 'SHORT_SPREAD' ? 'SELL' : 'BUY'
    const nearAction: 'BUY' | 'SELL' = tradeDir === 'SHORT_SPREAD' ? 'BUY' : 'SELL'

    let nearPx = 0
    let farPx = 0
    if (pricetype === 'LIMIT') {
      nearPx = Number.parseFloat(nearPrice)
      farPx = Number.parseFloat(farPrice)
      if (!(nearPx > 0) || !(farPx > 0)) {
        showToast.error('Enter valid limit prices for both legs')
        return
      }
    }

    const buildLeg = (
      symbol: string,
      exchange: string,
      action: 'BUY' | 'SELL',
      qty: number,
      price: number
    ): BasketOrderItem => {
      const leg: BasketOrderItem = {
        symbol,
        exchange,
        action,
        quantity: qty,
        pricetype,
        product,
        trigger_price: 0,
        disclosed_quantity: 0,
      }
      if (pricetype === 'LIMIT') leg.price = price
      return leg
    }

    const orders: BasketOrderItem[] = [
      buildLeg(near.symbol, near.exchange, nearAction, lotsN * nearLot, nearPx),
      buildLeg(far.symbol, far.exchange, farAction, lotsN * farLot, farPx),
    ]

    setSubmitting(true)
    try {
      const res = await tradingApi.placeBasketOrder(apiKey, 'calendar_arbitrage', orders)
      if (res.status === 'success') {
        const ok = (res.results || []).filter((r) => r.status === 'success').length
        const modeNote = res.mode === 'analyze' ? ' (analyzer)' : ''
        showToast.success(`Spread order placed: ${ok}/${orders.length} legs${modeNote}`, 'orders')
        setTradeRow(null)
      } else {
        showToast.error(res.message || 'Basket order failed')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to place spread order'
      showToast.error(message)
    } finally {
      setSubmitting(false)
    }
  }, [tradeRow, tradeDir, apiKey, lots, pricetype, product, nearPrice, farPrice])

  const connBadge = () => {
    if (conn.isFallbackMode) return <Badge variant="secondary">REST fallback (after-hours)</Badge>
    if (conn.isAuthenticated) return <Badge className="bg-emerald-600 text-white">Live</Badge>
    if (conn.isConnected) return <Badge variant="secondary">Authenticating…</Badge>
    return <Badge variant="outline">Connecting…</Badge>
  }

  return (
    <div className="py-6 space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Arbitrage</h1>
          <p className="text-muted-foreground mt-1">
            Realtime futures calendar-spread scanner (NFO &amp; MCX). Ranks near-vs-next and
            near-vs-third month pairs by executable bid/ask spread.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {connBadge()}
          <Button variant="outline" size="sm" onClick={loadUniverse} disabled={loading}>
            {loading ? 'Loading…' : 'Refresh universe'}
          </Button>
        </div>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">Filters</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-4">
            <div className="space-y-1.5">
              <Label>Exchange</Label>
              <Select value={exchangeFilter} onValueChange={setExchangeFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All</SelectItem>
                  {exchanges.map((ex) => (
                    <SelectItem key={ex} value={ex}>
                      {ex}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>Pair type</Label>
              <Select value={typeFilter} onValueChange={setTypeFilter}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="ALL">All</SelectItem>
                  <SelectItem value="near-next">Near vs Next</SelectItem>
                  <SelectItem value="near-third">Near vs Third</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="space-y-1.5">
              <Label>Min spread %</Label>
              <Input
                type="number"
                inputMode="decimal"
                step="0.05"
                placeholder="e.g. 0.5"
                value={minSpread}
                onChange={(e) => setMinSpread(e.target.value)}
              />
            </div>

            <div className="space-y-1.5">
              <Label>Underlying</Label>
              <Input
                placeholder="Search e.g. NIFTY"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>

            <div className="flex items-end gap-2 pb-1">
              <Switch id="only-liquid" checked={onlyLiquid} onCheckedChange={setOnlyLiquid} />
              <Label htmlFor="only-liquid" className="cursor-pointer">
                Two-sided quotes only
              </Label>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            Opportunities
            <span className="text-sm font-normal text-muted-foreground">
              {visibleRows.length} of {pairs.length} pairs
              {generatedAt ? ` · universe ${new Date(generatedAt).toLocaleTimeString()}` : ''}
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {universeError ? (
            <div className="text-sm text-destructive py-8 text-center">{universeError}</div>
          ) : loading ? (
            <div className="text-sm text-muted-foreground py-8 text-center">
              Loading futures universe…
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10">#</TableHead>
                  <TableHead>Underlying</TableHead>
                  <TableHead>Exch</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Near (bid/ask)</TableHead>
                  <TableHead>Far (bid/ask)</TableHead>
                  <TableHead className="text-right">Net</TableHead>
                  <TableHead className="text-right">Spread %</TableHead>
                  <TableHead>Direction</TableHead>
                  <TableHead className="text-right">Trade</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {visibleRows.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={10} className="text-center text-muted-foreground py-8">
                      No pairs match the current filters (or no live quotes yet).
                    </TableCell>
                  </TableRow>
                ) : (
                  visibleRows.map((row, idx) => {
                    const pctColor =
                      row.spreadPct == null
                        ? ''
                        : row.spreadPct > 0
                          ? 'text-emerald-600'
                          : 'text-red-600'
                    return (
                      <TableRow key={row.pair.id}>
                        <TableCell className="text-muted-foreground">{idx + 1}</TableCell>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-1.5">
                            <span
                              className={`inline-block h-2 w-2 rounded-full ${
                                row.fresh ? 'bg-emerald-500' : 'bg-muted-foreground/40'
                              }`}
                              title={row.fresh ? 'Live' : 'Stale / no recent tick'}
                            />
                            {row.pair.underlying}
                          </div>
                        </TableCell>
                        <TableCell>{row.pair.exchange}</TableCell>
                        <TableCell>
                          <Badge variant="outline" className="font-normal">
                            {row.pair.type === 'near-next' ? 'Next' : 'Third'}
                          </Badge>
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <div className="text-xs text-muted-foreground">
                            {row.pair.near.expiry}
                          </div>
                          {fmt(row.near?.bid)} / {fmt(row.near?.ask)}
                        </TableCell>
                        <TableCell className="whitespace-nowrap">
                          <div className="text-xs text-muted-foreground">{row.pair.far.expiry}</div>
                          {fmt(row.far?.bid)} / {fmt(row.far?.ask)}
                        </TableCell>
                        <TableCell className="text-right tabular-nums">
                          {fmt(row.bestCredit)}
                        </TableCell>
                        <TableCell className={`text-right tabular-nums font-semibold ${pctColor}`}>
                          {row.spreadPct == null ? '—' : `${row.spreadPct.toFixed(2)}%`}
                        </TableCell>
                        <TableCell className="text-xs">
                          {row.direction ? directionLabel(row.direction) : '—'}
                        </TableCell>
                        <TableCell className="text-right">
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={!row.hasData}
                            onClick={() => openTrade(row)}
                          >
                            Trade
                          </Button>
                        </TableCell>
                      </TableRow>
                    )
                  })
                )}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Dialog open={tradeRow !== null} onOpenChange={(o) => !o && setTradeRow(null)}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {tradeRow ? `${tradeRow.pair.underlying} calendar spread` : 'Spread order'}
            </DialogTitle>
            <DialogDescription>
              Two-leg basket order. BUY leg is executed before the SELL leg for margin efficiency.
            </DialogDescription>
          </DialogHeader>

          {tradeRow && (
            <div className="space-y-4">
              <div className="space-y-1.5">
                <Label>Direction</Label>
                <Select value={tradeDir} onValueChange={(v) => onChangeDir(v as Direction)}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="SHORT_SPREAD">
                      Sell far / Buy near (capture far premium)
                    </SelectItem>
                    <SelectItem value="LONG_SPREAD">Buy far / Sell near</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="grid grid-cols-3 gap-3">
                <div className="space-y-1.5">
                  <Label>Lots</Label>
                  <Input
                    type="number"
                    min="1"
                    step="1"
                    value={lots}
                    onChange={(e) => setLots(e.target.value)}
                  />
                </div>
                <div className="space-y-1.5">
                  <Label>Price type</Label>
                  <Select
                    value={pricetype}
                    onValueChange={(v) => {
                      setPricetype(v as 'LIMIT' | 'MARKET')
                      if (tradeRow) prefillPrices(tradeRow, tradeDir)
                    }}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="LIMIT">LIMIT</SelectItem>
                      <SelectItem value="MARKET">MARKET</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
                <div className="space-y-1.5">
                  <Label>Product</Label>
                  <Select value={product} onValueChange={(v) => setProduct(v as 'NRML' | 'MIS')}>
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="NRML">NRML</SelectItem>
                      <SelectItem value="MIS">MIS</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {(() => {
                const farAction = tradeDir === 'SHORT_SPREAD' ? 'SELL' : 'BUY'
                const nearAction = tradeDir === 'SHORT_SPREAD' ? 'BUY' : 'SELL'
                const lotsN = Number.parseInt(lots, 10)
                const nearLot = tradeRow.pair.near.lotsize ?? 0
                const farLot = tradeRow.pair.far.lotsize ?? 0
                const nearQty = Number.isInteger(lotsN) && lotsN > 0 ? lotsN * nearLot : 0
                const farQty = Number.isInteger(lotsN) && lotsN > 0 ? lotsN * farLot : 0
                return (
                  <div className="space-y-2 rounded-md border p-3 text-sm">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium">
                        <Badge
                          variant={nearAction === 'BUY' ? 'default' : 'destructive'}
                          className="mr-2"
                        >
                          {nearAction}
                        </Badge>
                        {tradeRow.pair.near.symbol}
                      </span>
                      <span className="text-muted-foreground">
                        {nearQty} ({lots || '0'}×{nearLot})
                      </span>
                    </div>
                    {pricetype === 'LIMIT' && (
                      <Input
                        type="number"
                        step={tradeRow.pair.near.tick_size || 0.05}
                        value={nearPrice}
                        onChange={(e) => setNearPrice(e.target.value)}
                        placeholder="Near leg limit price"
                      />
                    )}
                    <div className="flex items-center justify-between gap-2 pt-1">
                      <span className="font-medium">
                        <Badge
                          variant={farAction === 'BUY' ? 'default' : 'destructive'}
                          className="mr-2"
                        >
                          {farAction}
                        </Badge>
                        {tradeRow.pair.far.symbol}
                      </span>
                      <span className="text-muted-foreground">
                        {farQty} ({lots || '0'}×{farLot})
                      </span>
                    </div>
                    {pricetype === 'LIMIT' && (
                      <Input
                        type="number"
                        step={tradeRow.pair.far.tick_size || 0.05}
                        value={farPrice}
                        onChange={(e) => setFarPrice(e.target.value)}
                        placeholder="Far leg limit price"
                      />
                    )}
                    <div className="text-xs text-muted-foreground pt-1">
                      Executable net {fmt(tradeRow.bestCredit)} ·{' '}
                      {tradeRow.spreadPct == null ? '—' : `${tradeRow.spreadPct.toFixed(2)}%`} of
                      near mid
                    </div>
                  </div>
                )
              })()}
            </div>
          )}

          <DialogFooter>
            <Button variant="outline" onClick={() => setTradeRow(null)} disabled={submitting}>
              Cancel
            </Button>
            <Button onClick={submitTrade} disabled={submitting}>
              {submitting ? 'Placing…' : 'Place spread order'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
