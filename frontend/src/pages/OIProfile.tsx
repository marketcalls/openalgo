import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useThemeStore } from '@/stores/themeStore'
import {
  oiProfileApi,
  type OIProfileDataResponse,
  type CandleData,
} from '@/api/oi-profile'
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
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { showToast } from '@/utils/toast'
import Plot from 'react-plotly.js'

const FNO_EXCHANGES = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
}

const INTERVAL_DAYS: Record<string, number> = {
  '1m': 1,
  '5m': 5,
  '15m': 7,
}

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
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
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [intervals, setIntervals] = useState<string[]>(['5m'])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [profileData, setProfileData] = useState<OIProfileDataResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const requestIdRef = useRef(0)

  // Fetch supported intervals on mount
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setProfileData(null)

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
  }, [selectedExchange])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiry('')
    setProfileData(null)

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
      } catch {
        if (cancelled) return
        setExpiries([])
        setSelectedExpiry('')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUnderlying])

  // Fetch profile data
  const fetchProfileData = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiryForAPI = convertExpiryForAPI(selectedExpiry)
      const days = INTERVAL_DAYS[selectedInterval] || 5
      const response = await oiProfileApi.getProfileData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiryForAPI,
        interval: selectedInterval,
        days,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setProfileData(response)
      } else {
        showToast.error(response.message || 'Failed to fetch OI Profile data')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch OI Profile data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange, selectedInterval])

  useEffect(() => {
    if (selectedExpiry) {
      fetchProfileData()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry, selectedInterval])

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
      hoverBg: isDark
        ? isAnalyzer
          ? '#2d2545'
          : '#1e293b'
        : '#ffffff',
      hoverFont: isDark ? '#e0e0e0' : '#333333',
      hoverBorder: isDark
        ? isAnalyzer
          ? '#7c3aed'
          : '#475569'
        : '#e2e8f0',
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
        'select2d',
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
    if (!profileData?.oi_chain || !profileData.candles?.length)
      return { data: [], layout: {} }

    const candles = profileData.candles
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

    const expiryLabel = convertExpiryForAPI(selectedExpiry)

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
          text: 'CE <-> PE Change (D)',
          font: { color: themeColors.text, size: 11 },
        },
        zeroline: true,
        zerolinecolor: themeColors.grid,
      },
      // Shared Y-axis (price/strike)
      yaxis: {
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
  }, [profileData, themeColors, selectedExpiry, selectedUnderlying])

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
              {FNO_EXCHANGES.map((ex) => (
                <SelectItem key={ex.value} value={ex.value}>
                  {ex.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {/* Underlying */}
          <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
            <PopoverTrigger asChild>
              <Button variant="outline" role="combobox" aria-expanded={underlyingOpen} className="w-[160px] justify-between">
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
                        <Check className={`mr-2 h-4 w-4 ${selectedUnderlying === u ? 'opacity-100' : 'opacity-0'}`} />
                        {u}
                      </CommandItem>
                    ))}
                  </CommandGroup>
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>

          {/* Expiry */}
          <Select
            value={selectedExpiry}
            onValueChange={setSelectedExpiry}
            disabled={expiries.length === 0}
          >
            <SelectTrigger className="w-[160px]">
              <SelectValue placeholder="Expiry" />
            </SelectTrigger>
            <SelectContent>
              {expiries.map((e) => (
                <SelectItem key={e} value={e}>
                  {e}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

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
            Interval: {profileData.interval}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Candles: {profileData.candles?.length || 0}
          </Badge>
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
            />
          ) : (
            <div className="flex items-center justify-center h-[700px] text-muted-foreground">
              {selectedExpiry
                ? 'No data available'
                : 'Select an underlying and expiry to view OI Profile'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
