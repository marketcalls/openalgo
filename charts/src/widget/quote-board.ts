/**
 * Quote state for a list of instruments, without DOM.
 *
 * The board holds one stream per visible instrument and nothing for the rest,
 * so a watchlist of hundreds costs only what is on screen. It reports every
 * quote with a status that says how far to trust it: a quote held while its
 * stream reconnects, or one that outlived its row's visibility, is stale until
 * a fresh answer replaces it. It never derives a quote from bars.
 */
import type { InstrumentKey, QuoteFeed, QuoteSnapshot, QuoteStreamStatus, UnsubscribeFn } from 'openalgo-charts';
import { errorText } from './localization';
import { MAX_DELAY } from '../helpers/timers';

/** How far a row's quote can be trusted right now. */
export type QuoteRowStatus = 'loading' | 'live' | 'delayed' | 'snapshot' | 'stale' | 'unavailable' | 'error';
/** The whole board: the source kind and the worst stream state among visible rows. */
export type QuoteBoardStatus = 'unavailable' | 'idle' | 'snapshot' | 'connecting' | 'live' | 'reconnecting' | 'disconnected' | 'error';

export interface QuoteRow {
  instrument: InstrumentKey;
  quote: QuoteSnapshot | null;
  status: QuoteRowStatus;
  /** Local clock in milliseconds when the quote shown arrived. */
  receivedAt: number | null;
}

export interface QuoteBoardOptions {
  /** Without one, every row is `unavailable`. */
  feed?: QuoteFeed | null | undefined;
  /** A snapshot older than this is stale. Default 60000 ms. */
  staleAfterMs?: number | undefined;
  /** Refresh interval for visible rows when the source cannot stream. 0 disables. Default 15000 ms. */
  pollMs?: number | undefined;
  now?: () => number;
  /** Called after any change a row or the status shows. */
  onChange?(): void;
}

interface Stream { status: QuoteStreamStatus; closed: boolean; stop: UnsubscribeFn }
interface Entry {
  key: InstrumentKey;
  quote: QuoteSnapshot | null;
  receivedAt: number | null;
  /** Sequence of the last pushed quote, so an older snapshot answer cannot overwrite it. */
  pushed: number;
  /** A quote arrived since the row last became visible or its stream reconnected. */
  fresh: boolean;
  /** The source answered without this instrument. */
  missing: boolean;
  error: string | null;
  stream: Stream | null;
}
interface Request { controller: AbortController; ids: Set<string>; seq: number }

const RETAINED = 1000;
const idOf = (key: InstrumentKey): string => JSON.stringify([key.symbol, key.exchange]);
const message = (error: unknown): string => errorText({}, error);
const finite = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

/** Change and percent change against the provider's reference close, or null when it gave none. */
export function quoteChange(quote: QuoteSnapshot): { change: number; percent: number } | null {
  const reference = quote.previousClose;
  if (!finite(reference) || reference <= 0 || !finite(quote.last)) return null;
  const change = quote.last - reference;
  return { change, percent: change / reference * 100 };
}

/** A validated copy: an unknown field stays absent rather than becoming zero. */
function sanitize(input: QuoteSnapshot, key: InstrumentKey): QuoteSnapshot | null {
  if (input === null || typeof input !== 'object' || input.symbol !== key.symbol || (input.exchange ?? '') !== key.exchange || !finite(input.last)) return null;
  const out: QuoteSnapshot = { symbol: key.symbol, exchange: key.exchange, last: input.last };
  for (const field of ['previousClose', 'bid', 'ask', 'volume', 'time'] as const) if (finite(input[field])) out[field] = input[field];
  if (input.delayed === true) out.delayed = true;
  return out;
}

export class QuoteBoard {
  private readonly _feed: QuoteFeed | null;
  private readonly _staleAfter: number;
  private readonly _pollMs: number;
  private readonly _now: () => number;
  private readonly _onChange: () => void;
  private readonly _entries = new Map<string, Entry>();
  private _visible = new Set<string>();
  private readonly _requests = new Set<Request>();
  private _seq = 0;
  private _error: string | null = null;
  private _poll: ReturnType<typeof setTimeout> | null = null;
  private _stale: ReturnType<typeof setTimeout> | null = null;
  private _resync: InstrumentKey[] | null = null;
  private _destroyed = false;

  constructor(options: QuoteBoardOptions) {
    this._feed = options.feed ?? null;
    this._staleAfter = Math.max(0, options.staleAfterMs ?? 60000);
    this._pollMs = Math.max(0, options.pollMs ?? 15000);
    this._now = options.now ?? Date.now;
    this._onChange = () => { if (!this._destroyed) options.onChange?.(); };
  }

