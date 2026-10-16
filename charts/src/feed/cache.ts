/**
 * Warm-load bar cache: a wrapper around ANY `DataFeed`, so a custom feed gets
 * the same behaviour as `OpenAlgoDataFeed`.
 *
 *     const feed = withBarCache(new OpenAlgoDataFeed(cfg), { ttlMs: 60_000 });
 *
 * The design decisions, all of which are load-bearing:
 *
 * **Key.** `symbol | exchange | interval`, then the data variant when the
 * request names one (extended hours, raw prices): each is a separate provider
 * series, and the default variant adds nothing, so keys written before
 * variants existed still match. The requested range is deliberately
 * NOT part of the key: one entry per series holds the widest set fetched so
 * far, and a narrower request is served by slicing it. Keying on the range
 * would miss on every pan and on every "same chart, one bar later" reload,
 * which is exactly the traffic warm-load is meant to remove.
 *
 * **Freshness.** Two independent gates, both of which must pass:
 *   1. `ttlMs` bounds absolute age.
 *   2. Nothing new can have closed. An entry is complete through `to`; the next
 *      bar closes at `to + 1 + intervalSec`, measured on the feed's own bar
 *      grid rather than on UTC midnight, so a daily Indian bar opening at 03:45
 *      UTC is judged against its own session, not against the wrong boundary.
 * The effect is what you want from a warm cache: a closed session stays usable
 * for the whole TTL, while a 1m chart is only reused inside the current minute.
 *
 * **The forming bar is never cached.** A bar whose close time is still in the
 * future keeps moving, and serving yesterday's snapshot of it to a live chart
 * is worse than not caching at all: the chart would paint a frozen candle and
 * have no way to know. So the trailing forming bar is dropped on store, and
 * coverage ends at the last CLOSED bar. A cache hit can therefore be short by
 * at most one bar, the one a live subscription re-supplies immediately, and is
 * never wrong about a bar it does return.
 *
 * **Bounds.** Capped on both entry count (`max`) and total cached bars
 * (`maxBars`), LRU-evicted. Entries alone do not bound memory (one intraday
 * series can be 100k bars); bar count is the honest proxy for bytes that can be
 * measured without serialising. Byte counting would mean stringifying every
 * entry on every write, which costs more than the cache saves.
 *
 * **Storage.** A bounded in-memory copy is always available. A host may inject
 * `storage` to persist through localStorage, IndexedDB, or another store, but
 * the engine will not choose one itself. Durable reads, writes, and deletes are
 * best effort so storage denial or quota exhaustion cannot block market data.
 * Store methods may return a promise. `CachedBars` is plain JSON so it
 * round-trips through `JSON.stringify` unchanged.
 *
 * **Opt-out.** `getBars({ ..., noCache: true })` always hits the network (and
 * refreshes the entry); `invalidate()` and `clear()` drop entries by hand.
 */
import type { Bar, UTCSeconds } from '../model/bar';
import type { BarsPage, BarsPageRequest, BarsRequest, DataFeed, MarketDepth, UnsubscribeFn, LiveBarMeta, SymbolMatch, SymbolSearchRequest } from './types';
import { nextBucketStart, tryResolveInterval } from './intervals';
import { dataVariantKey, type DataVariantCapabilities, type DataVariantQuery } from './data-variant';

export type MaybePromise<T> = T | Promise<T>;

/** One cached series. Plain JSON: safe to persist as-is. */
export interface CachedBars {
  /** Persisted schema version. Missing means the compatible legacy schema. */
  version?: number;
  /** Closed bars only, ascending by time. */
  bars: Bar[];
  /** Coverage start: the `from` of the request that filled this entry. */
  from: UTCSeconds;
  /** Coverage end (inclusive): the last instant this entry is complete to. */
  to: UTCSeconds;
  /** Wall clock (ms) at store time, for TTL. */
  storedAt: number;
  /**
   * When the bar AFTER this entry's coverage closes, so freshness needs no
   * re-resolve. Null is impossible here: an entry whose bars have no knowable
   * close is never stored in the first place.
   */
  nextClose: UTCSeconds;
}

/**
 * Pluggable durable store. Sync or async operations are awaited and isolated
 * from the network result. The cache always keeps its own bounded memory copy.
 */
