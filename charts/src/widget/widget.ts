/**
 * The widget shell: a chart with its chrome, built in one call.
 *
 * `createWidget(container, options)` puts a `.oac-widget` root into the
 * container with a top bar, a stage (the tool rail beside the chart) and a
 * status line, creates the chart and the drawing controller inside it, wires
 * the keymap, the overlay stack and the toasts, and hands every mounted piece
 * one `WidgetContext`. A host that wants the chart alone still has the engine;
 * this is for the host that wants the terminal.
 *
 * Three decisions worth recording:
 *
 * - **The shell owns the theme, the symbol and the interval; the chart owns
 *   everything else.** The engine has no instrument concept, so symbol and
 *   interval live here, drive the feed from here, and are published on the bus
 *   as `symbol` and `interval` for a host (or a link group) to follow.
 * - **Persisted state is validated field by field and applied to the dataset
 *   it was captured on.** A viewport is a range of bar indices and means
 *   nothing on different bars, so a saved layout landing on another symbol
 *   keeps its indicators and panes and drops its view. Its drawings belong
 *   to the symbol it was saved on (`drawingScope`): each instrument keeps its
 *   own, and a layout from before that attaches its drawings to its symbol.
 * - **Every chord goes through one keymap in the capture phase.** The rail,
 *   the editing keys and the tool chords register there with a scope, so a
 *   dialog being open or the focus being in the rail is decided once, not in
 *   every listener.
 */
import {
  AlertController, ChartObjects, DataLoadingController, ShortcutManager, createChart, darkTheme, lightTheme, registeredIntervals, registeredChartTypes, tryResolveInterval, resolveInterval, isKnownInterval,
  dataVariantKey, normalizeDataVariant, publishDataContext, getSeriesTransform, registeredSeriesTransforms, VERSION,
  type Chart, type ChartOptions, type ChartTheme, type DataFeed, type Bar, type SeriesApi, type SeriesType, type DataVariant, type SeriesTransformSpec,
  type RestoreReport, type ChartSettingsValues, type BarsRequest, type DataLoadingOptions, type DataLoadingSnapshot, type AlertTriggeredPayload, type TradingCapabilityRequest, type TradingCapabilitySource,
} from 'openalgo-charts';
import { DrawingController, type DrawingDocumentStore, type InstrumentDrawings } from 'openalgo-charts/draw';
import {
  WidgetStorage, createOverlayStack, createTipController, h, widgetDialog,
  type AsyncStorageLike, type OverlayOptions, type OverlayStack, type TipController, type StorageLike, type WidgetBus, type WidgetBusEvents, type WidgetContext, type WidgetDialogName,
} from './context';
import { defaultWidgetStore } from './storage';
import { ChartHistory } from './history';
import { Keymap } from './keymap';
import { mountRail, toolName, type RailHandle, type RailOptions, type RailPrefs } from './rail';
import { mountStatusline, type StatuslineHandle } from './statusline';
import { isChartTypeChoice } from './chart-type-choice';
import { mountTopbar, type MenuRow, type SymbolSearch, type TopbarHandle } from './topbar';
import { feedSymbolSearch } from './symbol-picker';
import { mountToasts, type ToastHandle, type ToastKind, type Toaster } from './toast';
import { applyTokens, themeMode, widgetTokens, type WidgetThemeName } from './tokens';
import { injectWidgetStyles } from './styles';
import { mountDataStatus, type DataStatusHandle } from './data-status';
import { attachContextMenu, mountIndicatorSettings, mountDrawingProperties, mountAlertsPanel, type OrderRequest, type PanelHandle } from './dialogs/index';
import { mountObjectsPanel, createObjectsPanelContent } from './objects-panel';
import { mountMobile, type MobileHandle, type MobileMode } from './mobile';
import { mountDrawingToolbar, type DrawingToolbarHandle } from './drawing-toolbar';
import { createDrawingTemplates, type DrawingTemplates } from './drawing-templates';
import type { DrawingTemplateStore } from 'openalgo-charts/workspace';
import { errorText, widgetText, type WidgetTranslator } from './localization';
import { EventDetailsPopup, eventDetailsLabels, type EventDetailsPopupOptions } from './event-details';
import type { ChartEventClick } from 'openalgo-charts';
import { mountDataWindow } from './data-window';
import { mountPanelDock, type PanelDockHandle, type PanelDockState } from './panel-dock';
import { mountQuickEntry, type QuickEntryHandle } from './quick-entry';
import { WIDGET_COMPONENT_CSS } from './component-styles';
import { DateNavigator, timeBuckets, type DateNavigationResult, type DateNavigationTarget, type HistoryReach } from './date-navigator';
import { openDateNavigation } from './date-navigation-dialog';
import { mountWatchlistPanel, type WatchlistPanelOptions } from './watchlist-panel';
import { mountNewsPanel, type NewsPanelOptions } from './news-panel';
import { mountAccountSummary } from './account-summary';
import type { AccountStateSource } from 'openalgo-charts/trade';
import { dataVariantLabel } from './data-status';
import { installKeys, keyScopes, trackPointer, type KeysHost } from './widget-keys';
import {
  ShellBus, applySavedLayout, flushOnPageHide, readSaved, reportStorage, restoreWhenLoaded, restoreWidgetState, saveNow, scheduleSave,
  scopeDrawings, stripView as stripSavedView, type PersistHost,
} from './widget-persist';
// The bar, the ranges, the session calendar and the shading live in bottombar-shell.ts.
import { attachBottombar, BOTTOMBAR_OPTION_KEYS, type BottombarHost, type ShellBottombar, type WidgetBottombarOptions } from './bottombar-shell';
// Layouts: the store, the menu and the templates live in layouts-widget.ts.
import type { WorkspaceStore } from 'openalgo-charts/workspace';
import type { LayoutsController } from './layouts';
import { attachWidgetLayouts, type WidgetLayouts } from './layouts-widget';

/** The intervals offered when the host names none: the registry's codes are appended. */
export const DEFAULT_INTERVALS: readonly string[] = ['1m', '5m', '15m', '1h', '1d', '1w'];
/** Bars asked of the feed per load when the host names no lookback. */
export const DEFAULT_LOOKBACK_BARS = 500;
/** Debounce on writing the persisted layout, because drags fire per frame. */
export const SAVE_DEBOUNCE_MS = 250;
/** The storage entry the layout lives under. */
export const STATE_KEY = 'state';
/**
 * Where each instrument's drawings live beside the layout: this prefix, then
 * the instrument's key (`instrumentDrawingsKey`), as in `drawings:NSE:INFY`.
 */
export const DRAWINGS_KEY_PREFIX = 'drawings:';
export const WIDGET_STATE_VERSION = 1;

/**
 * The options of a chart under a grid's own
 * bottom bar, which carries Go to and the market status for every chart. Such
 * a chart shows neither in its own bars, and opens its go-to panel in the
 * context this gives, over the whole grid. Internal: the tier does not export it.
 */
export const GRID_BAR_CHARTS = new WeakMap<WidgetOptions, (ctx: WidgetContext) => WidgetContext>();

/** Named lists and their quotes for the docked watchlist. A chosen row charts that instrument. */
export type WidgetWatchlistOptions = Omit<WatchlistPanelOptions, 'onSelect' | 'normalize'>;
/** The news source for the docked reader, which follows the chart's instrument. */
export type WidgetNewsOptions = NewsPanelOptions;

