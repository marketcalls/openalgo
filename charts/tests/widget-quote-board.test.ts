import { afterEach, describe, expect, it, vi } from 'vitest';
import { QuoteBoard, quoteChange } from '../src/widget/quote-board';
import type { InstrumentKey, QuoteFeed, QuoteSnapshot, QuoteStreamHandlers, QuoteRequest } from '../src/feed/types';

const k = (symbol: string, exchange = 'NSE'): InstrumentKey => ({ symbol, exchange });
const q = (symbol: string, last: number, extra: Partial<QuoteSnapshot> = {}): QuoteSnapshot => ({ symbol, exchange: 'NSE', last, previousClose: 100, ...extra });
const tick = () => new Promise(resolve => setTimeout(resolve, 0));

interface Pending { request: QuoteRequest; resolve(value: QuoteSnapshot[]): void; reject(error: Error): void }

function streamingFeed() {
  const streams = new Map<string, QuoteStreamHandlers>();
  const log: string[] = [];
  const pending: Pending[] = [];
  const feed: QuoteFeed = {
    getQuotes: request => new Promise((resolve, reject) => { pending.push({ request, resolve, reject }); }),
    subscribeQuotes(instruments, handlers) {
      const id = instruments.map(i => i.symbol).join(',');
      log.push(`+${id}`);
      streams.set(id, handlers);
      return () => { log.push(`-${id}`); streams.delete(id); };
    },
  };
  return { feed, streams, log, pending };
}

afterEach(() => { vi.useRealTimers(); });

