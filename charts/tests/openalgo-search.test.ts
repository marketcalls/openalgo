import { describe, expect, it } from 'vitest';
import { OpenAlgoDataFeed } from '../src/feed/openalgo-rest';
import { OpenAlgoLiveDataFeed } from '../src/feed/openalgo-live';
import { withBarCache } from '../src/feed/cache';
import type { DataFeed, SymbolMatch } from '../src/feed/types';

// A placeholder, never a real key: the request body is asserted below.
const API_KEY = 'placeholder-key';

/** Rows in the platform's search shape, ranked the way it ranks them. */
const ROWS = [
  { symbol: 'NIFTY', brsymbol: 'Nifty 50', name: 'NIFTY', exchange: 'NSE_INDEX', brexchange: 'NSE_INDEX', token: '26000', expiry: '', strike: -1, lotsize: 1, instrumenttype: 'INDEX', tick_size: 0.05 },
  { symbol: 'NIFTY28OCT26FUT', brsymbol: 'NIFTY FUT 28 OCT 26', name: 'NIFTY', exchange: 'NFO', brexchange: 'NSE_FO', token: '35001', expiry: '28-OCT-26', strike: -1, lotsize: 65, instrumenttype: 'FUT', tick_size: 0.1 },
  { symbol: 'NIFTY28OCT2625000CE', brsymbol: 'NIFTY 25000 CE 28 OCT 26', name: 'NIFTY', exchange: 'NFO', brexchange: 'NSE_FO', token: '41001', expiry: '28-OCT-26', strike: 25000, lotsize: 65, instrumenttype: 'CE', tick_size: 0.05 },
  { symbol: 'NIFTY28OCT2625000PE', brsymbol: 'NIFTY 25000 PE 28 OCT 26', name: 'NIFTY', exchange: 'NFO', brexchange: 'NSE_FO', token: '41002', expiry: '28-OCT-26', strike: 25000, lotsize: 65, instrumenttype: 'PE', tick_size: 0.05 },
  { symbol: 'NIFTY25NOV2625500CE', brsymbol: 'NIFTY 25500 CE 25 NOV 26', name: 'NIFTY', exchange: 'NFO', brexchange: 'NSE_FO', token: '42001', expiry: '25-NOV-26', strike: 25500, lotsize: 65, instrumenttype: 'CE', tick_size: 0.05 },
  { symbol: 'NIFTY28OCT2625100CE', brsymbol: 'NIFTY 25100 CE 28 OCT 26', name: 'NIFTY', exchange: 'NFO', brexchange: 'NSE_FO', token: '41003', expiry: '28-OCT-26', strike: 25100, lotsize: 65, instrumenttype: 'CE', tick_size: 0.05 },
  { symbol: 'NIFTYBEES', brsymbol: 'NIFTYBEES-EQ', name: 'NIPPON INDIA ETF NIFTY BEES', exchange: 'NSE', brexchange: 'NSE', token: '10576', expiry: null, strike: -1, lotsize: 1, instrumenttype: 'EQ', tick_size: 0.01 },
  // Rows the mapper must not turn into hits.
  { symbol: '', name: 'blank', exchange: 'NSE' },
  { name: 'no symbol', exchange: 'NSE' },
  null,
];

function feedWith(answer: (url: string, init: RequestInit) => Promise<Partial<Response>> | Partial<Response>) {
  const calls: Array<{ url: string; init: RequestInit }> = [];
  const fetchImpl = (async (url: string, init: RequestInit) => {
    calls.push({ url, init });
    return answer(url, init);
  }) as unknown as typeof fetch;
  return { calls, feed: new OpenAlgoDataFeed({ baseUrl: 'https://openalgo.test', apiKey: API_KEY, fetchImpl }) };
}

const ok = (body: unknown): Partial<Response> => ({ ok: true, status: 200, json: async () => body });