export interface BarCacheStore {
  get(key: string): MaybePromise<CachedBars | undefined>;
  set(key: string, value: CachedBars): MaybePromise<void>;
  delete(key: string): MaybePromise<void>;
}

export interface BarCacheOptions {
  /** Absolute age bound, ms. Default 5 minutes. */
  ttlMs?: number;
  /** Maximum entries before LRU eviction. Default 24. */
  max?: number;
  /** Maximum total cached bars before LRU eviction. Default 250_000. */
  maxBars?: number;
  /** Optional durable store. Bounded in-memory retention is always enabled. */
  storage?: BarCacheStore;
  /** Injectable clock (ms), for tests and for hosts with a server clock. */
  now?: () => number;
  /**
   * Override how the cache decides when a bar closes. Return null for "unknown",
   * which makes the cache refuse to store the series rather than guess. Defaults
   * to {@link barCloseSec}, which asks the interval registry.
   */
  barCloses?: (interval: string, barStartSec: UTCSeconds) => number | null;
  /** IANA zone for calendar intervals. Defaults to the engine default. */
  timezone?: string;
}

/** A `BarsRequest` that can force a fresh fetch. */
export interface CachedBarsRequest extends BarsRequest {
  /** Skip the cached entry, fetch, and replace it with the fresh result. */
  noCache?: boolean;
}

/** Counts what this instance is tracking, not what a persistent store holds. */
export interface BarCacheStats {
  entries: number;
  bars: number;
  hits: number;
  misses: number;
  evictions: number;
}

const DEFAULT_TTL_MS = 5 * 60_000;
const DEFAULT_MAX = 24;
const DEFAULT_MAX_BARS = 250_000;

/** Current persisted entry schema. Legacy entries without this field remain readable. */
export const BAR_CACHE_VERSION = 1;

/**
 * The instant a bar starting at `barStartSec` closes, or null when that cannot
 * be known from the interval alone.
 *
 * This asks the interval registry rather than parsing the token itself. A second
 * parser here was the bug: it matched a fixed set of letter codes and returned
 * 60 seconds for anything else, so a host that registered its own code got a
 * cache that believed a new bar closed every minute. A tick-count series keyed
 * that way is served stale for up to a minute at a time, and a registered
 * calendar code was approximated at 30 days.
 *
 * Null means "no fixed close", and it is returned for two genuinely different
 * situations that both demand the same conservative answer:
 *
 *  - **tick and volume bars**, which close on trade flow. A 500-tick bar may run
 *    for a second or an hour, so nothing about elapsed time says whether the
 *    last bar is complete.
 *  - **an unregistered code.** Guessing 60 seconds is how the old parser turned
 *    a typo into a silently wrong cache.
 *
 * The caller must treat null as "cannot cache and cannot serve past coverage",
 * which is the safe direction: it refetches rather than serving something stale.
 */
export function barCloseSec(interval: string, barStartSec: UTCSeconds, zone?: string): number | null {
  const found = tryResolveInterval(interval);
  if (found === null) return null;
  const b = found.bucketing;
  // A fixed interval closes one span after the bar itself opens, NOT at the next
  // boundary of the epoch-anchored grid. Those are the same thing only when the
  // feed's bars happen to sit on that grid, and a session-anchored feed (09:15 in
  // Mumbai, 09:30 in New York) does not: asking the grid there answers early, and
  // the cache then treats a closed bar as still forming and refetches forever.
  // Grid alignment is how a tick is assigned to a bar, which is a different
  // question from how long that bar lasts.
  if (b.mode === 'interval') return barStartSec + b.seconds;
  // Calendar bars genuinely do start on a boundary, and their length is not fixed:
  // February and a leap February differ, and so do a 30 and a 31 day month. Only
  // the registry can resolve that, on the chart's calendar, hence the zone.
  return nextBucketStart(b, barStartSec, zone);
}

export function barCacheKey(req: BarsRequest): string {
  const variant = dataVariantKey(req.variant);
  return `${req.symbol}|${req.exchange}|${req.interval}${variant && '|' + variant}`;
}

