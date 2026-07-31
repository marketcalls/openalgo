/**
 * Plain-English guide to the backtest metrics, with the portfolio's own value
 * marked on each scale.
 *
 * A table of numbers tells a reader what the portfolio scored and nothing about
 * whether that is good. Every card here says what the metric means, what counts
 * as good, and puts a marker where this portfolio actually landed, so the
 * judgement is made for them rather than left as an exercise.
 *
 * The scales are judgement calls stated openly rather than hidden: a Sharpe of
 * 1.0 being "good" is a convention, not a law, and the labels say where the
 * boundaries were drawn so a reader can disagree with them.
 */
import { cn } from '@/lib/utils'

type Direction = 'higher' | 'lower' | 'centre'

interface Spec {
  key: string
  label: string
  badge: string
  badgeClass: string
  meaning: string
  /** Value at each end of the bar, and the label under each third. */
  from: number
  to: number
  stops: [string, string, string]
  direction: Direction
  format: (v: number) => string
  /**
   * The rating and the sentence for a given value. Written per metric rather
   * than derived from the bar position, because "beta 1.0" is neither good nor
   * bad and a generic scale would call it average.
   */
  verdict: (v: number) => { rating: string; tone: Tone; says: string }
}

type Tone = 'great' | 'good' | 'fair' | 'poor'

const TONE_CLASS: Record<Tone, string> = {
  great: 'bg-emerald-500/15 text-emerald-400',
  good: 'bg-teal-500/15 text-teal-400',
  fair: 'bg-amber-500/15 text-amber-400',
  poor: 'bg-rose-500/15 text-rose-400',
}

const pctOf = (dp = 1) => (v: number) => `${(v * 100).toFixed(dp)}%`
const plain = (dp = 2) => (v: number) => v.toFixed(dp)

