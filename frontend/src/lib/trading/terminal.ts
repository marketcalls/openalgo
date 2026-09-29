/**
 * Framework-agnostic controller for the charting terminal.
 *
 * Owns the openalgo-charts instance, the OpenAlgo data / WS / trade feeds, and
 * all imperative trading state (order lines, position marker, live candle
 * builder, tick handling). The React page (`Trading.tsx`) drives it through
 * plain methods and receives updates through the callback bag — so the canvas
 * chart, the 60fps tick path, and the WebSocket lifecycle stay off React's
 * render path, and unmount is a single `destroy()`.
 *
 * Ported from the standalone /trading page; the trading flow (history → live
 * candles → on-chart order lines, right-click to place, drag to modify, ✕ to
 * cancel, real-time order stream, REST fallback) is unchanged.
 */

import type {
  ChartObjectSnapshot,
  IndicatorState,
  LinkGroup,
  SeriesMarker,
  SeriesMarkers,
} from 'openalgo-charts'
import {
  AlertController,
  type AlertEventPayload,
  type AlertPatch,
  type AlertSource,
  type AlertsDocument,
  type Bar,
  BuySellButtons,
  CandleBuilder,
  ChartObjects,
  type ChartTheme,
  type ContextMenuEvent,
  compactVolume,
  createChart,
  DataLoadingController,
  type DataLoadingSnapshot,
  exportChartDataCsv,
  getIndicator,
  type IPrimitive,
  indicatorDefaults,
  type LtpEvent,
  type MarketDepth,
  OpenAlgoDataFeed,
  OpenAlgoTradeFeed,
  OpenAlgoWsFeed,
  type PriceLine,
  parseAlertsDocument,
  ReplayController,
  ReplayShade,
  type ReplayState,
  readChartSettings,
  registeredIndicators,
  type SeriesApi,
  type SeriesStyle,
  type SeriesType,
  TextWatermark,
  tryResolveInterval,
  withBarCache,
} from 'openalgo-charts'
import type {
  DrawingController,
  DrawingPatch,
  DrawingsDocument,
  DrawingText,
  DrawingTool,
} from 'openalgo-charts/draw'
import {
  evaluateExpression,
  parseExpression,
  runTransform,
  type SymbolExpression,
} from 'openalgo-charts/transform'
import type { AlertUi } from 'openalgo-charts/widget'
import {
  parseIndicatorStates,
  parseWorkspacePayload,
  type WorkspaceComparison,
  type WorkspacePane,
} from 'openalgo-charts/workspace'
import { deliverAlert, deliveryOf, readySound } from './alertDelivery'
import { reportFire } from './alertLog'
import type { AlertFacts } from './alertMessage'
import { fillAlertMessage } from './alertMessage'
import { askToNotify } from './alertNotify'
import { mergeAlertRuntime } from './alertRuntime'
import { ExpressionFeed, isChartExpression, resolveLeg } from './expressionFeed'
import {
  type IndicatorTemplateMode,
  planIndicatorTemplate,
  readStoredIndicators,
  type StoredIndicatorRecord,
} from './indicatorTemplates'
import { openInterestCapability } from './openInterest'
import { replayTiming } from './replayTiming'
import { TerminalComparisons } from './terminalComparisons'
import type { PreparedReplayMember } from './workspaceReplay'
import {
  createWorkspacePanePreferences,
  parseTerminalWorkspacePane,
  validateWorkspacePaneSupport,
} from './workspaceState'

export { dedupeIndicators } from './indicatorTemplates'

// Re-exported so the React layer imports its chart types from this facade
// rather than reaching into the library directly, as it already does for
// SymbolView, DrawStats and the rest.
export type { ReplayState }

type ChartInstance = ReturnType<typeof createChart>
type BuySellButtonsInstance = InstanceType<typeof BuySellButtons>
type TradeFeedInstance = InstanceType<typeof OpenAlgoTradeFeed>
type DrawingControllerInstance = InstanceType<typeof DrawingController>

/** The document a pane holds when it has nothing drawn. A fresh one each time, never shared. */
const emptyDrawings = (): DrawingsDocument => ({ version: 2, drawings: [] })

/**
 * Whether a stored value is already the 2.0 document. A 1.9.x save is a bare
 * array; anything else is garbage. The entries are not inspected: the tier's
 * own migration validates every field when it loads them.
 */
function isDrawingsDocument(value: unknown): value is DrawingsDocument {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const doc = value as { version?: unknown; drawings?: unknown }
  return doc.version === 2 && Array.isArray(doc.drawings)
}

/** What the toolbar needs to enable/disable its drawing buttons. */
export interface DrawStats {
  count: number
  canUndo: boolean
  canRedo: boolean
  /**
   * Whether anything is selected. The tier supports a shift-click multi-
   * selection; the rail's delete and the style bar act on all of it, while
   * `DrawSelection` describes the primary (the first id picked).
   */
  hasSelection: boolean
  magnet: boolean
  /**
   * Whether the armed tool survives a placement. Off, the tier disarms after
   * one drawing and the rail returns to the cursor, which is the tier's
   * default; on, the tool stays armed until it is turned off.
   */
  stay: boolean
  tool: string | null
  /**
   * Tool id -> keyboard chord, from the draw tier. Empty until the tier has
   * loaded; the rail simply renders no chord until then, rather than the rail
   * having to import the tier and undo its lazy loading.
   */
  shortcuts: Record<string, string>
}

import type { AgentChartCommand } from '@/lib/agent/stream'
import type { AppMode, ThemeMode } from '@/stores/themeStore'
import {
  type AlertChart,
  type AlertDrawings,
  type AlertTick,
  alertTitleFor,
  draftFor,
  draftProblem,
  hasAutoTitle,
  snapPrice,
  toAlertInput,
} from './alertsModel'
import {
  applyChartCommands,
  applyIndicatorCommands,
  type ChartContext,
  describeDrawings,
  isAgentDrawingId,
} from './chartContract'
import { CurrentDrawingSource, profileObjectProvider } from './chartObjectsAdapter'
import {
  applyChartDialogMetrics,
  buildChartTheme,
  mutedTradeColors,
  resolveCssColor,
  volumeColor,
} from './chartTheme'
import { CHART_TYPES } from './chartTypes'
import { COMPARISON_PALETTE } from './comparisonColors'
import { DRAW_TOOL_METADATA } from './drawingToolMetadata'
import { fmtPrice, money, priceDp, snapTick, tickSize } from './format'
import { factsFor } from './instrumentFacts'
import {
  type IntervalData,
  type IntervalGroup,
  intervalGroups,
  intervalSeconds,
  lookbackDays,
  pickInterval,
} from './intervals'
import {
  buildChartLegend,
  type LegendRun,
  legendHtml,
  legendToneStyle,
  lotInfoText,
} from './legend'
import { fileForScriptId } from './openscriptFiles'
import { loadOpenScriptStudies, SCRIPT_ALERT_EVENT } from './openscriptStudies'
import { profileIntervalSupported, selectProfileInterval } from './profileIntervals'
import { ProfileLayer, type ProfileMenuAction } from './profileLayer'
import {
  isProfileKind,
  type ProfileKind,
  profileDefaults,
  profileValues,
  readProfileSettings,
} from './profileSettings'
import { profileSettingsView } from './profileSettingsView'
import {
  VOLUME_DEFAULTS,
  volumeAverage,
  volumeAveragePoint,
  volumePoint,
  volumeSettingsView,
  volumeValues,
} from './volumeSettings'

export type OrderSide = 'BUY' | 'SELL'
export type OrderType = 'MARKET' | 'LIMIT' | 'SL' | 'SL-M'
export type ToastKind = 'ok' | 'err' | ''

/** Broker order shape stored per on-chart line (subset shared by book + WS). */
interface LineOrder {
  id: string
  side: OrderSide
  type: OrderType
  qty: number
  price: number
  triggerPrice?: number
  status: string
}

interface OrderLineRec {
  line: PriceLine
  order: LineOrder
  dragFrom?: number | null
}

interface PositionState {
  net: number
  avg: number
  product: string
}

/** Everything the toolbar needs to render for the loaded instrument. */
export interface SymbolView {
  symbol: string
  exchange: string
  name: string
  /** FnO lot-based entry (qty input means lots, × lotsize). */
  lots: boolean
  lotsize: number
  /** Instrument tick size; drives all price snapping/formatting (not shown in UI). */
  tick: number
  freezeQty: number
  quoteOnly: boolean
  /** Instrument capability; an absent live observation does not change it. */
  hasOpenInterest?: boolean
  /**
   * A chart of an expression (`NIFTY/RELIANCE`, `2*CE25000 - CE25200`) rather
   * than an instrument. There is nothing to place an order in and nothing to
   * subscribe to, so this is set alongside `quoteOnly`, and the order path
   * refuses it by name rather than trusting that alias to hold.
   */
  synthetic?: boolean
  productOptions: string[]
  product: string
}

export interface SearchRow {
  symbol: string
  exchange: string
  name?: string
  lotsize?: number | string
  [k: string]: unknown
}

/** A right-click order option for the context menu. */
export interface CtxItem {
  side: OrderSide
  type: OrderType
  label: string
  enabled: boolean
}

/**
 * An order the terminal has validated but not placed, in the shape the host's
 * order ticket takes. Produced while One-Click is off: the on-chart buttons and
 * the context-menu rows start an order but never place one, the way the option
 * chain's pills do. Quantity is in units (lots already multiplied out), which
 * is what the ticket and the broker both take.
 */
export interface OrderTicketRequest {
  symbol: string
  exchange: string
  action: OrderSide
  quantity: number
  lotSize: number
  tickSize: number
  product: 'MIS' | 'NRML' | 'CNC'
  priceType: OrderType
  /** Limit price, for LIMIT and SL. Absent on a market order. */
  price?: number
  /** Trigger, for SL and SL-M. */
  triggerPrice?: number
  strategy: string
}

/**
 * The order a ticket comes back with, in the placeorder endpoint's field
 * names: the trader may have changed the side, the quantity, the type or the
 * product before confirming, so it is taken whole rather than as a patch on
 * the OrderTicketRequest that opened it.
 */
export interface ConfirmedOrder {
  symbol: string
  exchange: string
  action: OrderSide
  quantity: number
  pricetype: OrderType
  product: 'MIS' | 'NRML' | 'CNC'
  price?: number
  trigger_price?: number
}

export interface TerminalCallbacks {
  onComparisonsChange?(state: TerminalComparisonState): void
  /** Chart configuration changed; live price updates do not fire this callback. */
  onWorkspaceChange?(): void
  onReady(info: { intervalGroups: IntervalGroup[]; interval: string; chartType: string }): void
  onIntervalChange?(interval: string): void
  onContextMenu?(menu: TerminalContextMenu): void
  onToast(msg: string, kind: ToastKind): void
  onWsState(state: string): void
  onSymbolLoaded(view: SymbolView): void
  /** Linked branding exposed in host chrome for keyboard and assistive technology. */
  onBrandingChange?(link: BrandingLink | null): void
  onLtp(ltp: number): void
  /** Drawing toolbar state changed (tool armed, shape added/removed, undo...). */
  onDrawChange?(stats: DrawStats): void
  /** The live indicator list changed. */
  onIndicatorsChange?(list: { id: string; name: string }[]): void
  /**
   * The gear on an indicator's on-chart legend was clicked. The engine is
   * canvas-only and ships no DOM, so the form is ours to render.
   */
  onIndicatorSettings?(req: IndicatorSettingsRequest): void
  /**
   * The braces button on an OpenScript study's legend row was clicked: show
   * this file's source.
   *
   * Only fires for a study the trader wrote. A built-in has no file behind it,
   * and the chart draws no button for one.
   */
  onOpenScriptSource?(file: string): void
  /**
   * Alerts were asked for. The host renders the dialog and drives the handle.
   *
   * Null means the chart this dialog belonged to has gone, which is the
   * terminal telling an open dialog to close rather than keep writing into a
   * controller nothing is evaluating any more.
   */
  onAlerts?(handle: AlertsHandle | null): void
  /**
   * An alert fired. Carries what fired rather than a handle, because this is a
   * record of a moment: the alert behind it may be edited, or gone, by the time
   * anybody reads the entry back.
   */
  /**
   * This chart has an alert controller now, or has lost the one it had.
   *
   * Separate from `onAlerts`, which means "open the editor" and carries a
   * handle built for that moment. A list is on screen the whole time and needs
   * the controller from the moment there is one, so it gets its own signal and
   * the narrower view that goes with it.
   */
  onAlertsReady?(view: AlertsView | null): void
  onAlertFired?(fire: AlertFire): void
  /**
   * The set of alerts changed: one was created, edited, removed, expired, or
   * dragged to a new price. The controller is mutable and `list()` hands back a
   * copy, so nothing else tells a list built from it that it is now stale.
   */
  onAlertsChanged?(): void
  /** The current chart generation's shared object inventory. */
  onObjectsChange?(objects: ChartObjects | null): void
  /** Opens this pane's existing chart settings dialog. */
  onChartSettings?(req: ChartSettingsRequest): void
  /** A drawing was selected (or deselected), for the style popover. */
  onDrawSelect?(sel: DrawSelection | null): void
  /**
   * The replay playhead moved, or replay was entered or left. Null means the
   * chart is live again, which is the transport bar's cue to hide itself.
   */
  onReplayChange?(state: ReplayState | null): void
  /** The volume histogram was switched from the legend readout. */
  onVolumeChange?(on: boolean): void
  /**
   * A text-bearing drawing needs its content. The engine renders `style.text`
   * but has no DOM to collect it with, so the host prompts.
   */
  onDrawTextEdit?(req: { id: string; tool: string; text: string }): void
  /**
   * One-Click is off and an order route was used: the on-chart Buy or Sell,
   * or a context-menu row. Every guard the armed path applies has already
   * passed. The engine ships no DOM, so the ticket is the host's to render;
   * nothing is placed until it confirms.
   */
  onOrderTicket?(req: OrderTicketRequest): void
}

export interface TerminalComparisonItem {
  id: string
  symbol: string
  exchange: string
  label: string
  color: string
  status: 'loading' | 'ready' | 'error'
  error?: string
}

export interface TerminalComparisonState {
  mode: 'price' | 'percentage'
  items: readonly TerminalComparisonItem[]
}

export interface BrandingLink {
  href: string
  label: string
}

/** Tools whose content is typed rather than dragged. */
const TEXT_TOOLS = new Set(
  Object.keys(DRAW_TOOL_METADATA).filter((id) => DRAW_TOOL_METADATA[id].text)
)

/** The colour forms emitted by the chart palette and the host token rasterizer. */
function drawingRgb(color: string): number[] | null {
  const value = color.trim()
  let rgb: number[] | null = null
  if (/^#[0-9a-f]{3,4}$/i.test(value)) {
    rgb = [...value.slice(1, 4)].map((channel) => parseInt(channel + channel, 16))
  } else if (/^#[0-9a-f]{6}([0-9a-f]{2})?$/i.test(value)) {
    rgb = [1, 3, 5].map((offset) => parseInt(value.slice(offset, offset + 2), 16))
  } else {
    const match = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*[\d.]+\s*)?\)$/i.exec(
      value
    )
    if (match) rgb = match.slice(1, 4).map(Number)
  }
  return rgb
}

/** Native colour inputs require hex even when the canvas theme uses rgb(). */
function drawingColorInput(color: string): string {
  const rgb = drawingRgb(color)
  return rgb
    ? `#${rgb
        .map((channel) =>
          Math.max(0, Math.min(255, Math.round(channel)))
            .toString(16)
            .padStart(2, '0')
        )
        .join('')}`
    : '#000000'
}

/** Match the renderer's automatic plate text while preserving an unset override. */
function drawingTextContrast(background: string): string {
  const rgb = drawingRgb(background)
  if (!rgb) return '#10131a'
  const [r, g, b] = rgb.map((channel) => {
    const value = channel / 255
    return value <= 0.03928 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? '#10131a' : '#ffffff'
}

/** The engine's font size for drawing text that carries none, in media px. */
const DRAWING_TEXT_PX = 12

/** Everything needed to generate an indicator settings form. */
/**
 * Everything the alert dialog acts on, in one handle.
 *
 * The engine ships an alert controller and, separately, an alert UI. The
 * controller is the part worth having and this page renders its own dialog, the
 * way it already renders its own indicator settings: the engine is canvas-only
 * and its dialog is a settings table, which is the wrong shape for an alert.
 *
 * Handed over as a snapshot taken when the dialog opens. A rebuild replaces the
 * chart and its controller, so a dialog holding an old one would write alerts
 * into a chart nobody is looking at; `onAlertsClosed` is how the terminal tells
 * it to stop.
 */
export interface AlertsHandle {
  /** The engine's controller: add, update, remove, list, availability. */
  alerts: AlertController
  /** The chart, for enumerating studies, bars and the timezone. */
  chart: AlertChart
  /** The drawing tier, once it is attached. Null while it is still loading. */
  drawings: AlertDrawings | null
  /** What this chart is showing, for naming an alert after it. */
  symbol: string
  /** The instrument's tick, so every stored price sits on one. */
  at: AlertTick
  /** A source to open the editor on, from a legend or a right-click. */
  source?: AlertSource
  /** An existing alert to edit, from a row in the list. */
  editAlertId?: string
}

/**
 * What a list of alerts needs, and nothing else.
 *
 * Narrower than `AlertsHandle` on purpose. The editor needs the instrument's
 * tick and the drawing tier as they are at the instant it opens, which is why
 * that handle is built per opening; a list needs the controller and the chart's
 * clock, and both last as long as the chart does.
 */
export interface AlertsView {
  alerts: AlertController
  chart: AlertChart
}

/** One alert firing, as the chart reported it. */
export interface AlertFire {
  /** Unique per firing. One alert fires many times and each is its own row. */
  key: string
  alertId: string
  title: string
  message: string
  symbol: string
  exchange: string
  /** The value that met the condition, when the event carried one. */
  price?: number
  /** The source bar's UTC seconds, not the browser's wall clock. */
  firedAt: number
  /**
   * The channels that accepted the message, on a row read back from the log.
   *
   * Absent on a firing as it happens, because the sends have not finished yet
   * and the row is shown the moment the alert fires rather than a second later.
   */
  delivered?: readonly string[]
}

export interface IndicatorSettingsRequest {
  instanceId: string
  name: string
  /** The descriptor's own value inputs — the "Inputs" tab. */
  inputs: IndicatorField[]
  /** Generated per-plot colour / width / dash inputs — the "Style" tab. */
  styleInputs: IndicatorField[]
  values: Record<string, unknown>
}

export interface IndicatorField {
  key: string
  type: string
  label: string
  /** Plot title the style inputs belong to, so a form can group them per plot. */
  group?: string
  /** A line of help a declaration carries, shown under its row. */
  tooltip?: string
  options?: { label: string; value: unknown }[]
  min?: number
  max?: number
  step?: number
  /** A disabled control keeps its saved value and explains the missing capability. */
  unavailable?: string
}

/**
 * A bullish/bearish colour pair on one labelled row, with an optional switch in
 * front of it. The engine adds this one widget on top of the indicator input
 * vocabulary because a candle's up/down colours are the property a trader
 * changes most, and expressing them as two stacked `color` rows costs three
 * times the height.
 *
 * `key` names the row, not a value: the values live at `up.key`, `down.key` and
 * `enabled.key`, each an ordinary flat key, so applying this row is exactly the
 * same patch operation as applying a plain colour.
 */
export interface ChartSettingsPairField {
  key: string
  type: 'colorPair'
  label: string
  group?: string
  enabled?: { key: string; default: boolean }
  up: { key: string; label: string; default: string }
  down: { key: string; label: string; default: string }
}

export type ChartSettingsField = IndicatorField | ChartSettingsPairField

export interface ChartSettingsTabView {
  id: string
  label: string
  description?: string
  inputs: ChartSettingsField[]
}

/** Everything needed to generate the chart settings form. */
export interface ChartSettingsRequest {
  tabs: ChartSettingsTabView[]
  values: Record<string, string | number | boolean>
  /**
   * The chart as this terminal builds it, before a single stored preference is
   * replayed. What "Reset to defaults" restores, and deliberately NOT the
   * engine's own defaults: this host turns the session clock and the bar
   * countdown on at construction, so resetting to the engine's answer would
   * switch off chrome the user never asked to lose.
   */
  defaults: Record<string, string | number | boolean>
}

/**
 * Normalize one engine input into the flat field shape both settings forms
 * render. Shared by the indicator dialog and the chart dialog: the engine
 * deliberately describes chart settings with the same `IndicatorInput`
 * vocabulary, so a host that can render one renders the other for free.
 */
function toField(f: { key: string; type: string; label?: string; group?: string }): IndicatorField {
  return {
    key: f.key,
    type: f.type,
    label: f.label ?? f.key,
    group: f.group,
    // An OpenScript declaration's help text. Dropped here, the dialog's line
    // of help under the row had nothing to show in the app.
    tooltip: (f as { tooltip?: string }).tooltip,
    options: (f as { options?: { label: string; value: unknown }[] }).options,
    min: (f as { min?: number }).min,
    max: (f as { max?: number }).max,
    step: (f as { step?: number }).step,
  }
}

/** The selected drawing's editable style. */
export interface DrawSelection {
  id: string
  tool: string
  /** Content is typed, so the style bar offers an edit button. */
  hasText: boolean
  color: string
  lineWidth: number
  lineStyle: string
  locked: boolean
}

/**
 * Everything a text-bearing drawing's settings dialog edits. The engine renders
 * all of it already (a drawing's `text` keys); it ships no DOM, so the form is
 * the host's and needs the current values to open populated rather than blank.
 */
export interface DrawTextStyle {
  text: string
  color: string
  fontSize: number
  bold: boolean
  italic: boolean
  background: boolean
  backgroundColor: string
  border: boolean
  borderColor: string
  wrap: boolean
}

export interface TerminalOptions {
  apiKey: string
  /**
   * Who is signed in. Optional, and empty is a working terminal.
   *
   * Only the messaging APIs need it: Telegram and WhatsApp address a user by
   * name, and an alert asking for either without one is refused by the server
   * rather than delivered to somebody else.
   */
  username?: string
  wsUrl: string
  container: HTMLElement
  legendEl: HTMLElement
  /** localStorage namespace so each grid pane restores independently (default 'oa-trading'). */
  storageKey?: string
  /** Isolated preferences for prepared panes; null disables persistence. Defaults to browser storage. */
  preferences?: Pick<Storage, 'getItem' | 'setItem'> | null
  /** A named workspace starts in isolated preferences and rejects incomplete restoration. */
  initialWorkspacePane?: WorkspacePane
  /** Reads the app's current theme so the canvas chrome tracks it. */
  getTheme: () => { mode: ThemeMode; appMode: AppMode }
  callbacks: TerminalCallbacks
}

export interface TerminalContextMenu {
  x: number
  y: number
  items: CtxItem[]
  profile: ProfileMenuAction | null
  alert?: { label: string; source: AlertSource; disabled?: boolean; reason?: string }
}

// CRYPTO is the broker-agnostic exchange for crypto derivatives (utils/constants.py); a
// contract there is NRML or MIS in lots, and CNC does not exist for it.
const DERIVATIVE_EXCHANGES = new Set(['NFO', 'BFO', 'CDS', 'BCD', 'MCX', 'NCO', 'NCDEX', 'CRYPTO'])

/**
 * Products a segment accepts. Derivative segments are NRML/MIS and cash equity
 * is CNC/MIS; the exchange alone decides, never the contract's lot size.
 */
export function productOptionsFor(exchange: string): string[] {
  return DERIVATIVE_EXCHANGES.has(exchange) ? ['MIS', 'NRML'] : ['MIS', 'CNC']
}

/** Whether quantity on this segment is entered in lots rather than units. */
export function usesLots(exchange: string): boolean {
  return DERIVATIVE_EXCHANGES.has(exchange)
}
const QUOTE_ONLY = new Set(['NSE_INDEX', 'BSE_INDEX', 'MCX_INDEX', 'GLOBAL_INDEX'])

/**
 * The tick to format an instrument's prices with.
 *
 * An index has no real tick: nothing trades it, so whatever the master
 * contract carries is just what the feed supplied. NIFTY and BANKNIFTY come
 * through at 0.0005 and SENSEX at 0.0001, and precision derived from those put
 * four decimals on the price axis, so NIFTY read 24175.6500. Quote-only
 * exchanges are pinned to 0.05 instead, which is paise, the way every other
 * instrument on screen reads.
 *
 * Deliberately not a blanket clamp on fine ticks: currency pairs on CDS quote
 * in four decimals for real, and USDINR must keep them.
 */
export function resolveTick(exchange: string, tickSize: unknown): number {
  if (QUOTE_ONLY.has(exchange)) return 0.05
  return Number(tickSize) || 0.05
}

/** Persist each study instance, including its visibility and pane placement. */
export type SavedIndicatorRecord = StoredIndicatorRecord

/** Avoid storage and React work for generic object events that changed no indicator. */
export function sameIndicatorRecords(
  left: readonly SavedIndicatorRecord[],
  right: readonly SavedIndicatorRecord[]
): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}

export function sameIndicatorInstances(
  left: readonly { id: string; name: string }[],
  right: readonly { id: string; name: string }[]
): boolean {
  return JSON.stringify(left) === JSON.stringify(right)
}
const STRATEGY = 'chart-trading'
/**
 * Minimum gap between two armed fires, the scalping terminal's figure. A
 * double-click on the on-chart Buy, or a click that lands as the canvas
 * repaints under it, must be one order and not two.
 */
export const ORDER_COOLDOWN_MS = 120

/**
 * The quantity an order carries, in units. The toolbar box means lots on a
 * derivative segment and shares on cash equity; the broker takes units either
 * way. One function so the armed path and the ticket cannot size differently.
 */
export function orderUnits(qty: number, lots: boolean, lotsize: number): number {
  const n = Math.max(1, Math.floor(qty || 1))
  return lots ? n * lotsize : n
}

/**
 * The ticket for an order the chart would otherwise place at once: the same
 * price mapping `placeFromMenu` sends the broker. A market order carries no
 * price; a limit carries the clicked price; a stop carries it as the trigger
 * and, for SL, as the limit too.
 */
export function buildOrderTicket(input: {
  sym: SymbolView
  qty: number
  product: string
  side: OrderSide
  type: OrderType
  /** The tick-snapped price the row was clicked at; ignored for MARKET. */
  price: number
}): OrderTicketRequest {
  const { sym, side, type, price } = input
  const stop = type === 'SL' || type === 'SL-M'
  return {
    symbol: sym.symbol,
    exchange: sym.exchange,
    action: side,
    quantity: orderUnits(input.qty, sym.lots, sym.lotsize),
    lotSize: sym.lots ? sym.lotsize : 1,
    tickSize: sym.tick,
    product: input.product as 'MIS' | 'NRML' | 'CNC',
    priceType: type,
    price: type === 'MARKET' || type === 'SL-M' ? undefined : price,
    triggerPrice: stop ? price : undefined,
    strategy: STRATEGY,
  }
}
const VISIBLE_BARS = 120
/** Empty bars kept between the newest candle and the price axis. */
const RIGHT_PAD_BARS = 4

/**
 * Where the exported PNG paints the OHLC readout, in CSS px. These mirror the
 * DOM overlay's own placement in `ChartPane` (`left-3 top-1.5`, a 12px line and
 * a 10px line under it), so the saved image puts the text where the screen
 * does rather than inventing a second layout.
 */
const LEGEND_X = 12
const LEGEND_Y = 8
const LEGEND_SUB_Y = 25
/** Space between two legend runs, in CSS px (the DOM renderer joins with ' '). */
const LEGEND_GAP = 6

const nowSec = () => Math.floor(Date.now() / 1000)

/**
 * Resolve once the chart has repainted.
 *
 * The chart schedules its repaint on `requestAnimationFrame`, and rAF callbacks
 * run in registration order, so a frame requested after `removePrimitive()`
 * runs after the repaint that call triggered. Two frames are waited on because
 * an invalidation raised during a paint defers to the next one. The timeout is
 * the escape hatch for a background tab, where rAF may never fire at all.
 */
function nextPaint(): Promise<void> {
  return new Promise((resolve) => {
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      resolve()
    }
    const timer = setTimeout(finish, 250)
    requestAnimationFrame(() =>
      requestAnimationFrame(() => {
        clearTimeout(timer)
        finish()
      })
    )
  })
}

export class TradingTerminal {
  private alerts: AlertController | null = null
  private alertUi: AlertUi | null = null
  private offAlertFullscreen: (() => void) | null = null
  private alertJson: AlertsDocument = { version: 1, alerts: [] }
  private offAlerts: (() => void)[] = []
  private offDeleteKey: (() => void) | null = null
  private alertSaveFailed = false
  private alertRuntimeScope: string | null = null
  private restoringAlertRuntime = false
  private chartToolsReady: Promise<void> = Promise.resolve()
  private historyPending = false
  private historyFailed = false
  private readonly apiKey: string
  private readonly wsUrl: string
  private readonly container: HTMLElement
  private readonly legendEl: HTMLElement
  private readonly getTheme: () => { mode: ThemeMode; appMode: AppMode }
  private readonly cb: TerminalCallbacks
  private readonly sk: string
  private readonly preferences: Pick<Storage, 'getItem' | 'setItem'> | null | undefined
  private preferenceFailure = false

  private chart: ChartInstance | null = null
  private offBranding: (() => void) | null = null
  private price: SeriesApi | null = null
  /** The backtest's marker layer, made once and refilled per run. */
  private btMarkers: SeriesMarkers | null = null
  private volume: SeriesApi | null = null
  private volumeMA: SeriesApi | null = null
  private displayedVolume: Bar[] = []

