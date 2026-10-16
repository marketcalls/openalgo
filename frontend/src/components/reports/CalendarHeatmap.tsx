// frontend/src/components/reports/CalendarHeatmap.tsx
/**
 * Shared calendar heat map (fork-only, see openalgo's SKYSHIELD_PATCHES.md
 * and docs/design/56-pnl-history). Modeled on Zerodha Console's own two
 * report heat maps: the P&L report's green/red-by-realized-P&L map and the
 * Tradebook report's blue-by-trade-count map. Both are the same layout
 * with a different value + color function, so the layout lives here once
 * and each page supplies its own `days` and `colorFor`.
 *
 * Layout: 12 discrete month blocks (each its own small grid of week-
 * columns, Sun-Sat as rows, no weekday header), spread across the full
 * container width with the gaps between them growing to fill it -
 * confirmed against a real Zerodha Console screenshot, which shows
 * visible whitespace *between* months (not one continuous flowing strip)
 * and the whole row stretched to fill its pane rather than sitting
 * compact on the left. An earlier version tried a true continuous
 * GitHub-contributions-style strip (weeks shared across month
 * boundaries, no gaps) - replaced because side-by-side comparison with
 * the reference showed Zerodha's months are visually distinct blocks.
 *
 * Always a trailing 12-month frame ending at endDate's own month,
 * regardless of how narrow the actual searched/filtered range is
 * (confirmed Zerodha behavior) - days outside the real fetched range
 * still render, just very faint, so the frame's size never jumps around
 * between a 7-day and a 90-day search.
 */
import { useMemo } from 'react'

export interface CalendarHeatmapDay {
  date: string // YYYY-MM-DD
  value: number
  tooltip: string
}

interface CalendarHeatmapProps {
  days: CalendarHeatmapDay[]
  startDate: string
  endDate: string
  colorFor: (value: number, maxAbs: number) => string
}

function toUTCDateStr(year: number, month: number, day: number): string {
  return new Date(Date.UTC(year, month, day)).toISOString().split('T')[0]
}

function addUTCDays(dateStr: string, delta: number): string {
  const [y, m, d] = dateStr.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + delta)
  return dt.toISOString().split('T')[0]
}

function monthShortLabel(year: number, month: number): string {
  return new Date(Date.UTC(year, month, 1)).toLocaleString('en-US', {
    month: 'short',
    timeZone: 'UTC',
  })
}

interface MonthGroup {
  key: string
  label: string
  weeks: (string | null)[][] // each week: 7 entries, Sun..Sat, null = padding outside this month
}

/** One month's own week-columns, padded to whole weeks at both ends (like
 * a mini calendar) but not sharing columns with neighboring months - each
 * group is a self-contained block. */
function buildMonthGroups(endDate: string): MonthGroup[] {
  const [ey, em] = endDate.split('-').map(Number)
  const endIdx = ey * 12 + (em - 1)
  const startIdx = endIdx - 11

  const groups: MonthGroup[] = []
  for (let idx = startIdx; idx <= endIdx; idx++) {
    const year = Math.floor(idx / 12)
    const month = ((idx % 12) + 12) % 12
    const firstOfMonth = toUTCDateStr(year, month, 1)
    const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate()
    const lastOfMonth = toUTCDateStr(year, month, daysInMonth)
    const firstWeekday = new Date(`${firstOfMonth}T00:00:00Z`).getUTCDay()
    const gridStart = addUTCDays(firstOfMonth, -firstWeekday)

    const weeks: (string | null)[][] = []
    let cursor = gridStart
    while (cursor <= lastOfMonth) {
      const week: (string | null)[] = []
      for (let row = 0; row < 7; row++) {
        week.push(cursor >= firstOfMonth && cursor <= lastOfMonth ? cursor : null)
        cursor = addUTCDays(cursor, 1)
      }
      weeks.push(week)
    }

    groups.push({ key: `${year}-${month}`, label: monthShortLabel(year, month), weeks })
  }
  return groups
}

// Sized to match the Zerodha reference's visual weight (confirmed against
// a real screenshot) - the first pass at 9px/2px read as too compact and
// small next to it.
const CELL = 16
const GAP = 3

export function CalendarHeatmap({ days, startDate, endDate, colorFor }: CalendarHeatmapProps) {
  const dayMap = useMemo(() => new Map(days.map((d) => [d.date, d])), [days])
  const maxAbs = useMemo(() => Math.max(1, ...days.map((d) => Math.abs(d.value))), [days])
  const groups = useMemo(() => buildMonthGroups(endDate), [endDate])

  return (
    <div className="flex justify-between w-full">
      {groups.map((group) => (
        <div key={group.key} className="flex flex-col items-center gap-1">
          <div className="flex" style={{ gap: GAP }}>
            {group.weeks.map((week, colIdx) => (
              <div key={colIdx} className="flex flex-col" style={{ gap: GAP }}>
                {week.map((dateStr, rowIdx) => {
                  if (!dateStr) {
                    return <div key={rowIdx} style={{ width: CELL, height: CELL }} />
                  }
                  const inRange = dateStr >= startDate && dateStr <= endDate
                  const entry = inRange ? dayMap.get(dateStr) : undefined
                  const bg = !inRange
                    ? 'rgba(148, 163, 184, 0.08)'
                    : entry
                      ? colorFor(entry.value, maxAbs)
                      : 'rgba(148, 163, 184, 0.15)'
                  return (
                    <div
                      key={dateStr}
                      title={inRange ? (entry?.tooltip ?? `${dateStr}: no data`) : undefined}
                      className="rounded-sm"
                      style={{ width: CELL, height: CELL, backgroundColor: bg }}
                    />
                  )
                })}
              </div>
            ))}
          </div>
          <span className="text-[9px] text-muted-foreground whitespace-nowrap">{group.label}</span>
        </div>
      ))}
    </div>
  )
}
