/**
 * The chart grid: several widgets in one workspace.
 *
 * `createChartGrid(container, options)` lays one widget out per cell on a rows
 * by columns grid, puts splitters between the tracks, keeps one cell active,
 * links the charts through the engine's link groups, and reads and writes the
 * portable payload of `openalgo-charts/workspace`, so a saved desk opens here
 * with the geometry, weights, focus and links it was saved with.
 *
 * Decisions worth recording:
 *
 * - **Every cell is an ordinary widget.** The grid adds layout, focus and
 *   linking around them and reaches each one through its public API, so a
 *   cell loads, cancels and tears down its own feed exactly as a lone widget.
 * - **One active cell answers the keyboard.** Every widget listens on the
 *   document, so without a referee one chord reaches each chart the pointer or
 *   the focus happens to touch. Other cells are silenced through
 *   `keyboardRoute`, and a key pressed with the focus on the page itself goes
 *   to the active chart while the pointer is over the grid.
 * - **Applying a workspace is all or nothing.** The new cells are built and
 *   restored off to the side; the first failure destroys them, which cancels
 *   their history requests, and the charts on screen are never touched.
 * - **A view set by data is not a pan.** A chart fitting bars it has just
 *   received moves its window, and broadcasting that to a follower on another
 *   timeframe would squeeze the follower's data into a sliver. Data-driven
 *   moves stay local; linked views converge on the next real pan or zoom.
 * - **Each chart keeps drawings per instrument, for itself.** A cell's store
 *   is its own, keyed by its pane id: two cells on one symbol writing one
 *   shared document would each overwrite the other's lines. The documents of
 *   the instruments a cell is not showing are saved beside the workspace,
 *   whose own payload carries only what each chart shows.
 * - **Maximizing is a view, not a layout.** It shows the active chart alone
 *   the way the compact width does, keeps every other chart alive behind it,
 *   and is not saved: a desk reopens as the grid it is.
 * - **The grid's chrome is the host's choice.** The bar over the charts and
 *   the one under them are off unless asked for, so a host with controls of
 *   its own keeps its page as it was, and each chart keeps its own Go to and
 *   market status until a bar under the grid takes them over.
 *
 * The grid's state is one object, `GridState`, that the functions here share
 * with the parts split out of this file: grid-persist.ts (the saved desk),
 * grid-tracks.ts (the tracks and their splitters) and grid-capture.ts (one
 * picture of every chart).
 */
import type { ChartTheme, DataFeed, DataVariant, LinkChart, LinkOptions, ResolvedLinkOptions } from 'openalgo-charts';
import type { WorkspaceChartState, WorkspacePane, WorkspacePayload, WorkspaceStore } from 'openalgo-charts/workspace';
import {
  WidgetBus, createOverlayStack, createTipController, h,
  type AsyncStorageLike, type OverlayOptions, type OverlayStack, type StorageLike, type TipController, type WidgetContext, type WidgetStorage,
} from './context';
import { mountBottombar, type BottombarHandle } from './bottombar';
import type { LayoutsController } from './layouts';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { applyTokens, widgetTokens, type WidgetThemeName } from './tokens';
import { GRID_BAR_CHARTS, createWidget, resolveTheme, type Widget, type WidgetOptions } from './widget';
import type { GridSaved } from './grid-saved';
import { canCopyImage } from './capture';
import { restorePane, THEME_SETTING, widgetPane } from './layouts-target';
import { cellDrawingStore, checkWorkspace, type ChartDrawings } from './grid-payload';
import { CHART_GRID_LAYOUTS, focusSlot, isChartGridLayout, type ChartGridLayoutId } from './grid-layouts';
import {
  ALL_OFF, GridLinks, channelsOf, describeGroups, instrument, linkMember,
  type ChartGridLinkGroup, type GridGroup, type LinkChannel,
} from './grid-links';
import type { GridBarHandle, GridBarHost } from './grid-bar';
import {
  captureBlocked, captureRows, copyAll, downloadAll, downloadGridScreenshot, report, takeGridScreenshot,
} from './grid-capture';
import { groupMark, installGridKeys, installHeaderDrag, neighbour } from './grid-cells';
import { followChords, gridStorage, leaving, openStoredDesk, saveNow, saveSoon, scheduleSave } from './grid-persist';
import { density, solo, splitters, tracks } from './grid-tracks';
import { lazyPart, partFailed, usePart, type PartSlot } from './lazy';
import { rovingIndex } from './roving';

/** The grid bar, fetched when a grid shows it, and its menus, fetched when one first opens (lazy.ts). Internal. */
export const gridBarPart = lazyPart(() => import('./grid-bar'));
export const gridMenusPart = lazyPart(() => import('./grid-menus'));

export { CHART_GRID_PRESETS, type ChartGridPreset } from './grid-layouts';

export interface ChartGridOptions extends Omit<WidgetOptions, 'persist' | 'storage' | 'keyboardRoute' | 'feed' | 'drawingStore' | 'captureRows'> {
  /**
   * Where the charts load bars: one feed for every chart, or a function that
   * builds each chart's feed from its pane id and the `historyPeriod` its
   * workspace pane carries, for a host whose source answers by period.
   */
  feed?: DataFeed | ((chart: { readonly id: string; readonly historyPeriod?: string | undefined }) => DataFeed);
  /** The layout to start with when nothing is restored: a preset or any `CHART_GRID_LAYOUTS` id. Default `1x1`. */
  preset?: ChartGridLayoutId;
  /** Link channels the first group starts with, and every new group. Default: crosshair and viewport on, the rest off. */
  links?: LinkOptions;
  /** At or below this width in CSS px only the active chart shows, with tabs to switch. 0 turns it off. Default 640. */
  compactWidth?: number;
  /** Keep the workspace between visits: `true` for one shared namespace, a string to name one. Default off. */
  persist?: boolean | string;
  /**
   * The store behind `persist`. Default: IndexedDB where the page has it
   * (since 2.5.10), else the page's `localStorage`. Over an asynchronous
   * store the saved desk lands when `ready` settles; a synchronous one, such
   * as `localStorage` passed here, restores it before `createChartGrid` returns.
   */
  storage?: StorageLike | AsyncStorageLike | null;
  /**
   * Show the grid bar over the charts: the layout picker, maximize and
   * restore, the link menu, a capture of every chart and, with `workspaces`,
   * the desk's saved layouts. Default false, so a host with its own controls
   * keeps its page as it was.
   */
  toolbar?: boolean;
  /**
   * One bottom bar under the grid, acting on the active chart: preset ranges,
   * Go to, the market status, the clock and the price scale toggles (since
   * 2.5.10). The charts then leave Go to out of their own bars and the market
   * status off their status lines. Default false, as for `toolbar`: each
   * chart keeps both.
   */
  bottombar?: boolean;
  /**
   * Saved layouts of the whole desk, and indicator templates in every
   * chart's picker: a `WorkspaceRepository` from `openalgo-charts/workspace`,
   * or a host's own `WorkspaceStore`. With the grid bar (`toolbar`) the grid
   * keeps a layouts controller over every chart: a Layouts control in the bar
   * saves and opens the desk, autosave follows it, and the layout that was
   * active when the page last closed opens once `ready` settles, unless the
   * host has applied a workspace by then. Without the bar the charts get their
   * templates only. Taken as a type only.
   */
  workspaces?: WorkspaceStore;
  /**
   * What the grid bar's Layouts control drives instead of the grid's own
   * controller: one the host built over this grid; false for no control.
   * Without the bar (`toolbar`), a controller given here drives each chart's
   * own Layouts button instead. A chart never saves a layout of its own inside
   * a grid.
   */
  layouts?: LayoutsController | false;
  /**
   * The layouts the bar's picker offers, in its order, as `intervals` lists
   * the intervals beside `interval`. Default: every `CHART_GRID_LAYOUTS`
   * entry. Empty: the bar has no Layout control. (`layouts` keeps its widget
   * meaning here: the saved-layouts controller every chart's menu drives.)
   */
  presets?: readonly ChartGridLayoutId[];
}

