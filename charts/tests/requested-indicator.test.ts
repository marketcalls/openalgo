import { afterEach, describe, expect, it } from 'vitest';
import type {
  Bar, ChartDataContext, IndicatorAttachContext, IndicatorDataStatus,
  IndicatorRequestState, IndicatorSettings, IndicatorSnapshotRequest, IndicatorValues, RequestedBarsSnapshot,
} from '../src/index';
import { createRequestedIndicator, type RequestedIndicatorDescriptor } from '../src/indicators/requested-indicator';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { fakeDocument } from './helpers/fake-dom';

const bars = (...times: number[]): Bar[] => times.map(time => ({ time, open: 999, high: 999, low: 999, close: 999 }));
const snapshot = (values = [10, 20, 30]): RequestedBarsSnapshot => ({
  bars: values.map((close, i) => ({ time: i * 60, open: close, high: close, low: close, close })),
  availableAt: values.map((_value, i) => (i + 1) * 60), confirmed: values.map(() => true),
});
const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) await Promise.resolve(); };

function harness(overrides: Partial<RequestedIndicatorDescriptor> = {}, modern = true) {
  let source = bars(60, 120, 180);
  let settings: IndicatorSettings = { instrument: 'OTHER', factor: 1 };
  let market: ChartDataContext = { symbol: 'PRIMARY', interval: '1m' };
  let state: IndicatorRequestState = {
    source: { sourceId: 1, revision: 1, historyRevision: 1, provenance: 'history', change: 'reset' },
    providerRevision: 1, dataRevision: 0, supportsSnapshots: true,
  };
  let retry: (() => void) | null = null;
  let recomputes = 0;
  const controller = new AbortController();
  const statuses: IndicatorDataStatus[] = [];
  const listeners = new Set<() => void>();
  const dataListeners = new Set<() => void>();
  const requests: { request: IndicatorSnapshotRequest; resolve(value: RequestedBarsSnapshot): void; reject(reason: unknown): void }[] = [];
  const descriptor = createRequestedIndicator({
    id: 'managed-request', name: 'Managed request', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'Value' }],
    request: ctx => ({ symbol: String(ctx.settings.instrument), interval: '1m', from: 0, to: ctx.bars[ctx.bars.length - 1]?.time ?? 0 }),
    expression: (requested, current) => ({ v: requested.map(bar => bar.close * Number(current.factor)) }),
    ...overrides,
  });
  const store = {};
  const context: IndicatorAttachContext = {
    bars: () => source, settings: () => settings, store, signal: controller.signal,
    dataContext: () => market,
    requestSnapshot: request => new Promise((resolve, reject) => requests.push({ request, resolve, reject })),
    requestState: modern ? () => state : undefined,
    subscribeRequestChanges: modern ? listener => { listeners.add(listener); return () => { listeners.delete(listener); }; } : undefined,
    subscribeDataChanges: listener => { const notify = () => listener('range'); dataListeners.add(notify); return () => { dataListeners.delete(notify); }; },
    setDataStatus: status => { statuses.push(status); },
    setDataRetry: callback => { retry = callback; },
    requestRecompute: () => { recomputes++; },
  };
  let cleanup = descriptor.attach!(context);
  const notify = (): void => { for (const listener of listeners) listener(); for (const listener of dataListeners) listener(); };
  return {
    requests, statuses, listeners, dataListeners, context, descriptor, store,
    values: () => descriptor.calc(source, settings, store).v,
    state: (patch: Partial<IndicatorRequestState>) => { state = { ...state, ...patch }; notify(); },
    revision: (revision: number) => { state = { ...state, source: { ...state.source!, revision, provenance: 'live', change: 'replace' } }; notify(); },
    range: (...times: number[]) => { source = bars(...times); state = { ...state, source: { ...state.source!, revision: state.source!.revision + 1 } }; notify(); },
    market: (value: ChartDataContext) => { market = value; notify(); },
    reattach: (patch: IndicatorSettings = {}) => {
      if (typeof cleanup === 'function') cleanup();
      settings = { ...settings, ...patch }; cleanup = descriptor.attach!(context);
    },
    retry: () => retry?.(),
    recomputes: () => recomputes,
    detach: () => { if (typeof cleanup === 'function') cleanup(); },
    remove: () => { controller.abort(); if (typeof cleanup === 'function') cleanup(); },
  };
}

