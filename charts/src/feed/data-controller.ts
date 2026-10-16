import type { Bar } from '../model/bar';
import type { BarSubscriptionOptions, BarsRequest, DataFeed, LiveBarMeta, UnsubscribeFn } from './types';
import { type HistoryRequestPool, sharedHistoryRequests, withHistoryDeadline } from './request-pool';
import { tryResolveInterval } from './intervals';
import { widenBar } from './candle-builder';
import { dataVariantError, normalizeDataVariant, unsupportedDataVariant, type DataVariantDimension } from './data-variant';
import type { LooseOptional } from '../helpers/types';

/** `unsupported`: the provider does not declare the requested variant, so nothing was fetched. */
export type DataLoadingStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'refreshing' | 'stale' | 'error' | 'unsupported';
export type HistoryLoadingStatus = 'idle' | 'loading' | 'error' | 'exhausted' | 'limited';
export type DataUpdateReason = 'load' | 'cache' | 'live' | 'refresh' | 'prepend' | 'resume' | 'state';

/** Display bars are held still while paused; bars() retains the live store. */
export interface DataLoadingSnapshot {
  readonly request: Readonly<BarsRequest> | null;
  readonly bars: readonly Bar[];
  readonly status: DataLoadingStatus;
  readonly historyStatus: HistoryLoadingStatus;
  readonly hasMore: boolean | null;
  readonly error?: Error;
  readonly historyError?: Error;
  readonly reason: DataUpdateReason;
  readonly paused: boolean;
  /** With status `unsupported`: the first field of the request's variant the provider does not serve. */
  readonly unsupported?: DataVariantDimension;
}

export interface DataLoadingOptions {
  requestPool?: HistoryRequestPool;
  timeoutMs?: number;
  pageSize?: number;
  /** Date-window fallback for feeds without getBarsPage. Defaults to the load window. */
  pageWindowSec?: number;
  /** Empty windows inspected per gesture, without claiming permanent exhaustion. */
  maxEmptyPages?: number;
  maxBars?: number;
  /** Optional history repair cadence. Zero disables polling. */
  pollIntervalMs?: number;
  /**
   * Repair the tail when a bar closes, driven by the stream rather than the
   * clock. A pushed bar that opens a new bucket means the bar before it has
   * just closed, so one refresh runs `delayMs` later (default 2500 ms), long
   * enough for a broker's history to have published the close. Nothing fires
   * while the stream is quiet, so a closed market costs no requests. When the
   * reply still stops short of the bar that closed, the repair retries
   * `retries` times (default 2), `retryDelayMs` apart (default 5000 ms).
   * Off by default.
   */
  refreshOnBarClose?: boolean | { delayMs?: number; retries?: number; retryDelayMs?: number };
  /**
   * Refresh at once when a pushed bar skips one or more whole buckets, which
   * is what a stream leaves behind after a dropped socket, a hidden tab or a
   * sleeping machine. Needs a fixed-length interval. Off by default.
   */
  refreshOnGap?: boolean;
  /**
   * How many bars back from the tail a refresh re-fetches. Unset re-fetches
   * the whole load window on every refresh, which is what polling always did;
   * a small number turns each repair into a tail request. A gap repair widens
   * the window to cover the gap. Needs a fixed-length interval; any other
   * interval keeps the whole window.
   */
  refreshWindowBars?: number;
  /** UTC seconds. */
  now?: () => number;
}

/** A patch clears an error by writing undefined, which a snapshot reads as none. */
type SnapshotPatch = Partial<Omit<DataLoadingSnapshot, 'error' | 'historyError'>>
  & { readonly error?: Error | undefined; readonly historyError?: Error | undefined };

/** What a stream-triggered repair is for, so the refresh can size its window and check its reply. */
interface Repair {
  /** Oldest time the window must reach, for a gap the stream skipped. */
  from?: number | undefined;
  /** The bar that just closed; a reply that stops short of it is retried. */
  expect?: number | undefined;
}

