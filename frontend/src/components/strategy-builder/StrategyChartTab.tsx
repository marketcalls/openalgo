/**
 * The strategy chart: a spread's combined premium over time, with the
 * underlying beside it.
 *
 * The premium is the chart's primary series, which is what makes a study added
 * from the indicator picker a study of the spread. The underlying is an overlay
 * on the left axis, because the two are in different units and sharing one
 * scale would flatten whichever has the smaller range, which is always the
 * premium.
 */

import type { SeriesApi } from 'openalgo-charts'
import type { Widget } from 'openalgo-charts/widget'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type StrategyChartData,
  type StrategyChartPoint,
  strategyChartApi,
} from '@/api/strategy-chart'
import { createStrategyChartFeed, type StrategyFeedRequest } from '@/lib/chart/feeds/strategyFeed'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { type ChartTooltipRow, StrategyChartShell } from './StrategyChartShell'

const DEFAULT_INTERVALS = ['1m', '3m', '5m', '10m', '15m', '30m', '1h']

interface StrategyChartTabProps {
  underlying: string
  exchange: string
  underlyingSymbol?: string
  underlyingExchange?: string
  legs: StrategyLeg[]
  optionExchange: string
}

/**
 * The leg set, as one string that changes whenever something materially
 * affects the combined premium.
 *
 * Lots, lot size and IV are deliberately absent: the combined premium is
 * quantity-independent, so refetching on a lot change would spend a broker
 * history call to redraw the same line.
 */
function legsIdentity(legs: StrategyLeg[], optionExchange: string): string {
  return legs
    .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
    .map((l) => `${l.symbol}|${optionExchange}|${l.side}`)
    .sort()
    .join(';')
}

/**
 * Fold an older page into what is already drawn.
 *
 * The page carries only the bars before the ones on screen, so its points are
 * prepended and everything else is kept from `current`: the spot, the entry
 * premium and the credit-or-debit tag all describe the strategy now, and the
 * older window's copies of them are a snapshot from before the reader scrolled.
 *
 * Merged by timestamp rather than concatenated, because the window sent to the
 * backend is padded to whole IST dates and therefore overlaps the bars already
 * held at its newer edge.
 */
function mergeOlder(current: StrategyChartData, older: StrategyChartData): StrategyChartData {
  const byTime = new Map(older.series.map((p) => [p.time, p]))
  for (const point of current.series) byTime.set(point.time, point)
  return {
    ...current,
    series: [...byTime.values()].sort((a, b) => a.time - b.time),
  }
}

