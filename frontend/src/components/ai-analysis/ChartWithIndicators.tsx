import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart,
  CandlestickSeries,
  LineSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
} from 'lightweight-charts'
import { Button } from '@/components/ui/button'
import type { CandleData, ChartOverlays } from '@/types/ai-analysis'

interface ChartWithIndicatorsProps {
  candles: CandleData[]
  overlays?: ChartOverlays
  height?: number
}

export function ChartWithIndicators({
  candles,
  overlays,
  height = 400,
}: ChartWithIndicatorsProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  // Toggle state for each overlay type
  const [showEMA, setShowEMA] = useState(true)
  const [showSMA, setShowSMA] = useState(true)
  const [showBB, setShowBB] = useState(true)
  const [showSupertrend, setShowSupertrend] = useState(true)
  const [showLevels, setShowLevels] = useState(true)

  const buildChart = useCallback(() => {
    if (!containerRef.current || candles.length === 0) return

    // Clean up previous chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const chart = createChart(containerRef.current, {
      layout: {
        background: { type: ColorType.Solid, color: '#ffffff' },
        textColor: '#333',
        fontSize: 11,
      },
      grid: {
        vertLines: { color: '#f0f0f0' },
        horzLines: { color: '#f0f0f0' },
      },
      crosshair: { mode: CrosshairMode.Normal },
      rightPriceScale: { borderColor: '#e0e0e0' },
      timeScale: {
        borderColor: '#e0e0e0',
        timeVisible: true,
        secondsVisible: false,
      },
      width: containerRef.current.clientWidth,
      height,
    })
    chartRef.current = chart

    // Sort candles
    const sorted = [...candles].sort((a, b) => a.time - b.time)

    // Candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      borderUpColor: '#16a34a',
      borderDownColor: '#dc2626',
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
    })
    candleSeries.setData(sorted)

    if (overlays) {
      // Lines: EMA, SMA, Supertrend
      for (const line of overlays.lines) {
        const isEMA = line.id.startsWith('ema')
        const isSMA = line.id.startsWith('sma')
        const isST = line.id === 'supertrend'

        if (isEMA && !showEMA) continue
        if (isSMA && !showSMA) continue
        if (isST && !showSupertrend) continue

        const lineSeries = chart.addSeries(LineSeries, {
          color: line.color,
          lineWidth: 1,
          priceLineVisible: false,
          lastValueVisible: false,
        })
        lineSeries.setData(line.data.map(d => ({ time: d.time, value: d.value })))
      }

      // Bands: Bollinger
      if (showBB) {
        for (const band of overlays.bands) {
          const upperSeries = chart.addSeries(LineSeries, {
            color: band.color,
            lineWidth: 1,
            lineStyle: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          upperSeries.setData(band.data.map(d => ({ time: d.time, value: d.upper })))

          const lowerSeries = chart.addSeries(LineSeries, {
            color: band.color,
            lineWidth: 1,
            lineStyle: 2,
            priceLineVisible: false,
            lastValueVisible: false,
          })
          lowerSeries.setData(band.data.map(d => ({ time: d.time, value: d.lower })))
        }
      }

      // Levels: CPR + Entry/SL/Target
      if (showLevels && overlays.levels.length > 0) {
        for (const level of overlays.levels) {
          candleSeries.createPriceLine({
            price: level.price,
            color: level.color,
            lineWidth: 1,
            lineStyle: 2,
            axisLabelVisible: true,
            title: level.label,
          })
        }
      }
    }

    chart.timeScale().fitContent()

    // Resize observer
    const resizeObserver = new ResizeObserver(() => {
      if (containerRef.current && chartRef.current) {
        chartRef.current.applyOptions({ width: containerRef.current.clientWidth })
      }
    })
    resizeObserver.observe(containerRef.current)

    return () => {
      resizeObserver.disconnect()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [candles, overlays, height, showEMA, showSMA, showBB, showSupertrend, showLevels])

  useEffect(() => {
    const cleanup = buildChart()
    return cleanup
  }, [buildChart])

  if (candles.length === 0) {
    return <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">No chart data</div>
  }

  return (
    <div className="space-y-2">
      {/* Toggle buttons */}
      <div className="flex gap-1 flex-wrap">
        <Button variant={showEMA ? 'default' : 'outline'} size="sm" className="h-6 text-xs px-2"
          onClick={() => setShowEMA(!showEMA)}>EMA</Button>
        <Button variant={showSMA ? 'default' : 'outline'} size="sm" className="h-6 text-xs px-2"
          onClick={() => setShowSMA(!showSMA)}>SMA</Button>
        <Button variant={showBB ? 'default' : 'outline'} size="sm" className="h-6 text-xs px-2"
          onClick={() => setShowBB(!showBB)}>BB</Button>
        <Button variant={showSupertrend ? 'default' : 'outline'} size="sm" className="h-6 text-xs px-2"
          onClick={() => setShowSupertrend(!showSupertrend)}>ST</Button>
        <Button variant={showLevels ? 'default' : 'outline'} size="sm" className="h-6 text-xs px-2"
          onClick={() => setShowLevels(!showLevels)}>Levels</Button>
      </div>
      <div ref={containerRef} className="w-full rounded border" />
    </div>
  )
}
