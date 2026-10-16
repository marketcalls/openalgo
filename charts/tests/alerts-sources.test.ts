import { afterEach, describe, expect, it, vi } from 'vitest';
import '../src/indicators/index';
import {
  AlertController, Chart, registerBarCondition, unregisterBarCondition, registeredBarConditions, registerIndicator,
} from '../src/index';
import type { AlertTriggeredPayload, Bar, BarConditionContext } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const customIds: string[] = [];
const bar = (time: number, close: number, oi?: number): Bar => ({ time, open: close, high: close, low: close, close, oi });
afterEach(() => {
  for (const chart of charts.splice(0)) chart.destroy();
  for (const id of customIds.splice(0)) unregisterBarCondition(id);
});

function setup(initial = [bar(60, 10), bar(120, 10), bar(180, 10), bar(240, 10), bar(300, 10)]) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  charts.push(chart);
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(initial);
  const alerts = new AlertController(chart);
  const fired: AlertTriggeredPayload[] = [];
  chart.on('alert:triggered', event => fired.push(event as AlertTriggeredPayload));
  return { chart, series, alerts, fired };
}

registerIndicator({
  id: 'alert-source-gapped', name: 'Gapped source', placement: 'pane', inputs: [],
  plots: [{ key: 'reading', type: 'line', title: 'Reading' }],
  calc: bars => ({ reading: bars.map(item => item.oi ?? null) }),
});

registerIndicator({
  id: 'alert-source-overlay', name: 'Mixed panes', placement: 'pane', inputs: [],
  plots: [{ key: 'price', type: 'line', title: 'Price reading', overlay: true }, { key: 'reading', type: 'line', title: 'Reading' }],
  calc: bars => ({ price: bars.map(item => item.close), reading: bars.map(item => item.oi ?? null) }),
});