describe('managed requested expression', () => {
  it('calculates the requested history before aligning and does not fetch during calculation', async () => {
    const h = harness({ expression: requested => {
      let total = 0;
      return { v: requested.map(bar => total += bar.close) };
    } });
    expect(h.values()).toEqual([null, null, null]);
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.values()).toEqual([10, 30, 60]);
    expect(h.values()).toEqual([10, 30, 60]);
    expect(h.requests).toHaveLength(1);
    expect(h.statuses[h.statuses.length - 1].state).toBe('ready'); h.remove();
  });

  it('initializes and aligns every named column of a bar-shaped plot', async () => {
    const h = harness({
      plots: [{ key: 'candle', type: 'candlestick', title: 'Candle', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }],
      expression: requested => ({
        o: requested.map(bar => bar.open), h: requested.map(bar => bar.high),
        l: requested.map(bar => bar.low), c: requested.map(bar => bar.close),
      }),
    });
    expect(h.descriptor.calc(h.context.bars(), {}, h.store)).toEqual({
      o: [null, null, null], h: [null, null, null], l: [null, null, null], c: [null, null, null],
    });
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.descriptor.calc(h.context.bars(), {}, h.store)).toEqual({
      o: [10, 20, 30], h: [10, 20, 30], l: [10, 20, 30], c: [10, 20, 30],
    }); h.remove();
  });

  it('keeps confirmed-prefix barriers and null gaps across refreshes', async () => {
    const h = harness({ gaps: 'missing' });
    h.range(60, 90, 120, 180);
    h.requests[0].resolve({ ...snapshot(), confirmed: [true, false, true] }); await settle();
    h.requests[1].resolve({ ...snapshot(), confirmed: [true, false, true] }); await settle();
    expect(h.values()).toEqual([10, null, null, null]);
    h.state({ dataRevision: 1 });
    h.requests[2].resolve({ ...snapshot([10, NaN, 30]), availableAt: [60, 120, 180] }); await settle();
    expect(h.values()).toEqual([10, null, null, 30]); h.remove();
  });

  it('coalesces repeated same-time changes into one active request and one latest catch-up', async () => {
    const h = harness();
    for (let i = 2; i <= 11; i++) h.revision(i);
    expect(h.requests).toHaveLength(1);
    expect(h.requests[0].request.signal?.aborted).toBe(false);
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.requests).toHaveLength(2);
    h.requests[1].resolve(snapshot([10, 20, 35])); await settle();
    expect(h.values()).toEqual([10, 20, 35]);
    expect(h.requests).toHaveLength(2);
    h.revision(11); expect(h.requests).toHaveLength(2); h.remove();
  });

  it('does not settle a placeholder when a provider synchronously announces another revision', async () => {
    const h = harness(); h.requests[0].resolve(snapshot()); await settle();
    const original = h.context.requestSnapshot!;
    let notified = false;
    h.context.requestSnapshot = request => {
      if (!notified) { notified = true; h.revision(3); }
      return original(request);
    };
    h.revision(2); await settle();
    expect(h.requests).toHaveLength(2);
    expect(h.values()).toEqual([10, 20, 30]);
    h.requests[1].resolve(snapshot([10, 20, 40])); await settle();
    expect(h.requests).toHaveLength(3);
    h.requests[2].resolve(snapshot([10, 20, 50])); await settle();
    expect(h.values()).toEqual([10, 20, 50]); h.remove();
  });

  it('does not resume an older selection after cancellation synchronously changes the provider', async () => {
    const h = harness(); h.requests[0].resolve(snapshot()); await settle(); h.revision(2);
    h.requests[1].request.signal!.addEventListener('abort', () => h.state({ providerRevision: 3 }), { once: true });
    h.state({ providerRevision: 2 });
    h.requests[h.requests.length - 1].resolve(snapshot([40, 50, 60])); await settle();
    expect(h.requests).toHaveLength(3);
    expect(h.values()).toEqual([40, 50, 60]); h.remove();
  });

  it.each(['provider', 'source', 'history', 'market', 'settings'] as const)('cancels and clears obsolete %s generations', async kind => {
    const h = harness();
    h.requests[0].resolve(snapshot()); await settle();
    h.revision(2);
    if (kind === 'provider') h.state({ providerRevision: 2 });
    if (kind === 'source') h.state({ source: { sourceId: 2, revision: 2, historyRevision: 1, provenance: 'live', change: 'replace' } });
    if (kind === 'history') h.state({ source: { sourceId: 1, revision: 3, historyRevision: 2, provenance: 'history', change: 'correction' } });
    if (kind === 'market') h.market({ symbol: 'NEXT', interval: '1m' });
    if (kind === 'settings') h.reattach({ instrument: 'NEXT' });
    expect(h.requests[1].request.signal?.aborted).toBe(true);
    expect(h.values()).toEqual([null, null, null]);
    h.requests[1].resolve(snapshot([1, 2, 3]));
    h.requests[2].resolve(snapshot([40, 50, 60])); await settle();
    expect(h.values()).toEqual([40, 50, 60]); h.remove();
  });

  it('retains pending work on style reattachment and evaluates with current settings', async () => {
    const h = harness();
    h.reattach({ factor: 2 }); await settle();
    expect(h.requests).toHaveLength(1);
    expect(h.requests[0].request.signal?.aborted).toBe(false);
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.values()).toEqual([20, 40, 60]); h.remove();
  });

  it('reloads the entire selected window on growth so expression warmup is retained', async () => {
    const h = harness();
    h.requests[0].resolve(snapshot()); await settle();
    h.range(-60, 60, 120, 180, 240);
    expect(h.requests[1].request).toMatchObject({ from: 0, to: 240 });
    h.requests[1].resolve(snapshot([10, 20, 30, 40])); await settle();
    expect(h.values()).toEqual([null, 10, 20, 30, 40]); h.remove();
  });

  it('reports failures, coalesces retry clicks and handles empty snapshots', async () => {
    const h = harness();
    const error = new Error('Unavailable'); h.requests[0].reject(error); await settle();
    expect(h.statuses[h.statuses.length - 1]).toEqual({ state: 'error', error });
    h.retry(); h.retry(); expect(h.requests).toHaveLength(2);
    h.requests[1].resolve(snapshot([])); await settle();
    expect(h.values()).toEqual([null, null, null]);
    expect(h.statuses[h.statuses.length - 1].state).toBe('empty'); h.remove();
  });

  it('copies provider snapshots and passes frozen requested input to expressions', async () => {
    const h = harness({ expression: requested => {
      expect(Object.isFrozen(requested)).toBe(true); expect(Object.isFrozen(requested[0])).toBe(true);
      return { v: requested.map(bar => bar.close) };
    } });
    const value = snapshot(); h.requests[0].resolve(value); await settle();
    (value.bars as Bar[])[0].close = 99; (value.availableAt as number[])[0] = 999;
    expect(h.values()).toEqual([10, 20, 30]); h.remove();
  });

  it('rejects malformed snapshots before publishing and leaves the last valid snapshot intact', async () => {
    const h = harness(); h.requests[0].resolve(snapshot()); await settle();
    h.revision(2); h.requests[1].resolve({ ...snapshot(), availableAt: [] }); await settle();
    expect(h.statuses[h.statuses.length - 1].state).toBe('error');
    expect(h.values()).toEqual([10, 20, 30]); h.remove();
  });

  it('reports expression repaint failures without publishing an invalid replacement snapshot', async () => {
    const h = harness(); h.requests[0].resolve(snapshot()); await settle();
    const failure = new Error('Invalid expression column');
    h.context.requestRecompute = () => { throw failure; };
    h.revision(2); h.requests[1].resolve(snapshot([40, 50, 60])); await settle();
    expect(h.statuses[h.statuses.length - 1]).toEqual({ state: 'error', error: failure });
    expect(h.values()).toEqual([10, 20, 30]); h.context.requestRecompute = () => {}; h.remove();
  });

  it.each([
    { symbol: '', interval: '1m', from: 0, to: 1 },
    { symbol: 'OTHER', interval: '', from: 0, to: 1 },
    { symbol: 'OTHER', interval: '1m', from: 2, to: 1 },
    { symbol: 'OTHER', interval: '1m', from: 0, to: Infinity },
    { symbol: 'OTHER', interval: '1m', from: 0, to: 1, asOf: NaN },
  ])('rejects invalid selections before calling a provider (%#)', request => {
    const h = harness({ request: () => request });
    expect(h.requests).toHaveLength(0); expect(h.statuses[h.statuses.length - 1].state).toBe('error'); h.remove();
  });

  it('cancels lost snapshot capability and can retry restored support', async () => {
    const h = harness(); h.state({ supportsSnapshots: false });
    expect(h.requests[0].request.signal?.aborted).toBe(true);
    expect(h.statuses[h.statuses.length - 1].state).toBe('unsupported');
    h.state({ supportsSnapshots: true }); h.requests[1].resolve(snapshot()); await settle();
    expect(h.values()).toEqual([10, 20, 30]); h.remove();
  });

  it('supports older contexts through data notifications and an optional snapshot hook', async () => {
    const h = harness({}, false);
    h.requests[0].resolve(snapshot()); await settle();
    h.revision(2); expect(h.requests).toHaveLength(2);
    h.remove(); expect(h.dataListeners.size).toBe(0);
    const unsupported = harness(); unsupported.remove();
    delete unsupported.context.requestSnapshot;
    const detach = unsupported.descriptor.attach!({ ...unsupported.context, signal: undefined, store: {} });
    expect(unsupported.statuses[unsupported.statuses.length - 1].state).toBe('unsupported');
    if (typeof detach === 'function') detach();
  });

  it('aborts removal and detached work and ignores providers that settle afterwards', async () => {
    const h = harness(); h.remove();
    expect(h.requests[0].request.signal?.aborted).toBe(true);
    const count = h.recomputes(); h.requests[0].resolve(snapshot()); await settle();
    expect(h.recomputes()).toBe(count); expect(h.listeners.size).toBe(0);
    expect(h.values()).toEqual([null, null, null]);
    const detached = harness(); detached.detach(); await settle();
    expect(detached.requests[0].request.signal?.aborted).toBe(true);
  });

  it('does not request empty source windows or unsupported selectors', () => {
    const h = harness({ request: () => null });
    expect(h.requests).toHaveLength(0); expect(h.statuses[h.statuses.length - 1].state).toBe('unsupported'); h.remove();
    const empty = harness(); empty.range();
    expect(empty.requests[0].request.signal?.aborted).toBe(true);
    expect(empty.values()).toEqual([]); expect(empty.statuses[empty.statuses.length - 1].state).toBe('empty'); empty.remove();
  });
});