  /* Drawing + indicator state. buildChart() throws the chart away on every
     interval / chart-type / theme change, so both round-trip through plain
     data here and are re-applied to the new chart. */
  private draw: DrawingControllerInstance | null = null
  private readonly objectDrawings = new CurrentDrawingSource()
  private objects: ChartObjects | null = null
  private offProfileObject: (() => void) | null = null
  private drawJson: DrawingsDocument = emptyDrawings()
  /**
   * A 1.9.x save (a bare array) waiting for the draw tier to migrate it. The
   * migration lives in the tier, which is fetched on first use, so it cannot
   * run on the boot path without bundling the tier for every pane; the array
   * waits here and `attachDrawing` lifts it the moment the tier is in hand.
   * Null once it has, or when the save was already a document.
   */
  private drawLegacy: readonly unknown[] | null = null
  private drawTool: string | null = null
  private drawMagnet = false
  private drawMagnetMode: 'off' | 'weak' | 'strong' = 'off'
  private drawStay = false
  /** True once a drawing control has been touched — gates the lazy tier fetch. */
  private drawEnabled = false
  private activeIndicators: SavedIndicatorRecord[] = []
  private indicatorsLoaded = false
  /** Guards syncIndicators while applyIndicators is mid-flight. */
  private applyingIndicators = false
  /** The generation whose saved instances are still crossing an async tier load. */
  private restoringIndicatorsOn: ChartInstance | null = null
  /** Last live instance identities sent to the pane toolbar. */
  private announcedIndicators: { id: string; name: string }[] = []
  /** History paging: in-flight guard, and whether the broker ran out. */
  private loadingOlder: { chart: ReturnType<typeof createChart>; ticket: number } | null = null
  private noMoreHistory = false
  private volumeOn = true
  private gridV = true
  private gridH = true
  private drawShortcuts: Record<string, string> = {}
  private matchShortcut:
    | ((e: {
        key: string
        altKey?: boolean
        ctrlKey?: boolean
        metaKey?: boolean
        shiftKey?: boolean
      }) => string | null)
    | null = null
  /**
   * What a key means for the selection or the placement in hand. The tier
   * installs no listener and answers questions instead, so a host that never
   * asks has a Delete key that does nothing. Null until the tier loads.
   */
  private keyAction:
    | ((
        e: {
          key: string
          ctrlKey?: boolean
          metaKey?: boolean
          shiftKey?: boolean
          altKey?: boolean
        },
        ctx: {
          hasSelection: boolean
          hasTarget: boolean
          editingText: boolean
          placing?: boolean
        }
      ) => { type: string; dx?: number; dy?: number } | null)
    | null = null
  /** The tier's tool registry, for a tool's own defaults; null until it loads. */
  private toolOf: ((id: string) => DrawingTool) | null = null
  private posLine: PriceLine | null = null
  private tradeBtns: BuySellButtonsInstance | null = null
  /** The bar the OHLC readout is currently showing; replayed into the export. */
  private legendBar: Bar | null = null
  private legendTime: number | null = null
  /**
   * Canvas primitives that are interaction affordances rather than chart
   * content. They are detached for the duration of a screenshot and re-attached
   * straight after, so a saved image carries nothing that invites a click.
   *
   * Registering here is how an overlay opts out: the capture path matches on
   * nothing, so a future overlay only has to add itself to be left out too.
   */
  private readonly screenshotExcluded: { primitive: IPrimitive; paneIndex: number }[] = []

  private ws: InstanceType<typeof OpenAlgoWsFeed> | null = null
  private rest: InstanceType<typeof OpenAlgoDataFeed> | null = null
  /**
   * The REST feed with warm-load caching in front of it. The data controller
   * asks this wrapper for a closed snapshot, then uses `noCache` for every
   * authoritative tail repair. `rest` remains available for finer replay bars.
   *
   * The cache never stores a forming bar, so a warm load is short by at most
   * the bar currently building, which the WebSocket supplies within a tick. A
   * chart with Buy and Sell buttons on it can be a bar behind for a moment; it
   * must never be confidently wrong about a price.
   */
  private cachedBars: ReturnType<typeof withBarCache> | null = null
  /** One owner for warm history, authoritative repair, paging and live merges. */
  private data: DataLoadingController | null = null
  private offData: (() => void) | null = null
  /** The request whose symbol/interval metadata the current chart was built for. */
  private chartDataKey: string | null = null
  private trade: TradeFeedInstance | null = null
  private builder: CandleBuilder | null = null
  /** The expression on the chart, when the pane shows a combination rather than an instrument. */
  private expr: SymbolExpression | null = null
  /** History for plain symbols and combinations alike; the controller talks only to this. */
  private exprFeed: ExpressionFeed | null = null
  /** Exchange a bare leg of the current expression resolves to. */
  private exprLegExchange = 'NSE'
  /** Latest price per leg, keyed as the expression names them. */
  private readonly legLtp = new Map<string, number>()
  /** The LTP subscriptions a combination holds, one per leg. */
  private legSubs: Array<{ symbol: string; exchange: string }> = []
  private offLtp: (() => void) | null = null
  private offDepth: (() => void) | null = null
  private offWsState: (() => void) | null = null
  private offWsControl: (() => void) | null = null
  private offOrderUpdate: (() => void) | null = null
  private offLegendActions: (() => void) | null = null
  private offReplayPointer: (() => void) | null = null
  private depthActive = false

  private rawBars: Bar[] = []
  /**
   * What the price series is actually showing: `rawBars`, or the output of the
   * chart type's transform (Heikin Ashi, Renko, ...). Replay has to walk this
   * rather than `rawBars`, because on a transformed chart the two differ in
   * both values and length.
   */
  private shownBars: Bar[] = []
  /**
   * The persisted chart-settings patch, kept as the flat dotted-key record the
   * engine reads and writes. Held here as well as in storage so an apply merges
   * onto what is already saved rather than replacing it.
   */
  private chartSettingsSaved: Record<string, string | number | boolean> = {}
  /**
   * The chart as this terminal builds it, captured once per build. See
   * {@link snapshotChartDefaults}.
   */
  private chartDefaults: Record<string, string | number | boolean> = {}
  private profileLayer: ProfileLayer | null = null
  private availableIntervals: string[] = ['1m', '5m', '15m', '1h', 'D']
  /** The workspace link group this pane belongs to, if sync is on. */
  private link: LinkGroup | null = null
  /** Non-null only while the chart is showing a replayed prefix. */
  private replay: ReplayController | null = null
  /** Non-null while the user is choosing the bar to replay from. */
  private replayPickIndex: number | null = null
  private replayPicking = false
  private replayLoading = false
  /** One veil per pane: the future has to be hidden on all of them. */
  private replayShades: ReplayShade[] = []
  private replayMark: TextWatermark | null = null
  /** Base-interval bars under the displayed ones, for intra-bar replay. */
  private replaySub: { interval: string; symbol: string; exchange: string; bars: Bar[] } | null =
    null
  private replayLoadTicket = 0
  private replayHistoryAbort: AbortController | null = null
  /** The price axis's autoscale state before replay forced it on. */
  private replayAutoScale = true
  private workspaceReplayLocked = false
  private replayInvalidation: (() => void) | null = null
  private workspaceReplayPick: {
    onPick(time: number): void
    onCancel(): void
    onPreview?(time: number): void
  } | null = null
  private workspaceReplayMember: {
    sessionId: number
    chart: ChartInstance
    price: SeriesApi
    data: DataLoadingController | null
    active: boolean
    preparing: boolean
    state: ReplayState | null
    autoScale: boolean
    positioned: boolean
    isCurrent(): boolean
    detachAbort(): void
  } | null = null
  private shownCount = 0
  private liveBucket: number | null = null
  private lastLtp: number | null = null
  private sym: SymbolView | null = null
  private position: PositionState | null = null
  private readonly orderLines = new Map<string, OrderLineRec>()

  private interval = '5m'
  /**
   * Who is signed in, for the messaging APIs that address a user by name.
   *
   * Empty until the host says. Telegram and WhatsApp both refuse a send with no
   * user, which is the right answer: a message with nobody to deliver it to is
   * not something to guess at.
   */
  private username = ''
  private ctype = 'candlestick'
  private product = 'MIS'
  private qty = 1
  /**
   * One-Click. Off, a Buy or a context-menu row opens the host's ticket; on,
   * it places at once. The page owns the switch and every pane follows it.
   * Default off: a fresh terminal must never send an order on one click.
   */
  private armed = false
  /** When the last armed order left, for the double-fire cooldown. */
  private lastFireAt = 0
  /** The theme the live chart was built with; the trade buttons derive from it. */
  private chartTheme: ChartTheme | null = null

  private bookTimer: ReturnType<typeof setInterval> | null = null
  private ltpPollTimer: ReturnType<typeof setInterval> | null = null
  /** Serialises agent chart commands. See {@link applyChartCommands}. */
  private chartCommandQueue: Promise<void> = Promise.resolve()
  private destroyed = false
  private initialWorkspacePane: WorkspacePane | null = null
  private preparingWorkspace = false
  private workspaceTransitionLocked = false
  private comparisons: TerminalComparisons | null = null
  private comparisonLoad: Promise<void> = Promise.resolve()
  private comparisonPreferences: { items: WorkspaceComparison[]; mode: 'price' | 'percent' } = {
    items: [],
    mode: 'percent',
  }

  /**
   * Whether this chart is watching a price for somebody.
   *
   * An armed alert is the one thing on a chart that has to keep working when
   * nobody is looking at it. Everything else a hidden tab does is a saving:
   * nothing repaints, so fetching bars nobody can see is wasted.
   */
  /**
   * What the chart knew when an alert fired, for the message's placeholders.
   *
   * Read from the bar the engine names rather than from the newest one: an
   * alert evaluated on a confirmed bar close is about that bar, and filling its
   * message from whatever has arrived since would print numbers the condition
   * was never measured against.
   */
  private alertFacts(event: { time?: number; index?: number; price?: number }): AlertFacts {
    const bars = this.shownBars
    const at =
      typeof event.index === 'number' && event.index >= 0 && event.index < bars.length
        ? bars[event.index]
        : [...bars].reverse().find((bar: Bar) => bar.time === event.time)
    return {
      ticker: this.sym?.symbol ?? '',
      exchange: this.sym?.exchange ?? '',
      interval: this.interval,
      open: at?.open ?? null,
      high: at?.high ?? null,
      low: at?.low ?? null,
      close: at?.close ?? null,
      volume: at?.volume ?? null,
      price: typeof event.price === 'number' ? event.price : (at?.close ?? null),
      time: typeof event.time === 'number' ? event.time : null,
      digits: this.dp(),
    }
  }

  /**
   * Delete or Backspace over the chart: remove the one thing under the pointer.
   *
   * The order matters more than the feature does, because every one of these
   * can be true at the same moment and deleting the wrong one is not
   * recoverable by pressing the key again.
   *
   * 1. **A field or a dialog wins outright.** Backspace in a text box is a
   *    character, and a terminal that ate it while somebody renamed a drawing
   *    would be unusable. This is why the handler is on the container and
   *    checks the target rather than sitting on the window.
   * 2. **A placement in progress is cancelled**, not committed and not deleted.
   *    Half a trend line is the thing the key is being pressed about.
   * 3. **Selected drawings go next**, because a selection is something the
   *    trader made deliberately and can see.
   * 4. **Then the hovered drawing**, which is the same gesture without the
   *    click.
   * 5. **An alert last**, and only when nothing above claimed the key. An
   *    alert's line sits across the whole pane, so it is under the pointer far
   *    more often than a drawing is, and letting it win would delete alerts
   *    while people meant to delete shapes.
   */
  private deleteAtPointer(): boolean {
    // A drawing being placed is a gesture, not an object: end the gesture.
    if (this.draw?.activeTool() && this.draw.cancel()) {
      this.afterDrawChange()
      return true
    }
    const selected = this.draw?.selection() ?? []
    if (selected.length) {
      this.draw?.removeMany(selected)
      this.afterDrawChange()
      return true
    }
    const overDrawing = this.draw?.hovered()
    if (overDrawing) {
      this.draw?.removeMany([overDrawing])
      this.afterDrawChange()
      return true
    }
    // `hovered()` is offered precisely so a host can bind a key to it: the
    // controller binds none itself, because a chart without the widget shell
    // has its own idea of what a keystroke means.
    const overAlert = this.alerts?.hovered()
    if (overAlert) {
      this.alerts?.remove(overAlert)
      // Nothing else to do: persistence is subscribed to `alert:removed`.
      return true
    }
    return false
  }

  /**
   * Wire Delete and Backspace over the plot.
   *
   * **Bound to the pointer, not to focus.** The gesture is to point at the
   * thing and press Delete, and a canvas cannot take focus, so waiting for a
   * focused element would mean the key only worked after a click that also
   * selects or deselects whatever it lands on. So the listener is on the
   * document and each terminal answers only while the pointer is inside its own
   * container, which is what makes the right pane respond in a four-pane
   * workspace.
   */
  private bindDeleteKey(): void {
    let over = false
    const enter = () => {
      over = true
    }
    const leave = () => {
      over = false
    }
    const onKey = (event: KeyboardEvent): void => {
      if (!over) return
      if (event.key !== 'Delete' && event.key !== 'Backspace') return
      // A modifier means something else is being asked for, and on a Mac
      // Cmd+Backspace is a text gesture rather than a chart one.
      if (event.ctrlKey || event.metaKey || event.altKey) return
      // Anything that takes typing owns its own Backspace, wherever the pointer
      // happens to be resting: a trader renaming a drawing in a dialog that
      // overlaps the chart must not delete the chart's contents by erasing a
      // character.
      //
      // `closest` is called defensively. A keystroke with nothing focused is
      // delivered to the document rather than to an element, and a handler that
      // assumed an element would throw on the one press it most needs to
      // handle: the one made without clicking anything first.
      const target = event.target as Element | null
      if (
        target?.closest?.(
          'input, textarea, select, [contenteditable="true"], [role="dialog"], [role="textbox"]'
        )
      ) {
        return
      }
      if (this.deleteAtPointer()) {
        // Only once something was actually removed: a Backspace that deleted
        // nothing is still the browser's to interpret.
        event.preventDefault()
        event.stopPropagation()
      }
    }
    this.container.addEventListener('pointerenter', enter)
    this.container.addEventListener('pointerleave', leave)
    document.addEventListener('keydown', onKey)
    this.offDeleteKey = () => {
      this.container.removeEventListener('pointerenter', enter)
      this.container.removeEventListener('pointerleave', leave)
      document.removeEventListener('keydown', onKey)
    }
  }

  private alertsArmed(): boolean {
    try {
      return this.alerts?.list().some((alert) => alert.state === 'armed') ?? false
    } catch {
      // A destroyed controller is not an armed alert.
      return false
    }
  }

  /**
   * A hidden tab stops fetching, unless an alert is waiting on the answer.
   *
   * Hiding used to stop the poll and the bar-close repair unconditionally. The
   * stream keeps running either way, so an alert still evaluated on the ticks
   * that arrived, but the two refreshes that correct a bar were gone: a closed
   * bar was never re-fetched, and the default alert policy is exactly the one
   * that waits for a bar to close. An alert set and then left in a background
   * tab is the ordinary way to use an alert, and it was the case that worked
   * least well.
   *
   * So the saving is kept for a chart with nothing armed on it, and a chart
   * with an armed alert stays awake. Comparisons follow the tab either way:
   * they are drawn, not watched, and nothing fires from them.
   */
  private readonly onVisibilityChange = () => {
    const visible = document.visibilityState !== 'hidden'
    this.data?.setVisible(visible || this.alertsArmed())
    this.comparisons?.setVisibleHost(visible)
  }

  constructor(opts: TerminalOptions) {
    const initial = opts.initialWorkspacePane
      ? parseTerminalWorkspacePane(opts.initialWorkspacePane)
      : null
    if (initial && !CHART_TYPES[initial.chartType])
      throw new Error(`Unsupported workspace chart type: ${initial.chartType}`)
    this.initialWorkspacePane = initial
    this.preparingWorkspace = initial !== null
    this.apiKey = opts.apiKey
    this.username = opts.username ?? ''
    this.wsUrl = opts.wsUrl
    this.container = opts.container
    this.bindDeleteKey()
    this.legendEl = opts.legendEl
    this.wireLegendActions()
    this.getTheme = opts.getTheme
    this.cb = opts.callbacks
    this.sk = opts.storageKey || 'oa-trading'
    this.preferences = initial ? createWorkspacePanePreferences(initial, this.sk) : opts.preferences
    this.interval = this.lsGet('interval') || '5m'
    this.ctype = this.lsGet('ctype') || 'candlestick'
    this.restoreChartTools()
    const comparisons = this.lsGet('comparisons')
    if (comparisons) {
      try {
        const saved = JSON.parse(comparisons)
        if (
          !saved ||
          !Array.isArray(saved.items) ||
          !['price', 'percent'].includes(saved.mode) ||
          !saved.items.every(
            (item: { visible?: unknown } | null) => typeof item?.visible === 'boolean'
          )
        )
          throw new Error('Invalid comparison preferences')
        const pane = parseTerminalWorkspacePane({
          id: 'comparison-preferences',
          symbol: 'comparison-preferences',
          exchange: '',
          interval: '1d',
          chartType: 'line',
          chart: { version: 1 },
          comparisons: saved.items,
          comparisonMode: saved.mode,
        })
        const sources = new Set<string>()
        for (const item of pane.comparisons) {
          const source = JSON.stringify([item.symbol, item.exchange])
          if (
            ![item.id, item.symbol, item.exchange].every((value) => value.trim().length > 0) ||
            sources.has(source)
          )
            throw new Error('Invalid comparison preferences')
          sources.add(source)
        }
        this.comparisonPreferences = { items: pane.comparisons, mode: pane.comparisonMode }
      } catch {
        this.reportPreferenceFailure(
          'Saved comparisons could not be read. Add them again to this chart.'
        )
      }
    }
    if (!CHART_TYPES[this.ctype]) this.ctype = 'candlestick'
  }

  /**
   * Per-pane persisted state. Each grid pane namespaces its localStorage by its
   * `storageKey`, so panes restore their own symbol/interval/chart-type/product
   * independently across layouts and reloads. The primary pane (`…-p0`) also
   * inherits the pre-namespacing global key once, so a single-chart user keeps
   * their last symbol after upgrading. Writes always go to the namespaced key.
   */
  private lsGet(key: string): string | null {
    try {
      const storage = this.preferences === undefined ? globalThis.localStorage : this.preferences
      if (!storage) return null
      const value = storage.getItem(`${this.sk}-${key}`)
      if (value !== null) return value
      return this.sk.endsWith('-p0') ? storage.getItem(`-${key}`) : null
    } catch {
      this.reportPreferenceFailure('Chart preferences are unavailable. Using defaults.')
      return null
    }
  }
  private lsSet(key: string, val: string): void {
    const changed = key !== 'product' && this.lsGet(key) !== val
    try {
      const storage = this.preferences === undefined ? globalThis.localStorage : this.preferences
      storage?.setItem(`${this.sk}-${key}`, val)
    } catch {
      this.reportPreferenceFailure(
        'Chart preferences could not be saved. Changes remain in this view.'
      )
    }
    if (
      changed &&
      !this.destroyed &&
      !this.preparingWorkspace &&
      !this.replay &&
      !this.replayPicking &&
      !this.replayLoading &&
      !this.workspaceReplayLocked &&
      !this.dataUnavailable()
    )
      this.cb.onWorkspaceChange?.()
  }
  private reportPreferenceFailure(message: string): void {
    if (this.preferenceFailure) return
    this.preferenceFailure = true
    this.cb.onToast(message, 'err')
  }

  /* ── tick-size / formatting bound to the loaded instrument ────────────── */
  private refPrice(): number {
    return this.lastLtp || (this.rawBars.length ? this.rawBars[this.rawBars.length - 1].close : 0)
  }
  private tick(): number {
    return tickSize(this.sym?.tick, this.refPrice())
  }
  private dp(): number {
    return priceDp(this.sym?.tick, this.refPrice())
  }
  private fmt(n: number): string {
    return fmtPrice(n, this.sym?.tick, this.refPrice())
  }
  private snap(n: number): number {
    return snapTick(n, this.sym?.tick, this.refPrice())
  }

