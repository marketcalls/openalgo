/**
 * Portfolio allocation over time — a stacked area of weights, 0 to 100%.
 *
 * The headline return hides what an investor most needs to see: a 60/40
 * portfolio that was never rebalanced does not stay 60/40, and by the end it
 * may be a different portfolio from the one they chose. Bands that visibly
 * widen and snap back on rebalance dates make that concrete in a way a final
 * weight column cannot.
 *
 * There is no cash band because the engine is long-only and fully invested —
 * weights always sum to 1. Drawing a flat zero would imply a capability that
 * does not exist.
 */
import { useState } from 'react'

interface Props {
  dates: string[]
  symbols: string[]
  series: Record<string, number[]>
  average: Record<string, number>
  height?: number
}

// Distinct at a glance, and stable per position so a symbol keeps its colour
// between the chart and the legend.
const PALETTE = [
  '#3b82f6', '#f59e0b', '#14b8a6', '#ef4444', '#22c55e',
  '#a855f7', '#06b6d4', '#f97316', '#84cc16', '#ec4899',
]

export function AllocationChart({
  dates,
  symbols,
  series,
  average,
  height = 300,
}: Props) {
  const [hover, setHover] = useState<number | null>(null)
  if (dates.length === 0 || symbols.length === 0) return null

  const n = dates.length
  const x = (i: number) => (i / Math.max(n - 1, 1)) * 100

  // Cumulative bands, bottom to top. Each area is drawn as its own closed
  // polygon between the running total below it and above it.
  let running = new Array(n).fill(0)
  const bands = symbols.map((symbol, s) => {
    const values = series[symbol] ?? new Array(n).fill(0)
    const lower = running
    const upper = lower.map((v, i) => v + (values[i] ?? 0))
    running = upper
    const top = upper.map((v, i) => `${x(i).toFixed(3)},${(100 - v * 100).toFixed(3)}`)
    const bottom = lower
      .map((v, i) => `${x(i).toFixed(3)},${(100 - v * 100).toFixed(3)}`)
      .reverse()
    return {
      symbol,
      colour: PALETTE[s % PALETTE.length],
      points: [...top, ...bottom].join(' '),
    }
  })

  return (
    <div className="space-y-2">
      <div className="flex items-start gap-4">
        <div className="relative flex-1" style={{ height }}>
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="h-full w-full"
            role="img"
            aria-label="Portfolio allocation over time"
            onMouseLeave={() => setHover(null)}
            onMouseMove={(e) => {
              const rect = e.currentTarget.getBoundingClientRect()
              const frac = (e.clientX - rect.left) / rect.width
              setHover(Math.min(n - 1, Math.max(0, Math.round(frac * (n - 1)))))
            }}
          >
            <title>Weight of each holding over the backtest</title>
            {bands.map((b) => (
              <polygon key={b.symbol} points={b.points} fill={b.colour} fillOpacity={0.85} />
            ))}
            {hover !== null && (
              <line
                x1={x(hover)}
                x2={x(hover)}
                y1={0}
                y2={100}
                stroke="currentColor"
                strokeWidth={0.3}
                vectorEffect="non-scaling-stroke"
                className="text-foreground/60"
              />
            )}
          </svg>
          <div className="pointer-events-none absolute inset-y-0 -left-9 flex w-8 flex-col justify-between text-[10px] text-muted-foreground">
            <span>100%</span>
            <span>50%</span>
            <span>0%</span>
          </div>
        </div>

        <div className="w-40 shrink-0 space-y-1 text-xs">
          {symbols.map((s, i) => (
            <div key={s} className="flex items-center gap-1.5">
              <span
                className="inline-block h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ background: PALETTE[i % PALETTE.length] }}
              />
              <span className="truncate">{s}</span>
              <span className="ml-auto tabular-nums text-muted-foreground">
                {hover !== null
                  ? `${((series[s]?.[hover] ?? 0) * 100).toFixed(1)}%`
                  : `${((average[s] ?? 0) * 100).toFixed(1)}%`}
              </span>
            </div>
          ))}
          <div className="border-t pt-1 text-[10px] text-muted-foreground">
            {hover !== null ? dates[hover] : 'average weight'}
          </div>
        </div>
      </div>

      <div className="flex justify-between text-[10px] text-muted-foreground">
        <span>{dates[0]}</span>
        <span>{dates[dates.length - 1]}</span>
      </div>
    </div>
  )
}