describe('requested replay isolation', () => {
  it('keeps unavailable observations out of an asOf expression and validates the entire response first', async () => {
    const seen: number[][] = [];
    const h = harness({
      request: () => ({ symbol: 'OTHER', interval: '1m', from: 0, to: 180, asOf: 125 }),
      expression: requested => { seen.push(requested.map(bar => bar.close)); return { v: requested.map(bar => bar.close) }; },
    });
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.values()).toEqual([10, 20, 20]); expect(seen).toEqual([[10, 20]]);
    h.revision(2);
    h.requests[1].resolve({ ...snapshot(), availableAt: [60, 120, 1] }); await settle();
    expect(h.statuses[h.statuses.length - 1].state).toBe('error');
    h.revision(3);
    h.requests[2].resolve({ ...snapshot(), availableAt: [60, null, 180] }); await settle();
    expect(h.values()).toEqual([10, 10, 10]); expect(seen[seen.length - 1]).toEqual([10]); h.remove();
  });

  it('keeps selector cutoff identity separate from an advancing replay clock', async () => {
    const h = harness({ request: () => ({ symbol: 'OTHER', interval: '1m', from: 0, to: 180, asOf: 125 }) });
    h.state({ replay: { time: 180, asOf: 200, forming: true } });
    h.requests[1].resolve(snapshot()); await settle();
    expect(h.values()).toEqual([10, 20, 20]);
    h.state({ replay: { time: 180, asOf: 210, forming: true } });
    expect(h.requests).toHaveLength(2);
    expect(h.values()).toEqual([10, 20, 20]); h.remove();
  });
  it('isolates live, forward, backward and restored requests and honors explicit target clocks', async () => {
    const h = harness({ targetTimes: ctx => ctx.bars.map((bar, i) => i === ctx.bars.length - 1 ? ctx.requestState?.replay?.asOf ?? bar.time : bar.time) });
    h.state({ replay: { time: 180, asOf: 200, forming: true } });
    expect(h.requests[0].request.signal?.aborted).toBe(true);
    expect(h.requests[1].request.asOf).toBe(200);
    h.requests[0].resolve(snapshot([1, 2, 3]));
    h.requests[1].resolve({ ...snapshot(), availableAt: [60, 120, 190] }); await settle();
    expect(h.values()).toEqual([10, 20, 30]);
    h.state({ replay: { time: 180, asOf: 210, forming: true } });
    expect(h.requests[2].request.asOf).toBe(210);
    h.state({ replay: { time: 180, asOf: 185, forming: true } });
    expect(h.requests[2].request.signal?.aborted).toBe(true);
    expect(h.values()).toEqual([null, null, null]);
    h.requests[2].resolve(snapshot([1, 2, 99]));
    h.requests[3].resolve({ ...snapshot(), availableAt: [60, 120, 190] }); await settle();
    expect(h.values()).toEqual([10, 20, 20]);
    h.state({ replay: undefined }); expect(h.values()).toEqual([null, null, null]);
    expect(h.requests[4].request.asOf).toBeUndefined();
    h.requests[4].resolve(snapshot([10, 20, 40])); await settle();
    expect(h.values()).toEqual([10, 20, 40]); h.remove();
  });

  it('does not infer an availability clock for legacy replay', () => {
    const h = harness(); h.state({ replay: { time: 180, forming: false } });
    expect(h.requests[0].request.signal?.aborted).toBe(true);
    expect(h.requests).toHaveLength(1);
    expect(h.statuses[h.statuses.length - 1].state).toBe('unsupported'); h.remove();
  });

  it('validates target alignment even before data arrives', () => {
    const h = harness({ targetTimes: () => [60, 120] });
    expect(() => h.values()).toThrow(/target.*length/i); h.remove();
  });
});

