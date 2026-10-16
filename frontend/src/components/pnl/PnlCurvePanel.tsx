// frontend/src/components/pnl/PnlCurvePanel.tsx
/**
 * The cumulative curve of the P&L page (fork-only): total, strategies and, for
 * the combined view, the realized and unrealized parts, with the drawdown in
 * its own pane. Line toggles on the plot, a table view, a PNG download. It
 * draws from the model only; resetting is driven by `resetSignal`.
 */
import {
  BaselineSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  LineSeries,
} from 'lightweight-charts'
import { ChevronDown, ChevronRight, Download } from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { cumulative, drawdown, runningMaxDrawdown, UNTAGGED } from '@/lib/pnlCurve'
import type { PnlModel } from '@/lib/pnlModel'
import { INK, REALIZED_COLOR, strategyColor, UNREALIZED_COLOR } from '@/lib/pnlPalette'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'
import { ChartWatermark, drawWatermark } from './ChartWatermark'

const CURVE_PANE_HEIGHT = 380
const DRAWDOWN_PANE_HEIGHT = 120
const CHART_HEIGHT = CURVE_PANE_HEIGHT + DRAWDOWN_PANE_HEIGHT

interface LineDef {
  name: string
  color: string
  width: number
  values: number[]
}

interface Props {
  model: PnlModel
  formatCurrency: (value: number) => string
  isDark: boolean
  title: string
  startDate: string
  endDate: string
  /** Bumped by the page (Alt+R) to put the plot scale back to the whole range. */
  resetSignal: number
}

