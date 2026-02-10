import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
} from 'lightweight-charts'
import { useThemeStore } from '@/stores/themeStore'
import { oiProfileApi } from '@/api/oi-profile'
import {
  straddleChartApi,
  type StraddleChartData,
  type StraddleDataPoint,
} from '@/api/straddle-chart'
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
import { Button } from '@/components/ui/button'
import { showToast } from '@/utils/toast'

const FNO_EXCHANGES = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
}

const CHART_HEIGHT = 500

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
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const mo = months[ist.getUTCMonth()]
  const hh = ist.getUTCHours().toString().padStart(2, '0')
  const mm = ist.getUTCMinutes().toString().padStart(2, '0')
  const ampm = ist.getUTCHours() >= 12 ? 'PM' : 'AM'
  return { date: `${dd} ${mo}`, time: `${hh}:${mm} ${ampm}` }
}

export default function StraddleChart() {
  const { mode, appMode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  const isAnalyzer = appMode === 'analyzer'

  // Control state
  const [isLoading, setIsLoading] = useState(false)
  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
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
  const chartRef = useRef<IChartApi | null>(null)
  const spotSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const straddleSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const syntheticSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<StraddleChartData | null>(null)
  const seriesDataMapRef = useRef<Map<number, StraddleDataPoint>>(new Map())

  // Send NFO/BFO directly — backend resolves correct exchange for index vs stock

  // Theme colors
  const colors = useMemo(() => {
    if (isAnalyzer) {
      return {
        text: '#d4bfff',
        grid: 'rgba(139, 92, 246, 0.1)',
        border: 'rgba(139, 92, 246, 0.2)',
        crosshair: 'rgba(139, 92, 246, 0.5)',
        crosshairLabel: '#4c1d95',
        spot: '#e2e8f0',
        straddle: '#a78bfa',
        synthetic: '#60a5fa',
        watermark: 'rgba(139, 92, 246, 0.12)',
        tooltipBg: 'rgba(30, 15, 60, 0.92)',
        tooltipBorder: 'rgba(139, 92, 246, 0.3)',
        tooltipText: '#d4bfff',
        tooltipMuted: '#a78bfa',
      }
    }
    if (isDarkMode) {
      return {
        text: '#a6adbb',
        grid: 'rgba(166, 173, 187, 0.1)',
        border: 'rgba(166, 173, 187, 0.2)',
        crosshair: 'rgba(166, 173, 187, 0.5)',
        crosshairLabel: '#1f2937',
        spot: '#e2e8f0',
        straddle: '#4ade80',
        synthetic: '#60a5fa',
        watermark: 'rgba(166, 173, 187, 0.12)',
        tooltipBg: 'rgba(17, 24, 39, 0.92)',
        tooltipBorder: 'rgba(166, 173, 187, 0.2)',
        tooltipText: '#e2e8f0',
        tooltipMuted: '#9ca3af',
      }
    }
    return {
      text: '#333',
      grid: 'rgba(0, 0, 0, 0.1)',
      border: 'rgba(0, 0, 0, 0.2)',
      crosshair: 'rgba(0, 0, 0, 0.3)',
      crosshairLabel: '#2563eb',
      spot: '#1e293b',
      straddle: '#16a34a',
      synthetic: '#2563eb',
      watermark: 'rgba(0, 0, 0, 0.06)',
      tooltipBg: 'rgba(255, 255, 255, 0.95)',
      tooltipBorder: 'rgba(0, 0, 0, 0.15)',
      tooltipText: '#1e293b',
      tooltipMuted: '#6b7280',
    }
  }, [isDarkMode, isAnalyzer])

  // Keep a stable ref to colors for the crosshair callback
  const colorsRef = useRef(colors)
  colorsRef.current = colors

  // ── Chart initialization ──────────────────────────────────────

  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return

    // Remove existing chart
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const container = chartContainerRef.current
    // Remove only chart children (preserve tooltip if it exists)
    const tooltip = tooltipRef.current
    container.innerHTML = ''
    // Re-append tooltip
    if (tooltip) container.appendChild(tooltip)

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: colors.text,
      },
      grid: {
        vertLines: { color: colors.grid, style: 1 as const, visible: true },
        horzLines: { color: colors.grid, style: 1 as const, visible: true },
      },
      leftPriceScale: {
        visible: true,
        borderColor: colors.border,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      rightPriceScale: {
        visible: true,
        borderColor: colors.border,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: colors.border,
        timeVisible: true,
        secondsVisible: false,
        tickMarkFormatter: (time: number) => {
          const d = new Date(time * 1000)
          const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000)
          const hh = ist.getUTCHours().toString().padStart(2, '0')
          const mm = ist.getUTCMinutes().toString().padStart(2, '0')
          if (parseInt(selectedDays) > 1) {
            const dd = ist.getUTCDate().toString().padStart(2, '0')
            const mo = (ist.getUTCMonth() + 1).toString().padStart(2, '0')
            return `${dd}/${mo} ${hh}:${mm}`
          }
          return `${hh}:${mm}`
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          width: 1 as const,
          color: colors.crosshair,
          style: 2 as const,
          labelVisible: false,
        },
        horzLine: {
          width: 1 as const,
          color: colors.crosshair,
          style: 2 as const,
          labelBackgroundColor: colors.crosshairLabel,
        },
      },
    })

    // Watermark
    const watermark = document.createElement('div')
    watermark.style.cssText = `position:absolute;z-index:2;font-family:Arial,sans-serif;font-size:48px;font-weight:bold;user-select:none;pointer-events:none;color:${colors.watermark}`
    watermark.textContent = 'OpenAlgo'
    container.appendChild(watermark)
    watermarkRef.current = watermark
    setTimeout(() => {
      watermark.style.left = `${container.offsetWidth / 2 - watermark.offsetWidth / 2}px`
      watermark.style.top = `${container.offsetHeight / 2 - watermark.offsetHeight / 2}px`
    }, 0)

    // Create tooltip element if not exists
    if (!tooltipRef.current) {
      const tt = document.createElement('div')
      tt.style.cssText =
        'position:absolute;z-index:10;pointer-events:none;display:none;border-radius:6px;padding:8px 12px;font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;line-height:1.6;white-space:nowrap;'
      container.appendChild(tt)
      tooltipRef.current = tt
    } else {
      container.appendChild(tooltipRef.current)
    }

    // Spot series (left Y-axis)
    const spotSeries = chart.addSeries(LineSeries, {
      color: colors.spot,
      lineWidth: 2,
      priceScaleId: 'left',
      title: 'Spot',
      lastValueVisible: true,
      priceLineVisible: true,
      visible: showSpot,
    })

    // Straddle series (right Y-axis)
    const straddleSeries = chart.addSeries(LineSeries, {
      color: colors.straddle,
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Straddle',
      lastValueVisible: true,
      priceLineVisible: true,
      visible: showStraddle,
    })

    // Synthetic Future series (left Y-axis, dashed)
    const syntheticSeries = chart.addSeries(LineSeries, {
      color: colors.synthetic,
      lineWidth: 1,
      lineStyle: 2, // Dashed
      priceScaleId: 'left',
      title: 'Synthetic Fut',
      lastValueVisible: true,
      priceLineVisible: false,
      visible: showSynthetic,
    })

    chartRef.current = chart
    spotSeriesRef.current = spotSeries
    straddleSeriesRef.current = straddleSeries
    syntheticSeriesRef.current = syntheticSeries

    // Crosshair move → custom tooltip
    chart.subscribeCrosshairMove((param) => {
      const tt = tooltipRef.current
      if (!tt || !container) return

      if (
        !param.time ||
        !param.point ||
        param.point.x < 0 ||
        param.point.y < 0 ||
        param.point.x > container.offsetWidth ||
        param.point.y > container.offsetHeight
      ) {
        tt.style.display = 'none'
        return
      }

      const time = param.time as number
      const point = seriesDataMapRef.current.get(time)
      if (!point) {
        tt.style.display = 'none'
        return
      }

      const c = colorsRef.current
      const { date, time: timeStr } = formatIST(time)

      tt.style.display = 'block'
      tt.style.background = c.tooltipBg
      tt.style.border = `1px solid ${c.tooltipBorder}`
      tt.style.color = c.tooltipText

      tt.innerHTML = `
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.straddle};font-weight:600">Straddle Price</span>
          <span style="color:${c.straddle};font-weight:600">${point.straddle.toFixed(2)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">&bull; ${point.atm_strike} Call:</span>
          <span>${point.ce_price.toFixed(2)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">&bull; ${point.atm_strike} Put:</span>
          <span>${point.pe_price.toFixed(2)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.synthetic}">Synthetic Fut</span>
          <span style="color:${c.synthetic}">${point.synthetic_future.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">Spot Price</span>
          <span>${point.spot.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px;margin-top:4px;border-top:1px solid ${c.tooltipBorder};padding-top:4px">
          <span style="color:${c.tooltipMuted}">${date}</span>
          <span style="color:${c.tooltipMuted}">${timeStr}</span>
        </div>
      `

      // Position tooltip — prefer right side, flip to left if near edge
      const tooltipW = tt.offsetWidth
      const tooltipH = tt.offsetHeight
      const x = param.point.x
      const y = param.point.y
      const margin = 16

      let left = x + margin
      if (left + tooltipW > container.offsetWidth) {
        left = x - tooltipW - margin
      }
      let top = y - tooltipH / 2
      if (top < 0) top = 0
      if (top + tooltipH > container.offsetHeight) {
        top = container.offsetHeight - tooltipH
      }

      tt.style.left = `${left}px`
      tt.style.top = `${top}px`
    })

    // Re-apply data if available
    if (chartDataRef.current) {
      applyDataToChart(chartDataRef.current)
    }

    // Resize handler
    const handleResize = () => {
      if (chartRef.current && container) {
        chartRef.current.applyOptions({ width: container.offsetWidth })
        if (watermarkRef.current) {
          watermarkRef.current.style.left = `${container.offsetWidth / 2 - watermarkRef.current.offsetWidth / 2}px`
          watermarkRef.current.style.top = `${container.offsetHeight / 2 - watermarkRef.current.offsetHeight / 2}px`
        }
      }
    }
    window.addEventListener('resize', handleResize)

    return () => {
      window.removeEventListener('resize', handleResize)
    }
  }, [colors, selectedDays, showStraddle, showSpot, showSynthetic])

  const applyDataToChart = useCallback((data: StraddleChartData) => {
    if (!data.series || data.series.length === 0) return

    const sorted = [...data.series].sort((a, b) => a.time - b.time)

    // Build lookup map for tooltip
    const map = new Map<number, StraddleDataPoint>()
    for (const p of sorted) {
      map.set(p.time, p)
    }
    seriesDataMapRef.current = map

    if (spotSeriesRef.current) {
      spotSeriesRef.current.setData(
        sorted.map((p) => ({
          time: p.time as import('lightweight-charts').UTCTimestamp,
          value: p.spot,
        }))
      )
    }

    if (straddleSeriesRef.current) {
      straddleSeriesRef.current.setData(
        sorted.map((p) => ({
          time: p.time as import('lightweight-charts').UTCTimestamp,
          value: p.straddle,
        }))
      )
    }

    if (syntheticSeriesRef.current) {
      syntheticSeriesRef.current.setData(
        sorted.map((p) => ({
          time: p.time as import('lightweight-charts').UTCTimestamp,
          value: p.synthetic_future,
        }))
      )
    }

    if (chartRef.current) {
      chartRef.current.timeScale().fitContent()
    }
  }, [])

  // ── Chart lifecycle ───────────────────────────────────────────

  useEffect(() => {
    const cleanup = initChart()
    return () => {
      cleanup?.()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
    }
  }, [initChart])

  // ── Series visibility toggles ─────────────────────────────────

  useEffect(() => {
    spotSeriesRef.current?.applyOptions({ visible: showSpot })
  }, [showSpot])

  useEffect(() => {
    straddleSeriesRef.current?.applyOptions({ visible: showStraddle })
  }, [showStraddle])

  useEffect(() => {
    syntheticSeriesRef.current?.applyOptions({ visible: showSynthetic })
  }, [showSynthetic])

  // ── Data fetching ─────────────────────────────────────────────

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
    const defaults = DEFAULT_UNDERLYINGS[selectedExchange] || []
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
  }, [selectedExchange])

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
      } catch {
        if (cancelled) return
        showToast.error('Failed to fetch expiry dates', 'positions')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUnderlying])

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
        days: parseInt(selectedDays),
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        applyDataToChart(res.data)
      } else {
        showToast.error(res.message || 'Failed to load straddle data', 'positions')
      }
    } catch {
      showToast.error('Failed to fetch straddle data', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [selectedExpiry, selectedInterval, selectedDays, selectedUnderlying, selectedExchange, applyDataToChart])

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
                {FNO_EXCHANGES.map((ex) => (
                  <SelectItem key={ex.value} value={ex.value}>
                    {ex.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
              <PopoverTrigger asChild>
                <Button variant="outline" role="combobox" aria-expanded={underlyingOpen} className="w-[140px] justify-between">
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
                <span className="font-semibold" style={{ color: colors.straddle }}>
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
                <span className="text-muted-foreground">
                  {latestPoint.atm_strike} CE{' '}
                </span>
                <span className="font-medium">{latestPoint.ce_price.toFixed(2)}</span>
              </div>
              <div>
                <span className="text-muted-foreground">
                  {latestPoint.atm_strike} PE{' '}
                </span>
                <span className="font-medium">{latestPoint.pe_price.toFixed(2)}</span>
              </div>
            </div>
          )}

          {/* Chart */}
          <div className="relative">
            <div
              ref={chartContainerRef}
              className="relative w-full rounded-lg border border-border/50"
              style={{ height: CHART_HEIGHT }}
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
                showStraddle
                  ? 'bg-muted font-medium'
                  : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded"
                style={{ backgroundColor: colors.straddle }}
              />
              Straddle
            </button>
            <button
              type="button"
              onClick={() => setShowSpot((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
                showSpot
                  ? 'bg-muted font-medium'
                  : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded"
                style={{ backgroundColor: colors.spot }}
              />
              Spot
            </button>
            <button
              type="button"
              onClick={() => setShowSynthetic((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${
                showSynthetic
                  ? 'bg-muted font-medium'
                  : 'opacity-50 hover:opacity-75'
              }`}
            >
              <span
                className="inline-block h-0.5 w-5 rounded border-dashed border-t-2"
                style={{ borderColor: colors.synthetic, backgroundColor: 'transparent' }}
              />
              Synthetic Fut
            </button>
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
