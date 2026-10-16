import { afterEach, describe, expect, it } from 'vitest';
import { AlertController, Chart, PriceLine } from '../src/index';
import type { AlertTriggeredPayload, Bar } from '../src/index';
import { fakeDocument } from './helpers/fake-dom';
import { DrawingController } from '../src/draw/index';
import '../src/indicators/index';

const cleanup: Chart[] = [];
const bar = (time: number, close = 99): Bar => ({ time, open: close, high: close, low: close, close });
afterEach(() => { for (const chart of cleanup.splice(0)) chart.destroy(); });

function setup() {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  cleanup.push(chart);
  chart.applySize(800, 600);
  chart.setDataContext({ symbol: 'ONE', exchange: 'EX', interval: '5m' });
  const series = chart.addSeries('candlestick');
  series.setData([bar(0), bar(300), bar(600)]);
  const alerts = new AlertController(chart);
  const fired: AlertTriggeredPayload[] = [];
  chart.on('alert:triggered', payload => fired.push(payload as AlertTriggeredPayload));
  const switchTo = (interval: string, bars: Bar[], symbol = 'ONE', exchange = 'EX') => {
    series.setData([]);
    chart.setDataContext({ symbol, exchange, interval });
    series.setData(bars);
  };
  const lines = () => chart.panes().flatMap(pane => [...pane.primitives()])
    .filter((primitive): primitive is PriceLine => primitive instanceof PriceLine);
  return { chart, series, alerts, fired, switchTo, lines };
}

describe('alert timeframe visibility and evaluation', () => {
  it('keeps both price range bounds visible on another timeframe without reinterpreting the trigger', () => {
    const { chart, alerts, series, switchTo, lines, fired } = setup();
    const alert = alerts.add({ source: { kind: 'price', price: 100, upperPrice: 110 }, condition: 'enteringRange', title: 'Watched range' });
    switchTo('1m', [bar(720), bar(780), bar(840)]);
    expect(chart.exportSVG()).toContain('Watched range');
    expect(lines().map(line => line.price)).toEqual([100, 110]);
    expect(chart.exportSVG()).toContain('5m');
    expect(lines().every(line => line.options().badge?.includes('Paused'))).toBe(true);
    expect(lines().every(line => line.options().cursor === undefined)).toBe(true);
    expect(alerts.availability(alert.id)).toMatchObject({ available: false, reason: expect.stringContaining('5m') });
    series.update(bar(840, 105));
    series.update(bar(900, 105));
    expect(fired).toEqual([]);
    expect(alerts.list()[0].scope.interval).toBe('5m');
  });

  it.each([['TWO', 'EX'], ['ONE', 'OTHER']])('does not expose price levels for %s on %s', (symbol, exchange) => {
    const { chart, alerts, switchTo } = setup();
    alerts.add({ source: { kind: 'price', price: 100 }, title: 'Instrument-owned level' });
    switchTo('1m', [bar(720), bar(780)], symbol, exchange);
    expect(chart.exportSVG()).not.toContain('Instrument-owned level');
    expect(alerts.list()).toHaveLength(1);
  });

  it('resumes the next original-timeframe close after visiting finer bars', () => {
    const { alerts, series, switchTo, fired, lines } = setup();
    const alert = alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp' });
    switchTo('1m', [bar(720, 101), bar(780, 101), bar(840, 101)]);
    expect(alerts.list()[0].lastClosedTime).toBe(300);
    series.update(bar(900, 101));
    switchTo('5m', [bar(0), bar(300), bar(600)]);
    expect(fired).toEqual([]);
    expect(alerts.availability(alert.id)).toMatchObject({ available: true });
    expect(lines()[0].options().cursor).toBe('ns-resize');
    series.update(bar(600, 101));
    series.update(bar(900, 101));
    expect(fired.map(event => [event.alertId, event.time])).toEqual([[alert.id, 600]]);
  });

  it('restores a price alert on another timeframe without consuming foreign history', () => {
    const original = setup();
    const alert = original.alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp', title: 'Restored price' });
    const document = JSON.parse(JSON.stringify(original.alerts.toJSON()));
    const restored = setup();
    restored.switchTo('1m', [bar(720, 101), bar(780, 101), bar(840, 101)]);
    restored.alerts.fromJSON(document);
    expect(restored.chart.exportSVG()).toContain('Restored price');
    expect(restored.alerts.list()[0].lastClosedTime).toBe(300);
    expect(restored.fired).toEqual([]);
    restored.switchTo('5m', [bar(0), bar(300), bar(600)]);
    restored.series.update(bar(600, 101));
    restored.series.update(bar(900, 101));
    expect(restored.fired.map(event => event.alertId)).toEqual([alert.id]);
  });

  it('preserves visible lifecycle states and never rearms a triggered once alert on another timeframe', () => {
    const { chart, alerts, series, switchTo, lines, fired } = setup();
    const once = alerts.add({ source: { kind: 'price', price: 100 }, condition: 'crossingUp', title: 'Once level' });
    series.update(bar(600, 101));
    series.update(bar(900, 101));
    alerts.add({ source: { kind: 'price', price: 98 }, state: 'disabled' });
    alerts.add({ source: { kind: 'price', price: 96 }, expiresAt: 1 });
    switchTo('1m', [bar(960), bar(1020), bar(1080)]);
    alerts.fromJSON(JSON.parse(JSON.stringify(alerts.toJSON())));
    expect(chart.exportSVG()).toContain('Once level (5m)');
    expect(lines().map(line => line.options().badge)).toEqual(['Triggered', 'Disabled', 'Expired']);
    series.update(bar(1080, 101));
    expect(fired.map(event => event.alertId)).toEqual([once.id]);
    expect(alerts.list().map(alert => alert.state)).toEqual(['triggered', 'disabled', 'expired']);
  });

  it('keeps study and drawing evaluation on their source timeframe and cancels an unfinished price edit', () => {
    const { chart, alerts, series, switchTo, fired } = setup();
    alerts.destroy();
    const draw = new DrawingController(chart);
    const controller = new AlertController(chart, { drawings: draw });
    const study = chart.addIndicator('ema', { length: 1 });
    const drawing = draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 600, price: 100 }] });
    const price = controller.add({ source: { kind: 'price', price: 100 }, title: 'Price threshold' });
    controller.add({ source: { kind: 'indicator', instanceId: study.id, plotKey: 'ma', value: 100 }, title: 'Study threshold' });
    controller.add({ source: { kind: 'drawing', drawingId: drawing.id }, title: 'Drawing threshold' });
    chart.emit('drag:start', { id: `alert:${price.id}:0`, paneIndex: 0, price: 100 });
    chart.emit('drag', { id: `alert:${price.id}:0`, paneIndex: 0, price: 105 });
    switchTo('1m', [bar(720), bar(780), bar(840)]);
    chart.emit('drag:end', { id: `alert:${price.id}:0`, paneIndex: 0, price: 105 });
    expect(controller.list()[0].source).toEqual({ kind: 'price', price: 100 });
    const svg = chart.exportSVG();
    expect(svg).toContain('Price threshold (5m)');
    expect(svg).not.toContain('Study threshold');
    expect(svg).not.toContain('Drawing threshold');
    series.update(bar(840, 101));
    series.update(bar(900, 101));
    expect(fired).toEqual([]);
    expect(controller.list()).toHaveLength(3);
    draw.destroy();
  });
});
