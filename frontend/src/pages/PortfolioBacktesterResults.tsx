/**
 * Portfolio Backtester report — a dedicated page for the result of one run.
 *
 * Kept off the builder page so a long report does not sit permanently below
 * the form: the result lives in usePortfolioBacktestStore, set by the builder
 * right before it navigates here.
 */
import { useState } from 'react'
import { useNavigate } from 'react-router'
import { downloadTearsheet } from '@/api/portfolio'
import { AllocationChart } from '@/components/portfolio/AllocationChart'
import { CrisisChart } from '@/components/portfolio/CrisisChart'
import { EoyChart } from '@/components/portfolio/EoyChart'
import { MetricGuide } from '@/components/portfolio/MetricGuide'
import { MonthlyReturnsHeatmap } from '@/components/portfolio/MonthlyReturnsHeatmap'
import { WeeklyReturnsHeatmap } from '@/components/portfolio/WeeklyReturnsHeatmap'
import { PortfolioLineChart } from '@/components/portfolio/PortfolioLineChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'
import { healthGradeTone } from '@/lib/portfolioRequest'
import { usePortfolioBacktestStore } from '@/stores/portfolioBacktestStore'

const pct = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '-' : `${(v * 100).toFixed(dp)}%`
const num = (v: number | null | undefined, dp = 2) =>
  v === null || v === undefined ? '-' : v.toFixed(dp)
const money = (v: number) =>
  `₹${v.toLocaleString('en-IN', { maximumFractionDigits: 0 })}`

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
                    {v === null ? '-' : v.toFixed(2)}
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

