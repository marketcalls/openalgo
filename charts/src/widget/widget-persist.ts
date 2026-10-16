/**
 * The shell's persisted state: the saved layout read before the shell is
 * built and applied once it is, each instrument's drawings kept beside it,
 * the debounced write after a change and the flush when the page goes away,
 * and `restoreState` applying a state a host kept.
 *
 * Over an asynchronous store (IndexedDB, the default) nothing saved can be
 * read while the shell is built. The shell is built on the defaults and kept
 * out of sight, its first load is held, and `restoreWhenLoaded` applies the
 * saved facts, drawings and layout once the store has answered, then starts
 * the load. Until then no save is written, so a slow store cannot have the
 * defaults written over the layout it has not returned yet, and the drawings
 * follow no instrument, so none is read from a copy not filled yet. A choice
 * the user or the host made in the meantime (a symbol, an interval, a whole
 * `restoreState`) is newer than the stored one and wins over it.
 *
 * Its own module so persistence can grow (an asynchronous store, a layouts
 * catalog) while widget.ts stays under its line cap. The shell calls each
 * function with itself as `this`, typed `PersistHost`, for the reasons
 * widget-keys.ts gives: a member the shell renames or retypes fails to
 * compile here, and the moved code reads and compresses as it did in
 * widget.ts. The tier entry exports none of it: the names hosts import
 * (`stripView` and the storage constants) stay declared in widget.ts.
 * `_scheduleSave` and `_saveNow` stay on the shell as one-line delegates,
 * because every change the shell follows schedules a save and `destroy`
 * writes the last one, and the timer's callback here calls back through them.
 */
import {
  dataVariantKey, isKnownInterval, normalizeDataVariant,
  type DataVariant, type RestoreReport,
} from 'openalgo-charts';
import {
  InstrumentDrawings, instrumentDrawingsKey, memoryDrawingStore, migrateUnscopedDrawings,
  type DrawingDocumentStore, type DrawingInstrument,
} from 'openalgo-charts/draw';
import { WidgetBus, type WidgetBusEvents, type WidgetStorage, type WidgetStorageError } from './context';
import { isChartTypeChoice } from './chart-type-choice';
import { errorText, widgetText } from './localization';
import { sanitizePanelDockState } from './panel-dock';
import { RAIL_PREFS_KEY, type RailPrefs } from './rail';
import type { WidgetThemeName } from './tokens';
import { restoreKeymap, type KeysHost } from './widget-keys';
import type {
  WidgetChartState, WidgetImpl, WidgetRestoreReport, WidgetState,
  DRAWINGS_KEY_PREFIX as DrawingsKeyPrefix, SAVE_DEBOUNCE_MS as SaveDebounceMs, STATE_KEY as StateKey, WIDGET_STATE_VERSION as StateVersion,
} from './widget';
import { isRecord } from '../helpers/validate';

// widget.ts declares these for hosts and imports this module, so reading them
// from there at run time would be an import cycle. Each copy is typed as its
// public constant's literal, so the two cannot drift apart without a compile
// error.
const SAVE_DEBOUNCE_MS: typeof SaveDebounceMs = 250;
const STATE_KEY: typeof StateKey = 'state';
const DRAWINGS_KEY_PREFIX: typeof DrawingsKeyPrefix = 'drawings:';
const WIDGET_STATE_VERSION: typeof StateVersion = 1;