/** Bars are mutated in place by live builders; never hand out our own objects. */
function cloneBars(bars: Bar[]): Bar[] {
  const out: Bar[] = new Array(bars.length) as Bar[];
  for (let i = 0; i < bars.length; i++) out[i] = { ...bars[i]! };
  return out;
}

/** Recency and size bookkeeping, kept in memory even when the store is not. */
interface IndexEntry { lastUsed: number; bars: number }

function throwIfAborted(signal?: AbortSignal): void {
  signal?.throwIfAborted();
}

export class BarCache implements DataFeed {
  /** The wrapped feed, for callers that need something this wrapper does not forward. */
  public readonly source: DataFeed;

  private readonly _backing: BarCacheStore | undefined;
  private readonly _memory = new Map<string, CachedBars>();
  /** Keys whose durable value may still exist after a failed write or delete. */
  private readonly _tombstones = new Set<string>();
  private readonly _writes = new Map<string, symbol>();
  private readonly _ttlMs: number;
  private readonly _max: number;
  private readonly _maxBars: number;
  private readonly _now: () => number;
  private readonly _barCloses: (interval: string, barStartSec: UTCSeconds) => number | null;
  private readonly _index = new Map<string, IndexEntry>();
  private _tick = 0;
  private _hits = 0;
  private _misses = 0;
  private _evictions = 0;

  public constructor(feed: DataFeed, options: BarCacheOptions = {}) {
    this.source = feed;
    this._backing = options.storage;
    this._ttlMs = options.ttlMs ?? DEFAULT_TTL_MS;
    this._max = options.max ?? DEFAULT_MAX;
    this._maxBars = options.maxBars ?? DEFAULT_MAX_BARS;
    this._now = options.now ?? (() => Date.now());
    const zone = options.timezone;
    this._barCloses = options.barCloses ?? ((iv, t) => barCloseSec(iv, t, zone));
    // Only advertise the optional DataFeed methods the wrapped feed actually
    // has: the codebase feature-detects `subscribeBars` to tell a history-only
    // feed from a live one, and a stub that always exists would defeat that.
    // Forwarded with every argument, not just the two `DataFeed` declares:
    // `OpenAlgoLiveDataFeed.subscribeBars` takes a third `opts` (seedFrom,
    // cumDayVolumeSoFar) and a wrapper that dropped it would silently stop a
    // live bar continuing the last history bar's bucket. Nothing here reads the
    // extra arguments; they only have to survive the hop.
    if (typeof feed.subscribeBars === 'function') {
      this.subscribeBars = (req, onBar, ...rest): UnsubscribeFn =>
        (feed.subscribeBars as (...a: unknown[]) => UnsubscribeFn)(req, onBar, ...rest);
    }
    if (typeof feed.subscribeDepth === 'function') {
      this.subscribeDepth = (req, onDepth, ...rest): UnsubscribeFn =>
        (feed.subscribeDepth as (...a: unknown[]) => UnsubscribeFn)(req, onDepth, ...rest);
    }
    if (typeof feed.getBarsPage === 'function') {
      this.getBarsPage = (req): Promise<BarsPage> => feed.getBarsPage!(req);
    }
    if (typeof feed.dataVariants === 'function') {
      this.dataVariants = (query): DataVariantCapabilities | Promise<DataVariantCapabilities> => feed.dataVariants!(query);
    }
    if (typeof feed.searchSymbols === 'function') {
      this.searchSymbols = (request): Promise<SymbolMatch[]> => feed.searchSymbols!(request);
    }
  }

  // `...rest` is part of the signature so a caller holding the concrete
  // `BarCache` can still pass a wrapped feed's extra options through.
  public subscribeBars?: (req: BarsRequest, onBar: (bar: Bar, meta?: LiveBarMeta) => void, ...rest: unknown[]) => UnsubscribeFn;
  public subscribeDepth?: (req: BarsRequest, onDepth: (depth: MarketDepth) => void, ...rest: unknown[]) => UnsubscribeFn;
  public getBarsPage?: (req: BarsPageRequest) => Promise<BarsPage>;
  public dataVariants?: (query: DataVariantQuery) => DataVariantCapabilities | Promise<DataVariantCapabilities>;
  public searchSymbols?: (request: SymbolSearchRequest) => Promise<SymbolMatch[]>;

