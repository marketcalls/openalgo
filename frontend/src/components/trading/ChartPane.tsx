// ChevronDown survives for the context menu's submenu arrow only. The
// toolbar buttons carry no caret: a chevron on every control is dead
// weight when the whole row opens menus, and it reads as a dated form
// control. Reserve the glyph for where it distinguishes something.
import { ChevronDown, RefreshCw, Search, Settings } from 'lucide-react'
import type { ChartObjects, LinkGroup } from 'openalgo-charts'
import type { WorkspacePane } from 'openalgo-charts/workspace'
import { useCallback, useEffect, useRef, useState } from 'react'
import { GridIcon, PencilIcon, VolumeIcon } from '@/components/chart/menuIcons'
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
import { lotInfoText } from '@/lib/trading/legend'
import { isProfileKind } from '@/lib/trading/profileSettings'
import {
  type AlertFire,
  type AlertsHandle,
  type AlertsView,
  type BrandingLink,
  type ChartSettingsRequest,
  type DrawSelection,
  type DrawStats,
  type IndicatorSettingsRequest,
  type OrderTicketRequest,
  type ReplayState,
  type SymbolView,
  type TerminalCallbacks,
  type TerminalComparisonState,
  type TerminalContextMenu,
  TradingTerminal,
} from '@/lib/trading/terminal'
import type { WorkspaceReplaySnapshot } from '@/lib/trading/workspaceReplay'
import { cn } from '@/lib/utils'
import { useAuthStore } from '@/stores/authStore'
import { useThemeStore } from '@/stores/themeStore'
import { showToast } from '@/utils/toast'
import { AlertsDialog } from './AlertsDialog'
import { ChartSettingsDialog } from './ChartSettingsDialog'
import { ChartToolbar } from './ChartToolbar'
import { ComparisonMenu } from './ComparisonMenu'
import { DrawingStyleBar } from './DrawingStyleBar'
import { DrawingTextDialog, type TextRequest } from './DrawingTextDialog'
import { IndicatorPickerDialog } from './IndicatorPickerDialog'
import { IndicatorSettingsDialog } from './IndicatorSettingsDialog'
import { PlaceOrderDialog } from './PlaceOrderDialog'
import { SymbolSearchDialog } from './SymbolSearchDialog'

/** Camera (screenshot) glyph. */
/** Hand-drawn to sit at the same 1.7 stroke as the camera beside them. */
function DownloadIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <path d="M12 3v11m0 0 4-4m-4 4-4-4" />
      <path d="M4 17v3h16v-3" />
    </svg>
  )
}

function CopyIcon({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      <rect x="8" y="8" width="12" height="12" rx="2" />
      <path d="M16 5.5H6A1.5 1.5 0 0 0 4.5 7v10" />
    </svg>
  )
}

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

/**
 * An oscillator crossing its threshold: a signal line weaving over and under a
 * dashed level, with the crossing marked.
 *
 * The old glyph was a bare zig-zag, which is the generic "chart" mark this
 * toolbar already uses for the chart-type button and the legend. This one says
 * what an indicator IS here rather than that a chart exists: a derived series
 * read against a level. The dashed rule and the dot survive 16px, which a
 * busier picture of a whole sub-pane would not.
 */
function IndicatorIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" {...glyph} className={className} aria-hidden="true">
      <path d="M3 12h18" strokeDasharray="2.5 2.6" opacity={0.55} />
      <path d="M3 17.5c2.2 0 2.4-9 5-9s2.6 8 5 8 2.6-9 5-9 2.6 4.5 3 5" />
      <circle cx="13" cy="12" r="1.6" fill="currentColor" stroke="none" />
    </svg>
  )
}

/**
 * Rewind: two triangles pointing back to a bar.
 *
 * It was a circular arrow, which is the universal glyph for "reload" and reads
 * as though the button refetches the chart. Replay winds the session back and
 * plays it forward, so a transport control is the honest picture. Filled rather
 * than stroked, so it stays legible at 16px where two thin outlined triangles
 * turn to mush.
 */
function ReplayIcon({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} fill="currentColor" aria-hidden="true">
      <path d="M11.5 6.4v11.2a.7.7 0 0 1-1.1.6l-7.1-5.6a.7.7 0 0 1 0-1.2l7.1-5.6a.7.7 0 0 1 1.1.6Z" />
      <path d="M20.5 6.4v11.2a.7.7 0 0 1-1.1.6l-7.1-5.6a.7.7 0 0 1 0-1.2l7.1-5.6a.7.7 0 0 1 1.1.6Z" />
    </svg>
  )
}

