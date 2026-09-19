import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type CandleData, type OIProfileDataResponse, oiProfileApi } from '@/api/oi-profile'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
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
import Plot from '@/lib/Plot2D'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

// FNO_EXCHANGES and DEFAULT_UNDERLYINGS are now provided by useSupportedExchanges() hook

// The backend sums at most this many expiries in one request
const MAX_EXPIRIES = 6

const INTERVAL_DAYS: Record<string, number> = {
  '1m': 1,
  '5m': 5,
  '15m': 7,
}

// How often a live page re-asks for the profile, in milliseconds. A closed
// market cannot move, but the beat still has to come back slowly rather than
// stop: a page left open overnight has to notice the next session opening.
const LIVE_REFRESH_MS = 3 * 60 * 1000
const CLOSED_REFRESH_MS = 15 * 60 * 1000

// An underlying nobody has looked at today has no previous-session OI cached
// for its legs; the backend fetches those in the background and says so rather
// than holding the request. The change columns fill in over a few of these.
const PENDING_REFRESH_MS = 10 * 1000

// Strikes either side of ATM kept in view regardless of how narrow the day's
// price range is, so the OI columns always carry some context.
const MIN_STRIKES_IN_VIEW = 5

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function candleEpochSeconds(candle: CandleData): number | null {
  const raw = candle.timestamp ?? candle.time
  if (raw === undefined || raw === null) return null
  if (typeof raw === 'number') {
    return raw > 1e12 ? Math.floor(raw / 1000) : raw
  }
  const d = new Date(String(raw))
  return Number.isNaN(d.getTime()) ? null : Math.floor(d.getTime() / 1000)
}

function formatCandleTime(candle: CandleData): string {
  const raw = candle.timestamp ?? candle.time
  if (!raw) return ''
  if (typeof raw === 'number') {
    const ms = raw > 1e12 ? raw : raw * 1000
    const d = new Date(ms)
    const dd = String(d.getDate()).padStart(2, '0')
    const mon = d.toLocaleString('en', { month: 'short' })
    const hh = String(d.getHours()).padStart(2, '0')
    const mm = String(d.getMinutes()).padStart(2, '0')
    return `${dd}-${mon} ${hh}:${mm}`
  }
  const s = String(raw)
  try {
    const d = new Date(s)
    if (!Number.isNaN(d.getTime())) {
      const dd = String(d.getDate()).padStart(2, '0')
      const mon = d.toLocaleString('en', { month: 'short' })
      const hh = String(d.getHours()).padStart(2, '0')
      const mm = String(d.getMinutes()).padStart(2, '0')
      return `${dd}-${mon} ${hh}:${mm}`
    }
  } catch {
    /* use raw */
  }
  return s
}

