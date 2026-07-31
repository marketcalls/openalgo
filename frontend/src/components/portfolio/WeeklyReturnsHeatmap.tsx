/**
 * Weekly returns grid — years down, ISO weeks across, with a year selector.
 *
 * Fifty-two columns is a lot to read at once, so a year can be picked out of
 * it. The colour scale stays fixed to the whole dataset when filtering, so a
 * quiet year does not repaint itself as dramatic simply because it is being
 * viewed alone.
 */
import { useState } from 'react'
import { cn } from '@/lib/utils'

interface Props {
  years: string[]
  weeks: number[]
  /** Fractions (0.026 = 2.6%), null where that week has no data. */
  values: (number | null)[][]
}

export function WeeklyReturnsHeatmap({ years, weeks, values }: Props) {
  const [selected, setSelected] = useState<string>('All')

  const flat = values.flat().filter((v): v is number => v !== null)
  // Fixed to the full dataset, not the visible slice.
  const extent = Math.max(...flat.map(Math.abs), 0.005)

  const cell = (v: number | null) => {
    if (v === null || Number.isNaN(v)) return 'transparent'
    const a = Math.min(Math.abs(v) / extent, 1) * 0.8
    return v >= 0 ? `rgba(34,197,94,${a})` : `rgba(239,68,68,${a})`
  }

  const rows = years
    .map((y, i) => ({ year: y, row: values[i] ?? [] }))
    .filter((r) => selected === 'All' || r.year === selected)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {['All', ...years].map((y) => (
          <button
            key={y}
            type="button"
            onClick={() => setSelected(y)}
            className={cn(
              'rounded px-2.5 py-1 text-xs transition-colors',
              selected === y
                ? 'bg-primary/15 text-primary ring-1 ring-primary/40'
                : 'text-muted-foreground hover:bg-accent'
            )}
          >
            {y}
          </button>
        ))}
      </div>

      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-px text-[10px]">
          <thead>
            <tr>
              <th className="sticky left-0 bg-background p-1 text-left font-medium text-muted-foreground">
                Year
              </th>
              {weeks.map((w) => (
                <th key={w} className="p-1 text-center font-medium text-muted-foreground">
                  {w}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ year, row }) => (
              <tr key={year}>
                <td className="sticky left-0 bg-background p-1 font-medium text-muted-foreground">
                  {year}
                </td>
                {weeks.map((w, j) => {
                  const v = row[j] ?? null
                  return (
                    <td
                      key={w}
                      title={
                        v === null ? `W${w}: no data` : `${year} W${w}: ${(v * 100).toFixed(2)}%`
                      }
                      className="min-w-7 rounded-sm p-1 text-center tabular-nums"
                      style={{ background: cell(v) }}
                    >
                      {v === null || Number.isNaN(v) ? '' : (v * 100).toFixed(1)}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-muted-foreground">
        ISO week numbers. Values are percent; hover a cell for the exact figure.
      </p>
    </div>
  )
}
