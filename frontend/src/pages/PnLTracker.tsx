/**
 * The intraday P&L tracker: the day's MTM curve with its drawdown beneath it,
 * the four summary cards above, and a screenshot of the lot.
 *
 * Drawn by openalgo-charts, the engine /trading uses, driven the way the other
 * read-only charts drive it (`BacktestChart`, `CandleViz`): `createChart` on a
 * host div, the app's theme tokens through `buildChartTheme`, and a theme
 * change applied with `setTheme` rather than by rebuilding the chart.
 *
 * Times arrive from the backend as real UTC milliseconds. They become real UTC
 * seconds here and nothing more: the engine labels them in IST itself, which
 * is its default zone.
 */

import { AlertTriangle, Camera, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import {
  type Chart,
  createChart,
  type PriceLine,
  type SeriesApi,
  type SeriesStyle,
  withAlpha,
} from 'openalgo-charts'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { buildChartTheme } from '@/lib/trading/chartTheme'
import { makeFormatCurrency } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { type AppMode, type ThemeMode, useThemeStore } from '@/stores/themeStore'
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

// PnL and drawdown are plotted in separate panes rather than sharing one price
// scale. Drawdown is always <= 0 and usually an order of magnitude smaller than
// MTM, so overlaying the two flattened both. Split 3:1 in favour of the PnL
// curve, which is the one being read closely.
const CHART_HEIGHT = 500
const PNL_PANE_WEIGHT = 3
const DRAWDOWN_PANE_WEIGHT = 1

// Drawdown keeps the amber of the Max Drawdown card above the chart, so the
// card points at the series it summarises. The theme has no token for it: its
// colours that carry a meaning are profit and loss, and those are what the MTM
// curve wears. Tailwind's yellow-500, as hex because the canvas cannot parse
// the oklch the card's class resolves to.
const COLOR_DRAWDOWN = '#eab308'

/**
 * The chart's palette and the MTM curve's colours for the current theme.
 *
 * The MTM curve is split at break-even in the theme's profit and loss colours,
 * so the colour itself says whether the day is green or red and the crossing
 * is obvious. Its value tag says where the day stands, green at or above zero
 * and red below, not which way the last minute moved; the engine colours that
 * tag from the theme's last-price pair, so the pair is set to the one colour.
 */
function chartLook(mode: ThemeMode, appMode: AppMode, lastPnl: number | null) {
  const base = buildChartTheme(mode, appMode)
  const standing = lastPnl !== null && lastPnl < 0 ? base.downColor : base.upColor
  const pnl: SeriesStyle = {
    baseValue: 0,
    topColor: base.upColor,
    bottomColor: base.downColor,
    areaTopColor: withAlpha(base.upColor, 0.28),
    areaBottomColor: withAlpha(base.downColor, 0.28),
    lineWidth: 2,
  }
  return { theme: { ...base, lastPriceUp: standing, lastPriceDown: standing }, pnl }
}

// Drawdown is also baselined at zero so the fill hangs from break-even down to
// the curve, which reads as depth rather than as a line floating in the middle
// of the pane. It is never positive, so the top half is defined but unused.
//
// Its own value tag is off: the engine colours a series' tag from the theme's
// last-price pair, which here means the MTM curve's green or red, and a green
// tag on the drawdown would read as a profit. The current drawdown is marked
// instead by an amber price line, `DRAWDOWN_LINE_ID`, kept at the last value.
const DRAWDOWN_STYLE: SeriesStyle = {
  baseValue: 0,
  topColor: COLOR_DRAWDOWN,
  bottomColor: COLOR_DRAWDOWN,
  areaTopColor: withAlpha(COLOR_DRAWDOWN, 0),
  areaBottomColor: withAlpha(COLOR_DRAWDOWN, 0.3),
  lineWidth: 2,
  lastValueVisible: false,
  priceLineVisible: false,
}
const DRAWDOWN_LINE_ID = 'pnl-drawdown-now'

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
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)
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
  const chartRef = useRef<Chart | null>(null)
  const pnlSeriesRef = useRef<SeriesApi | null>(null)
  const drawdownSeriesRef = useRef<SeriesApi | null>(null)
  // The last MTM drawn, which decides the colour of its value tag.
  const lastPnlRef = useRef<number | null>(null)
  // The amber mark at the current drawdown, made with the first data.
  const drawdownLineRef = useRef<PriceLine | null>(null)
  // Stable ref for formatCurrency: always holds the latest function without
  // being a useCallback/useEffect dependency. The chart price formatter reads
  // from this ref so it always uses the current broker format, while the chart
  // is built once and never rebuilt for a change of broker.
  const formatCurrencyRef = useRef(formatCurrency)
  useEffect(() => {
    formatCurrencyRef.current = formatCurrency
  }, [formatCurrency])

  // Apply the current theme, and the MTM curve's colours, to the live chart.
  // Reads the store rather than taking the theme as an argument, so the data
  // loader can call it without depending on the theme and refetching on a
  // theme switch.
  const applyLook = useCallback(() => {
    const chart = chartRef.current
    const pnlSeries = pnlSeriesRef.current
    if (!chart || !pnlSeries) return
    const { mode: m, appMode: a } = useThemeStore.getState()
    const look = chartLook(m, a, lastPnlRef.current)
    chart.setTheme(look.theme)
    pnlSeries.applyOptions(look.pnl)
  }, [])

  // Built once. The engine tracks its container's size itself, so there is no
  // resize listener, and a theme change is the effect below: the theme is read
  // here for the first paint only.
  // biome-ignore lint/correctness/useExhaustiveDependencies: theme excluded; handled by the re-theme effect
  useEffect(() => {
    const container = chartContainerRef.current
    if (!container) return

    const look = chartLook(mode, appMode, lastPnlRef.current)
    const chart = createChart(container, {
      theme: look.theme,
      ariaLabel: 'Intraday PnL curve and drawdown',
      // A read-only report: the keyboard belongs to the page, and the hover
      // zoom rail is chrome this chart does not need.
      shortcuts: false,
      timeNavigator: false,
    })
    const money = (price: number) => formatCurrencyRef.current(price)

    // PnL in the upper pane, split at break-even.
    const pnlSeries = chart.addSeries('baseline', {
      paneIndex: 0,
      priceScaleId: 'right',
      style: look.pnl,
      priceFormat: { type: 'custom', formatter: money },
    })
    pnlSeries.priceScale().setOptions({ marginTop: 0.1, marginBottom: 0.1 })

    // Drawdown in its own pane, under the curve it measures.
    const drawdownSeries = chart.addSeries('baseline', {
      paneIndex: 1,
      priceScaleId: 'right',
      style: DRAWDOWN_STYLE,
      priceFormat: { type: 'custom', formatter: money },
    })
    drawdownSeries.priceScale().setOptions({ marginTop: 0.1, marginBottom: 0.1 })

    // Adding the series creates the second pane; size them 3:1 now that it exists.
    chart.setPaneWeight(0, PNL_PANE_WEIGHT)
    chart.setPaneWeight(1, DRAWDOWN_PANE_WEIGHT)

    chartRef.current = chart
    pnlSeriesRef.current = pnlSeries
    drawdownSeriesRef.current = drawdownSeries

    return () => {
      chart.destroy()
      // `destroy` releases the engine's listeners; clearing the host is what
      // guarantees a remount starts on an empty div rather than stacking a
      // second canvas on the first.
      container.innerHTML = ''
      chartRef.current = null
      pnlSeriesRef.current = null
      drawdownSeriesRef.current = null
      drawdownLineRef.current = null
    }
  }, [])

  // Re-theme the chart in place. No rebuild and no refetch: the data is the
  // same whichever theme it is drawn in.
  // biome-ignore lint/correctness/useExhaustiveDependencies: applyLook reads the theme from the store; mode and appMode are the trigger
  useEffect(() => {
    applyLook()
  }, [mode, appMode, applyLook])

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

        // Update chart. Milliseconds to seconds, still real UTC: see the
        // module docstring.
        if (pnlSeriesRef.current && data.pnl_series && Array.isArray(data.pnl_series)) {
          const pnlData = data.pnl_series
            .map((point) => ({ time: Math.floor(point.time / 1000), value: point.value }))
            .sort((a, b) => a.time - b.time)

          if (pnlData.length > 0) {
            pnlSeriesRef.current.setData(pnlData)
            lastPnlRef.current = pnlData[pnlData.length - 1].value
            // The value tag follows where the day now stands.
            applyLook()
          }
        }

        if (
          drawdownSeriesRef.current &&
          data.drawdown_series &&
          Array.isArray(data.drawdown_series)
        ) {
          const drawdownData = data.drawdown_series
            .map((point) => ({ time: Math.floor(point.time / 1000), value: point.value }))
            .sort((a, b) => a.time - b.time)

          if (drawdownData.length > 0) {
            drawdownSeriesRef.current.setData(drawdownData)
            // The current drawdown, marked in amber on its own axis.
            const now = drawdownData[drawdownData.length - 1].value
            const label = formatCurrencyRef.current(now)
            if (drawdownLineRef.current) {
              drawdownLineRef.current.setOptions({ price: now, label })
            } else if (chartRef.current) {
              drawdownLineRef.current = chartRef.current.addPriceLine(
                {
                  id: DRAWDOWN_LINE_ID,
                  price: now,
                  color: COLOR_DRAWDOWN,
                  lineWidth: 1,
                  dashed: true,
                  label,
                },
                1
              )
            }
          }
        }

        if (chartRef.current) {
          chartRef.current.fitContent()
        }
      } else {
        showToast.error(result.message || 'Failed to load PnL data', 'positions')
      }
    } catch (_error) {
      showToast.error('Failed to load PnL data. Please try again.', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [applyLook])

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
        getComputedStyle(document.body).backgroundColor || (mode === 'dark' ? '#1f2937' : '#ffffff')

      // The chart goes into the image as the engine's own export of itself,
      // not as html2canvas' copy of its canvases. html2canvas copies a canvas
      // by reading its pixels back, and the chart's canvases live for the whole
      // visit, so from the second capture on Chrome flags every one of them
      // for repeated readback. The engine's export is one fresh canvas per
      // capture, with the axes and the corner mark already in it.
      const chartHost = chartContainerRef.current
      const chartImage = chartRef.current?.takeScreenshot().toDataURL('image/png') ?? null

      const canvas = await html2canvas(screenshotContainerRef.current, {
        backgroundColor: pageBackground,
        scale: 2,
        logging: false,
        useCORS: true,
        ignoreElements: (element) =>
          chartImage !== null &&
          element instanceof HTMLCanvasElement &&
          chartHost?.contains(element) === true,
        onclone: (clonedDocument) => {
          if (chartImage === null) return
          const clonedHost = clonedDocument.querySelector('[data-pnl-chart]')
          if (!clonedHost) return
          const image = clonedDocument.createElement('img')
          image.src = chartImage
          image.alt = ''
          image.style.cssText = 'position:absolute;inset:0;width:100%;height:100%'
          clonedHost.appendChild(image)
        },
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

  // Load the day once the chart above exists to take it.
  useEffect(() => {
    loadPnLData()
  }, [loadPnLData])

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
            <div
              ref={chartContainerRef}
              data-pnl-chart=""
              className="relative"
              style={{ height: CHART_HEIGHT }}
            />
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
