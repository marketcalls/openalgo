/**
 * SIP Backtester results.
 *
 * Renders from the stored response rather than re-running: every panel is a
 * view of one simulation, so a re-fetch per tab could show two panels
 * disagreeing about the same SIP.
 *
 * The headline is deliberately written as a sentence a person can read out
 * loud. XIRR is the honest single number for a SIP, but "you put in X, it
 * became Y" is what people actually want first.
 */

import { ArrowLeft } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { MonthlyReturnsHeatmap } from '@/components/portfolio/MonthlyReturnsHeatmap'
import { PortfolioLineChart } from '@/components/portfolio/PortfolioLineChart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { cn } from '@/lib/utils'
import { useSipBacktestStore } from '@/stores/sipBacktestStore'

const inr = (n: number | null | undefined, dp = 0) =>
  n === null || n === undefined
    ? '—'
    : `₹${new Intl.NumberFormat('en-IN', { maximumFractionDigits: dp }).format(n)}`

const pct = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined ? '—' : `${(n * 100).toFixed(dp)}%`

const signedPct = (n: number | null | undefined, dp = 2) =>
  n === null || n === undefined ? '—' : `${n >= 0 ? '+' : ''}${(n * 100).toFixed(dp)}%`

/** Sessions to a readable duration. ~21 trading sessions to a month. */
const sessionsToText = (n: number | null | undefined) => {
  if (n === null || n === undefined) return '—'
  if (n < 21) return `${n} sessions`
  const months = Math.round(n / 21)
  if (months < 12) return `${months} month${months === 1 ? '' : 's'}`
  const years = (months / 12).toFixed(1)
  return `${years} years`
}

function Stat({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: string
  hint?: string
  tone?: 'good' | 'bad' | 'plain'
}) {
  return (
    <div className="space-y-0.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div
        className={cn(
          'text-xl font-semibold tabular-nums',
          tone === 'good' && 'text-emerald-600 dark:text-emerald-500',
          tone === 'bad' && 'text-rose-600 dark:text-rose-500'
        )}
      >
        {value}
      </div>
      {hint && <div className="text-[11px] text-muted-foreground">{hint}</div>}
    </div>
  )
}