export interface WidgetOptions extends Omit<ChartOptions, 'theme'>, WidgetBottombarOptions {
  /** Docked Data and Objects panels. False retains the original Objects dialog. Default true. */
  panels?: boolean;
  /** Unclaimed letters and digits open symbol and interval entry on the focused chart. Default true. */
  typingNavigation?: boolean;
  /**
   * The `?` panel lets the user change the widget's and the chart's chords,
   * kept in `storage` when `persist` is on. False lists them only and applies
   * no saved chords. Default true.
   */
  shortcutsEditor?: boolean;
  /**
   * A docked watchlist: named lists from a store (a `WatchlistRepository` from
   * `openalgo-charts/workspace`), with prices only from `quotes`. Needs `panels`.
   */
  watchlist?: WidgetWatchlistOptions;
  /** A docked reader for the chart instrument's news. Needs `panels`. */
  news?: WidgetNewsOptions;
  /** Event marker clicks open details. Set false to provide a host-owned view. */
  eventDetails?: false | EventDetailsPopupOptions;
  /** Where bars come from. Without one the chart shows what the host sets on `widget.series` itself. */
  feed?: DataFeed | undefined;
  /** Shared history, paging and recovery options. `now` here uses UTC seconds. */
  loading?: DataLoadingOptions;
  symbol?: string | undefined;
  /** Exchange passed to the feed with the symbol. Default `''`. */
  exchange?: string | undefined;
  /** Interval code the registry knows (a built-in token or one passed to `registerInterval`). Default `1d`. */
  interval?: string | undefined;
  /**
   * Which of the feed's series to show: a session, an adjustment, a currency
   * or a unit. Default: the feed's own default series. The feed must declare
   * it through `dataVariants`, or the chart reports it unsupported.
   */
  variant?: DataVariant | undefined;
  /** The interval pills, each a known code. Default: `DEFAULT_INTERVALS` plus every registered code. */
  intervals?: readonly string[];
  /**
   * Primary chart type. Default `candlestick`. A registered renderer, or a
   * transform the chart applies (`registeredSeriesTransforms`, once the
   * transform tier is imported).
   */
  chartType?: string | undefined;
  /** `dark` (default), `light`, or a full `ChartTheme`; the chrome derives its palette from it. */
  theme?: WidgetThemeName | ChartTheme;
  /** The drawing rail. `false` hides it; an object restricts its tools or seeds its pins. Default on. */
  rail?: boolean | RailOptions;
  topbar?: boolean;
  statusline?: boolean;
  /** Narrow controls. Auto activates when the container is at most 640 CSS px wide, or, with a coarse primary pointer, at most 960 px wide and under 600 px tall (a phone on its side); a tablet or a touch laptop keeps the desktop chrome. Default auto. */
  mobile?: MobileMode;
  /**
   * Keep the layout, the rail preferences, the symbol, the interval and the
   * theme between visits. `true` uses one shared namespace; a string names one,
   * so two widgets on a page keep separate layouts. Default off.
   */
  persist?: boolean | string;
  /**
   * The store behind `persist`. Default: IndexedDB where the page has it
   * (since 2.5.10), else the page's `localStorage`. Over an asynchronous
   * store (one with `entries`, such as `createIndexedDbWidgetStorage`) the
   * saved layout lands when `ready` settles; a synchronous one, such as
   * `localStorage` passed here, applies it before `createWidget` returns.
   */
  storage?: StorageLike | AsyncStorageLike | null;
  /**
   * Whose drawings the chart shows. `'instrument'` (default): each symbol and
   * exchange keeps its own, saved when the chart moves to another instrument
   * and brought back when it returns, which is what a trader drawing levels
   * expects. `'chart'`: one drawing set that stays on screen whatever
   * instrument is loaded, as earlier releases did, for a host that wants
   * drawings to follow the chart.
   */
  drawingScope?: 'instrument' | 'chart';
  /**
   * Where the drawings of each instrument are kept in `'instrument'` scope.
   * Default: beside the layout in `storage` when `persist` is on
   * (`DRAWINGS_KEY_PREFIX`), else in memory for the life of the widget.
   */
  drawingStore?: DrawingDocumentStore;
  /** Saved drawing looks, a tool's default and named templates: a `DrawingTemplateRepository` from `openalgo-charts/workspace`. */
  drawingTemplates?: DrawingTemplateStore;
  /**
   * Saved layouts and indicator templates: a `WorkspaceRepository` from
   * `openalgo-charts/workspace`, or a host's own `WorkspaceStore`. It adds the
   * Layouts menu (top bar, and the More sheet on a phone) and templates in the
   * indicator picker, and reopens the layout that was active when the page
   * last closed. Taken as a type only: the workspace tier loads with the store.
   */
  workspaces?: WorkspaceStore;
  /** What the Layouts menu drives: default a controller over this widget; false for no menu. A chart grid decides what its charts get (`ChartGridOptions.layouts`). */
  layouts?: LayoutsController | false;
  /** The floating toolbar over the selected drawings on a desktop layout. Default: shown with the rail. */
  drawingToolbar?: boolean;
  /**
   * More rows at the end of the capture menu, read each time it opens; a
   * string starts a group. The chart grid adds its whole-grid capture here.
   */
  captureRows?: () => ReadonlyArray<MenuRow | string>;
  /** BCP 47 tag for the numbers on the status line. Default: the runtime's. */
  locale?: string;
  /** Host translations for widget chrome and dialogs, with English fallback. */
  translate?: WidgetTranslator;
  /** Show the Indicators button. Default true. */
  indicators?: boolean;
  /** Symbol lookup for the top bar's box, called as the user types. Default: the feed's `searchSymbols`, when it has one. */
  symbolSearch?: SymbolSearch;
  /** How many bars a load asks the feed for. Default `DEFAULT_LOOKBACK_BARS`. */
  lookbackBars?: number;
  /**
   * The widget's wall clock, in epoch milliseconds: the history load window,
   * the loading controller's clock (unless `loading.now` gives it one, in UTC
   * seconds), the status line and the bottom bar's clock and ranges. Default
   * `Date.now`. It shadows `ChartOptions.now`, the chart's animation clock
   * (monotonic, `performance.now` by default), which the widget does not pass
   * to its chart: its kinetic animation runs on the real clock.
   */
  now?: () => number;
  /** Order entry from the right-click menu. Without it the menu draws no trade rows. */
  onOrder?: (order: OrderRequest) => void;
  /** Supported host order routes, optionally resolved again for each request. */
  tradingCapabilities?: TradingCapabilitySource;
  /** The requested execution mode when the host capabilities constrain it. */
  tradingMode?: TradingCapabilityRequest['mode'];
  /** Locks order entry during host replay selection or workspace transitions. */
  tradingLocked?: () => boolean;
  /**
   * Account state for the status line, usually a trade-tier `AccountManager`.
   * Omitted shows no account; a source whose provider declares no accounts is
   * shown disabled with the reason. It only reads and switches accounts.
   */
  account?: AccountStateSource;
  /** Host CSP nonce for the widget and dialog stylesheet, assigned before insertion. */
  styleNonce?: string;
  /**
   * Which widget answers the keyboard when a host shows several. True sends
   * chords here as if the chart had focus, false silences this widget and its
   * chart's shortcuts, and undefined leaves the pointer and the focus to
   * decide, as they do for a lone widget. The chart grid supplies it per cell.
   */
  keyboardRoute?: () => boolean | undefined;
}

export type WidgetChartState = ReturnType<Chart['getState']>;

/** What `getState` returns and `restoreState` takes. JSON-safe. */
export interface WidgetState {
  version: typeof WIDGET_STATE_VERSION;
  symbol: string;
  exchange: string;
  interval: string;
  chartType: string;
  theme: WidgetThemeName;
  /** The data variant, absent for the feed's default. Optional in older records. */
  variant?: DataVariant;
  chart: WidgetChartState;
  rail: RailPrefs | null;
  /** Optional in older records. Width is bounded when restored. */
  panels?: PanelDockState | undefined;
  /**
   * The library version that wrote the state (since 2.6.3). Absent in older
   * records, which wrote every navigation option whether chosen or not.
   */
  savedBy?: string;
}

export interface WidgetRestoreReport {
  applied: boolean;
  reason?: string | undefined;
  /** The engine's own report for the chart half, when it was reached. */
  chart?: RestoreReport;
}

export type WidgetEventName = 'symbol' | 'interval' | 'variant' | 'theme' | 'layout' | 'data' | 'status';

export interface Widget {
  /** Managed data owner, or null when the host supplies series data directly. */
  readonly dataController: DataLoadingController | null;
  readonly chart: Chart;
  readonly draw: DrawingController;
  /**
   * What keeps the drawings per instrument, or null in `'chart'` scope. A
   * host reads another instrument's drawings through it (`document`), or
   * writes them now (`save`).
   */
  readonly instrumentDrawings: InstrumentDrawings | null;
  /** The template store's catalog as the widget holds it, or null without a `drawingTemplates` store. */
  readonly drawingTemplates: DrawingTemplates | null;
  /** The controller behind the Layouts menu, or null without one (`workspaces`, `layouts`). */
  readonly layouts: LayoutsController | null;
  readonly alerts: AlertController;
  /**
   * Settles once the persisted layout has been applied and the first load
   * has started (since 2.5.10). At once without `persist` or over a
   * synchronous store; over an asynchronous one (IndexedDB, the default)
   * when it has been read, and until then the widget stays out of sight and
   * shows the defaults. Never rejects: a store that fails is reported on the
   * status line and the widget opens on its defaults. A host that reads or
   * edits the restored layout (`getState`, the indicators, the view) awaits it.
   */
  readonly ready: Promise<void>;
  /** Shared inventory and supported actions for drawings, indicators and registered profiles. */
  readonly objects: ChartObjects;
  /**
   * One undo timeline for the chart: studies, their settings, the chart type,
   * price scales, panes and drawings. Ctrl+Z, Ctrl+Y, the rail and the mobile
   * controls all walk it. A host's own change that should not be a step goes
   * through `history.ignore`; loading a layout with `restoreState` clears it.
   */
  readonly history: ChartHistory;
  /** The `.oac-widget` element. */
  readonly root: HTMLElement;
  /** What every mounted piece was handed; a host mounting its own panel wants the same. */
  readonly context: WidgetContext;
  /** The primary series; its handle stays stable across chart-type changes. */
  readonly series: SeriesApi;
  symbol(): string;
  exchange(): string;
  interval(): string;
  /** The data variant in use, undefined for the feed's default series. */
  variant(): Readonly<DataVariant> | undefined;
  chartType(): string;
  theme(): WidgetThemeName;
  setSymbol(symbol: string, exchange?: string): void;
  setInterval(code: string): void;
  /**
   * Show another of the feed's series for the same instrument. A change is a
   * new source: the load in flight is cancelled, the bars are cleared and the
   * variant is loaded, or reported unsupported when the feed does not declare
   * it. Undefined returns to the default. Throws a TypeError for a malformed one.
   */
  setDataVariant(variant: DataVariant | undefined): void;
  /**
   * Select a chart type while retaining series state: a renderer, or a
   * transform the chart applies to the bars the widget loads (Heikin Ashi,
   * Renko, range bars, line break, point and figure, Kagi). A widget whose host
   * feeds `series` itself keeps point and figure and Kagi as renderers over the
   * elements that host prepares, as before.
   */
  setChartType(id: string): void;
  setTheme(theme: WidgetThemeName | ChartTheme): void;
  /** Open the settings dialog. False when the dialog tier has not registered one. */
  openSettings(): boolean;
  openIndicatorPicker(): boolean;
  /** Open the searchable object inventory. False after destruction. */
  openObjects(): boolean;
  /** Show candle and study readings. False when panels are disabled or after destruction. */
  openDataWindow(): boolean;
  /** Open trader alerts and their lifecycle states. False after destruction. */
  openAlerts(): boolean;
  /** Open the docked watchlist. False without a `watchlist` source, with panels off, or after destruction. */
  openWatchlist(): boolean;
  /** Open the docked news reader. False without a `news` source, with panels off, or after destruction. */
  openNews(): boolean;
  /** Open the Layouts menu. False without a `workspaces` store (or `layouts` controller), or after destruction. */
  openLayouts(): boolean;
  getState(): WidgetState;
  restoreState(state: unknown): WidgetRestoreReport;
  /** Load (or reload) bars from the feed for the current symbol and interval. */
  reload(): Promise<void>;
  /**
   * Show a date, or an explicit UTC range, after loading the older history it
   * needs through the feed. Waits for a load in flight; a newer request, a
   * symbol or interval change, a pan or zoom while history loads, or
   * destruction settles it `cancelled`.
   */
  goTo(target: DateNavigationTarget): Promise<DateNavigationResult>;
  /** Open the go-to panel. False after destruction or on an interval without time buckets. */
  openDateNavigation(): boolean;
  /** Show a preset range (`WidgetOptions.ranges`): its interval, its span in view, and the history that needs. One wider than the plot keeps its latest bars in view (`clipped`). */
  setRange(id: string): Promise<DateNavigationResult>;
  /** The preset range in force, or null: none was set, or the interval has changed since. */
  range(): string | null;
  on<K extends WidgetEventName>(event: K, cb: (payload: WidgetBusEvents[K]) => void): () => void;
  off<K extends WidgetEventName>(event: K, cb?: (payload: WidgetBusEvents[K]) => void): void;
  destroy(): void;
  readonly isDestroyed: boolean;
}

