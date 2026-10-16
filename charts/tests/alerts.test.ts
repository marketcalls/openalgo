import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AlertController, Chart } from '../src/index';
import type { Bar, AlertCondition, AlertInput, AlertTriggeredPayload } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close, low: close, close });
beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(1_000_000); });
afterEach(() => {
  for (const chart of charts.splice(0)) chart.destroy();
  vi.useRealTimers();
});

function setup(initial = [bar(60, 99), bar(120, 99)]) {
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

const input = (patch: Partial<AlertInput> = {}): AlertInput => ({
  source: { kind: 'price', price: 100 }, condition: 'crossingUp', ...patch,
});

describe('trader alert timing', () => {
  it('fires onTouch for an observed wick that onBarClose never confirms', () => {
    const { series, alerts, fired } = setup();
    const closed = alerts.add(input());
    const touch = alerts.add(input({ policy: 'onTouch' }));
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired.map(event => event.alertId)).toEqual([touch.id]);
    expect(fired[0]).toMatchObject({ time: 120, index: 1, price: 100 });
    series.update(bar(120, 99));
    series.update(bar(180, 99));
    expect(fired).toHaveLength(1);
    expect(alerts.list().find(alert => alert.id === closed.id)?.state).toBe('armed');
    expect(alerts.list().find(alert => alert.id === touch.id)?.state).toBe('triggered');
  });

  it('confirms a closed crossing only when the next live bar arrives', () => {
    const { series, alerts, fired } = setup();
    const payload = { route: 'host-owned', nested: { value: 7 } };
    const alert = alerts.add(input({ message: 'Threshold reached', payload }));
    series.update(bar(120, 101));
    expect(fired).toEqual([]);
    series.update(bar(180, 102));
    expect(fired).toHaveLength(1);
    expect(fired[0]).toMatchObject({ alertId: alert.id, time: 120, index: 1, price: 101, message: 'Threshold reached' });
    expect(fired[0].alert.payload).toBe(payload);
    series.update(bar(240, 99));
    series.update(bar(300, 102));
    series.update(bar(360, 103));
    expect(fired).toHaveLength(1);
    expect(alerts.list()[0].state).toBe('triggered');
  });

  it('seeds history silently and ignores a wick that predates arming', () => {
    const { series, alerts, fired } = setup([bar(60, 99), { ...bar(120, 99), high: 104 }]);
    alerts.add(input({ policy: 'onTouch' }));
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 99), high: 104, volume: 500 });
    expect(fired).toEqual([]);
    series.prependData([bar(0, 120)]);
    series.update({ ...bar(60, 99), high: 150 });
    series.setData([bar(60, 99), { ...bar(120, 99), high: 106 }]);
    series.update({ ...bar(120, 99), high: 106, volume: 700 });
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 101), high: 106 });
    expect(fired).toHaveLength(1);
  });

  it.each([
    ['crossing', 101, 99, 100, undefined, 99],
    ['crossingUp', 99, 101, 100, undefined, 101],
    ['crossingDown', 101, 99, 100, undefined, 99],
    ['greaterThan', 101, 102, 100, undefined, 102],
    ['lessThan', 99, 98, 100, undefined, 98],
    ['enteringRange', 95, 105, 100, 110, 105],
    ['leavingRange', 105, 115, 100, 110, 115],
    ['crossingUp', -1, 1, 0, undefined, 1],
  ] as const)('evaluates %s on confirmed values %s to %s', (condition, before, after, price, upperPrice, expected) => {
    const { series, alerts, fired } = setup([bar(60, before), bar(120, before)]);
    alerts.add(input({ condition, source: { kind: 'price', price, ...(upperPrice === undefined ? {} : { upperPrice }) } }));
    series.update(bar(120, after));
    series.update(bar(180, after));
    expect(fired.map(event => event.price)).toEqual([expected]);
  });

  it('consumes duplicate and cooldown-suppressed touches without replaying an old wick', () => {
    const { series, alerts, fired } = setup();
    alerts.add(input({ policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 10 }));
    series.update({ ...bar(120, 99), high: 102 });
    series.update({ ...bar(120, 99), high: 103 });
    expect(fired).toHaveLength(1);
    series.update(bar(180, 99));
    series.update({ ...bar(180, 99), high: 102 });
    expect(fired).toHaveLength(1);
    vi.advanceTimersByTime(11_000);
    series.update({ ...bar(180, 99), high: 103 });
    expect(fired).toHaveLength(1);
    series.update(bar(240, 99));
    series.update({ ...bar(240, 99), high: 102 });
    expect(fired.map(event => event.time)).toEqual([120, 240]);
    expect(alerts.list()[0].state).toBe('armed');
  });

  it('expires while data is idle and clears its single timer on disable or destruction', () => {
    const { chart, alerts, series, fired } = setup();
    const expired: unknown[] = [];
    chart.on('alert:expired', event => expired.push(event));
    const first = alerts.add(input({ expiresAt: 1002, policy: 'onTouch' }));
    const second = alerts.add(input({ expiresAt: 1003 }));
    expect(vi.getTimerCount()).toBe(1);
    vi.advanceTimersByTime(2000);
    expect(alerts.list().find(alert => alert.id === first.id)?.state).toBe('expired');
    expect(expired).toHaveLength(1);
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toEqual([]);
    alerts.disable(second.id);
    expect(vi.getTimerCount()).toBe(0);
    alerts.enable(second.id);
    expect(vi.getTimerCount()).toBe(1);
    chart.destroy();
    expect(vi.getTimerCount()).toBe(0);
    vi.advanceTimersByTime(20_000);
    expect(expired).toHaveLength(1);
    expect(() => alerts.add(input())).toThrow(/destroyed/i);
  });

  it('does not deliver during replay or against another instrument', () => {
    const { chart, alerts, series, fired } = setup();
    chart.setDataContext({ symbol: 'ONE', exchange: 'EX', interval: '1m' });
    alerts.add(input({ policy: 'onTouch', repeat: 'everyTime' }));
    chart.emit('replay:start', {});
    series.update({ ...bar(120, 99), high: 102 });
    chart.emit('replay:stop', {});
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toEqual([]);
    chart.setDataContext({ symbol: 'TWO', exchange: 'EX', interval: '1m' });
    series.update(bar(180, 99));
    series.update({ ...bar(180, 99), high: 103 });
    expect(fired).toEqual([]);
    chart.setDataContext({ symbol: 'ONE', exchange: 'EX', interval: '1m' });
    series.setData([bar(60, 99), bar(120, 99)]);
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toHaveLength(1);
  });

  it('keeps disable and update silent and requires a fresh post-enable touch', () => {
    const { alerts, series, fired } = setup();
    const alert = alerts.add(input({ policy: 'onTouch' }));
    alerts.disable(alert.id);
    series.update({ ...bar(120, 99), high: 102 });
    alerts.enable(alert.id);
    alerts.update(alert.id, { source: { kind: 'price', price: 101 }, title: 'Revised' });
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 103), high: 103 });
    expect(fired).toHaveLength(1);
    expect(fired[0].title).toBe('Revised');
    expect(fired[0].price).toBe(101);
  });

  it('commits once state before listeners run and skips an alert removed by a listener', () => {
    const { chart, alerts, series, fired } = setup();
    const first = alerts.add(input({ policy: 'onTouch' }));
    const second = alerts.add(input({ policy: 'onTouch' }));
    let stateAtDelivery: string | undefined;
    chart.on('alert:triggered', () => {
      stateAtDelivery = alerts.list().find(alert => alert.id === first.id)?.state;
      alerts.remove(second.id);
    });
    series.update({ ...bar(120, 99), high: 102 });
    expect(stateAtDelivery).toBe('triggered');
    expect(fired.map(event => event.alertId)).toEqual([first.id]);
    expect(alerts.list().map(alert => alert.id)).toEqual([first.id]);
  });

  it('does not trigger once again after a delivery listener throws', () => {
    const { chart, alerts, series, fired } = setup();
    alerts.add(input({ policy: 'onTouch' }));
    const off = chart.on('alert:triggered', () => { throw new Error('Host delivery failed'); });
    expect(() => series.update({ ...bar(120, 99), high: 102 })).not.toThrow();
    off();
    series.update({ ...bar(120, 99), high: 103 });
    expect(fired).toHaveLength(1);
    expect(alerts.list()[0].state).toBe('triggered');
  });

  it('rejects duplicate ids and invalid numeric conditions without changing existing alerts', () => {
    const { alerts } = setup();
    const original = alerts.add(input({ id: 'kept' }));
    expect(() => alerts.add(input({ id: 'kept' }))).toThrow(/id/i);
    for (const price of [NaN, Infinity]) expect(() => alerts.add(input({ source: { kind: 'price', price } }))).toThrow();
    for (const condition of ['enteringRange', 'leavingRange'] as AlertCondition[]) {
      expect(() => alerts.add(input({ condition }))).toThrow(/range|bound/i);
      expect(() => alerts.add(input({ condition, source: { kind: 'price', price: 100, upperPrice: 90 } }))).toThrow(/range|bound/i);
    }
    expect(() => alerts.update('kept', { cooldownSeconds: -1 })).toThrow();
    expect(alerts.list()).toEqual([original]);
    const copy = alerts.list()[0];
    if (copy.source.kind !== 'price') throw new Error('Expected price source');
    copy.source.price = 500;
    expect(alerts.list()[0].source).toEqual({ kind: 'price', price: 100 });
  });

  it('refuses duplicate controllers and tears down from a trigger callback', () => {
    const { chart, alerts, series, fired } = setup();
    expect(() => new AlertController(chart)).toThrow(/controller/i);
    alerts.add(input({ policy: 'onTouch' }));
    alerts.add(input({ policy: 'onTouch', expiresAt: 2000 }));
    chart.on('alert:triggered', () => chart.destroy());
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toHaveLength(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it('keeps an explicit host pause after replay stops and seeds on resume', () => {
    const { chart, alerts, series, fired } = setup();
    alerts.add(input({ policy: 'onTouch', repeat: 'everyTime' }));
    alerts.setPaused(true);
    chart.emit('replay:start', {});
    chart.emit('replay:stop', {});
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toEqual([]);
    alerts.setPaused(false);
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toEqual([]);
    series.update({ ...bar(120, 101), high: 102 });
    expect(fired).toHaveLength(1);
  });

  it('never redelivers a judged closed bar after a history replacement', () => {
    const { alerts, series, fired } = setup();
    alerts.add(input({ repeat: 'everyTime' }));
    series.update(bar(120, 101));
    series.update(bar(180, 99));
    expect(fired.map(event => event.time)).toEqual([120]);
    series.setData([bar(60, 99), bar(120, 101)]);
    series.update(bar(180, 99));
    expect(fired.map(event => event.time)).toEqual([120]);
    series.update(bar(240, 101));
    series.update(bar(300, 101));
    expect(fired.map(event => event.time)).toEqual([120, 240]);
  });

  it('never delivers an older touch after history moved behind a consumed bar', () => {
    const { alerts, series, fired } = setup();
    alerts.add(input({ policy: 'onTouch', repeat: 'everyTime' }));
    series.update({ ...bar(120, 99), high: 102 });
    series.update({ ...bar(180, 99), high: 102 });
    series.setData([bar(60, 99), bar(120, 99)]);
    series.update({ ...bar(120, 99), high: 103 });
    expect(fired.map(event => event.time)).toEqual([120, 180]);
  });

  it('uses the primary timeline when another series already extends the global axis', () => {
    const { chart, alerts, series, fired } = setup();
    const overlay = chart.addSeries('line');
    const events: unknown[] = [];
    chart.on('data:update', event => events.push(event));
    alerts.add(input());
    overlay.setData([bar(180, 20), bar(240, 20)]);
    expect(events).toEqual([]);
    series.update(bar(120, 101));
    series.update(bar(180, 101));
    expect(fired.map(event => event.time)).toEqual([120]);
    expect(events).toEqual([{ kind: 'update', time: 120 }, { kind: 'update', time: 180 }]);
    expect(chart.primaryBars()).toBe(chart.primaryBars());
    series.remove();
    expect(chart.primaryBars()).toEqual([]);
    expect(events[events.length - 1]).toEqual({ kind: 'reset' });
  });

  it('holds cooldown while the clock is behind the last delivery and expires before touching', () => {
    const { alerts, series, fired } = setup();
    const alert = alerts.add(input({ policy: 'onTouch', repeat: 'everyTime', cooldownSeconds: 10, expiresAt: 1020 }));
    series.update({ ...bar(120, 99), high: 102 });
    vi.setSystemTime(990_000);
    series.update({ ...bar(180, 99), high: 102 });
    expect(fired).toHaveLength(1);
    vi.setSystemTime(1_010_000);
    series.update({ ...bar(240, 99), high: 102 });
    expect(fired).toHaveLength(2);
    vi.setSystemTime(1_020_000);
    series.update({ ...bar(300, 99), high: 102 });
    expect(fired).toHaveLength(2);
    expect(alerts.list().find(item => item.id === alert.id)?.state).toBe('expired');
    expect(vi.getTimerCount()).toBe(0);
  });

  it('abandons stale evaluation after a trigger listener changes the data context', () => {
    const { chart, alerts, series, fired } = setup();
    alerts.add(input({ policy: 'onTouch' }));
    alerts.add(input({ policy: 'onTouch' }));
    chart.on('alert:triggered', () => chart.setDataContext({ symbol: 'CHANGED' }));
    series.update({ ...bar(120, 99), high: 102 });
    expect(fired).toHaveLength(1);
  });

  it('publishes the specified creation, update and removal events after committing state', () => {
    const { chart, alerts } = setup();
    const events: string[] = [];
    const counts: number[] = [];
    for (const name of ['alert:created', 'alert:updated', 'alert:removed']) {
      chart.on(name, () => { events.push(name); counts.push(alerts.list().length); });
    }
    const alert = alerts.add(input());
    alerts.disable(alert.id);
    alerts.remove(alert.id);
    expect(events).toEqual(['alert:created', 'alert:updated', 'alert:removed']);
    expect(counts).toEqual([1, 1, 0]);
  });
});