const BAR_CLOSE_DEFAULTS = { delayMs: 2500, retries: 2, retryDelayMs: 5000 };

function asError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error ?? 'History request failed'));
}
function positive(value: number, name: string): number {
  if (!Number.isFinite(value) || value <= 0) throw new RangeError(`${name} must be positive and finite`);
  return value;
}
function normalize(bars: readonly Bar[]): Bar[] {
  const result = new Map<number, Bar>();
  for (const bar of bars) {
    if (![bar.time, bar.open, bar.high, bar.low, bar.close].every(Number.isFinite)
      || bar.high < Math.max(bar.open, bar.close, bar.low) || bar.low > Math.min(bar.open, bar.close)
      || (bar.volume !== undefined && (!Number.isFinite(bar.volume) || bar.volume < 0))) {
      throw new Error('History contains an invalid candle');
    }
    result.set(bar.time, { ...bar });
  }
  return [...result.values()].sort((a, b) => a.time - b.time);
}
function merge(...parts: readonly (readonly Bar[])[]): Bar[] {
  return normalize(parts.flat());
}

/**
 * Owns history, paging and live updates for one current instrument. Consumers
 * decide how to paint snapshots; no canvas, DOM or broker execution is owned here.
 */
export class DataLoadingController {
  private readonly _feed: DataFeed;
  private readonly _pool: HistoryRequestPool;
  private readonly _options: DataLoadingOptions;
  private readonly _listeners = new Set<(snapshot: DataLoadingSnapshot) => void>();
  private _state: DataLoadingSnapshot = { request: null, bars: [], status: 'idle', historyStatus: 'idle', hasMore: null, reason: 'state', paused: false };
  private _bars: Bar[] = [];
  private _scope = new AbortController();
  private _refreshAbort: AbortController | null = null;
  private _pageAbort: AbortController | null = null;
  private _loadWork: Promise<readonly Bar[]> | null = null;
  private _pageWork: Promise<readonly Bar[]> | null = null;
  private _unsubscribe: UnsubscribeFn | null = null;
  private _stream = 0;
  private _generation = 0;
  private _refreshId = 0;
  private _before: number | undefined;
  private _buffer: Map<number, Bar> | null = null;
  private _poll: ReturnType<typeof setTimeout> | null = null;
  private _visible = true;
  private _destroyed = false;
  /**
   * Whether the provider has said it serves the current request's variant, or
   * the request names none. Until it has, nothing fetches, refreshes or pages
   * that variant: a declaration that failed is not a declaration.
   */
  private _declared = true;
  /** Seconds per bar of the current request, null when the interval is not fixed-length. */
  private _seconds: number | null = null;
  /** Bucket whose open is only the first tick a builder saw, until history covers it. */
  private _provisionalTime: number | null = null;
  private _repairTimer: ReturnType<typeof setTimeout> | null = null;
  private _repairRetries = 0;
  private _pendingRepair: Repair | null = null;
  private readonly _barClose: { delayMs: number; retries: number; retryDelayMs: number } | null;

