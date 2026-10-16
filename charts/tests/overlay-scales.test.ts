import { describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

function makeChart(): Chart {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false,
    pixelRatio: () => 1, raf: { schedule: callback => { callback(); return 1; }, cancel: () => {} } });
  chart.applySize(800, 600);
  chart.addSeries('line').setData([{ time: 1, value: 100 }, { time: 2, value: 110 }]);
  return chart;
}

describe('keyed hidden price scales', () => {
  it('keeps differently priced sources independent of each other and both axes', () => {
    const chart = makeChart();
    const a = chart.addSeries('line', { priceScaleId: 'overlay:a' });
    const b = chart.addSeries('line', { priceScaleId: 'overlay:b' });
    a.setData([{ time: 1, value: 1000 }, { time: 2, value: 1100 }]);
    b.setData([{ time: 1, value: 100000 }, { time: 2, value: 110000 }]);
    const pane = chart.panes()[0];
    expect(a.priceScale()).not.toBe(b.priceScale());
    expect(a.priceScale()).not.toBe(pane.priceScale);
    expect(pane.hasLeftScale()).toBe(false);
    expect(a.priceScale().priceToY(1100)).toBeCloseTo(b.priceScale().priceToY(110000), 6);
    expect(pane.axisScales()).toHaveLength(1);
    expect(pane.scales()).toHaveLength(3);
    expect(chart.priceAxisState(0, 'overlay:a')?.movable).toBe(false);
    chart.destroy();
  });

  it('shares an explicitly reused key and releases it after the last source leaves', () => {
    const chart = makeChart();
    const a = chart.addSeries('line', { priceScaleId: 'overlay:shared' });
    const b = chart.addSeries('line', { priceScaleId: 'overlay:shared' });
    expect(a.priceScale()).toBe(b.priceScale());
    expect(chart.panes()[0].scales()).toHaveLength(2);
    a.remove();
    expect(chart.panes()[0].scales()).toHaveLength(2);
    b.remove();
    expect(chart.panes()[0].scales()).toHaveLength(1);
    for (let index = 0; index < 40; index++) {
      chart.addSeries('line', { priceScaleId: `overlay:${index}` }).remove();
    }
    expect(chart.panes()[0].scales()).toHaveLength(1);
    chart.destroy();
  });

  it('retains the scale id in host-owned series state and updates height on resize', () => {
    const chart = makeChart();
    const source = chart.addSeries('line', { priceScaleId: 'overlay:source' });
    source.setData([{ time: 1, value: 2 }, { time: 2, value: 3 }]);
    expect(chart.getState().series?.[1]?.priceScaleId).toBe('overlay:source');
    chart.applySize(1000, 900);
    expect(source.priceScale().height).toBe(chart.panes()[0].priceScale.height);
    chart.setPriceScaleOptions({ minPrecision: 4 }, 'all');
    expect(source.priceScale().options.minPrecision).toBe(4);
    chart.destroy();
  });
});
