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
import {
  strategyChartApi,
  type MultiStrikeOIData,
  type MultiStrikeOILeg,
} from '@/api/strategy-chart'
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

// Stable palette used to colour per-leg OI series. Cycles if more than 10 legs.
const LEG_PALETTE = [
  '#a855f7', // violet
  '#3b82f6', // blue
  '#ec4899', // pink
  '#10b981', // emerald
  '#f97316', // orange
  '#06b6d4', // cyan
  '#eab308', // yellow
  '#ef4444', // red
  '#84cc16', // lime
  '#8b5cf6', // purple
]

interface MultiStrikeOITabProps {
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
 * Format an OI value in Indian short form (L = lakh, Cr = crore) — matches
 * the axis label style in the reference screenshot.
 */
function formatOI(v: number): string {
  if (!Number.isFinite(v)) return '—'
  const abs = Math.abs(v)
  if (abs >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`
  if (abs >= 1e5) return `${(v / 1e5).toFixed(2)}L`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return v.toFixed(0)
}

function formatExpiry(expiry: string | undefined): string {
  if (!expiry) return ''
  // "28APR26" → "28 APR"
  const m = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(expiry.toUpperCase())
  if (!m) return expiry
  return `${m[1]} ${m[2]}`
}

function legLabel(leg: MultiStrikeOILeg, underlying: string): string {
  const side = leg.option_type === 'CE' ? 'CALL' : leg.option_type === 'PE' ? 'PUT' : ''
  const expiry = formatExpiry(leg.expiry)
  const strike = leg.strike ?? ''
  return `${underlying} ${expiry} ${strike} ${side}`.replace(/\s+/g, ' ').trim()
}

function legsIdentity(legs: StrategyLeg[]): string {
  return legs
    .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
    .map((l) => `${l.symbol}|${l.side}`)
    .sort()
    .join(';')
}

export default function MultiStrikeOITab({
  underlying,
  exchange,
  legs,
  optionExchange,
}: MultiStrikeOITabProps) {
  const { mode, appMode } = useThemeStore()
  const isDarkMode = mode === 'dark'
  const isAnalyzer = appMode === 'analyzer'

  const [isLoading, setIsLoading] = useState(false)
  const [intervals, setIntervals] = useState<string[]>(['1m', '3m', '5m', '10m', '15m', '30m', '1h'])
  const [selectedInterval, setSelectedInterval] = useState('5m')
  const [selectedDays, setSelectedDays] = useState('3')
  const [chartData, setChartData] = useState<MultiStrikeOIData | null>(null)
  const [hiddenSeries, setHiddenSeries] = useState<Record<string, boolean>>({})

  const chartContainerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const underlyingSeriesRef = useRef<ISeriesApi<'Line'> | null>(null)
  // Keyed by leg symbol — survives leg reordering / re-render cycles.
  const legSeriesRef = useRef<Map<string, ISeriesApi<'Line'>>>(new Map())
  const tooltipRef = useRef<HTMLDivElement | null>(null)
  const watermarkRef = useRef<HTMLDivElement | null>(null)
  const chartDataRef = useRef<MultiStrikeOIData | null>(null)

  const colors = useMemo(() => {
    if (isAnalyzer) {
      return {
        text: '#d4bfff',
        grid: 'rgba(139, 92, 246, 0.1)',
        border: 'rgba(139, 92, 246, 0.2)',
        crosshair: 'rgba(139, 92, 246, 0.5)',
        crosshairLabel: '#4c1d95',
        underlying: '#fbbf24',
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
      watermark: 'rgba(0, 0, 0, 0.06)',
      tooltipBg: 'rgba(255, 255, 255, 0.95)',
      tooltipBorder: 'rgba(0, 0, 0, 0.15)',
      tooltipText: '#1e293b',
      tooltipMuted: '#6b7280',
    }
  }, [isDarkMode, isAnalyzer])

  const colorsRef = useRef(colors)
  colorsRef.current = colors

  // Stable per-leg colour, indexed by the symbol's position in the current
  // data payload. Rebuilt whenever chartData changes.
  const legColorMap = useMemo(() => {
    const map = new Map<string, string>()
    if (chartData?.legs) {
      chartData.legs.forEach((l, idx) => {
        map.set(l.symbol, LEG_PALETTE[idx % LEG_PALETTE.length])
      })
    }
    return map
  }, [chartData])

  // ── Chart init ────────────────────────────────────────────────
  const initChart = useCallback(() => {
    if (!chartContainerRef.current) return
    if (chartRef.current) {
      chartRef.current.remove()
      chartRef.current = null
    }
    legSeriesRef.current.clear()

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
      visible: !hiddenSeries['__underlying__'],
    })
    chartRef.current = chart
    underlyingSeriesRef.current = underlyingSeries

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
      const c = colorsRef.current
      const data = chartDataRef.current
      if (!data) {
        tt.style.display = 'none'
        return
      }

      const rows: string[] = []
      // Underlying
      const uPt = data.underlying_series.find((p) => p.time === time)
      if (uPt && !hiddenSeries['__underlying__']) {
        rows.push(
          `<div style="display:flex;justify-content:space-between;gap:16px">
            <span style="color:${c.underlying};font-weight:600">${data.underlying}</span>
            <span style="color:${c.underlying};font-weight:600">${uPt.value.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}</span>
          </div>`
        )
      }
      // Each visible leg
      for (const leg of data.legs) {
        if (hiddenSeries[leg.symbol]) continue
        const pt = leg.series.find((p) => p.time === time)
        if (!pt) continue
        const clr = legColorMap.get(leg.symbol) ?? '#888'
        rows.push(
          `<div style="display:flex;justify-content:space-between;gap:16px">
            <span style="color:${clr};font-weight:600">${legLabel(leg, data.underlying)}</span>
            <span style="color:${clr};font-weight:600">${formatOI(pt.value)}</span>
          </div>`
        )
      }

      if (rows.length === 0) {
        tt.style.display = 'none'
        return
      }

      const { date, time: timeStr } = formatIST(time)
      tt.style.display = 'block'
      tt.style.background = c.tooltipBg
      tt.style.border = `1px solid ${c.tooltipBorder}`
      tt.style.color = c.tooltipText
      tt.innerHTML = `
        ${rows.join('')}
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

    // Re-apply any existing data so re-inits (theme change, resize) don't blank.
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
  }, [colors, selectedDays])

