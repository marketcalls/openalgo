import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import type { Bar } from '../src/model/bar';
import { registerIndicator, sourceValues, type IndicatorAttachContext, type IndicatorDescriptor, type IndicatorStudySource } from '../src/model/indicator-registry';
import { SMA } from '../src/indicators/trend';
import { fakeDocument } from './helpers/fake-dom';

registerIndicator(SMA);
const charts: Chart[] = [];
let sequence = 0;
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
const reference = (instanceId: string, plotKey = 'ma') => ({ kind: 'indicator' as const, instanceId, plotKey });

function mount() {
  const document = fakeDocument();
  const pending = new Map<number, () => void>();
  let handle = 0;
  const chart = new Chart(document.createElement('div'), {
    document, timezone: 'Etc/UTC', pixelRatio: () => 1, shortcuts: false,
    raf: {
      schedule: callback => { pending.set(++handle, callback); return handle; },
      cancel: id => { pending.delete(id); },
    },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'DEPENDENT', interval: '1m' });
  const source = chart.addSeries('candlestick');
  source.setData([bar(0, 1), bar(60, 3), bar(120, 5), bar(180, 7)]);
  return { chart, source };
}

function pair() {
  const h = mount();
  const producer = h.chart.addIndicator('sma', { length: 2 });
  const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id) });
  return { ...h, producer, consumer };
}

function descriptor(patch: Partial<IndicatorDescriptor> = {}): string {
  const id = `study-input-${sequence++}`;
  registerIndicator({ ...SMA, ...patch, id, name: id });
  return id;
}

