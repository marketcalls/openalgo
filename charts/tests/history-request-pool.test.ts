import { afterEach, describe, expect, it, vi } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { BarsPage, BarsRequest, DataFeed } from '../src/feed/types';
import { HistoryRequestPool, sharedHistoryRequests, withHistoryDeadline } from '../src/feed/request-pool';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const request: BarsRequest = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m', from: 100, to: 300 };
const bars: Bar[] = [{ time: 100, open: 23800, high: 23804, low: 23798, close: 23802, volume: 65 }];
afterEach(() => vi.useRealTimers());

describe('shared historical requests', () => {
  it('shares one request without allowing one consumer to abort another', async () => {
    const response = deferred<Bar[]>();
    let count = 0;
    let signal: AbortSignal | undefined;
    const feed: DataFeed = { getBars: req => { count++; signal = req.signal; return response.promise; } };
    const pool = sharedHistoryRequests(feed);
    expect(sharedHistoryRequests(feed)).toBe(pool);
    const cancel = new AbortController();
    const first = pool.getBars({ ...request, signal: cancel.signal });
    const second = pool.getBars(request);
    const cancelled = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    cancel.abort();
    await cancelled;
    expect(signal?.aborted).toBe(false);
    response.resolve(bars);
    expect(await second).toEqual(bars);
    expect(count).toBe(1);
  });

  it('keeps different feeds and authoritative refreshes separate', async () => {
    let normal = 0;
    let other = 0;
    const a = sharedHistoryRequests({ getBars: async () => { normal++; return bars; } });
    const b = sharedHistoryRequests({ getBars: async () => { other++; return []; } });
    await Promise.all([a.getBars(request), a.getBars({ ...request, noCache: true }), b.getBars(request)]);
    expect(normal).toBe(2);
    expect(other).toBe(1);
  });

  it('aborts the source after its last consumer leaves and frees a stalled slot', async () => {
    let calls = 0;
    let firstSignal: AbortSignal | undefined;
    const pool = new HistoryRequestPool({ getBars: req => {
      calls++;
      if (calls === 1) { firstSignal = req.signal; return new Promise(() => {}); }
      return Promise.resolve(bars);
    } }, { maxConcurrent: 1 });
    const cancel = new AbortController();
    const first = pool.getBars({ ...request, signal: cancel.signal });
    const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const next = pool.getBars({ ...request, symbol: 'BANKNIFTY' });
    cancel.abort();
    await rejected;
    expect(firstSignal?.aborted).toBe(true);
    expect(await next).toEqual(bars);
  });

  it('prioritizes visible history over queued pagination and respects concurrency', async () => {
    const first = deferred<Bar[]>();
    const seen: string[] = [];
    const pool = new HistoryRequestPool({ getBars: req => {
      seen.push(req.symbol);
      return req.symbol === 'first' ? first.promise : Promise.resolve(bars);
    } }, { maxConcurrent: 1 });
    const active = pool.getBars({ ...request, symbol: 'first' });
    const low = pool.getBars({ ...request, symbol: 'older' }, 0);
    const high = pool.getBars({ ...request, symbol: 'visible' }, 10);
    expect(seen).toEqual(['first']);
    first.resolve(bars);
    await Promise.all([active, low, high]);
    expect(seen).toEqual(['first', 'visible', 'older']);
  });

  it('expires each consumer independently even while waiting in the queue', async () => {
    vi.useFakeTimers();
    const first = deferred<Bar[]>();
    const pool = new HistoryRequestPool({ getBars: () => first.promise }, { maxConcurrent: 1 });
    const active = pool.getBars({ ...request, timeoutMs: 100 });
    const queued = pool.getBars({ ...request, symbol: 'queued', timeoutMs: 10 });
    const expired = expect(queued).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(11);
    await expired;
    first.resolve(bars);
    expect(await active).toEqual(bars);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('cleans failures and returns independent snapshots to shared consumers', async () => {
    const first = deferred<Bar[]>();
    let calls = 0;
    const pool = new HistoryRequestPool({ getBars: () => {
      if (++calls === 1) throw new Error('offline');
      return first.promise;
    } });
    await expect(pool.getBars(request)).rejects.toThrow('offline');
    const a = pool.getBars(request);
    const b = pool.getBars(request);
    first.resolve(bars);
    const [one, two] = await Promise.all([a, b]);
    one[0].close = 0;
    expect(two[0].close).toBe(23802);
    expect(bars[0].close).toBe(23802);
  });

  it('shares page requests while preserving explicit exhaustion metadata', async () => {
    let calls = 0;
    const pool = new HistoryRequestPool({ getBars: async () => [], getBarsPage: async req => {
      calls++;
      expect(req.before).toBe(200);
      return { bars, hasMore: false };
    } });
    const req = { ...request, before: 200, countBack: 100 };
    expect(await Promise.all([pool.getBarsPage(req), pool.getBarsPage(req)])).toEqual([
      { bars, hasMore: false }, { bars, hasMore: false },
    ]);
    expect(calls).toBe(1);
  });
  it('preserves an undefined provider rejection and frees the queued slot', async () => {
    vi.useFakeTimers();
    const response = deferred<Bar[]>();
    const pool = new HistoryRequestPool({ getBars: req => req.symbol === request.symbol ? response.promise : Promise.resolve(bars) }, { maxConcurrent: 1 });
    let outcome: unknown = 'pending';
    const pending = pool.getBars(request).then(value => { outcome = value; }, error => { outcome = error; });
    const next = pool.getBars({ ...request, symbol: 'next' });
    response.reject(undefined);
    await Promise.resolve();
    await Promise.resolve();
    expect(outcome).toBeUndefined();
    await pending;
    expect(await next).toEqual(bars);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects malformed page results for every consumer and continues queued work', async () => {
    vi.useFakeTimers();
    const response = deferred<BarsPage>();
    const pool = new HistoryRequestPool({ getBars: async () => bars, getBarsPage: () => response.promise }, { maxConcurrent: 1 });
    const outcomes: unknown[] = [];
    const one = pool.getBarsPage({ ...request, before: 100, countBack: 10 }).catch(error => { outcomes.push(error); });
    const two = pool.getBarsPage({ ...request, before: 100, countBack: 10 }).catch(error => { outcomes.push(error); });
    const next = pool.getBars(request);
    response.resolve({ bars: null } as unknown as BarsPage);
    await Promise.resolve();
    await Promise.resolve();
    expect(outcomes).toHaveLength(2);
    expect(outcomes.every(error => error instanceof TypeError)).toBe(true);
    await Promise.all([one, two]);
    expect(await next).toEqual(bars);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('rejects undefined failures in the deadline wrapper', async () => {
    vi.useFakeTimers();
    const outcome = await withHistoryDeadline({}, () => Promise.reject(undefined)).then(
      value => ({ ok: true, value }), error => ({ ok: false, error }),
    );
    expect(outcome).toEqual({ ok: false, error: undefined });
    expect(vi.getTimerCount()).toBe(0);
  });

  it('drains a long queue of synchronous provider failures without recursion', async () => {
    const first = deferred<Bar[]>();
    let calls = 0;
    const pool = new HistoryRequestPool({ getBars: () => {
      if (calls++ === 0) return first.promise;
      throw new Error('offline');
    } }, { maxConcurrent: 1 });
    const outcomes = [pool.getBars(request)];
    for (let i = 0; i < 5000; i++) outcomes.push(pool.getBars({ ...request, symbol: String(i) }).catch(() => []));
    first.resolve(bars);
    await Promise.all(outcomes);
    expect(calls).toBe(5001);
  });

  it.each([
    { page: false, result: { bars: [] } },
    { page: true, result: [] },
    { page: false, result: [null] },
  ])('rejects a result with the wrong history shape: $page/$result', async ({ page, result }) => {
    const pool = new HistoryRequestPool({
      getBars: async () => result as unknown as Bar[],
      getBarsPage: async () => result as unknown as BarsPage,
    });
    const pending = page ? pool.getBarsPage({ ...request, before: 100, countBack: 10 }) : pool.getBars(request);
    await expect(pending).rejects.toBeInstanceOf(TypeError);
  });

  it('handles source cancellation that synchronously enqueues replacement work', async () => {
    const cancel = new AbortController();
    let replacement: Promise<Bar[]> | undefined;
    let calls = 0;
    const pool = new HistoryRequestPool({ getBars: req => {
      calls++;
      if (calls === 1) {
        req.signal?.addEventListener('abort', () => { replacement = pool.getBars(request); });
        return new Promise(() => {});
      }
      return Promise.resolve(bars);
    } }, { maxConcurrent: 1 });
    const first = pool.getBars({ ...request, signal: cancel.signal });
    const rejected = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    cancel.abort();
    await rejected;
    expect(await replacement).toEqual(bars);
    expect(calls).toBe(2);
  });

});