export interface ChartGridCell {
  /** The workspace pane id. */
  readonly id: string;
  readonly widget: Widget;
  /** The `.oac-grid__cell` element the widget lives in. */
  readonly element: HTMLElement;
  readonly row: number;
  readonly column: number;
  readonly rowSpan: number;
  readonly columnSpan: number;
  /**
   * The host's name for how much history the chart loads, from the applied
   * workspace pane or the active chart a preset copied. The grid only keeps it
   * and writes it back; a `feed` function is what honours it.
   */
  readonly historyPeriod?: string;
  /** The id of the link group the chart is in, or null when it links with none. */
  readonly linkGroup: string | null;
}

export interface ChartGridLayout {
  rows: number;
  columns: number;
  /** The layout id or saved preset name the layout came from, or null. */
  preset: string | null;
  rowWeights: number[];
  columnWeights: number[];
}

export interface ChartGridApplyReport {
  applied: boolean;
  reason?: string;
}

export interface ChartGridEvents {
  active: { id: string };
  /** `preset`, `weights`, `workspace`, `compact`, `maximize` or `swap`. */
  layout: { reason: string };
  /** The active chart's link channels, after any link, group or active chart change. */
  links: ResolvedLinkOptions;
  /** Every chart changed theme, through `setTheme` or one chart's own control. */
  theme: { theme: WidgetThemeName };
  [key: string]: unknown;
}

export type ChartGridEventName = 'active' | 'layout' | 'links' | 'theme';

export type { ChartGridLinkGroup } from './grid-links';

export interface ChartGrid {
  /** The `.oac-grid` element. */
  readonly root: HTMLElement;
  readonly isDestroyed: boolean;
  /** The cells in reading order: by row, then by column. */
  cells(): readonly ChartGridCell[];
  active(): ChartGridCell;
  /** Make a cell the one the keyboard and shared controls act on. False for an unknown id. */
  setActive(id: string, options?: { focus?: boolean }): boolean;
  layout(): ChartGridLayout;
  /**
   * What restoring the persisted workspace did when the grid was built: null
   * when nothing was stored, and until `ready` settles over an asynchronous
   * store. A refused desk stays stored, untouched, until the user changes the grid.
   */
  restored(): ChartGridApplyReport | null;
  /**
   * Settles once the persisted workspace has been read and applied (since
   * 2.5.10): at once without `persist` or over a synchronous store. Over an
   * asynchronous one (IndexedDB, the default) the grid is built from the
   * preset, out of sight and loading nothing, until then; a workspace applied
   * meanwhile wins over the stored one. Never rejects.
   */
  readonly ready: Promise<void>;
  /**
   * Reflow into a layout. The charts that fit keep their state in reading
   * order and new ones copy the active chart's instrument; in an uneven layout
   * the active chart takes the large slot, and stays even when it sat past the
   * charts that fit. Weights reset to the layout's.
   * Throws for an id that is not in `CHART_GRID_LAYOUTS`.
   */
  setPreset(preset: ChartGridLayoutId): void;
  /** Show one chart alone, the active one by default; the others stay alive. False for an unknown id or a single chart. */
  maximize(id?: string): boolean;
  /** Show every chart again after `maximize`. */
  restore(): void;
  /** The maximized chart's id, or null while the grid shows every chart. */
  maximized(): string | null;
  /** Trade the places of two charts, spans included. False for an unknown or repeated id. */
  swap(first: string, second: string): boolean;
  /** The active chart's link channels (the whole desk's until groups are made); every channel off when it links with none. */
  linkOptions(): ResolvedLinkOptions;
  /**
   * Switch channels of the active chart's group, or of every group when it is
   * in none. Switching symbol, interval or chart type linking on adopts the
   * active chart's choice.
   */
  setLinks(patch: LinkOptions): void;
  /** Every link group, in the order they were made, with the charts in each. */
  linkGroups(): readonly ChartGridLinkGroup[];
  /** Move a chart into a group, or out of every group with null. It adopts what the group links on. */
  setLinkGroup(cell: string, group: string | null): boolean;
  /** Start a group with this chart in it; the id, or null for an unknown chart or when sixteen groups exist. */
  addLinkGroup(cell: string, options?: { name?: string; links?: LinkOptions }): string | null;
  /** Switch channels of one group. False for an unknown group. */
  setGroupLinks(group: string, patch: LinkOptions): boolean;
  /** Name a group, 1 to 120 characters after trimming. */
  renameLinkGroup(group: string, name: string): boolean;
  /**
   * Send a chart's drawings to the charts its group shares drawings with, on
   * the same instrument. Drawings made before the switch went on stay private
   * until shared. The number shared, 0 when there is nowhere to share them.
   */
  shareDrawings(cell: string): number;
  theme(): WidgetThemeName;
  setTheme(theme: WidgetThemeName | ChartTheme): void;
  /** Whether the grid is narrow enough to show one chart at a time. */
  compact(): boolean;
  /**
   * One image of every chart at its place on the grid, at the device pixel
   * ratio. Null while the grid shows one chart at a time (compact or
   * maximized), when the hidden charts would come out blank.
   */
  takeScreenshot(): HTMLCanvasElement | null;
  /** Save `takeScreenshot()` as a PNG. False when there is no image or the runtime cannot save it. */
  downloadScreenshot(filename?: string): boolean;
  getWorkspace(): WorkspacePayload;
  /** Replace every chart with a validated payload, or change nothing and say why. */
  applyWorkspace(payload: WorkspacePayload): ChartGridApplyReport;
  on<K extends ChartGridEventName>(event: K, cb: (payload: ChartGridEvents[K]) => void): () => void;
  destroy(): void;
}

/** A chart on the grid, as the grid keeps it. Internal. */
export interface Cell {
  id: string;
  widget: Widget;
  element: HTMLElement;
  row: number;
  column: number;
  rowSpan: number;
  columnSpan: number;
  historyPeriod?: string;
  member: LinkChart;
  group: GridGroup<Cell> | null;
  /** The chart type last reported to the group, so a repeated notice is not a change. */
  type: string;
  /** The link group mark in the chart's bar, while groups are in use. */
  mark: HTMLButtonElement | null;
  offs: Array<() => void>;
  /** Bars across the window the chart showed last, 0 while it had no plot. */
  span: number;
  /** Keep that window through the next resize: set when a maximize or restore changes the chart's size. */
  hold: boolean;
}

interface Source {
  symbol?: string | undefined; exchange?: string | undefined; interval?: string | undefined; variant?: DataVariant | undefined;
  chartType?: string | undefined; historyPeriod?: string | undefined;
}

/**
 * The grid's own menus hang over every chart, so they live in a layer over
 * the whole grid rather than in any one widget. Made on first use: a grid
 * with no bar and one link group never opens a menu, and its page keeps
 * exactly the elements it had.
 */
interface ChromeLayer { el: HTMLElement; overlays: OverlayStack; tips: TipController }