const charts: Chart[] = [];
const replays: ReplayController[] = [];
let sequence = 0;
afterEach(() => {
  replays.splice(0).forEach(replay => replay.stop());
  charts.splice(0).forEach(chart => chart.destroy());
});

function chartHarness(overrides: Partial<RequestedIndicatorDescriptor> = {}) {
  const document = fakeDocument();
  const requests: { request: IndicatorSnapshotRequest; resolve(value: RequestedBarsSnapshot): void }[] = [];
  const provider = {
    requestBars: async () => [],
    requestSnapshot: (request: IndicatorSnapshotRequest): Promise<RequestedBarsSnapshot> => new Promise(resolve => requests.push({ request, resolve })),
  };
  const chart = new Chart(document.createElement('div'), {
    document, barsProvider: provider, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart); chart.applySize(800, 600); chart.setDataContext({ symbol: 'PRIMARY', interval: '1m' });
  const source = chart.addSeries('candlestick'); source.setData(bars(60, 120, 180));
  const id = `requested-managed-${sequence++}`;
  registerIndicator(createRequestedIndicator({
    id, name: 'Requested managed', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'Value' }],
    request: () => ({ symbol: 'OTHER', interval: '1m', from: 0, to: 300 }),
    expression: requested => ({ v: requested.map(bar => bar.close) }),
    targetTimes: ctx => ctx.bars.map((bar, i) => i === ctx.bars.length - 1 ? ctx.requestState?.replay?.asOf ?? bar.time : bar.time),
    ...overrides,
  }));
  const indicator = chart.addIndicator(id);
  return { chart, source, indicator, requests, provider };
}

