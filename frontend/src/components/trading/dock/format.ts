/**
 * How the dock prints a figure. Right-aligned tabular numbers are the
 * tables' job; this is what goes in the cell.
 */

const TWO_DP = new Intl.NumberFormat('en-IN', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
})

/** A price or a value: grouped, two decimals, no currency. */
export function fmt2(value: number): string {
  return TWO_DP.format(value)
}

/** A signed figure. The sign is always printed so colour is never the only cue. */
export function signed(value: number): string {
  if (value > 0) return `+${TWO_DP.format(value)}`
  if (value < 0) return `-${TWO_DP.format(Math.abs(value))}`
  return TWO_DP.format(0)
}

/** A signed whole quantity, for net positions. */
export function signedQty(value: number): string {
  const grouped = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 4 }).format(
    Math.abs(value)
  )
  if (value > 0) return `+${grouped}`
  if (value < 0) return `-${grouped}`
  return '0'
}

/** The direction a signed figure takes, for the emerald and rose the watchlist uses. */
export function direction(value: number): 'up' | 'down' | 'flat' {
  if (value > 0) return 'up'
  if (value < 0) return 'down'
  return 'flat'
}

/** The Date a broker timestamp names, in the shapes formatTime lists, or null. */
export function parseTimestamp(timestamp: string): Date | null {
  if (!timestamp) return null
  let date = new Date(timestamp)
  if (Number.isNaN(date.getTime())) {
    const norentm = timestamp.match(/^(\d{2}:\d{2}:\d{2})\s+(\d{2})-(\d{2})-(\d{4})$/)
    if (norentm) date = new Date(`${norentm[4]}-${norentm[3]}-${norentm[2]}T${norentm[1]}`)
  }
  if (Number.isNaN(date.getTime())) {
    const ddmmyyyy = timestamp.match(/^(\d{2})-(\d{2})-(\d{4})\s+(\d{2}:\d{2}:\d{2})$/)
    if (ddmmyyyy) date = new Date(`${ddmmyyyy[3]}-${ddmmyyyy[2]}-${ddmmyyyy[1]}T${ddmmyyyy[4]}`)
  }
  return Number.isNaN(date.getTime()) ? null : date
}

/**
 * A sortable instant for a broker timestamp: the epoch when the date is
 * readable, else seconds into the day when only a clock is, else null.
 * Books that carry only clocks are all from today, so the clock orders them.
 */
export function timeKey(timestamp: string): number | null {
  const date = parseTimestamp(timestamp)
  if (date !== null) return date.getTime()
  const clock = timestamp.match(/(\d{2}):(\d{2}):(\d{2})/)
  if (!clock) return null
  return Number(clock[1]) * 3600 + Number(clock[2]) * 60 + Number(clock[3])
}

/**
 * Wall-clock time out of a broker timestamp. Brokers disagree on the shape
 * (ISO, "HH:MM:SS DD-MM-YYYY", "DD-MM-YYYY HH:MM:SS"), so anything with a
 * readable clock in it yields the clock, and anything else is shown as sent.
 */
export function formatTime(timestamp: string): string {
  if (!timestamp) return '-'
  const date = parseTimestamp(timestamp)
  if (date === null) {
    const clock = timestamp.match(/(\d{2}:\d{2}:\d{2})/)
    return clock ? clock[1] : timestamp
  }
  return date.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}
