// frontend/src/lib/pnlBuckets.ts
/**
 * Day, week and month buckets of a daily P&L series, for the bar charts and
 * tables of the P&L page (fork-only, SKYSHIELD_PATCHES.md). Pure: dates are
 * YYYY-MM-DD strings and all calendar maths is done in UTC, so the result never
 * depends on the viewer's time zone.
 */

export type BucketUnit = 'day' | 'week' | 'month'

export interface Bucket {
  /** Stable key: the date, the Monday of the week, or YYYY-MM. */
  key: string
  /** The first calendar day of the bucket, for a chart's time axis. */
  start: string
  label: string
  /** The series total over the bucket. */
  value: number
  /** Days of the series that fall in the bucket. */
  days: number
  /** Running total up to and including this bucket. */
  cumulative: number
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function parts(date: string): [number, number, number] {
  const [y, m, d] = date.split('-').map(Number)
  return [y, m, d]
}

/** The Monday of the ISO week containing `date`. */
export function weekStart(date: string): string {
  const [y, m, d] = parts(date)
  const dt = new Date(Date.UTC(y, m - 1, d))
  const offset = (dt.getUTCDay() + 6) % 7 // Monday = 0
  dt.setUTCDate(dt.getUTCDate() - offset)
  return dt.toISOString().slice(0, 10)
}

function label(unit: BucketUnit, key: string): string {
  if (unit === 'day') return key
  if (unit === 'week') {
    const [, m, d] = parts(key)
    return `Week of ${String(d).padStart(2, '0')} ${MONTHS[m - 1]}`
  }
  const [y, m] = parts(`${key}-01`)
  return `${MONTHS[m - 1]} ${y}`
}

function keyOf(unit: BucketUnit, date: string): { key: string; start: string } {
  if (unit === 'day') return { key: date, start: date }
  if (unit === 'week') {
    const start = weekStart(date)
    return { key: start, start }
  }
  const key = date.slice(0, 7)
  return { key, start: `${key}-01` }
}

/**
 * Group an ascending daily series into buckets. Idle days are simply absent, so
 * a bucket with no activity does not appear.
 */
export function bucketize(dates: string[], values: number[], unit: BucketUnit): Bucket[] {
  const out: Bucket[] = []
  const index = new Map<string, Bucket>()
  dates.forEach((date, i) => {
    const { key, start } = keyOf(unit, date)
    let bucket = index.get(key)
    if (!bucket) {
      bucket = { key, start, label: label(unit, key), value: 0, days: 0, cumulative: 0 }
      index.set(key, bucket)
      out.push(bucket)
    }
    bucket.value += values[i] ?? 0
    bucket.days += 1
  })
  let running = 0
  for (const bucket of out) {
    running += bucket.value
    bucket.cumulative = running
  }
  return out
}