  public async getBars(req: CachedBarsRequest): Promise<Bar[]> {
    throwIfAborted(req.signal);
    // An open-ended request cannot be reasoned about: we would not know what the
    // entry covers. An interval whose bars have no knowable close cannot be
    // cached at all, because nothing tells us which of them are complete. Both
    // pass straight through, uncached in either direction.
    if (req.from === undefined || req.to === undefined) {
      const bars = await this.source.getBars(req);
      throwIfAborted(req.signal);
      return bars;
    }
    const key = barCacheKey(req);
    if (req.noCache !== true) {
      const hit = await this._lookup(key, req.interval, req.from, req.to);
      throwIfAborted(req.signal);
      if (hit !== undefined) {
        this._hits++;
        return hit;
      }
      this._misses++;
    }
    // Awaited, not caught: a rejected fetch must propagate untouched and must
    // leave the previous entry alone. Nothing is written unless bars arrive.
    throwIfAborted(req.signal);
    const bars = await this.source.getBars(req);
    throwIfAborted(req.signal);
    await this._put(key, req.from, req.to, req.interval, bars, req.signal);
    throwIfAborted(req.signal);
    return bars;
  }

  /** Read any valid, TTL-retained closed overlap without initiating a source request. */
  public async getCachedBars(req: BarsRequest): Promise<Bar[] | undefined> {
    throwIfAborted(req.signal);
    if (req.noCache === true || req.from === undefined || req.to === undefined) return undefined;
    const key = barCacheKey(req);
    const entry = await this._readEntry(key, req.interval);
    throwIfAborted(req.signal);
    if (entry === undefined) return undefined;
    if (this._now() - entry.storedAt > this._ttlMs) {
      await this._drop(key);
      throwIfAborted(req.signal);
      return undefined;
    }
    const snapshot = this._slice(entry, req.from, req.to);
    if (snapshot.length === 0) return undefined;
    this._remember(key, entry);
    await this._evict();
    throwIfAborted(req.signal);
    return snapshot;
  }

  /**
   * Drop one series, or (with no argument) everything this cache knows of.
   * "Knows of" is literal with an injected persistent store: recency and size
   * are tracked in memory, so keys written by an earlier session are dropped
   * when they are next read and found expired, not by `clear()`. A store that
   * outlives the process is responsible for its own overall quota.
   */
  public async invalidate(req?: Pick<BarsRequest, 'symbol' | 'exchange' | 'interval' | 'variant'>): Promise<void> {
    if (req === undefined) return this.clear();
    const key = barCacheKey(req);
    await this._drop(key);
  }

  public async clear(): Promise<void> {
    const keys = new Set([...this._memory.keys(), ...this._tombstones]);
    this._memory.clear();
    this._index.clear();
    for (const key of keys) await this._deleteBacking(key);
  }

  public stats(): BarCacheStats {
    let bars = 0;
    for (const e of this._index.values()) bars += e.bars;
    return { entries: this._index.size, bars, hits: this._hits, misses: this._misses, evictions: this._evictions };
  }

  private async _lookup(
    key: string,
    interval: string,
    from: UTCSeconds,
    to: UTCSeconds,
  ): Promise<Bar[] | undefined> {
    const entry = await this._readEntry(key, interval);
    if (entry === undefined) return undefined;
    const nowMs = this._now();
    if (nowMs - entry.storedAt > this._ttlMs) {
      await this._drop(key);
      return undefined;
    }
    // Older bars than we hold: a real gap at the left edge, so refetch rather
    // than paint a chart that silently starts late.
    if (from < entry.from) return undefined;
    // Past our coverage: allowed only while the bar after our last closed one
    // is still forming, i.e. nothing new could have been fetched anyway.
    const nowSec = Math.floor(nowMs / 1000);
    if (to > entry.to && nowSec >= entry.nextClose) return undefined;
    this._remember(key, entry);
    await this._evict();
    return this._slice(entry, from, to);
  }

  private _slice(entry: CachedBars, from: UTCSeconds, to: UTCSeconds): Bar[] {
    const out: Bar[] = [];
    for (const b of entry.bars) {
      if (b.time < from) continue;
      if (b.time > to) break;
      out.push({ ...b });
    }
    return out;
  }

