import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { getChartType } from '../src/model/chart-type-registry';
import { registerIndicator } from '../src/model/indicator-registry';
import type { SeriesStyle } from '../src/render/series-style';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
const makeChart = () => {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, shortcuts: false, raf: { schedule: () => 0 },
  });
  chart.applySize(800, 500);
  charts.push(chart);
  return chart;
};

describe('live series style snapshots', () => {
  it('captures renderer defaults and direct updates without exposing mutable style state', () => {
    const chart = makeChart();
    const series = chart.addSeries('line', { style: { barOffset: 2, color: '#00ccff' } });
    series.setData([{ time: 60, value: 10 }, { time: 120, value: 20 }]);
    const before = chart.seriesStyle(series)!;
    expect(before).toMatchObject({ ...getChartType('line').defaultStyle, barOffset: 2, color: '#00ccff' });
    expect(Object.isFrozen(before)).toBe(true);
    expect(() => { (before as SeriesStyle).barOffset = 99; }).toThrow(TypeError);
    series.applyOptions({ barOffset: -1.5, visible: false });
    expect(chart.seriesStyle(series)).toMatchObject({ barOffset: -1.5, visible: false });
    expect(before.barOffset).toBe(2);
    chart.setSeriesType(series, 'candlestick');
    expect(chart.seriesStyle(series)).toMatchObject({ barOffset: -1.5, color: '#00ccff', visible: false });
    expect(chart.seriesStyle(series)?.upColor).toBe(getChartType('candlestick').defaultStyle?.upColor);
    expect(series.getData().map(bar => bar.close)).toEqual([10, 20]);
  });

  it('returns null for foreign, removed and destroyed handles', () => {
    const chart = makeChart(), other = makeChart();
    const series = chart.addSeries('line');
    expect(other.seriesStyle(series)).toBeNull();
    series.remove();
    expect(chart.seriesStyle(series)).toBeNull();
    const live = chart.addSeries('line', { style: { barOffset: 7 } });
    chart.destroy();
    expect(chart.seriesStyle(live)).toBeNull();
  });

  it('reports actual study plot offsets after direct overrides and resource removal', () => {
    registerIndicator({
      id: 'style-snapshot-study', name: 'Offset study', placement: 'pane', inputs: [],
      plots: [{ key: 'value', title: 'Value', type: 'line', offset: 2, style: { color: '#ff9900' } }],
      calc: bars => ({ value: bars.map(bar => bar.close) }),
    });
    const chart = makeChart();
    chart.addSeries('line').setData([{ time: 60, value: 10 }, { time: 120, value: 20 }]);
    const study = chart.addIndicator('style-snapshot-study');
    const series = study.series('value')!;
    expect(chart.seriesStyle(series)?.barOffset).toBe(2);
    series.applyOptions({ barOffset: 4.5 });
    expect(chart.seriesStyle(series)?.barOffset).toBe(4.5);
    expect(study.values().value).toEqual([10, 20]);
    study.remove();
    expect(chart.seriesStyle(series)).toBeNull();
  });
});
