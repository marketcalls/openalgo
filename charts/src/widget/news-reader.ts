/**
 * An instrument's news, without DOM: the newest page, older pages by the
 * provider's cursor, and one lifecycle per instrument. Switching instrument or
 * destroying aborts what is in flight, and an answer that arrives anyway is
 * dropped by generation, because a provider may ignore the signal. Text is
 * kept as plain text; deciding which links are safe to open is the view's.
 */
import type { InstrumentKey, NewsFeed, NewsItem, NewsPage } from 'openalgo-charts';
import { errorText } from './localization';

export type NewsStatus = 'idle' | 'loading' | 'ready' | 'empty' | 'error';

export interface NewsSnapshot {
  instrument: InstrumentKey | null;
  /** `loading` covers a refresh too; the items already shown stay in `items`. */
  status: NewsStatus;
  /** Newest first, one per provider ID. */
  items: readonly NewsItem[];
  /** The provider offered an older page. */
  hasMore: boolean;
  loadingMore: boolean;
  /** The items shown could not be refreshed, or have outlived the stale window. */
  stale: boolean;
  /** The newest page failed to reload and the items shown are the earlier answer. */
  refreshFailed: boolean;
  /** The latest failure, cleared by the next success. */
  error: string | null;
  /** Local clock in milliseconds of the last newest-page answer. */
  loadedAt: number | null;
}

export interface NewsReaderOptions {
  feed: NewsFeed;
  /** Items asked for per page. Default 20. */
  pageSize?: number | undefined;
  /** News older than this since its load is flagged stale. Default 300000 ms. */
  staleAfterMs?: number | undefined;
  /** Items held at most; paging stops there. Default 500. */
  maxItems?: number | undefined;
  now?: () => number;
  onChange?(snapshot: NewsSnapshot): void;
}

const message = (error: unknown): string => errorText({}, error);
/** Control characters become spaces; a line break survives only where the field allows one. */
const controls = (value: string, breaks: boolean): string => Array.from(value, char => {
  const code = char.charCodeAt(0);
  return code >= 32 && code !== 127 ? char : breaks && char === '\n' ? char : ' ';
}).join('');
const line = (value: string, max: number): string => controls(value, false).replace(/\s+/g, ' ').trim().slice(0, max);
const block = (value: string, max: number): string => controls(value.replace(/\r\n?/g, '\n'), true).trim().slice(0, max);

/** A plain-text copy of a valid item, or null. Nothing here is ever markup. */
function sanitize(input: NewsItem): NewsItem | null {
  if (input === null || typeof input !== 'object') return null;
  const { id, time } = input;
  const headline = typeof input.headline === 'string' ? line(input.headline, 500) : '';
  if (typeof id !== 'string' || id === '' || id.length > 256 || headline === '' || typeof time !== 'number' || !Number.isFinite(time) || time <= 0) return null;
  const out: NewsItem = { id, headline, time };
  const source = typeof input.source === 'string' ? line(input.source, 120) : '';
  if (source !== '') out.source = source;
  const summary = typeof input.summary === 'string' ? block(input.summary, 4000) : '';
  if (summary !== '') out.summary = summary;
  if (typeof input.url === 'string' && input.url.length <= 2048) out.url = input.url.trim();
  return out;
}

export class NewsReader {
  private readonly _feed: NewsFeed;
  private readonly _pageSize: number;
  private readonly _staleAfter: number;
  private readonly _maxItems: number;
  private readonly _now: () => number;
  private readonly _onChange: (snapshot: NewsSnapshot) => void;
  private _instrument: InstrumentKey | null = null;
  private _status: NewsStatus = 'idle';
  private _items: NewsItem[] = [];
  private _cursor: string | null = null;
  private _loadingMore = false;
  private _refreshFailed = false;
  private _error: string | null = null;
  private _loadedAt: number | null = null;
  private _generation = 0;
  private readonly _controllers = new Set<AbortController>();
  private _staleTimer: ReturnType<typeof setTimeout> | null = null;
  private _destroyed = false;

  constructor(options: NewsReaderOptions) {
    this._feed = options.feed;
    this._pageSize = Math.max(1, Math.min(100, Math.round(options.pageSize ?? 20)));
    this._staleAfter = Math.max(0, options.staleAfterMs ?? 300000);
    this._maxItems = Math.max(1, Math.round(options.maxItems ?? 500));
    this._now = options.now ?? Date.now;
    this._onChange = snapshot => { if (!this._destroyed) options.onChange?.(snapshot); };
  }