/** The slice of the shell the persistence reads and drives. */
export interface PersistHost {
  readonly chart: WidgetImpl['chart'];
  readonly draw: WidgetImpl['draw'];
  readonly instrumentDrawings: WidgetImpl['instrumentDrawings'];
  readonly context: WidgetImpl['context'];
  readonly _doc: WidgetImpl['_doc'];
  readonly _opts: WidgetImpl['_opts'];
  readonly _bus: WidgetImpl['_bus'];
  readonly _storage: WidgetImpl['_storage'];
  readonly _toasts: WidgetImpl['_toasts'];
  readonly _series: WidgetImpl['_series'];
  readonly _rail: WidgetImpl['_rail'];
  readonly _topbar: WidgetImpl['_topbar'];
  readonly _statusline: WidgetImpl['_statusline'];
  readonly _mobile: WidgetImpl['_mobile'];
  readonly _dock: WidgetImpl['_dock'];
  readonly _destroyed: WidgetImpl['_destroyed'];
  readonly _cleanups: WidgetImpl['_cleanups'];
  _symbol: WidgetImpl['_symbol'];
  _exchange: WidgetImpl['_exchange'];
  _interval: WidgetImpl['_interval'];
  _variant: WidgetImpl['_variant'];
  _keepView: WidgetImpl['_keepView'];
  _pendingView: WidgetImpl['_pendingView'];
  _saveTimer: WidgetImpl['_saveTimer'];
  readonly getState: WidgetImpl['getState'];
  readonly chartType: WidgetImpl['chartType'];
  readonly setTheme: WidgetImpl['setTheme'];
  readonly setChartType: WidgetImpl['setChartType'];
  readonly _selectChartType: WidgetImpl['_selectChartType'];
  readonly reload: WidgetImpl['reload'];
  readonly _cancelNavigation: WidgetImpl['_cancelNavigation'];
  readonly _publishDataContext: WidgetImpl['_publishDataContext'];
  readonly _scheduleSave: WidgetImpl['_scheduleSave'];
  readonly _saveNow: WidgetImpl['_saveNow'];
  readonly root: WidgetImpl['root'];
  readonly history: WidgetImpl['history'];
  readonly dataController: WidgetImpl['dataController'];
  readonly _themeName: WidgetImpl['_themeName'];
  _restoring: WidgetImpl['_restoring'];
  _holdDrawings: WidgetImpl['_holdDrawings'];
  _saveWanted: WidgetImpl['_saveWanted'];
  _stateGiven: WidgetImpl['_stateGiven'];
}

/** The facts the shell was built on before its store answered, to tell a later change from a default. */
interface StartFacts {
  symbol: string;
  exchange: string;
  interval: string;
  variant: Readonly<DataVariant> | undefined;
  chartType: string;
  theme: WidgetThemeName;
}

/**
 * A stored variant: undefined for the default series, null for one this build
 * cannot read. That one falls back to the default series rather than failing
 * the widget, and its saved view is dropped, since it was taken on other bars.
 */
function savedVariant(value: unknown): Readonly<DataVariant> | undefined | null {
  try { return normalizeDataVariant(value); } catch { return null; }
}

/**
 * The body of the public `stripView`, which widget.ts declares, documents
 * and delegates here, so a saved layout can be read without importing
 * widget.ts at run time.
 */
export function stripView(state: WidgetChartState): WidgetChartState {
  const out = { ...state } as Record<string, unknown>;
  delete out.viewport;
  delete out.barSpacing;
  const clearScaleView = (value: unknown): unknown => {
    if (!isRecord(value)) return value;
    const scale = { ...value, autoScale: true } as Record<string, unknown>;
    delete scale.range;
    delete scale.ratioLock;
    return scale;
  };
  if (Array.isArray(out.panes)) {
    out.panes = (out.panes as unknown[]).map((pane) => {
      if (!isRecord(pane)) return pane;
      const next = { ...pane };
      if (isRecord(pane.priceScale)) next.priceScale = clearScaleView(pane.priceScale);
      if (isRecord(pane.scales)) next.scales = Object.fromEntries(
        Object.entries(pane.scales).map(([id, scale]) => [id, clearScaleView(scale)]),
      );
      return next;
    });
  }
  return out as unknown as WidgetChartState;
}

/**
 * Through 2.6.2 the chart state carried every navigation option, so each
 * layout saved then says mousePan: 'both' whether or not anyone chose it.
 * Restored, it switched every drag back to moving price and the pane to
 * manual scaling. An unstamped state therefore leaves the drag to the
 * options the widget was built with: its own default or the host's.
 */
function withoutRecordedDrag(savedBy: unknown, chart: WidgetChartState): WidgetChartState {
  if (savedBy !== undefined || chart.navigation?.mousePan !== 'both') return chart;
  const { mousePan: _recorded, ...navigation } = chart.navigation;
  return { ...chart, navigation };
}

