/**
 * The simulated P&L of an intraday ATM straddle, with the spot and the
 * synthetic future beside it, and the trade log under it.
 *
 * Drawn by openalgo-charts, the engine /trading uses, driven the way the other
 * read-only charts drive it (`BacktestChart`, `CandleViz`): `createChart` on a
 * host div and the app's theme tokens through `buildChartTheme`. The chart is
 * built once and restyled in place, so a theme switch or a series toggle keeps
 * the reader's zoom instead of throwing the chart away.
 *
 * **P&L is the primary series: a baseline at zero, on the right axis.** Above
 * zero it is drawn in the theme's up colour, below it in the down colour, the
 * same pair every other profit and loss on the platform wears. Spot and the
 * synthetic future share the left axis: both are index levels, and sharing a
 * scale with rupees of P&L would flatten the P&L.
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
import {
  type CustomStraddleData,
  customStraddleApi,
  type PnLDataPoint,
  type TradeEntry,
} from '@/api/custom-straddle'
import { oiProfileApi } from '@/api/oi-profile'
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
import { Input } from '@/components/ui/input'
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

const LOT_SIZE_DEFAULTS: Record<string, number> = {
  NIFTY: 65,
  BANKNIFTY: 30,
  FINNIFTY: 60,
  MIDCPNIFTY: 120,
  NIFTYNXT50: 25,
  SENSEX: 10,
  BANKEX: 15,
}

const ADJUSTMENT_DEFAULTS: Record<string, number> = {
  NIFTY: 50,
  BANKNIFTY: 100,
  FINNIFTY: 50,
  MIDCPNIFTY: 25,
  NIFTYNXT50: 50,
  SENSEX: 100,
  BANKEX: 100,
}

const CHART_HEIGHT = 480

/** Every value on this chart is rupees or index points: two decimals. */
const PRICE_FORMAT = { type: 'price', precision: 2, minMove: 0.01 } as const

/** The share of the pane kept clear above and below the P&L and the index levels. */
const PNL_MARGIN = 0.1
const INDEX_MARGIN = 0.05

/**
 * The chart theme and the series colours for one look.
 *
 * The chrome (background, grid, axes, crosshair) is the app's own tokens
 * through `buildChartTheme`, and so are profit and loss: the P&L baseline
 * takes its line and fill from the theme's baseline colours, which are its
 * up and down pair. Spot is the text colour, the plainest line on the chart.
 * The synthetic future is a series identity rather than a token, blue as it
 * has always been on this page.
 */
function pnlLook(mode: ThemeMode, appMode: AppMode) {
  const base = buildChartTheme(mode, appMode)
  return {
    theme: base,
    profit: base.upColor,
    loss: base.downColor,
    spot: resolveCssColor('var(--foreground)'),
    synthetic: isLightTheme(mode, appMode) ? '#2563eb' : '#60a5fa',
  }
}

type PnlLook = ReturnType<typeof pnlLook>

/**
 * The chart theme with the leading value tag in a colour that means something.
 *
 * The engine colours the tag of the first visible series by the direction of
 * its last move. For P&L the question is where the run stands, not which way
 * the last bar went, so the tag is the profit colour at or above zero and the
 * loss colour below it, as the line itself is. With P&L toggled off, spot (or
 * the synthetic future) leads, and its tag wears its own line colour.
 */
function chartThemeFor(
  look: PnlLook,
  shown: { showPnL: boolean; showSpot: boolean; showSynthetic: boolean },
  lastPnl: number | null
) {
  const tag = shown.showPnL
    ? (lastPnl ?? 0) >= 0
      ? look.profit
      : look.loss
    : shown.showSpot
      ? look.spot
      : look.synthetic
  return { ...look.theme, lastPriceUp: tag, lastPriceDown: tag }
}

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
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