  /** Follow another instrument. The same identity is a no-op; null clears the list. */
  setInstrument(instrument: InstrumentKey | null): void {
    if (this._destroyed) return;
    const next = instrument === null ? null : { symbol: instrument.symbol, exchange: instrument.exchange };
    const current = this._instrument;
    if (next?.symbol === current?.symbol && next?.exchange === current?.exchange) return;
    this._cancel();
    this._instrument = next;
    this._items = [];
    this._cursor = null;
    this._error = null;
    this._refreshFailed = false;
    this._loadedAt = null;
    this._status = 'idle';
    if (next === null) { this._emit(); return; }
    void this.refresh();
  }

  /** Reload the newest page. The items shown stay until it answers. */
  async refresh(): Promise<void> {
    if (this._destroyed || this._instrument === null) return;
    this._cancel();
    this._status = 'loading';
    this._emit();
    const page = await this._request();
    if (page === undefined) return;
    if (page instanceof Error) {
      this._error = page.message;
      if (this._items.length > 0) { this._status = 'ready'; this._refreshFailed = true; }
      else this._status = 'error';
    } else {
      this._items = [];
      this._cursor = this._take(page.items) > 0 ? this._nextCursor(page, undefined) : null;
      this._status = this._items.length > 0 ? 'ready' : 'empty';
      this._error = null;
      this._refreshFailed = false;
      this._loadedAt = this._now();
      this._scheduleStale();
    }
    this._emit();
  }

  /** Append the next older page, if the provider offered one and none is loading. */
  async loadMore(): Promise<void> {
    if (this._destroyed || this._status !== 'ready' || this._cursor === null || this._loadingMore) return;
    const cursor = this._cursor;
    this._loadingMore = true;
    this._emit();
    const page = await this._request(cursor);
    if (page === undefined) return;
    this._loadingMore = false;
    if (page instanceof Error) this._error = page.message;
    else {
      this._cursor = this._take(page.items) > 0 ? this._nextCursor(page, cursor) : null;
      this._error = null;
    }
    this._emit();
  }

  snapshot(): NewsSnapshot {
    const age = this._loadedAt === null ? 0 : this._now() - this._loadedAt;
    return {
      instrument: this._instrument === null ? null : { ...this._instrument },
      status: this._status,
      items: this._items.slice(),
      hasMore: this._cursor !== null,
      loadingMore: this._loadingMore,
      stale: this._refreshFailed || (this._loadedAt !== null && age > this._staleAfter),
      refreshFailed: this._refreshFailed,
      error: this._error,
      loadedAt: this._loadedAt,
    };
  }

  destroy(): void {
    if (this._destroyed) return;
    this._cancel();
    this._destroyed = true;
  }

  /** One page for the current instrument; undefined when superseded, an Error when it failed. */
  private async _request(cursor?: string): Promise<NewsPage | Error | undefined> {
    const instrument = this._instrument!;
    const generation = this._generation;
    const controller = new AbortController();
    this._controllers.add(controller);
    try {
      const page = await this._feed.getNews({
        symbol: instrument.symbol, exchange: instrument.exchange, limit: this._pageSize,
        ...(cursor === undefined ? {} : { cursor }), signal: controller.signal,
      });
      if (generation !== this._generation || this._destroyed) return undefined;
      return page !== null && typeof page === 'object' && Array.isArray(page.items) ? page : new Error('The news source returned no page');
    } catch (error) {
      return generation !== this._generation || this._destroyed ? undefined : new Error(message(error));
    } finally {
      this._controllers.delete(controller);
    }
  }

  /** Merge a page, newest first, one per ID. Returns how many were new, or 0 once the cap stops paging. */
  private _take(items: readonly NewsItem[]): number {
    const seen = new Set(this._items.map(existing => existing.id));
    let added = 0;
    for (const raw of items) {
      const clean = sanitize(raw);
      if (clean === null || seen.has(clean.id)) continue;
      seen.add(clean.id);
      this._items.push(clean);
      added++;
    }
    // Stable, so items sharing a timestamp keep the provider's order.
    this._items.sort((a, b) => b.time - a.time);
    if (this._items.length >= this._maxItems) { this._items.length = this._maxItems; return 0; }
    return added;
  }

  /** The next cursor, or null when there is none or it would ask for the same page again. */
  private _nextCursor(page: NewsPage, requested: string | undefined): string | null {
    const next = page.nextCursor;
    return typeof next === 'string' && next !== '' && next !== requested ? next : null;
  }

  private _cancel(): void {
    this._generation++;
    for (const controller of this._controllers) controller.abort();
    this._controllers.clear();
    this._loadingMore = false;
    if (this._staleTimer !== null) { clearTimeout(this._staleTimer); this._staleTimer = null; }
  }

  private _scheduleStale(): void {
    if (this._staleTimer !== null) clearTimeout(this._staleTimer);
    // Nothing else happens when news ages, so the reader says so itself.
    this._staleTimer = setTimeout(() => { this._staleTimer = null; this._emit(); }, this._staleAfter + 1);
  }

  private _emit(): void { this._onChange(this.snapshot()); }
}