  private async _put(
    key: string,
    from: UTCSeconds,
    to: UTCSeconds,
    interval: string,
    bars: Bar[],
    signal?: AbortSignal,
  ): Promise<void> {
    const nowMs = this._now();
    const nowSec = Math.floor(nowMs / 1000);
    const requested = bars.filter((bar) => bar.time >= from && bar.time <= to);
    let end = requested.length;
    // Drop every trailing bar that has not closed yet. Normally that is the one
    // forming candle; the loop also copes with a feed that stamps a bar ahead.
    // Each bar is asked for its OWN close. A calendar month is not a fixed span,
    // so a single duration would mis-date February and every 31 day month; and a
    // bar with no knowable close (a tick series, an unregistered code) is never
    // complete as far as this cache is concerned, so the loop drops the lot and
    // the entry is abandoned below.
    while (end > 0) {
      const close = this._barCloses(interval, requested[end - 1]!.time); // `end > 0`
      if (close !== null && close <= nowSec) break;
      end--;
    }
    if (end === 0) return; // Nothing closed to cache, and an empty entry would only mislead.
    // One series larger than the whole budget would evict everything else and
    // then itself on the next write, so it is simply not cached.
    if (end > this._maxBars) return;
    const closed = cloneBars(requested.slice(0, end));
    const last = closed[closed.length - 1]!; // `end > 0`, so at least one bar
    // Non-null by construction: the loop above only stopped on a bar that had a
    // close, and `nextClose` is the close of the bar that follows it, which is
    // the instant a hit past coverage stops being safe.
    const lastClose = this._barCloses(interval, last.time) as UTCSeconds;
    const nextClose = this._barCloses(interval, lastClose) ?? lastClose;
    const entry: CachedBars = {
      version: BAR_CACHE_VERSION,
      bars: closed,
      from,
      // Complete through whichever ends first: what we asked for, or the close
      // of the last bar we actually hold.
      to: Math.min(to, lastClose - 1),
      storedAt: nowMs,
      nextClose,
    };
    if (!this._validEntry(entry, interval, nowMs)) return;
    throwIfAborted(signal);
    const write = Symbol(key);
    this._writes.set(key, write);
    this._remember(key, entry);
    await this._writeBacking(key, entry);
    if (this._writes.get(key) !== write) {
      await this._restoreLatestBacking(key);
      throwIfAborted(signal);
      return;
    }
    if (signal?.aborted === true) {
      this._memory.delete(key);
      this._index.delete(key);
      this._writes.delete(key);
      await this._deleteBacking(key);
      throwIfAborted(signal);
    }
    await this._evict();
    if (signal?.aborted === true && this._writes.get(key) === write) {
      this._memory.delete(key);
      this._index.delete(key);
      this._writes.delete(key);
      await this._deleteBacking(key);
      throwIfAborted(signal);
    }
    if (this._writes.get(key) === write) this._writes.delete(key);
  }

  private async _drop(key: string): Promise<void> {
    this._memory.delete(key);
    this._index.delete(key);
    await this._deleteBacking(key);
  }

  private async _evict(): Promise<void> {
    for (;;) {
      let bars = 0;
      for (const e of this._index.values()) bars += e.bars;
      if (this._index.size <= this._max && bars <= this._maxBars) return;
      let victim: string | undefined;
      let oldest = Infinity;
      for (const [k, e] of this._index) {
        if (e.lastUsed < oldest) { oldest = e.lastUsed; victim = k; }
      }
      if (victim === undefined) return;
      this._evictions++;
      await this._drop(victim);
    }
  }

  private _remember(key: string, entry: CachedBars): void {
    const copy = this._cloneEntry(entry);
    this._memory.set(key, copy);
    this._index.set(key, { lastUsed: ++this._tick, bars: copy.bars.length });
  }

