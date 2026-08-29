import { LayoutGrid, Link2 as LinkIcon } from 'lucide-react'
import { createLinkGroup, type LinkGroup } from 'openalgo-charts'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Navbar } from '@/components/layout/Navbar'
import { ChartPane } from '@/components/trading/ChartPane'
import { DrawingRail } from '@/components/trading/DrawingRail'
import { OptionChainPanel } from '@/components/trading/OptionChainPanel'
import { type PanelId, RightRail } from '@/components/trading/RightRail'
import { TickBox } from '@/components/trading/TickBox'
import { WatchlistPanel } from '@/components/trading/WatchlistPanel'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { DrawStats, SearchRow, TradingTerminal } from '@/lib/trading/terminal'
import { cn } from '@/lib/utils'

const NO_DRAW: DrawStats = {
  count: 0,
  canUndo: false,
  canRedo: false,
  hasSelection: false,
  magnet: false,
  tool: null,
  shortcuts: {},
}

/**
 * Grid layout presets. Each preset is a
 * CSS grid: `areas` names the cells, `cells` maps each pane (in order) to a named
 * area — so a pane can span (e.g. the big left chart in "1 + 2").
 */
interface LayoutPreset {
  id: string
  label: string
  cols: string
  rows: string
  areas: string
  cells: string[]
}

const LAYOUTS: LayoutPreset[] = [
  { id: 'single', label: 'Single', cols: '1fr', rows: '1fr', areas: '"a"', cells: ['a'] },
  {
    id: 'cols2',
    label: '2 columns',
    cols: '1fr 1fr',
    rows: '1fr',
    areas: '"a b"',
    cells: ['a', 'b'],
  },
  {
    id: 'rows2',
    label: '2 rows',
    cols: '1fr',
    rows: '1fr 1fr',
    areas: '"a" "b"',
    cells: ['a', 'b'],
  },
  {
    id: 'oneTwo',
    label: '1 + 2',
    cols: '1.4fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b" "a c"',
    cells: ['a', 'b', 'c'],
  },
  {
    id: 'grid4',
    label: '2 × 2',
    cols: '1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b" "c d"',
    cells: ['a', 'b', 'c', 'd'],
  },
  {
    id: 'grid6',
    label: '3 × 2',
    cols: '1fr 1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b c" "d e f"',
    cells: ['a', 'b', 'c', 'd', 'e', 'f'],
  },
  {
    id: 'grid8',
    label: '4 × 2',
    cols: '1fr 1fr 1fr 1fr',
    rows: '1fr 1fr',
    areas: '"a b c d" "e f g h"',
    cells: ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'],
  },
]

const LAYOUT_KEY = 'oa-trading-layout'
const SYNC_KEY = 'oa-trading-sync'
const PANEL_KEY = 'oa-trading-panel'

/**
 * What a linked grid agrees on. The engine keeps the three independent, so the
 * control does too: a trader watching one instrument across four timeframes
 * wants crosshair and time linked and the symbol emphatically not, while a
 * sector grid wants the opposite.
 *
 * Crosshair and time default on and symbol defaults off, which is the reading
 * that never surprises: linking the pointer costs nothing, and silently
 * replacing the instrument in three panes because you changed one is a bad way
 * to learn a feature exists. With a single pane a group of one does nothing, so
 * the defaults are invisible until a grid makes them useful.
 */
interface SyncState {
  crosshair: boolean
  viewport: boolean
  symbol: boolean
}
const SYNC_DEFAULT: SyncState = { crosshair: true, viewport: true, symbol: false }

function readSync(): SyncState {
  try {
    const raw = localStorage.getItem(SYNC_KEY)
    if (!raw) return SYNC_DEFAULT
    const p = JSON.parse(raw) as Partial<SyncState>
    return {
      crosshair: p.crosshair ?? SYNC_DEFAULT.crosshair,
      viewport: p.viewport ?? SYNC_DEFAULT.viewport,
      symbol: p.symbol ?? SYNC_DEFAULT.symbol,
    }
  } catch {
    return SYNC_DEFAULT
  }
}

/** Mini glyph that previews a layout preset (renders the actual grid arrangement). */
function LayoutIcon({ preset, className }: { preset: LayoutPreset; className?: string }) {
  return (
    <span
      className={cn('grid h-4 w-4 gap-px', className)}
      style={{
        gridTemplateColumns: preset.cols,
        gridTemplateRows: preset.rows,
        gridTemplateAreas: preset.areas,
      }}
      aria-hidden="true"
    >
      {preset.cells.map((c) => (
        <span key={c} style={{ gridArea: c }} className="rounded-[1px] bg-current" />
      ))}
    </span>
  )
}

