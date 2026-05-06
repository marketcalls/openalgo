/**
 * Strategy v2 — runs list for a single strategy.
 *
 * Each row links to the run detail page with tabbed orderbook/tradebook/
 * positionbook/events views.
 *
 * URL: /strategy/v2/:strategyId/runs
 */
import { useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import { strategyV2Api } from '@/api/strategy_v2'
import { useStrategyV2Socket } from '@/hooks/useStrategyV2Socket'
import type { StrategyLeg, StrategyRun, StrategyV2 } from '@/types/strategy_v2'

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
                  // Live MTM from Socket.IO arrives only for the run that
                  // matches `live.pnl.run_id` (engine subscribes per active
                  // run). Closed runs show '—'; the active run shows the
                  // real-time aggregate. Falls back to the persisted peak
                  // until the first tick arrives.
                  const liveForThisRun =
                    live.pnl && live.pnl.run_id === r.id ? live.pnl : null
                  const liveMtm = liveForThisRun
                    ? liveForThisRun.agg_mtm
                    : null
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
    </div>
  )
}

function fmtMoney(n: number): string {
  if (!Number.isFinite(n)) return '—'
  const sign = n > 0 ? '+' : ''
  return `${sign}₹${n.toFixed(2)}`
}
