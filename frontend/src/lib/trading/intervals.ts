/**
 * Interval-token helpers for the trading terminal: how far back to fetch history
 * per timeframe, the bucket size for live candle aggregation, and grouping the
 * broker's supported intervals for the timeframe dropdown.
 */

/** History lookback (days) for an interval token — deeper for coarser frames. */
export function lookbackDays(interval: string): number {
  const m = /^(\d+)([smh])$/.exec(interval)
  if (m) {
    const n = Number(m[1])
    if (m[2] === 's') return 2
    if (m[2] === 'm') return n <= 1 ? 7 : n <= 5 ? 30 : n <= 15 ? 60 : 120
    return 180 // hours
  }
  if (interval === 'D') return 3 * 365
  if (interval === 'W') return 5 * 365
  if (interval === 'M') return 10 * 365
  return 30
}

/**
 * How far back a BACKTEST reaches by default, per interval.
 *
 * **Not `lookbackDays`, which is the chart's, and the difference is the point.**
 * That one decides how much history to draw, where a minute chart wants a week
 * because nobody scrolls back further. A backtest over a week of one minute
 * bars is a backtest over four sessions, which tells a trader nothing about a
 * strategy. The two questions have different right answers and keeping one
 * function for both is how a backtest ends up sized for a scrollbar.
 *
 * **The range is chosen so the bar count is useful and bounded.** Roughly, on an
 * Indian session of 375 minutes and about 21 sessions a month:
 *
 * ```
 * 1m    2 months    ~15,000 bars
 * 5m    2 months     ~3,100 bars
 * 15m   2 months     ~1,000 bars
 * 1h    2 years      ~3,100 bars
 * D     2 years        ~500 bars
 * W     5 years        ~260 bars
 * M     10 years       ~120 bars
 * ```
 *
 * Every one is far under the bar ceiling, which is what makes this the memory
 * conscious default: an intraday strategy is tested over months rather than
 * years, so an ordinary run fetches a few megabytes rather than tens, and a run
 * starts on its own whenever the instrument or the interval changes.
 *
 * **Weekly and monthly are not two years, deliberately.** Two years of monthly
 * bars is twenty four of them, which is not a backtest but a table. Those two
 * keep the deeper reach the chart already gives them, because for them the
 * bar count is the scarce thing rather than the memory.
 */
export function backtestLookbackDays(interval: string): number {
  const TWO_MONTHS = 60
  const TWO_YEARS = 2 * 365

  const parsed = /^(\d+)([smh])$/.exec(interval)
  if (parsed) {
    // Seconds and minutes are the intraday frames: two months of them is
    // already thousands of bars, and a year would be tens of thousands for no
    // extra insight into a strategy that closes every day.
    return parsed[2] === 'h' ? TWO_YEARS : TWO_MONTHS
  }
  if (interval === 'D') return TWO_YEARS
  if (interval === 'W') return 5 * 365
  if (interval === 'M') return 10 * 365

  // An interval this does not recognise, which is a broker naming one its own
  // way. Two months is the cautious answer: it is the smaller fetch, and a
  // trader who wants more moves the date box.
  return TWO_MONTHS
}

/** Interval token → seconds for the live CandleBuilder; null for D/W/M (no intraday aggregation). */
export function intervalSeconds(interval: string): number | null {
  const m = /^(\d+)([smh])$/.exec(interval)
  if (!m) return null
  const n = Number(m[1])
  return m[2] === 's' ? n : m[2] === 'm' ? n * 60 : n * 3600
}

export interface IntervalData {
  seconds?: string[]
  minutes?: string[]
  hours?: string[]
  days?: string[]
  weeks?: string[]
  months?: string[]
}

export interface IntervalGroup {
  label: string
  items: string[]
}

/** Broker interval payload → ordered, non-empty groups for the timeframe menu. */
export function intervalGroups(data: IntervalData): IntervalGroup[] {
  const order: [string, string[] | undefined][] = [
    ['seconds', data.seconds],
    ['minutes', data.minutes],
    ['hours', data.hours],
    ['days', data.days],
    ['weeks', data.weeks],
    ['months', data.months],
  ]
  return order
    .filter(([, arr]) => arr?.length)
    .map(([label, arr]) => ({ label, items: arr as string[] }))
}

/**
 * Pick the interval to show on load: the saved one if the broker still supports
 * it, else 5m, else the first minute interval, else whatever exists.
 */
export function pickInterval(groups: IntervalGroup[], saved: string | null): string {
  const all = groups.flatMap((g) => g.items)
  if (saved && all.includes(saved)) return saved
  if (all.includes('5m')) return '5m'
  const minutes = groups.find((g) => g.label === 'minutes')
  return minutes?.items[0] ?? all[0] ?? 'D'
}
