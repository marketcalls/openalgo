/**
 * An asynchronous widget store in memory, for tests of the widget and the
 * chart grid over a store whose answers arrive later, in an order the test
 * decides.
 */
import type { AsyncStorageLike, StorageLike } from '../../src/widget/index';

/**
 * An asynchronous store in memory. Each call answers on a later microtask,
 * or waits for `release()` while `hold` is on, so a test decides the order
 * in which the store's answers arrive.
 */
export class FakeAsyncStore implements AsyncStorageLike {
  public readonly map = new Map<string, string>();
  public readonly calls: string[] = [];
  public journal: StorageLike | null = null;
  public hold = false;
  public failEntries: Error | null = null;
  public failWrites: Error | null = null;
  public silent = false;
  /** Who listens for the changes other users of the store make. */
  public readonly listeners = new Set<(key: string, value: string | null) => void>();
  private readonly held: Array<() => void> = [];

  public entries(prefix: string): Promise<Array<[string, string]>> {
    this.calls.push(`entries ${prefix}`);
    return this.answer(() => {
      if (this.failEntries !== null) throw this.failEntries;
      return [...this.map].filter(([k]) => k.startsWith(prefix));
    });
  }

  public setItem(key: string, value: string): Promise<void> {
    this.calls.push(`set ${key} ${value}`);
    return this.answer(() => {
      if (this.failWrites !== null) throw this.failWrites;
      this.map.set(key, value);
    });
  }

  public removeItem(key: string): Promise<void> {
    this.calls.push(`remove ${key}`);
    return this.answer(() => {
      if (this.failWrites !== null) throw this.failWrites;
      this.map.delete(key);
    });
  }

  public subscribe(listener: (key: string, value: string | null) => void): () => void {
    this.listeners.add(listener);
    return () => { this.listeners.delete(listener); };
  }

  /** Another tab writing to the store: the value lands, and every listener hears of it. */
  public external(key: string, value: string | null): void {
    if (value === null) this.map.delete(key);
    else this.map.set(key, value);
    for (const listener of [...this.listeners]) listener(key, value);
  }

  /** Answer the calls held so far, in the order they were made. */
  public release(): void { for (const run of this.held.splice(0)) run(); }

  public writes(): string[] { return this.calls.filter(c => !c.startsWith('entries')); }

  private answer<T>(fn: () => T): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      const run = (): void => { try { resolve(fn()); } catch (error) { reject(error); } };
      if (this.silent) return;
      if (this.hold) this.held.push(run);
      else queueMicrotask(run);
    });
  }
}

/** Let every queued microtask, and the ones they queue, run. */
export const settle = async (): Promise<void> => { for (let i = 0; i < 30; i++) await Promise.resolve(); };
