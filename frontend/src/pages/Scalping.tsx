import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { scalpingApi } from '@/api/scalping'
import { tradingApi } from '@/api/trading'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
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
import { useAuthStore } from '@/stores/authStore'
import type { OptionChainRow, ScalpingAction, ScalpingProduct, SelectedLeg } from '@/types/scalping'
import { showToast } from '@/utils/toast'

const DEFAULT_STRIKE_COUNT = 10
const MAX_LOTS = 20
const BOOK_REFETCH_MS = 1000

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
  changePercent?: number
}

function Ticker({ title, symbol, ltp, changePercent }: TickerProps) {
  const isUp = (changePercent ?? 0) >= 0
  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm text-muted-foreground">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="font-mono text-xs text-muted-foreground">{symbol ?? '—'}</div>
        <div className="font-mono text-2xl font-semibold tabular-nums">
          {ltp != null ? ltp.toFixed(2) : '—'}
        </div>
        {changePercent != null && (
          <div className={`font-mono text-sm ${isUp ? 'text-green-600' : 'text-red-600'}`}>
            {isUp ? '+' : ''}
            {changePercent.toFixed(2)}%
          </div>
        )}
      </CardContent>
    </Card>
  )
}

export default function Scalping() {
  const apiKey = useAuthStore((s) => s.apiKey)
  const queryClient = useQueryClient()

  const [underlying, setUnderlying] = useState<string>('')
  const [expiry, setExpiry] = useState<string>('')
  const [ceStrike, setCeStrike] = useState<string>('')
  const [peStrike, setPeStrike] = useState<string>('')

  // Order-entry controls
  const [armed, setArmed] = useState(false)
  const [lots, setLots] = useState(1)
  const [product, setProduct] = useState<ScalpingProduct>('MIS')

  // Underlyings
  const { data: underlyingsResp } = useQuery({
    queryKey: ['scalping', 'underlyings'],
    queryFn: () => scalpingApi.getUnderlyings(),
  })
  const underlyings = underlyingsResp?.data ?? []
  const underlyingCfg = underlyings.find((u) => u.underlying === underlying)

  // Expiry (depends on underlying)
  const { data: expiryResp } = useQuery({
    queryKey: ['scalping', 'expiry', underlying],
    queryFn: () => scalpingApi.getExpiry(underlying),
    enabled: !!underlying,
  })
  const expiries = expiryResp?.data ?? []

  // Strikes / chain (depends on underlying + expiry)
  const { data: chainResp } = useQuery({
    queryKey: ['scalping', 'strikes', underlying, expiry],
    queryFn: () => scalpingApi.getStrikes(underlying, expiry, DEFAULT_STRIKE_COUNT),
    enabled: !!underlying && !!expiry,
  })
  const chain = useMemo(() => chainResp?.chain ?? [], [chainResp])
  const foExchange = chainResp?.fo_exchange ?? underlyingCfg?.fo_exchange ?? ''
  const indexExchange = chainResp?.index_exchange ?? underlyingCfg?.index_exchange ?? ''

  // Default the CE/PE strike to ATM once the chain loads.
  useEffect(() => {
    if (chainResp?.atm_strike != null && chain.length > 0) {
      const atm = String(chainResp.atm_strike)
      setCeStrike(atm)
      setPeStrike(atm)
    }
  }, [chainResp, chain])

  const ceRow = chain.find((r) => String(r.strike) === ceStrike)
  const peRow = chain.find((r) => String(r.strike) === peStrike)
  const ceLeg = buildLeg(ceRow, 'ce', foExchange)
  const peLeg = buildLeg(peRow, 'pe', foExchange)

  // Subscribe underlying + both legs to the live feed (Quote mode = ltp + change).
  const symbols = useMemo(() => {
    const list: Array<{ symbol: string; exchange: string }> = []
    if (underlying && indexExchange) list.push({ symbol: underlying, exchange: indexExchange })
    if (ceLeg) list.push({ symbol: ceLeg.symbol, exchange: ceLeg.exchange })
    if (peLeg) list.push({ symbol: peLeg.symbol, exchange: peLeg.exchange })
    return list
  }, [underlying, indexExchange, ceLeg, peLeg])

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

  // Books (positions / orders / trades) — auto-refetch for live grids + MTM.
  const { data: posResp } = useQuery({
    queryKey: ['scalping', 'positions'],
    queryFn: () => tradingApi.getPositions(apiKey ?? ''),
    enabled: !!apiKey,
    refetchInterval: BOOK_REFETCH_MS,
  })
  const { data: ordResp } = useQuery({
    queryKey: ['scalping', 'orders'],
    queryFn: () => tradingApi.getOrders(apiKey ?? ''),
    enabled: !!apiKey,
    refetchInterval: BOOK_REFETCH_MS,
  })
  const { data: trdResp } = useQuery({
    queryKey: ['scalping', 'trades'],
    queryFn: () => tradingApi.getTrades(apiKey ?? ''),
    enabled: !!apiKey,
    refetchInterval: BOOK_REFETCH_MS,
  })
  const positions = posResp?.data ?? []
  const orders = ordResp?.data?.orders ?? []
  const trades = trdResp?.data ?? []

  const netQty = positions.reduce((a, p) => a + (p.quantity || 0), 0)
  const mtm = positions.reduce((a, p) => a + (p.pnl || 0), 0)

  const refreshBooks = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['scalping', 'positions'] })
    queryClient.invalidateQueries({ queryKey: ['scalping', 'orders'] })
    queryClient.invalidateQueries({ queryKey: ['scalping', 'trades'] })
  }, [queryClient])

  // Latest order-entry state for the (stable) keyboard handler — avoids stale closures.
  const stateRef = useRef({ armed, lots, product, ceLeg, peLeg })
  stateRef.current = { armed, lots, product, ceLeg, peLeg }

  const submitOrder = useCallback(
    async (leg: SelectedLeg | null, action: ScalpingAction) => {
      const s = stateRef.current
      if (!s.armed) {
        showToast.error('One-Click is disarmed — enable it to trade', 'orders')
        return
      }
      if (!leg) {
        showToast.error('No strike selected', 'orders')
        return
      }
      if (!leg.lotsize) {
        showToast.error('Lot size unavailable for this strike', 'orders')
        return
      }
      const quantity = s.lots * leg.lotsize
      try {
        const res = await scalpingApi.placeOrder({
          symbol: leg.symbol,
          exchange: leg.exchange,
          action,
          quantity,
          product: s.product,
        })
        if (res.status === 'success') {
          showToast.success(
            `${action} ${leg.optionType} x${s.lots} (${quantity}) → ${res.orderid ?? 'ok'}`,
            'orders'
          )
          refreshBooks()
        } else {
          showToast.error(res.message ?? 'Order failed', 'orders')
        }
      } catch (e) {
        showToast.error((e as Error).message, 'orders')
      }
    },
    [refreshBooks]
  )

  const doCloseAll = useCallback(async () => {
    try {
      const res = await scalpingApi.closeAll()
      if (res.status === 'success') {
        showToast.success(res.message ?? 'All positions squared off', 'orders')
      } else {
        showToast.error(res.message ?? 'Close all failed', 'orders')
      }
    } catch (e) {
      showToast.error((e as Error).message, 'orders')
    }
    refreshBooks()
  }, [refreshBooks])

  const doCancelAll = useCallback(async () => {
    try {
      const res = await scalpingApi.cancelAll()
      if (res.status === 'success') {
        showToast.success(res.message ?? 'All orders cancelled', 'orders')
      } else {
        showToast.error(res.message ?? 'Cancel all failed', 'orders')
      }
    } catch (e) {
      showToast.error((e as Error).message, 'orders')
    }
    refreshBooks()
  }, [refreshBooks])

  // Global keyboard handler: arrows fire orders, F6 close-all, F7 cancel-all.
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
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
          <Badge variant={armed ? 'destructive' : 'secondary'}>
            One-Click {armed ? 'ARMED' : 'off'}
          </Badge>
          <Badge variant={wsBadge.variant}>{wsBadge.label}</Badge>
        </div>
      </div>

      {/* Selection controls */}
      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 md:grid-cols-4">
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
        </CardContent>
      </Card>

      {/* Live tickers */}
      <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <Ticker
          title="Call (CE)"
          symbol={ceLeg?.symbol}
          ltp={ceTick?.ltp}
          changePercent={ceTick?.change_percent}
        />
        <Ticker
          title={underlying || 'Underlying'}
          symbol={underlying}
          ltp={underlyingTick?.ltp}
          changePercent={underlyingTick?.change_percent}
        />
        <Ticker
          title="Put (PE)"
          symbol={peLeg?.symbol}
          ltp={peTick?.ltp}
          changePercent={peTick?.change_percent}
        />
      </div>

      {/* Order entry */}
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap items-center gap-6">
            <label className="flex items-center gap-2">
              <Switch checked={armed} onCheckedChange={setArmed} />
              <span className="text-sm font-medium">One-Click</span>
            </label>

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

            <div className="flex items-center gap-2">
              <span className="text-sm text-muted-foreground">Product</span>
              <Select value={product} onValueChange={(v) => setProduct(v as ScalpingProduct)}>
                <SelectTrigger className="w-28">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="MIS">MIS</SelectItem>
                  <SelectItem value="NRML">NRML</SelectItem>
                </SelectContent>
              </Select>
            </div>

            <div className="ml-auto flex items-center gap-6 font-mono">
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

          <div className="flex items-center gap-3">
            <Button variant="outline" onClick={doCloseAll}>
              Close All Positions / F6
            </Button>
            <Button variant="outline" onClick={doCancelAll}>
              Cancel All Orders / F7
            </Button>
            <span className="text-xs text-muted-foreground">
              Keys: ↑ Buy Call · ↓ Sell Call · → Buy Put · ← Sell Put · F6 close · F7 cancel
            </span>
          </div>
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
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Symbol</TableHead>
                <TableHead>Product</TableHead>
                <TableHead className="text-right">Qty</TableHead>
                <TableHead className="text-right">Avg</TableHead>
                <TableHead className="text-right">LTP</TableHead>
                <TableHead className="text-right">P&amp;L</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {positions.map((p) => (
                <TableRow key={`${p.symbol}-${p.product}`}>
                  <TableCell className="font-mono text-sm">{p.symbol}</TableCell>
                  <TableCell>{p.product}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">{p.quantity}</TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {p.average_price?.toFixed(2)}
                  </TableCell>
                  <TableCell className="text-right font-mono tabular-nums">
                    {p.ltp?.toFixed(2)}
                  </TableCell>
                  <TableCell
                    className={`text-right font-mono tabular-nums ${
                      (p.pnl || 0) >= 0 ? 'text-green-600' : 'text-red-600'
                    }`}
                  >
                    {p.pnl?.toFixed(2)}
                  </TableCell>
                </TableRow>
              ))}
              {positions.length === 0 && (
                <TableRow>
                  <TableCell colSpan={6} className="text-center text-muted-foreground">
                    No open positions
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
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
              {orders.map((o) => (
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
              {orders.length === 0 && (
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
              {trades.map((t) => (
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
              {trades.length === 0 && (
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
    </div>
  )
}
