/**
 * Portfolio Backtester — build a weighted portfolio, backtest it, read the result.
 *
 * Every tab renders from one response: they are all views of a single
 * simulation, so re-fetching per tab would risk two tabs disagreeing about
 * the same portfolio.
 */
import { useMemo, useState } from 'react'
import {
  type BacktestResponse,
  type PortfolioHolding,
  type PriceSource,
  type RebalanceRule,
  runPortfolioBacktest,
} from '@/api/portfolio'
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
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useAuthStore } from '@/stores/authStore'
import { cn } from '@/lib/utils'

const REBALANCE: { value: RebalanceRule; label: string; note: string }[] = [
  { value: 'never', label: 'Never', note: 'Buy & Hold' },
  { value: 'monthly', label: 'Monthly', note: '12x per year' },
  { value: 'quarterly', label: 'Quarterly', note: '4x per year' },
  { value: 'yearly', label: 'Yearly', note: '1x per year' },
]

const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : `${(v * 100).toFixed(dp)}%`
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '—' : v.toFixed(dp)
const money = (v: number) =>
  `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

function todayISO(offsetYears = 0): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - offsetYears)
  return d.toISOString().slice(0, 10)
}

/** A metric with its benchmark counterpart, the way the tabs present them. */
function Stat({
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

/**
 * Equity curve, drawn as an inline SVG.
 *
 * A chart library would be a heavier dependency than this needs: two series,
 * no interaction beyond a hover readout, and the shape is what matters.
 */
function EquityChart({
  portfolio,
  benchmark,
  height = 300,
}: {
  portfolio: { date: string; value: number }[]
  benchmark: { date: string; value: number }[]
  height?: number
}) {
  const path = (points: { value: number }[], lo: number, hi: number) => {
    if (points.length < 2) return ''
    const span = hi - lo || 1
    return points
      .map((p, i) => {
        const x = (i / (points.length - 1)) * 100
        const y = 100 - ((p.value - lo) / span) * 100
        return `${i === 0 ? 'M' : 'L'}${x.toFixed(3)},${y.toFixed(3)}`
      })
      .join(' ')
  }

  const all = [...portfolio, ...benchmark].map((p) => p.value)
  if (!all.length) return null
  const lo = Math.min(...all)
  const hi = Math.max(...all)

  return (
    <div className="w-full" style={{ height }}>
      <svg
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        className="h-full w-full"
        role="img"
        aria-label="Equity curve"
      >
        <title>Portfolio versus benchmark growth</title>
        {benchmark.length > 1 && (
          <path
            d={path(benchmark, lo, hi)}
            fill="none"
            stroke="#22c55e"
            strokeWidth="0.4"
            vectorEffect="non-scaling-stroke"
          />
        )}
        <path
          d={path(portfolio, lo, hi)}
          fill="none"
          stroke="#3b82f6"
          strokeWidth="0.6"
          vectorEffect="non-scaling-stroke"
        />
      </svg>
      <div className="mt-2 flex justify-between text-xs text-muted-foreground">
        <span>{portfolio[0]?.date}</span>
        <span className="flex gap-4">
          <span className="text-blue-500">■ Portfolio</span>
          {benchmark.length > 1 && <span className="text-emerald-500">■ Benchmark</span>}
        </span>
        <span>{portfolio[portfolio.length - 1]?.date}</span>
      </div>
    </div>
  )
}

/** Correlation heatmap. Null cells are drawn empty rather than as a colour. */
function CorrelationHeatmap({
  symbols,
  matrix,
}: {
  symbols: string[]
  matrix: (number | null)[][]
}) {
  const colour = (v: number | null) => {
    if (v === null) return 'transparent'
    // Diverging: red for together, blue for apart. Alpha carries strength so
    // a near-zero correlation reads as absence rather than as a pale colour.
    const a = Math.min(Math.abs(v), 1) * 0.85
    return v >= 0 ? `rgba(239,68,68,${a})` : `rgba(59,130,246,${a})`
  }

  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="p-1" />
            {symbols.map((s) => (
              <th key={s} className="p-1 text-left font-medium text-muted-foreground">
                {s}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {symbols.map((row, i) => (
            <tr key={row}>
              <td className="whitespace-nowrap p-1 pr-2 font-medium text-muted-foreground">
                {row}
              </td>
              {symbols.map((col, j) => {
                const v = matrix[i]?.[j] ?? null
                return (
                  <td
                    key={col}
                    className="min-w-14 rounded border border-border/40 p-1.5 text-center tabular-nums"
                    style={{ background: colour(v) }}
                    title={v === null ? 'too little overlap to measure' : `${row} vs ${col}`}
                  >
                    {v === null ? '—' : v.toFixed(2)}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export default function PortfolioBacktester() {
  const { apiKey } = useAuthStore()

  const [holdings, setHoldings] = useState<PortfolioHolding[]>([
    { symbol: 'NIFTYBEES', exchange: 'NSE', weight: 60 },
    { symbol: 'GOLDBEES', exchange: 'NSE', weight: 40 },
  ])
  const [benchmark, setBenchmark] = useState('NIFTYBEES')
  const [rebalance, setRebalance] = useState<RebalanceRule>('quarterly')
  const [source, setSource] = useState<PriceSource>('db')
  const [startDate, setStartDate] = useState(todayISO(5))
  const [endDate, setEndDate] = useState(todayISO(0))
  const [costBps, setCostBps] = useState(20)
  const [riskFree, setRiskFree] = useState(0)

  const [result, setResult] = useState<BacktestResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const totalWeight = useMemo(
    () => holdings.reduce((s, h) => s + (Number(h.weight) || 0), 0),
    [holdings]
  )

  const setHolding = (i: number, patch: Partial<PortfolioHolding>) =>
    setHoldings((prev) => prev.map((h, n) => (n === i ? { ...h, ...patch } : h)))

  const distributeEqually = () =>
    setHoldings((prev) =>
      prev.map((h) => ({ ...h, weight: Number((100 / prev.length).toFixed(2)) }))
    )

  const analyse = async () => {
    if (!apiKey) {
      setError('No API key found. Generate one on the API Key page.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const res = await runPortfolioBacktest({
        apikey: apiKey,
        holdings: holdings
          .filter((h) => h.symbol.trim() !== '')
          .map((h) => ({ ...h, symbol: h.symbol.trim().toUpperCase() })),
        start_date: startDate,
        end_date: endDate,
        benchmark: benchmark.trim() || null,
        rebalance,
        cost_bps: costBps,
        risk_free_rate: riskFree / 100,
        source,
      })
      if (res.status !== 'success') throw new Error(res.message || 'backtest failed')
      setResult(res)
    } catch (err: unknown) {
      const e = err as { response?: { data?: { message?: unknown } }; message?: string }
      const msg = e.response?.data?.message ?? e.message ?? 'backtest failed'
      setError(typeof msg === 'string' ? msg : JSON.stringify(msg))
      setResult(null)
    } finally {
      setBusy(false)
    }
  }

  const m = result?.metrics
  const warnings = result ? Object.keys(result.meta.data_warnings ?? {}) : []

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Portfolio Backtester</h1>
        <p className="text-sm text-muted-foreground">
          Build a portfolio, set weights, pick a benchmark, and see how it would have
          performed. Costs and rebalancing are modelled, not assumed away.
        </p>
      </div>

      {/* ── Builder ─────────────────────────────────────────────────── */}
      <div className="grid gap-4 md:grid-cols-3">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Benchmark</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Input
              value={benchmark}
              onChange={(e) => setBenchmark(e.target.value)}
              placeholder="NIFTYBEES"
            />
            <p className="text-xs text-muted-foreground">
              Compared against your portfolio. Leave blank to skip.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Rebalancing</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <Select
              value={rebalance}
              onValueChange={(v) => setRebalance(v as RebalanceRule)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {REBALANCE.map((r) => (
                  <SelectItem key={r.value} value={r.value}>
                    {r.label} <span className="text-muted-foreground">{r.note}</span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-xs text-muted-foreground">
              More often is not better — it costs turnover.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Analysis Period</CardTitle>
          </CardHeader>
          <CardContent className="grid grid-cols-2 gap-2">
            <div>
              <Label className="text-xs">Start</Label>
              <Input
                type="date"
                value={startDate}
                onChange={(e) => setStartDate(e.target.value)}
              />
            </div>
            <div>
              <Label className="text-xs">End</Label>
              <Input
                type="date"
                value={endDate}
                onChange={(e) => setEndDate(e.target.value)}
              />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between space-y-0 pb-3">
          <div>
            <CardTitle className="text-base">Portfolio Holdings</CardTitle>
            <p className="text-sm text-muted-foreground">
              NSE and BSE cash equity and ETFs.
            </p>
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                setHoldings((p) => [...p, { symbol: '', exchange: 'NSE', weight: 0 }])
              }
            >
              Add Stock
            </Button>
            <Button variant="outline" size="sm" onClick={distributeEqually}>
              Distribute Equally
            </Button>
          </div>
        </CardHeader>
        <CardContent className="space-y-2">
          {holdings.map((h, i) => (
            <div key={`row-${i}-${h.symbol}`} className="flex items-center gap-2">
              <Input
                className="flex-1"
                value={h.symbol}
                placeholder="Symbol"
                onChange={(e) => setHolding(i, { symbol: e.target.value.toUpperCase() })}
              />
              <Select
                value={h.exchange}
                onValueChange={(v) => setHolding(i, { exchange: v })}
              >
                <SelectTrigger className="w-24">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="NSE">NSE</SelectItem>
                  <SelectItem value="BSE">BSE</SelectItem>
                </SelectContent>
              </Select>
              <Input
                className="w-28"
                type="number"
                value={h.weight}
                onChange={(e) => setHolding(i, { weight: Number(e.target.value) })}
              />
              <Button
                variant="ghost"
                size="sm"
                disabled={holdings.length <= 1}
                onClick={() => setHoldings((p) => p.filter((_, n) => n !== i))}
              >
                Remove
              </Button>
            </div>
          ))}

          <div className="flex flex-wrap items-end gap-4 border-t pt-3">
            <div>
              <Label className="text-xs">Cost (bps)</Label>
              <Input
                className="w-24"
                type="number"
                value={costBps}
                onChange={(e) => setCostBps(Number(e.target.value))}
              />
            </div>
            <div>
              <Label className="text-xs">Risk-free rate (%)</Label>
              <Input
                className="w-28"
                type="number"
                value={riskFree}
                onChange={(e) => setRiskFree(Number(e.target.value))}
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
            <div className="ml-auto flex items-center gap-3">
              <span
                className={cn(
                  'text-sm tabular-nums',
                  Math.abs(totalWeight - 100) < 0.01
                    ? 'text-emerald-500'
                    : 'text-muted-foreground'
                )}
              >
                Total {totalWeight.toFixed(1)}%
              </span>
              <Button onClick={analyse} disabled={busy}>
                {busy ? 'Analysing…' : 'Analyze Portfolio'}
              </Button>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            Weights are normalised, so they need not total 100.
          </p>
        </CardContent>
      </Card>

      {error && (
        <Card className="border-rose-500/40">
          <CardContent className="p-4 text-sm text-rose-500">{error}</CardContent>
        </Card>
      )}

      {/* ── Results ─────────────────────────────────────────────────── */}
      {result && m && (
        <>
          {warnings.length > 0 && (
            <Card className="border-amber-500/40">
              <CardContent className="p-4 text-sm">
                <span className="font-medium text-amber-500">Check the data: </span>
                {warnings.join(', ')} moved far enough in one session to look like an
                unadjusted split or bonus. Re-ingest that history before trusting these
                numbers.
              </CardContent>
            </Card>
          )}

          <Tabs defaultValue="overview">
            <TabsList>
              <TabsTrigger value="overview">Overview</TabsTrigger>
              <TabsTrigger value="returns">Cumulative Returns</TabsTrigger>
              <TabsTrigger value="stats">Performance Stats</TabsTrigger>
              <TabsTrigger value="pnl">Itemised P&amp;L</TabsTrigger>
              <TabsTrigger value="correlation">Correlation</TabsTrigger>
            </TabsList>

            <TabsContent value="overview" className="space-y-4">
              <div className="grid gap-3 md:grid-cols-4">
                <Stat
                  label="Total Return"
                  value={pct(
                    result.equity.length
                      ? result.equity[result.equity.length - 1].value /
                          result.meta.initial_capital -
                          1
                      : null
                  )}
                  sub={`${result.meta.sessions} sessions`}
                  tone="good"
                />
                <Stat label="CAGR" value={pct(m.cagr)} sub={`benchmark ${pct(m.benchmark_cagr)}`} />
                <Stat label="Max Drawdown" value={pct(m.max_drawdown)} tone="bad" />
                <Stat
                  label="Effective Holdings"
                  value={num(result.diversification.effective_holdings, 1)}
                  sub={`of ${result.diversification.holdings} names`}
                />
              </div>
              <div className="grid gap-3 md:grid-cols-4">
                <Stat label="Sharpe" value={num(m.sharpe)} />
                <Stat label="Sortino" value={num(m.sortino)} />
                <Stat
                  label="Up / Down Capture"
                  value={`${num(m.up_capture)} / ${num(m.down_capture)}`}
                  sub="of the benchmark's moves"
                />
                <Stat
                  label="Cost Drag"
                  value={pct(result.rebalancing.cost_drag)}
                  sub={`${result.rebalancing.count} rebalances`}
                />
              </div>
              <p className="text-xs text-muted-foreground">
                Returns are price-only — broker history excludes dividends, so income
                is not counted here.
              </p>
            </TabsContent>

            <TabsContent value="returns">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Cumulative Returns</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Value of {money(result.meta.initial_capital)} invested on{' '}
                    {result.meta.start}
                  </p>
                </CardHeader>
                <CardContent>
                  <EquityChart
                    portfolio={result.equity}
                    benchmark={result.benchmark_equity}
                  />
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="stats">
              <Card>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">Metric</th>
                        <th className="p-3 text-right">Value</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[
                        ['Annual Return (CAGR)', pct(m.cagr)],
                        ['Annual Volatility', pct(m.volatility)],
                        ['Sharpe Ratio', num(m.sharpe)],
                        ['Sortino Ratio', num(m.sortino)],
                        ['Calmar Ratio', num(m.calmar)],
                        ['Max Drawdown', pct(m.max_drawdown)],
                        ['Win Rate', pct(m.win_rate)],
                        ['Best Day', pct(m.best_day)],
                        ['Worst Day', pct(m.worst_day)],
                        ['Value at Risk', pct(m.value_at_risk)],
                        ['Conditional VaR', pct(m.cvar)],
                        ['Ulcer Index', num(m.ulcer_index)],
                        ['Recovery Factor', num(m.recovery_factor)],
                        ['Tail Ratio', num(m.tail_ratio)],
                        ['Skew', num(m.skew)],
                        ['Kurtosis', num(m.kurtosis)],
                        ['Alpha', num(m.alpha, 4)],
                        ['Beta', num(m.beta)],
                        ['Information Ratio', num(m.information_ratio)],
                        ['Excess CAGR vs benchmark', pct(m.excess_cagr)],
                      ].map(([k, v]) => (
                        <tr key={k} className="border-b last:border-0">
                          <td className="p-3">{k}</td>
                          <td className="p-3 text-right tabular-nums">{v}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="pnl">
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Itemised P&amp;L</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Contribution is each holding's share of the portfolio return, so the
                    column sums to the total. It differs from the holding's own return
                    because of its weight.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="border-b text-xs text-muted-foreground">
                        <tr>
                          <th className="p-3 text-left">Symbol</th>
                          <th className="p-3 text-right">Invested</th>
                          <th className="p-3 text-right">Net P&amp;L</th>
                          <th className="p-3 text-right">Costs</th>
                          <th className="p-3 text-right">Own Return</th>
                          <th className="p-3 text-right">Contribution</th>
                          <th className="p-3 text-right">Weight → Final</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.items.map((it) => (
                          <tr key={it.symbol} className="border-b last:border-0">
                            <td className="p-3 font-medium">{it.symbol}</td>
                            <td className="p-3 text-right tabular-nums">
                              {money(it.invested)}
                            </td>
                            <td
                              className={cn(
                                'p-3 text-right tabular-nums',
                                it.net_pnl >= 0 ? 'text-emerald-500' : 'text-rose-500'
                              )}
                            >
                              {money(it.net_pnl)}
                            </td>
                            <td className="p-3 text-right tabular-nums text-muted-foreground">
                              {money(it.costs)}
                            </td>
                            <td className="p-3 text-right tabular-nums">
                              {pct(it.symbol_return)}
                            </td>
                            <td className="p-3 text-right font-medium tabular-nums">
                              {pct(it.contribution_pct)}
                            </td>
                            <td className="p-3 text-right tabular-nums text-muted-foreground">
                              {pct(it.weight_target, 1)} → {pct(it.weight_final, 1)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </TabsContent>

            <TabsContent value="correlation" className="space-y-4">
              <div className="grid gap-3 md:grid-cols-3">
                <Stat
                  label="Average Correlation"
                  value={num(result.correlation.average_pairwise)}
                  sub="between holdings"
                />
                <Stat
                  label="Diversification Ratio"
                  value={num(result.diversification.diversification_ratio)}
                  sub="1.0 means none at all"
                />
                <Stat
                  label="Largest Weight"
                  value={pct(result.diversification.largest_weight, 1)}
                  sub={`HHI ${num(result.diversification.hhi, 3)}`}
                />
              </div>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Correlation Heatmap</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Red moves together, blue moves apart. Holdings that all move
                    together are one bet wearing several names.
                  </p>
                </CardHeader>
                <CardContent>
                  <CorrelationHeatmap
                    symbols={result.correlation.symbols}
                    matrix={result.correlation.matrix}
                  />
                </CardContent>
              </Card>
            </TabsContent>
          </Tabs>
        </>
      )}
    </div>
  )
}
