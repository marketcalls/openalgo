/**
 * Strategy v2 — single run detail with tabbed reporting.
 *
 * Tabs (per plan §11 Phase 2):
 *   Overview     — state badge, P&L peaks, exit reason, run metadata
 *   Orders       — strategy-scoped orderbook, same shape as /api/v1/orderbook
 *   Trades       — strategy-scoped tradebook
 *   Positions    — strategy-scoped positionbook with RMS state surfaced
 *   Events       — audit timeline; "verify chain" button hits /audit/verify
 *
 * URL: /strategy/v2/:strategyId/runs/:runId
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { strategyV2Api } from '@/api/strategy_v2'
import { useStrategyV2Socket } from '@/hooks/useStrategyV2Socket'
import type {
  AuditVerifyResponse,
  RunEventRow,
  RunOrderbookResponse,
  RunPositionRow,
  RunTradeRow,
  StrategyRun,
} from '@/types/strategy_v2'

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

const ORDER_STATUS_BADGE: Record<string, string> = {
  complete: 'bg-emerald-500/15 text-emerald-700',
  open: 'bg-sky-500/15 text-sky-700',
  trigger_pending: 'bg-amber-500/15 text-amber-700',
  cancelled: 'bg-neutral-500/15 text-neutral-700',
  rejected: 'bg-rose-500/15 text-rose-700',
  pending: 'bg-neutral-500/15 text-neutral-700',
}

export default function StrategyV2RunDetail() {
  const { strategyId, runId } = useParams<{ strategyId: string; runId: string }>()
  const navigate = useNavigate()
  const sid = strategyId ? Number(strategyId) : null
  const rid = runId ? Number(runId) : null

  const [run, setRun] = useState<StrategyRun | null>(null)
  const [orderbook, setOrderbook] = useState<RunOrderbookResponse['data'] | null>(null)
  const [trades, setTrades] = useState<RunTradeRow[]>([])
  const [positions, setPositions] = useState<RunPositionRow[]>([])
  const [events, setEvents] = useState<RunEventRow[]>([])
  const [loading, setLoading] = useState(true)
  const [verifyResult, setVerifyResult] = useState<AuditVerifyResponse | null>(null)

  // Live updates via Socket.IO — joins room=f"strategy_{strategyId}" on
  // mount, leaves on unmount. Backend debounces at 200ms per run so even
  // 1000 ticks/sec only produces ~5 React renders/sec.
  const live = useStrategyV2Socket(sid, !!sid)

  useEffect(() => {
    if (!rid) return
    setLoading(true)
    Promise.all([
      strategyV2Api.getRun(rid),
      strategyV2Api.runOrderbook(rid),
      strategyV2Api.runTradebook(rid),
      strategyV2Api.runPositionbook(rid),
      strategyV2Api.runEvents(rid),
    ])
      .then(([rRun, rOb, rTb, rPb, rEv]) => {
        setRun(rRun)
        setOrderbook(rOb.data)
        setTrades(rTb.data || [])
        setPositions(rPb.data || [])
        setEvents(rEv.data || [])
      })
      .catch((err) => {
        toast.error('Failed to load run details')
        console.error(err)
      })
      .finally(() => setLoading(false))
  }, [rid])

  const onVerifyChain = async () => {
    if (!rid) return
    try {
      const r = await strategyV2Api.verifyAudit(rid)
      setVerifyResult(r)
      if (r.status === 'ok') {
        toast.success(`Audit chain verified — ${r.events_verified} events`)
      } else if (r.status === 'tampered') {
        toast.error(`Audit chain BROKEN — first bad event id ${r.first_bad_event_id}`)
      } else {
        toast.error(r.message || 'Verification failed')
      }
    } catch (err) {
      toast.error('Verification request failed')
      console.error(err)
    }
  }

  if (loading || !run) {
    return <div className="container mx-auto p-8">Loading…</div>
  }

  return (
    <div className="container mx-auto p-6 max-w-6xl space-y-6">
      <div>
        <button
          type="button"
          onClick={() => navigate(`/strategy/v2/${sid}/runs`)}
          className="text-sm text-muted-foreground hover:underline"
        >
          ← All runs
        </button>
        <div className="flex items-center gap-3 mt-1">
          <h1 className="text-2xl font-semibold">Run #{run.id}</h1>
          <Badge variant="outline" className={STATE_BADGE[run.state] || ''}>
            {run.state}
          </Badge>
          <Badge variant="outline">
            {run.mode === 'sandbox' ? 'SANDBOX' : 'LIVE'}
          </Badge>
        </div>
      </div>

      <Tabs defaultValue="overview">
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="orders">Orders ({orderbook?.orders.length ?? 0})</TabsTrigger>
          <TabsTrigger value="trades">Trades ({trades.length})</TabsTrigger>
          <TabsTrigger value="positions">Positions ({positions.length})</TabsTrigger>
          <TabsTrigger value="events">Events ({events.length})</TabsTrigger>
        </TabsList>

        {/* Overview ---------------------------------------------------- */}
        <TabsContent value="overview">
          {/* Live MTM card — only shown when the engine is actively
               broadcasting (run is IN_TRADE and ticks are flowing). */}
          {live.pnl && (
            <Card className="mb-4 border-emerald-500/30 bg-emerald-500/5">
              <CardHeader className="pb-2 flex flex-row items-center justify-between">
                <CardTitle className="text-base">Live</CardTitle>
                <span className="text-xs text-muted-foreground">
                  updated {live.pnl.ts_ist}
                </span>
              </CardHeader>
              <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                <Stat
                  label="Aggregate MTM"
                  value={fmtMoney(live.pnl.agg_mtm)}
                  tone={tone(live.pnl.agg_mtm)}
                />
                <Stat
                  label="Peak MTM"
                  value={fmtMoney(live.pnl.peak_mtm)}
                  tone="positive"
                />
                <Stat
                  label="Drawdown from peak"
                  value={fmtMoney(live.pnl.drawdown)}
                  tone="negative"
                />
                <Stat
                  label="Profit Lock"
                  value={live.pnl.profit_locked ? 'Armed' : 'Off'}
                  tone={live.pnl.profit_locked ? 'positive' : 'neutral'}
                />
              </CardContent>
            </Card>
          )}

          {/* Health banner — surfaces market_data_service.is_trade_management_safe.
               Stale/disconnected feed pauses RMS evaluations on the backend. */}
          {live.health && !live.health.feed_safe && (
            <Card className="mb-4 border-rose-500/40 bg-rose-500/10">
              <CardContent className="py-3 text-sm">
                <span className="font-medium text-rose-700">RMS paused</span>
                <span className="text-muted-foreground">
                  {' '}
                  — {live.health.reason || 'feed unsafe'}
                </span>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Run summary</CardTitle>
            </CardHeader>
            <CardContent className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
              <Stat label="Realized P&L" value={fmtMoney(run.realized_pnl)} tone={tone(run.realized_pnl)} />
              <Stat label="Peak MTM" value={fmtMoney(run.peak_mtm)} tone="positive" />
              <Stat label="Max Drawdown" value={fmtMoney(run.max_drawdown)} tone="negative" />
              <Stat label="Profit Locked" value={run.profit_locked ? 'Yes' : 'No'} />
              <Stat label="Triggered" value={run.triggered_at ?? '—'} />
              <Stat label="Entered" value={run.entered_at ?? '—'} />
              <Stat label="Exited" value={run.exited_at ?? '—'} />
              <Stat label="Exit Reason" value={run.exit_reason ?? '—'} />
              <Stat label="Signal Source" value={run.signal_source ?? '—'} />
            </CardContent>
          </Card>
        </TabsContent>

        {/* Orders ------------------------------------------------------ */}
        <TabsContent value="orders">
          <Card>
            <CardHeader>
              <CardTitle>Orders</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {orderbook && (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2">Time</th>
                      <th className="px-4 py-2">Symbol</th>
                      <th className="px-4 py-2">Action</th>
                      <th className="px-4 py-2">Qty</th>
                      <th className="px-4 py-2">Price</th>
                      <th className="px-4 py-2">Type</th>
                      <th className="px-4 py-2">Status</th>
                      <th className="px-4 py-2">Source</th>
                      <th className="px-4 py-2">Order ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {orderbook.orders.map((o, i) => (
                      <tr key={i} className="border-b last:border-b-0">
                        <td className="px-4 py-2 text-xs">{o.timestamp}</td>
                        <td className="px-4 py-2 font-mono text-xs">
                          {o.exchange}:{o.symbol}
                        </td>
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
                        <td className="px-4 py-2">{o.quantity}</td>
                        <td className="px-4 py-2">{o.price}</td>
                        <td className="px-4 py-2">{o.pricetype}</td>
                        <td className="px-4 py-2">
                          <Badge
                            variant="outline"
                            className={ORDER_STATUS_BADGE[o.order_status] || ''}
                          >
                            {o.order_status}
                          </Badge>
                        </td>
                        <td className="px-4 py-2 text-xs text-muted-foreground">{o.source}</td>
                        <td className="px-4 py-2 font-mono text-xs">{o.orderid}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {!orderbook?.orders.length && (
                <div className="p-12 text-center text-muted-foreground text-sm">
                  No orders for this run.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Trades ------------------------------------------------------ */}
        <TabsContent value="trades">
          <Card>
            <CardHeader>
              <CardTitle>Trades (fills)</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {trades.length ? (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2">Time</th>
                      <th className="px-4 py-2">Symbol</th>
                      <th className="px-4 py-2">Action</th>
                      <th className="px-4 py-2 text-right">Qty</th>
                      <th className="px-4 py-2 text-right">Avg Price</th>
                      <th className="px-4 py-2 text-right">Trade Value</th>
                      <th className="px-4 py-2">Order ID</th>
                    </tr>
                  </thead>
                  <tbody>
                    {trades.map((t, i) => (
                      <tr key={i} className="border-b last:border-b-0">
                        <td className="px-4 py-2 text-xs">{t.timestamp}</td>
                        <td className="px-4 py-2 font-mono text-xs">
                          {t.exchange}:{t.symbol}
                        </td>
                        <td className="px-4 py-2">{t.action}</td>
                        <td className="px-4 py-2 text-right">{t.quantity}</td>
                        <td className="px-4 py-2 text-right font-mono">
                          {t.average_price.toFixed(2)}
                        </td>
                        <td className="px-4 py-2 text-right font-mono">
                          {t.trade_value.toFixed(2)}
                        </td>
                        <td className="px-4 py-2 font-mono text-xs">{t.orderid}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <div className="p-12 text-center text-muted-foreground text-sm">
                  No fills recorded yet.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Positions --------------------------------------------------- */}
        <TabsContent value="positions">
          <Card>
            <CardHeader>
              <CardTitle>Positions</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              {positions.length ? (
                <table className="w-full text-sm">
                  <thead className="border-b text-left text-xs uppercase text-muted-foreground">
                    <tr>
                      <th className="px-4 py-2">Symbol</th>
                      <th className="px-4 py-2">State</th>
                      <th className="px-4 py-2 text-right">Net Qty</th>
                      <th className="px-4 py-2 text-right">Avg Entry</th>
                      <th className="px-4 py-2 text-right">LTP</th>
                      <th className="px-4 py-2 text-right">Unrealized</th>
                      <th className="px-4 py-2 text-right">SL · dist</th>
                      <th className="px-4 py-2 text-right">Target · dist</th>
                      <th className="px-4 py-2 text-right">Trail #</th>
                      <th className="px-4 py-2 text-right">Next trail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {positions.map((p) => {
                      const liveLeg = live.legs[p.leg_id]
                      const ltp = liveLeg?.ltp ?? p.ltp_decimal ?? null
                      const unreal = liveLeg?.mtm ?? p.unrealized_pnl
                      const slPrice = liveLeg?.current_sl_price ?? p.current_sl_price
                      const slDist = liveLeg?.sl_distance_pts ?? null
                      const tgtDist = liveLeg?.target_distance_pts ?? null
                      const nextTrail = liveLeg?.next_trail_at_pts ?? null
                      const trailCount =
                        liveLeg?.trail_advances_count ?? p.trail_advances_count
                      const isLive = !!liveLeg
                      return (
                        <tr
                          key={p.leg_id}
                          className={`border-b last:border-b-0 ${isLive ? 'bg-emerald-500/5' : ''}`}
                        >
                          <td className="px-4 py-2 font-mono text-xs">
                            {p.exchange}:{p.symbol}
                          </td>
                          <td className="px-4 py-2 text-xs">{p.leg_state}</td>
                          <td className="px-4 py-2 text-right">{p.net_qty}</td>
                          <td className="px-4 py-2 text-right">
                            {p.avg_entry?.toFixed(2) ?? '—'}
                          </td>
                          <td className="px-4 py-2 text-right font-mono">
                            {ltp != null ? Number(ltp).toFixed(2) : '—'}
                          </td>
                          <td
                            className={`px-4 py-2 text-right font-mono ${
                              unreal >= 0 ? 'text-emerald-700' : 'text-rose-700'
                            }`}
                          >
                            {fmtMoney(unreal)}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-xs">
                            {slPrice?.toFixed(2) ?? '—'}
                            {slDist != null && (
                              <span className="text-muted-foreground">
                                {' · '}
                                {slDist.toFixed(2)}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right font-mono text-xs">
                            {p.current_target_price?.toFixed(2) ?? '—'}
                            {tgtDist != null && (
                              <span className="text-muted-foreground">
                                {' · '}
                                {tgtDist.toFixed(2)}
                              </span>
                            )}
                          </td>
                          <td className="px-4 py-2 text-right">{trailCount}</td>
                          <td className="px-4 py-2 text-right text-xs text-muted-foreground">
                            {nextTrail != null ? nextTrail.toFixed(2) : '—'}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              ) : (
                <div className="p-12 text-center text-muted-foreground text-sm">
                  No positions.
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        {/* Events ------------------------------------------------------ */}
        <TabsContent value="events">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between">
              <CardTitle>Event timeline</CardTitle>
              <Button variant="outline" size="sm" onClick={onVerifyChain}>
                Verify Audit Chain
              </Button>
            </CardHeader>
            <CardContent>
              {verifyResult && (
                <div
                  className={`mb-4 p-3 rounded-md border text-sm ${
                    verifyResult.status === 'ok'
                      ? 'border-emerald-500/40 bg-emerald-500/10'
                      : 'border-rose-500/40 bg-rose-500/10'
                  }`}
                >
                  {verifyResult.status === 'ok' ? (
                    <>Audit chain intact — {verifyResult.events_verified} events.</>
                  ) : verifyResult.status === 'tampered' ? (
                    <>
                      Audit chain BROKEN at event id{' '}
                      <span className="font-mono">{verifyResult.first_bad_event_id}</span>.
                      Stored hash does not match the recomputed hash.
                    </>
                  ) : (
                    <>{verifyResult.message}</>
                  )}
                </div>
              )}
              {events.length ? (
                <ol className="space-y-2">
                  {events.map((e) => (
                    <li
                      key={e.id}
                      className="border rounded-md p-3 flex flex-col gap-1"
                    >
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-2">
                          <Badge variant="outline">{e.type}</Badge>
                          <span className="text-xs text-muted-foreground">
                            {e.ts_ist}
                          </span>
                        </div>
                        <span className="text-xs text-muted-foreground font-mono">
                          #{e.id}
                        </span>
                      </div>
                      {e.payload != null && (
                        <pre className="text-xs bg-muted/50 p-2 rounded font-mono overflow-x-auto">
                          {JSON.stringify(e.payload, null, 2)}
                        </pre>
                      )}
                    </li>
                  ))}
                </ol>
              ) : (
                <div className="p-12 text-center text-muted-foreground text-sm">
                  No audit events.
                </div>
              )}
            </CardContent>
          </Card>
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
  value: string
  tone?: 'positive' | 'negative' | 'neutral'
}) {
  const toneClass =
    tone === 'positive'
      ? 'text-emerald-700'
      : tone === 'negative'
        ? 'text-rose-700'
        : ''
  return (
    <div className="space-y-1">
      <div className="text-xs uppercase text-muted-foreground">{label}</div>
      <div className={`font-mono text-base ${toneClass}`}>{value}</div>
    </div>
  )
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}₹${n.toFixed(2)}`
}

function tone(n: number): 'positive' | 'negative' | 'neutral' {
  if (n > 0) return 'positive'
  if (n < 0) return 'negative'
  return 'neutral'
}
