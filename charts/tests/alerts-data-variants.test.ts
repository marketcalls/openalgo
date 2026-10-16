import { afterEach, describe, expect, it } from 'vitest';
import { AlertController, Chart, PriceLine, parseAlertsDocument, publishDataContext } from '../src/index';
import type { AlertTriggeredPayload, Bar, DataVariant } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';

// An alert belongs to the series it was set on. Extended hours, raw prices or
// another currency are other series of the same instrument: their ticks are
// not the ones the alert was set against, so it waits for its own series the
// way it waits for its own timeframe.

const cleanup: Chart[] = [];
const bar = (time: number, close = 99): Bar => ({ time, open: close, high: close, low: close, close });
afterEach(() => { for (const chart of cleanup.splice(0)) chart.destroy(); });

function setup(variant?: DataVariant) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  cleanup.push(chart);
  chart.applySize(800, 600);
  publishDataContext(chart, { symbol: 'ONE', exchange: 'EX', interval: '5m', variant });
  const series = chart.addSeries('candlestick');
  series.setData([bar(0), bar(300), bar(600)]);
  const alerts = new AlertController(chart);
  const fired: AlertTriggeredPayload[] = [];
  chart.on('alert:triggered', payload => fired.push(payload as AlertTriggeredPayload));
  const switchTo = (next: DataVariant | undefined, bars: Bar[]) => {
    series.setData([]);
    publishDataContext(chart, { symbol: 'ONE', exchange: 'EX', interval: '5m', variant: next });
    series.setData(bars);
  };
  const lines = () => chart.panes().flatMap(pane => [...pane.primitives()])
    .filter((primitive): primitive is PriceLine => primitive instanceof PriceLine);
  return { chart, series, alerts, fired, switchTo, lines };
}

describe('alerts and data variants', () => {
  it('keeps the scope of an alert on the default series exactly as it was', () => {
    const { chart, alerts } = setup();
    const alert = alerts.add({ source: { kind: 'price', price: 100 } });
    expect(alert.scope).toEqual({ symbol: 'ONE', exchange: 'EX', interval: '5m' });
    expect(Object.keys(alerts.toJSON().alerts[0].scope)).toEqual(['symbol', 'exchange', 'interval']);
    // A host that names the default as {} directly on the chart gets the same scope.
    chart.setDataContext({ symbol: 'TWO', exchange: 'EX', interval: '5m', variant: {} });
    expect(Object.keys(alerts.add({ source: { kind: 'price', price: 100 } }).scope)).toEqual(['symbol', 'exchange', 'interval']);
    // One the chart was handed malformed cannot be named, so no alert is set on it.
    chart.setDataContext({ symbol: 'THREE', exchange: 'EX', interval: '5m', variant: { session: 'overnight' } as never });
    expect(() => alerts.add({ source: { kind: 'price', price: 100 } })).toThrow(/alert scope/);
    expect(alerts.list()).toHaveLength(2);
  });

  it('evaluates an alert only on the series it was set on', () => {
    const { alerts, series, switchTo, fired, lines } = setup({ session: 'extended' });
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp', title: 'Extended level' });
    expect(alert.scope).toEqual({ symbol: 'ONE', exchange: 'EX', interval: '5m', variant: { session: 'extended' } });
    // The regular session crosses the level; the alert was not set on it.
    switchTo(undefined, [bar(0), bar(300), bar(600)]);
    series.update(bar(600, 101));
    series.update(bar(900, 101));
    expect(fired).toEqual([]);
    expect(alerts.availability(alert.id)).toMatchObject({ available: false, reason: expect.stringContaining('data variant') });
    // A session does not change what a price means, so the level stays in view, paused.
    expect(lines().map(line => line.price)).toEqual([100]);
    expect(lines()[0].options().badge).toContain('Paused');
    // Back on its own series it resumes with the next close, without replaying the visit.
    switchTo({ session: 'extended' }, [bar(0), bar(300), bar(600)]);
    expect(alerts.availability(alert.id)).toMatchObject({ available: true });
    series.update(bar(600, 101));
    series.update(bar(900, 101));
    expect(fired.map(event => [event.alertId, event.time])).toEqual([[alert.id, 600]]);
  });

  it('shows a fixed level only where its prices are quoted the same way', () => {
    const { chart, alerts, switchTo } = setup({ currency: 'USD' });
    alerts.add({ source: { kind: 'price', price: 100 }, title: 'Dollar level' });
    // The same number in another currency is another price.
    switchTo({ currency: 'EUR' }, [bar(0), bar(300)]);
    expect(chart.exportSVG()).not.toContain('Dollar level');
    // Another session of the same quote keeps it, labelled with where it evaluates.
    switchTo({ currency: 'USD', session: 'extended' }, [bar(0), bar(300)]);
    expect(chart.exportSVG()).toContain('Dollar level (5m, USD)');
    switchTo({ currency: 'USD' }, [bar(0), bar(300)]);
    expect(chart.exportSVG()).toContain('Dollar level');
    expect(chart.exportSVG()).not.toContain('Dollar level (');
  });

  it('reads a variant from a saved document and refuses one it cannot name', () => {
    const record = (scope: unknown) => ({ version: 1, alerts: [{ id: 'a', source: { kind: 'price', price: 100 }, scope }] });
    expect(parseAlertsDocument(record({ symbol: 'ONE', variant: { session: 'extended' } })).alerts[0].scope)
      .toEqual({ symbol: 'ONE', variant: { session: 'extended' } });
    expect(parseAlertsDocument(record({ symbol: 'ONE' })).alerts[0].scope).toEqual({ symbol: 'ONE' });
    for (const variant of [{ session: 'overnight' }, 'extended', { region: 'US' }]) {
      expect(() => parseAlertsDocument(record({ symbol: 'ONE', variant })), JSON.stringify(variant)).toThrow(/alert scope/);
    }
  });

  it('restores an alert saved on another series without evaluating it here', () => {
    const original = setup({ adjustment: 'raw' });
    const alert = original.alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp' });
    const saved = JSON.parse(JSON.stringify(original.alerts.toJSON()));
    const restored = setup();
    restored.alerts.fromJSON(saved);
    restored.series.update(bar(600, 101));
    restored.series.update(bar(900, 101));
    expect(restored.fired).toEqual([]);
    expect(restored.alerts.availability(alert.id).available).toBe(false);
  });
});