/**
 * Everything one grid keeps between calls, in one object: the functions of
 * this file and of the parts split out of it take it first. Internal.
 */
export interface GridState {
  readonly doc: Document;
  readonly options: ChartGridOptions;
  /** The options, as the translation every message the grid writes goes through. */
  readonly text: WidgetTranslationOptions;
  /** What every chart is built with: the grid's options less the grid's own. */
  readonly cellOptions: Record<string, unknown>;
  /** Made once the state is, since its failures are said on the active chart. */
  storage: WidgetStorage;
  readonly bus: WidgetBus<ChartGridEvents>;
  readonly links: GridLinks<Cell>;
  /** Undoes the grid's own listeners. */
  readonly offs: Array<() => void>;
  readonly root: HTMLElement;
  readonly tabs: HTMLElement;
  readonly body: HTMLElement;
  readonly barEl: HTMLElement | null;
  readonly footEl: HTMLElement | null;
  readonly splits: HTMLElement[];
  /** The grid a host holds, which the grid's own parts call too. */
  grid: ChartGrid;
  barHost: GridBarHost;
  /**
   * An asynchronous store has not answered yet: nothing is written, so the
   * preset cannot be saved over the desk it holds, and the preset's charts
   * are built without an instrument, so none of them asks the feed for one.
   */
  restoring: boolean;
  /**
   * A workspace was applied through `applyWorkspace`: one applied while the
   * store was read wins over the stored desk, and one applied before the saved
   * layouts reopen the last layout wins over that.
   */
  given: boolean;
  cells: Cell[];
  // The user's chords belong to the desk, not to one chart: one record in the
  // grid's storage, applied to every chart and passed on when a chart changes
  // it. Read when the stored desk is, since an asynchronous store has no copy before.
  chords: unknown;
  sharing: boolean;
  active: Cell | null;
  rows: number;
  cols: number;
  rowW: number[];
  colW: number[];
  preset: string | null;
  theme: WidgetThemeName | ChartTheme;
  themeSync: boolean;
  compact: boolean;
  maxed: boolean;
  pointerIn: boolean;
  destroyed: boolean;
  /** True while the grid itself moves a chart's window, which is no user navigation. */
  syncing: boolean;
  nextId: number;
  saveTimer: ReturnType<typeof setTimeout> | 0;
  saveQueued: boolean;
  /** The last save was refused by the store, and was said; the next refusal is the same failure. */
  saveRefused: boolean;
  /** A stored desk this grid refused to restore, kept until the user changes something. */
  held: boolean;
  restored: ChartGridApplyReport | null;
  /** The drawings of the charts on the grid, for the instruments each one is not showing. */
  drawings: ChartDrawings;
  chromeLayer: ChromeLayer | null;
  bar: GridBarHandle | null;
  foot: BottombarHandle | null;
  saved: GridSaved | null;
  ready: Promise<void>;
}

// `drawingStore` too: each cell gets a store of its own from the grid.
const GRID_ONLY_KEYS = ['preset', 'links', 'compactWidth', 'persist', 'storage', 'drawingStore', 'toolbar', 'presets'];

const ones = (n: number): number[] => Array.from({ length: n }, () => 1);

/**
 * Build a chart grid inside `container`: an element, or a selector resolved
 * against `options.document` or the page.
 */
export function createChartGrid(container: HTMLElement | string, options: ChartGridOptions = {}): ChartGrid {
  if (typeof container === 'string') {
    const found = (options.document ?? (globalThis as { document?: Document }).document)?.querySelector<HTMLElement>(container);
    if (!found) throw new Error(`openalgo-charts grid: no element matches "${container}"`);
    container = found;
  }
  const doc = options.document ?? container.ownerDocument;
  const text = options;
  const cellOptions = { ...options } as Record<string, unknown>;
  for (const key of GRID_ONLY_KEYS) delete cellOptions[key];
  // A cell in a two-column grid is often narrower than the phone threshold,
  // so cells keep desktop chrome unless the host asks for touch controls.
  // Each chart's capture menu offers the whole grid beside its own picture.
  Object.assign(cellOptions, { document: doc, mobile: options.mobile ?? 'never', captureRows: () => captureRows(s) });
  // A chart has no bottom bar of its own; the grid's one bar, when it has
  // one, acts on the active chart.
  cellOptions.bottombar = false;
  // Layouts: a chart never saves a layout of its own inside a grid. The
  // `workspaces` store still gives every picker its templates. The desk's
  // Layouts control is the grid bar's; without the bar, a controller the host
  // passes drives the menu of every chart.
  cellOptions.layouts = options.toolbar === true ? false : options.layouts ?? false;

  const root = h(doc, 'div', 'oac-grid');
  const tabs = h(doc, 'div', 'oac-grid__tabs', { role: 'tablist', 'aria-label': widgetText(text, 'Charts') });
  const body = h(doc, 'div', 'oac-grid__cells');
  tabs.hidden = true;
  // The strip is laid out at the bar's height now, so the charts keep their size when the bar arrives.
  const barEl = options.toolbar === true ? h(doc, 'div', 'oac-widget oac-grid__bar', { role: 'toolbar', 'aria-label': widgetText(text, 'Chart grid') }) : null;
  // The bottom bar's rules are scoped under `.oac-widget`, like every piece of the widget's chrome.
  const footEl = options.bottombar === true ? h(doc, 'div', 'oac-widget oac-grid__foot') : null;
  root.append(...(barEl === null ? [] : [barEl]), tabs, body, ...(footEl === null ? [] : [footEl]));

  // `storage`, `grid`, `barHost` and `restoring` are filled in just below: each reads the state.
  const s = {
    doc, options, text, cellOptions, bus: new WidgetBus<ChartGridEvents>(), links: new GridLinks<Cell>(options.links), offs: [],
    root, tabs, body, barEl, footEl, splits: [], given: false, cells: [], chords: null, sharing: false, active: null,
    rows: 1, cols: 1, rowW: [1], colW: [1], preset: null, theme: options.theme ?? 'dark',
    themeSync: false, compact: false, maxed: false, pointerIn: false, destroyed: false, syncing: false, nextId: 0,
    saveTimer: 0, saveQueued: false, saveRefused: false, held: false, restored: null, drawings: new Map(),
    chromeLayer: null, bar: null, foot: null, saved: null, ready: Promise.resolve(),
  } as Omit<GridState, 'storage' | 'grid' | 'barHost' | 'restoring'> as GridState;
  s.storage = gridStorage(s);
  s.restoring = !s.storage.loaded;
  const grid = s.grid = gridApi(s);
  s.barHost = barHostOf(s);

  paintTheme(s);
  container.appendChild(root);
  listenGrid(s);
  openStoredDesk(s, (payload, docs) => apply(s, payload, docs));

  // ── chrome, over the charts the grid opened with ─────────────────────
  if (footEl !== null) {
    const { tips, overlays } = chrome(s);
    const strip = footEl.appendChild(h(doc, 'div'));
    s.foot = mountBottombar({
      document: doc, locale: options.locale, translate: options.translate, tips, openOverlay: overlays.open,
      status: (message, kind) => s.active?.widget.context.status(message, kind),
    }, strip, { target: () => s.active?.widget ?? null, ranges: options.ranges, now: options.now, onGoTo: () => s.active?.widget.openDateNavigation() });
    s.offs.push(s.bus.on('active', () => s.foot?.refresh()));
  }
  // The desk's saved layouts come with the bar that shows them, and load with it.
  if (barEl !== null) {
    usePart(gridBarPart, module => {
      s.saved = module.attachGridSaved({
        grid, ready: s.ready, workspaces: options.workspaces, layouts: options.layouts,
        context: () => overGrid(s, (s.active as Cell).widget.context), opened: () => s.given,
      });
      s.bar = module.mountGridBar(s.barHost, barEl);
    }, error => report(s, partFailed(text, widgetText(text, 'Chart grid'), error), 'error'), () => !s.destroyed);
  }
  measure(s);
  return grid;
}

