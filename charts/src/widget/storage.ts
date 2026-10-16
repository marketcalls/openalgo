/**
 * The widget's IndexedDB store as the shell holds it: `createIndexedDbWidgetStorage`
 * and the store `persist` uses when the host names none.
 *
 * The store itself (storage-idb.ts) loads when a store is first created
 * (lazy.ts), so a widget that persists nothing never fetches it. Until it
 * arrives its reads and writes wait for it, and listeners added meanwhile are
 * attached once it is there; its journal is the page's synchronous store, as
 * before, so a page going away still has somewhere to put its pending writes.
 * Once it has arrived a store is built at once, as if it had been bundled in.
 */
import { defaultStorage, type AsyncStorageLike, type StorageLike } from './context';
import { lazyPart } from './lazy';

/** The database the widget keeps its preferences and layouts in when the host names none. Internal. */
export const DATABASE = 'openalgo-charts-widget';

export interface IndexedDbWidgetStorageOptions {
  /**
   * Where the writes still pending when the page goes away are kept until the
   * next load. Default: the page's `localStorage`. Null keeps no journal, and
   * those writes may be lost with the page.
   */
  journal?: StorageLike | null;
  /**
   * Where earlier releases kept the widget's keys, copied once into a
   * namespace this database has never held. Default: the page's
   * `localStorage`. Null copies nothing.
   */
  migrateFrom?: Storage | null;
}

export interface IndexedDbWidgetStorage extends AsyncStorageLike {
  /**
   * Hear each write that lands: this store's own, and those of any other
   * store over the same database in another tab. Returns the call that stops
   * listening.
   */
  subscribe(listener: (key: string, value: string | null) => void): () => void;
  /** Release the connection and stop listening. Later calls reject. */
  close(): void;
}

/** The IndexedDB store, fetched when the first store is created. Internal. */
export const indexedDbPart = lazyPart(() => import('./storage-idb'));

type IdbModule = NonNullable<typeof indexedDbPart.now>;
type Listener = (key: string, value: string | null) => void;

/** A store built by `open` once its code has arrived, and used through this until then. */
function lazyStore(open: (module: IdbModule) => AsyncStorageLike & { close?(): void }, journal: StorageLike | null): IndexedDbWidgetStorage {
  let real: (AsyncStorageLike & { close?(): void }) | null = null;
  let closed = false;
  const heard = new Map<Listener, (() => void) | undefined>();
  const build = (module: IdbModule): AsyncStorageLike & { close?(): void } => {
    if (real !== null) return real;
    const store = real = open(module);
    for (const listener of heard.keys()) heard.set(listener, store.subscribe?.(listener));
    if (closed) store.close?.();
    return store;
  };
  const now = (): AsyncStorageLike | null => real ?? (indexedDbPart.now === null ? null : build(indexedDbPart.now));
  const use = <T>(call: (store: AsyncStorageLike) => Promise<T>): Promise<T> => {
    const store = now();
    return store !== null ? call(store) : indexedDbPart.load().then(module => call(build(module)));
  };
  // Fetched as the store is created: a listener then hears other tabs' writes before this page reads or writes.
  if (now() === null) indexedDbPart.load().then(build, () => { /* the first call reports it */ });
  return {
    journal,
    entries: prefix => use(store => store.entries(prefix)),
    setItem: (key, value) => use(store => store.setItem(key, value)),
    removeItem: key => use(store => store.removeItem(key)),
    subscribe(listener) {
      heard.set(listener, now()?.subscribe?.(listener));
      return () => { heard.get(listener)?.(); heard.delete(listener); };
    },
    close() {
      closed = true;
      real?.close?.();
    },
  };
}

/**
 * A key-value store for the widget over IndexedDB: one object store of JSON
 * texts under the widget's keys, one transaction per call. Pass the page's
 * `indexedDB`; importing this module needs no browser. The store's code loads
 * as the first store is created (since 2.5.10): calls made before it arrives
 * wait for it.
 *
 * ```ts
 * createWidget(el, { persist: 'desk', storage: createIndexedDbWidgetStorage(indexedDB, 'my-app-charts') });
 * ```
 */
export function createIndexedDbWidgetStorage(factory: IDBFactory, name: string = DATABASE,
  options: IndexedDbWidgetStorageOptions = {}): IndexedDbWidgetStorage {
  const journal = options.journal === undefined ? defaultStorage() : options.journal;
  return lazyStore(module => module.openIndexedDbStore(factory, name, { ...options, journal }), journal);
}

let shared: { factory: IDBFactory; store: AsyncStorageLike } | null = null;

/**
 * The store behind `persist` when the host names none: IndexedDB where the
 * page has it, one connection for every widget on the page, else the page's
 * `localStorage`, else null. On IndexedDB, a database that cannot be read at
 * all falls back to the page's `localStorage` (storage-idb.ts).
 */
export function defaultWidgetStore(): StorageLike | AsyncStorageLike | null {
  let factory: IDBFactory | undefined;
  // Reading the property alone throws in some sandboxed frames.
  try { factory = (globalThis as { indexedDB?: IDBFactory }).indexedDB ?? undefined; } catch { factory = undefined; }
  if (factory === undefined || typeof factory.open !== 'function') return defaultStorage();
  const idb = factory;
  if (shared === null || shared.factory !== idb) shared = { factory: idb, store: lazyStore(module => module.openPageDefault(idb), defaultStorage()) };
  return shared.store;
}