/** The options the shell consumes; the rest of `WidgetOptions` is the chart's. */
const WIDGET_ONLY_KEYS: ReadonlyArray<keyof WidgetOptions> = [
  'feed', 'symbol', 'exchange', 'interval', 'variant', 'intervals', 'chartType', 'theme', 'rail', 'topbar', 'statusline',
  'mobile', 'loading', 'persist', 'storage', 'drawingScope', 'drawingStore', 'locale', 'translate', 'indicators', 'symbolSearch', 'lookbackBars', 'now', 'onOrder', 'styleNonce',
  'tradingCapabilities', 'tradingMode', 'tradingLocked', 'account',
  'eventDetails', 'captureRows',
  'panels', 'typingNavigation', 'keyboardRoute', 'watchlist', 'news', 'drawingTemplates', 'drawingToolbar',
  'shortcutsEditor',
  'workspaces', 'layouts',
  // The bottom bar's options are the widget's, not the chart's.
  ...BOTTOMBAR_OPTION_KEYS,
];

/**
 * The saved chart state without what describes the old view: the viewport
 * and every pinned price range go, the indicators, drawings and pane weights
 * stay. For a layout about to land on a different dataset.
 */
export function stripView(state: WidgetChartState): WidgetChartState { return stripSavedView(state); }

/** Resolve a theme option to the engine palette and the chrome mode. */
export function resolveTheme(t: WidgetThemeName | ChartTheme | undefined): { theme: ChartTheme; name: WidgetThemeName } {
  if (t === 'light') return { theme: lightTheme, name: 'light' };
  if (t === 'dark' || t === undefined) return { theme: darkTheme, name: 'dark' };
  return { theme: t, name: themeMode(t) };
}

/** The window the feed is asked for: `lookback` bars back from now, or five years for a non-time bucketing. */
export function loadWindow(interval: string, lookback: number, nowSec: number): { from: number; to: number } {
  const d = tryResolveInterval(interval);
  const seconds = d !== null && d.bucketing.mode === 'interval' ? d.bucketing.seconds : null;
  const span = seconds === null ? 5 * 365 * 86400 : Math.max(1, Math.round(lookback)) * seconds;
  return { from: nowSec - span, to: nowSec };
}

/** The facts the context reads live from the shell rather than copying. */
interface ThemeSource {
  theme(): WidgetThemeName;
  chartThemeInUse(): ChartTheme;
}

type ContextParts = Omit<WidgetContext, 'theme' | 'chartTheme'>;

/**
 * The context handed to every mounted piece. Theme facts are getters onto the
 * shell, so a dialog that reads `ctx.theme` after a switch sees the new one
 * without anyone re-handing it a context.
 */
class WidgetContextImpl implements WidgetContext {
  public readonly chart: Chart;
  public readonly draw: DrawingController;
  public readonly objects: ChartObjects | undefined;
  public readonly alerts: AlertController | undefined;
  public readonly history: ChartHistory | undefined;
  public drawingTemplates: DrawingTemplates | undefined;
  public readonly root: HTMLElement;
  public readonly document: Document;
  public readonly keymap: Keymap;
  public readonly bus: WidgetBus<WidgetBusEvents>;
  public readonly storage: WidgetStorage;
  public readonly locale: string | undefined;
  public readonly translate?: WidgetTranslator | undefined;
  public readonly symbolSearch?: SymbolSearch | undefined;
  public readonly toast: WidgetContext['toast'];
  public readonly openOverlay: WidgetContext['openOverlay'];
  public readonly status: WidgetContext['status'];
  public readonly tips: WidgetContext['tips'];
  public readonly overlays: WidgetContext['overlays'];
  public readonly symbol: WidgetContext['symbol'];
  public readonly interval: WidgetContext['interval'];
  public readonly intervals: readonly string[] | undefined;
  public readonly settingsDefaults: Readonly<ChartSettingsValues> | undefined;
  private readonly _source: ThemeSource;

  public constructor(source: ThemeSource, parts: ContextParts) {
    this._source = source;
    this.chart = parts.chart;
    this.draw = parts.draw;
    this.objects = parts.objects;
    this.alerts = parts.alerts;
    this.history = parts.history;
    this.root = parts.root;
    this.document = parts.document;
    this.keymap = parts.keymap;
    this.bus = parts.bus;
    this.storage = parts.storage;
    this.locale = parts.locale;
    this.translate = parts.translate;
    this.symbolSearch = parts.symbolSearch;
    this.toast = parts.toast;
    this.openOverlay = parts.openOverlay;
    this.status = parts.status;
    this.tips = parts.tips;
    this.overlays = parts.overlays;
    this.symbol = parts.symbol;
    this.interval = parts.interval;
    this.intervals = parts.intervals;
    this.settingsDefaults = parts.settingsDefaults;
  }

  public get theme(): WidgetThemeName { return this._source.theme(); }
  public get chartTheme(): ChartTheme { return this._source.chartThemeInUse(); }
}

/**
 * The chart's options from the widget's. Everything the widget does not
 * consume itself goes to the chart as is, so a host keeps every engine option
 * it had; the widget adds its default bar spacing, reduced motion when the
 * user asks for it, and for a routed widget the engine's shortcuts gated by
 * the same decision as its own chords (`inChart` answers while the route
 * leaves the choice open).
 */
function engineOptions(options: WidgetOptions, doc: Document, inChart: () => boolean): ChartOptions {
  const chartOpts = { ...options } as Record<string, unknown>;
  for (const k of WIDGET_ONLY_KEYS) delete chartOpts[k];
  // A drag moves time and leaves the price scale fitting what is in view, so
  // a later wheel zoom still refits it. Dragging price as well switched the
  // pane to manual scaling, and from then on a zoom left bars off the pane.
  // The price axis still pans and scales price; a host or the Mouse drag
  // setting can ask for 'both'.
  const navigation = { mousePan: 'horizontal' as const, ...options.navigation };
  // The wheel zooms about the latest bar, which stays still while history
  // compresses or opens out beside it; Ctrl or Cmd zooms about the cursor.
  if (chartOpts.zoomAnchor === undefined) chartOpts.zoomAnchor = 'right';
  chartOpts.navigation = navigation.defaultVisibleBars === undefined && navigation.defaultBarSpacing === undefined
    ? { ...navigation, defaultBarSpacing: options.timeScale?.barSpacing ?? 8 }
    : navigation;
  // `movablePrimaryPane` reaches the engine as the host gave it, off unless
  // set. The widget's own chrome follows the price pane wherever it sits,
  // but a host's code on `widget.chart` may still pass 0 for the price, and
  // only the host knows whether it does.
  const reducedMotion = doc.defaultView?.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;
  if (reducedMotion && chartOpts.animZoom === undefined) chartOpts.animZoom = false;
  if (reducedMotion && chartOpts.animAutoscale === undefined) chartOpts.animAutoscale = false;
  // A routed widget hands the engine's shortcuts the same decision as its own
  // chords, so a hovered chart that is not the routed one stays still. A
  // host's own manager, which a grid shares between its charts, is wrapped
  // per chart rather than rebuilt, and its scope still decides whenever the
  // route leaves the choice open.
  const route = options.keyboardRoute;
  const given = options.shortcuts;
  if (route !== undefined && given !== false) {
    const target = given instanceof ShortcutManager ? given : new ShortcutManager(given);
    chartOpts.shortcuts = new Proxy(target, {
      get: (t, key) => {
        if (key === 'scope') return 'global';
        if (key === 'resolve') return (e: KeyboardEvent) => ((route() ?? (t.scope === 'global' || inChart())) ? t.resolve(e) : null);
        const value = Reflect.get(t, key) as unknown;
        return typeof value === 'function' ? (value as (...args: unknown[]) => unknown).bind(t) : value;
      },
    });
  }
  return chartOpts as ChartOptions;
}

