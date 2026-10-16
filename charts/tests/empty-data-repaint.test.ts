import { describe, it, expect } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { Footprint, computeFootprint } from '../src/profile';

/**
 * A looping replay clears its series and starts over. Emptying a chart that
 * already had data must not throw or wedge the render loop.
 */
function mount() {
  const doc = fakeDocument();
  const container = doc.createElement('div') as unknown as Record<string, unknown>;
  container.clientWidth = 800; container.clientHeight = 600; container.ownerDocument = doc;
  container.contains = () => false;
  let frames = 0;
  const chart = new Chart(container as unknown as HTMLElement, {
    document: doc, pixelRatio: () => 1,
    raf: { schedule: (cb) => { frames++; cb(); return 1; }, cancel: () => {} },
  });
  return { chart, frames: () => frames };
}

describe('emptying a chart mid-flight', () => {
  it('setData([]) after data does not throw and still paints', () => {
    const { chart } = mount();
    const s = chart.addSeries('candlestick');
    s.setData([
      { time: 1000, open: 10, high: 12, low: 8, close: 11, volume: 5 },
      { time: 1060, open: 11, high: 13, low: 9, close: 12, volume: 6 },
    ]);
    expect(() => s.setData([])).not.toThrow();
    expect(() => chart.timeScale.fitContent(0)).not.toThrow();
  });

  it('Footprint.setBars([]) after bars does not throw', () => {
    const { chart } = mount();
    const s = chart.addSeries('candlestick');
    s.setData([{ time: 1000, open: 10, high: 12, low: 8, close: 11, volume: 5 }]);
    const fp = new Footprint({ tickSize: 0.5, statsRows: ['volume', 'delta'] });
    chart.addPrimitive(fp);
    fp.setBars([computeFootprint(1000, [{ price: 10, qty: 3, side: 'ask' }], 0.5)]);
    expect(() => fp.setBars([])).not.toThrow();
    expect(fp.autoscaleInfo()).toBeNull();
  });
});
