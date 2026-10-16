import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { OpenAlgoLiveDataFeed } from '../src/feed/openalgo-live';
import { FakeDataFeed } from '../src/feed/fake-feed';
import { withBarCache } from '../src/feed/cache';
import type { SocketLike } from '../src/feed/openalgo-ws';
import type { Bar } from '../src/model/bar';
import { createWidget, type Widget } from '../src/widget/widget';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
const T = 1_700_000_040;
const initial: Bar = { time: T, open: 10, high: 12, low: 9, close: 11, volume: 100 };
const cleanup: (() => void)[] = [];
afterEach(() => { for (const stop of cleanup.splice(0).reverse()) stop(); vi.useRealTimers(); });
const flush = async (): Promise<void> => { for (let i = 0; i < 20; i++) await Promise.resolve(); };

function pendingHistory() {
  let resolve!: (bars: Bar[]) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<Bar[]>((accept, fail) => { resolve = accept; reject = fail; });
  return { promise, resolve, reject };
}

function make(history: () => Promise<Bar[]>, cached = false): { widget: Widget; sockets: SocketLike[]; now: (n: number) => void } {
  const sockets: SocketLike[] = [];
  let now = T + 30;
  const feed = new OpenAlgoLiveDataFeed({
    baseUrl: 'https://feed.test', apiKey: 'fixture', wsUrl: 'ws://feed.test',
    heartbeat: { timeoutMs: 0 }, reconnect: { baseDelayMs: 1, jitter: false },
    fetchImpl: (async () => ({ ok: true, json: async () => ({ status: 'success', data: await history() }) }) as Response) as typeof fetch,
    socketFactory: () => {
      const socket: SocketLike = { readyState: 1, send: () => {}, close: () => {}, onopen: null, onclose: null, onmessage: null };
      sockets.push(socket);
      return socket;
    },
  });
  cleanup.push(() => feed.close());
  const doc = fakeWidgetDocument();
  const widget = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    feed: cached ? withBarCache(feed, { now: () => (T + 3600) * 1000 }) : feed,
    symbol: 'X', exchange: 'NSE', interval: '1m', lookbackBars: 30, now: () => now * 1000,
    document: doc as unknown as Document, pixelRatio: () => 1,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
  });
  widget.chart.applySize(800, 600);
  cleanup.push(() => widget.destroy());
  sockets[0].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
  return { widget, sockets, now: n => { now = n; } };
}

function tick(socket: SocketLike, time: number, price: number, quantity = 2): void {
  socket.onmessage?.({ data: JSON.stringify({ type: 'market_data', mode: 1, topic: 'X.NSE', data: {
    ltp: price, ltq: quantity, timestamp: time,
  } }) });
}