/** The grid as a host holds it: each call reads or changes the state. */
function gridApi(s: GridState): ChartGrid {
  const { links } = s;
  const grid: ChartGrid = {
    root: s.root,
    get ready() { return s.ready; },
    get isDestroyed() { return s.destroyed; },
    restored: () => s.restored,
    cells: () => s.cells.slice() as unknown as ChartGridCell[],
    active: () => s.active as unknown as ChartGridCell,
    theme: () => resolveTheme(s.theme).name,
    compact: () => s.compact,
    maximized: () => (s.maxed && s.active !== null ? s.active.id : null),
    linkOptions: () => links.optionsOf(s.active),
    linkGroups: () => describe(s),
    layout: () => ({ rows: s.rows, columns: s.cols, preset: s.preset, rowWeights: s.rowW.slice(), columnWeights: s.colW.slice() }),
    on: (event, cb) => s.bus.on(event, cb),
    setActive: (id, opts) => setActive(s, id, opts),
    setPreset: next => setPreset(s, next),

    maximize(id) {
      const cell = id === undefined ? s.active : s.cells.find(c => c.id === id);
      if (s.destroyed || cell == null || s.cells.length < 2) return false;
      grid.setActive(cell.id);
      setMaxed(s, true);
      return true;
    },

    restore() {
      if (!s.destroyed) setMaxed(s, false);
    },

    swap: (first, second) => swap(s, first, second),

    setLinks(patch) {
      const groups = s.active?.group != null ? [s.active.group] : links.groups;
      for (const group of groups) patchGroup(s, group, patch);
      saveSoon(s);
      paintMarks(s);
      emit(s, 'links', grid.linkOptions());
    },

    setLinkGroup(cellId, groupId) {
      const cell = s.cells.find(c => c.id === cellId);
      const group = groupId === null ? null : links.find(groupId);
      if (s.destroyed || cell === undefined || group === undefined) return false;
      if (group === null) links.leave(cell);
      else links.join(cell, group);
      linksChanged(s);
      return true;
    },

    addLinkGroup(cellId, opts = {}) {
      const cell = s.cells.find(c => c.id === cellId);
      if (s.destroyed || cell === undefined) return null;
      const name = opts.name?.trim();
      const group = links.create({ name: name === undefined || name === '' ? null : name.slice(0, 120), links: opts.links });
      if (group === null) return null;
      links.join(cell, group);
      linksChanged(s);
      return group.id;
    },

    setGroupLinks(groupId, patch) {
      const group = links.find(groupId);
      if (s.destroyed || group === undefined) return false;
      patchGroup(s, group, patch);
      saveSoon(s);
      paintMarks(s);
      emit(s, 'links', grid.linkOptions());
      return true;
    },

    renameLinkGroup(groupId, name) {
      const group = links.find(groupId);
      const clean = name.trim();
      if (s.destroyed || group === undefined || clean === '' || clean.length > 120) return false;
      group.name = clean;
      linksChanged(s);
      return true;
    },

    shareDrawings(cellId) {
      const cell = s.cells.find(c => c.id === cellId);
      const group = cell?.group;
      if (s.destroyed || cell === undefined || group == null || !group.links.options().drawings) return 0;
      return group.drawings.share(cell.widget.chart);
    },

    setTheme(next) {
      s.theme = next;
      paintTheme(s);
      s.themeSync = true;
      try { for (const c of s.cells) c.widget.setTheme(next); }
      finally { s.themeSync = false; }
      saveSoon(s);
      emit(s, 'theme', { theme: resolveTheme(next).name });
    },

    takeScreenshot: () => takeGridScreenshot(s),
    downloadScreenshot: filename => downloadGridScreenshot(s, filename),
    getWorkspace: () => getWorkspace(s),

    applyWorkspace(payload) {
      const result = apply(s, payload, new Map());
      // The newer desk: neither the stored one nor the last saved layout replaces it.
      if (result.applied) s.given = true;
      return result;
    },

    destroy: () => destroyGrid(s),
  };
  return grid;
}

const emit = <K extends ChartGridEventName>(s: GridState, event: K, payload: ChartGridEvents[K]): void => s.bus.emit(event, payload);

/** The grid's own layer, made on first use (see `ChromeLayer`). */
function chrome(s: GridState): ChromeLayer {
  if (s.chromeLayer === null) {
    const el = h(s.doc, 'div', 'oac-widget oac-grid__overlay');
    el.dataset.theme = resolveTheme(s.theme).name;
    s.root.appendChild(el);
    const overlays = createOverlayStack(el, s.doc);
    s.chromeLayer = { el, overlays, tips: createTipController(el, overlays.layer, s.doc) };
  }
  return s.chromeLayer;
}

function paintTheme(s: GridState): void {
  const t = resolveTheme(s.theme);
  s.root.dataset.theme = t.name;
  for (const el of [s.chromeLayer?.el, s.barEl, s.footEl]) if (el != null) el.dataset.theme = t.name;
  applyTokens(s.root, widgetTokens(t.theme, t.name));
}

/**
 * A chart's context over the grid's own layer: a panel the grid's chrome
 * opens for a chart (the Layouts menu, the go-to panel) hangs over the
 * whole grid, next to the control that opened it, where one small chart
 * would clip it. One opened with no anchor hangs from `anchor`.
 */
const overGrid = (s: GridState, ctx: WidgetContext, anchor?: () => HTMLElement | null): WidgetContext => Object.create(ctx, {
  root: { value: chrome(s).el },
  openOverlay: { value: (el: HTMLElement, o: OverlayOptions = {}) => chrome(s).overlays.open(el, { ...o, anchor: o.anchor ?? anchor?.() ?? undefined }) },
}) as WidgetContext;

// ── focus ──────────────────────────────────────────────────────────────
/**
 * Who answers a key. A cell that is not active never does. The active one
 * takes the key outright when the focus is on the page itself and the
 * pointer is over the grid; a focused splitter, tab or bar control keeps
 * its own keys; anything else is the widget's usual pointer-or-focus decision.
 */
function route(s: GridState, cell: Cell): boolean | undefined {
  if (cell !== s.active) return false;
  const focus = s.doc.activeElement;
  if (focus === null || focus === s.doc.body || focus === s.doc.documentElement) return s.pointerIn ? true : undefined;
  return s.root.contains(focus) && !s.cells.some(c => c.element.contains(focus)) ? false : undefined;
}

