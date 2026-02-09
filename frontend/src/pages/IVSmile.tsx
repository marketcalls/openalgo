import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useThemeStore } from '@/stores/themeStore'
import { ivSmileApi, type IVSmileDataResponse } from '@/api/iv-smile'
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

export default function IVSmile() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [ivData, setIvData] = useState<IVSmileDataResponse | null>(null)
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
    setIvData(null)

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await ivSmileApi.getUnderlyings(selectedExchange)
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
    setIvData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await ivSmileApi.getExpiries(selectedExchange, selectedUnderlying)
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

  // Fetch IV Smile data
  const fetchIVSmileData = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiryForAPI = convertExpiryForAPI(selectedExpiry)
      const response = await ivSmileApi.getIVSmileData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiryForAPI,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setIvData(response)
      } else {
        showToast.error(response.message || 'Failed to fetch IV Smile data')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch IV Smile data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange])

  useEffect(() => {
    if (selectedExpiry) {
      fetchIVSmileData()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry])

  // Auto-refresh
  useEffect(() => {
    if (autoRefresh && selectedExpiry) {
      intervalRef.current = setInterval(fetchIVSmileData, AUTO_REFRESH_INTERVAL)
    }
    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current)
        intervalRef.current = null
      }
    }
  }, [autoRefresh, fetchIVSmileData, selectedExpiry])

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
      callIV: '#3b82f6',
      putIV: '#ef4444',
      spotLine: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)',
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

  // Build IV Smile chart
  const ivSmilePlot = useMemo(() => {
    if (!ivData?.chain) return { data: [], layout: {} }

    const chain = ivData.chain
    const spotPrice = ivData.spot_price
    const atmStrike = ivData.atm_strike

    // Filter strikes with at least one valid IV
    const validChain = chain.filter((item) => item.ce_iv !== null || item.pe_iv !== null)

    if (validChain.length === 0) return { data: [], layout: {} }

    // Use actual strike values for x-axis (line chart)
    const strikes = validChain.map((item) => item.strike)
    const ceIVs = validChain.map((item) => item.ce_iv)
    const peIVs = validChain.map((item) => item.pe_iv)

    const data: PlotlyTypes.Data[] = [
      {
        x: strikes,
        y: ceIVs,
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        name: 'Call IV',
        line: { color: themeColors.callIV, width: 2.5 },
        marker: { size: 4, color: themeColors.callIV },
        hovertemplate: 'Strike: %{x}<br>Call IV: %{y:.2f}%<extra></extra>',
        connectgaps: true,
      },
      {
        x: strikes,
        y: peIVs,
        type: 'scatter' as const,
        mode: 'lines+markers' as const,
        name: 'Put IV',
        line: { color: themeColors.putIV, width: 2.5 },
        marker: { size: 4, color: themeColors.putIV },
        hovertemplate: 'Strike: %{x}<br>Put IV: %{y:.2f}%<extra></extra>',
        connectgaps: true,
      },
    ]

    const shapes: Partial<PlotlyTypes.Shape>[] = []
    const annotations: Partial<PlotlyTypes.Annotations>[] = []

    // Spot price vertical line
    if (spotPrice) {
      shapes.push({
        type: 'line' as const,
        x0: spotPrice,
        x1: spotPrice,
        y0: 0,
        y1: 1,
        yref: 'paper' as const,
        line: { color: themeColors.spotLine, width: 1.5, dash: 'dash' as const },
      })
      annotations.push({
        x: spotPrice,
        y: 1,
        yref: 'paper' as const,
        text: `Spot ${spotPrice?.toFixed(1)}`,
        showarrow: false,
        font: { color: themeColors.text, size: 11 },
        yanchor: 'bottom' as const,
      })
    }

    // ATM marker
    if (atmStrike && atmStrike !== spotPrice) {
      shapes.push({
        type: 'line' as const,
        x0: atmStrike,
        x1: atmStrike,
        y0: 0,
        y1: 1,
        yref: 'paper' as const,
        line: { color: themeColors.spotLine, width: 1, dash: 'dot' as const },
      })
    }

    const expiryLabel = convertExpiryForAPI(selectedExpiry)

    const layout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: `${selectedUnderlying} ${expiryLabel} - IV Smile`,
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
      showlegend: true,
      legend: {
        orientation: 'h' as const,
        x: 0.5,
        xanchor: 'center' as const,
        y: -0.15,
        font: { color: themeColors.text, size: 11 },
      },
      margin: { l: 60, r: 30, t: 50, b: 80 },
      xaxis: {
        title: { text: 'Strike Price', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
        tickangle: -45,
      },
      yaxis: {
        title: { text: 'Implied Volatility (%)', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
        ticksuffix: '%',
      },
      annotations,
      shapes,
    }

    return { data, layout }
  }, [ivData, themeColors, selectedExpiry, selectedUnderlying])

  // IV data table - strikes near ATM
  const ivTable = useMemo(() => {
    if (!ivData?.chain || !ivData.atm_strike) return []

    const atm = ivData.atm_strike
    return ivData.chain
      .filter((item) => {
        const distance = Math.abs(item.strike - atm) / atm
        return distance <= 0.05 && (item.ce_iv !== null || item.pe_iv !== null)
      })
      .map((item) => ({
        strike: item.strike,
        ce_iv: item.ce_iv,
        pe_iv: item.pe_iv,
        diff: item.ce_iv !== null && item.pe_iv !== null ? item.pe_iv - item.ce_iv : null,
        isATM: item.strike === atm,
      }))
  }, [ivData])

  return (
    <div className="py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h1 className="text-2xl font-bold">IV Smile</h1>
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
          <Button variant="outline" size="sm" onClick={fetchIVSmileData} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Info badges */}
      {ivData && ivData.status === 'success' && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {ivData.spot_price?.toFixed(1)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {ivData.atm_strike}
          </Badge>
          {ivData.atm_iv !== null && ivData.atm_iv !== undefined && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              ATM IV: {ivData.atm_iv}%
            </Badge>
          )}
          {ivData.skew !== null && ivData.skew !== undefined && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Skew (25d): {ivData.skew > 0 ? '+' : ''}
              {ivData.skew}%
            </Badge>
          )}
        </div>
      )}

      {/* Chart */}
      <Card>
        <CardContent className="p-2 sm:p-4">
          {isLoading && !ivData ? (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              Loading IV Smile data...
            </div>
          ) : ivSmilePlot.data.length > 0 ? (
            <Plot
              data={ivSmilePlot.data}
              layout={ivSmilePlot.layout}
              config={plotConfig}
              useResizeHandler
              style={{ width: '100%', height: '500px' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              {selectedExpiry
                ? 'No IV data available'
                : 'Select an underlying and expiry to view IV Smile'}
            </div>
          )}
        </CardContent>
      </Card>

      {/* IV Table near ATM */}
      {ivTable.length > 0 && (
        <Card>
          <CardContent className="p-4">
            <h3 className="font-semibold mb-3 text-sm">IV Near ATM</h3>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    <th className="text-left py-2 px-3 font-medium text-muted-foreground">
                      Strike
                    </th>
                    <th className="text-right py-2 px-3 font-medium text-blue-500">Call IV</th>
                    <th className="text-right py-2 px-3 font-medium text-red-500">Put IV</th>
                    <th className="text-right py-2 px-3 font-medium text-muted-foreground">
                      Diff (PE-CE)
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ivTable.map((row) => (
                    <tr
                      key={row.strike}
                      className={`border-b border-border/50 last:border-0 ${
                        row.isATM ? 'bg-muted/50 font-medium' : ''
                      }`}
                    >
                      <td className="py-2 px-3">
                        {row.strike}
                        {row.isATM && (
                          <span className="ml-1 text-xs text-muted-foreground">(ATM)</span>
                        )}
                      </td>
                      <td className="text-right py-2 px-3 text-blue-500">
                        {row.ce_iv !== null ? `${row.ce_iv}%` : '-'}
                      </td>
                      <td className="text-right py-2 px-3 text-red-500">
                        {row.pe_iv !== null ? `${row.pe_iv}%` : '-'}
                      </td>
                      <td
                        className={`text-right py-2 px-3 ${
                          row.diff !== null && row.diff > 0
                            ? 'text-red-500'
                            : row.diff !== null && row.diff < 0
                              ? 'text-blue-500'
                              : 'text-muted-foreground'
                        }`}
                      >
                        {row.diff !== null
                          ? `${row.diff > 0 ? '+' : ''}${row.diff.toFixed(2)}%`
                          : '-'}
                      </td>
                    </tr>
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
