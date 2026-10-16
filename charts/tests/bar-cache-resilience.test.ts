import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { BarsPageRequest, BarsRequest, DataFeed } from '../src/feed/types';
import {
  BAR_CACHE_VERSION,
  barCacheKey,
  type BarCacheStore,
  type CachedBars,
  withBarCache,
} from '../src/feed/cache';

const T0 = 1_700_000_000;
const REQ: BarsRequest = {
  symbol: 'RELIANCE',
  exchange: 'NSE',
  interval: '1m',
  from: T0,
  to: T0 + 180,
};

function makeBars(start = T0, count = 3): Bar[] {
  return Array.from({ length: count }, (_, index) => ({
    time: start + index * 60,
    open: 100 + index,
    high: 101 + index,
    low: 99 + index,
    close: 100.5 + index,
    volume: index * 10,
  }));
}

function entry(overrides: Partial<CachedBars> = {}): CachedBars {
  return {
    version: BAR_CACHE_VERSION,
    bars: makeBars(),
    from: T0,
    to: T0 + 179,
    storedAt: (T0 + 180) * 1000,
    nextClose: T0 + 240,
    ...overrides,
  };
}

class WorkingStore implements BarCacheStore {
  public readonly values = new Map<string, CachedBars>();
  public get(key: string): CachedBars | undefined { return this.values.get(key); }
  public set(key: string, value: CachedBars): void { this.values.set(key, value); }
  public delete(key: string): void { this.values.delete(key); }
}

class Feed implements DataFeed {
  public calls = 0;
  public bars = makeBars();
  public async getBars(): Promise<Bar[]> {
    this.calls++;
    return this.bars.map((bar) => ({ ...bar }));
  }
}

describe('BarCache storage resilience', () => {
  it('uses network and bounded memory when durable reads reject', async () => {
    const feed = new Feed();
    const store: BarCacheStore = {
      get: async () => { throw new Error('storage denied'); },
      set: () => {},
      delete: () => {},
    };
    const cache = withBarCache(feed, {
      storage: store,
      max: 1,
      now: () => (T0 + 180) * 1000,
    });

    expect(await cache.getBars(REQ)).toEqual(makeBars());
    expect(await cache.getBars(REQ)).toEqual(makeBars());
    expect(feed.calls).toBe(1);

    await cache.getBars({ ...REQ, symbol: 'TCS' });
    expect(cache.stats()).toMatchObject({ entries: 1, bars: 3 });
    await cache.getBars(REQ);
    expect(feed.calls).toBe(3);
  });

  it('returns successful network bars and retains them in memory when durable writes reject', async () => {
    const feed = new Feed();
    const store: BarCacheStore = {
      get: () => undefined,
      set: async () => { throw new Error('quota exceeded'); },
      delete: () => {},
    };
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 180) * 1000 });

    expect(await cache.getBars(REQ)).toEqual(makeBars());
    expect(await cache.getBars(REQ)).toEqual(makeBars());
    expect(feed.calls).toBe(1);
    expect(cache.stats()).toMatchObject({ entries: 1, bars: 3, hits: 1 });
  });

  it('keeps failed deletion nonfatal and does not resurrect the durable entry', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    let failDelete = false;
    store.delete = async () => {
      if (failDelete) throw new Error('delete denied');
    };
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 180) * 1000 });

    await cache.getBars(REQ);
    failDelete = true;
    await expect(cache.invalidate(REQ)).resolves.toBeUndefined();
    feed.bars = makeBars().map((bar) => ({ ...bar, close: bar.close + 20 }));

    const refreshed = await cache.getBars(REQ);
    expect(feed.calls).toBe(2);
    expect(refreshed[0].close).toBe(120.5);
  });
});

