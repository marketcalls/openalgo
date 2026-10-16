import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { createTier2Indicator, type Tier2Context, type Tier2Point } from '../src/indicators/external';
import { registerIndicator, type IndicatorSettings } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const data = [1, 2, 3, 4].map((time) => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const point = (time: number, v: number): Tier2Point => ({ time, values: { v } });

function deferred() {
  let resolve!: (points: readonly Tier2Point[]) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<readonly Tier2Point[]>((accept, fail) => {
    resolve = accept;
    reject = fail;
  });
  return { promise, resolve, reject };
}

function lifecycle(refetchOn: readonly string[] = ['symbol']) {
  const requests: (ReturnType<typeof deferred> & { context: Tier2Context })[] = [];
  const subscriptions: { context: Tier2Context; push: (point: Tier2Point) => void; stops: number }[] = [];
  const recomputes: number[] = [];
  let settings: IndicatorSettings = { symbol: 'AAA' };
  const store: Record<string, unknown> = {};
  const descriptor = createTier2Indicator({
    id: 'external-lifecycle', name: 'External', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'Value' }],
    refetchOn,
    fetch: (context) => {
      const request = { ...deferred(), context };
      requests.push(request);
      return request.promise;
    },
    subscribe: (context, push) => {
      const subscription = { context, push, stops: 0 };
      subscriptions.push(subscription);
      return () => { subscription.stops += 1; };
    },
  });
  return {
    descriptor, requests, subscriptions, recomputes,
    attach(patch: IndicatorSettings = {}) {
      settings = { ...settings, ...patch };
      const attachment = recomputes.length;
      recomputes.push(0);
      const detach = descriptor.attach!({
        settings: () => settings, bars: () => data, store,
        requestRecompute: () => { recomputes[attachment] += 1; },
      });
      return () => { if (typeof detach === 'function') detach(); };
    },
    values: () => descriptor.calc(data, settings, store).v,
  };
}

describe('Tier-2 request and attachment lifecycle', () => {
  it('clears loaded values immediately when a different symbol starts loading', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    h.requests[0].resolve([point(1, 111)]);
    await Promise.resolve();
    expect(h.values()).toEqual([111, 111, 111, 111]);
    detachA();
    const detachB = h.attach({ symbol: 'BBB' });
    expect(h.values()).toEqual([null, null, null, null]);
    expect(h.recomputes).toEqual([1, 1]);
    h.requests[1].reject(new Error('BBB unavailable'));
    await Promise.resolve();
    expect(h.values()).toEqual([null, null, null, null]);
    detachB();
  });

  it('clears previous-symbol live points before either history request settles', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    h.subscriptions[0].push(point(1, 111));
    detachA();
    const detachB = h.attach({ symbol: 'BBB' });
    expect(h.values()).toEqual([null, null, null, null]);
    expect(h.recomputes).toEqual([1, 1]);
    h.subscriptions[1].push(point(2, 222));
    h.requests[0].resolve([point(1, 112)]);
    h.requests[1].reject(new Error('BBB history unavailable'));
    await Promise.resolve();
    expect(h.values()).toEqual([null, 222, 222, 222]);
    detachB();
  });

  it('starts the new symbol request while old history is pending', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    detachA();
    const detachB = h.attach({ symbol: 'BBB' });
    expect(h.requests.map((r) => r.context.settings.symbol)).toEqual(['AAA', 'BBB']);

    h.requests[0].resolve([point(1, 111)]);
    h.subscriptions[0].push(point(2, 112));
    await Promise.resolve();
    expect(h.values()).toEqual([null, null, null, null]);
    expect(h.recomputes).toEqual([0, 0]);

    h.requests[1].resolve([point(1, 222)]);
    await Promise.resolve();
    expect(h.values()).toEqual([222, 222, 222, 222]);
    expect(h.recomputes).toEqual([0, 1]);
    detachB();
  });

  it.each(['success', 'error'] as const)('ignores late %s after AAA to BBB to AAA', async (outcome) => {
    const h = lifecycle();
    h.attach()();
    h.attach({ symbol: 'BBB' })();
    let detach = h.attach({ symbol: 'AAA' });
    expect(h.requests.map((r) => r.context.settings.symbol)).toEqual(['AAA', 'BBB', 'AAA']);
    h.requests[2].resolve([point(1, 333)]);
    await Promise.resolve();

    if (outcome === 'success') h.requests[0].resolve([point(1, 111)]);
    else h.requests[0].reject(new Error('stale request failed'));
    h.requests[1].reject(new Error('other symbol failed'));
    h.subscriptions[0].push(point(1, 112));
    h.subscriptions[1].push(point(1, 222));
    await Promise.resolve();
    expect(h.values()).toEqual([333, 333, 333, 333]);
    expect(h.recomputes).toEqual([0, 0, 1]);

    detach();
    detach = h.attach({ color: '#abcdef' });
    expect(h.requests).toHaveLength(3);
    expect(h.values()).toEqual([333, 333, 333, 333]);
    detach();
  });

  it('reuses pending history across style changes and notifies the current attachment', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    h.subscriptions[0].push(point(2, 222));
    detachA();
    const detachB = h.attach({ color: '#abcdef' });
    expect(h.requests).toHaveLength(1);
    h.subscriptions[0].push(point(3, 999));
    h.subscriptions[1].push(point(4, 444));
    h.requests[0].resolve([point(1, 111)]);
    await Promise.resolve();
    expect(h.values()).toEqual([111, 222, 222, 444]);
    expect(h.recomputes).toEqual([1, 2]);
    detachB();
  });

  it.each(['success', 'error'] as const)('ignores live callbacks and history %s after detach', async (outcome) => {
    const h = lifecycle();
    const detach = h.attach();
    h.subscriptions[0].push(point(2, 222));
    detach();
    detach();
    h.subscriptions[0].push(point(3, 333));
    if (outcome === 'success') h.requests[0].resolve([point(1, 111)]);
    else h.requests[0].reject(new Error('removed'));
    await Promise.resolve();
    expect(h.values()).toEqual([null, 222, 222, 222]);
    expect(h.recomputes).toEqual([1]);
    expect(h.subscriptions[0].stops).toBe(1);
  });

  it('keeps an old cleanup from stopping the current subscription', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    const detachB = h.attach({ symbol: 'BBB' });
    detachA();
    expect(h.subscriptions.map((s) => s.stops)).toEqual([1, 0]);
    h.subscriptions[1].push(point(2, 222));
    h.requests[1].resolve([point(1, 111)]);
    await Promise.resolve();
    expect(h.values()).toEqual([111, 222, 222, 222]);
    detachB();
    expect(h.subscriptions.map((s) => s.stops)).toEqual([1, 1]);
  });
});

