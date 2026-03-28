import { useEffect, useRef } from 'react'
import { BarChart3, Loader2 } from 'lucide-react'
import { createChart, CandlestickSeries, HistogramSeries, type IChartApi, type CandlestickData, type Time } from 'lightweight-charts'
import { Panel } from './shared/Panel'
import { useDashboardStore } from '@/stores/dashboardStore'

const TIMEFRAMES = ['1m', '5m', '15m', '1h'] as const

export function SmartChart() {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const symbol = useDashboardStore((s) => s.selectedSymbol)
  const selectedTf = useDashboardStore((s) => s.selectedTimeframe)
  const storeCandles = useDashboardStore((s) => s.candles[symbol]?.[selectedTf] ?? [])

  useEffect(() => {
    if (!containerRef.current) return

    const chart = createChart(containerRef.current, {
      layout: { background: { color: 'transparent' }, textColor: '#64748b', fontSize: 10 },
      grid: {
        vertLines: { color: 'rgba(51,65,85,0.3)' },
        horzLines: { color: 'rgba(51,65,85,0.3)' },
      },
      crosshair: {
        vertLine: { color: '#475569', width: 1, style: 2 },
        horzLine: { color: '#475569', width: 1, style: 2 },
      },
      rightPriceScale: { borderColor: '#1e293b', scaleMargins: { top: 0.1, bottom: 0.2 } },
      timeScale: { borderColor: '#1e293b', timeVisible: true, secondsVisible: false },
    })
    chartRef.current = chart

    const cs = chart.addSeries(CandlestickSeries, {
      upColor: '#10b981', downColor: '#f43f5e',
      borderUpColor: '#10b981', borderDownColor: '#f43f5e',
      wickUpColor: '#10b981', wickDownColor: '#f43f5e',
    })

    if (storeCandles.length > 0) {
      const data: CandlestickData<Time>[] = storeCandles.map((c) => ({
        time: (c.time / 1000) as Time,
        open: c.open, high: c.high, low: c.low, close: c.close,
      }))
      cs.setData(data)

      const vs = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: 'volume' })
      chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } })
      vs.setData(storeCandles.map((c) => ({
        time: (c.time / 1000) as Time,
        value: c.volume,
        color: c.close >= c.open ? 'rgba(16,185,129,0.3)' : 'rgba(244,63,94,0.3)',
      })))
    }

    chart.timeScale().fitContent()

    const ro = new ResizeObserver(() => {
      if (containerRef.current) {
        chart.applyOptions({ width: containerRef.current.clientWidth, height: containerRef.current.clientHeight })
      }
    })
    ro.observe(containerRef.current)
    return () => { ro.disconnect(); chart.remove() }
  }, [storeCandles, symbol, selectedTf])

  return (
    <Panel
      title="Smart Chart"
      icon={<BarChart3 size={14} />}
      compact
      className="h-full"
      action={
        <div className="flex items-center gap-1">
          <span className="text-xs font-bold text-slate-200">{symbol}</span>
          <span className="mx-1 text-slate-700">|</span>
          {TIMEFRAMES.map((tf) => (
            <button
              key={tf}
              className={`rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${
                tf === selectedTf ? 'bg-sky-600/30 text-sky-400' : 'text-slate-500 hover:text-slate-300'
              }`}
            >
              {tf}
            </button>
          ))}
          {storeCandles.length === 0 && (
            <span className="text-[10px] text-slate-600 ml-2">Waiting for data...</span>
          )}
        </div>
      }
    >
      <div ref={containerRef} className="h-full w-full min-h-[200px]" />
    </Panel>
  )
}
