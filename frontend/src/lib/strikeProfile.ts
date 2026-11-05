/**
 * Pure helpers for the Strike Profile tool: the strike by expiry grid of gamma
 * exposure (GEX) and delta exposure (DEX).
 *
 * Kept out of the page so the reading rules (which rows show, which cells are
 * an expiry's peaks, how a value is written) are tested without rendering.
 */
import type { StrikeProfileCell, StrikeProfileExpiry } from '@/api/strike-profile'

export type Metric = 'gex' | 'dex'
export type PeakMode = 'all' | 'max' | 'off'
/** Percent either side of spot, or null for every loaded strike. */
export type StrikeRange = 2 | 5 | 10 | null

export const RANGES: StrikeRange[] = [2, 5, 10, null]

/**
 * Rank of a range by width, so a pane can tell whether the loaded window
 * already covers what it wants to show.
 */
export function rangeRank(range: StrikeRange): number {
  return range === null ? Number.POSITIVE_INFINITY : range
}

/** True when strikes loaded for `loaded` include every strike `wanted` shows. */
export function rangeCovered(wanted: StrikeRange, loaded: StrikeRange): boolean {
  return rangeRank(wanted) <= rangeRank(loaded)
}

/**
 * Write an exposure in rupees crore the way the grid shows it: 2.4K, 808,
 * 88.6, 0.5. The sign is kept; `signed` adds a plus to positive values.
 */
export function formatExposure(value: number, signed = false): string {
  if (!Number.isFinite(value)) return ''
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : signed && value > 0 ? '+' : ''
  let body: string
  if (abs >= 1e5) body = `${(abs / 1e5).toFixed(1)}L`
  else if (abs >= 1000) body = `${(abs / 1000).toFixed(1)}K`
  else if (abs >= 100) body = abs.toFixed(0)
  else body = abs.toFixed(1)
  // A value that rounds to zero carries no sign.
  if (/^0(\.0)?$/.test(body)) return body
  return `${sign}${body}`
}

/** Expiry code as the API takes it: 28-AUG-2026 or 28-AUG-26 becomes 28AUG26. */
export function toApiExpiry(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

/** Short column date from a DDMMMYY code: 21OCT26 becomes 21 Oct. */
export function shortExpiryLabel(code: string): string {
  const match = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(code)
  if (!match) return code
  const month = MONTHS.find((m) => m.toUpperCase() === match[2]) ?? match[2]
  return `${Number(match[1])} ${month}`
}

export function cellValue(
  cell: StrikeProfileCell | null | undefined,
  metric: Metric
): number | null {
  if (!cell) return null
  return metric === 'gex' ? cell.gex : cell.dex
}

/**
 * Indexes into `strikes` that fall within the range around spot, highest
 * strike first (the order the table reads, top to bottom).
 */
export function visibleStrikeIndexes(
  strikes: number[],
  spot: number,
  range: StrikeRange
): number[] {
  const out: number[] = []
  for (let i = strikes.length - 1; i >= 0; i--) {
    if (range === null || Math.abs(strikes[i] - spot) <= (spot * range) / 100) out.push(i)
  }
  return out
}

/** Index of the strike nearest spot, or -1 for an empty list. */
export function nearestStrikeIndex(strikes: number[], spot: number): number {
  let best = -1
  for (let i = 0; i < strikes.length; i++) {
    if (best < 0 || Math.abs(strikes[i] - spot) < Math.abs(strikes[best] - spot)) best = i
  }
  return best
}

/**
 * One expiry's peak cells among the rows shown.
 *
 * Raw exposure is not like for like across expiries: a strike on today's
 * expiry carries far more gamma than the same strike weeks out. Marking each
 * expiry's own peaks shows where that expiry concentrates, whatever its size.
 *
 * `all` marks the larger of the two in magnitude, and the other side too when
 * it holds at least PEAK_SIDE_SHARE of that magnitude, so a column that is
 * almost entirely one sign does not flag a near-zero cell on the other. `max`
 * marks only the larger of the two, `off` none.
 *
 * @returns Strike indexes of the peak cells.
 */
export function expiryPeaks(
  values: (number | null)[],
  rows: number[],
  mode: PeakMode
): Set<number> {
  const peaks = new Set<number>()
  if (mode === 'off') return peaks
  let high = -1
  let low = -1
  for (const i of rows) {
    const v = values[i]
    if (v === null || v === undefined) continue
    if (v > 0 && (high < 0 || v > (values[high] as number))) high = i
    if (v < 0 && (low < 0 || v < (values[low] as number))) low = i
  }
  const highAbs = high >= 0 ? Math.abs(values[high] as number) : -1
  const lowAbs = low >= 0 ? Math.abs(values[low] as number) : -1
  const [main, mainAbs, other, otherAbs] =
    highAbs >= lowAbs ? [high, highAbs, low, lowAbs] : [low, lowAbs, high, highAbs]
  if (main >= 0) peaks.add(main)
  if (mode === 'all' && other >= 0 && otherAbs >= mainAbs * PEAK_SIDE_SHARE) peaks.add(other)
  return peaks
}

/** Share of the stronger side's peak the weaker side needs to be marked under `all`. */
export const PEAK_SIDE_SHARE = 0.2

/** Sum of an expiry's values over the rows shown; null when it lists none of them. */
export function columnTotal(values: (number | null)[], rows: number[]): number | null {
  let total = 0
  let any = false
  for (const i of rows) {
    const v = values[i]
    if (v === null || v === undefined) continue
    total += v
    any = true
  }
  return any ? total : null
}

/** Largest magnitude among the given values, at least a tiny positive number. */
export function maxMagnitude(values: Iterable<number | null>): number {
  let max = 0
  for (const v of values) {
    if (v !== null && Number.isFinite(v)) max = Math.max(max, Math.abs(v))
  }
  return max || 1e-9
}

/**
 * Shade strength for a cell, 0 to 1. Square root so that mid-sized cells stay
 * visible next to one dominant strike.
 */
export function shadeStrength(value: number, max: number): number {
  if (!max || !Number.isFinite(value)) return 0
  return Math.min(1, Math.sqrt(Math.abs(value) / max))
}

/** Column heading for an expiry: "3 DTE" over "21 Oct". */
export function expiryHeading(expiry: StrikeProfileExpiry): { dte: string; date: string } {
  return {
    dte: expiry.dte === null || expiry.dte === undefined ? 'n/a' : `${expiry.dte} DTE`,
    date: shortExpiryLabel(expiry.expiry),
  }
}