  public constructor(feed: DataFeed, options: DataLoadingOptions = {}) {
    this._feed = feed;
    this._pool = options.requestPool ?? sharedHistoryRequests(feed);
    this._options = { pageSize: 500, maxEmptyPages: 4, maxBars: 100_000, pollIntervalMs: 0, ...options };
    for (const key of ['pageSize', 'maxEmptyPages', 'maxBars'] as const) {
      const value = positive(this._options[key]!, key);
      if (!Number.isInteger(value)) throw new RangeError(`${key} must be an integer`);
    }
    if (options.pageWindowSec !== undefined) positive(options.pageWindowSec, 'pageWindowSec');
    if (options.timeoutMs !== undefined) positive(options.timeoutMs, 'timeoutMs');
    if (!Number.isFinite(this._options.pollIntervalMs) || this._options.pollIntervalMs! < 0) throw new RangeError('pollIntervalMs must be nonnegative');
    if (options.refreshWindowBars !== undefined && !Number.isInteger(positive(options.refreshWindowBars, 'refreshWindowBars'))) {
      throw new RangeError('refreshWindowBars must be an integer');
    }
    const close = options.refreshOnBarClose;
    this._barClose = !close ? null : { ...BAR_CLOSE_DEFAULTS, ...(close === true ? {} : close) };
    if (this._barClose) {
      for (const key of ['delayMs', 'retries', 'retryDelayMs'] as const) {
        const value = this._barClose[key];
        if (!Number.isFinite(value) || value < 0) throw new RangeError(`refreshOnBarClose.${key} must be nonnegative`);
      }
      if (!Number.isInteger(this._barClose.retries)) throw new RangeError('refreshOnBarClose.retries must be an integer');
    }
  }

  public getState(): DataLoadingSnapshot { return this._state; }
  public bars(): readonly Bar[] { return this._bars; }
  public subscribe(listener: (snapshot: DataLoadingSnapshot) => void): UnsubscribeFn {
    if (this._destroyed) return () => {};
    this._listeners.add(listener);
    return () => { this._listeners.delete(listener); };
  }

  public load(req: BarsRequest): Promise<readonly Bar[]> {
    if (this._destroyed) return Promise.resolve([]);
    const generation = ++this._generation;
    this._cancel();
    if (!this._current(generation)) return this._loadWork ?? Promise.resolve(this._bars);
    this._scope = new AbortController();
    this._bars = [];
    this._before = undefined;
    this._provisionalTime = null;
    const found = tryResolveInterval(req.interval);
    this._seconds = found?.bucketing.mode === 'interval' ? found.bucketing.seconds : null;
    const request = { ...req, signal: undefined, timeoutMs: req.timeoutMs ?? this._options.timeoutMs } satisfies LooseOptional<BarsRequest> as BarsRequest;
    // The default variant is no variant at all, so a request naming `{}` keys,
    // shares and fetches exactly like one that names nothing. A malformed one
    // is left for `_load` to report.
    try {
      const variant = normalizeDataVariant(req.variant);
      if (variant) request.variant = variant;
      else delete request.variant;
    } catch { /* reported by _load */ }
    this._state = { request, bars: [], status: 'loading', historyStatus: 'idle', hasMore: null, reason: 'load', paused: false };
    this._declared = request.variant === undefined;
    let complete!: (bars: readonly Bar[]) => void;
    const work = new Promise<readonly Bar[]>(resolve => { complete = resolve; });
    this._loadWork = work;
    this._publish('load');
    void this._load(request, req.signal, generation).then(complete);
    void work.then(() => { if (this._loadWork === work) this._loadWork = null; });
    return work;
  }

