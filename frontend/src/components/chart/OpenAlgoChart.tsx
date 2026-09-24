/**
 * The shared OpenAlgo chart: the full charting engine, read only.
 *
 * One component for every page that wants a real chart without trading and
 * without a live feed. What it draws comes entirely from the `feed` prop, so a
 * new data source is a new `DataFeed` beside this file rather than a change to
 * it: the local Historify store today, a broker's history or an in-memory
 * backtest result later.
 *
 * The two guarantees it makes are structural, not conditional. There is no
 * read-only mode to switch off, because neither capability is ever built:
 *
 * - **It cannot place an order.** `WidgetOptions.onOrder` is what draws trade
 *   rows into the right-click menu, and this component has no prop for it and
 *   never passes it. Order entry is not something a caller can turn on.
 * - **It cannot go live.** A feed reaches it through `DataFeed`, whose
 *   `subscribeBars` is optional; a feed that omits it has no way to push. The
 *   controller's own repair poll is closed separately with
 *   `pollIntervalMs: 0`, documented as "Zero disables polling", so nothing
 *   here touches the network after a load finishes.
 *
 * The widget is built once per feed. Symbol, interval and chart type are
 * applied through the widget handle rather than by rebuilding, because a
 * rebuild throws away the viewport, the drawings and the indicator panes that
 * the user just set up.
 */

import type { DataFeed, DataLoadingOptions, SeriesApi } from 'openalgo-charts'
import { createWidget, type SymbolSearch, type Widget } from 'openalgo-charts/widget'
import { useEffect, useRef, useState } from 'react'
import { ensureCalendarIntervals, ensureInterval } from '@/lib/chart/intervalRegistry'
import { buildChartTheme, volumeColor } from '@/lib/trading/chartTheme'
import { loadCustomIndicators } from '@/lib/trading/customIndicators'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'

/**
 * The timeframe to open on when the requested one cannot be resolved.
 *
 * Daily is a built-in token, so it always resolves, and every symbol in the
 * store that has any data at all is either daily or can be asked for daily.
 */
const FALLBACK_INTERVAL = 'D'

/**
 * Run an engine call that is allowed to reject its argument.
 *
 * `setInterval` and `setChartType` throw on a code the engine does not know,
 * and they are called from effects, so the throw unwinds through React and
 * takes the whole page to the error boundary. That is how a single unknown
 * timeframe turned into a blank screen with a stack trace on it. A rejected
 * value has to leave the chart exactly as it was instead.
 */
function attempt(run: () => void, onReject: (reason: Error) => void): void {
  try {
    run()
  } catch (error) {
    onReject(error instanceof Error ? error : new Error(String(error)))
  }
}

/**
 * Bars to show when the viewport has to be put back over the data.
 *
 * Matches the engine's own default load size, so a repaired view looks like a
 * freshly opened one rather than an arbitrary zoom.
 */
const DEFAULT_VISIBLE_BARS = 500

/**
 * Fewer visible candles than this means the data is effectively off screen.
 *
 * Not zero, because the failure looks like one candle at the very edge rather
 * than none: a viewport of `{from: 749, to: 1503}` over 750 bars still counts
 * the last bar as visible while showing a blank chart.
 */
const MIN_VISIBLE_BARS = 10

/**
 * Put the viewport back over the data when the first load lands outside it.
 *
 * The widget fixes its visible range when the chart is built, which is before
 * the first load has resolved, and it does not re-anchor once bars arrive. For
 * a live feed that is invisible, because the bars land where the range already
 * is. For stored data whose newest candle is days old they land far to the
 * left of it: with 750 bars loaded the saved viewport was `{from: 749, to:
 * 1503}`, starting at the last bar and running twice the dataset into empty
 * space, so the chart read as blank with a sliver of one candle at the edge.
 *
 * Returns whether it moved anything. The caller only offers it the first load
 * of a given instrument and timeframe, so reading the left edge of a history,
 * which is most of what this page is for, is never yanked back.
 */
function anchorViewport(widget: Widget): boolean {
  const chart = widget.chart
  const count = chart.dataLayer.length
  if (count <= 0) return false

  const last = count - 1
  const range = chart.getVisibleLogicalRange()
  if (range) {
    const visible = Math.min(last, range.to) - Math.max(0, range.from) + 1
    if (visible >= Math.min(MIN_VISIBLE_BARS, count)) return false
  }

  const visible = Math.min(DEFAULT_VISIBLE_BARS, count)
  chart.setVisibleLogicalRange({
    from: Math.max(0, last - visible + 1),
    // A little clear air past the newest candle, as every chart leaves.
    to: last + Math.max(1, Math.round(visible * 0.05)),
  })
  return true
}