  /* ── OpenAlgo REST gateway (public /api/v1, apikey in body) ───────────── */
  async api<T = { status?: string; message?: string; data?: unknown; mode?: string }>(
    path: string,
    body: Record<string, unknown> = {}
  ): Promise<T> {
    const res = await fetch(`/api/v1/${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ apikey: this.apiKey, ...body }),
    })
    const j = (await res.json().catch(() => ({}))) as T & { status?: string; message?: string }
    if (!res.ok || j.status === 'error')
      throw new Error(j.message || `${path} failed (${res.status})`)
    return j
  }

  async search(query: string, exchange?: string, limit = 30): Promise<SearchRow[]> {
    try {
      const j = await this.api<{ data?: SearchRow[] }>('search', {
        query,
        ...(exchange ? { exchange } : {}),
      })
      return (j.data || []).slice(0, limit)
    } catch {
      return []
    }
  }

  /* ── trader-facing error text (technical chain stripped; full to console) */
  private cleanError(e: unknown): string {
    console.error('[trading]', e)
    let m = String((e as Error)?.message || e || 'request failed')
    m = m
      .replace(/^openalgo-charts:\s*/i, '')
      .replace(/^\/api\/v1\/[\w/]+\s+failed\s+\(\d+\)(:\s*)?/i, '')
    return m.trim() || 'request failed'
  }
  private toast(msg: string, kind: ToastKind = '') {
    this.cb.onToast(msg, kind)
  }

  private tradeMode(): AppMode {
    return this.getTheme().appMode
  }

  /* ── chart types (transforms bucket volume onto their own element times) */
  private boxOf(): number {
    const c = this.rawBars.length ? this.rawBars[this.rawBars.length - 1].close : 100
    const t = this.tick()
    return Math.max(t, Number((Math.round((c * 0.0015) / t) * t).toFixed(this.dp())))
  }

  private setPriceData() {
    // History can finish during replay. Keep its live snapshot up to date,
    // but leave both displayed series and their timeline to the playhead.
    if (this.replayOwnsDisplay()) return
    if (!this.price || !this.volume || !this.rawBars.length) return
    const cfg = CHART_TYPES[this.ctype] || CHART_TYPES.candlestick
    if (cfg.transform) {
      const t = runTransform(cfg.transform(this.boxOf()), this.rawBars)
      this.price.setData(t)
      this.setVolumeData(t, this.bucketVolume(t))
      this.shownBars = t
    } else {
      this.price.setData(this.rawBars)
      this.setVolumeData(this.rawBars)
      this.shownBars = this.rawBars
    }
    this.shownCount = this.shownBars.length
    this.profileLayer?.refresh(true)
    this.refreshLegend()
  }

  private dataKey(request: { symbol: string; exchange: string; interval: string }): string {
    return `${request.exchange}:${request.symbol}:${request.interval}`
  }

  /** Apply a controller snapshot only to the symbol session that requested it. */
  private applyDataSnapshot(snapshot: DataLoadingSnapshot): void {
    const request = snapshot.request
    const sym = this.sym
    if (
      this.destroyed ||
      !request ||
      !sym ||
      request.symbol !== sym.symbol ||
      request.exchange !== sym.exchange ||
      request.interval !== this.interval
    )
      return

    this.noMoreHistory = snapshot.hasMore === false
    if (snapshot.reason === 'live' || snapshot.reason === 'state') return

    // While replay is paused, snapshots deliberately retain the display bars.
    // The controller's live store still accepts refreshes, pages and pushBar,
    // so keep rawBars current for the eventual resume without touching canvas.
    const owned = snapshot.paused ? this.data?.bars() : snapshot.bars
    if (!owned?.length) return
    const next = [...owned]
    const chart = this.chart
    const before = snapshot.reason === 'prepend' ? chart?.getVisibleLogicalRange() : null
    const countBefore = this.shownCount

    // History's view of the bar still forming: the sampled volume (a depth
    // subscription carries none), the true open when the builder opened the
    // bucket mid-way, and the union of the extremes. The close stays with the
    // ticks, which are fresher than any poll. The builder's own copy is
    // reconciled as well, or its next tick would write the stale values
    // straight back over the repair.
    if (snapshot.reason === 'refresh' && this.builder && this.liveBucket != null) {
      const current = this.builder.current()
      const index = current ? next.findIndex((bar) => bar.time === current.time) : -1
      if (current && index >= 0 && current.time === this.liveBucket) {
        const reconciled = this.builder.reconcile(next[index])
        if (reconciled) next[index] = reconciled
      }
    }

    this.rawBars = next
    if (snapshot.paused || this.replayOwnsDisplay()) return

    const key = this.dataKey(request)
    if (!this.chart || !this.price || !this.volume || this.chartDataKey !== key) {
      this.chartDataKey = key
      this.buildChart()
    } else {
      this.setPriceData()
      if (snapshot.reason === 'prepend') this.installComparisons()
    }

    // Prepending shifts logical indexes. Preserve the same candles in view,
    // including for transformed charts whose output count differs from OHLC.
    const inserted = this.shownCount - countBefore
    if (snapshot.reason === 'prepend' && before && inserted > 0 && chart && this.chart === chart) {
      chart.setVisibleLogicalRange({ from: before.from + inserted, to: before.to + inserted })
    }
  }

  /**
   * Push one bar into the live series without rebuilding either of them.
   *
   * `setPriceData` replaces both series wholesale and allocates a fresh volume
   * bar for every bar in history. On a tick that is the dominant cost of the
   * update, paid before a single indicator runs, and it grows with the history
   * loaded rather than with what changed. A one-bar update is O(1) and the chart
   * splices it.
   *
   * Only valid without a transform. Renko, Range, Point and Figure and Kagi
   * re-derive their whole series from the raw bars, so one new raw bar can
   * change the count and the shape of the output and the transform has to run
   * again. Those fall back to the full path.
   *
   * Returns false when the caller must rebuild instead.
   */
  private updateLiveBar(bar: Bar): boolean {
    if (!this.price || !this.volume) return false
    const cfg = CHART_TYPES[this.ctype] || CHART_TYPES.candlestick
    if (cfg.transform) return false
    // `update` appends or replaces by time on its own, which is exactly the
    // append-or-replace the caller has already applied to `rawBars`.
    this.price.update(bar)
    const settings = volumeValues(this.chartSettingsSaved)
    const point = volumePoint(
      bar,
      this.rawBars.at(-2)?.close,
      bar.volume ?? 0,
      this.volumeCandleStyle(),
      settings['volume.colorByDirection'] === true
    )
    const last = this.displayedVolume.length - 1
    if (last >= 0 && this.displayedVolume[last].time === point.time)
      this.displayedVolume[last] = point
    else this.displayedVolume.push(point)
    this.volume.update(point)
    if (settings['volume.showMA'] && this.volumeMA) {
      this.volumeMA.update(
        volumeAveragePoint(
          this.displayedVolume,
          this.displayedVolume.length - 1,
          Number(settings['volume.maPeriod'])
        )
      )
    }
    // Untransformed, the shown series *is* rawBars, which the caller mutated in
    // place, so only the count can have moved.
    this.shownBars = this.rawBars
    this.shownCount = this.rawBars.length
    this.profileLayer?.refresh()
    return true
  }

  private volumeCandleStyle(): SeriesStyle {
    const theme = this.chart?.theme()
    return {
      upColor: theme?.upColor,
      downColor: theme?.downColor,
      ...this.chart?.primarySeriesInfo()?.style,
    }
  }

  private volumeAvailable(): boolean {
    return this.sym?.synthetic === true || !QUOTE_ONLY.has(this.sym?.exchange ?? '')
  }

  private setVolumeData(prices: readonly Bar[], amounts?: readonly Bar[]): void {
    if (!this.volume || !this.chart) return
    const settings = volumeValues(this.chartSettingsSaved)
    const style = this.volumeCandleStyle()
    const byTime = amounts ? new Map(amounts.map((bar) => [bar.time, bar.close])) : null
    this.displayedVolume = prices.map((bar, index) =>
      volumePoint(
        bar,
        prices[index - 1]?.close,
        byTime?.get(bar.time) ?? bar.volume ?? 0,
        style,
        settings['volume.colorByDirection'] === true
      )
    )
    this.volume.setData(this.displayedVolume)
    if (!this.volumeMA) {
      this.volumeMA = this.chart.addSeries('line', {
        paneIndex: 0,
        priceScaleId: '',
        priceFormat: { type: 'volume' },
        style: { priceLineVisible: false, lastValueVisible: false },
      })
    }
    this.volumeMA.applyOptions({
      visible:
        this.volumeOn &&
        this.volumeAvailable() &&
        !isProfileKind(this.ctype) &&
        settings['volume.showMA'] === true,
      color: String(settings['volume.maColor']),
      lineWidth: Number(settings['volume.maWidth']),
      lineStyle: settings['volume.maStyle'] as 'solid' | 'dashed' | 'dotted',
    })
    this.volumeMA.setData(
      settings['volume.showMA']
        ? volumeAverage(this.displayedVolume, Number(settings['volume.maPeriod']))
        : []
    )
  }

  private refreshDisplayedVolume(): void {
    if (this.price && this.volume) this.setVolumeData(this.price.getData(), this.volume.getData())
  }

  private bucketVolume(tbars: Bar[]): Bar[] {
    const out: Bar[] = []
    let ri = 0
    for (const tb of tbars) {
      let v = 0
      while (ri < this.rawBars.length && this.rawBars[ri].time <= tb.time) {
        v += this.rawBars[ri].volume || 0
        ri++
      }
      out.push({ time: tb.time, open: 0, high: v, low: 0, close: v })
    }
    let rest = 0
    while (ri < this.rawBars.length) {
      rest += this.rawBars[ri].volume || 0
      ri++
    }
    if (out.length && rest) {
      const last = out[out.length - 1]
      last.high += rest
      last.close += rest
    }
    return out
  }

  /* ── legend (imperative; high-frequency, kept off React state) ────────── */
  /**
   * Close of the element before `bar` in whatever series is on screen.
   *
   * Read from `shownBars`, not `rawBars`: on a transformed chart type a drawn
   * element is not one raw bar, so measuring a Renko brick against the raw
   * candle behind it would report a change the chart never drew. Matched on
   * time, because the crosshair hands back the element it is over rather than
   * its index.
   */
  private closeBefore(bar: Bar | null): number | null {
    if (!bar) return null
    const bars = this.shownBars
    for (let i = bars.length - 1; i >= 0; i--) {
      if (bars[i].time === bar.time) return i > 0 ? bars[i - 1].close : null
    }
    return null
  }

  private setLegend(bar: Bar | null) {
    this.legendBar = bar
    if (!this.sym) {
      this.legendEl.innerHTML = ''
      return
    }
    this.legendEl.innerHTML = legendHtml(this.legendModel(bar))
  }

  /** Resolve the selected time again after history replacement or pagination. */
  private refreshLegend(bars: readonly Bar[] = this.shownBars): void {
    let selected = bars.at(-1) ?? null
    if (this.legendTime !== null) {
      let lo = 0
      let hi = bars.length - 1
      while (lo <= hi) {
        const mid = (lo + hi) >>> 1
        const bar = bars[mid]
        if (bar.time === this.legendTime) {
          selected = bar
          break
        }
        if (bar.time < this.legendTime) lo = mid + 1
        else hi = mid - 1
      }
    }
    this.setLegend(selected)
  }

  /**
   * The legend is rewritten on every crosshair move, so its controls are bound
   * by delegation on the container that survives. Binding per render would leak
   * a listener a frame.
   */
  private wireLegendActions(): void {
    this.offLegendActions?.()
    const act = (e: Event): void => {
      const el = (e.target as HTMLElement | null)?.closest?.('[data-legend-action]')
      if (!el) return
      if (el.getAttribute('data-legend-action') !== 'volume') return
      e.preventDefault()
      e.stopPropagation()
      this.setVolumeVisible(!this.volumeOn)
      this.setLegend(this.legendBar)
      this.cb.onVolumeChange?.(this.volumeOn)
    }
    const keydown = (e: Event): void => {
      const k = (e as KeyboardEvent).key
      if (k === 'Enter' || k === ' ') act(e)
    }
    this.legendEl.addEventListener('click', act)
    this.legendEl.addEventListener('keydown', keydown)
    this.offLegendActions = () => {
      this.legendEl.removeEventListener('click', act)
      this.legendEl.removeEventListener('keydown', keydown)
    }
  }

  /**
   * The readout's content, independent of how it is drawn. The DOM overlay and
   * the PNG export both render this, which is what stops the saved image from
   * quoting different numbers than the screen it was taken from.
   */
  private legendModel(bar: Bar | null): LegendRun[] {
    const sym = this.sym
    if (!sym) return []
    const runs = buildChartLegend({
      symbol: sym.symbol,
      interval: this.interval,
      exchange: sym.exchange,
      lotsize: sym.lots ? sym.lotsize : null,
      bar: bar && !this.volumeAvailable() ? { ...bar, volume: undefined } : bar,
      prevClose: this.closeBefore(bar),
      fmt: (n) => this.fmt(n),
      fmtVolume: compactVolume,
      volumeHidden: !this.volumeOn,
      openInterest: this.chart?.statusLineOptions().openInterest,
      hasOpenInterest: this.chart?.hasOpenInterest,
    })
    if (isProfileKind(this.ctype)) {
      runs.splice(2, 0, { text: CHART_TYPES[this.ctype].label, tone: 'meta' })
      return runs.map((run) =>
        run.action === 'volume' ? { ...run, action: undefined, dim: false } : run
      )
    }
    return runs
  }

  /* ── order lines / position marker ────────────────────────────────────── */
  private makeOrderLine(o: LineOrder): PriceLine {
    return this.chart!.addPriceLine(
      {
        price: o.triggerPrice ?? o.price,
        color: o.side === 'BUY' ? '#26a69a' : '#ef5350',
        lineWidth: 1,
        dashed: true,
        id: `order:${o.id}`,
        cursor: 'ns-resize',
        extentFromRight: 0.3,
        closeButton: true,
        badge: o.side,
        qty: o.qty,
        leftLabel: o.type,
      },
      0
    )
  }

  private posLabel(): string {
    if (!this.position) return ''
    const mark = this.lastLtp != null ? this.lastLtp : this.position.avg
    const pnl = (mark - this.position.avg) * this.position.net
    return `@ ${this.fmt(this.position.avg)}  ${pnl >= 0 ? '+' : '-'}₹${money(Math.abs(pnl))}`
  }

  private renderPosition(pos: Record<string, unknown> | undefined) {
    if (this.posLine && this.chart) {
      this.chart.removePrimitive(this.posLine)
      this.posLine = null
    }
    this.position = pos
      ? {
          net: Number(pos.quantity),
          avg: Number(pos.average_price),
          product: String(pos.product ?? ''),
        }
      : null
    if (!this.position || !this.chart || this.position.net === 0) {
      this.position = this.position && this.position.net !== 0 ? this.position : null
      return
    }
    this.posLine = this.chart.addPriceLine(
      {
        price: this.position.avg,
        color: this.position.net > 0 ? '#2e7d6b' : '#a14a52',
        lineWidth: 2,
        dashed: false,
        id: 'position',
        extentFromRight: 0.3,
        closeButton: true,
        badge: this.position.net > 0 ? 'LONG' : 'SHORT',
        qty: Math.abs(this.position.net),
        leftLabel: this.posLabel(),
      },
      0
    )
  }

  private async pollBook() {
    if (!this.trade || !this.sym || !this.chart) return
    try {
      const orders = await this.trade.getOrders() // caches modify context
      const seen = new Set<string>()
      for (const o of orders) {
        if (o.status !== 'working' || o.symbol !== this.sym.symbol) continue
        seen.add(o.id)
        const px = o.triggerPrice ?? o.price
        const rec = this.orderLines.get(o.id)
        if (rec) {
          rec.order = o as LineOrder
          rec.line.setPrice(px)
        } else {
          this.orderLines.set(o.id, {
            line: this.makeOrderLine(o as LineOrder),
            order: o as LineOrder,
          })
        }
      }
      for (const [id, rec] of this.orderLines)
        if (!seen.has(id)) {
          this.chart.removePrimitive(rec.line)
          this.orderLines.delete(id)
        }
    } catch {
      /* transient */
    }
    try {
      const j = await this.api<{ data?: Record<string, unknown>[] }>('positionbook')
      this.renderPosition(
        (j.data || []).find(
          (p) =>
            p.symbol === this.sym!.symbol &&
            p.exchange === this.sym!.exchange &&
            Number(p.quantity) !== 0
        )
      )
    } catch {
      /* transient */
    }
  }

  /* real order quantity (lots × lotsize for derivatives) */
  private orderQty(): number {
    return orderUnits(this.qty, this.sym?.lots ?? false, this.sym?.lotsize ?? 1)
  }
  /** Quantity chip text for the inline panel (lots for FnO, else qty). */
  private qtyChip(): string {
    if (!this.sym) return ''
    const n = Math.max(1, Math.floor(this.qty || 1))
    return this.sym.lots ? `${n}L` : String(n)
  }

  private marketPrice(): number | null {
    return this.lastLtp != null
      ? this.lastLtp
      : this.rawBars.length
        ? this.rawBars[this.rawBars.length - 1].close
        : null
  }

  private async placeFromMenu(side: OrderSide, type: OrderType) {
    if (this.refuseWhileReplaying()) return
    if (!this.sym || !this.trade) {
      this.toast('search a symbol first')
      return
    }
    if (this.sym.synthetic) {
      this.toast(
        `${this.sym.symbol} is a computed chart, not an instrument — there is nothing to trade`,
        'err'
      )
      return
    }
    if (this.sym.quoteOnly) {
      this.toast(`${this.sym.exchange} is quote-only — trading is not supported`, 'err')
      return
    }
    const qty = this.orderQty()
    if (this.sym.freezeQty > 1 && qty > this.sym.freezeQty) {
      this.toast(`qty ${qty} exceeds the freeze limit ${this.sym.freezeQty} — reduce lots`, 'err')
      return
    }
    const px = type === 'MARKET' ? 0 : this.snap(this.ctxPrice)
    const m = this.marketPrice()
    if (m != null && (type === 'SL' || type === 'SL-M') && (side === 'BUY' ? px <= m : px >= m)) {
      this.toast(
        `${side} stop must be ${side === 'BUY' ? 'above' : 'below'} LTP ${this.fmt(m)}`,
        'err'
      )
      return
    }
    // Every guard above has passed on both paths. Disarmed, the click opens
    // the ticket and stops here; armed, it is the order. The guards are not
    // moved below this fork on purpose: a ticket pre-filled with a stop on the
    // wrong side of LTP, or a quantity over the freeze limit, would only be
    // refused later by the broker, in words that do not say why.
    if (!this.armed) {
      if (!this.cb.onOrderTicket) {
        this.toast('One-Click is off', 'err')
        return
      }
      this.cb.onOrderTicket(
        buildOrderTicket({
          sym: this.sym,
          qty: this.qty,
          product: this.product,
          side,
          type,
          price: px,
        })
      )
      return
    }
    // The scalping terminal's double-fire guard: a second click inside the
    // window is the same click, not a second order.
    const now = Date.now()
    if (now - this.lastFireAt < ORDER_COOLDOWN_MS) return
    this.lastFireAt = now
    const lotTxt = this.sym.lots ? `${qty / this.sym.lotsize}L (${qty})` : qty
    const summary = `${side} ${type} ${lotTxt} ${this.sym.symbol}${type === 'MARKET' ? '' : ` @ ${this.fmt(px)}`} · ${this.product}`
    try {
      const r = await this.trade.place({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        side,
        type,
        qty,
        product: this.product as 'CNC' | 'NRML' | 'MIS',
        price: type === 'MARKET' ? undefined : px,
        triggerPrice: type === 'SL' || type === 'SL-M' ? px : undefined,
        mode: this.tradeMode(),
      })
      this.toast(`placed ${summary} (id ${r.orderId})`, 'ok')
      this.pollBook()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /**
   * Place the order a ticket confirmed, through the same feed the armed path
   * uses. The feed asserts the page's mode against the server before it
   * posts, so a disarmed click has the same refusal an armed one has when
   * the badge says live and the server has been switched to analyzer. The
   * caller is the ticket dialog, which shows the thrown message.
   */
  async placeTicket(order: ConfirmedOrder): Promise<{ orderId: string }> {
    // The ticket was refused before it opened; this covers a replay started
    // while it stood open. No toast here: the dialog shows the reason.
    if (this.tradingLocked()) throw new Error(this.tradingLockMessage())
    if (!this.trade) throw new Error('trading is not available')
    const stop = order.pricetype === 'SL' || order.pricetype === 'SL-M'
    try {
      const r = await this.trade.place({
        symbol: order.symbol,
        exchange: order.exchange,
        side: order.action,
        type: order.pricetype,
        qty: order.quantity,
        product: order.product,
        price: order.pricetype === 'MARKET' ? undefined : order.price,
        triggerPrice: stop ? order.trigger_price : undefined,
        mode: this.tradeMode(),
      })
      this.pollBook()
      return { orderId: r.orderId }
    } catch (e) {
      throw new Error(this.cleanError(e))
    }
  }

  async exitPosition() {
    if (this.refuseWhileReplaying()) return
    if (!this.trade || !this.position || !this.sym) return
    const qty = Math.abs(this.position.net)
    const side: OrderSide = this.position.net > 0 ? 'SELL' : 'BUY'
    try {
      // Square off with a plain market placeorder (opposite side, position qty) —
      // never placesmartorder.
      await this.trade.place({
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        side,
        type: 'MARKET',
        qty,
        product: (this.position.product || this.product) as 'CNC' | 'NRML' | 'MIS',
        mode: this.tradeMode(),
      })
      this.toast('position closed', 'ok')
      this.pollBook()
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /* ── chart build + interaction wiring ─────────────────────────────────── */
  private profileBlockMinutes(): number {
    return readProfileSettings('tpo', this.chartSettingsSaved).blockMinutes
  }

  private compatibleProfileInterval(kind: ProfileKind): string | null {
    return selectProfileInterval(
      kind,
      this.interval,
      this.profileBlockMinutes(),
      this.availableIntervals
    )
  }

  private hideProfileSeries(): void {
    if (!isProfileKind(this.ctype)) return
    // Retain OHLC data for the timeline, crosshair, replay and visible autoscale.
    this.price?.applyOptions({
      visible: true,
      bodyVisible: false,
      borderVisible: false,
      wickVisible: false,
    })
    this.volume?.applyOptions({ visible: false })
  }

  private installProfile(): void {
    this.offProfileObject?.()
    this.offProfileObject = null
    this.profileLayer?.dispose()
    this.profileLayer = null
    const chart = this.chart
    const price = this.price
    const kind = this.ctype
    if (!chart || !price || !isProfileKind(kind) || this.destroyed) return
    const settings = readProfileSettings(kind, this.chartSettingsSaved)
    const context = {
      tickSize: this.tick(),
      exchange: this.sym?.exchange ?? 'NSE',
      timezone: chart.timezone(),
      intervalSeconds: intervalSeconds(this.interval) ?? 300,
      priceScale: () => price.priceScale(),
    }
    this.hideProfileSeries()
    this.profileLayer = new ProfileLayer({
      host: {
        addPrimitive: (primitive) => chart.addPrimitive(primitive, 0),
        removePrimitive: (primitive) => chart.removePrimitive(primitive),
      },
      load: async () => {
        const { createChartProfile } = await import('./chartProfiles')
        return createChartProfile(kind, settings, context)
      },
      // getData includes the current partial replay bar; rawBars includes future bars.
      readBars: () => price.getData(),
      onError: (error) =>
        this.toast(`Profile could not be rendered: ${this.cleanError(error)}`, 'err'),
      onWarning: (message) => this.toast(message, ''),
    })
    this.offProfileObject =
      this.objects?.register(profileObjectProvider(kind, () => this.requestChartSettings())) ?? null
  }

  /** Open the pane-owned chart dialog from the canvas or object inventory. */
  private requestChartSettings(): void {
    void this.chartSettings().then((request) => {
      if (request) this.cb.onChartSettings?.(request)
    })
  }

  /** Reuse the existing pane editors for every built-in object settings action. */
  private openObjectSettings(object: ChartObjectSnapshot): void {
    if (object.kind === 'source') {
      this.requestChartSettings()
      return
    }
    if (object.kind === 'indicator') {
      this.openIndicatorSettings(object.sourceId)
      return
    }
    if (object.kind === 'drawing') {
      this.objects?.select(object.id)
      if (this.isTextDrawing(object.sourceId)) this.requestDrawTextEdit(object.sourceId)
    }
  }

  /** Install one inventory for exactly one chart generation. */
  private installObjects(): void {
    const chart = this.chart
    if (!chart || this.destroyed) return
    const objects = new ChartObjects(chart, {
      drawings: this.objectDrawings,
      onSettings: (object) => this.openObjectSettings(object),
    })
    this.objects = objects
    this.cb.onObjectsChange?.(objects)
  }

  /** Release inventory observations before any object or chart it reads. */
  private detachObjects(): void {
    const objects = this.objects
    this.objects = null
    this.cb.onObjectsChange?.(null)
    this.offProfileObject?.()
    this.offProfileObject = null
    objects?.destroy()
  }

  private buildChart() {
    this.legendTime = null
    this.stopReplay()
    this.comparisons?.detach()
    this.detachAlerts()
    this.detachObjects()
    this.profileLayer?.dispose()
    this.profileLayer = null
    // Snapshot drawings before the chart they live on goes away.
    this.detachDrawing()
    this.offBranding?.()
    this.offBranding = null
    if (this.chart) this.chart.destroy()
    // The primitives registered here belonged to the chart just destroyed.
    this.screenshotExcluded.length = 0
    this.container.innerHTML = ''
    const { mode, appMode } = this.getTheme()
    const theme = buildChartTheme(mode, appMode)
    this.chartTheme = theme
    this.chart = createChart(this.container, {
      priceAxisWidth: 78,
      theme,
      // No `navigation` override. The engine's default is `mousePan: 'both'`,
      // and this used to pin it to `'horizontal'`, so dragging the plot moved
      // through time and never through price. It was set with the 2.4.5
      // integration and carried no reason beside it, which is how it survived
      // three upgrades: nothing reads as wrong about a line that states a
      // default, and this one stated the opposite of it.
      //
      // The setting is the trader's either way. The engine exposes it in chart
      // settings as "Mouse drag" under Navigation, and `restoreChartSettings`
      // reapplies whatever they chose after every rebuild. Forcing it here also
      // made their choice the one thing a Reset would not return to, because
      // `chartDefaults` is read off the chart just after it is built.
      // Corner clock and bar countdown. Both are off by default in the engine,
      // deliberately: a countdown repaints every second, and on the historical
      // range a chart usually opens on it counts against a bar that closed months
      // ago. A live trading terminal is the case they are for, so this host opts
      // in. The clock reads the exchange's wall time through the chart's
      // configured timezone, which is what a trader is actually watching.
      axisChrome: { sessionClock: { showOffset: true }, barCountdown: true },
      // The library's built-in screenshot command calls its own
      // `downloadScreenshot()`, which knows nothing about this terminal's DOM
      // OHLC readout or its trade panel. Unbind it and claim the same chord for
      // `screenshot()` below, so the keyboard and the toolbar button produce the
      // same image instead of two different ones.
      // Alt+V and Alt+H were bound twice: the engine toggles a grid, the draw
      // tier arms the vertical and horizontal line. Both fired, so one press
      // moved the grid and armed a tool. The drawing tools keep the chords,
      // being the ones a trader reaches for mid-analysis and the ones the rail
      // advertises; the grid stays on the toolbar button and the right-click
      // menu, where it was already reachable.
      // A double-click used to reset the view, which fits every loaded bar and
      // so lands on the oldest one -- which is exactly where the history loader
      // wakes, so the gesture quietly fetched another page. It now maximizes the
      // pane under the pointer instead, and a second press puts the stack back.
      // Reset stays on the toolbar button, the right-click menu and Home.
      doubleClick: 'maximize',
      shortcuts: {
        disabledCommands: ['screenshot', 'toggleGridVert', 'toggleGridHorz'],
        customShortcuts: [
          {
            command: 'app:screenshot',
            label: 'Screenshot (PNG)',
            combos: 'Alt+Shift+KeyS',
            onTrigger: () => {
              void this.screenshot()
            },
          },
        ],
      },
      // The pane's top-left already holds this terminal's own OHLC readout (and
      // the lot line under it). Start the canvas indicator legends below both,
      // or they land underneath and their settings / close buttons cannot be
      // seen or clicked.
      // The corner already holds this terminal's OHLC readout and, below it,
      // the SELL/qty/BUY panel (44 + 42*0.72 ~= 75). Indicator legend rows have
      // to start under both or they land on top of the buttons.
      legendOffset: { top: 80 },
    })
    this.chart.setDataContext(
      this.sym
        ? {
            symbol: this.sym.symbol,
            exchange: this.sym.exchange,
            interval: this.interval,
            hasOpenInterest: this.sym.synthetic
              ? false
              : (this.sym.hasOpenInterest ?? openInterestCapability(this.sym.exchange)),
          }
        : { interval: this.interval }
    )
    this.offBranding = this.chart.on('branding:changed', () => {
      this.cb.onBrandingChange?.(this.brandingLink())
    })
    this.cb.onBrandingChange?.(this.brandingLink())
    const cfg = CHART_TYPES[this.ctype] || CHART_TYPES.candlestick
    const dp = this.dp()
    const style: SeriesStyle = cfg.baseline
      ? { baseValue: this.rawBars.reduce((s, b) => s + b.close, 0) / (this.rawBars.length || 1) }
      : {}
    // The marker layer is bound to the series it was made from, so a rebuilt
    // series leaves it pointing at one the chart no longer draws: the marks
    // vanish and nothing can take them down or put them back. Dropped here so
    // the next run makes a fresh one against the series that now exists.
    this.btMarkers = null
    this.price = this.chart.addSeries(cfg.series as SeriesType, {
      style,
      priceFormat: { type: 'custom', formatter: (p: number) => p.toFixed(dp) },
    })
    // Tell the engine the instrument's tick. Without it the price scale treats
    // `minMove: 0` as "infer precision from the visible range", so RELIANCE at a
    // 0.05 tick renders a decimal short, drawings snap to an invented grid, and
    // an indicator asking `ctx.tickSize` is told nobody knows. The value is the
    // same one this host already formats and snaps orders with.
    const tick = this.tick()
    if (tick > 0) this.chart.setPriceScaleOptions({ minMove: tick })
    // Volume rides an OVERLAY price scale inside the price pane rather than a
    // pane of its own: it autoscales independently but draws no axis, so the
    // right-hand column stays a clean price ladder instead of stacking a second
    // numeric scale beside it. The top margin pins the bars to the bottom fifth.
    this.volume = this.chart.addSeries('histogram', {
      paneIndex: 0,
      priceScaleId: '',
      style: { color: volumeColor(mode, appMode) },
      // Raw share counts run to nine digits; 'volume' renders 1.20M / 3.40B.
      priceFormat: { type: 'volume' },
    })
    this.volume.priceScale().setOptions({ marginTop: 0.82, marginBottom: 0 })
    this.volumeMA = null
    this.displayedVolume = []
    // A rebuild makes a fresh series, so the preference has to be re-applied
    // rather than assumed -- switching chart type or theme would show it again.
    if (!this.volumeOn || !this.volumeAvailable() || isProfileKind(this.ctype))
      this.volume.applyOptions({ visible: false })
    this.installObjects()
    // Same reasoning for the settings patch: a chart-type or theme switch
    // rebuilds the chart, and without this the user's colours, timezone and
    // scale options would silently revert to the engine defaults.
    //
    // The baseline is captured on the line before, and the order is the whole
    // point: one statement later the chart is carrying restored preferences and
    // is no longer a picture of anything's defaults. Synchronous for the same
    // reason -- `restoreChartSettings` and the grid re-apply further down both
    // write to this chart, and an awaited snapshot would land after them.
    this.snapshotChartDefaults()
    if (!this.preparingWorkspace) void this.restoreChartSettings()
    // A theme or chart-type switch throws the old Chart away, so membership has
    // to be re-established against the new one or the pane silently drops out
    // of the group it still believes it is in.
    this.joinLink()
    this.setPriceData()
    if (!this.preparingWorkspace) this.installComparisons()
    this.installProfile()

    this.applyDefaultViewport()

    // No LTP price line of our own. The engine already draws one for the price
    // series: a dashed line across the plot and a filled axis tag, coloured by
    // the forming candle's direction, at the same price. Adding a second put two
    // tags on the same pixel row, which is what made the axis read "24058.65"
    // twice, one printed through the other.
    //
    // The engine's is the one to keep. It reserves its band before the tick
    // ladder is drawn, so the prices either side yield to it instead of being
    // painted over, and it carries the countdown to the bar close. A price line
    // takes part in none of that: its tag is drawn straight onto the strip.
    //
    // The price itself is still needed: the Buy/Sell panel marks it.
    const lp =
      this.lastLtp != null
        ? this.lastLtp
        : this.rawBars.length
          ? this.rawBars[this.rawBars.length - 1].close
          : null

    // inline SELL · qty · BUY panel, docked top-left below the OHLC legend.
    if (!this.sym!.quoteOnly) {
      this.tradeBtns = new BuySellButtons({
        id: 'trade',
        position: 'top-left',
        margin: { x: 14, y: 44 },
        qty: this.qtyChip(),
        scale: 0.72,
      })
      if (lp != null) this.tradeBtns.setMark(lp)
      this.applyTradeColors()
      // Order entry is an affordance, not chart content: it is left out of a
      // saved image (see `screenshotExcluded`).
      this.addExcludedPrimitive(this.tradeBtns, 0)
    } else this.tradeBtns = null

    this.chart.subscribeCrosshairMove((e) => {
      this.legendTime = e.bar?.time ?? null
      this.refreshLegend(this.replayActive() ? (this.price?.getData() ?? []) : this.shownBars)
      if (e.source !== 'linked') this.moveReplayPick(e.index ?? null)
    })

    // Committing the pick on a plain DOM click rather than `subscribeClick`,
    // which reports the primitive that was hit: the shade deliberately hit-tests
    // to nothing so the bar underneath stays reachable, so there is no primitive
    // to report. A click that ends a pan must not count, so a drag of more than
    // a couple of pixels disarms it.
    this.offReplayPointer?.()
    let pressAt: { x: number; y: number } | null = null
    const pointerdown = (ev: Event) => {
      pressAt = { x: (ev as PointerEvent).clientX, y: (ev as PointerEvent).clientY }
    }
    const pointerup = (ev: Event) => {
      const from = pressAt
      pressAt = null
      if (!this.replayPicking || !from) return
      const e = ev as PointerEvent
      if (Math.abs(e.clientX - from.x) > 3 || Math.abs(e.clientY - from.y) > 3) return
      this.commitReplayPick()
    }
    this.container.addEventListener('pointerdown', pointerdown)
    this.container.addEventListener('pointerup', pointerup)
    this.offReplayPointer = () => {
      this.container.removeEventListener('pointerdown', pointerdown)
      this.container.removeEventListener('pointerup', pointerup)
    }

    // drag-to-modify with a drag ghost; commit on release (tick-snapped)
    this.chart.subscribeDrag(
      (id, p) => {
        if (!id.startsWith('order:') || id.endsWith('::close')) return
        // Silent: a refusal toast on every pointer sample would be a wall of them.
        if (this.tradingLocked()) return
        const rec = this.orderLines.get(id.slice(6))
        if (!rec) return
        if (rec.dragFrom == null) {
          rec.dragFrom = rec.line.price
          rec.line.setDragGhost(rec.dragFrom)
        }
        rec.line.setPrice(this.snap(p))
      },
      (id, p) => {
        if (!id.startsWith('order:') || id.endsWith('::close')) return
        // The release is the modify, so this is the one that must refuse.
        if (this.refuseWhileReplaying()) return
        const oid = id.slice(6)
        const rec = this.orderLines.get(oid)
        if (!rec) return
        rec.line.setDragGhost(null)
        rec.dragFrom = null
        const px = this.snap(p)
        const stop = rec.order.type === 'SL' || rec.order.type === 'SL-M'
        this.trade!.modify(oid, stop ? { triggerPrice: px } : { price: px })
          .then(() => this.pollBook())
          .catch((e) => {
            this.toast(this.cleanError(e), 'err')
            this.pollBook()
          })
      }
    )
    this.chart.subscribeClick((id) => {
      if (id === 'trade:buy') return void this.placeFromMenu('BUY', 'MARKET')
      if (id === 'trade:sell') return void this.placeFromMenu('SELL', 'MARKET')
      if (id === 'position::close') return void this.exitPosition()
      if (id.startsWith('order:') && id.endsWith('::close')) {
        if (this.refuseWhileReplaying()) return
        const oid = id.slice(6, -7)
        this.trade!.cancel(oid)
          .then(() => {
            this.toast(`order ${oid} cancelled`, 'ok')
            this.pollBook()
          })
          .catch((e) => this.toast(this.cleanError(e), 'err'))
      }
    })
    if (this.cb.onContextMenu) {
      this.chart.on('contextmenu', (payload) => this.showContextMenu(payload as ContextMenuEvent))
    }

    this.orderLines.clear()
    this.posLine = null
    this.position = null
    if (this.trade && this.sym) this.pollBook()
    this.refreshLegend()

    // Re-apply everything the rebuild just discarded.
    this.chart.setGridOptions({ vertLines: this.gridV, horzLines: this.gridH })
    if (!this.preparingWorkspace) {
      this.chartToolsReady = this.restoreChartContent(this.chart)
    }
    // The gear on an indicator's legend row. openalgo-charts is canvas-only and
    // ships no DOM, so it emits and the host renders the form.
    this.chart.on('indicatorSettings', (p) => {
      void this.emitIndicatorSettings((p as { instanceId: string }).instanceId)
    })
    // The braces beside the gear. The chart holds no code and no DOM, so it
    // names the indicator and we turn that back into the file it was compiled
    // from. An id that is not one of ours resolves to null and nothing opens,
    // which is what a built-in study should do if a button ever reaches here.
    this.chart.on('indicatorSource', (p) => {
      const file = fileForScriptId(String((p as { indicatorId?: unknown }).indicatorId ?? ''))
      if (file !== null) this.cb.onOpenScriptSource?.(file)
    })
    // The on-chart legend's x removes an indicator without going through this
    // class. Without this the toolbar list went stale, and worse, the tracked
    // list still held it — so the next rebuild (timeframe, chart type, theme)
    // brought the deleted indicator back.
    this.chart.on('indicatorRemoved', () => this.syncIndicators())
    // Visibility changes made from the Objects panel stay with the pane on a
    // chart rebuild, just like settings and removal from the canvas legend.
    this.chart.on('objects:change', () => this.syncIndicators())
    // Scrolling back past the loaded range pages in older bars.
    this.chart.setHistoryLoader(() => void this.loadOlderHistory())

    // Where an indicator gets another instrument's bars (openalgo-charts
    // 2.4.0). A relative-strength or beta study is a ratio against a benchmark,
    // and the engine is handed one symbol's history and owns no transport, so
    // it asks and the host answers.
    //
    // It answers through the terminal's OWN cached feed rather than a second
    // request path, which is what makes this cheap and correct: the same
    // broker session, the same bar cache, and the same rule about never
    // serving a forming bar from it. Nothing about the key reaches a chart
    // setting, so a saved layout carries the study's symbol and no credential.
    this.chart.setBarsProvider(async (request) => {
      const feed = this.cachedBars ?? this.rest
      if (!feed) return []
      const bars = await feed.getBars({
        symbol: request.symbol,
        // An indicator naming only a symbol means "on this chart's exchange",
        // which is the common case for a benchmark on the same venue.
        exchange: request.exchange ?? this.sym?.exchange ?? '',
        interval: request.interval,
        from: request.from,
        to: request.to,
        signal: request.signal,
      })
      return bars
    })
  }

  /** Safe link metadata for the active chart branding, if it supplies a destination. */
  brandingLink(): BrandingLink | null {
    const options = (
      this.chart as unknown as {
        brandingOptions?(): false | { href?: string; label?: string }
      } | null
    )?.brandingOptions?.()
    if (!options || typeof options.href !== 'string' || !/^https?:\/\//i.test(options.href))
      return null
    const label =
      typeof options.label === 'string' && options.label.trim()
        ? options.label.trim()
        : 'Chart branding'
    return { href: options.href, label }
  }

  /**
   * Rehydrate drawings, indicators, magnet and grid from this pane's own
   * storage slot. Anything malformed is dropped rather than thrown — a stale
   * entry must never stop the terminal booting.
   */
  private restoreChartTools(): void {
    try {
      const raw = this.lsGet('alerts')
      if (raw) this.alertJson = parseAlertsDocument(JSON.parse(raw))
    } catch {
      this.toast('Saved alerts could not be restored. Check the saved document.', 'err')
    }
    try {
      const raw = this.lsGet('draw')
      const parsed: unknown = raw ? JSON.parse(raw) : null
      if (Array.isArray(parsed)) {
        // A 1.9.x save. The migration lives in the draw tier, which is fetched
        // on first use, so the array cannot be lifted here without bundling the
        // tier for every pane. It is held apart from `drawJson` so nothing reads
        // its entries through the version 2 type (their text still sits in the
        // style bag, where `describeDrawings` would not find it) until
        // `attachDrawing` migrates it. The migration reads the array as-is, so
        // wrapping it in a version 2 envelope would gain nothing.
        if (parsed.length) {
          this.drawLegacy = parsed
          this.drawEnabled = true
        }
      } else if (isDrawingsDocument(parsed) && parsed.drawings.length) {
        this.drawJson = parsed
        this.drawEnabled = true
      }
    } catch {
      /* ignore */
    }
    try {
      const raw = this.lsGet('indicators')
      this.activeIndicators = readStoredIndicators(raw ? JSON.parse(raw) : [])
    } catch {
      /* ignore */
    }
    this.drawMagnet = this.lsGet('magnet') === '1'
    const magnetMode = this.lsGet('magnet-mode')
    this.drawMagnetMode =
      magnetMode === 'weak' || magnetMode === 'strong' || magnetMode === 'off'
        ? magnetMode
        : this.drawMagnet
          ? 'strong'
          : 'off'
    this.drawMagnet = this.drawMagnetMode !== 'off'
    this.drawStay = this.lsGet('stay') === '1'
    const grid = this.lsGet('grid')
    if (grid && grid.length === 2) {
      this.gridV = grid[0] === '1'
      this.gridH = grid[1] === '1'
    }
    // Absent means shown: only an explicit '0' hides it, so existing panes and
    // a first visit both keep volume.
    this.volumeOn = this.lsGet('vol') !== '0'
    try {
      const raw = this.lsGet('chartsettings')
      const parsed = raw ? (JSON.parse(raw) as Record<string, string | number | boolean>) : null
      if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
        this.chartSettingsSaved = parsed
      }
    } catch {
      /* ignore */
    }
  }

  /**
   * Page in the bars before the oldest one loaded, when the user scrolls back
   * to the left edge. The chart raises this once and waits for
   * `historyLoadComplete`, so every exit has to report back or paging stops for
   * the rest of the session.
   */
  private async loadOlderHistory(): Promise<void> {
    const chart = this.chart
    const sym = this.sym
    const interval = this.interval
    const data = this.data
    const rest = this.rest
    const ticket = this.loadTicket
    if (this.destroyed || !chart || chart.isDestroyed) return
    if (this.loadingOlder?.chart === chart && this.loadingOlder.ticket === ticket) return
    if (this.noMoreHistory || (!data && !rest) || !sym) {
      chart.historyLoadComplete()
      return
    }
    const oldest = this.rawBars[0]?.time
    if (oldest === undefined) {
      chart.historyLoadComplete()
      return
    }
    const request = { chart, ticket }
    this.loadingOlder = request
    try {
      if (data) {
        await data.loadMore()
        if (
          this.destroyed ||
          chart.isDestroyed ||
          chart !== this.chart ||
          ticket !== this.loadTicket ||
          sym !== this.sym ||
          interval !== this.interval ||
          data !== this.data
        )
          return
        this.applyDataSnapshot(data.getState())
        return
      }
      const to = oldest - 1
      const older = await rest!.getBars({
        symbol: sym.symbol,
        exchange: sym.exchange,
        interval,
        from: to - lookbackDays(interval) * 86400,
        to,
      })
      if (
        this.destroyed ||
        chart.isDestroyed ||
        chart !== this.chart ||
        ticket !== this.loadTicket ||
        sym !== this.sym ||
        interval !== this.interval ||
        rest !== this.rest
      )
        return
      // Trust nothing about the window the broker actually returned: keep only
      // what is genuinely older, or a re-sent overlapping page would duplicate
      // bars and grow rawBars without ever moving the left edge.
      const fresh = older.filter((b) => b.time < oldest)
      if (fresh.length === 0) {
        this.noMoreHistory = true
        return
      }
      // Prepending shifts every logical index by the inserted count, so the
      // view has to shift with it or the user is thrown back to the right edge
      // mid-scroll.
      const before = chart.getVisibleLogicalRange()
      const countBefore = this.shownCount
      this.rawBars = [...fresh, ...this.rawBars]
      this.setPriceData()
      // Measure the shift rather than assuming it is fresh.length: a
      // movement-driven chart type (Renko, P&F) turns raw bars into a different
      // number of elements, so the axis grows by its own amount.
      const inserted = this.shownCount - countBefore
      if (before && inserted > 0) {
        chart.setVisibleLogicalRange({
          from: before.from + inserted,
          to: before.to + inserted,
        })
      }
    } catch (e) {
      // A failed page must not poison the session; the next scroll retries.
      console.error('[trading] history paging', e)
    } finally {
      // An old page can finish after another chart or load started paging.
      // Release only its own work, never the newer request's loading state.
      if (this.loadingOlder === request) this.loadingOlder = null
      if (!this.destroyed && !chart.isDestroyed && this.loadingOlder?.chart !== chart) {
        chart.historyLoadComplete()
      }
    }
  }

  /* ── drawing tools (additive: the trading controls above are untouched) ── */

  /**
   * Snapshot the drawings and drop the controller. Called before the chart is
   * rebuilt and on destroy — the anchors are data, so they survive as JSON and
   * come back on the next chart.
   */
  private detachDrawing(): void {
    if (!this.draw) return
    const draw = this.draw
    try {
      this.drawJson = draw.toJSON()
      draw.destroy()
    } catch {
      /* chart already gone; keep the last snapshot we have */
    }
    this.objectDrawings.detach(draw)
    this.draw = null
  }

  /**
   * Attach the drawing tier to the current chart, fetching it on first use so a
   * pane that never draws never pays for the bundle.
   */
  private async attachDrawing(): Promise<void> {
    if (this.draw || !this.chart) return
    const chart = this.chart
    const {
      DrawingController,
      drawingShortcuts,
      getDrawingTool,
      keyToDrawingAction,
      matchDrawingShortcut,
      migrateDrawings,
    } = await import('openalgo-charts/draw')
    // The await is a real suspension point: the pane can be destroyed, or the
    // chart rebuilt again, while the tier is in flight.
    if (this.destroyed || this.chart !== chart || this.draw) return
    const draw = new DrawingController(this.chart, {
      magnet: this.drawMagnetMode,
      stayInDrawingMode: this.drawStay,
    })
    this.draw = draw
    this.objectDrawings.attach(draw)
    this.drawShortcuts = drawingShortcuts()
    this.matchShortcut = matchDrawingShortcut
    this.keyAction = keyToDrawingAction
    this.toolOf = getDrawingTool
    if (this.drawLegacy) {
      // The 1.9.x array becomes the document every other reader here expects.
      // Garbage yields an empty document rather than a throw, so a stale entry
      // still cannot stop the pane.
      this.drawJson = migrateDrawings(this.drawLegacy)
      this.drawLegacy = null
    }
    if (this.drawJson.drawings.length) {
      try {
        draw.fromJSON(this.drawJson)
      } catch {
        this.drawJson = emptyDrawings() // a shape from an older build; better empty than broken
      }
    }
    if (this.drawTool) draw.setTool(this.drawTool)
    this.chart.on('draw:tool', () => this.afterDrawChange())
    this.chart.on('draw:select', () => this.afterDrawChange())
    // A text tool is useless until it has text, so placing one asks straight
    // away rather than leaving an empty box on the chart.
    this.chart.on('draw:add', (p) => {
      const d = (p as { drawing?: { id: string; tool: string; text?: { value?: string } } }).drawing
      // Agent markup is exempt: it arrives with its caption already written, so
      // prompting for one would open a dialog nobody asked for, once per shape.
      if (d && TEXT_TOOLS.has(d.tool) && !isAgentDrawingId(d.id)) {
        this.cb.onDrawTextEdit?.({ id: d.id, tool: d.tool, text: d.text?.value ?? '' })
      }
    })
    this.chart.on('draw:add', () => this.afterDrawChange())
    this.chart.on('draw:remove', () => this.afterDrawChange())
    // Double-click a text drawing to open its settings. The chart's own
    // double-click resets the view, which it must not do when the gesture was
    // aimed at a drawing -- editSelectedText() reports whether it claimed it.
    // Double-click a text drawing to open its settings. Saying the press was
    // claimed keeps the chart from also maximizing the pane under it.
    this.chart.on('dblclick', (p) => {
      if (this.editSelectedText()) (p as { handled?: boolean }).handled = true
    })
    this.chart.on('draw:update', () => this.afterDrawChange())
    this.objects?.refresh()
  }

  private afterDrawChange(): void {
    if (!this.draw) return
    this.drawTool = this.draw.activeTool()
    this.drawJson = this.draw.toJSON()
    this.lsSet('draw', JSON.stringify(this.drawJson))
    this.cb.onDrawChange?.(this.drawStats())
    this.cb.onDrawSelect?.(this.drawSelection())
  }

  /** The selected drawing's editable style, or null when nothing is selected. */
  drawSelection(): DrawSelection | null {
    const id = this.draw?.selected()
    if (!this.draw || !id) return null
    const d = this.draw.get(id)
    if (!d) return null
    return {
      id: d.id,
      tool: d.tool,
      hasText: TEXT_TOOLS.has(d.tool),
      color: d.style.color ?? '#4f8cff',
      lineWidth: d.style.lineWidth ?? 1.5,
      lineStyle: d.style.lineStyle ?? 'solid',
      locked: d.locked === true,
    }
  }

  /** Whether a drawing's content is typed (so the host can offer an edit). */
  isTextDrawing(id: string): boolean {
    const d = this.draw?.get(id)
    return d !== undefined && TEXT_TOOLS.has(d.tool)
  }

  /**
   * Open the selected drawing's text settings, if it is a text-bearing one.
   * Returns whether it did, so a double-click handler knows not to also reset
   * the view. The engine's `dblclick` carries no id -- a press selects first,
   * so the selection is the target.
   */
  editSelectedText(): boolean {
    const id = this.draw?.selected()
    if (!id) return false
    const d = this.draw?.get(id)
    if (!d || !TEXT_TOOLS.has(d.tool)) return false
    this.requestDrawTextEdit(id)
    return true
  }

  /** Ask the host to edit a drawing's text — the style bar's T button. */
  requestDrawTextEdit(id: string): void {
    const d = this.draw?.get(id)
    if (!d || !TEXT_TOOLS.has(d.tool)) return
    this.cb.onDrawTextEdit?.({ id: d.id, tool: d.tool, text: d.text?.value ?? '' })
  }

  /**
   * The current text style of a drawing, for opening its settings populated.
   * Background and border default OFF, matching the engine's own defaults —
   * text dropped on a chart should be the words, not a filled plate.
   */
  /** A tool's default text (placeholder and size), or null when it has none. */
  private toolDefaultText(tool: string): DrawingText | null {
    try {
      return this.toolOf?.(tool).defaultText ?? null
    } catch {
      return null // a tool the registry no longer knows; the engine's default applies
    }
  }

  drawTextStyle(id: string): DrawTextStyle | null {
    const d = this.draw?.get(id)
    if (!d) return null
    const t: Partial<DrawingText> = d.text ?? {}
    const theme = this.chart?.theme()
    const lineColor = d.style.color ?? theme?.lineColor ?? '#4f8cff'
    const plate = d.tool !== 'text' && d.tool !== 'table'
    const backgroundColor =
      t.backgroundColor ??
      (plate
        ? lineColor
        : d.tool === 'table' || t.background === true
          ? (theme?.background ?? '#ffffff')
          : '#434651')
    const plateFill = d.tool === 'callout' || d.tool === 'price-label' ? lineColor : backgroundColor
    const color = t.color ?? (plate ? drawingTextContrast(plateFill) : lineColor)
    return {
      text: t.value ?? '',
      color: drawingColorInput(color),
      // Unset means the tool's own size, which is what the engine paints it at
      // (a price label is 12px, the text tool 14px). Seeding the dialog with a
      // host constant instead would enlarge a label whose caption alone was
      // edited.
      fontSize:
        t.fontSize ??
        this.toolDefaultText(d.tool)?.fontSize ??
        (d.tool === 'price-label' ? 12 : DRAWING_TEXT_PX),
      bold: t.bold === true,
      italic: t.italic === true,
      background: d.tool !== 'text' || t.background === true,
      backgroundColor: drawingColorInput(backgroundColor),
      border: d.tool === 'table' ? t.border !== false : t.border === true,
      borderColor: drawingColorInput(t.borderColor ?? lineColor),
      wrap: t.wrap === true,
    }
  }

  /**
   * Apply the text dialog's result. Empty text removes the drawing rather than
   * leaving an invisible box behind, the same rule `setDrawingText` follows.
   */
  applyDrawText(id: string, v: DrawTextStyle): void {
    if (!this.draw) return
    const trimmed = v.text.trim()
    if (trimmed === '') {
      this.draw.remove(id)
      this.afterDrawChange()
      return
    }
    const initial = this.drawTextStyle(id)
    if (!initial) return
    // Preserve absent overrides so content edits retain renderer defaults and
    // continue following future theme changes. Font colour belongs to text.
    const text: DrawingText = { value: trimmed }
    if (v.color !== initial.color) text.color = v.color
    if (v.fontSize !== initial.fontSize) text.fontSize = v.fontSize
    if (v.bold !== initial.bold) text.bold = v.bold
    if (v.italic !== initial.italic) text.italic = v.italic
    if (v.background !== initial.background) {
      text.background = v.background
      if (v.background) text.backgroundColor = v.backgroundColor
    }
    if (v.backgroundColor !== initial.backgroundColor) text.backgroundColor = v.backgroundColor
    if (v.border !== initial.border) text.border = v.border
    if (v.borderColor !== initial.borderColor) text.borderColor = v.borderColor
    if (v.wrap !== initial.wrap) text.wrap = v.wrap
    this.draw.update(id, { text })
    this.afterDrawChange()
  }

  /** Set a drawing's text. Empty text removes it rather than leaving a blank. */
  setDrawingText(id: string, text: string): void {
    if (!this.draw) return
    const trimmed = text.trim()
    if (trimmed === '') this.draw.remove(id)
    else this.draw.update(id, { text: { value: trimmed } })
    this.afterDrawChange()
  }

  /**
   * Restyle every selected drawing (colour, width, dash, lock). The style bar
   * shows the primary's values, but a shift-click selection is one edit to the
   * operator, so the patch lands on all of it as one undo entry.
   */
  styleSelectedDrawing(patch: {
    color?: string
    lineWidth?: number
    lineStyle?: 'solid' | 'dashed' | 'dotted'
    locked?: boolean
  }): void {
    const ids = this.draw?.selection() ?? []
    if (!this.draw || ids.length === 0) return
    const { locked, ...style } = patch
    const fields: DrawingPatch = {}
    if (Object.keys(style).length > 0) fields.style = style
    if (locked !== undefined) fields.locked = locked
    if (Object.keys(fields).length > 0) {
      this.draw.updateMany(ids.map((id) => ({ id, patch: fields })))
    }
    this.afterDrawChange()
  }

  /** Arm a drawing tool, or pass null to return to the cursor. */
  async setDrawTool(id: string | null): Promise<void> {
    this.drawEnabled = true
    this.drawTool = id
    await this.attachDrawing()
    this.draw?.setTool(id)
    this.cb.onDrawChange?.(this.drawStats())
  }

  /** Toolbar state: counts and what is currently possible. */
  /**
   * Arm the tool bound to this key event, reporting whether one matched so the
   * caller can swallow the key. The tier owns the chord table, so this is a
   * no-op until drawing has been attached.
   */
  handleDrawKey(e: {
    key: string
    altKey?: boolean
    ctrlKey?: boolean
    metaKey?: boolean
    shiftKey?: boolean
  }): boolean {
    if (this.alertDialogOpen()) return false
    const id = this.matchShortcut?.(e) ?? null
    if (id !== null) {
      void this.setDrawTool(id)
      return true
    }
    const d = this.draw
    if (!d || !this.keyAction) return false
    const action = this.keyAction(e, {
      hasSelection: d.selected() !== null,
      // The host tracks no hover target of its own, so a key acts on the
      // selection alone; a press selects first, which is what makes Delete
      // reach the drawing the user just clicked.
      hasTarget: false,
      editingText: false,
      placing: d.activeTool() !== null,
    })
    if (!action) return false
    const targets = [...d.selection()]
    switch (action.type) {
      case 'delete':
        if (targets.length === 0) return false
        d.removeMany(targets)
        break
      case 'undo':
        d.undo()
        break
      case 'redo':
        d.redo()
        break
      case 'duplicate':
        if (targets.length === 0) return false
        d.duplicate(targets)
        break
      case 'nudge':
        if (targets.length === 0) return false
        d.nudge(targets, action.dx ?? 0, action.dy ?? 0)
        break
      // cancel, finish and popAnchor belong to placement, which the rail's
      // own Escape already ends; copy, cut and paste are the clipboard's.
      default:
        return false
    }
    this.afterDrawChange()
    return true
  }

  drawStats(): DrawStats {
    const d = this.draw
    return {
      // A 1.9.x save counts its raw entries until the tier lifts it: the same
      // number the rail showed for that save before the upgrade.
      count: d ? d.drawings().length : (this.drawLegacy?.length ?? this.drawJson.drawings.length),
      canUndo: d ? d.canUndo() : false,
      canRedo: d ? d.canRedo() : false,
      hasSelection: d ? d.selected() !== null : false,
      magnet: this.drawMagnet,
      stay: this.drawStay,
      tool: this.drawTool,
      shortcuts: this.drawShortcuts,
    }
  }

  undoDraw(): void {
    this.draw?.undo()
    this.afterDrawChange()
  }

  redoDraw(): void {
    this.draw?.redo()
    this.afterDrawChange()
  }

  /** Remove every selected drawing, or every drawing when `all` is set. */
  removeDrawings(all: boolean): void {
    if (!this.draw) return
    if (all) this.draw.clear()
    else {
      const ids = this.draw.selection()
      if (ids.length) this.draw.removeMany(ids)
    }
    this.afterDrawChange()
  }

  /** Snap drawing anchors to the hovered bar's O/H/L/C. */
  setMagnet(on: boolean): void {
    this.drawMagnet = on
    this.drawMagnetMode = on ? 'strong' : 'off'
    this.draw?.setOptions({ magnet: on })
    this.lsSet('magnet', on ? '1' : '0')
    this.lsSet('magnet-mode', this.drawMagnetMode)
    this.cb.onDrawChange?.(this.drawStats())
  }

  /**
   * Keep the armed tool after a placement, instead of returning to the cursor.
   * Drawing three trend lines is three picks otherwise, and the rail resetting
   * itself reads as the click having failed rather than as the tool having
   * done its one job.
   */
  setDrawStay(on: boolean): void {
    this.drawStay = on
    this.draw?.setOptions({ stayInDrawingMode: on })
    this.lsSet('stay', on ? '1' : '0')
    this.cb.onDrawChange?.(this.drawStats())
  }

  /* The agent view of this chart, and the markup it puts on it. */

  /**
   * What the agent panel reports about this chart, read fresh at send time.
   *
   * Never captured and reused: the operator changes the symbol and then asks
   * about it, so a context snapshotted when the panel mounted would have the
   * agent analysing the instrument they used to be looking at.
   *
   * The shape is the wire's, defined once in `chartContract.ts` against
   * `services/agent/chart_contract.py`, so what is built here is posted as it
   * stands.
   *
   * @returns The context, or null when no instrument is loaded. Null means the
   *   panel sends no context at all and every reading tool says so plainly,
   *   which is better than a context naming an instrument that is not there.
   */
  /**
   * Put a backtest's fills on the price, or take them off.
   *
   * The price series and nothing else, because these mark what a run did to
   * the instrument the chart is showing. An empty list clears them, which is
   * how a panel takes down the previous run before drawing the next: the
   * library replaces the whole set, so a second run does not stack on the
   * first.
   *
   * Answers false when there is no price series yet, so a caller can say the
   * button did nothing rather than appearing to work. A pane that is still
   * loading its history is the ordinary way to reach that.
   */
  setBacktestMarkers(markers: readonly SeriesMarker[]): boolean {
    if (!this.price) return false
    // One layer, kept and reused. `createMarkers` builds a primitive and
    // attaches it, so calling it per run would stack a new layer over the old
    // one every time and the previous run's marks would stay on the chart with
    // nothing able to take them down.
    //
    // `rawBars` is handed over as the fallback because a mark is positioned by
    // the bar under it, and the price series has gaps wherever the feed did: a
    // fill landing in one is dropped without a word, which reads as the
    // backtest having missed a trade it actually took.
    if (!this.btMarkers) this.btMarkers = this.price.createMarkers(() => this.rawBars)
    this.btMarkers.setMarkers(markers)
    return true
  }

  chartContext(): ChartContext | null {
    const chart = this.chart
    if (!chart || !this.sym) return null

    // The live controller when the tier is up, its snapshot when it is not: a
    // pane whose drawings were restored from storage but never touched has
    // drawings to report and no controller to ask.
    const drawings = this.draw ? this.draw.toJSON().drawings : this.drawJson.drawings
    const { drawings: mine, agentGroups } = describeDrawings(drawings)

    // The viewport in seconds rather than in logical indices, because that is
    // what the bars the backend fetches are keyed by. indexToTimeFloat answers
    // for a fractional index and for one past the last bar, which is exactly
    // where a right edge sits.
    const range = chart.getVisibleLogicalRange()
    const layer = chart.dataLayer
    const from = Number(layer.indexToTimeFloat(range.from))
    const to = Number(layer.indexToTimeFloat(range.to))
    const last = this.rawBars[this.rawBars.length - 1]

    return {
      symbol: this.sym.symbol,
      exchange: this.sym.exchange,
      interval: this.interval,
      chart_type: this.ctype,
      bars_loaded: this.rawBars.length,
      visible_bars: Math.max(0, Math.round(range.to - range.from)),
      visible_from: Number.isFinite(from) ? Math.round(from) : null,
      visible_to: Number.isFinite(to) ? Math.round(to) : null,
      last_price: this.lastLtp ?? last?.close ?? null,
      indicators: this.listIndicators(),
      drawings: mine,
      agent_groups: agentGroups,
    }
  }

  /**
   * Apply one turn's chart commands.
   *
   * Queued rather than run on arrival. Attaching the drawing tier is a dynamic
   * import, so two frames landing close together would both await it and race
   * to draw into a controller that did not exist when either of them started;
   * chaining onto the previous promise makes the second wait for the first and
   * keeps the ops in the order the model sent them. A failure is swallowed
   * into the chain rather than rejecting it, so one bad frame cannot wedge
   * every later turn.
   *
   * @param commands - The `commands` list from one chart_command frame.
   * @returns Resolves once these commands have been applied.
   */
  applyChartCommands(commands: AgentChartCommand[]): Promise<void> {
    this.chartCommandQueue = this.chartCommandQueue
      .then(() => this.runChartCommands(commands))
      .catch((e) => {
        console.error('[trading] chart command', e)
      })
    return this.chartCommandQueue
  }

  private async runChartCommands(commands: AgentChartCommand[]): Promise<void> {
    if (this.destroyed || commands.length === 0) return

    // The two halves of the vocabulary land on two different surfaces: an
    // indicator is not a drawing, and a clear must never reach one.
    const indicators = commands.filter((c) => c.op === 'indicator')
    const rest = commands.filter((c) => c.op !== 'indicator')
    if (indicators.length) await this.runIndicatorCommands(indicators)
    if (this.destroyed || rest.length === 0) return

    // Agent markup is a drawing control being used, so the tier is fetched the
    // same way arming a tool fetches it.
    this.drawEnabled = true
    await this.attachDrawing()
    if (this.destroyed || !this.draw) return
    // Every add and remove emits its own event, and afterDrawChange is already
    // bound to those, so persistence and the rail's counter follow from this
    // without a second write here.
    applyChartCommands(this.draw, commands, { anchorTime: this.rawBars.at(-1)?.time })
  }

  /**
   * Add or remove the indicators the agent asked for.
   *
   * The decision is `chartContract.applyIndicatorCommands`, which is pure and
   * testable without a chart; this supplies the live tier and persists the
   * result. `loadIndicators` runs first so the operator's own modules from
   * `strategies/indicators/` have registered: the id is checked against the
   * chart's OWN registry, which is what lets a custom indicator be added by a
   * name no list on the server has ever heard of.
   */
  private async runIndicatorCommands(commands: AgentChartCommand[]): Promise<void> {
    await this.loadIndicators()
    if (this.destroyed) return
    const { hasIndicator } = await import('openalgo-charts')
    // Two awaits above, and the terminal can be torn down inside either, so the
    // chart is re-checked rather than asserted.
    if (this.destroyed || !this.chart) return
    const chart = this.chart

    const changed = applyIndicatorCommands(
      {
        indicators: () => chart.indicators(),
        addIndicator: (id, settings) => chart.addIndicator(id, settings),
        // The same call `removeIndicatorById` makes for the dialog's Remove,
        // so the agent's removal and the operator's are one behaviour.
        removeIndicator: (instanceId) => {
          chart.removeIndicator(instanceId)
        },
        hasIndicator,
      },
      commands
    )
    if (changed) this.syncIndicators()
  }

  /* ── indicators + grid (top-menu extras) ───────────────────────────────── */

  /** The registered indicator catalogue, loading the tier on first use. */
  async indicatorCatalog(): Promise<{ id: string; name: string; category: string }[]> {
    await this.loadIndicators()
    const { registeredIndicators } = await import('openalgo-charts')
    return registeredIndicators().map((d) => ({
      id: d.id,
      name: d.name,
      category: d.category ?? 'Other',
    }))
  }

  private async loadIndicators(): Promise<void> {
    // The built-in tier is a static bundle: import it once.
    if (!this.indicatorsLoaded) {
      await import('openalgo-charts/indicators')
      this.indicatorsLoaded = true
    }
    // The user's own modules are re-checked on every call, which is what makes a
    // newly added indicator appear on the next picker open rather than after a
    // page reload. The loader skips anything it has already imported, so a
    // repeat call costs one small JSON fetch. They register after the built-in
    // tier, so a module reusing a built-in id overrides it, not the reverse.
    const { loadCustomIndicators } = await import('./customIndicators')
    const custom = await loadCustomIndicators({
      // Raised while the indicator is running rather than while loading: a
      // `calc` whose columns do not line up with the bars draws nothing and
      // throws nothing, so this is the only place a user would hear about it.
      onProblem: (message) => this.toast(message, 'err'),
    })
    // A broken user file must not take the picker down with it, but it must not
    // fail silently either: without this the indicator is simply absent and
    // there is nothing anywhere to say why.
    for (const err of custom.errors) this.toast(`${err.file}: ${err.message}`, 'err')

    // The trader's OpenScript sources, compiled here and registered the same
    // way. After the custom modules so that neither tier can be shadowed by a
    // half-loaded one above it, and on every call for the same reason the
    // custom loader runs on every call: a script saved from the panel appears
    // on the next picker open rather than after a reload. A script already
    // compiled at its current modification time costs nothing.
    const studies = await loadOpenScriptStudies()
    // A script that will not compile is the one thing a trader cannot discover
    // any other way: there is no build step between saving and running, so this
    // toast is the compiler's only route to the person who wrote the mistake.
    for (const err of studies.errors) this.toast(`${err.file}: ${err.message}`, 'err')
  }

  /**
   * Register just what `ids` need, so a saved layout can be restored now.
   *
   * loadIndicators is the whole catalogue, which the picker needs and a restore
   * does not. With a folder of hundreds of user modules, waiting for all of them
   * held every saved indicator, built-in ones included, back for seconds on each
   * reload. A restore needs the built-in tier, the user modules that provide the
   * ids it holds (the loader knows which from what those modules registered on
   * earlier loads), and the OpenScript studies only when the layout holds one.
   * The rest of the catalogue follows in the background: see
   * completeIndicatorCatalogue.
   */
  private async loadIndicatorsFor(ids: readonly string[]): Promise<void> {
    if (!this.indicatorsLoaded) {
      await import('openalgo-charts/indicators')
      this.indicatorsLoaded = true
    }
    if (ids.length === 0) return

    const { ensureCustomIndicators } = await import('./customIndicators')
    const custom = await ensureCustomIndicators(ids, {
      onProblem: (message) => this.toast(message, 'err'),
    })
    for (const err of custom.errors) this.toast(`${err.file}: ${err.message}`, 'err')

    if (ids.some((id) => fileForScriptId(id) !== null)) {
      const studies = await loadOpenScriptStudies()
      for (const err of studies.errors) this.toast(`${err.file}: ${err.message}`, 'err')
    }
  }

  /**
   * Load the whole catalogue once the chart is on screen, so the picker opens
   * without waiting. Run when the browser is idle so it never competes with the
   * first paint of the chart, and never awaited: its problems are reported by
   * loadIndicators itself, the same toasts the picker would have raised.
   */
  private completeIndicatorCatalogue(): void {
    if (this.destroyed) return
    const run = () => {
      if (!this.destroyed) void this.loadIndicators().catch(() => {})
    }
    // Called on the global itself: a browser refuses requestIdleCallback detached
    // from window with an illegal invocation.
    const host = globalThis as { requestIdleCallback?: (cb: () => void) => number }
    if (typeof host.requestIdleCallback === 'function') host.requestIdleCallback(run)
    else setTimeout(run, 0)
  }

  /** Restore sources before the evaluator validates their saved identities. */
  private async restoreChartContent(chart: ChartInstance): Promise<void> {
    if (this.activeIndicators.length) await this.applyIndicators()
    if (this.destroyed || chart !== this.chart) return
    if (this.drawEnabled) await this.attachDrawing()
    if (this.destroyed || chart !== this.chart) return
    chart.setAlertState(this.alertJson)
    this.attachAlerts(chart)
    // The restore needed only its own studies; the picker needs everything.
    this.completeIndicatorCatalogue()
  }

  private attachAlerts(chart: ChartInstance): void {
    if (this.alerts || this.destroyed || this.chart !== chart) return
    // An alert that has fired or expired keeps its record and loses its line.
    //
    // The line is what a trader asked the engine to draw until something
    // happened; once it has, the line is a level nothing is watching, and a
    // chart carrying a week of them is a chart somebody stops reading. The
    // record stays, which is the part that matters: a once-only alert that has
    // fired must be restored as fired, or it re-arms on the next reload and
    // fires again on a price it already reported.
    //
    // Deleting the alert to be rid of the line is the mistake this replaces.
    // This terminal restores an alert's definition and its runtime state from
    // separate places, so a removed record lets the definition come back armed;
    // `terminalAlerts.test.ts` holds that. `spentLines` is the engine's own
    // answer, opt-in per host, and it changes nothing about evaluation.
    this.alerts = new AlertController(chart, {
      drawings: this.objectDrawings,
      spentLines: 'hide',
    })
    this.syncAlertPause()
    // Persist, and tell the page. A list built from the controller is a copy
    // taken at render time, and nothing else would tell it that it is stale.
    const save = () => {
      this.saveAlerts()
      this.cb.onAlertsChanged?.()
      // Arming the first alert on a tab that is already hidden has to wake the
      // feed, and removing the last one has to let it sleep again. Neither is a
      // visibility change, so nothing else would ask.
      this.onVisibilityChange()
    }
    for (const event of [
      'alert:created',
      'alert:updated',
      'alert:removed',
      'alert:triggered',
      'alert:expired',
      'alerts:restored',
      'alerts:checkpoint',
    ]) {
      this.offAlerts.push(chart.on(event, save))
    }
    let fireSequence = 0
    const deliver = (payload: unknown) => {
      const event = payload as AlertEventPayload & { price?: number }
      if (this.alertEvaluationPaused()) return
      const id = String(event.alertId ?? '')
      const alert = this.alerts?.list().find((one) => one.id === id)
      const fired = String(event.title ?? alert?.title ?? 'Alert')
      // The message is filled in against the bar that fired it, so a
      // notification on a locked phone carries the number rather than sending
      // the trader back to the chart to look it up.
      const said = fillAlertMessage(String(event.message ?? ''), this.alertFacts(event)) || fired
      this.toast(said, 'ok')
      const facts = this.alertFacts(event)
      void deliverAlert(
        deliveryOf(alert?.payload),
        {
          title: this.sym?.symbol ? `${this.sym.symbol}: ${fired}` : fired,
          body: said,
          tag: `openalgo-alert-${id || fired}`,
        },
        {
          apiKey: this.apiKey,
          username: this.username,
          // Named once per failure and never retried. These run on a price
          // being reached, and a retry behind a fired alert is a queue that
          // grows while the market moves.
          onProblem: (message) => this.toast(message, 'err'),
        }
      ).then((delivered) => {
        // Written down after the send, so the row can say what actually went
        // out rather than what was asked for. The log is the only record that
        // outlives the tab, and the only thing that answers "the message never
        // arrived, did it even fire" the next morning.
        void reportFire({
          alertId: id,
          title: String(event.title ?? 'Alert'),
          kind: String(alert?.source?.kind ?? 'price'),
          condition: String(alert?.condition ?? ''),
          symbol: this.sym?.symbol ?? '',
          exchange: this.sym?.exchange ?? '',
          interval: this.interval,
          ...(typeof facts.price === 'number' ? { price: facts.price } : {}),
          // The filled message, not the template: a log row reading
          // "crossed {{price}}" is a row nobody can read back.
          message: said,
          delivered,
        })
      })
      // Numbered as well as timed. The time on the event is the source bar's,
      // so two alerts firing on the same bar carry the same one, and a list
      // keyed by time alone would show one of them.
      fireSequence += 1
      this.cb.onAlertFired?.({
        key: `${event.alertId ?? 'alert'}-${fireSequence}`,
        alertId: String(event.alertId ?? ''),
        title: String(event.title ?? 'Alert'),
        message: String(event.message ?? ''),
        symbol: this.sym?.symbol ?? '',
        exchange: this.sym?.exchange ?? '',
        ...(typeof event.price === 'number' ? { price: event.price } : {}),
        firedAt: typeof event.time === 'number' ? event.time : Math.floor(Date.now() / 1000),
      })
    }
    this.offAlerts.push(chart.on('alert:triggered', deliver))
    this.offAlerts.push(chart.on('indicator:alert', deliver))
    // A script's alert that waits for its bar to close. The chart judges a
    // study's alerts once, on a bar's first tick, when such an alert is still
    // withheld, so it never fired live; the study announces the closed bar
    // itself (`openscriptStudies.hostedStudy`) and it is delivered like any
    // other, including being held back while replay or a workspace change owns
    // the chart.
    this.offAlerts.push(chart.on(SCRIPT_ALERT_EVENT, deliver))
    this.offAlerts.push(
      chart.on('alert:error', () => {
        this.toast('An alert condition could not be evaluated. Review its source.', 'err')
      })
    )
    // A dragged line is the one place an alert changes without a form. The
    // engine commits the price under the pointer and leaves the name alone, so
    // this is where both are put right. Bound to the drag's own event rather
    // than to `alert:updated`, so it cannot answer the update it makes itself.
    this.offAlerts.push(
      chart.on('alerts:changed', (payload: unknown) => {
        const id = (payload as { id?: unknown } | undefined)?.id
        if (typeof id === 'string') this.settleDraggedAlert(id)
      })
    )
    this.saveAlerts()
    // The list on the rail can be drawn from here on. The editor's handle is
    // still built per opening, because its tick and drawing tier are read at
    // the moment it opens and this one has to last as long as the chart.
    this.cb.onAlertsReady?.({ alerts: this.alerts, chart: chart as unknown as AlertChart })
  }

  private alertEvaluationPaused(): boolean {
    return (
      this.destroyed ||
      this.preparingWorkspace ||
      this.workspaceTransitionLocked ||
      this.workspaceReplayLocked ||
      this.replay !== null ||
      this.replayOwnsDisplay() ||
      this.replayPicking ||
      this.replayLoading ||
      this.dataUnavailable()
    )
  }

  private syncAlertPause(): void {
    this.alerts?.setPaused(this.alertEvaluationPaused())
  }

  private saveAlerts(): void {
    if (!this.alerts) return
    try {
      this.alertJson = this.alerts.toJSON()
      const serialized = JSON.stringify(this.alertJson)
      this.lsSet('alerts', serialized)
      if (
        this.alertRuntimeScope &&
        !this.destroyed &&
        !this.preparingWorkspace &&
        !this.workspaceTransitionLocked &&
        !this.restoringAlertRuntime
      ) {
        globalThis.localStorage.setItem(this.alertRuntimeScope, serialized)
      }
      this.alertSaveFailed = false
    } catch {
      if (!this.alertSaveFailed)
        this.toast('Alert state could not be saved. Check browser storage and payloads.', 'err')
      this.alertSaveFailed = true
    }
  }

  /** Bind only after a workspace is prepared, before its evaluator is unlocked. */
  setAlertRuntimeScope(scope: string | null, mode: 'restore' | 'seed'): void {
    this.alertRuntimeScope = scope
    if (!scope || !this.alerts || this.destroyed) return
    if (mode === 'restore') {
      this.restoringAlertRuntime = true
      try {
        const runtime = globalThis.localStorage.getItem(scope)
        if (runtime) this.alerts.fromJSON(mergeAlertRuntime(this.alerts.toJSON(), runtime))
      } catch {
        this.toast(
          'Alert runtime could not be restored. The saved workspace definition is retained.',
          'err'
        )
      } finally {
        this.restoringAlertRuntime = false
      }
    }
    this.saveAlerts()
  }

  /**
   * Put a dragged alert back on the tick, and rename it if we named it.
   *
   * Two corrections, both of a price that came from a pointer. A pixel maps to
   * a price with a dozen decimals behind it, so a line dropped where the axis
   * reads 1,260.55 was stored at 1260.5486842105263: a price the instrument
   * cannot trade at and a number nothing in the interface could show. And a
   * name generated from the old price goes on advertising it, so the row says
   * one number while the line sits at another.
   *
   * Both are no-ops when there is nothing to correct, which is what will happen
   * to the first of them once the engine rounds the drag itself.
   */
  private settleDraggedAlert(id: string): void {
    const controller = this.alerts
    const chart = this.chart
    if (!controller || !chart || this.destroyed) return
    const alert = controller.list().find((one) => one.id === id)
    if (!alert) return
    const at: AlertTick = { tick: this.sym?.tick, refPrice: this.refPrice() }
    const patch: AlertPatch = {}

    // Only a price is snapped. A study threshold is in the plot's own units,
    // and an oscillator running nought to a hundred has nothing to do with the
    // instrument's tick.
    if (alert.source.kind === 'price') {
      const price = snapPrice(alert.source.price, at)
      const upper =
        alert.source.upperPrice === undefined ? undefined : snapPrice(alert.source.upperPrice, at)
      if (price !== alert.source.price || upper !== alert.source.upperPrice) {
        patch.source = {
          ...alert.source,
          price,
          ...(upper === undefined ? {} : { upperPrice: upper }),
        }
      }
    }

    if (hasAutoTitle(alert)) {
      // Named from the snapped source, not the one that was dropped, or the
      // name would carry the decimals the price has just lost.
      const settled = { ...alert, source: patch.source ?? alert.source }
      const title = alertTitleFor(
        settled,
        chart as unknown as AlertChart,
        this.sym?.symbol ?? '',
        at
      )
      if (title !== alert.title) patch.title = title
    }

    if (patch.source === undefined && patch.title === undefined) return
    try {
      controller.update(id, patch)
    } catch {
      // The engine refused the corrected alert. The dragged one is still
      // armed and still evaluated; leaving it be is better than removing it.
    }
  }

  private detachAlerts(): void {
    this.offAlertFullscreen?.()
    this.offAlertFullscreen = null
    this.alertUi?.destroy()
    this.alertUi = null
    this.saveAlerts()
    for (const dispose of this.offAlerts.splice(0)) dispose()
    this.alerts?.destroy()
    this.alerts = null
    // The dialog is holding the controller that has just been destroyed. Left
    // open it would write alerts nothing evaluates, into a chart that is gone.
    this.cb.onAlerts?.(null)
    this.cb.onAlertsReady?.(null)
  }

  alertDialogOpen(): boolean {
    return this.alertUi?.isOpen() ?? false
  }

  /**
   * Make the alert the trader just pointed at, with no form in between.
   *
   * **Right-clicking a price is already the whole instruction.** The price is
   * the one thing a form would ask for, and it has just been given by pointing
   * at it; everything else has a default that is right almost every time. A
   * dialog here is a confirmation step on a decision already made, and it costs
   * the gesture its speed, which is the only reason to use it.
   *
   * The form is still there for the alert that needs it, on the toolbar's
   * Alerts button, and the created alert is editable from the rail the moment
   * it exists. So nothing is lost by making it now: what a right-click produces
   * is exactly the alert the form would have proposed, because both seed from
   * `draftFor`.
   */
  async createAlertAt(source: AlertSource): Promise<boolean> {
    const chart = this.chart
    if (!chart || this.destroyed || this.preparingWorkspace) return false
    try {
      await this.chartToolsReady
      if (this.destroyed || this.chart !== chart || !this.alerts) return false
      await this.attachDrawing()
      if (this.destroyed || this.chart !== chart || !this.alerts) return false

      const at: AlertTick = { tick: this.sym?.tick, refPrice: this.refPrice() }
      const draft = draftFor({
        chart: chart as unknown as AlertChart,
        drawings: (this.draw ?? null) as AlertDrawings | null,
        zone: chart.timezone(),
        source,
        at,
      })
      const problem = draftProblem(
        draft,
        chart as unknown as AlertChart,
        (this.draw ?? null) as AlertDrawings | null
      )
      if (problem !== null) {
        this.toast(problem, 'err')
        return false
      }
      const input = toAlertInput(
        draft,
        chart as unknown as AlertChart,
        (this.draw ?? null) as AlertDrawings | null,
        this.sym?.symbol ?? '',
        at
      )
      if (input === null) return false
      const made = this.alerts.add(input)
      // Borrowed from the click that made it: a browser starts an audio context
      // suspended and only asks about notifications inside a gesture, and this
      // is the gesture. Without it the first alert to fire hours later is silent
      // and the trader believes it never fired.
      readySound()
      if (deliveryOf(made.payload).notify) void askToNotify()
      this.toast(`Alert set: ${made.title}`, 'ok')
      return true
    } catch (error) {
      if (!this.destroyed && this.chart === chart)
        this.toast(`The alert could not be set: ${this.cleanError(error)}`, 'err')
      return false
    }
  }

  /**
   * Open the alert dialog, on a source when one was clicked.
   *
   * The drawing tier is attached first because an alert can be set on a
   * drawing's level, and a dialog that offered the option and then found no
   * drawings would be telling the trader they have none.
   */
  async openAlerts(source?: AlertSource, editAlertId?: string): Promise<boolean> {
    const chart = this.chart
    if (!chart || this.destroyed || this.preparingWorkspace) return false
    if (this.cb.onAlerts) {
      try {
        await this.chartToolsReady
        if (this.destroyed || this.chart !== chart || !this.alerts) return false
        await this.attachDrawing()
        if (this.destroyed || this.chart !== chart || !this.alerts) return false
        this.cb.onAlerts({
          alerts: this.alerts,
          chart: chart as unknown as AlertChart,
          drawings: (this.draw ?? null) as AlertDrawings | null,
          symbol: this.sym?.symbol ?? '',
          at: { tick: this.sym?.tick, refPrice: this.refPrice() },
          ...(source ? { source } : {}),
          ...(editAlertId ? { editAlertId } : {}),
        })
        return true
      } catch (error) {
        if (!this.destroyed && this.chart === chart)
          this.toast(`Alerts could not be opened: ${this.cleanError(error)}`, 'err')
        return false
      }
    }
    try {
      await this.chartToolsReady
      if (this.destroyed || this.chart !== chart || !this.alerts) return false
      await this.attachDrawing()
      const { createAlertUi } = await import('openalgo-charts/widget')
      if (this.destroyed || this.chart !== chart || !this.draw || !this.alerts) return false
      if (!this.alertUi) {
        const doc = this.container.ownerDocument
        const mount = () => (doc.fullscreenElement as HTMLElement | null) ?? doc.body
        const ui = createAlertUi(mount(), {
          chart,
          draw: this.draw,
          alerts: this.alerts,
          theme: this.getTheme().mode,
          chartTheme: this.chartTheme ?? undefined,
          onOpenChange: (open) => {
            if (this.alertUi) this.alertUi.root.dataset.tradingDialogOpen = String(open)
          },
        })
        this.alertUi = ui
        // A split pane must not clip source controls or shrink a phone dialog.
        ui.root.style.position = 'fixed'
        ui.root.style.zIndex = '100'
        // The engine's dialogs are a step smaller than this app's controls in
        // every dimension. Applied after `createAlertUi`, which writes the
        // engine's own token set as it builds the root.
        applyChartDialogMetrics(ui.root)
        const fullscreen = () => {
          ui.close()
          mount().appendChild(ui.root)
        }
        doc.addEventListener('fullscreenchange', fullscreen)
        this.offAlertFullscreen = () => doc.removeEventListener('fullscreenchange', fullscreen)
      }
      return source ? this.alertUi.openEditor({ source }) : this.alertUi.openList()
    } catch (error) {
      if (!this.destroyed && this.chart === chart)
        this.toast(`Alerts could not be opened: ${this.cleanError(error)}`, 'err')
      return false
    }
  }

  /** Re-add the tracked indicators to a freshly built chart. */
  private async applyIndicators(): Promise<void> {
    // Captured BEFORE the await. loadIndicators can take a moment on first
    // use (it dynamically imports the custom tier), and a rebuild inside that
    // window replaces this.chart -- so resuming here and reading the field
    // would add this run's indicators to a chart another run has already
    // populated, duplicating every one of them.
    const chart = this.chart
    if (!chart) return
    this.restoringIndicatorsOn = chart
    try {
      await this.loadIndicatorsFor(this.activeIndicators.map((record) => record.indicatorId))
      if (this.destroyed || !this.chart || this.chart !== chart) return
      // Re-adding walks the tracked list, so a sync mid-loop would read a
      // half-applied chart and truncate it.
      this.applyingIndicators = true
      try {
        if (this.activeIndicators.every((record) => record.paneIndex !== undefined)) {
          chart.restoreState({
            version: 1,
            indicators: this.activeIndicators as IndicatorState[],
            drawings: this.draw?.toJSON() ?? this.drawJson,
            alerts: this.alertJson,
          })
        } else {
          // Legacy duplicate healing happens during migration. Modern templates
          // may intentionally contain identical studies, including a shared pane.
          for (const rec of this.activeIndicators) {
            try {
              const inst = this.chart.addIndicator(rec.indicatorId, rec.settings, {
                paneIndex: rec.paneIndex,
              })
              inst.setVisible(rec.visible !== false)
            } catch {
              /* An unregistered legacy study must not prevent chart restoration. */
            }
          }
        }
      } finally {
        this.applyingIndicators = false
      }
    } catch (error) {
      if (!this.destroyed && this.chart === chart) {
        this.toast(`Indicators could not be restored: ${this.cleanError(error)}`, 'err')
      }
      return
    } finally {
      if (this.restoringIndicatorsOn === chart) this.restoringIndicatorsOn = null
    }
    this.syncIndicators()
  }

  /** Gather a settings form for one live indicator and hand it to the host. */
  private async emitIndicatorSettings(instanceId: string): Promise<void> {
    if (!this.chart || !this.cb.onIndicatorSettings) return
    const inst = this.chart.indicators().find((i) => i.id === instanceId)
    if (!inst) return
    const { registeredIndicators, indicatorStyleInputs } = await import('openalgo-charts')
    const descriptor = registeredIndicators().find((d) => d.id === inst.indicatorId)
    if (!descriptor) return
    // Value inputs and generated style inputs stay separate so the form can tab
    // them the way a charting package does; one component covers every
    // indicator without a line of indicator-specific code.
    this.cb.onIndicatorSettings({
      instanceId,
      name: inst.name,
      values: { ...inst.settings() },
      inputs: descriptor.inputs
        .map(toField)
        .map((f) => this.fillIntervalOptions(f, inst.settings())),
      styleInputs: indicatorStyleInputs(descriptor).map(toField),
    })
  }

  /**
   * Give an `interval` input (2.4.0) the timeframes this broker actually serves.
   *
   * The library's own widget offers its registered codes, which is the right
   * answer for a generic host. Here we know better: the broker told us its
   * intervals at boot, and offering one it does not serve is a control that
   * looks fine and returns nothing. A descriptor that declares its own options
   * keeps them.
   *
   * A value outside that list is kept as its own entry rather than dropped.
   * The engine resolves more codes than any one broker serves (`1d` and `D`
   * are the same bucket to it), so a descriptor defaulting to `1d` against a
   * broker that lists `D` would otherwise show a select reading "Chart
   * interval" while the study computed on `1d`: a control disagreeing with the
   * value behind it, which is worse than no control.
   */
  private fillIntervalOptions(
    field: IndicatorField,
    values: Record<string, unknown>
  ): IndicatorField {
    if (field.type !== 'interval' || field.options !== undefined) return field
    // The empty entry is "the chart's own interval", which is how a study says
    // it is not folding at all.
    const options = [
      { label: 'Chart interval', value: '' as unknown },
      ...this.availableIntervals.map((code) => ({ label: code, value: code as unknown })),
    ]
    const current = values[field.key]
    if (
      typeof current === 'string' &&
      current !== '' &&
      !this.availableIntervals.includes(current)
    ) {
      options.push({ label: current, value: current })
    }
    return { ...field, options }
  }

  /** The descriptor's default settings, for the form's Defaults action. */
  async indicatorDefaultsFor(instanceId: string): Promise<Record<string, unknown> | null> {
    const inst = this.chart?.indicators().find((i) => i.id === instanceId)
    if (!inst) return null
    const { registeredIndicators, indicatorDefaults } = await import('openalgo-charts')
    const d = registeredIndicators().find((x) => x.id === inst.indicatorId)
    return d ? { ...indicatorDefaults(d) } : null
  }

  /** Apply a settings patch to a live indicator. */
  updateIndicatorSettings(instanceId: string, patch: Record<string, unknown>): void {
    const inst = this.chart?.indicators().find((i) => i.id === instanceId)
    if (!inst) return
    inst.setSettings(patch)
    this.syncIndicators()
  }

  /** Open the settings form for an indicator from the host's own UI. */
  openIndicatorSettings(instanceId: string): void {
    void this.emitIndicatorSettings(instanceId)
  }

  /* ── chart settings ─────────────────────────────────────────────────────
   * The engine is canvas-only and ships no DOM, so it describes its settings
   * dialog declaratively and the host renders it — the same contract the
   * indicator form already uses, which is why `toField` is shared.
   */

  /**
   * The settings schema and its current values. Read at open time rather than
   * cached: the Price tab depends on the live series type, the colour defaults
   * come from the active theme, and the timezone list has to include whatever
   * zone the chart is already in.
   */
  async chartSettings(): Promise<ChartSettingsRequest | null> {
    const chart = this.chart
    if (!chart) return null
    const { chartSettingsSchema, readChartSettings } = await import('openalgo-charts')
    if (chart !== this.chart || this.destroyed) return null
    const tabs = chartSettingsSchema(chart).map((t) => ({
      id: t.id,
      label: t.label,
      inputs: t.inputs.map((i) =>
        i.type === 'colorPair'
          ? (i as unknown as ChartSettingsPairField)
          : {
              ...toField(i as { key: string; type: string; label?: string; group?: string }),
              ...(i.key === 'statusLine.openInterest' && chart.hasOpenInterest === false
                ? { unavailable: 'Open interest is unavailable for this instrument.' }
                : {}),
            }
      ),
    }))
    return volumeSettingsView(
      profileSettingsView(
        {
          tabs,
          values: { ...readChartSettings(chart) },
          defaults: { ...this.chartDefaults },
        },
        this.ctype,
        this.chartSettingsSaved
      ),
      this.chartSettingsSaved
    )
  }

  /**
   * Record the chart as this terminal builds it: engine defaults with this
   * host's construction options already on top, and nothing restored from
   * storage yet. That combination is what a user means by "default" here.
   *
   * The engine's own per-control defaults, which the schema does publish, are
   * the wrong answer to reset against. This host opts into the corner session
   * clock and the bar countdown at construction, both off in the engine, so a
   * reset driven from the schema would quietly switch off chrome the user never
   * touched. It would also fight the grid, which the context menu owns under a
   * separate key: the engine's default is on, and a reset would flip the grid
   * back on for someone who had turned it off from the menu, leaving the two
   * owners disagreeing about the same two booleans.
   *
   * Re-taken on every build, which is also what keeps it honest across a theme
   * switch: `applyTheme` rebuilds the chart, so the colours here are always the
   * live theme's rather than whichever palette was on at boot.
   */
  private snapshotChartDefaults(): void {
    if (!this.chart) return
    this.chartDefaults = { ...readChartSettings(this.chart) }
  }

  /**
   * Apply a patch from the settings dialog and persist it.
   *
   * Persistence is a merge, not a replace: the dialog sends only the keys it
   * changed, and a key the engine no longer knows is ignored on the way back
   * in, so a layout saved by a newer build still restores into an older one.
   *
   * What is stored is then pruned back to the keys that genuinely DIFFER from
   * the baseline, and that prune is what makes "reset to defaults" survive a
   * reload. A reset arrives here as an ordinary patch setting each key back to
   * its baseline value; merging it blindly would store the entire default set,
   * and `restoreChartSettings` would replay it on the next boot. Since a colour
   * baseline is the active theme's, that replay would nail the chart to the
   * palette of whichever theme happened to be on at reset time, and a later
   * switch to light or dark would leave the candles behind. Storing only real
   * deviations lets an untouched control keep following the theme, which is
   * what "default" has to mean for the reset to be worth having.
   */
  async applyChartSettings(patch: Record<string, string | number | boolean>): Promise<void> {
    const chart = this.chart
    if (!chart) return
    const { applyChartSettings } = await import('openalgo-charts')
    if (chart !== this.chart || this.destroyed) return
    const enginePatch = Object.fromEntries(
      Object.entries(patch).filter(
        ([key]) => !key.startsWith('profiles.') && !key.startsWith('volume.')
      )
    )
    const merged = { ...this.chartSettingsSaved, ...patch }
    if (
      isProfileKind(this.ctype) &&
      !selectProfileInterval(
        this.ctype,
        this.interval,
        readProfileSettings('tpo', merged).blockMinutes,
        this.availableIntervals
      )
    ) {
      this.toast('The broker has no interval compatible with this TPO block size', 'err')
      return
    }
    if ('time.timezone' in enginePatch && enginePatch['time.timezone'] !== chart.timezone())
      this.stopReplay()
    applyChartSettings(chart, enginePatch)
    const defaults = {
      ...this.chartDefaults,
      ...profileDefaults('tpo'),
      ...profileDefaults('session-volume-profile'),
      ...VOLUME_DEFAULTS,
    }
    for (const kind of ['tpo', 'session-volume-profile'] as const) {
      const normalized = profileValues(kind, merged)
      for (const key of Object.keys(normalized)) {
        if (key in merged) merged[key] = normalized[key]
      }
    }
    for (const [key, value] of Object.entries(volumeValues(merged))) {
      if (key in merged) merged[key] = value
    }
    const kept: Record<string, string | number | boolean> = {}
    for (const [k, v] of Object.entries(merged)) {
      // A key absent from the baseline is kept: an unrecognised control is not
      // evidence that its value is the default one.
      if (!(k in defaults) || defaults[k] !== v) kept[k] = v
    }
    this.chartSettingsSaved = kept
    this.lsSet('chartsettings', JSON.stringify(kept))
    this.adoptGridFromPatch(patch)
    this.refreshDisplayedVolume()
    this.refreshLegend(this.replayActive() ? (this.price?.getData() ?? []) : this.shownBars)
    if (isProfileKind(this.ctype)) {
      const interval = this.compatibleProfileInterval(this.ctype)
      if (interval && interval !== this.interval) {
        this.setInterval(interval)
        this.toast(`Using ${interval} bars for the selected profile block size`, '')
      } else {
        this.installProfile()
      }
    }
  }

  /**
   * Keep the two owners of grid visibility from disagreeing.
   *
   * Grid lines can be changed from two places: the context menu, which writes
   * `gridV`/`gridH` and its own storage key, and the settings dialog, which
   * patches `canvas.grid.*` straight through to the engine. Left alone the two
   * drift apart, and the context menu -- which is re-applied verbatim on every
   * rebuild -- eventually wins, so a grid switched from the dialog silently
   * comes back on the next theme or chart-type change. Mirroring the patch here
   * makes the dialog write through the same field the menu reads, so the menu's
   * tick matches the chart and a rebuild re-applies what the user last chose,
   * whichever control they chose it with.
   */
  private adoptGridFromPatch(patch: Record<string, string | number | boolean>): void {
    const v = patch['canvas.grid.vertLines']
    const h = patch['canvas.grid.horzLines']
    if (v === undefined && h === undefined) return
    this.gridV = v === undefined ? this.gridV : v === true
    this.gridH = h === undefined ? this.gridH : h === true
    this.lsSet('grid', `${this.gridV ? 1 : 0}${this.gridH ? 1 : 0}`)
  }

  /**
   * Re-apply the persisted settings once the chart exists. Called from the
   * chart's own setup rather than `restoreChartTools`, because these write
   * through the live chart object instead of seeding a field read at build
   * time. A malformed entry is dropped: a stale setting must never stop the
   * terminal booting.
   */
  private async restoreChartSettings(strict = false): Promise<void> {
    const chart = this.chart
    if (!chart || !Object.keys(this.chartSettingsSaved).length) return
    try {
      const { applyChartSettings } = await import('openalgo-charts')
      if (chart !== this.chart || this.destroyed) return
      applyChartSettings(
        chart,
        Object.fromEntries(
          Object.entries(this.chartSettingsSaved).filter(
            ([key]) => !key.startsWith('profiles.') && !key.startsWith('volume.')
          )
        )
      )
      this.installProfile()
      this.refreshDisplayedVolume()
      this.refreshLegend(this.replayActive() ? (this.price?.getData() ?? []) : this.shownBars)
    } catch (error) {
      if (strict) throw error
      /* ignore */
    }
  }

  /**
   * Re-read the tracked list from the chart, which is the only thing that knows
   * the truth — indicators can also be removed from their own on-chart legend.
   * Reading the whole list rather than patching it also keeps duplicates right:
   * two SMAs differ only by instance id, so "remove the one with this
   * indicatorId" would drop an arbitrary one of them.
   */
  private syncIndicators(): void {
    if (!this.chart || this.applyingIndicators || this.restoringIndicatorsOn === this.chart) return
    const next = this.chart.indicators().map((i) => ({
      instanceId: i.id,
      indicatorId: i.indicatorId,
      settings: { ...i.settings() },
      visible: i.visible(),
      paneIndex: i.paneIndex,
    }))
    if (!sameIndicatorRecords(this.activeIndicators, next)) {
      this.activeIndicators = next
      this.lsSet('indicators', JSON.stringify({ version: 2, indicators: this.activeIndicators }))
    }
    const announced = this.listIndicators().map(({ id, name }) => ({ id, name }))
    if (!sameIndicatorInstances(this.announcedIndicators, announced)) {
      this.announcedIndicators = announced
      this.cb.onIndicatorsChange?.(announced)
    }
  }

  captureWorkspacePane(id: string): WorkspacePane {
    const chart = this.chart
    const symbol = this.sym
    if (this.destroyed || !chart || !symbol) throw new Error('Chart is not available')
    if (this.dataUnavailable()) throw new Error('Chart history is loading or unavailable')
    if (
      this.replayOwnsDisplay() ||
      this.replayPicking ||
      this.replayLoading ||
      this.workspaceReplayLocked
    )
      throw new Error('Leave replay before saving a workspace')
    const context = chart.getDataContext()
    if (
      context?.symbol !== symbol.symbol ||
      context.exchange !== symbol.exchange ||
      context.interval !== this.interval
    )
      throw new Error('Chart history is still loading')
    if (this.restoringIndicatorsOn === chart) throw new Error('Studies are still loading')
    if (this.drawLegacy || (this.drawEnabled && !this.draw))
      throw new Error('Drawings are still loading')
    return parseWorkspacePayload({
      layout: {
        rows: 1,
        columns: 1,
        slots: [{ paneId: id, row: 0, column: 0, rowSpan: 1, columnSpan: 1 }],
      },
      activePaneId: id,
      panes: [
        {
          id,
          symbol: symbol.symbol,
          exchange: symbol.exchange,
          interval: this.interval,
          chartType: this.ctype,
          chart: {
            ...(this.comparisons?.captureBaseState() ?? chart.getState()),
            drawings: this.draw?.toJSON() ?? this.drawJson,
          },
          settings: this.chartSettingsSaved,
          volume: this.volumeOn,
          magnet:
            this.draw?.magnetMode() ?? this.drawMagnetMode ?? (this.drawMagnet ? 'strong' : 'off'),
          stay: this.drawStay,
          comparisons: this.comparisons?.specs() ?? this.comparisonPreferences?.items ?? [],
          comparisonMode: this.comparisons?.mode ?? this.comparisonPreferences?.mode ?? 'price',
        },
      ],
    }).panes[0]
  }

  captureIndicatorTemplate(): IndicatorState[] {
    if (this.destroyed || !this.chart) throw new Error('Chart is not available')
    const indicators = parseIndicatorStates(this.chart.getState().indicators ?? [])
    for (const indicator of indicators) delete indicator.instanceId
    return indicators
  }

  exportDataCsv(): string {
    if (this.destroyed || !this.chart || this.dataUnavailable())
      throw new Error('Chart history is unavailable for export')
    if (
      this.replayPicking ||
      this.replayLoading ||
      (this.workspaceReplayLocked && !this.workspaceReplayMember)
    )
      throw new Error('Finish replay selection and loading before exporting data')
    return exportChartDataCsv(this.chart)
  }

  comparisonState(): TerminalComparisonState {
    return {
      mode:
        (this.comparisons?.mode ?? this.comparisonPreferences?.mode) === 'percent'
          ? 'percentage'
          : 'price',
      items: (this.comparisons?.rows() ?? []).map((row) => ({
        id: row.id,
        symbol: row.symbol,
        exchange: row.exchange,
        label: `${row.exchange}:${row.symbol}`,
        // Always set by the time a row exists; the palette entry keeps a
        // swatch from being blank if that ever stops being true, and keeps it
        // from being the one colour a comparison is not allowed to be.
        color: row.color ?? COMPARISON_PALETTE[0],
        status:
          row.status === 'ready'
            ? 'ready'
            : ['idle', 'loading', 'refreshing'].includes(row.status)
              ? 'loading'
              : 'error',
        ...(row.error ? { error: row.error } : {}),
      })),
    }
  }

  private installComparisons(): void {
    const chart = this.chart
    const feed = this.cachedBars ?? this.rest
    if (!chart || !feed || this.destroyed) return
    let setup = Promise.resolve()
    if (!this.comparisons) {
      const comparisons = new TerminalComparisons({
        feed,
        ws: { url: this.wsUrl, apiKey: this.apiKey },
        now: () => this.gridNow(),
        onChange: () => {
          if (this.destroyed || this.comparisons !== comparisons) return
          this.comparisonPreferences = { items: comparisons.specs(), mode: comparisons.mode }
          this.lsSet('comparisons', JSON.stringify(this.comparisonPreferences))
          this.cb.onComparisonsChange?.(this.comparisonState())
        },
      })
      this.comparisons = comparisons
      setup = comparisons.replace(this.comparisonPreferences.items, this.comparisonPreferences.mode)
    }
    const comparisons = this.comparisons
    const interval = this.interval
    const ticket = this.loadTicket
    const symbolOwner = this.sym
    const isCurrent = () =>
      !this.destroyed &&
      chart === this.chart &&
      interval === this.interval &&
      ticket === this.loadTicket &&
      symbolOwner === this.sym
    const to = this.gridNow()
    this.comparisonLoad = setup.then(async () => {
      if (!isCurrent()) return
      comparisons.setVisibleHost(document.visibilityState !== 'hidden')
      await comparisons.bind(chart, {
        interval,
        from: this.rawBars[0]?.time ?? to - lookbackDays(interval) * 86400,
        to,
        timezone: chart.timezone(),
      })
      if (isCurrent()) this.cb.onComparisonsChange?.(this.comparisonState())
    })
    void this.comparisonLoad.catch((error) => {
      if (isCurrent() && !this.preparingWorkspace)
        this.toast(`Comparison history: ${this.cleanError(error)}`, 'err')
    })
  }

  async addComparison(symbol: string, exchange: string): Promise<void> {
    const chart = this.chart
    const interval = this.interval
    const symbolOwner = this.sym
    if (!chart || this.destroyed || this.dataUnavailable())
      throw new Error('Chart history is unavailable')
    if (this.workspaceReplayLocked || this.replayOwnsDisplay() || this.replayPicking)
      throw new Error('Leave replay before adding a comparison')
    if (isChartExpression(symbol)) throw new Error('Choose an instrument for comparison')
    if (!this.comparisons) this.installComparisons()
    await this.comparisonLoad.catch(() => {})
    if (
      this.destroyed ||
      chart !== this.chart ||
      interval !== this.interval ||
      symbolOwner !== this.sym ||
      this.dataUnavailable() ||
      !this.comparisons
    )
      throw new Error('The chart changed while comparison history was loading')
    if (this.workspaceReplayLocked || this.replayOwnsDisplay() || this.replayPicking)
      throw new Error('Leave replay before adding a comparison')
    // No colour: `TerminalComparisons` assigns one, because it is the only
    // place that sees every colour already on this chart. Choosing here by
    // counting what exists handed the third comparison the second's colour as
    // soon as the first was removed, and its first entry was the engine's own
    // default line blue, so comparison one looked like a line the chart had
    // drawn by accident.
    await this.comparisons.add({
      id: crypto.randomUUID(),
      symbol,
      exchange,
      visible: true,
    })
  }

  removeComparison(id: string): void {
    this.comparisons?.remove(id)
  }

  setComparisonMode(mode: 'price' | 'percentage'): void {
    if (mode !== 'price' && mode !== 'percentage') throw new Error('Invalid comparison mode')
    const selected = mode === 'percentage' ? 'percent' : 'price'
    if (this.comparisons) this.comparisons.setMode(selected)
    else {
      this.comparisonPreferences.mode = selected
      this.lsSet('comparisons', JSON.stringify(this.comparisonPreferences))
      this.cb.onComparisonsChange?.(this.comparisonState())
    }
  }

  async applyIndicatorTemplate(
    input: IndicatorState[],
    mode: IndicatorTemplateMode
  ): Promise<void> {
    const incoming = parseIndicatorStates(input)
    const chart = this.chart
    if (this.destroyed || !chart) throw new Error('Chart is not available')
    await this.loadIndicators()
    if (this.destroyed || this.chart !== chart)
      throw new Error('The chart changed while studies were loading')
    if (this.restoringIndicatorsOn === chart)
      throw new Error('Studies are still loading. Try again when loading finishes.')
    const previousState = chart.getState()
    const previous = parseIndicatorStates(previousState.indicators ?? [])
    const retained = {
      drawings: this.draw?.toJSON() ?? this.drawJson,
      alerts: previousState.alerts ?? this.alertJson,
    }
    const planned = planIndicatorTemplate(
      previous,
      incoming,
      mode,
      new Set(registeredIndicators().map((descriptor) => descriptor.id)),
      chart.panes().length
    )
    this.applyingIndicators = true
    try {
      const report = chart.restoreState({ version: 1, indicators: planned, ...retained })
      if (!report.applied) throw new Error(report.reason ?? 'Template could not be applied')
    } catch (error) {
      if (!this.destroyed && this.chart === chart) {
        try {
          chart.restoreState({ version: 1, indicators: previous, ...retained })
        } catch (rollbackError) {
          throw new AggregateError(
            [error, rollbackError],
            'Template failed and previous studies could not be restored'
          )
        }
      }
      throw error
    } finally {
      this.applyingIndicators = false
      if (!this.destroyed && this.chart === chart) this.syncIndicators()
    }
  }

  /**
   * Put a study on the chart, or apply one of the trader's scripts again.
   *
   * **A script already on this chart is applied, not added a second time.** The
   * scripts panel's Apply and the strategy's Apply both land here, and pressing
   * Apply after an edit is how a trader asks to see the edit; a second copy
   * beside the first, still running the old code, is not that. The copy on the
   * chart holds the descriptor it was built from, so a recompute alone would run
   * the old program again: it is rebuilt from the registry instead, keeping its
   * instance id, pane, settings and visibility (an alert on one of its plots is
   * bound to that id). Only a script: a built-in added twice from the picker is
   * two studies on purpose, three moving averages being the ordinary case.
   *
   * A script's session facts arrive after it is first drawn, so the note about
   * an empty study waits for them rather than describing the study before them.
   */
  async addIndicatorById(indicatorId: string): Promise<void> {
    await this.loadIndicators()
    const chart = this.chart
    if (this.destroyed || !chart) return
    const script = fileForScriptId(indicatorId) !== null
    try {
      if (
        script &&
        this.restoringIndicatorsOn !== chart &&
        chart.indicators().some((one) => one.indicatorId === indicatorId)
      ) {
        await this.reapplyScript(chart, indicatorId)
        return
      }
      const inst = chart.addIndicator(indicatorId, {})
      this.syncIndicators()
      if (script) await this.scriptFactsSettled()
      if (this.chart === chart && chart.indicators().includes(inst)) this.warnIfStarved(inst)
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /**
   * Rebuild every copy of a script on this chart from the registered program.
   *
   * `restoreState` is the chart's own replace-in-place: it keeps each study's
   * instance id, order, pane, settings and visibility, which removing a copy and
   * adding a new one would not. It rebuilds every study on the chart to do it,
   * and it stops part way if one of them cannot be built, so the edited script
   * is calculated on this chart's bars first. One that fails is reported and the
   * chart is left exactly as it was, still drawing the version that worked.
   */
  private async reapplyScript(chart: ChartInstance, indicatorId: string): Promise<void> {
    const refusal = this.studyRefusal(chart, indicatorId)
    if (refusal !== null) {
      this.toast(this.cleanError(refusal), 'err')
      return
    }
    const state = chart.getState()
    this.applyingIndicators = true
    try {
      const report = chart.restoreState({
        version: 1,
        indicators: parseIndicatorStates(state.indicators ?? []),
        drawings: this.draw?.toJSON() ?? this.drawJson,
        alerts: state.alerts ?? this.alertJson,
      })
      if (!report.applied) throw new Error('The study could not be applied again')
    } finally {
      this.applyingIndicators = false
      if (!this.destroyed && this.chart === chart) this.syncIndicators()
    }
    await this.scriptFactsSettled()
    if (this.destroyed || this.chart !== chart) return
    const applied = chart.indicators().find((one) => one.indicatorId === indicatorId)
    if (applied) this.warnIfStarved(applied)
  }

  /**
   * Why the registered study cannot be calculated on this chart, or null.
   *
   * Run with each copy's own settings over the chart's own bars, in a store
   * nothing else holds, which is what the chart would do when it built it.
   */
  private studyRefusal(chart: ChartInstance, indicatorId: string): unknown {
    const descriptor = getIndicator(indicatorId)
    const bars = chart.primaryBars()
    const context = chart.getDataContext()
    const tick = this.tick()
    const ctx = {
      barState: { isNew: false, isConfirmed: true, isRealtime: false, lastIndex: bars.length - 1 },
      symbol: context?.symbol,
      interval: context?.interval,
      timezone: chart.timezone(),
      now: () => Date.now() / 1000,
      ...(tick > 0 ? { tickSize: tick } : {}),
    }
    for (const inst of chart.indicators()) {
      if (inst.indicatorId !== indicatorId) continue
      try {
        descriptor.calc(bars, { ...indicatorDefaults(descriptor), ...inst.settings() }, {}, ctx)
      } catch (error) {
        return error
      }
    }
    return null
  }

  /** Resolves once this chart's instrument facts have arrived or cannot be had. */
  private async scriptFactsSettled(): Promise<void> {
    const sym = this.sym
    if (sym && !sym.synthetic && sym.exchange) await factsFor(sym.symbol, sym.exchange)
  }

  /**
   * Tell the user when a study has nothing to plot on the bars loaded.
   *
   * Every indicator needs a warmup before it can print, and a few need a long
   * one: Special K sums rates of change out to 530 bars and only starts at 725,
   * and openalgo-charts 1.8.3 lengthened several warmups by correcting how they
   * seed. On an intraday chart holding a few hundred bars those studies now draw
   * an empty pane, which is the correct answer and looks exactly like a broken
   * indicator. Saying so once, at the moment it is added, is the difference.
   *
   * **It says what is known and no more.** An empty study is not always a short
   * one: a session study before its session, or one that plots only on the bar
   * a condition holds, has nothing to draw on a chart of any length. Saying it
   * needed more history sent the trader loading more for nothing, so the note
   * states the fact and offers the history only as the thing to try if the
   * study is one that needs it.
   *
   * Only the columns drawn as plots count. A study's values also carry its alert
   * conditions and its paint, none of them a line, and a study that draws only a
   * grid or marks has no plot to be empty.
   *
   * Reading `values()` is safe here: the engine flushes any pending recompute on
   * that call, so this sees the result of the add rather than the frame before.
   */
  private warnIfStarved(inst: {
    name: string
    indicatorId: string
    values(): Record<string, unknown>
    series(plotKey: string): unknown
  }): void {
    const loaded = this.rawBars.length
    if (!loaded) return
    const cols = Object.entries(inst.values())
      .filter(([key, col]) => Array.isArray(col) && inst.series(key) !== undefined)
      .map(([, col]) => col as unknown[])
    if (cols.length === 0) return
    const anyFinite = cols.some((col) =>
      col.some((v) => typeof v === 'number' && Number.isFinite(v))
    )
    if (anyFinite) return
    if (
      ['open-interest', 'open-interest-change', 'open-interest-buildup'].includes(
        inst.indicatorId
      ) &&
      !this.rawBars.some((bar) => Number.isFinite(bar.oi))
    ) {
      const supported =
        this.sym?.hasOpenInterest ?? openInterestCapability(this.sym?.exchange ?? '')
      this.toast(
        supported === false
          ? 'Open interest is not available for this instrument.'
          : 'The loaded history contains no open interest readings.',
        ''
      )
      return
    }
    this.toast(
      `${inst.name} has nothing to plot on the ${loaded} bars loaded. If it needs a longer history before it starts, widen the range or pick a longer interval.`,
      ''
    )
  }

  removeIndicatorById(instanceId: string): void {
    if (!this.chart) return
    this.chart.removeIndicator(instanceId)
    this.syncIndicators()
  }

  /**
   * The live indicators, carrying both ids because its two callers need
   * different ones.
   *
   * The rail's list removes one overlay of several, so it needs the instance
   * `id`. The agent names a descriptor it can add and remove, so it needs
   * `indicatorId`: handed `ema-1` it would ask the chart to remove an
   * indicator no registry has ever heard of, and the command would be dropped
   * without a word. One shape carrying both is what keeps that from becoming
   * two functions that drift.
   */
  listIndicators(): { id: string; indicatorId: string; name: string }[] {
    return this.chart
      ? this.chart.indicators().map((i) => ({ id: i.id, indicatorId: i.indicatorId, name: i.name }))
      : []
  }

  /**
   * Join or leave the workspace link group.
   *
   * The engine has no notion of a symbol, so following one is a callback: the
   * group decides WHEN, this host decides HOW. `loadSymbol` is the same path
   * the symbol search uses, so a linked change behaves exactly like a typed one
   * -- same fetch, same cache, same teardown of a running replay.
   */
  setLinkGroup(group: LinkGroup | null): void {
    if (this.link && this.chart && this.link !== group) this.link.remove(this.chart)
    this.link = group
    this.joinLink()
  }

  /**
   * The group's symbol is `EXCHANGE:SYMBOL`, not a bare ticker.
   *
   * The engine treats the value as an opaque string, and a bare symbol is not
   * an instrument here: the same ticker exists on more than one exchange, so
   * following one would be a coin toss over which book you ended up charting.
   */
  private linkSymbol(): string | undefined {
    return this.sym ? `${this.sym.exchange}:${this.sym.symbol}` : undefined
  }

  private joinLink(): void {
    if (!this.link || !this.chart) return
    this.link.add(this.chart, {
      symbol: this.linkSymbol(),
      interval: this.interval,
      onInterval: (next) => this.setInterval(next) === next,
      onSymbol: (next) => {
        // Ignore an echo of what this pane already shows: the group puts a
        // joining member onto the agreed symbol, and reloading a chart onto the
        // instrument it already displays would throw away its viewport.
        if (this.linkSymbol() === next) return
        const cut = next.indexOf(':')
        if (cut <= 0) return // not ours to interpret
        void this.loadSymbol({ symbol: next.slice(cut + 1), exchange: next.slice(0, cut) })
      },
    })
  }

  /**
   * Now, snapped down to the bar grid.
   *
   * The cache keys on symbol, exchange and interval and then slices by range,
   * so the range has to be STABLE between two loads inside the same bar. A raw
   * `nowSec()` moves every second, which the cache reads as a request for data
   * it does not hold, and the hit rate is then exactly zero. Snapping makes
   * every load inside one bar ask the identical question.
   *
   * Count-driven and calendar codes have no fixed grid to snap to, so they fall
   * through unsnapped and simply do not benefit. That is the honest outcome
   * rather than inventing a grid they do not have.
   */
  private gridNow(): number {
    const found = tryResolveInterval(this.interval)
    const step = found?.bucketing.mode === 'interval' ? found.bucketing.seconds : 0
    const now = nowSec()
    return step > 0 ? Math.floor(now / step) * step : now
  }

  /** Grid visibility, independently per axis. */
  setGrid(vertical: boolean, horizontal: boolean): void {
    this.gridV = vertical
    this.gridH = horizontal
    this.chart?.setGridOptions({ vertLines: vertical, horzLines: horizontal })
    this.lsSet('grid', `${vertical ? 1 : 0}${horizontal ? 1 : 0}`)
  }

  gridState(): { vertical: boolean; horizontal: boolean } {
    return { vertical: this.gridV, horizontal: this.gridH }
  }

  /**
   * Show or hide the built-in volume histogram, remembered per pane.
   *
   * Hidden rather than removed: the series keeps taking data, so toggling back
   * is instant and no history has to be refetched. It also keeps the overlay
   * price scale in place, which is what the bars are measured against.
   */
  setVolumeVisible(on: boolean): void {
    this.volumeOn = on
    this.volume?.applyOptions({
      visible: on && this.volumeAvailable() && !isProfileKind(this.ctype),
    })
    this.volumeMA?.applyOptions({
      visible:
        on &&
        this.volumeAvailable() &&
        !isProfileKind(this.ctype) &&
        volumeValues(this.chartSettingsSaved)['volume.showMA'] === true,
    })
    this.lsSet('vol', on ? '1' : '0')
  }

  volumeVisible(): boolean {
    return this.volumeOn
  }

  /**
   * The interval a displayed bar is built from, so replay can form one in front
   * of the user rather than landing it whole.
   *
   * One rung down, not the finest available: 1-minute bars under a daily chart
   * are 375 steps per candle, which is not a replay, it is a stall. An interval
   * with no rung below it replays bar by bar, as it always did.
   */
  private static readonly REPLAY_SUB: Record<string, string> = {
    '3m': '1m',
    '5m': '1m',
    '10m': '5m',
    '15m': '5m',
    '30m': '15m',
    '1h': '15m',
    '60m': '15m',
    '2h': '30m',
    '4h': '1h',
    D: '1h',
    '1d': '1h',
    W: 'D',
    '1w': 'D',
  }

  /* ── market replay ──────────────────────────────────────────────────────
   * Walk the loaded session forward a bar at a time. The engine's controller
   * feeds the series a prefix of the bars, which is what makes every indicator
   * redraw as it stood at that moment rather than needing replay-aware code of
   * its own.
   *
   * Both the price and the volume series are driven: the chart merges every
   * series onto one time axis, so a volume histogram left at full length would
   * drag future timestamps back onto the axis and undo the illusion.
   */

  /** True while the chart is showing a replayed prefix rather than live data. */
  replayActive(): boolean {
    return this.replay !== null || this.workspaceReplayMember?.active === true
  }

  private replayOwnsDisplay(): boolean {
    return this.replayActive() || this.workspaceReplayMember?.preparing === true
  }

  setWorkspaceReplayLocked(locked: boolean): void {
    this.workspaceReplayLocked = locked
    this.syncAlertPause()
    this.showTradeButtons(
      !locked && !this.replayOwnsDisplay() && !this.replayPicking && !this.replayLoading
    )
    if (!locked) {
      this.workspaceReplayMember?.detachAbort()
      this.workspaceReplayMember = null
    }
  }

  setReplayInvalidationHandler(handler: (() => void) | null): void {
    this.replayInvalidation = handler
  }

  beginWorkspaceReplayPick(
    onPick: (time: number) => void,
    onCancel: () => void,
    onPreview?: (time: number) => void
  ): boolean {
    if (this.destroyed || this.replayOwnsDisplay() || this.replayPicking || this.replayLoading)
      return false
    this.startReplay()
    if (!this.replayPicking) return false
    this.workspaceReplayPick = { onPick, onCancel, onPreview }
    this.publishReplayPreview()
    return true
  }

  private publishReplayPreview(): void {
    const index = this.replayPickIndex
    if (index === null || !this.chart || !this.workspaceReplayPick?.onPreview) return
    const bar = this.shownBars[index]
    if (!bar) return
    this.workspaceReplayPick.onPreview(
      replayTiming(this.interval, this.chart.timezone()).barEndTime(bar, index)
    )
  }

  setWorkspaceReplayPreview(time: number | null): void {
    if (time === null) {
      this.setReplayShade(null)
      return
    }
    if (!this.chart) return
    const timing = replayTiming(this.interval, this.chart.timezone())
    let last = -1
    for (let index = 0; index < this.shownBars.length; index++) {
      if (timing.barEndTime(this.shownBars[index], index) > time) break
      last = index
    }
    this.setReplayShade(last)
  }

  async prepareReplayMember({
    id,
    sessionId,
    signal,
  }: {
    id: string
    sessionId: number
    signal: AbortSignal
  }): Promise<PreparedReplayMember> {
    const chart = this.chart
    const price = this.price
    if (this.destroyed || !chart || !price || this.dataUnavailable() || price.getData().length < 2)
      throw new Error('Every replay chart needs available history')
    if (signal.aborted) throw new Error('Replay preparation was cancelled')
    if (this.replay || this.workspaceReplayMember?.active)
      throw new Error('This chart already has a replay owner')
    const data = this.data
    const sym = this.sym
    const interval = this.interval
    const ctype = this.ctype
    const timezone = chart.timezone()
    const previous = this.workspaceReplayMember
    if (previous) this.restoreReplayMember(previous.sessionId)
    previous?.detachAbort()
    const member = {
      sessionId,
      chart,
      price,
      data,
      active: false,
      preparing: true,
      state: null as ReplayState | null,
      autoScale: price.priceScale().autoScale,
      positioned: false,
      isCurrent: () =>
        !this.destroyed &&
        !signal.aborted &&
        this.workspaceReplayMember === member &&
        this.chart === chart &&
        this.price === price &&
        this.data === data &&
        this.sym === sym &&
        this.interval === interval &&
        this.ctype === ctype &&
        chart.timezone() === timezone,
      detachAbort: () => signal.removeEventListener('abort', cancel),
    }
    const cancel = () => {
      if (this.workspaceReplayMember !== member || !member.preparing) return
      this.replayHistoryAbort?.abort()
      this.restoreReplayMember(sessionId)
    }
    this.workspaceReplayMember = member
    signal.addEventListener('abort', cancel, { once: true })
    this.replayLoading = true
    this.replayPicking = false
    this.workspaceReplayPick = null
    this.setReplayShade(null)
    this.syncAlertPause()
    data?.setPaused(true)
    this.showTradeButtons(false)
    this.cb.onReplayChange?.(null)
    try {
      const transformed = Boolean(CHART_TYPES[ctype]?.transform)
      const finer = transformed ? undefined : TradingTerminal.REPLAY_SUB[interval]
      let sub = finer ? await this.loadReplaySubBars() : null
      if (!member.isCurrent())
        throw new Error('Replay preparation was cancelled or the chart changed')
      let timing = replayTiming(interval, timezone, sub?.length ? finer : undefined)
      if (sub?.length) {
        const candidates = sub
        const endTime = timing.subBarEndTime!
        const valid = candidates.every((bar, index) => {
          if (![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite))
            return false
          if (index > 0 && bar.time <= candidates[index - 1].time) return false
          try {
            const end = endTime(bar, index)
            return (
              Number.isFinite(end) &&
              end > bar.time &&
              (index === candidates.length - 1 || end <= candidates[index + 1].time)
            )
          } catch {
            return false
          }
        })
        if (!valid) {
          sub = null
          this.replaySub = null
          timing = replayTiming(interval, timezone)
        }
      }
      const series = this.volume ? [price, this.volume] : [price]
      if (this.volumeMA) series.push(this.volumeMA)
      return {
        isCurrent: member.isCurrent,
        member: {
          id,
          chart,
          options: {
            series,
            // Inactive members must be prepared again from their current live series.
            timing,
            ...(sub?.length ? { subBars: sub } : {}),
            onFrame: (state) => {
              if (!member.isCurrent() || !member.active) return
              member.state = state
              this.refreshDisplayedVolume()
              this.refreshLegend(price.getData())
              this.profileLayer?.refresh(true)
              this.cb.onReplayChange?.(state)
            },
          },
        },
      }
    } catch (error) {
      this.restoreReplayMember(sessionId)
      throw error
    }
  }

  setReplayParticipation(sessionId: number, active: boolean, state?: ReplayState): void {
    const member = this.workspaceReplayMember
    if (!member || member.sessionId !== sessionId || !member.isCurrent()) return
    if (!active) {
      this.restoreReplayMember(sessionId)
      return
    }
    if (!member.active) {
      member.autoScale = member.price.priceScale().autoScale
      member.positioned = false
    }
    member.active = true
    member.preparing = false
    this.replayLoading = false
    member.data?.setPaused(true)
    member.chart.setAutoScale(true)
    this.showReplayMark(true)
    this.showTradeButtons(false)
    this.syncAlertPause()
    if (state) {
      member.state = state
      if (!member.positioned) {
        const to = state.index + 4
        member.chart.setVisibleLogicalRange(
          state.index > VISIBLE_BARS ? { from: to - VISIBLE_BARS, to } : { from: -1, to }
        )
        member.positioned = true
      }
      this.cb.onReplayChange?.(state)
    }
  }

  restoreReplayMember(sessionId: number): void {
    const member = this.workspaceReplayMember
    if (!member || member.sessionId !== sessionId || (!member.active && !member.preparing)) return
    member.active = false
    member.preparing = false
    member.state = null
    member.positioned = false
    this.replayLoading = false
    if (this.chart !== member.chart || this.price !== member.price) return
    let failed = false
    let failure: unknown
    const attempt = (action: () => void) => {
      try {
        action()
      } catch (error) {
        if (!failed) {
          failed = true
          failure = error
        }
      }
    }
    attempt(() => this.showReplayMark(false))
    attempt(() => member.chart.setAutoScale(member.autoScale))
    if (this.data === member.data) attempt(() => member.data?.setPaused(false))
    if (!this.destroyed) {
      attempt(() => this.setPriceData())
      attempt(() => this.refreshLegend())
      attempt(() => this.syncAlertPause())
      attempt(() => this.showTradeButtons(!this.workspaceReplayLocked))
      attempt(() => this.cb.onReplayChange?.(null))
    }
    if (failed) throw failure
  }

  /**
   * Order entry is closed while the chart is replaying, or while a start bar is
   * being picked.
   *
   * A replayed chart is a simulation, and an order placed from one is not: it
   * goes to the broker, at the live price, against a chart showing a session
   * that finished weeks ago. The two things a trader reads before pressing Buy,
   * the candles and the button's own price, disagree by however far back the
   * playhead is, and neither of them says so.
   *
   * Guarded here rather than only on the buttons, because every route into an
   * order has to close: the on-chart Buy and Sell, the context menu, a bracket,
   * dragging an order line to a new price, cancelling one, and closing a
   * position. A guard on the visible control is a guard on the route somebody
   * did not use.
   */
  private tradingLocked(): boolean {
    return (
      this.destroyed ||
      this.preparingWorkspace ||
      this.workspaceTransitionLocked ||
      this.workspaceReplayLocked ||
      this.alertDialogOpen() ||
      this.dataUnavailable() ||
      this.replay !== null ||
      this.replayOwnsDisplay() ||
      this.replayPicking ||
      this.replayLoading
    )
  }

  /** Locks existing panes while their owning page prepares a replacement grid. */
  setWorkspaceTransitionLocked(locked: boolean): void {
    this.workspaceTransitionLocked = locked
    this.syncAlertPause()
    if (!locked) this.saveAlerts()
  }

  private tradingLockMessage(): string {
    if (this.destroyed) return 'This chart is closed. Use the active chart to trade.'
    if (this.alertDialogOpen()) return 'Close the alert dialog before trading.'
    if (this.dataUnavailable())
      return 'Chart history is loading or unavailable. Wait for data before trading.'
    return this.preparingWorkspace || this.workspaceTransitionLocked
      ? 'Workspace is loading. Wait for it to finish before trading.'
      : 'Replay is a simulation. Leave replay to trade.'
  }

  /** Says no once, in the words of the reason, rather than doing nothing. */
  private refuseWhileReplaying(): boolean {
    if (!this.tradingLocked()) return false
    this.toast(this.tradingLockMessage(), 'err')
    return true
  }

  replayState(): ReplayState | null {
    return this.workspaceReplayMember?.state ?? this.replay?.state() ?? null
  }

  /**
   * Enter replay. Defaults to a quarter of the way in, so there is history to
   * read on the left and session left to walk on the right: opening on bar 0
   * shows an empty chart, which reads as broken.
   */
  /** True while the user is choosing a start bar. */
  replayPickingBar(): boolean {
    return this.replayPicking
  }

  replayLoadingBars(): boolean {
    return this.replayLoading
  }

  /**
   * Step one of replay: choose where to start.
   *
   * Opening a quarter of the way in quietly decided the exercise for the user.
   * The bar you start from is the whole premise ("from here, what happens
   * next?"), so it is picked, and while it is being picked everything to the
   * right is greyed. Choosing a start while able to read the next twenty bars is
   * choosing on hindsight, which is the one thing replay exists to remove.
   */
  startReplay(startIndex?: number): void {
    if (this.dataUnavailable()) return
    if (
      this.replayOwnsDisplay() ||
      this.replayPicking ||
      this.replayLoading ||
      !this.chart ||
      !this.price
    )
      return
    if (this.shownBars.length < 2) return
    if (startIndex !== undefined) {
      void this.beginReplayAt(startIndex)
      return
    }
    this.replayPicking = true
    this.syncAlertPause()
    this.replayPickIndex = Math.floor(this.shownBars.length / 4)
    this.setReplayShade(this.replayPickIndex)
    this.showTradeButtons(false)
    this.cb.onReplayChange?.(null)
  }

  /** The hovered bar, while the picker is open. Driven by the crosshair. */
  moveReplayPick(index: number | null): void {
    if (!this.replayPicking || index === null) return
    const total = this.shownBars.length
    if (total === 0) return
    const clamped = Math.max(0, Math.min(total - 1, Math.round(index)))
    if (clamped === this.replayPickIndex) return
    this.replayPickIndex = clamped
    this.setReplayShade(clamped)
    this.publishReplayPreview()
  }

  /** The bar under the cursor right now, for a host that labels the prompt. */
  replayPickBar(): Bar | null {
    if (this.replayPickIndex === null) return null
    return this.shownBars[this.replayPickIndex] ?? null
  }

  /** Commit the pick. A click on the plot lands here. */
  commitReplayPick(): void {
    if (!this.replayPicking || this.replayPickIndex === null) return
    const workspace = this.workspaceReplayPick
    if (workspace) {
      const index = this.replayPickIndex
      const bar = this.shownBars[index]
      if (!bar || !this.chart) return
      try {
        const time = replayTiming(this.interval, this.chart.timezone()).barEndTime(bar, index)
        this.workspaceReplayPick = null
        this.replayPicking = false
        this.replayPickIndex = null
        this.setReplayShade(null)
        workspace.onPick(time)
      } catch (error) {
        this.toast(this.cleanError(error), 'err')
        this.cancelReplayPick()
      }
      return
    }
    void this.beginReplayAt(this.replayPickIndex)
  }

  cancelReplayPick(): void {
    if (this.replayLoading) {
      this.stopReplay()
      return
    }
    if (!this.replayPicking) return
    const workspace = this.workspaceReplayPick
    this.workspaceReplayPick = null
    this.replayPicking = false
    this.replayPickIndex = null
    this.syncAlertPause()
    this.setReplayShade(null)
    this.showTradeButtons(true)
    this.cb.onReplayChange?.(null)
    workspace?.onCancel()
  }

  /**
   * Move (or raise, or clear) the veil on every pane.
   *
   * Per pane and built lazily, because a pane can appear while the picker is
   * open and one left bright to the right of the cut shows exactly what the
   * shade is hiding on the pane above it.
   */
  private setReplayShade(index: number | null): void {
    if (!this.chart) return
    const panes = this.chart.panes()
    for (let i = this.replayShades.length; i < panes.length; i++) {
      const shade = new ReplayShade({ index: null, lineVisible: i === 0 })
      this.chart.addPrimitive(shade, i)
      this.replayShades.push(shade)
    }
    for (const shade of this.replayShades) shade.setOptions({ index })
  }

  /**
   * Step two: walk forward from the chosen bar.
   *
   * The veil comes off here rather than staying on the un-walked future, because
   * replay truncates the series: past the playhead there is nothing left to
   * cover.
   */
  private async beginReplayAt(startIndex: number): Promise<void> {
    if (
      this.replay ||
      this.replayLoading ||
      !this.chart ||
      !this.price ||
      this.shownBars.length < 2
    )
      return
    const chart = this.chart
    const price = this.price
    const data = this.data
    const ticket = ++this.replayLoadTicket
    this.replayLoading = true
    this.syncAlertPause()
    data?.setPaused(true)
    this.replayPicking = false
    this.showTradeButtons(false)
    this.cb.onReplayChange?.(null)
    this.setReplayShade(null)
    const driven = this.volume ? [this.price, this.volume] : [this.price]
    if (this.volumeMA) driven.push(this.volumeMA)
    // Walk what the price series is showing, not the raw feed: on Heikin Ashi
    // or Renko those are different arrays of different lengths, so replaying
    // rawBars would repaint the chart as plain candles and put the playhead at
    // the wrong bar.
    // Copied, not aliased. Untransformed, `shownBars` *is* `rawBars`, which
    // the tick path pushes to, so handing it over directly let the replay set
    // grow while it was being walked: the total moved and the end of the session
    // receded with every tick that arrived.
    const bars = this.shownBars.slice()
    const from = Math.max(0, Math.min(bars.length - 1, Math.floor(startIndex)))
    const sub = await this.loadReplaySubBars()
    // The await above yields, and the user may have left in the meantime.
    if (
      this.destroyed ||
      chart !== this.chart ||
      price !== this.price ||
      ticket !== this.replayLoadTicket ||
      this.replay
    ) {
      // Do not unpause a newer replay attempt that superseded this await.
      if (
        !this.destroyed &&
        data === this.data &&
        ticket === this.replayLoadTicket &&
        !this.replay
      ) {
        this.replayLoading = false
        data?.setPaused(false)
        this.syncAlertPause()
        this.showTradeButtons(true)
        this.cb.onReplayChange?.(null)
      }
      return
    }
    this.replay = new ReplayController(this.chart, {
      series: driven,
      bars,
      startIndex: from,
      subBars: sub ?? undefined,
      onFrame: (state) => {
        this.refreshDisplayedVolume()
        this.refreshLegend(price.getData())
        this.profileLayer?.refresh(true)
        this.cb.onReplayChange?.(state)
      },
    })
    this.replayLoading = false
    this.showReplayMark(true)
    this.showTradeButtons(false)
    // Entering replay truncates the series to a prefix, but leaves the viewport
    // and the price range where the user had them -- which is at the right edge
    // on the newest bars, hundreds of bars past the end of that prefix and at a
    // price the prefix never trades at. The result is an apparently empty chart
    // with the candles clipped off the top. Put the view on the playhead and
    // re-measure the axis, the same way the initial load does.
    const to = from + 4
    this.chart.timeScale.setVisibleLogicalRange(
      from > VISIBLE_BARS ? { from: to - VISIBLE_BARS, to } : { from: -1, to }
    )
    // Remembered so a hand-pinned axis is not silently lost: replay has to
    // autoscale to stay readable as it walks, but that is replay's state, not
    // a change to the chart the user set up.
    this.replayAutoScale = this.chart.panes()[0]?.priceScale.autoScale ?? true

    this.chart.setAutoScale(true)
    this.cb.onReplayChange?.(this.replay.state())
  }

  /**
   * The base-interval session under the displayed one.
   *
   * Closed bars are immutable, so this is cached for the interval it belongs to
   * and re-fetched only when the interval changes. It deliberately reads through
   * the plain REST feed rather than the bar cache: the cache is keyed on the
   * chart's own interval, and a replay set is history, so there is nothing here
   * for a forming-bar rule to protect.
   *
   * A failure is not an error the user needs to see. Replay falls back to
   * whole-bar steps, which is what it did before this existed.
   */
  private async loadReplaySubBars(): Promise<Bar[] | null> {
    const interval = this.interval
    const finer = TradingTerminal.REPLAY_SUB[interval]
    const sym = this.sym
    const rest = this.rest
    if (!finer || !sym || !rest) return null
    if (
      this.replaySub?.interval === interval &&
      this.replaySub.symbol === sym.symbol &&
      this.replaySub.exchange === sym.exchange
    )
      return this.replaySub.bars
    const request = new AbortController()
    this.replayHistoryAbort?.abort()
    this.replayHistoryAbort = request
    try {
      const to = this.gridNow()
      const bars = await rest.getBars({
        symbol: sym.symbol,
        exchange: sym.exchange,
        interval: finer,
        from: to - lookbackDays(interval) * 86400,
        to,
        signal: request.signal,
      })
      if (
        request.signal.aborted ||
        !bars.length ||
        this.destroyed ||
        this.sym !== sym ||
        this.interval !== interval
      )
        return null
      this.replaySub = { interval, symbol: sym.symbol, exchange: sym.exchange, bars }
      return bars
    } catch {
      return null
    } finally {
      if (this.replayHistoryAbort === request) this.replayHistoryAbort = null
    }
  }

  /**
   * The mode marker. A chart replaying August looks exactly like a chart showing
   * today, and reading a live decision off history is the mistake this prevents,
   * so it goes on with replay and comes off with it.
   */
  /**
   * Take the Buy and Sell buttons off the chart, or put them back.
   *
   * Removing rather than grey-ing: the panel quotes a live price, and a live
   * price sitting over a replayed session is the confusion this exists to
   * remove, whether or not it can be pressed. `removePrimitive` only marks the
   * pane dirty, so the chart repaints them away on the next frame.
   */
  private showTradeButtons(on: boolean): void {
    if (!this.chart || !this.tradeBtns) return
    if (this.workspaceReplayLocked) on = false
    if (on) this.chart.addPrimitive(this.tradeBtns, 0)
    else this.chart.removePrimitive(this.tradeBtns)
  }

  private showReplayMark(on: boolean): void {
    if (!this.chart) return
    if (on) {
      if (!this.replayMark) {
        this.replayMark = new TextWatermark({ text: 'Replay' })
        this.chart.addPrimitive(this.replayMark, 0)
      } else {
        this.replayMark.setOptions({ text: 'Replay' })
      }
    } else if (this.replayMark) {
      this.replayMark.setOptions({ text: '' })
    }
  }

  /** Leave replay and put the live chart back exactly where the user left it. */
  stopReplay(): void {
    this.replayInvalidation?.()
    const member = this.workspaceReplayMember
    if (member) {
      this.restoreReplayMember(member.sessionId)
      member.detachAbort()
      this.workspaceReplayMember = null
    }
    this.replayLoadTicket++
    this.replayHistoryAbort?.abort()
    this.replayHistoryAbort = null
    const wasLoading = this.replayLoading
    this.replayLoading = false
    this.cancelReplayPick()
    this.data?.setPaused(false)
    if (!this.replay) {
      if (wasLoading) {
        this.showTradeButtons(true)
        this.cb.onReplayChange?.(null)
      }
      this.syncAlertPause()
      return
    }
    this.replay.stop()
    this.replay = null
    this.showReplayMark(false)
    this.showTradeButtons(true)
    if (!this.replayAutoScale) this.chart?.setAutoScale(false)
    // The session kept accumulating in rawBars while replay held the series, so
    // the live chart comes back caught up rather than frozen at the moment
    // replay started. Only a transformed chart has to rebuild from scratch.
    this.setPriceData()
    this.refreshLegend()
    this.syncAlertPause()
    this.cb.onReplayChange?.(null)
  }

  replayPlay(speed?: number): void {
    this.replay?.play(speed === undefined ? undefined : { speed })
    this.cb.onReplayChange?.(this.replayState())
  }

  replayPause(): void {
    this.replay?.pause()
    this.cb.onReplayChange?.(this.replayState())
  }

  replayStep(n = 1): void {
    this.replay?.step(n)
  }

  replayStepBack(n = 1): void {
    this.replay?.stepBack(n)
  }

  replaySeek(index: number): void {
    this.replay?.seek(index)
  }

  /* ── WS-down fallback: poll quotes so LTP + the forming candle stay live ─ */
  private startLtpFallback() {
    if (this.ltpPollTimer) return
    this.ltpPollTimer = setInterval(async () => {
      if (!this.sym) return
      if (this.sym.synthetic && this.expr) {
        // A combination polls each leg and folds, the same as the socket path.
        try {
          for (const leg of this.expr.symbols) {
            const r = resolveLeg(leg, this.exprLegExchange)
            const j = await this.api<{ data?: { ltp?: number } }>('quotes', {
              symbol: r.symbol,
              exchange: r.exchange,
            })
            if (typeof j.data?.ltp === 'number' && j.data.ltp > 0) this.legLtp.set(leg, j.data.ltp)
          }
          this.onCombinedTick(this.expr, nowSec())
          this.cb.onWsState('fallback')
        } catch {
          /* next cycle */
        }
        return
      }
      try {
        const j = await this.api<{ data?: { ltp?: number; bid?: number; ask?: number } }>(
          'quotes',
          {
            symbol: this.sym.symbol,
            exchange: this.sym.exchange,
          }
        )
        const q = j.data || {}
        if (typeof q.ltp === 'number' && q.ltp > 0)
          this.onTick({ symbol: this.sym.symbol, ltp: q.ltp, timeSec: nowSec() })
        if (
          this.tradeBtns &&
          typeof q.bid === 'number' &&
          typeof q.ask === 'number' &&
          q.bid > 0 &&
          q.ask > 0
        ) {
          this.depthActive = true
          this.tradeBtns.setPrices(q.bid, q.ask)
        }
        this.cb.onWsState('fallback')
      } catch {
        /* next cycle */
      }
    }, 4000)
  }
  private stopLtpFallback() {
    if (this.ltpPollTimer) {
      clearInterval(this.ltpPollTimer)
      this.ltpPollTimer = null
    }
  }

  /* single tick path shared by WS pushes and the REST fallback */
  private onTick(e: { symbol?: string; ltp: number; ltq?: number; timeSec?: number }) {
    if (!this.sym || (e.symbol && e.symbol !== this.sym.symbol)) return
    this.lastLtp = e.ltp
    this.cb.onLtp(e.ltp)
    // Recolour with the price: the line belongs to the forming candle, so it
    // follows that candle's direction rather than sitting amber forever.
    if (this.position && this.posLine) this.posLine.setLeftLabel(this.posLabel())
    if (this.tradeBtns && !this.depthActive) this.tradeBtns.setMark(e.ltp)
    if (this.builder) {
      const u = this.builder.onTick({ time: e.timeSec || nowSec(), price: e.ltp, ltq: e.ltq })
      if (u) {
        this.liveBucket = u.bar.time
        // Key the upsert on time rather than the builder's isNew flag, so a
        // builder that ever disagrees with rawBars about the current bucket
        // overwrites that bar instead of appending a duplicate of it.
        const last = this.rawBars[this.rawBars.length - 1]
        if (last && last.time === u.bar.time) this.rawBars[this.rawBars.length - 1] = u.bar
        else this.rawBars.push(u.bar)
        // History and live bars share one bounded store. The terminal retains
        // its existing single WS subscription and supplies its built bar here.
        // A bucket the builder opened mid-way, because history stopped one bar
        // short or the socket came back, is provisional: history keeps the open.
        if (u.provisional) this.data?.pushBar(u.bar, { provisional: true })
        else this.data?.pushBar(u.bar)
        // Replay owns the series while it is running. Writing the live bar into
        // it puts a candle at the current wall-clock bucket, at the current
        // price, hundreds of bars past the playhead: a lone spike far from the
        // replayed action that drags the price axis and the last-price line with
        // it, then vanishes on the next replay frame when setData rewrites the
        // prefix. rawBars keeps accumulating either way, so leaving replay finds
        // the session already caught up.
        if (this.replayOwnsDisplay()) {
          this.cb.onLtp(e.ltp)
          return
        }
        // One bar in, one bar out. Only a transformed chart has to rebuild.
        if (!this.updateLiveBar(u.bar)) this.setPriceData()
      }
    }
    // The legend belongs to the bar on screen. During replay that is the
    // playhead's, written by onReplayChange, not the live one.
    if (!this.replayOwnsDisplay()) {
      this.refreshLegend()
    }
  }

  /* ── live data: WS ticks → candles; depth → bid/ask ───────────────────── */
  private connectLive() {
    if (!this.ws || !this.sym) return
    const sec = intervalSeconds(this.interval)
    // Broker history is already aligned to the instrument's actual session.
    // Using one known bar as the congruent anchor preserves openings such as
    // 09:15 for hourly candles instead of snapping them to the Unix epoch.
    const sessionAnchorSec = this.rawBars[this.rawBars.length - 1]?.time ?? 0
    this.builder = sec
      ? new CandleBuilder({ intervalSec: sec, volumeMode: 'ltq-sum', sessionAnchorSec })
      : null
    // History normally ends *inside* the bar currently forming. An unseeded
    // builder has no current bar, so its first tick opens a second one for that
    // same bucket -- opening at whatever tick price arrives first instead of the
    // bucket's true open, restarting volume at 0, and leaving rawBars with two
    // entries for one time. Seeding hands it the last bar so ticks fold into it.
    if (this.builder && this.rawBars.length) {
      this.builder.seed(this.rawBars[this.rawBars.length - 1])
    }
    this.depthActive = false
    if (this.offLtp) {
      this.offLtp()
      this.offLtp = null
    }
    if (this.offDepth) {
      this.offDepth()
      this.offDepth = null
    }
    this.offLtp = this.ws.onLtp((e: LtpEvent) => {
      this.cb.onWsState('live')
      this.stopLtpFallback()
      this.onTick(e)
    })
    this.offDepth = this.ws.onDepth((symbol: string, _exchange: string, depth: MarketDepth) => {
      if (!this.sym || symbol !== this.sym.symbol) return
      const bid = depth.bids?.[0]?.price
      const ask = depth.asks?.[0]?.price
      if (typeof bid === 'number' && typeof ask === 'number' && bid > 0 && ask > 0) {
        this.depthActive = true
        if (this.tradeBtns) this.tradeBtns.setPrices(bid, ask)
      }
      // Depth is the terminal's ONLY subscription for tradeable instruments,
      // so the chart ticks off depth.ltp -- a first-class field in every mode-3
      // payload per the WebSocket protocol (docs/prompt/websockets-format.md).
      // This replaced the old dual LTP+Depth subscribe, which broke on brokers
      // whose adapters track one mode per symbol (Depth overwrote LTP and the
      // chart froze while depth kept flowing -- issue #1664).
      if (typeof depth.ltp === 'number' && depth.ltp > 0) {
        this.cb.onWsState('live')
        this.stopLtpFallback()
        // Depth has an exchange timestamp but no classified trade quantity in
        // the OpenAlgo mode-3 contract. Preserve its time and leave volume for
        // the authoritative history reconcile.
        this.onTick({ ltp: depth.ltp, timeSec: depth.timeSec })
      }
    })
    // One subscription per symbol, mode picked by instrument type: indices
    // have no order book (LTP), tradeables get Depth which embeds ltp.
    if (this.sym.quoteOnly) {
      this.ws.subscribe('LTP', this.sym.symbol, this.sym.exchange)
    } else {
      this.ws.subscribe('Depth', this.sym.symbol, this.sym.exchange, 5)
    }
  }

  /* ── live data for a combination: one LTP stream per leg, folded per tick ── */
  private connectExpressionLive(expr: SymbolExpression) {
    if (!this.ws) return
    const sec = intervalSeconds(this.interval)
    const sessionAnchorSec = this.rawBars[this.rawBars.length - 1]?.time ?? 0
    // The builder aggregates the folded value, so the forming bar's open, high
    // and low belong to the combination rather than to any one leg. Seeded from
    // the folded history like an instrument's builder: when history stopped one
    // bucket short, the first tick opens a provisional bar and the repair after
    // the bar closes brings the open it missed.
    this.builder = sec
      ? new CandleBuilder({ intervalSec: sec, volumeMode: 'ltq-sum', sessionAnchorSec })
      : null
    if (this.builder && this.rawBars.length) {
      this.builder.seed(this.rawBars[this.rawBars.length - 1])
    }
    // Every leg starts at the close its history ended on, so the first tick of
    // any one leg already has a price for the others to fold with.
    this.legLtp.clear()
    for (const leg of expr.symbols) {
      const rows = this.exprFeed?.legBars[leg]
      const last = rows?.[rows.length - 1]
      if (last) this.legLtp.set(leg, last.close)
    }
    this.depthActive = false
    if (this.offLtp) {
      this.offLtp()
      this.offLtp = null
    }
    if (this.offDepth) {
      this.offDepth()
      this.offDepth = null
    }
    this.offLtp = this.ws.onLtp((e: LtpEvent) => {
      const leg = this.legFor(expr, e.symbol, e.exchange)
      if (!leg) return
      this.cb.onWsState('live')
      this.stopLtpFallback()
      this.legLtp.set(leg, e.ltp)
      this.onCombinedTick(expr, e.timeSec)
    })
    this.legSubs = expr.symbols.map((leg) => resolveLeg(leg, this.exprLegExchange))
    for (const leg of this.legSubs) this.ws.subscribe('LTP', leg.symbol, leg.exchange)
  }

  /** Which leg of the expression a tick belongs to, or null when it is not ours. */
  private legFor(expr: SymbolExpression, symbol: string | undefined, exchange: string | undefined) {
    if (!symbol) return null
    for (const leg of expr.symbols) {
      const r = resolveLeg(leg, this.exprLegExchange)
      if (r.symbol === symbol && (!exchange || r.exchange === exchange)) return leg
    }
    return null
  }

  /** Fold the latest price of every leg into one tick for the combined series. */
  private onCombinedTick(expr: SymbolExpression, timeSec?: number) {
    const legs: Record<string, Bar[]> = {}
    for (const leg of expr.symbols) {
      const p = this.legLtp.get(leg)
      if (p === undefined) return // a leg without a price cannot be folded yet
      legs[leg] = [{ time: 0, open: p, high: p, low: p, close: p }]
    }
    const value = evaluateExpression(expr, legs)[0]?.close
    // A divisor at zero folds to a gap, and a gap is not a price.
    if (value === undefined || !Number.isFinite(value)) return
    this.onTick({ ltp: value, timeSec })
  }

  /** Repair a known stream gap immediately through the shared data owner. */
  private reconcileNow(): void {
    void this.runReconcile()
  }

  private async runReconcile(): Promise<void> {
    const ticket = this.loadTicket
    const sym = this.sym
    const interval = this.interval
    const data = this.data
    const rest = this.rest
    if (!this.destroyed && sym && data) {
      await data.refresh()
      if (
        this.destroyed ||
        ticket !== this.loadTicket ||
        sym !== this.sym ||
        interval !== this.interval ||
        data !== this.data
      )
        return
      this.applyDataSnapshot(data.getState())
      return
    }
    try {
      if (!this.destroyed && sym && rest) {
        const to = nowSec()
        const fresh = await rest.getBars({
          symbol: sym.symbol,
          exchange: sym.exchange,
          interval,
          from: to - Math.min(3, lookbackDays(interval)) * 86400,
          to,
        })
        // A response belongs to the load that requested it, even when a new
        // load selects the same symbol. It must not mutate the next session.
        if (
          this.destroyed ||
          ticket !== this.loadTicket ||
          sym !== this.sym ||
          interval !== this.interval ||
          rest !== this.rest
        )
          return
        const byTime = new Map(fresh.map((b) => [b.time, b]))
        let changed = false
        for (let i = 0; i < this.rawBars.length; i++) {
          const f = byTime.get(this.rawBars[i].time)
          if (f && (this.liveBucket == null || f.time < this.liveBucket)) {
            this.rawBars[i] = f
            changed = true
          }
        }

        // Insert the bars we never built at all.
        //
        // The loop above only snaps bars already on the chart, so a bucket
        // the client missed outright stayed missing until a reload. It goes
        // missing whenever the tick stream is not running for a whole
        // interval: the socket drops, the feed pauses because the tab was
        // hidden, or the machine sleeps. The candles either side are fine,
        // so the chart shows a clean hole and the OHLC legend disagrees with
        // the broker for those buckets.
        //
        // `fresh` already holds them, and this is the one place that has
        // both sides to compare. Only closed buckets are filled: the
        // forming bar belongs to the tick stream, which is fresher than a
        // poll and must never be overwritten by it.
        if (this.rawBars.length > 0) {
          const known = new Set(this.rawBars.map((b) => b.time))
          const earliest = this.rawBars[0].time
          const missing = fresh.filter(
            (b) =>
              b.time > earliest &&
              !known.has(b.time) &&
              (this.liveBucket == null || b.time < this.liveBucket)
          )
          if (missing.length > 0) {
            // Merge and re-sort rather than splice at a found index: a
            // history page landing between the fetch and this line would
            // invalidate any index computed before the await.
            this.rawBars = [...this.rawBars, ...missing].sort((a, b) => a.time - b.time)
            changed = true
          }
        }
        // The forming bar's volume cannot come from the tick stream. A
        // tradeable's only subscription is Depth, and a depth payload
        // carries ltp but no last-traded-qty, so 'ltq-sum' has nothing to
        // accumulate and the live bar reads 0 on a symbol visibly trading.
        // History is the only source that has it, so take it from there --
        // and take only it. OHLC stays with the ticks, which are fresher
        // than a 30-second poll and must not jump backwards to it.
        if (this.builder && this.liveBucket != null) {
          const f = byTime.get(this.liveBucket)
          const cur = this.builder.current()
          if (f && cur && cur.time === this.liveBucket) {
            // Volume inside a bar only ever grows, so the higher of the two
            // is the later reading. It also keeps the histogram monotonic
            // when a poll lands mid-print and briefly reports less.
            const vol = Math.max(f.volume ?? 0, cur.volume ?? 0)
            if (vol !== (cur.volume ?? 0)) {
              // Re-seed rather than patch rawBars alone: the builder folds
              // the next tick into its own copy of the bar, which would
              // write the stale volume straight back over this.
              this.builder.seed({ ...cur, volume: vol })
              const last = this.rawBars[this.rawBars.length - 1]
              if (last && last.time === this.liveBucket) {
                this.rawBars[this.rawBars.length - 1] = { ...last, volume: vol }
                changed = true
              }
            }
          }
        }
        if (changed) this.setPriceData()
      }
    } catch {
      /* next cycle retries */
    }
  }

  /** Monotonic id for the most recent loadSymbol; older loads abandon. */
  private loadTicket = 0

  /* ── symbol selection ─────────────────────────────────────────────────── */
  /**
   * Chart an expression over several instruments: `NIFTY/RELIANCE`,
   * `2*CE25000 - CE25200`, `(A+B)/2`.
   *
   * History goes through the same controller as an instrument, behind a feed
   * that fetches every leg and folds them, so the warm load, the repair after
   * each bar closes and the gap repair all apply. Live ticks arrive per leg
   * and are folded into one series by `connectExpressionLive`. The result is
   * never allowed to look tradeable.
   */
  private async loadExpression(
    source: string,
    ticket: number,
    opts: { silent?: boolean }
  ): Promise<boolean> {
    let expr: SymbolExpression
    try {
      expr = parseExpression(source)
    } catch (e) {
      if (!opts.silent) this.toast(`${this.cleanError(e)}`, 'err')
      return false
    }

    // A bare leg inherits the exchange of whatever the pane showed before,
    // which is what a trader typing `NIFTY/RELIANCE` means. Remembered here so
    // every later repair resolves the legs the same way the load did.
    if (!this.sym?.synthetic) this.exprLegExchange = this.sym?.exchange || 'NSE'
    const to = this.gridNow()
    const request = {
      symbol: source,
      exchange: '',
      interval: this.interval,
      from: to - lookbackDays(this.interval) * 86400,
      to,
    }
    const inner = this.cachedBars ?? this.rest
    if (!inner) return false
    const feed = this.exprFeed ?? new ExpressionFeed(inner, () => this.exprLegExchange)
    let bars: readonly Bar[]
    try {
      bars = this.data ? await this.data.load(request) : await feed.getBars(request)
    } catch (e) {
      if (this.destroyed || ticket !== this.loadTicket) return false
      this.rawBars = []
      if (!opts.silent) this.toast(`${source}: ${this.cleanError(e)}`, 'err')
      return false
    }
    if (this.destroyed || ticket !== this.loadTicket) return false
    if (!bars.length) {
      // The controller resolves with what it has and reports the failure in
      // its state: a missing leg is an error, legs that never share a bar are
      // an empty result.
      this.rawBars = []
      const error = this.data?.getState().error
      if (!opts.silent) {
        this.toast(
          `${source}: ${error ? this.cleanError(error) : `the legs share no bars on ${this.interval}`}`,
          'err'
        )
      }
      return false
    }

    // `quoteOnly` keeps the product picker and the depth ladder away; `synthetic`
    // is what the order path refuses by name.
    this.sym = {
      symbol: source,
      exchange: '',
      name: 'Computed chart',
      lotsize: 1,
      lots: false,
      tick: 0,
      freezeQty: 1,
      quoteOnly: true,
      synthetic: true,
      hasOpenInterest: false,
      productOptions: [],
      product: '',
    }
    this.rawBars = [...bars]
    this.lastLtp = null
    this.liveBucket = null
    this.noMoreHistory = false // the feed pages every leg
    this.expr = expr
    this.buildChart()
    this.connectExpressionLive(expr)
    return true
  }

  async loadSymbol(
    pick: SearchRow,
    opts: { silent?: boolean; strict?: boolean } = {}
  ): Promise<boolean> {
    if (this.destroyed || !this.rest) return false
    const ticket = ++this.loadTicket
    this.historyPending = true
    this.historyFailed = false
    this.syncAlertPause()
    this.alertUi?.close()
    this.showTradeButtons(false)
    let loaded = false
    try {
      const result = await this.loadSymbolRequest(pick, opts, ticket)
      if (result && !this.destroyed && ticket === this.loadTicket) await this.chartToolsReady
      loaded = result
      return loaded && !this.destroyed && ticket === this.loadTicket
    } finally {
      if (!this.destroyed && ticket === this.loadTicket) {
        this.historyPending = false
        this.historyFailed = !loaded
        this.syncAlertPause()
        this.showTradeButtons(loaded)
        if (loaded && !this.preparingWorkspace) this.cb.onWorkspaceChange?.()
      }
    }
  }

  dataUnavailable(): boolean {
    return this.historyPending || this.historyFailed
  }

  private async loadSymbolRequest(
    pick: SearchRow,
    opts: { silent?: boolean; strict?: boolean },
    ticket: number
  ): Promise<boolean> {
    const feed = this.cachedBars ?? this.rest
    if (!feed) return false
    /**
     * Claim this load. Two awaits follow -- the symbol lookup and the bars --
     * and a second call arriving inside either of them used to run to
     * completion alongside this one. Both then reached buildChart, and the
     * indicator re-apply of the FIRST resumed against the chart the SECOND had
     * just created, adding every tracked indicator twice. syncIndicators read
     * that back as the tracked list, so the next rebuild doubled it again:
     * clicking down an option chain left thirty copies of one indicator's
     * legend covering the chart.
     */
    // Replay holds a snapshot of the bars it was started on, and stop() puts
    // that snapshot back. Carrying it across a symbol change would restore the
    // previous instrument's data onto the new one.
    this.stopReplay()
    this.comparisons?.detach()
    // swap the live stream: drop the previous symbol's subscription
    if (
      this.ws &&
      this.sym &&
      (this.sym.symbol !== pick.symbol || this.sym.exchange !== pick.exchange)
    ) {
      // Mirror connectLive's single-subscription model: the outgoing symbol
      // holds exactly one mode -- LTP when quote-only, Depth otherwise. A
      // combination holds one LTP subscription per leg instead.
      try {
        if (this.sym.synthetic) {
          for (const leg of this.legSubs) this.ws.unsubscribe('LTP', leg.symbol, leg.exchange)
          this.legSubs = []
          this.legLtp.clear()
          this.expr = null
        } else if (this.sym.quoteOnly) {
          this.ws.unsubscribe('LTP', this.sym.symbol, this.sym.exchange)
        } else {
          this.ws.unsubscribe('Depth', this.sym.symbol, this.sym.exchange)
        }
      } catch {
        /* not subscribed */
      }
    }
    // An expression is not an instrument: there is no master record to look up,
    // no lot size, no tick and nothing to subscribe to. It takes its own path
    // and never reaches the order machinery below.
    //
    // **An exchange is what says this is an instrument.** Reading the symbol
    // alone cannot tell `BAJAJ-AUTO` from a subtraction, because to the chart's
    // grammar that is exactly what it is: `isPlainSymbol` returns false and
    // `parseExpression` succeeds, so a name with a hyphen in it was sent down
    // the expression path and fetched as `BAJAJ` minus `AUTO`, two instruments
    // that do not exist. The symbol search picked the instrument correctly and
    // this threw the choice away, which is why the chart reported a 400 for a
    // symbol the platform resolves perfectly well.
    //
    // A computed chart carries no exchange and never can: it is several
    // instruments, possibly on different ones. So the exchange is the thing
    // that settles it, and it does not require guessing at the name.
    if (pick.expression === true || (!pick.exchange && isChartExpression(pick.symbol))) {
      return await this.loadExpression(pick.symbol, ticket, opts)
    }
    // authoritative metadata (lotsize / tick_size / freeze_qty)
    let info: Record<string, unknown> = { ...pick }
    try {
      const j = await this.api<{ data?: Record<string, unknown> }>('symbol', {
        symbol: pick.symbol,
        exchange: pick.exchange,
      })
      if (
        opts.strict &&
        (!j.data || j.data.symbol !== pick.symbol || j.data.exchange !== pick.exchange)
      )
        throw new Error(`Workspace symbol metadata is unavailable: ${pick.exchange}:${pick.symbol}`)
      info = { ...pick, ...(j.data || {}) }
    } catch (error) {
      if (opts.strict) throw error
      /* search row already carries the essentials */
    }
    // A newer load claimed the pane while this one was waiting.
    if (this.destroyed || ticket !== this.loadTicket) return false
    const exchange = String(info.exchange)
    const lotsize = Number(info.lotsize) || 1
    // The segment decides this, never the lot size. Every MCX, NCO and CDS
    // contract carries lotsize 1 in the master, so a `lotsize > 1` guard read
    // them as cash equity and offered CNC — which those segments do not accept,
    // so the broker rejected the order. Quantity is unaffected: orderQty() is
    // lots × lotsize, and multiplying by a lot size of 1 sends the same number.
    const lots = usesLots(exchange)
    const savedProduct = this.lsGet('product')
    const productOptions = productOptionsFor(exchange)
    this.product = productOptions.includes(savedProduct || '')
      ? (savedProduct as string)
      : productOptions[0]
    this.sym = {
      symbol: String(info.symbol),
      exchange,
      name: String(info.name || ''),
      lotsize,
      lots,
      tick: resolveTick(exchange, info.tick_size),
      freezeQty: Number(info.freeze_qty) || 1,
      quoteOnly: QUOTE_ONLY.has(exchange),
      hasOpenInterest: openInterestCapability(exchange, info),
      productOptions,
      product: this.product,
    }
    this.qty = 1
    this.lsSet('symbol', JSON.stringify({ symbol: this.sym.symbol, exchange: this.sym.exchange }))
    // Tell the group before the history fetch below, so a linked grid starts
    // loading together rather than one pane at a time. The group's own echo
    // guard stops this coming straight back at us.
    if (this.link && this.chart) this.link.setSymbol(this.chart, `${exchange}:${this.sym.symbol}`)

    // history
    const to = this.gridNow()
    this.lastLtp = null
    this.liveBucket = null
    this.noMoreHistory = false
    let bars: readonly Bar[]
    try {
      const request = {
        symbol: this.sym.symbol,
        exchange: this.sym.exchange,
        interval: this.interval,
        from: to - lookbackDays(this.interval) * 86400,
        to,
      }
      bars = this.data ? await this.data.load(request) : await feed.getBars(request)
    } catch (e) {
      if (this.destroyed || ticket !== this.loadTicket) return false
      this.rawBars = []
      if (!opts.silent) this.toast(`history error: ${this.cleanError(e)}`, 'err')
      return false // caller may fall back (e.g. to the default symbol)
    }
    // Validate before assigning: an older response must neither overwrite the
    // active session nor recreate a chart after its terminal was destroyed.
    if (this.destroyed || ticket !== this.loadTicket) return false
    this.rawBars = [...bars]
    if (!this.rawBars.length) {
      if (!opts.silent) {
        const error = this.data?.getState().error
        this.toast(
          error
            ? `history error: ${this.cleanError(error)}`
            : `no history for ${this.sym.symbol} ${this.sym.exchange} ${this.interval}`,
          'err'
        )
      }
      return false
    }
    this.lastLtp = this.rawBars[this.rawBars.length - 1].close
    const key = this.dataKey({
      symbol: this.sym.symbol,
      exchange: this.sym.exchange,
      interval: this.interval,
    })
    if (!this.chart || !this.price || !this.volume || this.chartDataKey !== key) {
      this.chartDataKey = key
      this.buildChart()
    } else {
      this.setPriceData()
      this.installComparisons()
    }
    this.cb.onLtp(this.lastLtp)
    this.cb.onSymbolLoaded(this.sym)

    // live subscription (swap the previous symbol's stream)
    this.connectLive()
    this.pollBook()
    return true
  }

  /* ── toolbar setters (called by the React page) ───────────────────────── */
  setInterval(iv: string): string {
    if (iv === this.interval) return iv
    if (!this.availableIntervals.includes(iv)) {
      this.toast(`The connected feed does not support ${iv}`, 'err')
      return this.interval
    }
    if (
      isProfileKind(this.ctype) &&
      !profileIntervalSupported(this.ctype, iv, this.profileBlockMinutes())
    ) {
      this.toast(
        this.ctype === 'tpo'
          ? 'Choose an intraday interval that divides the TPO block size'
          : 'Session Volume Profile requires an intraday interval',
        'err'
      )
      return this.interval
    }
    this.stopReplay() // same reason as loadSymbol: the bars are about to change
    this.interval = iv
    this.lsSet('interval', iv)
    this.cb.onIntervalChange?.(iv)
    if (this.link && this.chart) this.link.setInterval(this.chart, iv)
    if (this.sym) this.reloadCurrent()
    return iv
  }
  setChartType(v: string): string {
    if (!CHART_TYPES[v]) return this.ctype
    const interval = isProfileKind(v) ? this.compatibleProfileInterval(v) : this.interval
    if (!interval) {
      this.toast('The broker has no intraday interval compatible with this profile', 'err')
      return this.ctype
    }
    this.stopReplay()
    this.ctype = v
    this.lsSet('ctype', v)
    if (interval !== this.interval) {
      this.setInterval(interval)
      this.toast(`Using ${interval} bars for ${CHART_TYPES[v].label}`, '')
    } else if (this.rawBars.length) this.buildChart()
    return v
  }
  setProduct(p: string) {
    this.product = p
    this.lsSet('product', p)
  }
  setQty(n: number) {
    this.qty = Math.max(1, Math.floor(n || 1))
    if (this.tradeBtns) this.tradeBtns.setQty(this.qtyChip())
  }
  /**
   * One-Click on or off. Nothing here gates a risk-reducing action: the
   * position pill's close, an order line's cancel and drag-to-modify work the
   * same either way, as they do on the scalping terminal.
   */
  setArmed(on: boolean) {
    if (this.armed === on) return
    this.armed = on
    this.applyTradeColors()
  }
  oneClickArmed(): boolean {
    return this.armed
  }
  /**
   * The Buy and Sell panel says which it is. Armed, the theme's own buy and
   * sell colours: the click is the order. Off, both are pulled towards the
   * background so they read as a control that opens something rather than one
   * that fires. A colour swap on the primitive, not a rebuild: the panel keeps
   * its prices and its place.
   */
  private applyTradeColors(): void {
    if (!this.tradeBtns) return
    if (this.armed || !this.chartTheme) {
      this.tradeBtns.setColors(undefined, undefined)
      return
    }
    const muted = mutedTradeColors(this.chartTheme)
    this.tradeBtns.setColors(muted.buy, muted.sell)
  }
  private reloadCurrent() {
    if (!this.sym) return
    this.loadSymbol({ symbol: this.sym.symbol, exchange: this.sym.exchange, name: this.sym.name })
  }

  /** Rebuild the canvas with the current app theme (called on theme toggle). */
  applyTheme() {
    if (this.chart && this.rawBars.length) this.buildChart()
  }

  /**
   * The zoom the chart opens at: a FIXED number of recent bars, so the visible
   * price range, and the cursor to price mapping, are the same on every screen
   * width.
   *
   * The trailing pad is what keeps the newest candle off the price axis. It is
   * measured in bars, which is the reason it has to be applied together with the
   * bar count and not on its own: four bars is a comfortable margin at this
   * zoom and three pixels once a month of five-minute history is squeezed into
   * one screen.
   */
  private applyDefaultViewport(): void {
    if (!this.chart) return
    if (this.shownCount > VISIBLE_BARS) {
      const to = this.shownCount - 1 + RIGHT_PAD_BARS
      this.chart.timeScale.setVisibleLogicalRange({ from: to - VISIBLE_BARS, to })
    } else if (this.chart.timeScale.barSpacing > 14) {
      this.chart.timeScale.setBarSpacing(14)
    }
  }

  /**
   * Reset returns to the view the chart opened at, not to the whole of history.
   *
   * `chart.resetScale()` alone re-enables price autoscale and then fits every
   * loaded bar, which on a month of five-minute history is roughly 1900 candles
   * across 1400 px: sub-pixel bars, and a trailing gap of three pixels because
   * that gap is counted in bars too. A reference terminal returns to a readable
   * window instead, which is also what this chart did when it loaded.
   */
  resetScale() {
    if (!this.chart) return
    this.chart.resetScale()
    this.applyDefaultViewport()
  }

  /* ── PNG export ───────────────────────────────────────────────────────── */

  /**
   * Attach a primitive that must never appear in an exported image.
   *
   * Anything an image cannot be used for — a button, a drag handle — belongs
   * here rather than on `addPrimitive` directly. See `screenshotExcluded`.
   */
  private addExcludedPrimitive(primitive: IPrimitive, paneIndex = 0) {
    this.chart?.addPrimitive(primitive, paneIndex)
    this.screenshotExcluded.push({ primitive, paneIndex })
  }

  /**
   * Save the chart as a PNG.
   *
   * openalgo-charts' own `downloadScreenshot()` is deliberately not used. It
   * composites the pane canvases and nothing else, which gets both halves of
   * this wrong: the OHLC readout is a DOM overlay this terminal owns, so it is
   * invisible to a canvas composite and vanished from the saved image, while
   * the SELL/qty/BUY panel *is* a canvas primitive, so it was baked in — a
   * static image with order buttons on it. So the export is driven from here:
   * detach the interaction-only overlays, take the composite, paint the readout
   * onto it, restore. Filename convention and canvas theme are unchanged.
   */
  /** `SYMBOL-interval-timestamp.png`, so a folder of these sorts usefully. */
  private screenshotName(): string {
    const stamp = new Date().toISOString().slice(0, 16).replace(/[T:]/g, '-')
    return `${this.sym?.symbol ?? 'chart'}-${this.interval}-${stamp}.png`
  }

  /** Save the chart as a PNG. */
  async screenshot(): Promise<void> {
    const chart = this.chart
    if (!chart || !this.sym) return
    try {
      const canvas = await this.captureCanvas(chart)
      if (!canvas) return
      const a = document.createElement('a')
      a.href = canvas.toDataURL('image/png')
      a.download = this.screenshotName()
      a.click()
      this.toast('Chart saved', 'ok')
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /**
   * The chart as a named PNG file, or null when there is nothing to capture.
   *
   * A `File` rather than a `Blob` because every caller needs the name as well
   * as the bytes, and a File is a Blob, so the clipboard takes it unchanged.
   * The name is the same `SYMBOL-interval-timestamp.png` the saved image uses,
   * which is what makes an attached screenshot say in the conversation which
   * chart it was.
   *
   * This is the one place a PNG is produced. Copying to the clipboard and
   * attaching one to an agent turn both come through here, so a change to what
   * is composited, or to which overlays are taken down first, reaches both.
   */
  async snapshotPng(): Promise<File | null> {
    const chart = this.chart
    if (!chart || !this.sym) return null
    const canvas = await this.captureCanvas(chart)
    if (!canvas) return null
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, 'image/png'))
    if (!blob) return null
    return new File([blob], this.screenshotName(), { type: 'image/png' })
  }

  /**
   * Put the chart on the clipboard as an image, ready to paste.
   *
   * The image clipboard is the only form that pastes into a post composer or a
   * chat, which is what people do with a chart far more often than they file it.
   * It needs a secure context and a user gesture: a click on the menu item is
   * the gesture, and 127.0.0.1 counts as secure alongside https, so a local
   * OpenAlgo qualifies. Anything else is reported rather than failing silently.
   */
  async copyScreenshot(): Promise<void> {
    if (!this.chart || !this.sym) return
    try {
      if (!navigator.clipboard || typeof ClipboardItem === 'undefined') {
        throw new Error('Copying images needs https or localhost')
      }
      const file = await this.snapshotPng()
      if (!file) throw new Error('The chart produced no image')
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': file })])
      this.toast('Chart copied, paste it anywhere', 'ok')
    } catch (e) {
      this.toast(this.cleanError(e), 'err')
    }
  }

  /**
   * Composite the chart into an offscreen canvas with the export excluded
   * overlays taken down, then paint the OHLC readout into the corner the DOM
   * overlay occupies on screen.
   *
   * The detach/re-attach is why this is async: `removePrimitive` only marks the
   * pane dirty, so the buttons are still in the canvas bitmap until the chart
   * repaints on the next frame.
   */
  private async captureCanvas(chart: ChartInstance): Promise<HTMLCanvasElement | null> {
    const hidden = [...this.screenshotExcluded]
    for (const o of hidden) chart.removePrimitive(o.primitive)
    // Selection handles are grab targets; the drawing itself stays. Every
    // selected id is kept, not only the primary: a shift-click selection would
    // otherwise come back as its first member.
    const selected = this.draw?.selection() ?? []
    if (selected.length) this.draw?.select(null)
    try {
      await nextPaint()
      // A theme toggle or an interval change during that frame rebuilds the
      // chart, and the one captured here would no longer be on screen.
      if (this.destroyed || this.chart !== chart) return null
      const shot = chart.takeScreenshot()
      this.paintLegend(shot)
      return shot
    } finally {
      if (!this.destroyed && this.chart === chart) {
        for (const o of hidden) chart.addPrimitive(o.primitive, o.paneIndex)
        if (selected.length) this.draw?.select(selected)
      }
    }
  }

  /**
   * Paint the OHLC readout onto a captured canvas, where the DOM overlay sits
   * on screen and in the colours it is showing.
   *
   * The capture is device-pixel sized, and the ratio is derived from the canvas
   * against the container rather than read from `devicePixelRatio` — that is
   * the ratio the chart actually rendered at, which is what has to be matched
   * for the text to land in the right place on a fractional-scaling display.
   *
   * The foreground goes through `resolveCssColor` because the app's theme
   * tokens are oklch, which a canvas is not guaranteed to parse: assigning one
   * to `fillStyle` is silently ignored and the text would paint in whatever
   * colour was set last (black, on a dark chart).
   */
  private paintLegend(canvas: HTMLCanvasElement) {
    const ctx = canvas.getContext('2d')
    if (!ctx || !this.sym) return
    const cssWidth = this.container.clientWidth || canvas.width
    const ratio = canvas.width / cssWidth
    const css = getComputedStyle(this.legendEl)
    const family = css.fontFamily || 'system-ui, sans-serif'
    const foreground = css.color ? resolveCssColor(css.color) : '#e4e8f4'
    ctx.save()
    ctx.scale(ratio, ratio)
    ctx.textBaseline = 'top'
    ctx.font = `500 12px ${family}`
    let x = LEGEND_X
    for (const run of this.legendModel(this.legendBar)) {
      const tone = legendToneStyle(run.tone, foreground)
      ctx.fillStyle = tone.color
      ctx.globalAlpha = tone.alpha
      ctx.fillText(run.text, x, LEGEND_Y)
      x += ctx.measureText(run.text).width + LEGEND_GAP
    }
    const sub = lotInfoText(this.sym, this.qty)
    if (sub) {
      ctx.font = `10px ${family}`
      ctx.fillStyle = foreground
      ctx.globalAlpha = 0.65
      ctx.fillText(sub, LEGEND_X, LEGEND_SUB_Y)
    }
    ctx.restore()
  }

  /* ── right-click order menu ───────────────────────────────────────────── */
  private ctxPrice = 0

  private showContextMenu(event: ContextMenuEvent): void {
    const chart = this.chart
    if (!chart || this.destroyed) return
    event.preventDefault()
    const { target } = event
    let alert: TerminalContextMenu['alert']
    if (target.kind === 'drawing' && target.id?.startsWith('draw:')) {
      const drawingId = target.id.slice(5).split('#')[0]
      if (this.draw?.get(drawingId)) {
        const info = this.draw.alertInfo(drawingId)
        alert = {
          label: 'Create drawing alert',
          source: { kind: 'drawing', drawingId },
          disabled: !info.available,
          reason: info.reason,
        }
      }
    } else if (target.kind === 'indicator' && target.instanceId) {
      const instance = chart.indicators().find((study) => study.id === target.instanceId)
      const plot =
        instance &&
        getIndicator(instance.indicatorId).plots.find(
          (candidate) =>
            (candidate.overlay ? 0 : instance.paneIndex) === event.paneIndex &&
            (target.plotKey === undefined || candidate.key === target.plotKey)
        )
      if (instance && plot) {
        const value = instance.values()[plot.key]?.[event.index ?? chart.primaryBars().length - 1]
        alert = {
          label: 'Create study alert',
          source: {
            kind: 'indicator',
            instanceId: instance.id,
            plotKey: plot.key,
            value: value ?? NaN,
          },
        }
      }
    } else if (event.paneIndex === 0 && event.price !== null && Number.isFinite(event.price)) {
      // Snapped to the instrument's tick, not the raw price under the pointer.
      // A pixel maps to a price with fifteen decimals behind it, so the menu
      // offered "Create price alert at 1,293.63" and the dialog it opened put
      // 1293.6305656934308 in the box: the label and the field disagreed, and
      // the alert was armed at a price the instrument cannot trade at.
      const price = this.snap(event.price)
      alert = {
        label: `Create price alert at ${this.fmt(price)}`,
        source: { kind: 'price', price },
      }
    }
    const box = this.container.getBoundingClientRect()
    this.cb.onContextMenu?.({
      x: box.left + event.point.x,
      y: box.top + event.point.y,
      items:
        event.paneIndex === 0 && event.price !== null
          ? (this.contextMenuAt(event.point.y)?.items ?? [])
          : [],
      profile: this.profileContextMenuAt(event.point.x, event.point.y),
      alert,
    })
  }
  /** Per-session profile actions are available for quote-only instruments too. */
  profileContextMenuAt(localX: number, localY: number) {
    const chart = this.chart
    if (!chart || !this.profileLayer) return null
    const maximized = chart.maximizedPane()
    if (maximized !== null && maximized !== 0) return null
    // Native primitives receive plot coordinates; a left price axis adds an
    // origin offset to the container coordinates used by the React menu.
    const time = chart.dataLayer.indexToTime(0)
    if (time === undefined) return null
    const plotLeft = chart.timeToCoordinate(time) - chart.timeScale.indexToX(0)
    return this.profileLayer.contextMenuAt(localX - plotLeft, localY)
  }

  /** Build the context-menu items for a right-click at container-local y. */
  contextMenuAt(localY: number): { price: number; items: CtxItem[] } | null {
    if (!this.chart || !this.sym || this.sym.quoteOnly) return null
    const p = this.chart.coordinateToPrice(localY, 0)
    if (p == null) return null
    this.ctxPrice = this.snap(p)
    const m = this.marketPrice()
    const lotTxt = this.sym.lots ? `${Math.max(1, Math.floor(this.qty || 1))}L` : this.orderQty()
    const defs: [OrderSide, OrderType][] = [
      ['BUY', 'MARKET'],
      ['BUY', 'LIMIT'],
      ['BUY', 'SL'],
      ['SELL', 'MARKET'],
      ['SELL', 'LIMIT'],
      ['SELL', 'SL'],
    ]
    const items = defs.map(([side, type]) => {
      const v = side === 'BUY' ? 'Buy' : 'Sell'
      const label =
        type === 'MARKET'
          ? `${v} ${lotTxt} Market`
          : type === 'LIMIT'
            ? `${v} ${lotTxt} Limit @ ${this.fmt(this.ctxPrice)}`
            : `${v} ${lotTxt} Stop @ ${this.fmt(this.ctxPrice)}`
      let enabled = true
      if (m != null) {
        if (type === 'SL') enabled = side === 'BUY' ? this.ctxPrice > m : this.ctxPrice < m
        else if (type === 'LIMIT') enabled = side === 'BUY' ? this.ctxPrice < m : this.ctxPrice > m
      }
      return { side, type, label, enabled }
    })
    return { price: this.ctxPrice, items }
  }
  placeCtx(side: OrderSide, type: OrderType) {
    void this.placeFromMenu(side, type)
  }

  /* ── bootstrap + teardown ─────────────────────────────────────────────── */
  private assertWorkspacePreparation(chart?: ChartInstance): void {
    if (this.destroyed || !this.preparingWorkspace)
      throw new Error('Workspace preparation was cancelled')
    if (chart && this.chart !== chart) throw new Error('Workspace chart changed during preparation')
  }

  private async restoreInitialWorkspace(pane: WorkspacePane): Promise<void> {
    const chart = this.chart
    if (!chart) throw new Error('Workspace chart is unavailable')
    this.assertWorkspacePreparation(chart)
    const context = chart.getDataContext()
    if (
      context?.symbol !== pane.symbol ||
      context.exchange !== pane.exchange ||
      context.interval !== pane.interval
    )
      throw new Error('Workspace chart context changed during preparation')
    await this.restoreChartSettings(true)
    this.assertWorkspacePreparation(chart)
    this.applyingIndicators = true
    try {
      const report = chart.restoreState(pane.chart)
      if (!report.applied || report.indicators !== (pane.chart.indicators?.length ?? 0))
        throw new Error('Workspace studies and settings could not be restored completely')
      // Host series own their data; the engine returns only style descriptors.
      const primary = report.series.find(
        (series) =>
          series.paneIndex === 0 &&
          series.priceScaleId === 'right' &&
          series.type === CHART_TYPES[pane.chartType].series
      )
      if (primary) this.price?.applyOptions(primary.style)
      const volume = report.series.find(
        (series) =>
          series.paneIndex === 0 && series.priceScaleId === '' && series.type === 'histogram'
      )
      if (volume) this.volume?.applyOptions(volume.style)
      const average = report.series.find(
        (series) => series.paneIndex === 0 && series.priceScaleId === '' && series.type === 'line'
      )
      if (average) this.volumeMA?.applyOptions(average.style)
      // The host volume switch stays authoritative across future chart rebuilds.
      this.setVolumeVisible(pane.volume)
    } finally {
      this.applyingIndicators = false
    }
    this.syncIndicators()
    const document = pane.chart.drawings ?? emptyDrawings()
    if (!isDrawingsDocument(document)) throw new Error('Unsupported workspace drawing document')
    if (document.drawings.length) {
      const { migrateDrawings, getDrawingTool } = await import('openalgo-charts/draw')
      this.assertWorkspacePreparation(chart)
      const migrated = migrateDrawings(document)
      const ids = new Set(document.drawings.map((drawing) => drawing.id))
      if (
        migrated.drawings.length !== document.drawings.length ||
        ids.size !== document.drawings.length ||
        migrated.drawings.some(
          (drawing, index) =>
            drawing.id !== document.drawings[index].id ||
            !getDrawingTool(drawing.tool) ||
            drawing.paneIndex >= chart.panes().length
        )
      )
        throw new Error('Workspace drawings could not be restored completely')
      this.drawJson = migrated
      this.drawEnabled = true
      await this.attachDrawing()
      this.assertWorkspacePreparation(chart)
      if (this.draw?.toJSON().drawings.length !== migrated.drawings.length)
        throw new Error('Workspace drawings could not be restored completely')
    }
    this.attachAlerts(chart)
    this.installComparisons()
    await this.comparisonLoad
    this.assertWorkspacePreparation(chart)
  }

  async init(): Promise<void> {
    try {
      await this.initialize()
    } catch (error) {
      if (this.initialWorkspacePane) this.destroy()
      throw error
    }
  }

  private async initialize(): Promise<void> {
    if (this.destroyed) {
      if (this.initialWorkspacePane) throw new Error('Workspace preparation was cancelled')
      return
    }
    this.rest = new OpenAlgoDataFeed({
      baseUrl: '',
      apiKey: this.apiKey,
      hasOpenInterest: (request) => {
        const sym = this.sym
        return sym?.symbol === request.symbol && sym.exchange === request.exchange
          ? (sym.hasOpenInterest ?? openInterestCapability(sym.exchange))
          : openInterestCapability(request.exchange ?? '')
      },
    })
    this.cachedBars = withBarCache(this.rest, { ttlMs: 10 * 60_000 })
    this.exprFeed = new ExpressionFeed(this.cachedBars, () => this.exprLegExchange)
    // Repair follows the stream: one small refresh a moment after each bar
    // closes, an immediate one when the stream skips a bucket, and each asks
    // history for the last few bars only. The 30-second poll stays, now as a
    // tail request rather than the whole window, because a tradeable's only
    // subscription is Depth, which carries no traded quantity: history is the
    // sole source of the forming bar's volume, and a volume pane frozen for a
    // whole bar reads as a dead feed.
    this.data = new DataLoadingController(this.exprFeed, {
      now: nowSec,
      pollIntervalMs: 30_000,
      refreshOnBarClose: true,
      refreshOnGap: true,
      refreshWindowBars: 5,
      pageSize: 500,
      maxEmptyPages: 4,
      maxBars: 100_000,
    })
    this.offData = this.data.subscribe((snapshot) => this.applyDataSnapshot(snapshot))
    document.addEventListener('visibilitychange', this.onVisibilityChange)
    this.onVisibilityChange()
    this.trade = new OpenAlgoTradeFeed({ baseUrl: '', apiKey: this.apiKey, strategy: STRATEGY })

    // broker-supported intervals → the timeframe dropdown
    let groups: IntervalGroup[]
    try {
      const j = await this.api<{ data?: IntervalData }>('intervals')
      groups = intervalGroups(j.data || {})
    } catch (error) {
      if (this.initialWorkspacePane) throw error
      groups = intervalGroups({ minutes: ['1m', '5m', '15m'], hours: ['1h'], days: ['D'] })
    }
    // The pane may have closed while intervals loaded. Do not reopen its resources.
    if (this.destroyed) {
      if (this.initialWorkspacePane) throw new Error('Workspace preparation was cancelled')
      return
    }
    this.availableIntervals = groups.flatMap((group) => group.items)
    if (this.initialWorkspacePane) {
      const pane = this.initialWorkspacePane
      // Only what this pane holds: the validation below reads the registry for
      // the pane's own studies, and the rest of the catalogue follows once the
      // chart is up.
      await this.loadIndicatorsFor((pane.chart.indicators ?? []).map((study) => study.indicatorId))
      this.assertWorkspacePreparation()
      validateWorkspacePaneSupport(pane, {
        chartTypes: new Set(Object.keys(CHART_TYPES)),
        intervals: new Set(this.availableIntervals),
        indicators: new Set(registeredIndicators().map((study) => study.id)),
      })
      if (
        isProfileKind(this.ctype) &&
        !profileIntervalSupported(this.ctype, pane.interval, this.profileBlockMinutes())
      )
        throw new Error(`Unsupported workspace profile interval: ${pane.interval}`)
      this.interval = pane.interval
    } else {
      this.interval = pickInterval(groups, this.lsGet('interval'))
    }
    if (!this.initialWorkspacePane && isProfileKind(this.ctype)) {
      const interval = this.compatibleProfileInterval(this.ctype)
      if (interval) this.interval = interval
      else this.ctype = 'candlestick'
    }
    this.cb.onReady({ intervalGroups: groups, interval: this.interval, chartType: this.ctype })

    // one WebSocket for ticks + the account-level order stream.
    this.ws = new OpenAlgoWsFeed({ url: this.wsUrl, apiKey: this.apiKey })
    this.offWsState = this.ws.onState((s) => {
      if (this.destroyed) return
      this.cb.onWsState(s)
      if (s === 'closed' || s === 'error' || s === 'reconnecting') this.startLtpFallback()
      // Back on the wire after a break: whatever closed between the drop and
      // now was never built from ticks, so reconcile at once instead of waiting
      // for the next poll staring at the hole. The builder is reseeded from its
      // own bar first, which marks the bucket it opens next as provisional: the
      // first tick after a gap is not that bucket's open.
      if (s === 'open') {
        const current = this.builder?.current()
        if (current) this.builder?.seed(current)
        this.reconcileNow()
      }
    })
    this.offWsControl = this.ws.onControl((m) => {
      if (m.type === 'auth' && m.status !== 'success') this.cb.onWsState('auth failed')
    })
    this.offOrderUpdate = this.ws.onOrderUpdate((e) => {
      if (!this.sym || e.symbol !== this.sym.symbol || !this.chart) return
      const working =
        e.status === 'open' || e.status === 'trigger pending' || e.status === 'pending'
      const rec = this.orderLines.get(e.orderId)
      const o: LineOrder = {
        id: e.orderId,
        side: e.action,
        type: e.pricetype as OrderType,
        qty: e.quantity,
        price: e.price,
        triggerPrice: e.triggerPrice,
        status: working ? 'working' : e.status,
      }
      if (working) {
        if (rec) {
          rec.order = o
          rec.line.setPrice(e.triggerPrice ?? e.price)
        } else this.orderLines.set(e.orderId, { line: this.makeOrderLine(o), order: o })
      } else if (rec) {
        this.chart.removePrimitive(rec.line)
        this.orderLines.delete(e.orderId)
      }
      if (e.status === 'rejected')
        this.toast(`rejected: ${e.rejectionReason || 'see order book'}`, 'err')
      if (e.status === 'complete')
        this.toast(
          `filled: ${e.action} ${e.quantity} @ ${this.fmt(e.averagePrice || e.price)}`,
          'ok'
        )
      if (!working) this.pollBook() // fills/cancels move the position book too
    })
    this.ws.connect()
    this.ws.subscribeOrders()

    if (this.bookTimer) clearInterval(this.bookTimer)
    this.bookTimer = setInterval(() => this.pollBook(), 8000)

    if (this.initialWorkspacePane) {
      const pane = this.initialWorkspacePane
      const rows = isChartExpression(pane.symbol)
        ? [{ symbol: pane.symbol, exchange: pane.exchange, expression: true }]
        : await this.search(pane.symbol, pane.exchange)
      this.assertWorkspacePreparation()
      const row = rows.find(
        (value) => value.symbol === pane.symbol && value.exchange === pane.exchange
      )
      if (!row) throw new Error(`Workspace symbol is unavailable: ${pane.exchange}:${pane.symbol}`)
      const loaded = await this.loadSymbol(row, { silent: true, strict: true })
      this.assertWorkspacePreparation()
      if (!loaded)
        throw new Error(
          `Workspace history is unavailable: ${pane.exchange}:${pane.symbol} ${pane.interval}`
        )
      await this.restoreInitialWorkspace(pane)
      this.assertWorkspacePreparation()
      this.initialWorkspacePane = null
      this.preparingWorkspace = false
      this.syncAlertPause()
      return
    }

    // restore the last symbol; fall back to BHEL/NSE if it's gone or has no data.
    let loaded = false
    try {
      const saved = JSON.parse(this.lsGet('symbol') || 'null') as {
        symbol?: string
        exchange?: string
      } | null
      if (saved?.symbol) {
        const rows = await this.search(saved.symbol, saved.exchange)
        const row = rows.find((r) => r.symbol === saved.symbol && r.exchange === saved.exchange)
        if (row) loaded = await this.loadSymbol(row, { silent: true })
      }
    } catch {
      /* fall through to the default */
    }
    if (!loaded && !this.destroyed) {
      try {
        const rows = await this.search('BHEL', 'NSE')
        const bhel = rows.find((r) => r.symbol === 'BHEL' && r.exchange === 'NSE')
        if (bhel) await this.loadSymbol(bhel)
      } catch {
        /* leave the chart empty; the user can search */
      }
    }
  }

  destroy() {
    if (this.destroyed) return
    this.replayInvalidation?.()
    this.replayInvalidation = null
    if (this.workspaceReplayMember || this.workspaceReplayPick) this.stopReplay()
    this.destroyed = true
    let comparisonError: unknown
    let comparisonFailed = false
    try {
      this.comparisons?.destroy()
    } catch (error) {
      comparisonFailed = true
      comparisonError = error
    }
    this.comparisons = null
    this.offDeleteKey?.()
    this.offDeleteKey = null
    this.offBranding?.()
    this.offBranding = null
    this.cb.onBrandingChange?.(null)
    document.removeEventListener('visibilitychange', this.onVisibilityChange)
    this.offData?.()
    this.offData = null
    this.data?.destroy()
    this.data = null
    this.detachAlerts()
    this.detachObjects()
    this.detachDrawing()
    if (this.bookTimer) clearInterval(this.bookTimer)
    this.bookTimer = null
    this.stopLtpFallback()
    this.offLtp?.()
    this.offLtp = null
    this.offDepth?.()
    this.offDepth = null
    this.offWsState?.()
    this.offWsState = null
    this.offWsControl?.()
    this.offWsControl = null
    this.offOrderUpdate?.()
    this.offOrderUpdate = null
    this.offReplayPointer?.()
    this.offReplayPointer = null
    this.offLegendActions?.()
    this.offLegendActions = null
    try {
      this.ws?.close()
    } catch {
      /* already closed */
    }
    try {
      this.stopReplay() // release the controller before its chart disappears
    } catch {
      /* nothing to leave */
    }
    this.profileLayer?.dispose()
    this.profileLayer = null
    try {
      this.chart?.destroy()
    } catch {
      /* already gone */
    }
    this.chart = null
    this.ws = null
    this.screenshotExcluded.length = 0
    if (comparisonFailed) throw comparisonError
  }
}