const SPECS: Spec[] = [
  {
    key: 'cagr',
    label: 'CAGR',
    badge: 'RETURN',
    badgeClass: 'bg-emerald-500/15 text-emerald-400',
    meaning:
      'Compound annual growth rate: what the portfolio earned per year, with compounding. Compare it directly against the benchmark CAGR. Beating it by 2 points a year is a real edge.',
    from: 0,
    to: 0.18,
    stops: ['0%', '8%', '18%+'],
    direction: 'higher',
    format: pctOf(),
    verdict: (v) =>
      v >= 0.18
        ? { rating: 'Excellent', tone: 'great', says: 'Compounding at a rate few portfolios sustain.' }
        : v >= 0.12
          ? { rating: 'Strong', tone: 'good', says: 'Comfortably ahead of a fixed deposit and most index funds.' }
          : v >= 0.06
            ? { rating: 'Modest', tone: 'fair', says: 'Growing, but not by much more than inflation.' }
            : { rating: 'Weak', tone: 'poor', says: 'Barely growing, or losing ground in real terms.' },
  },
  {
    key: 'sharpe',
    label: 'Sharpe Ratio',
    badge: 'RISK ADJUSTED',
    badgeClass: 'bg-indigo-500/15 text-indigo-400',
    meaning:
      'Return per unit of risk. Above 1.0 is good, above 1.5 is very good. Below 0.5 means the portfolio took a lot of risk for what it delivered.',
    from: 0,
    to: 2,
    stops: ['under 0.5 weak', '1.0 good', '1.5+ great'],
    direction: 'higher',
    format: plain(),
    verdict: (v) =>
      v >= 1.5
        ? { rating: 'Excellent', tone: 'great', says: 'Very well paid for the risk it carried.' }
        : v >= 1.0
          ? { rating: 'Good', tone: 'good', says: 'Above the 1.0 that counts as a good result.' }
          : v >= 0.5
            ? { rating: 'Fair', tone: 'fair', says: 'Getting paid, but not much, for the swings.' }
            : { rating: 'Weak', tone: 'poor', says: 'Taking real risk for very little in return.' },
  },
  {
    key: 'max_drawdown',
    label: 'Max Drawdown',
    badge: 'RISK',
    badgeClass: 'bg-rose-500/15 text-rose-400',
    meaning:
      'The worst fall from a peak. A value of 35% means the portfolio lost 35% from its high before recovering. This is the pain you would have had to sit through.',
    from: -0.4,
    to: -0.05,
    stops: ['40%+ severe', '25%', '10% mild'],
    direction: 'higher',
    format: pctOf(),
    verdict: (v) =>
      v >= -0.15
        ? { rating: 'Comfortable', tone: 'great', says: 'Never fell far enough to test your nerve.' }
        : v >= -0.25
          ? { rating: 'Normal', tone: 'good', says: 'A fall most equity investors would recognise.' }
          : v >= -0.4
            ? { rating: 'Painful', tone: 'fair', says: 'Deep enough that many would have sold near the bottom.' }
            : { rating: 'Severe', tone: 'poor', says: 'A fall this deep needs years to recover from.' },
  },
  {
    key: 'volatility',
    label: 'Volatility',
    badge: 'RISK',
    badgeClass: 'bg-rose-500/15 text-rose-400',
    meaning:
      'How much the value swings year to year. Lower is calmer. Indian equity indices typically run near 15%, so under that is a smooth ride and well over it is a bumpy one.',
    from: 0.3,
    to: 0.05,
    stops: ['30% wild', '15% typical', '5% calm'],
    direction: 'higher',
    format: pctOf(),
    verdict: (v) =>
      v <= 0.1
        ? { rating: 'Calm', tone: 'great', says: 'Moves gently. Easy to hold through.' }
        : v <= 0.18
          ? { rating: 'Typical', tone: 'good', says: 'About as bumpy as the index itself.' }
          : v <= 0.25
            ? { rating: 'Bumpy', tone: 'fair', says: 'Swings hard enough to be uncomfortable.' }
            : { rating: 'Wild', tone: 'poor', says: 'Large swings. Expect sleepless stretches.' },
  },
  {
    key: 'sortino',
    label: 'Sortino Ratio',
    badge: 'DOWNSIDE',
    badgeClass: 'bg-purple-500/15 text-purple-400',
    meaning:
      'Like Sharpe, but it only counts the downside swings. Upside volatility is not a problem for an investor. A high Sortino next to a modest Sharpe means the swings were mostly upward.',
    from: 0,
    to: 2.5,
    stops: ['under 1.0 weak', '1.5 good', '2.0+ excellent'],
    direction: 'higher',
    format: plain(),
    verdict: (v) =>
      v >= 2
        ? { rating: 'Excellent', tone: 'great', says: 'The big moves were mostly upward.' }
        : v >= 1.5
          ? { rating: 'Good', tone: 'good', says: 'Downside swings are well contained.' }
          : v >= 1
            ? { rating: 'Fair', tone: 'fair', says: 'Downside is noticeable but not alarming.' }
            : { rating: 'Weak', tone: 'poor', says: 'The falls are doing most of the moving.' },
  },
  {
    key: 'alpha',
    label: 'Alpha',
    badge: 'SKILL',
    badgeClass: 'bg-emerald-500/15 text-emerald-400',
    meaning:
      'Return above the benchmark once its risk is accounted for. Positive means the choices added something. Negative means a plain index fund would have done better.',
    from: -0.1,
    to: 0.1,
    stops: ['negative', '0', 'positive'],
    direction: 'centre',
    format: (v) => v.toFixed(3),
    verdict: (v) =>
      v >= 0.05
        ? { rating: 'Real edge', tone: 'great', says: 'The choices added meaningfully over the index.' }
        : v > 0.005
          ? { rating: 'Slight edge', tone: 'good', says: 'A little better than simply buying the index.' }
          : v > -0.005
            ? { rating: 'Neutral', tone: 'fair', says: 'Effectively matching the index once risk is counted.' }
            : { rating: 'Negative', tone: 'poor', says: 'An index fund would have served you better.' },
  },
  {
    key: 'beta',
    label: 'Beta',
    badge: 'SENSITIVITY',
    badgeClass: 'bg-amber-500/15 text-amber-400',
    meaning:
      'How much the portfolio moves when the market moves. Beta 1.2 means it swings 20% harder than the index, in both directions. Below 0.8 is defensive.',
    from: 0,
    to: 1.6,
    stops: ['under 0.8 defensive', '1.0 market', 'over 1.2 aggressive'],
    direction: 'centre',
    format: plain(),
    verdict: (v) =>
      v <= 0.8
        ? { rating: 'Defensive', tone: 'good', says: 'Moves less than the market, in both directions.' }
        : v <= 1.2
          ? { rating: 'Market-like', tone: 'good', says: 'Rises and falls roughly with the index.' }
          : v <= 1.5
            ? { rating: 'Aggressive', tone: 'fair', says: 'Amplifies the market, gains and losses alike.' }
            : { rating: 'Very aggressive', tone: 'poor', says: 'Swings far harder than the index.' },
  },
  {
    key: 'calmar',
    label: 'Calmar Ratio',
    badge: 'RECOVERY',
    badgeClass: 'bg-sky-500/15 text-sky-400',
    meaning:
      'Annual return divided by the worst drawdown. It answers whether the return justified the deepest fall along the way. Above 1.0 means yes.',
    from: 0,
    to: 2,
    stops: ['under 0.5 weak', '1.0 good', '2.0+ great'],
    direction: 'higher',
    format: plain(),
    verdict: (v) =>
      v >= 2
        ? { rating: 'Excellent', tone: 'great', says: 'The return more than justified the worst fall.' }
        : v >= 1
          ? { rating: 'Good', tone: 'good', says: 'The return was worth the drawdown along the way.' }
          : v >= 0.5
            ? { rating: 'Fair', tone: 'fair', says: 'The fall was steep relative to what it earned.' }
            : { rating: 'Weak', tone: 'poor', says: 'The drawdown was not repaid by the return.' },
  },
  {
    key: 'win_rate',
    label: 'Win Rate',
    badge: 'CONSISTENCY',
    badgeClass: 'bg-teal-500/15 text-teal-400',
    meaning:
      'The share of days that finished positive. Around 50% is normal for equities. Far more important is how big the winners are against the losers, so treat this as texture, not a verdict.',
    from: 0.4,
    to: 0.6,
    stops: ['40%', '50% typical', '60%'],
    direction: 'higher',
    format: pctOf(0),
    verdict: (v) =>
      v >= 0.55
        ? { rating: 'Frequent wins', tone: 'good', says: 'More up days than most, though size matters more.' }
        : v >= 0.48
          ? { rating: 'Typical', tone: 'good', says: 'About half the days are positive, as expected.' }
          : { rating: 'Few wins', tone: 'fair', says: 'Fewer up days, so the winners must be large.' },
  },
  {
    key: 'cvar',
    label: 'Conditional VaR',
    badge: 'TAIL RISK',
    badgeClass: 'bg-rose-500/15 text-rose-400',
    meaning:
      'The average loss on the worst 5% of days. Value at Risk says how bad a bad day is; this says how bad it gets once you are already in one.',
    from: -0.05,
    to: -0.005,
    stops: ['5%+ heavy', '2%', 'under 1% light'],
    direction: 'higher',
    format: pctOf(2),
    verdict: (v) =>
      v >= -0.015
        ? { rating: 'Light tail', tone: 'great', says: 'Even the worst days stay small.' }
        : v >= -0.03
          ? { rating: 'Normal tail', tone: 'good', says: 'Bad days look like ordinary equity bad days.' }
          : { rating: 'Heavy tail', tone: 'poor', says: 'The worst days are severe when they come.' },
  },
]

