/**
 * One chart pane on the Historify charts page.
 *
 * The pane owns its own instrument, timeframe and chart type, and renders the
 * shared read-only chart under a toolbar of its own. The toolbar exists rather
 * than using the engine's built-in top bar for two reasons that the built-in
 * one cannot cover: the symbol list has to be restricted to what has actually
 * been downloaded, carrying expiry and strike so an option contract is
 * identifiable; and the timeframe control has to compose an arbitrary interval,
 * which a fixed row of pills cannot express.
 *
 * Everything it can do is a read. There is no order path here, by construction
 * rather than by permission: see `OpenAlgoChart`.
 */

import {
  BarChart3,
  Camera,
  Layers,
  Maximize2,
  Minimize2,
  Redo2,
  Rewind,
  Search,
  Settings2,
  Shapes,
  Undo2,
} from 'lucide-react'
import type { DataFeed } from 'openalgo-charts'
import { registeredIndicators } from 'openalgo-charts'
import type { Widget } from 'openalgo-charts/widget'
import { captureName } from 'openalgo-charts/widget'
import { type ReactNode, useEffect, useMemo, useRef, useState } from 'react'
import { ChartContextMenu, type ChartMenuAnchor } from '@/components/chart/ChartContextMenu'
import { ChartReplayBar } from '@/components/chart/ChartReplayBar'
import { OpenAlgoChart } from '@/components/chart/OpenAlgoChart'
import { useChartReplay } from '@/components/chart/useChartReplay'
import {
  type CatalogEntry,
  IndicatorPickerDialog,
} from '@/components/trading/IndicatorPickerDialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import type { CatalogSymbol } from '@/lib/historify/catalog'
import {
  availableIntervals,
  CUSTOM_UNITS,
  composeInterval,
  type IntervalUnit,
  isIntervalAvailable,
  parseInterval,
  unavailableReason,
} from '@/lib/historify/intervals'
import { CHART_TYPE_GROUPS, CHART_TYPES, chartTypeIcon } from '@/lib/trading/chartTypes'
import { cn } from '@/lib/utils'
import { showToast } from '@/utils/toast'

export interface PaneState {
  symbol: string
  exchange: string
  interval: string
  chartType: string
}

export interface HistorifyChartPaneProps {
  paneId: string
  feed: DataFeed
  symbols: CatalogSymbol[]
  state: PaneState
  onChange: (next: Partial<PaneState>) => void
  focused: boolean
  onFocus: () => void
  /** True while the catalog is still being read. */
  loading: boolean
  /** localStorage namespace, so each pane keeps its own drawings and studies. */
  persistKey: string
  /**
   * Page-level controls, rendered beside this pane's Indicators button.
   *
   * They belong to the page rather than to a pane, so the page passes them in
   * and passes them to one pane only. The alternative is the full-width strip
   * this page used to carry, which spent a row of height on a handful of
   * controls. `/trading` folds its layout picker in the same way and for the
   * same reason.
   */
  pageControls?: ReactNode
}