function syncCompact(s: GridState): void {
  const { doc, tabs } = s;
  for (const c of s.cells) c.element.hidden = solo(s) && c !== s.active;
  for (const split of s.splits) split.hidden = solo(s);
  tabs.hidden = !solo(s) || s.cells.length < 2;
  const said = (c: Cell): string => `${c.widget.symbol()} ${c.widget.interval()}`.trim();
  tabs.replaceChildren(...(tabs.hidden ? [] : s.cells.map((c, i) => {
    // One tab stop for the row; the arrows walk it (see `listenGrid`).
    const tab = h(doc, 'button', 'oac-grid__tab', { type: 'button', role: 'tab', 'aria-selected': String(c === s.active), tabindex: c === s.active ? '0' : '-1' });
    tab.textContent = said(c);
    // Two charts of one symbol and interval are told apart by their place.
    if (s.cells.some(o => o !== c && said(o) === said(c))) tab.setAttribute('aria-label', `${said(c)} (${i + 1})`);
    tab.addEventListener('click', () => s.grid.setActive(c.id, { focus: true }));
    return tab;
  })));
  s.bar?.refresh();
}

function markActive(s: GridState): void {
  for (const c of s.cells) {
    c.element.dataset.active = String(c === s.active);
    if (c === s.active) c.element.setAttribute('aria-current', 'true');
    else c.element.removeAttribute('aria-current');
  }
  syncCompact(s);
}

function measure(s: GridState): void {
  if (s.destroyed) return;
  density(s);
  const width = s.root.getBoundingClientRect().width;
  const limit = s.options.compactWidth ?? 640;
  // Zero means not laid out yet (hidden, or not in the document): no verdict.
  const next = limit > 0 && width > 0 && width <= limit;
  s.root.dataset.compact = String(next);
  if (next === s.compact) return;
  s.compact = next;
  syncCompact(s);
  density(s);
  emit(s, 'layout', { reason: 'compact' });
}

// ── maximize ───────────────────────────────────────────────────────────
function setMaxed(s: GridState, on: boolean): boolean {
  if (on === s.maxed) return false;
  s.maxed = on;
  // Maximizing is looking closer, not further back: the chart keeps the
  // window it showed as it grows, and again as it shrinks back.
  if (s.active !== null) s.active.hold = true;
  s.root.dataset.maximized = String(on);
  syncCompact(s);
  // The cell changed size with no change to the grid's, which is all the size observer watches.
  density(s);
  emit(s, 'layout', { reason: 'maximize' });
  return true;
}
function maximizeBlocked(s: GridState): string | null {
  if (s.cells.length < 2) return widgetText(s.text, 'There is only one chart');
  if (s.compact) return widgetText(s.text, 'The grid shows one chart at a time at this width');
  return null;
}
function toggleMaximize(s: GridState, cell: Cell | null = s.active): void {
  if (cell === null) return;
  if (s.maxed && cell === s.active) s.grid.restore();
  else s.grid.maximize(cell.id);
}

// ── link group marks ───────────────────────────────────────────────────
const groupName = (s: GridState, group: GridGroup<Cell>): string => group.name ?? widgetText(s.text, 'Group {letter}', { letter: group.letter });
const describe = (s: GridState): ChartGridLinkGroup[] => describeGroups(s.links, s.cells, group => groupName(s, group));
const describeOf = (s: GridState, group: GridGroup<Cell> | null): ChartGridLinkGroup | null => describe(s).find(g => g.id === group?.id) ?? null;

/**
 * Each chart's name for assistive technology, and its group mark. The marks
 * appear once the desk has more than the one group every chart starts in,
 * so a desk that never uses groups looks as it always has.
 */
function paintMarks(s: GridState): void {
  const { doc, text } = s;
  const plain = s.links.trivial(s.cells);
  s.cells.forEach((c, i) => {
    const index = i + 1;
    c.element.setAttribute('aria-label', plain ? widgetText(text, 'Chart {index}', { index })
      : c.group === null ? widgetText(text, 'Chart {index}, not linked', { index })
        : widgetText(text, 'Chart {index}, linked in {name}', { index, name: groupName(s, c.group) }));
    if (plain) { c.mark?.remove(); c.mark = null; return; }
    if (c.mark === null) {
      const mark = c.mark = h(doc, 'button', 'oac-grid__mark', { type: 'button', 'aria-haspopup': 'menu' });
      mark.addEventListener('click', () => { s.grid.setActive(c.id); s.barHost.openMenu('link', mark); });
      const head = c.widget.root.querySelector('.oac-topbar');
      if (head !== null) head.prepend(mark);
      else { mark.classList.add('oac-grid__mark--float'); c.element.appendChild(mark); }
    }
    c.mark.replaceChildren(groupMark(doc, describeOf(s, c.group)));
    const title = c.group === null ? widgetText(text, 'Not linked') : widgetText(text, 'Linked in {name}', { name: groupName(s, c.group) });
    c.mark.setAttribute('aria-label', title);
    c.mark.title = title;
    if (c.group === null) delete c.mark.dataset.group;
    else c.mark.dataset.group = c.group.letter;
  });
  s.bar?.refresh();
}

/** After any change to groups or membership: marks, the bar, the event and the saved desk. */
function linksChanged(s: GridState): void {
  s.links.prune(s.cells);
  paintMarks(s);
  saveSoon(s);
  emit(s, 'links', s.grid.linkOptions());
}

function render(s: GridState): void {
  const { doc, body } = s;
  body.style.gridTemplateColumns = tracks(s.colW);
  body.style.gridTemplateRows = tracks(s.rowW);
  for (const split of s.splits.splice(0)) split.remove();
  // The page order is what Tab and a screen reader follow, and what each
  // cell's `Chart {index}` name counts, so it follows the places a swap or
  // an uneven layout gives. Moving a node takes the focus off it; it goes back.
  const focused = doc.activeElement as HTMLElement | null;
  s.cells.forEach((c, i) => {
    c.element.style.gridArea = `${2 * c.row + 1} / ${2 * c.column + 1} / ${2 * (c.row + c.rowSpan)} / ${2 * (c.column + c.columnSpan)}`;
    const at = body.children[i] ?? null;
    if (at !== c.element) body.insertBefore(c.element, at);
  });
  if (focused !== null && focused !== doc.activeElement && s.cells.some(c => c.element.contains(focused))) focused.focus({ preventScroll: true });
  splitters(s, 'column');
  splitters(s, 'row');
  s.root.dataset.single = String(s.cells.length === 1);
  paintMarks(s);
  markActive(s);
  density(s);
}

// ── cells ──────────────────────────────────────────────────────────────
function makeCell(s: GridState, id: string, source: Source, parent: HTMLElement, cellTheme: WidgetThemeName | ChartTheme, docs: ChartDrawings): Cell {
  const { footEl } = s;
  const element = h(s.doc, 'div', 'oac-grid__cell', { role: 'group' });
  element.dataset.paneId = id;
  parent.appendChild(element);
  const { historyPeriod } = source, feed = s.options.feed;
  const cell = { id, element, row: 0, column: 0, rowSpan: 1, columnSpan: 1, offs: [], span: 0, hold: false, historyPeriod, group: null, mark: null, type: '' } as unknown as Cell;
  const chartOptions: WidgetOptions = {
    ...s.cellOptions, theme: cellTheme, symbol: s.restoring ? undefined : source.symbol, exchange: source.exchange, interval: source.interval,
    variant: source.variant, chartType: source.chartType, keyboardRoute: () => route(s, cell),
    feed: typeof feed === 'function' ? feed({ id, historyPeriod }) : feed, drawingStore: cellDrawingStore(id, docs),
  };
  // The bar under the grid carries this chart's Go to, which opens over the grid from that bar.
  if (footEl !== null) GRID_BAR_CHARTS.set(chartOptions, ctx => overGrid(s, ctx, () => footEl.querySelector<HTMLElement>('.oac-bottombar__goto')));
  try {
    cell.widget = createWidget(element, chartOptions);
  } catch (error) {
    element.remove();
    throw error;
  }
  cell.type = cell.widget.chartType();
  // Read live, like the cell's place: a host holding a cell sees it move between groups.
  Object.defineProperty(cell, 'linkGroup', { enumerable: true, get: () => cell.group?.id ?? null });
  return cell;
}

