import { describe, it, expect } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { BarsRequest, DataFeed, UnsubscribeFn } from '../src/feed/types';
import {
  withBarCache,
  barCacheKey,
  barCloseSec,

  type BarCacheStore,
  type CachedBars,
} from '../src/feed/cache';
import { registerInterval } from '../src/feed/intervals';

const T0 = 1_700_000_000; // arbitrary round epoch, UTC seconds
const MIN = 60;

function makeBars(start: number, count: number, intervalSec = MIN): Bar[] {
  const bars: Bar[] = [];
  for (let i = 0; i < count; i++) {
    const t = start + i * intervalSec;
    bars.push({ time: t, open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 10 * i });
  }
  return bars;
}

/** History-only stub feed that counts calls and honours the requested range. */
class StubFeed implements DataFeed {
  public calls: BarsRequest[] = [];
  public bars: Bar[] = [];
  public error: Error | null = null;

  public constructor(bars: Bar[] = []) {
    this.bars = bars;
  }

  public get count(): number {
    return this.calls.length;
  }

  public async getBars(req: BarsRequest): Promise<Bar[]> {
    this.calls.push({ ...req });
    if (this.error !== null) throw this.error;
    return this.bars
      .filter((b) => (req.from === undefined || b.time >= req.from) && (req.to === undefined || b.time <= req.to))
      .map((b) => ({ ...b }));
  }
}

/** Live stub: same, plus the optional subscription methods. */
class LiveStubFeed extends StubFeed {
  public subscribed = 0;
  public subscribeBars(_req: BarsRequest, _onBar: (bar: Bar) => void): UnsubscribeFn {
    this.subscribed++;
    return () => { this.subscribed--; };
  }
}

/** Async store that records every call, standing in for IndexedDB. */
class RecordingStore implements BarCacheStore {
  public readonly map = new Map<string, CachedBars>();
  public gets: string[] = [];
  public sets: string[] = [];
  public deletes: string[] = [];

  public async get(key: string): Promise<CachedBars | undefined> {
    this.gets.push(key);
    return this.map.get(key);
  }
  public async set(key: string, value: CachedBars): Promise<void> {
    this.sets.push(key);
    // Round-trip through JSON: proves the entry is persistable as-is.
    this.map.set(key, JSON.parse(JSON.stringify(value)) as CachedBars);
  }
  public async delete(key: string): Promise<void> {
    this.deletes.push(key);
    this.map.delete(key);
  }
}

const REQ: BarsRequest = { symbol: 'RELIANCE', exchange: 'NSE', interval: '1m', from: T0, to: T0 + 3600 };

/** 60 closed 1m bars, T0 .. T0+3540; the last one closes exactly at T0+3600. */
function closedSetup(overrides: { ttlMs?: number; max?: number; maxBars?: number; nowSec?: number } = {}) {
  const feed = new StubFeed(makeBars(T0, 60));
  let nowMs = (overrides.nowSec ?? T0 + 3600) * 1000;
  const cache = withBarCache(feed, {
    ttlMs: overrides.ttlMs ?? 10_000,
    max: overrides.max,
    maxBars: overrides.maxBars,
    now: () => nowMs,
  });
  return { feed, cache, advance: (sec: number) => { nowMs += sec * 1000; }, nowMs: () => nowMs };
}