/**
 * The popup chart-owned event markers open, in the widget's language and on
 * the chart's clock, closed by a context change or new events. Returns the
 * teardown.
 */
function eventDetailsPopup(ctx: WidgetContext, chartEl: HTMLElement, options: WidgetOptions): () => void {
  const chart = ctx.chart;
  const own = options.eventDetails === false ? undefined : options.eventDetails;
  const eventDetails = new EventDetailsPopup(chartEl, {
    styleNonce: options.styleNonce, overlays: ctx.overlays,
    formatTime: time => {
      const date = new Date(time * 1000);
      return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(options.locale, {
        timeZone: chart.timezone(), dateStyle: 'medium', timeStyle: 'short',
      }).format(date) : String(time);
    },
    ...own,
    // In the widget's language; a host's own labels still win, one by one.
    labels: { ...eventDetailsLabels(ctx), ...own?.labels },
    // Reuse the host's shared stylesheet and its preserved CSP nonce.
    injectStyles: false,
  });
  const offs = [
    chart.on('event:click', payload => {
      const details = payload as ChartEventClick;
      eventDetails.open(details, details.point);
    }),
    chart.on('data:context', () => eventDetails.close()),
    chart.on('events:change', () => eventDetails.close()),
  ];
  return () => { for (const off of offs) off(); eventDetails.destroy(); };
}

/**
 * A study legend's eye, gear and cross and the cross on an order or position
 * line are painted on the canvas, with no element to carry a name, so the
 * chart's hover id raises the widget's tip at the pointer saying what a press
 * does. Returns the teardown.
 */
function canvasButtonTips(ctx: WidgetContext, chartEl: HTMLElement): () => void {
  const spot = h(ctx.document, 'span', 'oac-tip-spot', { 'aria-hidden': 'true' });
  ctx.root.appendChild(spot);
  let said: string | null = null;
  const words = (id: string): string | null => {
    const sep = id.lastIndexOf('::');
    if (sep < 0) return null;
    const owner = id.slice(0, sep), action = id.slice(sep + 2);
    // The trade tier's lines hit-test as order: and position:, the chart's own trading layer as ord: and pos:.
    if (/^(?:ord|order):/.test(owner)) return action === 'close' ? widgetText(ctx, 'Cancel order') : null;
    if (/^(?:pos|position):/.test(owner)) return action === 'close' ? widgetText(ctx, 'Close position') : null;
    const study = owner.startsWith('indicator:') ? ctx.chart.indicators().find(item => item.id === owner.slice('indicator:'.length)) : undefined;
    if (study === undefined) return null;
    const name = study.name;
    return action === 'hide' ? widgetText(ctx, study.visible() ? 'Hide {name}' : 'Show {name}', { name })
      : action === 'settings' ? widgetText(ctx, 'Settings for {name}', { name })
        : action === 'close' ? widgetText(ctx, 'Remove {name}', { name }) : null;
  };
  ctx.tips.attach(spot, () => (said === null ? null : { title: said, side: 'bottom' }));
  const move = (e: PointerEvent): void => {
    const root = ctx.root.getBoundingClientRect();
    spot.style.left = `${e.clientX - root.left}px`;
    spot.style.top = `${e.clientY - root.top}px`;
  };
  chartEl.addEventListener('pointermove', move);
  const off = ctx.chart.on('hover', payload => {
    const id = (payload as { id: string | null }).id;
    said = id === null ? null : words(id);
    if (said !== null) ctx.tips.show(spot);
    else if (ctx.tips.target() === spot) ctx.tips.hide();
  });
  return () => { off(); chartEl.removeEventListener('pointermove', move); spot.remove(); };
}

class WidgetImpl implements Widget {
  public readonly dataController: DataLoadingController | null;
  public readonly chart: Chart;
  public readonly draw: DrawingController;
  public readonly instrumentDrawings: InstrumentDrawings | null;
  public readonly drawingTemplates: DrawingTemplates | null;
  public readonly objects: ChartObjects;
  public readonly alerts: AlertController;
  public readonly history: ChartHistory;
  public readonly root: HTMLElement;
  public readonly context: WidgetContext;
  public readonly ready: Promise<void>;
  private readonly _series: SeriesApi;

  private readonly _doc: Document;
  private readonly _opts: WidgetOptions;
  private readonly _bus = new ShellBus();
  private readonly _storage: WidgetStorage;
  private readonly _keymap: Keymap;
  private readonly _toasts: Toaster;
  private readonly _chartEl: HTMLElement;
  private _rail: RailHandle | null = null;
  private _topbar: TopbarHandle | null = null;
  private _statusline: StatuslineHandle | null = null;
  private _mobile: MobileHandle | null = null;
  private _drawbar: DrawingToolbarHandle | null = null;
  private _objectsPanel: PanelHandle | null = null;
  private _dock: PanelDockHandle | null = null;
  private _quickEntry: QuickEntryHandle | null = null;
  private _alertsPanel: PanelHandle | null = null;
  private _goToPanel: PanelHandle | null = null;
  private _layouts: WidgetLayouts | null = null;
  private readonly _navigator: DateNavigator;
  /** The ranges, the load window and the bar's controls (bottombar-shell.ts). */
  private readonly _bottombar: ShellBottombar;
  /** Bumped by every go-to request and every context change, so a waiting request knows it lost. */
  private _navigation = 0;
  private _loading: Promise<unknown> | null = null;
  /** Set while the widget itself moves the view for arriving data, which is not the user moving on. */
  private _anchoring = false;
  private readonly _intervals: string[];

  private _symbol: string;
  private _exchange: string;
  private _interval: string;
  private _variant: Readonly<DataVariant> | undefined;
  private _chartType: string;
  private _chartTypeRequest = 0;
  private _themeName: WidgetThemeName;
  private _chartTheme: ChartTheme;

  /** Not private: only the keyboard code in widget-keys.ts writes and reads it. */
  public _pointerInside = false;
  private _pointerInChart = false;
  private readonly _dataStatus: DataStatusHandle;
  private _displayedBars: readonly Bar[] | null = null;
  private _dataState: DataLoadingSnapshot | null = null;
  private _initialView = true;
  private _pendingView: WidgetChartState['viewport'] | null = null;
  private _keepView = false;
  private _saveTimer: ReturnType<typeof setTimeout> | 0 = 0;
  /** An asynchronous store has not answered yet: saves wait, and the first load is held. */
  private _restoring: boolean;
  // Not private: only widget-persist.ts reads the next three.
  /** Until the store answers, the drawings follow no instrument. */
  public _holdDrawings: boolean;
  /** A save was asked for while restoring; the one change worth writing once the store answers. */
  public _saveWanted = false;
  /** The host restored a whole state while restoring, which the stored one does not overwrite. */
  public _stateGiven = false;
  private _destroyed = false;
  private readonly _cleanups: Array<() => void> = [];

