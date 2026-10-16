import { afterEach, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });
function rig() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
  charts.push(chart);
  chart.applySize(800, 500);
  chart.addSeries('candlestick').setData(Array.from({ length: 10 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 10, high: 12, low: 9, close: 11,
  })));
  chart.setVisibleLogicalRange({ from: -1, to: 12 });
  return chart;
}
it('publishes linked readings to multiple observers without replacing the host callback or moving the pointer', () => {
  const chart = rig();
  const host = vi.fn(), first = vi.fn(), second = vi.fn(), pointerMove = vi.fn();
  chart.subscribeCrosshairMove(host);
  chart.on('crosshair:readout', first);
  const off = chart.on('crosshair:readout', second);
  chart.on('crosshair:move', pointerMove);
  chart.setLinkedCrosshairIndex(2);
  expect(first).toHaveBeenCalledWith(expect.objectContaining({ source: 'linked', time: 1700000120 }));
  expect(second).toHaveBeenCalledTimes(1);
  expect(host).toHaveBeenCalledTimes(1);
  expect(pointerMove).not.toHaveBeenCalled();
  off();
  chart.setLinkedCrosshairIndex(null);
  expect(first).toHaveBeenLastCalledWith(expect.objectContaining({ time: null, bar: null }));
  expect(second).toHaveBeenCalledTimes(1);
});
it('publishes physical readings when only the readout bus has observers', () => {
  const chart = rig(), listener = vi.fn();
  chart.on('crosshair:readout', listener);
  const x = chart.timeToCoordinate(1700000180)!;
  (chart as unknown as { _onPointerMove(e: unknown): void })._onPointerMove(pointer('move', x, 200, { buttons: 0 }));
  expect(listener).toHaveBeenCalledWith(expect.objectContaining({ time: 1700000180 }));
});