describe('barCloseSec', () => {
  it('closes a fixed interval one span after the bar opens', () => {
    // One span after the bar OPENS, whatever the epoch grid says. T0 is 20s into
    // a minute, which is what a session-anchored feed looks like, and answering
    // from the grid there would report the bar closing 40s early.
    expect(barCloseSec('1m', T0)).toBe(T0 + 60);
    expect(barCloseSec('5m', T0)).toBe(T0 + 300);
    expect(barCloseSec('1h', T0)).toBe(T0 + 3600);
  });

  it('closes a registered calendar bar on the real boundary, not an average month', () => {
    // February 2024 is a leap month: 29 days, not the 30 an averaged span
    // assumes, and January is 31. A fixed duration is wrong for both.
    const dispose = registerInterval({
      code: 'MO',
      bucketing: { mode: 'calendar', unit: 'month', count: 1, timezone: 'UTC' },
    });
    try {
      const jan = Date.UTC(2024, 0, 1) / 1000;
      const feb = Date.UTC(2024, 1, 1) / 1000;
      expect(barCloseSec('MO', jan, 'UTC')).toBe(feb);
      expect(barCloseSec('MO', jan, 'UTC')! - jan).toBe(31 * 86_400);
      expect(barCloseSec('MO', feb, 'UTC')! - feb).toBe(29 * 86_400);
    } finally {
      dispose();
    }
  });

  it('refuses upper-case M rather than reading it as minutes', () => {
    // Every terminal reads lower-case m as minutes and upper-case M as a month.
    // Folding the two made a monthly bar close every sixty seconds.
    expect(barCloseSec('M', T0)).toBeNull();
    expect(barCloseSec('1M', T0)).toBeNull();
    expect(barCloseSec('1m', Math.floor(T0 / 60) * 60)).toBe(Math.floor(T0 / 60) * 60 + 60);
  });

  it('returns null rather than guessing, which is what the old parser got wrong', () => {
    // An unregistered code used to resolve to 60 seconds, so a cache keyed on it
    // served a stale tail for a minute at a time.
    expect(barCloseSec('renko-10', T0)).toBeNull();
    expect(barCloseSec('not-an-interval', T0)).toBeNull();
  });
});

describe('barCacheKey', () => {
  it('separates symbol, exchange and interval', () => {
    expect(barCacheKey({ symbol: 'X', exchange: 'NSE', interval: '5m' })).toBe('X|NSE|5m');
    expect(barCacheKey({ symbol: 'X', exchange: 'BSE', interval: '5m' }))
      .not.toBe(barCacheKey({ symbol: 'X', exchange: 'NSE', interval: '5m' }));
  });
});

describe('BarCache hit and miss', () => {
  it('serves a repeat request without touching the network', async () => {
    const { feed, cache } = closedSetup();
    const first = await cache.getBars(REQ);
    expect(feed.count).toBe(1);
    const second = await cache.getBars(REQ);
    expect(feed.count).toBe(1);
    expect(second).toEqual(first);
    expect(cache.stats()).toMatchObject({ hits: 1, misses: 1, entries: 1 });
  });

  it('misses on a different symbol, exchange or interval', async () => {
    const { feed, cache } = closedSetup();
    await cache.getBars(REQ);
    await cache.getBars({ ...REQ, symbol: 'TCS' });
    expect(feed.count).toBe(2);
    await cache.getBars({ ...REQ, exchange: 'BSE' });
    expect(feed.count).toBe(3);
    await cache.getBars({ ...REQ, interval: '5m' });
    expect(feed.count).toBe(4);
  });

  it('expires on TTL', async () => {
    const { feed, cache, advance } = closedSetup({ ttlMs: 10_000 });
    await cache.getBars(REQ);
    advance(9);
    await cache.getBars(REQ);
    expect(feed.count).toBe(1);
    advance(2); // 11s total, past the 10s TTL
    await cache.getBars(REQ);
    expect(feed.count).toBe(2);
  });

  it('does not cache an empty result', async () => {
    const feed = new StubFeed([]);
    const cache = withBarCache(feed, { now: () => (T0 + 3600) * 1000 });
    expect(await cache.getBars(REQ)).toEqual([]);
    await cache.getBars(REQ);
    expect(feed.count).toBe(2);
    expect(cache.stats().entries).toBe(0);
  });
});

