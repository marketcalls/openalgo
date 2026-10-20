import { AlertTriangle, Camera, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

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
  BaselineSeries,
  ColorType,
  CrosshairMode,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'

// PnL and drawdown are plotted in separate panes rather than sharing one price
// scale. Drawdown is always <= 0 and usually an order of magnitude smaller than
// MTM, so overlaying the two flattened both. Split 3:1 in favour of the PnL
// curve, which is the one being read closely.
const CHART_HEIGHT = 500
const PNL_PANE_RATIO = 3
const DRAWDOWN_PANE_RATIO = 1
const PNL_PANE_HEIGHT = Math.round(
  (CHART_HEIGHT * PNL_PANE_RATIO) / (PNL_PANE_RATIO + DRAWDOWN_PANE_RATIO)
)
const DRAWDOWN_PANE_HEIGHT = CHART_HEIGHT - PNL_PANE_HEIGHT

// Series colors deliberately mirror the metric cards above the chart, so each
// card points at the series it summarises: green and red for MTM either side of
// break-even, amber for drawdown. Tailwind 500-weight hex values, because the
// canvas cannot parse the oklch CSS tokens the cards use.
const COLOR_PROFIT = '#22c55e' // green-500, matches a positive Current MTM
const COLOR_LOSS = '#ef4444' // red-500, matches a negative Current MTM
const COLOR_DRAWDOWN = '#eab308' // yellow-500, matches the Max Drawdown card

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

export default function PnLTracker() {
  const { mode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  const { user } = useAuthStore()
  const formatCurrency = useMemo(() => makeFormatCurrency(user?.broker), [user?.broker])

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
  const pnlSeriesRef = useRef<ISeriesApi<'Baseline'> | null>(null)
  const drawdownSeriesRef = useRef<ISeriesApi<'Baseline'> | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)
  // Stable ref for formatCurrency — always holds the latest function without
  // being a useCallback/useEffect dependency.  The chart price formatter reads
  // from this ref so it always uses the current broker format, while initChart
  // does NOT need formatCurrency in its dependency array.  This prevents the
  // cascade: user?.broker changes → formatCurrency new ref → initChart new ref
  // → both useEffects fire → duplicate chart init + duplicate API requests.
  const formatCurrencyRef = useRef(formatCurrency)
  useEffect(() => {
    formatCurrencyRef.current = formatCurrency
  }, [formatCurrency])

  // Initialize chart
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return

    // Remove existing chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    // Remove existing watermark before creating a new one — prevents stacking
    // multiple watermark divs when initChart is called more than once (e.g. on
    // theme change or dependency array re-evaluation).
    if (watermarkRef.current?.parentNode) {
      watermarkRef.current.parentNode.removeChild(watermarkRef.current)
      watermarkRef.current = null
    }

    const container = chartContainerRef.current

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: isDarkMode ? '#a6adbb' : '#333',
        panes: {
          enableResize: true,
          separatorColor: isDarkMode ? 'rgba(166, 173, 187, 0.2)' : 'rgba(0, 0, 0, 0.2)',
          separatorHoverColor: isDarkMode ? 'rgba(166, 173, 187, 0.4)' : 'rgba(0, 0, 0, 0.35)',
        },
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
      // Centre within the PnL pane rather than the whole chart, so the 3:1 split
      // does not leave the watermark straddling the pane separator.
      //
      // paneSize() reads live chart internals and throws once the chart has been
      // disposed — which happens here, because this runs from a setTimeout and
      // from the resize handler, both of which can outlive a re-init on theme
      // change. Fall back to the configured height; the watermark is cosmetic
      // and must never take the resize handler down with it.
      let topPaneHeight = PNL_PANE_HEIGHT
      try {
        topPaneHeight = chart.paneSize(0).height || PNL_PANE_HEIGHT
      } catch {
        // Chart already disposed; the constant is still the right answer.
      }
      watermark.style.left = `${container.offsetWidth / 2 - watermark.offsetWidth / 2}px`
      watermark.style.top = `${topPaneHeight / 2 - watermark.offsetHeight / 2}px`
    }
    setTimeout(positionWatermark, 0)

    // PnL in the upper pane, split at break-even so the colour itself says
    // whether the day is green or red, and the crossing point is obvious.
    const pnlSeries = chart.addSeries(
      BaselineSeries,
      {
        baseValue: { type: 'price', price: 0 },
        topLineColor: COLOR_PROFIT,
        topFillColor1: 'rgba(34, 197, 94, 0.28)',
        topFillColor2: 'rgba(34, 197, 94, 0.02)',
        bottomLineColor: COLOR_LOSS,
        bottomFillColor1: 'rgba(239, 68, 68, 0.02)',
        bottomFillColor2: 'rgba(239, 68, 68, 0.28)',
        lineWidth: 2,
        priceScaleId: 'right',
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => formatCurrencyRef.current(price),
        },
      },
      0
    )

    // Drawdown in its own pane. Also baselined at zero so the fill hangs from
    // break-even down to the curve, which reads as depth rather than as a line
    // floating in the middle of the pane.
    const drawdownSeries = chart.addSeries(
      BaselineSeries,
      {
        baseValue: { type: 'price', price: 0 },
        // Drawdown is never positive; the top half is defined but unused.
        topLineColor: COLOR_DRAWDOWN,
        topFillColor1: 'rgba(234, 179, 8, 0)',
        topFillColor2: 'rgba(234, 179, 8, 0)',
        bottomLineColor: COLOR_DRAWDOWN,
        bottomFillColor1: 'rgba(234, 179, 8, 0.04)',
        bottomFillColor2: 'rgba(234, 179, 8, 0.30)',
        lineWidth: 2,
        priceScaleId: 'right',
        priceFormat: {
          type: 'custom',
          formatter: (price: number) => formatCurrencyRef.current(price),
        },
      },
      1
    )

    // Adding the series creates the second pane; size them 3:1 now that it exists.
    const panes = chart.panes()
    if (panes.length > 1) {
      panes[0].setHeight(PNL_PANE_HEIGHT)
      panes[1].setHeight(DRAWDOWN_PANE_HEIGHT)
    }

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
    } catch (_error) {
      showToast.error('Failed to load PnL data. Please try again.', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Take screenshot - html2canvas-pro supports oklch colors natively
  const takeScreenshot = async () => {
    if (!screenshotContainerRef.current) return

    setIsCapturing(true)

    // html2canvas-pro clones every canvas on the page and reads each one back
    // with getImageData, but builds those contexts without willReadFrequently,
    // so Chrome logs a performance warning per canvas on every capture. Opt the
    // clones in for the duration of the capture only.
    //
    // The isConnected guard is what makes this safe: html2canvas' clones are
    // detached when it asks for their context, while the live chart canvases are
    // in the document. Without the guard we would also flag the chart's own
    // context, which pins it to software rendering for the rest of the session.
    const originalGetContext = HTMLCanvasElement.prototype.getContext
    HTMLCanvasElement.prototype.getContext = function patchedGetContext(
      this: HTMLCanvasElement,
      contextId: string,
      options?: unknown
    ) {
      if (contextId === '2d' && !this.isConnected) {
        return originalGetContext.call(this, contextId, {
          ...(options as CanvasRenderingContext2DSettings),
          willReadFrequently: true,
        })
      }
      return originalGetContext.call(this, contextId, options as never)
    } as typeof HTMLCanvasElement.prototype.getContext

    try {
      // Match the page's own background instead of a hardcoded slate, so the
      // exported PNG does not sit on a colour the app never shows. Reading the
      // computed style also keeps it correct for any future theme.
      const pageBackground =
        getComputedStyle(document.body).backgroundColor || (isDarkMode ? '#1f2937' : '#ffffff')

      const canvas = await html2canvas(screenshotContainerRef.current, {
        backgroundColor: pageBackground,
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
    } catch (_error) {
      showToast.error('Failed to capture screenshot', 'positions')
    } finally {
      // Always restore, including on the error path — a leaked prototype patch
      // would outlive this page and affect every canvas in the app.
      HTMLCanvasElement.prototype.getContext = originalGetContext
      setIsCapturing(false)
    }
  }

  // Initialize chart and load data
  useEffect(() => {
    const resizeCleanup = initChart()
    loadPnLData()

    return () => {
      // Remove the resize listener registered inside initChart
      resizeCleanup?.()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
      if (watermarkRef.current?.parentNode) {
        watermarkRef.current.parentNode.removeChild(watermarkRef.current)
        watermarkRef.current = null
      }
    }
  }, [initChart, loadPnLData])

  // Re-initialize chart on theme change
  useEffect(() => {
    if (chartRef.current) {
      const resizeCleanup = initChart()
      loadPnLData()
      return resizeCleanup
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
            <div className="flex flex-wrap justify-between items-center gap-2">
              <CardTitle>Intraday PnL Curve</CardTitle>
              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                <span className="flex items-center gap-1.5">
                  {/* Split swatch: the MTM curve is green above break-even, red below */}
                  <span className="inline-flex h-3 w-3 overflow-hidden rounded-full">
                    <span className="h-full w-1/2 bg-green-500" />
                    <span className="h-full w-1/2 bg-red-500" />
                  </span>
                  MTM PnL
                </span>
                <span className="flex items-center gap-1.5">
                  <span className="inline-block w-3 h-3 rounded-full bg-yellow-500"></span>
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