  private async _load(req: BarsRequest, callerSignal: AbortSignal | undefined, generation: number): Promise<readonly Bar[]> {
    if (!this._current(generation)) return this._bars;
    const scope = this._scope;
    const abort = (): void => scope.abort();
    callerSignal?.addEventListener('abort', abort, { once: true });
    if (callerSignal?.aborted) scope.abort();
    try {
      if (req.variant !== undefined) {
        // Ask before the cache or the network: a variant the provider never
        // declared is not fetched and relabelled, it is reported. A malformed
        // one throws below, which is reported as an error.
        const declared = this._feed.dataVariants;
        const capabilities = declared === undefined ? undefined : await withHistoryDeadline({ signal: scope.signal, timeoutMs: req.timeoutMs },
          signal => Promise.resolve(declared.call(this._feed, { symbol: req.symbol, exchange: req.exchange, interval: req.interval, signal })));
        if (!this._current(generation)) return this._bars;
        const unsupported = unsupportedDataVariant(capabilities, req.variant);
        if (unsupported !== null) {
          this._publish('state', { status: 'unsupported', unsupported, error: dataVariantError(unsupported, req.variant) });
          return this._bars;
        }
        this._declared = true;
      }
      let cached: Bar[] | undefined;
      if (!req.noCache && this._feed.getCachedBars) {
        try {
          const snapshot = await withHistoryDeadline({ signal: scope.signal, timeoutMs: Math.min(req.timeoutMs ?? 500, 500) },
            signal => this._feed.getCachedBars!({ ...req, signal }));
          cached = snapshot ? normalize(snapshot) : undefined;
        } catch { /* A cache failure cannot prevent authoritative history loading. */ }
      }
      if (!this._current(generation)) return this._bars;
      if (scope.signal.aborted) throw scope.signal.reason;
      if (cached?.length) {
        this._bars = cached;
        this._publish('cache', { status: 'refreshing' });
      }
      // `cached` holds a bar whenever it is read here.
      const from = cached?.length && req.from !== undefined && cached[0]!.time <= req.from
        ? Math.max(req.from, cached[Math.max(0, cached.length - 2)]!.time) : req.from;
      const fresh = await this._pool.getBars({ ...req, from, signal: scope.signal, noCache: req.noCache || !!this._feed.getCachedBars } satisfies LooseOptional<BarsRequest> as BarsRequest, 10);
      if (!this._current(generation)) return this._bars;
      this._bars = this._replaceWindow(normalize(fresh), from, req.to);
      this._limit();
      this._before = this._bars[0]?.time ?? req.from;
      this._publish('load', { status: this._bars.length ? 'ready' : 'empty', error: undefined });
      this._startStream(generation);
      if (this._current(generation)) this._schedulePoll();
    } catch (error) {
      if (this._current(generation)) this._publish('state', {
        status: scope.signal.aborted ? 'idle' : this._bars.length ? 'stale' : 'error',
        error: scope.signal.aborted ? undefined : asError(error),
      });
    } finally { callerSignal?.removeEventListener('abort', abort); }
    return this._bars;
  }

  public refresh(): Promise<readonly Bar[]> {
    return this._refresh();
  }

  private async _refresh(repair?: Repair): Promise<readonly Bar[]> {
    if (this._destroyed || !this._state.request || this._state.status === 'unsupported') return this._bars;
    if (this._loadWork) return this._loadWork;
    // The provider never answered for this variant (its declaration failed or
    // timed out), so a retry asks it again, through a load, rather than
    // fetching a series it may not serve.
    if (!this._declared) return this.load(this._state.request);
    const generation = this._generation;
    const id = ++this._refreshId;
    const previous = this._refreshAbort;
    this._refreshAbort = null;
    previous?.abort();
    if (!this._current(generation) || id !== this._refreshId) return this._bars;
    const abort = new AbortController();
    this._refreshAbort = abort;
    this._clearPoll();
    this._buffer ??= new Map();
    const original = this._state.request;
    const held = this._bars[this._bars.length - 1];
    const { from, to } = this._refreshWindow(original, held, repair);
    this._publish('state', { status: 'refreshing', error: undefined });
    try {
      const fresh = await this._pool.getBars({ ...original, from, to, noCache: true, signal: abort.signal } satisfies LooseOptional<BarsRequest> as BarsRequest, 5);
      if (!this._current(generation) || id !== this._refreshId) return this._bars;
      if (fresh.length === 0 && this._bars.length) throw new Error('History refresh returned no bars');
      const newest = this._mergeRefresh(fresh, from, to, held);
      this._buffer = null;
      this._limit();
      this._publish('refresh', { status: this._bars.length ? 'ready' : 'empty', error: undefined });
      this._startStream(generation);
      // History had not caught up to the bar that closed. Ask again in a while,
      // a bounded number of times, rather than leaving the bar to the next poll.
      if (repair?.expect !== undefined && newest < repair.expect && this._barClose && this._repairRetries < this._barClose.retries) {
        this._repairRetries++;
        this._scheduleRepair({ expect: repair.expect }, this._barClose.retryDelayMs);
      }
    } catch (error) {
      if (!this._current(generation) || id !== this._refreshId || abort.signal.aborted) return this._bars;
      // Retain buffered observations through failed repair and retry. The last
      // authoritative display stays visible and explicitly stale in the meantime.
      this._limit();
      this._publish('refresh', { status: this._bars.length ? 'stale' : 'error', error: asError(error) });
    } finally {
      if (this._current(generation) && id === this._refreshId) {
        this._refreshAbort = null;
        this._schedulePoll();
        const pending = this._pendingRepair;
        this._pendingRepair = null;
        if (pending) void this._refresh(pending);
      }
    }
    return this._bars;
  }

