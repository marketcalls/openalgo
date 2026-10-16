import { afterEach, describe, expect, it, vi } from 'vitest';
import { referenceQuoteFeed, referenceNewsFeed, watchlistSymbolSearch, panelStorage, referencePanelStorage } from '../src/market-panels.js';

const response = (body, status = 200) => ({ ok: status < 400, status, json: async () => body });

function server() {
  const asked = [];
  let fail = false;
  const fetchImpl = vi.fn(async url => {
    asked.push(decodeURIComponent(String(url).split('symbols=')[1]));
    if (fail) return response({ error: 'fixture: offline' }, 502);
    return response(decodeURIComponent(String(url).split('symbols=')[1]).split(',').map((symbol, i) => ({
      symbol, exchange: '', last: 100 + i, previousClose: 99, time: 1700000000,
    })));
  });
  return { fetchImpl, asked, setFail: on => { fail = on; } };
}

afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });

describe('reference quote feed', () => {
  it('answers every row stream from one shared poll and skips what the source cannot quote', async () => {
    vi.useFakeTimers();
    const s = server();
    const feed = referenceQuoteFeed({ pollMs: 1000, fetchImpl: s.fetchImpl });
    const seen = { A: [], B: [] };
    const status = [];
    const offA = feed.subscribeQuotes([{ symbol: 'AAPL', exchange: '' }], { onQuote: q => seen.A.push(q.last), onStatus: v => status.push(v) });
    feed.subscribeQuotes([{ symbol: 'MSFT', exchange: '' }], { onQuote: q => seen.B.push(q.last) });
    feed.subscribeQuotes([{ symbol: 'AAPL/MSFT', exchange: '' }], { onQuote: () => { throw new Error('an expression has no quote'); } });
    await vi.advanceTimersByTimeAsync(0);
    expect(s.asked).toEqual(['AAPL,MSFT']);
    expect(seen).toEqual({ A: [100], B: [101] });
    expect(status).toEqual(['connecting', 'live']);
    await vi.advanceTimersByTimeAsync(1000);
    expect(s.asked).toHaveLength(2);
    offA();
    await vi.advanceTimersByTimeAsync(1000);
    expect(s.asked[2]).toBe('MSFT');
    expect(feed.subscribed()).toEqual(['MSFT', 'AAPL/MSFT']);
  });

  it('reports a failed poll as reconnecting and the next good one as live', async () => {
    vi.useFakeTimers();
    const s = server();
    const feed = referenceQuoteFeed({ pollMs: 1000, fetchImpl: s.fetchImpl });
    const status = [];
    feed.subscribeQuotes([{ symbol: 'AAPL', exchange: '' }], { onQuote: () => {}, onStatus: (v, error) => status.push(error ? `${v}: ${error.message}` : v) });
    await vi.advanceTimersByTimeAsync(0);
    s.setFail(true);
    await vi.advanceTimersByTimeAsync(1000);
    s.setFail(false);
    await vi.advanceTimersByTimeAsync(1000);
    expect(status).toEqual(['connecting', 'live', 'reconnecting: fixture: offline', 'live']);
    feed.setOffline(true);
    await vi.advanceTimersByTimeAsync(1000);
    expect(status.at(-1)).toBe('reconnecting: The quote server is unreachable');
  });

  it('reports a server without a quote source as disconnected and stops asking', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => response({ error: 'quotes are served only with --fixture', code: 'not_available' }, 501));
    const feed = referenceQuoteFeed({ pollMs: 1000, fetchImpl });
    const status = [];
    feed.subscribeQuotes([{ symbol: 'AAPL', exchange: '' }], { onQuote: () => {}, onStatus: (v, error) => status.push(error ? `${v}: ${error.message}` : v) });
    await vi.advanceTimersByTimeAsync(5000);
    expect(status).toEqual(['connecting', 'disconnected: quotes are served only with --fixture']);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('after a 501 answers every later ask itself: no snapshot request, and new rows start disconnected', async () => {
    vi.useFakeTimers();
    const fetchImpl = vi.fn(async () => response({ error: 'quotes are served only with --fixture', code: 'not_available' }, 501));
    const feed = referenceQuoteFeed({ pollMs: 1000, fetchImpl });
    // The panel asks for a snapshot as rows scroll into view, before any poll has run.
    await expect(feed.getQuotes({ instruments: [{ symbol: 'AAPL', exchange: '' }] })).rejects.toThrow('only with --fixture');
    await expect(feed.getQuotes({ instruments: [{ symbol: 'MSFT', exchange: '' }] })).rejects.toThrow('only with --fixture');
    const status = [];
    feed.subscribeQuotes([{ symbol: 'NVDA', exchange: '' }], { onQuote: () => {}, onStatus: v => status.push(v) });
    await vi.advanceTimersByTimeAsync(5000);
    await expect(feed.getQuotes({ instruments: [{ symbol: 'TCS.NS', exchange: '' }] })).rejects.toThrow('only with --fixture');
    expect(status).toEqual(['disconnected']);
    expect(fetchImpl).toHaveBeenCalledTimes(1);
  });

  it('stops polling once the last row unsubscribes', async () => {
    vi.useFakeTimers();
    const s = server();
    const feed = referenceQuoteFeed({ pollMs: 1000, fetchImpl: s.fetchImpl });
    const off = feed.subscribeQuotes([{ symbol: 'AAPL', exchange: '' }], { onQuote: () => {} });
    await vi.advanceTimersByTimeAsync(0);
    off();
    await vi.advanceTimersByTimeAsync(5000);
    expect(s.asked).toHaveLength(1);
    expect(feed.stats()).toMatchObject({ subscribes: 1, unsubscribes: 1, requests: 1 });
  });

  it('asks the snapshot endpoint only for tickers, with the caller\'s signal', async () => {
    const s = server();
    const feed = referenceQuoteFeed({ fetchImpl: s.fetchImpl });
    const signal = new AbortController().signal;
    expect(await feed.getQuotes({ instruments: [{ symbol: 'AAPL/MSFT', exchange: '' }], signal })).toEqual([]);
    expect(s.fetchImpl).not.toHaveBeenCalled();
    await feed.getQuotes({ instruments: [{ symbol: '^NSEI', exchange: '' }], signal });
    expect(s.fetchImpl).toHaveBeenCalledWith('/api/quotes?symbols=%5ENSEI', { signal, cache: 'no-store' });
  });
});

