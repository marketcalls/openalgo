// frontend/src/lib/pnlCurve.ts
/**
 * Pure maths for the P&L Curve page (fork-only, see SKYSHIELD_PATCHES.md):
 * daily and cumulative realized P&L, drawdown, summary statistics and the
 * monthly table, from the closed lots GET /api/v1/pnl/history returns. No I/O
 * and no React, so every figure on the page is covered by tests.
 *
 * Everything is by the day a lot was closed out (its exit date), the same
 * basis as the P&L History day-wise table. A lot's strategy is the strategy
 * of the fill that opened it; a lot with none is "Untagged".
 */

export const UNTAGGED = 'Untagged'

export interface CurveLot {
  exit_timestamp: string
  realized_pnl: number
  strategy: string | null
  /** Present on lots from /pnl/history; used by the page-level Filters dialog. */
  symbol?: string
  exchange?: string
  product?: string | null
}

export interface DailySeries {
  /** Ascending YYYY-MM-DD dates on which at least one lot closed. */
  dates: string[]
  /** Daily P&L over all lots, aligned to `dates`. */
  total: number[]
  /** Daily P&L per strategy, each aligned to `dates` (zero on idle days). */
  byStrategy: Map<string, number[]>
}

export function strategyOf(lot: CurveLot): string {
  return lot.strategy || UNTAGGED
}

export function dailySeries(lots: CurveLot[]): DailySeries {
  const perDay = new Map<string, Map<string, number>>()
  for (const lot of lots) {
    const date = lot.exit_timestamp.slice(0, 10)
    const strategy = strategyOf(lot)
    const day = perDay.get(date) ?? new Map<string, number>()
    day.set(strategy, (day.get(strategy) ?? 0) + lot.realized_pnl)
    perDay.set(date, day)
  }

  const dates = Array.from(perDay.keys()).sort()
  const names = new Set<string>()
  for (const day of perDay.values()) for (const name of day.keys()) names.add(name)

  const byStrategy = new Map<string, number[]>()
  for (const name of names) {
    byStrategy.set(
      name,
      dates.map((date) => perDay.get(date)?.get(name) ?? 0)
    )
  }
  const total = dates.map((date) => {
    let sum = 0
    for (const value of perDay.get(date)?.values() ?? []) sum += value
    return sum
  })
  return { dates, total, byStrategy }
}

export function cumulative(daily: number[]): number[] {
  let running = 0
  return daily.map((value) => {
    running += value
    return running
  })
}

export interface MaxDrawdown {
  /** Negative or zero: the deepest fall from a running peak. */
  depth: number
  /** Date of the peak the fall started from; null when it started from the first day's start (zero). */
  peakDate: string | null
  troughDate: string | null
  /** First date the curve got back to the peak; null while still under water. */
  recoveryDate: string | null
  /** Calendar days from the peak (or the first date) to recovery, or to the last date if not recovered. */
  days: number
}

export interface DrawdownResult {
  /** Drawdown from the running peak at every date, zero or negative. */
  series: number[]
  max: MaxDrawdown
}

function dayDiff(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000)
}

/** The curve starts at zero before the first date, so the first peak is zero. */
export function drawdown(dates: string[], cum: number[]): DrawdownResult {
  const series: number[] = []
  let peak = 0
  let peakDate: string | null = null
  let worst = 0
  let worstPeakDate: string | null = null
  let worstPeakValue = 0
  let worstTroughIdx = -1

  cum.forEach((value, i) => {
    if (value > peak) {
      peak = value
      peakDate = dates[i]
    }
    const depth = value - peak
    series.push(depth)
    if (depth < worst) {
      worst = depth
      worstPeakDate = peakDate
      worstPeakValue = peak
      worstTroughIdx = i
    }
  })

  if (worstTroughIdx < 0) {
    return {
      series,
      max: { depth: 0, peakDate: null, troughDate: null, recoveryDate: null, days: 0 },
    }
  }

  let recoveryDate: string | null = null
  for (let i = worstTroughIdx + 1; i < cum.length; i++) {
    if (cum[i] >= worstPeakValue) {
      recoveryDate = dates[i]
      break
    }
  }
  const startDate = worstPeakDate ?? dates[0]
  const endDate = recoveryDate ?? dates[dates.length - 1]
  return {
    series,
    max: {
      depth: worst,
      peakDate: worstPeakDate,
      troughDate: dates[worstTroughIdx],
      recoveryDate,
      days: dayDiff(startDate, endDate),
    },
  }
}

