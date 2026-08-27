/**
 * EOY returns: portfolio against benchmark, one pair of bars per calendar year.
 *
 * The table beside this carries more detail, but a table cannot show shape —
 * that one year did most of the work, or that the portfolio and the index
 * diverged only in the years that mattered. Grouped bars make both obvious at a
 * glance, which is why every tearsheet has this chart.
 *
 * The dashed red line is the portfolio's own average year, so a run of
 * mediocre years next to one spectacular one reads as exactly that rather than
 * averaging into a comfortable-looking number.
 */
interface YearRow {
  year: string
  portfolio: number | null
  benchmark?: number | null
  difference?: number | null
  won?: boolean
}

interface Props {
  rows: YearRow[]
  benchmarkLabel?: string
  height?: number
}

export function EoyChart({ rows, benchmarkLabel = 'Benchmark', height = 300 }: Props) {
  const years = rows.filter((r) => r.portfolio !== null)
  if (years.length === 0) return null

  const values = years.flatMap((r) =>
    [r.portfolio, r.benchmark].filter((v): v is number => v !== null && v !== undefined)
  )
  const hi = Math.max(...values, 0)
  const lo = Math.min(...values, 0)
  // Round the axis outward to a sensible step so the gridlines land on
  // readable numbers rather than on the data's exact extremes.
  const step = Math.max(0.05, Math.ceil(Math.max(Math.abs(hi), Math.abs(lo)) / 4 / 0.05) * 0.05)
  const top = Math.ceil(hi / step) * step || step
  const bottom = Math.floor(lo / step) * step
  const range = top - bottom || 1

  const y = (v: number) => ((top - v) / range) * 100
  const zero = y(0)
  const average =
    years.reduce((sum, r) => sum + (r.portfolio ?? 0), 0) / years.length

  const ticks: number[] = []
  for (let v = bottom; v <= top + 1e-9; v += step) ticks.push(Number(v.toFixed(4)))

  const slot = 100 / years.length
  const barW = slot * 0.32

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-end gap-4 text-xs">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-amber-400" />
          {benchmarkLabel}
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 rounded-sm bg-blue-500" />
          Portfolio
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-px w-4 border-t border-dashed border-rose-500" />
          average year
        </span>
      </div>

      <div className="relative pl-12" style={{ height }}>
        {/* Y axis */}
        <div className="pointer-events-none absolute inset-y-0 left-0 w-11">
          {ticks.map((t) => (
            <span
              key={t}
              className="absolute right-1 -translate-y-1/2 text-[10px] tabular-nums text-muted-foreground"
              style={{ top: `${y(t)}%` }}
            >
              {(t * 100).toFixed(0)}%
            </span>
          ))}
        </div>

        <svg
          viewBox="0 0 100 100"
          preserveAspectRatio="none"
          className="h-full w-full overflow-visible"
          role="img"
          aria-label="End-of-year returns against the benchmark"
        >
          <title>Portfolio and benchmark return for each calendar year</title>

          {ticks.map((t) => (
            <line
              key={t}
              x1="0"
              x2="100"
              y1={y(t)}
              y2={y(t)}
              stroke="currentColor"
              strokeWidth="0.15"
              vectorEffect="non-scaling-stroke"
              className="text-border"
            />
          ))}

          {/* Zero, and the portfolio's average year */}
          <line
            x1="0"
            x2="100"
            y1={zero}
            y2={zero}
            stroke="currentColor"
            strokeWidth="0.4"
            strokeDasharray="2 2"
            vectorEffect="non-scaling-stroke"
            className="text-foreground/70"
          />
          <line
            x1="0"
            x2="100"
            y1={y(average)}
            y2={y(average)}
            stroke="#f43f5e"
            strokeWidth="0.4"
            strokeDasharray="3 2"
            vectorEffect="non-scaling-stroke"
          />

          {years.map((r, i) => {
            const centre = i * slot + slot / 2
            const bars: { v: number; x: number; fill: string; label: string }[] = []
            if (r.benchmark !== null && r.benchmark !== undefined) {
              bars.push({
                v: r.benchmark,
                x: centre - barW - 0.6,
                fill: '#fbbf24',
                label: benchmarkLabel,
              })
            }
            bars.push({
              v: r.portfolio ?? 0,
              x: centre + 0.6,
              fill: '#3b82f6',
              label: 'Portfolio',
            })
            return bars.map((b) => (
              <rect
                key={`${r.year}-${b.label}`}
                x={b.x}
                width={barW}
                y={b.v >= 0 ? y(b.v) : zero}
                height={Math.abs(y(b.v) - zero)}
                fill={b.fill}
              >
                <title>{`${r.year} ${b.label}: ${(b.v * 100).toFixed(2)}%`}</title>
              </rect>
            ))
          })}
        </svg>
      </div>

      {/* X axis */}
      <div className="flex pl-12">
        {years.map((r) => (
          <span
            key={r.year}
            className="flex-1 text-center text-[10px] tabular-nums text-muted-foreground"
          >
            {r.year}
          </span>
        ))}
      </div>
    </div>
  )
}
