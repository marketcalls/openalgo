/**
 * The widget's persisted preferences: `WidgetStorage`, namespaced JSON over
 * a synchronous store (`localStorage`) or an asynchronous one (IndexedDB)
 * that never throws, with the journal that keeps an asynchronous store's
 * pending writes when a page goes away. The IndexedDB store itself is
 * storage.ts.
 */
import { isRecord } from '../helpers/validate';

// ── storage ────────────────────────────────────────────────────────────

/** The three calls the widget makes on a synchronous store. `localStorage` satisfies it. */
export interface StorageLike {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

/**
 * A store whose calls settle later, as IndexedDB's do. The widget reads a
 * namespace from it once (`entries`) and answers every later read from that
 * copy, so its own reads stay synchronous; writes follow behind. Having an
 * `entries` method is what marks a store as asynchronous.
 */
export interface AsyncStorageLike {
  /** Every stored key that starts with `prefix`, with its value. */
  entries(prefix: string): Promise<ReadonlyArray<readonly [key: string, value: string]>>;
  setItem(key: string, value: string): Promise<void>;
  removeItem(key: string): Promise<void>;
  /**
   * A synchronous store the writes still pending are copied to when the page
   * goes away, and read back by the next `load`, because an asynchronous
   * write started as a page closes may never land. Without one, those writes
   * are lost with the page.
   */
  readonly journal?: StorageLike | null | undefined;
  /**
   * Hear each change other users of the store make once it has landed:
   * another tab on the same database, or another widget on the page. The
   * widget keeps its copy of the namespace current with it, as a synchronous
   * store's reads are, so an instrument whose drawings another tab changed
   * opens with them rather than overwriting them with an older copy. A null
   * value is a removal. Returns the call that stops listening. Without it,
   * the copy knows only what it read at load and what it wrote itself.
   */
  subscribe?(listener: (key: string, value: string | null) => void): () => void;
}

/** A write or a read an asynchronous store refused, as `WidgetStorageOptions.onError` receives it. */
export interface WidgetStorageError {
  /**
   * `load` when the namespace could not be read, after which the session
   * keeps its changes in memory only, since writing could overwrite what was
   * never read; `write` or `remove` for one key, which is tried again with
   * the next change or `flush`.
   */
  operation: 'load' | 'write' | 'remove';
  /** The full key, or the namespace prefix for `load`. */
  key: string;
  error: unknown;
}

export interface WidgetStorageOptions {
  /** Called for each failure of an asynchronous store. The widget shows it on its status line. */
  onError?: (error: WidgetStorageError) => void;
}

/** Every key the widget writes sits under this prefix, so a host on the same origin cannot collide. */
export const STORAGE_PREFIX = 'oac-widget:';
/** The journal of a namespace sits under this prefix, outside `STORAGE_PREFIX` so no namespace can hold it. */
const JOURNAL_PREFIX = 'oac-widget-journal:';
/**
 * How long `load` waits for an asynchronous store. A store that never
 * answers (IndexedDB has been seen to hang on open) would otherwise keep the
 * widget from ever loading its chart.
 */
const LOAD_TIMEOUT_MS = 4000;

/**
 * Namespaced JSON storage that never throws: a private window, a full quota
 * or a blocked store all read as "nothing saved" and write as "not kept".
 *
 * Over a synchronous store every call goes straight through. Over an
 * asynchronous one, `get`, `set` and `remove` work on a copy of the namespace
 * in memory: `load` fills it once, and each change is sent behind it, the
 * changes to one key made within one task coalesced into one write. A write
 * made before `load` settles waits for it and wins over the stored value,
 * because it is the newer of the two. A store that can say so (`subscribe`)
 * keeps the copy current with the writes other tabs land, as a synchronous
 * store's reads always were, until `close`.
 */
export class WidgetStorage {
  private readonly _store: StorageLike | null;
  private readonly _async: AsyncStorageLike | null;
  private readonly _ns: string;
  private readonly _journalKey: string;
  private readonly _onError: ((error: WidgetStorageError) => void) | undefined;
  /** The asynchronous namespace as last read or written, by full key, as JSON text. */
  private readonly _mirror = new Map<string, string>();
  /** Changes not sent yet, by full key: the text, or null for a remove. */
  private readonly _pending = new Map<string, string | null>();
  /** Changes sent and not settled yet. */
  private readonly _sending = new Map<string, string | null>();
  /** Changes the store refused, sent again with the next change or flush. */
  private readonly _refused = new Map<string, string | null>();
  private _loading: Promise<void> | null = null;
  private _loaded: boolean;
  private _memoryOnly = false;
  private _drain: Promise<void> | null = null;
  private _queued = false;
  private _journaled = false;
  /** Changes other users made, heard while the namespace was being read, applied over what it returned. */
  private readonly _heard = new Map<string, string | null>();
  private _unsubscribe: (() => void) | null = null;
  private _closed = false;