  /** The span a refresh asks history for: the request's own width ending now, or a tail window. */
  private _refreshWindow(original: BarsRequest, held: Bar | undefined, repair: Repair | undefined): { from: number | undefined; to: number } {
    const to = Math.max(original.to ?? 0, (this._options.now ?? (() => Date.now() / 1000))());
    const width = original.from !== undefined && original.to !== undefined ? original.to - original.from : undefined;
    let from = width === undefined ? original.from : to - width;
    // A tail window asks history only for the bars a repair can change. A gap
    // reaches back to the last bar the stream delivered before it.
    if (this._options.refreshWindowBars !== undefined && this._seconds !== null && held) {
      from = held.time - this._options.refreshWindowBars * this._seconds;
      if (repair?.from !== undefined) from = Math.min(from, repair.from);
    }
    return { from, to };
  }

  /**
   * Put a refresh's answer in place of the window it covers, keep what the
   * stream built past it, and fold in what arrived meanwhile. Returns the
   * newest bar time the answer held.
   */
  private _mergeRefresh(fresh: Bar[], from: number | undefined, to: number, held: Bar | undefined): number {
    const arrived = normalize(fresh);
    // REST is authoritative for the bars it returned and for nothing past
    // them. The bar the stream just completed is routinely a few seconds
    // ahead of a broker's history endpoint, and a refresh that fires inside
    // that gap would otherwise delete it: on screen the current candle
    // becomes the previous one, vanishes, and backfills on a later poll. So
    // the window handed over to REST ends at the newest bar REST actually
    // has, and anything the stream built beyond it is kept. Bars inside the
    // window are still REST's to correct.
    let newest = -Infinity;
    for (const value of arrived) if (value.time > newest) newest = value.time;
    const authoritativeTo = arrived.length ? Math.min(to, newest) : to;
    const updated = this._replaceWindow(arrived, from, authoritativeTo);
    const byTime = new Map(updated.map(bar => [bar.time, bar]));
    // The bar that was forming when the request went out is the one bar both
    // sides observed at once. Its extremes are the union, since each side saw
    // real prices, and its volume the larger, since volume only grows. Its
    // open and close are REST's: the open because a builder that opened the
    // bucket mid-way only saw its first tick, the close because a live push
    // during the request (below) is the only proof the stream is fresher.
    const forming = held && held.time === newest ? byTime.get(held.time) : undefined;
    if (held && forming) byTime.set(held.time, widenBar(forming, held));
    if (this._provisionalTime !== null && byTime.has(this._provisionalTime) && this._provisionalTime <= authoritativeTo) {
      this._provisionalTime = null;
    }
    for (const live of this._buffer?.values() ?? []) {
      const historical = byTime.get(live.time);
      // Whole-bar observations cannot reveal their overlap with a REST snapshot.
      // Preserve observed live extrema/close without adding the volumes twice.
      // Absence on the newer observation must not inherit an older open interest.
      byTime.set(live.time, historical ? { ...widenBar(historical, live), close: live.close, oi: live.oi } satisfies LooseOptional<Bar> as Bar : live);
    }
    this._bars = normalize([...byTime.values()]);
    return newest;
  }

