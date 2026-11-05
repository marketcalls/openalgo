/**
 * Option Greeks: the ATM call's and put's IV, Delta, Theta, Vega and Gamma over
 * the session, one tab per metric, the call beside the put.
 *
 * Drawn by openalgo-charts, the engine /trading uses, driven the way the other
 * read-only charts drive it (`BacktestChart`, `CandleViz`): `createChart` on a
 * host div per panel, the app's theme tokens through `buildChartTheme`, and a
 * theme change applied with `setTheme` rather than by rebuilding ten charts.
 *
 * The call is drawn in the theme's up colour and the put in its down colour,
 * the green and red the panel headings and the info bar already use for them.
 *
 * Times arrive from the backend as real UTC seconds and are handed over as
 * they are: the engine labels them in IST itself, which is its default zone,
 * and switches from clock to date at a day boundary on a multi-day range.
 */

import { Check, ChevronsUpDown } from 'lucide-react'
import { type Chart, createChart, type SeriesApi } from 'openalgo-charts'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { type IVChartData, ivChartApi } from '@/api/iv-chart'
import { Button } from '@/components/ui/button'
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
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { useSupportedExchanges } from '@/hooks/useSupportedExchanges'
import { serverSentence } from '@/lib/serverSentence'
import { buildChartTheme } from '@/lib/trading/chartTheme'
import { type AppMode, type ThemeMode, useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

// FNO_EXCHANGES and DEFAULT_UNDERLYINGS are now provided by useSupportedExchanges() hook

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

const SIDES = ['ce', 'pe'] as const
type Side = (typeof SIDES)[number]

interface ChartInstance {
  chart: Chart
  series: SeriesApi
  side: Side
}

/**
 * One panel's palette: the app's theme, with the side's colour as its line and
 * its current-value tag. The tag would otherwise turn green or red with the
 * last move, which on a put drawn in red reads as a second, unrelated signal.
 */
function sideTheme(mode: ThemeMode, appMode: AppMode, side: Side) {
  const theme = buildChartTheme(mode, appMode)
  const color = side === 'ce' ? theme.upColor : theme.downColor
  return { theme: { ...theme, lastPriceUp: color, lastPriceDown: color }, color }
}

export default function IVChart() {
  const mode = useThemeStore((state) => state.mode)
  const appMode = useThemeStore((state) => state.appMode)
  const { toolsFnoExchanges, defaultToolsFnoExchange, defaultUnderlyings } = useSupportedExchanges()

  // Control state
  const [isLoading, setIsLoading] = useState(false)
  const [activeTab, setActiveTab] = useState<MetricKey>('iv')
  const [selectedExchange, setSelectedExchange] = useState(defaultToolsFnoExchange)
  const [underlyings, setUnderlyings] = useState<string[]>(
    defaultUnderlyings[defaultToolsFnoExchange] || []
  )
  const [underlyingOpen, setUnderlyingOpen] = useState(false)
  const [selectedUnderlying, setSelectedUnderlying] = useState(
    defaultUnderlyings[defaultToolsFnoExchange]?.[0] || ''
  )
  const [expiries, setExpiries] = useState<string[]>([])
  const [selectedExpiry, setSelectedExpiry] = useState('')
  const [intervals, setIntervals] = useState<string[]>([])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [selectedDays, setSelectedDays] = useState('1')
  const [chartData, setChartData] = useState<IVChartData | null>(null)

  // Re-sync exchange when broker capabilities load asynchronously
  useEffect(() => {
    setSelectedExchange((prev) =>
      prev && toolsFnoExchanges.some((ex) => ex.value === prev) ? prev : defaultToolsFnoExchange
    )
  }, [defaultToolsFnoExchange, toolsFnoExchanges])

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

  // ── Data update ─────────────────────────────────────────────────

  const updateAllCharts = useCallback((data: IVChartData) => {
    for (const metric of METRICS) {
      for (const optType of ['CE', 'PE'] as const) {
        const key = `${metric}-${optType.toLowerCase()}`
        const inst = chartsRef.current.get(key)
        if (!inst) continue

        const seriesData = data.series.find((s) => s.option_type === optType)
        if (!seriesData) continue

        // Real UTC seconds, handed over as they are: see the module docstring.
        const points = seriesData.iv_data
          .filter((p) => p[metric] !== null)
          .map((p) => ({ time: p.time, value: p[metric] as number }))
          .sort((a, b) => a.time - b.time)

        inst.series.setData(points)
        inst.chart.fitContent()
      }
    }
  }, [])

  // ── Chart initialization (all 10 charts) ────────────────────────

  // Built once. The engine tracks each container's size itself, so a window
  // resize or a tab switch needs nothing from here, and a theme change is the
  // effect below: the theme is read here for the first paint only.
  // biome-ignore lint/correctness/useExhaustiveDependencies: theme excluded; handled by the re-theme effect
  useEffect(() => {
    const built = chartsRef.current
    const hosts: HTMLDivElement[] = []

    for (const metric of METRICS) {
      for (const side of SIDES) {
        const key = `${metric}-${side}`
        const container = containerRefs.current.get(key)
        if (!container) continue

        const cfg = METRIC_CONFIG[metric]
        const title = side === 'ce' ? cfg.ceTitle : cfg.peTitle
        const { theme, color } = sideTheme(mode, appMode, side)

        const chart = createChart(container, {
          theme,
          ariaLabel: `${title} chart`,
          // A read-only study: the keyboard belongs to the page, and the hover
          // zoom rail is more chrome than a half-width panel has room for.
          shortcuts: false,
          timeNavigator: false,
        })
        const series = chart.addSeries('line', {
          priceScaleId: 'right',
          style: { color, lineWidth: 2, title },
          priceFormat: { type: 'custom', formatter: cfg.formatter },
        })
        series.priceScale().setOptions({ marginTop: 0.1, marginBottom: 0.1 })

        built.set(key, { chart, series, side })
        hosts.push(container)
      }
    }

    // Re-apply data to newly created charts
    if (chartDataRef.current) updateAllCharts(chartDataRef.current)

    return () => {
      for (const [, inst] of built) inst.chart.destroy()
      built.clear()
      // `destroy` releases the engine's listeners; clearing the host is what
      // guarantees a remount starts on an empty div rather than stacking a
      // second canvas on the first.
      for (const host of hosts) host.innerHTML = ''
    }
  }, [updateAllCharts])

  // ── Theme ───────────────────────────────────────────────────────

  // Re-theme every chart in place, and recolour each line with its side.
  useEffect(() => {
    for (const [, inst] of chartsRef.current) {
      const { theme, color } = sideTheme(mode, appMode, inst.side)
      inst.chart.setTheme(theme)
      inst.series.applyOptions({ color })
    }
  }, [mode, appMode])

  // ── Data fetching ───────────────────────────────────────────────

  // biome-ignore lint/correctness/useExhaustiveDependencies: run-once on mount to load the available interval list; selectedInterval is read only to seed a default and must not re-trigger this fetch on user interval changes
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
  }, [selectedExchange, defaultUnderlyings])

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
      } catch (error) {
        if (cancelled) return
        showToast.error(serverSentence(error, 'Failed to fetch expiry dates'), 'positions')
      }
    }
    fetchExpiries()
    return () => {
      cancelled = true
    }
  }, [selectedUnderlying, selectedExchange])

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
        days: parseInt(selectedDays, 10),
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        updateAllCharts(res.data)
      } else {
        showToast.error(res.message || 'Failed to load data', 'positions')
      }
    } catch (error) {
      showToast.error(serverSentence(error, 'Failed to fetch data'), 'positions')
    } finally {
      setIsLoading(false)
    }
  }, [
    selectedExpiry,
    selectedInterval,
    selectedDays,
    selectedUnderlying,
    selectedExchange,
    updateAllCharts,
  ])

  useEffect(() => {
    loadData()
  }, [loadData])

  // ── Tab change with resize ──────────────────────────────────────

  // The engine follows its container's size on its own. Fitting the tab that
  // has just come into view keeps the whole range in it, as it always has.
  const handleTabChange = (value: string) => {
    setActiveTab(value as MetricKey)
    requestAnimationFrame(() => {
      for (const side of SIDES) {
        chartsRef.current.get(`${value}-${side}`)?.chart.fitContent()
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
                {toolsFnoExchanges.map((ex) => (
                  <SelectItem key={ex.value} value={ex.value}>
                    {ex.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            <Popover open={underlyingOpen} onOpenChange={setUnderlyingOpen}>
              <PopoverTrigger asChild>
                <Button
                  variant="outline"
                  role="combobox"
                  aria-expanded={underlyingOpen}
                  className="w-[140px] justify-between"
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
