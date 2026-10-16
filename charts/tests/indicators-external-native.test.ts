import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorValues } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { createTier2Indicator, type Tier2Context, type Tier2Descriptor, type Tier2Point } from '../src/indicators/external';
import { fakeDocument } from './helpers/fake-dom';

const bars = (...times: number[]) => times.map(time => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const point = (time: number, v: number | null): Tier2Point => ({ time, values: { v } });
const settle = async (): Promise<void> => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
const charts: Chart[] = [];
const replays: ReplayController[] = [];
let sequence = 0;
afterEach(() => { replays.splice(0).forEach(replay => replay.stop()); charts.splice(0).forEach(chart => chart.destroy()); });

function mount(live = false, patch: Partial<Tier2Descriptor> = {}) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart); chart.applySize(800, 600); chart.setDataContext({ symbol: 'PRIMARY', interval: '1m' });
  const source = chart.addSeries('candlestick'); source.setData(bars(0, 60, 120));
  const requests: { context: Tier2Context; resolve(value: readonly Tier2Point[]): void; reject(error: unknown): void }[] = [];
  const subscriptions: { context: Tier2Context; push(value: Tier2Point): void; stops: number; onStop?: () => void }[] = [];
  let onFetch: (() => void) | undefined;
  let onSubscribe: (() => void) | undefined;
  const id = `external-native-${sequence++}`;
  registerIndicator(createTier2Indicator({
    id, name: 'External native', placement: 'pane', inputs: [],
    plots: [{ key: 'v', type: 'line', title: 'Value' }],
    fetch: context => {
      onFetch?.();
      return new Promise((resolve, reject) => requests.push({ context, resolve, reject }));
    },
    subscribe: live ? (context, push) => {
      const subscription: typeof subscriptions[number] = { context, push, stops: 0 };
      subscriptions.push(subscription); onSubscribe?.();
      return () => { subscription.stops++; subscription.onStop?.(); };
    } : undefined,
    ...patch,
  }));
  const indicator = chart.addIndicator(id);
  return {
    chart, source, indicator, requests, subscriptions,
    fetchHook: (callback: () => void) => { onFetch = callback; },
    subscribeHook: (callback: () => void) => { onSubscribe = callback; },
    initial: async () => { requests[0].resolve([point(0, 10), point(60, 20), point(120, 30)]); await settle(); },
  };
}