  public constructor(namespace: string, store: StorageLike | AsyncStorageLike | null, options: WidgetStorageOptions = {}) {
    this._ns = STORAGE_PREFIX + namespace + ':';
    this._journalKey = JOURNAL_PREFIX + namespace;
    const isAsync = store !== null && typeof (store as Partial<AsyncStorageLike>).entries === 'function';
    this._store = isAsync ? null : store as StorageLike | null;
    this._async = isAsync ? store as AsyncStorageLike : null;
    this._loaded = !isAsync;
    this._onError = options.onError;
  }

  public key(name: string): string { return this._ns + name; }

  public get(name: string): unknown {
    if (this._async !== null) {
      const text = this._mirror.get(this.key(name));
      try { return text === undefined ? null : JSON.parse(text); } catch { return null; }
    }
    if (this._store === null) return null;
    try {
      const raw = this._store.getItem(this.key(name));
      return raw === null ? null : JSON.parse(raw);
    } catch { return null; }
  }

  /** True when the write landed; over an asynchronous store, when it was taken to be sent. */
  public set(name: string, value: unknown): boolean {
    if (this._async !== null) {
      let text: string | undefined;
      try { text = JSON.stringify(value); } catch { return false; }
      this._queue(this.key(name), text ?? null);
      return true;
    }
    if (this._store === null) return false;
    try { this._store.setItem(this.key(name), JSON.stringify(value)); return true; } catch { return false; }
  }

  public remove(name: string): void {
    if (this._async !== null) { this._queue(this.key(name), null); return; }
    if (this._store === null) return;
    try { this._store.removeItem(this.key(name)); } catch { /* nothing to remove, or no store */ }
  }

  /** Whether writes can land at all. */
  public get enabled(): boolean { return this._store !== null || this._async !== null; }

  /** Whether reads answer from what is stored: always over a synchronous store, once `load` has settled over an asynchronous one. */
  public get loaded(): boolean { return this._loaded; }

  /**
   * Read the namespace from an asynchronous store, once; later calls return
   * the same promise. Settles at once over a synchronous store. Never
   * rejects: a store that fails or does not answer within a few seconds is
   * reported through `onError`, and the session then runs on memory.
   */
  public load(): Promise<void> {
    if (this._loading === null) this._loading = this._async === null ? Promise.resolve() : this._read(this._async);
    return this._loading;
  }

  /**
   * Stop following the changes other users of an asynchronous store make.
   * Changes already taken are still sent. The widget calls it when it is
   * destroyed; a copy nobody reads again need not follow the store.
   */
  public close(): void {
    this._closed = true;
    const off = this._unsubscribe;
    this._unsubscribe = null;
    try { off?.(); } catch { /* a store that fails to let go holds only a listener that now does nothing */ }
  }

  /**
   * Send every change made so far now, and settle once each has landed or
   * failed. Before the sends it copies them to the store's journal, which is
   * what makes it the call for a page going away. Never rejects.
   */
  public async flush(): Promise<void> {
    if (this._async === null) return;
    this._writeJournal(this._async.journal);
    this._requeue();
    do await this._send(); while (this._pending.size > 0 && !this._memoryOnly);
  }

  private _queue(key: string, text: string | null): void {
    if (text === null) this._mirror.delete(key);
    else this._mirror.set(key, text);
    this._refused.delete(key);
    this._pending.set(key, text);
    if (this._queued) return;
    this._queued = true;
    queueMicrotask(() => { this._queued = false; void this._send(); });
  }

  private _requeue(): void {
    for (const [key, text] of this._refused) if (!this._pending.has(key)) this._pending.set(key, text);
    this._refused.clear();
  }

  private async _read(store: AsyncStorageLike): Promise<void> {
    // Before the read goes out, so a change landing while it runs is heard.
    if (!this._closed && typeof store.subscribe === 'function') {
      try { this._unsubscribe = store.subscribe((key, text) => this._hear(key, text)); } catch { /* the copy then knows what it read */ }
    }
    let rows: ReadonlyArray<readonly [string, string]> = [];
    try {
      rows = await within(Promise.resolve().then(() => store.entries(this._ns)), LOAD_TIMEOUT_MS);
    } catch (error) {
      this._memoryOnly = true;
      this._report('load', this._ns, error);
    }
    if (!this._memoryOnly) {
      // Newest first: a change made in this session, then the journal the
      // last page left, then what the store holds.
      const journal = readJournal(store.journal, this._journalKey, this._ns);
      if (journal !== null) {
        this._journaled = true;
        for (const [key, text] of journal) {
          if (this._pending.has(key)) continue;
          if (text === null) this._mirror.delete(key);
          else this._mirror.set(key, text);
          this._pending.set(key, text);
        }
      }
      for (const row of Array.isArray(rows) ? rows : []) {
        const [key, text] = row;
        if (typeof key === 'string' && key.startsWith(this._ns) && typeof text === 'string' && !this._pending.has(key)) this._mirror.set(key, text);
      }
      // Heard while the read ran, so at least as new as what it returned.
      for (const [key, text] of this._heard) {
        if (this._pending.has(key)) continue;
        if (text === null) this._mirror.delete(key);
        else this._mirror.set(key, text);
      }
    }
    this._heard.clear();
    this._loaded = true;
    if (!this._memoryOnly && (this._pending.size > 0 || this._journaled)) void this._send();
  }

