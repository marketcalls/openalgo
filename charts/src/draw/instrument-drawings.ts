/**
 * Drawings per instrument: one drawing document for each instrument a chart
 * shows, kept in a store the host chooses, and swapped as the chart moves
 * from one instrument to another.
 *
 * A trader's levels belong to the symbol they were drawn on. The controller
 * holds one document and knows nothing of instruments (the engine has no
 * instrument concept), so without this a trend line drawn on one symbol stays
 * on screen for every symbol loaded after it, and deleting it anywhere
 * deletes it everywhere.
 *
 * The rules this keeps, each of which a host would otherwise have to get right
 * on its own:
 *
 * - **The instrument comes from the chart's data context.** A `data:context`
 *   naming another symbol or exchange saves the outgoing document and loads
 *   the incoming one, in the same turn, so nothing that listens after it (an
 *   alert, a link group) ever sees one instrument's drawings under another's
 *   name. An interval or a data variant is the same instrument, and a context
 *   that names no instrument changes nothing.
 * - **A swap is not an edit.** It records no undo step, and it clears the
 *   drawing undo history the way any `fromJSON` does: a step taken on one
 *   instrument describes that instrument's drawings, and taking it back on
 *   another would put one of them there. A drag in progress is put back first
 *   and a shape half placed is dropped, with the tool left armed.
 * - **The whole document swaps**, drawings pinned to the viewport included: a
 *   group or a stacking order can span both spaces, and a note pinned to the
 *   screen is nearly always about the instrument on it. Transient drawings
 *   (`policy.persistent` false) are the host's and are not saved; a host
 *   keeping one per instrument places it again after the swap.
 * - **Every committed change is written at once**, only when the saved
 *   document actually changed, so a reload loses nothing and a stream of
 *   updates to transient drawings writes nothing. An instrument left with no
 *   drawings has its entry removed rather than an empty one kept.
 * - **A store that fails loses nothing for the session.** A refused write is
 *   reported through `onError` and the document is held in memory, read back
 *   from there, and written again with the next change.
 * - **Anything else that replaces the whole document** (a host's `fromJSON`,
 *   a chart layout restored) is the current instrument's new document, and is
 *   written as such.
 * - **A stored document of an earlier version is read through the migration**
 *   and written back only when something in it changes, in the version that
 *   holds it then: a version 2 document stays version 2 until a drawing in it
 *   is given an interval range, and a version 3 one keeps its ranges.
 *
 * The store is synchronous on purpose: a swap happens inside the context
 * change, and an answer arriving later would land one instrument's drawings
 * on whatever the chart shows by then. A host whose drawings live on a
 * server keeps a synchronous copy here and syncs it in the background.
 */
import type { DrawingController } from './controller';
import type { DrawingsDocument } from './types';
import { migrateDrawings } from './migrate';
import { drawingsDocumentVersion } from './intervals';

/** An instrument as a chart's data context names it. */
export interface DrawingInstrument {
  symbol?: string;
  exchange?: string;
}

/**
 * Where the documents live, one per instrument key. The host's choice:
 * `memoryDrawingStore` (the default), `webStorageDrawingStore` over a web
 * storage the host hands it, or its own. Synchronous; a throw from any
 * method, or `set` returning false, is a failure the helper reports.
 */
export interface DrawingDocumentStore {
  /** The document stored under `key`, or null (or undefined) when there is none. */
  get(key: string): unknown;
  /** Store `document` under `key`. False, or a throw, when the write did not land. */
  set(key: string, document: DrawingsDocument): boolean | void;
  /** Forget whatever is stored under `key`. */
  remove(key: string): void;
}

/** The three members of a web storage `webStorageDrawingStore` uses. */
export interface DrawingTextStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/** The slice of the chart `InstrumentDrawings` needs. */
export interface InstrumentDrawingsChart {
  readonly isDestroyed?: boolean;
  on(event: string, handler: (payload: unknown) => void): () => void;
  getDataContext?(): Readonly<DrawingInstrument> | undefined;
}

/** A store operation that failed, as `InstrumentDrawingsOptions.onError` receives it. */
export interface InstrumentDrawingsError {
  operation: 'read' | 'write' | 'remove';
  key: string;
  error: unknown;
}