describe('BarCache range coverage', () => {
  it('satisfies a narrower request from a wider cached range', async () => {
    const { feed, cache } = closedSetup();
    await cache.getBars(REQ);
    const narrow = await cache.getBars({ ...REQ, from: T0 + 600, to: T0 + 1200 });
    expect(feed.count).toBe(1);
    expect(narrow.map((b) => b.time)).toEqual([T0 + 600, T0 + 660, T0 + 720, T0 + 780, T0 + 840, T0 + 900,
      T0 + 960, T0 + 1020, T0 + 1080, T0 + 1140, T0 + 1200]);
  });

  it('misses when the request reaches further back than the cached range', async () => {
    const { feed, cache } = closedSetup();
    await cache.getBars({ ...REQ, from: T0 + 600 });
    await cache.getBars({ ...REQ, from: T0 });
    expect(feed.count).toBe(2);
  });

  it('misses when the request reaches past a bar that has since closed', async () => {
    const { feed, cache, advance } = closedSetup({ ttlMs: 10 * 60_000 });
    await cache.getBars(REQ); // covers through T0+3599
    advance(59); // still inside the forming T0+3600 bar
    await cache.getBars({ ...REQ, to: T0 + 3659 });
    expect(feed.count).toBe(1);
    advance(1); // the T0+3600 bar has now closed: a fresh fetch would return more
    await cache.getBars({ ...REQ, to: T0 + 3660 });
    expect(feed.count).toBe(2);
  });

  it('serves a request that ends inside the cached range regardless of the clock', async () => {
    const { feed, cache, advance } = closedSetup({ ttlMs: 60 * 60_000 });
    await cache.getBars(REQ);
    advance(600); // ten new bars would exist by now
    await cache.getBars({ ...REQ, to: T0 + 1200 }); // but this range is fully closed history
    expect(feed.count).toBe(1);
  });
});

describe('BarCache forming bar rule', () => {
  it('never stores or serves the currently forming bar', async () => {
    // 61 bars: T0 .. T0+3600. At T0+3630 the last one is still forming.
    const feed = new StubFeed(makeBars(T0, 61));
    let nowMs = (T0 + 3630) * 1000;
    const cache = withBarCache(feed, { ttlMs: 10 * 60_000, now: () => nowMs });

    const live = await cache.getBars(REQ);
    expect(live[live.length - 1].time).toBe(T0 + 3600); // the feed's own answer includes it

    // The forming bar moves. A cache that served its old close would paint a
    // frozen candle; this one has not kept it at all.
    feed.bars[60] = { ...feed.bars[60], close: 999, high: 1000 };
    const warm = await cache.getBars(REQ);
    expect(feed.count).toBe(1); // still a hit
    expect(warm[warm.length - 1].time).toBe(T0 + 3540);
    expect(warm.some((b) => b.close === 999)).toBe(false);

    // Once that bar closes, the entry no longer covers what is available.
    nowMs = (T0 + 3661) * 1000;
    const refetched = await cache.getBars({ ...REQ, to: T0 + 3661 });
    expect(feed.count).toBe(2);
    expect(refetched[refetched.length - 1].close).toBe(999);
  });

  it('caches nothing when every returned bar is still forming', async () => {
    const feed = new StubFeed(makeBars(T0 + 3600, 1));
    const cache = withBarCache(feed, { now: () => (T0 + 3630) * 1000 });
    await cache.getBars({ ...REQ, from: T0 + 3600, to: T0 + 3660 });
    await cache.getBars({ ...REQ, from: T0 + 3600, to: T0 + 3660 });
    expect(feed.count).toBe(2);
    expect(cache.stats().entries).toBe(0);
  });
});

describe('BarCache bounds', () => {
  it('evicts the least recently used entry over the entry cap', async () => {
    const { feed, cache } = closedSetup({ max: 2 });
    await cache.getBars({ ...REQ, symbol: 'A' });
    await cache.getBars({ ...REQ, symbol: 'B' });
    await cache.getBars({ ...REQ, symbol: 'A' }); // A is now the most recent
    expect(feed.count).toBe(2);
    await cache.getBars({ ...REQ, symbol: 'C' }); // evicts B
    expect(cache.stats()).toMatchObject({ entries: 2, evictions: 1 });
    await cache.getBars({ ...REQ, symbol: 'A' });
    expect(feed.count).toBe(3); // A survived
    await cache.getBars({ ...REQ, symbol: 'B' });
    expect(feed.count).toBe(4); // B was evicted
  });

  it('evicts on the total bar cap, not just the entry count', async () => {
    const { feed, cache } = closedSetup({ max: 10, maxBars: 100 });
    await cache.getBars({ ...REQ, symbol: 'A' }); // 60 bars
    expect(cache.stats().bars).toBe(60);
    await cache.getBars({ ...REQ, symbol: 'B' }); // 120 > 100, so A goes
    expect(cache.stats()).toMatchObject({ entries: 1, bars: 60, evictions: 1 });
    await cache.getBars({ ...REQ, symbol: 'A' });
    expect(feed.count).toBe(3);
  });

  it('refuses to cache a single series larger than the whole budget', async () => {
    const { cache } = closedSetup({ maxBars: 10 });
    await cache.getBars(REQ);
    expect(cache.stats()).toMatchObject({ entries: 0, evictions: 0 });
  });
});