  const applyDataToChart = useCallback(
    (data: MultiStrikeOIData) => {
      const chart = chartRef.current
      if (!chart) return

      // Underlying
      underlyingSeriesRef.current?.setData(
        [...data.underlying_series]
          .sort((a, b) => a.time - b.time)
          .map((p) => ({ time: p.time as UTCTimestamp, value: p.value }))
      )

      // Leg series — reconcile against existing refs so toggling legs doesn't
      // leak chart resources. Remove series for legs that disappeared.
      const activeSymbols = new Set(data.legs.map((l) => l.symbol))
      for (const [sym, series] of legSeriesRef.current.entries()) {
        if (!activeSymbols.has(sym)) {
          try {
            chart.removeSeries(series)
          } catch {
            /* already removed */
          }
          legSeriesRef.current.delete(sym)
        }
      }

      for (let i = 0; i < data.legs.length; i++) {
        const leg = data.legs[i]
        const color = LEG_PALETTE[i % LEG_PALETTE.length]
        let series = legSeriesRef.current.get(leg.symbol)
        if (!series) {
          series = chart.addSeries(LineSeries, {
            color,
            lineWidth: 2,
            priceScaleId: 'right',
            title: legLabel(leg, data.underlying),
            lastValueVisible: true,
            priceLineVisible: false,
            visible: !hiddenSeries[leg.symbol],
          })
          legSeriesRef.current.set(leg.symbol, series)
        } else {
          series.applyOptions({
            color,
            title: legLabel(leg, data.underlying),
            visible: !hiddenSeries[leg.symbol],
          })
        }
        series.setData(
          [...leg.series]
            .sort((a, b) => a.time - b.time)
            .map((p) => ({ time: p.time as UTCTimestamp, value: p.value }))
        )
      }

      chart.timeScale().fitContent()
    },
    [hiddenSeries]
  )