export interface CurrentDrawdown {
  /** Zero or negative: how far below the running peak the curve is on its last date. */
  depth: number
  /** The running peak and the date it was set; null while the peak is still the start (zero). */
  peakValue: number
  peakDate: string | null
  /** Calendar days from the peak to the last date; 0 at a new high. */
  daysSincePeak: number
  atHigh: boolean
}

/** Where the curve stands now against its own running peak. */
export function currentDrawdown(dates: string[], cum: number[]): CurrentDrawdown {
  let peak = 0
  let peakDate: string | null = null
  cum.forEach((value, i) => {
    if (value > peak) {
      peak = value
      peakDate = dates[i]
    }
  })
  if (cum.length === 0) {
    return { depth: 0, peakValue: 0, peakDate: null, daysSincePeak: 0, atHigh: true }
  }
  const last = cum[cum.length - 1]
  const depth = last - peak
  const lastDate = dates[dates.length - 1]
  const from = peakDate ?? dates[0]
  return {
    depth,
    peakValue: peak,
    peakDate,
    daysSincePeak: depth < 0 ? dayDiff(from, lastDate) : 0,
    atHigh: depth >= 0,
  }
}

/** The deepest drawdown seen so far on each date (a running minimum, never rises). */
export function runningMaxDrawdown(series: number[]): number[] {
  let worst = 0
  return series.map((value) => {
    if (value < worst) worst = value
    return worst
  })
}

export interface DayExtreme {
  date: string
  value: number
}

export interface CurveStats {
  netPnl: number
  /** Days on which at least one lot closed. */
  activeDays: number
  winDays: number
  lossDays: number
  /** Win days over win plus loss days; null with no decided day. */
  winRate: number | null
  avgWinDay: number | null
  avgLossDay: number | null
  /** Sum of winning days over the absolute sum of losing days; null with no losing day. */
  profitFactor: number | null
  bestDay: DayExtreme | null
  worstDay: DayExtreme | null
  longestWinStreak: number
  longestLossStreak: number
}

export function stats(dates: string[], daily: number[]): CurveStats {
  let netPnl = 0
  let winSum = 0
  let lossSum = 0
  let winDays = 0
  let lossDays = 0
  let best: DayExtreme | null = null
  let worst: DayExtreme | null = null
  let winStreak = 0
  let lossStreak = 0
  let longestWin = 0
  let longestLoss = 0

  daily.forEach((value, i) => {
    netPnl += value
    if (best === null || value > best.value) best = { date: dates[i], value }
    if (worst === null || value < worst.value) worst = { date: dates[i], value }
    if (value > 0) {
      winDays += 1
      winSum += value
      winStreak += 1
      lossStreak = 0
    } else if (value < 0) {
      lossDays += 1
      lossSum += value
      lossStreak += 1
      winStreak = 0
    } else {
      winStreak = 0
      lossStreak = 0
    }
    longestWin = Math.max(longestWin, winStreak)
    longestLoss = Math.max(longestLoss, lossStreak)
  })

  const decided = winDays + lossDays
  return {
    netPnl,
    activeDays: daily.length,
    winDays,
    lossDays,
    winRate: decided > 0 ? winDays / decided : null,
    avgWinDay: winDays > 0 ? winSum / winDays : null,
    avgLossDay: lossDays > 0 ? lossSum / lossDays : null,
    profitFactor: lossDays > 0 ? winSum / Math.abs(lossSum) : null,
    bestDay: best,
    worstDay: worst,
    longestWinStreak: longestWin,
    longestLossStreak: longestLoss,
  }
}

export interface MonthlyRow {
  year: number
  /** January to December; null for a month with no closed lot. */
  months: (number | null)[]
  total: number
}

export function monthly(dates: string[], daily: number[]): MonthlyRow[] {
  const byYear = new Map<number, (number | null)[]>()
  dates.forEach((date, i) => {
    const year = Number(date.slice(0, 4))
    const month = Number(date.slice(5, 7)) - 1
    const row = byYear.get(year) ?? new Array<number | null>(12).fill(null)
    row[month] = (row[month] ?? 0) + daily[i]
    byYear.set(year, row)
  })
  return Array.from(byYear.entries())
    .sort((a, b) => a[0] - b[0])
    .map(([year, months]) => ({
      year,
      months,
      total: months.reduce<number>((sum, value) => sum + (value ?? 0), 0),
    }))
}