describe('Tier-2 history and live reconciliation', () => {
  it('preserves a live point delivered before history resolves', async () => {
    const h = lifecycle();
    const detach = h.attach();
    h.subscriptions[0].push(point(2, 222));
    h.requests[0].resolve([point(1, 111)]);
    await Promise.resolve();
    expect(h.values()).toEqual([111, 222, 222, 222]);
    detach();
  });

  it('gives live arrivals precedence over duplicate and out-of-order history', async () => {
    const h = lifecycle();
    const detach = h.attach();
    h.subscriptions[0].push(point(4, 400));
    h.subscriptions[0].push(point(2, 200));
    h.subscriptions[0].push(point(2, 222));
    h.requests[0].resolve([
      point(3, 300), point(2, 20), point(1, 100), point(2, 21), point(3, 333),
    ]);
    await Promise.resolve();
    expect(h.values()).toEqual([100, 222, 333, 400]);
    h.subscriptions[0].push(point(3, 334));
    h.subscriptions[0].push(point(1, 101));
    expect(h.values()).toEqual([101, 222, 334, 400]);
    detach();
  });

  it('preserves live points when history is empty', async () => {
    const h = lifecycle();
    const detach = h.attach();
    h.subscriptions[0].push(point(2, 222));
    h.requests[0].resolve([]);
    await Promise.resolve();
    expect(h.values()).toEqual([null, 222, 222, 222]);
    detach();
  });

  it('treats empty history as loaded across style-only settings changes', async () => {
    const h = lifecycle();
    h.attach();
    h.requests[0].resolve([]);
    await Promise.resolve();
    const detach = h.attach({ color: '#abcdef' });
    expect(h.requests).toHaveLength(1);
    expect(h.values()).toEqual([null, null, null, null]);
    h.subscriptions[1].push(point(2, 222));
    expect(h.values()).toEqual([null, 222, 222, 222]);
    detach();
  });

  it('retries failed history even with no refetch keys and existing live data', async () => {
    const h = lifecycle([]);
    const detachA = h.attach();
    h.subscriptions[0].push(point(2, 222));
    h.requests[0].reject(new Error('network'));
    await Promise.resolve();
    expect(h.values()).toEqual([null, 222, 222, 222]);
    detachA();
    const detachB = h.attach({ color: '#abcdef' });
    expect(h.requests).toHaveLength(2);
    h.subscriptions[1].push(point(2, 223));
    h.requests[1].resolve([point(1, 111), point(2, 200)]);
    await Promise.resolve();
    expect(h.values()).toEqual([111, 223, 223, 223]);
    detachB();
  });

  it('uses only current-symbol history and live points after a settings change', async () => {
    const h = lifecycle();
    const detachA = h.attach();
    h.requests[0].resolve([point(1, 111), point(3, 999)]);
    await Promise.resolve();
    detachA();
    const detachB = h.attach({ symbol: 'BBB' });
    h.subscriptions[1].push(point(4, 444));
    h.requests[1].resolve([point(2, 222)]);
    await Promise.resolve();
    expect(h.values()).toEqual([null, 222, 222, 444]);
    detachB();
  });
});

