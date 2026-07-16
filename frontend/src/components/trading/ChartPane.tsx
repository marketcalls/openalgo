import { ChevronDown, RefreshCw, Search } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
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
  type SearchRow,
  type SymbolView,
  type TerminalCallbacks,
  TradingTerminal,
} from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'

/** TradingView-style camera (screenshot) glyph. */
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
}

/**
 * One independent charting terminal in the grid: its own toolbar (symbol search,
 * timeframe, chart type, product, qty), its own openalgo-charts instance + feeds
 * (via `TradingTerminal`), and its own on-chart order/position lines.
 */
export function ChartPane({ paneId, apiKey, wsUrl, style }: Props) {
  const chartRef = useRef<HTMLDivElement>(null)
  const legendRef = useRef<HTMLDivElement>(null)
  const terminalRef = useRef<TradingTerminal | null>(null)
  const aliveRef = useRef(true)
  const { mode, appMode } = useThemeStore()

  const [ready, setReady] = useState(false)
  const [intervalGroups, setIntervalGroups] = useState<IntervalGroup[]>([])
  const [interval, setIntervalState] = useState('5m')
  const [chartType, setChartTypeState] = useState('candlestick')
  const [sym, setSym] = useState<SymbolView | null>(null)
  const [qty, setQty] = useState(1)
  const [wsState, setWsState] = useState('connecting')

  // symbol search
  const [query, setQuery] = useState('')
  const [rows, setRows] = useState<SearchRow[]>([])
  const [searchOpen, setSearchOpen] = useState(false)
  const [searchSel, setSearchSel] = useState(-1)
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  // right-click order menu
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
        setQuery(view.symbol)
      },
      onLtp: () => {}, // legend overlay + canvas render the live price
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
    }

    return () => {
      aliveRef.current = false
      terminal?.destroy()
      terminalRef.current = null
    }
  }, [paneId, apiKey, wsUrl])

  /* ── keep the canvas theme in sync with the app theme ─────────────────── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: mode/appMode are the trigger — the effect re-themes the canvas whenever the app theme changes
  useEffect(() => {
    terminalRef.current?.applyTheme()
  }, [mode, appMode])

  /* ── symbol search (debounced, all exchanges — pick inline like TradingView) */
  const runSearch = useCallback(async (q: string) => {
    const t = terminalRef.current
    if (!t) return
    const res = await t.search(q)
    if (!aliveRef.current) return
    setRows(res)
    setSearchSel(-1)
    setSearchOpen(res.length > 0)
  }, [])

  const onQueryChange = (v: string) => {
    setQuery(v)
    if (searchTimer.current) clearTimeout(searchTimer.current)
    const q = v.trim()
    if (q.length < 2) {
      setRows([])
      setSearchOpen(false)
      return
    }
    searchTimer.current = setTimeout(() => runSearch(q), 220)
  }

  const pickSymbol = (row: SearchRow) => {
    setSearchOpen(false)
    setRows([])
    terminalRef.current?.loadSymbol(row)
  }

  const onSearchKey = (e: React.KeyboardEvent) => {
    if (!rows.length) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setSearchSel((s) => (s + 1) % rows.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setSearchSel((s) => (s - 1 + rows.length) % rows.length)
    } else if (e.key === 'Enter') {
      const pick = rows[searchSel >= 0 ? searchSel : 0]
      if (pick) pickSymbol(pick)
    } else if (e.key === 'Escape') {
      setSearchOpen(false)
    }
  }

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
    const res = t.contextMenuAt(e.clientY - rect.top)
    if (!res) return // quote-only / no chart: let the native menu (Save image) through
    e.preventDefault()
    setCtx({
      x: Math.min(e.clientX, window.innerWidth - 240),
      y: Math.min(e.clientY, window.innerHeight - 300),
      items: res.items,
    })
  }
  useEffect(() => {
    if (!ctx) return
    const close = () => setCtx(null)
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
    }
  }, [ctx])

  const chartTypeDef = CHART_TYPES[chartType] ?? CHART_TYPES.candlestick

  return (
    <section
      style={style}
      className="relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card"
    >
      {/* Per-pane control row */}
      <div className="flex flex-wrap items-center gap-1.5 border-b bg-background/60 px-2 py-1.5">
        {/* Symbol search */}
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={query}
            onChange={(e) => onQueryChange(e.target.value)}
            onKeyDown={onSearchKey}
            onFocus={() => rows.length && setSearchOpen(true)}
            onBlur={() => setTimeout(() => setSearchOpen(false), 150)}
            placeholder="Search symbol…"
            className="h-8 w-44 pl-8 text-sm"
            aria-label="Search symbol"
          />
          {searchOpen && rows.length > 0 && (
            <div className="absolute left-0 top-full z-40 mt-1 max-h-80 w-80 overflow-y-auto rounded-md border bg-popover p-1 shadow-md">
              {rows.map((r, i) => (
                <button
                  type="button"
                  key={`${r.symbol}:${r.exchange}`}
                  onMouseDown={(e) => {
                    e.preventDefault()
                    pickSymbol(r)
                  }}
                  className={cn(
                    'flex w-full items-center gap-2 rounded-sm px-2 py-1.5 text-left text-sm',
                    i === searchSel ? 'bg-accent text-accent-foreground' : 'hover:bg-accent/60'
                  )}
                >
                  <span className="font-medium">{r.symbol}</span>
                  <span className="flex-1 truncate text-xs text-muted-foreground">
                    {r.name || ''}
                  </span>
                  {Number(r.lotsize) > 1 && (
                    <span className="text-[10px] text-muted-foreground">
                      lot {String(r.lotsize)}
                    </span>
                  )}
                  <span className="rounded bg-muted px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
                    {r.exchange}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>

        {/* Timeframe */}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-8 min-w-12 gap-1 font-medium">
              {interval || '—'}
              <ChevronDown className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-64">
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
            <Button variant="outline" size="sm" className="h-8 gap-1" title={chartTypeDef.label}>
              <span className="h-4 w-4">{chartTypeIcon(chartTypeDef.iconKey)}</span>
              <ChevronDown className="h-3.5 w-3.5 opacity-60" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="w-52">
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

        {/* Product (segmented) */}
        {sym && !sym.quoteOnly && (
          <div className="flex overflow-hidden rounded-md border">
            {sym.productOptions.map((p) => (
              <button
                type="button"
                key={p}
                onClick={() => changeProduct(p)}
                className={cn(
                  'px-2.5 py-1 text-xs font-medium transition-colors',
                  p === sym.product ? 'bg-primary text-primary-foreground' : 'hover:bg-muted'
                )}
              >
                {p}
              </button>
            ))}
          </div>
        )}

        {/* Quantity */}
        <div className="flex items-center gap-1">
          <label className="text-[11px] text-muted-foreground" htmlFor={`qty-${paneId}`}>
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

        {/* Right side: connection LED + actions */}
        <div className="ml-auto flex items-center gap-1.5">
          <span
            className={cn('inline-block h-2.5 w-2.5 rounded-full', ledClass(wsState))}
            title={`WebSocket ${wsState}`}
          />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => terminalRef.current?.resetScale()}
            title="Fit chart to screen"
            aria-label="Fit chart to screen"
          >
            <RefreshCw className="h-4 w-4" />
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
      <div className="relative min-h-0 flex-1">
        <div className="pointer-events-none absolute left-3 top-1.5 z-10 flex flex-col gap-0.5">
          <div ref={legendRef} className="text-xs font-medium text-foreground" />
          {sym && lotInfoText(sym, qty) && (
            <span className="text-[10px] text-muted-foreground">{lotInfoText(sym, qty)}</span>
          )}
        </div>
        <div ref={chartRef} className="absolute inset-0" onContextMenu={onContextMenu} />

        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            Loading…
          </div>
        )}

        {ctx && (
          <div
            className="fixed z-50 w-56 overflow-hidden rounded-md border bg-popover p-1 shadow-lg"
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
          </div>
        )}
      </div>
    </section>
  )
}