export interface InstrumentDrawingsOptions {
  /** Where the documents live. Default: `memoryDrawingStore()`, for the life of the page. */
  store?: DrawingDocumentStore;
  /**
   * The key an instrument's document is stored under, or null for a context
   * that names no instrument. Default `instrumentDrawingsKey`. A host that
   * wants drawings per data variant too, or one namespace per chart, says so here.
   */
  key?: (instrument: DrawingInstrument) => string | null;
  /**
   * Which document wins when the helper starts on an instrument the store
   * already holds one for while the controller holds another. `'stored'`
   * (default) loads the stored one, which is right for a chart built fresh.
   * `'live'` keeps the controller's, even an empty one, and writes it to the
   * store, for a host that has just loaded that instrument's drawings itself
   * (a layout, a chart rebuilt from the one it replaces). Either way, drawings the
   * controller holds for an instrument the store has nothing for are kept as
   * that instrument's: that is how a document saved before drawings were per
   * instrument is attached to the instrument it was drawn on.
   */
  prefer?: 'stored' | 'live';
  /** Called for every store operation that failed. The document stays in memory for the session. */
  onError?: (error: InstrumentDrawingsError) => void;
}

/** As the controller writes an empty chart, so a swap to an instrument with nothing stored compares equal. */
const EMPTY: DrawingsDocument = { version: drawingsDocumentVersion([]), drawings: [] };

/** A document with nothing in it, which is stored as no entry at all. */
const isEmpty = (document: DrawingsDocument): boolean => document.drawings.length === 0 && !document.groups?.length;

/**
 * The default key: the exchange and the symbol, `NSE:INFY`, or the symbol
 * alone when there is no exchange. Each part is URI-encoded, so a colon
 * inside a symbol cannot make two instruments one key. Null when the symbol
 * is missing or blank. Case is kept: the host decides whether `infy` and
 * `INFY` are one instrument, and the widget uppercases symbols itself.
 */
export function instrumentDrawingsKey(instrument: DrawingInstrument | null | undefined): string | null {
  const symbol = typeof instrument?.symbol === 'string' ? instrument.symbol.trim() : '';
  if (symbol === '') return null;
  const exchange = typeof instrument?.exchange === 'string' ? instrument.exchange.trim() : '';
  return exchange === '' ? encodeURIComponent(symbol) : `${encodeURIComponent(exchange)}:${encodeURIComponent(symbol)}`;
}

/** A store in memory, for the life of the page. Each document is kept as text, so no caller shares an object with it. */
export function memoryDrawingStore(): DrawingDocumentStore {
  const entries = new Map<string, string>();
  return {
    get: key => { const text = entries.get(key); return text === undefined ? null : JSON.parse(text) as unknown; },
    set: (key, document) => { entries.set(key, JSON.stringify(document)); return true; },
    remove: key => { entries.delete(key); },
  };
}

/**
 * A store over a web storage the host hands it (the page's `localStorage`,
 * or anything with the same three members), one JSON entry per instrument
 * under `prefix`. A text that does not parse throws from `get`, which the
 * helper reports and treats as no drawings.
 */
export function webStorageDrawingStore(storage: DrawingTextStorage, prefix: string): DrawingDocumentStore {
  return {
    get: key => { const text = storage.getItem(prefix + key); return text === null ? null : JSON.parse(text) as unknown; },
    set: (key, document) => { storage.setItem(prefix + key, JSON.stringify(document)); },
    remove: key => { storage.removeItem(prefix + key); },
  };
}

/**
 * Attach a document saved before drawings were kept per instrument (one set
 * for the whole chart) to the instrument it was saved with, so no one loses
 * the drawings they already have. It is written only when the store holds
 * nothing for that instrument yet and the document has something in it; an
 * instrument that already has its own keeps it. True when it was written.
 */
export function migrateUnscopedDrawings(store: DrawingDocumentStore, key: string | null, document: unknown): boolean {
  if (key === null) return false;
  const migrated = migrateDrawings(document);
  if (isEmpty(migrated)) return false;
  let existing: unknown;
  // A store that cannot say what it holds is not written over.
  try { existing = store.get(key); } catch { return false; }
  if (existing !== null && existing !== undefined) return false;
  try { return store.set(key, migrated) !== false; } catch { return false; }
}