export default function SipBacktesterResults() {
  const navigate = useNavigate()
  const result = useSipBacktestStore((s) => s.result)
  const request = useSipBacktestStore((s) => s.request)
  const [tab, setTab] = useState<'overview' | 'timing' | 'compare' | 'detail'>('overview')

  const valueSeries = useMemo(() => {
    if (!result) return []
    return [
      {
        name: 'Value',
        color: '#10b981',
        data: result.curves.value,
      },
      {
        name: 'Invested',
        color: '#94a3b8',
        data: result.curves.invested,
      },
      ...(result.benchmark?.curve
        ? [
            {
              name: `${result.benchmark.symbol} SIP`,
              color: '#6366f1',
              data: result.benchmark.curve,
            },
          ]
        : []),
    ]
  }, [result])

  if (!result || !request) {
    return (
      <div className="container mx-auto space-y-4 p-4">
        <h1 className="text-2xl font-bold tracking-tight">SIP Backtester</h1>
        <p className="text-sm text-muted-foreground">No result to show. Run a backtest first.</p>
        <Button onClick={() => navigate('/sip-backtester')}>Set up a SIP</Button>
      </div>
    )
  }

  const h = result.headline
  const u = result.underwater
  const d = result.drawdown
  const gainPositive = (h.gain ?? 0) >= 0

  return (
    <div className="container mx-auto space-y-4 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">
            {request.symbol} <span className="text-muted-foreground">{request.exchange}</span>
          </h1>
          <p className="text-sm text-muted-foreground">
            {inr(request.amount)} {result.request.frequency} from {h.start} to {h.end}
            {request.step_up_percent ? ` · ${request.step_up_percent}% annual step-up` : ''}
            {' · '}
            {result.request.source === 'db' ? 'Historify' : 'Broker API'}
          </p>
        </div>
        <Button variant="outline" onClick={() => navigate('/sip-backtester')}>
          <ArrowLeft className="mr-1 h-4 w-4" /> Change
        </Button>
      </div>

      {/* ── The sentence ─────────────────────────────────────────────── */}
      <Card>
        <CardContent className="pt-6">
          <p className="text-lg leading-relaxed">
            You invested <span className="font-semibold">{inr(h.invested)}</span> across{' '}
            <span className="font-semibold">{h.installments}</span> installments. It became{' '}
            <span
              className={cn(
                'font-semibold',
                gainPositive
                  ? 'text-emerald-600 dark:text-emerald-500'
                  : 'text-rose-600 dark:text-rose-500'
              )}
            >
              {inr(h.final_value)}
            </span>{' '}
            — {h.multiple ? `${h.multiple.toFixed(2)}×` : '—'} your money. That is{' '}
            <span className="font-semibold">{signedPct(h.absolute_return)}</span> on the capital you
            put in, an <span className="font-semibold">XIRR of {pct(h.xirr)}</span> a year, over{' '}
            {h.years?.toFixed(1)} years.
          </p>
          {h.cost_advantage !== null && h.cost_advantage < 0 && (
            <p className="mt-2 text-sm text-muted-foreground">
              Buying a fixed amount each time got your shares{' '}
              <span className="font-medium text-emerald-600 dark:text-emerald-500">
                {Math.abs(h.cost_advantage * 100).toFixed(2)}% cheaper
              </span>{' '}
              than the average price over the same dates — {inr(h.average_cost, 2)} against{' '}
              {inr(h.average_price, 2)}.
            </p>
          )}
          {u.ever_underwater && (
            <p className="mt-1 text-sm text-muted-foreground">
              Along the way it was worth less than you had put in for{' '}
              <span className="font-medium">{pct(u.share_below, 0)}</span> of the time, the longest
              stretch running {sessionsToText(u.longest_streak_sessions)}, at worst{' '}
              {pct(u.worst_shortfall)} below cost.
            </p>
          )}
        </CardContent>
      </Card>

      {/* ── Headline numbers ─────────────────────────────────────────── */}
      <Card>
        <CardContent className="grid grid-cols-2 gap-4 pt-6 md:grid-cols-4 lg:grid-cols-9">
          <Stat
            label="XIRR"
            value={pct(h.xirr)}
            tone={(h.xirr ?? 0) >= 0 ? 'good' : 'bad'}
            hint="annualised, cash-flow aware"
          />
          <Stat label="Invested" value={inr(h.invested)} />
          <Stat label="Current value" value={inr(h.final_value)} />
          <Stat
            label="Gain"
            value={inr(h.gain)}
            tone={gainPositive ? 'good' : 'bad'}
            hint="value minus invested"
          />
          <Stat
            label="Absolute return"
            value={signedPct(h.absolute_return)}
            tone={gainPositive ? 'good' : 'bad'}
            hint="on total capital invested"
          />
          <Stat
            label="Shares held"
            value={h.units ? h.units.toFixed(0) : '—'}
            hint={`avg ${inr(h.average_cost, 2)}`}
          />
          <Stat
            label="Uninvested cash"
            value={inr(h.cash, 2)}
            hint="whole shares leave a remainder"
          />
          <Stat
            label="Max drawdown"
            value={pct(d.max_drawdown)}
            tone="bad"
            hint={
              d.recovered ? `recovered in ${sessionsToText(d.recovery_sessions)}` : 'not recovered'
            }
          />
          <Stat label="Charges" value={inr(h.charges)} hint="brokerage across all installments" />
        </CardContent>
      </Card>

      {result.warnings.length > 0 && (
        <div className="rounded-md border border-amber-500/50 bg-amber-500/10 p-3 text-sm">
          <span className="font-medium">Check this data.</span> {result.warnings.join(' ')}
        </div>
      )}

      {/* ── Tabs ─────────────────────────────────────────────────────── */}
      <div className="flex gap-1 border-b">
        {(
          [
            ['overview', 'Overview'],
            ['timing', 'Starting in a crisis'],
            ['compare', 'Comparisons'],
            ['detail', 'Detail'],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            onClick={() => setTab(key)}
            className={cn(
              'px-3 py-2 text-sm transition-colors',
              tab === key
                ? 'border-b-2 border-primary font-medium'
                : 'text-muted-foreground hover:text-foreground'
            )}
          >
            {label}
          </button>
        ))}
      </div>

      {/* ── Overview ─────────────────────────────────────────────────── */}
      {tab === 'overview' && (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Value against what you put in</CardTitle>
            </CardHeader>
            <CardContent>
              <PortfolioLineChart series={valueSeries} height={340} format={(v) => inr(v)} />
              <p className="mt-2 text-xs text-muted-foreground">
                The grey line is money paid in. Wherever green sits below it, the holding was worth
                less than its cost.
              </p>
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Year by year</CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1 text-left">Year</th>
                      <th className="py-1 text-right">Invested</th>
                      <th className="py-1 text-right">Value</th>
                      <th className="py-1 text-right">Gain</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {result.yearly.map((y) => (
                      <tr key={y.year} className="border-b last:border-0">
                        <td className="py-1">{y.year}</td>
                        <td className="py-1 text-right">{inr(y.invested_to_date)}</td>
                        <td className="py-1 text-right">{inr(y.value)}</td>
                        <td
                          className={cn(
                            'py-1 text-right',
                            (y.gain ?? 0) >= 0
                              ? 'text-emerald-600 dark:text-emerald-500'
                              : 'text-rose-600 dark:text-rose-500'
                          )}
                        >
                          {inr(y.gain)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Month by month</CardTitle>
              </CardHeader>
              <CardContent>
                <MonthlyReturnsHeatmap
                  years={result.monthly_heatmap.years}
                  columns={result.monthly_heatmap.columns}
                  values={result.monthly_heatmap.values}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  Market movement only — the installment paid in that month is subtracted, so this
                  is not just a picture of your deposits.
                </p>
              </CardContent>
            </Card>
          </div>
        </div>
      )}

      {/* ── Timing ───────────────────────────────────────────────────── */}
      {tab === 'timing' && (
        <div className="space-y-4">
          {result.crisis && result.crisis.periods.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Would starting in a crash have ruined it?</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-sm">
                  Across{' '}
                  <span className="font-semibold">{result.crisis.summary.crises} crises</span> your
                  data covers, beginning the SIP{' '}
                  <span className="font-semibold">as the crash started</span> beat waiting for it to
                  end in <span className="font-semibold">{result.crisis.summary.early_wins}</span>{' '}
                  of them
                  {result.crisis.summary.median_advantage !== null && (
                    <>
                      , by a median of{' '}
                      <span className="font-semibold">
                        {signedPct(result.crisis.summary.median_advantage)}
                      </span>{' '}
                      XIRR
                    </>
                  )}
                  .
                </p>
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead className="text-xs text-muted-foreground">
                      <tr className="border-b">
                        <th className="py-1 text-left">Crisis</th>
                        <th className="py-1 text-right">Market</th>
                        <th className="py-1 text-right">Started into it</th>
                        <th className="py-1 text-right">Waited for the end</th>
                        <th className="py-1 text-right">Difference</th>
                      </tr>
                    </thead>
                    <tbody className="tabular-nums">
                      {result.crisis.periods.map((c) => (
                        <tr key={c.key} className="border-b last:border-0">
                          <td className="py-1">
                            <div>{c.label}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {c.crisis_start} to {c.crisis_end}
                            </div>
                          </td>
                          <td
                            className={cn(
                              'py-1 text-right',
                              (c.market_move ?? 0) < 0 && 'text-rose-600 dark:text-rose-500'
                            )}
                          >
                            {signedPct(c.market_move, 1)}
                          </td>
                          <td className="py-1 text-right">
                            <div className="font-medium">{pct(c.started_into_it.xirr)}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {inr(c.started_into_it.final_value)}
                            </div>
                          </td>
                          <td className="py-1 text-right">
                            <div className="font-medium">{pct(c.waited_for_the_end.xirr)}</div>
                            <div className="text-[11px] text-muted-foreground">
                              {inr(c.waited_for_the_end.final_value)}
                            </div>
                          </td>
                          <td
                            className={cn(
                              'py-1 text-right font-medium',
                              c.starting_early_won
                                ? 'text-emerald-600 dark:text-emerald-500'
                                : 'text-muted-foreground'
                            )}
                          >
                            {signedPct(c.xirr_advantage)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="text-xs text-muted-foreground">
                  Both columns run the same installment to the same end date, so only the start
                  moves. A SIP begun into a falling market spends the decline buying cheap units;
                  one begun after the recovery pays post-rebound prices from its first installment.
                  That is the opposite of the lumpsum intuition, which is exactly why it is worth
                  measuring rather than assuming. Crises your price history does not fully cover are
                  left out rather than reported from partial data.
                </p>
              </CardContent>
            </Card>
          )}

          {result.start_date_heatmap && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Would it have mattered when you started?</CardTitle>
              </CardHeader>
              <CardContent>
                <MonthlyReturnsHeatmap
                  years={result.start_date_heatmap.rows}
                  columns={result.start_date_heatmap.columns}
                  values={result.start_date_heatmap.values}
                />
                <p className="mt-2 text-xs text-muted-foreground">
                  XIRR for a SIP begun in each month and held for each period. Columns that flatten
                  out to the right mean the start date stopped mattering once the horizon was long
                  enough.
                </p>
              </CardContent>
            </Card>
          )}

          {result.rolling_xirr && result.rolling_xirr.length > 0 && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Every window in history, not just this one
                </CardTitle>
              </CardHeader>
              <CardContent className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="text-xs text-muted-foreground">
                    <tr className="border-b">
                      <th className="py-1 text-left">Holding period</th>
                      <th className="py-1 text-right">Windows</th>
                      <th className="py-1 text-right">Worst</th>
                      <th className="py-1 text-right">Median</th>
                      <th className="py-1 text-right">Best</th>
                      <th className="py-1 text-right">Profitable</th>
                    </tr>
                  </thead>
                  <tbody className="tabular-nums">
                    {result.rolling_xirr.map((r) => (
                      <tr key={r.years} className="border-b last:border-0">
                        <td className="py-1">
                          {r.years} year{r.years === 1 ? '' : 's'}
                        </td>
                        <td className="py-1 text-right">{r.windows}</td>
                        <td className="py-1 text-right text-rose-600 dark:text-rose-500">
                          {pct(r.worst)}
                        </td>
                        <td className="py-1 text-right font-medium">{pct(r.median)}</td>
                        <td className="py-1 text-right text-emerald-600 dark:text-emerald-500">
                          {pct(r.best)}
                        </td>
                        <td className="py-1 text-right">{pct(r.positive_share, 0)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                <p className="mt-2 text-xs text-muted-foreground">
                  A single headline XIRR is one draw from this distribution. The gap between worst
                  and best is what starting at a different time would have cost or gained you.
                </p>
              </CardContent>
            </Card>
          )}

          {result.sip_date_heatmap && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">Which date of the month?</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="flex flex-wrap gap-1">
                  {result.sip_date_heatmap.days.map((day, i) => {
                    const v = result.sip_date_heatmap!.values[i]
                    const best = day === result.sip_date_heatmap!.best_day
                    return (
                      <div
                        key={day}
                        className={cn(
                          'w-16 rounded border px-1 py-1 text-center text-xs tabular-nums',
                          best && 'border-emerald-500 bg-emerald-500/10'
                        )}
                      >
                        <div className="text-muted-foreground">{day}</div>
                        <div className="font-medium">{pct(v, 1)}</div>
                      </div>
                    )
                  })}
                </div>
                <p className="mt-2 text-xs text-muted-foreground">
                  Best was the {result.sip_date_heatmap.best_day}th, worst the{' '}
                  {result.sip_date_heatmap.worst_day}th — a spread of{' '}
                  {pct(result.sip_date_heatmap.spread)}. Usually small enough that picking a date
                  you will not miss matters more than picking the best one.
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Comparisons ──────────────────────────────────────────────── */}
      {tab === 'compare' && (
        <div className="space-y-4">
          {result.lumpsum && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">SIP against a lumpsum</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <Stat label="SIP value" value={inr(result.lumpsum.sip_final_value)} />
                  <Stat label="Lumpsum value" value={inr(result.lumpsum.final_value)} />
                  <Stat
                    label="Difference"
                    value={inr(Math.abs(result.lumpsum.difference ?? 0))}
                    tone={result.lumpsum.sip_won ? 'good' : 'bad'}
                    hint={result.lumpsum.sip_won ? 'SIP ahead' : 'lumpsum ahead'}
                  />
                  <Stat label="Lumpsum XIRR" value={pct(result.lumpsum.xirr)} />
                </div>
                <p className="text-xs text-muted-foreground">
                  The same total money put in on {result.lumpsum.entry_date} at{' '}
                  {inr(result.lumpsum.entry_price, 2)}. In a market that rose steadily, lumpsum
                  usually wins — money in earlier compounds longer. Shown either way rather than
                  only when it flatters the SIP.
                </p>
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Would a different frequency have helped?</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-muted-foreground">
                  <tr className="border-b">
                    <th className="py-1 text-left">Frequency</th>
                    <th className="py-1 text-right">Per installment</th>
                    <th className="py-1 text-right">Count</th>
                    <th className="py-1 text-right">Invested</th>
                    <th className="py-1 text-right">Value</th>
                    <th className="py-1 text-right">XIRR</th>
                  </tr>
                </thead>
                <tbody className="tabular-nums">
                  {result.frequency_comparison.map((f) => (
                    <tr
                      key={f.frequency}
                      className={cn(
                        'border-b last:border-0',
                        f.frequency === result.request.frequency && 'bg-muted/50 font-medium'
                      )}
                    >
                      <td className="py-1 capitalize">{f.frequency}</td>
                      <td className="py-1 text-right">{inr(f.amount_per_installment)}</td>
                      <td className="py-1 text-right">{f.installments}</td>
                      <td className="py-1 text-right">{inr(f.invested)}</td>
                      <td className="py-1 text-right">{inr(f.final_value)}</td>
                      <td className="py-1 text-right">{pct(f.xirr)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-2 text-xs text-muted-foreground">
                Amounts are scaled so each frequency invests about the same per year — otherwise a
                weekly SIP simply invests four times as much and "wins" for a reason that has
                nothing to do with frequency.
              </p>
            </CardContent>
          </Card>

          {result.charges && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">What the charges cost you</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
                  <Stat label="Total charges" value={inr(result.charges.total)} />
                  <Stat label="Per installment" value={inr(result.charges.per_installment, 2)} />
                  <Stat
                    label="Drag"
                    value={pct(result.charges.drag)}
                    hint="of everything paid in"
                  />
                  <Stat
                    label="Model"
                    value={result.charges.exchange}
                    hint={result.charges.model.replace('_', ' ')}
                  />
                </div>
                <div className="flex flex-wrap gap-2">
                  {Object.entries(result.charges.breakdown)
                    .filter(([k, v]) => k !== 'total' && v > 0)
                    .map(([k, v]) => (
                      <div key={k} className="rounded border px-2 py-1 text-xs">
                        <span className="text-muted-foreground">{k.replace(/_/g, ' ')}</span>{' '}
                        <span className="font-medium tabular-nums">{inr(v, 2)}</span>
                      </div>
                    ))}
                </div>
                <p className="text-xs text-muted-foreground">
                  Charged on every installment, so they scale with how often you invest. They reduce
                  the units bought rather than appearing as a separate deduction — which is why a
                  higher-frequency SIP can cost more for the same yearly outlay.
                </p>
              </CardContent>
            </Card>
          )}

          {result.benchmark && !result.benchmark.error && (
            <Card>
              <CardHeader className="pb-2">
                <CardTitle className="text-sm">
                  Against a SIP into {result.benchmark.symbol}
                </CardTitle>
              </CardHeader>
              <CardContent className="grid grid-cols-2 gap-4 md:grid-cols-4">
                <Stat label={`${request.symbol} XIRR`} value={pct(h.xirr)} />
                <Stat
                  label={`${result.benchmark.symbol} XIRR`}
                  value={pct(result.benchmark.xirr)}
                />
                <Stat
                  label="Excess"
                  value={signedPct(result.benchmark.excess_xirr)}
                  tone={result.benchmark.beat_benchmark ? 'good' : 'bad'}
                />
                <Stat
                  label={`${result.benchmark.symbol} value`}
                  value={inr(result.benchmark.headline?.final_value)}
                />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── Detail ───────────────────────────────────────────────────── */}
      {tab === 'detail' && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm">Every installment</CardTitle>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b">
                  <th className="py-1 text-left">#</th>
                  <th className="py-1 text-left">Scheduled</th>
                  <th className="py-1 text-left">Executed</th>
                  <th className="py-1 text-right">Amount</th>
                </tr>
              </thead>
              <tbody className="tabular-nums">
                {result.installments.map((i, n) => (
                  <tr key={`${i.executed}-${n}`} className="border-b last:border-0">
                    <td className="py-1">{n + 1}</td>
                    <td className="py-1">{i.requested}</td>
                    <td
                      className={cn(
                        'py-1',
                        i.requested !== i.executed && 'text-amber-600 dark:text-amber-500'
                      )}
                    >
                      {i.executed}
                    </td>
                    <td className="py-1 text-right">{inr(i.amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="mt-2 text-xs text-muted-foreground">
              Highlighted dates rolled forward because the scheduled day was a holiday or a weekend,
              which is what a broker actually does.
            </p>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