/**
 * The saved layout, onto the dataset it belongs to: its view only on the
 * instrument (symbol and exchange), interval and variant it was saved on,
 * then its rail preferences and panels. Runs once the chrome is built.
 */
export function applySavedLayout(this: PersistHost, saved: WidgetState | null): void {
  if (saved?.chart !== undefined) {
    const same = saved.symbol === this._symbol && saved.exchange === this._exchange && saved.interval === this._interval
      && dataVariantKey(saved.variant) === dataVariantKey(this._variant);
    const recorded = withoutRecordedDrag(saved.savedBy, saved.chart);
    let layout = same ? recorded : stripView(recorded);
    // The layout's own drawings were attached to its instrument by
    // `scopeDrawings`; the chart keeps the ones the current instrument has,
    // already on it. A layout that names no instrument has nowhere else to
    // keep them, so they land as they always did and go to the first
    // instrument charted.
    if (this.instrumentDrawings !== null && savedKey(saved) !== null) layout = { ...layout, drawings: this.draw.toJSON() };
    const report = this.chart.restoreState(layout);
    if (report.applied) {
      restorePrimaryStyle.call(this, saved.chart);
      this._keepView = same;
      this._pendingView = same ? saved.chart.viewport ?? null : null;
    } else {
      this._toasts.toast(widgetText(this.context, 'The saved layout could not be restored: {error}', { error: report.reason ?? 'unknown reason' }), 'error');
    }
  }
  if (saved?.rail && this._rail !== null) this._rail.restorePrefs(saved.rail);
  if (saved?.panels) this._dock?.restore(saved.panels);
}

/**
 * Drawings per instrument, from the store the host named or the one the
 * persisted layout sits in. A layout saved before drawings were per
 * instrument holds the drawings of the instrument it was saved on, which
 * are attached to that instrument here, so opening on another symbol
 * neither shows them there nor loses them.
 */
export function scopeDrawings(this: PersistHost, saved: WidgetState | null): InstrumentDrawings {
  const storage = this._storage;
  const store: DrawingDocumentStore = this._opts.drawingStore ?? (storage.enabled ? storedDrawings(storage) : memoryDrawingStore());
  if (saved?.chart?.drawings !== undefined) migrateUnscopedDrawings(store, savedKey(saved), saved.chart.drawings);
  return new InstrumentDrawings(this.chart, this.draw, {
    store,
    // While the store has not answered, no instrument: nothing is read from
    // a copy not filled yet, and nothing written over what it holds.
    ...(this._holdDrawings ? { key: (instrument: DrawingInstrument) => (this._holdDrawings ? null : instrumentDrawingsKey(instrument)) } : {}),
    // Reported on the status line, as a failed layout write is: the drawings
    // stay in memory for the session and the next change tries again. The
    // shell may still be under construction, so this does what the
    // context's own status call does rather than going through it.
    onError: ({ operation, key }) => {
      if (operation === 'read' || this._destroyed) return;
      const text = widgetText(this._opts, 'The drawings for {instrument} could not be saved', { instrument: decodeURIComponent(key) });
      this._statusline?.setMessage(text, 'error');
      this._bus.emit('status', { text, kind: 'error' });
    },
  });
}

/** Each instrument's drawings beside the layout, in the widget's own storage. */
function storedDrawings(storage: WidgetStorage): DrawingDocumentStore {
  return {
    get: key => storage.get(DRAWINGS_KEY_PREFIX + key),
    set: (key, document) => storage.set(DRAWINGS_KEY_PREFIX + key, document),
    remove: key => storage.remove(DRAWINGS_KEY_PREFIX + key),
  };
}

/** Let the drawings follow the instrument the chart shows, reading its own from the store. */
function releaseDrawings(this: PersistHost): void {
  if (!this._holdDrawings) return;
  this._holdDrawings = false;
  this.instrumentDrawings?.setInstrument({ symbol: this._symbol, exchange: this._exchange });
}

/**
 * A state the host restores before the store has answered is the newer
 * layout: the stored one is not applied over it, and the drawings follow the
 * instruments from now on, so the state's own reach theirs.
 */
function takeGivenState(this: PersistHost): void {
  if (!this._restoring) return;
  this._stateGiven = true;
  releaseDrawings.call(this);
}

