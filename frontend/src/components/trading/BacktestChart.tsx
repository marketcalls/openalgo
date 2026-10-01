/**
 * The equity curve or the drawdown of a backtest, drawn with this platform's
 * own charting engine.
 *
 * **The same engine the terminal draws prices with**, driven the way
 * `CandleViz` drives it for an agent answer: `createChart` on a host div, the
 * app's theme tokens through `buildChartTheme`, and a dynamic import so a
 * trader who never opens the backtest panel never pays for the charting bundle.
 * Nothing here is a second way to drive the library.
 *
 * **One series per chart, one chart per tab.** The panel shows equity and
 * drawdown on tabs of their own, so each gets the panel's full chart height
 * instead of half of a small box.
 *
 * **Both are baseline series.** Equity is measured from where the run started:
 * green above the starting capital, red below it, which is the first thing a
 * reader looks for. Drawdown is measured from zero and is zero or negative, the
 * sign the report already carries, so it fills downward in red and the worst
 * moment of a run is the lowest point of its pane, not the highest.
 *
 * **A point with no time is dropped rather than placed.** A bar can arrive
 * without one, and the engine's time axis would put it at the epoch, dragging
 * the whole curve flat against the right edge.
 */

import type { Chart } from 'openalgo-charts'
import { useEffect, useMemo, useRef } from 'react'
import { compactMoney } from '@/lib/trading/backtestFormat'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'

/** One point of the report's equity curve, as much of it as this draws. */
export interface CurvePoint {
  time?: unknown
  equity?: unknown
  drawdown?: unknown
}

/** Which of the report's two curves to draw. */
export type CurveKind = 'equity' | 'drawdown'

interface Props {
  points: readonly CurvePoint[]
  /** Equity by default. */
  show?: CurveKind
  /** The run's currency, so the axis reads in rupees (or dollars for crypto). */
  currency?: string
  /** The run's zone, so the time axis reads in the instrument's own hours. */
  timeZone?: string
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
  drawdownPercent: Plottable[]
} {
  const equity: Plottable[] = []
  const drawdown: Plottable[] = []
  const drawdownPercent: Plottable[] = []

  for (const point of points) {
    const ms = finite(point.time)
    if (ms === null) continue
    const time = Math.floor(ms / 1000)

    const value = finite(point.equity)
    if (value !== null) equity.push({ time, value })

    const under = finite(point.drawdown)
    if (under !== null) {
      drawdown.push({ time, value: under })
      // Drawdown as a share of the peak it fell from, which is how it is read:
      // the peak is the equity now less the (negative) drawdown.
      const peak = value === null ? null : value - under
      if (peak !== null && peak > 0) drawdownPercent.push({ time, value: (under / peak) * 100 })
    }
  }

  return { equity, drawdown, drawdownPercent }
}

/** The series a tab draws: equity in money, drawdown in percent of the peak. */
function plotted(points: readonly CurvePoint[], show: CurveKind): Plottable[] {
  const series = seriesFrom(points)
  return show === 'equity' ? series.equity : series.drawdownPercent
}

export function BacktestChart({
  points,
  show = 'equity',
  currency = 'INR',
  timeZone = 'Asia/Kolkata',
  className,
}: Props) {
  const host = useRef<HTMLDivElement | null>(null)
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)

  useEffect(() => {
    const container = host.current
    if (!container) return

    const data = plotted(points, show)
    if (data.length < 2) return

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
        const colours = theme.buildChartTheme(mode, appMode)
        const base = show === 'equity' ? data[0].value : 0
        const last = data[data.length - 1].value
        // The current-value tag says where the run stands, not which way the
        // last bar moved: green above the starting capital (or at a new high
        // for drawdown), red below it. The engine colours that tag from the
        // theme's last-price colours, so this chart's theme carries it.
        const standing = last >= base ? colours.upColor : colours.downColor
        const created = core.createChart(container, {
          theme: { ...colours, lastPriceUp: standing, lastPriceDown: standing },
          priceAxisWidth: 56,
          ariaLabel: show === 'equity' ? 'Equity curve' : 'Drawdown',
          ...(core.isValidTimezone(timeZone) ? { timezone: timeZone } : {}),
          // This panel is a report and not a workspace. The keyboard belongs to
          // the page, and a hover rail on a chart this size is more chrome than
          // chart.
          shortcuts: false,
          timeNavigator: false,
          // The corner mark sits on the curve in a chart this small.
          branding: false,
        })
        instance = created

        // The component can unmount inside the awaits above, in which case the
        // cleanup has already run and this instance is the one nobody destroys.
        if (disposed) {
          created.destroy()
          instance = null
          return
        }

        const fill = (colour: string) => core.withAlpha(colour, 0.22)
        created
          .addSeries('baseline', {
            style: {
              // Equity from the capital it started with; drawdown from zero.
              baseValue: base,
              // Drawdown is never above zero; a touch of zero is not a gain, so
              // its line stays red rather than flecking green at each new high.
              topColor: show === 'equity' ? colours.upColor : colours.downColor,
              bottomColor: colours.downColor,
              areaTopColor: fill(show === 'equity' ? colours.upColor : colours.downColor),
              areaBottomColor: fill(colours.downColor),
              lineWidth: 1.5,
            },
            // Read as money and as a percentage on the axis and the crosshair,
            // not as bare numbers with two decimals.
            priceFormat: {
              type: 'custom',
              formatter:
                show === 'equity'
                  ? (value: number) => compactMoney(value, currency)
                  : (value: number) => `${value.toFixed(2)}%`,
            },
          })
          .setData(data)
        created.fitContent()
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
  }, [points, show, currency, timeZone, mode, appMode])

  // Memoised, because this runs on every render and the run above it may hold
  // fifty thousand points: walking all of them to find out whether there are at
  // least two is work repeated for nothing on every unrelated state change in
  // the panel.
  const drawable = useMemo(() => plotted(points, show).length >= 2, [points, show])
  if (!drawable) return null

  return (
    <div
      ref={host}
      className={cn('h-60 w-full overflow-hidden rounded border border-border', className)}
    />
  )
}
