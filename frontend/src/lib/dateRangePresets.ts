// frontend/src/lib/dateRangePresets.ts
/**
 * Shared quick date-range presets for the P&L History and Trade Book
 * filter rows (fork-only). Used via <DateRangePresets> below.
 *
 * "Current week" is Monday of this week through today (not a rolling
 * 7-day window - that's the separate "Last 7 Days" preset). "Current
 * month" is the 1st of this month through today. Financial year follows
 * the Indian FY convention: Apr 1 - Mar 31. "Current FY" runs to today
 * (it isn't over yet); "Prev. FY" is the full closed year, Apr 1 to the
 * following Mar 31 - not truncated, since it already ended.
 */

// Deliberately NOT toISOString() - that converts to UTC, which rolls a
// local-midnight date (e.g. the 1st of the month, built via
// `new Date(year, month, day)`) back to the previous day for any
// timezone ahead of UTC, IST included. Building the string from local
// getters keeps every preset on the calendar day it actually means.
function toDateStr(d: Date): string {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

function addDays(base: Date, delta: number): Date {
  const d = new Date(base)
  d.setDate(d.getDate() + delta)
  return d
}

function startOfWeekMonday(base: Date): Date {
  const day = base.getDay() // 0=Sun..6=Sat
  const daysSinceMonday = day === 0 ? 6 : day - 1
  return addDays(base, -daysSinceMonday)
}

function startOfMonth(base: Date): Date {
  return new Date(base.getFullYear(), base.getMonth(), 1)
}

// The calendar year an Indian FY *starts* in - e.g. FY2026-27 (Apr 2026 -
// Mar 2027) has a start year of 2026. Before April, we're still in the FY
// that started the previous calendar year.
function currentFYStartYear(base: Date): number {
  return base.getMonth() >= 3 ? base.getFullYear() : base.getFullYear() - 1
}

export interface DateRange {
  start: string
  end: string
}

export interface DateRangePreset {
  key: string
  label: string
  range: () => DateRange
}

export const DATE_RANGE_PRESETS: DateRangePreset[] = [
  {
    key: 'prev_fy',
    label: 'Prev. FY',
    range: () => {
      const today = new Date()
      const fyStartYear = currentFYStartYear(today) - 1
      return {
        start: toDateStr(new Date(fyStartYear, 3, 1)),
        end: toDateStr(new Date(fyStartYear + 1, 2, 31)),
      }
    },
  },
  {
    key: 'current_fy',
    label: 'Current FY',
    range: () => {
      const today = new Date()
      const fyStartYear = currentFYStartYear(today)
      return { start: toDateStr(new Date(fyStartYear, 3, 1)), end: toDateStr(today) }
    },
  },
  {
    key: 'current_month',
    label: 'Current Month',
    range: () => {
      const today = new Date()
      return { start: toDateStr(startOfMonth(today)), end: toDateStr(today) }
    },
  },
  {
    key: 'current_week',
    label: 'Current Week',
    range: () => {
      const today = new Date()
      return { start: toDateStr(startOfWeekMonday(today)), end: toDateStr(today) }
    },
  },
]
