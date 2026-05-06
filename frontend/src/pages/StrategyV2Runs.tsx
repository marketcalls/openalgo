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
import type { StrategyRun, StrategyV2 } from '@/types/strategy_v2'

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
  const [loading, setLoading] = useState(true)

  const sid = strategyId ? Number(strategyId) : null

  useEffect(() => {
    if (!sid) return
    setLoading(true)
    Promise.all([strategyV2Api.get(sid), strategyV2Api.listRuns(sid)])
      .then(([s, r]) => {
        setStrategy(s.strategy)
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
                  <th className="px-4 py-3 text-right">Realized P&L</th>
                  <th className="px-4 py-3 text-right">Peak</th>
                  <th className="px-4 py-3 text-right">Drawdown</th>
                </tr>
              </thead>
              <tbody>
                {runs.map((r) => (
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
                ))}
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