describe('quote board', () => {
  it('subscribes only the visible instruments and releases exactly the ones that leave', () => {
    const { feed, log } = streamingFeed();
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A'), k('B')]);
    expect(log).toEqual(['+A', '+B']);
    board.setVisible([k('B'), k('C')]);
    expect(log).toEqual(['+A', '+B', '-A', '+C']);
    expect(board.subscribed().map(i => i.symbol)).toEqual(['B', 'C']);
    // The same symbol on another venue is another instrument with its own stream.
    board.setVisible([k('B'), k('C'), k('B', 'BSE')]);
    expect(log.slice(-1)).toEqual(['+B']);
    expect(board.subscribed()).toHaveLength(3);
    board.destroy();
  });

  it('asks for one snapshot per newly visible batch and aborts it when every row it served leaves', async () => {
    const { feed, pending } = streamingFeed();
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A'), k('B')]);
    expect(pending).toHaveLength(1);
    expect(pending[0].request.instruments).toEqual([k('A'), k('B')]);
    board.setVisible([k('B')]);
    // B still wants the answer, so the request survives.
    expect(pending[0].request.signal!.aborted).toBe(false);
    board.setVisible([k('Z')]);
    expect(pending[0].request.signal!.aborted).toBe(true);
    pending[0].resolve([q('A', 101), q('B', 102)]);
    await tick();
    expect(board.row(k('B')).quote).toBeNull();
    board.destroy();
  });

  it('destroy cancels every stream and request and ignores late callbacks', async () => {
    const { feed, streams, pending, log } = streamingFeed();
    const onChange = vi.fn();
    const board = new QuoteBoard({ feed, onChange });
    board.setVisible([k('A')]);
    const handlers = streams.get('A')!;
    board.destroy();
    expect(log).toEqual(['+A', '-A']);
    expect(pending[0].request.signal!.aborted).toBe(true);
    onChange.mockClear();
    handlers.onQuote(q('A', 150));
    handlers.onStatus?.('live');
    pending[0].resolve([q('A', 150)]);
    await tick();
    expect(onChange).not.toHaveBeenCalled();
    expect(board.row(k('A')).quote).toBeNull();
    board.setVisible([k('A')]);
    expect(log).toEqual(['+A', '-A']);
  });

  it('shows streamed quotes as live, stale while reconnecting, and refreshes the snapshot on reconnect', async () => {
    const { feed, streams, pending } = streamingFeed();
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A')]);
    expect(board.status()).toBe('connecting');
    const handlers = streams.get('A')!;
    handlers.onQuote(q('A', 101));
    // The first streamed quote is the evidence the stream works.
    expect(board.row(k('A'))).toMatchObject({ status: 'live', quote: { last: 101 } });
    expect(board.status()).toBe('live');
    handlers.onStatus!('reconnecting', new Error('socket closed'));
    expect(board.status()).toBe('reconnecting');
    expect(board.row(k('A'))).toMatchObject({ status: 'stale', quote: { last: 101 } });
    handlers.onStatus!('live');
    // Updates may have been missed while the stream was down. One request
    // serves every stream that reconnected in the same turn.
    await tick();
    expect(pending).toHaveLength(2);
    expect(pending[1].request.instruments).toEqual([k('A')]);
    expect(board.row(k('A')).status).toBe('stale');
    pending[1].resolve([q('A', 104)]);
    await tick();
    expect(board.row(k('A'))).toMatchObject({ status: 'live', quote: { last: 104 } });
    handlers.onStatus!('disconnected');
    expect(board.status()).toBe('disconnected');
    expect(board.row(k('A')).status).toBe('stale');
    board.destroy();
  });

  it('keeps a hidden row\'s last quote only as stale until a fresh answer arrives', async () => {
    const { feed, streams, pending } = streamingFeed();
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A')]);
    streams.get('A')!.onQuote(q('A', 101));
    board.setVisible([]);
    board.setVisible([k('A')]);
    expect(board.row(k('A'))).toMatchObject({ status: 'stale', quote: { last: 101 } });
    pending[pending.length - 1].resolve([q('A', 99)]);
    await tick();
    streams.get('A')!.onStatus!('live');
    expect(board.row(k('A'))).toMatchObject({ status: 'live', quote: { last: 99 } });
    board.destroy();
  });

  it('polls a snapshot-only source while rows are visible and ages quotes into stale when refreshes fail', async () => {
    vi.useFakeTimers();
    let now = 0;
    const calls: string[][] = [];
    let fail = false;
    const feed: QuoteFeed = {
      getQuotes: async ({ instruments }) => {
        calls.push(instruments.map(i => i.symbol));
        if (fail) throw new Error('offline');
        return instruments.map(i => q(i.symbol, 200));
      },
    };
    const board = new QuoteBoard({ feed, pollMs: 1000, staleAfterMs: 5000, now: () => now });
    board.setVisible([k('A'), k('B')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(board.status()).toBe('snapshot');
    expect(board.row(k('A'))).toMatchObject({ status: 'snapshot', quote: { last: 200 } });
    now = 1000;
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toEqual([['A', 'B'], ['A', 'B']]);
    fail = true;
    now = 2000;
    await vi.advanceTimersByTimeAsync(1000);
    expect(board.status()).toBe('error');
    expect(board.error()).toBe('offline');
    // Still inside the stale window: the last answer stands, flagged by the board status.
    expect(board.row(k('A')).status).toBe('snapshot');
    now = 7000;
    await vi.advanceTimersByTimeAsync(5000);
    expect(board.row(k('A')).status).toBe('stale');
    board.setVisible([]);
    const before = calls.length;
    await vi.advanceTimersByTimeAsync(10000);
    expect(calls).toHaveLength(before);
    board.destroy();
  });

  it('arms no stale timer behind a live stream, so a quiet market costs nothing', async () => {
    vi.useFakeTimers();
    const { feed, streams } = streamingFeed();
    const onChange = vi.fn();
    const board = new QuoteBoard({ feed, staleAfterMs: 200, onChange });
    board.setVisible([k('A')]);
    streams.get('A')!.onQuote(q('A', 101));
    expect(board.row(k('A')).status).toBe('live');
    onChange.mockClear();
    // A live stream vouches for its last quote however long nothing trades.
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(60000);
    expect(onChange).not.toHaveBeenCalled();
    expect(board.row(k('A')).status).toBe('live');
    // A stream that drops back to connecting leaves only the snapshot window to trust.
    streams.get('A')!.onQuote(q('A', 102));
    streams.get('A')!.onStatus!('connecting');
    expect(board.row(k('A')).status).toBe('snapshot');
    onChange.mockClear();
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(60000);
    expect(board.row(k('A')).status).toBe('stale');
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    board.destroy();
  });

  it('ages each snapshot into stale with one timer per transition, then schedules nothing and repaints nothing', async () => {
    vi.useFakeTimers();
    const feed: QuoteFeed = { getQuotes: async ({ instruments }) => instruments.map(i => q(i.symbol, 200)) };
    const onChange = vi.fn();
    const board = new QuoteBoard({ feed, pollMs: 0, staleAfterMs: 1000, onChange });
    board.setVisible([k('A')]);
    await vi.advanceTimersByTimeAsync(300);
    board.setVisible([k('A'), k('B')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(board.row(k('A')).status).toBe('snapshot');
    expect(board.row(k('B')).status).toBe('snapshot');
    onChange.mockClear();
    // One timer, for the next row to age: A, answered 300 ms before B.
    expect(vi.getTimerCount()).toBe(1);
    await vi.advanceTimersByTimeAsync(701);
    expect(board.row(k('A')).status).toBe('stale');
    expect(board.row(k('B')).status).toBe('snapshot');
    expect(onChange).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(300);
    expect(board.row(k('B')).status).toBe('stale');
    expect(onChange).toHaveBeenCalledTimes(2);
    // Every row on screen is already stale: nothing is left to wait for.
    expect(vi.getTimerCount()).toBe(0);
    await vi.advanceTimersByTimeAsync(600000);
    expect(onChange).toHaveBeenCalledTimes(2);
    board.destroy();
  });

  it('waits out a stale window longer than one timer delay can hold, instead of re-arming at once', async () => {
    vi.useFakeTimers();
    const feed: QuoteFeed = { getQuotes: async ({ instruments }) => instruments.map(i => q(i.symbol, 200)) };
    const onChange = vi.fn();
    // Thirty days: past the 2^31 - 1 ms a timer delay holds before it wraps and fires at once.
    const window = 30 * 24 * 3600 * 1000;
    const board = new QuoteBoard({ feed, pollMs: 0, staleAfterMs: window, onChange });
    board.setVisible([k('A')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(board.row(k('A')).status).toBe('snapshot');
    onChange.mockClear();
    const armed = vi.spyOn(globalThis, 'setTimeout');
    await vi.advanceTimersByTimeAsync(1000);
    const rearmed = armed.mock.calls.length;
    armed.mockRestore();
    expect(rearmed).toBe(0);
    await vi.advanceTimersByTimeAsync(window - 1000);
    expect(board.row(k('A')).status).toBe('snapshot');
    expect(onChange).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(board.row(k('A')).status).toBe('stale');
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
    board.destroy();
  });

  it('polls no faster than asked when the interval is longer than one timer delay can hold', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const feed: QuoteFeed = { getQuotes: async ({ instruments }) => { calls++; return instruments.map(i => q(i.symbol, 200)); } };
    const board = new QuoteBoard({ feed, pollMs: 2 ** 31 });
    board.setVisible([k('A')]);
    await vi.advanceTimersByTimeAsync(0);
    expect(calls).toBe(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(calls).toBe(1);
    board.destroy();
  });

  it('ignores quotes for another instrument, non-finite prices and instruments nobody asked for', async () => {
    const { feed, streams, pending } = streamingFeed();
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A')]);
    const handlers = streams.get('A')!;
    handlers.onQuote({ symbol: 'A', exchange: 'BSE', last: 1 });
    handlers.onQuote({ symbol: 'B', exchange: 'NSE', last: 2 });
    handlers.onQuote({ symbol: 'A', exchange: 'NSE', last: Number.NaN });
    expect(board.row(k('A')).quote).toBeNull();
    pending[0].resolve([q('Q', 5), { symbol: 'A', exchange: 'NSE', last: 7, previousClose: Number.POSITIVE_INFINITY, bid: 6.5 }]);
    await tick();
    expect(board.row(k('Q')).quote).toBeNull();
    // Non-finite optional fields are unknown, not copied.
    expect(board.row(k('A')).quote).toEqual({ symbol: 'A', exchange: 'NSE', last: 7, bid: 6.5 });
    board.destroy();
  });

  it('without a quote source every row is unavailable and no price is shown', () => {
    const board = new QuoteBoard({ feed: undefined });
    board.setVisible([k('A')]);
    expect(board.status()).toBe('unavailable');
    expect(board.row(k('A'))).toEqual({ instrument: k('A'), quote: null, status: 'unavailable', receivedAt: null });
    board.destroy();
  });

  it('marks an instrument the source did not answer as unavailable, and a failed first snapshot as an error', async () => {
    const answers: Array<() => Promise<QuoteSnapshot[]>> = [async () => [q('A', 1)], async () => { throw new Error('bad gateway'); }];
    const feed: QuoteFeed = { getQuotes: () => answers.shift()!() };
    const board = new QuoteBoard({ feed, pollMs: 0 });
    board.setVisible([k('A'), k('B')]);
    await tick();
    expect(board.row(k('B')).status).toBe('unavailable');
    board.setVisible([k('A'), k('B'), k('C')]);
    await tick();
    expect(board.row(k('C')).status).toBe('error');
    expect(board.row(k('A')).status).toBe('snapshot');
    board.destroy();
  });

  it('reports delayed quotes as delayed, and a provider that throws on subscribe as an error row', async () => {
    const feed: QuoteFeed = {
      getQuotes: async ({ instruments }) => instruments.map(i => q(i.symbol, 10, { delayed: true })),
      subscribeQuotes: () => { throw new Error('no entitlement'); },
    };
    const board = new QuoteBoard({ feed });
    board.setVisible([k('A')]);
    expect(board.row(k('A')).status).toBe('error');
    await tick();
    expect(board.row(k('A'))).toMatchObject({ status: 'delayed', quote: { last: 10 } });
    board.destroy();
  });

  it('computes change figures only from a reported reference close', () => {
    expect(quoteChange(q('A', 110))).toEqual({ change: 10, percent: 10 });
    expect(quoteChange({ symbol: 'A', exchange: '', last: 5 })).toBeNull();
    expect(quoteChange({ symbol: 'A', exchange: '', last: 5, previousClose: 0 })).toBeNull();
  });
});
