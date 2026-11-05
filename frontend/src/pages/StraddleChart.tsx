/**
 * The dynamic ATM straddle over time, with the spot and the synthetic future
 * beside it.
 *
 * Drawn by openalgo-charts, the engine /trading uses, driven the way the other
 * read-only charts drive it (`BacktestChart`, `CandleViz`): `createChart` on a
 * host div and the app's theme tokens through `buildChartTheme`. The chart is
 * built once and restyled in place, so a theme switch or a series toggle keeps
 * the reader's zoom instead of throwing the chart away.
 *
 * **The straddle is the primary series, on the right axis.** It is what the
 * page is for, so the engine's own readout follows it. Spot and the synthetic
 * future share the left axis: both are index levels, and sharing one scale with
 * a premium would flatten the premium.
 *
 * **Times are real UTC seconds.** The backend sends `int(ts.timestamp())` and
 * the engine shows its axis in IST by default, so the times go in untouched.
 * Adding the 5h30m offset here, as some lightweight-charts pages had to, would
 * label every bar five and a half hours late.
 *
 * **The tooltip is this page's own DOM**, fed by the engine's crosshair: the
 * core tier draws no legend of its own.
 */

import { type Chart, createChart, type SeriesApi } from 'openalgo-charts'
import { Check, ChevronsUpDown } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { oiProfileApi } from '@/api/oi-profile'
import {
  type StraddleChartData,
  type StraddleDataPoint,
  straddleChartApi,
} from '@/api/straddle-chart'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { serverSentence } from '@/lib/serverSentence'
import { buildChartTheme, isLightTheme, resolveCssColor } from '@/lib/trading/chartTheme'
import { type AppMode, type ThemeMode, useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

// FNO_EXCHANGES and DEFAULT_UNDERLYINGS are now provided by useSupportedExchanges() hook

const CHART_HEIGHT = 500

/** Every value on this chart is a price in rupees or index points: two decimals. */
const PRICE_FORMAT = { type: 'price', precision: 2, minMove: 0.01 } as const

/** The share of the pane kept clear above and below each axis's data. */
const SCALE_MARGIN = 0.05

/**
 * The chart theme and the three series colours for one look.
 *
 * The chrome (background, grid, axes, crosshair) is the app's own tokens
 * through `buildChartTheme`. Spot is the text colour, the plainest line on the
 * chart. The straddle and the synthetic future are series identities rather
 * than tokens: green and blue in Live, and in Analyze the straddle takes the
 * mode's violet accent, as it always has on this page.
 */
function straddleLook(mode: ThemeMode, appMode: AppMode) {
  const base = buildChartTheme(mode, appMode)
  const light = isLightTheme(mode, appMode)
  return {
    theme: base,
    spot: resolveCssColor('var(--foreground)'),
    straddle: appMode === 'analyzer' ? base.lineColor : light ? '#16a34a' : '#4ade80',
    synthetic: light ? '#2563eb' : '#60a5fa',
  }
}

type StraddleLook = ReturnType<typeof straddleLook>

/**
 * The chart theme with the value tags in their series' colours.
 *
 * The engine colours the tag of the first visible series by direction, green
 * or red, and every other tag in its own line colour. On this chart a tag
 * names a series, not a move, so the first visible series' colour goes into
 * both directions. That series is the straddle until it is toggled off, when
 * spot (or the synthetic future) takes its place.
 */
function chartThemeFor(
  look: StraddleLook,
  shown: { showStraddle: boolean; showSpot: boolean; showSynthetic: boolean }
) {
  const tag = shown.showStraddle ? look.straddle : shown.showSpot ? look.spot : look.synthetic
  return { ...look.theme, lastPriceUp: tag, lastPriceDown: tag }
}

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function formatIST(unixSeconds: number): { date: string; time: string } {
  const d = new Date(unixSeconds * 1000)
  const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000)
  const dd = ist.getUTCDate().toString().padStart(2, '0')
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ]
  const mo = months[ist.getUTCMonth()]
  const hh = ist.getUTCHours().toString().padStart(2, '0')
  const mm = ist.getUTCMinutes().toString().padStart(2, '0')
  const ampm = ist.getUTCHours() >= 12 ? 'PM' : 'AM'
  return { date: `${dd} ${mo}`, time: `${hh}:${mm} ${ampm}` }
}

