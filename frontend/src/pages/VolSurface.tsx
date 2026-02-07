import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type * as PlotlyTypes from 'plotly.js'
import Plot from 'react-plotly.js'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { optionChainApi } from '@/api/option-chain'
import { volSurfaceApi, type VolSurfaceData } from '@/api/vol-surface'
import { Card, CardContent } from '@/components/ui/card'
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

const UNDERLYINGS = [
  { value: 'NIFTY', label: 'NIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'BANKNIFTY', label: 'BANKNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'SENSEX', label: 'SENSEX', exchange: 'BFO', brokerExchange: 'BSE_INDEX' },
  { value: 'FINNIFTY', label: 'FINNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
  { value: 'MIDCPNIFTY', label: 'MIDCPNIFTY', exchange: 'NFO', brokerExchange: 'NSE_INDEX' },
]

const STRIKE_COUNTS = [
  { value: '10', label: '10' },
  { value: '15', label: '15' },
  { value: '20', label: '20' },
  { value: '25', label: '25' },
  { value: '30', label: '30' },
  { value: '35', label: '35' },
  { value: '40', label: '40' },
]

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

export default function VolSurface() {
  const { mode, appMode } = useThemeStore()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer
  const { apiKey } = useAuthStore()

  const [selectedUnderlying, setSelectedUnderlying] = useState(UNDERLYINGS[0].value)
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiries, setSelectedExpiries] = useState<string[]>([])
  const [strikeCount, setStrikeCount] = useState('40')
  const [surfaceData, setSurfaceData] = useState<VolSurfaceData | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const requestIdRef = useRef(0)

  const underlyingConfig =
    UNDERLYINGS.find((u) => u.value === selectedUnderlying) || UNDERLYINGS[0]

  // Theme colors
  const themeColors = useMemo(
    () => ({
      text: isDark ? '#e0e0e0' : '#333333',
      grid: isDark
        ? isAnalyzer
          ? 'rgba(180,160,255,0.15)'
          : 'rgba(255,255,255,0.1)'
        : 'rgba(0,0,0,0.08)',
      hoverBg: isDark ? (isAnalyzer ? '#2d2545' : '#1e293b') : '#ffffff',
      hoverFont: isDark ? '#e0e0e0' : '#333333',
      hoverBorder: isDark ? (isAnalyzer ? '#7c3aed' : '#475569') : '#e2e8f0',
      colorscale: isAnalyzer ? 'Plasma' : isDark ? 'Viridis' : 'YlOrRd',
    }),
    [isDark, isAnalyzer]
  )

  // Fetch expiries when underlying changes — clear state to prevent race condition
  useEffect(() => {
    if (!apiKey) return
    setExpiries([])
    setSelectedExpiries([])
    setSurfaceData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const res = await optionChainApi.getExpiries(
          apiKey,
          underlyingConfig.value,
          underlyingConfig.exchange,
          'options'
        )
        if (cancelled) return
        if (res.status === 'success' && res.data && res.data.length > 0) {
          setExpiries(res.data)
          // Auto-select first 4 expiries
          setSelectedExpiries(res.data.slice(0, 4))
        }
      } catch {
        if (cancelled) return
        showToast.error('Failed to fetch expiry dates')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [apiKey, underlyingConfig.value, underlyingConfig.exchange])

  // Toggle an expiry selection
  const toggleExpiry = useCallback(
    (expiry: string) => {
      setSelectedExpiries((prev) => {
        if (prev.includes(expiry)) {
          return prev.filter((e) => e !== expiry)
        }
        if (prev.length >= 8) return prev
        return [...prev, expiry]
      })
    },
    []
  )

  // Load surface data
  const loadData = useCallback(async () => {
    if (selectedExpiries.length === 0) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const res = await volSurfaceApi.getSurfaceData({
        underlying: underlyingConfig.value,
        exchange: underlyingConfig.brokerExchange,
        expiry_dates: selectedExpiries.map(convertExpiryForAPI),
        strike_count: parseInt(strikeCount),
      })
      if (requestIdRef.current !== requestId) return
      if (res.status === 'success' && res.data) {
        setSurfaceData(res.data)
      } else {
        showToast.error(res.message || 'Failed to load vol surface')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch vol surface data')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedExpiries, strikeCount, underlyingConfig])

  // Build Plotly data
  const plotData = useMemo(() => {
    if (!surfaceData) return { data: [], layout: {} }

    const { strikes, expiries: expiryInfo, surface } = surfaceData

    // X = strikes, Y = expiry indices (labels via ticktext), Z = IV matrix
    const yIndices = expiryInfo.map((_, i) => i)
    const expiryLabels = expiryInfo.map((e) => e.date)

    // Build customdata for hover: 2D array matching surface shape [expiry_idx][strike_idx]
    const customdata = surface.map((_, i) =>
      Array(strikes.length).fill(expiryLabels[i])
    )

    const data: PlotlyTypes.Data[] = [
      {
        type: 'surface' as const,
        x: strikes,
        y: yIndices,
        z: surface,
        customdata: customdata as unknown as PlotlyTypes.Datum[][],
        colorscale: themeColors.colorscale as PlotlyTypes.ColorScale,
        hovertemplate:
          'Strike: %{x}<br>Expiry: %{customdata}<br>IV: %{z:.2f}%<extra></extra>',
        colorbar: {
          title: { text: 'IV %', font: { color: themeColors.text, size: 12 } },
          tickfont: { color: themeColors.text },
          outlinewidth: 0,
          len: 0.6,
        },
        opacity: 0.95,
      },
    ]

    const layout: Partial<PlotlyTypes.Layout> = {
      autosize: true,
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(0,0,0,0)',
      font: { color: themeColors.text, family: 'system-ui, sans-serif' },
      margin: { l: 0, r: 0, t: 0, b: 0 },
      scene: {
        aspectmode: 'manual' as const,
        aspectratio: { x: 2, y: 1.2, z: 0.8 },
        domain: { x: [0, 1], y: [0, 1] },
        xaxis: {
          title: { text: 'Strike Price', font: { color: themeColors.text, size: 12 } },
          tickfont: { color: themeColors.text, size: 10 },
          gridcolor: themeColors.grid,
          backgroundcolor: 'rgba(0,0,0,0)',
        },
        yaxis: {
          title: { text: 'Expiry', font: { color: themeColors.text, size: 12 } },
          tickfont: { color: themeColors.text, size: 10 },
          tickvals: yIndices,
          ticktext: expiryLabels,
          gridcolor: themeColors.grid,
          backgroundcolor: 'rgba(0,0,0,0)',
        },
        zaxis: {
          title: { text: 'Implied Volatility', font: { color: themeColors.text, size: 12 } },
          tickfont: { color: themeColors.text, size: 10 },
          gridcolor: themeColors.grid,
          backgroundcolor: 'rgba(0,0,0,0)',
        },
        camera: {
          eye: { x: 1.6, y: -1.6, z: 0.7 },
        },
        bgcolor: 'rgba(0,0,0,0)',
      },
      hoverlabel: {
        bgcolor: themeColors.hoverBg,
        font: { color: themeColors.hoverFont, size: 12 },
        bordercolor: themeColors.hoverBorder,
      },
      showlegend: false,
    }

    return { data, layout }
  }, [surfaceData, themeColors, isDark])

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
        <h1 className="text-2xl font-bold">Vol Surface</h1>
        <div className="flex items-center gap-3">
          <Select
            value={selectedUnderlying}
            onValueChange={(v) => {
              setSelectedUnderlying(v)
              setSelectedExpiries([])
              setExpiries([])
              setSurfaceData(null)
            }}
          >
            <SelectTrigger className="w-[140px]">
              <SelectValue placeholder="Underlying" />
            </SelectTrigger>
            <SelectContent>
              {UNDERLYINGS.map((u) => (
                <SelectItem key={u.value} value={u.value}>
                  {u.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Select value={strikeCount} onValueChange={setStrikeCount}>
            <SelectTrigger className="w-[100px]">
              <SelectValue placeholder="Strikes" />
            </SelectTrigger>
            <SelectContent>
              {STRIKE_COUNTS.map((s) => (
                <SelectItem key={s.value} value={s.value}>
                  {s.label} Strikes
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          <Button
            variant="outline"
            size="sm"
            onClick={loadData}
            disabled={isLoading || selectedExpiries.length === 0}
          >
            {isLoading ? 'Loading...' : 'Load Surface'}
          </Button>
        </div>
      </div>

      {/* Expiry selection */}
      {expiries.length > 0 && (
        <div className="flex flex-wrap gap-2">
          <span className="text-sm text-muted-foreground self-center mr-1">Expiries:</span>
          {expiries.map((exp) => (
            <button
              key={exp}
              type="button"
              onClick={() => toggleExpiry(exp)}
              className={`px-2.5 py-1 rounded-md text-xs border transition-colors ${
                selectedExpiries.includes(exp)
                  ? 'bg-primary text-primary-foreground border-primary'
                  : 'bg-muted/50 text-muted-foreground border-border hover:bg-muted'
              }`}
            >
              {exp}
            </button>
          ))}
        </div>
      )}

      {/* Info badges */}
      {surfaceData && (
        <div className="flex flex-wrap gap-2">
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Spot: {surfaceData.underlying_ltp?.toFixed(2)}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            ATM: {surfaceData.atm_strike}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Expiries: {surfaceData.expiries.length}
          </Badge>
          <Badge variant="secondary" className="text-sm px-3 py-1">
            Strikes: {surfaceData.strikes.length}
          </Badge>
        </div>
      )}

      {/* Chart */}
      <Card>
        <CardContent className="p-2 sm:p-4">
          {isLoading && !surfaceData ? (
            <div className="flex items-center justify-center h-[700px] text-muted-foreground">
              <div className="flex items-center gap-2">
                <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
                Computing volatility surface...
              </div>
            </div>
          ) : surfaceData ? (
            <Plot
              data={plotData.data}
              layout={plotData.layout}
              config={plotConfig}
              useResizeHandler
              style={{ width: '100%', height: '700px' }}
            />
          ) : (
            <div className="flex items-center justify-center h-[700px] text-muted-foreground">
              {expiries.length > 0
                ? 'Select expiries and click "Load Surface" to view the volatility surface'
                : 'Select an underlying to begin'}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