describe('requested indicator on native Chart', () => {
  it('adopts an unstarted request when a loading listener synchronously changes style', async () => {
    const h = chartHarness(); h.requests[0].resolve(snapshot()); await settle();
    let changed = false;
    const unsubscribe = h.indicator.subscribeDataStatus(status => {
      if (status.state === 'loading' && !changed) {
        changed = true;
        h.indicator.setSettings({ 'v:color': '#ff0000' });
      }
    });
    h.source.update({ ...bars(180)[0], close: 888 });
    expect(h.requests).toHaveLength(2);
    expect(h.requests[1].request.signal?.aborted).toBe(false);
    h.requests[1].resolve(snapshot([10, 20, 40])); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 40]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
    expect(h.requests).toHaveLength(2); unsubscribe();
  });

  it('adopts a request without duplicating it when the provider synchronously changes style', async () => {
    const h = chartHarness(); h.requests[0].resolve(snapshot()); await settle();
    h.chart.setBarsProvider({
      requestBars: h.provider.requestBars,
      requestSnapshot: request => {
        h.indicator.setSettings({ 'v:color': '#ff0000' });
        return h.provider.requestSnapshot(request);
      },
    });
    expect(h.requests).toHaveLength(2);
    h.requests[1].resolve(snapshot([40, 50, 60])); await settle();
    expect(h.indicator.values().v).toEqual([40, 50, 60]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
    expect(h.requests).toHaveLength(2);
  });

  it('preserves a settings calculation error through reattachment and recovers without refetching', async () => {
    const failure = new Error('Factor must be positive');
    const h = chartHarness({
      inputs: [{ key: 'factor', type: 'number', label: 'Factor', default: 1 }],
      expression: (requested, settings) => {
        const factor = Number(settings.factor);
        if (factor <= 0) throw failure;
        return { v: requested.map(bar => bar.close * factor) };
      },
    });
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.indicator.dataStatus()?.state).toBe('ready');
    h.indicator.setSettings({ factor: -1 });
    expect(h.indicator.dataStatus()).toEqual({ state: 'error', error: failure });
    expect(h.requests).toHaveLength(1);
    h.indicator.setSettings({ factor: 2 });
    expect(h.indicator.values().v).toEqual([20, 40, 60]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
    expect(h.requests).toHaveLength(1);
  });

  it('retains native calculation errors and the last accepted snapshot', async () => {
    const h = chartHarness({ expression: (requested): IndicatorValues => requested[0]?.close === 40
      ? { wrong: requested.map(bar => bar.close) } : { v: requested.map(bar => bar.close) } });
    h.requests[0].resolve(snapshot()); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
    h.chart.invalidateRequestedData(); h.requests[1].resolve(snapshot([40, 50, 60])); await settle();
    expect(h.indicator.dataStatus()?.state).toBe('error');
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
  });

  it('refreshes same-time values, explicit requested confirmation and provider replacements', async () => {
    const h = chartHarness();
    h.requests[0].resolve({ ...snapshot(), confirmed: [true, true, false] }); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 20]);
    h.source.update({ ...bars(180)[0], close: 888 });
    h.requests[1].resolve(snapshot([10, 20, 40])); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 40]);
    h.chart.invalidateRequestedData(); expect(h.requests).toHaveLength(3);
    h.chart.setBarsProvider({ ...h.provider });
    expect(h.requests[2].request.signal?.aborted).toBe(true);
    expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[2].resolve(snapshot([1, 2, 3])); h.requests[3].resolve(snapshot([50, 60, 70])); await settle();
    expect(h.indicator.values().v).toEqual([50, 60, 70]);
    h.chart.setBarsProvider(null); expect(h.indicator.dataStatus()?.state).toBe('unsupported');
  });

  it('clears same-shaped history and source replacements', async () => {
    const h = chartHarness(); h.requests[0].resolve(snapshot()); await settle();
    h.source.setData(bars(60, 120, 180)); expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[1].resolve(snapshot([30, 40, 50])); await settle();
    expect(h.indicator.values().v).toEqual([30, 40, 50]);
    h.source.remove(); const replacement = h.chart.addSeries('candlestick'); replacement.setData(bars(60, 120, 180));
    expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[h.requests.length - 1].resolve(snapshot([60, 70, 80])); await settle();
    expect(h.indicator.values().v).toEqual([60, 70, 80]);
  });

  it('observes availability movement within one primary replay observation and restores live data', async () => {
    const h = chartHarness(); h.requests[0].resolve(snapshot()); await settle();
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 250 });
    replays.push(replay);
    const timed = { ...snapshot(), availableAt: [60, 120, 260] };
    h.requests[h.requests.length - 1].resolve(timed); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 20]);
    replay.seekTime(270);
    expect(h.requests[h.requests.length - 1].request.asOf).toBe(270);
    h.requests[h.requests.length - 1].resolve(timed); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
    replay.seekTime(250); expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[h.requests.length - 1].resolve(timed); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 20]);
    replay.stop(); expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[h.requests.length - 1].resolve(snapshot([10, 20, 50])); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 50]);
  });
});