  /** The instruments on screen. Streams and snapshot requests follow this set exactly. */
  setVisible(instruments: readonly InstrumentKey[]): void {
    if (this._destroyed) return;
    const next = new Map<string, InstrumentKey>();
    for (const item of instruments) next.set(idOf(item), { symbol: item.symbol, exchange: item.exchange });
    for (const id of this._visible) if (!next.has(id)) this._hide(id);
    const added: InstrumentKey[] = [];
    const before = this._visible;
    this._visible = new Set(next.keys());
    for (const [id, key] of next) if (!before.has(id)) { this._show(id, key); added.push(key); }
    // A request whose rows have all left the screen is no longer wanted by anyone.
    for (const request of this._requests) {
      if (![...request.ids].some(id => this._visible.has(id))) { request.controller.abort(); this._requests.delete(request); }
    }
    this._trim();
    if (added.length > 0) this._snapshot(added);
    this._schedulePoll();
    // A row that left the screen no longer needs its deadline watched.
    this._scheduleStale();
    this._onChange();
  }

  row(instrument: InstrumentKey): QuoteRow {
    const key = { symbol: instrument.symbol, exchange: instrument.exchange };
    const entry = this._entries.get(idOf(key));
    const row = (status: QuoteRowStatus): QuoteRow => ({ instrument: key, quote: entry?.quote ? { ...entry.quote } : null, status, receivedAt: entry?.receivedAt ?? null });
    if (this._feed === null) return row('unavailable');
    if (!entry?.quote) return row(entry?.error ? 'error' : entry?.missing ? 'unavailable' : 'loading');
    const delayed = entry.quote.delayed === true;
    if (!entry.fresh || !this._visible.has(idOf(key))) return row('stale');
    const stream = entry.stream?.status;
    if (stream === 'live') return row(delayed ? 'delayed' : 'live');
    if (stream === 'reconnecting' || stream === 'disconnected') return row('stale');
    // Snapshot-only, or a stream still connecting: trust the answer while it is young.
    if (this._now() - (entry.receivedAt ?? 0) > this._staleAfter) return row('stale');
    return row(delayed ? 'delayed' : 'snapshot');
  }

  status(): QuoteBoardStatus {
    if (this._feed === null) return 'unavailable';
    const streams = [...this._visible].map(id => this._entries.get(id)?.stream).filter((s): s is Stream => !!s && !s.closed);
    if (streams.length === 0) return this._error !== null ? 'error' : this._visible.size > 0 && !this._feed.subscribeQuotes ? 'snapshot' : 'idle';
    for (const state of ['disconnected', 'reconnecting', 'connecting'] as const) if (streams.some(s => s.status === state)) return state;
    return 'live';
  }

  /** The last snapshot failure, cleared by the next success. */
  error(): string | null { return this._error; }

  /** Instruments with an open stream, in screen order. */
  subscribed(): InstrumentKey[] {
    return [...this._visible].map(id => this._entries.get(id)).filter((e): e is Entry => !!e?.stream && !e.stream.closed).map(e => ({ ...e.key }));
  }

  destroy(): void {
    if (this._destroyed) return;
    this._destroyed = true;
    for (const entry of this._entries.values()) entry.stream?.stop();
    for (const request of this._requests) request.controller.abort();
    this._requests.clear();
    if (this._poll !== null) clearTimeout(this._poll);
    if (this._stale !== null) clearTimeout(this._stale);
    this._entries.clear();
    this._visible.clear();
  }

  private _show(id: string, key: InstrumentKey): void {
    let entry = this._entries.get(id);
    if (!entry) {
      entry = { key, quote: null, receivedAt: null, pushed: 0, fresh: false, missing: false, error: null, stream: null };
      this._entries.set(id, entry);
    } else {
      // Map order is the retention order: a row seen again is the newest.
      this._entries.delete(id); this._entries.set(id, entry);
    }
    entry.fresh = false; entry.missing = false; entry.error = null;
    const feed = this._feed;
    if (!feed?.subscribeQuotes) return;
    const stream: Stream = { status: 'connecting', closed: false, stop: () => {} };
    entry.stream = stream;
    const target = entry;
    try {
      const stop = feed.subscribeQuotes([{ ...key }], {
        onQuote: quote => {
          if (stream.closed || this._destroyed) return;
          const clean = sanitize(quote, key);
          if (clean === null) return;
          // The first quote a stream delivers is the evidence that it works.
          if (stream.status === 'connecting') stream.status = 'live';
          target.pushed = ++this._seq;
          this._accept(target, clean);
          this._scheduleStale();
          this._onChange();
        },
        onStatus: status => {
          if (stream.closed || this._destroyed) return;
          const was = stream.status;
          stream.status = status;
          if (status === 'live' && (was === 'reconnecting' || was === 'disconnected')) {
            // Updates may have been missed while the stream was down.
            target.fresh = false;
            this._queueResync(key);
          }
          // Whether age can make this row stale depends on the stream's state.
          this._scheduleStale();
          this._onChange();
        },
      });
      stream.stop = () => { stream.closed = true; try { stop(); } catch { /* A provider failing to release cannot keep the row. */ } };
    } catch (error) {
      stream.closed = true;
      entry.stream = null;
      entry.error = message(error);
    }
  }

