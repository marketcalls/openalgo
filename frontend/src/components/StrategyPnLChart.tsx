import { AlertTriangle, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useThemeStore } from '@/stores/themeStore'
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'

interface PnLDataPoint {
  time: number
  value: number
}

interface StrategyPnLData {
  current_mtm: number
  max_mtm: number
  max_mtm_time: string | null
  min_mtm: number
  min_mtm_time: string | null
  max_drawdown: number
  pnl_series: PnLDataPoint[]
  drawdown_series: PnLDataPoint[]
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat('en-IN', {
    style: 'currency',
    currency: 'INR',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value)
}

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', { credentials: 'include' })
  const data = await response.json()
  return data.csrf_token
}

interface StrategyPnLChartProps {
  instanceId: string
  strategyName?: string
}

export default function StrategyPnLChart({ instanceId, strategyName }: StrategyPnLChartProps) {
  const { mode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  const [isLoading, setIsLoading] = useState(false)
  const [metrics, setMetrics] = useState({
    currentMtm: 0,
    maxMtm: 0,
    maxMtmTime: '--:--',
    minMtm: 0,
    minMtmTime: '--:--',
    maxDrawdown: 0,
  })
  const [hasData, setHasData] = useState(false)

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const pnlSeriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const drawdownSeriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)

  // Initialize chart — identical to PnLTracker
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
      pnlSeriesRef.current = null
      drawdownSeriesRef.current = null
      if (watermarkRef.current) {
        watermarkRef.current.remove()
        watermarkRef.current = null
      }
    }

    const container = chartContainerRef.current

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: 400,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDarkMode ? '#a6adbb' : '#333',
      },
      grid: {
        vertLines: {
          color: isDarkMode ? 'rgba(166, 173, 187, 0.1)' : 'rgba(0, 0, 0, 0.1)',
          style: 1,
          visible: true,
        },
        horzLines: {
          color: isDarkMode ? 'rgba(166, 173, 187, 0.1)' : 'rgba(0, 0, 0, 0.1)',
          style: 1,
          visible: true,
        },
      },
      rightPriceScale: {
        borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: number) => {
          const date = new Date(time * 1000)
          const istOffset = 5.5 * 60 * 60 * 1000
          const istDate = new Date(date.getTime() + istOffset)
          const hours = istDate.getUTCHours().toString().padStart(2, '0')
          const minutes = istDate.getUTCMinutes().toString().padStart(2, '0')
          return `${hours}:${minutes}`
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          width: 1,
          color: isDarkMode ? 'rgba(166, 173, 187, 0.5)' : 'rgba(0, 0, 0, 0.3)',
          style: 2,
          labelVisible: false,
        },
        horzLine: {
          width: 1,
          color: isDarkMode ? 'rgba(166, 173, 187, 0.5)' : 'rgba(0, 0, 0, 0.3)',
          style: 2,
          labelBackgroundColor: isDarkMode ? '#1f2937' : '#2563eb',
        },
      },
    })

    // Watermark
    const watermark = document.createElement('div')
    watermark.style.position = 'absolute'
    watermark.style.zIndex = '2'
    watermark.style.color = isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.15)'
    watermark.style.fontFamily = 'Arial, sans-serif'
    watermark.style.fontSize = '36px'
    watermark.style.fontWeight = 'bold'
    watermark.style.userSelect = 'none'
    watermark.style.pointerEvents = 'none'
    watermark.textContent = 'OpenAlgo'
    container.appendChild(watermark)
    watermarkRef.current = watermark

    const positionWatermark = () => {
      if (!watermark || !container) return
      watermark.style.left = `${container.offsetWidth / 2 - watermark.offsetWidth / 2}px`
      watermark.style.top = `${container.offsetHeight / 2 - watermark.offsetHeight / 2}px`
    }
    setTimeout(positionWatermark, 0)

    // P&L series — purple (matching PnLTracker)
    const pnlSeries = chart.addSeries(AreaSeries, {
      lineColor: '#570df8',
      topColor: 'rgba(87, 13, 248, 0.4)',
      bottomColor: 'rgba(87, 13, 248, 0.0)',
      lineWidth: 2,
      priceScaleId: 'right',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => formatCurrency(price),
      },
    })

    // Drawdown series — pink (matching PnLTracker)
    const drawdownSeries = chart.addSeries(AreaSeries, {
      lineColor: '#f000b8',
      topColor: 'rgba(240, 0, 184, 0.0)',
      bottomColor: 'rgba(240, 0, 184, 0.4)',
      lineWidth: 2,
      priceScaleId: 'right',
      priceFormat: {
        type: 'custom',
        formatter: (price: number) => formatCurrency(price),
      },
    })

    chartRef.current = chart
    pnlSeriesRef.current = pnlSeries
    drawdownSeriesRef.current = drawdownSeries

    const handleResize = () => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({ width: container.offsetWidth })
        positionWatermark()
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [isDarkMode])

  // Init chart on mount and theme change
  useEffect(() => {
    const cleanup = initChart()
    return () => {
      cleanup?.()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
        pnlSeriesRef.current = null
        drawdownSeriesRef.current = null
      }
      if (watermarkRef.current) {
        watermarkRef.current.remove()
        watermarkRef.current = null
      }
    }
  }, [initChart])

  // Fetch minute-level P&L data from backend
  const loadPnLData = useCallback(async () => {
    if (!instanceId) return
    setIsLoading(true)
    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/pnltracker/api/strategy-pnl', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
        body: JSON.stringify({ instance_id: instanceId }),
      })

      if (!response.ok) throw new Error('Failed to fetch strategy P&L data')

      const result = await response.json()

      if (result.status === 'success') {
        const data: StrategyPnLData = result.data

        setMetrics({
          currentMtm: data.current_mtm,
          maxMtm: data.max_mtm,
          maxMtmTime: data.max_mtm_time || '--:--',
          minMtm: data.min_mtm,
          minMtmTime: data.min_mtm_time || '--:--',
          maxDrawdown: data.max_drawdown,
        })

        const hasSeries = data.pnl_series && data.pnl_series.length > 0
        setHasData(hasSeries)

        if (pnlSeriesRef.current && hasSeries) {
          // Backend sends timestamps in ms — convert to seconds for lightweight-charts
          const pnlData = data.pnl_series
            .map((point) => ({
              time: Math.floor(point.time / 1000) as UTCTimestamp,
              value: point.value,
            }))
            .sort((a, b) => a.time - b.time)
          pnlSeriesRef.current.setData(pnlData)
        }

        if (drawdownSeriesRef.current && data.drawdown_series?.length > 0) {
          const ddData = data.drawdown_series
            .map((point) => ({
              time: Math.floor(point.time / 1000) as UTCTimestamp,
              value: point.value,
            }))
            .sort((a, b) => a.time - b.time)
          drawdownSeriesRef.current.setData(ddData)
        }

        if (chartRef.current) {
          chartRef.current.timeScale().fitContent()
        }
      } else {
        showToast.error(result.message || 'Failed to load strategy P&L data', 'positions')
      }
    } catch {
      showToast.error('Failed to load strategy P&L data. Please try again.', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [instanceId])

  // Load data on mount
  useEffect(() => {
    loadPnLData()
  }, [loadPnLData])

  return (
    <div className="space-y-4">
      {/* Metrics Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {/* Current P&L */}
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground">Current P&L</CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div
              className={`text-xl font-bold font-mono ${metrics.currentMtm >= 0 ? 'text-green-500' : 'text-red-500'}`}
            >
              {formatCurrency(metrics.currentMtm)}
            </div>
          </CardContent>
        </Card>

        {/* Max P&L */}
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <TrendingUp className="h-3 w-3 text-green-500" />
              Max P&L
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="text-xl font-bold font-mono text-green-500">
              {formatCurrency(metrics.maxMtm)}
            </div>
            <div className="text-xs text-muted-foreground">at {metrics.maxMtmTime}</div>
          </CardContent>
        </Card>

        {/* Min P&L */}
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <TrendingDown className="h-3 w-3 text-red-500" />
              Min P&L
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="text-xl font-bold font-mono text-red-500">
              {formatCurrency(metrics.minMtm)}
            </div>
            <div className="text-xs text-muted-foreground">at {metrics.minMtmTime}</div>
          </CardContent>
        </Card>

        {/* Max Drawdown */}
        <Card>
          <CardHeader className="pb-1 pt-3 px-4">
            <CardTitle className="text-xs font-medium text-muted-foreground flex items-center gap-1">
              <AlertTriangle className="h-3 w-3 text-yellow-500" />
              Max Drawdown
            </CardTitle>
          </CardHeader>
          <CardContent className="px-4 pb-3">
            <div className="text-xl font-bold font-mono text-yellow-500">
              {formatCurrency(Math.abs(metrics.maxDrawdown))}
            </div>
            <div className="text-xs text-muted-foreground">Peak to trough</div>
          </CardContent>
        </Card>
      </div>

      {/* Chart */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex justify-between items-center">
            <CardTitle className="text-sm">
              {strategyName ? `${strategyName} — Intraday P&L Curve` : 'Intraday P&L Curve'}
            </CardTitle>
            <div className="flex items-center gap-3">
              {/* Legend */}
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-[#570df8]" />
                  MTM P&L
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-[#f000b8]" />
                  Drawdown
                </span>
              </div>
              {/* Refresh button */}
              <Button
                variant="outline"
                size="sm"
                onClick={loadPnLData}
                disabled={isLoading}
                className="h-7 px-2 text-xs"
              >
                <RefreshCw className={`h-3 w-3 mr-1 ${isLoading ? 'animate-spin' : ''}`} />
                {isLoading ? 'Loading…' : 'Refresh'}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {!hasData && !isLoading ? (
            <div className="flex items-center justify-center h-40 text-muted-foreground text-sm">
              No trade data for today — P&L curve will appear once trades are recorded.
            </div>
          ) : null}
          {isLoading && !hasData ? (
            <div className="flex items-center justify-center h-40">
              <div className="flex items-center gap-3">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-primary" />
                <span className="text-sm text-muted-foreground">Loading P&L data…</span>
              </div>
            </div>
          ) : null}
          <div
            ref={chartContainerRef}
            className="relative"
            style={{ height: '400px', display: hasData ? 'block' : 'none' }}
          />
        </CardContent>
      </Card>
    </div>
  )
}