  useEffect(() => {
    const cleanup = initChart()
    return () => {
      cleanup?.()
      if (chartRef.current) {
        chartRef.current.remove()
        chartRef.current = null
      }
      legSeriesRef.current.clear()
    }
  }, [initChart])

  // Toggle visibility without refetching
  useEffect(() => {
    underlyingSeriesRef.current?.applyOptions({ visible: !hiddenSeries['__underlying__'] })
    for (const [sym, series] of legSeriesRef.current.entries()) {
      series.applyOptions({ visible: !hiddenSeries[sym] })
    }
  }, [hiddenSeries])

  // Intervals
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
        // keep defaults
      }
    })()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const identity = useMemo(() => legsIdentity(legs), [legs])

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
        strike: l.strike,
        optionType: l.optionType,
        expiry: l.expiry,
      }))
    if (payloadLegs.length === 0) {
      chartDataRef.current = null
      setChartData(null)
      // Clear leg series
      const chart = chartRef.current
      if (chart) {
        for (const series of legSeriesRef.current.values()) {
          try {
            chart.removeSeries(series)
          } catch {
            /* already removed */
          }
        }
      }
      legSeriesRef.current.clear()
      underlyingSeriesRef.current?.setData([])
      return
    }
    setIsLoading(true)
    try {
      const res = await strategyChartApi.getMultiStrikeOI({
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
        showToast.error(res.message || 'Failed to load OI data')
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load OI data'
      showToast.error(msg)
    } finally {
      setIsLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [underlying, exchange, identity, selectedInterval, selectedDays, optionExchange, applyDataToChart])

  useEffect(() => {
    const handle = setTimeout(() => {
      loadData()
    }, 300)
    return () => clearTimeout(handle)
  }, [loadData])

  const toggle = useCallback((key: string) => {
    setHiddenSeries((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  const activeOptionLegs = useMemo(
    () => legs.filter((l) => l.segment === 'OPTION' && l.active && l.symbol).length,
    [legs]
  )

  const missingOI = useMemo(
    () => (chartData?.legs ?? []).filter((l) => !l.has_oi).length,
    [chartData]
  )

  if (activeOptionLegs === 0) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="text-sm text-muted-foreground">
          Add at least one active option leg to see Multi Strike OI.
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
              <span className="text-muted-foreground">Legs </span>
              <span className="font-medium">{chartData.legs.length}</span>
            </div>
          </div>
        )}
      </div>

      {missingOI > 0 && (
        <div className="mb-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
          {missingOI} leg{missingOI === 1 ? '' : 's'} returned no OI history — your broker may not
          report historical OI for options.
        </div>
      )}
      {chartData && !chartData.underlying_available && (
        <div className="mb-2 rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[11px] text-blue-700 dark:text-blue-400">
          Your broker doesn't return {selectedInterval} candles for the underlying index — showing
          leg OI only. Try a coarser interval (e.g., 5m) to see the underlying overlay.
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
              Loading OI data...
            </div>
          </div>
        )}
      </div>

      {/* Legend + toggles */}
      <div className="mt-3 flex flex-wrap items-center justify-center gap-2">
        <button
          type="button"
          onClick={() => toggle('__underlying__')}
          className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
            !hiddenSeries['__underlying__'] ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
          }`}
        >
          <span
            className="inline-block h-0.5 w-5 rounded"
            style={{ backgroundColor: colors.underlying }}
          />
          {underlying || 'Underlying'}
        </button>
        {chartData?.legs.map((leg, idx) => {
          const clr = LEG_PALETTE[idx % LEG_PALETTE.length]
          const hidden = hiddenSeries[leg.symbol]
          return (
            <button
              key={leg.symbol}
              type="button"
              onClick={() => toggle(leg.symbol)}
              className={`flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors ${
                !hidden ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
              }`}
              title={leg.symbol}
            >
              <span className="inline-block h-0.5 w-5 rounded" style={{ backgroundColor: clr }} />
              {legLabel(leg, chartData.underlying)}
            </button>
          )
        })}
      </div>
    </div>
  )
}