/** Curved arrow back. Mirrored for redo, so the pair reads as one control. */
function UndoIcon({ className, flip }: { className?: string; flip?: boolean }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      style={flip ? { transform: 'scaleX(-1)' } : undefined}
    >
      <path d="M9 14 4 9l5-5" />
      <path d="M4 9h10a6 6 0 0 1 0 12h-3" />
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

interface Props {
  /** Undefined keeps the local toolbar; null waits for the shared host. */
  toolbarHost?: HTMLElement | null
  focused?: boolean
  paneLabel?: string
  chartSelector?: React.ReactNode
  /** Stable pane id — namespaces the pane's persisted symbol/interval/type. */
  paneId: string
  apiKey: string
  wsUrl: string
  initialWorkspacePane?: WorkspacePane
  transitionLocked?: boolean
  onInitialized?(paneId: string, terminal: TradingTerminal): void
  onInitializationError?(paneId: string, error: unknown): void
  onWorkspaceChange?(): void
  /** A page owner replaces the individual replay transport. */
  onReplayStart?(paneId: string): void
  workspaceReplay?: WorkspaceReplaySnapshot
  onBeforeSourceChange?(): void
  /** Grid placement (e.g. `{ gridArea }`) applied to the pane's root. */
  style?: React.CSSProperties
  /**
   * Tool armed by the page-level drawing rail. One rail serves every pane, so
   * each arms the same tool and whichever pane you draw in gets the shape.
   */
  sharedTool?: string | null
  sharedMagnet?: boolean
  sharedStay?: boolean
  /** This pane became the drawing target (pointer went down inside it). */
  onFocusPane?(terminal: TradingTerminal | null, paneId?: string): void
  /**
   * Reports this pane's instrument as `EXCHANGE:SYMBOL`, so the page can show
   * which watchlist row is charted here. Fires on every load, not only on
   * focus: a pane can change symbol from its own toolbar, from a linked group
   * or from a panel click, and the highlight has to follow all three.
   */
  onSymbolChange?(paneId: string, key: string | null): void
  /**
   * Announces this pane's terminal to the page as it is built, and passes null
   * as it is torn down. The page-level side panels act on a pane rather than
   * owning one, so without this they would have nothing to act on until the
   * user had clicked a chart -- a watchlist whose search returned no results
   * and whose rows charted nothing, on a page that looks perfectly ready.
   */
  onTerminalChange?(paneId: string, terminal: TradingTerminal | null): void
  /** Reports the current chart generation's object inventory. */
  onObjectsChange?(paneId: string, objects: ChartObjects | null): void
  /**
   * The braces button on an OpenScript study's legend row was pressed: open
   * this file's source. The page owns the panel that shows it, so the pane
   * passes it straight up rather than rendering anything itself.
   */
  onOpenScriptSource?(file: string): void
  /** This pane's alert controller, or null once its chart has gone. */
  onAlertsReady?(paneId: string, view: AlertsView | null): void
  /** An alert fired on this pane. */
  onAlertFired?(fire: AlertFire): void
  /** This pane's set of alerts changed. */
  onAlertsChanged?(): void
  /** Drawing state of this pane, for the shared rail's buttons. */
  onDrawStats?(stats: DrawStats): void
  /** Workspace link group this pane joins, if the page made one. */
  linkGroup?: LinkGroup | null
  /**
   * One-Click, from the page's switch. Off (the default), the on-chart Buy
   * and Sell and the context-menu rows open an order ticket in this pane; on,
   * they place at once. One switch for every pane, like sync: a grid where
   * one chart fires and the next one asks is a grid that will be misread.
   */
  armed?: boolean
  /** Show/hide the page-level rail — the action lives in each pane's menu. */
  onToggleRail?(): void
  railVisible?: boolean
  /** Workspace controls displayed beside the selected chart's controls. */
  layoutPicker?: React.ReactNode
}

/**
 * One independent terminal, retaining its controls, feeds and overlays when
 * the selected chart's toolbar is displayed in the shared workspace row.
 */
export function ChartPane({
  toolbarHost,
  focused = true,
  paneLabel,
  chartSelector,
  paneId,
  apiKey,
  wsUrl,
  initialWorkspacePane,
  transitionLocked = false,
  onInitialized,
  onInitializationError,
  onWorkspaceChange,
  onReplayStart,
  workspaceReplay,
  onBeforeSourceChange,
  style,
  sharedTool,
  sharedMagnet,
  sharedStay,
  onFocusPane,
  onSymbolChange,
  onTerminalChange,
  onObjectsChange,
  onOpenScriptSource,
  onAlertsReady,
  onAlertFired,
  onAlertsChanged,
  onDrawStats,
  linkGroup,
  armed = false,
  onToggleRail,
  railVisible,
  layoutPicker,
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
  const workspaceCbRef = useRef(onWorkspaceChange)
  workspaceCbRef.current = onWorkspaceChange
  const preparedRef = useRef(false)
  const initializedCbRef = useRef(onInitialized)
  initializedCbRef.current = onInitialized
  const initializationErrorCbRef = useRef(onInitializationError)
  initializationErrorCbRef.current = onInitializationError
  const lockedRef = useRef(transitionLocked)
  lockedRef.current = transitionLocked
  const statsCbRef = useRef(onDrawStats)
  statsCbRef.current = onDrawStats
  // Held in a ref for the same reason as statsCbRef: the terminal's callbacks
  // are captured once when it boots, so reading the prop directly would pin
  // the first render's closure for the life of the pane.
  const symbolCbRef = useRef(onSymbolChange)
  symbolCbRef.current = onSymbolChange
  const terminalCbRef = useRef(onTerminalChange)
  terminalCbRef.current = onTerminalChange
  const objectsCbRef = useRef(onObjectsChange)
  objectsCbRef.current = onObjectsChange
  const scriptSourceCbRef = useRef(onOpenScriptSource)
  scriptSourceCbRef.current = onOpenScriptSource
  const alertsCbRef = useRef({ onAlertsReady, onAlertFired, onAlertsChanged })
  alertsCbRef.current = { onAlertsReady, onAlertFired, onAlertsChanged }
  // The flag as it stands when the terminal boots; the effect below tracks it
  // from then on. Read through a ref so the boot effect does not re-run and
  // rebuild the terminal on every toggle.
  const armedRef = useRef(armed)
  armedRef.current = armed
  const { mode, appMode } = useThemeStore()

  const [ready, setReady] = useState(false)
  const [intervalGroups, setIntervalGroups] = useState<IntervalGroup[]>([])
  const [interval, setIntervalState] = useState('5m')
  const [chartType, setChartTypeState] = useState('candlestick')
  const [sym, setSym] = useState<SymbolView | null>(null)
  const [branding, setBranding] = useState<BrandingLink | null>(null)
  const [qty, setQty] = useState(1)
  const [wsState, setWsState] = useState('connecting')
  /**
   * Just the two history flags, mirrored locally. The full DrawStats is pushed
   * to the parent for the drawing rail, but the toolbar's undo/redo sit in THIS
   * component, and reading a parent's state back down would make the buttons
   * lag a shape behind. Narrowed to two booleans on purpose: every drawing edit
   * fires this, and re-rendering the toolbar because a tool was armed or a
   * shape was selected would be work for nothing.
   */
  const [history, setHistory] = useState({ canUndo: false, canRedo: false })
  const noteHistory = useCallback((s: DrawStats) => {
    setHistory((prev) =>
      prev.canUndo === s.canUndo && prev.canRedo === s.canRedo
        ? prev
        : { canUndo: s.canUndo, canRedo: s.canRedo }
    )
  }, [])

  // symbol search modal (per-pane; opened from the toolbar symbol pill)
  const [searchOpen, setSearchOpen] = useState(false)

  // drawing + indicator controls (additive; the trading controls are unchanged)
  const [indicators, setIndicators] = useState<{ id: string; name: string }[]>([])
  const [comparisons, setComparisons] = useState<TerminalComparisonState>({
    mode: 'price',
    items: [],
  })
  const [catalog, setCatalog] = useState<{ id: string; name: string; category: string }[]>([])
  const [pickerOpen, setPickerOpen] = useState(false)
  const [grid, setGrid] = useState({ vertical: true, horizontal: true })
  const [fullscreen, setFullscreen] = useState(false)
  const [gridSub, setGridSub] = useState(false)
  const [volumeOn, setVolumeOn] = useState(true)
  /**
   * The snapshot menu: saving and pasting are both wanted, so the camera asks.
   *
   * Held as viewport coordinates rather than opened as an absolutely positioned
   * child, because the toolbar row scrolls horizontally: `overflow-x: auto`
   * forces the other axis to `auto` as well, and the row is only 111px tall, so
   * an absolute child was clipped to a three-pixel sliver. Nothing inside a
   * scrolling strip can hang below it.
   */
  const [snapOpen, setSnapOpen] = useState(false)
  useEffect(() => {
    if (!focused) setSnapOpen(false)
  }, [focused])
  const [snapAt, setSnapAt] = useState<{ top: number; right: number } | null>(null)
  const snapBtnRef = useRef<HTMLButtonElement>(null)

  const openSnapMenu = useCallback(() => {
    const r = snapBtnRef.current?.getBoundingClientRect()
    if (!r) return
    // Right-aligned to the button, so the menu opens inward and cannot run off
    // the window edge the camera sits near.
    setSnapAt({ top: Math.round(r.bottom + 6), right: Math.round(window.innerWidth - r.right) })
    setSnapOpen(true)
  }, [])
  const [drawSel, setDrawSel] = useState<DrawSelection | null>(null)
  const [indSettings, setIndSettings] = useState<IndicatorSettingsRequest | null>(null)
  /** The alert dialog's handle, or null when it is shut. */
  const [alertsHandle, setAlertsHandle] = useState<AlertsHandle | null>(null)
  // Read from the chart each time the gear is clicked rather than held: the
  // schema depends on the live series type, theme and timezone.
  const [chartSettings, setChartSettings] = useState<ChartSettingsRequest | null>(null)
  const [textReq, setTextReq] = useState<TextRequest | null>(null)

  // right-click menu: order entry, then the view actions
  const [ctx, setCtx] = useState<TerminalContextMenu | null>(null)
  /**
   * The order ticket, while One-Click is off. The terminal validates the
   * click and hands over what it would have sent; the same dialog the option
   * chain opens confirms it, so a chart button starts an order but never
   * places one until the trader says so.
   */
  const [ticket, setTicket] = useState<OrderTicketRequest | null>(null)
  // Null whenever the chart is live. The transport bar renders only while
  // replay owns the data, so there is nothing to hide when it does not.
  const [replay, setReplay] = useState<ReplayState | null>(null)
  /** True while a start bar is being chosen, before replay owns the data. */
  const [picking, setPicking] = useState(false)
  const [replayLoading, setReplayLoading] = useState(false)
  /** The confirm shown on leaving: the playhead is the only record of the walk. */
  const [confirmLeave, setConfirmLeave] = useState(false)

  /* ── boot this pane's terminal once ───────────────────────────────────── */
  useEffect(() => {
    let current = true
    preparedRef.current = false
    setReady(false)
    let terminal: TradingTerminal | null = null

    const callbacks: TerminalCallbacks = {
      onContextMenu: (menu) => {
        if (!current) return
        setGridSub(false)
        setCtx({
          ...menu,
          x: Math.max(0, Math.min(menu.x, window.innerWidth - 240)),
          y: Math.max(0, Math.min(menu.y, window.innerHeight - (menu.profile ? 490 : 430))),
        })
      },
      onWorkspaceChange: () => {
        if (current && preparedRef.current) workspaceCbRef.current?.()
      },
      onReady: ({ intervalGroups: g, interval: iv, chartType: ct }) => {
        if (!current) return
        setIntervalGroups(g)
        setIntervalState(iv)
        setChartTypeState(ct)
      },
      onToast: (msg, kind) => {
        if (!current) return
        if (kind === 'ok') showToast.success(msg)
        else if (kind === 'err') showToast.error(msg)
        else showToast.info(msg)
      },
      onIntervalChange: (iv) => current && setIntervalState(iv),
      onWsState: (s) => current && setWsState(s),
      onSymbolLoaded: (view) => {
        if (!current) return
        setSym(view)
        setQty(1)
        symbolCbRef.current?.(paneId, `${view.exchange}:${view.symbol}`)
        if (preparedRef.current) workspaceCbRef.current?.()
      },
      onBrandingChange: (link) => current && setBranding(link),
      onLtp: () => {}, // legend overlay + canvas render the live price
      onDrawChange: (s) => {
        if (!current) return
        statsCbRef.current?.(s)
        noteHistory(s)
      },
      onIndicatorsChange: (list) => current && setIndicators(list),
      onComparisonsChange: (state) => current && setComparisons(state),
      onIndicatorSettings: (req) => current && setIndSettings(req),
      // Null is the terminal saying the chart this dialog belonged to has gone,
      // which shuts it rather than leaving it writing into a dead controller.
      onAlerts: (handle) => current && setAlertsHandle(handle),
      onAlertsReady: (view) => current && alertsCbRef.current.onAlertsReady?.(paneId, view),
      onAlertFired: (fire) => current && alertsCbRef.current.onAlertFired?.(fire),
      onAlertsChanged: () => current && alertsCbRef.current.onAlertsChanged?.(),
      onChartSettings: (req) => current && setChartSettings(req),
      onObjectsChange: (objects) => current && objectsCbRef.current?.(paneId, objects),
      onOpenScriptSource: (file) => current && scriptSourceCbRef.current?.(file),
      onDrawSelect: (sel) => current && setDrawSel(sel),
      // The legend readout is a second switch for the same thing as the context
      // menu row, so the menu label has to follow it.
      onVolumeChange: (on) => current && setVolumeOn(on),
      onReplayChange: (state) => {
        if (!current) return
        setReplay(state)
        setPicking(terminalRef.current?.replayPickingBar() ?? false)
        setReplayLoading(terminalRef.current?.replayLoadingBars() ?? false)
        if (state === null) setConfirmLeave(false)
      },
      onDrawTextEdit: (r) => {
        if (!current) return
        // The ref, not the local: `terminal` is still unassigned while this
        // object literal is being built. Callbacks only fire after construction.
        const style = terminalRef.current?.drawTextStyle(r.id)
        if (style) setTextReq({ id: r.id, tool: r.tool, style })
      },
      onOrderTicket: (req) => current && setTicket(req),
    }

    const release = () => {
      current = false
      preparedRef.current = false
      terminalCbRef.current?.(paneId, null)
      terminal?.destroy()
      if (terminalRef.current === terminal) terminalRef.current = null
    }
    const fail = (error: unknown) => {
      if (!current) return
      release()
      setReady(false)
      if (initializationErrorCbRef.current) initializationErrorCbRef.current(paneId, error)
      else showToast.error(error instanceof Error ? error.message : 'Chart initialization failed')
    }

    if (chartRef.current && legendRef.current) {
      try {
        const owner = new TradingTerminal({
          apiKey,
          // Only the messaging channels of an alert need it, and an empty name
          // is a terminal that works with those two refused by the server.
          username: useAuthStore.getState().user?.username ?? '',
          wsUrl,
          container: chartRef.current,
          legendEl: legendRef.current,
          storageKey: `oa-trading-${paneId}`,
          initialWorkspacePane,
          getTheme: () => {
            const s = useThemeStore.getState()
            return { mode: s.mode, appMode: s.appMode }
          },
          callbacks,
        })
        terminal = owner
        terminalRef.current = owner
        owner.setWorkspaceTransitionLocked(lockedRef.current)
        owner.setArmed(armedRef.current && !lockedRef.current)
        terminalCbRef.current?.(paneId, owner)
        owner.setLinkGroup(linkGroup ?? null)
        void owner
          .init()
          .then(() => {
            if (!current) return
            preparedRef.current = true
            const stats = owner.drawStats()
            statsCbRef.current?.(stats)
            noteHistory(stats)
            setGrid(owner.gridState())
            setVolumeOn(owner.volumeVisible())
            setReady(true)
            initializedCbRef.current?.(paneId, owner)
          })
          .catch(fail)
      } catch (error) {
        fail(error)
      }
    }

    return () => {
      if (current) release()
    }
    // `username` is read at build time rather than subscribed: a terminal is
    // rebuilt on a sign-in change anyway, and re-creating the chart because a
    // display name moved would throw away every drawing on it.
  }, [paneId, apiKey, wsUrl, noteHistory, linkGroup, initialWorkspacePane])

  /* ── follow the page-level drawing rail ───────────────────────────────── */
  useEffect(() => {
    if (sharedTool === undefined || (initialWorkspacePane && !preparedRef.current)) return
    void terminalRef.current?.setDrawTool(sharedTool)
  }, [sharedTool, initialWorkspacePane])
  useEffect(() => {
    if (sharedMagnet === undefined || (initialWorkspacePane && !preparedRef.current)) return
    terminalRef.current?.setMagnet(sharedMagnet)
  }, [sharedMagnet, initialWorkspacePane])

  useEffect(() => {
    if (sharedStay === undefined || (initialWorkspacePane && !preparedRef.current)) return
    terminalRef.current?.setDrawStay(sharedStay)
  }, [sharedStay, initialWorkspacePane])
  /* ── follow the page-level One-Click switch ───────────────────────────── */
  useEffect(() => {
    terminalRef.current?.setWorkspaceTransitionLocked(transitionLocked)
    terminalRef.current?.setArmed(armed && !transitionLocked)
  }, [armed, transitionLocked])

  /* ── keep the canvas theme in sync with the app theme ─────────────────── */
  // biome-ignore lint/correctness/useExhaustiveDependencies: mode/appMode are the trigger — the effect re-themes the canvas whenever the app theme changes
  useEffect(() => {
    terminalRef.current?.applyTheme()
  }, [mode, appMode])

  /* ── toolbar actions ──────────────────────────────────────────────────── */
  const changeInterval = (iv: string) => {
    onBeforeSourceChange?.()
    setIntervalState(terminalRef.current?.setInterval(iv) ?? iv)
  }
  const changeChartType = (v: string) => {
    onBeforeSourceChange?.()
    setChartTypeState(terminalRef.current?.setChartType(v) ?? v)
  }
  const downloadCsv = () => {
    const terminal = terminalRef.current
    if (!terminal) return
    try {
      const url = URL.createObjectURL(
        new Blob([terminal.exportDataCsv()], { type: 'text/csv;charset=utf-8' })
      )
      const link = document.createElement('a')
      try {
        link.href = url
        link.download = `${sym?.symbol ?? paneId}-${interval}.csv`.replace(/[^a-zA-Z0-9._-]/g, '_')
        document.body.append(link)
        link.click()
      } finally {
        link.remove()
        URL.revokeObjectURL(url)
      }
    } catch (error) {
      showToast.error(error instanceof Error ? error.message : 'Unable to export chart data')
    }
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
  useEffect(() => {
    if (!ctx) return
    const close = () => {
      setGridSub(false)
      setCtx(null)
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    window.addEventListener('click', close)
    window.addEventListener('scroll', close, true)
    window.addEventListener('keydown', onKeyDown)
    return () => {
      window.removeEventListener('click', close)
      window.removeEventListener('scroll', close, true)
      window.removeEventListener('keydown', onKeyDown)
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

  // The product the toggle switches to; with two options that is "the other".
  const nextProduct = sym
    ? sym.productOptions[(sym.productOptions.indexOf(sym.product) + 1) % sym.productOptions.length]
    : ''

  const chartTypeDef = CHART_TYPES[chartType] ?? CHART_TYPES.candlestick
  // The three chart-owned settings editors are deliberately lightweight host
  // overlays rather than Radix dialogs. Publish their presence on the pane so
  // the page-level Escape handler can dismiss only the top surface.
  const paneDialogOpen =
    searchOpen ||
    pickerOpen ||
    chartSettings !== null ||
    indSettings !== null ||
    alertsHandle !== null ||
    textReq !== null ||
    ticket !== null ||
    confirmLeave

  return (
    <section
      ref={paneRef}
      aria-label={paneLabel ?? `Chart ${paneId}`}
      // biome-ignore lint/a11y/noNoninteractiveTabindex: Focusing this canvas region selects the chart for toolbar and keyboard actions.
      tabIndex={0}
      data-chart-pane={paneId}
      data-chart-focused={focused}
      data-trading-dialog-open={paneDialogOpen ? 'true' : undefined}
      style={style}
      className={cn(
        'relative flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-lg border bg-card outline-none focus-visible:ring-2 focus-visible:ring-primary',
        toolbarHost !== undefined && focused && 'border-primary'
      )}
      onFocusCapture={(event) => {
        if (transitionLocked || (event.target as Element).closest('[data-workspace-control]'))
          return
        onFocusPane?.(terminalRef.current, paneId)
      }}
      onPointerUpCapture={() => {
        if (ready && !transitionLocked && !replay && !picking) onWorkspaceChange?.()
      }}
      onWheelCapture={() => {
        if (ready && !transitionLocked && !replay && !picking) onWorkspaceChange?.()
      }}
      onKeyUpCapture={() => {
        if (ready && !transitionLocked && !replay && !picking) onWorkspaceChange?.()
      }}
      onPointerDownCapture={(event) => {
        // Workspace controls keep the chart selected before the control opened.
        if (transitionLocked || (event.target as Element).closest('[data-workspace-control]'))
          return
        onFocusPane?.(terminalRef.current, paneId)
      }}
    >
      <ChartToolbar host={toolbarHost} active={focused} fullscreen={fullscreen}>
        <div
          role="toolbar"
          aria-label="Chart controls"
          data-toolbar-pane={paneId}
          inert={transitionLocked ? true : undefined}
          className="flex flex-nowrap items-center gap-1.5 no-scrollbar overflow-x-auto border-b bg-background/60 px-2 py-1.5"
        >
          {!fullscreen && chartSelector && (
            <div className="sticky left-0 z-10 shrink-0 bg-background pr-1">{chartSelector}</div>
          )}
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
              <Button
                variant="outline"
                size="sm"
                className="h-8 min-w-12 shrink-0 gap-1 font-medium"
              >
                {interval || '—'}
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
              <Button
                variant="outline"
                size="sm"
                className="h-8 shrink-0 gap-1"
                title={chartTypeDef.label}
              >
                <span className="h-4 w-4">{chartTypeIcon(chartTypeDef.iconKey)}</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent container={menuHost} align="start" className="w-60">
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
            <label
              className="whitespace-nowrap text-[11px] text-muted-foreground"
              htmlFor={`qty-${paneId}`}
            >
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

          {/* Indicators. A dialog rather than a dropdown: 105 built-ins in a
            264px column was a scroll race, with no way to jump to a category
            and no memory of what you reach for daily. */}
          <Button
            variant="outline"
            size="sm"
            className="h-8 shrink-0 gap-1"
            title="Indicators"
            onClick={() => {
              setPickerOpen(true)
              void openIndicators()
            }}
          >
            <IndicatorIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Indicators</span>
            {indicators.length > 0 && (
              <span className="rounded bg-primary/15 px-1 text-[10px] font-medium text-primary">
                {indicators.length}
              </span>
            )}
          </Button>

          <Button
            variant="outline"
            size="sm"
            className="h-8 shrink-0"
            title="Alerts"
            onClick={() => void terminalRef.current?.openAlerts()}
          >
            Alerts
          </Button>

          <ComparisonMenu
            state={comparisons}
            disabled={
              !ready ||
              transitionLocked ||
              (workspaceReplay
                ? workspaceReplay.phase !== 'idle'
                : Boolean(replay || picking || replayLoading))
            }
            container={menuHost}
            search={(query, exchange, limit) =>
              terminalRef.current?.search(query, exchange, limit) ?? Promise.resolve([])
            }
            onAdd={(symbol, exchange) =>
              terminalRef.current?.addComparison(symbol, exchange) ??
              Promise.reject(new Error('Chart is not ready'))
            }
            onRemove={(id) => terminalRef.current?.removeComparison(id)}
            onModeChange={(value) => terminalRef.current?.setComparisonMode(value)}
          />

          {/* Replay. A toolbar action rather than a context-menu entry: it changes
            what the whole chart is showing, and the transport bar it opens has
            to be discoverable without a right-click. */}
          <Button
            variant="outline"
            size="sm"
            className={cn(
              'h-8 shrink-0 gap-1',
              (workspaceReplay
                ? workspaceReplay.phase !== 'idle'
                : replay || picking || replayLoading) && 'border-primary text-primary'
            )}
            onClick={() => {
              if (onReplayStart) {
                onReplayStart(paneId)
                return
              }
              if (replay) setConfirmLeave(true)
              else if (replayLoading) terminalRef.current?.stopReplay()
              else if (picking) terminalRef.current?.cancelReplayPick()
              else terminalRef.current?.startReplay()
            }}
            title={
              workspaceReplay && workspaceReplay.phase !== 'idle'
                ? 'Stop workspace replay'
                : replay
                  ? 'Leave replay'
                  : replayLoading
                    ? 'Cancel replay loading'
                    : picking
                      ? 'Cancel bar selection'
                      : 'Replay this session from a bar you pick'
            }
          >
            <ReplayIcon className="h-4 w-4" />
            <span className="hidden sm:inline">Replay</span>
          </Button>

          {/* Workspace controls share the selected chart's row, but they are not
            about this chart: they are the grid, its templates and whether a
            click anywhere in it sends an order. They sat between Alerts and
            Compare, which put two scopes in one run of buttons and left Compare
            stranded on the far side of the One-Click badge from the two
            controls it belongs with. Their own group, after everything that
            acts on this chart, with the divider saying so. */}
          {!fullscreen && layoutPicker}

          {/* Undo / redo for drawings. Also on the drawing rail, and deliberately
            here as well: the rail can be hidden, and these two are reached far
            more often than the tool that made the shape. Both stay mounted and
            go disabled rather than disappearing, so the toolbar does not reflow
            as you draw. The engine's history is drawing-only, so the labels say
            so -- a bare "Undo" next to a Replay button would imply it could
            take back an order. */}
          <div className="mx-0.5 h-5 w-px shrink-0 bg-border" aria-hidden="true" />
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => terminalRef.current?.undoDraw()}
            disabled={!history.canUndo}
            title="Undo drawing (Ctrl + Z)"
            aria-label="Undo drawing"
          >
            <UndoIcon className="h-[17px] w-[17px]" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 shrink-0"
            onClick={() => terminalRef.current?.redoDraw()}
            disabled={!history.canRedo}
            title="Redo drawing (Ctrl + Shift + Z)"
            aria-label="Redo drawing"
          >
            <UndoIcon className="h-[17px] w-[17px]" flip />
          </Button>

          {/* Right side: connection LED + actions */}
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {branding && (
              <a
                href={branding.href}
                target="_blank"
                rel="noopener noreferrer"
                aria-label={branding.label}
                className="inline-flex min-h-11 items-center whitespace-nowrap px-2 text-[11px] text-muted-foreground hover:text-foreground hover:underline sm:min-h-0 sm:px-0"
              >
                {branding.label}
              </a>
            )}
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
            {/* Positioned, so the menu below anchors to the camera and not to
              whatever ancestor happens to be relative. */}
            <div className="relative">
              <Button
                variant="ghost"
                size="icon"
                className={cn('h-8 w-8', snapOpen && 'text-primary')}
                ref={snapBtnRef}
                onClick={(e) => {
                  // Shift skips the menu and saves, for anyone who only ever saves.
                  if (e.shiftKey) {
                    void terminalRef.current?.screenshot()
                    return
                  }
                  if (snapOpen) setSnapOpen(false)
                  else openSnapMenu()
                }}
                title="Chart snapshot"
                aria-label="Chart snapshot"
              >
                <CameraIcon className="h-[17px] w-[17px]" />
              </Button>
              {snapOpen && (
                <>
                  {/* Catches the click that dismisses, so the menu closes on any
                  outside press without a document listener that would also
                  swallow the press that opened it. */}
                  <div className="fixed inset-0 z-40" onClick={() => setSnapOpen(false)} />
                  <div
                    className="fixed z-50 w-56 rounded-md border bg-popover p-1 shadow-lg"
                    style={{ top: snapAt?.top ?? 0, right: snapAt?.right ?? 0 }}
                  >
                    <div className="px-2 pb-1 pt-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
                      Chart snapshot
                    </div>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                      onClick={() => {
                        setSnapOpen(false)
                        void terminalRef.current?.screenshot()
                      }}
                    >
                      <DownloadIcon className="h-3.5 w-3.5 opacity-70" />
                      Download image
                    </button>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent disabled:opacity-40"
                      disabled={
                        workspaceReplay
                          ? workspaceReplay.phase === 'picking' ||
                            workspaceReplay.phase === 'loading'
                          : picking || replayLoading
                      }
                      title={
                        workspaceReplay?.phase === 'picking' ||
                        workspaceReplay?.phase === 'loading' ||
                        picking ||
                        replayLoading
                          ? 'Finish selecting and loading replay before exporting data'
                          : 'Export displayed chart data'
                      }
                      onClick={() => {
                        setSnapOpen(false)
                        downloadCsv()
                      }}
                    >
                      <DownloadIcon className="h-3.5 w-3.5 opacity-70" />
                      Download CSV
                    </button>
                    <button
                      type="button"
                      className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-xs hover:bg-accent"
                      onClick={() => {
                        setSnapOpen(false)
                        void terminalRef.current?.copyScreenshot()
                      }}
                    >
                      <CopyIcon className="h-3.5 w-3.5 opacity-70" />
                      Copy image
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </div>
      </ChartToolbar>

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
        <IndicatorPickerDialog
          open={pickerOpen}
          catalog={catalog}
          active={indicators}
          onAdd={(id) => void terminalRef.current?.addIndicatorById(id)}
          onRemove={(id) => terminalRef.current?.removeIndicatorById(id)}
          onSettings={(id) => terminalRef.current?.openIndicatorSettings(id)}
          onClose={() => setPickerOpen(false)}
        />
        <ChartSettingsDialog
          req={chartSettings}
          onApply={(patch) => {
            void terminalRef.current?.applyChartSettings(patch)
          }}
          onClose={() => setChartSettings(null)}
        />
        <AlertsDialog handle={alertsHandle} onClose={() => setAlertsHandle(null)} />
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
        <div ref={chartRef} className="absolute inset-0" />

        {!ready && (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-muted-foreground">
            Loading…
          </div>
        )}

        {/*
          Replay transport. The engine's controller is headless by design, so the
          bar, the clock and the scrub are ours to draw. It renders only while
          replay owns the chart's data: `replay` is null the moment we are live
          again, which is also the signal that Exit has done its work.
        */}
        {/*
          Step one of replay. The bar you start from is the whole premise of the
          exercise, so it is picked rather than guessed at from the viewport, and
          everything to its right is greyed while it is being picked: choosing a
          start with the next twenty bars readable is choosing on hindsight.
        */}
        {!onReplayStart && (picking || replayLoading) && (
          <div className="pointer-events-auto absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-lg border border-border bg-popover/95 px-3 py-2 text-xs shadow-lg backdrop-blur">
            <span>
              <span className="font-medium">
                {replayLoading ? 'Loading replay history' : 'Select a bar'}
              </span>{' '}
              {!replayLoading && <span className="text-muted-foreground">to replay from</span>}
            </span>
            <button
              type="button"
              className="rounded border border-border px-2 py-1 hover:bg-accent"
              onClick={() => terminalRef.current?.cancelReplayPick()}
            >
              Cancel
            </button>
          </div>
        )}

        {!onReplayStart && confirmLeave && (
          <div className="pointer-events-auto absolute inset-0 z-30 flex items-center justify-center bg-black/45">
            <div className="w-[340px] rounded-lg border border-border bg-popover p-4 shadow-xl">
              <h4 className="mb-2 text-sm font-medium">Leave replay?</h4>
              <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
                The chart goes back to the live session and the playhead is lost.
              </p>
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  className="rounded border border-border px-3 py-1.5 text-xs hover:bg-accent"
                  onClick={() => setConfirmLeave(false)}
                >
                  Stay
                </button>
                <button
                  type="button"
                  className="rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:opacity-90"
                  onClick={() => {
                    setConfirmLeave(false)
                    terminalRef.current?.stopReplay()
                  }}
                >
                  Leave
                </button>
              </div>
            </div>
          </div>
        )}

        {!onReplayStart && replay && (
          <div className="pointer-events-auto absolute bottom-3 left-1/2 z-20 flex -translate-x-1/2 items-center gap-2 rounded-lg border border-border bg-popover/95 px-2 py-1.5 shadow-lg backdrop-blur">
            <button
              type="button"
              className="rounded px-2 py-1 text-xs hover:bg-accent"
              title={`Step back ${replay.subSteps > 1 ? 'one step of the forming bar' : 'one bar'}`}
              onClick={() => terminalRef.current?.replayStepBack()}
            >
              Prev
            </button>
            <button
              type="button"
              className="rounded bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:opacity-90"
              title={replay.playing ? 'Pause' : 'Play'}
              onClick={() =>
                replay.playing
                  ? terminalRef.current?.replayPause()
                  : terminalRef.current?.replayPlay()
              }
            >
              {replay.playing ? 'Pause' : 'Play'}
            </button>
            <button
              type="button"
              className="rounded px-2 py-1 text-xs hover:bg-accent"
              title={`Step forward ${replay.subSteps > 1 ? 'one step of the forming bar' : 'one bar'}`}
              onClick={() => terminalRef.current?.replayStep()}
            >
              Next
            </button>

            <input
              type="range"
              min={0}
              max={Math.max(0, replay.total - 1)}
              value={replay.index}
              className="mx-1 h-1 w-40 cursor-pointer accent-primary"
              title="Scrub the session"
              onChange={(e) => terminalRef.current?.replaySeek(Number(e.target.value))}
            />

            <span className="tabular-nums text-[11px] text-muted-foreground">
              {replay.index + 1} / {replay.total}
            </span>
            {/* Only while a bar actually forms over several steps, so a plain
                whole-bar replay does not carry a permanent "1/1". */}
            {replay.subSteps > 1 && (
              <span className="tabular-nums text-[11px] text-primary">
                {replay.subIndex + 1}/{replay.subSteps}
              </span>
            )}

            <select
              className="rounded border border-border bg-background px-1 py-0.5 text-[11px]"
              value={replay.speed}
              title="Bars per second"
              onChange={(e) => terminalRef.current?.replayPlay(Number(e.target.value))}
            >
              {[0.5, 1, 2, 4, 10].map((x) => (
                <option key={x} value={x}>
                  {x}x
                </option>
              ))}
            </select>

            <button
              type="button"
              className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent hover:text-foreground"
              title="Leave replay and return to the live chart"
              onClick={() => setConfirmLeave(true)}
            >
              Exit
            </button>
          </div>
        )}

        {ctx && (
          <div
            className="fixed z-50 w-56 rounded-md border bg-popover p-1 shadow-lg"
            style={{ left: ctx.x, top: ctx.y }}
          >
            {ctx.profile && (
              <>
                <div className="px-2 py-1 text-xs text-muted-foreground">
                  {ctx.profile.sessionLabel}
                </div>
                <button type="button" className={ctxRow} onClick={() => run(ctx.profile!.run)}>
                  {ctx.profile.label}
                </button>
                <div className="my-1 h-px bg-border" />
              </>
            )}
            {ctx.alert && (
              <button
                type="button"
                className={cn(ctxRow, ctx.alert.disabled && 'cursor-not-allowed opacity-40')}
                disabled={ctx.alert.disabled}
                title={ctx.alert.reason}
                onClick={() => {
                  // Made there and then. The price is the one thing a form
                  // would ask for and it has just been given by pointing at it;
                  // the alert is editable from the rail the moment it exists.
                  void terminalRef.current?.createAlertAt(ctx.alert!.source)
                  setCtx(null)
                }}
              >
                {ctx.alert.label}
              </button>
            )}
            {/* No entry for the form. The menu's job here is the alert at the
                price under the pointer, which the entry above makes; a second
                entry one line below it, spelled almost the same and doing
                something else, is a choice nobody wants to make mid-gesture.
                The form is on the toolbar, where somebody who wants it is
                already looking. */}
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
            <button
              type="button"
              className={ctxRow}
              onClick={() => run(() => terminalRef.current?.resetScale())}
            >
              <RefreshCw className="h-3.5 w-3.5 opacity-70" />
              Reset chart view
            </button>
            {/* Settings sits on the chart it configures rather than in the
                toolbar: right-click is where a terminal user reaches for it, and
                the toolbar row is already the most contended space on the page. */}
            <button
              type="button"
              className={ctxRow}
              onClick={() =>
                run(() => {
                  void terminalRef.current?.chartSettings().then((cs) => cs && setChartSettings(cs))
                })
              }
            >
              <Settings className="h-3.5 w-3.5 opacity-70" />
              Chart settings...
            </button>
            {onToggleRail && (
              <button type="button" className={ctxRow} onClick={() => run(onToggleRail)}>
                <PencilIcon className="h-3.5 w-3.5 opacity-70" />
                {railVisible ? 'Hide drawing tools' : 'Show drawing tools'}
              </button>
            )}
            {!isProfileKind(chartType) && (
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
            )}
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
        onPick={(row) => {
          onBeforeSourceChange?.()
          void terminalRef.current?.loadSymbol(row)
        }}
        initialQuery={sym?.symbol}
      />

      {/* The order ticket One-Click off opens: the same dialog the option chain
          and pages/OptionChain.tsx use, so quantity, product and price are
          confirmed in one place and analyze mode is honoured the same way.
          A success needs no toast here; the socket provider shows the broker's
          order event once, for every surface. The confirmed order goes out
          through the terminal's own feed, never straight to the API: the
          feed asserts the page's mode against the server first, the way the
          armed path does. Portalled into the pane while it is the fullscreen
          element, as the menus are, or it would open unseen behind it. */}
      <PlaceOrderDialog
        open={ticket !== null}
        onOpenChange={(next) => !next && setTicket(null)}
        container={menuHost}
        place={(order) => {
          const terminal = terminalRef.current
          if (!terminal) return Promise.reject(new Error('chart is not ready'))
          return terminal.placeTicket(order)
        }}
        symbol={ticket?.symbol}
        exchange={ticket?.exchange}
        action={ticket?.action}
        quantity={ticket?.quantity}
        lotSize={ticket?.lotSize}
        tickSize={ticket?.tickSize}
        product={ticket?.product}
        priceType={ticket?.priceType}
        price={ticket?.price}
        triggerPrice={ticket?.triggerPrice}
        strategy={ticket?.strategy}
        onSuccess={() => setTicket(null)}
      />
    </section>
  )
}
