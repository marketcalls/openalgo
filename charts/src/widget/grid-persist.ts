/**
 * The chart grid's persisted desk: the store behind `persist`, the debounced
 * and the prompt write after a change, the flush when the page goes away, the
 * user's chords shared by every chart, and reading the stored desk back when
 * the grid is built.
 *
 * Its own module so grid.ts carries the layout and the charts. Each function
 * takes the grid's state (`GridState`, grid.ts) and reads or writes only its
 * persistence fields besides what it names.
 */
import type { WorkspacePayload } from 'openalgo-charts/workspace';
import type { DrawingsDocument } from 'openalgo-charts/draw';
import { WidgetStorage } from './context';
import { defaultWidgetStore } from './storage';
import { errorText, widgetText } from './localization';
import { SAVE_DEBOUNCE_MS } from './widget';
import { readChartDrawings, type ChartDrawings } from './grid-payload';
import { KEYMAP_KEY } from './keymap';
import type { Cell, ChartGridApplyReport, GridState } from './grid';

const STATE_KEY = 'grid';
/** The drawings of each chart, per instrument, beside the workspace. */
const DRAWINGS_KEY = 'grid-drawings';

/** The store behind `persist`, or none. Its failures are said on the active chart. */
export function gridStorage(s: GridState): WidgetStorage {
  const { options, text } = s;
  const store = options.persist ? (options.storage === undefined ? defaultWidgetStore() : options.storage) : null;
  return new WidgetStorage(typeof options.persist === 'string' ? options.persist : 'default', store, {
    // The grid has no status line of its own; the active chart's says it. A
    // read that failed is a toast as well, as in one widget: the charts'
    // first loads take the status line over at once.
    onError: failure => {
      if (s.destroyed || s.active === null) return;
      const error = errorText(text, failure.error);
      const context = s.active.widget.context;
      if (failure.operation !== 'load') {
        context.status(widgetText(text, 'Saved chart settings could not be written: {error}', { error }), 'error');
        return;
      }
      const message = widgetText(text, 'Saved chart settings could not be read, so changes are kept for this session only: {error}', { error });
      context.status(message, 'error');
      context.toast(message, 'error');
    },
  });
}

/** A stream of changes (a pan, a zoom, a drag) settles before it is written. */
export function scheduleSave(s: GridState): void {
  s.held = false;
  if (!s.storage.enabled || s.destroyed) return;
  if (s.saveTimer !== 0) clearTimeout(s.saveTimer);
  s.saveTimer = setTimeout(() => saveNow(s), SAVE_DEBOUNCE_MS);
}

/**
 * A discrete change (a preset, a link, an instrument) is written before the
 * task ends. A write left to a timer or to the unload flush can be lost when
 * the page reloads at once: one browser engine was seen to drop storage
 * writes made while the page unloads.
 */
export function saveSoon(s: GridState): void {
  s.held = false;
  if (!s.storage.enabled || s.destroyed || s.saveQueued) return;
  s.saveQueued = true;
  queueMicrotask(() => { s.saveQueued = false; saveNow(s); });
}

export function saveNow(s: GridState): void {
  if (s.saveTimer !== 0) { clearTimeout(s.saveTimer); s.saveTimer = 0; }
  if (!s.storage.enabled || s.destroyed || s.held || s.restoring || s.active === null) return;
  const desk = s.storage.set(STATE_KEY, s.grid.getWorkspace());
  // Only the charts on the grid: a chart the grid dropped takes its drawings with it.
  const charts: Record<string, Record<string, DrawingsDocument>> = {};
  for (const cell of s.cells) {
    const mine = s.drawings.get(cell.id);
    if (mine !== undefined && mine.size > 0) charts[cell.id] = Object.fromEntries(mine);
  }
  const drawn = s.storage.set(DRAWINGS_KEY, { version: 1, charts });
  // A synchronous store refuses a write it has no room for by returning
  // false, with no error to report, so it is said here, as one widget says
  // it: once per run of refusals, not at every debounce while the store is full.
  const refused = !desk || !drawn;
  if (refused && !s.saveRefused) s.active.widget.context.status(widgetText(s.text, 'The chart layout could not be saved'), 'error');
  s.saveRefused = refused;
}