  public constructor(container: HTMLElement, options: WidgetOptions) {
    this._opts = options;
    this.dataController = options.feed ? new DataLoadingController(options.feed, {
      now: () => Math.floor((options.now ?? Date.now)() / 1000),
      ...options.loading,
    }) : null;
    this._navigator = new DateNavigator({ chart: () => this.chart, loadHistory: time => this._loadHistory(time) });
    const doc = options.document ?? container.ownerDocument;
    this._doc = doc;
    injectWidgetStyles(doc, WIDGET_COMPONENT_CSS, options.styleNonce);

    // ── persisted facts, before anything is built from them ────────────
    const ns = typeof options.persist === 'string' ? options.persist : 'default';
    const store = options.persist ? (options.storage === undefined ? defaultWidgetStore() : options.storage) : null;
    this._storage = new WidgetStorage(ns, store, { onError: failure => reportStorage.call(this as unknown as PersistHost, failure) });
    // An asynchronous store answers later: until then `saved` is null, the
    // shell is built on the defaults, and `restoreWhenLoaded` applies it.
    this._restoring = !this._storage.loaded;
    this._holdDrawings = this._restoring;
    const saved = readSaved.call(this as unknown as PersistHost);

    this._symbol = (options.symbol ?? saved?.symbol ?? '').toUpperCase();
    this._exchange = options.exchange ?? saved?.exchange ?? '';
    // A code nothing recognises is an error at the call site (the engine's
    // own rule: a chart showing the wrong timeframe is a wrong trade), and a
    // saved code from a build that registered it is dropped for the default.
    if (options.interval !== undefined) resolveInterval(options.interval);
    for (const code of options.intervals ?? []) resolveInterval(code);
    const savedInterval = saved !== null && isKnownInterval(saved.interval) ? saved.interval : '1d';
    this._interval = options.interval ?? savedInterval;
    // Like the interval: a malformed variant is an error at the call site, and
    // `readSaved` has already dropped one the stored record could not name.
    this._variant = options.variant !== undefined ? normalizeDataVariant(options.variant) : saved?.variant;
    const wantType = options.chartType ?? saved?.chartType ?? 'candlestick';
    if (options.chartType !== undefined && !isChartTypeChoice(options.chartType)) {
      throw new Error(`openalgo-charts widget: "${options.chartType}" is not a registered chart type`);
    }
    this._chartType = isChartTypeChoice(wantType) ? wantType : 'candlestick';
    const t = resolveTheme(options.theme ?? saved?.theme);
    this._themeName = t.name;
    this._chartTheme = t.theme;

    const set = new Set<string>(options.intervals ?? [...DEFAULT_INTERVALS, ...registeredIntervals().map((d) => d.code)]);
    set.add(this._interval);
    this._intervals = Array.from(set);

    // ── the frame ──────────────────────────────────────────────────────
    const root = h(doc, 'div', 'oac-widget');
    root.dataset.theme = this._themeName;
    applyTokens(root, widgetTokens(this._chartTheme, this._themeName));
    this.root = root;
    const topbarEl = h(doc, 'div', 'oac-topbar');
    if (options.topbar === false) topbarEl.hidden = true;
    root.appendChild(topbarEl);
    const stage = h(doc, 'div', 'oac-stage');
    root.appendChild(stage);
    const railEl = h(doc, 'div', 'oac-rail');
    if (options.rail === false) railEl.hidden = true;
    stage.appendChild(railEl);
    const chartEl = h(doc, 'div', 'oac-chart');
    this._chartEl = chartEl;
    stage.appendChild(chartEl);
    const statusEl = h(doc, 'div', 'oac-statusline');
    if (options.statusline === false) statusEl.hidden = true;
    root.appendChild(statusEl);
    const toastEl = h(doc, 'div', 'oac-toasts');
    root.appendChild(toastEl);
    container.appendChild(root);

    // ── the engine ─────────────────────────────────────────────────────
    this.chart = createChart(chartEl, { ...engineOptions(options, doc, () => this._inChart()), theme: this._chartTheme, document: doc });
    chartEl.setAttribute('aria-label', options.ariaLabel ?? widgetText(options, 'Price chart'));
    const transform = this._transformFor(this._chartType, options.chartType === undefined ? saved?.chart : undefined);
    this._series = this.chart.addSeries((transform === null ? this._chartType : getSeriesTransform(transform.type).renderer) as SeriesType,
      transform === null ? {} : { transform });
    this._publishDataContext();
    this.draw = new DrawingController(this.chart, {});
    // Before the alerts and before the saved layout lands: the drawings on the
    // chart are the current instrument's from the first moment anything reads them.
    this.instrumentDrawings = options.drawingScope === 'chart' ? null : scopeDrawings.call(this as unknown as PersistHost, saved);
    this.alerts = new AlertController(this.chart, { drawings: this.draw });
    this.objects = new ChartObjects(this.chart, {
      drawings: this.draw,
      // The name the rail and the properties title give the tool, translated.
      drawingName: tool => widgetText(options, `schema.drawing.${tool}.name`, {}, toolName(tool)),
      onSettings: object => {
        if (object.kind === 'source') this.openSettings();
        else if (object.kind === 'indicator') mountIndicatorSettings(this.context, undefined, { instanceId: object.sourceId });
        else if (object.kind === 'drawing') mountDrawingProperties(this.context, undefined, { ids: [object.sourceId] });
      },
    });
    // Before any chrome, so the first action a control takes is already a step.
    this.history = new ChartHistory(this.chart, {
      draw: this.draw,
      series: () => this._series,
      // Through the shell, so the top bar and the persisted layout follow.
      setChartType: id => this.setChartType(id),
      onError: ({ direction, error }) => {
        const reason = errorText(this.context, error);
        this._toasts.toast(direction === 'undo'
          ? widgetText(this.context, 'That step could not be undone: {error}', { error: reason })
          : widgetText(this.context, 'That step could not be redone: {error}', { error: reason }), 'error');
      },
    });

    // ── shared furniture ───────────────────────────────────────────────
    const overlays = createOverlayStack(root, doc);
    const tips = createTipController(root, overlays.layer, doc);
    this._toasts = mountToasts(toastEl, doc, options);
    const sc = this.chart.shortcuts;
    // The manager itself, not a listing of it: the shortcuts editor rebinds the chart's commands through it.
    this._keymap = new Keymap({ chart: sc, scopes: () => keyScopes.call(this as unknown as KeysHost) });
    this._keymap.onConflict((c) => this._bus.emit('keymap:conflict', { combo: c.combo, kept: c.kept, shadowed: c.shadowed }));
    this.context = this._createContext(root, doc, options, overlays, tips);
    this._cleanups.push(() => { tips.destroy(); overlays.destroy(); });
    this._cleanups.push(canvasButtonTips(this.context, chartEl));
    if (options.eventDetails !== false) this._cleanups.push(eventDetailsPopup(this.context, chartEl, options));
    this._dataStatus = mountDataStatus(this.context, stage, this.dataController, () => { void this.reload(); });
    if (options.panels !== false) {
      this._dock = mountPanelDock(this.context, stage, {
        data: host => mountDataWindow(this.context, host),
        objects: host => {
          const content = createObjectsPanelContent(this.context);
          host.appendChild(content.element);
          return content;
        },
        // An optional handler is passed only when there is one, so the
        // public declarations keep their method form.
        // Rows name instruments as setSymbol will chart them, so case cannot split one instrument in two.
        ...(options.watchlist ? { watchlist: (host: HTMLElement) => mountWatchlistPanel(this.context, host, {
          ...options.watchlist!, onSelect: instrument => this.setSymbol(instrument.symbol, instrument.exchange),
          normalize: instrument => ({ symbol: instrument.symbol.trim().toUpperCase(), exchange: instrument.exchange }),
        }) } : {}),
        ...(options.news ? { news: (host: HTMLElement) => mountNewsPanel(this.context, host, options.news!) } : {}),
        onChange: () => { this._bus.emit('layout', { reason: 'panels' }); this._scheduleSave(); },
      });
    }
    // The right-click menu is the one dialog nothing in the chrome opens, so
    // the shell subscribes it to the chart itself.
    this._cleanups.push(attachContextMenu(this.context, {
      ...(options.onOrder ? { onOrder: options.onOrder } : {}), tradingCapabilities: options.tradingCapabilities, tradingMode: options.tradingMode,
      ...(options.tradingLocked ? { tradingLocked: options.tradingLocked } : {}),
    }));

    // ── chrome ─────────────────────────────────────────────────────────
    if (options.rail !== false) {
      const railOpts: RailOptions = { ...(typeof options.rail === 'object' ? options.rail : {}), cursorTarget: chartEl };
      this._rail = mountRail(this.context, railEl, railOpts);
    }
    this.drawingTemplates = options.drawingTemplates ? createDrawingTemplates(this.context, options.drawingTemplates) : null;
    (this.context as WidgetContextImpl).drawingTemplates = this.drawingTemplates ?? undefined;
    if (options.drawingToolbar ?? options.rail !== false) this._drawbar = mountDrawingToolbar(this.context, stage, { chart: chartEl, templates: this.drawingTemplates });
    // With no bottom bar, here or under a grid, Go to and the market status stay in the chart's own bars.
    const gridBar = GRID_BAR_CHARTS.has(options);
    const barless = options.bottombar === false && !gridBar;
    if (options.statusline !== false) {
      this._statusline = mountStatusline(this.context, statusEl, { locale: options.locale, marketStatus: barless, now: options.now });
      this._statusline.setSymbol(this._symbol, this._exchange, this._interval);
      if (options.account !== undefined) {
        const summary = mountAccountSummary(this.context, statusEl, { source: options.account, locale: options.locale });
        this._cleanups.push(() => summary.destroy());
      }
    }
    // The calendar, the shading, the ranges and the bottom bar, between the stage and the status line.
    this._bottombar = attachBottombar.call(this as unknown as BottombarHost, statusEl);
    this._layouts = attachWidgetLayouts(this, options); // Layouts: before the chrome that opens the menu.
    if (options.topbar !== false) {
      this._topbar = mountTopbar(this.context, topbarEl, {
        intervals: this._intervals,
        indicators: options.indicators,
        search: this.context.symbolSearch,
        state: () => ({ symbol: this._symbol, exchange: this._exchange, interval: this._interval, chartType: this.chartType(), theme: this._themeName }),
        onSymbol: (s, ex) => this.setSymbol(s, ex),
        onInterval: (code) => this.setInterval(code),
        onChartType: (id) => this.setChartType(id),
        onTheme: (next) => this.setTheme(next),
        onSettings: (anchor) => this._openDialog('settings', anchor),
        onIndicators: (anchor) => this._openDialog('indicatorPicker', anchor),
        onObjects: (anchor) => this._openObjects(anchor),
        ...(options.panels === false ? {} : { onDataWindow: () => this._dock?.toggle('data') }),
        onAlerts: (anchor) => this._openAlerts(anchor),
        ...(this._docked('watchlist') ? { onWatchlist: () => this._dock?.toggle('watchlist') } : {}),
        ...(this._docked('news') ? { onNews: () => this._dock?.toggle('news') } : {}),
        ...(barless ? { onGoTo: (anchor: HTMLElement) => this._openGoTo(anchor) } : {}),
        layouts: this._layouts?.controller ?? undefined, onLayouts: (anchor) => this._layouts?.open(anchor),
        settingsAvailable: () => widgetDialog('settings') !== null,
        indicatorsAvailable: () => widgetDialog('indicatorPicker') !== null,
        dataAvailable: () => this.dataController === null || this._dataState?.status === 'ready' || this._dataState?.status === 'stale',
        captureRows: options.captureRows,
      });
    }
    this._mobile = mountMobile(this.context, {
      mode: options.mobile,
      container,
      intervals: this._intervals,
      topbar: options.topbar !== false,
      rail: this._rail,
      tools: typeof options.rail === 'object' ? options.rail.tools : undefined,
      indicators: options.indicators !== false,
      search: this.context.symbolSearch,
      state: () => ({ symbol: this._symbol, exchange: this._exchange, interval: this._interval, chartType: this.chartType(), theme: this._themeName }),
      onSymbol: (symbol, exchange) => this.setSymbol(symbol, exchange),
      onInterval: (code) => this.setInterval(code),
      onChartType: (id) => this.setChartType(id),
      onTheme: () => this.setTheme(this._themeName === 'dark' ? 'light' : 'dark'),
      onSettings: (anchor) => this._openDialog('settings', anchor),
      onIndicators: (anchor) => this._openDialog('indicatorPicker', anchor),
      onObjects: (anchor) => this._openObjects(anchor),
      ...(options.panels === false ? {} : { onDataWindow: () => this._dock?.toggle('data') }),
      onAlerts: (anchor) => this._openAlerts(anchor),
      ...(this._docked('watchlist') ? { onWatchlist: () => this._dock?.open('watchlist') } : {}),
      ...(this._docked('news') ? { onNews: () => this._dock?.open('news') } : {}),
      // A grid's bar shows on a phone too, so its Go to is the only one.
      ...(gridBar ? {} : { onGoTo: (anchor: HTMLElement) => this._openGoTo(anchor) }),
      onProperties: (anchor) => this._openDialog('drawingProperties', anchor),
      onCapture: (anchor) => this._topbar?.openCapture(anchor),
      // The More sheet stands in for the bottom bar the phone layout hides.
      bottombar: this._bottombar.controls,
      ...(this._layouts?.controller ? { onLayouts: () => this._layouts?.open() } : {}),
      settingsAvailable: () => widgetDialog('settings') !== null,
      indicatorsAvailable: () => widgetDialog('indicatorPicker') !== null,
    });

    installKeys.call(this as unknown as KeysHost);
    this._keymap.attach(doc);
    if (options.typingNavigation !== false) {
      this._quickEntry = mountQuickEntry(this.context, {
        enabled: () => !this._destroyed && this._doc.activeElement !== null
          && this._chartEl.contains(this._doc.activeElement) && this.draw.selection().length === 0,
        onSymbol: (symbol, exchange) => this.setSymbol(symbol, exchange),
        onInterval: code => this.setInterval(code), search: this.context.symbolSearch,
      });
    }
    trackPointer.call(this as unknown as KeysHost);
    this._followChart();

    // ── the saved layout, onto the dataset it belongs to ───────────────
    applySavedLayout.call(this as unknown as PersistHost, saved);

    if (this.dataController !== null) {
      this._cleanups.push(this.dataController.subscribe(state => this._applyData(state)));
      this.chart.setHistoryLoader(() => {
        void this.dataController!.loadMore().finally(() => { if (!this._destroyed) this.chart.historyLoadComplete(); });
      });
      const visibility = (): void => this.dataController!.setVisible(!doc.hidden);
      doc.addEventListener('visibilitychange', visibility);
      this._cleanups.push(() => doc.removeEventListener('visibilitychange', visibility));
      if (doc.hidden) visibility();
      if (this._symbol !== '' && !this._restoring) void this.reload();
    }
    this.ready = this._restoring ? restoreWhenLoaded.call(this as unknown as PersistHost) : Promise.resolve();
  }