describe('reference news feed', () => {
  it('passes the cursor back untouched and refuses an expression', async () => {
    const fetchMock = vi.fn(async () => response({ items: [{ id: 'a', headline: 'A', time: 1 }], nextCursor: '5:1' }));
    vi.stubGlobal('fetch', fetchMock);
    const page = await referenceNewsFeed.getNews({ symbol: 'RELIANCE.NS', exchange: '', limit: 20, cursor: '9:1' });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/news?symbol=RELIANCE.NS&limit=20&cursor=9%3A1');
    expect(page).toEqual({ items: [{ id: 'a', headline: 'A', time: 1 }], nextCursor: '5:1' });
    await expect(referenceNewsFeed.getNews({ symbol: 'AAPL/MSFT', exchange: '', limit: 20 })).rejects.toThrow('one ticker');
    fetchMock.mockResolvedValueOnce(response({ error: 'fixture: FAIL always fails upstream' }, 502));
    await expect(referenceNewsFeed.getNews({ symbol: 'FAIL', exchange: '', limit: 20 })).rejects.toThrow('always fails');
  });

  it('keeps the ticker as the whole identity for watchlist search results', () => {
    const hit = watchlistSymbolSearch('reliance').find(item => item.symbol === 'RELIANCE.NS');
    expect(hit).toBeDefined();
    expect(hit.exchange).toBeUndefined();
  });
});

describe('reference panel storage', () => {
  it('keeps the watchlist sort where a rebuilt dock finds it again', () => {
    const saved = new Map();
    const local = { getItem: key => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: key => saved.delete(key) };
    // Each symbol load rebuilds the dock, and with it the panel: a new storage over the same page store.
    expect(panelStorage(local).set('watchlist-sort', { key: 'percent', direction: 'descending' })).toBe(true);
    expect(panelStorage(local).get('watchlist-sort')).toEqual({ key: 'percent', direction: 'descending' });
    expect([...saved.keys()]).toEqual(['oac-widget:yfinance-panels:watchlist-sort']);
  });

  it('falls back to one page-lifetime store when the page has none', () => {
    const shared = referencePanelStorage();
    expect(referencePanelStorage()).toBe(shared);
    expect(shared.set('watchlist-sort', { key: 'symbol', direction: 'ascending' })).toBe(true);
    expect(referencePanelStorage().get('watchlist-sort')).toEqual({ key: 'symbol', direction: 'ascending' });
  });
});
