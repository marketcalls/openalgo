import { AlertTriangle, Camera, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { showToast } from '@/utils/toast'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { useThemeStore } from '@/stores/themeStore'

async function fetchCSRFToken(): Promise<string> {
  const response = await fetch('/auth/csrf-token', {
    credentials: 'include',
  })
  const data = await response.json()
  return data.csrf_token
}

// Use html2canvas-pro which has native oklch color support
import html2canvas from 'html2canvas-pro'
import {
  AreaSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'

interface PnLDataPoint {
  time: number
  value: number
}

interface PnLData {
  current_mtm: number
  max_mtm: number
  max_mtm_time: string
  min_mtm: number
  min_mtm_time: string
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

export default function PnLTracker() {
  const { mode } = useThemeStore()
  const isDarkMode = mode === 'dark'

  // State
  const [isLoading, setIsLoading] = useState(false)
  const [isCapturing, setIsCapturing] = useState(false)
  const [metrics, setMetrics] = useState({
    currentMtm: 0,
    maxMtm: 0,
    maxMtmTime: '--:--',
    minMtm: 0,
    minMtmTime: '--:--',
    maxDrawdown: 0,
  })

  // Refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const screenshotContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const pnlSeriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const drawdownSeriesRef = useRef<ISeriesApi<'Area'> | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)

  // Initialize chart
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return

    // Remove existing chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const container = chartContainerRef.current

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: 500,
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

    // Add watermark
    const watermark = document.createElement('div')
    watermark.style.position = 'absolute'
    watermark.style.zIndex = '2'
    watermark.style.color = isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.15)'
    watermark.style.fontFamily = 'Arial, sans-serif'
    watermark.style.fontSize = '48px'
    watermark.style.fontWeight = 'bold'
    watermark.style.userSelect = 'none'
    watermark.style.pointerEvents = 'none'
    watermark.textContent = 'OpenAlgo'
    container.appendChild(watermark)
    watermarkRef.current = watermark

    // Position watermark
    const positionWatermark = () => {
      if (!watermark || !container) return
      watermark.style.left = `${container.offsetWidth / 2 - watermark.offsetWidth / 2}px`
      watermark.style.top = `${container.offsetHeight / 2 - watermark.offsetHeight / 2}px`
    }
    setTimeout(positionWatermark, 0)

    // Create PnL series
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

    // Create Drawdown series
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

    // Handle resize
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

  // Load PnL data
  const loadPnLData = useCallback(async () => {
    setIsLoading(true)
    try {
      const csrfToken = await fetchCSRFToken()

      const response = await fetch('/pnltracker/api/pnl', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
        },
        credentials: 'include',
      })

      if (!response.ok) throw new Error('Failed to fetch PnL data')

      const result = await response.json()

      if (result.status === 'success') {
        const data: PnLData = result.data

        // Update metrics
        setMetrics({
          currentMtm: data.current_mtm,
          maxMtm: data.max_mtm,
          maxMtmTime: data.max_mtm_time || '--:--',
          minMtm: data.min_mtm,
          minMtmTime: data.min_mtm_time || '--:--',
          maxDrawdown: data.max_drawdown,
        })

        // Update chart
        if (pnlSeriesRef.current && data.pnl_series && Array.isArray(data.pnl_series)) {
          const pnlData = data.pnl_series
            .map((point) => ({
              time: Math.floor(point.time / 1000) as import('lightweight-charts').UTCTimestamp,
              value: point.value,
            }))
            .sort((a, b) => a.time - b.time)

          if (pnlData.length > 0) {
            pnlSeriesRef.current.setData(pnlData)
          }
        }

        if (
          drawdownSeriesRef.current &&
          data.drawdown_series &&
          Array.isArray(data.drawdown_series)
        ) {
          const drawdownData = data.drawdown_series
            .map((point) => ({
              time: Math.floor(point.time / 1000) as import('lightweight-charts').UTCTimestamp,
              value: point.value,
            }))
            .sort((a, b) => a.time - b.time)

          if (drawdownData.length > 0) {
            drawdownSeriesRef.current.setData(drawdownData)
          }
        }

        if (chartRef.current) {
          chartRef.current.timeScale().fitContent()
        }
      } else {
        showToast.error(result.message || 'Failed to load PnL data', 'positions')
      }
    } catch (error) {
      showToast.error('Failed to load PnL data. Please try again.', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Take screenshot - html2canvas-pro supports oklch colors natively
  const takeScreenshot = async () => {
    if (!screenshotContainerRef.current) return

    setIsCapturing(true)

    try {
      const canvas = await html2canvas(screenshotContainerRef.current, {
        backgroundColor: isDarkMode ? '#1f2937' : '#ffffff',
        scale: 2,
        logging: false,
        useCORS: true,
      })

      canvas.toBlob(
        (blob) => {
          if (!blob) return
          const url = URL.createObjectURL(blob)
          const link = document.createElement('a')
          const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5)
          link.download = `PnL_Tracker_${timestamp}.png`
          link.href = url
          document.body.appendChild(link)
          link.click()
          document.body.removeChild(link)
          URL.revokeObjectURL(url)

          showToast.success('Screenshot saved successfully!', 'positions')
        },
        'image/png',
        1.0
      )
    } catch (error) {
      showToast.error('Failed to capture screenshot', 'positions')
    } finally {
      setIsCapturing(false)
    }
  }

  // Initialize chart and load data
  useEffect(() => {
    initChart()
    loadPnLData()

    return () => {
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [initChart, loadPnLData])

  // Re-initialize chart on theme change
  useEffect(() => {
    if (chartRef.current) {
      initChart()
      loadPnLData()
    }
  }, [initChart, loadPnLData])

  return (
    <div className="container mx-auto py-6 px-4">
      {/* Header */}
      <div className="flex justify-between items-center mb-6">
        <div>
          <h1 className="text-3xl font-bold">PnL Tracker</h1>
          <p className="text-muted-foreground">Monitor your intraday profit and loss</p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={takeScreenshot} disabled={isCapturing}>
            {isCapturing ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current mr-2"></div>
                Capturing...
              </>
            ) : (
              <>
                <Camera className="h-4 w-4 mr-2" />
                Screenshot
              </>
            )}
          </Button>
          <Button onClick={loadPnLData} disabled={isLoading}>
            {isLoading ? (
              <>
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-current mr-2"></div>
                Loading...
              </>
            ) : (
              <>
                <RefreshCw className="h-4 w-4 mr-2" />
                Refresh
              </>
            )}
          </Button>
        </div>
      </div>

      {/* Screenshot Container */}
      <div ref={screenshotContainerRef}>
        {/* Metrics Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          {/* Current MTM */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                Current MTM
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div
                className={`text-2xl font-bold font-mono ${metrics.currentMtm >= 0 ? 'text-green-500' : 'text-red-500'}`}
              >
                {formatCurrency(metrics.currentMtm)}
              </div>
              <div
                className={`text-sm ${metrics.currentMtm >= 0 ? 'text-green-500' : 'text-red-500'}`}
              >
                {metrics.currentMtm >= 0 ? '+' : ''}
                {((metrics.currentMtm / 100000) * 100).toFixed(2)}%
              </div>
            </CardContent>
          </Card>

          {/* Max MTM */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <TrendingUp className="h-4 w-4 text-green-500" />
                Max MTM
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-green-500">
                {formatCurrency(metrics.maxMtm)}
              </div>
              <div className="text-sm text-muted-foreground">at {metrics.maxMtmTime}</div>
            </CardContent>
          </Card>

          {/* Min MTM */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <TrendingDown className="h-4 w-4 text-red-500" />
                Min MTM
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-red-500">
                {formatCurrency(metrics.minMtm)}
              </div>
              <div className="text-sm text-muted-foreground">at {metrics.minMtmTime}</div>
            </CardContent>
          </Card>

          {/* Max Drawdown */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-1">
                <AlertTriangle className="h-4 w-4 text-yellow-500" />
                Max Drawdown
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold font-mono text-yellow-500">
                {formatCurrency(Math.abs(metrics.maxDrawdown))}
              </div>
              <div className="text-sm text-muted-foreground">Peak to trough</div>
            </CardContent>
          </Card>
        </div>

        {/* Chart Container */}
        <Card>
          <CardHeader>
            <div className="flex justify-between items-center">
              <CardTitle>Intraday PnL Curve</CardTitle>
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-[#570df8]"></span>
                  MTM PnL
                </span>
                <span className="flex items-center gap-1">
                  <span className="inline-block w-3 h-3 rounded-full bg-[#f000b8]"></span>
                  Drawdown
                </span>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <div ref={chartContainerRef} className="relative" style={{ height: '500px' }} />
          </CardContent>
        </Card>
      </div>

      {/* Loading Overlay */}
      {isLoading && (
        <div className="fixed inset-0 bg-background/50 z-50 flex items-center justify-center">
          <Card className="p-8">
            <div className="flex items-center gap-3">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
              <span className="text-lg">Loading PnL data...</span>
            </div>
          </Card>
        </div>
      )}
    </div>
  )
}
