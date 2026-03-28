import { useEffect, useRef } from 'react'
import {
  createChart,
  CandlestickSeries,
  ColorType,
  CrosshairMode,
  type IChartApi,
} from 'lightweight-charts'
import { toCandlestickData } from '@/lib/lightweightCharts'

interface Candle {
  time: number
  open: number
  high: number
  low: number
  close: number
}

interface TradeLevel {
  price: number
  color: string
  label: string
}

interface MiniChartProps {
  candles: Candle[]
  entry?: number
  stopLoss?: number
  target1?: number
  target2?: number
  target3?: number
  height?: number
}

export function MiniChart({
  candles,
  entry,
  stopLoss,
  target1,
  target2,
  target3,
  height = 350,
}: MiniChartProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)

  useEffect(() => {
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

    // Add candlestick series
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#16a34a',
      downColor: '#dc2626',
      borderUpColor: '#16a34a',
      borderDownColor: '#dc2626',
      wickUpColor: '#16a34a',
      wickDownColor: '#dc2626',
    })

    // Sort candles by time
    const sorted = [...candles].sort((a, b) => a.time - b.time)
    candleSeries.setData(toCandlestickData(sorted))

    // Add trade level lines
    const levels: TradeLevel[] = []
    if (entry) levels.push({ price: entry, color: '#3b82f6', label: 'Entry' })
    if (stopLoss) levels.push({ price: stopLoss, color: '#dc2626', label: 'SL' })
    if (target1) levels.push({ price: target1, color: '#16a34a', label: 'T1' })
    if (target2) levels.push({ price: target2, color: '#22c55e', label: 'T2' })
    if (target3) levels.push({ price: target3, color: '#86efac', label: 'T3' })

    for (const level of levels) {
      candleSeries.createPriceLine({
        price: level.price,
        color: level.color,
        lineWidth: 1,
        lineStyle: 2, // Dashed
        axisLabelVisible: true,
        title: level.label,
      })
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
  }, [candles, entry, stopLoss, target1, target2, target3, height])

  if (candles.length === 0) {
    return <div className="flex items-center justify-center h-48 text-sm text-muted-foreground">No chart data</div>
  }

  return <div ref={containerRef} className="w-full rounded border" />
}
