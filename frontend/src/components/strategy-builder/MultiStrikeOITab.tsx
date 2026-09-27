/**
 * Open interest for every leg of the strategy, against the underlying.
 *
 * The underlying is the primary series, so a study added from the indicator
 * picker is a study of the index. Open interest is not in the engine's bar
 * model and there is one curve per leg, so neither could be the primary; they
 * are overlays on the left axis, in contract counts, with their own compact
 * formatter. The left axis rather than the right because the right one is
 * already the underlying's: sharing it put a five-figure index and an
 * eight-figure contract count on one scale, which drew the index as a flat line
 * along the bottom.
 */

import type { SeriesApi } from 'openalgo-charts'
import type { Widget } from 'openalgo-charts/widget'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  type MultiStrikeOIData,
  type MultiStrikeOILeg,
  type OIPoint,
  strategyChartApi,
} from '@/api/strategy-chart'
import { createMultiStrikeOIFeed, type StrategyFeedRequest } from '@/lib/chart/feeds/strategyFeed'
import type { StrategyLeg } from '@/lib/strategyMath'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { type ChartTooltipRow, StrategyChartShell } from './StrategyChartShell'

const DEFAULT_INTERVALS = ['1m', '3m', '5m', '10m', '15m', '30m', '1h']

/** Per-leg colours, cycled past the tenth leg. */
const LEG_PALETTE = [
  '#a855f7',
  '#3b82f6',
  '#ec4899',
  '#10b981',
  '#f97316',
  '#06b6d4',
  '#eab308',
  '#ef4444',
  '#84cc16',
  '#8b5cf6',
]

interface MultiStrikeOITabProps {
  underlying: string
  exchange: string
  underlyingSymbol?: string
  underlyingExchange?: string
  legs: StrategyLeg[]
  optionExchange: string
}

/**
 * Open interest in Indian short form.
 *
 * Contract counts run to eight digits on an index option, which is a price axis
 * of unreadable numbers. Lakh and crore are the units these are quoted in.
 */
export function formatOI(v: number): string {
  if (!Number.isFinite(v)) return '-'
  const abs = Math.abs(v)
  if (abs >= 1e7) return `${(v / 1e7).toFixed(2)}Cr`
  if (abs >= 1e5) return `${(v / 1e5).toFixed(2)}L`
  if (abs >= 1e3) return `${(v / 1e3).toFixed(1)}K`
  return v.toFixed(0)
}

function formatExpiry(expiry: string | undefined): string {
  if (!expiry) return ''
  const m = /^(\d{2})([A-Z]{3})(\d{2})$/.exec(expiry.toUpperCase())
  return m ? `${m[1]} ${m[2]}` : expiry
}

function legLabel(leg: MultiStrikeOILeg, underlying: string): string {
  const side = leg.option_type === 'CE' ? 'CALL' : leg.option_type === 'PE' ? 'PUT' : ''
  return `${underlying} ${formatExpiry(leg.expiry)} ${leg.strike ?? ''} ${side}`
    .replace(/\s+/g, ' ')
    .trim()
}

/**
 * A key that is unique per leg rather than per symbol.
 *
 * Two legs of a strategy can name the same contract, a long and a short of the
 * same strike among them. Keying by symbol merged those into one curve while
 * still drawing two legend entries, so one of the two toggles moved nothing.
 */
function legKey(leg: MultiStrikeOILeg, index: number): string {
  return `${index}:${leg.symbol}:${leg.side}`
}

/** Older points folded into a curve that is already drawn, oldest first. */
function joinSeries(current: readonly OIPoint[], older: readonly OIPoint[]): OIPoint[] {
  const byTime = new Map(older.map((p) => [p.time, p]))
  for (const point of current) byTime.set(point.time, point)
  return [...byTime.values()].sort((a, b) => a.time - b.time)
}

/**
 * Fold an older page into what is already drawn.
 *
 * Legs are matched by position, which is what the whole tab keys on: the
 * backend returns them in the order they were sent, and that order is the same
 * for both requests because the leg set did not change between them. A leg the
 * page did not answer for keeps the points it already had rather than being
 * emptied.
 *
 * The spot and the leg list are kept from `current`: they describe the strategy
 * now, not at the far end of the history the reader scrolled into.
 */
function mergeOlder(current: MultiStrikeOIData, older: MultiStrikeOIData): MultiStrikeOIData {
  return {
    ...current,
    underlying_series: joinSeries(current.underlying_series, older.underlying_series),
    legs: current.legs.map((leg, i) => ({
      ...leg,
      series: joinSeries(leg.series, older.legs[i]?.series ?? []),
    })),
  }
}

