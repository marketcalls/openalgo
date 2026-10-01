/**
 * Shared chrome for the strategy builder's two chart tabs.
 *
 * Both tabs draw different things, but everything around the canvas is the
 * same: a timeframe, a refresh, an indicator picker, a full screen toggle, a
 * right-click menu, a row of banners and a legend. This holds that, so the tabs are left
 * holding only what is genuinely theirs, which is the shape of their data.
 *
 * What it deliberately does not carry is replay. The transport is built for
 * stepping through price history bar by bar, and neither of these charts is
 * price history: one is a spread's premium, the other is open interest. A
 * control that runs but means nothing is worse than an absent one.
 */

import { BarChart3, Maximize2, Minimize2, RefreshCw, Settings2 } from 'lucide-react'
import type { CrosshairMoveEvent, DataFeed } from 'openalgo-charts'
import { registeredIndicators } from 'openalgo-charts'
import type { Widget } from 'openalgo-charts/widget'
import { type ReactNode, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { ChartContextMenu, type ChartMenuAnchor } from '@/components/chart/ChartContextMenu'
import {
  type ChartDataEvent,
  OpenAlgoChart,
  type OpenAlgoChartProps,
} from '@/components/chart/OpenAlgoChart'
import {
  type CatalogEntry,
  IndicatorPickerDialog,
} from '@/components/trading/IndicatorPickerDialog'
import { Button } from '@/components/ui/button'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

/**
 * Height of the pane when it is not full screen.
 *
 * Taller than the 480 px canvas these tabs used to draw, because the toolbar,
 * the banners and the legend now live inside the same box and the canvas should
 * not be the thing that gives up the room.
 */
const PANE_HEIGHT = 560

export interface StrategyChartShellProps {
  /**
   * Bars for the primary series.
   *
   * Must keep a stable identity: `OpenAlgoChart` rebuilds its widget when this
   * changes, and a rebuild costs the user every indicator and drawing on the
   * chart. Parameters belong behind the feed's own `read` callback, with
   * `reloadKey` below driving the refetch.
   */
  feed: DataFeed
  /** Label for the primary series, shown in the engine's own status furniture. */
  symbol: string
  exchange: string
  interval: string
  intervals: readonly string[]
  onIntervalChange: (interval: string) => void
  /**
   * Anything that should send the feed back to the network, as one string.
   *
   * The legs are not part of the engine's own idea of a request, which is a
   * symbol and a timeframe, so nothing in the engine knows that changing them
   * invalidates what is drawn. Changing this value reloads the chart,
   * debounced, without rebuilding it.
   */
  reloadKey: string
  /** True while a load is in flight, for the refresh button and the veil. */
  busy: boolean
  onBusyChange: (busy: boolean) => void
  /** localStorage namespace. Each tab needs its own or they share a workspace. */
  persistKey: string
  /** Right-hand side of the toolbar: the tab's own numeric readout. */
  readout?: ReactNode
  /** Banners between the toolbar and the canvas. */
  notices?: ReactNode
  /** Legend and series toggles under the canvas. */
  legend?: ReactNode
  /** The live widget handle, for the tab's overlay series. Null on teardown. */
  onReady: (widget: Widget | null) => void
  onData?: (event: ChartDataEvent) => void
  /**
   * Rows for the floating readout that follows the crosshair.
   *
   * Called with the bar under the cursor. Return null when that bar has nothing
   * to say and the box stays hidden, rather than showing an empty frame over a
   * gap in the data.
   *
   * The shell owns the box, its placement and its timestamp; a tab owns only
   * what its own numbers mean.
   */
  tooltip?: (time: number) => ChartTooltipRow[] | null
  /** Stream-driven repair for a tab that pushes live bars; see the chart's prop. */
  loading?: OpenAlgoChartProps['loading']
}

/** One labelled number in the crosshair readout. */
export interface ChartTooltipRow {
  label: string
  value: string
  color: string
}

/**
 * The hovered timestamp, as a reader in India reads it.
 *
 * Through `Intl` with the zone named rather than by adding five and a half
 * hours to a UTC date: the arithmetic happens to be right for IST and is wrong
 * the moment anyone points this at a market that observes daylight saving.
 */
const IST_DATE = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  day: '2-digit',
  month: 'short',
})
const IST_TIME = new Intl.DateTimeFormat('en-IN', {
  timeZone: 'Asia/Kolkata',
  hour: '2-digit',
  minute: '2-digit',
  hour12: true,
})

/** Where the crosshair is, in the chart box's own pixels. */
interface HoverPoint {
  time: number
  x: number
  y: number
}