describe('native external history lifecycle', () => {
  it('refreshes the same-time overlap without aborting active work and coalesces the latest revision', async () => {
    const h = mount(); await h.initial();
    expect(h.requests[0].context.requestState?.source?.sourceId).toBeDefined();
    for (let i = 2; i <= 11; i++) h.source.update({ ...bars(120)[0], close: i });
    expect(h.requests).toHaveLength(2);
    expect(h.requests[1].context).toMatchObject({ from: 120, to: 120 });
    expect(h.requests[1].context.signal?.aborted).toBe(false);
    h.requests[1].resolve([point(120, 35)]); await settle();
    expect(h.requests).toHaveLength(3);
    h.requests[2].resolve([point(120, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 40]); expect(h.requests).toHaveLength(3);
  });

  it.each(['reset', 'correction', 'source', 'provider', 'context'] as const)('invalidates points, live buffers and stale completions on %s', async change => {
    const h = mount(true); await h.initial();
    h.subscriptions[0].push(point(120, 33)); h.indicator.retryData();
    if (change === 'reset') h.source.setData(bars(0, 60, 120));
    if (change === 'correction') h.source.update({ ...bars(60)[0], close: 5 });
    if (change === 'source') { h.source.remove(); h.chart.addSeries('candlestick').setData(bars(0, 60, 120)); }
    if (change === 'provider') h.chart.setBarsProvider(async () => []);
    if (change === 'context') h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' });
    expect(h.requests[1].context.signal?.aborted).toBe(true);
    expect(h.subscriptions[0].stops).toBe(1);
    expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[1].resolve([point(0, 999)]); h.subscriptions[0].push(point(120, 999));
    h.requests[h.requests.length - 1].resolve([point(0, 40), point(60, 50), point(120, 60)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 50, 60]);
  });

  it('preserves a proven prepend boundary and live overlap while extending history', async () => {
    const h = mount(true); await h.initial(); h.subscriptions[0].push(point(120, 33));
    h.source.prependData(bars(-120, -60));
    expect(h.requests).toHaveLength(2);
    expect(h.requests[1].context).toMatchObject({ from: -120, to: 0 });
    expect(h.subscriptions[0].stops).toBe(0);
    h.requests[1].resolve([point(-120, 1), point(-60, 2), point(0, 999), point(120, 999)]); await settle();
    expect(h.indicator.values().v).toEqual([1, 2, 10, 20, 33]);
  });

  it('retains pending work on safe prepend but clears overlapping historical replacements', async () => {
    const h = mount(); h.source.prependData(bars(-60));
    expect(h.requests).toHaveLength(1); expect(h.requests[0].context.signal?.aborted).toBe(false);
    h.requests[0].resolve([point(0, 10), point(120, 30)]); await settle();
    expect(h.requests[1].context).toMatchObject({ from: -60, to: 0 });
    h.source.prependData([{ ...bars(60)[0], close: 55 }]);
    expect(h.requests[1].context.signal?.aborted).toBe(true);
    expect(h.indicator.values().v).toEqual([null, null, null, null]);
    expect(h.requests[2].context).toMatchObject({ from: -60, to: 120 });
  });

  it('covers both ends when prepend and append arrive during a pending tail refresh', async () => {
    const h = mount(); await h.initial();
    h.source.update({ ...bars(120)[0], close: 2 });
    h.source.prependData(bars(-60)); h.source.update(bars(180)[0]);
    expect(h.requests).toHaveLength(2);
    h.requests[1].resolve([point(120, 35)]); await settle();
    expect(h.requests[2].context).toMatchObject({ from: -60, to: 0 });
    h.requests[2].resolve([point(-60, 5), point(0, 999)]); await settle();
    expect(h.requests).toHaveLength(4);
    expect(h.requests[3].context).toMatchObject({ from: 120, to: 180 });
    h.requests[3].resolve([point(120, 36), point(180, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([5, 10, 20, 36, 40]);
    expect(h.requests).toHaveLength(4);
  });

  it('avoids history fetches on subscribed price ticks but fully refreshes explicit external revisions', async () => {
    const h = mount(true); await h.initial(); h.subscriptions[0].push(point(60, 22));
    for (let i = 0; i < 8; i++) h.source.update({ ...bars(120)[0], close: i });
    expect(h.requests).toHaveLength(1);
    h.chart.invalidateRequestedData(); h.chart.invalidateRequestedData();
    expect(h.requests).toHaveLength(2); expect(h.requests[1].context).toMatchObject({ from: 0, to: 120 });
    h.subscriptions[0].push(point(120, 44));
    h.requests[1].resolve([point(0, 50), point(120, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([50, 50, 44]);
    expect(h.requests).toHaveLength(3);
    h.requests[2].resolve([point(0, 60), point(120, 45)]); await settle();
    expect(h.indicator.values().v).toEqual([60, 60, 45]);
  });

  it('keeps an explicit replacement authoritative after a failed refresh is retried', async () => {
    const h = mount(true); await h.initial(); h.subscriptions[0].push(point(60, 22));
    h.chart.invalidateRequestedData(); h.requests[1].reject(new Error('Unavailable')); await settle();
    h.indicator.retryData(); h.requests[2].resolve([point(0, 50)]); await settle();
    expect(h.indicator.values().v).toEqual([50, 50, 50]);
  });

  it('retains full replacement intent when a price update follows a failed external refresh', async () => {
    const h = mount(); await h.initial();
    h.chart.invalidateRequestedData(); h.requests[1].reject(new Error('Unavailable')); await settle();
    h.source.update({ ...bars(120)[0], close: 2 });
    expect(h.requests[2].context).toMatchObject({ from: 0, to: 120 });
    h.requests[2].resolve([point(0, 50)]); await settle();
    expect(h.indicator.values().v).toEqual([50, 50, 50]);
  });

  it.each(['calculation', 'response'] as const)('services a newer queued revision after a %s failure', async failure => {
    const h = mount(false, { calc: (_bars, external) => {
      if (external.v[2] === 999) throw new Error('Rejected value');
      return external;
    } });
    await h.initial();
    h.source.update({ ...bars(120)[0], close: 2 });
    h.source.update({ ...bars(120)[0], close: 3 });
    h.requests[1].resolve(failure === 'calculation' ? [point(120, 999)] : null as unknown as readonly Tier2Point[]);
    await settle();
    expect(h.requests).toHaveLength(3);
    h.requests[2].resolve([point(120, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 40]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
  });
});

describe('native external replay availability', () => {
  it('defaults to unsupported during replay and stops subscriptions and pending requests', async () => {
    const h = mount(true); await h.initial(); h.indicator.retryData();
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 180 }); replays.push(replay);
    expect(h.indicator.dataStatus()?.state).toBe('unsupported');
    expect(h.requests[1].context.signal?.aborted).toBe(true); expect(h.subscriptions[0].stops).toBe(1);
    expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[1].resolve([point(0, 99)]); h.subscriptions[0].push(point(120, 99)); await settle();
    expect(h.indicator.values().v).toEqual([null, null, null]);
    replay.stop(); expect(h.requests[h.requests.length - 1].context.asOf).toBeUndefined();
    h.requests[h.requests.length - 1].resolve([point(0, 50)]); await settle();
    expect(h.indicator.values().v).toEqual([50, 50, 50]);
  });

  it('replaces complete windows on forward availability movement and isolates backward replay and live restore', async () => {
    const h = mount(true, { supportsReplay: true }); await h.initial();
    const replay = new ReplayController(h.chart, { timing: { barEndTime: bar => bar.time + 60 }, startTime: 200 }); replays.push(replay);
    let request = h.requests[h.requests.length - 1];
    expect(request.context.asOf).toBe(200); expect(h.subscriptions[0].stops).toBe(1);
    request.resolve([point(0, 10), point(60, 20), point(120, 30), point(220, 99)]); await settle();
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
    replay.seekTime(230); request = h.requests[h.requests.length - 1];
    expect(request.context).toMatchObject({ from: 0, to: 120, asOf: 230 });
    request.resolve([point(0, 40), point(120, null)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 40, null]);
    expect(h.subscriptions).toHaveLength(1);
    replay.seekTime(240); const obsolete = h.requests[h.requests.length - 1];
    replay.seekTime(200); expect(obsolete.context.signal?.aborted).toBe(true);
    expect(h.indicator.values().v).toEqual([null, null, null]);
    obsolete.resolve([point(0, 99)]);
    h.requests[h.requests.length - 1].resolve([point(0, 10)]); await settle();
    expect(h.indicator.values().v).toEqual([10, 10, 10]);
    replay.stop(); expect(h.indicator.values().v).toEqual([null, null, null]);
    h.requests[h.requests.length - 1].resolve([point(0, 70)]); await settle();
    expect(h.indicator.values().v).toEqual([70, 70, 70]);
    expect(h.subscriptions[h.subscriptions.length - 1].stops).toBe(0);
  });

  it('declines legacy replay even when the descriptor opts in', async () => {
    const h = mount(true, { supportsReplay: true }); await h.initial();
    replays.push(new ReplayController(h.chart, { startIndex: 1 }));
    expect(h.indicator.dataStatus()?.state).toBe('unsupported');
    expect(h.subscriptions[0].stops).toBe(1);
  });
});

describe('native external callback ownership', () => {
  it('keeps an unsupported status when calculation synchronously invalidates a live callback', async () => {
    let change: (() => void) | undefined;
    const h = mount(true, {
      supports: ctx => ctx.dataContext?.symbol !== 'UNSUPPORTED',
      calc: (_bars, external) => { const callback = change; change = undefined; callback?.(); return external; },
    });
    await h.initial();
    change = () => h.chart.setDataContext({ symbol: 'UNSUPPORTED', interval: '1m' });
    h.subscriptions[0].push(point(120, 40));
    expect(h.indicator.dataStatus()?.state).toBe('unsupported');
    expect(h.subscriptions[0].stops).toBe(1);
  });

  it.each(['loading', 'fetch'] as const)('adopts pending history when style changes during %s', async when => {
    const h = mount(); await h.initial(); let once = false;
    const restyle = (): void => { if (!once) { once = true; h.indicator.setSettings({ 'v:color': '#ff0000' }); } };
    const unsubscribe = when === 'loading' ? h.indicator.subscribeDataStatus(status => { if (status.state === 'loading') restyle(); }) : () => {};
    if (when === 'fetch') h.fetchHook(restyle);
    h.indicator.retryData(); expect(h.requests).toHaveLength(2);
    h.requests[1].resolve([point(0, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 40, 40]); expect(h.requests).toHaveLength(2); unsubscribe();
  });

  it('disposes a subscription returned after it synchronously changed generation', async () => {
    const h = mount(true); await h.initial(); let once = false;
    h.subscribeHook(() => { if (!once) { once = true; h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' }); } });
    h.indicator.setSettings({ 'v:color': '#ff0000' });
    expect(h.subscriptions.map(subscription => subscription.stops)).toEqual([1, 1, 0]);
    h.subscriptions[1].push(point(0, 999));
    h.requests[h.requests.length - 1].resolve([point(0, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 40, 40]);
  });

  it('clears the disposer before a cleanup callback changes providers again', async () => {
    const h = mount(true); await h.initial();
    h.subscriptions[0].onStop = () => h.chart.setBarsProvider(async () => []);
    h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' });
    expect(h.subscriptions[0].stops).toBe(1);
    h.requests[h.requests.length - 1].resolve([point(0, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 40, 40]);
    expect(h.subscriptions.filter(subscription => subscription.stops === 0)).toHaveLength(1);
  });

  it('clears pending ownership before abort callbacks change the provider', async () => {
    const h = mount(); await h.initial(); h.indicator.retryData();
    h.requests[1].context.signal!.addEventListener('abort', () => h.chart.setBarsProvider(async () => []), { once: true });
    h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' });
    h.requests[h.requests.length - 1].resolve([point(0, 40)]); await settle();
    expect(h.indicator.values().v).toEqual([40, 40, 40]);
    expect(h.requests).toHaveLength(3);
  });

  it('keeps calculation errors through completion and style reattachment and recovers with valid settings', async () => {
    const error = new Error('Factor must be positive');
    const h = mount(false, {
      inputs: [{ key: 'factor', type: 'number', label: 'Factor', default: 1 }],
      calc: (_bars, external, settings): IndicatorValues => {
        if (Number(settings.factor) < 0 || external.v[0] === 999) throw error;
        return { v: external.v.map(value => value === null ? null : value * Number(settings.factor)) };
      },
    });
    await h.initial(); h.indicator.retryData(); h.requests[1].resolve([point(0, 999)]); await settle();
    expect(h.indicator.dataStatus()).toEqual({ state: 'error', error });
    expect(h.indicator.values().v).toEqual([10, 20, 30]);
    h.indicator.setSettings({ factor: -1 }); expect(h.indicator.dataStatus()).toEqual({ state: 'error', error });
    h.indicator.setSettings({ factor: 2 });
    expect(h.indicator.values().v).toEqual([20, 40, 60]);
    expect(h.indicator.dataStatus()?.state).toBe('ready');
    expect(h.requests).toHaveLength(2);
  });

  it('aborts removal, ignores late data and releases each subscription once', async () => {
    const h = mount(true); h.indicator.remove();
    expect(h.requests[0].context.signal?.aborted).toBe(true); expect(h.subscriptions[0].stops).toBe(1);
    h.requests[0].resolve([point(0, 999)]); h.subscriptions[0].push(point(0, 999)); await settle();
    expect(h.indicator.values().v).toEqual([null, null, null]);
  });
});
