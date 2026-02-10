import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useThemeStore } from '@/stores/themeStore'
import { oiTrackerApi, type OIDataResponse } from '@/api/oi-tracker'
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
  return num.toString()
}

export default function OITracker() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [oiData, setOiData] = useState<OIDataResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const requestIdRef = useRef(0)

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setOiData(null)

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await oiTrackerApi.getUnderlyings(selectedExchange)
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
    return () => { cancelled = true }
  }, [selectedExchange])

  // Fetch expiries when underlying changes
  useEffect(() => {
    if (!selectedUnderlying) return
    setExpiries([])
    setSelectedExpiry('')
    setOiData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await oiTrackerApi.getExpiries(selectedExchange, selectedUnderlying)
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
    return () => { cancelled = true }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUnderlying])

  // Fetch OI data - uses requestIdRef to discard stale responses
  const fetchOIData = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiryForAPI = convertExpiryForAPI(selectedExpiry)
      const response = await oiTrackerApi.getOIData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiryForAPI,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setOiData(response)
      } else {
        showToast.error(response.message || 'Failed to fetch OI data')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch OI data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange])

  useEffect(() => {
    if (selectedExpiry) {
      fetchOIData()
    }
    // Only trigger on expiry change - not on fetchOIData identity change,
    // which would cause a stale request with mixed params during exchange switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry])

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

  // Build Plotly data
  const plotData = useMemo(() => {
    if (!oiData?.chain) return { data: [], layout: {} }

    const lotSize = oiData.lot_size || 1
    const atmStrike = oiData.atm_strike
    const chain = oiData.chain

    // Use integer indices for x-axis to force even spacing
    const xIndices = chain.map((_, i) => i)
    const tickLabels = chain.map((item) => item.strike.toString())
    const ceOILots = chain.map((item) => Math.round(item.ce_oi / lotSize))
    const peOILots = chain.map((item) => Math.round(item.pe_oi / lotSize))

    // Show every Nth tick to avoid label overlap
    const tickStep = Math.max(1, Math.floor(chain.length / 15))
    const tickVals = xIndices.filter((_, i) => i % tickStep === 0)
    const tickText = tickLabels.filter((_, i) => i % tickStep === 0)

    const data: PlotlyTypes.Data[] = [
      {
        x: xIndices,
        y: ceOILots,
        type: 'bar' as const,
        name: 'Call Options OI (lots)',
        marker: { color: themeColors.ceBar },
        hovertemplate: 'Strike %{text}<br>CE OI: %{y:,}<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
      },
      {
        x: xIndices,
        y: peOILots,
        type: 'bar' as const,
        name: 'Put Options OI (lots)',
        marker: { color: themeColors.peBar },
        hovertemplate: 'Strike %{text}<br>PE OI: %{y:,}<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
      },
    ]

    const expiryLabel = convertExpiryForAPI(selectedExpiry)

    // Find ATM index in the chain for annotation/shape positioning
    const atmIndex = atmStrike ? chain.findIndex((item) => item.strike === atmStrike) : -1

    const annotations: Partial<PlotlyTypes.Annotations>[] =
      atmIndex >= 0
        ? [
            {
              x: atmIndex,
              y: 1,
              yref: 'paper' as const,
              text: `${selectedUnderlying} ATM Strike ${atmStrike}`,
              showarrow: false,
              font: { color: themeColors.text, size: 12 },
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

    const layout: Partial<PlotlyTypes.Layout> = {
      title: {
        text: `${selectedUnderlying} ${expiryLabel} - current`,
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
        y: -0.15,
        font: { color: themeColors.text, size: 11 },
      },
      margin: { l: 70, r: 30, t: 50, b: 80 },
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
        title: { text: 'Open Interest', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
      },
      annotations,
      shapes,
    }

    return { data, layout }
  }, [oiData, themeColors, selectedExpiry, selectedUnderlying])

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

  return (
    <div className="py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <h1 className="text-2xl font-bold">OI Tracker</h1>
        <div className="flex items-center gap-3">
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

          {/* Refresh */}
          <Button variant="outline" size="sm" onClick={fetchOIData} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Info badges */}
      {oiData && oiData.status === 'success' && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {oiData.spot_price?.toFixed(1)}
          </Badge>
          {oiData.futures_price && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Futures: {oiData.futures_price.toFixed(1)}
            </Badge>
          )}
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Lot Size: {oiData.lot_size}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            PCR (OI): {oiData.pcr_oi?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            PCR (Vol): {oiData.pcr_volume?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {oiData.atm_strike}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Total CE OI: {formatNumber(oiData.total_ce_oi || 0)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Total PE OI: {formatNumber(oiData.total_pe_oi || 0)}
          </Badge>
        </div>
      )}

      {/* Chart */}
      <Card>
        <CardContent className="p-2 sm:p-4">
          {isLoading && !oiData ? (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              Loading OI data...
            </div>
          ) : oiData?.chain && oiData.chain.length > 0 ? (
            <Plot
              data={plotData.data}
              layout={plotData.layout}
              config={plotConfig}
              useResizeHandler
              style={{ width: '100%', height: '500px' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              {selectedExpiry ? 'No OI data available' : 'Select an underlying and expiry to view OI data'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
