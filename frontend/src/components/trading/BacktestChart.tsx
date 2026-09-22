/**
 * The equity curve and the drawdown beneath it, drawn with this platform's own
 * charting engine.
 *
 * **The same engine the terminal draws prices with**, driven the way
 * `CandleViz` drives it for an agent answer: `createChart` on a host div, the
 * app's theme tokens through `buildChartTheme`, and a dynamic import so a
 * trader who never opens the backtest panel never pays for the charting bundle.
 * Nothing here is a second way to drive the library.
 *
 * **Two panes and not two charts.** The engine creates a higher pane on demand,
 * so the drawdown sits under the equity on one shared time axis. Two separate
 * charts would need their time axes kept in step by hand, and the first thing a
 * reader does with these two series is look down from a peak to the trough
 * underneath it.
 *
 * **Drawdown is drawn as an area under zero**, which is the sign the report
 * already carries: `drawdown` is zero or negative and never positive, so the
 * series needs no transformation and the shape on screen is the shape in the
 * record. Flipping it to draw upward would put the worst moment of a run at the
 * top of its own pane.
 *
 * **A point with no time is dropped rather than placed.** A bar can arrive
 * without one, and the engine's time axis would put it at the epoch, dragging
 * the whole curve flat against the right edge.
 */

import type { Chart } from 'openalgo-charts'
import { useEffect, useMemo, useRef } from 'react'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'

/** One point of the report's equity curve, as much of it as this draws. */
export interface CurvePoint {
  time?: unknown
  equity?: unknown
  drawdown?: unknown
}

interface Props {
  points: readonly CurvePoint[]
  className?: string
}

/** A point the axis can place: a time in seconds and a finite value. */
interface Plottable {
  time: number
  value: number
}

/**
 * A number, or nothing, without treating absence as zero.
 *
 * `Number(null)` is `0` and `Number.isFinite(0)` is true, so reading these
 * fields through a bare coercion turned every absent value into a real one: a
 * bar with no time was placed at the epoch and a point with no equity was drawn
 * at zero. Both draw without an error and both are wrong.
 */
function finite(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const asNumber = Number(value)
  return Number.isFinite(asNumber) ? asNumber : null
}

/**
 * The two series, in the engine's own units.
 *
 * The report counts milliseconds and the chart's time axis counts seconds, the
 * same conversion the run itself makes in the other direction when it reads
 * history. Getting it wrong here does not throw: it draws a curve dated 1970.
 */
export function seriesFrom(points: readonly CurvePoint[]): {
  equity: Plottable[]
  drawdown: Plottable[]
} {
  const equity: Plottable[] = []
  const drawdown: Plottable[] = []

  for (const point of points) {
    const ms = finite(point.time)
    if (ms === null) continue
    const time = Math.floor(ms / 1000)

    const value = finite(point.equity)
    if (value !== null) equity.push({ time, value })

    const under = finite(point.drawdown)
    if (under !== null) drawdown.push({ time, value: under })
  }

  return { equity, drawdown }
}

export function BacktestChart({ points, className }: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)

  useEffect(() => {
    const container = host.current
    if (!container) return

    const { equity, drawdown } = seriesFrom(points)
    if (equity.length < 2) return

    let disposed = false
    let instance: Chart | null = null

    const build = async () => {
      // Dynamic, so the charting bundle is the backtest panel's cost and not
      // every trading page's. chartTheme imports the library itself, so
      // importing it statically would pull the engine in regardless.
      const [core, theme] = await Promise.all([
        import('openalgo-charts'),
        import('@/lib/trading/chartTheme'),
      ])
      if (disposed) return

      try {
        const created = core.createChart(container, {
          theme: theme.buildChartTheme(mode, appMode),
          priceAxisWidth: 56,
          ariaLabel: 'Equity curve and drawdown',
          // This panel is a report and not a workspace. The keyboard belongs to
          // the page, and a hover rail on a chart this size is more chrome than
          // chart.
          shortcuts: false,
          timeNavigator: false,
        })
        instance = created

        // The component can unmount inside the awaits above, in which case the
        // cleanup has already run and this instance is the one nobody destroys.
        if (disposed) {
          created.destroy()
          instance = null
          return
        }

        created.addSeries('area', { paneIndex: 0 }).setData(equity)
        if (drawdown.length >= 2) {
          created.addSeries('area', { paneIndex: 1 }).setData(drawdown)
        }
      } catch {
        // An exception thrown from an effect unmounts the tree above it, which
        // here would take the whole panel down over a chart. A report with no
        // picture is still a report.
        instance?.destroy()
        instance = null
      }
    }

    void build()

    return () => {
      disposed = true
      instance?.destroy()
      instance = null
    }
  }, [points, mode, appMode])

  // Memoised, because this runs on every render and the run above it may hold
  // fifty thousand points: walking all of them to find out whether there are at
  // least two is work repeated for nothing on every unrelated state change in
  // the panel.
  const drawable = useMemo(() => seriesFrom(points).equity.length >= 2, [points])
  if (!drawable) return null

  return (
    <div
      ref={host}
      className={cn('h-48 w-full overflow-hidden rounded border border-border', className)}
    />
  )
}