describe('BarCache injected storage', () => {
  it('reads and writes through the injected store', async () => {
    const store = new RecordingStore();
    const feed = new StubFeed(makeBars(T0, 60));
    const cache = withBarCache(feed, { storage: store, ttlMs: 10_000, now: () => (T0 + 3600) * 1000 });
    await cache.getBars(REQ);
    expect(store.sets).toEqual(['RELIANCE|NSE|1m']);
    await cache.getBars(REQ);
    expect(feed.count).toBe(1);
    expect(store.gets.length).toBe(2);
    expect(store.map.get('RELIANCE|NSE|1m')?.bars.length).toBe(60);
  });

  it('warm-loads from a store filled by an earlier session', async () => {
    const store = new RecordingStore();
    const previous = new StubFeed(makeBars(T0, 60));
    const first = withBarCache(previous, { storage: store, ttlMs: 60_000, now: () => (T0 + 3600) * 1000 });
    await first.getBars(REQ);

    // New process, new cache instance, same store. No network at all.
    const feed = new StubFeed(makeBars(T0, 60));
    const second = withBarCache(feed, { storage: store, ttlMs: 60_000, now: () => (T0 + 3610) * 1000 });
    const bars = await second.getBars(REQ);
    expect(feed.count).toBe(0);
    expect(bars.length).toBe(60);
  });

  it('deletes an expired entry from the store rather than leaving it', async () => {
    const store = new RecordingStore();
    const feed = new StubFeed(makeBars(T0, 60));
    let nowMs = (T0 + 3600) * 1000;
    const cache = withBarCache(feed, { storage: store, ttlMs: 10_000, now: () => nowMs });
    await cache.getBars(REQ);
    nowMs += 11_000;
    await cache.getBars(REQ);
    expect(store.deletes).toContain('RELIANCE|NSE|1m');
  });
});

describe('BarCache failure handling', () => {
  it('does not cache anything when the fetch rejects', async () => {
    const feed = new StubFeed(makeBars(T0, 60));
    feed.error = new Error('network down');
    const cache = withBarCache(feed, { now: () => (T0 + 3600) * 1000 });
    await expect(cache.getBars(REQ)).rejects.toThrow('network down');
    expect(cache.stats().entries).toBe(0);
    feed.error = null;
    expect((await cache.getBars(REQ)).length).toBe(60);
    expect(feed.count).toBe(2);
  });

  it('leaves a good entry intact when a later forced fetch fails', async () => {
    const feed = new StubFeed(makeBars(T0, 60));
    const cache = withBarCache(feed, { ttlMs: 10 * 60_000, now: () => (T0 + 3600) * 1000 });
    await cache.getBars(REQ);
    feed.error = new Error('network down');
    await expect(cache.getBars({ ...REQ, noCache: true })).rejects.toThrow('network down');
    feed.error = null;
    const bars = await cache.getBars(REQ);
    expect(bars.length).toBe(60);
    expect(feed.count).toBe(2); // the initial fill and the failed forced fetch
  });
});

