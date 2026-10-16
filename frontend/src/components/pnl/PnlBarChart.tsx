// frontend/src/components/pnl/PnlBarChart.tsx
/**
 * Bars of a day / week / month P&L series (fork-only), green above zero and
 * red below, on the same chart library, theme and crosshair as the curve.
 */
import { ColorType, CrosshairMode, createChart, HistogramSeries } from 'lightweight-charts'
import { useEffect, useRef, useState } from 'react'
import type { Bucket } from '@/lib/pnlBuckets'
import { INK, negative, positive } from '@/lib/pnlPalette'
import { ChartWatermark } from './ChartWatermark'

const HEIGHT = 340

interface Props {
  buckets: Bucket[]
  isDark: boolean
  formatCurrency: (value: number) => string
}

export function PnlBarChart({ buckets, isDark, formatCurrency }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const formatRef = useRef(formatCurrency)
  formatRef.current = formatCurrency
  const [tip, setTip] = useState<{ left: number; top: number; text: string; value: number } | null>(
    null
  )

  useEffect(() => {
    const container = containerRef.current
    if (!container || buckets.length === 0) return
    const ink = isDark ? INK.dark : INK.light
    const grid = isDark ? 'rgba(166, 173, 187, 0.12)' : 'rgba(0, 0, 0, 0.08)'
    const axis = isDark ? 'rgba(166, 173, 187, 0.25)' : 'rgba(0, 0, 0, 0.2)'

    const chart = createChart(container, {
      width: container.clientWidth,
      height: HEIGHT,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: ink.text },
      grid: { vertLines: { visible: false }, horzLines: { color: grid } },
      rightPriceScale: { borderColor: axis, scaleMargins: { top: 0.1, bottom: 0.1 } },
      timeScale: { borderColor: axis },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { width: 1, color: axis, style: 2, labelVisible: false },
        horzLine: { width: 1, color: axis, style: 2 },
      },
      localization: { priceFormatter: (price: number) => formatRef.current(price) },
    })
    const bars = chart.addSeries(HistogramSeries, {
      priceLineVisible: false,
      lastValueVisible: false,
      base: 0,
    })
    const up = positive(isDark)
    const down = negative(isDark)
    bars.setData(
      buckets.map((b) => ({ time: b.start, value: b.value, color: b.value >= 0 ? up : down }))
    )
    chart.timeScale().fitContent()

    const byStart = new Map(buckets.map((b) => [b.start, b]))
    chart.subscribeCrosshairMove((param) => {
      if (!param.point || !param.time || param.point.x < 0 || param.point.y < 0) {
        setTip(null)
        return
      }
      const bucket = byStart.get(String(param.time))
      if (!bucket) {
        setTip(null)
        return
      }
      setTip({
        left: param.point.x,
        top: param.point.y,
        text: `${bucket.label} (${bucket.days} day${bucket.days === 1 ? '' : 's'})`,
        value: bucket.value,
      })
    })

    const observer = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }))
    observer.observe(container)
    return () => {
      observer.disconnect()
      chart.remove()
      setTip(null)
    }
  }, [buckets, isDark])

  if (buckets.length === 0) {
    return <p className="py-10 text-center text-muted-foreground">Nothing to plot</p>
  }
  return (
    <div className="relative">
      <ChartWatermark isDark={isDark} />
      <div ref={containerRef} className="relative z-[1]" style={{ height: HEIGHT }} />
      {tip && (
        <div
          className="pointer-events-none absolute z-10 rounded-md border bg-popover px-3 py-2 text-xs shadow-md"
          style={{
            left: Math.min(tip.left + 16, (containerRef.current?.clientWidth ?? 600) - 200),
            top: Math.max(tip.top - 20, 0),
          }}
        >
          <div className="mb-1 font-medium">{tip.text}</div>
          <div className="font-mono">{formatCurrency(tip.value)}</div>
        </div>
      )}
    </div>
  )
}