/**
 * The user's chords belong to the desk, not to one chart: one record in the
 * grid's storage, applied to every chart and passed on when a chart changes it.
 */
export function followChords(s: GridState, cell: Cell): void {
  if (s.options.shortcutsEditor === false) return;
  const km = cell.widget.context.keymap;
  km.applyOverrides(s.chords);
  cell.offs.push(km.onChange(() => {
    if (s.sharing) return;
    s.sharing = true;
    try {
      const next = km.overrides();
      s.chords = next;
      for (const other of s.cells) if (other !== cell) other.widget.context.keymap.applyOverrides(next);
      if (Object.keys(next).length === 0) s.storage.remove(KEYMAP_KEY); else s.storage.set(KEYMAP_KEY, next);
    } finally { s.sharing = false; }
  }));
}

/** The desk's chords on every chart built before the store answered. */
function shareChords(s: GridState): void {
  if (s.options.shortcutsEditor === false) return;
  s.sharing = true;
  try { for (const cell of s.cells) cell.widget.context.keymap.applyOverrides(s.chords); } finally { s.sharing = false; }
}

/**
 * A debounced save still pending when the tab closes is the user's last
 * change, and so is a layout's inside autosave's quiet period; an
 * asynchronous store journals what may not land in time. Hiding writes
 * only a save still pending, as in one widget: a tab left for another on
 * the same desk would otherwise write its older desk over the one saved
 * there, at every switch.
 */
export function leaving(s: GridState, hiding: boolean): void {
  if (!hiding || s.saveTimer !== 0) saveNow(s);
  void s.storage.flush();
  s.saved?.flush();
}

type Apply = (payload: WorkspacePayload, docs: ChartDrawings) => ChartGridApplyReport;

/** The stored desk, or the preset when none can be applied. `late`: the preset was built while the store was read. */
function restore(s: GridState, late: boolean, apply: Apply): void {
  const { storage, options } = s;
  s.chords = storage.get(KEYMAP_KEY);
  // Written now, since nothing was while the store was read; the stored desk is older.
  if (s.given) { shareChords(s); saveSoon(s); return; }
  const stored = storage.get(STATE_KEY);
  s.restored = stored === null ? null : apply(stored as WorkspacePayload, readChartDrawings(storage.get(DRAWINGS_KEY)));
  if (s.restored?.applied === true) return;
  if (!late) s.grid.setPreset(options.preset ?? '1x1');
  else {
    shareChords(s);
    // Built with no instrument, so none asked the feed for one; they load it
    // now. Before `held` is set: a symbol change clears it.
    if (options.symbol !== undefined) for (const cell of s.cells) cell.widget.setSymbol(options.symbol, options.exchange);
  }
  if (s.restored !== null) {
    // The stored desk may only be waiting for a study or chart type the page
    // registers later, so it is kept, not overwritten by this fallback.
    s.held = true;
    s.grid.active().widget.context.toast(widgetText(s.text, 'The saved layout could not be restored: {error}', { error: s.restored.reason ?? '' }), 'error');
  }
}

/** Open the stored desk now over a synchronous store, or once an asynchronous one has answered. */
export function openStoredDesk(s: GridState, apply: Apply): void {
  if (!s.restoring) { restore(s, false, apply); return; }
  s.grid.setPreset(s.options.preset ?? '1x1');
  s.root.style.visibility = 'hidden';
  s.ready = s.storage.load().then(() => {
    if (s.destroyed) return;
    s.restoring = false;
    // `ready` never rejects: a desk that cannot be applied is reported, as the widget reports its own.
    try { restore(s, true, apply); } catch (error) {
      s.grid.active().widget.context.toast(widgetText(s.text, 'The saved layout could not be restored: {error}', { error: errorText(s.text, error) }), 'error');
    } finally { s.root.style.visibility = ''; }
  });
}
