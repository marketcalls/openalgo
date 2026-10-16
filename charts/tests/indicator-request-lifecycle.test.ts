import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorAttachContext, type IndicatorBarsProvider, type IndicatorBarsProviderAccess, type IndicatorBarsRequest, type IndicatorSnapshotRequest } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { IndicatorInstance, type IndicatorHost } from '../src/model/indicator-instance';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
let sequence = 0;
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); });
const bars: Bar[] = [{ time: 60, open: 10, high: 12, low: 9, close: 11 }];
const request: IndicatorBarsRequest = { symbol: 'SECOND', exchange: 'X', interval: '1m', from: 0, to: 120 };

function pendingProvider() {
  const requests: { request: IndicatorBarsRequest; resolve(value: readonly Bar[]): void; reject(error: unknown): void }[] = [];
  const provider: IndicatorBarsProvider = request => new Promise((resolve, reject) => requests.push({ request, resolve, reject }));
  return { requests, provider };
}

function mount(provider: IndicatorBarsProvider | IndicatorBarsProviderAccess) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, barsProvider: provider, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'FIRST', exchange: 'X', interval: '1m' });
  chart.addSeries('candlestick').setData(bars);
  let context!: IndicatorAttachContext;
  const id = `request-lifecycle-${sequence++}`;
  registerIndicator({ id, name: 'Request lifecycle', placement: 'pane', inputs: [],
    plots: [{ key: 'value', title: 'Value', type: 'line' }],
    calc: data => ({ value: data.map(bar => bar.close) }),
    attach: attached => { context = attached; },
  });
  const indicator = chart.addIndicator(id);
  return { chart, indicator, context: () => context, request: (signal?: AbortSignal) => context.requestBars!({ ...request, signal }) };
}