describe('OpenAlgoDataFeed.searchSymbols', () => {
  it('posts the query to the search endpoint and maps rows onto picker results', async () => {
    const { calls, feed } = feedWith(() => ok({ status: 'success', message: 'Found 10 matching symbols', data: ROWS }));
    const hits = await feed.searchSymbols({ query: 'NIFTY' });
    expect(calls).toHaveLength(1);
    expect(calls[0].url).toBe('https://openalgo.test/api/v1/search');
    expect(calls[0].init.method).toBe('POST');
    expect((calls[0].init.headers as Record<string, string>)['Content-Type']).toBe('application/json');
    expect(JSON.parse(String(calls[0].init.body))).toEqual({ apikey: API_KEY, query: 'NIFTY' });
    expect(calls[0].init.signal).toBeInstanceOf(AbortSignal);
    // Ranked as the platform ranked them. Options of one underlying and expiry
    // share a row; an expiry with a single option lists that option itself.
    expect(hits).toEqual<SymbolMatch[]>([
      { symbol: 'NIFTY', exchange: 'NSE_INDEX', name: 'NIFTY', assetClass: 'Index' },
      { symbol: 'NIFTY28OCT26FUT', exchange: 'NFO', name: 'NIFTY', assetClass: 'Futures' },
      { symbol: 'NIFTY 28-OCT-26', exchange: 'NFO', assetClass: 'Options', contractGroup: { label: 'NIFTY 28-OCT-26', contracts: [
        { symbol: 'NIFTY28OCT2625000CE', exchange: 'NFO', name: 'NIFTY', assetClass: 'Options' },
        { symbol: 'NIFTY28OCT2625000PE', exchange: 'NFO', name: 'NIFTY', assetClass: 'Options' },
        { symbol: 'NIFTY28OCT2625100CE', exchange: 'NFO', name: 'NIFTY', assetClass: 'Options' },
      ] } },
      { symbol: 'NIFTY25NOV2625500CE', exchange: 'NFO', name: 'NIFTY', assetClass: 'Options' },
      { symbol: 'NIFTYBEES', exchange: 'NSE', name: 'NIPPON INDIA ETF NIFTY BEES', assetClass: 'Equity' },
    ]);
  });

  it('keeps an equity whose symbol ends like an option out of the option groups', async () => {
    const { feed } = feedWith(() => ok({ status: 'success', data: [
      { symbol: 'BAJFINANCE', name: 'BAJAJ FINANCE LIMITED', exchange: 'NSE', expiry: '' },
      { symbol: 'BAJFINANCE', name: 'BAJAJ FINANCE LIMITED', exchange: 'BSE' },
    ] }));
    expect(await feed.searchSymbols({ query: 'bajfinance' })).toEqual([
      { symbol: 'BAJFINANCE', exchange: 'NSE', name: 'BAJAJ FINANCE LIMITED', assetClass: 'Equity' },
      { symbol: 'BAJFINANCE', exchange: 'BSE', name: 'BAJAJ FINANCE LIMITED', assetClass: 'Equity' },
    ]);
  });

  it('shows at most fifty rows, the closest first', async () => {
    const data = Array.from({ length: 500 }, (_, i) => ({ symbol: `S${String(i).padStart(3, '0')}`, name: `Stock ${i}`, exchange: 'NSE', expiry: '' }));
    const { feed } = feedWith(() => ok({ status: 'success', data }));
    const hits = await feed.searchSymbols({ query: 'S' });
    expect(hits).toHaveLength(50);
    expect(hits[0].symbol).toBe('S000');
    expect(hits[49].symbol).toBe('S049');
  });

  it('answers a blank query with no hits and no request', async () => {
    const { calls, feed } = feedWith(() => ok({ status: 'success', data: ROWS }));
    expect(await feed.searchSymbols({ query: '   ' })).toEqual([]);
    expect(calls).toHaveLength(0);
  });

  it('treats no matches as an empty answer', async () => {
    const { feed } = feedWith(() => ok({ status: 'success', message: 'No matching symbols found', data: [] }));
    expect(await feed.searchSymbols({ query: 'ZZZZ' })).toEqual([]);
  });

  it('rejects a failed status or an error body without echoing the key', async () => {
    const denied = feedWith(() => ({ ok: false, status: 403, json: async () => ({ status: 'error', message: 'Invalid openalgo apikey' }) }));
    const refusal = await denied.feed.searchSymbols({ query: 'RELIANCE' }).catch((error: Error) => error);
    expect(refusal).toBeInstanceOf(Error);
    expect((refusal as Error).message).toContain('403');
    expect((refusal as Error).message).not.toContain(API_KEY);
    const failed = feedWith(() => ok({ status: 'error', message: 'Query parameter is required and cannot be empty' }));
    await expect(failed.feed.searchSymbols({ query: 'RELIANCE' })).rejects.toThrow('Query parameter is required');
    const odd = feedWith(() => ok({ status: 'error', message: { query: ['Missing'] } }));
    await expect(odd.feed.searchSymbols({ query: 'RELIANCE' })).rejects.toThrow(/search failed/);
  });

  it('cancels the request when the caller aborts', async () => {
    let seen: AbortSignal | null | undefined;
    const { feed } = feedWith((_url, init) => {
      seen = init.signal;
      return { ok: true, status: 200, json: () => new Promise(() => {}) };
    });
    const cancel = new AbortController();
    const pending = feed.searchSymbols({ query: 'INFY', signal: cancel.signal });
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    cancel.abort();
    await rejected;
    expect(seen?.aborted).toBe(true);
  });
});

describe('search through composed and wrapped feeds', () => {
  const socketFactory = () => ({ readyState: 0, send() {}, close() {}, onopen: null, onclose: null, onerror: null, onmessage: null }) as never;

  it('the live feed searches through its history adapter', async () => {
    const bodies: unknown[] = [];
    const fetchImpl = (async (_url: string, init: RequestInit) => {
      bodies.push(JSON.parse(String(init.body)));
      return ok({ status: 'success', data: [{ symbol: 'INFY', name: 'INFOSYS LIMITED', exchange: 'NSE', expiry: '' }] });
    }) as unknown as typeof fetch;
    const feed = new OpenAlgoLiveDataFeed({ baseUrl: 'https://openalgo.test', apiKey: API_KEY, wsUrl: 'ws://openalgo.test', fetchImpl, socketFactory });
    expect(await feed.searchSymbols({ query: 'INFY' })).toEqual([{ symbol: 'INFY', exchange: 'NSE', name: 'INFOSYS LIMITED', assetClass: 'Equity' }]);
    expect(bodies).toEqual([{ apikey: API_KEY, query: 'INFY' }]);
  });

  it('the bar cache forwards search only when the wrapped feed has it', async () => {
    const searching: DataFeed = { getBars: async () => [], searchSymbols: async request => [{ symbol: request.query, exchange: 'NSE' }] };
    const cached = withBarCache(searching);
    const signal = new AbortController().signal;
    expect(await cached.searchSymbols?.({ query: 'TCS', signal })).toEqual([{ symbol: 'TCS', exchange: 'NSE' }]);
    expect(withBarCache({ getBars: async () => [] }).searchSymbols).toBeUndefined();
  });
});