/** A chart with no plot shows an empty window, and has none to give. */
const span = (cell: Cell): number => {
  const range = cell.widget.chart.getVisibleLogicalRange();
  return range.to - range.from;
};
/** The linked window of the chart's group becomes the one this chart shows. */
const keep = (cell: Cell): void => {
  const group = cell.group;
  if (group === null) return;
  const chart = cell.widget.chart, range = chart.getVisibleLogicalRange(), data = chart.dataLayer;
  const from = data.indexToTimeFloat(range.from), to = data.indexToTimeFloat(range.to);
  if (to > from) { group.view = { from, to }; group.keeper = cell; }
};
const forget = (group: GridGroup<Cell> | null): void => {
  if (group !== null) { group.view = null; group.keeper = null; }
};

/**
 * After a resize a linked chart shows the window it showed before. The
 * engine keeps its right edge, so a chart following new bars goes on
 * following them; putting its span back, rather than its bar width, keeps
 * charts of different widths on the same window. A chart that had no plot
 * (hidden behind the compact tabs or a maximized chart) had no window, and
 * takes its group's linked one. Before any linked navigation there is no
 * shared window, and a resize is left to the engine.
 */
function fit(s: GridState, cell: Cell): void {
  const chart = cell.widget.chart, range = chart.getVisibleLogicalRange(), data = chart.dataLayer, had = cell.span;
  const group = cell.group;
  const linked = group !== null && group.links.options().viewport ? group.view : null;
  const hold = cell.hold && had > 0;
  cell.hold = false;
  if (hold || (linked !== null && (had > 0 || cell !== group?.keeper))) {
    s.syncing = true;
    try {
      chart.setVisibleLogicalRange(had > 0 || linked === null ? { from: range.to - had, to: range.to }
        : { from: data.timeToIndexFloat(linked.from), to: data.timeToIndexFloat(linked.to) });
    } finally { s.syncing = false; }
  }
  cell.span = span(cell);
  if (cell === group?.keeper || (linked !== null && had === 0)) keep(cell);
}

/** Wire a built cell into the save, tab and link bookkeeping. Its group is joined separately. */
function join(s: GridState, cell: Cell): void {
  const { widget } = cell;
  const chart = widget.chart;
  followChords(s, cell);
  let settling = false, following = false;
  // A window set by fresh bars, by the grid or by the link group following
  // another chart is not the user's navigation: the chart that was navigated
  // keeps the linked window, whichever of the two hears the pan first.
  const own = (): boolean => settling || s.syncing || following;
  cell.offs.push(chart.on('data:update', () => {
    settling = true;
    queueMicrotask(() => { settling = false; });
    cell.span = span(cell);
    if (cell === cell.group?.keeper) keep(cell);
  }));
  cell.member = linkMember(chart, own, move => {
    following = true;
    try { move(); } finally { following = false; }
  });
  // A new instrument fits its own view, so the keeper's window is no longer
  // the linked one; the other charts still show it.
  const changed = (): void => { if (cell === cell.group?.keeper) forget(cell.group); syncCompact(s); saveSoon(s); };
  const moved = (): void => {
    const mine = !own();
    cell.span = span(cell);
    // A navigation sets the linked window; the keeper's other moves carry it along.
    if (mine || cell === cell.group?.keeper) keep(cell);
    // A window set by data is still written, but a desk held after a refused restore stays held.
    if (mine || !s.held) scheduleSave(s);
  };
  // The widget reports a chart type change as a layout change, from its
  // own menu, an undo or a restore alike; the group hears it once.
  const typed = (): void => {
    const next = widget.chartType();
    if (next === cell.type) return;
    cell.type = next;
    cell.group?.links.setChartType(cell.member, next);
  };
  const soon = (): void => saveSoon(s), later = (): void => scheduleSave(s);
  cell.offs.push(
    widget.on('interval', ({ interval }) => cell.group?.links.setInterval(cell.member, interval)),
    widget.on('theme', ({ chartTheme }) => { if (!s.themeSync) s.grid.setTheme(chartTheme); }),
    widget.on('symbol', changed),
    widget.on('interval', changed),
    widget.on('variant', changed),
    widget.on('layout', typed),
    widget.on('layout', later),
    chart.on('pan', moved),
    chart.on('zoom', moved),
    chart.on('resize', () => fit(s, cell)),
    ...installGridKeys({
      keymap: widget.context.keymap, text: s.text, maximized: () => s.maxed,
      toggleMaximize: () => {
        if (!s.maxed && maximizeBlocked(s) !== null) return false;
        toggleMaximize(s, cell);
        return true;
      },
      restore: () => setMaxed(s, false),
      focus: dir => {
        const next = neighbour(s.cells, cell, dir);
        if (next === undefined) return false;
        // After this key is done: every chart's keymap hears it on the
        // document, and the chart made active now would take it as its own.
        queueMicrotask(() => { if (!s.destroyed) s.grid.setActive(next.id, { focus: true }); });
        return true;
      },
      swap: dir => {
        const next = neighbour(s.cells, cell, dir);
        if (next === undefined || solo(s)) return false;
        s.grid.swap(cell.id, next.id);
        return true;
      },
    }),
  );
  for (const event of ['draw:add', 'draw:remove', 'alert:created', 'alert:removed'] as const) cell.offs.push(chart.on(event, soon));
  // These arrive once per frame while something is dragged.
  for (const event of ['draw:update', 'alert:updated', 'objects:change'] as const) cell.offs.push(chart.on(event, later));
}

function drop(s: GridState, cell: Cell): void {
  if (cell === cell.group?.keeper) forget(cell.group);
  for (const off of cell.offs.splice(0)) off();
  if (cell.member !== undefined) s.links.leave(cell);
  cell.widget.destroy();
  cell.element.remove();
}

function activateFrom(s: GridState, target: EventTarget | null): void {
  const cell = s.cells.find(c => c.element.contains(target as Node | null));
  if (cell !== undefined) s.grid.setActive(cell.id);
}

/** The member the group follows when a switch goes on: the active chart when it is in the group, else its first chart. */
const leaderOf = (s: GridState, group: GridGroup<Cell>): Cell | undefined => (s.active?.group === group ? s.active : s.cells.find(c => c.group === group));
/** Record the leader's instrument, interval and type, so a channel switched on converges on them. */
function lead(s: GridState, group: GridGroup<Cell>, patch: LinkOptions): void {
  const leader = leaderOf(s, group);
  if (leader === undefined) return;
  if (patch.symbol) group.links.setSymbol(leader.member, instrument(leader.widget.symbol(), leader.widget.exchange()));
  if (patch.interval) group.links.setInterval(leader.member, leader.widget.interval());
  if (patch.chartType) group.links.setChartType(leader.member, leader.widget.chartType());
}
function patchGroup(s: GridState, group: GridGroup<Cell>, patch: LinkOptions): void {
  // A window from before viewport linking came on says nothing about the charts now.
  if (patch.viewport && !group.links.options().viewport) forget(group);
  // Recorded before the switch flips, so the group converges on its leader.
  lead(s, group, patch);
  group.links.setOptions(patch);
}

