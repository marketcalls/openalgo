/**
 * What the three catalog repositories share (workspaces, watchlists, drawing
 * templates): one serialized queue of revision-checked changes, and the
 * revision-checked storage in memory.
 *
 * Each change is applied to the catalog as stored at that moment, so an edit
 * made in another session survives; the whole candidate is validated before
 * storage is touched; a stale `expectedRevision`, or a write racing another
 * session, is refused as a conflict; subscribers hear the committed catalog
 * before the change's promise resolves. Internal: each repository keeps one
 * `CatalogQueue` and delegates to it, so its public shape is its own.
 */
import { number, readJson, string, WorkspaceDocumentError } from './json';

/** Storage for one catalog kind. The host must atomically reject writes whose expectedRevision is stale. */
interface CatalogStorage<C> {
  read(namespace: string): Promise<unknown | null>;
  write(namespace: string, catalog: C, expectedRevision: number, options?: { signal?: AbortSignal | undefined }): Promise<void>;
}

/** One catalog kind: how a stored catalog is validated, and the error a stale write raises. */
export interface CatalogKind<C> {
  /** Parse the complete catalog; corrupt storage is never replaced. */
  parse(input: unknown): C;
  conflict(): Error;
}

const copy = <T>(value: T): T => readJson(value) as T;

/** The ID factory a repository uses unless given one. */
export function randomId(): string {
  if (!globalThis.crypto?.randomUUID) throw new WorkspaceDocumentError('Supply an ID factory when crypto.randomUUID is unavailable');
  return globalThis.crypto.randomUUID();
}

/** One namespace's catalog, changed one serialized, revision-checked transaction at a time. */
export class CatalogQueue<C extends { revision: number }> {
  public readonly namespace: string;
  private readonly _listeners = new Set<(catalog: C) => void>();
  private _queue: Promise<void> = Promise.resolve();

  public constructor(private readonly _storage: CatalogStorage<C>, namespace: string,
    private readonly _kind: CatalogKind<C>, private readonly _empty: () => C) {
    this.namespace = string(namespace, 'storage namespace');
  }

  public async load(): Promise<C> {
    await this._queue;
    return this._read();
  }

  public subscribe(listener: (catalog: C) => void): () => void {
    this._listeners.add(listener);
    return () => { this._listeners.delete(listener); };
  }

  public transact<T>(mutate: (catalog: C) => T, options: { signal?: AbortSignal | undefined; expectedRevision?: number } = {}): Promise<T> {
    const { signal } = options;
    // A malformed revision is the caller's mistake: refused before the queue, never read against storage.
    const expected = options.expectedRevision === undefined ? undefined
      : number(options.expectedRevision, 'expected revision', 0, Number.MAX_SAFE_INTEGER, true);
    const operation = this._queue.then(async () => {
      signal?.throwIfAborted();
      const catalog = await this._read();
      signal?.throwIfAborted();
      if (expected !== undefined && catalog.revision !== expected) throw this._kind.conflict();
      const revision = catalog.revision;
      const result = mutate(catalog);
      catalog.revision++;
      // Validate the entire candidate, including limits, before touching storage.
      const next = this._kind.parse(catalog);
      signal?.throwIfAborted();
      await this._storage.write(this.namespace, next, revision, { signal });
      for (const listener of Array.from(this._listeners)) {
        // A host listener failing is reported, but the write has committed and resolves.
        try { listener(copy(next)); } catch (error) { queueMicrotask(() => { throw error; }); }
      }
      return result === undefined ? result : copy(result);
    });
    this._queue = operation.then(() => {}, () => {});
    return operation;
  }

  private async _read(): Promise<C> {
    const input = await this._storage.read(this.namespace);
    return input === null ? this._empty() : this._kind.parse(input);
  }
}

/**
 * Revision-checked storage in memory: for tests, previews and hosts without
 * IndexedDB. Nothing outlives the page. `seed` maps namespaces to catalogs.
 * It keeps the IndexedDB adapter's contract: a stale or skipping write is
 * refused, and a corrupt stored catalog is never replaced.
 */
export function createMemoryCatalogStorage<C extends { revision: number }>(seed: Readonly<Record<string, unknown>>, kind: CatalogKind<C>): CatalogStorage<C> {
  // Copies in and out: a caller holding a seed or a read value cannot reach the stored one.
  const values = new Map<string, unknown>(Object.entries(seed).map(([key, value]) => [key, copy(value)]));
  return {
    async read(namespace) {
      const value = values.get(string(namespace, 'storage namespace'));
      return value === undefined ? null : copy(value);
    },
    async write(namespace, catalog, expectedRevision, options) {
      options?.signal?.throwIfAborted();
      const key = string(namespace, 'storage namespace');
      const expected = number(expectedRevision, 'expected revision', 0, Number.MAX_SAFE_INTEGER, true);
      const next = kind.parse(catalog);
      if (next.revision !== expected + 1) throw new WorkspaceDocumentError('A write must advance the catalog revision by one');
      const previous = values.get(key);
      // Nothing awaits between the comparison and the write, so it is atomic.
      if ((previous === undefined ? 0 : kind.parse(previous).revision) !== expected) throw kind.conflict();
      values.set(key, next);
    },
  };
}