/**
 * Keeps a drawing controller's document per instrument. Build it once the
 * controller exists; it follows the chart's data context from then on.
 *
 * ```ts
 * const scoped = new InstrumentDrawings(chart, draw, {
 *   store: webStorageDrawingStore(localStorage, 'my-app:drawings:'),
 * });
 * chart.setDataContext({ symbol: 'INFY', exchange: 'NSE', interval: '5m' });
 * ```
 */
export class InstrumentDrawings {
  private readonly _draw: DrawingController;
  private readonly _store: DrawingDocumentStore;
  private readonly _keyOf: (instrument: DrawingInstrument) => string | null;
  private readonly _onError: ((error: InstrumentDrawingsError) => void) | undefined;
  private _key: string | null = null;
  /** The current instrument's document as last written or loaded, to skip a write that changes nothing. */
  private _text: string | null = null;
  /** Documents whose write failed, by key: what the store should hold, kept for the session. */
  private readonly _held = new Map<string, string>();
  private _swapping = false;
  private _destroyed = false;
  private readonly _off: (() => void)[] = [];

  public constructor(chart: InstrumentDrawingsChart, controller: DrawingController, options: InstrumentDrawingsOptions = {}) {
    this._draw = controller;
    this._store = options.store ?? memoryDrawingStore();
    this._keyOf = options.key ?? instrumentDrawingsKey;
    this._onError = options.onError;
    if (chart.isDestroyed === true || controller.isDestroyed) { this._destroyed = true; return; }
    this._off.push(
      chart.on('data:context', context => this._follow(context as DrawingInstrument | undefined)),
      chart.on('drawing:change', () => this._changed()),
      chart.on('draw:destroy', payload => {
        if ((payload as { controller?: unknown } | null)?.controller === controller) this.destroy();
      }),
      chart.on('destroy', () => this.destroy()),
    );
    const key = this._keyFor(chart.getDataContext?.());
    if (key !== null) this._start(key, options.prefer ?? 'stored');
  }

  public get isDestroyed(): boolean { return this._destroyed; }

  /** The key of the instrument whose drawings are on the chart, or null before the chart has named one. */
  public key(): string | null { return this._key; }

  /**
   * Move to another instrument now, without waiting for the chart's data
   * context: for a host that does not publish one, or that switches its
   * drawings ahead of its data. A later context naming the same instrument
   * changes nothing. Null, or an instrument with no key, changes nothing.
   */
  public setInstrument(instrument: DrawingInstrument | null): void {
    if (this._destroyed || instrument === null) return;
    this._follow(instrument);
  }

  /**
   * The saved document of an instrument: the drawings on the chart for the
   * current one, the stored document for any other, or null when it has
   * none (or no key). A copy either way.
   */
  public document(instrument: DrawingInstrument): DrawingsDocument | null {
    const key = this._keyFor(instrument);
    if (key === null) return null;
    const document = key === this._key && !this._destroyed ? this._draw.toJSON() : this._read(key);
    return document === null || isEmpty(document) ? null : document;
  }

  /**
   * Replace one instrument's drawings. On the current instrument that is the
   * controller's `fromJSON`, which clears its undo history; on any other, the
   * stored document, shown when the chart next moves there. For a layout
   * that brings the drawings of an instrument the chart is about to show.
   */
  public setDocument(instrument: DrawingInstrument, document: unknown): void {
    const key = this._keyFor(instrument);
    if (this._destroyed || key === null) return;
    if (key === this._key) { this._draw.fromJSON(document); return; }
    this._write(key, JSON.stringify(migrateDrawings(document)));
  }

  /** Write the current instrument's document now, and any the store refused before. False while one is still refused. */
  public save(): boolean {
    if (this._destroyed) return this._held.size === 0;
    for (const [key, text] of [...this._held]) if (key !== this._key) this._write(key, text);
    if (this._key !== null) this._saveCurrent(true);
    return this._held.size === 0;
  }

