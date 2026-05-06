/**
 * Strategy v2 — runs list for a single strategy.
 *
 * Tabs:
 *   Runs         — per-run lifecycle list (default landing tab)
 *   Orderbook    — strategy-level orderbook aggregated across every run
 *                  (same envelope as global /orderbook)
 *   Tradebook    — strategy-level tradebook
 *   Positions    — currently OPEN positions across the strategy
 *
 * URL: /strategy/v2/:strategyId/runs
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { strategyV2Api } from '@/api/strategy_v2'
import { useStrategyV2Socket } from '@/hooks/useStrategyV2Socket'
import type {
  RunPositionRow,
  RunTradeRow,
  StrategyLeg,
  StrategyRun,
  StrategyV2,
} from '@/types/strategy_v2'

interface OrderRow {
  action: string
  symbol: string
  exchange: string
  orderid: string
  product: string
  quantity: string
  price: number
  pricetype: string
  order_status: string
  trigger_price: number
  timestamp: string
  source?: string
  mode?: string
  run_id?: number
}

interface OrderbookStats {
  total_buy_orders: number
  total_sell_orders: number
  total_completed_orders: number
  total_open_orders: number
  total_rejected_orders: number
}

const STATUS_BADGE: Record<string, string> = {
  complete: 'bg-emerald-500/15 text-emerald-700',
  open: 'bg-sky-500/15 text-sky-700',
  rejected: 'bg-rose-500/15 text-rose-700',
  cancelled: 'bg-neutral-500/15 text-neutral-700',
}

const STATE_BADGE: Record<string, string> = {
  ARMED: 'bg-emerald-500/15 text-emerald-700',
  ENTERING: 'bg-sky-500/15 text-sky-700',
  IN_TRADE: 'bg-emerald-500/15 text-emerald-700',
  EXITING: 'bg-amber-500/15 text-amber-700',
  CLOSED: 'bg-neutral-500/15 text-neutral-700',
  ENTRY_FAILED: 'bg-rose-500/15 text-rose-700',
  EXIT_FAILED: 'bg-rose-500/15 text-rose-700',
  ERRORED: 'bg-rose-500/15 text-rose-700',
  STOPPED: 'bg-neutral-500/15 text-neutral-700',
}

export default function StrategyV2Runs() {
  const { strategyId } = useParams<{ strategyId: string }>()
  const navigate = useNavigate()
  const [runs, setRuns] = useState<StrategyRun[]>([])
  const [strategy, setStrategy] = useState<StrategyV2 | null>(null)
  const [legs, setLegs] = useState<StrategyLeg[]>([])
  const [loading, setLoading] = useState(true)

  // Strategy-level book data — fetched lazily when user switches tabs.
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [orderStats, setOrderStats] = useState<OrderbookStats | null>(null)
  const [trades, setTrades] = useState<RunTradeRow[]>([])
  const [positions, setPositions] = useState<RunPositionRow[]>([])
  // Positions opens by default — it's the most actionable view (what's
  // currently exposed). Runs is for lifecycle drill-down; orders/trades
  // are post-mortem audit.
  const [tab, setTab] = useState<'runs' | 'orders' | 'trades' | 'positions'>('positions')

  const sid = strategyId ? Number(strategyId) : null

  // Socket.IO subscription — surfaces live MTM from the engine for any
  // active run. Backend debounces at 5Hz per run, so the table updates
  // smoothly without thrashing renders. The hook joins room=strategy_<sid>
  // on mount and leaves on unmount.
  const live = useStrategyV2Socket(sid, !!sid)

  useEffect(() => {
    if (!sid) return
    setLoading(true)
    Promise.all([strategyV2Api.get(sid), strategyV2Api.listRuns(sid)])
      .then(([s, r]) => {
        setStrategy(s.strategy)
        setLegs(s.legs)
        setRuns(r)
      })
      .catch((err) => {
        toast.error('Failed to load runs')
        console.error(err)
      })
      .finally(() => setLoading(false))
  }, [sid])

  // Lazy-fetch each tab's data on first switch + when the user comes
  // back to it (so e.g. closing a position reflects in Positions tab).
  useEffect(() => {
    if (!sid) return
    if (tab === 'orders') {
      strategyV2Api
        .strategyOrderbook(sid)
        .then((r) => {
          setOrders((r.data?.orders ?? []) as OrderRow[])
          setOrderStats((r.data?.statistics ?? null) as OrderbookStats | null)
        })
        .catch((err) => {
          toast.error('Failed to load orderbook')
          console.error(err)
        })
    } else if (tab === 'trades') {
      strategyV2Api
        .strategyTradebook(sid)
        .then((r) => setTrades(r.data ?? []))
        .catch((err) => {
          toast.error('Failed to load tradebook')
          console.error(err)
        })
    } else if (tab === 'positions') {
      strategyV2Api
        .strategyPositionbook(sid)
        .then((r) => setPositions(r.data ?? []))
        .catch((err) => {
          toast.error('Failed to load positionbook')
          console.error(err)
        })
    }
  }, [sid, tab])

  if (loading) {
    return <div className="container mx-auto p-8">Loading…</div>
  }

  return (
    <div className="container mx-auto p-6 max-w-6xl space-y-6">
      <div>
        <button
          type="button"
          onClick={() => navigate(`/strategy/v2/${sid}`)}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← {strategy?.name ?? 'Strategy'}
        </button>
        <h1 className="text-2xl font-semibold mt-1">Runs</h1>
        <p className="text-sm text-muted-foreground">
          Each run is one signal-to-flat lifecycle. Click a row to inspect orderbook,
          trades, positions, and the audit timeline.
        </p>
      </div>

      {/* Strategy intent banner — what this strategy is configured to trade,
          so the user doesn't have to bounce back to the builder to remember. */}
      {legs.length > 0 && (
        <Card>
          <CardContent className="py-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
            <span className="text-xs uppercase text-muted-foreground">
              Trades
            </span>
            {legs.map((l) => (
              <Badge
                key={l.id}
                variant="outline"
                className={
                  l.position === 'B'
                    ? 'bg-emerald-500/10 text-emerald-700 border-emerald-500/30'
                    : 'bg-rose-500/10 text-rose-700 border-rose-500/30'
                }
              >
                <span className="font-mono">
                  {l.segment === 'CASH'
                    ? `${l.symbol_cash}${l.exchange_cash ? ` · ${l.exchange_cash}` : ''}`
                    : `${strategy?.underlying ?? ''} ${l.expiry_type ?? ''} ${l.option_type ?? ''}`}
                </span>
                <span className="ml-2 text-xs">
                  {l.position} ·{' '}
                  {l.segment === 'CASH' ? `${l.qty} qty` : `${l.lots} lots`}
                  {' · '}
                  {l.product}
                </span>
              </Badge>
            ))}
          </CardContent>
        </Card>
      )}

      <Tabs value={tab} onValueChange={(v) => setTab(v as typeof tab)}>
        <TabsList>
          <TabsTrigger value="positions">Positions ({positions.length})</TabsTrigger>
          <TabsTrigger value="orders">Orderbook</TabsTrigger>
          <TabsTrigger value="trades">Tradebook ({trades.length || ''})</TabsTrigger>
          <TabsTrigger value="runs">Runs ({runs.length})</TabsTrigger>
        </TabsList>

        {/* ---------- Positions ---------- */}
        <TabsContent value="positions">
          <Card>
            <CardContent className="p-0">
              {positions.length === 0 ? (
                <div className="py-12 text-center text-muted-foreground">
                  No open positions. Fire a webhook to enter.
                </div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Symbol</th>
                      <th className="px-4 py-3">Exchange</th>
                      <th className="px-4 py-3">Product</th>
                      <th className="px-4 py-3 text-right">Qty</th>
                      <th className="px-4 py-3 text-right">Avg Price</th>
                      <th className="px-4 py-3 text-right">LTP</th>
                      <th className="px-4 py-3 text-right">P&L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => (
                      <tr key={`${p.run_id}-${p.leg_id}`} className="border-b last:border-b-0">
                        <td className="px-4 py-2 font-mono">{p.symbol}</td>
                        <td className="px-4 py-2 text-xs">{p.exchange}</td>
                        <td className="px-4 py-2 text-xs">{p.product}</td>
                        <td className="px-4 py-2 text-right font-mono">{p.quantity}</td>
                        <td className="px-4 py-2 text-right font-mono">{p.average_price}</td>
                        <td className="px-4 py-2 text-right font-mono">{p.ltp}</td>
                        <td
                          className={`px-4 py-2 text-right font-mono ${
                            Number(p.pnl) > 0
                              ? 'text-emerald-700'
                              : Number(p.pnl) < 0
                                ? 'text-rose-700'
                                : ''
                          }`}
                        >
                          {p.pnl}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------- Orderbook ---------- */}
        <TabsContent value="orders">
          {orderStats && (
            <Card className="mb-3">
              <CardContent className="py-3 grid grid-cols-2 sm:grid-cols-5 gap-3 text-sm">
                <Stat label="Buy" value={orderStats.total_buy_orders} />
                <Stat label="Sell" value={orderStats.total_sell_orders} />
                <Stat label="Complete" value={orderStats.total_completed_orders} tone="positive" />
                <Stat label="Open" value={orderStats.total_open_orders} />
                <Stat label="Rejected" value={orderStats.total_rejected_orders} tone="negative" />
              </CardContent>
            </Card>
          )}
          <Card>
            <CardContent className="p-0">
              {orders.length === 0 ? (
                <div className="py-12 text-center text-muted-foreground">No orders.</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Symbol</th>
                      <th className="px-4 py-3">Exchange</th>
                      <th className="px-4 py-3">Action</th>
                      <th className="px-4 py-3 text-right">Qty</th>
                      <th className="px-4 py-3 text-right">Price</th>
                      <th className="px-4 py-3">Type</th>
                      <th className="px-4 py-3">Product</th>
                      <th className="px-4 py-3">Status</th>
                      <th className="px-4 py-3">Order ID</th>
                      <th className="px-4 py-3">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orders.map((o) => (
                      <tr key={o.orderid || `${o.run_id}-${o.symbol}-${o.timestamp}`} className="border-b last:border-b-0">
                        <td className="px-4 py-2 font-mono">{o.symbol}</td>
                        <td className="px-4 py-2 text-xs">{o.exchange}</td>
                        <td className="px-4 py-2">
                          <Badge
                            variant="outline"
                            className={
                              o.action === 'BUY'
                                ? 'bg-emerald-500/15 text-emerald-700'
                                : 'bg-rose-500/15 text-rose-700'
                            }
                          >
                            {o.action}
                          </Badge>
                        </td>
                        <td className="px-4 py-2 text-right font-mono">{o.quantity}</td>
                        <td className="px-4 py-2 text-right font-mono">{o.price}</td>
                        <td className="px-4 py-2 text-xs">{o.pricetype}</td>
                        <td className="px-4 py-2 text-xs">{o.product}</td>
                        <td className="px-4 py-2">
                          <Badge variant="outline" className={STATUS_BADGE[o.order_status] || ''}>
                            {o.order_status}
                          </Badge>
                        </td>
                        <td className="px-4 py-2 font-mono text-xs">{o.orderid || '—'}</td>
                        <td className="px-4 py-2 text-xs">{o.timestamp || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------- Tradebook ---------- */}
        <TabsContent value="trades">
          <Card>
            <CardContent className="p-0">
              {trades.length === 0 ? (
                <div className="py-12 text-center text-muted-foreground">No trades.</div>
              ) : (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">Symbol</th>
                      <th className="px-4 py-3">Exchange</th>
                      <th className="px-4 py-3">Action</th>
                      <th className="px-4 py-3 text-right">Qty</th>
                      <th className="px-4 py-3 text-right">Avg Price</th>
                      <th className="px-4 py-3 text-right">Trade Value</th>
                      <th className="px-4 py-3">Product</th>
                      <th className="px-4 py-3">Order ID</th>
                      <th className="px-4 py-3">Timestamp</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t) => (
                      <tr key={`${t.orderid || ''}-${t.timestamp || ''}`} className="border-b last:border-b-0">
                        <td className="px-4 py-2 font-mono">{t.symbol}</td>
                        <td className="px-4 py-2 text-xs">{t.exchange}</td>
                        <td className="px-4 py-2">
                          <Badge
                            variant="outline"
                            className={
                              t.action === 'BUY'
                                ? 'bg-emerald-500/15 text-emerald-700'
                                : 'bg-rose-500/15 text-rose-700'
                            }
                          >
                            {t.action}
                          </Badge>
                        </td>
                        <td className="px-4 py-2 text-right font-mono">{t.quantity}</td>
                        <td className="px-4 py-2 text-right font-mono">{t.average_price}</td>
                        <td className="px-4 py-2 text-right font-mono">{t.trade_value}</td>
                        <td className="px-4 py-2 text-xs">{t.product}</td>
                        <td className="px-4 py-2 font-mono text-xs">{t.orderid || '—'}</td>
                        <td className="px-4 py-2 text-xs">{t.timestamp || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* ---------- Runs ---------- */}
        <TabsContent value="runs">
          {runs.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center text-muted-foreground">
                No runs yet. Fire a webhook to start one.
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-3">#</th>
                      <th className="px-4 py-3">State</th>
                      <th className="px-4 py-3">Mode</th>
                      <th className="px-4 py-3">Triggered</th>
                      <th className="px-4 py-3">Entered</th>
                      <th className="px-4 py-3">Exited</th>
                      <th className="px-4 py-3">Exit Reason</th>
                      <th className="px-4 py-3 text-right">Live MTM</th>
                      <th className="px-4 py-3 text-right">Realized P&L</th>
                      <th className="px-4 py-3 text-right">Peak</th>
                      <th className="px-4 py-3 text-right">Drawdown</th>
                    </tr>
                  </thead>
                  <tbody>
                    {runs.map((r) => {
                      const liveForThisRun =
                        live.pnl && live.pnl.run_id === r.id ? live.pnl : null
                      const liveMtm = liveForThisRun ? liveForThisRun.agg_mtm : null
                      return (
                        <tr
                          key={r.id}
                          className="border-b last:border-b-0 hover:bg-muted/40 cursor-pointer"
                          onClick={() => navigate(`/strategy/v2/${sid}/runs/${r.id}`)}
                        >
                          <td className="px-4 py-2 font-mono text-xs">{r.id}</td>
                          <td className="px-4 py-2">
                            <Badge variant="outline" className={STATE_BADGE[r.state] || ''}>
                              {r.state}
                            </Badge>
                          </td>
                          <td className="px-4 py-2">{r.mode === 'sandbox' ? 'SBX' : 'LIVE'}</td>
                          <td className="px-4 py-2 text-xs">{r.triggered_at ?? '—'}</td>
                          <td className="px-4 py-2 text-xs">{r.entered_at ?? '—'}</td>
                          <td className="px-4 py-2 text-xs">{r.exited_at ?? '—'}</td>
                          <td className="px-4 py-2 text-xs">{r.exit_reason ?? '—'}</td>
                          <td
                            className={`px-4 py-2 text-right font-mono ${
                              liveMtm === null
                                ? 'text-muted-foreground'
                                : liveMtm > 0
                                  ? 'text-emerald-700'
                                  : liveMtm < 0
                                    ? 'text-rose-700'
                                    : ''
                            }`}
                          >
                            {liveMtm === null ? '—' : fmtMoney(liveMtm)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {fmtMoney(r.realized_pnl)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-emerald-700">
                            {fmtMoney(r.peak_mtm)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-rose-700">
                            {fmtMoney(r.max_drawdown)}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          )}
        </TabsContent>
      </Tabs>
    </div>
  )
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string
  value: number
  tone?: 'positive' | 'negative'
}) {
  const cls = tone === 'positive' ? 'text-emerald-700' : tone === 'negative' ? 'text-rose-700' : ''
  return (
    <div className="space-y-1">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className={`font-mono text-lg ${cls}`}>{Math.round(value)}</div>
    </div>
  )
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}₹${n.toFixed(2)}`
}