describe('BarCache opt-out and invalidation', () => {
  it('noCache always fetches and refreshes the entry', async () => {
    const { feed, cache } = closedSetup({ ttlMs: 10 * 60_000 });
    await cache.getBars(REQ);
    feed.bars = makeBars(T0, 60).map((b) => ({ ...b, close: b.close + 5 }));
    await cache.getBars({ ...REQ, noCache: true });
    expect(feed.count).toBe(2);
    const after = await cache.getBars(REQ); // served from the refreshed entry
    expect(feed.count).toBe(2);
    expect(after[0].close).toBe(feed.bars[0].close);
  });

  it('invalidate drops one series and clear drops all of them', async () => {
    const { feed, cache } = closedSetup({ ttlMs: 10 * 60_000 });
    await cache.getBars({ ...REQ, symbol: 'A' });
    await cache.getBars({ ...REQ, symbol: 'B' });
    await cache.invalidate({ symbol: 'A', exchange: 'NSE', interval: '1m' });
    expect(cache.stats().entries).toBe(1);
    await cache.getBars({ ...REQ, symbol: 'A' });
    expect(feed.count).toBe(3);
    await cache.getBars({ ...REQ, symbol: 'B' });
    expect(feed.count).toBe(3);
    await cache.clear();
    expect(cache.stats().entries).toBe(0);
    await cache.getBars({ ...REQ, symbol: 'B' });
    expect(feed.count).toBe(4);
  });

  it('passes an open-ended request straight through, uncached', async () => {
    const { feed, cache } = closedSetup();
    await cache.getBars({ symbol: 'RELIANCE', exchange: 'NSE', interval: '1m' });
    await cache.getBars({ symbol: 'RELIANCE', exchange: 'NSE', interval: '1m' });
    expect(feed.count).toBe(2);
    expect(cache.stats().entries).toBe(0);
  });

  it('a barCloses override returning null opts that interval out', async () => {
    const feed = new StubFeed(makeBars(T0, 60));
    const cache = withBarCache(feed, {
      now: () => (T0 + 3600) * 1000,
      barCloses: (i: string, t: number) => (i === '1m' ? null : t + 60),
    });
    await cache.getBars(REQ);
    await cache.getBars(REQ);
    expect(feed.count).toBe(2);
  });

  it('refuses to cache a series whose bars have no knowable close', async () => {
    // A tick-count series is the real case: a 500-tick bar may run a second or an
    // hour, so nothing about elapsed time says the last one is complete. The old
    // parser answered 60 seconds and cached it anyway.
    const feed = new StubFeed(makeBars(T0, 60));
    const cache = withBarCache(feed, { now: () => (T0 + 3600) * 1000 });
    await cache.getBars({ ...REQ, interval: 'T500' });
    await cache.getBars({ ...REQ, interval: 'T500' });
    expect(feed.count).toBe(2);
    expect(cache.stats().entries).toBe(0);
  });
});

describe('BarCache isolation and passthrough', () => {
  it('hands out copies so a caller mutating a hit cannot corrupt the cache', async () => {
    const { cache } = closedSetup({ ttlMs: 10 * 60_000 });
    await cache.getBars(REQ); // fill
    const hit = await cache.getBars(REQ);
    hit[0].close = -1; // a live chart mutates its last bar in place; so might any caller
    hit.length = 1;
    const again = await cache.getBars(REQ);
    expect(again.length).toBe(60);
    expect(again[0].close).toBe(100.5);
  });

  it('stores copies so the wrapped feed mutating its own bars cannot corrupt the cache', async () => {
    // A feed that hands back the very objects it keeps, as a live builder does.
    const held = makeBars(T0, 60);
    const feed: DataFeed = {
      getBars: async (req) => held.filter((b) => b.time >= req.from! && b.time <= req.to!),
    };
    const cache = withBarCache(feed, { ttlMs: 10 * 60_000, now: () => (T0 + 3600) * 1000 });
    await cache.getBars(REQ);
    held[0].close = -1;
    const hit = await cache.getBars(REQ);
    expect(hit[0].close).toBe(100.5);
  });

  it('exposes subscribeBars only when the wrapped feed has it', async () => {
    const historyOnly = withBarCache(new StubFeed());
    expect(historyOnly.subscribeBars).toBeUndefined();

    const live = new LiveStubFeed();
    const wrapped = withBarCache(live);
    expect(typeof wrapped.subscribeBars).toBe('function');
    const off = wrapped.subscribeBars!(REQ, () => {});
    expect(live.subscribed).toBe(1);
    off();
    expect(live.subscribed).toBe(0);
    expect(wrapped.source).toBe(live);
  });
});
