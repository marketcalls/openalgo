import { ChevronDown, RefreshCw, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { CHART_TYPE_GROUPS, CHART_TYPES, chartTypeIcon } from '@/lib/trading/chartTypes'
import type { IntervalGroup } from '@/lib/trading/intervals'
import {
  type CtxItem,
  type DrawSelection,
  type DrawStats,
  type IndicatorSettingsRequest,
  type SymbolView,
  type TerminalCallbacks,
  TradingTerminal,
} from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'
import { DrawingStyleBar } from './DrawingStyleBar'
import { DrawingTextDialog, type TextRequest } from './DrawingTextDialog'
import { IndicatorSettingsDialog } from './IndicatorSettingsDialog'
import { SymbolSearchDialog } from './SymbolSearchDialog'

/** Camera (screenshot) glyph. */
function CameraIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      className={className}
      aria-hidden="true"
    >
      <path d="M4 8.5h3l1.2-2h7.6L18 8.5h2A1.5 1.5 0 0 1 21.5 10v8A1.5 1.5 0 0 1 20 19.5H4A1.5 1.5 0 0 1 2.5 18v-8A1.5 1.5 0 0 1 4 8.5Z" />
      <circle cx="12" cy="13.5" r="3.2" />
    </svg>
  )
}

const glyph = {
  fill: 'none' as const,
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round' as const,
  strokeLinejoin: 'round' as const,
}

function IndicatorIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M3 16.5l4-7 3.5 3.5L14 5l3.5 5.5L21 8" />
    </svg>
  )
}

function PencilIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M4 20.5h4L20 8.5a2.4 2.4 0 0 0-3.4-3.4L4.5 17z" />
      <path d="M15.5 6.5 18.5 9.5" />
    </svg>
  )
}

/** Three rising bars — the volume histogram in miniature. */
function VolumeIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="none" stroke="currentColor" strokeWidth={1.8} strokeLinecap="round" aria-hidden="true">
      <path d="M5 20v-6M12 20V8M19 20v-9" />
    </svg>
  )
}

function GridIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M3 9h18M3 15h18M9 3v18M15 3v18" />
    </svg>
  )
}

function FullscreenIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M13 4h7v7M11 20H4v-7M20 4l-7 7M4 20l7-7" />
    </svg>
  )
}

function ledClass(state: string): string {
  if (state === 'live' || state === 'open')
    return 'bg-emerald-500 shadow-[0_0_6px] shadow-emerald-500/70'
  if (state === 'closed' || state === 'error' || state === 'auth failed') return 'bg-rose-500'
  return 'bg-amber-500'
}

function lotInfoText(v: SymbolView | null, qty: number): string {
  if (!v) return ''
  if (v.lots) {
    const lots = Math.max(1, Math.floor(qty || 1))
    let t = `${lots} × ${v.lotsize} = ${lots * v.lotsize} qty`
    if (v.freezeQty > 1 && lots * v.lotsize > v.freezeQty) t += ` ⚠ freeze ${v.freezeQty}`
    return t
  }
  return v.quoteOnly ? 'quote-only (no trading)' : ''
}

interface Props {
  /** Stable pane id — namespaces the pane's persisted symbol/interval/type. */
  paneId: string
  apiKey: string
  wsUrl: string
  /** Grid placement (e.g. `{ gridArea }`) applied to the pane's root. */
  style?: React.CSSProperties
  /**
   * Tool armed by the page-level drawing rail. One rail serves every pane, so
   * each arms the same tool and whichever pane you draw in gets the shape.
   */
  sharedTool?: string | null
  sharedMagnet?: boolean
  /** This pane became the drawing target (pointer went down inside it). */
  onFocusPane?(terminal: TradingTerminal | null): void
  /** Drawing state of this pane, for the shared rail's buttons. */
  onDrawStats?(stats: DrawStats): void
  /** Show/hide the page-level rail — the action lives in each pane's menu. */
  onToggleRail?(): void
  railVisible?: boolean
}

/**
 * One independent charting terminal in the grid: its own toolbar (symbol search,
 * timeframe, chart type, product, qty), its own openalgo-charts instance + feeds
 * (via `TradingTerminal`), and its own on-chart order/position lines.
 */
