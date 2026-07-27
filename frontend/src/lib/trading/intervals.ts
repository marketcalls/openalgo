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