// ── the bar ────────────────────────────────────────────────────────────
/** What the grid bar (grid-bar.ts) and its menus (grid-menus.ts) read from the grid and ask it to do. */
function barHostOf(s: GridState): GridBarHost {
  const { doc, text, options } = s;
  /** A menu on its way: of the bar's menus pressed meanwhile, the last one opens, once, as one press after another would leave it. */
  const menuSlot: PartSlot = { waiting: null };
  const barHost: GridBarHost = {
    doc, text,
    get overlays() { return chrome(s).overlays; },
    get tips() { return chrome(s).tips; },
    layouts: (options.presets ?? (Object.keys(CHART_GRID_LAYOUTS) as ChartGridLayoutId[])).filter(isChartGridLayout),
    layout: () => s.preset,
    setLayout: id => s.grid.setPreset(id),
    maximized: () => s.maxed,
    maximizeBlocked: () => maximizeBlocked(s),
    toggleMaximize: () => toggleMaximize(s),
    links: {
      groups: () => describe(s),
      current: () => describeOf(s, s.active?.group ?? null),
      setGroup: id => { if (s.active !== null) s.grid.setLinkGroup(s.active.id, id); },
      newGroup: () => { if (s.active !== null) s.grid.addLinkGroup(s.active.id); },
      rename: (id, name) => s.grid.renameLinkGroup(id, name),
      setChannel: (channel: LinkChannel | 'nearest', on) => {
        const group = s.active?.group;
        if (group == null) return;
        s.grid.setGroupLinks(group.id, channel === 'nearest' ? { whenMissing: on ? 'nearest' : 'hide' } : { [channel]: on });
      },
      share: () => {
        const count = s.active === null ? 0 : s.grid.shareDrawings(s.active.id);
        report(s, count > 0 ? widgetText(text, count === 1 ? 'Shared {count} drawing' : 'Shared {count} drawings', { count }) : widgetText(text, 'No drawing here can be shared'));
        return count;
      },
    },
    capture: { blocked: () => captureBlocked(s), download: () => downloadAll(s), copy: () => copyAll(s), canCopy: canCopyImage },
    get saved() { return s.saved ?? undefined; },
    openMenu: (which, anchor) => usePart(gridMenusPart, module => {
      if (which === 'layouts') module.openLayoutPicker(barHost, anchor);
      else if (which === 'link') module.openLinkMenu(barHost, anchor);
      else module.openCaptureMenu(barHost, anchor);
    }, error => report(s, partFailed(text, widgetText(text, which === 'layouts' ? 'Arrange charts' : which === 'link' ? 'Linking' : 'Capture every chart'), error), 'error'),
    () => !s.destroyed && anchor.isConnected, { slot: menuSlot, doc, from: anchor }),
  };
  return barHost;
}

// ── the grid's calls ───────────────────────────────────────────────────
function setActive(s: GridState, id: string, opts: { focus?: boolean } = {}): boolean {
  const cell = s.cells.find(c => c.id === id);
  if (cell === undefined || s.destroyed) return false;
  const changed = cell !== s.active;
  const before = s.active?.group ?? null;
  s.active = cell;
  markActive(s);
  if (opts.focus) cell.widget.root.querySelector<HTMLElement>('.oac-chart')?.focus({ preventScroll: true });
  if (changed) {
    // Focus is no edit, so it never ends the hold on a refused desk.
    if (!s.held) saveSoon(s);
    emit(s, 'active', { id });
    if (before !== cell.group) emit(s, 'links', s.grid.linkOptions());
  }
  return true;
}

function setPreset(s: GridState, next: ChartGridLayoutId): void {
  if (!isChartGridLayout(next)) throw new Error(`openalgo-charts grid: "${String(next)}" is not a preset or layout`);
  if (s.destroyed) return;
  const { links } = s;
  const spec = CHART_GRID_LAYOUTS[next];
  const count = spec.slots.length;
  const kept = s.cells.slice(0, count);
  const focus = focusSlot(spec);
  // The large slot is the active chart's, so it stays even when it sits
  // past the charts that fit; the last of those makes room for it.
  if (focus >= 0 && s.active !== null && !kept.includes(s.active)) kept.splice(count - 1, 1, s.active);
  const before = s.active;
  // Read now: dropping a chart takes it out of its group.
  const group = before === null ? links.groups[0] ?? links.create() : before.group;
  const from = s.active?.widget;
  const source: Source = from === undefined ? s.options
    : { symbol: from.symbol(), exchange: from.exchange(), interval: from.interval(), variant: from.variant(), chartType: from.chartType(), historyPeriod: s.active?.historyPeriod };
  const made: Cell[] = [];
  try {
    while (kept.length + made.length < count) {
      let id: string;
      do id = `p${s.nextId++}`; while (s.cells.some(cell => cell.id === id));
      made.push(makeCell(s, id, source, s.body, s.theme, s.drawings));
    }
  } catch (error) {
    made.forEach(cell => drop(s, cell));
    throw error;
  }
  s.maxed = false;
  s.root.dataset.maximized = 'false';
  for (const cell of s.cells.filter(c => !kept.includes(c))) { drop(s, cell); s.drawings.delete(cell.id); }
  if (s.active === null || !kept.includes(s.active)) s.active = kept[0] ?? made[0]!; // between them they hold every slot, and a layout has one
  // In an uneven layout the chart being worked on takes the large slot;
  // the others keep their reading order around it.
  const order = [...kept, ...made];
  if (focus >= 0) { order.splice(order.indexOf(s.active), 1); order.splice(focus, 0, s.active); }
  order.forEach((cell, i) => Object.assign(cell, spec.slots[i]));
  s.cells = order;
  made.forEach(cell => join(s, cell));
  // A new chart copies the active chart's instrument and joins its group.
  if (group !== null) for (const cell of made) links.join(cell, group);
  links.prune(s.cells);
  s.rows = spec.rows; s.cols = spec.columns; s.rowW = spec.rowWeights.slice(); s.colW = spec.columnWeights.slice(); s.preset = next;
  render(s);
  saveSoon(s);
  emit(s, 'layout', { reason: 'preset' });
  if (s.active !== before) emit(s, 'active', { id: s.active.id });
}

function swap(s: GridState, first: string, second: string): boolean {
  const a = s.cells.find(c => c.id === first), b = s.cells.find(c => c.id === second);
  if (s.destroyed || a === undefined || b === undefined || a === b) return false;
  const place = (c: Cell): Pick<Cell, 'row' | 'column' | 'rowSpan' | 'columnSpan'> => ({ row: c.row, column: c.column, rowSpan: c.rowSpan, columnSpan: c.columnSpan });
  const [pa, pb] = [place(a), place(b)];
  Object.assign(a, pb);
  Object.assign(b, pa);
  s.cells.sort((x, y) => x.row - y.row || x.column - y.column);
  render(s);
  saveSoon(s);
  emit(s, 'layout', { reason: 'swap' });
  return true;
}

function getWorkspace(s: GridState): WorkspacePayload {
  const plain = s.links.trivial(s.cells);
  const payload: WorkspacePayload = {
    layout: {
      rows: s.rows, columns: s.cols,
      slots: s.cells.map(c => ({ paneId: c.id, row: c.row, column: c.column, rowSpan: c.rowSpan, columnSpan: c.columnSpan })),
      ...(s.preset === null ? {} : { preset: s.preset }), rowWeights: s.rowW.slice(), columnWeights: s.colW.slice(),
    },
    panes: s.cells.map((c): WorkspacePane => {
      const w = c.widget.getState();
      return { ...widgetPane(c.id, w, w.chart as WorkspaceChartState), historyPeriod: c.historyPeriod,
        ...(plain || c.group === null ? {} : { linkGroup: c.group.id }) };
    }),
    activePaneId: (s.active as Cell).id,
    sync: s.links.sync(s.cells, group => groupName(s, group)),
  };
  // Chart states carry absent optional fields; the portable form is plain JSON.
  return JSON.parse(JSON.stringify(payload)) as WorkspacePayload;
}