describe('BarCache durable entry validation', () => {
  it('retains real zero and missing open interest through durable reads', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    const saved = entry();
    saved.bars[0].oi = 150;
    saved.bars[2].oi = 0;
    store.values.set(barCacheKey(REQ), saved);
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 180) * 1000 });
    expect((await cache.getCachedBars(REQ))?.map(bar => bar.oi)).toEqual([150, undefined, 0]);
    expect(feed.calls).toBe(0);
  });

  it('accepts a structurally valid legacy entry without a version', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    const legacy = entry();
    delete legacy.version;
    store.values.set(barCacheKey(REQ), legacy);
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 180) * 1000 });

    expect(await cache.getCachedBars(REQ)).toEqual(makeBars());
    expect(feed.calls).toBe(0);
  });

  it.each([
    ['unknown version', entry({ version: BAR_CACHE_VERSION + 1 }), REQ],
    ['non-array bars', entry({ bars: 'broken' as unknown as Bar[] }), REQ],
    ['non-finite bar data', entry({ bars: [{ ...makeBars()[0], close: Number.NaN }] }), REQ],
    ['non-finite open interest', entry({ bars: makeBars().map((bar, i) => i === 0 ? { ...bar, oi: Number.NaN } : bar) }), REQ],
    ['descending bar times', entry({ bars: makeBars().reverse() }), REQ],
    ['non-finite coverage', entry({ from: Number.NaN }), REQ],
    ['a future storage timestamp', entry({ storedAt: (T0 + 181) * 1000 }), REQ],
    ['bar outside coverage', entry({ to: T0 + 59 }), { ...REQ, to: T0 + 59 }],
    ['invalid next close', entry({ nextClose: T0 + 179 }), { ...REQ, to: T0 + 120 }],
  ])('rejects %s and fetches usable network bars', async (_label, invalid, request) => {
    const feed = new Feed();
    const store = new WorkingStore();
    store.values.set(barCacheKey(REQ), invalid);
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 180) * 1000 });

    const expected = makeBars().filter((bar) => bar.time <= request.to!);
    feed.bars = expected;
    expect(await cache.getCachedBars(request)).toBeUndefined();
    expect(await cache.getBars(request)).toEqual(expected);
    expect(feed.calls).toBe(1);
    expect(store.values.get(barCacheKey(REQ))?.version).toBe(BAR_CACHE_VERSION);
  });

  it('rejects a durable snapshot containing a forming bar', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    const forming = makeBars(T0, 4);
    store.values.set(barCacheKey(REQ), entry({
      bars: forming,
      to: T0 + 180,
      nextClose: T0 + 300,
    }));
    const cache = withBarCache(feed, { storage: store, now: () => (T0 + 210) * 1000 });

    expect(await cache.getCachedBars(REQ)).toBeUndefined();
    expect(feed.calls).toBe(0);
  });

  it('rejects an oversized durable snapshot instead of exceeding the memory budget', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    store.values.set(barCacheKey(REQ), entry({
      bars: makeBars(T0, 4),
      to: T0 + 239,
      nextClose: T0 + 300,
    }));
    const cache = withBarCache(feed, {
      storage: store,
      maxBars: 3,
      now: () => (T0 + 240) * 1000,
    });

    expect(await cache.getCachedBars({ ...REQ, to: T0 + 239 })).toBeUndefined();
    expect(cache.stats()).toMatchObject({ entries: 0, bars: 0 });
  });
});

describe('BarCache cached snapshot reads', () => {
  it('reads a cloned closed snapshot without fetching and honours range coverage', async () => {
    const feed = new Feed();
    const cache = withBarCache(feed, { now: () => (T0 + 180) * 1000 });

    expect(await cache.getCachedBars(REQ)).toBeUndefined();
    expect(feed.calls).toBe(0);
    await cache.getBars(REQ);
    const warm = await cache.getCachedBars({ ...REQ, from: T0 + 60, to: T0 + 120 });
    expect(warm?.map((bar) => bar.time)).toEqual([T0 + 60, T0 + 120]);
    warm![0].close = -1;
    expect((await cache.getCachedBars(REQ))?.[1].close).toBe(101.5);
    expect(feed.calls).toBe(1);
  });

  it('returns retained overlap for warm paint while normal hits require current coverage', async () => {
    const feed = new Feed();
    let nowMs = (T0 + 180) * 1000;
    const cache = withBarCache(feed, { ttlMs: 10 * 60_000, now: () => nowMs });
    await cache.getBars(REQ);
    nowMs = (T0 + 300) * 1000;

    const warm = await cache.getCachedBars({ ...REQ, from: T0 - 60, to: T0 + 300 });
    expect(warm).toEqual(makeBars());
    expect(feed.calls).toBe(1);

    await cache.getBars({ ...REQ, from: T0 - 60, to: T0 + 300 });
    expect(feed.calls).toBe(2);
  });
});