  /** The context every piece of chrome reads, over the furniture the constructor has just built. */
  private _createContext(root: HTMLElement, doc: Document, options: WidgetOptions, overlays: OverlayStack, tips: TipController): WidgetContext {
    // The host's lookup wins; without one, a feed that searches serves every picker.
    const symbolSearch = options.symbolSearch ?? feedSymbolSearch(options.feed, () => this._exchange);
    return new WidgetContextImpl(this, {
      chart: this.chart,
      draw: this.draw,
      objects: this.objects,
      alerts: this.alerts,
      history: this.history,
      root,
      document: doc,
      keymap: this._keymap,
      bus: this._bus,
      storage: this._storage,
      locale: options.locale,
      translate: options.translate,
      symbolSearch,
      toast: (message: string, kind?: ToastKind): ToastHandle => this._toasts.toast(message, kind),
      openOverlay: (el: HTMLElement, o?: OverlayOptions): (() => void) => overlays.open(el, o),
      status: (text: string, kind: 'info' | 'error' = 'info'): void => {
        this._statusline?.setMessage(text, kind);
        this._bus.emit('status', { text, kind });
      },
      tips,
      overlays,
      symbol: () => ({ symbol: this._symbol, exchange: this._exchange }),
      interval: () => this._interval,
      intervals: options.intervals === undefined ? undefined : this._intervals,
      settingsDefaults: { 'navigation.mousePan': options.navigation?.mousePan ?? 'horizontal' },
    });
  }

  // ── facts ────────────────────────────────────────────────────────────
  public get series(): SeriesApi { return this._series; }
  public get layouts(): LayoutsController | null { return this._layouts?.controller ?? null; }
  public get isDestroyed(): boolean { return this._destroyed; }
  public symbol(): string { return this._symbol; }
  public exchange(): string { return this._exchange; }
  public interval(): string { return this._interval; }
  public variant(): Readonly<DataVariant> | undefined { return this._variant; }
  public chartType(): string {
    return this.chart.seriesTransform(this._series)?.type ?? this.chart.seriesType(this._series) ?? this._chartType;
  }

  /**
   * The transform a chart type applies, with the options a saved chart state
   * gave it, or null for a renderer. Point and figure and Kagi are both. A
   * widget that loads its own bars applies the transform. One whose host feeds
   * `widget.series` keeps them a renderer, which is the 2.5.x contract for a
   * host that prepares its own elements, so none is transformed twice.
   */
  private _transformFor(id: string, saved?: { series?: unknown }): SeriesTransformSpec | null {
    if (!registeredSeriesTransforms().includes(id) || (this._opts.feed === undefined && registeredChartTypes().includes(id))) return null;
    const series = Array.isArray(saved?.series) ? (saved.series as readonly ({ transform?: SeriesTransformSpec } | null)[]) : [];
    const options = series.find(item => item?.transform?.type === id)?.transform?.options;
    if (options === undefined) return { type: id };
    try { getSeriesTransform(id).create(options); return { type: id, options }; }
    catch { return { type: id }; } // options this build refuses: the transform's defaults
  }

  public theme(): WidgetThemeName { return this._themeName; }
  /** The engine palette in force, for the context's `chartTheme` getter. */
  public chartThemeInUse(): ChartTheme { return this._chartTheme; }

  public on<K extends WidgetEventName>(event: K, cb: (payload: WidgetBusEvents[K]) => void): () => void {
    return this._bus.on(event, cb);
  }

  public off<K extends WidgetEventName>(event: K, cb?: (payload: WidgetBusEvents[K]) => void): void {
    this._bus.off(event, cb);
  }

  // ── symbol, interval, type, theme ────────────────────────────────────
  public setSymbol(symbol: string, exchange?: string): void {
    const s = symbol.trim().toUpperCase();
    const ex = exchange ?? this._exchange;
    if (s === this._symbol && ex === this._exchange) { this._topbar?.refresh(); this._mobile?.refresh(); return; }
    this._symbol = s;
    this._exchange = ex;
    this._cancelNavigation();
    this._keepView = false;
    this._pendingView = null;
    if (this.dataController === null) {
      this._series.setData([]);
      this._publishDataContext();
    }
    this._statusline?.setSymbol(s, ex, this._interval);
    this._topbar?.refresh();
    this._mobile?.refresh();
    this._scheduleSave();
    if (this._opts.feed) void this.reload();
    // Listeners last, so a host's own bug in one cannot leave the shell
    // half-updated. A link group listens for the same fact on the chart's bus.
    this._bus.emit('symbol', { symbol: s, exchange: ex });
    this.chart.emit('symbol', { symbol: s, exchange: ex });
  }

