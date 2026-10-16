import { number, string, WorkspaceDocumentError } from './json';
import { parseWorkspaceCatalog, WorkspaceConflictError, type WorkspaceStorage, type WorkspaceCatalog, type WorkspaceOperationOptions } from './repository';

export interface IndexedDbWorkspaceStorage extends WorkspaceStorage {
  /** Release the connection. Existing transactions may finish; new calls reject. */
  close(): Promise<void>;
}

/** A revisioned catalog store: what the workspace, watchlist and drawing-template adapters share. */
export interface IndexedDbCatalogStorage<C extends { revision: number }> {
  read(namespace: string): Promise<unknown | null>;
  write(namespace: string, catalog: C, expectedRevision: number, options?: WorkspaceOperationOptions): Promise<void>;
  close(): Promise<void>;
}

/**
 * One atomic compare-and-write transaction per catalog, for any catalog kind.
 * `label` names the kind in error messages; `parse` validates both the
 * candidate and the stored value, so a corrupt record is never replaced.
 */
export function createIndexedDbCatalogStorage<C extends { revision: number }>(
  factory: IDBFactory, databaseName: string, label: string, parse: (input: unknown) => C, conflict: () => Error,
): IndexedDbCatalogStorage<C> {
  const name = string(databaseName, 'database name');
  let opening: Promise<IDBDatabase> | null = null;
  let connection: IDBDatabase | null = null;
  let closed = false;
  const closedError = () => new Error(`${label} storage is closed. Create a new adapter to reconnect.`);

  function open(): Promise<IDBDatabase> {
    if (closed) return Promise.reject(closedError());
    if (opening) return opening;
    opening = new Promise<IDBDatabase>((resolve, reject) => {
      const request = factory.open(name, 1);
      let failed = false;
      request.onupgradeneeded = () => {
        if (!request.result.objectStoreNames.contains('catalogs')) request.result.createObjectStore('catalogs');
      };
      request.onblocked = () => { failed = true; reject(new Error(`${label} database is blocked by another session. Close that session and retry.`)); };
      request.onerror = () => { failed = true; reject(request.error ?? new Error(`Cannot open ${label.toLowerCase()} database`)); };
      request.onsuccess = () => {
        const db = request.result;
        if (closed || failed) { db.close(); reject(closedError()); return; }
        connection = db;
        db.onversionchange = () => { closed = true; db.close(); connection = null; };
        db.onclose = () => { closed = true; connection = null; };
        resolve(db);
      };
    }).catch(error => { opening = null; throw error; });
    return opening;
  }

  return {
    async read(namespace) {
      const key = string(namespace, 'storage namespace');
      const db = await open();
      return new Promise<unknown | null>((resolve, reject) => {
        const transaction = db.transaction('catalogs', 'readonly');
        const request = transaction.objectStore('catalogs').get(key);
        let value: unknown = null;
        request.onsuccess = () => { value = request.result ?? null; };
        transaction.oncomplete = () => resolve(value);
        transaction.onabort = () => reject(transaction.error ?? new Error(`${label} read was aborted`));
      });
    },
    async write(namespace, catalog, expectedRevision, options) {
      const signal = options?.signal;
      signal?.throwIfAborted();
      const key = string(namespace, 'storage namespace');
      const expected = number(expectedRevision, 'expected revision', 0, Number.MAX_SAFE_INTEGER, true);
      const next = parse(catalog);
      if (next.revision !== expected + 1) throw new WorkspaceDocumentError('A write must advance the catalog revision by one');
      const db = await open();
      signal?.throwIfAborted();
      return new Promise<void>((resolve, reject) => {
        const transaction = db.transaction('catalogs', 'readwrite');
        const store = transaction.objectStore('catalogs');
        const request = store.get(key);
        let failure: unknown;
        const cancel = () => {
          try {
            transaction.abort();
            failure = signal?.reason;
          } catch { /* A committed transaction cannot be undone by cancellation. */ }
        };
        const cleanup = () => signal?.removeEventListener('abort', cancel);
        signal?.addEventListener('abort', cancel, { once: true });
        request.onsuccess = () => {
          try {
            const previous = request.result;
            const revision = previous === undefined ? 0 : parse(previous).revision;
            if (revision !== expected) throw conflict();
            store.put(next, key);
          } catch (error) {
            failure = error;
            transaction.abort();
          }
        };
        transaction.oncomplete = () => { cleanup(); resolve(); };
        transaction.onabort = () => { cleanup(); reject(failure ?? transaction.error ?? new Error(`${label} save was aborted`)); };
      });
    },
    async close() {
      closed = true;
      if (connection) { connection.close(); connection = null; }
      // An open already in flight closes its result in onsuccess.
      if (opening) await opening.catch(() => {});
    },
  };
}

/**
 * Browser persistence with one atomic compare-and-write transaction per catalog.
 * Pass the host's indexedDB explicitly; importing this module needs no browser.
 */
export function createIndexedDbWorkspaceStorage(
  factory: IDBFactory,
  databaseName = 'openalgo-chart-workspaces',
): IndexedDbWorkspaceStorage {
  return createIndexedDbCatalogStorage<WorkspaceCatalog>(factory, databaseName, 'Workspace', parseWorkspaceCatalog, () => new WorkspaceConflictError());
}
