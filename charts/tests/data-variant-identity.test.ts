import { afterEach, describe, expect, it } from 'vitest';
import {
  dataVariantKey, normalizeDataVariant, publishDataContext, unsupportedDataVariant,
} from '../src/feed/data-variant';
import { inheritedDataVariant } from '../src/indicators/index';
import { createRequestedIndicator } from '../src/indicators/requested-indicator';
import { createTier2Indicator, type Tier2Context } from '../src/indicators/external';
import { AlertController } from '../src/alerts/controller';
import type { ChartDataContext, IndicatorDataStatus, IndicatorSnapshotRequest } from '../src/index';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorAttachContext, type IndicatorBarsRequest } from '../src/model/indicator-registry';
import { OpenAlgoLiveDataFeed } from '../src/feed/openalgo-live';
import * as base from '../src/index';
import { fakeDocument } from './helpers/fake-dom';

const cleanups: (() => void)[] = [];
afterEach(() => cleanups.splice(0).reverse().forEach(fn => fn()));
const bar = (time: number) => ({ time, open: 100, high: 101, low: 99, close: 100 });
const settle = async (): Promise<void> => { for (let i = 0; i < 8; i++) await Promise.resolve(); };
function mount(): Chart {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, raf: { schedule: () => 0 }, shortcuts: false });
  chart.applySize(800, 600);
  cleanups.push(() => chart.destroy());
  return chart;
}

describe('data variant identity', () => {
  it('normalises a variant to the fields it names and the default to nothing', () => {
    expect(normalizeDataVariant(undefined)).toBeUndefined();
    expect(normalizeDataVariant(null)).toBeUndefined();
    expect(normalizeDataVariant({})).toBeUndefined();
    expect(normalizeDataVariant({ session: undefined })).toBeUndefined();
    const value = normalizeDataVariant({ unit: 'per lot', session: 'extended' });
    expect(value).toEqual({ unit: 'per lot', session: 'extended' });
    expect(Object.isFrozen(value)).toBe(true);
  });

  it('rejects what it cannot serve faithfully rather than guessing', () => {
    for (const bad of [
      'extended', [], { session: 'overnight' }, { adjustment: 'split-only' }, { currency: '' }, { currency: '   ' },
      { unit: 7 }, { currency: 'X'.repeat(33) }, { timezone: 'UTC' },
    ]) expect(() => normalizeDataVariant(bad), JSON.stringify(bad)).toThrow(TypeError);
  });

  it('keys by value, not by field order, and keys the default as empty', () => {
    expect(dataVariantKey()).toBe('');
    expect(dataVariantKey({})).toBe('');
    expect(dataVariantKey({ currency: 'USD', session: 'extended' })).toBe(dataVariantKey({ session: 'extended', currency: 'USD' }));
    // An explicit regular session is its own identity: the provider's default may be extended.
    expect(dataVariantKey({ session: 'regular' })).not.toBe(dataVariantKey({}));
    expect(dataVariantKey({ currency: 'USD' })).not.toBe(dataVariantKey({ unit: 'USD' }));
  });

  it('serves the default always and anything else only when declared', () => {
    expect(unsupportedDataVariant(undefined, undefined)).toBeNull();
    expect(unsupportedDataVariant(undefined, {})).toBeNull();
    expect(unsupportedDataVariant(undefined, { session: 'regular' })).toBe('session');
    expect(unsupportedDataVariant({}, { adjustment: 'raw' })).toBe('adjustment');
    expect(unsupportedDataVariant({ sessions: [] }, { session: 'extended' })).toBe('session');
    const capabilities = { sessions: ['regular', 'extended'] as const, adjustments: ['raw'] as const, currencies: ['USD'], units: ['per share'] };
    expect(unsupportedDataVariant(capabilities, { session: 'extended', adjustment: 'raw', currency: 'USD', unit: 'per share' })).toBeNull();
    expect(unsupportedDataVariant(capabilities, { currency: 'usd' })).toBe('currency');
    expect(unsupportedDataVariant(capabilities, { unit: 'per lot' })).toBe('unit');
  });

  it('lets another instrument inherit how bars are observed but not what they are quoted in', () => {
    expect(inheritedDataVariant(undefined)).toBeUndefined();
    expect(inheritedDataVariant({ currency: 'USD', unit: 'per lot' })).toBeUndefined();
    expect(inheritedDataVariant({ session: 'extended', adjustment: 'raw', currency: 'USD' })).toEqual({ session: 'extended', adjustment: 'raw' });
  });

  it('exports the variant surface from the base entry point', () => {
    for (const name of ['normalizeDataVariant', 'dataVariantKey', 'unsupportedDataVariant', 'publishDataContext', 'dataVariantError']) {
      expect(typeof (base as Record<string, unknown>)[name], name).toBe('function');
    }
  });

  it('refuses a variant on the live stream, which carries one series per instrument', () => {
    const feed = new OpenAlgoLiveDataFeed({ apiKey: 'k', baseUrl: '', wsUrl: 'ws://test', socketFactory: () => ({ send() {}, close() {}, readyState: 1 }) as never });
    expect(() => feed.subscribeBars({ symbol: 'X', exchange: 'NSE', interval: '1m', variant: { session: 'extended' } }, () => {}))
      .toThrow(expect.objectContaining({ name: 'DataVariantUnsupportedError' }) as Error);
  });
});

