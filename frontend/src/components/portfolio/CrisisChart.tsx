/**
 * Crisis-period bars: portfolio against benchmark across historical stress windows.
 *
 * A diverging bar per period, benchmark drawn as a lighter outline behind the
 * portfolio's solid bar, so the comparison reads without a legend lookup. This
 * is the chart that turns "defensive" from a claim into a number — and it also
 * shows the cost of that defensiveness in the recoveries, which a
 * crashes-only view would flatter.
 */
interface CrisisPeriod {
  key: string
  label: string
  note?: string
  start: string
  end: string
  portfolio: number | null
  benchmark: number | null
  excess: number | null
  partial?: boolean
}

interface Props {
  periods: CrisisPeriod[]
}

export function CrisisChart({ periods }: Props) {
  const rows = periods.filter((p) => p.portfolio !== null)
  if (rows.length === 0) return null

  const values = rows.flatMap((p) =>
    [p.portfolio, p.benchmark].filter((v): v is number => v !== null)
  )
  const extent = Math.max(...values.map(Math.abs), 0.05)
  // Percentage of the track that one unit of return occupies, with the zero
  // line in the middle so gains and losses are directly comparable.
  const half = 50
  const pos = (v: number) => (v / extent) * half

  return (
    <div className="space-y-1">
      {rows.map((p) => {
        const port = p.portfolio ?? 0
        const bench = p.benchmark
        return (
          <div key={p.key} className="grid grid-cols-[11rem_1fr] items-center gap-3">
            <div className="truncate text-right text-xs" title={p.note || p.label}>
              {p.label}
              {p.partial && (
                <span className="ml-1 text-[10px] text-amber-500" title="only partly covered by this backtest">
                  partial
                </span>
              )}
            </div>

            <div className="relative h-7">
              {/* zero line */}
              <div className="absolute inset-y-0 left-1/2 w-px bg-border" />

              {/* benchmark, behind */}
              {bench !== null && (
                <div
                  className="absolute top-1 h-5 rounded-sm border border-dashed border-muted-foreground/50 bg-muted-foreground/10"
                  style={{
                    left: `${bench >= 0 ? half : half + pos(bench)}%`,
                    width: `${Math.abs(pos(bench))}%`,
                  }}
                />
              )}

              {/* portfolio, in front */}
              <div
                className={`absolute top-2 h-3 rounded-sm ${
                  port >= 0 ? 'bg-blue-500' : 'bg-rose-500'
                }`}
                style={{
                  left: `${port >= 0 ? half : half + pos(port)}%`,
                  width: `${Math.abs(pos(port))}%`,
                }}
              />

              <span
                className={`absolute top-1 text-xs tabular-nums ${
                  port >= 0 ? 'text-blue-500' : 'text-rose-500'
                }`}
                style={
                  port >= 0
                    ? { left: `calc(${half + Math.abs(pos(port))}% + 6px)` }
                    : { right: `calc(${half + Math.abs(pos(port))}% + 6px)` }
                }
              >
                {port >= 0 ? '+' : ''}
                {(port * 100).toFixed(1)}%
              </span>
            </div>
          </div>
        )
      })}
      <div className="flex justify-end gap-4 pt-2 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm bg-blue-500" /> Portfolio
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-4 rounded-sm border border-dashed border-muted-foreground/50 bg-muted-foreground/10" />
          Benchmark
        </span>
      </div>
    </div>
  )
}