  public setInterval(code: string): void {
    const c = code.trim();
    if (c === '') throw new Error('openalgo-charts widget: interval code must not be empty');
    resolveInterval(c);
    if (c === this._interval) { this._topbar?.refresh(); this._mobile?.refresh(); return; }
    this._interval = c;
    this._cancelNavigation();
    this._keepView = false;
    this._pendingView = null;
    if (this.dataController === null) {
      this._series.setData([]);
      this._publishDataContext();
    }
    this._statusline?.setSymbol(this._symbol, this._exchange, c);
    this._topbar?.refresh();
    this._mobile?.refresh();
    this._scheduleSave();
    if (this._opts.feed) void this.reload();
    this._bus.emit('interval', { interval: c });
  }

  public setDataVariant(variant: DataVariant | undefined): void {
    const next = normalizeDataVariant(variant);
    if (dataVariantKey(next) === dataVariantKey(this._variant)) return;
    this._variant = next;
    this._cancelNavigation();
    this._keepView = false;
    this._pendingView = null;
    if (this.dataController === null) {
      this._series.setData([]);
      this._publishDataContext();
    }
    this._scheduleSave();
    if (this._opts.feed) void this.reload();
    this._bus.emit('variant', { variant: next });
  }

  public setChartType(id: string): void { this._selectChartType(id); }

  /** `setChartType`, and a restore bringing the transform options its state saved. */
  private _selectChartType(id: string, saved?: Parameters<WidgetImpl['_transformFor']>[1]): void {
    if (!isChartTypeChoice(id)) throw new Error(`openalgo-charts widget: "${id}" is not a registered chart type`);
    // The type on screen again changes nothing, and keeps the options it was set up with.
    if (id === this.chartType() && saved === undefined) return;
    const transform = this._transformFor(id, saved);
    const request = ++this._chartTypeRequest;
    let changed = this.chart.setSeriesTransform(this._series, transform);
    // Each step notifies, and a listener may have chosen another type meanwhile.
    if (request !== this._chartTypeRequest) return;
    if (transform === null) changed = this.chart.setSeriesType(this._series, id as SeriesType) || changed;
    if (!changed || request !== this._chartTypeRequest || this.chartType() !== id) return;
    this._scheduleSave();
    this._bus.emit('layout', { reason: 'chartType', chartType: id });
  }

  public setTheme(theme: WidgetThemeName | ChartTheme): void {
    const t = resolveTheme(theme);
    this._themeName = t.name;
    this._chartTheme = t.theme;
    this.chart.setTheme(t.theme);
    this.root.dataset.theme = t.name;
    applyTokens(this.root, widgetTokens(t.theme, t.name));
    this._topbar?.refresh();
    this._mobile?.refresh();
    this._scheduleSave();
    this._bus.emit('theme', { theme: t.name, chartTheme: t.theme });
  }

  public openSettings(): boolean { return this._openDialog('settings'); }
  public openIndicatorPicker(): boolean { return this._openDialog('indicatorPicker'); }

  public openObjects(): boolean { return this._openObjects(); }
  public openDataWindow(): boolean {
    if (this._destroyed || !this._dock) return false;
    this._dock.open('data');
    return true;
  }
  public openAlerts(): boolean { return this._openAlerts(); }
  public openWatchlist(): boolean { return this._openDocked('watchlist'); }
  public openNews(): boolean { return this._openDocked('news'); }
  public openLayouts(): boolean { return !this._destroyed && (this._layouts?.open() ?? false); }

  /** Whether the dock carries this source: the option was given and panels are on. */
  private _docked(panel: 'watchlist' | 'news'): boolean {
    return this._opts.panels !== false && this._opts[panel] !== undefined;
  }

  private _openDocked(panel: 'watchlist' | 'news'): boolean {
    if (this._destroyed || !this._dock || !this._docked(panel)) return false;
    this._dock.open(panel);
    return true;
  }
  public openDateNavigation(): boolean { return this._openGoTo(); }
  // A range is the widget's, so it works with the bottom bar off.
  public setRange(id: string): Promise<DateNavigationResult> { return this._bottombar.setRange(id); }
  public range(): string | null { return this._bottombar.range(); }

  private _openGoTo(anchor?: HTMLElement): boolean {
    if (this._destroyed || timeBuckets(this._interval) === null) return false;
    if (this._goToPanel?.isOpen()) { this._goToPanel.el.focus(); return true; }
    let mine = 0;
    this._goToPanel = openDateNavigation(GRID_BAR_CHARTS.get(this._opts)?.(this.context) ?? this.context, anchor, {
      navigate: target => {
        const work = this.goTo(target);
        mine = this._navigation;
        return work;
      },
      // Only the panel's own request: a newer goTo or a context change already replaced it.
      cancel: () => { if (mine === this._navigation) this._cancelNavigation(); },
      onClose: () => { this._goToPanel = null; },
    });
    return true;
  }

  private _openAlerts(anchor?: HTMLElement): boolean {
    if (this._destroyed) return false;
    if (this._alertsPanel?.isOpen()) { this._alertsPanel.el.focus(); return true; }
    this._alertsPanel = mountAlertsPanel(this.context, anchor, { onClose: () => { this._alertsPanel = null; } });
    return true;
  }

  private _openObjects(anchor?: HTMLElement): boolean {
    if (this._destroyed) return false;
    if (this._dock) { this._dock.open('objects'); return true; }
    if (this._objectsPanel?.isOpen()) { this._objectsPanel.el.focus(); return true; }
    this._objectsPanel = mountObjectsPanel(this.context, anchor, { onClose: () => { this._objectsPanel = null; } });
    return true;
  }

  private _openDialog(name: WidgetDialogName, anchor?: HTMLElement): boolean {
    const mount = widgetDialog(name);
    if (mount === null) return false;
    mount(this.context, anchor);
    return true;
  }

  // ── data ─────────────────────────────────────────────────────────────
  private _publishDataContext(): void {
    const previous = this.chart.getDataContext();
    // Capabilities belong to the instrument, so an interval change retains them
    // while a symbol change waits for fresh metadata from the host.
    const sameInstrument = previous?.symbol === this._symbol && previous.exchange === this._exchange;
    // The variant is part of the source, so it goes through the helper that
    // makes a change of variant alone count as one.
    publishDataContext(this.chart, {
      symbol: this._symbol, exchange: this._exchange, interval: this._interval,
      ...(sameInstrument && previous.hasOpenInterest !== undefined ? { hasOpenInterest: previous.hasOpenInterest } : {}),
      ...(this._variant ? { variant: this._variant } : {}),
    });
  }

  public async reload(): Promise<void> {
    const controller = this.dataController;
    if (controller === null || this._destroyed) return;
    // The load the saved layout starts is this one: nothing goes out for the defaults.
    if (this._restoring) { await this.ready; await this._loading; return; }
    const current = controller.getState().request;
    const same = current?.symbol === this._symbol && current.exchange === this._exchange && current.interval === this._interval
      && dataVariantKey(current.variant) === dataVariantKey(this._variant);
    if (same) { await controller.refresh(); return; }
    const nowSec = this._opts.loading?.now?.() ?? Math.floor((this._opts.now ?? Date.now)() / 1000);
    const request: BarsRequest = { symbol: this._symbol, exchange: this._exchange, interval: this._interval,
      // A range in force widens the window to its sessions.
      ...this._bottombar.fetchWindow(loadWindow(this._interval, this._opts.lookbackBars ?? DEFAULT_LOOKBACK_BARS, nowSec), nowSec),
      ...(this._variant ? { variant: this._variant } : {}) };
    this._initialView = true;
    this._displayedBars = null;
    this._series.setData([]);
    this._publishDataContext();
    const work = controller.load(request);
    this._loading = work;
    await work;
    if (this._loading === work) this._loading = null;
  }

  public async goTo(target: DateNavigationTarget): Promise<DateNavigationResult> {
    const request = ++this._navigation;
    this._navigator.cancel();
    if (this._restoring) await this.ready;
    // The placement belongs after the accepted load, or the first data would reset it.
    if (this._loading !== null) await this._loading;
    if (request !== this._navigation || this._destroyed) return { status: 'cancelled' };
    return this._navigator.goTo(target);
  }

  private _cancelNavigation(): void {
    this._navigation++;
    this._navigator.cancel();
  }

  /** One reach of the managed controller, translated into what the navigator can decide on. */
  private async _loadHistory(time: number): Promise<HistoryReach> {
    const controller = this.dataController;
    const state = controller?.getState();
    if (controller == null || state === undefined || state.paused || state.request === null) return 'unavailable';
    if (state.hasMore === false) return 'exhausted';
    const first = controller.bars()[0]?.time;
    // A pan or zoom the widget did not make while the page loads (a gesture,
    // a key, a linked chart, the host's own call) means the view is wanted
    // elsewhere, and a placement landing after it would undo it. A first load
    // is not watched: the chart is blank until it lands and then resets.
    const moved = (): void => { if (!this._anchoring) this._cancelNavigation(); };
    const offs = [this.chart.on('pan', moved), this.chart.on('zoom', moved)];
    try { await controller.loadMore(time); } finally { for (const off of offs) off(); }
    const next = controller.getState();
    if (next.historyStatus === 'error') throw next.historyError ?? new Error('Older history failed to load');
    if (next.historyStatus === 'limited') return 'limited';
    const reached = controller.bars()[0]?.time;
    if (reached !== undefined && (first === undefined || reached < first)) return 'loaded';
    return next.hasMore === false ? 'exhausted' : 'empty';
  }