describe('trader alert sources', () => {
  it('places an overlay-plot alert on its actual price pane', () => {
    const { chart, alerts } = setup();
    const study = chart.addIndicator('alert-source-overlay');
    expect(study.paneIndex).toBeGreaterThan(0);
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'price', value: 13 } });
    expect(alerts.availability(alert.id)).toMatchObject({ available: true, paneIndex: 0 });
  });
  it('resolves the selected instance after invalidation, even with two identical study ids', () => {
    const { chart, series, alerts, fired } = setup();
    const slow = chart.addIndicator('ema', { length: 5 });
    const fast = chart.addIndicator('ema', { length: 1 });
    const slowAlert = alerts.add({ source: { kind: 'indicator', instanceId: slow.id, plotKey: 'ma', value: 13 }, condition: 'crossingUp' });
    const fastAlert = alerts.add({ source: { kind: 'indicator', instanceId: fast.id, plotKey: 'ma', value: 13 }, condition: 'crossingUp' });
    series.update(bar(300, 14));
    expect(fired).toEqual([]);
    series.update(bar(360, 14));
    expect(fired.map(event => event.alertId)).toEqual([fastAlert.id]);
    expect(fired[0]).toMatchObject({ time: 300, index: 4, price: 14 });
    expect(alerts.list().find(item => item.id === slowAlert.id)?.state).toBe('armed');
  });

  it('observes plot units, never primary high/low, and never bridges a missing value as zero', () => {
    const { chart, series, alerts, fired } = setup([bar(60, 100, 1), bar(120, 100, 1)]);
    const study = chart.addIndicator('alert-source-gapped');
    const alert = alerts.add({
      source: { kind: 'indicator', instanceId: study.id, plotKey: 'reading', value: 0 },
      condition: 'crossingDown', policy: 'onTouch',
    });
    series.update({ ...bar(120, 100, 1), low: -50, high: 500 });
    expect(fired).toEqual([]);
    series.update(bar(120, 100));
    expect(alerts.availability(alert.id)).toMatchObject({ available: false, reason: expect.stringMatching(/value/i) });
    series.update(bar(120, 100, -1));
    expect(fired).toEqual([]);
    series.update(bar(120, 100, 1));
    series.update(bar(120, 100, -1));
    expect(fired.map(event => event.price)).toEqual([-1]);
    expect(alerts.availability(alert.id)).toMatchObject({ available: true, paneIndex: study.paneIndex });
  });

  it('treats a zero plot reading as available and respects closed plot gaps', () => {
    const { chart, series, alerts, fired } = setup([bar(60, 100, 1), bar(120, 100)]);
    const study = chart.addIndicator('alert-source-gapped');
    const alert = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'reading', value: 0 }, condition: 'crossingDown' });
    series.update(bar(120, 100, -1));
    series.update(bar(180, 100));
    expect(fired).toHaveLength(1);
    expect(alerts.availability(alert.id).available).toBe(false);
    series.update(bar(180, 100, 0));
    expect(alerts.availability(alert.id).available).toBe(true);
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'reading', value: 1 }, condition: 'crossingDown' });
    series.setData([bar(60, 100, 2), bar(120, 100), bar(180, 100, 0)]);
    series.update(bar(240, 100, 0));
    expect(fired).toHaveLength(1);
  });

  it('reports unavailable instance, plot, market and pause without inventing readings', () => {
    const { chart, series, alerts, fired } = setup();
    chart.setDataContext({ symbol: 'ONE', interval: '1m' });
    const study = chart.addIndicator('ema', { length: 1 });
    const good = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 0 }, condition: 'greaterThan' });
    const missing = alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'missing', value: 0 } });
    expect(alerts.availability(missing.id)).toMatchObject({ available: false, reason: expect.stringMatching(/plot/i) });
    alerts.setPaused(true);
    expect(alerts.availability(good.id)).toMatchObject({ available: false, reason: expect.stringMatching(/paused/i) });
    alerts.setPaused(false);
    chart.setDataContext({ symbol: 'TWO', interval: '1m' });
    expect(alerts.availability(good.id)).toMatchObject({ available: false, reason: expect.stringMatching(/context|instrument/i) });
    chart.setDataContext({ symbol: 'ONE', interval: '1m' });
    study.remove();
    expect(alerts.availability(good.id)).toMatchObject({ available: false, reason: expect.stringMatching(/instance/i) });
    series.update(bar(360, 100));
    expect(fired).toEqual([]);
  });

  it('does not flush studies on forming updates for price or confirmed-only plot alerts', () => {
    const { chart, series, alerts } = setup();
    const study = chart.addIndicator('ema', { length: 1 });
    alerts.add({ source: { kind: 'price', price: 30 } });
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 30 } });
    const accessor = vi.spyOn(chart, 'indicators');
    for (let close = 11; close < 20; close++) series.update(bar(300, close));
    expect(accessor).not.toHaveBeenCalled();
    series.update(bar(360, 20));
    expect(accessor).toHaveBeenCalled();
  });

  it('starts the next intrabar plot crossing from the latest previous close, even after a consumed touch', () => {
    const { chart, series, alerts, fired } = setup([bar(60, 100, 9), bar(120, 100, 9)]);
    const study = chart.addIndicator('alert-source-gapped');
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'reading', value: 10 },
      condition: 'crossingUp', policy: 'onTouch', repeat: 'everyTime' });
    series.update(bar(120, 100, 11));
    series.update(bar(120, 100, 9));
    series.update(bar(180, 100, 11));
    expect(fired.map(event => event.time)).toEqual([120, 180]);
  });

  it('silently reseeds a study edit instead of calling its changed output a market crossing', () => {
    const { chart, series, alerts, fired } = setup([bar(60, 10), bar(120, 20)]);
    const study = chart.addIndicator('ema', { length: 2 });
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 17 },
      condition: 'crossingUp', policy: 'onTouch' });
    study.setSettings({ length: 1 });
    series.update({ ...bar(120, 20), volume: 100 });
    expect(fired).toEqual([]);
    series.update(bar(120, 16));
    series.update(bar(120, 18));
    expect(fired).toHaveLength(1);
  });

  it('keeps study recomputation deferred during a host pause and reseeds once on resume', () => {
    const { chart, series, alerts, fired } = setup();
    const study = chart.addIndicator('ema', { length: 1 });
    alerts.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 13 },
      policy: 'onTouch', condition: 'crossingUp' });
    alerts.setPaused(true);
    const accessor = vi.spyOn(chart, 'indicators');
    series.update(bar(300, 14));
    series.update(bar(300, 15));
    expect(accessor).not.toHaveBeenCalled();
    alerts.setPaused(false);
    expect(accessor).toHaveBeenCalledTimes(1);
    series.update(bar(300, 15));
    expect(fired).toEqual([]);
    series.update(bar(300, 12));
    series.update(bar(300, 14));
    expect(fired).toHaveLength(1);
  });

  it('passes named predicates only the revealed prefix and leaves delivery to the host', () => {
    const { series, alerts, fired } = setup([bar(60, 10), bar(120, 10)]);
    const observations: { length: number; index: number; last: number }[] = [];
    customIds.push('observed-prefix');
    registerBarCondition({ id: 'observed-prefix', title: 'Observed prefix', when: ({ bars, index }: BarConditionContext) => {
      observations.push({ length: bars.length, index, last: bars[bars.length - 1].time });
      return bars[index].close > bars[index].open;
    } });
    const alert = alerts.add({ source: { kind: 'barCondition', id: 'observed-prefix' } });
    expect(alert.condition).toBe('matches');
    expect(observations).toEqual([]);
    series.update({ ...bar(120, 12), open: 10 });
    series.update(bar(180, 11));
    expect(observations).toEqual([{ length: 2, index: 1, last: 120 }]);
    expect(fired).toHaveLength(1);
    expect(fired[0]).toMatchObject({ time: 120, price: 12, alertId: alert.id });
  });

  it.each([
    ['bullish', { open: 9, close: 10, high: 10, low: 9 }],
    ['bearish', { open: 11, close: 10, high: 11, low: 10 }],
    ['inside', { open: 10, close: 10, high: 10.5, low: 9.5 }],
    ['outside', { open: 10, close: 10, high: 12, low: 8 }],
    ['gap-up', { open: 12, close: 13, high: 14, low: 12 }],
    ['gap-down', { open: 8, close: 7, high: 8, low: 6 }],
  ] as const)('evaluates built-in %s on the confirmed bar', (id, values) => {
    const { series, alerts, fired } = setup([{ ...bar(60, 10), high: 11, low: 9 }, bar(120, 10)]);
    alerts.add({ source: { kind: 'barCondition', id } });
    series.update({ time: 120, ...values });
    expect(fired).toEqual([]);
    series.update(bar(180, 10));
    expect(fired.map(event => event.time)).toEqual([120]);
  });

  it('supports explicit intrabar predicates and isolates a failing custom predicate', () => {
    const { chart, series, alerts, fired } = setup([bar(60, 10), bar(120, 10)]);
    customIds.push('failing-predicate');
    registerBarCondition({ id: 'failing-predicate', title: 'Fails', when: () => { throw new Error('Custom failure'); } });
    const errors: unknown[] = [];
    chart.on('alert:error', event => errors.push(event));
    alerts.add({ source: { kind: 'barCondition', id: 'failing-predicate' }, policy: 'onTouch' });
    const good = alerts.add({ source: { kind: 'barCondition', id: 'bullish' }, policy: 'onTouch' });
    series.update({ ...bar(120, 12), open: 10 });
    expect(errors).toHaveLength(1);
    expect(fired.map(event => event.alertId)).toEqual([good.id]);
    series.update({ ...bar(120, 13), open: 10 });
    expect(errors).toHaveLength(1);
  });

  it('validates source-specific conditions and resolves registered predicates without storing functions', () => {
    const { alerts } = setup();
    expect(registeredBarConditions().map(item => item.id)).toEqual(expect.arrayContaining(['bullish', 'bearish', 'inside', 'outside', 'gap-up', 'gap-down']));
    expect(() => alerts.add({ source: { kind: 'barCondition', id: 'bullish' }, condition: 'crossing' })).toThrow(/condition/i);
    expect(() => alerts.add({ source: { kind: 'price', price: 0 }, condition: 'matches' })).toThrow(/condition/i);
    expect(() => alerts.add({ source: { kind: 'indicator', instanceId: 'one', plotKey: 'v', value: NaN } })).toThrow();
    expect(() => registerBarCondition({ id: 'bad', title: '', when: () => true })).toThrow();
    const id = 'custom-condition';
    customIds.push(id);
    registerBarCondition({ id, title: 'Custom', when: () => true });
    expect(() => registerBarCondition({ id, title: 'Duplicate', when: () => true })).toThrow(/id|registered/i);
    const alert = alerts.add({ source: { kind: 'barCondition', id } });
    expect(alert.source).toEqual({ kind: 'barCondition', id });
    expect(alerts.availability(alert.id).available).toBe(true);
    unregisterBarCondition(id);
    expect(alerts.availability(alert.id)).toMatchObject({ available: false, reason: expect.stringMatching(/condition/i) });
  });
});