function destroyGrid(s: GridState): void {
  if (s.destroyed) return;
  saveNow(s);
  // Sends an asynchronous store's writes, and stops following other tabs' changes to it.
  void s.storage.flush();
  s.storage.close();
  s.destroyed = true;
  for (const off of s.offs.splice(0)) off();
  s.saved?.destroy();
  // Before the overlays: the bar closes its zone menu there.
  s.foot?.destroy();
  s.chromeLayer?.overlays.destroy();
  s.chromeLayer?.tips.destroy();
  s.bar?.destroy();
  s.cells.splice(0).forEach(cell => drop(s, cell));
  s.links.destroy();
  s.root.remove();
  s.bus.clear();
}

/**
 * Apply a workspace whose charts start from `docs` for the instruments
 * they are not showing: the saved ones when the grid restores its own
 * desk, none for a desk the host hands over, whose payload carries only
 * the drawings each chart shows.
 */
function apply(s: GridState, payload: WorkspacePayload, docs: ChartDrawings): ChartGridApplyReport {
  if (s.destroyed) return { applied: false, reason: 'the grid is destroyed' };
  const reason = checkWorkspace(payload);
  if (reason !== '') return { applied: false, reason };
  const { links } = s;
  const saved = payload.panes.find(p => p.id === payload.activePaneId)?.settings?.[THEME_SETTING];
  const nextTheme = saved === 'dark' || saved === 'light' ? saved : s.theme;
  const staging = s.doc.createElement('div');
  const made: Cell[] = [];
  try {
    for (const slot of payload.layout.slots.slice().sort((a, b) => a.row - b.row || a.column - b.column)) {
      const pane = payload.panes.find(p => p.id === slot.paneId) as WorkspacePane;
      const cell = makeCell(s, pane.id, pane, staging, nextTheme, docs);
      made.push(cell);
      Object.assign(cell, { row: slot.row, column: slot.column, rowSpan: slot.rowSpan ?? 1, columnSpan: slot.columnSpan ?? 1 });
      // The grid gives every chart the one theme it applies below.
      const report = restorePane(cell.widget, pane, false);
      if (!report.applied) throw new Error(`${pane.id}: ${report.reason ?? 'the chart state could not be restored'}`);
      cell.type = cell.widget.chartType();
    }
  } catch (error) {
    made.reverse().forEach(cell => drop(s, cell));
    return { applied: false, reason: error instanceof Error ? error.message : String(error) };
  }
  s.maxed = false;
  s.root.dataset.maximized = 'false';
  s.cells.forEach(cell => drop(s, cell));
  links.destroy();
  s.cells = made;
  s.drawings = docs;
  const { layout, sync } = payload;
  s.rows = layout.rows; s.cols = layout.columns;
  s.rowW = layout.rowWeights?.slice() ?? ones(s.rows);
  s.colW = layout.columnWeights?.slice() ?? ones(s.cols);
  s.preset = layout.preset ?? null;
  s.theme = nextTheme;
  paintTheme(s);
  s.active = made.find(c => c.id === payload.activePaneId) as Cell;
  made.forEach(cell => join(s, cell));
  // Every channel off while the charts join, so joining cannot overwrite a
  // saved chart; the checks above make the final switch-on agree already.
  const groups = sync.groups === undefined ? [{ id: undefined, name: null, channels: channelsOf(sync), panes: payload.panes }]
    : sync.groups.map(g => ({ id: g.id, name: g.name, channels: channelsOf(g), panes: payload.panes.filter(p => p.linkGroup === g.id) }));
  for (const entry of groups) {
    const group = links.create({ id: entry.id, name: entry.name, links: ALL_OFF }) as GridGroup<Cell>;
    // A group is saved under the name it shows, because the schema needs one.
    // Read back as that same name it would count as named: a desk back to
    // one group would keep its marks and keep writing groups. It stays
    // unnamed, and shows the name in whatever language opens it.
    if (group.name === widgetText(s.text, 'Group {letter}', { letter: group.letter })) group.name = null;
    for (const pane of entry.panes) links.join(made.find(c => c.id === pane.id) as Cell, group);
    // Record the leader's choices first, then switch on: the group converges on what it just heard.
    lead(s, group, { symbol: true, interval: true, chartType: true });
    group.links.setOptions(entry.channels);
  }
  links.prune(s.cells);
  render(s);
  saveSoon(s);
  emit(s, 'layout', { reason: 'workspace' });
  emit(s, 'active', { id: s.active.id });
  emit(s, 'links', s.grid.linkOptions());
  return { applied: true };
}

// ── listeners ──────────────────────────────────────────────────────────
/** The grid's own listeners, each undone through `offs` when the grid is destroyed. */
function listenGrid(s: GridState): void {
  const { doc, root, tabs, offs } = s;
  const listen = (target: EventTarget, type: string, fn: (e: Event) => void, capture = false): void => {
    target.addEventListener(type, fn, capture);
    offs.push(() => target.removeEventListener(type, fn, capture));
  };
  // The tabs follow the arrows, Home and End, each one showing its chart as the focus lands.
  listen(tabs, 'keydown', e => {
    const list = Array.from(tabs.children);
    const to = rovingIndex((e as KeyboardEvent).key, list.indexOf(doc.activeElement as Element), list.length, ['ArrowLeft', 'ArrowRight']);
    const cell = s.cells[to];
    if (to < 0 || cell === undefined) return;
    // Claimed here, as a splitter claims its arrows, so no chart pans with it.
    e.preventDefault();
    e.stopPropagation();
    s.grid.setActive(cell.id);
    (tabs.children[to] as HTMLElement | undefined)?.focus();
  });
  // Capture, so a chart that stops its own pointer events still activates.
  listen(root, 'pointerdown', e => activateFrom(s, e.target), true);
  listen(root, 'focusin', e => activateFrom(s, e.target));
  listen(root, 'pointerenter', () => { s.pointerIn = true; });
  listen(root, 'pointerleave', () => { s.pointerIn = false; });
  offs.push(installHeaderDrag({
    doc, body: s.body, root,
    cells: () => s.cells,
    enabled: () => !solo(s) && s.cells.length > 1,
    swap: (a, b) => s.grid.swap(a.id, b.id),
    toggleMaximize: cell => { if (s.cells.length > 1 && !s.compact) { s.grid.setActive(cell.id); toggleMaximize(s, cell); } },
  }));
  const win = doc.defaultView as (Window & typeof globalThis) | null;
  const Observer = win?.ResizeObserver;
  if (Observer !== undefined) {
    const observer = new Observer(() => measure(s));
    observer.observe(root);
    offs.push(() => observer.disconnect());
  }
  if (win != null && typeof win.addEventListener === 'function') {
    if (Observer === undefined) listen(win, 'resize', () => measure(s));
    listen(win, 'pagehide', () => leaving(s, false));
  }
  // Hiding is the last moment a page is sure to see; unload may never come.
  listen(doc, 'visibilitychange', () => { if (doc.visibilityState === 'hidden') leaving(s, true); });
}