  private _applyData(state: DataLoadingSnapshot): void {
    if (this._destroyed || state.request === null) return;
    const previous = this._dataState;
    this._dataState = state;
    this._dataStatus.update(state);
    const { symbol, interval } = state.request;
    if (!state.paused && state.bars !== this._displayedBars) {
      const before = this._series.getData();
      const view = this.chart.getVisibleLogicalRange();
      // The view indexes what is drawn: a transformed series draws elements its handle does not return.
      const transformed = this.chart.seriesTransform(this._series) !== null;
      const drawn = transformed ? this.chart.primaryBars() : before;
      const anchor = drawn[Math.max(0, Math.min(drawn.length - 1, Math.round(view.from)))];
      const anchorIndex = anchor === undefined ? -1 : drawn.findIndex(bar => bar.time === anchor.time);
      const tail = state.bars[state.bars.length - 1];
      if (state.reason === 'live' && tail !== undefined && before[0]?.time === state.bars[0]?.time &&
        (before.length === state.bars.length || before.length + 1 === state.bars.length)) this._series.update(tail);
      else {
        // A page of older history reaches a transformed series as a prepend, so the
        // sizes it resolved from the loaded history stand and no brick is resized.
        const oldest = before[0];
        const older = transformed && state.reason === 'prepend' && oldest !== undefined ? state.bars.filter(bar => bar.time < oldest.time) : [];
        if (older.length > 0 && older.length + before.length === state.bars.length) this._series.prependData(older);
        else this._series.setData(state.bars);
        this._anchoring = true;
        if (state.bars.length > 0) {
          if (this._initialView) {
            if (this._pendingView) this.chart.setVisibleLogicalRange(this._pendingView);
            else if (!this._keepView) this.chart.resetScale();
            this._pendingView = null;
            this._initialView = false;
            this._keepView = false;
          } else {
            // Elements are formed again from the new history, so the anchor is the last one at or before its time.
            const after = transformed ? this.chart.primaryBars() : state.bars;
            const nextIndex = anchor === undefined ? -1 : transformed
              ? after.filter(bar => bar.time <= anchor.time).length - 1 : after.findIndex(bar => bar.time === anchor.time);
            const shift = nextIndex < 0 || anchorIndex < 0 ? 0 : nextIndex - anchorIndex;
            this.chart.setVisibleLogicalRange({ from: view.from + shift, to: view.to + shift });
          }
        }
        this._anchoring = false;
      }
      this._displayedBars = state.bars;
      this._statusline?.refresh();
    }
    if (previous?.status === state.status && previous.error === state.error && !['load', 'refresh', 'prepend', 'resume'].includes(state.reason)) return;
    if (state.status === 'unsupported') {
      // Nothing was fetched and a retry would ask the same provider the same
      // question, so this says what is missing and leaves the choice to the user.
      const variant = dataVariantLabel(this.context, state.request.variant, state.unsupported);
      this.context.status(widgetText(this.context, 'Not available from this source: {variant}', { variant }), 'error');
      this._bus.emit('data', { symbol, interval, bars: 0, error: state.error?.message });
    } else if (state.status === 'loading') this.context.status(widgetText(this.context, 'Loading {symbol} {interval}', { symbol, interval }));
    else if (state.status === 'refreshing') this.context.status(widgetText(this.context, 'History is stale. Refreshing {symbol} {interval}', { symbol, interval }));
    else if (state.status === 'error' || state.status === 'stale') {
      this.context.status(state.status === 'stale' ? widgetText(this.context, 'History is stale for {symbol} {interval}', { symbol, interval }) : widgetText(this.context, 'Could not load {symbol} {interval}', { symbol, interval }), 'error');
      if (state.error && state.error !== previous?.error) {
        this._toasts.toast(widgetText(this.context, 'Could not load {symbol} {interval}: {error}', { symbol, interval, error: state.error.message }), 'error');
        this._bus.emit('data', { symbol, interval, bars: 0, error: state.error.message });
      }
    } else if (state.status === 'ready' || state.status === 'empty') {
      this.context.status(state.bars.length === 0 ? widgetText(this.context, 'No bars for {symbol} {interval}', { symbol, interval }) : widgetText(this.context, state.bars.length === 1 ? '{count} bar' : '{count} bars', { count: state.bars.length }));
      this._bus.emit('data', { symbol, interval, bars: state.bars.length });
    }
  }

  // ── state ────────────────────────────────────────────────────────────
  public getState(): WidgetState {
    return {
      version: WIDGET_STATE_VERSION,
      symbol: this._symbol,
      exchange: this._exchange,
      interval: this._interval,
      chartType: this.chartType(),
      theme: this._themeName,
      ...(this._variant ? { variant: this._variant } : {}),
      chart: this.chart.getState(),
      rail: this._rail?.prefs() ?? null,
      panels: this._dock?.state(),
      savedBy: VERSION,
    };
  }

  public restoreState(state: unknown): WidgetRestoreReport {
    // A loaded layout is a new document, not a step: nothing recorded before
    // it describes the chart it builds, and nothing it sets is the user's edit.
    const report = this.history.ignore(() => restoreWidgetState.call(this as unknown as PersistHost, state));
    if (report.applied) this.history.clear();
    return report;
  }

  private _scheduleSave(): void { scheduleSave.call(this as unknown as PersistHost); }

  private _saveNow(): void { saveNow.call(this as unknown as PersistHost); }

  // ── keyboard ─────────────────────────────────────────────────────────
  /** The engine's own test for its shortcuts: the pointer over the chart, or the focus in it. */
  private _inChart(): boolean {
    const active = this._doc.activeElement;
    return this._pointerInChart || (active !== null && this._chartEl.contains(active));
  }

  /** Every change that lands in `getState` schedules a save and a layout notice. */
  private _followChart(): void {
    const chartEvents = ['paneAdded', 'paneResized', 'paneMoved', 'paneMaximized', 'paneCollapsed', 'paneRemoved', 'indicatorRemoved', 'indicatorSettings', 'priceAxisMoved', 'objects:change'] as const;
    for (const ev of chartEvents) {
      this._cleanups.push(this.chart.on(ev, () => {
        if (ev === 'objects:change' && this.chartType() !== this._chartType) {
          this._chartType = this.chartType();
          this._topbar?.refresh();
          this._mobile?.refresh();
          this._statusline?.refresh();
        }
        this._bus.emit('layout', { reason: ev });
        this._scheduleSave();
      }));
    }
    for (const ev of ['draw:add', 'draw:remove', 'draw:update', 'draw:paste', 'draw:cut',
      'alert:created', 'alert:updated', 'alert:removed', 'alert:triggered', 'alert:expired', 'alerts:restored', 'alerts:checkpoint'] as const) {
      this._cleanups.push(this.chart.on(ev, () => this._scheduleSave()));
    }
    // An undo can set what the chart does not announce, a pane height or a
    // scale option, and the saved layout has to follow it all the same.
    this._cleanups.push(this.history.subscribe(() => this._scheduleSave()));
    this._cleanups.push(this.chart.on('alert:triggered', payload => {
      const event = payload as AlertTriggeredPayload;
      this.context.toast(event.message ?? event.title, 'success');
    }));
    flushOnPageHide.call(this as unknown as PersistHost);
  }

  public destroy(): void {
    if (this._destroyed) return;
    this._saveNow();
    // Sends an asynchronous store's writes now, journaled in case the page is
    // going too, and stops following other tabs' changes to it.
    void this._storage.flush();
    this._storage.close();
    this._destroyed = true;
    this._cancelNavigation();
    this._navigator.destroy();
    this._goToPanel?.close();
    this._quickEntry?.destroy();
    this._dock?.destroy();
    this.dataController?.destroy();
    this._dataStatus.destroy();
    this._layouts?.destroy();
    this._mobile?.destroy();
    this._mobile = null;
    this._drawbar?.destroy();
    this.drawingTemplates?.destroy();
    if (this._saveTimer !== 0) { clearTimeout(this._saveTimer); this._saveTimer = 0; }
    for (const c of this._cleanups.splice(0)) c();
    this._topbar?.destroy();
    this._rail?.destroy();
    this._statusline?.destroy();
    this._toasts.destroy();
    this._keymap.destroy();
    this.history.destroy();
    this.objects.destroy();
    this.alerts.destroy();
    this.instrumentDrawings?.destroy();
    this.draw.destroy();
    this.chart.destroy();
    this.root.remove();
    this._bus.clear();
  }
}

/** For the host types of widget-keys.ts and widget-persist.ts; the tier entry does not export it. */
export type { WidgetImpl };

/**
 * Build a widget inside `container`: an element, or a selector (or id)
 * resolved against `options.document` or the page.
 */
export function createWidget(container: HTMLElement | string, options: WidgetOptions = {}): Widget {
  let el: HTMLElement | null;
  if (typeof container === 'string') {
    const doc = options.document ?? (globalThis as { document?: Document }).document;
    if (doc === undefined) throw new Error('openalgo-charts widget: a selector needs a document');
    el = doc.querySelector<HTMLElement>(container) ?? doc.getElementById(container);
    if (el === null) throw new Error(`openalgo-charts widget: no element matches "${container}"`);
  } else {
    el = container;
  }
  return new WidgetImpl(el, options);
}