  /**
   * Supply bars from an existing host subscription instead of subscribing twice.
   *
   * `meta.provisional` marks a bar whose open is only the first tick a builder
   * saw, see `CandleUpdate.provisional`. Pushed onto a bar history already
   * holds for that bucket, it keeps that bar's open and widens the extremes
   * instead of replacing them, so a repair that found the true open is not
   * undone by the next tick.
   */
  public pushBar(value: Bar, meta?: LiveBarMeta): void {
    if (this._destroyed || !this._state.request || this._state.status === 'unsupported') return;
    let bar: Bar;
    try { bar = normalize([value])[0]!; } catch (error) { // one valid bar in is one out; an invalid one throws
      this._publish('state', { status: this._bars.length ? 'stale' : 'error', error: asError(error) });
      return;
    }
    const tail = this._bars[this._bars.length - 1];
    if (tail && bar.time < tail.time) return;
    const provisional = meta?.provisional === true;
    const rollover = !tail || bar.time > tail.time;
    if (rollover) {
      if (provisional) this._provisionalTime = bar.time;
    } else if (provisional && this._provisionalTime !== bar.time) {
      bar = { ...widenBar(bar, tail), open: tail.open };
    }
    if (this._buffer) {
      this._buffer.set(bar.time, bar);
      while (this._buffer.size > this._options.maxBars!) this._buffer.delete(this._buffer.keys().next().value!);
    }
    const next = this._bars.slice();
    if (tail?.time === bar.time) next[next.length - 1] = { ...bar, volume: bar.volume ?? tail.volume } satisfies LooseOptional<Bar> as Bar;
    else next.push(bar);
    this._bars = next;
    this._limit();
    if (!this._buffer) this._publish('live', { status: this._state.status === 'stale' ? 'stale' : 'ready' });
    // After the bar is stored and shown: a repair started here sizes its window
    // from the real tail, and never holds the new bar back behind itself.
    if (rollover) this._onNewBucket(tail?.time, bar.time);
  }

  /** The stream opened a bucket: the one before it closed, and any between were skipped. */
  private _onNewBucket(closed: number | undefined, opened: number): void {
    if (this._options.refreshOnGap && this._seconds !== null && closed !== undefined && opened - closed > this._seconds) {
      // The skipped buckets are closed already, so there is nothing to wait for.
      this._requestRepair({ from: closed });
      return;
    }
    if (this._barClose) {
      this._repairRetries = 0;
      this._scheduleRepair({ expect: closed }, this._barClose.delayMs);
    }
  }
  private _scheduleRepair(repair: Repair, delayMs: number): void {
    this._clearRepairTimer();
    if (this._destroyed || !this._visible) return;
    this._repairTimer = setTimeout(() => { this._repairTimer = null; this._requestRepair(repair); }, delayMs);
  }
  /** Run a repair now, or queue one behind the refresh already in flight rather than aborting it. */
  private _requestRepair(repair: Repair): void {
    if (this._destroyed || !this._visible || !this._state.request || this._loadWork) return;
    if (this._refreshAbort) {
      const pending = this._pendingRepair;
      this._pendingRepair = {
        from: pending?.from === undefined ? repair.from : repair.from === undefined ? pending.from : Math.min(pending.from, repair.from),
        expect: pending?.expect === undefined ? repair.expect : repair.expect === undefined ? pending.expect : Math.max(pending.expect, repair.expect),
      };
      return;
    }
    void this._refresh(repair);
  }
  private _clearRepairTimer(): void {
    if (this._repairTimer !== null) clearTimeout(this._repairTimer);
    this._repairTimer = null;
  }

