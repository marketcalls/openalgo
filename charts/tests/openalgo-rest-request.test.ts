import { afterEach, describe, expect, it, vi } from 'vitest';
import { HistoryRequestPool } from '../src/feed/request-pool';
import { OpenAlgoDataFeed } from '../src/feed/openalgo-rest';

const request = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m', from: 100, to: 300 };
afterEach(() => vi.useRealTimers());

describe('history cancellation and deadlines', () => {
  it('omits unsupported OI using request-scoped host metadata without erasing genuine zero', async () => {
    const feed = new OpenAlgoDataFeed({
      baseUrl: 'https://feed.test', apiKey: 'fixture',
      hasOpenInterest: req => req.exchange === 'NFO' ? true : req.exchange === 'NSE' ? false : undefined,
      fetchImpl: (async () => ({ ok: true, json: async () => ({ data: [
        { timestamp: 100, open: 100, high: 101, low: 99, close: 100, oi: 0 },
        { timestamp: 200, open: 100, high: 101, low: 99, close: 100, oi: 140 },
      ] }) }) as Response) as typeof fetch,
    });
    const [cash, contract, unknown] = await Promise.all([
      feed.getBars({ ...request, exchange: 'NSE' }),
      feed.getBars(request),
      feed.getBars({ ...request, exchange: 'CUSTOM' }),
    ]);
    expect(cash.every(bar => !Object.prototype.hasOwnProperty.call(bar, 'oi'))).toBe(true);
    expect(contract.map(bar => bar.oi)).toEqual([0, 140]);
    expect(unknown.map(bar => bar.oi)).toEqual([0, 140]);
  });

  it('cancels an outstanding body read, even if the injected fetch ignores cancellation', async () => {
    let signal: AbortSignal | null | undefined;
    const feed = new OpenAlgoDataFeed({ baseUrl: 'https://feed.test', apiKey: 'fixture', fetchImpl: (async (_url, init) => {
      signal = init?.signal;
      return { ok: true, json: () => new Promise(() => {}) } as Response;
    }) as typeof fetch });
    const cancel = new AbortController();
    const pending = feed.getBars({ ...request, signal: cancel.signal });
    const rejected = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    await Promise.resolve();
    cancel.abort();
    await rejected;
    expect(signal?.aborted).toBe(true);
  });

  it('times out a stalled response body and clears its deadline after success', async () => {
    vi.useFakeTimers();
    const feed = new OpenAlgoDataFeed({ baseUrl: 'https://feed.test', apiKey: 'fixture', fetchImpl: (async () =>
      ({ ok: true, json: () => new Promise(() => {}) }) as Response) as typeof fetch });
    const pending = feed.getBars({ ...request, timeoutMs: 20 });
    const rejected = expect(pending).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(21);
    await rejected;
    expect(vi.getTimerCount()).toBe(0);
    const healthy = new OpenAlgoDataFeed({ baseUrl: 'https://feed.test', apiKey: 'fixture', fetchImpl: (async () =>
      ({ ok: true, json: async () => ({ data: [] }) }) as Response) as typeof fetch });
    expect(await healthy.getBars(request)).toEqual([]);
    expect(vi.getTimerCount()).toBe(0);
  });
  it('keeps a shared REST request alive for a later consumer with a longer deadline', async () => {
    vi.useFakeTimers();
    let finish!: (value: { data: [] }) => void;
    let signal: AbortSignal | null | undefined;
    let calls = 0;
    const feed = new OpenAlgoDataFeed({ baseUrl: 'https://feed.test', apiKey: 'fixture', fetchImpl: (async (_url, init) => {
      calls++;
      signal = init?.signal;
      return { ok: true, json: () => new Promise(resolve => { finish = resolve; }) } as Response;
    }) as typeof fetch });
    const pool = new HistoryRequestPool(feed);
    const first = pool.getBars({ ...request, timeoutMs: 1000 });
    const expired = expect(first).rejects.toMatchObject({ name: 'TimeoutError' });
    await vi.advanceTimersByTimeAsync(500);
    const second = pool.getBars({ ...request, timeoutMs: 20_000 });
    const secondOutcome = second.then(value => ({ value }), error => ({ error }));
    await vi.advanceTimersByTimeAsync(15_500);
    await expired;
    expect(signal?.aborted).toBe(false);
    finish({ data: [] });
    expect(await secondOutcome).toEqual({ value: [] });
    expect(calls).toBe(1);
    expect(vi.getTimerCount()).toBe(0);
  });

});