export default function OIProfile() {
  const { mode, appMode } = useThemeStore()
  const { toolsFnoExchanges, defaultToolsFnoExchange, defaultUnderlyings } = useSupportedExchanges()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState(defaultToolsFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultToolsFnoExchange] || []
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultToolsFnoExchange]?.[0] || ''
  )
  const [expiries, setExpiries] = useState<string[]>([])
  // Multiple expiries can be ticked; their OI is summed per strike.
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>([])
  const [expiryOpen, setExpiryOpen] = useState(false)
  const [intervals, setIntervals] = useState<string[]>(['5m'])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [profileData, setProfileData] = useState<OIProfileDataResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const requestIdRef = useRef(0)
  // Arbitrary time window (unix seconds) the user drag-selected on the
  // candlestick panel. When set, OI change is scoped to this window instead
  // of the default "vs previous day's close".
  const [windowRange, setWindowRange] = useState<{ start: number; end: number } | null>(null)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && toolsFnoExchanges.some((ex) => ex.value === prev) ? prev : defaultToolsFnoExchange
    )
  }, [defaultToolsFnoExchange, toolsFnoExchanges])

  // Fetch supported intervals on mount
  // biome-ignore lint/correctness/useExhaustiveDependencies: intervals are fetched once on mount; selectedInterval is only read to validate the initial default, not to re-trigger the fetch
  useEffect(() => {
    const fetchIntervals = async () => {
      try {
        const response = await oiProfileApi.getIntervals()
        if (response.status === 'success' && response.data?.intervals.length) {
          setIntervals(response.data.intervals)
          if (!response.data.intervals.includes(selectedInterval)) {
            setSelectedInterval(response.data.intervals[0])
          }
        }
      } catch {
        // Keep defaults
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
    setSelectedExpiries([])
    setProfileData(null)
    setWindowRange(null)

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
  }, [selectedExchange, defaultUnderlyings[selectedExchange]])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiries([])
    setProfileData(null)
    setWindowRange(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await oiProfileApi.getExpiries(selectedExchange, selectedUnderlying)
        if (cancelled) return
        if (response.status === 'success' && response.expiries.length > 0) {
          setExpiries(response.expiries)
          setSelectedExpiries([response.expiries[0]])
        } else {
          setExpiries([])
          setSelectedExpiries([])
        }
      } catch {
        if (cancelled) return
        setExpiries([])
        setSelectedExpiries([])
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

  // Which selection the plot on screen belongs to. The two-pass load below
  // needs to know whether there is anything painted yet for what is being
  // asked for - a repaint of the same selection must not blank its change
  // columns on the way through.
  const paintedKeyRef = useRef<string | null>(null)

  // Fetch profile data
  const fetchProfileData = useCallback(async () => {
    if (selectedExpiries.length === 0) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiriesForAPI = selectedExpiries.map(convertExpiryForAPI)
      const days = INTERVAL_DAYS[selectedInterval] || 5
      const params = {
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiriesForAPI[0],
        expiry_dates: expiriesForAPI,
        interval: selectedInterval,
        days,
        ...(windowRange ? { window_start: windowRange.start, window_end: windowRange.end } : {}),
      }
      const selectionKey = JSON.stringify(params)

      // Open interest answers in well under a second. The change columns need
      // the open interest every leg carried into the session, which is one
      // broker history call each the first time it is asked for - most of a
      // minute over a full chain. So paint the fast answer straight away and
      // upgrade it when the slow one lands, rather than holding a blank page.
      // Only on a selection that has nothing on screen yet: repainting a
      // selection already showing its change columns would blank them.
      if (paintedKeyRef.current !== selectionKey && !windowRange) {
        const fast = await oiProfileApi.getProfileData({ ...params, include_change: false })
        if (requestIdRef.current !== requestId) return
        if (fast.status === 'success') setProfileData(fast)
      }

      const response = await oiProfileApi.getProfileData(params)
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setProfileData(response)
        paintedKeyRef.current = selectionKey
      } else {
        showToast.error(response.message || 'Failed to fetch OI Profile data')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch OI Profile data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiries, selectedExchange, selectedInterval, windowRange])

  useEffect(() => {
    if (selectedExpiries.length > 0) {
      fetchProfileData()
    }
  }, [selectedExpiries, fetchProfileData])

  // Keep the page live. The exchange republishes open interest every few
  // minutes, so a three-minute beat is as fresh as the number can be; the
  // backend shares one answer across every client asking for the same
  // picture, so the beat costs the broker nothing extra. It skips while the
  // tab is hidden, and stretches rather than stops once the market closes -
  // only a fetch can tell the page the next session has opened.
  //
  // A drag-selected window is a fixed [start, end]; re-asking cannot change it.
  const liveRefreshPaused = Boolean(windowRange) || selectedExpiries.length === 0
  const refreshMs = profileData?.oi_change_pending
    ? PENDING_REFRESH_MS
    : profileData?.market_open === false
      ? CLOSED_REFRESH_MS
      : LIVE_REFRESH_MS

  useEffect(() => {
    if (liveRefreshPaused) return

    const beat = () => {
      if (!document.hidden) fetchProfileData()
    }
    const timer = setInterval(beat, refreshMs)
    // A tab coming back to the front is stale by however long it was away.
    const onVisible = () => {
      if (!document.hidden) fetchProfileData()
    }
    document.addEventListener('visibilitychange', onVisible)
    return () => {
      clearInterval(timer)
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [liveRefreshPaused, refreshMs, fetchProfileData])

  // Drag-select a range on the candlestick panel to scope OI change to that
  // window instead of the default daily delta. Clears when the interval
  // changes, since a window from a different candle set is meaningless.
  // biome-ignore lint/correctness/useExhaustiveDependencies: selectedInterval is the trigger, not a value read inside
  useEffect(() => {
    setWindowRange(null)
  }, [selectedInterval])

  const handlePlotSelected = useCallback(
    (event: PlotlyTypes.PlotSelectionEvent | undefined) => {
      if (!event?.points?.length || !profileData?.candles) return
      // Only the candlestick trace (curveNumber 0) carries a meaningful time axis.
      const candleIndices = event.points.filter((p) => p.curveNumber === 0).map((p) => p.pointIndex)
      if (candleIndices.length === 0) return
      const minIdx = Math.min(...candleIndices)
      const maxIdx = Math.max(...candleIndices)
      const start = candleEpochSeconds(profileData.candles[minIdx])
      const end = candleEpochSeconds(profileData.candles[maxIdx])
      if (start === null || end === null || start >= end) return
      setWindowRange({ start, end })
    },
    [profileData]
  )

  const clearWindow = useCallback(() => setWindowRange(null), [])

  // Tick an expiry on or off. The last one cannot be unticked - an empty
  // selection has nothing to plot.
  const toggleExpiry = useCallback(
    (expiry: string) => {
      setSelectedExpiries((prev) => {
        if (prev.includes(expiry)) {
          return prev.length === 1 ? prev : prev.filter((e) => e !== expiry)
        }
        if (prev.length >= MAX_EXPIRIES) {
          showToast.error(`You can combine up to ${MAX_EXPIRIES} expiries`)
          return prev
        }
        // Keep the chart's expiry order the same as the dropdown's
        return [...prev, expiry].sort((a, b) => expiries.indexOf(a) - expiries.indexOf(b))
      })
    },
    [expiries]
  )

  // Theme colors
  const themeColors = useMemo(
    () => ({
      bg: 'rgba(0,0,0,0)',
      paper: 'rgba(0,0,0,0)',
      text: isDark ? '#e0e0e0' : '#333333',
      grid: isDark
        ? isAnalyzer
          ? 'rgba(180,160,255,0.1)'
          : 'rgba(255,255,255,0.1)'
        : 'rgba(0,0,0,0.08)',
      ceOI: '#22c55e',
      peOI: '#ef4444',
      ceChange: '#86efac',
      peChange: '#fca5a5',
      atmLine: '#eab308',
      hoverBg: isDark ? (isAnalyzer ? '#2d2545' : '#1e293b') : '#ffffff',
      hoverFont: isDark ? '#e0e0e0' : '#333333',
      hoverBorder: isDark ? (isAnalyzer ? '#7c3aed' : '#475569') : '#e2e8f0',
      increasing: '#22c55e',
      decreasing: '#ef4444',
    }),
    [isDark, isAnalyzer]
  )

  // Plotly config
  const plotConfig: Partial<PlotlyTypes.Config> = useMemo(
    () => ({
      displayModeBar: true,
      displaylogo: false,
      modeBarButtonsToRemove: [
        'pan2d',
        'lasso2d',
        'autoScale2d',
        'toggleSpikelines',
      ] as PlotlyTypes.ModeBarDefaultButtons[],
      responsive: true,
    }),
    []
  )

  // Build the 3-column plot
  const profilePlot = useMemo(() => {
    // The OI columns are the point of the page; the futures candles are
    // context. A broker that answers the chain but not the futures history
    // used to blank the whole plot, so only the chain is required here.
    if (!profileData?.oi_chain?.length) return { data: [], layout: {} }

    const candles = profileData.candles ?? []
    const oiChain = profileData.oi_chain
    const atmStrike = profileData.atm_strike

    // Futures candle time labels (category x-axis)
    const candleTimes = candles.map(formatCandleTime)
    const opens = candles.map((c) => c.open)
    const highs = candles.map((c) => c.high)
    const lows = candles.map((c) => c.low)
    const closes = candles.map((c) => c.close)

    // OI data
    const strikes = oiChain.map((item) => item.strike)
    const ceOI = oiChain.map((item) => item.ce_oi)
    const peOI = oiChain.map((item) => -item.pe_oi) // negative for left side
    const ceOIChange = oiChain.map((item) => item.ce_oi_change)
    const peOIChange = oiChain.map((item) => -item.pe_oi_change)

    // Custom data for hover on PE (show absolute values)
    const peOIAbs = oiChain.map((item) => item.pe_oi)
    const peOIChangeAbs = oiChain.map((item) => item.pe_oi_change)

    // Tick labels for candle x-axis (show every Nth)
    const total = candleTimes.length
    const tickStep = Math.max(1, Math.floor(total / 10))
    const candleTickVals = candleTimes.filter((_, i) => i % tickStep === 0)

    const data: PlotlyTypes.Data[] = [
      // Column 1: Futures candlestick
      {
        x: candleTimes,
        open: opens,
        high: highs,
        low: lows,
        close: closes,
        type: 'candlestick' as const,
        name: profileData.futures_symbol || 'Futures',
        xaxis: 'x',
        yaxis: 'y',
        increasing: { line: { color: themeColors.increasing } },
        decreasing: { line: { color: themeColors.decreasing } },
        showlegend: false,
      },
      // Column 2: CE OI (right side - positive)
      {
        y: strikes,
        x: ceOI,
        type: 'bar' as const,
        orientation: 'h' as const,
        name: 'CE OI',
        marker: { color: themeColors.ceOI },
        xaxis: 'x2',
        yaxis: 'y',
        hovertemplate: '<b>%{y} CE</b><br>OI: %{x:,.0f}<extra></extra>',
        showlegend: false,
      },
      // Column 2: PE OI (left side - negative)
      {
        y: strikes,
        x: peOI,
        type: 'bar' as const,
        orientation: 'h' as const,
        name: 'PE OI',
        marker: { color: themeColors.peOI },
        xaxis: 'x2',
        yaxis: 'y',
        customdata: peOIAbs,
        hovertemplate: '<b>%{y} PE</b><br>OI: %{customdata:,.0f}<extra></extra>',
        showlegend: false,
      },
      // Column 3: CE OI Change (right side)
      {
        y: strikes,
        x: ceOIChange,
        type: 'bar' as const,
        orientation: 'h' as const,
        name: 'CE Change',
        marker: { color: themeColors.ceChange },
        xaxis: 'x3',
        yaxis: 'y',
        hovertemplate: '<b>%{y} CE</b><br>Change: %{x:,.0f}<extra></extra>',
        showlegend: false,
      },
      // Column 3: PE OI Change (left side - negative)
      {
        y: strikes,
        x: peOIChange,
        type: 'bar' as const,
        orientation: 'h' as const,
        name: 'PE Change',
        marker: { color: themeColors.peChange },
        xaxis: 'x3',
        yaxis: 'y',
        customdata: peOIChangeAbs,
        hovertemplate: '<b>%{y} PE</b><br>Change: %{customdata:,.0f}<extra></extra>',
        showlegend: false,
      },
    ]

    const expiryLabel = selectedExpiries.map(convertExpiryForAPI).join(' + ')

    // ATM horizontal line
    const shapes: Partial<PlotlyTypes.Shape>[] = atmStrike
      ? [
          {
            type: 'line' as const,
            x0: 0,
            x1: 1,
            xref: 'paper' as const,
            y0: atmStrike,
            y1: atmStrike,
            line: { color: themeColors.atmLine, width: 2, dash: 'dash' as const },
          },
        ]
      : []

    const annotations: Partial<PlotlyTypes.Annotations>[] = atmStrike
      ? [
          {
            x: 0,
            xref: 'paper' as const,
            y: atmStrike,
            text: `ATM ${atmStrike}`,
            showarrow: false,
            font: { color: themeColors.atmLine, size: 11 },
            xanchor: 'left' as const,
            yanchor: 'bottom' as const,
          },
        ]
      : []

    // Price action first, padded; then widened so at least a few strikes
    // either side of ATM are always on screen even on a very quiet day.
    const yRange = ((): [number, number] | undefined => {
      if (!candles.length) return undefined
      const hi = Math.max(...highs)
      const lo = Math.min(...lows)
      // A malformed candle would make these NaN, and a NaN range renders an
      // empty plot. Falling back to autoscale shows a squeezed chart, which
      // is still a chart.
      if (!Number.isFinite(hi) || !Number.isFinite(lo)) return undefined
      const pad = Math.max((hi - lo) * 0.15, 1)
      let top = hi + pad
      let bottom = lo - pad
      if (atmStrike) {
        const step = strikes.length > 1 ? Math.abs(strikes[1] - strikes[0]) : 0
        const band = step * MIN_STRIKES_IN_VIEW
        top = Math.max(top, atmStrike + band)
        bottom = Math.min(bottom, atmStrike - band)
      }
      return [bottom, top]
    })()

    const layout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: `${selectedUnderlying} ${expiryLabel} - Futures with OI Profile`,
        font: { color: themeColors.text, size: 14 },
      },
      paper_bgcolor: themeColors.paper,
      plot_bgcolor: themeColors.bg,
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      barmode: 'overlay' as const,
      bargap: 0.1,
      showlegend: false,
      dragmode: 'select' as const,
      margin: { l: 60, r: 30, t: 50, b: 60 },
      hoverlabel: {
        bgcolor: themeColors.hoverBg,
        font: { color: themeColors.hoverFont, size: 12 },
        bordercolor: themeColors.hoverBorder,
      },
      // Column 1: Futures candles
      xaxis: {
        domain: [0, 0.48],
        type: 'category' as const,
        tickmode: 'array' as const,
        tickvals: candleTickVals,
        tickfont: { color: themeColors.text, size: 9 },
        gridcolor: themeColors.grid,
        title: { text: 'Time', font: { color: themeColors.text, size: 11 } },
        rangeslider: { visible: false },
      },
      // Column 2: Current OI
      xaxis2: {
        domain: [0.5, 0.74],
        anchor: 'y' as const,
        tickfont: { color: themeColors.text, size: 9 },
        gridcolor: themeColors.grid,
        title: {
          text: 'CE <-> PE OI',
          font: { color: themeColors.text, size: 11 },
        },
        zeroline: true,
        zerolinecolor: themeColors.grid,
      },
      // Column 3: OI Change
      xaxis3: {
        domain: [0.76, 1],
        anchor: 'y' as const,
        tickfont: { color: themeColors.text, size: 9 },
        gridcolor: themeColors.grid,
        title: {
          // Named for what it measures: the build since this session opened,
          // or the build across the window the user dragged out.
          text: windowRange ? 'CE <-> PE Change (Window)' : 'CE <-> PE Change (Today)',
          font: { color: themeColors.text, size: 11 },
        },
        zeroline: true,
        zerolinecolor: themeColors.grid,
      },
      // Shared Y-axis (price/strike)
      yaxis: {
        // Framed on the price action, not on the whole strike ladder. The two
        // panels share this axis, and the ladder is far taller than the day's
        // range - 2000 points of strikes against 494 points of candles, which
        // squeezed the candlestick panel into a quarter of its height and got
        // worse the more strikes were asked for. Widened to keep a band of
        // strikes either side of ATM in view; zooming out still reveals the
        // rest, which is all still in the data.
        range: yRange,
        title: {
          text: 'Price / Strike',
          font: { color: themeColors.text, size: 11 },
        },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
        showgrid: true,
      },
      shapes,
      annotations,
    }

    return { data, layout }
  }, [profileData, themeColors, selectedExpiries, selectedUnderlying, windowRange])

  return (
    <div className="py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h1 className="text-2xl font-bold">OI Profile</h1>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Exchange */}
          <Select value={selectedExchange} onValueChange={setSelectedExchange}>
            <SelectTrigger className="w-[100px]">
              <SelectValue placeholder="Exchange" />
            </SelectTrigger>
            <SelectContent>
              {toolsFnoExchanges.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Underlying */}
          <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={underlyingOpen}
                className="w-[160px] justify-between"
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

          {/* Expiry - tick up to MAX_EXPIRIES to sum their OI per strike */}
          <Popover open={expiryOpen} onOpenChange={setExpiryOpen}>
            <PopoverTrigger asChild>
              <Button
                variant="outline"
                role="combobox"
                aria-expanded={expiryOpen}
                disabled={expiries.length === 0}
                className="w-[200px] justify-between"
              >
                <span className="truncate">
                  {selectedExpiries.length === 0
                    ? 'Expiry'
                    : selectedExpiries.length === 1
                      ? selectedExpiries[0]
                      : `${selectedExpiries.length} expiries`}
                </span>
                <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-0" align="start">
              <Command>
                <CommandInput placeholder="Search expiry..." />
                <CommandList>
                  <CommandEmpty>No expiry found</CommandEmpty>
                  <CommandGroup>
                    {expiries.map((e) => (
                      <CommandItem key={e} value={e} onSelect={() => toggleExpiry(e)}>
                        <Check
                          className={`mr-2 h-4 w-4 ${selectedExpiries.includes(e) ? 'opacity-100' : 'opacity-0'}`}
                        />
                        {e}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>

          {/* Interval */}
          <Select value={selectedInterval} onValueChange={setSelectedInterval}>
            <SelectTrigger className="w-[100px]">
              <SelectValue placeholder="Interval" />
            </SelectTrigger>
            <SelectContent>
              {intervals.map((i) => (
                <SelectItem key={i} value={i}>
                  {i}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Refresh */}
          <Button variant="outline" size="sm" onClick={fetchProfileData} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>

          {/* Clear the drag-selected OI change window, if any */}
          {windowRange && (
            <Button variant="outline" size="sm" onClick={clearWindow}>
              Clear window
            </Button>
          )}
        </div>
      </div>

      {/* Info badges */}
      {profileData && profileData.status === 'success' && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {profileData.spot_price?.toFixed(1)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {profileData.atm_strike}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Lot Size: {profileData.lot_size}
          </Badge>
          {profileData.futures_symbol && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Futures: {profileData.futures_symbol}
            </Badge>
          )}
          <Badge variant="secondary" className="text-sm px-3 py-1">
            {selectedExpiries.length > 1
              ? `Expiries: ${selectedExpiries.join(' + ')}`
              : `Expiry: ${selectedExpiries[0] || '-'}`}
          </Badge>{' '}
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Interval: {profileData.interval}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Candles: {profileData.candles?.length || 0}
          </Badge>
          {windowRange ? (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Window: {new Date(windowRange.start * 1000).toLocaleTimeString()} –{' '}
              {new Date(windowRange.end * 1000).toLocaleTimeString()}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-sm px-3 py-1 text-muted-foreground">
              Drag on the candles to scope OI change to a window
            </Badge>
          )}
        </div>
      )}

      {/* Chart */}
      <Card>
        <CardContent className="p-2 sm:p-4">
          {isLoading && !profileData ? (
            <div className="flex items-center justify-center h-[700px] text-muted-foreground">
              Loading OI Profile data...
            </div>
          ) : profilePlot.data.length > 0 ? (
            <Plot
              data={profilePlot.data}
              layout={profilePlot.layout}
              config={plotConfig}
              useResizeHandler
              style={{ width: '100%', height: '700px' }}
              onSelected={handlePlotSelected}
              onDeselect={clearWindow}
            />
          ) : (
            <div className="flex items-center justify-center h-[700px] text-muted-foreground">
              {selectedExpiries.length > 0
                ? 'No data available'
                : 'Select an underlying and expiry to view OI Profile'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
