/**
 * Month-by-month returns grid — years down, months across, one chip per cell.
 *
 * This is how an investor actually reads a track record: not "CAGR 18%" but
 * "which months hurt, and did the bad ones cluster". A single annualised
 * number cannot show a run of four negative months, and that run is what makes
 * people abandon a strategy.
 */
interface Props {
  years: string[]
  columns: string[]
  /**
   * Fractions as openstatz returns them (0.1728 = 17.28%), null where the
   * month is absent. Not percentages -- formatting them as though they were
   * showed a 17% year as '0.2%'.
   */
  values: (number | null)[][]
}

export function MonthlyReturnsHeatmap({ years, columns, values }: Props) {
  const flat = values.flat().filter((v): v is number => v !== null)
  // Scale colour to the data's own worst move, so a calm portfolio is not
  // washed out and a violent one is not saturated.
  const extent = Math.max(...flat.map(Math.abs), 0.01)

  const cell = (v: number | null) => {
    if (v === null || Number.isNaN(v)) return 'transparent'
    const a = Math.min(Math.abs(v) / extent, 1) * 0.85
    return v >= 0 ? `rgba(34,197,94,${a})` : `rgba(239,68,68,${a})`
  }

  return (
    <div className="overflow-x-auto">
      <div
        className="grid gap-1"
        style={{ gridTemplateColumns: `3rem repeat(${columns.length}, minmax(2.5rem, 1fr))` }}
      >
        <div />
        {columns.map((c, i) => (
          <div
            key={`${c}-${i}`}
            className="pb-1 text-center text-xs font-medium text-muted-foreground"
          >
            {c.charAt(0)}
          </div>
        ))}

        {years.map((y, i) => (
          <div key={y} className="contents">
            <div className="flex items-center text-xs font-medium text-muted-foreground">
              {y}
            </div>
            {columns.map((c, j) => {
              const v = values[i]?.[j] ?? null
              return (
                <div
                  key={`${y}-${c}-${j}`}
                  className="rounded-md border border-border/40 p-2 text-center text-xs tabular-nums"
                  style={{ background: cell(v) }}
                >
                  {v === null || Number.isNaN(v) ? '' : (v * 100).toFixed(1)}
                </div>
              )
            })}
          </div>
        ))}
      </div>
    </div>
  )
}