export function HistorifyChartPane({
  paneId,
  feed,
  symbols,
  state,
  onChange,
  focused,
  onFocus,
  loading,
  persistKey,
  pageControls,
}: HistorifyChartPaneProps) {
  const paneRef = useRef<HTMLDivElement>(null)
  const widgetRef = useRef<Widget | null>(null)
  const [fullscreen, setFullscreen] = useState(false)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [intervalOpen, setIntervalOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [customValue, setCustomValue] = useState('25')
  const [customUnit, setCustomUnit] = useState<IntervalUnit>('m')
  const [emptyNotice, setEmptyNotice] = useState<string | null>(null)
  const [indicatorsOpen, setIndicatorsOpen] = useState(false)
  const [menuAt, setMenuAt] = useState<ChartMenuAnchor | null>(null)
  const [railVisible, setRailVisible] = useState(true)
  const [volumeVisible, setVolumeVisible] = useState(false)
  const [activeIndicators, setActiveIndicators] = useState<{ id: string; name: string }[]>([])

  const selected = useMemo(
    () => symbols.find((s) => s.symbol === state.symbol && s.exchange === state.exchange) ?? null,
    [symbols, state.symbol, state.exchange]
  )
  const stored = selected?.sources ?? new Set()
  const intervals = useMemo(() => availableIntervals(stored), [stored])

  /**
   * The newest candle the store holds for what this pane is drawing.
   *
   * A computed timeframe is aggregated from one of the two stored intervals,
   * so the horizon is that source's, not the selected token's. Without this
   * the chart opens on a window ending now and finds nothing, because the
   * newest stored candle is days old over any weekend.
   */
  const dataEndsAt = useMemo(() => {
    const source = parseInterval(state.interval)?.source
    return source ? selected?.lastBySource[source] : undefined
  }, [selected, state.interval])

  const matches = useMemo(() => {
    const needle = query.trim().toLowerCase()
    const rows = needle
      ? symbols.filter(
          (s) =>
            s.symbol.toLowerCase().includes(needle) ||
            s.exchange.toLowerCase().includes(needle) ||
            (s.name ?? '').toLowerCase().includes(needle)
        )
      : symbols
    // Capped because the catalog can hold an entire option chain and a list
    // that long is slower to read than typing two more characters.
    return rows.slice(0, 50)
  }, [symbols, query])

  /**
   * What is on this chart, read from the chart rather than tracked here.
   *
   * The picker needs the live list and the button needs its count, and both
   * have to survive an indicator removed from the Objects panel, hidden from
   * the legend, or restored with a saved layout. Subscribing to the chart's own
   * object inventory covers every one of those; a list maintained beside it
   * would only know about the picker.
   */
  const [widget, setWidget] = useState<Widget | null>(null)
  useEffect(() => {
    if (!widget) {
      setActiveIndicators([])
      return
    }
    // Read through `chart.indicators()` rather than off the snapshots, because
    // `onRemove` and `onSettings` need true instance ids.
    const sync = () =>
      setActiveIndicators(widget.chart.indicators().map((i) => ({ id: i.id, name: i.name })))
    sync()
    return widget.objects.subscribe(sync)
  }, [widget])

  /**
   * The registry, read when the dialog opens.
   *
   * Not on mount: user modules in `strategies/indicators/` register during the
   * chart's own build, so a catalogue captured earlier would list the 102
   * built-ins and none of yours.
   */
  const replay = useChartReplay(widget)

  /**
   * Whether the drawing history has anything in it.
   *
   * Polled rather than subscribed because `DrawingController` publishes no
   * history event, and a disabled-looking button that is actually live is
   * worse than a cheap interval. The rate is well under a frame.
   */
  const [history, setHistory] = useState({ undo: false, redo: false })
  useEffect(() => {
    if (!widget) {
      setHistory({ undo: false, redo: false })
      return
    }
    const read = () => {
      if (widget.isDestroyed) return
      setHistory({ undo: widget.draw.canUndo(), redo: widget.draw.canRedo() })
    }
    read()
    const timer = window.setInterval(read, 400)
    return () => window.clearInterval(timer)
  }, [widget])

  const catalog = useMemo<CatalogEntry[]>(() => {
    if (!indicatorsOpen) return []
    return registeredIndicators().map((d) => ({
      id: d.id,
      name: d.name,
      category: d.category ?? 'Other',
    }))
  }, [indicatorsOpen])

  /** Open the engine's settings form for one indicator instance. */
  const openIndicatorSettings = (instanceId: string) => {
    if (!widget) return
    const object = widget.objects
      .list()
      .find((o) => o.kind === 'indicator' && o.sourceId === instanceId)
    widget.objects.openSettings(object?.id ?? instanceId)
  }

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
        showToast.error('Full screen is not available in this browser.', 'historify')
      })
    }
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

  /** Menus portal into the pane while it is fullscreen, or they open unseen. */
  const menuHost = fullscreen ? paneRef.current : null

  const pickSymbol = (row: CatalogSymbol) => {
    setPickerOpen(false)
    setQuery('')
    // Carry the timeframe over when the new symbol can serve it, otherwise
    // land on one it actually has rather than an empty chart.
    const interval = isIntervalAvailable(state.interval, row.sources)
      ? state.interval
      : (availableIntervals(row.sources)[0] ?? state.interval)
    onChange({ symbol: row.symbol, exchange: row.exchange, interval })
  }

  const pickInterval = (token: string) => {
    setIntervalOpen(false)
    const reason = unavailableReason(token, stored)
    if (reason) {
      showToast.error(reason, 'historify')
      return
    }
    onChange({ interval: token })
  }

  const applyCustomInterval = () => {
    const token = composeInterval(customValue, customUnit)
    if (!token) {
      showToast.error('Enter a whole number of periods, for example 25 minutes.', 'historify')
      return
    }
    pickInterval(token)
  }

  /**
   * Copy the chart to the clipboard as a PNG.
   *
   * Uses the engine's composite rather than grabbing a canvas: the chart draws
   * across several layers and a raw grab catches whichever one is on top,
   * which is usually the transparent crosshair overlay.
   */
  const copyChartImage = async () => {
    const instance = widgetRef.current
    if (!instance) return
    try {
      const canvas = instance.chart.takeScreenshot()
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'))
      if (!blob) throw new Error('no image')
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      showToast.success('Chart copied to the clipboard.', 'historify')
    } catch {
      // Clipboard images need a secure context and permission, and neither is
      // something the reader can infer from a failure.
      showToast.error(
        'The chart could not be copied. Your browser only allows this over a secure connection, so use Download image instead.',
        'historify'
      )
    }
  }

  const downloadChartImage = () => {
    const instance = widgetRef.current
    if (!instance) return
    instance.chart.downloadScreenshot(`${captureName(instance.symbol(), instance.interval())}.png`)
  }

  const chartType = CHART_TYPES[state.chartType] ?? CHART_TYPES.candlestick

  return (
    <div
      ref={paneRef}
      onPointerDownCapture={onFocus}
      /*
       * Capture, not bubble. The engine listens for `contextmenu` on its own
       * canvas; stopping the event on the way down means the canvas never sees
       * it, so the widget's short menu never opens and there is one menu rather
       * than two on a single click. Only over the canvas: a right-click on the
       * drawing rail is the rail's business.
       */
      onContextMenuCapture={(event) => {
        if (!(event.target instanceof HTMLCanvasElement)) return
        event.preventDefault()
        event.stopPropagation()
        setMenuAt({ x: event.clientX, y: event.clientY })
      }}
      className={cn(
        'relative flex h-full min-h-0 flex-1 flex-col overflow-hidden rounded-lg border bg-card',
        focused ? 'border-primary/60' : 'border-border'
      )}
    >
      <div className="flex h-10 shrink-0 items-center gap-1 border-b px-2">
        <Popover open={pickerOpen} onOpenChange={setPickerOpen}>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="sm" className="h-7 gap-1 px-2 font-semibold">
              <Search className="h-3.5 w-3.5 text-muted-foreground" />
              {state.symbol ? (
                <>
                  <span className="truncate">{state.symbol}</span>
                  <Badge variant="secondary" className="px-1 py-0 text-[10px]">
                    {state.exchange}
                  </Badge>
                </>
              ) : (
                <span className="text-muted-foreground">Select symbol</span>
              )}
            </Button>
          </PopoverTrigger>
          <PopoverContent container={menuHost} align="start" className="w-80 p-0">
            <Command shouldFilter={false}>
              <CommandInput
                placeholder="Search downloaded symbols"
                value={query}
                onValueChange={setQuery}
              />
              <CommandList>
                <CommandEmpty>
                  {symbols.length === 0
                    ? 'Nothing has been downloaded yet. Download a symbol from Historify to chart it.'
                    : 'No downloaded symbol matches that. Only symbols already in your local data appear here.'}
                </CommandEmpty>
                <CommandGroup>
                  {matches.map((row) => (
                    <CommandItem
                      key={`${row.symbol}:${row.exchange}`}
                      value={`${row.symbol}:${row.exchange}`}
                      onSelect={() => pickSymbol(row)}
                      className="flex items-center justify-between gap-2"
                    >
                      <div className="min-w-0">
                        <div className="truncate font-medium">{row.symbol}</div>
                        {row.name ? (
                          <div className="truncate text-muted-foreground text-xs">{row.name}</div>
                        ) : null}
                      </div>
                      <div className="flex shrink-0 items-center gap-1">
                        <Badge variant="outline" className="px-1 py-0 text-[10px]">
                          {row.exchange}
                        </Badge>
                        <span className="text-[10px] text-muted-foreground">
                          {[...row.sources].join(' ')}
                        </span>
                      </div>
                    </CommandItem>
                  ))}
                </CommandGroup>
              </CommandList>
            </Command>
          </PopoverContent>
        </Popover>

        <Popover open={intervalOpen} onOpenChange={setIntervalOpen}>
          <PopoverTrigger asChild>
            <Button variant="ghost" size="sm" className="h-7 px-2 font-medium text-xs">
              {state.interval}
            </Button>
          </PopoverTrigger>
          <PopoverContent container={menuHost} align="start" className="w-64 p-2">
            {intervals.length === 0 ? (
              <p className="p-1 text-muted-foreground text-xs">
                This symbol has no downloaded data yet. Download it from Historify first.
              </p>
            ) : (
              <div className="grid grid-cols-5 gap-1">
                {intervals.map((token) => (
                  <Button
                    key={token}
                    variant={token === state.interval ? 'default' : 'ghost'}
                    size="sm"
                    className="h-7 px-0 text-xs"
                    onClick={() => pickInterval(token)}
                  >
                    {token}
                  </Button>
                ))}
              </div>
            )}
            <div className="mt-2 border-t pt-2">
              <p className="mb-1 text-[11px] text-muted-foreground">Custom interval</p>
              <div className="flex items-center gap-1">
                <Input
                  type="number"
                  min="1"
                  max="999"
                  value={customValue}
                  onChange={(e) => setCustomValue(e.target.value)}
                  className="h-7 w-16 text-center"
                />
                <select
                  value={customUnit}
                  onChange={(e) => setCustomUnit(e.target.value as IntervalUnit)}
                  className="h-7 rounded-md border bg-background px-2 text-xs"
                  aria-label="Custom interval unit"
                >
                  {CUSTOM_UNITS.map((unit) => (
                    <option key={unit.value} value={unit.value}>
                      {unit.label}
                    </option>
                  ))}
                </select>
                <Button size="sm" className="h-7 px-2 text-xs" onClick={applyCustomInterval}>
                  Apply
                </Button>
              </div>
            </div>
          </PopoverContent>
        </Popover>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7" title={chartType.label}>
              {chartTypeIcon(chartType.iconKey)}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent container={menuHost} align="start" className="w-52">
            {CHART_TYPE_GROUPS.map((group, index) => (
              <div key={group[0].value}>
                {index > 0 ? <DropdownMenuSeparator /> : null}
                {group.map((def) => (
                  <DropdownMenuItem
                    key={def.value}
                    onSelect={() => onChange({ chartType: def.value })}
                    className={cn('gap-2', def.value === state.chartType && 'text-primary')}
                  >
                    {chartTypeIcon(def.iconKey)}
                    <span>{def.label}</span>
                  </DropdownMenuItem>
                ))}
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Indicators sits with the timeframe and chart type rather than with
            the pane's own controls, because it belongs to what is being drawn
            rather than to the pane, which is where /trading puts it too. */}
        <Button
          variant="outline"
          size="sm"
          className="h-7 shrink-0 gap-1 px-2 text-xs"
          title="Indicators"
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

        {pageControls}

        {/* Replay. A toolbar action rather than a context-menu entry: it
            changes what the whole chart is showing, and the transport it opens
            has to be discoverable without a right-click. */}
        <Button
          variant="outline"
          size="sm"
          className={cn(
            'h-7 shrink-0 gap-1 px-2 text-xs',
            replay.mode !== 'off' && 'border-primary text-primary'
          )}
          title="Bar replay"
          onClick={() => (replay.mode === 'off' ? replay.arm() : replay.exit())}
        >
          <Rewind className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Replay</span>
        </Button>

        <div className="mx-1 h-4 w-px shrink-0 bg-border" />

        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          title="Undo drawing"
          disabled={!history.undo}
          onClick={() => widget?.draw.undo()}
        >
          <Undo2 className="h-3.5 w-3.5" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 shrink-0"
          title="Redo drawing"
          disabled={!history.redo}
          onClick={() => widget?.draw.redo()}
        >
          <Redo2 className="h-3.5 w-3.5" />
        </Button>

        <div className="ml-auto flex items-center gap-0.5">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" className="h-7 w-7" title="Chart image">
                <Camera className="h-3.5 w-3.5" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent container={menuHost} align="end" className="w-48">
              <DropdownMenuItem onSelect={() => void copyChartImage()}>
                Copy to clipboard
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={downloadChartImage}>Download image</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Objects"
            onClick={() => widgetRef.current?.openObjects()}
          >
            <Shapes className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            title="Chart settings"
            onClick={() => widgetRef.current?.openSettings()}
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

      {state.symbol && selected ? (
        <OpenAlgoChart
          feed={feed}
          dataEndsAt={dataEndsAt}
          volume={volumeVisible}
          symbol={state.symbol}
          exchange={state.exchange}
          interval={state.interval}
          chartType={state.chartType}
          persistKey={persistKey}
          topbar={false}
          onReady={(instance) => {
            widgetRef.current = instance
            setWidget(instance)
          }}
          onIntervalRejected={(rejected) => {
            showToast.error(
              `The chart cannot draw ${rejected} candles. Pick another timeframe.`,
              'historify'
            )
          }}
          onData={(event) => {
            if (event.error) {
              setEmptyNotice(
                'That data could not be read from your local store. Try the symbol again, and re-download it from Historify if this keeps happening.'
              )
              return
            }
            setEmptyNotice(
              event.bars === 0
                ? (unavailableReason(event.interval, stored) ??
                    'No candles are stored for this symbol at this timeframe yet. Download the range you want from Historify.')
                : null
            )
          }}
        />
      ) : state.symbol && loading ? (
        <div className="flex min-h-0 flex-1 items-center justify-center p-4">
          <p className="text-muted-foreground text-xs">Reading your local data</p>
        </div>
      ) : state.symbol ? (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-4 text-center">
          <Layers className="h-8 w-8 text-muted-foreground/60" />
          <p className="font-medium text-sm">{state.symbol} is not in your local data</p>
          <p className="max-w-xs text-muted-foreground text-xs">
            Download it from Historify on {state.exchange}, or pick a symbol you already hold.
          </p>
        </div>
      ) : (
        <div className="flex min-h-0 flex-1 flex-col items-center justify-center gap-2 p-4 text-center">
          <Layers className="h-8 w-8 text-muted-foreground/60" />
          <p className="font-medium text-sm">Pick a symbol to chart</p>
          <p className="max-w-xs text-muted-foreground text-xs">
            {symbols.length === 0
              ? 'Nothing has been downloaded yet. Download a symbol from Historify and it will appear here.'
              : 'Only symbols in your local data are listed, so every chart here is data you already hold.'}
          </p>
        </div>
      )}

      {emptyNotice && state.symbol ? (
        <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 flex justify-center p-3">
          <p className="pointer-events-auto max-w-md rounded-md border bg-card/95 px-3 py-2 text-center text-muted-foreground text-xs shadow-sm">
            {emptyNotice}
          </p>
        </div>
      ) : null}
      <ChartContextMenu
        widget={widget}
        at={menuAt}
        onClose={() => setMenuAt(null)}
        railVisible={railVisible}
        onToggleRail={() => setRailVisible((on) => !on)}
        volumeVisible={volumeVisible}
        onToggleVolume={() => setVolumeVisible((on) => !on)}
      />

      <ChartReplayBar replay={replay} />

      {/* The same browser /trading uses, rather than the engine's own list:
          the catalogue is long enough that categories, starred entries and
          recents are the difference between finding a study and scrolling for
          it. Favourites and recents are keyed globally inside the dialog, so
          what you reach for follows you between the two pages. */}
      <IndicatorPickerDialog
        open={indicatorsOpen}
        catalog={catalog}
        active={activeIndicators}
        onAdd={(indicatorId) => widget?.chart.addIndicator(indicatorId)}
        onRemove={(instanceId) => widget?.chart.removeIndicator(instanceId)}
        onSettings={openIndicatorSettings}
        onClose={() => setIndicatorsOpen(false)}
      />
      <span className="sr-only">{paneId}</span>
    </div>
  )
}
