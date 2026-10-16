import { afterEach, describe, expect, it, vi } from 'vitest';
import { DataLoadingController } from '../src/feed/data-controller';
import type { Bar } from '../src/model/bar';
import type { BarsRequest, BarSubscriptionOptions, DataFeed } from '../src/feed/types';

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
const bar = (time: number, close = 23802, volume = 65): Bar =>
  ({ time, open: 23800, high: Math.max(23804, close), low: Math.min(23798, close), close, volume });
const req: BarsRequest = { symbol: 'NIFTY', exchange: 'NFO', interval: '1m', from: 100, to: 300 };
const cleanups: (() => void)[] = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(fn => fn()); vi.useRealTimers(); });
function make(feed: DataFeed, options = {}) {
  const controller = new DataLoadingController(feed, { now: () => 300, ...options });
  cleanups.push(() => controller.destroy());
  return controller;
}
const settle = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };

describe('managed chart data loading', () => {
  it('distinguishes a local retention limit from provider exhaustion', async () => {
    let pages = 0;
    const controller = make({ getBars: async () => [bar(200), bar(300)],
      getBarsPage: async () => { pages++; return { bars: [bar(50), bar(100)], hasMore: true }; },
    }, { maxBars: 3 });
    await controller.load(req);
    await controller.loadMore();
    expect(controller.bars().map(value => value.time)).toEqual([100, 200, 300]);
    expect(controller.getState()).toMatchObject({ historyStatus: 'limited', hasMore: true });
    await controller.loadMore();
    expect(pages).toBe(1);
  });

  it('finishes an aborted warm-cache load without leaving a loading state', async () => {
    const pending = deferred<Bar[] | undefined>();
    const signal = new AbortController();
    const controller = make({ getCachedBars: () => pending.promise, getBars: async () => [bar(100)] });
    const work = controller.load({ ...req, signal: signal.signal });
    signal.abort();
    await work;
    expect(controller.getState().status).toBe('idle');
  });

  it('stops state delivery when a subscriber destroys the controller', async () => {
    const controller = make({ getBars: async () => [bar(100)] });
    await controller.load(req);
    controller.subscribe(() => controller.destroy());
    const late = vi.fn();
    controller.subscribe(late);
    controller.pushBar(bar(200));
    expect(late).not.toHaveBeenCalled();
  });

  it('does not replace a reentrant context load with obsolete work', async () => {
    const pending = deferred<Bar[]>();
    let calls = 0;
    const controller = make({ getBars: async request => {
      calls++;
      return request.symbol === 'BANKNIFTY' ? pending.promise : [bar(100)];
    } });
    let replacement: Promise<readonly Bar[]> | undefined;
    controller.subscribe(state => {
      if (state.request?.symbol === 'NIFTY') replacement = controller.load({ ...req, symbol: 'BANKNIFTY' });
    });
    await controller.load(req);
    const repair = controller.refresh();
    await settle();
    expect(calls).toBe(1);
    pending.resolve([bar(200, 48000)]);
    await Promise.all([replacement, repair]);
    expect(controller.getState()).toMatchObject({ status: 'ready', request: { symbol: 'BANKNIFTY' } });
  });

  it('keeps context switches usable when a provider cleanup throws', async () => {
    const controller = make({ getBars: async request => [bar(100, request.symbol === 'NIFTY' ? 23802 : 48000)],
      subscribeBars: () => () => { throw new Error('provider cleanup'); } });
    await controller.load(req);
    await controller.load({ ...req, symbol: 'BANKNIFTY' });
    expect(controller.bars()[0].close).toBe(48000);
  });

  it('rejects obsolete history and live callbacks after an instrument switch', async () => {
    const first = deferred<Bar[]>();
    const callbacks: ((bar: Bar) => void)[] = [];
    let signal: AbortSignal | undefined;
    const controller = make({ getBars: request => {
      if (request.symbol === 'NIFTY') { signal = request.signal; return first.promise; }
      return Promise.resolve([bar(200, 48000)]);
    }, subscribeBars: (_req, push) => { callbacks.push(push); return () => {}; } });
    const pending = controller.load(req);
    await controller.load({ ...req, symbol: 'BANKNIFTY' });
    first.resolve([bar(100)]);
    await pending;
    expect(signal?.aborted).toBe(true);
    expect(controller.getState().request?.symbol).toBe('BANKNIFTY');
    expect(controller.bars().map(value => value.close)).toEqual([48000]);
    await controller.load({ ...req, symbol: 'OTHER' });
    callbacks[0](bar(300, 1));
    expect(controller.bars().map(value => value.close)).toEqual([48000]);
  });

  it('paints cached closed bars then replaces them with authoritative history', async () => {
    const fresh = deferred<Bar[]>();
    let requested: BarsRequest | undefined;
    const controller = make({ getCachedBars: async () => [bar(100), bar(200)],
      getBars: request => { requested = request; return fresh.promise; } });
    const pending = controller.load(req);
    await settle();
    expect(controller.getState().reason).toBe('cache');
    expect(controller.getState().status).toBe('refreshing');
    expect(controller.bars()).toHaveLength(2);
    expect(requested?.noCache).toBe(true);
    fresh.resolve([bar(100), bar(200, 23810), bar(300)]);
    await pending;
    expect(controller.getState().status).toBe('ready');
    expect(controller.bars().map(value => value.close)).toEqual([23802, 23810, 23802]);
  });

  it('opens the chart even when reading its warm snapshot fails', async () => {
    const controller = make({ getCachedBars: async () => { throw new Error('storage denied'); }, getBars: async () => [bar(100)] });
    await controller.load(req);
    expect(controller.getState().status).toBe('ready');
    expect(controller.bars()).toHaveLength(1);
  });

  it('seeds live updates and merges reconnect snapshots without double-counting volume', async () => {
    const recovery = deferred<Bar[]>();
    let loads = 0;
    let push!: (value: Bar) => void;
    let options: BarSubscriptionOptions | undefined;
    const controller = make({ getBars: async () => ++loads === 1 ? [bar(100), bar(200)] : recovery.promise,
      subscribeBars: (_req, callback, opts) => { push = callback; options = opts; return () => {}; } });
    await controller.load(req);
    expect(options?.seedFrom).toEqual(bar(200));
    const pending = controller.refresh();
    push(bar(200, 23820, 80));
    push(bar(300, 23825, 20));
    recovery.resolve([bar(100), bar(200, 23810, 90)]);
    await pending;
    expect(controller.bars()).toHaveLength(3);
    expect(controller.bars()[1]).toMatchObject({ close: 23820, high: 23820, volume: 90 });
    expect(options?.seedFrom).toEqual(bar(300, 23825, 20));
  });

  it('keeps stale history visible after recovery fails and supports retry', async () => {
    let loads = 0;
    const controller = make({ getBars: async () => {
      if (++loads === 2) throw new Error('offline');
      return [bar(100, loads === 1 ? 23802 : 23810)];
    } });
    await controller.load(req);
    await controller.refresh();
    expect(controller.getState().status).toBe('stale');
    expect(controller.bars()[0].close).toBe(23802);
    await controller.refresh();
    expect(controller.getState().status).toBe('ready');
    expect(controller.bars()[0].close).toBe(23810);
  });

  it('suspends display delivery during replay while maintaining the live store', async () => {
    const controller = make({ getBars: async () => [bar(100), bar(200)] });
    await controller.load(req);
    controller.setPaused(true);
    const visible = controller.getState().bars;
    controller.pushBar(bar(300));
    expect(controller.getState().bars).toBe(visible);
    expect(controller.bars()).toHaveLength(3);
    await controller.refresh();
    expect(controller.getState().bars).toBe(visible);
    controller.setPaused(false);
    expect(controller.getState().reason).toBe('resume');
    expect(controller.getState().bars).toEqual(controller.bars());
  });

  it('prepends distinct older bars and respects explicit exhaustion', async () => {
    let pages = 0;
    const controller = make({ getBars: async () => [bar(200), bar(300)], getBarsPage: async request => {
      pages++;
      expect(request.before).toBe(200);
      return { bars: [bar(100), bar(200, 1)], hasMore: false };
    } });
    await controller.load(req);
    await controller.loadMore();
    expect(controller.getState().reason).toBe('prepend');
    expect(controller.bars().map(value => value.time)).toEqual([100, 200, 300]);
    expect(controller.bars()[1].close).toBe(23802);
    expect(controller.getState().hasMore).toBe(false);
    await controller.loadMore();
    expect(pages).toBe(1);
  });

  it('crosses empty date windows without claiming the provider has exhausted history', async () => {
    const seen: number[] = [];
    const controller = make({ getBars: async request => {
      if (!seen.length) { seen.push(request.to!); return [bar(200)]; }
      seen.push(request.to!);
      return seen.length < 4 ? [] : [bar(-250)];
    } }, { pageWindowSec: 200, maxEmptyPages: 4 });
    await controller.load(req);
    await controller.loadMore();
    expect(seen).toHaveLength(4);
    expect(controller.bars().map(value => value.time)).toEqual([-250, 200]);
    expect(controller.getState().hasMore).toBeNull();
  });

  it('bounds empty-page scanning and leaves later searches possible', async () => {
    let calls = 0;
    const controller = make({ getBars: async () => ++calls === 1 ? [bar(200)] : [] }, { maxEmptyPages: 2 });
    await controller.load(req);
    await controller.loadMore();
    expect(calls).toBe(3);
    expect(controller.getState().hasMore).toBeNull();
    expect(controller.getState().historyStatus).toBe('idle');
    await controller.loadMore();
    expect(calls).toBe(5);
  });

  it('does not deliver a stale older page into the next instrument', async () => {
    const older = deferred<{ bars: Bar[] }>();
    const controller = make({ getBars: async request => [bar(200, request.symbol === 'NIFTY' ? 23802 : 48000)],
      getBarsPage: () => older.promise });
    await controller.load(req);
    const pending = controller.loadMore();
    await controller.load({ ...req, symbol: 'BANKNIFTY' });
    older.resolve({ bars: [bar(100)] });
    await pending;
    expect(controller.bars().map(value => value.close)).toEqual([48000]);
  });

  it('distinguishes empty history, initial failure and pagination failure', async () => {
    let fail = false;
    const controller = make({ getBars: async () => {
      if (fail) throw new Error('unavailable');
      return [];
    } });
    await controller.load(req);
    expect(controller.getState().status).toBe('empty');
    fail = true;
    await controller.load(req);
    expect(controller.getState().status).toBe('error');
    expect(controller.getState().error?.message).toBe('unavailable');
  });

  it('tears down subscriptions and pending requests without a late state event', async () => {
    let off = 0;
    const pending = deferred<Bar[]>();
    let loads = 0;
    const controller = make({ getBars: async () => ++loads === 1 ? [bar(100)] : pending.promise,
      subscribeBars: () => () => { off++; } });
    await controller.load(req);
    let events = 0;
    controller.subscribe(() => { events++; });
    const refresh = controller.refresh();
    controller.destroy();
    const before = events;
    pending.resolve([bar(200)]);
    await refresh;
    expect(events).toBe(before);
    expect(off).toBe(1);
  });

  it('pauses polling when hidden and refreshes on return', async () => {
    vi.useFakeTimers();
    let calls = 0;
    const controller = make({ getBars: async () => { calls++; return [bar(100)]; } }, { pollIntervalMs: 100 });
    await controller.load(req);
    controller.setVisible(false);
    await vi.advanceTimersByTimeAsync(500);
    expect(calls).toBe(1);
    controller.setVisible(true);
    await settle();
    expect(calls).toBe(2);
    controller.destroy();
    expect(vi.getTimerCount()).toBe(0);
  });
});
