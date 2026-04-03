import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronsUpDown } from 'lucide-react'
import {
  BaselineSeries,
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { useThemeStore } from '@/stores/themeStore'
import { oiProfileApi } from '@/api/oi-profile'
import {
  customStraddleApi,
  type CustomStraddleData,
  type PnLDataPoint,
  type TradeEntry,
} from '@/api/custom-straddle'
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
import { Input } from '@/components/ui/input'
import { showToast } from '@/utils/toast'

// FNO_EXCHANGES and DEFAULT_UNDERLYINGS are now provided by useSupportedExchanges() hook

const LOT_SIZE_DEFAULTS: Record<string, number> = {
  NIFTY: 65, BANKNIFTY: 30, FINNIFTY: 60, MIDCPNIFTY: 120, NIFTYNXT50: 25,
  SENSEX: 10, BANKEX: 15,
}

const ADJUSTMENT_DEFAULTS: Record<string, number> = {
  NIFTY: 50, BANKNIFTY: 100, FINNIFTY: 50, MIDCPNIFTY: 25, NIFTYNXT50: 50,
  SENSEX: 100, BANKEX: 100,
}

const CHART_HEIGHT = 480

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
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const mo = months[ist.getUTCMonth()]
  const hh = ist.getUTCHours().toString().padStart(2, '0')
  const mm = ist.getUTCMinutes().toString().padStart(2, '0')
  const ampm = ist.getUTCHours() >= 12 ? 'PM' : 'AM'
  return { date: `${dd} ${mo}`, time: `${hh}:${mm} ${ampm}` }
}

function formatINR(value: number): string {
  const abs = Math.abs(value)
  const formatted = abs.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
  return value < 0 ? `-${formatted}` : formatted
}

