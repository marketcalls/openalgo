/**
 * The widget's IndexedDB store, and the store `persist` uses when the host
 * names none. It loads when a store is first built (storage.ts, lazy.ts), so
 * a widget that persists nothing never fetches it.
 *
 * `localStorage` is synchronous, shared with the host's own keys and capped
 * at a few megabytes per origin, which drawings kept for every instrument a
 * trader has looked at can reach. IndexedDB has room, but answers later, so
 * the store here is an `AsyncStorageLike`: `WidgetStorage` reads a namespace
 * from it once and writes behind.
 *
 * Five decisions worth recording:
 *
 * - **A namespace this database has never held takes what an earlier release
 *   left in the page's storage.** The first read of an empty namespace copies
 *   every `oac-widget:<namespace>:` key from `localStorage` in the same
 *   transaction and marks the namespace as copied, so a layout saved before
 *   the upgrade opens as it was, and a namespace emptied later is not filled
 *   again from the old copy. The old keys are left where they were: going
 *   back to an earlier release, or to `storage: localStorage`, still finds them.
 * - **The writes pending when the page goes away are journaled in
 *   `localStorage`.** IndexedDB may not commit a transaction started while a
 *   page unloads; the journal is small, written once, and replayed and
 *   removed by the next load.
 * - **Another tab upgrading or deleting the database is let through.** The
 *   connection closes when asked, and the next call opens a new one.
 * - **Each write that lands is announced**, to the other widgets on the page
 *   and, over a broadcast channel named after the database, to other tabs.
 *   The widget answers reads from a copy it took at load; without this, a tab
 *   opened earlier would show an instrument without the lines another tab
 *   drew on it since, and its next change there would write over them. A
 *   synchronous store never had that gap, since every read went to it.
 * - **The default falls back to `localStorage` when the database cannot be
 *   read at all**, so a browser that offers IndexedDB but refuses it keeps
 *   persisting as earlier releases did. A host that names this store gets
 *   IndexedDB or a reported failure, never a quiet change of store.
 */
import { STORAGE_PREFIX, defaultStorage, type AsyncStorageLike } from './context';
import { DATABASE, type IndexedDbWidgetStorage, type IndexedDbWidgetStorageOptions } from './storage';

const STORE = 'entries';
/** Where a namespace's copy from the page's storage is recorded; outside every `oac-widget:` range. */
const COPIED = 'copied:';
/** The broadcast channel a database announces its landed writes on, by database name. */
const CHANNEL = 'oac-widget-store:';

type ChangeListener = (key: string, value: string | null) => void;

/** The store `createIndexedDbWidgetStorage` builds (storage.ts), once this module has arrived. */
export function openIndexedDbStore(factory: IDBFactory, name: string, options: IndexedDbWidgetStorageOptions): IndexedDbWidgetStorage {
  const journal = options.journal === undefined ? defaultStorage() : options.journal;
  const legacy = options.migrateFrom === undefined ? pageStorage() : options.migrateFrom;
  let opening: Promise<IDBDatabase> | null = null;
  let closed = false;
  const listeners = new Set<ChangeListener>();
  // Open while someone on this page listens; a write landing with nobody
  // listening here is still announced to other tabs, on a channel of its own.
  let channel: BroadcastChannel | null = null;

  const tell = (key: string, value: string | null): void => {
    for (const listener of [...listeners]) {
      try { listener(key, value); } catch { /* one listener's failure is not the write's */ }
    }
  };
  const announce = (key: string, value: string | null): void => {
    tell(key, value);
    const Channel = broadcastChannel();
    if (Channel === null) return;
    try {
      if (channel !== null) { channel.postMessage({ key, value }); return; }
      const once = new Channel(CHANNEL + name);
      once.postMessage({ key, value });
      once.close();
    } catch { /* another tab then learns of it at its next load, as without a channel */ }
  };
  const listen = (): void => {
    const Channel = broadcastChannel();
    if (channel !== null || Channel === null || closed) return;
    try {
      channel = new Channel(CHANNEL + name);
      channel.onmessage = (event: MessageEvent) => {
        const data = event.data as { key?: unknown; value?: unknown } | null;
        if (typeof data?.key === 'string' && (typeof data.value === 'string' || data.value === null)) tell(data.key, data.value);
      };
    } catch { channel = null; }
  };
  const stopListening = (): void => {
    if (channel === null) return;
    channel.onmessage = null;
    channel.close();
    channel = null;
  };

  const open = (): Promise<IDBDatabase> => {
    if (closed) return Promise.reject(new Error('The widget storage is closed'));
    if (opening !== null) return opening;
    const attempt: Promise<IDBDatabase> = new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(name, 1);
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains(STORE)) request.result.createObjectStore(STORE);
      };
      request.onblocked = () => reject(new Error('The widget storage is held open by another tab'));
      request.onerror = () => reject(request.error ?? new Error('The widget storage could not be opened'));
      request.onsuccess = () => {
        const db = request.result;
        if (closed) { db.close(); reject(new Error('The widget storage is closed')); return; }
        db.onversionchange = () => { db.close(); if (opening === attempt) opening = null; };
        db.onclose = () => { if (opening === attempt) opening = null; };
        resolve(db);
      };
    }).catch((error: unknown) => {
      if (opening === attempt) opening = null;
      throw error;
    });
    opening = attempt;
    return attempt;
  };

  /** One transaction on the store, settled when it commits. */
  const run = async <T>(mode: IDBTransactionMode, body: (store: IDBObjectStore, done: (value: T) => void) => void): Promise<T> => {
    const db = await open();
    return new Promise<T>((resolve, reject) => {
      const tx = db.transaction(STORE, mode);
      let value: T | undefined;
      tx.oncomplete = () => resolve(value as T);
      tx.onabort = () => reject(tx.error ?? new Error('The widget storage transaction was aborted'));
      body(tx.objectStore(STORE), result => { value = result; });
    });
  };

  return {
    journal,
    entries: prefix => run<Array<[string, string]>>('readwrite', (store, done) => {
      const rows: Array<[string, string]> = [];
      done(rows);
      const range = keyRange(prefix);
      const cursor = range === null ? store.openCursor() : store.openCursor(range);
      cursor.onsuccess = () => {
        const at = cursor.result;
        if (at !== null) {
          if (typeof at.key === 'string' && at.key.startsWith(prefix) && typeof at.value === 'string') rows.push([at.key, at.value]);
          at.continue();
          return;
        }
        if (rows.length > 0 || legacy === null) return;
        const marker = store.get(COPIED + prefix);
        marker.onsuccess = () => {
          if (marker.result !== undefined) return;
          const copied = legacyEntries(legacy, prefix);
          if (copied.length === 0) return;
          for (const [key, value] of copied) { store.put(value, key); rows.push([key, value]); }
          store.put(new Date().toISOString(), COPIED + prefix);
        };
      };
    }),
    setItem: (key, value) => run<void>('readwrite', store => { store.put(value, key); }).then(() => announce(key, value)),
    removeItem: key => run<void>('readwrite', store => { store.delete(key); }).then(() => announce(key, null)),
    subscribe: listener => {
      listeners.add(listener);
      listen();
      return () => {
        listeners.delete(listener);
        if (listeners.size === 0) stopListening();
      };
    },
    close: () => {
      closed = true;
      listeners.clear();
      stopListening();
      const pending = opening;
      opening = null;
      void pending?.then(db => db.close(), () => {});
    },
  };
}

