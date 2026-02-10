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
import { ivChartApi, type IVChartData } from '@/api/iv-chart'
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { showToast } from '@/utils/toast'

const FNO_EXCHANGES = [
  { value: 'NFO', label: 'NFO' },
  { value: 'BFO', label: 'BFO' },
]

const DEFAULT_UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
}

const METRICS = ['iv', 'delta', 'theta', 'vega', 'gamma'] as const
type MetricKey = (typeof METRICS)[number]

const METRIC_CONFIG: Record<
  MetricKey,
  { label: string; ceTitle: string; peTitle: string; formatter: (v: number) => string }
> = {
  iv: {
    label: 'IV',
    ceTitle: 'CE IV',
    peTitle: 'PE IV',
    formatter: (v) => `${v.toFixed(2)}%`,
  },
  delta: {
    label: 'Delta',
    ceTitle: 'CE Delta',
    peTitle: 'PE Delta',
    formatter: (v) => v.toFixed(4),
  },
  theta: {
    label: 'Theta',
    ceTitle: 'CE Theta',
    peTitle: 'PE Theta',
    formatter: (v) => v.toFixed(4),
  },
  vega: {
    label: 'Vega',
    ceTitle: 'CE Vega',
    peTitle: 'PE Vega',
    formatter: (v) => v.toFixed(4),
  },
  gamma: {
    label: 'Gamma',
    ceTitle: 'CE Gamma',
    peTitle: 'PE Gamma',
    formatter: (v) => v.toFixed(6),
  },
}

const CHART_HEIGHT = 350

function convertExpiryForAPI(expiry: string): string {
  if (!expiry) return ''
  const parts = expiry.split('-')
  if (parts.length === 3) {
    return `${parts[0]}${parts[1].toUpperCase()}${parts[2].slice(-2)}`
  }
  return expiry.replace(/-/g, '').toUpperCase()
}

interface ChartInstance {
  chart: IChartApi
  series: ISeriesApi<'Line'>
}