  private async _readEntry(key: string, interval: string): Promise<CachedBars | undefined> {
    const memory = this._memory.get(key);
    if (this._backing === undefined || this._tombstones.has(key)) return memory;
    let stored: unknown;
    try {
      stored = await this._backing.get(key);
    } catch {
      return memory;
    }
    if (stored === undefined) return memory;
    const nowMs = this._now();
    if (!this._validEntry(stored, interval, nowMs)) {
      await this._deleteBacking(key);
      return memory;
    }
    const durable = this._cloneEntry(stored);
    if (memory !== undefined && memory.storedAt >= durable.storedAt) return memory;
    return durable;
  }

  private _validEntry(value: unknown, interval: string, nowMs: number): value is CachedBars {
    if (typeof value !== 'object' || value === null) return false;
    const candidate = value as Partial<CachedBars>;
    if (candidate.version !== undefined && candidate.version !== BAR_CACHE_VERSION) return false;
    if (!Number.isFinite(candidate.from) || !Number.isInteger(candidate.from)) return false;
    if (!Number.isFinite(candidate.to) || !Number.isInteger(candidate.to)) return false;
    if (!Number.isFinite(candidate.storedAt) || candidate.storedAt! < 0 || candidate.storedAt! > nowMs) return false;
    if (!Number.isFinite(candidate.nextClose) || !Number.isInteger(candidate.nextClose)) return false;
    if (candidate.from! > candidate.to! || candidate.nextClose! <= candidate.to!) return false;
    if (!Array.isArray(candidate.bars) || candidate.bars.length === 0) return false;
    if (candidate.bars.length > this._maxBars || this._max < 1) return false;
    const nowSec = Math.floor(nowMs / 1000);
    let previous = -Infinity;
    let lastClose: number | null = null;
    for (const bar of candidate.bars) {
      if (!this._validBar(bar) || bar.time <= previous) return false;
      if (bar.time < candidate.from! || bar.time > candidate.to!) return false;
      lastClose = this._barCloses(interval, bar.time);
      if (lastClose === null || lastClose > nowSec) return false;
      previous = bar.time;
    }
    const expectedNextClose = this._barCloses(interval, lastClose as UTCSeconds) ?? lastClose;
    return candidate.nextClose === expectedNextClose;
  }

  private _validBar(value: unknown): value is Bar {
    if (typeof value !== 'object' || value === null) return false;
    const bar = value as Partial<Bar>;
    if (!Number.isInteger(bar.time)) return false;
    if (![bar.open, bar.high, bar.low, bar.close].every(Number.isFinite)) return false;
    if (bar.volume !== undefined && !Number.isFinite(bar.volume)) return false;
    if (bar.oi !== undefined && !Number.isFinite(bar.oi)) return false;
    return bar.color === undefined || typeof bar.color === 'string';
  }

  private _cloneEntry(entry: CachedBars): CachedBars {
    const copy: CachedBars = {
      bars: cloneBars(entry.bars),
      from: entry.from,
      to: entry.to,
      storedAt: entry.storedAt,
      nextClose: entry.nextClose,
    };
    if (entry.version !== undefined) copy.version = entry.version;
    return copy;
  }

  private async _writeBacking(key: string, entry: CachedBars): Promise<void> {
    if (this._backing === undefined) return;
    try {
      await this._backing.set(key, this._cloneEntry(entry));
      this._tombstones.delete(key);
    } catch {
      this._tombstones.add(key);
    }
  }

  private async _deleteBacking(key: string): Promise<void> {
    if (this._backing === undefined) return;
    try {
      await this._backing.delete(key);
      this._tombstones.delete(key);
    } catch {
      this._tombstones.add(key);
    }
  }

  private async _restoreLatestBacking(key: string): Promise<void> {
    const latest = this._memory.get(key);
    if (latest === undefined) await this._deleteBacking(key);
    else await this._writeBacking(key, latest);
  }
}

/**
 * Wrap any `DataFeed` in a warm-load bar cache.
 *
 *     const feed = withBarCache(new OpenAlgoDataFeed(cfg), { ttlMs, max, storage });
 *
 * A hit ends at the last closed bar; a live subscription supplies the forming
 * one. A host with none must ask again with `noCache: true` when a hit ends
 * before a bar it has already shown, or its chart steps back to an older close.
 */
export function withBarCache(feed: DataFeed, options?: BarCacheOptions): BarCache {
  return new BarCache(feed, options);
}