/** The key the drawings of a persisted layout belong under, or null when it names no instrument. */
function savedKey(saved: WidgetState): string | null {
  return instrumentDrawingsKey({ symbol: saved.symbol.toUpperCase(), exchange: saved.exchange });
}

/**
 * The saved style of the series on screen. A chart restore never touches
 * series, which belong to the host, so the colours a layout was saved with
 * (from the settings or a chart type's own dialog) are the widget's to put
 * back. Only the entry saved for the same chart type applies: a style written
 * for point and figure means nothing to candles.
 */
function restorePrimaryStyle(this: PersistHost, state: WidgetChartState): void {
  const type = this.chart.seriesTransform(this._series)?.type ?? this.chart.seriesType(this._series);
  const entry = (state.series ?? []).find(item => item !== null && (item.transform?.type ?? item.type) === type);
  if (entry?.style !== undefined && Object.keys(entry.style).length > 0) this._series.applyOptions(entry.style);
}

/** What `restoreState` applies, inside the history's `ignore`. */
export function restoreWidgetState(this: PersistHost, state: unknown): WidgetRestoreReport {
  if (!isRecord(state)) return { applied: false, reason: 'not a widget state object' };
  if (state.version !== undefined && state.version !== WIDGET_STATE_VERSION) {
    return { applied: false, reason: `widget state version ${String(state.version)} is not ${WIDGET_STATE_VERSION}` };
  }
  // Read before anything is applied: a variant this build cannot name would
  // be served as some other series, so the whole state is refused. A state
  // that names none was saved on the feed's default series (getState leaves
  // the default out, and nothing saved before variants could name another),
  // so it restores onto the default whatever this widget shows now. Keeping
  // the current variant instead would land its view on bars it never saw.
  let variant: Readonly<DataVariant> | undefined;
  try { variant = normalizeDataVariant(state.variant); }
  catch (error) { return { applied: false, reason: error instanceof Error ? error.message : 'invalid data variant' }; }
  if (state.theme === 'dark' || state.theme === 'light') this.setTheme(state.theme);
  if (isChartTypeChoice(state.chartType)) this._selectChartType(state.chartType, isRecord(state.chart) ? state.chart : undefined);
  if (state.rail !== undefined && this._rail !== null) this._rail.restorePrefs(state.rail);
  if (state.panels !== undefined) this._dock?.restore(state.panels);
  const symbol = typeof state.symbol === 'string' ? state.symbol.toUpperCase() : this._symbol;
  const exchange = typeof state.exchange === 'string' ? state.exchange : this._exchange;
  const interval = typeof state.interval === 'string' && isKnownInterval(state.interval) ? state.interval : this._interval;
  const sameVariant = dataVariantKey(variant) === dataVariantKey(this._variant);
  const same = symbol === this._symbol && exchange === this._exchange && interval === this._interval && sameVariant;
  let chart: RestoreReport | undefined;
  if (isRecord(state.chart)) {
    let doc = withoutRecordedDrag(state.savedBy, state.chart as unknown as WidgetChartState);
    const scoped = this.instrumentDrawings;
    // A layout for another instrument brings that instrument's drawings.
    // They wait in its store while the chart restore keeps the ones on
    // screen, which are this instrument's until the switch below, so the
    // alerts the layout restores are judged against their own drawings.
    const moving = scoped !== null && (symbol !== this._symbol || exchange !== this._exchange)
      && instrumentDrawingsKey({ symbol, exchange }) !== null;
    const incoming = doc.drawings;
    if (moving) doc = { ...doc, drawings: this.draw.toJSON() };
    chart = this.chart.restoreState(same ? doc : stripView(doc));
    if (!chart.applied) return { applied: false, reason: chart.reason, chart };
    restorePrimaryStyle.call(this, doc);
    takeGivenState.call(this);
    if (moving && scoped !== null) scoped.setDocument({ symbol, exchange }, incoming ?? []);
    this._keepView = same;
    this._pendingView = same ? doc.viewport ?? null : null;
  }
  takeGivenState.call(this);
  if (!same) {
    this._cancelNavigation();
    if (interval !== this._interval) {
      this._interval = interval;
      this._bus.emit('interval', { interval });
    }
    if (symbol !== this._symbol || exchange !== this._exchange) {
      this._symbol = symbol;
      this._exchange = exchange;
      // The widget's bus only, where setSymbol and a late store load also
      // announce on the chart's. A link group and the chart grid follow the
      // chart's 'symbol' and pass it to every chart linked to this one; a
      // restore is a saved layout being applied (the grid applies each cell
      // this way), which that broadcast would overwrite chart by chart.
      this._bus.emit('symbol', { symbol, exchange });
    }
    if (!sameVariant) {
      this._variant = variant;
      this._bus.emit('variant', { variant });
    }
    this._statusline?.setSymbol(this._symbol, this._exchange, this._interval);
    this._topbar?.refresh();
    this._mobile?.refresh();
    if (this._opts.feed) void this.reload();
    else {
      this._series.setData([]);
      this._publishDataContext();
    }
  }
  this._rail?.refresh();
  this._statusline?.refresh();
  this._bus.emit('layout', { reason: 'restore', chartType: this.chartType() });
  this._scheduleSave();
  return chart === undefined ? { applied: true } : { applied: true, chart };
}