export default function IVChart() {
  const { mode } = useThemeStore()
  const isDarkMode = mode === 'dark'

  // Control state
  const [isLoading, setIsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<MetricKey>('iv')
  const [selectedExchange, setSelectedExchange] = useState('NFO')
  const [underlyings, setUnderlyings] = useState<string[]>(DEFAULT_UNDERLYINGS.NFO)
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState('NIFTY')
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [intervals, setIntervals] = useState<string[]>([])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [selectedDays, setSelectedDays] = useState('1')
  const [chartData, setChartData] = useState<IVChartData | null>(null)

  // Chart refs
  const containerRefs = useRef<Map<string, HTMLDivElement>>(new Map())
  const chartsRef = useRef<Map<string, ChartInstance>>(new Map())
  const chartDataRef = useRef<IVChartData | null>(null)

  // Send NFO/BFO directly — backend resolves correct exchange for index vs stock

  // Stable ref callbacks - one per chart container, never recreated
  const refCallbacks = useMemo(() => {
    const cbs: Record<string, (el: HTMLDivElement | null) => void> = {}
    for (const metric of METRICS) {
      for (const type of ['ce', 'pe']) {
        const key = `${metric}-${type}`
        cbs[key] = (el: HTMLDivElement | null) => {
          if (el) containerRefs.current.set(key, el)
          else containerRefs.current.delete(key)
        }
      }
    }
    return cbs
  }, [])

  // ── Chart creation helpers ──────────────────────────────────────

  const makeChartOptions = useCallback(
    (width: number) => ({
      width,
      height: CHART_HEIGHT,
      layout: {
        background: { type: ColorType.Solid as const, color: 'transparent' },
        textColor: isDarkMode ? '#a6adbb' : '#333',
      },
      grid: {
        vertLines: {
          color: isDarkMode ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.1)',
          style: 1 as const,
          visible: true,
        },
        horzLines: {
          color: isDarkMode ? 'rgba(166,173,187,0.1)' : 'rgba(0,0,0,0.1)',
          style: 1 as const,
          visible: true,
        },
      },
      rightPriceScale: {
        borderColor: isDarkMode ? 'rgba(166,173,187,0.2)' : 'rgba(0,0,0,0.2)',
        scaleMargins: { top: 0.1, bottom: 0.1 },
      },
      timeScale: {
        borderColor: isDarkMode ? 'rgba(166,173,187,0.2)' : 'rgba(0,0,0,0.2)',
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
          color: isDarkMode ? 'rgba(166,173,187,0.5)' : 'rgba(0,0,0,0.3)',
          style: 2 as const,
          labelVisible: false,
        },
        horzLine: {
          width: 1 as const,
          color: isDarkMode ? 'rgba(166,173,187,0.5)' : 'rgba(0,0,0,0.3)',
          style: 2 as const,
          labelBackgroundColor: isDarkMode ? '#1f2937' : '#2563eb',
        },
      },
    }),
    [isDarkMode, selectedDays]
  )

  const addWatermark = useCallback(
    (container: HTMLDivElement) => {
      const el = document.createElement('div')
      el.style.cssText = `position:absolute;z-index:2;font-family:Arial,sans-serif;font-size:28px;font-weight:bold;user-select:none;pointer-events:none;color:${isDarkMode ? 'rgba(166,173,187,0.12)' : 'rgba(0,0,0,0.06)'}`
      el.textContent = 'OpenAlgo'
      container.appendChild(el)
      setTimeout(() => {
        el.style.left = `${container.offsetWidth / 2 - el.offsetWidth / 2}px`
        el.style.top = `${container.offsetHeight / 2 - el.offsetHeight / 2}px`
      }, 0)
    },
    [isDarkMode]
  )

  // ── Data update ─────────────────────────────────────────────────

  const updateAllCharts = useCallback((data: IVChartData) => {
    for (const metric of METRICS) {
      for (const optType of ['CE', 'PE'] as const) {
        const key = `${metric}-${optType.toLowerCase()}`
        const inst = chartsRef.current.get(key)
        if (!inst) continue

        const seriesData = data.series.find((s) => s.option_type === optType)
        if (!seriesData) continue

        const points = seriesData.iv_data
          .filter((p) => p[metric] !== null)
          .map((p) => ({
            time: p.time as import('lightweight-charts').UTCTimestamp,
            value: p[metric] as number,
          }))
          .sort((a, b) => a.time - b.time)

        inst.series.setData(points)
        inst.chart.timeScale().fitContent()
      }
    }
  }, [])

  // ── Chart initialization (all 10 charts) ────────────────────────

  useEffect(() => {
    // Tear down previous charts
    for (const [, inst] of chartsRef.current) inst.chart.remove()
    chartsRef.current.clear()
    // Clear watermarks from containers
    for (const [, el] of containerRefs.current) el.innerHTML = ''

    // Use width from any visible container (IV tab is active by default)
    const refContainer = containerRefs.current.get('iv-ce')
    const fallbackW = refContainer?.offsetWidth || 500

    for (const metric of METRICS) {
      for (const type of ['ce', 'pe'] as const) {
        const key = `${metric}-${type}`
        const container = containerRefs.current.get(key)
        if (!container) continue

        const w = container.offsetWidth > 0 ? container.offsetWidth : fallbackW
        const color = type === 'ce' ? '#22c55e' : '#ef4444'
        const cfg = METRIC_CONFIG[metric]
        const title = type === 'ce' ? cfg.ceTitle : cfg.peTitle

        const chart = createChart(container, makeChartOptions(w))
        const series = chart.addSeries(LineSeries, {
          color,
          lineWidth: 2,
          priceScaleId: 'right',
          title,
          priceFormat: { type: 'custom' as const, formatter: cfg.formatter },
        })

        addWatermark(container)
        chartsRef.current.set(key, { chart, series })
      }
    }

    // Re-apply data to newly created charts
    if (chartDataRef.current) updateAllCharts(chartDataRef.current)

    return () => {
      for (const [, inst] of chartsRef.current) inst.chart.remove()
      chartsRef.current.clear()
    }
  }, [makeChartOptions, addWatermark, updateAllCharts])

  // ── Window resize ───────────────────────────────────────────────

  useEffect(() => {
    const onResize = () => {
      for (const [key, inst] of chartsRef.current) {
        const c = containerRefs.current.get(key)
        if (c && c.offsetWidth > 0) inst.chart.applyOptions({ width: c.offsetWidth })
      }
    }
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])

  // ── Data fetching ───────────────────────────────────────────────

  useEffect(() => {
    const fetchIntervals = async () => {
      try {
        const res = await ivChartApi.getIntervals()
        if (res.status === 'success' && res.data) {
          const all = [
            ...(res.data.seconds || []),
            ...(res.data.minutes || []),
            ...(res.data.hours || []),
          ]
          setIntervals(all.length > 0 ? all : ['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
          if (all.length > 0 && !all.includes(selectedInterval)) {
            setSelectedInterval(all.includes('5m') ? '5m' : all[0])
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
        const response = await ivChartApi.getUnderlyings(selectedExchange)
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
        const response = await ivChartApi.getExpiries(selectedExchange, selectedUnderlying)
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

  // ── Load IV + Greeks data ───────────────────────────────────────

  const loadData = useCallback(async () => {
    if (!selectedExpiry) return
    setIsLoading(true)
    try {
      const res = await ivChartApi.getIVData({
        underlying: selectedUnderlying,
        exchange: selectedExchange,
        expiry_date: convertExpiryForAPI(selectedExpiry),
        interval: selectedInterval,
        days: parseInt(selectedDays),
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        updateAllCharts(res.data)
      } else {
        showToast.error(res.message || 'Failed to load data', 'positions')
      }
    } catch {
      showToast.error('Failed to fetch data', 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [selectedExpiry, selectedInterval, selectedDays, selectedUnderlying, selectedExchange, updateAllCharts])

  useEffect(() => {
    loadData()
  }, [loadData])

  // ── Tab change with resize ──────────────────────────────────────

  const handleTabChange = (value: string) => {
    setActiveTab(value as MetricKey)
    requestAnimationFrame(() => {
      for (const type of ['ce', 'pe']) {
        const key = `${value}-${type}`
        const inst = chartsRef.current.get(key)
        const c = containerRefs.current.get(key)
        if (inst && c && c.offsetWidth > 0) {
          inst.chart.applyOptions({ width: c.offsetWidth })
          inst.chart.timeScale().fitContent()
        }
      }
    })
  }

  // ── Display helpers ─────────────────────────────────────────────

  const getLatestValue = (type: 'CE' | 'PE', metric: MetricKey): string => {
    if (!chartData) return '--'
    const s = chartData.series.find((x) => x.option_type === type)
    if (!s) return '--'
    const valid = s.iv_data.filter((p) => p[metric] !== null)
    if (valid.length === 0) return '--'
    const v = valid[valid.length - 1][metric]
    if (v === null) return '--'
    return METRIC_CONFIG[metric].formatter(v)
  }

  // ── Render ──────────────────────────────────────────────────────

  return (
    <div className="container mx-auto px-4 py-6 max-w-7xl">
      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-xl font-semibold">Option Greeks</CardTitle>
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
                {['1', '5', '10', '15'].map((d) => (
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
          {chartData && (
            <div className="flex flex-wrap items-center gap-x-6 gap-y-1 mb-4 text-sm">
              <div>
                <span className="text-muted-foreground">ATM Strike: </span>
                <span className="font-medium">{chartData.atm_strike}</span>
              </div>
              <div>
                <span className="text-muted-foreground">LTP: </span>
                <span className="font-medium">{chartData.underlying_ltp?.toFixed(2)}</span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-green-500" />
                <span className="text-muted-foreground">CE: </span>
                <span className="font-medium">{chartData.ce_symbol}</span>
                <span className="text-green-600 dark:text-green-400 font-medium ml-1">
                  {getLatestValue('CE', 'iv')}
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-2.5 rounded-full bg-red-500" />
                <span className="text-muted-foreground">PE: </span>
                <span className="font-medium">{chartData.pe_symbol}</span>
                <span className="text-red-600 dark:text-red-400 font-medium ml-1">
                  {getLatestValue('PE', 'iv')}
                </span>
              </div>
            </div>
          )}

          {/* Metric tabs */}
          <Tabs value={activeTab} onValueChange={handleTabChange}>
            <TabsList className="grid w-full max-w-md grid-cols-5">
              {METRICS.map((m) => (
                <TabsTrigger key={m} value={m}>
                  {METRIC_CONFIG[m].label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>

          {/* Chart panels — all 10 rendered, only active tab visible */}
          <div className="mt-4">
            {METRICS.map((metric) => (
              <div
                key={metric}
                className={activeTab !== metric ? 'h-0 overflow-hidden pointer-events-none' : ''}
              >
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {/* CE chart */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-green-600 dark:text-green-400">
                        {chartData?.ce_symbol || 'CE'} {METRIC_CONFIG[metric].label}
                      </span>
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {getLatestValue('CE', metric)}
                      </span>
                    </div>
                    <div
                      ref={refCallbacks[`${metric}-ce`]}
                      className="relative w-full rounded-lg border border-border/50"
                      style={{ height: CHART_HEIGHT }}
                    />
                  </div>
                  {/* PE chart */}
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-sm font-medium text-red-600 dark:text-red-400">
                        {chartData?.pe_symbol || 'PE'} {METRIC_CONFIG[metric].label}
                      </span>
                      <span className="text-sm tabular-nums text-muted-foreground">
                        {getLatestValue('PE', metric)}
                      </span>
                    </div>
                    <div
                      ref={refCallbacks[`${metric}-pe`]}
                      className="relative w-full rounded-lg border border-border/50"
                      style={{ height: CHART_HEIGHT }}
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
