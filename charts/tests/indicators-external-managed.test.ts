import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { IndicatorAttachContext, IndicatorDataChange, IndicatorDataStatus, ChartDataContext } from '../src/model/indicator-registry';
import { createTier2Indicator, type Tier2Context, type Tier2Point } from '../src/indicators/external';

const bars = (...times: number[]): Bar[] => times.map((time) => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const point = (time: number, value: number): Tier2Point => ({ time, values: { v: value } });

function managed(supported = true, live = true) {
  let source = bars(3, 4);
  let market: ChartDataContext = { symbol: 'AAA', exchange: 'X', interval: '1m' };
  let available = supported;
  let retry: (() => void) | null = null;
  const controller = new AbortController();
  const listeners = new Set<(change: IndicatorDataChange) => void>();
  const statuses: IndicatorDataStatus[] = [];
  const requests: { ctx: Tier2Context; resolve(points: readonly Tier2Point[]): void; reject(error: Error): void }[] = [];
  const subscriptions: { push(point: Tier2Point): void; stops: number }[] = [];
  const store = {};
  const descriptor = createTier2Indicator({
    id: 'managed-study', name: 'Managed', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'Value' }],
    supports: () => available,
    fetch: (ctx) => new Promise((resolve, reject) => { requests.push({ ctx, resolve, reject }); }),
    subscribe: live ? (_ctx, push) => {
      const subscription = { push, stops: 0 };
      subscriptions.push(subscription);
      return () => { subscription.stops++; };
    } : undefined,
  });
  const context: IndicatorAttachContext = {
    settings: () => ({}), bars: () => source, store, requestRecompute: () => {},
    dataContext: () => market,
    subscribeDataChanges: (listener) => { listeners.add(listener); return () => { listeners.delete(listener); }; },
    setDataStatus: (status) => { statuses.push(status); },
    setDataRetry: (callback) => { retry = callback; },
    signal: controller.signal,
  };
  const detach = descriptor.attach!(context);
  return {
    requests, subscriptions, statuses, listeners,
    context: (next: ChartDataContext) => { market = next; for (const listener of listeners) listener('context'); },
    range: (...times: number[]) => { source = bars(...times); for (const listener of listeners) listener('range'); },
    support: (next: boolean) => { available = next; },
    retry: () => retry?.(),
    values: () => descriptor.calc(source, {}, store).v,
    remove: () => { controller.abort(); if (typeof detach === 'function') detach(); },
  };
}

