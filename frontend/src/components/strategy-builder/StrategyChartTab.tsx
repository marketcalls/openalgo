import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ColorType,
  CrosshairMode,
  LineSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts'
import { strategyChartApi, type StrategyChartData, type StrategyChartPoint } from '@/api/strategy-chart'
import type { StrategyLeg } from '@/lib/strategyMath'
import { useThemeStore } from '@/stores/themeStore'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Button } from '@/components/ui/button'
import { showToast } from '@/utils/toast'

const CHART_HEIGHT = 480

interface StrategyChartTabProps {
  underlying: string
  exchange: string
  legs: StrategyLeg[]
  optionExchange: string
}

function formatIST(unixSeconds: number): { date: string; time: string } {
  const d = new Date(unixSeconds * 1000)
  const ist = new Date(d.getTime() + 5.5 * 60 * 60 * 1000)
  const dd = ist.getUTCDate().toString().padStart(2, '0')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const mo = months[ist.getUTCMonth()]
  const hh24 = ist.getUTCHours()
  const hh = hh24.toString().padStart(2, '0')
  const mm = ist.getUTCMinutes().toString().padStart(2, '0')
  const ampm = hh24 >= 12 ? 'PM' : 'AM'
  return { date: `${dd} ${mo}`, time: `${hh}:${mm} ${ampm}` }
}

/**
 * Build a compact identity string from the leg set that changes any time
 * something materially affects the combined premium (symbol, side, exchange,
 * active flag). We use this to auto-refetch on leg add/remove/toggle without
 * re-firing on unrelated state (lots, lotSize, iv, etc).
 */
function legsIdentity(legs: StrategyLeg[], optionExchange: string): string {
  return legs
    .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
    .map((l) => `${l.symbol}|${optionExchange}|${l.side}`)
    .sort()
    .join(';')
}