  /** Stop following the chart. The documents stay where they are. */
  public destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    for (const off of this._off.splice(0)) off();
  }

  // ── internals ──────────────────────────────────────────────────────────

  private _keyFor(instrument: DrawingInstrument | null | undefined): string | null {
    if (instrument === null || instrument === undefined) return null;
    try { return this._keyOf(instrument); } catch { return null; }
  }

  /** The drawings the controller would save, as text. */
  private _live(): string {
    return JSON.stringify(this._draw.toJSON());
  }

  /** Take `key` as the current instrument, with the drawings `prefer` picks. */
  private _start(key: string, prefer: 'stored' | 'live'): void {
    this._key = key;
    const stored = this._read(key);
    const live = this._live();
    if (stored !== null && prefer === 'stored') {
      if (JSON.stringify(stored) !== live) this._load(stored);
      this._text = this._live();
      return;
    }
    // Nothing stored for it and nothing on the chart: nothing to write.
    if (stored === null && isEmpty(JSON.parse(live) as DrawingsDocument)) { this._text = live; return; }
    // The drawings on the chart are this instrument's: a document saved
    // before there were instruments, or the one the host has just loaded.
    this._text = null;
    this._saveCurrent(false);
  }

  private _follow(context: DrawingInstrument | undefined): void {
    if (this._destroyed || this._draw.isDestroyed) return;
    const key = this._keyFor(context);
    // A context naming no instrument leaves the drawings with the last one.
    if (key === null || key === this._key) return;
    if (this._key === null) { this._start(key, 'stored'); return; }
    this._swap(key);
  }

  private _swap(next: string): void {
    const draw = this._draw;
    // The outgoing document as it stood before the gesture, which a context
    // change abandons; a shape half placed goes with it, the tool stays armed.
    draw.cancelDrag();
    const tool = draw.activeTool();
    if (tool !== null) draw.setTool(tool, { space: draw.activeToolSpace() });
    this._saveCurrent(false);
    this._key = next;
    const stored = this._read(next);
    this._load(stored ?? EMPTY);
    // A listener on the load (a link group bringing a peer's newer copy) can
    // have changed what is on the chart: that is this instrument's too.
    const live = this._live();
    this._text = stored === null ? JSON.stringify(EMPTY) : JSON.stringify(stored);
    if (live !== this._text) this._saveCurrent(false);
  }

  /** Put `document` on the controller without the change it announces being written back. */
  private _load(document: DrawingsDocument): void {
    this._swapping = true;
    try { this._draw.fromJSON(document); }
    finally { this._swapping = false; }
  }

  private _changed(): void {
    if (this._swapping || this._destroyed || this._key === null || this._draw.isDestroyed) return;
    this._saveCurrent(false);
  }

  /** Write the current document when it changed, or always when `force`. */
  private _saveCurrent(force: boolean): void {
    const key = this._key;
    if (key === null) return;
    const text = this._live();
    if (!force && text === this._text && !this._held.has(key)) return;
    this._text = text;
    this._write(key, text);
  }

  private _write(key: string, text: string): void {
    const document = JSON.parse(text) as DrawingsDocument;
    const operation = isEmpty(document) ? 'remove' : 'write';
    try {
      if (operation === 'remove') this._store.remove(key);
      else if (this._store.set(key, document) === false) throw new Error('The drawing store refused the write');
      this._held.delete(key);
    } catch (error) {
      this._held.set(key, text);
      this._report(operation, key, error);
    }
  }

  /** The stored document for `key`, migrated to the current shape, or null. A held one comes first. */
  private _read(key: string): DrawingsDocument | null {
    const held = this._held.get(key);
    if (held !== undefined) return JSON.parse(held) as DrawingsDocument;
    let value: unknown;
    try { value = this._store.get(key); }
    catch (error) { this._report('read', key, error); return null; }
    if (value === null || value === undefined) return null;
    const document = migrateDrawings(value);
    return isEmpty(document) ? null : document;
  }

  private _report(operation: InstrumentDrawingsError['operation'], key: string, error: unknown): void {
    try { this._onError?.({ operation, key, error }); } catch { /* A host's report cannot undo the swap. */ }
  }
}

/** `new InstrumentDrawings(chart, controller, options)`, as a function. */
export function createInstrumentDrawings(chart: InstrumentDrawingsChart, controller: DrawingController,
  options: InstrumentDrawingsOptions = {}): InstrumentDrawings {
  return new InstrumentDrawings(chart, controller, options);
}