describe('managed external studies', () => {
  it('cancels obsolete market requests, clears old values and rejects stale completions', async () => {
    const h = managed();
    expect(h.requests[0].ctx.dataContext).toEqual({ symbol: 'AAA', exchange: 'X', interval: '1m' });
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('loading');
    h.subscriptions[0].push(point(3, 10));
    h.context({ symbol: 'BBB', exchange: 'X', interval: '1m' });
    expect(h.requests[0].ctx.signal?.aborted).toBe(true);
    expect(h.values()).toEqual([null, null]);
    h.requests[0].resolve([point(3, 99)]);
    h.subscriptions[0].push(point(4, 99));
    h.requests[1].resolve([point(3, 20)]);
    await Promise.resolve();
    expect(h.values()).toEqual([20, 20]);
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('ready');
    h.context({ symbol: 'BBB', exchange: 'Y', interval: '1m' });
    expect(h.values()).toEqual([null, null]);
    expect(h.requests).toHaveLength(3);
    h.remove();
  });

  it('extends prepended history and retains live overlaps without fetching every tick', async () => {
    const h = managed();
    h.requests[0].resolve([point(3, 30), point(4, 40)]);
    await Promise.resolve();
    h.range(1, 2, 3, 4);
    expect(h.requests).toHaveLength(2);
    expect([h.requests[1].ctx.from, h.requests[1].ctx.to]).toEqual([1, 3]);
    h.subscriptions[h.subscriptions.length - 1].push(point(4, 44));
    h.requests[1].resolve([point(1, 10), point(3, 3), point(4, 4)]);
    await Promise.resolve();
    expect(h.values()).toEqual([10, 10, 30, 44]);
    h.range(1, 2, 3, 4);
    h.range(1, 2, 3, 4, 5);
    expect(h.requests).toHaveLength(2);
    h.remove();
  });

  it('loads a prepend that arrives while the initial request is pending', async () => {
    const h = managed();
    h.range(1, 2, 3, 4);
    h.requests[0].resolve([point(3, 30)]);
    await Promise.resolve();
    expect(h.requests).toHaveLength(2);
    h.requests[1].resolve([point(1, 10)]);
    await Promise.resolve();
    expect(h.values()).toEqual([10, 10, 30, 30]);
    h.remove();
  });

  it('retains source identity on replay truncation without exposing future observations', async () => {
    const h = managed();
    h.requests[0].resolve([point(3, 30), point(4, 40)]);
    await Promise.resolve();
    h.range(3);
    h.subscriptions[0].push(point(4, 444));
    expect(h.values()).toEqual([30]);
    h.range(3, 4);
    expect(h.values()).toEqual([30, 444]);
    expect(h.requests).toHaveLength(1);
    h.remove();
  });

  it('reports unsupported without fetching and allows explicit retry after support changes', async () => {
    const h = managed(false);
    expect(h.requests).toHaveLength(0);
    expect(h.subscriptions).toHaveLength(0);
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('unsupported');
    h.support(true);
    h.retry();
    expect(h.requests).toHaveLength(1);
    h.requests[0].resolve([]);
    await Promise.resolve();
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('empty');
    h.subscriptions[0].push(point(3, 30));
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('ready');
    h.remove();
  });

  it('exposes failed retries and preserves live points over retried history', async () => {
    const h = managed();
    const failure = new Error('history unavailable');
    h.subscriptions[0].push(point(4, 44));
    h.requests[0].reject(failure);
    await Promise.resolve();
    expect(h.statuses[h.statuses.length - 1]).toEqual({ state: 'error', error: failure });
    h.retry();
    h.retry();
    expect(h.requests).toHaveLength(2);
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('loading');
    h.requests[1].reject(failure);
    await Promise.resolve();
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('error');
    h.retry();
    h.requests[2].resolve([point(3, 30), point(4, 4)]);
    await Promise.resolve();
    expect(h.values()).toEqual([30, 44]);
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('ready');
    h.remove();
  });

  it('refreshes the forming overlap when a history-only study advances', async () => {
    const h = managed(true, false);
    h.requests[0].resolve([point(3, 30), point(4, 40)]);
    await Promise.resolve();
    h.range(3, 4, 5);
    expect([h.requests[1].ctx.from, h.requests[1].ctx.to]).toEqual([4, 5]);
    h.requests[1].resolve([point(4, 44), point(5, 50)]);
    await Promise.resolve();
    expect(h.values()).toEqual([30, 44, 50]);
    h.range(3, 4, 5);
    expect(h.requests).toHaveLength(2);
    h.remove();
  });

  it('ignores former live callbacks after the provider becomes unsupported', async () => {
    const h = managed();
    h.subscriptions[0].push(point(3, 30));
    h.support(false);
    h.range(3, 4);
    h.subscriptions[0].push(point(4, 44));
    h.requests[0].resolve([point(3, 33)]);
    await Promise.resolve();
    expect(h.values()).toEqual([null, null]);
    expect(h.statuses[h.statuses.length - 1]?.state).toBe('unsupported');
    expect(h.requests[0].ctx.signal?.aborted).toBe(true);
    h.remove();
  });

  it('aborts pending work and removes context, retry and live listeners on teardown', async () => {
    const h = managed();
    h.remove();
    expect(h.requests[0].ctx.signal?.aborted).toBe(true);
    expect(h.listeners.size).toBe(0);
    expect(h.subscriptions[0].stops).toBe(1);
    const states = h.statuses.length;
    h.requests[0].resolve([point(3, 33)]);
    h.subscriptions[0].push(point(3, 33));
    h.retry();
    h.context({ symbol: 'BBB' });
    await Promise.resolve();
    expect(h.requests).toHaveLength(1);
    expect(h.statuses).toHaveLength(states);
    expect(h.values()).toEqual([null, null]);
  });
});
