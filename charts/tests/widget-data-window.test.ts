import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { readDataWindow, mountDataWindow } from '../src/widget/data-window';
import type { WidgetContext } from '../src/widget/context';
import { fakeWidgetDocument, fakeContainer, type FakeElement } from './helpers/fake-dom-widget';

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });
function rig() {
  const doc = fakeWidgetDocument(), root = fakeContainer(doc);
  const chart = new Chart(root as unknown as HTMLElement, { document: doc as unknown as Document,
    shortcuts: false, pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.setDataContext({ symbol: 'TEST', exchange: 'NFO', interval: '1m' });
  const series = chart.addSeries('candlestick');
  series.setData([
    { time: 1700000000, open: 10, high: 12, low: 9, close: 11, volume: 0, oi: 0 },
    { time: 1700000060, open: 11, high: 13, low: 10, close: 12 },
  ]);
  const ctx = { chart, document: doc, root, locale: 'en-US' } as unknown as WidgetContext;
  return { chart, series, ctx, doc, root };
}
const value = (snapshot: ReturnType<typeof readDataWindow>, key: string): string | undefined =>
  snapshot.sections.flatMap(section => section.rows).find(row => row.key === key)?.value;

describe('data window readings', () => {
  it('distinguishes zero volume and OI from absent readings on the live bar', () => {
    const { chart } = rig();
    const old = readDataWindow(chart, 1700000000);
    expect(value(old, 'volume')).toBe('0');
    expect(value(old, 'oi')).toBe('0');
    const live = readDataWindow(chart);
    expect(value(live, 'volume')).toBe('Unavailable');
    expect(value(live, 'oi')).toBe('Unavailable');
    expect(live.time).toBe(1700000060);
  });
  it('leaves gaps empty instead of displaying the latest candle under a missing timestamp', () => {
    const { chart } = rig();
    const snapshot = readDataWindow(chart, 1700000030);
    expect(snapshot.time).toBe(1700000030);
    expect(value(snapshot, 'close')).toBe('Unavailable');
  });
  it('honors explicit absence of open interest on cash instruments', () => {
    const { chart } = rig();
    chart.setDataContext({ symbol: 'CASH', exchange: 'NSE', interval: '1m', hasOpenInterest: false });
    expect(value(readDataWindow(chart, 1700000000), 'oi')).toBeUndefined();
  });
  it('uses the primary source formatter for price readings', () => {
    const { chart, series } = rig();
    series.priceScale().setPriceFormatter(price => `Q${price}`);
    expect(value(readDataWindow(chart), 'close')).toBe('Q12');
  });
  it('uses plot labels and custom formatting, keeps duplicate study instances and never reports NaN', () => {
    const { chart } = rig();
    registerIndicator({ id: 'window-study', name: 'Window study', placement: 'pane', inputs: [],
      plots: [{ key: 'a', title: 'Signal', type: 'line', priceFormat: { type: 'custom', formatter: n => `${n} units` } }],
      calc: () => ({ a: [4, NaN] }) });
    const a = chart.addIndicator('window-study'), b = chart.addIndicator('window-study');
    const snapshot = readDataWindow(chart, 1700000000);
    expect(snapshot.sections.filter(s => s.id === a.id || s.id === b.id)).toHaveLength(2);
    expect(value(snapshot, `${a.id}:a`)).toBe('4 units');
    expect(value(readDataWindow(chart), `${a.id}:a`)).toBe('Unavailable');
  });
  it('reads the value painted by a shifted plot and the close column of a candle plot', () => {
    const { chart } = rig();
    registerIndicator({ id: 'window-shift', name: 'Shifted study', placement: 'pane', inputs: [],
      plots: [
        { key: 'signal', title: 'Signal', type: 'line', offset: 1 },
        { key: 'candle', title: 'Candle close', type: 'candlestick', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
      ], calc: () => ({ signal: [4, 8], o: [1, 2], h: [3, 4], l: [0, 1], c: [2, 3] }) });
    const study = chart.addIndicator('window-shift');
    expect(value(readDataWindow(chart), `${study.id}:signal`)).toBe('4');
    expect(value(readDataWindow(chart), `${study.id}:candle`)).toBe('3');
    expect(value(readDataWindow(chart, 1700000000), `${study.id}:signal`)).toBe('Unavailable');
  });
  it('updates the timestamp on timezone change without recopying history on hover', async () => {
    const r = rig(), host = r.doc.createElement('div'); r.root.appendChild(host);
    const getData = vi.spyOn(r.series, 'getData');
    const panel = mountDataWindow(r.ctx, host as unknown as HTMLElement);
    const calls = getData.mock.calls.length;
    r.chart.setLinkedCrosshairIndex(0); await Promise.resolve();
    r.chart.setLinkedCrosshairIndex(1); await Promise.resolve();
    expect(getData.mock.calls.length).toBe(calls);
    r.chart.setTimezone('UTC'); await Promise.resolve();
    expect(host.textContent).toContain('(UTC)');
    panel.destroy();
  });
  it('updates from linked readings, data and context and detaches on destruction', async () => {
    const r = rig(), host = r.doc.createElement('div'); r.root.appendChild(host);
    const panel = mountDataWindow(r.ctx, host as unknown as HTMLElement);
    r.chart.setLinkedCrosshairIndex(0); await Promise.resolve();
    expect((panel.el as unknown as FakeElement).textContent).toContain('10.00');
    r.chart.setDataContext({ symbol: 'NEW', exchange: 'NSE', interval: '1m' });
    r.series.setData([]); await Promise.resolve();
    expect(host.textContent).toContain('NEW');
    expect(host.textContent).not.toContain('10.00');
    panel.destroy();
    r.series.setData([{ time: 1700000060, open: 3, high: 4, low: 2, close: 3 }]);
    await Promise.resolve();
    expect(host.textContent).toBe('');
  });
});