export default function Trading() {
  const [layoutId, setLayoutId] = useState(() => {
    const saved = localStorage.getItem(LAYOUT_KEY)
    return LAYOUTS.some((l) => l.id === saved) ? (saved as string) : 'single'
  })
  const [sync, setSync] = useState<SyncState>(readSync)
  /**
   * One group for the whole workspace, created once and kept for the life of
   * the page. Panes join it as their charts are built and re-join after every
   * rebuild, so changing a layout, theme or chart type does not quietly drop a
   * pane out of the group it still thinks it belongs to.
   */
  const linkRef = useRef<LinkGroup | null>(null)
  if (linkRef.current === null) linkRef.current = createLinkGroup(sync)

  const [apiKey, setApiKey] = useState<string | null>(null)
  const [wsUrl, setWsUrl] = useState<string | null>(null)
  const [noApiKey, setNoApiKey] = useState(false)

  /* ── one drawing rail for every pane ─────────────────────────────────── */
  const [tool, setTool] = useState<string | null>(null)
  const [magnet, setMagnet] = useState(false)
  const [showRail, setShowRail] = useState(true)
  const [stats, setStats] = useState<DrawStats>(NO_DRAW)
  // Undo / delete act on the pane you last drew in; arming a tool hits them all,
  // so whichever pane you click next is the one that gets the shape.
  const activeRef = useRef<TradingTerminal | null>(null)

  /* ── side panels ─────────────────────────────────────────────────────── */
  const [panel, setPanel] = useState<PanelId | null>(() => {
    const saved = localStorage.getItem(PANEL_KEY)
    return saved === 'watchlist' || saved === 'options' ? saved : null
  })
  /**
   * Which pane a panel click loads into, and whose instrument the watchlist
   * highlights. The first pane until the user touches another, so a click in
   * the panel does something sensible before any pane has been focused.
   */
  const [focusedPane, setFocusedPane] = useState('p0')
  const [paneSymbols, setPaneSymbols] = useState<Record<string, string | null>>({})
  /**
   * Every live pane's terminal, keyed by pane id.
   *
   * activeRef alone is not enough: it is only set once the user has clicked
   * into a pane, so on a fresh page load the panels had nothing to act on and
   * their search returned no results at all. This is populated as each pane
   * builds, so the panels work from the first paint.
   */
  const terminalsRef = useRef<Record<string, TradingTerminal | null>>({})

  const noteTerminal = useCallback((paneId: string, terminal: TradingTerminal | null) => {
    if (terminal) terminalsRef.current[paneId] = terminal
    else delete terminalsRef.current[paneId]
  }, [])

  /** The pane a panel acts on: the focused one, else any pane that is up. */
  const panelTarget = useCallback(
    () =>
      terminalsRef.current[focusedPane] ??
      activeRef.current ??
      Object.values(terminalsRef.current)[0] ??
      null,
    [focusedPane]
  )

  const focusPane = useCallback((t: TradingTerminal | null, paneId?: string) => {
    activeRef.current = t
    if (paneId) setFocusedPane(paneId)
    if (t) setStats(t.drawStats())
  }, [])

  const noteSymbol = useCallback((paneId: string, key: string | null) => {
    setPaneSymbols((prev) => (prev[paneId] === key ? prev : { ...prev, [paneId]: key }))
  }, [])

  /**
   * Load an instrument chosen in a side panel.
   *
   * Panels are page-level and panes are not, so the click has to be routed to
   * one. It goes to the pane the user last touched -- the same pane the drawing
   * rail acts on, so "the pane I am working in" means one thing everywhere.
   */
  const sendToFocusedPane = useCallback(
    (row: SearchRow) => {
      void panelTarget()?.loadSymbol(row)
    },
    [panelTarget]
  )

  /** Bound to the focused pane so panel search returns broker-supported rows. */
  const searchFromFocusedPane = useCallback(
    (query: string, exchange?: string, limit?: number) =>
      panelTarget()?.search(query, exchange, limit) ?? Promise.resolve([]),
    [panelTarget]
  )
  const railStats: DrawStats = { ...stats, tool, magnet }
  /**
   * Hand a key event to the focused pane; it reports whether a tool claimed it.
   * The chord table ships with the lazily loaded draw tier, so the terminal --
   * not this page and not the rail -- is what can answer.
   */
  const armByShortcut = useCallback((e: KeyboardEvent) => {
    const t = activeRef.current
    if (!t || !t.armByShortcut(e)) return false
    setTool(t.drawStats().tool)
    setStats(t.drawStats())
    return true
  }, [])

  const act = (fn: (t: TradingTerminal) => void) => {
    const t = activeRef.current
    if (!t) return
    fn(t)
    setStats(t.drawStats())
  }

  useEffect(() => {
    localStorage.setItem(LAYOUT_KEY, layoutId)
  }, [layoutId])

  useEffect(() => {
    if (panel) localStorage.setItem(PANEL_KEY, panel)
    else localStorage.removeItem(PANEL_KEY)
  }, [panel])

  /**
   * Escape closes the open panel, the way it disarms a drawing tool. Without
   * it the only way back to a full-width chart is a 32px target in the corner.
   *
   * Closing the panel is the LAST thing Escape should do, so this yields twice:
   *
   * - to any open Radix surface. Checking only the scroll lock and role=dialog
   *   missed the non-modal ones: the option chain's underlying combobox is a
   *   Popover, which sets neither, so dismissing the search closed the whole
   *   panel underneath it.
   * - to an armed drawing tool, which DrawingRail disarms on the same key
   *   without stopping propagation. One Escape did both.
   */
  useEffect(() => {
    if (!panel) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return
      if (tool) return
      // Never steal Escape from a field, the way DrawingRail does not.
      const target = e.target as HTMLElement | null
      if (
        target &&
        (target.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(target.tagName))
      ) {
        return
      }
      if (document.body.hasAttribute('data-scroll-locked')) return
      if (
        document.querySelector(
          '[data-state="open"][role="dialog"],' +
            '[data-state="open"][data-slot="popover-content"],' +
            '[data-state="open"][role="menu"],' +
            '[data-state="open"][role="listbox"]'
        )
      ) {
        return
      }
      setPanel(null)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [panel, tool])

  useEffect(() => {
    localStorage.setItem(SYNC_KEY, JSON.stringify(sync))
    // setOptions, not a rebuild: the engine clears the linked crosshairs when
    // that switch goes off and converges the group on its agreed symbol when
    // the symbol switch comes on, neither of which a fresh group would do.
    linkRef.current?.setOptions(sync)
  }, [sync])

  useEffect(() => {
    const group = linkRef.current
    return () => group?.destroy()
  }, [])

  // Fetch the API key + WS URL once; every pane shares them.
  useEffect(() => {
    let alive = true
    ;(async () => {
      try {
        const [keyRes, cfgRes] = await Promise.all([
          fetch('/api/websocket/apikey').then((r) => r.json()),
          fetch('/api/websocket/config').then((r) => r.json()),
        ])
        if (!alive) return
        if (keyRes.status !== 'success') {
          setNoApiKey(true)
          return
        }
        setApiKey(keyRes.api_key)
        setWsUrl(cfgRes.websocket_url || 'ws://127.0.0.1:8765')
      } catch {
        if (alive) setNoApiKey(true)
      }
    })()
    return () => {
      alive = false
    }
  }, [])

  const layout = LAYOUTS.find((l) => l.id === layoutId) ?? LAYOUTS[0]

  /**
   * The layout picker, rendered beside the first pane's Indicators button.
   *
   * It used to sit in a full-width row of its own carrying 134px of content
   * across 1536px, so 91 per cent of that row was empty and it cost 45px of
   * chart height plus a border. It is a page-level control, so only the first
   * pane gets it: repeating it per pane would say the layout is per-pane.
   *
   * Icon-only, and with no label naming the current preset. The preset is
   * already legible from the grid itself, and the panes on screen say it
   * louder than the word "Single" ever did.
   */
  const layoutPicker = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          className="h-8 w-8 shrink-0"
          title={`Layout: ${layout.label}`}
          aria-label={`Chart layout: ${layout.label}`}
        >
          <LayoutGrid className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <div className="grid grid-cols-4 gap-1 p-1">
          {LAYOUTS.map((l) => (
            <DropdownMenuItem
              key={l.id}
              onSelect={() => setLayoutId(l.id)}
              title={l.label}
              className={cn(
                'flex aspect-square flex-col items-center justify-center gap-1 rounded border',
                l.id === layoutId
                  ? 'border-primary bg-primary/10 text-primary'
                  : 'text-muted-foreground'
              )}
            >
              <LayoutIcon preset={l} />
              <span className="text-[9px] font-medium">{l.cells.length}</span>
            </DropdownMenuItem>
          ))}
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  )

  /**
   * Chart sync, beside the layout picker because the two describe the same
   * thing: how the panes relate to each other. Page-level, so only pane zero
   * carries it.
   *
   * The trigger lights up only while something is actually linked, and it is
   * disabled outright on a single-pane layout. A group of one has nobody to
   * sync with, so an inviting control there would promise something it cannot
   * do; disabled with its state still readable is the honest version.
   */
  const syncOn = sync.crosshair || sync.viewport || sync.symbol
  const syncPicker = (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="outline"
          size="icon"
          disabled={layout.cells.length < 2}
          className={cn('h-8 w-8 shrink-0', syncOn && layout.cells.length > 1 && 'text-primary')}
          title={
            layout.cells.length < 2
              ? 'Chart sync needs more than one pane'
              : syncOn
                ? 'Chart sync is on'
                : 'Chart sync is off'
          }
          aria-label="Chart sync"
        >
          <LinkIcon className="h-4 w-4" />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-56">
        <div className="px-2 pb-1 pt-1.5 text-[10px] font-medium uppercase tracking-wider text-muted-foreground/70">
          Sync across panes
        </div>
        {(
          [
            ['crosshair', 'Crosshair', 'Mirror the hovered bar'],
            ['viewport', 'Time range', 'Mirror pan and zoom'],
            ['symbol', 'Symbol', 'Load the same instrument everywhere'],
          ] as const
        ).map(([key, label, hint]) => (
          // A label, not a button, and the row carries no click handler of its
          // own. A <button> wrapping a checkbox is invalid HTML and behaves
          // exactly as badly as that suggests: the row handler and the input's
          // own change both fire, the switch toggles twice, and it appears to
          // do nothing at all. The label forwards a click on the text to the
          // input, so every part of the row toggles it exactly once.
          //
          // Not a DropdownMenuItem either: these are three independent
          // switches and the menu has to stay open while all three are set.
          <label
            key={key}
            className="flex w-full cursor-pointer items-start gap-2.5 rounded px-2 py-1.5 text-left transition-colors hover:bg-accent"
          >
            <TickBox
              checked={sync[key]}
              onChange={(next) => setSync((p) => ({ ...p, [key]: next }))}
              label={label}
              className="mt-0.5"
            />
            <span className="min-w-0 flex-1">
              <span className="block text-[13px] leading-5">{label}</span>
              <span className="block text-[11px] leading-4 text-muted-foreground">{hint}</span>
            </span>
          </label>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )

  return (
    <>
      {/* Full-bleed page: the nav must match the chart width, not
          Layout's centred container. See NavbarProps.fluid. */}
      <Navbar fluid />
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* Rail + grid */}
        <main className="flex min-h-0 flex-1">
          {showRail && apiKey && wsUrl && (
            <DrawingRail
              stats={railStats}
              onPick={(id) => setTool(id)}
              onUndo={() => act((t) => t.undoDraw())}
              onRedo={() => act((t) => t.redoDraw())}
              onRemove={(all) => act((t) => t.removeDrawings(all))}
              onMagnet={(v) => setMagnet(v)}
              onShortcut={armByShortcut}
            />
          )}
          <div className="min-h-0 min-w-0 flex-1">
            {noApiKey ? (
              <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
                <p className="text-sm text-muted-foreground">No API key found for charting.</p>
                <a href="/apikey" className="text-sm font-medium text-primary underline">
                  Generate an API key
                </a>
              </div>
            ) : apiKey && wsUrl ? (
              <div
                className="grid h-full min-h-0 gap-2 p-2"
                style={{
                  gridTemplateColumns: layout.cols,
                  gridTemplateRows: layout.rows,
                  gridTemplateAreas: layout.areas,
                }}
              >
                {layout.cells.map((cell, i) => (
                  <ChartPane
                    key={`p${i}`}
                    paneId={`p${i}`}
                    apiKey={apiKey}
                    wsUrl={wsUrl}
                    style={{ gridArea: cell }}
                    sharedTool={tool}
                    sharedMagnet={magnet}
                    onFocusPane={focusPane}
                    onSymbolChange={noteSymbol}
                    onTerminalChange={noteTerminal}
                    onDrawStats={setStats}
                    onToggleRail={() => setShowRail((v) => !v)}
                    railVisible={showRail}
                    linkGroup={linkRef.current}
                    layoutPicker={
                      i === 0 ? (
                        <>
                          {layoutPicker}
                          {syncPicker}
                        </>
                      ) : undefined
                    }
                  />
                ))}
              </div>
            ) : (
              <div className="flex h-full items-center justify-center text-sm text-muted-foreground">
                Loading charting terminal…
              </div>
            )}
          </div>

          {/* Side panels, between the grid and the rail that toggles them.
              Both are page-level: they act on the focused pane rather than
              belonging to one, so repeating them per pane would be wrong. */}
          {apiKey && wsUrl && panel === 'watchlist' && (
            <WatchlistPanel
              apiKey={apiKey}
              onPick={sendToFocusedPane}
              search={searchFromFocusedPane}
              activeSymbol={paneSymbols[focusedPane] ?? null}
            />
          )}
          {apiKey && wsUrl && panel === 'options' && (
            <OptionChainPanel
              apiKey={apiKey}
              onPick={sendToFocusedPane}
              activeSymbol={paneSymbols[focusedPane] ?? null}
            />
          )}

          {apiKey && wsUrl && <RightRail active={panel} onSelect={setPanel} />}
        </main>
      </div>
    </>
  )
}