/**
 * The readout's own palette, carried over unchanged from the charts these tabs
 * replaced.
 *
 * Not the generic popover tokens: the box sits on the plot rather than on the
 * page, so it is tinted to the chart surface underneath it, and analyzer mode
 * tints violet the way the rest of that mode does. Keeping the exact values
 * means the tab looks the same after the migration as before it.
 */
function tooltipPalette(mode: string, appMode: string) {
  if (appMode === 'analyzer') {
    return {
      background: 'rgba(30, 15, 60, 0.92)',
      border: 'rgba(139, 92, 246, 0.3)',
      text: '#d4bfff',
      muted: '#a78bfa',
    }
  }
  if (mode === 'dark') {
    return {
      background: 'rgba(17, 24, 39, 0.92)',
      border: 'rgba(166, 173, 187, 0.2)',
      text: '#e2e8f0',
      muted: '#9ca3af',
    }
  }
  return {
    background: 'rgba(255, 255, 255, 0.95)',
    border: 'rgba(0, 0, 0, 0.15)',
    text: '#1e293b',
    muted: '#6b7280',
  }
}

/**
 * Keep the readout inside the chart.
 *
 * It flips to the other side of the cursor rather than being clamped at the
 * edge, because a box pinned against the right border covers the very bars a
 * reader is hovering at the end of the series, which is where they spend most
 * of their time.
 */
function placeTooltip(
  point: HoverPoint,
  box: { width: number; height: number },
  frame: { width: number; height: number }
): { left: number; top: number } {
  const margin = 16
  let left = point.x + margin
  if (left + box.width > frame.width) left = point.x - box.width - margin
  if (left < 0) left = margin
  let top = point.y - box.height / 2
  if (top < 0) top = 0
  if (top + box.height > frame.height) top = Math.max(0, frame.height - box.height)
  return { left, top }
}