function money(v: number | undefined): string {
  if (typeof v !== 'number' || !Number.isFinite(v)) return '-'
  return v.toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

export default function StrategyChartTab({
  underlying,
  exchange,
  underlyingSymbol,
  underlyingExchange,
  legs,
  optionExchange,
}: StrategyChartTabProps) {
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)

  const [intervals, setIntervals] = useState<string[]>(DEFAULT_INTERVALS)
  const [interval, setInterval] = useState('5m')
  const [busy, setBusy] = useState(false)
  const [chartData, setChartData] = useState<StrategyChartData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [widget, setWidget] = useState<Widget | null>(null)
  const [showUnderlying, setShowUnderlying] = useState(true)
  const [showCombined, setShowCombined] = useState(true)

  const colors = useMemo(() => {
    if (appMode === 'analyzer') return { underlying: '#fbbf24', combined: '#a78bfa' }
    if (mode === 'dark') return { underlying: '#fbbf24', combined: '#a78bfa' }
    return { underlying: '#d97706', combined: '#7c3aed' }
  }, [mode, appMode])

  const payloadLegs = useMemo(
    () =>
      legs
        .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
        .map((l) => ({
          symbol: l.symbol,
          exchange: optionExchange,
          side: l.side,
          segment: l.segment,
          active: l.active,
          price: l.price,
        })),
    [legs, optionExchange]
  )

  /**
   * What the feed reads at fetch time.
   *
   * Held in a ref rather than captured, so the feed below can be built once and
   * keep its identity while all of this changes. See `StrategyFeedOptions.read`
   * for why that matters.
   */
  const request = useRef<StrategyFeedRequest | null>(null)
  request.current =
    underlying && exchange
      ? {
          underlying,
          exchange,
          underlyingSymbol,
          underlyingExchange,
          legs: payloadLegs,
        }
      : null

  const feed = useMemo(
    () =>
      createStrategyChartFeed({
        read: () => request.current,
        onPayload: (data, { paging }) => {
          setChartData((prev) => (paging && prev && data ? mergeOlder(prev, data) : data))
          if (data) setLoadError(null)
        },
      }),
    []
  )

  // The timeframe list the broker actually serves, fetched once.
  // biome-ignore lint/correctness/useExhaustiveDependencies: mount-only; `interval` is read to seed a default and must not re-trigger the fetch
  useEffect(() => {
    let cancelled = false
    void (async () => {
      try {
        const res = await strategyChartApi.getIntervals()
        if (cancelled || res.status !== 'success' || !res.data) return
        const all = [
          ...(res.data.seconds || []),
          ...(res.data.minutes || []),
          ...(res.data.hours || []),
        ]
        if (all.length === 0) return
        setIntervals(all)
        if (!all.includes(interval)) {
          setInterval(all.includes('5m') ? '5m' : (all[0] ?? '5m'))
        }
      } catch {
        // Keep the defaults. An unreachable interval list is not a reason to
        // leave the tab without a timeframe control.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  /**
   * The underlying overlay.
   *
   * Created once per widget and kept, rather than added and removed with the
   * legend toggle: hiding it keeps its place on the left axis, so turning it
   * back on does not re-autoscale the pane under the reader.
   */
  const overlay = useRef<SeriesApi | null>(null)
  useEffect(() => {
    if (!widget) {
      overlay.current = null
      return
    }
    const series = widget.chart.addSeries('line', {
      priceScaleId: 'left',
      style: { color: colors.underlying, lineWidth: 2 },
    })
    overlay.current = series
    return () => {
      overlay.current = null
      if (!widget.isDestroyed) series.remove()
    }
  }, [widget, colors.underlying])

  // The overlay's points. The endpoint returns them on the same timestamps as
  // the premium, so there is nothing to align: a point the underlying is
  // missing is simply absent, and the engine draws that as a gap.
  useEffect(() => {
    const series = overlay.current
    if (!series) return
    const points = (chartData?.series ?? [])
      .filter(
        (p): p is StrategyChartPoint & { underlying: number } => typeof p.underlying === 'number'
      )
      .map((p) => ({ time: p.time, value: p.underlying }))
      .sort((a, b) => a.time - b.time)
    series.setData(points)
  }, [chartData])

  useEffect(() => {
    overlay.current?.applyOptions({ visible: showUnderlying })
  }, [showUnderlying])

  useEffect(() => {
    if (!widget) return
    widget.series.applyOptions({ visible: showCombined, color: colors.combined })
  }, [widget, showCombined, colors.combined])

  /** The latest bar, for the toolbar readout and the legend. */
  const point = useMemo(() => {
    const series = chartData?.series
    return series?.length ? series[series.length - 1] : null
  }, [chartData])

  /**
   * Rows for the readout that follows the crosshair.
   *
   * Looked up by exact timestamp rather than nearest: the crosshair reports the
   * bar it snapped to, and a nearest-match would quietly quote a neighbouring
   * bar's premium wherever the series has a gap.
   */
  const tooltip = useCallback(
    (time: number): ChartTooltipRow[] | null => {
      const at = chartData?.series.find((p) => p.time === time)
      if (!at) return null
      const rows: ChartTooltipRow[] = []
      if (typeof at.underlying === 'number') {
        rows.push({
          label: underlying || 'Underlying',
          value: money(at.underlying),
          color: colors.underlying,
        })
      }
      rows.push({
        label: `Strategy (${chartData?.tag === 'credit' ? 'Credit' : chartData?.tag === 'debit' ? 'Debit' : 'Net'})`,
        value: at.combined_premium.toFixed(2),
        color: colors.combined,
      })
      return rows
    },
    [chartData, underlying, colors]
  )

  const identity = useMemo(() => legsIdentity(legs, optionExchange), [legs, optionExchange])
  const activeOptionLegs = payloadLegs.length
  const hasFuturesLeg = useMemo(() => legs.some((l) => l.segment === 'FUTURE' && l.active), [legs])

  const onData = useCallback((event: { error?: string }) => {
    setLoadError(event.error ?? null)
  }, [])

  if (activeOptionLegs === 0) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="text-muted-foreground text-sm">
          Add at least one active option leg to see the Strategy Chart.
        </div>
      </div>
    )
  }

  const tagLabel =
    chartData?.tag === 'credit' ? 'Credit' : chartData?.tag === 'debit' ? 'Debit' : 'Net'

  return (
    <StrategyChartShell
      feed={feed}
      // Uppercase deliberately: the widget upper-cases whatever it is given,
      // and the chart compares the two to decide whether the instrument
      // changed, so a label that does not survive the round trip would ask it
      // to reload on every pass.
      symbol={`${underlying || 'STRATEGY'} PREMIUM`.toUpperCase()}
      exchange={optionExchange}
      interval={interval}
      intervals={intervals}
      onIntervalChange={setInterval}
      // The underlying is absent: it is the chart's symbol, so a change to it
      // already reloads the widget and adding it here would fetch twice.
      reloadKey={identity}
      busy={busy}
      onBusyChange={setBusy}
      persistKey="strategybuilder:strategy-chart"
      onReady={setWidget}
      onData={onData}
      tooltip={tooltip}
      readout={
        chartData ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            <div>
              <span className="text-muted-foreground">Spot </span>
              <span className="font-medium" style={{ color: colors.underlying }}>
                {money(chartData.underlying_ltp)}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Entry {tagLabel} </span>
              <span className="font-medium" style={{ color: colors.combined }}>
                {money(chartData.entry_abs_premium)}
              </span>
            </div>
            {point ? (
              <div>
                <span className="text-muted-foreground">Current </span>
                <span className="font-semibold" style={{ color: colors.combined }}>
                  {money(point.combined_premium)}
                </span>
              </div>
            ) : null}
          </div>
        ) : null
      }
      notices={
        <>
          {loadError ? (
            <div className="rounded-md border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-[11px] text-red-700 dark:text-red-400">
              {loadError}
            </div>
          ) : null}
          {hasFuturesLeg ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
              Futures legs are excluded from the combined premium: price levels are not premia.
            </div>
          ) : null}
          {chartData && !chartData.underlying_available ? (
            <div className="rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[11px] text-blue-700 dark:text-blue-400">
              Your broker does not return {interval} candles for the underlying index, so only the
              strategy premium is drawn. Try a coarser interval to see the underlying overlay.
            </div>
          ) : null}
        </>
      }
      legend={
        <div className="flex flex-wrap items-center justify-center gap-2">
          <LegendToggle
            on={showCombined}
            color={colors.combined}
            label="Strategy"
            onClick={() => setShowCombined((v) => !v)}
          />
          <LegendToggle
            on={showUnderlying}
            color={colors.underlying}
            label={underlying || 'Underlying'}
            onClick={() => setShowUnderlying((v) => !v)}
          />
        </div>
      }
    />
  )
}

/**
 * A series' name and colour, which is also the switch that shows or hides it.
 *
 * No value beside the label: the readout that follows the crosshair carries
 * the numbers, and a second copy here would be showing the last bar while the
 * cursor sits on a different one.
 */
function LegendToggle({
  on,
  color,
  label,
  onClick,
}: {
  on: boolean
  color: string
  label: string
  onClick: () => void
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={on}
      title={on ? `Hide ${label}` : `Show ${label}`}
      className={cn(
        'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
        on ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
      )}
    >
      <span className="inline-block h-0.5 w-5 rounded" style={{ backgroundColor: color }} />
      {label}
    </button>
  )
}