describe('publishing a variant to a chart', () => {
  it('treats a change of variant alone as a change of source', async () => {
    const chart = mount();
    const price = chart.addSeries('candlestick');
    let ctx!: IndicatorAttachContext;
    const requests: IndicatorBarsRequest[] = [];
    chart.setBarsProvider(request => { requests.push(request); return new Promise(() => {}); });
    registerIndicator({ id: 'variant-probe', name: 'Variant probe', placement: 'pane', inputs: [],
      plots: [{ key: 'v', title: 'V', type: 'line' }], calc: bars => ({ v: bars.map(() => 1) }),
      attach: context => { ctx = context; } });
    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m' });
    price.setData([bar(60), bar(120)]);
    chart.setEvents([{ time: 60, type: 'dividend', label: 'D' }]);
    chart.addIndicator('variant-probe');
    const changes: unknown[] = [];
    ctx.subscribeDataChanges!(change => changes.push(change));
    const inFlight = ctx.requestBars!({ symbol: 'SPY', interval: '1m', from: 0, to: 120 });
    const aborted = expect(inFlight).rejects.toBeDefined();
    const revision = ctx.requestState!().source!.revision;

    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });
    expect(chart.getDataContext()).toEqual({ symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });
    await aborted;
    expect(ctx.requestState!().source!.revision).toBeGreaterThan(revision);
    expect(changes).toContain('context');
    // The instrument never changed on the way, so its event calendar stays.
    expect(chart.eventMarkers()?.events()).toHaveLength(1);
    // The same variant again is not a new source.
    const settled = changes.length;
    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });
    expect(changes).toHaveLength(settled);
    // And back to the default is.
    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m', variant: {} });
    expect(chart.getDataContext()).toEqual({ symbol: 'AAPL', exchange: 'US', interval: '1m' });
    expect(changes.length).toBeGreaterThan(settled);
    await settle();
    expect(requests).toHaveLength(1);
  });

  it('reaches studies and alerts once when only the variant changes', async () => {
    const chart = mount();
    const snapshots: IndicatorSnapshotRequest[] = [];
    chart.setBarsProvider({
      requestBars: async () => [],
      requestSnapshot: request => { snapshots.push(request); return new Promise(() => {}); },
    });
    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m' });
    chart.addSeries('candlestick').setData([bar(60), bar(120)]);
    // A requested study that asks in the chart's own interval, the usual shape.
    registerIndicator(createRequestedIndicator({
      id: 'variant-once-requested', name: 'Requested', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      request: ctx => ({ symbol: 'SPY', interval: ctx.dataContext?.interval ?? '', from: 0, to: 120 }),
      expression: requested => ({ v: requested.map(value => value.close) }),
    }));
    const fetched: Tier2Context[] = [];
    registerIndicator(createTier2Indicator({
      id: 'variant-once-external', name: 'External', placement: 'pane', inputs: [], plots: [{ key: 'v', type: 'line', title: 'V' }],
      fetch: context => { fetched.push(context); return new Promise(() => {}); },
    }));
    const requested = chart.addIndicator('variant-once-requested');
    chart.addIndicator('variant-once-external');
    const alerts = new AlertController(chart);
    alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp' });
    await settle();
    const statuses: IndicatorDataStatus['state'][] = [];
    requested.subscribeDataStatus(status => statuses.push(status.state));
    const contexts: (ChartDataContext | undefined)[] = [];
    chart.on('data:context', context => contexts.push({ ...(context as ChartDataContext) }));
    let checkpoints = 0;
    chart.on('alerts:checkpoint', () => { checkpoints++; });
    const before = { snapshots: snapshots.length, fetched: fetched.length };

    publishDataContext(chart, { symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });

    // The chart compares variants itself, so a variant-only change is one
    // context: the detour through a context with the interval cleared never runs.
    expect(contexts.map(context => [context?.interval, context?.variant])).toEqual([['1m', { session: 'extended' }]]);
    // The library's own studies and alerts wait for the real one: nothing
    // asks a provider for the interval-less context, reports an error for it
    // or saves the alerts twice.
    expect(snapshots.slice(before.snapshots).map(request => [request.interval, request.variant])).toEqual([['1m', { session: 'extended' }]]);
    expect(fetched.slice(before.fetched).map(context => [context.dataContext?.interval, context.dataContext?.variant]))
      .toEqual([['1m', { session: 'extended' }]]);
    expect(statuses).not.toContain('error');
    expect(checkpoints).toBe(1);
    alerts.destroy();
  });

  it('is a new source to Chart.setDataContext itself, announced once', () => {
    const chart = mount();
    chart.setDataContext({ symbol: 'AAPL', exchange: 'US', interval: '1m' });
    const seen: (ChartDataContext | undefined)[] = [];
    chart.on('data:context', context => seen.push(context));
    chart.setDataContext({ symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });
    expect(chart.getDataContext()?.variant).toEqual({ session: 'extended' });
    expect(seen).toHaveLength(1);
    // The same variant in a new object is the same source.
    chart.setDataContext({ symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended' } });
    expect(seen).toHaveLength(1);
    // An unset dimension reads as absent, as dataVariantKey reads it.
    chart.setDataContext({ symbol: 'AAPL', exchange: 'US', interval: '1m', variant: { session: 'extended', unit: undefined } });
    expect(seen).toHaveLength(1);
    chart.setDataContext({ symbol: 'AAPL', exchange: 'US', interval: '1m' });
    expect(chart.getDataContext()?.variant).toBeUndefined();
    expect(seen).toHaveLength(2);
  });

  it('works for a context without an interval', () => {
    const chart = mount();
    publishDataContext(chart, { symbol: 'AAPL' });
    publishDataContext(chart, { symbol: 'AAPL', variant: { adjustment: 'raw' } });
    expect(chart.getDataContext()).toEqual({ symbol: 'AAPL', variant: { adjustment: 'raw' } });
    publishDataContext(chart, undefined);
    expect(chart.getDataContext()).toBeUndefined();
  });
});
