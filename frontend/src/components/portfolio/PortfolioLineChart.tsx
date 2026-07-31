/**
 * Interactive line/area chart for the backtest report, on openalgo-charts.
 *
 * Replaces a static SVG: an equity curve is something an investor reads by
 * pointing at it — "what was I worth in March 2022", "how deep was that dip" —
 * and a picture cannot answer either. The engine gives crosshair, tooltip,
 * zoom and pan for free, and it is the same renderer the trading terminal uses,
 * so the two look and behave alike.
 */
import { useEffect, useRef, useState } from 'react'
import { createChart } from 'openalgo-charts'
import { buildChartTheme } from '@/lib/trading/chartTheme'
import { useThemeStore } from '@/stores/themeStore'

export interface SeriesSpec {
  name: string
  color: string
  data: { date: string; value: number }[]
  /** Fill under the line — right for a single equity curve, wrong for a pair. */
  area?: boolean
}

interface Props {
  series: SeriesSpec[]
  height?: number
  /** Formats the crosshair readout; defaults to a plain number. */
  format?: (v: number) => string
}

/** ISO date -> epoch seconds, which is what the chart indexes on. */
const toEpoch = (iso: string) => Math.floor(new Date(`${iso}T00:00:00Z`).getTime() / 1000)

export function PortfolioLineChart({ series, height = 320, format }: Props) {
  const holder = useRef<HTMLDivElement>(null)
  const [readout, setReadout] = useState<{ label: string; values: string[] } | null>(null)
  const { mode, appMode } = useThemeStore()

  useEffect(() => {
    const el = holder.current
    if (!el || series.length === 0) return

    // The terminal's own theme builder, so the report and the trading chart
    // are the same chart wearing the same colours.
    // No height option: the engine sizes itself to its container, which the
    // wrapper below fixes.
    const chart = createChart(el, { theme: buildChartTheme(mode, appMode) })

    const handles = series.map((s) =>
      chart.addSeries(s.area ? 'area' : 'line', {
        style: { color: s.color, lineWidth: 2, topColor: `${s.color}33`, bottomColor: `${s.color}00` },
      })
    )

    series.forEach((s, i) => {
      handles[i].setData(
        s.data.map((p) => ({ time: toEpoch(p.date), value: p.value, close: p.value }))
      )
    })

    const longest = series.reduce((a, b) => (a.data.length >= b.data.length ? a : b))
    chart.timeScale.fitContent(longest.data.length)

    // Crosshair readout. The chart is canvas-only and ships no DOM, so the
    // label is ours to render — which also keeps it styled like the rest of
    // the page rather than like a chart library.
    chart.subscribeCrosshairMove((e) => {
      const i = e.index
      if (i === null || i < 0 || i >= longest.data.length) {
        setReadout(null)
        return
      }
      setReadout({
        label: longest.data[i]?.date ?? '',
        values: series.map((s) => {
          const v = s.data[i]?.value
          return v === undefined ? '-' : format ? format(v) : v.toFixed(2)
        }),
      })
    })

    // The engine tracks its own container size, so there is no resize call to
    // make here; destroying it on unmount is the whole cleanup.
    return () => chart.destroy()
  }, [series, format, mode, appMode])

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-4 text-xs">
        {series.map((s, i) => (
          <span key={s.name} className="flex items-center gap-1.5">
            <span
              className="inline-block h-2 w-2 rounded-sm"
              style={{ background: s.color }}
            />
            <span className="text-muted-foreground">{s.name}</span>
            <span className="tabular-nums">{readout?.values[i] ?? ''}</span>
          </span>
        ))}
        {readout && (
          <span className="ml-auto text-muted-foreground">{readout.label}</span>
        )}
      </div>
      <div ref={holder} style={{ height }} />
    </div>
  )
}