function formatINR(value: number): string {
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString('en-IN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
  return value < 0 ? `-${formatted}` : formatted
}

export default function CustomStraddle() {
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
  const [intervals, setIntervals] = useState<string[]>([
    '1m',
    '3m',
    '5m',
    '10m',
    '15m',
    '30m',
    '1h',
  ])
  const [selectedInterval, setSelectedInterval] = useState('1m')
  const [selectedDays, setSelectedDays] = useState('1')

  // Strategy controls
  const [lotSize, setLotSize] = useState(65)
  const [numLots, setNumLots] = useState(1)
  const [adjustmentPoints, setAdjustmentPoints] = useState(50)

  // Chart / data
  const [chartData, setChartData] = useState<CustomStraddleData | null>(null)
  const [showPnL, setShowPnL] = useState(true)
  const [showSpot, setShowSpot] = useState(false)
  const [showSynthetic, setShowSynthetic] = useState(false)

  // Refs
  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<Chart | null>(null)
  const pnlSeriesRef = useRef<SeriesApi | null>(null)
  const spotSeriesRef = useRef<SeriesApi | null>(null)
  const syntheticSeriesRef = useRef<SeriesApi | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<CustomStraddleData | null>(null)
  const seriesDataMapRef = useRef<Map<number, PnLDataPoint>>(new Map())
  // The last P&L drawn, which decides the colour of its value tag.
  const lastPnlRef = useRef<number | null>(null)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Theme colours, for the chart and for the legend beside it.
  const look = useMemo(() => pnlLook(mode, appMode), [mode, appMode])

  // Read on every crosshair move and on every data load, so they are read from
  // refs rather than closed over.
  const lookRef = useRef<PnlLook>(look)
  lookRef.current = look
  const visibleRef = useRef({ showPnL, showSpot, showSynthetic })
  visibleRef.current = { showPnL, showSpot, showSynthetic }

  /** Push the current look, toggles and last P&L into the chart's theme. */
  const applyTheme = useCallback(() => {
    chartRef.current?.setTheme(
      chartThemeFor(lookRef.current, visibleRef.current, lastPnlRef.current)
    )
  }, [])

  // ── Chart ────────────────────────────────────────────────────

  const applyDataToChart = useCallback(
    (data: CustomStraddleData) => {
      if (!data.pnl_series?.length) return

      const sorted = [...data.pnl_series].sort((a, b) => a.time - b.time)
      const map = new Map<number, PnLDataPoint>()
      for (const p of sorted) map.set(p.time, p)
      seriesDataMapRef.current = map
      lastPnlRef.current = sorted[sorted.length - 1].pnl

      // The backend's times are already real UTC seconds, which is what the
      // engine takes. See the module docstring.
      pnlSeriesRef.current?.setData(sorted.map((p) => ({ time: p.time, value: p.pnl })))
      spotSeriesRef.current?.setData(sorted.map((p) => ({ time: p.time, value: p.spot })))
      syntheticSeriesRef.current?.setData(
        sorted.map((p) => ({ time: p.time, value: p.synthetic_future }))
      )

      // A run that ended in a loss turns the value tag red.
      applyTheme()
      chartRef.current?.fitContent()
    },
    [applyTheme]
  )

  // Built once. Theme changes and toggles restyle it in place below, so the
  // reader's zoom survives both.
  useEffect(() => {
    const host = chartContainerRef.current
    if (!host) return

    const shown = visibleRef.current
    const chart = createChart(host, {
      theme: chartThemeFor(lookRef.current, shown, lastPnlRef.current),
      // A read-only analytic chart: the keyboard belongs to the page's controls.
      shortcuts: false,
      ariaLabel: 'Straddle P&L chart',
    })

    // P&L first: the primary series, a baseline at zero on the right axis. Its
    // colours are left to the theme, whose baseline pair is profit and loss.
    const pnlSeries = chart.addSeries('baseline', {
      priceScaleId: 'right',
      priceFormat: PRICE_FORMAT,
      style: {
        baseValue: 0,
        lineWidth: 2,
        title: 'P&L',
        lastValueVisible: true,
        priceLineVisible: true,
        visible: shown.showPnL,
      },
    })

    // Spot and the synthetic future share the left axis.
    const spotSeries = chart.addSeries('line', {
      priceScaleId: 'left',
      priceFormat: PRICE_FORMAT,
      style: {
        color: lookRef.current.spot,
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
        color: lookRef.current.synthetic,
        lineWidth: 1,
        lineStyle: 'dashed',
        title: 'Synthetic Fut',
        lastValueVisible: true,
        priceLineVisible: false,
        visible: shown.showSynthetic,
      },
    })

    pnlSeries.priceScale().setOptions({ marginTop: PNL_MARGIN, marginBottom: PNL_MARGIN })
    spotSeries.priceScale().setOptions({ marginTop: INDEX_MARGIN, marginBottom: INDEX_MARGIN })

    chartRef.current = chart
    pnlSeriesRef.current = pnlSeries
    spotSeriesRef.current = spotSeries
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
      const pnlColor = point.pnl >= 0 ? c.profit : c.loss

      tt.innerHTML = `
        <div class="flex justify-between gap-4 font-semibold" style="color:${pnlColor}">
          <span>P&amp;L</span>
          <span>${formatINR(point.pnl)}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">Spot</span>
          <span>${point.spot.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">ATM Strike</span>
          <span>${point.atm_strike}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">Entry Strike</span>
          <span>${point.entry_strike}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">Straddle</span>
          <span>${point.straddle.toFixed(2)}</span>
        </div>
        <div class="flex justify-between gap-4" style="color:${c.synthetic}">
          <span>Synthetic Fut</span>
          <span>${point.synthetic_future.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div class="flex justify-between gap-4">
          <span class="text-muted-foreground">Adjustments</span>
          <span>${point.adjustments}</span>
        </div>
        <div class="mt-1 flex justify-between gap-4 border-t border-border pt-1 text-muted-foreground">
          <span>${date}</span>
          <span>${timeStr}</span>
        </div>
      `
      tt.style.display = 'block'

      // Position the tooltip: prefer the right side, flip to the left near the edge.
      const tooltipW = tt.offsetWidth
      const tooltipH = tt.offsetHeight
      const { x, y } = e.point
      let left = x + 16
      if (left + tooltipW > host.offsetWidth) left = x - tooltipW - 16
      let top = y - tooltipH / 2
      if (top + tooltipH > host.offsetHeight) top = host.offsetHeight - tooltipH
      if (top < 0) top = 0
      tt.style.left = `${left}px`
      tt.style.top = `${top}px`
    })

    // Re-apply data if it arrived before the chart was built.
    if (chartDataRef.current) applyDataToChart(chartDataRef.current)

    return () => {
      offCrosshair()
      chart.destroy()
      // `destroy` releases the engine's listeners; clearing the host is what
      // guarantees a remount starts on an empty div.
      host.innerHTML = ''
      if (tooltipRef.current) tooltipRef.current.style.display = ''
      chartRef.current = null
      pnlSeriesRef.current = null
      spotSeriesRef.current = null
      syntheticSeriesRef.current = null
    }
  }, [applyDataToChart])

  // Restyled in place, never rebuilt: the chrome and the P&L through the
  // theme, the index lines by their own colours. A toggle re-themes too,
  // because which series is first visible decides whose colour the leading
  // value tag wears.
  useEffect(() => {
    if (!chartRef.current) return
    applyTheme()
    pnlSeriesRef.current?.applyOptions({ visible: showPnL })
    spotSeriesRef.current?.applyOptions({ color: look.spot, visible: showSpot })
    syntheticSeriesRef.current?.applyOptions({ color: look.synthetic, visible: showSynthetic })
  }, [look, showPnL, showSpot, showSynthetic, applyTheme])

  // ── Data fetching ────────────────────────────────────────────

  // biome-ignore lint/correctness/useExhaustiveDependencies: one-time fetch of available intervals on mount; selectedInterval is only read to seed the initial default and must not retrigger the network call when the user changes the interval.
  useEffect(() => {
    const fetchIntervals = async () => {
      try {
        const res = await customStraddleApi.getIntervals()
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

  // Fetch underlyings on exchange change
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
          if (!response.underlyings.includes(defaults[0]))
            setSelectedUnderlying(response.underlyings[0])
        }
      } catch {
        /* keep defaults */
      }
    }
    fetchUnderlyings()
    return () => {
      cancelled = true
    }
  }, [selectedExchange, defaultUnderlyings])

  // Fetch lot size from DB and set adjustment defaults when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setAdjustmentPoints(ADJUSTMENT_DEFAULTS[selectedUnderlying] || 50)

    let cancelled = false
    const fetchLotSize = async () => {
      try {
        const res = await customStraddleApi.getLotSize(selectedUnderlying, selectedExchange)
        if (cancelled) return
        if (res.status === 'success' && res.lotsize) {
          setLotSize(res.lotsize)
        } else {
          setLotSize(LOT_SIZE_DEFAULTS[selectedUnderlying] || 50)
        }
      } catch {
        if (!cancelled) setLotSize(LOT_SIZE_DEFAULTS[selectedUnderlying] || 50)
      }
    }
    fetchLotSize()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

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
        if (!cancelled)
          showToast.error(serverSentence(error, 'Failed to fetch expiry dates'), 'positions')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

  // ── Load simulation data ─────────────────────────────────────

  const loadData = useCallback(async () => {
    if (!selectedExpiry) return
    setIsLoading(true)
    try {
      const res = await customStraddleApi.simulate({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: convertExpiryForAPI(selectedExpiry),
        interval: selectedInterval,
        days: parseInt(selectedDays, 10),
        adjustment_points: adjustmentPoints,
        lot_size: lotSize,
        lots: numLots,
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        applyDataToChart(res.data)
      } else {
        showToast.error(res.message || 'Failed to load simulation data', 'positions')
      }
    } catch (err: unknown) {
      const axiosErr = err as { response?: { data?: { message?: string } } }
      const msg = axiosErr?.response?.data?.message || 'Failed to fetch simulation data'
      showToast.error(msg, 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [
    selectedExpiry,
    selectedInterval,
    selectedDays,
    selectedUnderlying,
    selectedExchange,
    adjustmentPoints,
    lotSize,
    numLots,
    applyDataToChart,
  ])

  // ── Display helpers ──────────────────────────────────────────

  const latestPoint: PnLDataPoint | null = useMemo(() => {
    if (!chartData?.pnl_series?.length) return null
    return chartData.pnl_series[chartData.pnl_series.length - 1]
  }, [chartData])

  const summary = chartData?.summary

  // ── Render ───────────────────────────────────────────────────

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-xl font-semibold">Straddle PnL Simulator</CardTitle>
        </CardHeader>
        <CardContent>
          {/* Row 1: Market controls */}
          <div className="flex flex-wrap items-center gap-3 mb-3">
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
                {['1', '3', '5', '7', '10'].map((d) => (
                  <SelectItem key={d} value={d}>
                    {d} {d === '1' ? 'Day' : 'Days'}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {/* Row 2: Strategy controls */}
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Lot Size</label>
              <Input
                type="number"
                value={lotSize}
                onChange={(e) => setLotSize(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="w-[80px] h-9"
                min={1}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Lots</label>
              <Input
                type="number"
                value={numLots}
                onChange={(e) => setNumLots(Math.max(1, parseInt(e.target.value, 10) || 1))}
                className="w-[70px] h-9"
                min={1}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Adj Points</label>
              <Input
                type="number"
                value={adjustmentPoints}
                onChange={(e) =>
                  setAdjustmentPoints(Math.max(1, parseInt(e.target.value, 10) || 1))
                }
                className="w-[80px] h-9"
                min={1}
              />
            </div>
            <div className="text-xs text-muted-foreground">
              Qty: <span className="font-medium text-foreground">{lotSize * numLots}</span>
            </div>
            <Button variant="outline" size="sm" onClick={loadData} disabled={isLoading}>
              {isLoading ? 'Simulating...' : 'Simulate'}
            </Button>
          </div>

          {/* Summary bar */}
          {summary && latestPoint && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-sm">
              <div>
                <span className="text-muted-foreground">P&L </span>
                <span
                  className={`font-semibold ${summary.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}
                >
                  {formatINR(summary.total_pnl)}
                </span>
              </div>
              <div>
                <span className="text-muted-foreground">Adjustments </span>
                <span className="font-medium">{summary.total_adjustments}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Max </span>
                <span className="font-medium text-green-500">{formatINR(summary.max_pnl)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Min </span>
                <span className="font-medium text-red-500">{formatINR(summary.min_pnl)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Spot </span>
                <span className="font-medium">{latestPoint.spot.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">Entry Strike </span>
                <span className="font-medium">{latestPoint.entry_strike}</span>
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
              data-testid="straddle-pnl-tooltip"
              className="pointer-events-none absolute z-10 hidden whitespace-nowrap rounded-md border border-border bg-popover/95 px-3 py-2 font-mono text-xs leading-relaxed text-popover-foreground shadow-sm"
            />
            {isLoading && (
              <div className="absolute inset-0 flex items-center justify-center bg-background/60 rounded-lg">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  Running simulation...
                </div>
              </div>
            )}
          </div>

          {/* Legend toggles */}
          <div className="flex items-center justify-center gap-4 mt-3">
            <button
              type="button"
              onClick={() => setShowPnL((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${showPnL ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'}`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded"
                style={{ backgroundColor: look.profit }}
              />
              P&L
            </button>
            <button
              type="button"
              onClick={() => setShowSpot((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${showSpot ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'}`}
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
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${showSynthetic ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'}`}
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

      {/* Trades Table */}
      {chartData?.trades && chartData.trades.length > 0 && (
        <Card className="mt-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg font-semibold">
              Trade Log ({chartData.trades.length} trades)
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto max-h-[400px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-background border-b">
                  <tr className="text-left text-muted-foreground">
                    <th className="py-2 pr-4 font-medium">Time</th>
                    <th className="py-2 pr-4 font-medium">Type</th>
                    <th className="py-2 pr-4 font-medium text-right">Strike</th>
                    <th className="py-2 pr-4 font-medium text-right">CE</th>
                    <th className="py-2 pr-4 font-medium text-right">PE</th>
                    <th className="py-2 pr-4 font-medium text-right">Straddle</th>
                    <th className="py-2 pr-4 font-medium text-right">Spot</th>
                    <th className="py-2 pr-4 font-medium text-right">Leg P&L</th>
                    <th className="py-2 font-medium text-right">Cumulative</th>
                  </tr>
                </thead>
                <tbody>
                  {chartData.trades.map((trade, idx) => (
                    <TradeRow key={idx} trade={trade} />
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}

function TradeRow({ trade }: { trade: TradeEntry }) {
  const { date, time } = formatIST(trade.time)
  const typeColor =
    trade.type === 'ENTRY'
      ? 'text-blue-500'
      : trade.type === 'ADJUSTMENT'
        ? 'text-amber-500'
        : 'text-purple-500'

  const pnlColor = trade.leg_pnl > 0 ? 'text-green-500' : trade.leg_pnl < 0 ? 'text-red-500' : ''
  const cumColor =
    trade.cumulative_pnl > 0 ? 'text-green-500' : trade.cumulative_pnl < 0 ? 'text-red-500' : ''

  const strikeDisplay =
    trade.type === 'ADJUSTMENT' && trade.old_strike
      ? `${trade.old_strike} -> ${trade.strike}`
      : `${trade.strike}`

  return (
    <tr className="border-b border-border/30 hover:bg-muted/30">
      <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">
        {date} {time}
      </td>
      <td className={`py-2 pr-4 font-medium ${typeColor}`}>{trade.type}</td>
      <td className="py-2 pr-4 text-right font-mono">{strikeDisplay}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.ce_price.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.pe_price.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.straddle.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.spot.toFixed(2)}</td>
      <td className={`py-2 pr-4 text-right font-mono ${pnlColor}`}>
        {trade.type === 'ENTRY' ? '-' : formatINR(trade.leg_pnl)}
      </td>
      <td className={`py-2 text-right font-mono ${cumColor}`}>{formatINR(trade.cumulative_pnl)}</td>
    </tr>
  )
}