describe('Tier-2 chart lifecycle integration', () => {
  it('publishes per-instance status and retries without changing settings', async () => {
    const h = lifecycle();
    registerIndicator(h.descriptor);
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, raf: { schedule: () => 0 }, pixelRatio: () => 1, shortcuts: false,
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(data);
    const indicator = chart.addIndicator(h.descriptor.id, { symbol: 'AAA' });
    const states: string[] = [];
    const events: unknown[] = [];
    chart.on('indicator:data-status', (event) => { events.push(event); });
    const unsubscribe = indicator.subscribeDataStatus((status) => { states.push(status.state); });
    expect(indicator.dataStatus()).toEqual({ state: 'loading' });
    const failure = new Error('unavailable');
    h.requests[0].reject(failure);
    await Promise.resolve();
    expect(indicator.dataStatus()).toEqual({ state: 'error', error: failure });
    indicator.retryData();
    h.requests[1].resolve([]);
    await Promise.resolve();
    expect(states).toEqual(['loading', 'error', 'loading', 'empty']);
    expect(events).toHaveLength(3);
    unsubscribe();
    indicator.retryData();
    expect(h.requests).toHaveLength(3);
    indicator.setSettings({ 'v:color': '#123456' });
    expect(h.requests).toHaveLength(3);
    expect(h.requests[2].context.signal?.aborted).toBe(false);
    chart.removeIndicator(indicator.id);
    expect(h.requests[2].context.signal?.aborted).toBe(true);
    indicator.retryData();
    h.requests[2].resolve([point(1, 999)]);
    await Promise.resolve();
    expect(states).toEqual(['loading', 'error', 'loading', 'empty']);
    expect(h.requests).toHaveLength(3);
    chart.destroy();
  });

  it('switches pending settings through IndicatorApi and stops updates on removal', async () => {
    const h = lifecycle();
    registerIndicator(h.descriptor);
    const doc = fakeDocument();
    const chart = new Chart(doc.createElement('div'), {
      document: doc, raf: { schedule: () => 0 }, pixelRatio: () => 1, shortcuts: false,
    });
    chart.applySize(800, 600);
    chart.addSeries('candlestick').setData(data);
    const indicator = chart.addIndicator(h.descriptor.id, { symbol: 'AAA' });
    indicator.setSettings({ symbol: 'BBB' });
    expect(h.requests.map((r) => r.context.settings.symbol)).toEqual(['AAA', 'BBB']);
    h.requests[0].resolve([point(1, 111)]);
    h.subscriptions[1].push(point(2, 222));
    h.requests[1].resolve([point(1, 200)]);
    await Promise.resolve();
    expect(indicator.values().v).toEqual([200, 222, 222, 222]);

    indicator.setSettings({ symbol: 'CCC' });
    expect(indicator.values().v).toEqual([null, null, null, null]);
    expect(chart.removeIndicator(indicator.id)).toBe(true);
    h.requests[2].resolve([point(1, 333)]);
    h.subscriptions[2].push(point(2, 334));
    await Promise.resolve();
    expect(chart.indicators()).toHaveLength(0);
    expect(indicator.values().v).toEqual([null, null, null, null]);
    expect(h.subscriptions.map((s) => s.stops)).toEqual([1, 1, 1]);
    chart.destroy();
  });
});
