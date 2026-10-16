import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { indicatorDefaults, registerIndicator } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { VOLUME } from '../src/indicators/volume';
import { fakeDocument } from './helpers/fake-dom';

registerIndicator(VOLUME);
const bars: Bar[] = [10, 20, 30, 60].map((volume, i) => ({
  time: 1735689600 + i * 60, open: 100, high: 105, low: 95,
  close: [102, 98, 100, 104][i], volume,
}));
const charts: Chart[] = [];
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

function mount(settings: Record<string, unknown> = {}) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel() {} },
  });
  charts.push(chart);
  chart.applySize(800, 600);
  const price = chart.addSeries('candlestick');
  price.setData(bars);
  const study = chart.addIndicator('volume', settings);
  return { chart, price, study };
}

describe('volume study', () => {
  it('preserves the existing histogram and leaves the average off by default', () => {
    const { study } = mount();
    expect(study.values().volume).toEqual([10, 20, 30, 60]);
    expect(study.values().ma).toEqual([null, null, null, null]);
    expect(study.series('volume')!.getData().every(b => b.color === undefined)).toBe(true);
    expect(indicatorDefaults(VOLUME).showMA).toBe(false);
  });

  it('warms up for a full period and corrects live replacements and appends', () => {
    const { price, study } = mount({ showMA: true, maPeriod: 3 });
    expect(study.values().ma.slice(0, 3)).toEqual([null, null, 20]);
    expect(study.values().ma[3]).toBeCloseTo(110 / 3);
    price.update({ ...bars[3], volume: 90 });
    expect(study.values().ma[3]).toBeCloseTo(140 / 3);
    price.update({ ...bars[3], time: bars[3].time + 60, volume: 120 });
    expect(study.values().ma[4]).toBe(80);
    study.setSettings({ maPeriod: 2 });
    expect(study.values().ma).toEqual([null, 15, 25, 60, 105]);
    study.setSettings({ showMA: false });
    expect(study.values().ma).toEqual([null, null, null, null, null]);
  });

  it('follows candle direction, treats dojis as up, and recolours existing bars', () => {
    const { price, study } = mount({ colorByDirection: true, upColor: '#00aa00', downColor: '#aa0000' });
    const colors = () => study.series('volume')!.getData().map(b => b.color);
    expect(colors()).toEqual(['#00aa00', '#aa0000', '#00aa00', '#00aa00']);
    price.update({ ...bars[3], close: 96 });
    expect(colors()[3]).toBe('#aa0000');
    study.setSettings({ upColor: '#11bb11', downColor: '#bb1111' });
    expect(colors()).toEqual(['#11bb11', '#bb1111', '#11bb11', '#bb1111']);
    study.setSettings({ colorByDirection: false });
    expect(colors()).toEqual([undefined, undefined, undefined, undefined]);
  });

  it('shares the volume scale and keeps replay-prefix calculations free of later bars', () => {
    const { price, study } = mount({ showMA: true, maPeriod: 2 });
    expect(study.series('ma')).toBeDefined();
    expect(study.series('ma')!.priceScale()).toBe(study.series('volume')!.priceScale());
    price.setData(bars.slice(0, 2));
    expect(study.values().ma).toEqual([null, 15]);
    expect(study.series('ma')!.getData()).toHaveLength(2);
  });

  it('treats missing volume as zero and normalizes the averaging period', () => {
    const { price, study } = mount({ showMA: true, maPeriod: 0 });
    price.setData([{ ...bars[0], volume: undefined }, bars[1]]);
    expect(study.values().volume).toEqual([0, 20]);
    expect(study.values().ma).toEqual([0, 20]);
    study.setSettings({ maPeriod: 2.2 });
    expect(study.values().ma).toEqual([null, 10]);
  });
});