export interface StrategySummary {
  strategy: string
  netPnl: number
  maxDrawdown: number
  winRate: number | null
  profitFactor: number | null
  activeDays: number
}

/** One row per strategy, each judged on its own days. */
export function strategySummaries(series: DailySeries): StrategySummary[] {
  const rows: StrategySummary[] = []
  for (const [strategy, daily] of series.byStrategy) {
    // Only the days this strategy closed something: an idle zero is not a day.
    const dates: string[] = []
    const active: number[] = []
    daily.forEach((value, i) => {
      if (value !== 0) {
        dates.push(series.dates[i])
        active.push(value)
      }
    })
    const summary = stats(dates, active)
    rows.push({
      strategy,
      netPnl: summary.netPnl,
      maxDrawdown: drawdown(dates, cumulative(active)).max.depth,
      winRate: summary.winRate,
      profitFactor: summary.profitFactor,
      activeDays: summary.activeDays,
    })
  }
  return rows.sort((a, b) => b.netPnl - a.netPnl)
}

// ---------------------------------------------------------------------------
// Daily realized + unrealized curve (equity), from GET /api/v1/pnl/curve.
// ---------------------------------------------------------------------------

export type CurveMode = 'realized' | 'unrealized' | 'combined'

export interface CurveStrategySeries {
  /** Realized on each day (a daily amount). */
  realized: number[]
  /** Open lots valued at each day's close (a level). */
  unrealized: number[]
}

export interface CurveNotes {
  orphan_sells: { symbol: string; date: string }[]
  missing_close: string[]
  missing_base: string[]
  calendar?: string
}

export interface CurveData {
  dates: string[]
  by_strategy: Record<string, CurveStrategySeries>
  basis: string
  base_date: string | null
  notes: CurveNotes
}

export const OTHER_STRATEGY = 'Other'

/**
 * Keep the first `maxNames` strategies (sorted by name) and fold the rest into
 * "Other"; "Untagged" stays its own series. Returns the kept names in colour
 * order and every series by display name.
 */
export function foldCurveStrategies(
  byStrategy: Record<string, CurveStrategySeries>,
  maxNames: number
): { names: string[]; byName: Map<string, CurveStrategySeries> } {
  const all = Object.keys(byStrategy)
    .filter((n) => n !== UNTAGGED)
    .sort()
  const kept = all.slice(0, maxNames)
  const byName = new Map<string, CurveStrategySeries>()

  const add = (name: string, series: CurveStrategySeries) => {
    const existing = byName.get(name)
    if (!existing) {
      byName.set(name, { realized: [...series.realized], unrealized: [...series.unrealized] })
      return
    }
    series.realized.forEach((v, i) => {
      existing.realized[i] += v
    })
    series.unrealized.forEach((v, i) => {
      existing.unrealized[i] += v
    })
  }

  for (const name of all) add(kept.includes(name) ? name : OTHER_STRATEGY, byStrategy[name])
  if (byStrategy[UNTAGGED]) add(UNTAGGED, byStrategy[UNTAGGED])
  return { names: kept, byName }
}

/** One strategy's daily change for the chosen mode; cumulating it gives the curve. */
function dailyChange(series: CurveStrategySeries, mode: CurveMode): number[] {
  return series.realized.map((realized, i) => {
    const level = series.unrealized[i]
    const step = level - (i > 0 ? series.unrealized[i - 1] : 0)
    if (mode === 'realized') return realized
    if (mode === 'unrealized') return step
    return realized + step
  })
}

/**
 * The page's DailySeries for a curve: total and per strategy as daily changes,
 * so cumulative(), drawdown(), stats() and monthly() work on it unchanged.
 * `include` picks the selected strategies; the total is theirs alone.
 */
export function curveSeries(
  dates: string[],
  byName: Map<string, CurveStrategySeries>,
  mode: CurveMode,
  include: (name: string) => boolean = () => true
): DailySeries {
  const total = dates.map(() => 0)
  const byStrategy = new Map<string, number[]>()
  for (const [name, series] of byName) {
    if (!include(name)) continue
    const change = dailyChange(series, mode)
    byStrategy.set(name, change)
    change.forEach((v, i) => {
      total[i] += v
    })
  }
  return { dates, total, byStrategy }
}