  /**
   * One older page. `until` (UTC seconds) widens a date feed's window to reach
   * it in one request, up to `maxBars` bars of a fixed interval; a paged feed
   * keeps its ordinary window.
   */
  public loadMore(until?: number): Promise<readonly Bar[]> {
    if (this._pageWork) return this._pageWork;
    if (this._destroyed || !this._state.request || this._loadWork || this._state.paused || this._state.hasMore === false
      || !this._declared) return Promise.resolve(this._bars);
    if (this._bars.length >= this._options.maxBars!) {
      this._publish('state', { historyStatus: 'limited' });
      return Promise.resolve(this._bars);
    }
    const generation = this._generation;
    let complete!: (bars: readonly Bar[]) => void;
    const work = new Promise<readonly Bar[]>(resolve => { complete = resolve; });
    this._pageWork = work;
    void this._loadMore(generation, until).then(complete);
    void work.then(() => { if (this._pageWork === work) this._pageWork = null; });
    return work;
  }

  private async _loadMore(generation: number, until?: number): Promise<readonly Bar[]> {
    const req = this._state.request!;
    const pageWindow = this._options.pageWindowSec ?? Math.max(1, (req.to ?? 0) - (req.from ?? 0) || 86400);
    // A paged feed counts back from `before`, so widening its dates buys nothing.
    // A date feed's window stops at what retention could keep: anything older is
    // fetched only to be dropped, and one very wide request can outlast the pool.
    const reach = this._feed.getBarsPage || !Number.isFinite(until) ? 0 : this._options.maxBars! * (this._seconds ?? Infinity);
    const abort = new AbortController();
    this._pageAbort = abort;
    this._publish('state', { historyStatus: 'loading', historyError: undefined });
    try {
      for (let attempt = 0; attempt < this._options.maxEmptyPages!; attempt++) {
        const before = this._before ?? this._bars[0]?.time ?? req.from;
        if (before === undefined) throw new Error('Older history needs a starting time');
        const window = reach > 0 ? Math.max(pageWindow, Math.min(reach, before - until!)) : pageWindow;
        const request = { ...req, from: before - window, to: before - 0.000001, before,
          countBack: this._options.pageSize!, signal: abort.signal };
        const page = this._feed.getBarsPage ? await this._pool.getBarsPage(request)
          : { bars: await this._pool.getBars(request), hasMore: undefined, nextBefore: undefined };
        if (!this._current(generation) || abort.signal.aborted) return this._bars;
        const older = normalize(page.bars).filter(bar => bar.time < before);
        const cursor = page.nextBefore ?? older[0]?.time ?? before - window;
        if (!Number.isFinite(cursor) || cursor >= before) throw new Error('History page did not advance its cursor');
        this._before = cursor;
        if (older.length) {
          const retained = new Set(this._bars.map(bar => bar.time));
          const additions = older.filter(bar => !retained.has(bar.time));
          const room = Math.max(0, this._options.maxBars! - this._bars.length);
          this._bars = merge(room ? additions.slice(-room) : [], this._bars);
          const limited = additions.length > room || this._bars.length >= this._options.maxBars!;
          // Retention is a local limit, not evidence of provider exhaustion.
          this._publish('prepend', { hasMore: additions.length > room ? true : page.hasMore ?? null,
            historyStatus: limited ? 'limited' : page.hasMore === false ? 'exhausted' : 'idle' });
          return this._bars;
        }
        if (page.hasMore === false) { this._publish('state', { hasMore: false, historyStatus: 'exhausted' }); return this._bars; }
      }
      this._publish('state', { hasMore: null, historyStatus: 'idle' });
    } catch (error) {
      if (this._current(generation) && !abort.signal.aborted) this._publish('state', { historyStatus: 'error', historyError: asError(error) });
    } finally { if (this._pageAbort === abort) this._pageAbort = null; }
    return this._bars;
  }

  public setPaused(paused: boolean): void {
    if (this._destroyed || paused === this._state.paused) return;
    this._state = { ...this._state, paused };
    this._publish(paused ? 'state' : 'resume');
  }