export default function PortfolioBacktesterResults() {
  const navigate = useNavigate()
  const { result, request } = usePortfolioBacktestStore()
  const [exporting, setExporting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!result || !result.metrics) {
    return (
      <div className="container mx-auto space-y-4 p-4">
        <Card>
          <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
            <p className="text-sm text-muted-foreground">
              No backtest result to show. Run a backtest first.
            </p>
            <Button onClick={() => navigate('/portfolio-backtester')}>
              Go to Portfolio Backtester
            </Button>
          </CardContent>
        </Card>
      </div>
    )
  }

  const m = result.metrics
  const warnings = Object.keys(result.meta.data_warnings ?? {})

  const exportTearsheet = async () => {
    if (!request) return
    setExporting(true)
    setError(null)
    try {
      await downloadTearsheet(request)
    } catch (err: unknown) {
      const e = err as { message?: string }
      setError(e.message ?? 'tearsheet export failed')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Backtest Report</h1>
          <p className="text-sm text-muted-foreground">
            {result.meta.start} to {result.meta.end}
            {result.meta.benchmark ? ` · benchmark ${result.meta.benchmark}` : ''}
          </p>
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={exportTearsheet}
            disabled={exporting || !request}
            title="Full openstatz tearsheet as a self-contained HTML file"
          >
            {exporting ? 'Building…' : 'Tearsheet'}
          </Button>
          <Button variant="outline" onClick={() => navigate('/portfolio-backtester')}>
            Back to Builder
          </Button>
        </div>
      </div>

      {error && (
        <Card className="border-rose-500/40">
          <CardContent className="p-4 text-sm text-rose-500">{error}</CardContent>
        </Card>
      )}

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
          <TabsTrigger value="drawdown">Drawdown</TabsTrigger>
          <TabsTrigger value="periodreturns">Returns</TabsTrigger>
          <TabsTrigger value="rolling">Rolling Stats</TabsTrigger>
          <TabsTrigger value="compare">Compare</TabsTrigger>
          <TabsTrigger value="robustness">Robustness</TabsTrigger>
          <TabsTrigger value="allocation">Allocation</TabsTrigger>
          <TabsTrigger value="structure">Structure</TabsTrigger>
          <TabsTrigger value="attribution">Attribution</TabsTrigger>
          <TabsTrigger value="crisis">Crisis</TabsTrigger>
          <TabsTrigger value="health">Health</TabsTrigger>
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
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">What the trading cost</CardTitle>
              <p className="text-sm text-muted-foreground">
                The real schedule, itemised. Note which line dominates, it is
                not brokerage, which is why zero-brokerage does not make
                rebalancing free.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <tbody>
                  {[
                    ['Brokerage', result.costs.brokerage],
                    ['STT', result.costs.stt],
                    ['Exchange txn charge', result.costs.exchange_txn],
                    ['GST', result.costs.gst],
                    ['SEBI charges', result.costs.sebi],
                    ['Stamp duty', result.costs.stamp_duty],
                    ['Slippage', result.costs.slippage],
                  ]
                    .filter(([, v]) => v !== undefined)
                    .map(([k, v]) => (
                      <tr key={k as string} className="border-b">
                        <td className="p-2.5 pl-4">{k}</td>
                        <td className="p-2.5 pr-4 text-right tabular-nums">
                          {money(v as number)}
                        </td>
                      </tr>
                    ))}
                  <tr className="font-semibold">
                    <td className="p-2.5 pl-4">Total tax and charges</td>
                    <td className="p-2.5 pr-4 text-right tabular-nums">
                      {money(result.costs.total)}
                    </td>
                  </tr>
                  <tr className="text-muted-foreground">
                    <td className="p-2.5 pl-4">
                      Return given up ({(result.costs.turnover * 100).toFixed(1)}%
                      turnover)
                    </td>
                    <td className="p-2.5 pr-4 text-right tabular-nums">
                      {pct(result.costs.drag)}
                    </td>
                  </tr>
                </tbody>
              </table>
            </CardContent>
          </Card>
          <p className="text-xs text-muted-foreground">
            Returns are price-only: broker history excludes dividends, so income
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
              <PortfolioLineChart
                height={340}
                format={money}
                series={[
                  { name: 'Portfolio', color: '#3b82f6', data: result.equity },
                  ...(result.benchmark_equity.length > 1
                    ? [
                        {
                          name: result.meta.benchmark ?? 'Benchmark',
                          color: '#22c55e',
                          data: result.benchmark_equity,
                        },
                      ]
                    : []),
                ]}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="stats" className="space-y-4">
          <div>
            <h3 className="text-base font-semibold">Understanding your results</h3>
            <p className="text-sm text-muted-foreground">
              What each number means, what good looks like, and where this
              portfolio landed.
            </p>
          </div>
          <MetricGuide metrics={m as unknown as Record<string, number | null>} />
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

        <TabsContent value="drawdown" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Drawdown</CardTitle>
              <p className="text-sm text-muted-foreground">
                How far below the previous peak, and for how long. The shape
                matters more than the worst number.
              </p>
            </CardHeader>
            <CardContent>
              <PortfolioLineChart
                height={260}
                format={(v) => `${v.toFixed(2)}%`}
                series={[
                  {
                    name: 'Drawdown',
                    color: '#ef4444',
                    data: result.series.drawdown,
                    area: true,
                  },
                ]}
              />
            </CardContent>
          </Card>
          {result.series.drawdown_episodes &&
            result.series.drawdown_episodes.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Worst Episodes</CardTitle>
                </CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">Start</th>
                        <th className="p-3 text-left">Valley</th>
                        <th className="p-3 text-left">Recovered</th>
                        <th className="p-3 text-right">Days</th>
                        <th className="p-3 text-right">Depth</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.series.drawdown_episodes.map((d) => (
                        <tr
                          key={`${d.start}-${d.valley}`}
                          className="border-b last:border-0"
                        >
                          <td className="p-3">{d.start}</td>
                          <td className="p-3">{d.valley}</td>
                          <td className="p-3">{d.end}</td>
                          <td className="p-3 text-right tabular-nums">{d.days}</td>
                          <td className="p-3 text-right tabular-nums text-rose-500">
                            {pct(d.depth)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            )}
        </TabsContent>

        <TabsContent value="periodreturns" className="space-y-4">
          {result.series.yearly_returns &&
            result.series.yearly_returns.length > 0 && (
              <>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">
                    EOY Returns vs Benchmark
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    One pair of bars per calendar year. The dashed red line is the
                    portfolio's own average year. A run of ordinary years beside
                    one spectacular one should read as exactly that.
                  </p>
                </CardHeader>
                <CardContent>
                  <EoyChart
                    rows={result.series.yearly_returns}
                    benchmarkLabel={result.meta.benchmark ?? 'Benchmark'}
                    height={300}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Yearly Returns</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    An investor lives through calendar years, not annualised
                    averages, "did it beat the index this year" is the question
                    actually asked of a portfolio.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">Year</th>
                        <th className="p-3 text-right">Portfolio</th>
                        <th className="p-3 text-right">Benchmark</th>
                        <th className="p-3 text-right">Difference</th>
                        <th className="p-3 text-right">Multiplier</th>
                        <th className="p-3 text-center">Won</th>
                      </tr>
                    </thead>
                    <tbody>
                      {result.series.yearly_returns.map((y) => (
                        <tr key={y.year} className="border-b last:border-0">
                          <td className="p-3 font-medium">{y.year}</td>
                          <td
                            className={cn(
                              'p-3 text-right tabular-nums',
                              (y.portfolio ?? 0) >= 0
                                ? 'text-emerald-500'
                                : 'text-rose-500'
                            )}
                          >
                            {pct(y.portfolio)}
                          </td>
                          <td className="p-3 text-right tabular-nums text-muted-foreground">
                            {pct(y.benchmark)}
                          </td>
                          <td
                            className={cn(
                              'p-3 text-right font-medium tabular-nums',
                              (y.difference ?? 0) >= 0
                                ? 'text-emerald-500'
                                : 'text-rose-500'
                            )}
                          >
                            {y.difference === null || y.difference === undefined
                              ? '-'
                              : `${y.difference >= 0 ? '+' : ''}${(y.difference * 100).toFixed(2)}%`}
                          </td>
                          <td className="p-3 text-right tabular-nums text-muted-foreground">
                            {y.multiplier === null || y.multiplier === undefined
                              ? '-'
                              : `${y.multiplier.toFixed(2)}x`}
                          </td>
                          <td
                            className={cn(
                              'p-3 text-center font-semibold',
                              y.won ? 'text-emerald-500' : 'text-rose-500'
                            )}
                          >
                            {y.won === undefined ? '' : y.won ? '+' : '-'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
              </>
            )}
          {result.series.monthly_returns && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Monthly Returns</CardTitle>
                <p className="text-sm text-muted-foreground">
                  A run of bad months is what makes people abandon a strategy, and
                  an annualised number cannot show one.
                </p>
              </CardHeader>
              <CardContent>
                <MonthlyReturnsHeatmap
                  years={result.series.monthly_returns.years}
                  columns={result.series.monthly_returns.columns}
                  values={result.series.monthly_returns.values}
                />
              </CardContent>
            </Card>
          )}
          {result.series.weekly_returns.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">Weekly Returns</CardTitle>
                <p className="text-sm text-muted-foreground">
                  Select a year to see every week.
                </p>
              </CardHeader>
              <CardContent>
                <WeeklyReturnsHeatmap series={result.series.weekly_returns} />
              </CardContent>
            </Card>
          )}
          {result.series.seasonality && (
            <div className="grid gap-3 md:grid-cols-3 lg:grid-cols-6">
              <Stat
                label="Best Month"
                value={pct(result.series.seasonality.best_month)}
                tone="good"
              />
              <Stat
                label="Worst Month"
                value={pct(result.series.seasonality.worst_month)}
                tone="bad"
              />
              <Stat
                label="Avg Up Month"
                value={pct(result.series.seasonality.avg_up_month)}
                tone="good"
              />
              <Stat
                label="Avg Down Month"
                value={pct(result.series.seasonality.avg_down_month)}
                tone="bad"
              />
              <Stat
                label="Win Months"
                value={pct(result.series.seasonality.win_months, 0)}
              />
              <Stat
                label="Win Quarters"
                value={pct(result.series.seasonality.win_quarters, 0)}
              />
            </div>
          )}
          {result.series.return_quantiles &&
            result.series.return_quantiles.length > 0 && (
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Return Quantiles</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    How the spread narrows with holding period. The share of
                    periods that ended down is the practical read.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="overflow-x-auto">
                    <table className="w-full text-sm">
                      <thead className="border-b text-xs text-muted-foreground">
                        <tr>
                          <th className="p-3 text-left">Period</th>
                          <th className="p-3 text-right">n</th>
                          <th className="p-3 text-right">Worst</th>
                          <th className="p-3 text-right">25%</th>
                          <th className="p-3 text-right">Median</th>
                          <th className="p-3 text-right">75%</th>
                          <th className="p-3 text-right">Best</th>
                          <th className="p-3 text-right">Ended down</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.series.return_quantiles.map((q) => (
                          <tr key={q.period} className="border-b last:border-0">
                            <td className="p-3 font-medium">{q.period}</td>
                            <td className="p-3 text-right tabular-nums text-muted-foreground">
                              {q.count}
                            </td>
                            <td className="p-3 text-right tabular-nums text-rose-500">
                              {pct(q.min)}
                            </td>
                            <td className="p-3 text-right tabular-nums">{pct(q.q1)}</td>
                            <td className="p-3 text-right font-medium tabular-nums">
                              {pct(q.median)}
                            </td>
                            <td className="p-3 text-right tabular-nums">{pct(q.q3)}</td>
                            <td className="p-3 text-right tabular-nums text-emerald-500">
                              {pct(q.max)}
                            </td>
                            <td className="p-3 text-right tabular-nums">
                              {pct(q.negative_share, 0)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            )}
        </TabsContent>

        <TabsContent value="rolling" className="space-y-4">
          {result.series.rolling ? (
            <>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">
                    Rolling Sharpe ({result.series.rolling.window} sessions)
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">
                    A flattering full-period Sharpe can hide one that has been
                    deteriorating for a year.
                  </p>
                </CardHeader>
                <CardContent>
                  <PortfolioLineChart
                    height={240}
                    format={(v) => v.toFixed(2)}
                    series={[
                      {
                        name: 'Rolling Sharpe',
                        color: '#8b5cf6',
                        data: result.series.rolling.sharpe,
                      },
                    ]}
                  />
                </CardContent>
              </Card>
              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Rolling Volatility</CardTitle>
                </CardHeader>
                <CardContent>
                  <PortfolioLineChart
                    height={240}
                    format={(v) => `${(v * 100).toFixed(1)}%`}
                    series={[
                      {
                        name: 'Rolling Volatility',
                        color: '#f59e0b',
                        data: result.series.rolling.volatility,
                      },
                    ]}
                  />
                </CardContent>
              </Card>
            </>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                Not enough history for a rolling window over this period.
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="compare" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-2">
            <Stat
              label="Best Risk-Adjusted"
              value={result.rebalancing_sweep.best_by_sharpe ?? '-'}
              sub="highest Sharpe"
              tone="good"
            />
            <Stat
              label="Highest Return"
              value={result.rebalancing_sweep.best_by_return ?? '-'}
              sub="often not the same thing"
            />
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Rebalancing Comparison</CardTitle>
              <p className="text-sm text-muted-foreground">
                The same holdings under every rule. Trading more is not better -
                watch the cost drag column against what the extra trades bought.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="p-3 text-left">Rule</th>
                      <th className="p-3 text-right">Total</th>
                      <th className="p-3 text-right">CAGR</th>
                      <th className="p-3 text-right">Sharpe</th>
                      <th className="p-3 text-right">Max DD</th>
                      <th className="p-3 text-right">Cost drag</th>
                      <th className="p-3 text-right">Turnover</th>
                      <th className="p-3 text-right">Rebalances</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.rebalancing_sweep.variants.map((v) => {
                      const bestSharpe = v.label === result.rebalancing_sweep.best_by_sharpe
                      return (
                        <tr
                          key={v.label}
                          className={cn(
                            'border-b last:border-0',
                            bestSharpe && 'bg-emerald-500/5'
                          )}
                        >
                          <td className="p-3 font-medium">
                            {v.label}
                            {bestSharpe && (
                              <span className="ml-2 text-xs text-emerald-500">best</span>
                            )}
                          </td>
                          <td className="p-3 text-right tabular-nums">
                            {pct(v.total_return)}
                          </td>
                          <td className="p-3 text-right tabular-nums">{pct(v.cagr)}</td>
                          <td className="p-3 text-right font-medium tabular-nums">
                            {num(v.sharpe)}
                          </td>
                          <td className="p-3 text-right tabular-nums text-rose-500">
                            {pct(v.max_drawdown)}
                          </td>
                          <td className="p-3 text-right tabular-nums text-amber-500">
                            {pct(v.cost_drag, 3)}
                          </td>
                          <td className="p-3 text-right tabular-nums text-muted-foreground">
                            {pct(v.turnover, 0)}
                          </td>
                          <td className="p-3 text-right tabular-nums text-muted-foreground">
                            {v.rebalances}
                          </td>
                        </tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Equity Curves</CardTitle>
              <p className="text-sm text-muted-foreground">
                On one axis, because the difference between two schedules is
                usually invisible in their headline returns.
              </p>
            </CardHeader>
            <CardContent>
              <PortfolioLineChart
                height={320}
                format={money}
                series={Object.entries(result.rebalancing_sweep.curves).map(
                  ([label, data], i) => ({
                    name: label,
                    color: ['#3b82f6', '#22c55e', '#f59e0b', '#a855f7', '#ef4444'][i % 5],
                    data,
                  })
                )}
              />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="robustness" className="space-y-4">
          <p className="text-sm text-muted-foreground">
            A single backtest answers “what happened”. These answer whether it
            would have held on windows you did not pick, and how much was luck.
          </p>

          {result.walk_forward.summary ? (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <Stat
                  label="Windows Positive"
                  value={pct(result.walk_forward.summary.positive_share, 0)}
                  sub={`of ${result.walk_forward.summary.count} rolling windows`}
                  tone={
                    result.walk_forward.summary.positive_share > 0.7 ? 'good' : undefined
                  }
                />
                <Stat
                  label="Median Window"
                  value={pct(result.walk_forward.summary.median)}
                  sub={`${result.walk_forward.summary.window_years}y windows`}
                />
                <Stat label="Best" value={pct(result.walk_forward.summary.best)} tone="good" />
                <Stat label="Worst" value={pct(result.walk_forward.summary.worst)} tone="bad" />
              </div>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Walk-Forward Windows</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    The spread is the point, not the average. A strategy whose whole
                    result came from one exceptional stretch looks very different
                    here from one that worked repeatedly.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <div className="max-h-80 overflow-y-auto">
                    <table className="w-full text-sm">
                      <thead className="sticky top-0 border-b bg-card text-xs text-muted-foreground">
                        <tr>
                          <th className="p-3 text-left">Window</th>
                          <th className="p-3 text-right">Return</th>
                          <th className="p-3 text-right">CAGR</th>
                          <th className="p-3 text-right">Max DD</th>
                        </tr>
                      </thead>
                      <tbody>
                        {result.walk_forward.windows.map((w) => (
                          <tr key={w.start} className="border-b last:border-0">
                            <td className="p-3 text-xs text-muted-foreground">
                              {w.start} → {w.end}
                            </td>
                            <td
                              className={cn(
                                'p-3 text-right tabular-nums',
                                w.total_return >= 0 ? 'text-emerald-500' : 'text-rose-500'
                              )}
                            >
                              {pct(w.total_return)}
                            </td>
                            <td className="p-3 text-right tabular-nums">{pct(w.cagr)}</td>
                            <td className="p-3 text-right tabular-nums text-rose-500">
                              {pct(w.max_drawdown)}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </CardContent>
              </Card>
            </>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                {result.walk_forward.note ?? 'Not enough history for walk-forward.'}
              </CardContent>
            </Card>
          )}

          {result.monte_carlo.paths > 0 && result.monte_carlo.cagr ? (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-base">
                  Monte Carlo, {result.monte_carlo.paths.toLocaleString()} paths
                </CardTitle>
                <p className="text-sm text-muted-foreground">
                  Block bootstrap, not independent days: drawing single days
                  destroys volatility clustering and makes drawdowns look far
                  milder than markets produce. Seeded, so the risk numbers do not
                  change each time you look at them.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <div className="grid gap-3 md:grid-cols-3">
                  <Stat
                    label="Probability of Loss"
                    value={pct(result.monte_carlo.probability_of_loss, 1)}
                    sub="of resampled paths ended down"
                  />
                  <Stat
                    label="Median CAGR"
                    value={pct(result.monte_carlo.cagr.median)}
                    sub={`5th-95th: ${pct(result.monte_carlo.cagr.p05)} to ${pct(result.monte_carlo.cagr.p95)}`}
                  />
                  <Stat
                    label="Worst Drawdown Seen"
                    value={pct(result.monte_carlo.worst_drawdown_seen)}
                    sub="across all paths"
                    tone="bad"
                  />
                </div>

                <table className="w-full text-sm">
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="p-3 text-left">Outcome</th>
                      <th className="p-3 text-right">5%</th>
                      <th className="p-3 text-right">25%</th>
                      <th className="p-3 text-right">Median</th>
                      <th className="p-3 text-right">75%</th>
                      <th className="p-3 text-right">95%</th>
                    </tr>
                  </thead>
                  <tbody>
                    {(
                      [
                        { label: 'Total return', band: result.monte_carlo.total_return },
                        { label: 'CAGR', band: result.monte_carlo.cagr },
                        { label: 'Max drawdown', band: result.monte_carlo.max_drawdown },
                      ] as const
                    ).map(({ label, band }) =>
                      band ? (
                        <tr key={label} className="border-b last:border-0">
                          <td className="p-3">{label}</td>
                          {(['p05', 'p25', 'median', 'p75', 'p95'] as const).map((k) => (
                            <td key={k} className="p-3 text-right tabular-nums">
                              {pct(band[k])}
                            </td>
                          ))}
                        </tr>
                      ) : null
                    )}
                  </tbody>
                </table>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                {result.monte_carlo.note ?? 'Not enough history for Monte Carlo.'}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="allocation" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">
                Portfolio Allocation Over Time
              </CardTitle>
              <p className="text-sm text-muted-foreground">
                What you actually held, session by session. Bands widen as winners
                run and snap back on each rebalance. A portfolio left alone stops
                being the one you chose.
              </p>
            </CardHeader>
            <CardContent className="pl-12">
              <AllocationChart
                dates={result.allocation.dates}
                symbols={result.allocation.symbols}
                series={result.allocation.series}
                average={result.allocation.average}
                height={320}
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Target versus Realised</CardTitle>
              <p className="text-sm text-muted-foreground">
                The average weight actually held differs from the target whenever
                the portfolio was allowed to drift.
              </p>
            </CardHeader>
            <CardContent className="p-0">
              <table className="w-full text-sm">
                <thead className="border-b text-xs text-muted-foreground">
                  <tr>
                    <th className="p-3 text-left">Symbol</th>
                    <th className="p-3 text-right">Target</th>
                    <th className="p-3 text-right">Average held</th>
                    <th className="p-3 text-right">Final</th>
                    <th className="p-3 text-right">Drift</th>
                  </tr>
                </thead>
                <tbody>
                  {result.items.map((it) => {
                    const avg = result.allocation.average[it.symbol] ?? 0
                    return (
                      <tr key={it.symbol} className="border-b last:border-0">
                        <td className="p-3 font-medium">{it.symbol}</td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          {pct(it.weight_target, 1)}
                        </td>
                        <td className="p-3 text-right tabular-nums">{pct(avg, 1)}</td>
                        <td className="p-3 text-right tabular-nums">
                          {pct(it.weight_final, 1)}
                        </td>
                        <td
                          className={cn(
                            'p-3 text-right font-medium tabular-nums',
                            Math.abs(it.weight_final - it.weight_target) > 0.05
                              ? 'text-amber-500'
                              : 'text-muted-foreground'
                          )}
                        >
                          {`${it.weight_final - it.weight_target >= 0 ? '+' : ''}${((it.weight_final - it.weight_target) * 100).toFixed(1)}pp`}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="structure" className="space-y-4">
          <div className="grid gap-3 md:grid-cols-3">
            <Stat
              label="Effective Bets"
              value={String(result.structure.effective_bets)}
              sub={`from ${result.items.length} holdings`}
            />
            <Stat
              label="Largest Cluster"
              value={pct(result.structure.largest_cluster_weight, 1)}
              sub="moves as one position"
              tone={result.structure.largest_cluster_weight > 0.5 ? 'bad' : undefined}
            />
            <Stat
              label="Funds vs Stocks"
              value={`${pct(result.structure.instrument_classes.fund ?? 0, 0)} / ${pct(
                result.structure.instrument_classes.stock ?? 0,
                0
              )}`}
              sub={result.structure.instrument_class_basis}
            />
          </div>

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Co-movement Clusters</CardTitle>
              <p className="text-sm text-muted-foreground">
                Holdings correlated above {result.structure.threshold} are grouped:
                they behave as one position, whatever their names or sectors say.
                A shock to any member hits the whole cluster.
              </p>
            </CardHeader>
            <CardContent className="space-y-2">
              {result.structure.clusters.map((c) => (
                <div key={c.id} className="rounded-md border p-3">
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium">
                      {c.independent ? 'Independent holding' : `Cluster ${c.id}`}
                    </span>
                    <span className="tabular-nums text-sm">{pct(c.weight, 1)}</span>
                  </div>
                  <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded bg-muted">
                    <div
                      className={cn(
                        'h-full rounded',
                        c.independent ? 'bg-emerald-500' : 'bg-amber-500'
                      )}
                      style={{ width: `${Math.min(c.weight * 100, 100)}%` }}
                    />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {c.members.map((m) => (
                      <span
                        key={m}
                        className="rounded bg-muted px-1.5 py-0.5 text-xs"
                      >
                        {m}
                      </span>
                    ))}
                  </div>
                </div>
              ))}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-4 text-sm text-muted-foreground">
              {result.structure.sector_note}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="attribution" className="space-y-4">
          {result.attribution.available ? (
            <>
              <div className="grid gap-3 md:grid-cols-4">
                <Stat
                  label="Excess vs Benchmark"
                  value={pct(result.attribution.excess_return)}
                  sub="what has to be explained"
                  tone={(result.attribution.excess_return ?? 0) >= 0 ? 'good' : 'bad'}
                />
                <Stat
                  label="Selection"
                  value={pct(result.attribution.selection_effect)}
                  sub="were these the right things to own"
                />
                <Stat
                  label="Allocation"
                  value={pct(result.attribution.allocation_effect)}
                  sub="did the weighting help"
                />
                <Stat
                  label="Trading costs"
                  value={pct(result.attribution.cost_effect)}
                  sub="net return versus gross"
                />
              </div>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">How it splits</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Selection is an equal-weighted basket of the same holdings
                    against the benchmark: the picks, with sizing removed.
                    Allocation is the realized gross portfolio against that
                    basket. Trading costs bridge gross to net. Together they
                    sum to the net excess.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  <table className="w-full text-sm">
                    <tbody>
                      {[
                        ['Portfolio', result.attribution.portfolio_return],
                        ['Equal-weighted basket', result.attribution.equal_weight_return],
                        ['Benchmark', result.attribution.benchmark_return],
                      ].map(([label, v]) => (
                        <tr key={label as string} className="border-b">
                          <td className="p-3">{label}</td>
                          <td className="p-3 text-right tabular-nums">
                            {pct(v as number)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2">
                  <CardTitle className="text-base">Contribution by Holding</CardTitle>
                  <p className="text-sm text-muted-foreground">
                    Each holding's share of the out- or under-performance, not its
                    standalone result, the column sums to the excess.
                  </p>
                </CardHeader>
                <CardContent className="p-0">
                  {(result.attribution.holdings ?? []).length > 0 ? (
                    <table className="w-full text-sm">
                    <thead className="border-b text-xs text-muted-foreground">
                      <tr>
                        <th className="p-3 text-left">Symbol</th>
                        <th className="p-3 text-right">Weight</th>
                        <th className="p-3 text-right">Own return</th>
                        <th className="p-3 text-right">vs benchmark</th>
                        <th className="p-3 text-right">Contribution</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(result.attribution.holdings ?? []).map((h) => (
                        <tr key={h.symbol} className="border-b last:border-0">
                          <td className="p-3 font-medium">{h.symbol}</td>
                          <td className="p-3 text-right tabular-nums text-muted-foreground">
                            {pct(h.weight, 1)}
                          </td>
                          <td className="p-3 text-right tabular-nums">{pct(h.return)}</td>
                          <td
                            className={cn(
                              'p-3 text-right tabular-nums',
                              h.vs_benchmark >= 0 ? 'text-emerald-500' : 'text-rose-500'
                            )}
                          >
                            {h.vs_benchmark >= 0 ? '+' : ''}
                            {(h.vs_benchmark * 100).toFixed(2)}%
                          </td>
                          <td
                            className={cn(
                              'p-3 text-right font-medium tabular-nums',
                              h.contribution >= 0 ? 'text-emerald-500' : 'text-rose-500'
                            )}
                          >
                            {h.contribution >= 0 ? '+' : ''}
                            {(h.contribution * 100).toFixed(2)}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    </table>
                  ) : (
                    <p className="p-4 text-sm text-muted-foreground">
                      {result.attribution.holdings_reason}
                    </p>
                  )}
                </CardContent>
              </Card>

              <p className="text-xs text-muted-foreground">
                {result.attribution.method}
              </p>
            </>
          ) : (
            <Card>
              <CardContent className="p-4 text-sm text-muted-foreground">
                {result.attribution.reason ?? 'Attribution needs a benchmark.'}
              </CardContent>
            </Card>
          )}
        </TabsContent>

        <TabsContent value="crisis" className="space-y-4">
          {result.crisis.summary && (
            <div className="grid gap-3 md:grid-cols-4">
              <Stat
                label="Average Return"
                value={pct(result.crisis.summary.average_return)}
                sub={`across ${result.crisis.summary.count} periods`}
              />
              <Stat
                label="Hit Rate"
                value={pct(result.crisis.summary.hit_rate, 0)}
                sub="beat the benchmark"
              />
              <Stat
                label="Worst Crisis"
                value={pct(result.crisis.summary.worst)}
                tone="bad"
              />
              <Stat
                label="Best Period"
                value={pct(result.crisis.summary.best)}
                tone="good"
              />
            </div>
          )}

          {result.crisis.summary?.by_scope && (
            <div className="grid gap-3 md:grid-cols-2">
              {Object.entries(result.crisis.summary.by_scope).map(([scope, v]) => (
                <Card key={scope}>
                  <CardContent className="p-4">
                    <div className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
                      {scope === 'india' ? 'Domestic events' : 'Global shocks'}
                    </div>
                    <div className="mt-1 flex items-baseline gap-4">
                      <span className="text-2xl font-semibold tabular-nums">
                        {pct(v.average_return)}
                      </span>
                      <span className="text-sm text-muted-foreground">
                        hit rate {pct(v.hit_rate, 0)} over {v.count}
                      </span>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Crisis Period Summary</CardTitle>
              <p className="text-sm text-muted-foreground">
                How the portfolio held up when it mattered, against the benchmark
                over the same window. Recoveries are included on purpose, a
                crashes-only view flatters anything defensive.
              </p>
            </CardHeader>
            <CardContent>
              <CrisisChart periods={result.crisis.periods} />
            </CardContent>
          </Card>

          <Card>
            <CardContent className="p-0">
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="border-b text-xs text-muted-foreground">
                    <tr>
                      <th className="p-3 text-left">Period</th>
                      <th className="p-3 text-left">Scope</th>
                      <th className="p-3 text-left">Window</th>
                      <th className="p-3 text-right">Portfolio</th>
                      <th className="p-3 text-right">Benchmark</th>
                      <th className="p-3 text-right">Excess</th>
                    </tr>
                  </thead>
                  <tbody>
                    {result.crisis.periods.map((c) => (
                      <tr key={c.key} className="border-b last:border-0">
                        <td className="p-3">
                          <div className="font-medium">{c.label}</div>
                          {c.note && (
                            <div className="text-xs text-muted-foreground">{c.note}</div>
                          )}
                        </td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {c.scope === 'india' ? 'Domestic' : 'Global'}
                          {c.partial && (
                            <span className="ml-1 text-amber-500">partial</span>
                          )}
                        </td>
                        <td className="p-3 text-xs text-muted-foreground">
                          {c.start} → {c.end}
                          {c.days ? (
                            <div>
                              {c.days} days
                              {c.sessions ? ` · ${c.sessions} sessions` : ''}
                            </div>
                          ) : null}
                        </td>
                        <td
                          className={cn(
                            'p-3 text-right tabular-nums',
                            (c.portfolio ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          )}
                        >
                          {pct(c.portfolio)}
                        </td>
                        <td className="p-3 text-right tabular-nums text-muted-foreground">
                          {pct(c.benchmark)}
                        </td>
                        <td
                          className={cn(
                            'p-3 text-right font-medium tabular-nums',
                            (c.excess ?? 0) >= 0 ? 'text-emerald-500' : 'text-rose-500'
                          )}
                        >
                          {c.excess === null ? '-' : `${c.excess >= 0 ? '+' : ''}${(c.excess * 100).toFixed(2)}%`}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="health" className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-base">Portfolio Health</CardTitle>
              <p className="text-sm text-muted-foreground">
                Every pillar shows the inputs it read, the formula it applied and
                the weight it carried, so you can disagree with the grade and see
                exactly where.
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-baseline gap-4">
                <div
                  className={cn(
                    'text-5xl font-bold tabular-nums',
                    healthGradeTone(result.health.grade) === 'good'
                      ? 'text-emerald-500'
                      : healthGradeTone(result.health.grade) === 'bad'
                        ? 'text-rose-500'
                        : 'text-muted-foreground'
                  )}
                >
                  {result.health.grade ?? '-'}
                </div>
                <div className="text-2xl tabular-nums text-muted-foreground">
                  {result.health.score ?? '-'}/100
                </div>
                {result.health.unmeasured.length > 0 && (
                  <div className="text-xs text-muted-foreground">
                    {result.health.unmeasured.join(', ')} could not be measured and
                    were left out rather than scored zero
                  </div>
                )}
              </div>

              <div className="space-y-3">
                {result.health.pillars.map((p) => (
                  <div key={p.key} className="rounded-md border p-3">
                    <div className="flex items-center justify-between gap-4">
                      <span className="font-medium">{p.label}</span>
                      <span className="tabular-nums text-muted-foreground">
                        {p.score === null ? 'not measured' : `${p.score}/100`}
                        {p.effective_weight > 0 &&
                          ` · ${(p.effective_weight * 100).toFixed(0)}% of grade`}
                      </span>
                    </div>
                    {p.score !== null && (
                      <div className="mt-2 h-1.5 w-full overflow-hidden rounded bg-muted">
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
                    <p className="mt-1 text-xs text-muted-foreground">
                      <span className="font-medium">Formula: </span>
                      {p.formula}
                    </p>
                    <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                      {JSON.stringify(p.inputs)}
                    </p>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