export default function StrategyChartTab({
  underlying,
  exchange,
  legs,
  optionExchange,
}: StrategyChartTabProps) {
  const { mode, appMode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  const isAnalyzer = appMode === 'analyzer'

  const [isLoading, setIsLoading] = useState(false)
  const [intervals, setIntervals] = useState<string[]>(['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [selectedDays, setSelectedDays] = useState('3')
  const [chartData, setChartData] = useState<StrategyChartData | null>(null)

  const [showUnderlying, setShowUnderlying] = useState(true)
  const [showCombined, setShowCombined] = useState(true)

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const underlyingSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const combinedSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<StrategyChartData | null>(null)
  const seriesMapRef = useRef<Map<number, StrategyChartPoint>>(new Map())

  const colors = useMemo(() => {
    if (isAnalyzer) {
      return {
        text: '#d4bfff',
        grid: 'rgba(139, 92, 246, 0.1)',
        border: 'rgba(139, 92, 246, 0.2)',
        crosshair: 'rgba(139, 92, 246, 0.5)',
        crosshairLabel: '#4c1d95',
        underlying: '#fbbf24',
        combined: '#a78bfa',
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
        underlying: '#fbbf24',
        combined: '#a78bfa',
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
      underlying: '#d97706',
      combined: '#7c3aed',
      watermark: 'rgba(0, 0, 0, 0.06)',
      tooltipBg: 'rgba(255, 255, 255, 0.95)',
      tooltipBorder: 'rgba(0, 0, 0, 0.15)',
      tooltipText: '#1e293b',
      tooltipMuted: '#6b7280',
    }
  }, [isDarkMode, isAnalyzer])

  const colorsRef = useRef(colors)
  colorsRef.current = colors

  // ── Chart init ────────────────────────────────────────────────
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

    const watermark = document.createElement('div')
    watermark.style.cssText = `position:absolute;z-index:2;font-family:Arial,sans-serif;font-size:48px;font-weight:bold;user-select:none;pointer-events:none;color:${colors.watermark}`
    watermark.textContent = 'OpenAlgo'
    container.appendChild(watermark)
    watermarkRef.current = watermark
    setTimeout(() => {
      watermark.style.left = `${container.offsetWidth / 2 - watermark.offsetWidth / 2}px`
      watermark.style.top = `${container.offsetHeight / 2 - watermark.offsetHeight / 2}px`
    }, 0)

    if (!tooltipRef.current) {
      const tt = document.createElement('div')
      tt.style.cssText =
        'position:absolute;z-index:10;pointer-events:none;display:none;border-radius:6px;padding:8px 12px;font-family:ui-monospace,SFMono-Regular,monospace;font-size:12px;line-height:1.6;white-space:nowrap;'
      container.appendChild(tt)
      tooltipRef.current = tt
    } else {
      container.appendChild(tooltipRef.current)
    }

    const underlyingSeries = chart.addSeries(LineSeries, {
      color: colors.underlying,
      lineWidth: 2,
      priceScaleId: 'left',
      title: 'Underlying',
      lastValueVisible: true,
      priceLineVisible: true,
      visible: showUnderlying,
    })

    const combinedSeries = chart.addSeries(LineSeries, {
      color: colors.combined,
      lineWidth: 2,
      priceScaleId: 'right',
      title: 'Strategy',
      lastValueVisible: true,
      priceLineVisible: true,
      visible: showCombined,
    })

    chartRef.current = chart
    underlyingSeriesRef.current = underlyingSeries
    combinedSeriesRef.current = combinedSeries

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
      const point = seriesMapRef.current.get(time)
      if (!point) {
        tt.style.display = 'none'
        return
      }
      const c = colorsRef.current
      const { date, time: timeStr } = formatIST(time)
      const tag = chartDataRef.current?.tag ?? 'flat'
      const tagLabel = tag === 'credit' ? 'Credit' : tag === 'debit' ? 'Debit' : 'Flat'

      tt.style.display = 'block'
      tt.style.background = c.tooltipBg
      tt.style.border = `1px solid ${c.tooltipBorder}`
      tt.style.color = c.tooltipText

      const underlyingRow =
        typeof point.underlying === 'number'
          ? `<div style="display:flex;justify-content:space-between;gap:16px">
              <span style="color:${c.underlying};font-weight:600">${underlying}</span>
              <span style="color:${c.underlying};font-weight:600">${point.underlying.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
            </div>`
          : ''
      tt.innerHTML = `
        ${underlyingRow}
        <div style="display:flex;justify-content:space-between;gap:16px">
          <span style="color:${c.combined};font-weight:600">Strategy (${tagLabel})</span>
          <span style="color:${c.combined};font-weight:600">${point.combined_premium.toFixed(2)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;gap:16px;margin-top:4px;border-top:1px solid ${c.tooltipBorder};padding-top:4px">
          <span style="color:${c.tooltipMuted}">${date}</span>
          <span style="color:${c.tooltipMuted}">${timeStr}</span>
        </div>
      `

      const tooltipW = tt.offsetWidth
      const tooltipH = tt.offsetHeight
      const x = param.point.x
      const y = param.point.y
      const margin = 16
      let left = x + margin
      if (left + tooltipW > container.offsetWidth) left = x - tooltipW - margin
      let top = y - tooltipH / 2
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
    return () => window.removeEventListener('resize', handleResize)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [colors, selectedDays, underlying])

  const applyDataToChart = useCallback((data: StrategyChartData) => {
    if (!data.series || data.series.length === 0) {
      underlyingSeriesRef.current?.setData([])
      combinedSeriesRef.current?.setData([])
      seriesMapRef.current = new Map()
      return
    }
    const sorted = [...data.series].sort((a, b) => a.time - b.time)
    const map = new Map<number, StrategyChartPoint>()
    for (const p of sorted) map.set(p.time, p)
    seriesMapRef.current = map

    // The underlying column is optional — when the broker doesn't support
    // the requested interval for the index (e.g., Zerodha 1m on NIFTY),
    // we skip it. lightweight-charts treats missing values as gaps, so
    // we filter the points that actually carry an underlying close.
    const underlyingPoints = sorted
      .filter((p): p is StrategyChartPoint & { underlying: number } => typeof p.underlying === 'number')
      .map((p) => ({ time: p.time as UTCTimestamp, value: p.underlying }))
    underlyingSeriesRef.current?.setData(underlyingPoints)
    combinedSeriesRef.current?.setData(
      sorted.map((p) => ({ time: p.time as UTCTimestamp, value: p.combined_premium }))
    )
    chartRef.current?.timeScale().fitContent()
  }, [])

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

  useEffect(() => {
    underlyingSeriesRef.current?.applyOptions({ visible: showUnderlying })
  }, [showUnderlying])

  useEffect(() => {
    combinedSeriesRef.current?.applyOptions({ visible: showCombined })
  }, [showCombined])

  // ── Intervals ─────────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const res = await strategyChartApi.getIntervals()
        if (cancelled) return
        if (res.status === 'success' && res.data) {
          const all = [
            ...(res.data.seconds || []),
            ...(res.data.minutes || []),
            ...(res.data.hours || []),
          ]
          if (all.length > 0) {
            setIntervals(all)
            if (!all.includes(selectedInterval)) {
              setSelectedInterval(all.includes('5m') ? '5m' : all.includes('1m') ? '1m' : all[0])
            }
          }
        }
      } catch {
        // Keep defaults
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Leg identity — drives auto-refetch on add/remove/toggle ───
  const identity = useMemo(() => legsIdentity(legs, optionExchange), [legs, optionExchange])

  const loadData = useCallback(async () => {
    if (!underlying || !exchange) return
    const payloadLegs = legs
      .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
      .map((l) => ({
        symbol: l.symbol,
        exchange: optionExchange,
        side: l.side,
        segment: l.segment,
        active: l.active,
        price: l.price,
      }))
    if (payloadLegs.length === 0) {
      setChartData(null)
      chartDataRef.current = null
      underlyingSeriesRef.current?.setData([])
      combinedSeriesRef.current?.setData([])
      seriesMapRef.current = new Map()
      return
    }
    setIsLoading(true)
    try {
      const res = await strategyChartApi.getStrategyChart({
        underlying,
        exchange,
        legs: payloadLegs,
        interval: selectedInterval,
        days: parseInt(selectedDays),
      })
      if (res.status === 'success' && res.data) {
        chartDataRef.current = res.data
        setChartData(res.data)
        applyDataToChart(res.data)
      } else {
        showToast.error(res.message || 'Failed to load strategy chart')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load strategy chart'
      showToast.error(msg)
    } finally {
      setIsLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying, exchange, identity, selectedInterval, selectedDays, applyDataToChart, optionExchange])

  // Auto-refetch on leg/interval/days changes. Debounced so rapid leg edits
  // (template pick, batch add) don't hammer the broker — the backend already
  // has an implicit rate limit of ~3 history calls/sec.
  useEffect(() => {
    const handle = setTimeout(() => {
      loadData()
    }, 300)
    return () => clearTimeout(handle)
  }, [loadData])

  const latest = useMemo(() => {
    if (!chartData?.series?.length) return null
    return chartData.series[chartData.series.length - 1]
  }, [chartData])

  const hasFuturesLeg = useMemo(
    () => legs.some((l) => l.segment === 'FUTURE' && l.active),
    [legs]
  )

  const activeOptionLegs = useMemo(
    () => legs.filter((l) => l.segment === 'OPTION' && l.active && l.symbol).length,
    [legs]
  )

  if (activeOptionLegs === 0) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="text-sm text-muted-foreground">
          Add at least one active option leg to see the Strategy Chart.
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border bg-card p-4 shadow-sm">
      {/* Controls */}
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <Select value={selectedInterval} onValueChange={setSelectedInterval}>
          <SelectTrigger className="w-[110px]">
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
          <SelectTrigger className="w-[110px]">
            <SelectValue placeholder="Days" />
          </SelectTrigger>
          <SelectContent>
            {['1', '3', '5', '10'].map((d) => (
              <SelectItem key={d} value={d}>
                {d} {d === '1' ? 'Day' : 'Days'}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button variant="outline" size="sm" onClick={loadData} disabled={isLoading}>
          {isLoading ? 'Loading...' : 'Refresh'}
        </Button>

        {chartData && (
          <div className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <div>
              <span className="text-muted-foreground">Spot </span>
              <span className="font-medium" style={{ color: colors.underlying }}>
                {chartData.underlying_ltp?.toLocaleString('en-IN', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                }) || '—'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">
                Entry {chartData.tag === 'credit' ? 'Credit' : chartData.tag === 'debit' ? 'Debit' : 'Net'}{' '}
              </span>
              <span className="font-medium" style={{ color: colors.combined }}>
                {chartData.entry_abs_premium.toFixed(2)}
              </span>
            </div>
            {latest && (
              <div>
                <span className="text-muted-foreground">Current </span>
                <span className="font-semibold" style={{ color: colors.combined }}>
                  {latest.combined_premium.toFixed(2)}
                </span>
              </div>
            )}
          </div>
        )}
      </div>

      {hasFuturesLeg && (
        <div className="mb-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
          Note: Futures legs are excluded from the combined premium — price levels are not premia.
        </div>
      )}
      {chartData && !chartData.underlying_available && (
        <div className="mb-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[11px] text-blue-700 dark:text-blue-400">
          Your broker doesn't return {selectedInterval} candles for the underlying index — showing
          strategy premium only. Try a coarser interval (e.g., 5m) to see the underlying overlay.
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
          <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/60">
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Loading strategy chart...
            </div>
          </div>
        )}
      </div>

      {/* Series toggles */}
      <div className="mt-3 flex items-center justify-center gap-4">
        <button
          type="button"
          onClick={() => setShowCombined((v) => !v)}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
            showCombined ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
          }`}
        >
          <span className="inline-block h-0.5 w-5 rounded" style={{ backgroundColor: colors.combined }} />
          Strategy
        </button>
        <button
          type="button"
          onClick={() => setShowUnderlying((v) => !v)}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
            showUnderlying ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
          }`}
        >
          <span
            className="inline-block h-0.5 w-5 rounded"
            style={{ backgroundColor: colors.underlying }}
          />
          {underlying || 'Underlying'}
        </button>
      </div>
    </div>
  )
}
