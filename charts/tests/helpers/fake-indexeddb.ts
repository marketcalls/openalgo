/**
 * An in-memory IndexedDB with the few members the widget's store uses: open
 * with an upgrade, one object store with out-of-line keys, get, put, delete
 * and a cursor, and transactions that complete once their last request has
 * answered (writes are applied at once, not at commit). Every request answers on a later microtask, as a browser's do on
 * a later task, so code that forgets to wait fails here too. Not a general
 * implementation: no indexes, no key paths, no key ranges.
 */

type Handler = ((this: unknown) => void) | null;

interface FakeRequest<T> {
  result: T;
  error: Error | null;
  onsuccess: Handler;
  onerror: Handler;
  onupgradeneeded?: Handler;
  onblocked?: Handler;
}

export class FakeIndexedDb {
  /** Every database by name: its version, and each object store's records. */
  public readonly databases = new Map<string, { version: number; stores: Map<string, Map<string, unknown>> }>();
  /** Open connections, so a test can ask them to close. */
  public readonly connections: FakeConnection[] = [];
  /** Fail every open with this error. */
  public failOpen: Error | null = null;
  /** Leave every open unanswered. */
  public hangOpen = false;
  public opens = 0;

  public open(name: string, version = 1): FakeRequest<FakeConnection> {
    this.opens++;
    const request: FakeRequest<FakeConnection> = { result: undefined as unknown as FakeConnection, error: null, onsuccess: null, onerror: null, onupgradeneeded: null, onblocked: null };
    queueMicrotask(() => {
      if (this.hangOpen) return;
      if (this.failOpen !== null) { request.error = this.failOpen; request.onerror?.call(request); return; }
      let db = this.databases.get(name);
      if (db === undefined) this.databases.set(name, db = { version: 0, stores: new Map() });
      const connection = new FakeConnection(db.stores);
      this.connections.push(connection);
      request.result = connection;
      if (db.version < version) { db.version = version; request.onupgradeneeded?.call(request); }
      request.onsuccess?.call(request);
    });
    return request;
  }

  /** The records of one object store, for assertions. */
  public records(name: string, store = 'entries'): Map<string, unknown> {
    return this.databases.get(name)?.stores.get(store) ?? new Map();
  }

  /** What another tab deleting the database does to the connections open here. */
  public versionChange(): void {
    for (const c of this.connections) if (!c.closed) c.onversionchange?.call(c);
  }
}

export class FakeConnection {
  public onversionchange: Handler = null;
  public onclose: Handler = null;
  public closed = false;
  public readonly objectStoreNames: { contains(name: string): boolean };

  public constructor(private readonly stores: Map<string, Map<string, unknown>>) {
    this.objectStoreNames = { contains: name => stores.has(name) };
  }

  public createObjectStore(name: string): void { this.stores.set(name, new Map()); }

  public transaction(name: string, mode: 'readonly' | 'readwrite'): FakeTransaction {
    if (this.closed) throw new Error('InvalidStateError: the connection is closed');
    const records = this.stores.get(name);
    if (records === undefined) throw new Error(`NotFoundError: no object store ${name}`);
    return new FakeTransaction(records, mode);
  }

  public close(): void { this.closed = true; }
}

export class FakeTransaction {
  public oncomplete: Handler = null;
  public onabort: Handler = null;
  public error: Error | null = null;
  private pending = 0;
  private done = false;

  // Writes land at once rather than at commit: the widget's store never
  // relies on an abort rolling one back, and two transactions writing
  // side by side then cannot lose each other's records.
  public constructor(private readonly records: Map<string, unknown>, private readonly mode: 'readonly' | 'readwrite') {
    // A transaction that is given no request completes all the same.
    queueMicrotask(() => this.settle());
  }

  public objectStore(): FakeObjectStore { return new FakeObjectStore(this); }

  /** Run `fn` as a request answering on a later microtask. */
  public request<T>(fn: (records: Map<string, unknown>) => T): FakeRequest<T> {
    const request: FakeRequest<T> = { result: undefined as unknown as T, error: null, onsuccess: null, onerror: null };
    this.pending++;
    queueMicrotask(() => {
      try {
        request.result = fn(this.records);
        request.onsuccess?.call(request);
      } catch (error) {
        request.error = error as Error;
        request.onerror?.call(request);
        this.abort(error as Error);
      }
      this.pending--;
      queueMicrotask(() => this.settle());
    });
    return request;
  }

  public write(): void {
    if (this.mode !== 'readwrite') throw new Error('ReadOnlyError');
  }

  public abort(error: Error | null = null): void {
    if (this.done) return;
    this.done = true;
    this.error = error;
    this.onabort?.call(this);
  }

  private settle(): void {
    if (this.done || this.pending > 0) return;
    this.done = true;
    this.oncomplete?.call(this);
  }
}

interface FakeCursor { key: string; value: unknown; continue(): void }

export class FakeObjectStore {
  public constructor(private readonly tx: FakeTransaction) {}

  public get(key: string): FakeRequest<unknown> { return this.tx.request(records => records.get(key)); }

  public put(value: unknown, key: string): FakeRequest<string> {
    this.tx.write();
    return this.tx.request(records => { records.set(key, structuredClone(value)); return key; });
  }

  public delete(key: string): FakeRequest<undefined> {
    this.tx.write();
    return this.tx.request(records => { records.delete(key); return undefined; });
  }

  public openCursor(): FakeRequest<FakeCursor | null> {
    const request: FakeRequest<FakeCursor | null> = { result: null, error: null, onsuccess: null, onerror: null };
    let keys: string[] | null = null;
    let at = 0;
    // Each step is a request of the transaction, so it stays open while the cursor walks.
    const advance = (): void => {
      const step = this.tx.request<FakeCursor | null>(records => {
        keys ??= [...records.keys()].sort();
        while (at < keys.length && !records.has(keys[at])) at++;
        if (at >= keys.length) return null;
        const key = keys[at++];
        return { key, value: records.get(key), continue: advance };
      });
      step.onsuccess = () => { request.result = step.result; request.onsuccess?.call(request); };
    };
    advance();
    return request;
  }
}