  private _hide(id: string): void {
    const entry = this._entries.get(id);
    if (!entry) return;
    entry.stream?.stop();
    entry.stream = null;
    entry.fresh = false;
  }

  private _trim(): void {
    for (const [id] of this._entries) {
      if (this._entries.size <= RETAINED) break;
      if (!this._visible.has(id)) this._entries.delete(id);
    }
  }

  private _accept(entry: Entry, quote: QuoteSnapshot): void {
    entry.quote = quote;
    entry.receivedAt = this._now();
    entry.fresh = true;
    entry.missing = false;
    entry.error = null;
  }

  private _queueResync(key: InstrumentKey): void {
    if (this._resync !== null) { this._resync.push(key); return; }
    this._resync = [key];
    // Streams sharing one connection report the same reconnect together: ask once.
    queueMicrotask(() => {
      const keys = (this._resync ?? []).filter(item => this._visible.has(idOf(item)));
      this._resync = null;
      if (keys.length > 0 && !this._destroyed) this._snapshot(keys);
    });
  }

  private _snapshot(keys: InstrumentKey[]): void {
    const feed = this._feed;
    if (feed === null || this._destroyed) return;
    const request: Request = { controller: new AbortController(), ids: new Set(keys.map(idOf)), seq: ++this._seq };
    this._requests.add(request);
    let answer: Promise<QuoteSnapshot[]>;
    try { answer = Promise.resolve(feed.getQuotes({ instruments: keys.map(key => ({ ...key })), signal: request.controller.signal })); }
    catch (error) { answer = Promise.reject(error); }
    answer.then(quotes => {
      if (!this._requests.delete(request) || this._destroyed) return;
      const answered = new Set<string>();
      for (const quote of Array.isArray(quotes) ? quotes : []) {
        const id = quote && typeof quote === 'object' ? idOf({ symbol: quote.symbol, exchange: quote.exchange ?? '' }) : '';
        const entry = this._entries.get(id);
        if (!entry || !request.ids.has(id) || !this._visible.has(id)) continue;
        const clean = sanitize(quote, entry.key);
        if (clean === null) continue;
        answered.add(id);
        if (entry.pushed > request.seq) continue;
        this._accept(entry, clean);
      }
      for (const id of request.ids) {
        const entry = this._entries.get(id);
        if (entry && !answered.has(id) && this._visible.has(id) && !entry.quote) entry.missing = true;
      }
      this._error = null;
      this._scheduleStale();
      this._onChange();
    }, error => {
      if (!this._requests.delete(request) || this._destroyed) return;
      this._error = message(error);
      for (const id of request.ids) {
        const entry = this._entries.get(id);
        if (entry && !entry.quote && this._visible.has(id)) entry.error = this._error;
      }
      this._onChange();
    });
  }

  private _schedulePoll(): void {
    if (this._poll !== null) { clearTimeout(this._poll); this._poll = null; }
    if (this._destroyed || this._feed === null || this._feed.subscribeQuotes || this._pollMs === 0 || this._visible.size === 0) return;
    this._poll = setTimeout(() => {
      this._poll = null;
      this._snapshot([...this._visible].map(id => this._entries.get(id)!.key));
      this._schedulePoll();
    }, Math.min(this._pollMs, MAX_DELAY));
  }

  /** When a visible row turns stale by age alone, or null when age cannot change what it shows. */
  private _expires(id: string): number | null {
    const entry = this._entries.get(id);
    if (!entry?.fresh || entry.quote === null || entry.receivedAt === null) return null;
    // A live stream vouches for its quote however quiet the market; a broken one is stale already.
    const stream = entry.stream?.status;
    return stream === 'live' || stream === 'reconnecting' || stream === 'disconnected' ? null : entry.receivedAt + this._staleAfter;
  }

  /**
   * One timer, for the next moment a row on screen ages into stale. A deadline
   * already passed is a row already shown stale, so an idle board waits for
   * nothing and repaints nothing.
   */
  private _scheduleStale(): void {
    if (this._stale !== null) { clearTimeout(this._stale); this._stale = null; }
    if (this._destroyed) return;
    const now = this._now();
    let next = Infinity;
    for (const id of this._visible) {
      const at = this._expires(id);
      if (at !== null && at >= now) next = Math.min(next, at);
    }
    if (next === Infinity) return;
    this._stale = setTimeout(() => {
      this._stale = null;
      // row() calls a quote stale once its age exceeds the window; a timer that fires early changes nothing,
      // which is also how a deadline beyond the longest delay is waited out in steps.
      if (this._now() > next) this._onChange();
      this._scheduleStale();
    }, Math.min(next - now + 1, MAX_DELAY));
  }
}