  public setVisible(visible: boolean): void {
    if (this._destroyed || visible === this._visible) return;
    this._visible = visible;
    if (!visible) { this._clearPoll(); this._clearRepairTimer(); this._pendingRepair = null; }
    else void this.refresh();
  }

  public destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    this._generation++;
    this._cancel();
    this._listeners.clear();
  }

  private _current(generation: number): boolean { return !this._destroyed && generation === this._generation; }
  private _replaceWindow(fresh: Bar[], from?: number, to?: number): Bar[] {
    if (from === undefined || to === undefined) return fresh;
    return merge(this._bars.filter(bar => bar.time < from || bar.time > to), fresh);
  }
  private _limit(): void {
    if (this._bars.length > this._options.maxBars!) this._bars = this._bars.slice(-this._options.maxBars!);
  }
  private _publish(reason: DataUpdateReason, patch: SnapshotPatch = {}): void {
    if (this._destroyed) return;
    this._state = { ...this._state, ...patch, reason, bars: this._state.paused || this._buffer ? this._state.bars : this._bars } satisfies LooseOptional<DataLoadingSnapshot> as DataLoadingSnapshot;
    const snapshot = this._state;
    for (const listener of [...this._listeners]) {
      if (this._destroyed || this._state !== snapshot) break;
      try { listener(snapshot); } catch { /* One host listener cannot stop data ownership or cleanup. */ }
    }
  }
  private _startStream(generation: number): void {
    if (!this._current(generation)) return;
    const previousId = this._stream;
    const stream = ++this._stream;
    const previous = this._unsubscribe;
    this._unsubscribe = null;
    if (!this._feed.subscribeBars) { this._release(previous); return; }
    try {
      const unsubscribe = this._feed.subscribeBars(this._state.request!, (bar, meta) => {
        if (this._current(generation) && stream === this._stream) this.pushBar(bar, meta);
      }, { seedFrom: this._bars[this._bars.length - 1], onResync: () => {
        if (this._current(generation) && stream === this._stream) void this.refresh();
      } } satisfies LooseOptional<BarSubscriptionOptions> as BarSubscriptionOptions);
      if (this._current(generation) && stream === this._stream) this._unsubscribe = unsubscribe;
      else this._release(unsubscribe);
      // Acquire before releasing so ref-counted feeds retain the underlying topic.
      this._release(previous);
    } catch (error) {
      if (this._current(generation) && stream === this._stream) {
        this._stream = previousId;
        this._unsubscribe = previous;
        this._buffer ??= new Map();
        this._publish('state', { status: this._bars.length ? 'stale' : 'error', error: asError(error) });
      } else this._release(previous);
    }
  }
  private _release(unsubscribe: UnsubscribeFn | null): void {
    try { unsubscribe?.(); } catch { /* A provider cleanup cannot block the remaining owned resources. */ }
  }
  private _clearPoll(): void { if (this._poll !== null) clearTimeout(this._poll); this._poll = null; }
  private _schedulePoll(): void {
    this._clearPoll();
    if (!this._destroyed && this._visible && this._options.pollIntervalMs! > 0) {
      this._poll = setTimeout(() => { this._poll = null; void this.refresh(); }, this._options.pollIntervalMs);
    }
  }
  private _cancel(): void {
    const scope = this._scope;
    const refresh = this._refreshAbort;
    const page = this._pageAbort;
    const unsubscribe = this._unsubscribe;
    // Detach ownership before callbacks: a provider may synchronously open the
    // next context from an abort or unsubscribe handler.
    this._refreshAbort = null;
    this._pageAbort = null;
    this._loadWork = null;
    this._pageWork = null;
    this._buffer = null;
    this._pendingRepair = null;
    this._stream++;
    this._unsubscribe = null;
    this._clearPoll();
    this._clearRepairTimer();
    scope.abort();
    refresh?.abort();
    page?.abort();
    this._release(unsubscribe);
  }
}
