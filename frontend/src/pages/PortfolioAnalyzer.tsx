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
import {
  analyseHoldings,
  type HoldingsAnalysis,
  type PriceSource,
} from '@/api/portfolio'
import { CrisisChart } from '@/components/portfolio/CrisisChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'
import { healthGradeTone } from '@/lib/portfolioRequest'

const inr = (v: number) =>
  `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 2, minimumFractionDigits: 2 })}`
const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '-' : `${(v * 100).toFixed(dp)}%`
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '-' : v.toFixed(dp)

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
  const [source, setSource] = useState<PriceSource>('db')
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
        source,
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
            Your live holdings, graded: concentration, co-movement, drawdown
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
          <div>
            <Label className="text-xs">Data source</Label>
            <Select value={source} onValueChange={(v) => setSource(v as PriceSource)}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="db">Historify (local)</SelectItem>
                <SelectItem value="api">Broker API</SelectItem>
              </SelectContent>
            </Select>
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
              value={s.invested === null ? '-' : inr(s.invested)}
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
              value={health?.grade ? `${health.score}/100 (${health.grade})` : '-'}
              sub={health ? `${health.pillars.length} pillars, formulas shown` : undefined}
              tone={healthGradeTone(health?.grade)}
            />
            <Metric
              label="Effective Bets"
              value={
                result.analysis
                  ? String(result.analysis.structure.effective_bets)
                  : '-'
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
                depends on current value, weights, concentration, co-movement,
                health and risk, is unaffected, and the P&amp;L shown is the
                broker's own figure.
              </CardContent>
            </Card>
          )}

          {result.skipped.length > 0 && (
            <Card className="border-amber-500/40">
              <CardContent className="p-4 text-sm">
                <span className="font-medium text-amber-500">Not analysed: </span>
                {result.skipped.join(', ')}, held on an exchange this tool does not
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
                          {h.average_price > 0 ? h.average_price.toFixed(2) : '-'}
                        </td>
                        <td className="p-3 text-right tabular-nums">
                          {h.last_price.toFixed(2)}
                        </td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          {h.invested > 0 ? inr(h.invested) : '-'}
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

          {result.analysis?.asset_returns?.length ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Asset Returns</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Each holding on its own, close to close. A window longer than the
                  available history shows n/a rather than a since-inception figure
                  dressed up as a five-year return.
                </p>
              </CardHeader>
              <CardContent className="p-0">
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">Symbol</th>
                        {(['1W', '1M', '3M', '1Y', '3Y', '5Y'] as const).map((w) => (
                          <th key={w} className="p-3 text-right">
                            {w}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.analysis.asset_returns.map((a) => (
                        <tr key={a.symbol} className="border-b last:border-0">
                          <td className="p-3 font-medium">{a.symbol}</td>
                          {(['1W', '1M', '3M', '1Y', '3Y', '5Y'] as const).map((w) => {
                            const v = a[w]
                            return (
                              <td key={w} className="p-1.5 text-right">
                                {v === null ? (
                                  <span className="text-xs text-muted-foreground">n/a</span>
                                ) : (
                                  <span
                                    className={cn(
                                      'inline-block w-full rounded px-2 py-1 text-right tabular-nums',
                                      v >= 0
                                        ? 'bg-emerald-500/15 text-emerald-400'
                                        : 'bg-rose-500/15 text-rose-400'
                                    )}
                                    style={{
                                      // Stronger colour for a bigger move, so the
                                      // eye lands on what actually moved.
                                      opacity: Math.min(1, 0.45 + Math.abs(v) * 1.2),
                                    }}
                                  >
                                    {v >= 0 ? '+' : ''}
                                    {(v * 100).toFixed(1)}%
                                  </span>
                                )}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ) : null}

          {result.analysis?.correlation?.symbols?.length ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Asset Correlation Matrix</CardTitle>
                <p className="text-sm text-muted-foreground">
                  How each pair moved together over the lookback. Holdings that move
                  as one are a single bet however many names they carry.
                </p>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="border-separate border-spacing-0.5 text-xs">
                    <thead>
                      <tr>
                        <th className="p-2" />
                        {result.analysis.correlation.symbols.map((c) => (
                          <th key={c} className="p-2 font-medium text-muted-foreground">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.analysis.correlation.symbols.map((row, i) => (
                        <tr key={row}>
                          <td className="whitespace-nowrap p-2 font-medium text-muted-foreground">
                            {row}
                          </td>
                          {result.analysis?.correlation.symbols.map((col, j) => {
                            const v = result.analysis?.correlation.matrix[i]?.[j] ?? null
                            return (
                              <td
                                key={col}
                                title={
                                  v === null
                                    ? 'too little overlap to measure'
                                    : `${row} vs ${col}: ${v.toFixed(2)}`
                                }
                                className="min-w-16 rounded p-2 text-center tabular-nums"
                                style={{
                                  background:
                                    v === null
                                      ? 'transparent'
                                      : `rgba(34,197,94,${Math.min(Math.abs(v), 1) * 0.7})`,
                                }}
                              >
                                {v === null ? '-' : v.toFixed(2)}
                              </td>
                            )
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          ) : null}

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
            <>
              {result.analysis.crisis.summary && (
                <div className="grid gap-3 md:grid-cols-3">
                  <Metric
                    label="Crises Covered"
                    value={String(result.analysis.crisis.summary.count)}
                    sub={`inside the ${lookback}-day lookback`}
                  />
                  <Metric
                    label="Beat the Benchmark"
                    value={pct(result.analysis.crisis.summary.hit_rate, 0)}
                    sub="of those periods"
                    tone={
                      (result.analysis.crisis.summary.hit_rate ?? 0) >= 0.5
                        ? 'good'
                        : 'bad'
                    }
                  />
                  <Metric
                    label="Worst Crisis"
                    value={pct(result.analysis.crisis.summary.worst)}
                    tone="bad"
                  />
                </div>
              )}

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">In Past Crises</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    How these same weights would have fared, with the window each one
                    ran over and how long it lasted. Only crises inside the lookback
                    appear, widen it to see more.
                  </p>
                </CardHeader>
                <CardContent>
                  <CrisisChart periods={result.analysis.crisis.periods} />
                </CardContent>
              </Card>
            </>
          ) : null}

          <p className="text-xs text-muted-foreground">{result.meta.basis}</p>
          {result.analysis_error && (
            <Card className="border-amber-500/40">
              <CardContent className="space-y-1 p-4 text-sm">
                <div>
                  <span className="font-medium text-amber-500">
                    Historical analysis unavailable:{' '}
                  </span>
                  {result.analysis_error}
                </div>
                {source === 'db' && (
                  <div className="text-xs text-muted-foreground">
                    A real account usually holds something nobody has ingested.
                    Switch the data source to <strong>Broker API</strong> and run
                    again, slower and rate limited, but it covers every symbol you
                    own. The figures above do not depend on this and are unaffected.
                  </div>
                )}
              </CardContent>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