export function ChartPane({
  paneId,
  apiKey,
  wsUrl,
  style,
  sharedTool,
  sharedMagnet,
  onFocusPane,
  onDrawStats,
  onToggleRail,
  railVisible,
}: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const legendRef = useRef<HTMLDivElement>(null)
  /**
   * The whole pane — what "full screen chart" expands. Fullscreening only the
   * plot would take the toolbar off screen with it, and the drawing rail's
   * flyouts are portalled, so they need a container inside the same element.
   */
  const paneRef = useRef<HTMLElement>(null)
  const terminalRef = useRef<TradingTerminal | null>(null)
  const aliveRef = useRef(true)
  const statsCbRef = useRef(onDrawStats)
  statsCbRef.current = onDrawStats
  const { mode, appMode } = useThemeStore()

  const [ready, setReady] = useState(false)
  const [intervalGroups, setIntervalGroups] = useState<IntervalGroup[]>([])
  const [interval, setIntervalState] = useState('5m')
  const [chartType, setChartTypeState] = useState('candlestick')
  const [sym, setSym] = useState<SymbolView | null>(null)
  const [qty, setQty] = useState(1)
  const [wsState, setWsState] = useState('connecting')

  // symbol search modal (per-pane; opened from the toolbar symbol pill)
  const [searchOpen, setSearchOpen] = useState(false)

  // drawing + indicator controls (additive; the trading controls are unchanged)
  const [indicators, setIndicators] = useState<{ id: string; name: string }[]>([])
  const [catalog, setCatalog] = useState<{ id: string; name: string; category: string }[]>([])
  const [grid, setGrid] = useState({ vertical: true, horizontal: true })
  const [fullscreen, setFullscreen] = useState(false)
  const [gridSub, setGridSub] = useState(false)
  const [volumeOn, setVolumeOn] = useState(true)
  const [drawSel, setDrawSel] = useState<DrawSelection | null>(null)
  const [indSettings, setIndSettings] = useState<IndicatorSettingsRequest | null>(null)
  const [textReq, setTextReq] = useState<TextRequest | null>(null)

  // right-click menu: order entry, then the view actions
  const [ctx, setCtx] = useState<{ x: number; y: number; items: CtxItem[] } | null>(null)

  /* ── boot this pane's terminal once ───────────────────────────────────── */
  useEffect(() => {
    aliveRef.current = true
    let terminal: TradingTerminal | null = null

    const callbacks: TerminalCallbacks = {
      onReady: ({ intervalGroups: g, interval: iv, chartType: ct }) => {
        if (!aliveRef.current) return
        setIntervalGroups(g)
        setIntervalState(iv)
        setChartTypeState(ct)
        setReady(true)
      },
      onToast: (msg, kind) => {
        if (kind === 'ok') showToast.success(msg)
        else if (kind === 'err') showToast.error(msg)
        else showToast.info(msg)
      },
      onWsState: (s) => aliveRef.current && setWsState(s),
      onSymbolLoaded: (view) => {
        if (!aliveRef.current) return
        setSym(view)
        setQty(1)
      },
      onLtp: () => {}, // legend overlay + canvas render the live price
      onDrawChange: (s) => {
        if (!aliveRef.current) return
        statsCbRef.current?.(s)
      },
      onIndicatorsChange: (list) => aliveRef.current && setIndicators(list),
      onIndicatorSettings: (req) => aliveRef.current && setIndSettings(req),
      onDrawSelect: (sel) => aliveRef.current && setDrawSel(sel),
      onDrawTextEdit: (r) => {
        if (!aliveRef.current) return
        // The ref, not the local: `terminal` is still unassigned while this
        // object literal is being built. Callbacks only fire after construction.
        const style = terminalRef.current?.drawTextStyle(r.id)
        if (style) setTextReq({ id: r.id, tool: r.tool, style })
      },
    }

    if (chartRef.current && legendRef.current) {
      terminal = new TradingTerminal({
        apiKey,
        wsUrl,
        container: chartRef.current,
        legendEl: legendRef.current,
        storageKey: `oa-trading-${paneId}`,
        getTheme: () => {
          const s = useThemeStore.getState()
          return { mode: s.mode, appMode: s.appMode }
        },
        callbacks,
      })
      terminalRef.current = terminal
      terminal.init()
      statsCbRef.current?.(terminal.drawStats())
      setGrid(terminal.gridState())
      setVolumeOn(terminal.volumeVisible())
    }

    return () => {
      aliveRef.current = false
      terminal?.destroy()
      terminalRef.current = null
    }
  }, [paneId, apiKey, wsUrl])

  /* ── follow the page-level drawing rail ───────────────────────────────── */
  useEffect(() => {
    if (sharedTool === undefined) return
    void terminalRef.current?.setDrawTool(sharedTool)
  }, [sharedTool])
  useEffect(() => {
    if (sharedMagnet === undefined) return
    terminalRef.current?.setMagnet(sharedMagnet)
  }, [sharedMagnet])

  /* ── keep the canvas theme in sync with the app theme ─────────────────── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: mode/appMode are the trigger — the effect re-themes the canvas whenever the app theme changes
  useEffect(() => {
    terminalRef.current?.applyTheme()
  }, [mode, appMode])

  /* ── toolbar actions ──────────────────────────────────────────────────── */
  const changeInterval = (iv: string) => {
    setIntervalState(iv)
    terminalRef.current?.setInterval(iv)
  }
  const changeChartType = (v: string) => {
    setChartTypeState(v)
    terminalRef.current?.setChartType(v)
  }
  const changeProduct = (p: string) => {
    if (!sym) return
    setSym({ ...sym, product: p })
    terminalRef.current?.setProduct(p)
  }
  const changeQty = (n: number) => {
    const v = Math.max(1, Math.floor(n || 1))
    setQty(v)
    terminalRef.current?.setQty(v)
  }

  /* ── right-click order menu ───────────────────────────────────────────── */
  const onContextMenu = (e: React.MouseEvent) => {
    const t = terminalRef.current
    if (!t || !chartRef.current) return
    const rect = chartRef.current.getBoundingClientRect()
    // Order rows need a tradeable instrument; the view actions below them do
    // not, so a quote-only index still gets the menu, just without them.
    const res = t.contextMenuAt(e.clientY - rect.top)
    e.preventDefault()
    setGridSub(false)
    setCtx({
      x: Math.min(e.clientX, window.innerWidth - 240),
      y: Math.min(e.clientY, window.innerHeight - 360),
      items: res ? res.items : [],
    })
  }
  useEffect(() => {
    if (!ctx) return
    const close = () => {
      setGridSub(false)
      setCtx(null)
    }
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [ctx])

  /* ── drawing / indicator / view actions (additive) ────────────────────── */
  const openIndicators = async () => {
    const t = terminalRef.current
    if (!t || catalog.length) return
    try {
      setCatalog(await t.indicatorCatalog())
    } catch {
      showToast.error('could not load the indicator catalogue')
    }
  }
  const toggleGrid = (which: 'vertical' | 'horizontal' | 'both' | 'none') => {
    const next =
      which === 'both'
        ? { vertical: true, horizontal: true }
        : which === 'none'
          ? { vertical: false, horizontal: false }
          : which === 'vertical'
            ? { vertical: true, horizontal: false }
            : { vertical: false, horizontal: true }
    setGrid(next)
    terminalRef.current?.setGrid(next.vertical, next.horizontal)
  }
  const toggleFullscreen = () => {
    const el = paneRef.current
    if (!el) return
    if (document.fullscreenElement) void document.exitFullscreen()
    else void el.requestFullscreen().catch(() => showToast.error('full screen unavailable'))
  }
  // The chart's ResizeObserver handles the geometry; this tracks the flag so the
  // button reflects state (including Esc-to-exit) and so every menu in the pane
  // can be portalled inside the fullscreen element while it is active.
  useEffect(() => {
    const sync = () => setFullscreen(document.fullscreenElement === paneRef.current)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])
  // Menu is w-56 (224) and the submenu w-36 (144); opening right needs both
  // plus the gap, so near the right edge it opens left instead.
  const gridSubLeft = ctx !== null && ctx.x + 224 + 4 + 144 > window.innerWidth

  /** One row of the right-click menu. */
  const ctxRow =
    'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm hover:bg-accent hover:text-accent-foreground'
  /** Run a menu action and dismiss the menu. */
  const run = (fn: () => void) => {
    fn()
    setGridSub(false)
    setCtx(null)
  }

  /** Portal target for menus: the pane itself in fullscreen, body otherwise. */
  const menuHost = fullscreen ? paneRef.current : null

  const catalogGroups = catalog.reduce<Record<string, typeof catalog>>((acc, d) => {
    const list = acc[d.category] ?? []
    list.push(d)
    acc[d.category] = list
    return acc
  }, {})

  // The product the toggle switches to; with two options that is "the other".
  const nextProduct = sym
    ? sym.productOptions[(sym.productOptions.indexOf(sym.product) + 1) % sym.productOptions.length]
    : ''

  const chartTypeDef = CHART_TYPES[chartType] ?? CHART_TYPES.candlestick

  return (
    <section
      ref={paneRef}
      style={style}
      className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card"
    >
      {/* Per-pane control row. One line: the row scrolls rather than wrapping,
          so the view actions stay beside the instrument controls instead of
          dropping to a second row and eating chart height. */}
      <div className="flex flex-nowrap items-center gap-1.5 no-scrollbar overflow-x-auto border-b bg-background/60 px-2 py-1.5">
        {/* Symbol pill — opens the search modal for this pane */}
        <Button
          variant="outline"
          size="sm"
          className="h-8 shrink-0 gap-2 font-medium"
          onClick={() => setSearchOpen(true)}
          title="Search symbol"
        >
          <Search className="h-3.5 w-3.5 opacity-60" />
          <span className="max-w-[10rem] truncate">{sym?.symbol ?? 'Search symbol'}</span>
          {sym && (
            <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
              {sym.exchange}
            </span>
          )}
        </Button>

        {/* Timeframe */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 min-w-12 shrink-0 gap-1 font-medium">
              {interval || '—'}
              <ChevronDown className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent container={menuHost} align="start" className="w-64">
            {intervalGroups.map((g) => (
              <div key={g.label} className="px-1 pb-1">
                <div className="px-1 py-1 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  {g.label}
                </div>
                <div className="grid grid-cols-4 gap-1">
                  {g.items.map((iv) => (
                    <DropdownMenuItem
                      key={iv}
                      onSelect={() => changeInterval(iv)}
                      className={cn(
                        'justify-center rounded border text-xs',
                        iv === interval && 'border-primary bg-primary/10 text-primary'
                      )}
                    >
                      {iv}
                    </DropdownMenuItem>
                  ))}
                </div>
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Chart type */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 shrink-0 gap-1" title={chartTypeDef.label}>
              <span className="h-4 w-4">{chartTypeIcon(chartTypeDef.iconKey)}</span>
              <ChevronDown className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent container={menuHost} align="start" className="w-52">
            {CHART_TYPE_GROUPS.map((group, gi) => (
              <div key={group[0].value}>
                {gi > 0 && <DropdownMenuSeparator />}
                {group.map((d) => (
                  <DropdownMenuItem
                    key={d.value}
                    onSelect={() => changeChartType(d.value)}
                    className={cn('gap-2 text-sm', d.value === chartType && 'text-primary')}
                  >
                    <span className="h-4 w-4">{chartTypeIcon(d.iconKey)}</span>
                    {d.label}
                  </DropdownMenuItem>
                ))}
              </div>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Product. Always exactly two options (MIS|CNC for equity, MIS|NRML
            for derivatives), so a segmented control spends double the width to
            show one you are not using — this toggles and names the other. */}
        {sym && !sym.quoteOnly && sym.productOptions.length > 0 && (
          <button
            type="button"
            onClick={() => changeProduct(nextProduct)}
            title={`Product ${sym.product} — click for ${nextProduct}`}
            aria-label={`Product ${sym.product}, click for ${nextProduct}`}
            className="h-8 shrink-0 whitespace-nowrap rounded-md bg-primary px-2.5 text-xs font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            {sym.product}
          </button>
        )}

        {/* Quantity */}
        <div className="flex shrink-0 items-center gap-1">
          <label className="whitespace-nowrap text-[11px] text-muted-foreground" htmlFor={`qty-${paneId}`}>
            {sym?.lots ? 'Lots' : 'Qty'}
          </label>
          <Input
            id={`qty-${paneId}`}
            type="number"
            min={1}
            value={qty}
            onChange={(e) => changeQty(Number(e.target.value))}
            className="h-8 w-16 text-sm"
          />
        </div>

        {/* Indicators (additive) */}
        <DropdownMenu onOpenChange={(o) => o && void openIndicators()}>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 shrink-0 gap-1" title="Indicators">
              <IndicatorIcon className="h-4 w-4" />
              <span className="hidden sm:inline">Indicators</span>
              {indicators.length > 0 && (
                <span className="rounded bg-primary/15 px-1 text-[10px] font-medium text-primary">
                  {indicators.length}
                </span>
              )}
              <ChevronDown className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent container={menuHost} align="start" className="max-h-80 w-64 overflow-y-auto">
            {indicators.length > 0 && (
              <>
                <div className="px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  On this chart
                </div>
                {indicators.map((i) => (
                  <DropdownMenuItem
                    key={i.id}
                    onSelect={(e) => {
                      // Settings and remove on one row; the gear must not fall
                      // through to the row's remove action.
                      const target = e.target as HTMLElement
                      if (target.closest('[data-act="settings"]')) {
                        e.preventDefault()
                        terminalRef.current?.openIndicatorSettings(i.id)
                        return
                      }
                      terminalRef.current?.removeIndicatorById(i.id)
                    }}
                    className="justify-between gap-2 text-sm"
                  >
                    {i.name}
                    <span className="flex items-center gap-2">
                      <span data-act="settings" className="text-xs text-primary hover:underline">
                        settings
                      </span>
                      <span className="text-xs text-muted-foreground">remove</span>
                    </span>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </>
            )}
            {Object.entries(catalogGroups).map(([cat, list]) => (
              <div key={cat}>
                <div className="px-2 pb-1 pt-2 text-[10px] font-medium uppercase tracking-wider text-muted-foreground">
                  {cat}
                </div>
                {list.map((d) => (
                  <DropdownMenuItem
                    key={d.id}
                    onSelect={() => void terminalRef.current?.addIndicatorById(d.id)}
                    className="text-sm"
                  >
                    {d.name}
                  </DropdownMenuItem>
                ))}
              </div>
            ))}
            {catalog.length === 0 && (
              <div className="px-2 py-3 text-sm text-muted-foreground">Loading…</div>
            )}
          </DropdownMenuContent>
        </DropdownMenu>

        {/* Right side: connection LED + actions */}
        <div className="ml-auto flex shrink-0 items-center gap-1.5">
          <span
            className={cn('inline-block h-2.5 w-2.5 rounded-full', ledClass(wsState))}
            title={`WebSocket ${wsState}`}
          />
          {/* Full screen chart (additive) */}
          <Button
            variant="ghost"
            size="icon"
            className={cn('h-8 w-8', fullscreen && 'text-primary')}
            onClick={toggleFullscreen}
            title={fullscreen ? 'Exit full screen (Esc)' : 'Full screen chart'}
            aria-label="Toggle full screen chart"
          >
            <FullscreenIcon className="h-[17px] w-[17px]" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => terminalRef.current?.screenshot()}
            title="Save chart screenshot"
            aria-label="Save chart screenshot"
          >
            <CameraIcon className="h-[17px] w-[17px]" />
          </Button>
        </div>
      </div>

      {/* Chart area */}
      <div className="relative min-h-0 flex-1 bg-card">
        <DrawingStyleBar
          sel={drawSel}
          onStyle={(patch) => terminalRef.current?.styleSelectedDrawing(patch)}
          onDelete={() => terminalRef.current?.removeDrawings(false)}
          onEditText={() => drawSel && terminalRef.current?.requestDrawTextEdit(drawSel.id)}
        />
        <DrawingTextDialog
          req={textReq}
          onSubmit={(id, value) => terminalRef.current?.applyDrawText(id, value)}
          onClose={() => setTextReq(null)}
        />
        <IndicatorSettingsDialog
          req={indSettings}
          onApply={(id, patch) => terminalRef.current?.updateIndicatorSettings(id, patch)}
          onDefaults={(id) =>
            terminalRef.current
              ? terminalRef.current.indicatorDefaultsFor(id)
              : Promise.resolve(null)
          }
          onClose={() => setIndSettings(null)}
        />
        <div className="pointer-events-none absolute left-3 top-1.5 z-10 flex flex-col gap-0.5">
          <div ref={legendRef} className="text-xs font-medium text-foreground" />
          {sym && lotInfoText(sym, qty) && (
            <span className="text-[10px] text-muted-foreground">{lotInfoText(sym, qty)}</span>
          )}
        </div>
        <div
          ref={chartRef}
          className="absolute inset-0"
          onContextMenu={onContextMenu}
          onPointerDownCapture={() => onFocusPane?.(terminalRef.current)}
        />

        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            Loading…
          </div>
        )}

        {ctx && (
          <div
            className="fixed z-50 w-56 rounded-md border bg-popover p-1 shadow-lg"
            style={{ left: ctx.x, top: ctx.y }}
          >
            {ctx.items.map((it) => (
              <button
                type="button"
                key={`${it.side}:${it.type}`}
                disabled={!it.enabled}
                onClick={() => {
                  terminalRef.current?.placeCtx(it.side, it.type)
                  setCtx(null)
                }}
                className={cn(
                  'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm',
                  it.enabled
                    ? 'hover:bg-accent hover:text-accent-foreground'
                    : 'cursor-not-allowed opacity-40',
                  it.side === 'BUY'
                    ? 'text-emerald-600 dark:text-emerald-400'
                    : 'text-rose-600 dark:text-rose-400'
                )}
              >
                {it.label}
              </button>
            ))}

            {/* View actions live here rather than in the toolbar — they are
                occasional, and the row they used to occupy is chart height. */}
            {ctx.items.length > 0 && <div className="my-1 h-px bg-border" />}
            <button type="button" className={ctxRow} onClick={() => run(() => terminalRef.current?.resetScale())}>
              <RefreshCw className="h-3.5 w-3.5 opacity-70" />
              Reset chart view
            </button>
            {onToggleRail && (
              <button type="button" className={ctxRow} onClick={() => run(onToggleRail)}>
                <PencilIcon className="h-3.5 w-3.5 opacity-70" />
                {railVisible ? 'Hide drawing tools' : 'Show drawing tools'}
              </button>
            )}
            <button
              type="button"
              className={ctxRow}
              onClick={() =>
                run(() => {
                  const next = !volumeOn
                  terminalRef.current?.setVolumeVisible(next)
                  setVolumeOn(next)
                })
              }
            >
              <VolumeIcon className="h-3.5 w-3.5 opacity-70" />
              {volumeOn ? 'Hide volume' : 'Show volume'}
            </button>
            <div className="relative" onMouseLeave={() => setGridSub(false)}>
              <button
                type="button"
                className={ctxRow}
                // Opens on hover, the way a nested menu is expected to. The
                // click also has to stop propagating: the menu closes itself on
                // any window click, so clicking Grid was tearing down the very
                // menu the submenu belongs to.
                onMouseEnter={() => setGridSub(true)}
                onClick={(e) => {
                  e.stopPropagation()
                  setGridSub((v) => !v)
                }}
                aria-expanded={gridSub}
              >
                <GridIcon className="h-3.5 w-3.5 opacity-70" />
                Grid
                <ChevronDown className="ml-auto h-3.5 w-3.5 -rotate-90 opacity-60" />
              </button>
              {gridSub && (
                <div
                  className={cn(
                    'absolute top-0 w-36 rounded-md border bg-popover p-1 shadow-lg',
                    gridSubLeft ? 'right-full mr-1' : 'left-full ml-1'
                  )}
                >
                  {(
                    [
                      ['both', 'Grid', grid.vertical && grid.horizontal],
                      ['horizontal', 'Horizontal', !grid.vertical && grid.horizontal],
                      ['vertical', 'Vertical', grid.vertical && !grid.horizontal],
                      ['none', 'None', !grid.vertical && !grid.horizontal],
                    ] as const
                  ).map(([key, label, active]) => (
                    <button
                      type="button"
                      key={key}
                      className={ctxRow}
                      onClick={(e) => {
                        e.stopPropagation()
                        run(() => toggleGrid(key))
                      }}
                    >
                      <span className="w-3.5 text-xs">{active ? '✓' : ''}</span>
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </div>

      <SymbolSearchDialog
        open={searchOpen}
        onOpenChange={setSearchOpen}
        search={(q, ex, limit) =>
          terminalRef.current ? terminalRef.current.search(q, ex, limit) : Promise.resolve([])
        }
        onPick={(row) => terminalRef.current?.loadSymbol(row)}
        initialQuery={sym?.symbol}
      />
    </section>
  )
}
