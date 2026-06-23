import { Check, ChevronsUpDown } from 'lucide-react'
import type * as PlotlyTypes from 'plotly.js'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type ExpectedMoveBand,
  type GammaDensityResponse,
  gammaDensityApi,
} from '@/api/gamma-density'
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

const AUTO_REFRESH_MS = 60_000
const GAUSSIAN_POINTS = 121

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

function formatNum(n: number | undefined | null, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return '--'
  return n.toLocaleString('en-IN', { maximumFractionDigits: digits })
}

export default function GammaDensity() {
  const { mode, appMode } = useThemeStore()
  const {
    toolsFnoExchanges: fnoExchanges,
    defaultToolsFnoExchange: defaultFnoExchange,
    defaultUnderlyings,
  } = useSupportedExchanges()
  const isAnalyzer = appMode === 'analyzer'
  const isDark = mode === 'dark' || isAnalyzer

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
  const [data, setData] = useState<GammaDensityResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [autoRefresh, setAutoRefresh] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null)
  const requestIdRef = useRef(0)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Fetch underlyings when exchange changes
  useEffect(() => {
    const defaults = defaultUnderlyings[selectedExchange] || []
    setUnderlyings(defaults)
    setSelectedUnderlying(defaults[0] || '')
    setExpiries([])
    setSelectedExpiry('')
    setData(null)

    let cancelled = false
    const fetchUnderlyings = async () => {
      try {
        const response = await gammaDensityApi.getUnderlyings(selectedExchange)
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
    setSelectedExpiry('')
    setData(null)

    let cancelled = false
    const fetchExpiries = async () => {
      try {
        const response = await gammaDensityApi.getExpiries(selectedExchange, selectedUnderlying)
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
  }, [selectedUnderlying, selectedExchange])

  const fetchData = useCallback(async () => {
    if (!selectedExpiry) return
    const requestId = ++requestIdRef.current
    setIsLoading(true)
    try {
      const response = await gammaDensityApi.getGammaDensity({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: convertExpiryForAPI(selectedExpiry),
      })
      if (requestIdRef.current !== requestId) return
      if (response.status === 'success') {
        setData(response)
        setLastUpdated(new Date())
      } else {
        showToast.error(response.message || 'Failed to fetch gamma density')
      }
    } catch {
      if (requestIdRef.current !== requestId) return
      showToast.error('Failed to fetch gamma density')
    } finally {
      if (requestIdRef.current === requestId) setIsLoading(false)
    }
  }, [selectedUnderlying, selectedExpiry, selectedExchange])

  // biome-ignore lint/correctness/useExhaustiveDependencies: fire only on expiry change to avoid stale mixed-param requests during exchange/underlying switches
  useEffect(() => {
    if (selectedExpiry) fetchData()
  }, [selectedExpiry])

  useEffect(() => {
    if (!autoRefresh || !selectedExpiry) return
    const id = window.setInterval(() => fetchData(), AUTO_REFRESH_MS)
    return () => window.clearInterval(id)
  }, [autoRefresh, selectedExpiry, fetchData])

  const themeColors = useMemo(
    () => ({
      bg: 'rgba(0,0,0,0)',
      text: isDark ? '#e0e0e0' : '#333333',
      grid: isDark
        ? isAnalyzer
          ? 'rgba(180,160,255,0.1)'
          : 'rgba(255,255,255,0.08)'
        : 'rgba(0,0,0,0.08)',
      density: '#f59e0b', // amber — Γ×OI line
      densityFill: 'rgba(245,158,11,0.12)',
      convexity: '#22c55e', // green — convexity bell
      convexityFill: 'rgba(34,197,94,0.14)',
      spot: isDark ? '#60a5fa' : '#2563eb',
      band: isDark ? 'rgba(96,165,250,0.10)' : 'rgba(37,99,235,0.07)',
      hoverBg: isDark ? (isAnalyzer ? '#2d2545' : '#1e293b') : '#ffffff',
      hoverFont: isDark ? '#e0e0e0' : '#333333',
      hoverBorder: isDark ? (isAnalyzer ? '#7c3aed' : '#475569') : '#e2e8f0',
    }),
    [isDark, isAnalyzer]
  )

  // Build one Plotly panel (Intraday or To Expiry)
  const buildPanel = useCallback(
    (
      densityKey: 'density_intraday' | 'density_expiry',
      band: ExpectedMoveBand | undefined
    ): { data: PlotlyTypes.Data[]; layout: Partial<PlotlyTypes.Layout> } => {
      const chain = data?.chain ?? []
      const spot = data?.spot_price
      if (chain.length === 0 || !spot) return { data: [], layout: {} }

      const strikes = chain.map((c) => c.strike)
      const minK = Math.min(...strikes)
      const maxK = Math.max(...strikes)

      // Density (Γ×OI), normalized to its own peak so it sits on a 0..1 axis
      const rawDensity = chain.map((c) => c[densityKey] || 0)
      const maxDensity = Math.max(...rawDensity, 1e-12)
      const density = rawDensity.map((d) => d / maxDensity)

      // Convexity zone — Gaussian centred on spot, width = 1σ expected move
      const sigma = band?.sigma_move && band.sigma_move > 0 ? band.sigma_move : 0
      const gx: number[] = []
      const gy: number[] = []
      if (sigma > 0) {
        const step = (maxK - minK) / (GAUSSIAN_POINTS - 1)
        for (let i = 0; i < GAUSSIAN_POINTS; i++) {
          const x = minK + i * step
          gx.push(x)
          gy.push(Math.exp(-0.5 * ((x - spot) / sigma) ** 2))
        }
      }

      const traces: PlotlyTypes.Data[] = [
        {
          x: gx,
          y: gy,
          type: 'scatter' as const,
          mode: 'lines' as const,
          name: 'Convexity Zone',
          line: { color: themeColors.convexity, width: 2 },
          fill: 'tozeroy' as const,
          fillcolor: themeColors.convexityFill,
          hovertemplate: 'Price %{x:,.0f}<extra>Convexity</extra>',
        },
        {
          x: strikes,
          y: density,
          type: 'scatter' as const,
          mode: 'lines+markers' as const,
          name: 'Density (Γ×OI)',
          line: { color: themeColors.density, width: 2, shape: 'linear' as const },
          marker: { color: themeColors.density, size: 3 },
          hovertemplate: 'Strike %{x:,.0f}<br>Density %{y:.2f}<extra></extra>',
        },
      ]

      const shapes: Partial<PlotlyTypes.Shape>[] = []
      const annotations: Partial<PlotlyTypes.Annotations>[] = []

      // ±1σ shaded expected-move band
      if (band && band.one_sigma_low < band.one_sigma_high) {
        shapes.push({
          type: 'rect' as const,
          xref: 'x' as const,
          yref: 'paper' as const,
          x0: band.one_sigma_low,
          x1: band.one_sigma_high,
          y0: 0,
          y1: 1,
          fillcolor: themeColors.band,
          line: { width: 0 },
          layer: 'below' as const,
        })
      }

      // Spot vertical line
      shapes.push({
        type: 'line' as const,
        xref: 'x' as const,
        yref: 'paper' as const,
        x0: spot,
        x1: spot,
        y0: 0,
        y1: 1,
        line: { color: themeColors.spot, width: 1.5, dash: 'dash' as const },
      })
      annotations.push({
        x: spot,
        y: 1,
        yref: 'paper' as const,
        text: 'Spot',
        showarrow: false,
        font: { color: themeColors.spot, size: 11 },
        yanchor: 'bottom' as const,
      })

      const layout: Partial<PlotlyTypes.Layout> = {
        paper_bgcolor: themeColors.bg,
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
          y: 1.08,
          font: { color: themeColors.text, size: 11 },
        },
        margin: { l: 50, r: 20, t: 30, b: 40 },
        xaxis: {
          range: [minK, maxK],
          title: { text: 'Strike / Price', font: { color: themeColors.text, size: 11 } },
          tickfont: { color: themeColors.text, size: 10 },
          gridcolor: themeColors.grid,
        },
        yaxis: {
          range: [0, 1.08],
          tickfont: { color: themeColors.text, size: 10 },
          gridcolor: themeColors.grid,
        },
        shapes,
        annotations,
      }

      return { data: traces, layout }
    },
    [data, themeColors]
  )

  const intradayPanel = useMemo(
    () => buildPanel('density_intraday', data?.intraday_band),
    [buildPanel, data]
  )
  const expiryPanel = useMemo(
    () => buildPanel('density_expiry', data?.expiry_band),
    [buildPanel, data]
  )

  const plotConfig: Partial<PlotlyTypes.Config> = useMemo(
    () => ({
      displayModeBar: false,
      displaylogo: false,
      responsive: true,
    }),
    []
  )

  const hasData = data?.status === 'success' && (data.chain?.length ?? 0) > 0

  return (
    <div className="py-6 space-y-4">
      {/* Header */}
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold">Gamma Density</h1>
            {lastUpdated && (
              <Badge variant={autoRefresh ? 'default' : 'secondary'} className="uppercase">
                {autoRefresh ? 'Live' : 'Snapshot'}
              </Badge>
            )}
          </div>
          <p className="text-muted-foreground text-sm mt-1">
            Γ×OI density and convexity zones — where hedging pressure concentrates
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {/* Exchange selector */}
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

          {/* Underlying selector */}
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
            onClick={() => setAutoRefresh((v) => !v)}
            disabled={!selectedExpiry}
          >
            Auto: {autoRefresh ? 'ON' : 'OFF'}
          </Button>

          {/* Refresh */}
          <Button variant="outline" size="sm" onClick={fetchData} disabled={isLoading}>
            {isLoading ? 'Loading...' : 'Refresh'}
          </Button>
        </div>
      </div>

      {/* Stat cards */}
      {hasData && (
        <div className="grid grid-cols-2 sm:grid-cols-4 xl:grid-cols-8 gap-3">
          <StatCard label="Spot" value={formatNum(data?.spot_price, 1)} />
          <StatCard label="ATM IV" value={`${formatNum(data?.atm_iv)}%`} />
          <StatCard
            label="Sigma Move"
            value={`±${formatNum(data?.sigma_move)}`}
            sub={`${formatNum(data?.dte_days, 1)}d to expiry`}
          />
          <StatCard
            label="1σ Low"
            value={formatNum(data?.one_sigma_low, 0)}
            valueClass="text-red-500"
          />
          <StatCard
            label="1σ High"
            value={formatNum(data?.one_sigma_high, 0)}
            valueClass="text-green-500"
          />
          <StatCard
            label="2σ Lower Tail"
            value={formatNum(data?.two_sigma_low, 0)}
            valueClass="text-red-500"
          />
          <StatCard
            label="2σ Upper Tail"
            value={formatNum(data?.two_sigma_high, 0)}
            valueClass="text-green-500"
          />
          <StatCard label="DTE" value={formatNum(data?.dte_days, 1)} sub="days" />
        </div>
      )}

      {/* Charts */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <ChartPanel
          title="Intraday"
          subtitle="1-day hedging pressure"
          isLoading={isLoading && !data}
          hasData={hasData && intradayPanel.data.length > 0}
          panel={intradayPanel}
          plotConfig={plotConfig}
          emptyText={selectedExpiry ? 'No gamma data available' : 'Select an underlying and expiry'}
        />
        <ChartPanel
          title="To Expiry"
          subtitle="Terminal pin / gravity"
          isLoading={isLoading && !data}
          hasData={hasData && expiryPanel.data.length > 0}
          panel={expiryPanel}
          plotConfig={plotConfig}
          emptyText={selectedExpiry ? 'No gamma data available' : 'Select an underlying and expiry'}
        />
      </div>

      <p className="text-xs text-muted-foreground">
        Shaded band = ±1σ expected range. The density curve marks strikes where dealer Γ×OI is
        concentrated — spot gravitates to (long gamma) or accelerates away from (short gamma) these
        zones. Greeks use the Black-76 model (opengreeks).
        {lastUpdated && (
          <span className="ml-1">Last updated: {lastUpdated.toLocaleTimeString()}.</span>
        )}
      </p>
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string
  value: string
  sub?: string
  valueClass?: string
}) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</div>
        <div className={`text-lg font-bold ${valueClass ?? ''}`}>{value}</div>
        {sub && <div className="text-[11px] text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  )
}

function ChartPanel({
  title,
  subtitle,
  isLoading,
  hasData,
  panel,
  plotConfig,
  emptyText,
}: {
  title: string
  subtitle: string
  isLoading: boolean
  hasData: boolean
  panel: { data: PlotlyTypes.Data[]; layout: Partial<PlotlyTypes.Layout> }
  plotConfig: Partial<PlotlyTypes.Config>
  emptyText: string
}) {
  return (
    <Card>
      <CardContent className="p-3 sm:p-4">
        <div className="mb-1">
          <div className="font-semibold">{title}</div>
          <div className="text-xs text-muted-foreground">{subtitle}</div>
        </div>
        {isLoading ? (
          <div className="flex items-center justify-center h-[420px] text-muted-foreground">
            Loading…
          </div>
        ) : hasData ? (
          <Plot
            data={panel.data}
            layout={panel.layout}
            config={plotConfig}
            useResizeHandler
            style={{ width: '100%', height: '420px' }}
          />
        ) : (
          <div className="flex items-center justify-center h-[420px] text-muted-foreground">
            {emptyText}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