/** The stored layout, checked field by field, or null when nothing this build can read is stored. */
export function readSaved(this: PersistHost): WidgetState | null {
  const raw = this._storage.get(STATE_KEY);
  if (!isRecord(raw) || raw.version !== WIDGET_STATE_VERSION) return null;
  const variant = savedVariant(raw.variant);
  const chart = isRecord(raw.chart) ? (raw.chart as unknown as WidgetChartState) : undefined;
  const out: WidgetState = {
    version: WIDGET_STATE_VERSION,
    symbol: typeof raw.symbol === 'string' ? raw.symbol : '',
    exchange: typeof raw.exchange === 'string' ? raw.exchange : '',
    interval: typeof raw.interval === 'string' && raw.interval !== '' ? raw.interval : '1d',
    chartType: typeof raw.chartType === 'string' ? raw.chartType : 'candlestick',
    theme: raw.theme === 'light' ? 'light' : 'dark',
    ...(variant ? { variant } : {}),
    chart: (chart && variant === null ? stripView(chart) : chart) as WidgetChartState,
    rail: isRecord(raw.rail) ? (raw.rail as unknown as RailPrefs) : null,
    panels: sanitizePanelDockState(raw.panels),
    ...(typeof raw.savedBy === 'string' ? { savedBy: raw.savedBy } : {}),
  };
  return out;
}

/** One write, a debounce after the last change, because drags fire per frame. */
export function scheduleSave(this: PersistHost): void {
  if (!this._storage.enabled || this._destroyed) return;
  if (this._restoring) { this._saveWanted = true; return; }
  if (this._saveTimer !== 0) clearTimeout(this._saveTimer);
  this._saveTimer = setTimeout(() => { this._saveTimer = 0; this._saveNow(); }, SAVE_DEBOUNCE_MS);
}

/** The write itself, now: a failure is reported on the status line, never thrown. */
export function saveNow(this: PersistHost): void {
  if (!this._storage.enabled || this._destroyed) return;
  if (this._restoring) { this._saveWanted = true; return; }
  if (this._saveTimer !== 0) { clearTimeout(this._saveTimer); this._saveTimer = 0; }
  try {
    if (!this._storage.set(STATE_KEY, this.getState())) this.context.status(widgetText(this.context, 'The chart layout could not be saved'), 'error');
  } catch (error) {
    this.context.status(widgetText(this.context, 'The chart layout could not be saved: {error}', { error: error instanceof Error ? error.message : 'invalid state' }), 'error');
  }
}