/**
 * Point the volume histogram at whatever the price series is holding.
 *
 * Fed as bars rather than values because the histogram reads `close`: giving
 * it the volume as both high and close is what makes the column that height.
 */
function syncVolume(widget: Widget, series: SeriesApi | null): void {
  if (!series) return
  series.setData(
    widget.series.getData().map((bar) => ({
      time: bar.time,
      open: 0,
      high: bar.volume ?? 0,
      low: 0,
      close: bar.volume ?? 0,
    }))
  )
}

/** What a finished load reported, so a host can explain an empty chart. */
export interface ChartDataEvent {
  symbol: string
  interval: string
  bars: number
  error?: string
}

export interface OpenAlgoChartProps {
  /** Where bars come from. Changing it rebuilds the chart. */
  feed: DataFeed
  /**
   * The newest moment this source can speak for, in UTC seconds.
   *
   * Omit it for a live feed, which runs to the wall clock. Supply it for
   * stored data, where the engine's two clocks otherwise both point past the
   * end of the dataset:
   *
   * - The opening window is built backwards from this clock, so without it a
   *   store whose newest candle is a few days old, which is every store over a
   *   weekend, opens on an empty window and reports having no bars.
   * - A refresh re-requests a window ending at `Math.max(originalTo, now())`
   *   and throws "History refresh returned no bars" when that window is empty
   *   while bars are held, which painted a stale error over good candles every
   *   time the tab regained focus.
   */
  dataEndsAt?: number
  symbol: string
  exchange: string
  interval: string
  /** Interval pills, only meaningful while `topbar` is on. */
  intervals?: readonly string[]
  chartType?: string
  /** Symbol lookup for the widget's own top bar, only used while `topbar` is on. */
  symbolSearch?: SymbolSearch
  /**
   * localStorage namespace for this chart's layout, drawings and indicators.
   * Give each pane its own so two charts on a page do not share a workspace.
   * Omit it and nothing is remembered.
   */
  persistKey?: string
  /** The engine's own top bar. Off when the host renders its own controls. */
  topbar?: boolean
  /** The drawing rail. */
  rail?: boolean
  statusline?: boolean
  /** The top bar's Indicators button. */
  indicators?: boolean
  className?: string
  onSymbolChange?: (symbol: string, exchange: string) => void
  onIntervalChange?: (interval: string) => void
  onChartTypeChange?: (chartType: string) => void
  /**
   * Draw a volume histogram over the price pane.
   *
   * The widget tier builds no volume series of its own, so this is the chart's
   * own: a histogram on the price pane's hidden overlay scale, which is where
   * every terminal puts it, kept in step with the bars on every load.
   */
  volume?: boolean
  /** Fires when a load finishes or fails. The host owns the message. */
  onData?: (event: ChartDataEvent) => void
  /**
   * Fires when the engine will not accept a timeframe, instead of throwing.
   * The chart keeps the one it had. The host owns what the user is told.
   */
  onIntervalRejected?: (interval: string) => void
  /** The live handle, for a host toolbar driving settings, indicators or objects. */
  onReady?: (widget: Widget | null) => void
  /**
   * Repair driven by the stream, for a host that pushes live bars into
   * `widget.dataController` itself: a refresh after each bar closes, one when
   * a bucket is skipped, each fetching only the tail. The history poll stays
   * closed whatever is passed here, so a host that pushes nothing still gets a
   * chart that never touches the network after a load.
   */
  loading?: Pick<DataLoadingOptions, 'refreshOnBarClose' | 'refreshOnGap' | 'refreshWindowBars'>
}

