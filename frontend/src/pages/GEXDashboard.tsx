import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useThemeStore } from '@/stores/themeStore'
import { gexApi, type GEXDataResponse } from '@/api/gex'
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

const AUTO_REFRESH_INTERVAL = 30000

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function formatNumber(num: number): string {
  if (num >= 10000000) return `${(num / 10000000).toFixed(1)}Cr`
  if (num >= 100000) return `${(num / 100000).toFixed(1)}L`
  if (num >= 1000) return `${(num / 1000).toFixed(1)}K`
  return num.toFixed(0)
}

export default function GEXDashboard() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [gexData, setGexData] = useState<GEXDataResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const requestIdRef = useRef(0)
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setGexData(null)

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await gexApi.getUnderlyings(selectedExchange)
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
    setGexData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await gexApi.getExpiries(selectedExchange, selectedUnderlying)
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

  // Fetch GEX data
  const fetchGEXData = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiryForAPI = convertExpiryForAPI(selectedExpiry)
      const response = await gexApi.getGEXData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiryForAPI,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setGexData(response)
      } else {
        showToast.error(response.message || 'Failed to fetch GEX data')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch GEX data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange])

  useEffect(() => {
    if (selectedExpiry) {
      fetchGEXData()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry])

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh && selectedExpiry) {
      intervalRef.current = setInterval(fetchGEXData, AUTO_REFRESH_INTERVAL)
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [autoRefresh, fetchGEXData, selectedExpiry])

  // Theme colors for Plotly
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
      ceBar: '#ef4444',
      peBar: '#22c55e',
      positiveGex: '#3b82f6',
      negativeGex: '#f97316',
      atmLine: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)',
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

  // Build OI Walls chart
  const oiWallsPlot = useMemo(() => {
    if (!gexData?.chain) return { data: [], layout: {} }

    const lotSize = gexData.lot_size || 1
    const atmStrike = gexData.atm_strike
    const chain = gexData.chain

    const xIndices = chain.map((_, i) => i)
    const tickLabels = chain.map((item) => item.strike.toString())
    const ceOILots = chain.map((item) => Math.round(item.ce_oi / lotSize))
    const peOILots = chain.map((item) => Math.round(item.pe_oi / lotSize))

    const tickStep = Math.max(1, Math.floor(chain.length / 15))
    const tickVals = xIndices.filter((_, i) => i % tickStep === 0)
    const tickText = tickLabels.filter((_, i) => i % tickStep === 0)

    const data: PlotlyTypes.Data[] = [
      {
        x: xIndices,
        y: ceOILots,
        type: 'bar' as const,
        name: 'Call OI (lots)',
        marker: { color: themeColors.ceBar },
        hovertemplate: 'Strike %{text}<br>CE OI: %{y:,}<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
      },
      {
        x: xIndices,
        y: peOILots,
        type: 'bar' as const,
        name: 'Put OI (lots)',
        marker: { color: themeColors.peBar },
        hovertemplate: 'Strike %{text}<br>PE OI: %{y:,}<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
      },
    ]

    const atmIndex = atmStrike ? chain.findIndex((item) => item.strike === atmStrike) : -1

    const annotations: Partial<PlotlyTypes.Annotations>[] =
      atmIndex >= 0
        ? [
            {
              x: atmIndex,
              y: 1,
              yref: 'paper' as const,
              text: `ATM ${atmStrike}`,
              showarrow: false,
              font: { color: themeColors.text, size: 11 },
              yanchor: 'bottom' as const,
            },
          ]
        : []

    const shapes: Partial<PlotlyTypes.Shape>[] =
      atmIndex >= 0
        ? [
            {
              type: 'line' as const,
              x0: atmIndex,
              x1: atmIndex,
              y0: 0,
              y1: 1,
              yref: 'paper' as const,
              line: { color: themeColors.atmLine, width: 1.5, dash: 'dash' as const },
            },
          ]
        : []

    const expiryLabel = convertExpiryForAPI(selectedExpiry)

    const layout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: `${selectedUnderlying} ${expiryLabel} - OI Walls`,
        font: { color: themeColors.text, size: 14 },
      },
      paper_bgcolor: themeColors.paper,
      plot_bgcolor: themeColors.bg,
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      barmode: 'group' as const,
      bargap: 0.15,
      hovermode: 'x unified' as const,
      hoverlabel: {
        bgcolor: themeColors.hoverBg,
        font: { color: themeColors.hoverFont, size: 12 },
        bordercolor: themeColors.hoverBorder,
      },
      showlegend: true,
      legend: {
        orientation: 'h' as const,
        x: 0.5,
        xanchor: 'center' as const,
        y: -0.18,
        font: { color: themeColors.text, size: 11 },
      },
      margin: { l: 60, r: 20, t: 50, b: 80 },
      xaxis: {
        tickmode: 'array' as const,
        tickvals: tickVals,
        ticktext: tickText,
        title: { text: 'Strike Price', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
        tickangle: -45,
      },
      yaxis: {
        title: { text: 'Open Interest (lots)', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
      },
      annotations,
      shapes,
    }

    return { data, layout }
  }, [gexData, themeColors, selectedExpiry, selectedUnderlying])

  // Build Net GEX chart
  const netGexPlot = useMemo(() => {
    if (!gexData?.chain) return { data: [], layout: {} }

    const atmStrike = gexData.atm_strike
    const chain = gexData.chain

    const xIndices = chain.map((_, i) => i)
    const tickLabels = chain.map((item) => item.strike.toString())
    const netGexValues = chain.map((item) => item.net_gex)

    // Color bars based on positive/negative
    const barColors = netGexValues.map((v) =>
      v >= 0 ? themeColors.positiveGex : themeColors.negativeGex
    )

    const tickStep = Math.max(1, Math.floor(chain.length / 15))
    const tickVals = xIndices.filter((_, i) => i % tickStep === 0)
    const tickText = tickLabels.filter((_, i) => i % tickStep === 0)

    const data: PlotlyTypes.Data[] = [
      {
        x: xIndices,
        y: netGexValues,
        type: 'bar' as const,
        name: 'Net GEX',
        marker: { color: barColors },
        hovertemplate: 'Strike %{text}<br>Net GEX: %{y:,.2f}<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
        showlegend: false,
      },
    ]

    const atmIndex = atmStrike ? chain.findIndex((item) => item.strike === atmStrike) : -1

    const annotations: Partial<PlotlyTypes.Annotations>[] =
      atmIndex >= 0
        ? [
            {
              x: atmIndex,
              y: 1,
              yref: 'paper' as const,
              text: `ATM ${atmStrike}`,
              showarrow: false,
              font: { color: themeColors.text, size: 11 },
              yanchor: 'bottom' as const,
            },
          ]
        : []

    const shapes: Partial<PlotlyTypes.Shape>[] = [
      // Zero line
      {
        type: 'line' as const,
        x0: 0,
        x1: 1,
        xref: 'paper' as const,
        y0: 0,
        y1: 0,
        line: { color: themeColors.grid, width: 1 },
      },
    ]

    if (atmIndex >= 0) {
      shapes.push({
        type: 'line' as const,
        x0: atmIndex,
        x1: atmIndex,
        y0: 0,
        y1: 1,
        yref: 'paper' as const,
        line: { color: themeColors.atmLine, width: 1.5, dash: 'dash' as const },
      })
    }

    const expiryLabel = convertExpiryForAPI(selectedExpiry)

    const layout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: `${selectedUnderlying} ${expiryLabel} - Net GEX Walls`,
        font: { color: themeColors.text, size: 14 },
      },
      paper_bgcolor: themeColors.paper,
      plot_bgcolor: themeColors.bg,
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      hovermode: 'x unified' as const,
      hoverlabel: {
        bgcolor: themeColors.hoverBg,
        font: { color: themeColors.hoverFont, size: 12 },
        bordercolor: themeColors.hoverBorder,
      },
      showlegend: false,
      margin: { l: 60, r: 20, t: 50, b: 80 },
      xaxis: {
        tickmode: 'array' as const,
        tickvals: tickVals,
        ticktext: tickText,
        title: { text: 'Strike Price', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
        tickangle: -45,
      },
      yaxis: {
        title: { text: 'Net GEX (gamma x OI x lot)', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
      },
      annotations,
      shapes,
    }

    return { data, layout }
  }, [gexData, themeColors, selectedExpiry, selectedUnderlying])

  // Find top GEX strikes
  const topStrikes = useMemo(() => {
    if (!gexData?.chain) return { topCallOI: [], topPutOI: [], topNetGex: [] }

    const chain = [...gexData.chain]
    const lotSize = gexData.lot_size || 1

    const topCallOI = [...chain]
      .sort((a, b) => b.ce_oi - a.ce_oi)
      .slice(0, 5)
      .map((item) => ({ strike: item.strike, value: Math.round(item.ce_oi / lotSize) }))

    const topPutOI = [...chain]
      .sort((a, b) => b.pe_oi - a.pe_oi)
      .slice(0, 5)
      .map((item) => ({ strike: item.strike, value: Math.round(item.pe_oi / lotSize) }))

    const topNetGex = [...chain]
      .sort((a, b) => Math.abs(b.net_gex) - Math.abs(a.net_gex))
      .slice(0, 5)
      .map((item) => ({ strike: item.strike, value: item.net_gex }))

    return { topCallOI, topPutOI, topNetGex }
  }, [gexData])

  return (
    <div className="py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h1 className="text-2xl font-bold">GEX Dashboard</h1>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Exchange selector */}
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

          {/* Underlying selector */}
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

          {/* Expiry selector */}
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

          {/* Auto-refresh toggle */}
          <Button
            variant={autoRefresh ? 'default' : 'outline'}
            size="sm"
            onClick={() => setAutoRefresh(!autoRefresh)}
          >
            {autoRefresh ? 'Auto: ON' : 'Auto: OFF'}
          </Button>

          {/* Refresh */}
          <Button variant="outline" size="sm" onClick={fetchGEXData} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Info badges */}
      {gexData && gexData.status === 'success' && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {gexData.spot_price?.toFixed(1)}
          </Badge>
          {gexData.futures_price && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Futures: {gexData.futures_price.toFixed(1)}
            </Badge>
          )}
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Lot Size: {gexData.lot_size}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            PCR: {gexData.pcr_oi?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {gexData.atm_strike}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Net GEX: {formatNumber(gexData.total_net_gex || 0)}
          </Badge>
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* OI Walls Chart */}
        <Card>
          <CardContent className="p-2 sm:p-4">
            {isLoading && !gexData ? (
              <div className="flex items-center justify-center h-[450px] text-muted-foreground">
                Loading GEX data...
              </div>
            ) : gexData?.chain && gexData.chain.length > 0 ? (
              <Plot
                data={oiWallsPlot.data}
                layout={oiWallsPlot.layout}
                config={plotConfig}
                useResizeHandler
                style={{ width: '100%', height: '450px' }}
              />
            ) : (
              <div className="flex items-center justify-center h-[450px] text-muted-foreground">
                {selectedExpiry
                  ? 'No OI data available'
                  : 'Select an underlying and expiry to view OI Walls'}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Net GEX Chart */}
        <Card>
          <CardContent className="p-2 sm:p-4">
            {isLoading && !gexData ? (
              <div className="flex items-center justify-center h-[450px] text-muted-foreground">
                Loading GEX data...
              </div>
            ) : gexData?.chain && gexData.chain.length > 0 ? (
              <Plot
                data={netGexPlot.data}
                layout={netGexPlot.layout}
                config={plotConfig}
                useResizeHandler
                style={{ width: '100%', height: '450px' }}
              />
            ) : (
              <div className="flex items-center justify-center h-[450px] text-muted-foreground">
                {selectedExpiry
                  ? 'No GEX data available'
                  : 'Select an underlying and expiry to view Net GEX'}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Top Strikes Tables */}
      {gexData?.chain && gexData.chain.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {/* Top Call OI */}
          <Card>
            <CardContent className="p-4">
              <h3 className="font-semibold mb-3 text-sm">Top Call OI (Resistance)</h3>
              <div className="space-y-1">
                {topStrikes.topCallOI.map((item, idx) => (
                  <div
                    key={item.strike}
                    className="flex justify-between text-sm py-1 border-b border-border/50 last:border-0"
                  >
                    <span className="text-muted-foreground">
                      {idx + 1}. {item.strike}
                    </span>
                    <span className="font-medium text-red-500">{formatNumber(item.value)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Top Put OI */}
          <Card>
            <CardContent className="p-4">
              <h3 className="font-semibold mb-3 text-sm">Top Put OI (Support)</h3>
              <div className="space-y-1">
                {topStrikes.topPutOI.map((item, idx) => (
                  <div
                    key={item.strike}
                    className="flex justify-between text-sm py-1 border-b border-border/50 last:border-0"
                  >
                    <span className="text-muted-foreground">
                      {idx + 1}. {item.strike}
                    </span>
                    <span className="font-medium text-green-500">{formatNumber(item.value)}</span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>

          {/* Top Net GEX */}
          <Card>
            <CardContent className="p-4">
              <h3 className="font-semibold mb-3 text-sm">Top Net GEX Strikes</h3>
              <div className="space-y-1">
                {topStrikes.topNetGex.map((item, idx) => (
                  <div
                    key={item.strike}
                    className="flex justify-between text-sm py-1 border-b border-border/50 last:border-0"
                  >
                    <span className="text-muted-foreground">
                      {idx + 1}. {item.strike}
                    </span>
                    <span
                      className={`font-medium ${item.value >= 0 ? 'text-blue-500' : 'text-orange-500'}`}
                    >
                      {item.value >= 0 ? '+' : ''}
                      {formatNumber(item.value)}
                    </span>
                  </div>
                ))}
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* GEX Data Table */}
      {gexData?.chain && gexData.chain.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <h3 className="font-semibold mb-3 text-sm">GEX Table</h3>
            <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-background z-10">
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-3 font-medium text-muted-foreground">Strike</th>
                    <th className="text-right py-2 px-3 font-medium text-muted-foreground">Call GEX</th>
                    <th className="text-right py-2 px-3 font-medium text-muted-foreground">Put GEX</th>
                    <th className="text-right py-2 px-3 font-medium text-muted-foreground">Net GEX</th>
                  </tr>
                </thead>
                <tbody>
                  {gexData.chain.map((item) => {
                    const isATM = item.strike === gexData.atm_strike
                    return (
                      <tr
                        key={item.strike}
                        className={`border-b border-border/30 ${isATM ? 'bg-yellow-500/10 font-semibold' : 'hover:bg-muted/50'}`}
                      >
                        <td className="py-1.5 px-3">
                          {item.strike}
                          {isATM && (
                            <span className="ml-2 text-xs text-yellow-500">ATM</span>
                          )}
                        </td>
                        <td className="py-1.5 px-3 text-right text-red-500">
                          {item.ce_gex.toFixed(2)}
                        </td>
                        <td className="py-1.5 px-3 text-right text-green-500">
                          {item.pe_gex.toFixed(2)}
                        </td>
                        <td
                          className={`py-1.5 px-3 text-right font-medium ${item.net_gex >= 0 ? 'text-blue-500' : 'text-orange-500'}`}
                        >
                          {item.net_gex >= 0 ? '+' : ''}
                          {item.net_gex.toFixed(2)}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
                <tfoot className="sticky bottom-0 bg-background border-t-2 border-border">
                  <tr className="font-semibold">
                    <td className="py-2 px-3">Total</td>
                    <td className="py-2 px-3 text-right text-red-500">
                      {(gexData.total_ce_gex || 0).toFixed(2)}
                    </td>
                    <td className="py-2 px-3 text-right text-green-500">
                      {(gexData.total_pe_gex || 0).toFixed(2)}
                    </td>
                    <td
                      className={`py-2 px-3 text-right ${(gexData.total_net_gex || 0) >= 0 ? 'text-blue-500' : 'text-orange-500'}`}
                    >
                      {(gexData.total_net_gex || 0) >= 0 ? '+' : ''}
                      {(gexData.total_net_gex || 0).toFixed(2)}
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
