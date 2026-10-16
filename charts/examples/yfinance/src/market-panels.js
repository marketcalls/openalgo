// Watchlists and news for the reference host: named lists kept in IndexedDB,
// quotes and news from this server's fixture endpoints. Nothing here reads a
// bar: a row's price is a quote or nothing.
//
// The quote feed answers the panel's per-row streams from one shared poll of
// /api/quotes, so ten visible rows cost one request per step, not ten. A poll
// that fails reports the stream as reconnecting, which the panel shows as
// stale; the next good poll reports it live again and the panel refetches.
import {
  WatchlistRepository, createIndexedDbWatchlistStorage, createMemoryWatchlistStorage,
} from '/dist/openalgo-charts.workspace.mjs';
import { WidgetStorage } from '/dist/openalgo-charts.widget.mjs';
import { referenceSymbolSearch } from './symbol-search.js';

const POLL_MS = 2000;
const NAMESPACE = 'yfinance';
const FIRST_LIST = ['AAPL', 'MSFT', 'NVDA', 'RELIANCE.NS', 'INFY.NS', 'TCS.NS', '^NSEI', 'BTC-USD'];
// The server's own symbol rule. An arithmetic expression (AAPL/MSFT) is not an
// instrument the source can quote, so it stays unknown rather than failing the batch.
const TICKER = /^\^?[A-Za-z0-9][A-Za-z0-9.\-=]{0,23}$/;

async function answer(response) {
  let body = null;
  try { body = await response.json(); } catch { /* A body that is not JSON reports the status below. */ }
  if (!response.ok) throw Object.assign(new Error(body?.error || `HTTP ${response.status}`), { status: response.status });
  return body;
}

/** One shared poll behind every row's stream. `setOffline` and `stats` are for the demo's tests. */
export function referenceQuoteFeed({ pollMs = POLL_MS, fetchImpl = (...args) => fetch(...args) } = {}) {
  const rows = new Map();
  const stats = { requests: 0, subscribes: 0, unsubscribes: 0 };
  let status = 'connecting';
  let timer = null;
  let inFlight = false;
  let offline = false;
  // A 501 means this server has no quote source at all. Its error answers every
  // later snapshot and poll here, so the page asks exactly once.
  let unavailable = null;
  const keyOf = instrument => JSON.stringify([instrument.symbol, instrument.exchange]);

  async function request(instruments, signal) {
    const symbols = [...new Set(instruments.filter(i => i.exchange === '' && TICKER.test(i.symbol)).map(i => i.symbol))];
    if (symbols.length === 0) return [];
    if (unavailable) throw unavailable;
    stats.requests++;
    if (offline) throw new Error('The quote server is unreachable');
    try {
      return await answer(await fetchImpl(`/api/quotes?symbols=${encodeURIComponent(symbols.join(','))}`, { signal, cache: 'no-store' }));
    } catch (error) {
      if (error?.status === 501) giveUp(error);
      throw error;
    }
  }
  function report(next, error) {
    if (next === status) return;
    status = next;
    for (const row of rows.values()) for (const handlers of row) handlers.onStatus?.(next, error);
  }
  function giveUp(error) {
    unavailable = error;
    if (timer !== null) { clearTimeout(timer); timer = null; }
    report('disconnected', error);
  }
  function schedule(delay) {
    if (timer === null && !inFlight && rows.size > 0 && !unavailable) timer = setTimeout(poll, delay);
  }
  async function poll() {
    timer = null;
    inFlight = true;
    try {
      const quotes = await request([...rows.keys()].map(key => { const [symbol, exchange] = JSON.parse(key); return { symbol, exchange }; }));
      report('live');
      for (const quote of quotes) for (const handlers of rows.get(keyOf(quote)) ?? []) handlers.onQuote(quote);
    } catch (error) {
      if (!unavailable) report('reconnecting', error);
    } finally {
      inFlight = false;
      schedule(pollMs);
    }
  }
  return {
    getQuotes: ({ instruments, signal }) => request(instruments, signal),
    subscribeQuotes(instruments, handlers) {
      stats.subscribes++;
      const keys = instruments.map(keyOf);
      for (const key of keys) {
        if (!rows.has(key)) rows.set(key, new Set());
        rows.get(key).add(handlers);
      }
      handlers.onStatus?.(status, unavailable ?? undefined);
      schedule(0);
      return () => {
        stats.unsubscribes++;
        for (const key of keys) {
          rows.get(key)?.delete(handlers);
          if (rows.get(key)?.size === 0) rows.delete(key);
        }
        if (rows.size === 0 && timer !== null) { clearTimeout(timer); timer = null; }
      };
    },
    subscribed: () => [...rows.keys()].map(key => JSON.parse(key)[0]),
    stats: () => ({ ...stats }),
    setOffline(on) { offline = Boolean(on); },
  };
}

/** News pages from /api/news. The cursor is the server's, passed back untouched. */
export const referenceNewsFeed = {
  async getNews({ symbol, exchange, cursor, limit, signal }) {
    if (exchange !== '' || !TICKER.test(symbol)) throw new Error('News follows one ticker, not an expression');
    const params = new URLSearchParams({ symbol, limit: String(limit) });
    if (cursor) params.set('cursor', cursor);
    const page = await answer(await fetch(`/api/news?${params}`, { signal, cache: 'no-store' }));
    return { items: page.items, nextCursor: page.nextCursor };
  },
};

/**
 * This host names an instrument by its ticker alone, which already carries
 * the venue (RELIANCE.NS). Search results keep that identity, so a saved row
 * matches the chart and the quote source.
 */
export const watchlistSymbolSearch = query => referenceSymbolSearch(query).map(({ exchange: _venue, ...hit }) => hit);

let store = null;
let quotes = null;

/** The page's one list store, shared by both charts' panels. A first visit gets a list to try. */
export function referenceWatchlists() {
  if (store) return store;
  const storage = typeof indexedDB === 'undefined' ? createMemoryWatchlistStorage()
    : createIndexedDbWatchlistStorage(indexedDB, 'openalgo-yfinance-watchlists');
  store = new WatchlistRepository(storage, NAMESPACE);
  store.load().then(catalog => {
    if (catalog.revision !== 0) return undefined;
    return store.createList('Reference', FIRST_LIST.map(symbol => ({ symbol, exchange: '' })))
      .then(list => store.setActiveList(list.id));
  }).catch(() => { /* The panel reports a storage failure itself. */ });
  return store;
}

export function referenceQuotes() {
  quotes ??= referenceQuoteFeed();
  return quotes;
}

function pageStorage() {
  try { return typeof globalThis.localStorage?.getItem === 'function' ? globalThis.localStorage : null; } catch { return null; }
}

function memoryStorage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => { values.set(key, String(value)); }, removeItem: key => { values.delete(key); } };
}

/**
 * Where the panels keep their own preferences, such as the watchlist's sort.
 * This host rebuilds a chart's dock whenever a symbol loads, and the alert
 * context the dock borrows stores nothing, so without this choosing a row
 * would drop the sort the row was chosen from.
 */
export function panelStorage(local = pageStorage()) {
  return new WidgetStorage('yfinance-panels', local ?? memoryStorage());
}

let panels = null;

/** The page's one panel store, shared by both charts; memory for the page's life when storage is blocked. */
export function referencePanelStorage() {
  panels ??= panelStorage();
  return panels;
}