describe('native indicator request cancellation', () => {
  it('combines caller cancellation with removal and fences ignored cancellation', async () => {
    const p = pendingProvider(), h = mount(p.provider), caller = new AbortController();
    const outcome = h.request(caller.signal).catch(error => error);
    expect(p.requests).toHaveLength(1);
    h.indicator.remove();
    expect(caller.signal.aborted).toBe(false);
    expect(p.requests[0].request.signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
    p.requests[0].resolve(bars);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
  });

  it('preserves the caller reason and leaves other requests running', async () => {
    const p = pendingProvider(), h = mount(p.provider), caller = new AbortController();
    const reason = new Error('caller cancelled');
    const cancelled = h.request(caller.signal).catch(error => error);
    const retained = h.request();
    caller.abort(reason);
    expect(await cancelled).toBe(reason);
    expect(p.requests[1].request.signal?.aborted).toBe(false);
    p.requests[1].resolve(bars);
    expect(await retained).toEqual(bars);
  });

  it('does not call the provider for pre-aborted callers or removed instances', async () => {
    const provider = vi.fn(async () => bars), h = mount(provider), caller = new AbortController();
    caller.abort();
    await expect(h.request(caller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    h.indicator.remove();
    await expect(h.request()).rejects.toMatchObject({ name: 'AbortError' });
    expect(provider).not.toHaveBeenCalled();
  });

  it.each(['replacement', 'removal'] as const)('cancels the old provider on %s and serves only the current provider', async mode => {
    const p = pendingProvider(), h = mount(p.provider), replacement = vi.fn(async () => bars);
    const outcome = h.request().catch(error => error);
    h.chart.setBarsProvider(mode === 'replacement' ? replacement : null);
    expect(p.requests[0].request.signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
    p.requests[0].resolve([{ ...bars[0], close: 999 }]);
    if (mode === 'replacement') {
      expect(await h.request()).toEqual(bars);
      expect(replacement).toHaveBeenCalledTimes(1);
    } else await expect(h.request()).rejects.toThrow(/no bars provider/);
  });

  it('does not cancel when the same provider is set again', async () => {
    const p = pendingProvider(), h = mount(p.provider), outcome = h.request();
    h.chart.setBarsProvider(p.provider);
    expect(p.requests[0].request.signal?.aborted).toBe(false);
    p.requests[0].resolve(bars);
    expect(await outcome).toEqual(bars);
  });

  it.each([
    { symbol: 'NEXT', exchange: 'X', interval: '1m' },
    { symbol: 'FIRST', exchange: 'Y', interval: '1m' },
    { symbol: 'FIRST', exchange: 'X', interval: '5m' },
    undefined,
  ])('cancels requests belonging to a replaced chart context: %j', async next => {
    const p = pendingProvider(), h = mount(p.provider), outcome = h.request().catch(error => error);
    h.chart.setDataContext(next);
    expect(p.requests[0].request.signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
    const current = h.request();
    p.requests[1].resolve(bars);
    expect(await current).toEqual(bars);
  });

  it('retains requests across capability-only context changes', async () => {
    const p = pendingProvider(), h = mount(p.provider), outcome = h.request();
    h.chart.setDataContext({ symbol: 'FIRST', exchange: 'X', interval: '1m', hasOpenInterest: true });
    expect(p.requests[0].request.signal?.aborted).toBe(false);
    p.requests[0].resolve(bars);
    expect(await outcome).toEqual(bars);
  });

  it('aborts pending requests when the chart is destroyed', async () => {
    const p = pendingProvider(), h = mount(p.provider), caller = new AbortController();
    const outcome = h.request(caller.signal).catch(error => error);
    h.chart.destroy();
    expect(p.requests[0].request.signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
  });

  it('rejects if the provider replaces itself before returning', async () => {
    const h = mount(() => { chart.setBarsProvider(async () => bars); return Promise.resolve([{ ...bars[0], close: 999 }]); });
    const chart = h.chart;
    await expect(h.request()).rejects.toMatchObject({ name: 'AbortError' });
    expect(await h.request()).toEqual(bars);
  });

  it('turns synchronous provider throws into rejected requests', async () => {
    const failure = new Error('provider failed'), h = mount(() => { throw failure; });
    let result!: Promise<readonly Bar[]>;
    expect(() => { result = h.request(); }).not.toThrow();
    await expect(result).rejects.toBe(failure);
  });

  it('cannot restart a provider from its cancellation callback during chart teardown', async () => {
    const replacement = vi.fn(async () => bars);
    let restarted!: Promise<readonly Bar[]>;
    const h: ReturnType<typeof mount> = mount(request => {
      request.signal!.addEventListener('abort', () => {
        h.chart.setBarsProvider(replacement);
        restarted = h.request();
        void restarted.catch(() => {});
      }, { once: true });
      return new Promise(() => {});
    });
    const pending = h.request().catch(error => error);
    h.chart.destroy();
    expect(await pending).toMatchObject({ name: 'AbortError' });
    await expect(restarted).rejects.toMatchObject({ name: 'AbortError' });
    expect(replacement).not.toHaveBeenCalled();
  });
});

describe('native requested snapshot access', () => {
  const snapshot = { bars, availableAt: [120], confirmed: [true] };

  it('preserves provider method receivers and raw requests', async () => {
    const provider = {
      marker: snapshot,
      requestBars: async function () { return this.marker.bars; },
      requestSnapshot: async function () { return this.marker; },
    };
    const h = mount(provider);
    expect(h.chart.hasSnapshotProvider()).toBe(true);
    expect(h.context().requestState!().supportsSnapshots).toBe(true);
    expect(await h.request()).toEqual(bars);
    expect(await h.context().requestSnapshot!(request)).toEqual(snapshot);
  });

  it('reports unsupported snapshot capability without fabricating metadata', async () => {
    const provider = vi.fn(async () => bars), h = mount(provider);
    expect(h.chart.hasSnapshotProvider()).toBe(false);
    expect(h.context().requestState!().supportsSnapshots).toBe(false);
    await expect(h.context().requestSnapshot!(request)).rejects.toThrow(/unsupported/);
    expect(provider).not.toHaveBeenCalled();
  });

  it('cancels pending snapshot requests on provider replacement', async () => {
    let received!: IndicatorSnapshotRequest;
    const h = mount({ requestBars: async () => bars,
      requestSnapshot: next => { received = next; return new Promise(() => {}); } });
    const outcome = h.context().requestSnapshot!(request).catch(error => error);
    h.chart.setBarsProvider(async () => bars);
    expect(received.signal?.aborted).toBe(true);
    expect(await outcome).toMatchObject({ name: 'AbortError' });
  });

  it('publishes request revisions without inventing source updates', () => {
    const h = mount(async () => bars), context = h.context(), notify = vi.fn();
    const stop = context.subscribeRequestChanges!(notify);
    const initial = context.requestState!();
    h.chart.invalidateRequestedData();
    expect(context.requestState!()).toMatchObject({ source: initial.source, dataRevision: initial.dataRevision + 1 });
    expect(notify).toHaveBeenCalledTimes(1);
    h.chart.primarySeries()!.update({ ...bars[0], close: 12 });
    expect(context.requestState!().source?.revision).toBe(initial.source!.revision + 1);
    expect(notify).toHaveBeenCalledTimes(2);
    h.chart.setBarsProvider(async () => bars);
    expect(context.requestState!().providerRevision).toBe(initial.providerRevision + 1);
    expect(notify).toHaveBeenCalledTimes(3);
    stop();
    h.chart.invalidateRequestedData();
    expect(notify).toHaveBeenCalledTimes(3);
  });

  it('exposes timed replay availability and notifies movement within an unchanged primary observation', () => {
    const h = mount(async () => bars), context = h.context();
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 130 });
    const source = context.requestState!().source;
    expect(context.requestState!().replay).toEqual({ time: 60, asOf: 130, forming: false });
    const notify = vi.fn(), stop = context.subscribeRequestChanges!(notify);
    replay.seekTime(140);
    expect(context.requestState!().source).toBe(source);
    expect(context.requestState!().replay?.asOf).toBe(140);
    expect(notify).toHaveBeenCalledTimes(1);
    replay.seekTime(140);
    expect(notify).toHaveBeenCalledTimes(1);
    replay.seekTime(135);
    expect(context.requestState!().replay?.asOf).toBe(135);
    expect(notify).toHaveBeenCalledTimes(2);
    stop();
    replay.stop();
    expect(context.requestState!().replay).toBeUndefined();
  });

  it('caps snapshot requests at the replay availability clock and retains stricter cutoffs', async () => {
    const requests: IndicatorSnapshotRequest[] = [];
    const h = mount({ requestBars: async () => bars, requestSnapshot: async next => { requests.push(next); return snapshot; } });
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 130 });
    await h.context().requestSnapshot!(request);
    await h.context().requestSnapshot!({ ...request, asOf: 999 });
    await h.context().requestSnapshot!({ ...request, asOf: 100 });
    expect(requests.map(item => item.asOf)).toEqual([130, 130, 100]);
    replay.stop();
    await h.context().requestSnapshot!(request);
    expect(requests[3].asOf).toBeUndefined();
  });

  it('refuses snapshots during replay without an explicit availability clock', async () => {
    const provider = vi.fn(async () => snapshot), h = mount({ requestBars: async () => bars, requestSnapshot: provider });
    const replay = new ReplayController(h.chart, { startIndex: 0 });
    await expect(h.context().requestSnapshot!(request)).rejects.toThrow(/availability clock/);
    expect(provider).not.toHaveBeenCalled();
    replay.stop();
  });

  it('rejects invalid snapshot cutoffs before contacting the provider', async () => {
    const provider = vi.fn(async () => snapshot), h = mount({ requestBars: async () => bars, requestSnapshot: provider });
    for (const asOf of [NaN, Infinity, -Infinity]) await expect(h.context().requestSnapshot!({ ...request, asOf })).rejects.toThrow(/finite/);
    expect(provider).not.toHaveBeenCalled();
  });

  it('preserves custom host method receivers for request hooks', async () => {
    const h = mount(async () => bars);
    const base = (h.chart as unknown as { _indicatorHost(): IndicatorHost })._indicatorHost();
    const requestState = { providerRevision: 1, dataRevision: 2, supportsSnapshots: true };
    const host = { ...base, snapshot, current: requestState, listeners: new Set<() => void>(),
      requestBars() { return Promise.resolve(this.snapshot.bars); },
      requestSnapshot() { return Promise.resolve(this.snapshot); },
      requestState() { return this.current; },
      subscribeRequestChanges(listener: () => void) { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; },
    };
    let context!: IndicatorAttachContext;
    const indicator = new IndicatorInstance(host, { id: 'receiver-probe', name: 'Receiver', placement: 'pane', inputs: [], plots: [],
      calc: () => ({}), attach: ctx => { context = ctx; } });
    try {
      expect(await context.requestBars!(request)).toEqual(bars);
      expect(await context.requestSnapshot!(request)).toEqual(snapshot);
      expect(context.requestState!()).toEqual(requestState);
      const stop = context.subscribeRequestChanges!(() => {});
      expect(host.listeners.size).toBe(1);
      stop();
      expect(host.listeners.size).toBe(0);
    } finally { indicator.remove(); }
  });

  it('does not resume an obsolete replay write after a request listener stops replay', () => {
    const h = mount(async () => bars);
    const full = [...bars, { ...bars[0], time: 120 }];
    h.chart.primarySeries()!.setData(full);
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 180 });
    let stopped = false;
    const unsubscribe = h.context().subscribeRequestChanges!(() => {
      if (stopped) return;
      stopped = true;
      replay.stop();
    });
    replay.seekTime(120);
    expect(h.context().requestState!().replay).toBeUndefined();
    expect(h.chart.primarySeries()!.getData()).toEqual(full);
    unsubscribe();
  });

  it('protects the initial state of a replacement source before its first data', () => {
    const h = mount(async () => bars);
    h.chart.primarySeries()!.remove();
    const replacement = h.chart.addSeries('candlestick');
    const state = h.context().requestState!().source!;
    expect(Object.isFrozen(state)).toBe(true);
    expect(() => { (state as { sourceId: number }).sourceId = -1; }).toThrow();
    replacement.setData(bars);
    expect(h.context().requestState!().source).toMatchObject({ sourceId: state.sourceId, revision: 1 });
  });

  it.each(['stop after data', 'nested seek', 'restart during stop'] as const)('retains the newest replay transition: %s', mode => {
    const h = mount(async () => bars), source = h.chart.primarySeries()!;
    const full = [...bars, { ...bars[0], time: 120 }];
    source.setData(full);
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 180 });
    let handled = false;
    const unsubscribe = h.context().subscribeRequestChanges!(() => {
      if (handled) return;
      const state = h.context().requestState!();
      if (mode === 'stop after data' && source.getData().length !== 1) return;
      if (mode === 'restart during stop' && state.replay !== undefined) return;
      handled = true;
      if (mode === 'stop after data') replay.stop();
      else replay.seekTime(mode === 'nested seek' ? 180 : 120);
    });
    if (mode === 'restart during stop') replay.stop();
    else replay.seekTime(120);
    expect(handled).toBe(true);
    expect(source.getData()).toEqual(mode === 'restart during stop' ? [bars[0]] : full);
    expect(h.context().requestState!().replay?.asOf).toBe(mode === 'stop after data' ? undefined : mode === 'nested seek' ? 180 : 120);
    unsubscribe();
  });
});