  /**
   * One sender at a time, in batches: a key is not sent again while its last
   * write is out, so a newer value always lands after an older one. The
   * journal goes once everything it held has landed.
   */
  private _send(): Promise<void> {
    const store = this._async;
    if (this._drain !== null || store === null) return this._drain ?? Promise.resolve();
    const drain = (async (): Promise<void> => {
      await this.load();
      while (this._pending.size > 0 && !this._memoryOnly) {
        const batch = [...this._pending];
        this._pending.clear();
        for (const [key, text] of batch) this._sending.set(key, text);
        const results = await Promise.allSettled(batch.map(([key, text]) =>
          Promise.resolve().then(() => (text === null ? store.removeItem(key) : store.setItem(key, text)))));
        results.forEach((result, i) => {
          const [key, text] = batch[i]!; // one settled result per batch entry, in order
          this._sending.delete(key);
          if (result.status === 'fulfilled') return;
          if (!this._pending.has(key)) this._refused.set(key, text);
          this._report(text === null ? 'remove' : 'write', key, result.reason);
        });
      }
      if (this._journaled && !this._memoryOnly && this._pending.size === 0 && this._sending.size === 0 && this._refused.size === 0) {
        this._journaled = false;
        try { store.journal?.removeItem(this._journalKey); } catch { /* a journal that stays is replayed once more, harmlessly */ }
      }
    })();
    this._drain = drain;
    void drain.finally(() => {
      this._drain = null;
      // A change made as the last batch settled found this sender still busy.
      if (this._pending.size > 0 && !this._memoryOnly) void this._send();
    });
    return drain;
  }

  /**
   * A change another user of the store made, once it landed. A key this copy
   * has changed and not seen land keeps its own value: that write goes out
   * after, so it is the one the store keeps.
   */
  private _hear(key: unknown, text: unknown): void {
    if (this._closed || this._memoryOnly || typeof key !== 'string' || !key.startsWith(this._ns)) return;
    if (text !== null && typeof text !== 'string') return;
    if (this._pending.has(key) || this._sending.has(key) || this._refused.has(key)) return;
    if (!this._loaded) { this._heard.set(key, text); return; }
    if (text === null) this._mirror.delete(key);
    else this._mirror.set(key, text);
  }

  private _writeJournal(journal: StorageLike | null | undefined): void {
    if (journal === null || journal === undefined || this._memoryOnly) return;
    const entries: Record<string, string | null> = {};
    let any = false;
    // Oldest first, so the newest change to a key is the one kept. A journal
    // the last page left and this one has not read yet is kept under them.
    const earlier = this._loaded ? [] : readJournal(journal, this._journalKey, this._ns) ?? [];
    for (const map of [earlier, this._refused, this._sending, this._pending]) for (const [key, text] of map) { entries[key] = text; any = true; }
    if (!any) return;
    try {
      journal.setItem(this._journalKey, JSON.stringify({ version: 1, entries }));
      this._journaled = true;
    } catch { /* a full or blocked journal leaves the writes to land or not */ }
  }

  private _report(operation: WidgetStorageError['operation'], key: string, error: unknown): void {
    try { this._onError?.({ operation, key, error }); } catch { /* a host's report cannot stop the storage */ }
  }
}

/** The changes a journal holds for the namespace `prefix`, or null when there is none. */
function readJournal(journal: StorageLike | null | undefined, key: string, prefix: string): Array<[string, string | null]> | null {
  if (journal === null || journal === undefined) return null;
  let raw: string | null;
  try { raw = journal.getItem(key); } catch { return null; }
  if (raw === null) return null;
  try {
    const parsed = JSON.parse(raw) as unknown;
    if (!isRecord(parsed) || parsed.version !== 1 || !isRecord(parsed.entries)) return [];
    return Object.entries(parsed.entries).filter((entry): entry is [string, string | null] =>
      entry[0].startsWith(prefix) && (typeof entry[1] === 'string' || entry[1] === null));
  } catch { return []; }
}

/** `work`, or a rejection after `ms`. */
function within<T>(work: Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`no answer within ${ms} ms`)), ms);
    work.then(value => { clearTimeout(timer); resolve(value); }, (error: unknown) => { clearTimeout(timer); reject(error); });
  });
}

/** The page's `localStorage` when it exists and works, else null. */
export function defaultStorage(): StorageLike | null {
  try {
    const g = globalThis as { localStorage?: StorageLike };
    return g.localStorage !== undefined && typeof g.localStorage.getItem === 'function' ? g.localStorage : null;
  } catch { return null; }
}