export default function StraddleChart() {
  const { mode, appMode } = useThemeStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
  } = useSupportedExchanges()

  // Control state
  const [isLoading, setIsLoading] = useState(false)
  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultFnoExchange] || []
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultFnoExchange]?.[0] || ''
  )
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [intervals, setIntervals] = useState<string[]>([])
  const [selectedInterval, setSelectedInterval] = useState('1m')
  const [selectedDays, setSelectedDays] = useState('3')
  const [chartData, setChartData] = useState<StraddleChartData | null>(null)

  // Series visibility toggles
  const [showStraddle, setShowStraddle] = useState(true)
  const [showSpot, setShowSpot] = useState(false)
  const [showSynthetic, setShowSynthetic] = useState(false)

  // Chart refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)
  const spotSeriesRef = useRef<SeriesApi | null>(null)
  const straddleSeriesRef = useRef<SeriesApi | null>(null)
  const syntheticSeriesRef = useRef<SeriesApi | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<StraddleChartData | null>(null)
  const seriesDataMapRef = useRef<Map<number, StraddleDataPoint>>(new Map())

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Send NFO/BFO directly: the backend resolves the correct exchange for index vs stock

  // Theme colours, for the chart and for the legend and info bar beside it.
  const look = useMemo(() => straddleLook(mode, appMode), [mode, appMode])

  // The tooltip reads the colours on every crosshair move, so it reads them
  // from a ref rather than closing over the look it was created with.
  const lookRef = useRef<StraddleLook>(look)
  lookRef.current = look

  // The toggles as they stand when the chart is built, so a chart built after a
  // toggle starts with the reader's choice rather than the defaults.
  const visibleRef = useRef({ showStraddle, showSpot, showSynthetic })
  visibleRef.current = { showStraddle, showSpot, showSynthetic }

  const applyDataToChart = useCallback((data: StraddleChartData) => {
    if (!data.series || data.series.length === 0) return

    const sorted = [...data.series].sort((a, b) => a.time - b.time)

    // Build lookup map for tooltip
    const map = new Map<number, StraddleDataPoint>()
    for (const p of sorted) {
      map.set(p.time, p)
    }
    seriesDataMapRef.current = map

    // The backend's times are already real UTC seconds, which is what the
    // engine takes. See the module docstring.
    spotSeriesRef.current?.setData(sorted.map((p) => ({ time: p.time, value: p.spot })))
    straddleSeriesRef.current?.setData(sorted.map((p) => ({ time: p.time, value: p.straddle })))
    syntheticSeriesRef.current?.setData(
      sorted.map((p) => ({ time: p.time, value: p.synthetic_future }))
    )

    chartRef.current?.fitContent()
  }, [])

  // ── Chart lifecycle ───────────────────────────────────────────

  // Built once. Theme changes and toggles restyle it in place below, so the
  // reader's zoom survives both.
  useEffect(() => {
    const host = chartContainerRef.current
    if (!host) return

    const initial = lookRef.current
    const shown = visibleRef.current
    const chart = createChart(host, {
      theme: chartThemeFor(initial, shown),
      // A read-only analytic chart: the keyboard belongs to the page's controls.
      shortcuts: false,
      ariaLabel: 'Straddle chart',
    })

    // Straddle first: the primary series, on the right axis.
    const straddleSeries = chart.addSeries('line', {
      priceScaleId: 'right',
      priceFormat: PRICE_FORMAT,
      style: {
        color: initial.straddle,
        lineWidth: 2,
        title: 'Straddle',
        lastValueVisible: true,
        priceLineVisible: true,
        visible: shown.showStraddle,
      },
    })

    // Spot and the synthetic future share the left axis.
    const spotSeries = chart.addSeries('line', {
      priceScaleId: 'left',
      priceFormat: PRICE_FORMAT,
      style: {
        color: initial.spot,
        lineWidth: 2,
        title: 'Spot',
        lastValueVisible: true,
        priceLineVisible: true,
        visible: shown.showSpot,
      },
    })

    const syntheticSeries = chart.addSeries('line', {
      priceScaleId: 'left',
      priceFormat: PRICE_FORMAT,
      style: {
        color: initial.synthetic,
        lineWidth: 1,
        lineStyle: 'dashed',
        title: 'Synthetic Fut',
        lastValueVisible: true,
        priceLineVisible: false,
        visible: shown.showSynthetic,
      },
    })

    straddleSeries.priceScale().setOptions({ marginTop: SCALE_MARGIN, marginBottom: SCALE_MARGIN })
    spotSeries.priceScale().setOptions({ marginTop: SCALE_MARGIN, marginBottom: SCALE_MARGIN })

    chartRef.current = chart
    spotSeriesRef.current = spotSeries
    straddleSeriesRef.current = straddleSeries
    syntheticSeriesRef.current = syntheticSeries

    // The tooltip follows the crosshair. The engine reports the hovered bar in
    // real UTC seconds, the same base the backend's points are keyed in.
    const offCrosshair = chart.subscribeCrosshairMove((e) => {
      const tt = tooltipRef.current
      if (!tt) return

      const point = e.time == null ? undefined : seriesDataMapRef.current.get(e.time)
      if (!point || !e.point) {
        tt.style.display = ''
        return
      }

      const c = lookRef.current
      const { date, time: timeStr } = formatIST(point.time)

      tt.innerHTML = `
        <div class="flex justify-between gap-4 font-semibold" style="color:${c.straddle}">
          <span>Straddle Price</span>
          <span>${point.straddle.toFixed(2)}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">&bull; ${point.atm_strike} Call:</span>
          <span>${point.ce_price.toFixed(2)}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">&bull; ${point.atm_strike} Put:</span>
          <span>${point.pe_price.toFixed(2)}</span>
        </div>
        <div class="flex justify-between gap-4" style="color:${c.synthetic}">
          <span>Synthetic Fut</span>
          <span>${point.synthetic_future.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">Spot Price</span>
          <span>${point.spot.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div class="mt-1 flex justify-between gap-4 border-t border-border pt-1 text-muted-foreground">
          <span>${date}</span>
          <span>${timeStr}</span>
        </div>
      `
      tt.style.display = 'block'

      // Position the tooltip: prefer the right side, flip to the left near the edge
      const tooltipW = tt.offsetWidth
      const tooltipH = tt.offsetHeight
      const { x, y } = e.point
      const margin = 16

      let left = x + margin
      if (left + tooltipW > host.offsetWidth) {
        left = x - tooltipW - margin
      }
      let top = y - tooltipH / 2
      if (top + tooltipH > host.offsetHeight) {
        top = host.offsetHeight - tooltipH
      }
      if (top < 0) top = 0

      tt.style.left = `${left}px`
      tt.style.top = `${top}px`
    })

    // Re-apply data if it arrived before the chart was built.
    if (chartDataRef.current) {
      applyDataToChart(chartDataRef.current)
    }

    return () => {
      offCrosshair()
      chart.destroy()
      // `destroy` releases the engine's listeners; clearing the host is what
      // guarantees a remount starts on an empty div.
      host.innerHTML = ''
      if (tooltipRef.current) tooltipRef.current.style.display = ''
      chartRef.current = null
      spotSeriesRef.current = null
      straddleSeriesRef.current = null
      syntheticSeriesRef.current = null
    }
  }, [applyDataToChart])

  // ── Theme and series visibility ───────────────────────────────

  // Restyled in place, never rebuilt: the chrome through the theme, the lines
  // by their own colours. A toggle re-themes too, because which series is
  // first visible decides whose colour the leading value tag wears.
  useEffect(() => {
    const chart = chartRef.current
    if (!chart) return
    chart.setTheme(chartThemeFor(look, { showStraddle, showSpot, showSynthetic }))
    straddleSeriesRef.current?.applyOptions({ color: look.straddle, visible: showStraddle })
    spotSeriesRef.current?.applyOptions({ color: look.spot, visible: showSpot })
    syntheticSeriesRef.current?.applyOptions({ color: look.synthetic, visible: showSynthetic })
  }, [look, showStraddle, showSpot, showSynthetic])

  // ── Data fetching ─────────────────────────────────────────────

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time mount fetch of available intervals; selectedInterval is only read to seed the default and must not re-trigger this fetch when the user changes interval
  useEffect(() => {
    const fetchIntervals = async () => {
      try {
        const res = await straddleChartApi.getIntervals()
        if (res.status === 'success' && res.data) {
          const all = [
            ...(res.data.seconds || []),
            ...(res.data.minutes || []),
            ...(res.data.hours || []),
          ]
          setIntervals(all.length > 0 ? all : ['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
          if (all.length > 0 && !all.includes(selectedInterval)) {
            setSelectedInterval(all.includes('1m') ? '1m' : all[0])
          }
        }
      } catch {
        setIntervals(['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
      }
    }
    fetchIntervals()
  }, [])

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setChartData(null)
    chartDataRef.current = null

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await oiProfileApi.getUnderlyings(selectedExchange)
        if (cancelled) return
        if (response.status === 'success' && response.underlyings.length > 0) {
          setUnderlyings(response.underlyings)
          if (!response.underlyings.includes(defaults[0])) {
            setSelectedUnderlying(response.underlyings[0])
          }
        }
      } catch {
        // Keep defaults
      }
    }
    fetchUnderlyings()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiry('')
    setChartData(null)
    chartDataRef.current = null

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await oiProfileApi.getExpiries(selectedExchange, selectedUnderlying)
        if (cancelled) return
        if (response.status === 'success' && response.expiries.length > 0) {
          setExpiries(response.expiries)
          setSelectedExpiry(response.expiries[0])
        } else {
          setExpiries([])
          setSelectedExpiry('')
        }
      } catch (error) {
        if (cancelled) return
        showToast.error(serverSentence(error, 'Failed to fetch expiry dates'), 'positions')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

  // ── Load straddle data ────────────────────────────────────────

  const loadData = useCallback(async () => {
    if (!selectedExpiry) return
    setIsLoading(true)
    try {
      const res = await straddleChartApi.getStraddleData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: convertExpiryForAPI(selectedExpiry),
        interval: selectedInterval,
        days: parseInt(selectedDays, 10),
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        applyDataToChart(res.data)
      } else {
        showToast.error(res.message || 'Failed to load straddle data', 'positions')
      }
    } catch (error) {
      showToast.error(serverSentence(error, 'Failed to fetch straddle data'), 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [
    selectedExpiry,
    selectedInterval,
    selectedDays,
    selectedUnderlying,
    selectedExchange,
    applyDataToChart,
  ])

  useEffect(() => {
    loadData()
  }, [loadData])

  // ── Display helpers ───────────────────────────────────────────

  const latestPoint: StraddleDataPoint | null = useMemo(() => {
    if (!chartData?.series?.length) return null
    return chartData.series[chartData.series.length - 1]
  }, [chartData])

  // ── Render ────────────────────────────────────────────────────

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-xl font-semibold">Straddle Chart</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Controls */}
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <Select value={selectedExchange} onValueChange={setSelectedExchange}>
              <SelectTrigger className="w-[100px]">
                <SelectValue placeholder="Exchange" />
              </SelectTrigger>
              <SelectContent>
                {fnoExchanges.map((ex) => (
                  <SelectItem key={ex.value} value={ex.value}>
                    {ex.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  role="combobox"
                  aria-expanded={underlyingOpen}
                  className="w-[140px] justify-between"
                >
                  {selectedUnderlying || 'Underlying'}
                  <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-48 p-0" align="start">
                <Command>
                  <CommandInput placeholder="Search underlying..." />
                  <CommandList>
                    <CommandEmpty>No underlying found</CommandEmpty>
                    <CommandGroup>
                      {underlyings.map((u) => (
                        <CommandItem
                          key={u}
                          value={u}
                          onSelect={() => {
                            setSelectedUnderlying(u)
                            setUnderlyingOpen(false)
                          }}
                        >
                          <Check
                            className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`}
                          />
                          {u}
                        </CommandItem>
                      ))}
                    </CommandGroup>
                  </CommandList>
                </Command>
              </PopoverContent>
            </Popover>

            <Select value={selectedExpiry} onValueChange={setSelectedExpiry}>
              <SelectTrigger className="w-[140px]">
                <SelectValue placeholder="Expiry" />
              </SelectTrigger>
              <SelectContent>
                {expiries.map((exp) => (
                  <SelectItem key={exp} value={exp}>
                    {exp}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={selectedInterval} onValueChange={setSelectedInterval}>
              <SelectTrigger className="w-[100px]">
                <SelectValue placeholder="Interval" />
              </SelectTrigger>
              <SelectContent>
                {intervals.map((intv) => (
                  <SelectItem key={intv} value={intv}>
                    {intv}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={selectedDays} onValueChange={setSelectedDays}>
              <SelectTrigger className="w-[100px]">
                <SelectValue placeholder="Days" />
              </SelectTrigger>
              <SelectContent>
                {['1', '3', '5'].map((d) => (
                  <SelectItem key={d} value={d}>
                    {d} {d === '1' ? 'Day' : 'Days'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Button variant="outline" size="sm" onClick={loadData} disabled={isLoading}>
              {isLoading ? 'Loading...' : 'Refresh'}
            </Button>
          </div>

          {/* Info bar */}
          {latestPoint && chartData && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-sm">
              <div>
                <span className="text-muted-foreground">Straddle Price </span>
                <span className="font-semibold" style={{ color: look.straddle }}>
                  {latestPoint.straddle.toFixed(2)}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Spot </span>
                <span className="font-medium">{latestPoint.spot.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Straddle Strike </span>
                <span className="font-medium">{latestPoint.atm_strike}</span>
              </div>
              <div>
                <span className="text-muted-foreground">{latestPoint.atm_strike} CE </span>
                <span className="font-medium">{latestPoint.ce_price.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">{latestPoint.atm_strike} PE </span>
                <span className="font-medium">{latestPoint.pe_price.toFixed(2)}</span>
              </div>
            </div>
          )}

          {/* Chart */}
          <div className="relative">
            {/* The engine tracks this box's size itself, so it needs a real height. */}
            <div
              ref={chartContainerRef}
              className="relative w-full overflow-hidden rounded-lg border border-border/50"
              style={{ height: CHART_HEIGHT }}
            />
            {/* Filled and placed from the crosshair; hidden until a bar is hovered. */}
            <div
              ref={tooltipRef}
              data-testid="straddle-tooltip"
              className="pointer-events-none absolute z-10 hidden whitespace-nowrap rounded-md border border-border bg-popover/95 px-3 py-2 font-mono text-xs leading-relaxed text-popover-foreground shadow-sm"
            />
            {isLoading && (
              <div className="absolute inset-0 flex items-center justify-center bg-background/60 rounded-lg">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  Loading straddle data...
                </div>
              </div>
            )}
          </div>

          {/* Toggleable Legend */}
          <div className="flex items-center justify-center gap-4 mt-3">
            <button
              type="button"
              onClick={() => setShowStraddle((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
                showStraddle ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded"
                style={{ backgroundColor: look.straddle }}
              />
              Straddle
            </button>
            <button
              type="button"
              onClick={() => setShowSpot((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
                showSpot ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded"
                style={{ backgroundColor: look.spot }}
              />
              Spot
            </button>
            <button
              type="button"
              onClick={() => setShowSynthetic((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
                showSynthetic ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded border-dashed border-t-2"
                style={{ borderColor: look.synthetic, backgroundColor: 'transparent' }}
              />
              Synthetic Fut
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