/** Writes a pending save when the page goes away; the listener goes with the shell. */
export function flushOnPageHide(this: PersistHost): void {
  const win = this._doc.defaultView;
  const later = !this._storage.loaded;
  if (win !== null && win !== undefined && typeof win.addEventListener === 'function') {
    // A debounced save still pending when the tab closes is the last quarter
    // second of the user's work; pagehide is the last synchronous moment.
    // An asynchronous store is sent everything now as well, which journals
    // what may not land before the page is gone.
    const flush = later ? (): void => { this._saveNow(); void this._storage.flush(); } : (): void => this._saveNow();
    win.addEventListener('pagehide', flush);
    this._cleanups.push(() => win.removeEventListener('pagehide', flush));
  }
  if (later) {
    // A phone closes a page it has hidden without a pagehide, so hiding is
    // the last moment such a page is sure to see. Only a save still pending
    // is written: a tab the user merely leaves for another on the same
    // namespace would otherwise write its older layout over the one saved
    // there, at every switch.
    const doc = this._doc;
    const hidden = (): void => {
      if (doc.visibilityState !== 'hidden') return;
      if (this._saveTimer !== 0) this._saveNow();
      void this._storage.flush();
    };
    doc.addEventListener('visibilitychange', hidden);
    this._cleanups.push(() => doc.removeEventListener('visibilitychange', hidden));
  }
}

/**
 * With an asynchronous store: keep the shell out of sight, read the store,
 * then apply what it holds and start the load that was held. The promise is
 * the widget's `ready`, and never rejects.
 */
export function restoreWhenLoaded(this: PersistHost): Promise<void> {
  const start: StartFacts = {
    symbol: this._symbol, exchange: this._exchange, interval: this._interval, variant: this._variant,
    chartType: this.chartType(), theme: this._themeName,
  };
  // Hidden rather than removed, so the chrome keeps its measured size: the
  // defaults would otherwise show for a moment before the saved layout.
  this.root.style.visibility = 'hidden';
  return this._storage.load().then(() => {
    if (this._destroyed) return;
    try { this._bus.shelter(() => applyLoaded.call(this, start)); }
    catch (error) {
      this._restoring = false;
      this._toasts.toast(widgetText(this.context, 'The saved layout could not be restored: {error}', { error: errorText(this.context, error) }), 'error');
      // The drawings follow the instrument shown, and the chart loads it,
      // rather than stay empty. A second failure is the one just reported.
      try { releaseDrawings.call(this); startHeldLoad.call(this); } catch { /* reported above */ }
    } finally {
      this._restoring = false;
      this._holdDrawings = false;
      this.root.style.visibility = '';
    }
  });
}

/**
 * The shell's own bus, which can hold back its listeners' throws while a late
 * restore runs. A host's listener that throws is its own bug, and must not
 * leave that restore half applied or its held load never started: the next
 * save would write the half over the whole layout. The setters let such a
 * throw reach the host's own call; a late restore has no call above it, and
 * `ready` never rejects, so there it is dropped, as the engine drops one from
 * its own events, after every other listener has run. An error of the
 * restore's own still reaches its report.
 */
export class ShellBus extends WidgetBus<WidgetBusEvents> {
  private _sheltered = false;

  public override emit<K extends keyof WidgetBusEvents & string>(event: K, payload: WidgetBusEvents[K]): void {
    if (!this._sheltered) { super.emit(event, payload); return; }
    try { super.emit(event, payload); } catch { /* a host listener's own bug; the others have run */ }
  }

  /** Run `body` with its listeners' throws held back. */
  public shelter(body: () => void): void {
    const outer = this._sheltered;
    this._sheltered = true;
    try { body(); } finally { this._sheltered = outer; }
  }
}

/** The load the constructor held, unless one for the instrument shown is already out. */
function startHeldLoad(this: PersistHost): void {
  const controller = this.dataController;
  const request = controller?.getState().request ?? null;
  const loading = request !== null && request.symbol === this._symbol && request.exchange === this._exchange
    && request.interval === this._interval && dataVariantKey(request.variant) === dataVariantKey(this._variant);
  if (controller !== null && this._symbol !== '' && !loading) void this.reload();
}

/**
 * The saved facts, drawings and layout, as the constructor applies them from
 * a synchronous store: a fact the host passed as an option stays, and so does
 * one the user or the host has changed since the shell was built. Then the
 * held load goes out, and the changes are announced last, as the setters
 * announce theirs. Runs inside `ShellBus.shelter`.
 */