describe('BarCache cancellation and forwarding', () => {
  it('does not call the source when already aborted', async () => {
    const feed = new Feed();
    const controller = new AbortController();
    controller.abort();
    const cache = withBarCache(feed);

    await expect(cache.getBars({ ...REQ, signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(feed.calls).toBe(0);
  });

  it('rejects an obsolete completion before publishing or caching it', async () => {
    let resolveFetch: ((bars: Bar[]) => void) | undefined;
    let markStarted: (() => void) | undefined;
    const started = new Promise<void>((resolve) => { markStarted = resolve; });
    const source: DataFeed = {
      getBars: () => new Promise<Bar[]>((resolve) => {
        resolveFetch = resolve;
        markStarted!();
      }),
    };
    const store = new WorkingStore();
    const controller = new AbortController();
    const cache = withBarCache(source, { storage: store, now: () => (T0 + 180) * 1000 });
    const pending = cache.getBars({ ...REQ, signal: controller.signal });

    await started;
    controller.abort();
    resolveFetch!(makeBars());
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(store.values.size).toBe(0);
    expect(cache.stats()).toMatchObject({ entries: 0, bars: 0 });
  });

  it('checks cancellation again immediately before writing the snapshot', async () => {
    const feed = new Feed();
    const store = new WorkingStore();
    const controller = new AbortController();
    const cache = withBarCache(feed, {
      storage: store,
      now: () => (T0 + 180) * 1000,
      barCloses: (_interval, time) => {
        controller.abort();
        return time + 60;
      },
    });

    await expect(cache.getBars({ ...REQ, signal: controller.signal })).rejects.toMatchObject({ name: 'AbortError' });
    expect(store.values.size).toBe(0);
    expect(cache.stats()).toMatchObject({ entries: 0, bars: 0 });
  });

  it('does not let an older aborted write erase a newer snapshot', async () => {
    const older = makeBars().map((bar) => ({ ...bar, close: bar.close + 10 }));
    const newer = makeBars().map((bar) => ({ ...bar, close: bar.close + 20 }));
    let fetchCount = 0;
    const source: DataFeed = {
      getBars: async () => (++fetchCount === 1 ? older : newer),
    };
    const values = new Map<string, CachedBars>();
    let releaseOlderWrite: (() => void) | undefined;
    let markOlderWriteStarted: (() => void) | undefined;
    const olderWriteStarted = new Promise<void>((resolve) => { markOlderWriteStarted = resolve; });
    const store: BarCacheStore = {
      get: (key) => values.get(key),
      set: async (key, value) => {
        if (value.bars[0].close === 110.5) {
          markOlderWriteStarted!();
          await new Promise<void>((resolve) => { releaseOlderWrite = resolve; });
        }
        values.set(key, value);
      },
      delete: (key) => { values.delete(key); },
    };
    const controller = new AbortController();
    const cache = withBarCache(source, { storage: store, now: () => (T0 + 180) * 1000 });

    const oldRequest = cache.getBars({ ...REQ, noCache: true, signal: controller.signal });
    await olderWriteStarted;
    controller.abort();
    await expect(cache.getBars({ ...REQ, noCache: true })).resolves.toEqual(newer);
    releaseOlderWrite!();
    await expect(oldRequest).rejects.toMatchObject({ name: 'AbortError' });

    expect(await cache.getCachedBars(REQ)).toEqual(newer);
    expect(values.get(barCacheKey(REQ))?.bars).toEqual(newer);
  });

  it('forwards pagination only when the source provides it', async () => {
    const historyOnly = withBarCache(new Feed());
    expect(historyOnly.getBarsPage).toBeUndefined();

    const seen: BarsPageRequest[] = [];
    const source: DataFeed = {
      getBars: async () => [],
      getBarsPage: async (req) => {
        seen.push(req);
        return { bars: makeBars(), hasMore: false, nextBefore: T0 };
      },
    };
    const cache = withBarCache(source);
    const request: BarsPageRequest = { ...REQ, before: T0, countBack: 3 };

    await expect(cache.getBarsPage!(request)).resolves.toMatchObject({ hasMore: false, nextBefore: T0 });
    expect(seen).toEqual([request]);
  });
});