describe('widget with the OpenAlgo live feed', () => {
  it('retains live extrema and close during repair without adding overlapping volumes', async () => {
    vi.useFakeTimers();
    const pending = pendingHistory();
    let calls = 0;
    const { widget, sockets } = make(async () => ++calls === 1 ? [initial] : pending.promise);
    await flush();
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    tick(sockets[1], T + 35, 40);
    tick(sockets[1], T + 40, 15, 3);
    expect(widget.series.getData()).toEqual([initial]);
    pending.resolve([{ ...initial, open: 9.5, high: 13, low: 8, close: 12, volume: 140 }]);
    await flush();
    expect(widget.series.getData()).toEqual([
      { time: T, open: 9.5, high: 40, low: 8, close: 15, volume: 140 },
    ]);
    tick(sockets[1], T + 45, 16, 4);
    expect(widget.series.getData()[0].volume).toBe(144);
    expect(widget.series.getData()[0].high).toBe(40);
  });

  it('starts a newer repair when another reconnect occurs during pending history', async () => {
    vi.useFakeTimers();
    const firstRepair = pendingHistory();
    const secondRepair = pendingHistory();
    let calls = 0;
    const { widget, sockets, now } = make(async () => {
      calls += 1;
      return calls === 1 ? [initial] : calls === 2 ? firstRepair.promise : secondRepair.promise;
    });
    await flush();
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    now(T + 150);
    sockets[1].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[2].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    expect(calls).toBe(3);
    const repaired = [initial, { ...initial, time: T + 60 }, { ...initial, time: T + 120 }];
    secondRepair.resolve(repaired);
    await flush();
    firstRepair.resolve([{ ...initial, close: 999 }]);
    await flush();
    expect(widget.series.getData()).toEqual(repaired);
    tick(sockets[2], T + 155, 14);
    expect(widget.series.getData().map(bar => bar.time)).toEqual([T, T + 60, T + 120]);
    expect(widget.series.getData()[2].close).toBe(14);
  });

  it('keeps display paused after failed repair and reconciles buffered ticks on retry', async () => {
    vi.useFakeTimers();
    const pending = pendingHistory();
    let calls = 0;
    const { widget, sockets } = make(async () => {
      calls += 1;
      return calls === 1 ? [initial] : calls === 2 ? pending.promise : [{ ...initial, volume: 140 }];
    });
    await flush();
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    tick(sockets[1], T + 35, 40);
    pending.reject(new Error('history unavailable'));
    await flush();
    tick(sockets[1], T + 40, 15);
    expect(widget.series.getData()).toEqual([initial]);
    await widget.reload();
    expect(widget.series.getData()).toEqual([{ ...initial, high: 40, close: 15, volume: 140 }]);
  });

  it('discards a pending repair and buffered ticks when the symbol changes', async () => {
    vi.useFakeTimers();
    const pending = pendingHistory();
    let calls = 0;
    const other = { time: T, open: 20, high: 22, low: 19, close: 21, volume: 200 };
    const { widget, sockets } = make(async () => {
      calls += 1;
      return calls === 1 ? [initial] : calls === 2 ? pending.promise : [other];
    });
    await flush();
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    tick(sockets[1], T + 35, 999);
    widget.setSymbol('Y');
    await flush();
    pending.resolve([{ ...initial, high: 999, close: 999 }]);
    await flush();
    tick(sockets[1], T + 40, 1000);
    expect(widget.series.getData()).toEqual([other]);
  });

  it('continues a supplied seed in the synthetic feed instead of updating old history', () => {
    let advance = (): void => {};
    const feed = new FakeDataFeed(60, callback => { advance = callback; return () => {}; });
    const delivered: Bar[] = [];
    feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', from: T - 1800 },
      bar => delivered.push(bar), { seedFrom: initial });
    advance();
    expect(delivered[0].time).toBe(T + 60);
    expect(delivered[0].open).toBe(11);
  });

  it('continues historical OHLC and volume on the first same-bucket tick', async () => {
    const { widget, sockets } = make(async () => [initial]);
    await flush();
    tick(sockets[0], T + 30, 11.5);
    expect(widget.series.getData()).toEqual([{ ...initial, close: 11.5, volume: 102 }]);
  });

  it('repairs missing and corrected bars after reauthentication and preserves the visible range', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const repaired = [
      { ...initial, high: 13, close: 12, volume: 140 },
      { time: T + 60, open: 12, high: 14, low: 11, close: 13, volume: 50 },
      { time: T + 120, open: 13, high: 15, low: 12, close: 14, volume: 30 },
    ];
    const { widget, sockets, now } = make(async () => ++calls === 1 ? [initial] : repaired);
    await flush();
    widget.chart.setVisibleLogicalRange({ from: -3, to: 4 });
    const viewport = widget.chart.timeScale.visibleRange();
    now(T + 150);
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    expect(widget.series.getData()).toEqual(repaired);
    expect(widget.chart.timeScale.visibleRange()).toEqual(viewport);
    tick(sockets[1], T + 155, 14.5, 3);
    expect(widget.series.getData()[2]).toEqual({ ...repaired[2], close: 14.5, volume: 33 });
  });

  it('keeps history visible and reports stale data when reconnect recovery fails', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const { widget, sockets } = make(async () => {
      if (++calls > 1) throw new Error('history offline');
      return [initial];
    });
    await flush();
    const status: string[] = [];
    widget.on('status', event => status.push(event.text));
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    expect(widget.series.getData()).toEqual([initial]);
    expect(status.some(text => /stale/i.test(text))).toBe(true);
  });

  it('refreshes authoritative history on reload and recovery even with a warm closed cache', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const corrected = { ...initial, high: 13, close: 12, volume: 140 };
    const { widget, sockets } = make(async () => ++calls === 1 ? [initial] : [corrected], true);
    await flush();
    await widget.reload();
    expect(calls).toBe(2);
    expect(widget.series.getData()).toEqual([corrected]);
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    expect(calls).toBe(3);
    expect(widget.series.getData()).toEqual([corrected]);
  });

  it('retries authoritative history after cached-feed recovery fails', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const corrected = { ...initial, close: 12, volume: 140 };
    const { widget, sockets } = make(async () => {
      calls++;
      if (calls === 2) throw new Error('temporary outage');
      return calls === 1 ? [initial] : [corrected];
    }, true);
    await flush();
    sockets[0].onclose?.();
    await vi.advanceTimersByTimeAsync(1);
    sockets[1].onmessage?.({ data: JSON.stringify({ type: 'auth', status: 'success' }) });
    await flush();
    expect(calls).toBe(2);
    expect(widget.series.getData()).toEqual([initial]);
    await widget.reload();
    expect(calls).toBe(3);
    expect(widget.series.getData()).toEqual([corrected]);
  });
});