export function StrategyChartShell({
  feed,
  symbol,
  exchange,
  interval,
  intervals,
  onIntervalChange,
  reloadKey,
  busy,
  onBusyChange,
  persistKey,
  readout,
  notices,
  legend,
  onReady,
  onData,
  tooltip,
  loading,
}: StrategyChartShellProps) {
  const paneRef = useRef<HTMLDivElement>(null)
  const plotRef = useRef<HTMLDivElement>(null)
  const boxRef = useRef<HTMLDivElement>(null)
  const [widget, setWidget] = useState<Widget | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [indicatorsOpen, setIndicatorsOpen] = useState(false)
  const [activeIndicators, setActiveIndicators] = useState<{ id: string; name: string }[]>([])
  const [hover, setHover] = useState<HoverPoint | null>(null)
  const [menuAt, setMenuAt] = useState<ChartMenuAnchor | null>(null)
  const [railVisible, setRailVisible] = useState(true)

  const mode = useThemeStore((s) => s.mode)
  const appMode = useThemeStore((s) => s.appMode)
  const palette = useMemo(() => tooltipPalette(mode, appMode), [mode, appMode])

  /**
   * Follow the crosshair.
   *
   * `chart.on` rather than `subscribeCrosshairMove`: the latter is a single
   * slot and the widget's own status line already holds it, so subscribing
   * that way would silently replace the OHLC readout at the bottom.
   */
  useEffect(() => {
    if (!widget) return
    return widget.chart.on('crosshair:move', (payload) => {
      const e = payload as CrosshairMoveEvent
      if (e.time === null || e.point === null) {
        setHover((prev) => (prev === null ? prev : null))
        return
      }
      const next = { time: e.time, x: e.point.x, y: e.point.y }
      setHover((prev) =>
        prev && prev.time === next.time && prev.x === next.x && prev.y === next.y ? prev : next
      )
    })
  }, [widget])

  const rows = hover && tooltip ? tooltip(hover.time) : null
  const showTooltip = hover !== null && rows !== null && rows.length > 0

  /**
   * Place the box after it has been laid out, so its own size is known.
   *
   * Measured every move rather than cached: the widest row decides the width,
   * and that changes as the numbers under the cursor do.
   */
  useLayoutEffect(() => {
    const box = boxRef.current
    const plot = plotRef.current
    if (!box || !plot || !hover || !showTooltip) return
    const { left, top } = placeTooltip(
      hover,
      { width: box.offsetWidth, height: box.offsetHeight },
      { width: plot.clientWidth, height: plot.clientHeight }
    )
    box.style.left = `${left}px`
    box.style.top = `${top}px`
  })

  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === paneRef.current)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  const toggleFullscreen = () => {
    const el = paneRef.current
    if (!el) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else {
      void el.requestFullscreen().catch(() => {
        showToast.error('Full screen is not available in this browser.')
      })
    }
  }

  /**
   * What is on the chart, read from the chart rather than tracked beside it.
   *
   * An indicator can also be removed from the Objects panel or restored with a
   * saved layout, and a list maintained here would only know about the ones the
   * picker added.
   */
  useEffect(() => {
    if (!widget) {
      setActiveIndicators([])
      return
    }
    const sync = () =>
      setActiveIndicators(widget.chart.indicators().map((i) => ({ id: i.id, name: i.name })))
    sync()
    return widget.objects.subscribe(sync)
  }, [widget])

  /**
   * The catalogue, read when the dialog opens rather than on mount.
   *
   * User modules in `strategies/indicators/` register during the chart's own
   * build, so a snapshot taken earlier would list the built-ins and none of
   * yours.
   */
  const catalog = useMemo<CatalogEntry[]>(() => {
    if (!indicatorsOpen) return []
    return registeredIndicators().map((d) => ({
      id: d.id,
      name: d.name,
      category: d.category ?? 'Other',
    }))
  }, [indicatorsOpen])

  const openIndicatorSettings = (instanceId: string) => {
    if (!widget) return
    const object = widget.objects
      .list()
      .find((o) => o.kind === 'indicator' && o.sourceId === instanceId)
    widget.objects.openSettings(object?.id ?? instanceId)
  }

  /**
   * Send the feed back to the network when the request behind it changed.
   *
   * Debounced, because a template pick or a batch leg edit rewrites the legs
   * several times in a few milliseconds and each one would otherwise be a
   * broker history call. `reload` rather than a rebuild, so the indicators and
   * drawings survive the refetch.
   *
   * The interval is not in here: it is a prop on the chart, so the widget
   * reloads on its own when it changes.
   */
  const reload = useRef<() => void>(() => {})
  reload.current = () => {
    if (!widget || widget.isDestroyed) return
    onBusyChange(true)
    void widget.reload().catch(() => {
      // The engine paints its own failed-load row with a Retry button, and
      // `onData` carries the message to the tab. Nothing to add here, but the
      // veil has to come down either way.
    })
  }

  /**
   * Show or hide the engine's drawing rail.
   *
   * `rail` is a create-time widget option, so the alternative to touching the
   * element is rebuilding the chart, which would throw away the drawings the
   * rail exists to make. Hidden rather than removed, so the tools, their
   * favourites and the armed tool all survive being put away.
   */
  useEffect(() => {
    const rail = widget?.root.querySelector<HTMLElement>('.oac-rail')
    if (!rail) return
    rail.style.display = railVisible ? '' : 'none'
  }, [widget, railVisible])

  /** The widget, and the request its bars were fetched for. */
  const applied = useRef<{ widget: Widget | null; key: string }>({ widget: null, key: '' })

  useEffect(() => {
    if (!widget) return
    // A widget given a feed loads once as it is built, so the key it was built
    // with is already on screen. Reloading for it too would make every first
    // view of the tab two broker calls rather than one.
    //
    // Nor is `busy` raised here. That first load starts inside the widget's own
    // construction and can finish before this effect has run, in which case the
    // `data` event that lowers the flag has already been and gone: the button
    // then reads Loading for as long as the tab is open, over a chart that is
    // finished. The engine shows its own progress row meanwhile, so there is
    // nothing to cover. Only a reload this component asked for raises it, where
    // both edges are in one place.
    if (applied.current.widget !== widget) {
      applied.current = { widget, key: reloadKey }
      return
    }
    if (applied.current.key === reloadKey) return
    applied.current = { widget, key: reloadKey }
    const handle = setTimeout(() => reload.current(), 300)
    return () => clearTimeout(handle)
  }, [reloadKey, widget])

  return (
    <div
      ref={paneRef}
      /*
       * Capture, not bubble. The engine listens for `contextmenu` on its own
       * canvas; stopping the event on the way down means the canvas never sees
       * it, so there is one menu rather than two on a single click. Only over
       * the canvas: a right-click on the drawing rail is the rail's business.
       */
      onContextMenuCapture={(event) => {
        if (!(event.target instanceof HTMLCanvasElement)) return
        event.preventDefault()
        event.stopPropagation()
        setMenuAt({ x: event.clientX, y: event.clientY })
      }}
      className={cn(
        'flex min-h-0 flex-col overflow-hidden rounded-xl border bg-card shadow-sm',
        fullscreen && 'h-full rounded-none border-0'
      )}
      style={fullscreen ? undefined : { height: PANE_HEIGHT }}
    >
      <div className="flex shrink-0 flex-wrap items-center gap-2 border-b px-2 py-1.5">
        <Select value={interval} onValueChange={onIntervalChange}>
          <SelectTrigger className="h-7 w-[92px] text-xs">
            <SelectValue placeholder="Interval" />
          </SelectTrigger>
          <SelectContent>
            {intervals.map((token) => (
              <SelectItem key={token} value={token}>
                {token}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          title="Indicators"
          disabled={!widget}
          onClick={() => setIndicatorsOpen(true)}
        >
          <BarChart3 className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Indicators</span>
          {activeIndicators.length > 0 ? (
            <span className="rounded bg-primary/15 px-1 font-medium text-[10px] text-primary">
              {activeIndicators.length}
            </span>
          ) : null}
        </Button>

        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1 px-2 text-xs"
          // The label is hidden below the small breakpoint, so the button needs
          // a name of its own or it is an unexplained icon on a phone.
          title="Refresh"
          onClick={() => reload.current()}
          disabled={busy || !widget}
        >
          <RefreshCw className={cn('h-3.5 w-3.5', busy && 'animate-spin')} />
          <span className="hidden sm:inline">{busy ? 'Loading' : 'Refresh'}</span>
        </Button>

        {readout ? <div className="ml-auto flex items-center">{readout}</div> : null}

        <div className={cn('flex items-center gap-0.5', !readout && 'ml-auto')}>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Chart settings"
            disabled={!widget}
            onClick={() => widget?.openSettings()}
          >
            <Settings2 className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title={fullscreen ? 'Exit full screen' : 'Full screen'}
            onClick={toggleFullscreen}
          >
            {fullscreen ? (
              <Minimize2 className="h-3.5 w-3.5" />
            ) : (
              <Maximize2 className="h-3.5 w-3.5" />
            )}
          </Button>
        </div>
      </div>

      {notices ? <div className="shrink-0 space-y-1 px-2 pt-1.5">{notices}</div> : null}

      <div ref={plotRef} className="relative flex min-h-0 flex-1 flex-col">
        <OpenAlgoChart
          feed={feed}
          symbol={symbol}
          exchange={exchange}
          interval={interval}
          chartType="line"
          persistKey={persistKey}
          topbar={false}
          loading={loading}
          onReady={(instance) => {
            setWidget(instance)
            onReady(instance)
          }}
          onData={(event) => {
            onBusyChange(false)
            onData?.(event)
          }}
          onIntervalRejected={(rejected) => {
            showToast.error(`The chart cannot draw ${rejected} candles. Pick another timeframe.`)
          }}
        />
        {showTooltip && hover ? (
          <div
            ref={boxRef}
            data-testid="chart-tooltip"
            /*
             * Transparent to the pointer, always. The engine takes pointer
             * capture on its canvas to pan, and a box under the cursor that
             * accepts events would swallow the drag the moment the crosshair
             * moved under it, which is every time.
             */
            className="pointer-events-none absolute z-20 whitespace-nowrap rounded-md px-3 py-2 text-xs"
            style={{
              background: palette.background,
              border: `1px solid ${palette.border}`,
              color: palette.text,
              fontFamily: 'ui-monospace, SFMono-Regular, monospace',
              lineHeight: 1.6,
            }}
          >
            {rows.map((row) => (
              <div key={row.label} className="flex justify-between gap-4">
                <span className="font-semibold" style={{ color: row.color }}>
                  {row.label}
                </span>
                <span className="font-semibold" style={{ color: row.color }}>
                  {row.value}
                </span>
              </div>
            ))}
            <div
              className="mt-1 flex justify-between gap-4 pt-1"
              style={{ borderTop: `1px solid ${palette.border}`, color: palette.muted }}
            >
              <span>{IST_DATE.format(hover.time * 1000)}</span>
              <span>{IST_TIME.format(hover.time * 1000)}</span>
            </div>
          </div>
        ) : null}
        {busy ? (
          <div className="pointer-events-none absolute inset-0 z-10 flex items-center justify-center bg-background/50">
            <div className="flex items-center gap-2 text-muted-foreground text-sm">
              <div className="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent" />
              Loading
            </div>
          </div>
        ) : null}
      </div>

      {legend ? <div className="shrink-0 border-t px-2 py-1.5">{legend}</div> : null}

      <ChartContextMenu
        widget={widget}
        at={menuAt}
        onClose={() => setMenuAt(null)}
        railVisible={railVisible}
        onToggleRail={() => setRailVisible((on) => !on)}
      />

      <IndicatorPickerDialog
        open={indicatorsOpen}
        catalog={catalog}
        active={activeIndicators}
        onAdd={(indicatorId) => widget?.chart.addIndicator(indicatorId)}
        onRemove={(instanceId) => widget?.chart.removeIndicator(instanceId)}
        onSettings={openIndicatorSettings}
        onClose={() => setIndicatorsOpen(false)}
      />
    </div>
  )
}