function applyLoaded(this: PersistHost, start: StartFacts): void {
  const wanted = this._saveWanted;
  const saved = this._stateGiven ? null : readSaved.call(this);
  const o = this._opts;
  const before = { symbol: this._symbol, exchange: this._exchange, interval: this._interval, variant: this._variant };
  if (saved !== null) {
    const instrument = this._symbol === start.symbol && this._exchange === start.exchange;
    if (instrument && o.symbol === undefined) this._symbol = saved.symbol.toUpperCase();
    if (instrument && o.exchange === undefined) this._exchange = saved.exchange;
    if (o.interval === undefined && this._interval === start.interval && isKnownInterval(saved.interval)) this._interval = saved.interval;
    if (o.variant === undefined && dataVariantKey(this._variant) === dataVariantKey(start.variant)) this._variant = saved.variant;
  }
  const moved = this._symbol !== before.symbol || this._exchange !== before.exchange;
  const changed = moved || this._interval !== before.interval || dataVariantKey(this._variant) !== dataVariantKey(before.variant);
  if (changed) {
    // As setSymbol does: bars a host set for the defaults are not this dataset's.
    if (this.dataController === null) this._series.setData([]);
    this._publishDataContext();
    this._statusline?.setSymbol(this._symbol, this._exchange, this._interval);
    this._topbar?.refresh();
    this._mobile?.refresh();
  }
  this.history.ignore(() => {
    if (saved !== null && this.instrumentDrawings !== null && saved.chart?.drawings !== undefined) {
      migrateUnscopedDrawings(o.drawingStore ?? storedDrawings(this._storage), savedKey(saved), saved.chart.drawings);
    }
    releaseDrawings.call(this);
    // The rail read its own entry while the copy was empty. It is its own
    // key, written whether or not a layout ever was, and a synchronous store
    // hands it to the rail at mount either way; a layout's own rail, applied
    // next, wins over it there too.
    const rail = this._storage.get(RAIL_PREFS_KEY);
    if (rail !== null && this._rail !== null) this._rail.restorePrefs(rail);
    // The user's chords are their own key too, and the keymap read an empty
    // copy at mount, as the rail did.
    restoreKeymap.call(this as unknown as KeysHost);
    if (saved === null) return;
    const type = saved.chartType;
    if (o.chartType === undefined && this.chartType() === start.chartType && type !== start.chartType && isChartTypeChoice(type)) this._selectChartType(type, saved.chart);
    if (o.theme === undefined && this._themeName === start.theme && saved.theme !== start.theme) this.setTheme(saved.theme);
    applySavedLayout.call(this, saved);
  });
  if (saved !== null) {
    this._rail?.refresh();
    this._statusline?.refresh();
  }
  this._restoring = false;
  this._saveWanted = false;
  // Only a change made meanwhile is written: applying what is stored changes
  // nothing worth writing, and a layout this build refused stays stored.
  if (wanted) this._scheduleSave();
  startHeldLoad.call(this);
  if (this._interval !== before.interval) this._bus.emit('interval', { interval: this._interval });
  if (moved) {
    this._bus.emit('symbol', { symbol: this._symbol, exchange: this._exchange });
    this.chart.emit('symbol', { symbol: this._symbol, exchange: this._exchange });
  }
  if (dataVariantKey(this._variant) !== dataVariantKey(before.variant)) this._bus.emit('variant', { variant: this._variant });
  if (saved !== null) this._bus.emit('layout', { reason: 'restore', chartType: this.chartType() });
}

/**
 * A failure of an asynchronous store, on the status line as a failed layout
 * write is. A read that failed is raised as a toast as well, as a failed load
 * is: it comes just before the first load, whose own messages take the status
 * line over at once. A refused write is not, since a full store refuses every
 * change and a toast for each would bury the chart.
 */
export function reportStorage(this: PersistHost, failure: WidgetStorageError): void {
  if (this._destroyed) return;
  const error = errorText(this.context, failure.error);
  if (failure.operation !== 'load') {
    this.context.status(widgetText(this.context, 'Saved chart settings could not be written: {error}', { error }), 'error');
    return;
  }
  const text = widgetText(this.context, 'Saved chart settings could not be read, so changes are kept for this session only: {error}', { error });
  this.context.status(text, 'error');
  this._toasts.toast(text, 'error');
}