function legsIdentity(legs: StrategyLeg[], optionExchange: string): string {
  return legs
    .filter((l) => l.segment === 'OPTION' && l.active && l.symbol)
    .map((l) => `${l.symbol}|${optionExchange}|${l.side}`)
    .sort()
    .join(';')
}

export default function MultiStrikeOITab({
  underlying,
  exchange,
  underlyingSymbol,
  underlyingExchange,
  legs,
  optionExchange,
}: MultiStrikeOITabProps) {
  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)

  const [intervals, setIntervals] = useState<string[]>(DEFAULT_INTERVALS)
  const [interval, setInterval] = useState('5m')
  const [busy, setBusy] = useState(false)
  const [chartData, setChartData] = useState<MultiStrikeOIData | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [widget, setWidget] = useState<Widget | null>(null)
  const [hidden, setHidden] = useState<Record<string, boolean>>({})

  const underlyingColor = useMemo(
    () => (mode === 'dark' || appMode === 'analyzer' ? '#fbbf24' : '#d97706'),
    [mode, appMode]
  )

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
          strike: l.strike,
          optionType: l.optionType,
          expiry: l.expiry,
        })),
    [legs, optionExchange]
  )

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
      createMultiStrikeOIFeed({
        read: () => request.current,
        onPayload: (data, { paging }) => {
          setChartData((prev) => (paging && prev && data ? mergeOlder(prev, data) : data))
          if (data) setLoadError(null)
        },
      }),
    []
  )

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
        // Keep the defaults.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  const overlays = useRef(new Map<string, SeriesApi>())
  const legRows = useMemo(() => chartData?.legs ?? [], [chartData])

  /**
   * One line per leg on the left axis, reconciled against the payload rather
   * than rebuilt from it.
   *
   * Reconciled because a refresh usually returns the same legs, and dropping
   * every curve to recreate it would make each poll a visible flicker. Legs that
   * left are removed, legs that stayed keep their series and are recoloured:
   * the palette is positional, so removing a leg from the middle shifts the
   * colour of everything after it, and a series left on its old colour would
   * disagree with the legend under the chart.
   */
  useEffect(() => {
    if (!widget || widget.isDestroyed) return
    const series = overlays.current
    const wanted = new Set(legRows.map((leg, i) => legKey(leg, i)))

    for (const [key, line] of series) {
      if (wanted.has(key)) continue
      line.remove()
      series.delete(key)
    }

    legRows.forEach((leg, i) => {
      const key = legKey(leg, i)
      const style = {
        color: LEG_PALETTE[i % LEG_PALETTE.length],
        lineWidth: 2,
        title: legLabel(leg, chartData?.underlying ?? ''),
      }
      let line = series.get(key)
      if (line) {
        line.applyOptions(style)
      } else {
        line = widget.chart.addSeries('line', {
          priceScaleId: 'left',
          style,
          // Contract counts, not rupees: the axis and the crosshair tag both
          // read in lakh and crore.
          priceFormat: { type: 'custom', formatter: formatOI },
        })
        series.set(key, line)
      }
      line.setData(
        [...leg.series]
          .sort((a, b) => a.time - b.time)
          .map((p) => ({ time: p.time, value: p.value }))
      )
    })
  }, [widget, legRows, chartData?.underlying])

  /** Drop every curve with the chart that owns them. */
  useEffect(() => {
    if (!widget) return
    return () => {
      if (!widget.isDestroyed) for (const line of overlays.current.values()) line.remove()
      overlays.current.clear()
    }
  }, [widget])

  useEffect(() => {
    legRows.forEach((leg, i) => {
      const key = legKey(leg, i)
      overlays.current.get(key)?.applyOptions({ visible: !hidden[key] })
    })
  }, [legRows, hidden])

  useEffect(() => {
    if (!widget) return
    widget.series.applyOptions({
      visible: !hidden.__underlying__,
      color: underlyingColor,
    })
  }, [widget, hidden.__underlying__, underlyingColor])

  /**
   * Rows for the readout that follows the crosshair: the underlying, then every
   * leg still showing.
   *
   * A hidden leg is left out rather than greyed, so the box says exactly what
   * the chart is drawing. Legs are looked up by exact timestamp, because an OI
   * series can be missing a bar the index has and a nearest-match would quote
   * the wrong minute's open interest.
   */
  const tooltip = useCallback(
    (time: number): ChartTooltipRow[] | null => {
      const rows: ChartTooltipRow[] = []
      if (!hidden.__underlying__) {
        const spot = chartData?.underlying_series.find((p) => p.time === time)
        if (spot) {
          rows.push({
            label: chartData?.underlying ?? 'Underlying',
            value: spot.value.toLocaleString('en-IN', {
              minimumFractionDigits: 2,
              maximumFractionDigits: 2,
            }),
            color: underlyingColor,
          })
        }
      }
      legRows.forEach((leg, i) => {
        const key = legKey(leg, i)
        if (hidden[key]) return
        const at = leg.series.find((p) => p.time === time)
        if (!at) return
        rows.push({
          label: legLabel(leg, chartData?.underlying ?? ''),
          value: formatOI(at.value),
          color: LEG_PALETTE[i % LEG_PALETTE.length],
        })
      })
      return rows.length > 0 ? rows : null
    },
    [chartData, legRows, hidden, underlyingColor]
  )

  const identity = useMemo(() => legsIdentity(legs, optionExchange), [legs, optionExchange])
  const activeOptionLegs = payloadLegs.length
  const missingOI = useMemo(() => legRows.filter((l) => !l.has_oi).length, [legRows])

  const onData = useCallback((event: { error?: string }) => {
    setLoadError(event.error ?? null)
  }, [])

  const toggle = useCallback((key: string) => {
    setHidden((prev) => ({ ...prev, [key]: !prev[key] }))
  }, [])

  if (activeOptionLegs === 0) {
    return (
      <div className="rounded-xl border bg-card p-8 text-center shadow-sm">
        <div className="text-muted-foreground text-sm">
          Add at least one active option leg to see Multi Strike OI.
        </div>
      </div>
    )
  }

  return (
    <StrategyChartShell
      feed={feed}
      symbol={(underlying || 'UNDERLYING').toUpperCase()}
      exchange={exchange}
      interval={interval}
      intervals={intervals}
      onIntervalChange={setInterval}
      reloadKey={identity}
      busy={busy}
      onBusyChange={setBusy}
      persistKey="strategybuilder:multi-strike-oi"
      onReady={setWidget}
      onData={onData}
      tooltip={tooltip}
      readout={
        chartData ? (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-xs">
            <div>
              <span className="text-muted-foreground">Spot </span>
              <span className="font-medium" style={{ color: underlyingColor }}>
                {chartData.underlying_ltp?.toLocaleString('en-IN', {
                  minimumFractionDigits: 2,
                  maximumFractionDigits: 2,
                }) || '-'}
              </span>
            </div>
            <div>
              <span className="text-muted-foreground">Legs </span>
              <span className="font-medium">{legRows.length}</span>
            </div>
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
          {missingOI > 0 ? (
            <div className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-[11px] text-amber-700 dark:text-amber-400">
              {missingOI} leg{missingOI === 1 ? '' : 's'} returned no OI history. Your broker may
              not report historical open interest for options.
            </div>
          ) : null}
          {chartData && !chartData.underlying_available ? (
            <div className="rounded-md border border-blue-500/30 bg-blue-500/10 px-3 py-1.5 text-[11px] text-blue-700 dark:text-blue-400">
              Your broker does not return {interval} candles for the underlying index, so only leg
              OI is drawn. Try a coarser interval to see the underlying.
            </div>
          ) : null}
        </>
      }
      legend={
        <div className="flex flex-wrap items-center justify-center gap-2">
          <button
            type="button"
            onClick={() => toggle('__underlying__')}
            aria-pressed={!hidden.__underlying__}
            className={cn(
              'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
              !hidden.__underlying__ ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
            )}
          >
            <span
              className="inline-block h-0.5 w-5 rounded"
              style={{ backgroundColor: underlyingColor }}
            />
            {underlying || 'Underlying'}
          </button>
          {legRows.map((leg, i) => {
            const key = legKey(leg, i)
            return (
              <button
                key={key}
                type="button"
                onClick={() => toggle(key)}
                aria-pressed={!hidden[key]}
                title={leg.symbol}
                className={cn(
                  'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs transition-colors',
                  !hidden[key] ? 'bg-muted font-medium' : 'opacity-50 hover:opacity-75'
                )}
              >
                <span
                  className="inline-block h-0.5 w-5 rounded"
                  style={{ backgroundColor: LEG_PALETTE[i % LEG_PALETTE.length] }}
                />
                {legLabel(leg, chartData?.underlying ?? '')}
              </button>
            )
          })}
        </div>
      }
    />
  )
}