export default function CustomStraddle() {
  const { mode, appMode } = useThemeStore()
  const { fnoExchanges, defaultFnoExchange, defaultUnderlyings } = useSupportedExchanges()
  const isDarkMode = mode === 'dark'
  const isAnalyzer = appMode === 'analyzer'

  // Control state
  const [isLoading, setIsLoading] = useState(false)
  const [selectedExchange, setSelectedExchange] = useState(defaultFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(defaultUnderlyings[defaultFnoExchange] || [])
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState(defaultUnderlyings[defaultFnoExchange]?.[0] || '')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [intervals, setIntervals] = useState<string[]>(['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
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
  const chartRef = useRef<IChartApi | null>(null)
  const pnlSeriesRef = useRef<ISeriesApi<'Baseline'> | null>(null)
  const spotSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const syntheticSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<CustomStraddleData | null>(null)
  const seriesDataMapRef = useRef<Map<number, PnLDataPoint>>(new Map())

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && fnoExchanges.some((ex) => ex.value === prev) ? prev : defaultFnoExchange
    )
  }, [defaultFnoExchange, fnoExchanges])

  // Theme colors
  const colors = useMemo(() => {
    if (isAnalyzer) {
      return {
        text: '#d4bfff', grid: 'rgba(139, 92, 246, 0.1)',
        border: 'rgba(139, 92, 246, 0.2)', crosshair: 'rgba(139, 92, 246, 0.5)',
        crosshairLabel: '#4c1d95', spot: '#e2e8f0',
        profitLine: '#4ade80', profitFill1: 'rgba(74, 222, 128, 0.28)', profitFill2: 'rgba(74, 222, 128, 0.05)',
        lossLine: '#f87171', lossFill1: 'rgba(248, 113, 113, 0.05)', lossFill2: 'rgba(248, 113, 113, 0.28)',
        watermark: 'rgba(139, 92, 246, 0.12)', synthetic: '#60a5fa',
        tooltipBg: 'rgba(30, 15, 60, 0.92)', tooltipBorder: 'rgba(139, 92, 246, 0.3)',
        tooltipText: '#d4bfff', tooltipMuted: '#a78bfa',
      }
    }
    if (isDarkMode) {
      return {
        text: '#a6adbb', grid: 'rgba(166, 173, 187, 0.1)',
        border: 'rgba(166, 173, 187, 0.2)', crosshair: 'rgba(166, 173, 187, 0.5)',
        crosshairLabel: '#1f2937', spot: '#e2e8f0',
        profitLine: '#4ade80', profitFill1: 'rgba(74, 222, 128, 0.28)', profitFill2: 'rgba(74, 222, 128, 0.05)',
        lossLine: '#f87171', lossFill1: 'rgba(248, 113, 113, 0.05)', lossFill2: 'rgba(248, 113, 113, 0.28)',
        watermark: 'rgba(166, 173, 187, 0.12)', synthetic: '#60a5fa',
        tooltipBg: 'rgba(17, 24, 39, 0.92)', tooltipBorder: 'rgba(166, 173, 187, 0.2)',
        tooltipText: '#e2e8f0', tooltipMuted: '#9ca3af',
      }
    }
    return {
      text: '#333', grid: 'rgba(0, 0, 0, 0.1)',
      border: 'rgba(0, 0, 0, 0.2)', crosshair: 'rgba(0, 0, 0, 0.3)',
      crosshairLabel: '#2563eb', spot: '#1e293b',
      profitLine: '#16a34a', profitFill1: 'rgba(22, 163, 106, 0.28)', profitFill2: 'rgba(22, 163, 106, 0.05)',
      lossLine: '#dc2626', lossFill1: 'rgba(220, 38, 38, 0.05)', lossFill2: 'rgba(220, 38, 38, 0.28)',
      watermark: 'rgba(0, 0, 0, 0.06)', synthetic: '#2563eb',
      tooltipBg: 'rgba(255, 255, 255, 0.95)', tooltipBorder: 'rgba(0, 0, 0, 0.15)',
      tooltipText: '#1e293b', tooltipMuted: '#6b7280',
    }
  }, [isDarkMode, isAnalyzer])

  const colorsRef = useRef(colors)
  colorsRef.current = colors

  // ── Chart ────────────────────────────────────────────────────

  const applyDataToChart = useCallback((data: CustomStraddleData) => {
    if (!data.pnl_series?.length) return

    const sorted = [...data.pnl_series].sort((a, b) => a.time - b.time)
    const map = new Map<number, PnLDataPoint>()
    for (const p of sorted) map.set(p.time, p)
    seriesDataMapRef.current = map

    if (pnlSeriesRef.current) {
      pnlSeriesRef.current.setData(
        sorted.map((p) => ({ time: p.time as UTCTimestamp, value: p.pnl }))
      )
    }

    if (spotSeriesRef.current) {
      spotSeriesRef.current.setData(
        sorted.map((p) => ({ time: p.time as UTCTimestamp, value: p.spot }))
      )
    }

    if (syntheticSeriesRef.current) {
      syntheticSeriesRef.current.setData(
        sorted.map((p) => ({ time: p.time as UTCTimestamp, value: p.synthetic_future }))
      )
    }

    chartRef.current?.timeScale().fitContent()
  }, [])

  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return

    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }

    const container = chartContainerRef.current
    const tooltip = tooltipRef.current
    container.innerHTML = ''
    if (tooltip) container.appendChild(tooltip)

    const chart = createChart(container, {
      width: container.offsetWidth,
      height: CHART_HEIGHT,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: colors.text },
      grid: {
        vertLines: { color: colors.grid, style: 1, visible: true },
        horzLines: { color: colors.grid, style: 1, visible: true },
      },
      leftPriceScale: { visible: true, borderColor: colors.border, scaleMargins: { top: 0.05, bottom: 0.05 } },
      rightPriceScale: { visible: true, borderColor: colors.border, scaleMargins: { top: 0.1, bottom: 0.1 } },
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
        vertLine: { width: 1, color: colors.crosshair, style: 2, labelVisible: false },
        horzLine: { width: 1, color: colors.crosshair, style: 2, labelBackgroundColor: colors.crosshairLabel },
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

    // Tooltip
    if (!tooltipRef.current) {
      const tt = document.createElement('div')
      tt.style.cssText =
        'position:absolute;z-index:10;pointer-events:none;display:none;border-radius:6px;padding:8px 12px;font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;line-height:1.6;white-space:nowrap;'
      container.appendChild(tt)
      tooltipRef.current = tt
    } else {
      container.appendChild(tooltipRef.current)
    }

    // PnL series — BaselineSeries (green above 0, red below 0)
    const pnlSeries = chart.addSeries(BaselineSeries, {
      baseValue: { type: 'price', price: 0 },
      topLineColor: colors.profitLine,
      topFillColor1: colors.profitFill1,
      topFillColor2: colors.profitFill2,
      bottomLineColor: colors.lossLine,
      bottomFillColor1: colors.lossFill1,
      bottomFillColor2: colors.lossFill2,
      lineWidth: 2,
      priceScaleId: 'right',
      lastValueVisible: true,
      priceLineVisible: true,
      visible: showPnL,
    })

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

    // Synthetic Future series (left Y-axis, dashed)
    const syntheticSeries = chart.addSeries(LineSeries, {
      color: colors.synthetic,
      lineWidth: 1,
      lineStyle: 2,
      priceScaleId: 'left',
      title: 'Synthetic Fut',
      lastValueVisible: true,
      priceLineVisible: false,
      visible: showSynthetic,
    })

    chartRef.current = chart
    pnlSeriesRef.current = pnlSeries
    spotSeriesRef.current = spotSeries
    syntheticSeriesRef.current = syntheticSeries

    // Crosshair tooltip
    chart.subscribeCrosshairMove((param) => {
      const tt = tooltipRef.current
      if (!tt || !container) return
      if (!param.time || !param.point || param.point.x < 0 || param.point.y < 0 ||
          param.point.x > container.offsetWidth || param.point.y > container.offsetHeight) {
        tt.style.display = 'none'
        return
      }
      const time = param.time as number
      const point = seriesDataMapRef.current.get(time)
      if (!point) { tt.style.display = 'none'; return }

      const c = colorsRef.current
      const { date, time: timeStr } = formatIST(time)
      const pnlColor = point.pnl >= 0 ? c.profitLine : c.lossLine

      tt.style.display = 'block'
      tt.style.background = c.tooltipBg
      tt.style.border = `1px solid ${c.tooltipBorder}`
      tt.style.color = c.tooltipText

      tt.innerHTML = `
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${pnlColor};font-weight:600">P&L</span>
          <span style="color:${pnlColor};font-weight:600">${formatINR(point.pnl)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">Spot</span>
          <span>${point.spot.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">ATM Strike</span>
          <span>${point.atm_strike}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">Entry Strike</span>
          <span>${point.entry_strike}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">Straddle</span>
          <span>${point.straddle.toFixed(2)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.synthetic}">Synthetic Fut</span>
          <span style="color:${c.synthetic}">${point.synthetic_future.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.tooltipMuted}">Adjustments</span>
          <span>${point.adjustments}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px;margin-top:4px;border-top:1px solid ${c.tooltipBorder};padding-top:4px">
          <span style="color:${c.tooltipMuted}">${date}</span>
          <span style="color:${c.tooltipMuted}">${timeStr}</span>
        </div>
      `

      const tooltipW = tt.offsetWidth
      const tooltipH = tt.offsetHeight
      let left = param.point.x + 16
      if (left + tooltipW > container.offsetWidth) left = param.point.x - tooltipW - 16
      let top = param.point.y - tooltipH / 2
      if (top < 0) top = 0
      if (top + tooltipH > container.offsetHeight) top = container.offsetHeight - tooltipH
      tt.style.left = `${left}px`
      tt.style.top = `${top}px`
    })

    if (chartDataRef.current) applyDataToChart(chartDataRef.current)

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
    return () => { window.removeEventListener('resize', handleResize) }
  }, [colors, selectedDays, showPnL, showSpot, showSynthetic, applyDataToChart])

  // Chart lifecycle
  useEffect(() => {
    const cleanup = initChart()
    return () => {
      cleanup?.()
      if (chartRef.current) { chartRef.current.remove(); chartRef.current = null }
    }
  }, [initChart])

  useEffect(() => { pnlSeriesRef.current?.applyOptions({ visible: showPnL }) }, [showPnL])
  useEffect(() => { spotSeriesRef.current?.applyOptions({ visible: showSpot }) }, [showSpot])
  useEffect(() => { syntheticSeriesRef.current?.applyOptions({ visible: showSynthetic }) }, [showSynthetic])

  // ── Data fetching ────────────────────────────────────────────

  useEffect(() => {
    const fetchIntervals = async () => {
      try {
        const res = await customStraddleApi.getIntervals()
        if (res.status === 'success' && res.data) {
          const all = [...(res.data.seconds || []), ...(res.data.minutes || []), ...(res.data.hours || [])]
          setIntervals(all.length > 0 ? all : ['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
          if (all.length > 0 && !all.includes(selectedInterval)) {
            setSelectedInterval(all.includes('1m') ? '1m' : all[0])
          }
        }
      } catch { setIntervals(['1m', '3m', '5m', '10m', '15m', '30m', '1h']) }
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
          if (!response.underlyings.includes(defaults[0])) setSelectedUnderlying(response.underlyings[0])
        }
      } catch { /* keep defaults */ }
    }
    fetchUnderlyings()
    return () => { cancelled = true }
  }, [selectedExchange])

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
    return () => { cancelled = true }
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
      } catch {
        if (!cancelled) showToast.error('Failed to fetch expiry dates', 'positions')
      }
    }
    fetchExpiries()
    return () => { cancelled = true }
  }, [selectedUnderlying])

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
        days: parseInt(selectedDays),
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
  }, [selectedExpiry, selectedInterval, selectedDays, selectedUnderlying, selectedExchange,
      adjustmentPoints, lotSize, numLots, applyDataToChart])

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
              <SelectTrigger className="w-[100px]"><SelectValue placeholder="Exchange" /></SelectTrigger>
              <SelectContent>
                {fnoExchanges.map((ex) => (
                  <SelectItem key={ex.value} value={ex.value}>{ex.label}</SelectItem>
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
                        <CommandItem key={u} value={u} onSelect={() => { setSelectedUnderlying(u); setUnderlyingOpen(false) }}>
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
              <SelectTrigger className="w-[140px]"><SelectValue placeholder="Expiry" /></SelectTrigger>
              <SelectContent>
                {expiries.map((exp) => (
                  <SelectItem key={exp} value={exp}>{exp}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={selectedInterval} onValueChange={setSelectedInterval}>
              <SelectTrigger className="w-[100px]"><SelectValue placeholder="Interval" /></SelectTrigger>
              <SelectContent>
                {intervals.map((intv) => (
                  <SelectItem key={intv} value={intv}>{intv}</SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Select value={selectedDays} onValueChange={setSelectedDays}>
              <SelectTrigger className="w-[100px]"><SelectValue placeholder="Days" /></SelectTrigger>
              <SelectContent>
                {['1', '3', '5', '7', '10'].map((d) => (
                  <SelectItem key={d} value={d}>{d} {d === '1' ? 'Day' : 'Days'}</SelectItem>
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
                onChange={(e) => setLotSize(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-[80px] h-9"
                min={1}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Lots</label>
              <Input
                type="number"
                value={numLots}
                onChange={(e) => setNumLots(Math.max(1, parseInt(e.target.value) || 1))}
                className="w-[70px] h-9"
                min={1}
              />
            </div>
            <div className="flex items-center gap-1.5">
              <label className="text-xs text-muted-foreground whitespace-nowrap">Adj Points</label>
              <Input
                type="number"
                value={adjustmentPoints}
                onChange={(e) => setAdjustmentPoints(Math.max(1, parseInt(e.target.value) || 1))}
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
                <span className={`font-semibold ${summary.total_pnl >= 0 ? 'text-green-500' : 'text-red-500'}`}>
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
            <div
              ref={chartContainerRef}
              className="relative w-full rounded-lg border border-border/50"
              style={{ height: CHART_HEIGHT }}
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
              <span className="inline-block h-0.5 w-5 rounded" style={{ backgroundColor: colors.profitLine }} />
              P&L
            </button>
            <button
              type="button"
              onClick={() => setShowSpot((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${showSpot ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'}`}
            >
              <span className="inline-block h-0.5 w-5 rounded" style={{ backgroundColor: colors.spot }} />
              Spot
            </button>
            <button
              type="button"
              onClick={() => setShowSynthetic((v) => !v)}
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs transition-colors ${showSynthetic ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'}`}
            >
              <span className="inline-block h-0.5 w-5 rounded border-dashed border-t-2" style={{ borderColor: colors.synthetic, backgroundColor: 'transparent' }} />
              Synthetic Fut
            </button>
          </div>
        </CardContent>
      </Card>

      {/* Trades Table */}
      {chartData?.trades && chartData.trades.length > 0 && (
        <Card className="mt-4">
          <CardHeader className="pb-3">
            <CardTitle className="text-lg font-semibold">Trade Log ({chartData.trades.length} trades)</CardTitle>
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
  const typeColor = trade.type === 'ENTRY'
    ? 'text-blue-500'
    : trade.type === 'ADJUSTMENT'
      ? 'text-amber-500'
      : 'text-purple-500'

  const pnlColor = trade.leg_pnl > 0 ? 'text-green-500' : trade.leg_pnl < 0 ? 'text-red-500' : ''
  const cumColor = trade.cumulative_pnl > 0 ? 'text-green-500' : trade.cumulative_pnl < 0 ? 'text-red-500' : ''

  const strikeDisplay = trade.type === 'ADJUSTMENT' && trade.old_strike
    ? `${trade.old_strike} -> ${trade.strike}`
    : `${trade.strike}`

  return (
    <tr className="border-b border-border/30 hover:bg-muted/30">
      <td className="py-2 pr-4 whitespace-nowrap text-muted-foreground">{date} {time}</td>
      <td className={`py-2 pr-4 font-medium ${typeColor}`}>{trade.type}</td>
      <td className="py-2 pr-4 text-right font-mono">{strikeDisplay}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.ce_price.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.pe_price.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.straddle.toFixed(2)}</td>
      <td className="py-2 pr-4 text-right font-mono">{trade.spot.toFixed(2)}</td>
      <td className={`py-2 pr-4 text-right font-mono ${pnlColor}`}>
        {trade.type === 'ENTRY' ? '-' : formatINR(trade.leg_pnl)}
      </td>
      <td className={`py-2 text-right font-mono ${cumColor}`}>
        {formatINR(trade.cumulative_pnl)}
      </td>
    </tr>
  )
}