export function OpenAlgoChart({
  feed,
  dataEndsAt,
  symbol,
  exchange,
  interval,
  intervals,
  chartType = 'candlestick',
  symbolSearch,
  persistKey,
  volume = false,
  topbar = false,
  rail = true,
  statusline = true,
  indicators = true,
  className,
  onSymbolChange,
  onIntervalChange,
  onChartTypeChange,
  onData,
  onIntervalRejected,
  onReady,
  loading,
}: OpenAlgoChartProps) {
  const hostRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<Widget | null>(null)
  /** Instrument and timeframe whose first load has already been anchored. */
  const anchored = useRef<string | null>(null)
  const volumeSeries = useRef<SeriesApi | null>(null)
  const [ready, setReady] = useState(0)

  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)

  /**
   * Props the build reads but must not rebuild for.
   *
   * The callbacks are the obvious case: a host that declares them inline gets
   * a new identity every render, and a widget rebuilt on every render would
   * lose the chart on each keystroke. The same applies to `intervals` and
   * `symbolSearch`, which are usually literals.
   */
  const latest = useRef({
    dataEndsAt,
    symbol,
    exchange,
    interval,
    chartType,
    intervals,
    symbolSearch,
    onSymbolChange,
    onIntervalChange,
    onChartTypeChange,
    onData,
    onIntervalRejected,
    onReady,
    loading,
  })
  latest.current = {
    dataEndsAt,
    symbol,
    exchange,
    interval,
    chartType,
    intervals,
    symbolSearch,
    onSymbolChange,
    onIntervalChange,
    onChartTypeChange,
    onData,
    onIntervalRejected,
    onReady,
    loading,
  }

  useEffect(() => {
    const host = hostRef.current
    if (!host) return

    let cancelled = false
    const offs: Array<() => void> = []

    const build = async () => {
      // The built-in studies live in their own tier and the widget does not
      // pull it: on the base tier alone `registeredIndicators()` answers 0, and
      // 102 once this import has run. Without it a host that offers an
      // indicator picker opens an empty one on any install that happens to have
      // no indicator modules of its own, because the loader below returns early
      // when it finds none. Built-ins first, so a user module reusing a
      // built-in id overrides it rather than the reverse.
      try {
        await import('openalgo-charts/indicators')
      } catch {
        // A chart without studies is still a chart.
      }
      // User indicator modules register into the engine's global registry, so
      // this only has to succeed once per session and the loader de-duplicates
      // concurrent callers. It is documented never to throw; the guard is here
      // so that if it ever does, the page still gets a chart.
      try {
        await loadCustomIndicators()
      } catch {
        // A user module that will not import must not cost the built-in tier.
      }
      if (cancelled) return

      const theme = useThemeStore.getState()
      const p = latest.current

      // Above a week the engine has to be taught the code before it is handed
      // one: a month is not a fixed number of seconds, so `M`, `Q` and `Y` are
      // not built-in tokens. Falling back rather than throwing matters most
      // here, because this runs on first paint and an exception would open the
      // page on an error boundary instead of a chart.
      // Before anything the widget might restore from its own saved layout.
      ensureCalendarIntervals()
      const startInterval = ensureInterval(p.interval) ? p.interval : FALLBACK_INTERVAL
      if (startInterval !== p.interval) p.onIntervalRejected?.(p.interval)

      const widget = createWidget(host, {
        feed,
        loading: {
          ...p.loading,
          // The controller's history-repair poll. Zero closes it, which is what
          // makes this chart genuinely static rather than quietly refreshing.
          // After the spread on purpose: no host reopens it.
          pollIntervalMs: 0,
          // Read through the ref so a symbol change moves the horizon without
          // rebuilding the chart. See `dataEndsAt` for why both clocks matter.
          now: () => latest.current.dataEndsAt ?? Math.floor(Date.now() / 1000),
        },
        symbol: p.symbol,
        exchange: p.exchange,
        interval: startInterval,
        chartType: p.chartType,
        theme: buildChartTheme(theme.mode, theme.appMode),
        // The widget's own clock, in milliseconds, which is what sizes the
        // opening load window.
        now: () => (latest.current.dataEndsAt ?? Math.floor(Date.now() / 1000)) * 1000,
        topbar,
        rail,
        statusline,
        indicators,
        ...(p.intervals ? { intervals: p.intervals } : {}),
        ...(p.symbolSearch ? { symbolSearch: p.symbolSearch } : {}),
        ...(persistKey ? { persist: persistKey } : {}),
        // onOrder is deliberately absent. Without it the right-click menu
        // draws no trade rows, which is how this chart is kept unable to
        // place an order.
      })
      if (cancelled) {
        widget.destroy()
        return
      }
      widgetRef.current = widget

      offs.push(
        widget.on('symbol', (e) => latest.current.onSymbolChange?.(e.symbol, e.exchange)),
        widget.on('interval', (e) => latest.current.onIntervalChange?.(e.interval)),
        widget.on('layout', (e) => {
          if (e.chartType) latest.current.onChartTypeChange?.(e.chartType)
        }),
        widget.on('data', (e) => {
          // Only the first load of an instrument and timeframe, so paging
          // older bars in never yanks the view back. Runs before the host's
          // handler, so a chart that has just received its first bars is
          // already looking at them.
          const key = `${e.symbol}|${e.interval}`
          if (e.bars > 0 && anchored.current !== key && !widget.isDestroyed) {
            anchored.current = key
            attempt(
              () => anchorViewport(widget),
              () => {}
            )
          }
          if (e.bars > 0 && !widget.isDestroyed) {
            attempt(
              () => syncVolume(widget, volumeSeries.current),
              () => {}
            )
          }
          latest.current.onData?.(e)
        })
      )

      latest.current.onReady?.(widget)
      setReady((n) => n + 1)
    }

    void build()

    return () => {
      cancelled = true
      for (const off of offs) off()
      latest.current.onReady?.(null)
      widgetRef.current?.destroy()
      widgetRef.current = null
    }
  }, [feed, persistKey, topbar, rail, statusline, indicators])

  /**
   * The volume histogram.
   *
   * Added and removed rather than hidden, so a chart without it carries no
   * series at all: an extra series on the shared time axis is not free, and
   * replay would have to truncate it to keep the axis honest.
   */
  useEffect(() => {
    const widget = widgetRef.current
    if (!ready || !widget) return

    if (!volume) {
      volumeSeries.current?.remove()
      volumeSeries.current = null
      return
    }
    if (volumeSeries.current) return

    const theme = useThemeStore.getState()
    const series = widget.chart.addSeries('histogram', {
      paneIndex: 0,
      // '' is the hidden overlay scale: the histogram sits under the candles
      // and draws no axis of its own.
      priceScaleId: '',
      style: { color: volumeColor(theme.mode, theme.appMode) },
      // Raw share counts run to nine digits; 'volume' renders 1.20M / 3.40B.
      priceFormat: { type: 'volume' },
    })
    // Pinned to the bottom fifth, so it reads as a footer to the price rather
    // than competing with it.
    series.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 })
    volumeSeries.current = series
    syncVolume(widget, series)

    return () => {
      volumeSeries.current?.remove()
      volumeSeries.current = null
    }
  }, [volume, ready])

  // Theme, re-applied rather than rebuilt. `ready` is in the deps so the first
  // pass runs once the widget exists, not before.
  useEffect(() => {
    if (!ready) return
    widgetRef.current?.setTheme(buildChartTheme(mode, appMode))
  }, [mode, appMode, ready])

  /**
   * Reload when the source's horizon becomes known, or moves.
   *
   * The catalog that knows how far the store runs is fetched after this
   * component mounts, so the first build almost always happens with
   * `dataEndsAt` still undefined and loads against the wall clock, which for a
   * dataset a few days old finds nothing. The chart then sits on "no bars"
   * over half a million stored candles, because nothing asks it to look again.
   */
  const appliedHorizon = useRef<number | undefined>(dataEndsAt)
  useEffect(() => {
    const widget = widgetRef.current
    if (!ready || !widget) return
    if (appliedHorizon.current === dataEndsAt) return
    appliedHorizon.current = dataEndsAt
    if (dataEndsAt === undefined) return
    void widget.reload()
  }, [dataEndsAt, ready])

  useEffect(() => {
    const widget = widgetRef.current
    if (!ready || !widget) return
    if (widget.symbol() !== symbol || widget.exchange() !== exchange) {
      widget.setSymbol(symbol, exchange)
    }
  }, [symbol, exchange, ready])

  useEffect(() => {
    const widget = widgetRef.current
    if (!ready || !widget) return
    if (widget.interval() === interval) return

    // Register a calendar code before using it, and treat a code the engine
    // still will not take as a refusal rather than an exception: the chart
    // keeps the timeframe it was on and the host says why.
    if (!ensureInterval(interval)) {
      latest.current.onIntervalRejected?.(interval)
      return
    }
    attempt(
      () => widget.setInterval(interval),
      () => latest.current.onIntervalRejected?.(interval)
    )
  }, [interval, ready])

  useEffect(() => {
    const widget = widgetRef.current
    if (!ready || !widget) return
    if (widget.chartType() !== chartType) {
      // Also allowed to reject, for a chart type this build does not register.
      attempt(
        () => widget.setChartType(chartType),
        () => {}
      )
    }
  }, [chartType, ready])

  // The engine tracks its own container size, so there is no ResizeObserver
  // here. It needs a box with a real height to measure, which is what the
  // absolute fill gives it inside a flex parent that has min-h-0.
  return (
    <div className={cn('relative min-h-0 flex-1 overflow-hidden', className)}>
      <div ref={hostRef} className="absolute inset-0" />
    </div>
  )
}
