/**
 * Month-by-month returns grid — years down, months across.
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
    const a = Math.min(Math.abs(v) / extent, 1) * 0.8
    return v >= 0 ? `rgba(34,197,94,${a})` : `rgba(239,68,68,${a})`
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full border-separate border-spacing-0.5 text-xs">
        <thead>
          <tr>
            <th className="p-1 text-left font-medium text-muted-foreground">Year</th>
            {columns.map((c) => (
              <th
                key={c}
                className={`p-1 text-center font-medium text-muted-foreground ${
                  c === 'EOY' ? 'border-l' : ''
                }`}
              >
                {c}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((y, i) => (
            <tr key={y}>
              <td className="p-1 font-medium text-muted-foreground">{y}</td>
              {columns.map((c, j) => {
                const v = values[i]?.[j] ?? null
                return (
                  <td
                    key={c}
                    className={`min-w-12 rounded p-1.5 text-center tabular-nums ${
                      c === 'EOY' ? 'font-semibold' : ''
                    }`}
                    style={{ background: cell(v) }}
                  >
                    {v === null || Number.isNaN(v) ? '' : `${(v * 100).toFixed(1)}%`}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