export function PnlCurvePanel({
  model,
  formatCurrency,
  isDark,
  title,
  startDate,
  endDate,
  resetSignal,
}: Props) {
  const [open, setOpen] = useState(true)
  const [view, setView] = useState<'chart' | 'table'>('chart')
  const [hiddenLines, setHiddenLines] = useState<Set<string>>(new Set())
  const [tooltip, setTooltip] = useState<{
    left: number
    top: number
    date: string
    rows: { name: string; color: string; value: number }[]
    drawdown: number | null
    maxDrawdown: number | null
  } | null>(null)

  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const formatRef = useRef(formatCurrency)
  formatRef.current = formatCurrency

  const { series } = model
  const totalCum = useMemo(() => cumulative(series.total), [series])
  const dd = useMemo(() => drawdown(series.dates, totalCum), [series, totalCum])
  const mddSoFar = useMemo(() => runningMaxDrawdown(dd.series), [dd])
  const ink = isDark ? INK.dark : INK.light

  const lines = useMemo<LineDef[]>(() => {
    const out: LineDef[] = [{ name: 'Total', color: ink.total, width: 3, values: totalCum }]
    for (const name of model.strategyNames) {
      const daily = series.byStrategy.get(name)
      if (daily) {
        out.push({
          name,
          color: strategyColor(name, model.coloured, isDark),
          width: 2,
          values: cumulative(daily),
        })
      }
    }
    const split = model.splitLines
    if (split) {
      out.push({ name: 'Realized', color: REALIZED_COLOR, width: 2, values: split.realized })
      out.push({ name: 'Unrealized', color: UNREALIZED_COLOR, width: 2, values: split.unrealized })
    }
    return out
  }, [series, totalCum, model.strategyNames, model.coloured, model.splitLines, isDark, ink.total])

  // A reset from the page puts the scale back; the toggles stay as they are.
  // biome-ignore lint/correctness/useExhaustiveDependencies: only the signal matters
  useEffect(() => {
    if (resetSignal === 0) return
    setTooltip(null)
    chartRef.current?.timeScale().fitContent()
  }, [resetSignal])

  // biome-ignore lint/correctness/useExhaustiveDependencies: lines carries series and theme; format via ref
  useEffect(() => {
    const container = containerRef.current
    if (!open || !container || view !== 'chart' || series.dates.length === 0) return

    const grid = isDark ? 'rgba(166, 173, 187, 0.12)' : 'rgba(0, 0, 0, 0.08)'
    const axis = isDark ? 'rgba(166, 173, 187, 0.25)' : 'rgba(0, 0, 0, 0.2)'
    const chart = createChart(container, {
      width: container.clientWidth,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: ink.text,
        panes: { enableResize: true, separatorColor: axis, separatorHoverColor: axis },
      },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: axis, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: { borderColor: axis },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { width: 1, color: axis, style: 2, labelVisible: false },
        horzLine: { width: 1, color: axis, style: 2 },
      },
      localization: { priceFormatter: (price: number) => formatRef.current(price) },
    })

    const drawn = new Map<ISeriesApi<'Line'>, { name: string; color: string }>()
    for (const line of lines) {
      if (hiddenLines.has(line.name)) continue
      const s = chart.addSeries(
        LineSeries,
        {
          color: line.color,
          lineWidth: line.width as 1 | 2 | 3,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerRadius: 4,
        },
        0
      )
      s.setData(series.dates.map((date, i) => ({ time: date, value: line.values[i] })))
      drawn.set(s, { name: line.name, color: line.color })
    }

    const ddColor = isDark ? 'rgba(201, 200, 190, 0.85)' : 'rgba(82, 81, 78, 0.85)'
    const ddSeries = chart.addSeries(
      BaselineSeries,
      {
        baseValue: { type: 'price', price: 0 },
        topLineColor: ddColor,
        topFillColor1: 'rgba(0, 0, 0, 0)',
        topFillColor2: 'rgba(0, 0, 0, 0)',
        bottomLineColor: ddColor,
        bottomFillColor1: isDark ? 'rgba(201, 200, 190, 0.04)' : 'rgba(82, 81, 78, 0.04)',
        bottomFillColor2: isDark ? 'rgba(201, 200, 190, 0.3)' : 'rgba(82, 81, 78, 0.3)',
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1
    )
    ddSeries.setData(series.dates.map((date, i) => ({ time: date, value: dd.series[i] })))
    // The deepest drawdown so far, dashed, in the same pane.
    const mddSeries = chart.addSeries(
      LineSeries,
      {
        color: isDark ? 'rgba(230, 103, 103, 0.9)' : 'rgba(227, 73, 72, 0.9)',
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      },
      1
    )
    mddSeries.setData(series.dates.map((date, i) => ({ time: date, value: mddSoFar[i] })))

    const panes = chart.panes()
    panes[0]?.setHeight(CURVE_PANE_HEIGHT)
    panes[1]?.setHeight(DRAWDOWN_PANE_HEIGHT)
    chart.timeScale().fitContent()
    chartRef.current = chart

    chart.subscribeCrosshairMove((param) => {
      if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
        setTooltip(null)
        return
      }
      const rows: { name: string; color: string; value: number }[] = []
      for (const [s, meta] of drawn) {
        const point = param.seriesData.get(s) as { value?: number } | undefined
        if (point && typeof point.value === 'number') rows.push({ ...meta, value: point.value })
      }
      const d = param.seriesData.get(ddSeries) as { value?: number } | undefined
      const m = param.seriesData.get(mddSeries) as { value?: number } | undefined
      setTooltip({
        left: param.point.x,
        top: param.point.y,
        date: String(param.time),
        rows,
        drawdown: d && typeof d.value === 'number' ? d.value : null,
        maxDrawdown: m && typeof m.value === 'number' ? m.value : null,
      })
    })

    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }))
    observer.observe(container)
    return () => {
      observer.disconnect()
      chart.remove()
      chartRef.current = null
      setTooltip(null)
    }
  }, [open, view, lines, hiddenLines, isDark, dd, mddSoFar, series.dates])

  const toggleLine = (name: string) =>
    setHiddenLines((prev) => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })

  const downloadImage = () => {
    const chart = chartRef.current
    if (!chart) return
    try {
      const shot = chart.takeScreenshot()
      const band = 56
      const out = document.createElement('canvas')
      out.width = shot.width
      out.height = shot.height + band
      const ctx = out.getContext('2d')
      if (!ctx) return
      ctx.fillStyle = isDark ? '#0b0b0b' : '#ffffff'
      ctx.fillRect(0, 0, out.width, out.height)
      ctx.fillStyle = isDark ? '#ffffff' : '#0b0b0b'
      ctx.font = 'bold 16px sans-serif'
      ctx.fillText(`${title}  ${startDate} to ${endDate}`, 12, 22)
      ctx.font = '13px sans-serif'
      let x = 12
      for (const line of lines.filter((l) => !hiddenLines.has(l.name))) {
        ctx.fillStyle = line.color
        ctx.fillRect(x, 36, 10, 10)
        ctx.fillStyle = isDark ? '#c3c2b7' : '#52514e'
        const label = `${line.name}  ${formatCurrency(line.values[line.values.length - 1] ?? 0)}`
        ctx.fillText(label, x + 16, 46)
        x += 16 + ctx.measureText(label).width + 18
      }
      drawWatermark(ctx, isDark, out.width / 2, band + shot.height / 2)
      ctx.drawImage(shot, 0, band)
      out.toBlob((blob) => {
        if (!blob) return
        const url = URL.createObjectURL(blob)
        const link = document.createElement('a')
        link.href = url
        link.download = `PnL_Curve_${new Date().toISOString().slice(0, 10)}.png`
        document.body.appendChild(link)
        link.click()
        document.body.removeChild(link)
        URL.revokeObjectURL(url)
        showToast.success('Chart saved', 'system')
      }, 'image/png')
    } catch {
      showToast.error('Could not save the chart image', 'system')
    }
  }

  const pnlClass = (value: number) => (value >= 0 ? 'text-green-600' : 'text-red-600')

  return (
    <Card>
      <CardHeader className="flex flex-row items-start justify-between gap-4">
        <button
          type="button"
          className="flex items-start gap-2 text-left"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
        >
          {open ? (
            <ChevronDown className="mt-1 h-4 w-4" />
          ) : (
            <ChevronRight className="mt-1 h-4 w-4" />
          )}
          <span>
            <CardTitle>{title}</CardTitle>
            <CardDescription>
              Click a name on the plot to show or hide a line. Alt+R resets the scale.
            </CardDescription>
          </span>
        </button>
        {open && (
          <fieldset className="m-0 flex min-w-0 gap-2 border-0 p-0" aria-label="Chart or table">
            <Button
              size="sm"
              variant="outline"
              onClick={downloadImage}
              disabled={view !== 'chart'}
              aria-label="Download the chart as an image"
            >
              <Download className="h-4 w-4" />
            </Button>
            <Button
              size="sm"
              variant={view === 'chart' ? 'default' : 'outline'}
              onClick={() => setView('chart')}
            >
              Chart
            </Button>
            <Button
              size="sm"
              variant={view === 'table' ? 'default' : 'outline'}
              onClick={() => setView('table')}
            >
              Table
            </Button>
          </fieldset>
        )}
      </CardHeader>
      {open && (
        <CardContent>
          {series.dates.length === 0 ? (
            <p className="py-10 text-center text-muted-foreground">
              Nothing to plot for these filters
            </p>
          ) : view === 'chart' ? (
            <>
              <div className="relative">
                <ChartWatermark isDark={isDark} />
                <div
                  ref={containerRef}
                  className="relative z-[1]"
                  style={{ height: CHART_HEIGHT }}
                />
                <div className="absolute left-2 top-2 z-10 flex max-w-[85%] flex-wrap gap-1">
                  {lines.map((line) => {
                    const off = hiddenLines.has(line.name)
                    return (
                      <button
                        key={line.name}
                        type="button"
                        aria-pressed={!off}
                        onClick={() => toggleLine(line.name)}
                        className={cn(
                          'flex items-center gap-1.5 rounded-full border bg-background/80 px-2 py-0.5 text-xs backdrop-blur-sm transition-opacity',
                          off && 'opacity-40'
                        )}
                      >
                        <span
                          className="inline-block h-2 w-2 rounded-full"
                          style={{ backgroundColor: line.color }}
                        />
                        {line.name === UNTAGGED ? 'Untagged' : line.name}
                      </button>
                    )
                  })}
                </div>
                {tooltip && (
                  <div
                    className="pointer-events-none absolute z-10 rounded-md border bg-popover px-3 py-2 text-xs shadow-md"
                    style={{
                      left: Math.min(
                        tooltip.left + 16,
                        (containerRef.current?.clientWidth ?? 600) - 220
                      ),
                      top: Math.max(tooltip.top - 20, 0),
                      minWidth: 190,
                    }}
                  >
                    <div className="mb-1 font-medium">{tooltip.date}</div>
                    {tooltip.rows.map((row) => (
                      <div key={row.name} className="flex items-center justify-between gap-4">
                        <span className="flex items-center gap-2">
                          <span
                            className="inline-block h-2 w-2 rounded-full"
                            style={{ backgroundColor: row.color }}
                          />
                          {row.name}
                        </span>
                        <span className="font-mono">{formatCurrency(row.value)}</span>
                      </div>
                    ))}
                    {tooltip.drawdown !== null && (
                      <div className="mt-1 flex justify-between gap-4 border-t pt-1 text-muted-foreground">
                        <span>Current drawdown</span>
                        <span className="font-mono">{formatCurrency(tooltip.drawdown)}</span>
                      </div>
                    )}
                    {tooltip.maxDrawdown !== null && (
                      <div className="flex justify-between gap-4 text-muted-foreground">
                        <span>Max drawdown so far</span>
                        <span className="font-mono">{formatCurrency(tooltip.maxDrawdown)}</span>
                      </div>
                    )}
                  </div>
                )}
              </div>
              <p className="mt-2 text-xs text-muted-foreground">
                Lower pane: current drawdown from the running high (grey), and the deepest drawdown
                so far (dashed).
              </p>
            </>
          ) : (
            <div className="max-h-[520px] overflow-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Date</TableHead>
                    <TableHead className="text-right">Day</TableHead>
                    <TableHead className="text-right">Cumulative</TableHead>
                    <TableHead className="text-right">Drawdown</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {series.dates.map((date, i) => (
                    <TableRow key={date}>
                      <TableCell>{date}</TableCell>
                      <TableCell
                        className={cn('text-right font-medium', pnlClass(series.total[i]))}
                      >
                        {formatCurrency(series.total[i])}
                      </TableCell>
                      <TableCell className={cn('text-right font-medium', pnlClass(totalCum[i]))}>
                        {formatCurrency(totalCum[i])}
                      </TableCell>
                      <TableCell className="text-right text-muted-foreground">
                        {formatCurrency(dd.series[i])}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}
