/**
 * Portfolio Analyzer — the account you actually hold, not one you typed in.
 *
 * The backtester answers "what would this allocation have done". This answers
 * "what am I holding, and is it any good": live weights from the broker, then
 * the same health, risk and crisis analysis run over them.
 *
 * The distinction the page has to keep making is that historical figures
 * describe *today's* holdings run over past prices, not the account's own
 * performance — the broker says what is held now, never when it was bought.
 * Stated plainly rather than left for the reader to assume the stronger claim.
 */
import { useState } from 'react'
import { analyseHoldings, type HoldingsAnalysis } from '@/api/portfolio'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

const inr = (v: number) =>
  `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(dp)}%`
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : v.toFixed(dp)

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub?: string
  tone?: 'good' | 'bad'
}) {
  return (
    <Card>
      <CardContent className="p-4">
        <div className="text-xs font-medium text-muted-foreground">{label}</div>
        <div
          className={cn(
            'mt-1 text-2xl font-semibold tabular-nums',
            tone === 'good' && 'text-emerald-500',
            tone === 'bad' && 'text-rose-500'
          )}
        >
          {value}
        </div>
        {sub && <div className="mt-0.5 text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  )
}

export default function PortfolioAnalyzer() {
  const { apiKey } = useAuthStore()
  const [lookback, setLookback] = useState(365)
  const [result, setResult] = useState<HoldingsAnalysis | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = async () => {
    if (!apiKey) {
      setError('No API key found. Generate one on the API Key page.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await analyseHoldings({
        apikey: apiKey,
        lookback_days: lookback,
        benchmark: 'NIFTY',
        source: 'db',
      })
      if (res.status !== 'success') throw new Error(res.message || 'analysis failed')
      setResult(res)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: unknown } }; message?: string }
      const msg = e.response?.data?.message ?? e.message ?? 'analysis failed'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const s = result?.summary
  const health = result?.analysis?.health
  const m = result?.analysis?.metrics

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Portfolio Analyzer</h1>
          <p className="text-sm text-muted-foreground">
            Your live holdings, graded — concentration, co-movement, drawdown
            resilience and how they behaved in past crises.
          </p>
        </div>
        <div className="flex items-end gap-3">
          <div>
            <Label className="text-xs">Lookback (days)</Label>
            <Input
              className="w-28"
              type="number"
              value={lookback}
              onChange={(e) => setLookback(Number(e.target.value))}
            />
          </div>
          <Button onClick={run} disabled={busy}>
            {busy ? 'Analysing…' : 'Analyse Holdings'}
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-rose-500/40">
          <CardContent className="p-4 text-sm text-rose-500">{error}</CardContent>
        </Card>
      )}

      {result && s && (
        <>
          <div className="grid gap-3 md:grid-cols-5">
            <Metric
              label="Worth Today"
              value={inr(s.current)}
              sub={`${s.count} holdings`}
            />
            <Metric
              label="Invested"
              value={s.invested === null ? '—' : inr(s.invested)}
              sub={s.invested === null ? 'broker reports no average price' : undefined}
            />
            <Metric
              label="Total P&L"
              value={inr(s.pnl)}
              sub={
                s.pnl_pct === null
                  ? 'percent needs a cost basis'
                  : `${s.pnl_pct.toFixed(2)}%`
              }
              tone={s.pnl >= 0 ? 'good' : 'bad'}
            />
            <Metric
              label="Health"
              value={health?.grade ? `${health.score}/100 (${health.grade})` : '—'}
              sub={health ? `${health.pillars.length} pillars, formulas shown` : undefined}
              tone={(health?.score ?? 0) >= 60 ? 'good' : 'bad'}
            />
            <Metric
              label="Effective Bets"
              value={
                result.analysis
                  ? String(result.analysis.structure.effective_bets)
                  : '—'
              }
              sub={`from ${s.count} names`}
            />
          </div>

          {s.has_cost_basis === false && (
            <Card className="border-amber-500/40">
              <CardContent className="p-4 text-sm">
                <span className="font-medium text-amber-500">No cost basis: </span>
                your broker returns holdings without an average price, so invested
                value and return percentages cannot be computed. Everything that
                depends on current value — weights, concentration, co-movement,
                health and risk — is unaffected, and the P&amp;L shown is the
                broker's own figure.
              </CardContent>
            </Card>
          )}

          {result.skipped.length > 0 && (
            <Card className="border-amber-500/40">
              <CardContent className="p-4 text-sm">
                <span className="font-medium text-amber-500">Not analysed: </span>
                {result.skipped.join(', ')} — held on an exchange this tool does not
                price. They are listed below but excluded from the figures above.
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Holdings</CardTitle>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="p-3 text-left">Symbol</th>
                      <th className="p-3 text-right">Weight</th>
                      <th className="p-3 text-right">Qty</th>
                      <th className="p-3 text-right">Avg</th>
                      <th className="p-3 text-right">Live</th>
                      <th className="p-3 text-right">Invested</th>
                      <th className="p-3 text-right">Current</th>
                      <th className="p-3 text-right">P&amp;L</th>
                    </tr>
                  </thead>
                  <tbody>
                    {s.holdings.map((h) => (
                      <tr key={`${h.symbol}-${h.exchange}`} className="border-b last:border-0">
                        <td className="p-3">
                          <div className="font-medium">{h.symbol}</div>
                          <div className="text-xs text-muted-foreground">
                            {h.exchange}
                            {h.product ? ` · ${h.product}` : ''}
                          </div>
                        </td>
                        <td className="p-3 text-right">
                          <span
                            className={cn(
                              'rounded px-1.5 py-0.5 text-xs tabular-nums',
                              h.weight > 0.3
                                ? 'bg-amber-500/15 text-amber-500'
                                : 'text-muted-foreground'
                            )}
                          >
                            {pct(h.weight, 1)}
                          </span>
                        </td>
                        <td className="p-3 text-right tabular-nums">{h.quantity}</td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          {h.average_price > 0 ? h.average_price.toFixed(2) : '—'}
                        </td>
                        <td className="p-3 text-right tabular-nums">
                          {h.last_price.toFixed(2)}
                        </td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          {h.invested > 0 ? inr(h.invested) : '—'}
                        </td>
                        <td className="p-3 text-right tabular-nums">{inr(h.current)}</td>
                        <td
                          className={cn(
                            'p-3 text-right tabular-nums',
                            h.pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          )}
                        >
                          {inr(h.pnl)}
                          {h.pnl_pct !== null && (
                            <div className="text-xs">{h.pnl_pct.toFixed(2)}%</div>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          {m && (
            <div className="grid gap-3 md:grid-cols-5">
              <Metric label="CAGR" value={pct(m.cagr)} sub={`over ${lookback} days`} />
              <Metric label="Volatility" value={pct(m.volatility)} />
              <Metric label="Sharpe" value={num(m.sharpe)} />
              <Metric label="Max Drawdown" value={pct(m.max_drawdown)} tone="bad" />
              <Metric label="Value at Risk" value={pct(m.value_at_risk)} />
            </div>
          )}

          {health && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Health Breakdown</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Every pillar shows its inputs and formula, so the grade can be argued
                  with rather than merely believed.
                </p>
              </CardHeader>
              <CardContent className="space-y-2">
                {health.pillars.map((p) => (
                  <div key={p.key} className="rounded-md border p-3">
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium">{p.label}</span>
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {p.score === null ? 'not measured' : `${p.score}/100`}
                      </span>
                    </div>
                    {p.score !== null && (
                      <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-muted">
                        <div
                          className={cn(
                            'h-full rounded',
                            p.score >= 70
                              ? 'bg-emerald-500'
                              : p.score >= 40
                                ? 'bg-amber-500'
                                : 'bg-rose-500'
                          )}
                          style={{ width: `${p.score}%` }}
                        />
                      </div>
                    )}
                    <p className="mt-2 text-sm">{p.comment}</p>
                    <p className="mt-1 text-xs text-muted-foreground">{p.formula}</p>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          {result.analysis?.crisis?.periods?.length ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">In Past Crises</CardTitle>
                <p className="text-sm text-muted-foreground">
                  How these same weights would have fared. Only windows inside the
                  lookback appear — widen it to see more.
                </p>
              </CardHeader>
              <CardContent className="p-0">
                <table className="w-full text-sm">
                  <tbody>
                    {result.analysis.crisis.periods.map((c) => (
                      <tr key={c.key} className="border-b last:border-0">
                        <td className="p-3">{c.label}</td>
                        <td
                          className={cn(
                            'p-3 text-right tabular-nums',
                            (c.portfolio ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          )}
                        >
                          {pct(c.portfolio)}
                        </td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          benchmark {pct(c.benchmark)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          ) : null}

          <p className="text-xs text-muted-foreground">{result.meta.basis}</p>
          {result.analysis_error && (
            <p className="text-xs text-amber-500">
              Historical analysis unavailable: {result.analysis_error}
            </p>
          )}
        </>
      )}
    </div>
  )
}