function position(spec: Spec, value: number): number {
  const t = (value - spec.from) / (spec.to - spec.from)
  return Math.min(100, Math.max(0, t * 100))
}

export function MetricGuide({ metrics }: { metrics: Record<string, number | null | undefined> }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
      {SPECS.map((spec) => {
        const value = metrics[spec.key]
        const known = value !== null && value !== undefined && Number.isFinite(value)
        const at = known ? position(spec, value as number) : null
        const verdict = known ? spec.verdict(value as number) : null

        return (
          <div key={spec.key} className="rounded-lg border p-4">
            <div className="flex items-start justify-between gap-2">
              <span className="font-semibold">{spec.label}</span>
              <span
                className={cn(
                  'shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium tracking-wide',
                  spec.badgeClass
                )}
              >
                {spec.badge}
              </span>
            </div>

            <p className="mt-1.5 text-xs leading-relaxed text-muted-foreground">
              {spec.meaning}
            </p>

            <div className="relative mt-4 h-2 rounded-full bg-gradient-to-r from-rose-500 via-amber-400 to-emerald-500">
              {at !== null && (
                <span
                  className="absolute top-1/2 h-4 w-1 -translate-x-1/2 -translate-y-1/2 rounded-full bg-foreground ring-2 ring-background"
                  style={{ left: `${at}%` }}
                  title={`This portfolio: ${spec.format(value as number)}`}
                />
              )}
            </div>

            <div className="mt-1 flex justify-between text-[10px] text-muted-foreground">
              {spec.stops.map((label) => (
                <span key={label}>{label}</span>
              ))}
            </div>

            {known ? (
              <div className="mt-3 rounded-md bg-muted/40 p-2.5">
                <div className="flex items-center gap-2">
                  <span className="text-lg font-semibold tabular-nums">
                    {spec.format(value as number)}
                  </span>
                  <span
                    className={cn(
                      'rounded px-1.5 py-0.5 text-[10px] font-medium',
                      TONE_CLASS[verdict!.tone]
                    )}
                  >
                    {verdict!.rating}
                  </span>
                </div>
                <p className="mt-1 text-xs text-muted-foreground">{verdict!.says}</p>
              </div>
            ) : (
              <div className="mt-3 text-xs text-muted-foreground">
                Not available. Alpha and beta need a benchmark.
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
