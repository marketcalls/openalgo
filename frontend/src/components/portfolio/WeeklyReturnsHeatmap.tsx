/**
 * Weekly returns as a chip grid for one year at a time, each chip carrying its
 * own week-ending date.
 *
 * Fifty-two weeks across a table is unreadable at a glance; picking one year
 * and showing its actual calendar dates is what lets a reader place a bad
 * week against an event they remember, rather than against an ISO week
 * number nobody thinks in.
 */
import { useMemo, useState } from 'react'
import type { CurvePoint } from '@/api/portfolio'

interface Props {
  /** Week-ending return points, one per calendar week, across the whole backtest. */
  series: CurvePoint[]
}

const formatWeekEnding = (iso: string) =>
  new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', {
    month: 'short',
    day: '2-digit',
    timeZone: 'UTC',
  })

export function WeeklyReturnsHeatmap({ series }: Props) {
  const years = useMemo(
    () => Array.from(new Set(series.map((p) => p.date.slice(0, 4)))).sort(),
    [series]
  )
  const [year, setYear] = useState(years[years.length - 1] ?? '')

  // Fixed to the full dataset, not the visible year, so switching years does
  // not repaint a quiet year as dramatic simply because it is being viewed alone.
  const extent = Math.max(...series.map((p) => Math.abs(p.value)), 0.005)

  const cell = (v: number) => {
    const a = Math.min(Math.abs(v) / extent, 1) * 0.85
    return v >= 0 ? `rgba(34,197,94,${a})` : `rgba(239,68,68,${a})`
  }

  const rows = series.filter((p) => p.date.slice(0, 4) === year)

  if (years.length === 0) {
    return <p className="text-sm text-muted-foreground">Not enough history for weekly returns.</p>
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs text-muted-foreground">
          {rows.length} weeks &middot; week-ending return
        </p>
        <select
          value={year}
          onChange={(e) => setYear(e.target.value)}
          className="rounded-md border border-input bg-background px-2 py-1 text-sm"
        >
          {years.map((y) => (
            <option key={y} value={y}>
              {y}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap gap-1.5">
        {rows.map((p) => (
          <div
            key={p.date}
            title={`Week ending ${p.date}: ${(p.value * 100).toFixed(2)}%`}
            className="w-20 rounded-md border border-border/40 p-2 text-center"
            style={{ background: cell(p.value) }}
          >
            <div className="text-sm font-semibold tabular-nums">
              {(p.value * 100).toFixed(1)}
            </div>
            <div className="mt-0.5 text-[10px] text-muted-foreground">
              {formatWeekEnding(p.date)}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
