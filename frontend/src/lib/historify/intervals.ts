/**
 * The interval grammar Historify's DuckDB store actually accepts.
 *
 * This exists because nothing on the server will tell you.
 * `/historify/api/historify-intervals` reports six tokens, sorted
 * lexicographically ("15m" < "1h" < "1m" < "30m" < "5m" < "D"), while
 * `/historify/api/data` never validates `interval` at all and happily serves
 * any multiple the parser understands. Driving a timeframe list from that route
 * would hide most of what works; passing a token it has not heard of returns an
 * empty 200 rather than an error.
 *
 * So the grammar is mirrored here from `database/historify_db.py:659-734`:
 *
 *     ^(\d+)([mhDWMQY])$     plus the bare letters D W M Q Y
 *
 * Case matters, and it is the trap in the whole scheme: lowercase `m` is
 * minutes, uppercase `M` is months.
 *
 * Two shapes parse but return nothing, so they must never be emitted:
 *
 * - `1D`, `2D`, `3D`. They type as "daily", which is neither the intraday
 *   branch nor the daily-aggregated branch, so the query falls through to a
 *   stored-table read for a literal interval of "1D", a row that does not
 *   exist. `D` is the only daily token. It is not "1D" spelled short.
 * - `MO` for months. `M` is the token; `MO` fails the regex outright. The page
 *   this replaces emitted `MO`, which is why its custom monthly option has
 *   never drawn a single candle.
 */

/** The unit letters the store understands, with minutes and months distinct. */
export type IntervalUnit = 'm' | 'h' | 'W' | 'M' | 'Q' | 'Y'

/** Which stored interval a token is served or aggregated from. */
export type SourceInterval = '1m' | 'D'

export interface ParsedInterval {
  unit: IntervalUnit | 'D'
  value: number
  /** The stored interval this token needs in order to return anything. */
  source: SourceInterval
}

/** The units the custom builder offers. `D` is deliberately absent: see above. */
export const CUSTOM_UNITS: ReadonlyArray<{ value: IntervalUnit; label: string }> = [
  { value: 'm', label: 'min' },
  { value: 'h', label: 'hr' },
  { value: 'W', label: 'Week' },
  { value: 'M', label: 'Month' },
  { value: 'Q', label: 'Qtr' },
  { value: 'Y', label: 'Year' },
]

/**
 * The standard timeframe pills, in time order.
 *
 * Hand-held rather than fetched, for the reason in the file header. Ordered by
 * duration, which the server's own sorted list is not.
 */
export const STANDARD_INTERVALS: readonly string[] = [
  '1m',
  '3m',
  '5m',
  '10m',
  '15m',
  '30m',
  '1h',
  '2h',
  '4h',
  'D',
  'W',
  'M',
  'Q',
  'Y',
]

const TOKEN = /^(\d+)([mhDWMQY])$/

/** Parse a token the way the server does, or null if it would return nothing. */
export function parseInterval(token: string): ParsedInterval | null {
  const raw = token?.trim()
  if (!raw) return null

  // The bare letters. `D` reads from storage; the rest aggregate from it.
  if (raw === 'D') return { unit: 'D', value: 1, source: 'D' }
  if (raw === 'W') return { unit: 'W', value: 1, source: 'D' }
  if (raw === 'M') return { unit: 'M', value: 1, source: 'D' }
  if (raw === 'Q') return { unit: 'Q', value: 1, source: 'D' }
  if (raw === 'Y') return { unit: 'Y', value: 1, source: 'D' }

  const match = TOKEN.exec(raw)
  if (!match) return null

  const value = Number(match[1])
  const unit = match[2] as IntervalUnit | 'D'
  if (!Number.isFinite(value) || value <= 0) return null

  // `<n>D` parses on the server and then reads a stored row that is never
  // written. Treat it as unsupported here rather than shipping a silent blank.
  if (unit === 'D') return null

  if (unit === 'm' || unit === 'h') return { unit, value, source: '1m' }
  return { unit, value, source: 'D' }
}

/**
 * Build a token from the custom builder's two fields.
 *
 * Returns null rather than a broken token when the pair cannot be expressed,
 * so a caller cannot accidentally request something that answers with silence.
 */
export function composeInterval(value: number | string, unit: IntervalUnit): string | null {
  const n = Math.floor(Number(value))
  if (!Number.isFinite(n) || n <= 0) return null

  // A single week, month, quarter or year is the bare letter. `1W` also works
  // on the server, but the bare form is what the standard pills use and one
  // spelling per timeframe keeps saved layouts comparable.
  if (unit !== 'm' && unit !== 'h') {
    return n === 1 ? unit : `${n}${unit}`
  }
  return `${n}${unit}`
}

/** Whether a token is intraday, which decides IST handling and session logic. */
export function isIntradayInterval(token: string): boolean {
  const parsed = parseInterval(token)
  return parsed?.source === '1m'
}

/**
 * The stored intervals present for one symbol, from catalog rows.
 *
 * Only `1m` and `D` are ever downloaded; everything else is computed from one
 * of them, so anything else in the catalog is not a usable source.
 */
export function storedSources(intervals: Iterable<string>): Set<SourceInterval> {
  const found = new Set<SourceInterval>()
  for (const interval of intervals) {
    if (interval === '1m') found.add('1m')
    else if (interval === 'D') found.add('D')
  }
  return found
}

/** Whether a token can return candles given what has been downloaded. */
export function isIntervalAvailable(token: string, stored: Set<SourceInterval>): boolean {
  const parsed = parseInterval(token)
  return parsed ? stored.has(parsed.source) : false
}

/** The standard pills worth showing for a symbol, given what it has stored. */
export function availableIntervals(stored: Set<SourceInterval>): string[] {
  return STANDARD_INTERVALS.filter((token) => isIntervalAvailable(token, stored))
}

/**
 * Why a timeframe cannot be drawn, written for a trader.
 *
 * Returns null when it can. The distinction that matters is the one a user
 * cannot guess: weekly and monthly candles are built from stored daily bars,
 * never from minute bars, so a symbol downloaded at 1m only shows nothing on
 * `W` however much data it has.
 */
export function unavailableReason(token: string, stored: Set<SourceInterval>): string | null {
  const parsed = parseInterval(token)
  if (!parsed) {
    return `${token} is not a timeframe this data store can build. Pick one from the list, or compose minutes, hours, weeks, months, quarters or years.`
  }
  if (stored.has(parsed.source)) return null

  if (parsed.source === '1m') {
    return 'This timeframe is built from 1 minute data, which has not been downloaded for this symbol. Download 1 minute data from Historify first.'
  }
  return 'Weekly, monthly, quarterly and yearly candles are built from daily data, which has not been downloaded for this symbol. Download daily data from Historify first.'
}
