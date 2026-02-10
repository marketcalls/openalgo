import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useThemeStore } from '@/stores/themeStore'
import { oiTrackerApi, type MaxPainResponse } from '@/api/oi-tracker'
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

export default function MaxPain() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [maxPainData, setMaxPainData] = useState<MaxPainResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const requestIdRef = useRef(0)

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setMaxPainData(null)

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
    setMaxPainData(null)

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

  // Fetch max pain data - uses requestIdRef to discard stale responses
  const fetchMaxPain = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const expiryForAPI = convertExpiryForAPI(selectedExpiry)
      const response = await oiTrackerApi.getMaxPain({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: expiryForAPI,
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setMaxPainData(response)
      } else {
        showToast.error(response.message || 'Failed to calculate Max Pain')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to calculate Max Pain')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange])

  useEffect(() => {
    if (selectedExpiry) {
      fetchMaxPain()
    }
    // Only trigger on expiry change - not on fetchMaxPain identity change,
    // which would cause a stale request with mixed params during exchange switch.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedExpiry])

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
      barColor: isAnalyzer ? '#8b5cf6' : '#7c3aed',
      maxPainBar: isAnalyzer ? '#c084fc' : '#a78bfa',
      markerLine: isDark ? 'rgba(255,255,255,0.6)' : 'rgba(0,0,0,0.5)',
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

  // Build Plotly chart data
  const plotData = useMemo(() => {
    if (!maxPainData?.pain_data) return { data: [], layout: {} }

    const maxPainStrike = maxPainData.max_pain_strike
    const painData = maxPainData.pain_data

    // Use integer indices for x-axis to force even spacing
    const xIndices = painData.map((_, i) => i)
    const tickLabels = painData.map((item) => item.strike.toString())
    const totalPainCr = painData.map((item) => item.total_pain_cr)

    // Show every Nth tick to avoid label overlap
    const tickStep = Math.max(1, Math.floor(painData.length / 15))
    const tickVals = xIndices.filter((_, i) => i % tickStep === 0)
    const tickText = tickLabels.filter((_, i) => i % tickStep === 0)

    // Color each bar - highlight max pain strike differently
    const barColors = painData.map((item) =>
      item.strike === maxPainStrike ? themeColors.maxPainBar : themeColors.barColor
    )

    const data: PlotlyTypes.Data[] = [
      {
        x: xIndices,
        y: totalPainCr,
        type: 'bar' as const,
        name: 'Max Pain',
        marker: { color: barColors },
        hovertemplate: 'Strike %{text}<br>MaxPain: %{y:.2f} Crs.<extra></extra>',
        text: tickLabels,
        textposition: 'none' as const,
      },
    ]

    // Find max pain index in the chain for annotation/shape positioning
    const maxPainIndex = maxPainStrike
      ? painData.findIndex((item) => item.strike === maxPainStrike)
      : -1

    const annotations: Partial<PlotlyTypes.Annotations>[] =
      maxPainIndex >= 0
        ? [
            {
              x: maxPainIndex,
              y: 1,
              yref: 'paper' as const,
              text: `Max Pain ${maxPainStrike}`,
              showarrow: false,
              font: { color: themeColors.text, size: 12, family: 'system-ui, sans-serif' },
              yanchor: 'bottom' as const,
            },
          ]
        : []

    const shapes: Partial<PlotlyTypes.Shape>[] =
      maxPainIndex >= 0
        ? [
            {
              type: 'line' as const,
              x0: maxPainIndex,
              x1: maxPainIndex,
              y0: 0,
              y1: 1,
              yref: 'paper' as const,
              line: { color: themeColors.markerLine, width: 1.5, dash: 'dash' as const },
            },
          ]
        : []

    const layout: Partial<PlotlyTypes.Layout> = {
      paper_bgcolor: themeColors.paper,
      plot_bgcolor: themeColors.bg,
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      bargap: 0.15,
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
      margin: { l: 60, r: 30, t: 30, b: 80 },
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
        title: { text: 'Max-Pain (Crs.)', font: { color: themeColors.text, size: 12 } },
        tickfont: { color: themeColors.text, size: 10 },
        gridcolor: themeColors.grid,
      },
      annotations,
      shapes,
    }

    return { data, layout }
  }, [maxPainData, themeColors])

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
        <h1 className="text-2xl font-bold">Max Pain</h1>
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
          <Button variant="outline" size="sm" onClick={fetchMaxPain} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Info badges */}
      {maxPainData && maxPainData.status === 'success' && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {maxPainData.spot_price?.toFixed(1)}
          </Badge>
          {maxPainData.futures_price && (
            <Badge variant="secondary" className="text-sm px-3 py-1">
              Futures: {maxPainData.futures_price.toFixed(1)}
            </Badge>
          )}
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Lot Size: {maxPainData.lot_size}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            PCR (OI): {maxPainData.pcr_oi?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            PCR (Vol): {maxPainData.pcr_volume?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1 font-semibold">
            Max Pain: {maxPainData.max_pain_strike}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {maxPainData.atm_strike}
          </Badge>
        </div>
      )}

      {/* Chart */}
      <Card>
        <CardContent className="p-2 sm:p-4">
          {isLoading && !maxPainData ? (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              Calculating Max Pain...
            </div>
          ) : maxPainData?.pain_data && maxPainData.pain_data.length > 0 ? (
            <Plot
              data={plotData.data}
              layout={plotData.layout}
              config={plotConfig}
              useResizeHandler
              style={{ width: '100%', height: '500px' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[500px] text-muted-foreground">
              {selectedExpiry
                ? 'No data available for Max Pain calculation'
                : 'Select an underlying and expiry to view Max Pain'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