describe('native dependent study inputs', () => {
  it('shows the selected study identity in legend parameters through settings changes', () => {
    const { producer, consumer } = pair();
    expect(consumer.legend()!.options().params).toBe(`2 ${producer.id}/ma`);
    consumer.setSettings({ source: 'open' });
    expect(consumer.legend()!.options().params).toBe('2 open');
    consumer.setSettings({ source: reference(producer.id) });
    producer.remove();
    expect(consumer.legend()!.options().params).toBe(`2 ${producer.id}/ma`);
  });

  it('calculates an average of an average from committed producer output', () => {
    const h = pair();
    expect(h.producer.values().ma).toEqual([null, 2, 4, 6]);
    expect(h.consumer.values().ma).toEqual([null, null, 3, 5]);
  });

  it('updates the downstream same-time value without shifting its warmup', () => {
    const h = pair();
    h.source.update(bar(180, 9));
    expect(h.producer.values().ma).toEqual([null, 2, 4, 7]);
    expect(h.consumer.values().ma).toEqual([null, null, 3, 5.5]);
  });

  it('recalculates downstream after a producer setting changes without a source tick', () => {
    const h = pair();
    h.producer.setSettings({ length: 3 });
    expect(h.producer.values().ma).toEqual([null, null, 3, 5]);
    expect(h.consumer.values().ma).toEqual([null, null, null, 4]);
  });

  it('calculates a diamond once per node while retaining adversarial display order', () => {
    const h = mount();
    const calls: string[] = [];
    const rootId = descriptor({ calc: (...args) => { calls.push('root'); return SMA.calc(...args); } });
    const scale = (label: string, multiplier: number): string => descriptor({
      inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true }],
      calc: (bars, settings, _store, context) => {
        calls.push(label);
        return { ma: sourceValues(bars, settings.source as IndicatorStudySource, context).map(value => value !== null && Number.isFinite(value) ? value * multiplier : null) };
      },
    });
    const sumId = descriptor({
      inputs: [
        { key: 'left', type: 'source', label: 'Left', default: 'close', allowStudyOutputs: true },
        { key: 'right', type: 'source', label: 'Right', default: 'close', allowStudyOutputs: true },
      ],
      calc: (bars, settings, _store, context) => {
        calls.push('sum');
        const left = sourceValues(bars, settings.left as IndicatorStudySource, context);
        const right = sourceValues(bars, settings.right as IndicatorStudySource, context);
        return { ma: left.map((value, i) => {
          const other = right[i];
          return value !== null && other !== null && Number.isFinite(value) && Number.isFinite(other) ? value + other : null;
        }) };
      },
    });
    const root = h.chart.addIndicator(rootId, { length: 1 });
    const left = h.chart.addIndicator(scale('left', 2), { source: reference(root.id) });
    const right = h.chart.addIndicator(scale('right', 3), { source: reference(root.id) });
    const sum = h.chart.addIndicator(sumId, { left: reference(left.id), right: reference(right.id) });
    for (let i = 0; i < 3; i++) expect(h.chart.reorderIndicator(root.id, 1)).toBe(true);
    for (let i = 0; i < 2; i++) expect(h.chart.reorderIndicator(sum.id, -1)).toBe(true);
    const display = [sum.id, left.id, right.id, root.id];
    expect(h.chart.indicators().map(item => item.id)).toEqual(display);
    calls.length = 0;
    h.source.update(bar(180, 9));
    expect(calls).toEqual([]);
    expect(sum.values().ma).toEqual([5, 15, 25, 45]);
    expect(calls).toEqual(['root', 'left', 'right', 'sum']);
    expect(h.chart.indicators().map(item => item.id)).toEqual(display);
    expect(calls).toHaveLength(4);
  });

  it('reads bar-aligned values from a hidden displaced plot on another pane and scale', () => {
    const h = mount();
    const id = descriptor({ placement: 'pane', plots: SMA.plots.map(plot => ({ ...plot, offset: 2 })) });
    const producer = h.chart.addIndicator(id, { length: 2 }, { priceScaleId: 'left' });
    producer.setVisible(false);
    const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id) });
    expect(producer.paneIndex).not.toBe(consumer.paneIndex);
    expect(consumer.values().ma).toEqual([null, null, 3, 5]);
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, null, 3, 5.5]);
  });

  it('rebuilds dependent history after correction and tail writes share one flush', () => {
    const h = pair();
    h.source.update(bar(60, 30));
    h.source.update(bar(180, 9));
    expect(h.consumer.values().ma).toEqual([null, null, 16.5, 12.25]);
    expect(h.producer.values().ma).toEqual([null, 15.5, 17.5, 7]);
  });

  it('uses a full downstream pass when its producer has only a full calculation', () => {
    const h = mount();
    let tails = 0;
    const id = descriptor({ calcTail: () => { tails++; return null; } });
    // The built-in average has a tail of its own and a spread of it does not,
    // so the producer here is a spread.
    const producer = h.chart.addIndicator(descriptor(), { length: 2 });
    const consumer = h.chart.addIndicator(id, { length: 2, source: reference(producer.id) });
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, null, 3, 5.5]);
    expect(tails).toBe(0);
  });

  it('retains a missing reference as unavailable instead of falling back to price', () => {
    const h = mount();
    const selected = reference('unavailable-study');
    const consumer = h.chart.addIndicator('sma', { length: 2, source: selected });
    expect(consumer.settings().source).toEqual(selected);
    expect(consumer.values().ma).toEqual([null, null, null, null]);
    expect(consumer.dataStatus()?.state).toBe('error');
  });

  it('keeps a removed producer unavailable until the reference is explicitly changed', () => {
    const h = pair();
    const selected = reference(h.producer.id);
    h.producer.remove();
    expect(h.consumer.settings().source).toEqual(selected);
    expect(h.consumer.values().ma).toEqual([null, null, null, null]);
    expect(h.consumer.dataStatus()?.state).toBe('error');
    const replacement = h.chart.addIndicator('sma', { length: 2 });
    expect(replacement.id).not.toBe(selected.instanceId);
    expect(h.consumer.values().ma).toEqual([null, null, null, null]);
    h.consumer.setSettings({ source: reference(replacement.id) });
    expect(h.consumer.values().ma).toEqual([null, null, 3, 5]);
    expect(h.consumer.dataStatus()?.state).not.toBe('error');
  });

  it('clears descendants and silences alerts while a producer fails, then recovers without a price update', () => {
    const h = mount();
    const id = descriptor({
      inputs: [...SMA.inputs, { key: 'broken', type: 'boolean', label: 'Broken', default: false }],
      calc: (...args) => { if (args[1].broken) throw new Error('Producer calculation failed'); return SMA.calc(...args); },
    });
    const alertId = descriptor({ alerts: [{ id: 'available', title: 'Available', frequency: 'everyUpdate', when: () => true }] });
    const producer = h.chart.addIndicator(id, { length: 2 });
    const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id) });
    const descendant = h.chart.addIndicator(alertId, { length: 1, source: reference(consumer.id) });
    descendant.values();
    const oldDrawing = producer.series('ma')!.getData();
    const events: unknown[] = [];
    h.chart.on('indicator:alert', event => events.push(event));
    producer.setSettings({ broken: true });
    expect(producer.series('ma')!.getData()).toEqual(oldDrawing);
    expect(consumer.values().ma).toEqual([null, null, null, null]);
    expect(descendant.values().ma).toEqual([null, null, null, null]);
    expect(consumer.dataStatus()?.state).toBe('error');
    expect(descendant.dataStatus()?.state).toBe('error');
    h.source.update(bar(180, 9));
    descendant.values();
    expect(events).toEqual([]);
    producer.setSettings({ broken: false });
    expect(consumer.values().ma).toEqual([null, null, 3, 5.5]);
    expect(descendant.values().ma).toEqual([null, null, 3, 5.5]);
    expect(consumer.dataStatus()?.state).not.toBe('error');
    expect(events).toEqual([]);
  });

  it.each(['self', 'cycle'] as const)('rejects a %s link before changing settings, styles or subscriptions', kind => {
    const h = mount();
    const lifecycle: string[] = [];
    const id = descriptor({ attach: () => { lifecycle.push('attach'); return () => { lifecycle.push('detach'); }; } });
    const producer = h.chart.addIndicator(id, { length: 2 });
    const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id) });
    consumer.values();
    const settings = producer.settings();
    const series = producer.series('ma');
    expect(() => producer.setSettings({
      source: reference(kind === 'self' ? producer.id : consumer.id), 'ma:color': '#ff0000', length: 3,
    })).toThrow();
    expect(producer.settings()).toEqual(settings);
    expect(producer.series('ma')).toBe(series);
    expect(lifecycle).toEqual(['attach']);
    expect(consumer.values().ma).toEqual([null, null, 3, 5]);
  });

  it('rejects malformed and unknown scalar plots without changing an accepted reference', () => {
    const h = pair();
    const settings = h.consumer.settings();
    for (const source of [reference(h.producer.id, ''), reference(h.producer.id, 'missing'), { kind: 'indicator', instanceId: 42, plotKey: 'ma' }]) {
      expect(() => h.consumer.setSettings({ source, 'ma:color': '#ff0000' })).toThrow();
      expect(h.consumer.settings()).toEqual(settings);
    }
    expect(h.consumer.values().ma).toEqual([null, null, 3, 5]);
  });

  it('requires the descriptor source input to opt into study outputs', () => {
    const h = mount();
    const producer = h.chart.addIndicator('sma', { length: 2 });
    const id = descriptor({ inputs: SMA.inputs.map(input => input.type === 'source' ? { ...input, allowStudyOutputs: false } : input) });
    const consumer = h.chart.addIndicator(id, { length: 2 });
    const settings = consumer.settings();
    expect(() => consumer.setSettings({ source: reference(producer.id) })).toThrow();
    expect(consumer.settings()).toEqual(settings);
    expect(consumer.values().ma).toEqual([null, 2, 4, 6]);
  });

  it('isolates accepted and returned reference objects from external mutation', () => {
    const h = mount();
    const producer = h.chart.addIndicator('sma', { length: 2 });
    const selected = reference(producer.id);
    const consumer = h.chart.addIndicator('sma', { length: 2, source: selected });
    selected.instanceId = 'mutated-input';
    const returned = consumer.settings().source as IndicatorStudySource;
    expect(returned).toEqual(reference(producer.id));
    expect(returned).not.toBe(selected);
    Reflect.set(returned, 'instanceId', 'mutated-output');
    const next = consumer.settings().source;
    expect(next).toEqual(reference(producer.id));
    expect(next).not.toBe(returned);
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, null, 3, 5.5]);
  });

  it('propagates asynchronous producer refresh without a source tick or dependent alert', () => {
    const h = mount();
    let attachment!: IndicatorAttachContext;
    const id = descriptor({
      calc: (bars, _settings, store) => ({ ma: bars.map(item => item.close * Number(store.factor ?? 1)) }),
      attach: context => { attachment = context; },
    });
    const consumerId = descriptor({ alerts: [{ id: 'live', title: 'Live', frequency: 'everyUpdate', when: () => true }] });
    const producer = h.chart.addIndicator(id);
    const consumer = h.chart.addIndicator(consumerId, { length: 2, source: reference(producer.id) });
    consumer.values();
    const events: unknown[] = [];
    h.chart.on('indicator:alert', event => events.push(event));
    attachment.store.factor = 10;
    attachment.requestRecompute();
    expect(consumer.values().ma).toEqual([null, 20, 40, 60]);
    expect(events).toEqual([]);
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, 20, 40, 70]);
    expect(events).toHaveLength(1);
  });

  it('requires a declared scalar plot rather than selecting an OHLC plot identity', () => {
    const h = mount();
    const id = descriptor({
      plots: [
        { key: 'candles', title: 'Candles', type: 'candlestick', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
        { key: 'scalar', title: 'Scalar', type: 'line' },
      ],
      calc: bars => ({
        o: bars.map(item => item.open), h: bars.map(item => item.high), l: bars.map(item => item.low),
        c: bars.map(item => item.close), scalar: bars.map(item => item.close),
      }),
    });
    const producer = h.chart.addIndicator(id);
    const before = h.chart.indicators().length;
    expect(() => h.chart.addIndicator('sma', { length: 2, source: reference(producer.id, 'candles') })).toThrow();
    expect(h.chart.indicators()).toHaveLength(before);
    const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id, 'scalar') });
    expect(consumer.values().ma).toEqual([null, 2, 4, 6]);
  });

  it.each(['calc', 'alert'] as const)('withholds a stale descendant snapshot when a consumer %s changes the producer', stage => {
    const h = mount();
    let mutate = (): void => {};
    const producer = h.chart.addIndicator('sma', { length: 2 });
    const consumerId = descriptor({
      calc: (...args) => { if (stage === 'calc') mutate(); return SMA.calc(...args); },
      alerts: [{ id: 'change', title: 'Change', frequency: 'everyUpdate', when: () => { if (stage === 'alert') mutate(); return true; } }],
    });
    const consumer = h.chart.addIndicator(consumerId, { length: 2, source: reference(producer.id) });
    let descendantCalls = 0;
    const descendantId = descriptor({ calc: (...args) => { descendantCalls++; return SMA.calc(...args); } });
    const descendant = h.chart.addIndicator(descendantId, { length: 1, source: reference(consumer.id) });
    descendant.values(); descendantCalls = 0;
    mutate = () => { mutate = () => {}; producer.setSettings({ length: 1 }); };
    h.source.update(bar(180, 9));
    expect(descendant.values().ma).toEqual([null, null, null, null]);
    expect(descendantCalls).toBe(0);
    expect(descendant.dataStatus()?.state).toBe('error');
    expect(descendant.values().ma).toEqual([null, 2, 4, 7]);
    expect(descendantCalls).toBe(1);
    expect(descendant.dataStatus()?.state).not.toBe('error');
  });

  it('allows downstream tail calculation only while producer prefix history stays unchanged', () => {
    const h = mount();
    let producerTails = 0;
    let consumerTails = 0;
    const producerId = descriptor({
      calc: bars => ({ ma: bars.map(item => item.close) }),
      calcTail: (bars, _settings, from) => { producerTails++; return { ma: bars.slice(from).map(item => item.close) }; },
    });
    const consumerId = descriptor({
      calcTail: (bars, settings, from, _previous, _store, context) => {
        consumerTails++;
        return { ma: sourceValues(bars, settings.source as IndicatorStudySource, context).slice(from) };
      },
    });
    const producer = h.chart.addIndicator(producerId);
    const consumer = h.chart.addIndicator(consumerId, { length: 1, source: reference(producer.id) });
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([1, 3, 5, 9]);
    expect([producerTails, consumerTails]).toEqual([1, 1]);
    h.source.update(bar(60, 30)); h.source.update(bar(180, 11));
    expect(consumer.values().ma).toEqual([1, 30, 5, 11]);
    expect([producerTails, consumerTails]).toEqual([1, 1]);
  });

  it('rejects a resolver read that was not declared as an opted-in input', () => {
    const h = mount();
    const producer = h.chart.addIndicator('sma', { length: 2 });
    const id = descriptor({
      inputs: [],
      calc: (bars, _settings, _store, context) => ({ ma: sourceValues(bars, reference(producer.id), context) }),
    });
    const before = h.chart.indicators().length;
    expect(() => h.chart.addIndicator(id)).toThrow(/declared.*input/);
    expect(h.chart.indicators()).toHaveLength(before);
  });

  it('does not accept a short producer column until aligned output recovers', () => {
    const h = mount();
    const id = descriptor({
      inputs: [{ key: 'short', type: 'boolean', label: 'Short', default: true }],
      calc: (bars, settings) => ({ ma: (settings.short ? bars.slice(1) : bars).map(item => item.close) }),
    });
    const producer = h.chart.addIndicator(id);
    const consumer = h.chart.addIndicator('sma', { length: 2, source: reference(producer.id) });
    expect(consumer.values().ma).toEqual([null, null, null, null]);
    expect(consumer.dataStatus()?.state).toBe('error');
    producer.setSettings({ short: false });
    expect(consumer.values().ma).toEqual([null, 2, 4, 6]);
    expect(consumer.dataStatus()?.state).not.toBe('error');
  });

  it('keeps bar-color precedence in display order when dependency order differs', () => {
    const h = mount();
    const producerId = descriptor({ barColors: ({ bars }) => bars.map(() => '#ff0000') });
    const consumerId = descriptor({ barColors: ({ bars }) => bars.map(() => '#00ff00') });
    const producer = h.chart.addIndicator(producerId, { length: 2 });
    const consumer = h.chart.addIndicator(consumerId, { length: 2, source: reference(producer.id) });
    consumer.values();
    expect(h.source.getData().map(item => item.color)).toEqual(new Array(4).fill('#00ff00'));
    expect(h.chart.reorderIndicator(consumer.id, -1)).toBe(true);
    h.source.update(bar(180, 9));
    expect(consumer.values().ma).toEqual([null, null, 3, 5.5]);
    expect(h.chart.indicators().map(item => item.id)).toEqual([consumer.id, producer.id]);
    expect(h.source.getData().map(item => item.color)).toEqual(new Array(4).fill('#ff0000'));
  });
});