/** The page's `BroadcastChannel`, or null where it has none. */
function broadcastChannel(): typeof BroadcastChannel | null {
  const Channel = (globalThis as { BroadcastChannel?: typeof BroadcastChannel }).BroadcastChannel;
  return typeof Channel === 'function' ? Channel : null;
}

/** Every key under `prefix` and its value in a web storage; nothing when it cannot be read. */
function legacyEntries(storage: Storage, prefix: string): Array<[string, string]> {
  const out: Array<[string, string]> = [];
  try {
    for (let i = 0; i < storage.length; i++) {
      const key = storage.key(i);
      if (key === null || !key.startsWith(prefix)) continue;
      const value = storage.getItem(key);
      if (value !== null) out.push([key, value]);
    }
  } catch { return []; }
  return out;
}

/** The keys under `prefix`, where the page has key ranges; null to scan them all. */
function keyRange(prefix: string): IDBKeyRange | null {
  const Range = (globalThis as { IDBKeyRange?: typeof IDBKeyRange }).IDBKeyRange;
  try { return Range === undefined ? null : Range.bound(prefix, prefix + '\uffff'); } catch { return null; }
}

/** The page's `localStorage` as a full web storage, for the copy, or null. */
function pageStorage(): Storage | null {
  const store = defaultStorage() as Partial<Storage> | null;
  return store !== null && typeof store.key === 'function' && typeof store.length === 'number' ? store as Storage : null;
}

/** The store `defaultWidgetStore` hands every widget on the page (storage.ts), once this module has arrived. */
export function openPageDefault(factory: IDBFactory): AsyncStorageLike {
  return orPageStorage(openIndexedDbStore(factory, DATABASE, {}));
}

/**
 * `idb`, or the page's `localStorage` when the database cannot be read at
 * all. A browser can offer `indexedDB` and refuse every open (turned off, or
 * in some private windows) while its `localStorage` works; such a page keeps
 * its layouts where every release before this one kept them, rather than
 * losing each session's changes. Decided once, by the first read: a database
 * that has answered is kept for the page, so one refused write never splits
 * a page's keys between two stores.
 */
function orPageStorage(idb: IndexedDbWidgetStorage): AsyncStorageLike {
  const page = pageStorage();
  if (page === null) return idb;
  let use: 'idb' | 'page' | null = null;
  const onPage = (write: () => void): Promise<void> => {
    try { write(); return Promise.resolve(); } catch (error) { return Promise.reject(error); }
  };
  return {
    journal: idb.journal,
    // The database's own announcements while it is the store; on the page's
    // storage, the storage event it fires in this tab for another tab's write.
    subscribe: listener => {
      const off = idb.subscribe((key, value) => { if (use !== 'page') listener(key, value); });
      const win = globalThis as { addEventListener?: Window['addEventListener']; removeEventListener?: Window['removeEventListener'] };
      const changed = (event: StorageEvent): void => {
        if (use === 'page' && event.storageArea === page && event.key?.startsWith(STORAGE_PREFIX) === true) listener(event.key, event.newValue);
      };
      try { win.addEventListener?.('storage', changed); } catch { /* no other tab to hear from */ }
      return () => {
        off();
        try { win.removeEventListener?.('storage', changed); } catch { /* never added */ }
      };
    },
    entries: prefix => use === 'page' ? Promise.resolve(legacyEntries(page, prefix)) : idb.entries(prefix).then(
      rows => { use = 'idb'; return rows; },
      (error: unknown) => {
        if (use === 'idb') throw error;
        use = 'page';
        return legacyEntries(page, prefix);
      }),
    setItem: (key, value) => use === 'page' ? onPage(() => page.setItem(key, value)) : idb.setItem(key, value),
    removeItem: key => use === 'page' ? onPage(() => page.removeItem(key)) : idb.removeItem(key),
  };
}
