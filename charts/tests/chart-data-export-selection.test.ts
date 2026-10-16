import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { exportChartDataCsv, type ChartDataCsvOptions } from '../src/model/chart-data-export';
import { registerIndicator } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';
import '../src/indicators/index';

const cleanup: (() => void)[] = [];
afterEach(() => {
  vi.restoreAllMocks();
  for (const dispose of cleanup.splice(0).reverse()) dispose();
});
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
const header = 'time,open,high,low,close,volume,oi';
function setup(data: Bar[] = [bar(-0.25, 1), bar(0.125, 3), bar(0.25, 5), bar(0.375, 7)]) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, raf: { schedule: () => 0 }, shortcuts: false });
  cleanup.push(() => chart.destroy());
  chart.applySize(800, 600);
  const series = chart.addSeries('candlestick');
  series.setData(data);
  return { chart, series, data };
}
function unreadChart() {
  const primaryBars = vi.fn(() => { throw new Error('unexpected primary read'); });
  const indicators = vi.fn(() => { throw new Error('unexpected indicator read'); });
  return { chart: { primaryBars, indicators } as unknown as Chart, primaryBars, indicators };
}
const unsafe = (value: unknown): ChartDataCsvOptions => value as ChartDataCsvOptions;

describe('selected chart data CSV', () => {
  it('exports explicit instance order including hidden instances with repeated names', () => {
    const { chart } = setup();
    const fast = chart.addIndicator('sma', { length: 1 });
    const slow = chart.addIndicator('sma', { length: 2 });
    slow.setVisible(false);
    const csv = exportChartDataCsv(chart, { indicators: [slow.id, fast.id], range: { from: 0.125, to: 0.25 } });
    expect(csv).toBe(`${header},indicator:${slow.id}:ma,indicator:${fast.id}:ma\r\n`
      + '0.125,3,4,2,3,,,2,3\r\n0.25,5,6,4,5,,,4,5\r\n');
  });

  it('filters inclusive fractional and negative UTC times after full-history warmup', () => {
    const { chart } = setup();
    const study = chart.addIndicator('sma', { length: 3 });
    const prefix = `${header},indicator:${study.id}:ma\r\n`;
    expect(exportChartDataCsv(chart, { indicators: [study.id], range: { from: 0.25, to: 0.375 } }))
      .toBe(prefix + '0.25,5,6,4,5,,,3\r\n0.375,7,8,6,7,,,5\r\n');
    expect(exportChartDataCsv(chart, { range: { from: -0.25, to: -0.25 } }))
      .toBe(prefix + '-0.25,1,2,0,1,,,\r\n');
    expect(exportChartDataCsv(chart, { range: { to: -0.125 } }))
      .toBe(prefix + '-0.25,1,2,0,1,,,\r\n');
    expect(exportChartDataCsv(chart, { range: { from: 0.375 } }))
      .toBe(prefix + '0.375,7,8,6,7,,,5\r\n');
  });

  it('retains default bytes with true, undefined and empty unrestricted ranges', () => {
    const { chart } = setup();
    chart.addIndicator('sma', { length: 2 }).setVisible(false);
    const baseline = exportChartDataCsv(chart);
    expect(exportChartDataCsv(chart, { indicators: true })).toBe(baseline);
    expect(exportChartDataCsv(chart, { indicators: undefined, range: {} })).toBe(baseline);
    expect(exportChartDataCsv(chart, { range: { from: undefined, to: undefined } })).toBe(baseline);
    expect(exportChartDataCsv(chart, { range: Object.create(null) })).toBe(baseline);
  });

  it.each([{ indicators: false }, { indicators: [] }] as const)('does not read studies when selection is $indicators', ({ indicators }) => {
    const { chart } = setup();
    const study = chart.addIndicator('sma', { length: 2 });
    const list = vi.spyOn(chart, 'indicators');
    const values = vi.spyOn(study, 'values');
    const sample = vi.fn((time: number) => bar(time, 20));
    const csv = exportChartDataCsv(chart, { indicators, range: { from: 0.25 }, comparisons: [{ symbol: 'OTHER', barAt: sample }] });
    expect(csv).toBe(`${header},comparison:1:OTHER:close\r\n0.25,5,6,4,5,,,20\r\n0.375,7,8,6,7,,,20\r\n`);
    expect(list).not.toHaveBeenCalled();
    expect(values).not.toHaveBeenCalled();
    expect(sample.mock.calls).toEqual([[0.25], [0.375]]);
  });

  it('returns only the selected header for a nonoverlap or an empty installed history', () => {
    const { chart, series } = setup();
    const first = chart.addIndicator('sma', { length: 2 });
    const second = chart.addIndicator('ema', { length: 2 });
    const options = { indicators: [second.id], range: { from: 1, to: 2 } };
    const values = vi.spyOn(first, 'values');
    expect(exportChartDataCsv(chart, options)).toBe(`${header},indicator:${second.id}:ma\r\n`);
    expect(values).not.toHaveBeenCalled();
    series.setData([]);
    expect(exportChartDataCsv(chart, options)).toBe(`${header},indicator:${second.id}:ma\r\n`);
  });

  it('flushes same-turn dependencies without exporting the unselected producer', () => {
    const { chart, series } = setup();
    const producer = chart.addIndicator('sma', { length: 2 });
    const consumer = chart.addIndicator('sma', { length: 2, source: { kind: 'indicator', instanceId: producer.id, plotKey: 'ma' } });
    series.update(bar(0.375, 11));
    expect(exportChartDataCsv(chart, { indicators: [consumer.id], range: { from: 0.375 } }))
      .toBe(`${header},indicator:${consumer.id}:ma\r\n0.375,11,12,10,11,,,6\r\n`);
  });

  it('exports only the installed replay prefix despite a range beyond its boundary', () => {
    const { chart, series, data } = setup();
    const study = chart.addIndicator('sma', { length: 2 });
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 1 });
    cleanup.push(() => replay.stop());
    expect(exportChartDataCsv(chart, { indicators: [study.id], range: { from: 0.125, to: 10 } }))
      .toBe(`${header},indicator:${study.id}:ma\r\n0.125,3,4,2,3,,,2\r\n`);
    expect(chart.primaryBars()).toHaveLength(2);
  });

  it('snapshots source rows and accepted selected arrays before comparison callbacks', () => {
    const { chart, series } = setup([bar(1, 2), bar(2, 4)]);
    const study = chart.addIndicator('sma', { length: 1 });
    const accepted = study.values().ma;
    const csv = exportChartDataCsv(chart, { indicators: [study.id], comparisons: [{ symbol: 'OTHER', barAt: time => {
      (accepted as (number | null)[])[1] = 999;
      series.update(bar(2, 90));
      return bar(time, 7);
    } }] });
    expect(csv).toBe(`${header},indicator:${study.id}:ma,comparison:1:OTHER:close\r\n1,2,3,1,2,,,2,7\r\n2,4,5,3,4,,,4,7\r\n`);
  });

  it('rejects source replacement during accepted-value reads rather than mixing histories', () => {
    const { chart, series } = setup();
    const study = chart.addIndicator('sma', { length: 1 });
    const accepted = study.values();
    vi.spyOn(study, 'values').mockImplementation(() => { series.setData([bar(9, 99)]); return accepted; });
    expect(() => exportChartDataCsv(chart, { indicators: [study.id] })).toThrow(/changed|stable|snapshot/i);
  });

  it('rejects primary mutation inside the initial native calculation flush', () => {
    const { chart, series } = setup();
    let mutate = false;
    registerIndicator({ id: 'csv-selection-mutating', name: 'Selection mutation', placement: 'onchart', inputs: [],
      plots: [{ key: 'value', type: 'line', title: 'Value' }], calc: data => {
        if (mutate) { mutate = false; series.setData([bar(9, 99)]); }
        return { value: data.map(item => item.close) };
      } });
    const study = chart.addIndicator('csv-selection-mutating');
    series.update(bar(0.375, 8));
    mutate = true;
    expect(() => exportChartDataCsv(chart, { indicators: [study.id] })).toThrow(/changed|stable|snapshot/i);
  });

  it('retains raw declared plot keys and order without expanding a candle calculation', () => {
    registerIndicator({ id: 'csv-selection-candle', name: 'Selected candle', placement: 'onchart', inputs: [],
      plots: [{ key: 'constructor', type: 'candlestick', title: 'Candle', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
        { key: 'scalar', type: 'line', title: 'Scalar' }],
      calc: () => ({ o: [1], h: [3], l: [0], c: [2], scalar: [7] }) });
    const { chart } = setup([bar(1, 2)]);
    const study = chart.addIndicator('csv-selection-candle');
    expect(exportChartDataCsv(chart, { indicators: Object.freeze([study.id]) }))
      .toBe(`${header},indicator:${study.id}:constructor,indicator:${study.id}:scalar\r\n1,2,3,1,2,,,,7\r\n`);
  });

  it('detaches validated IDs and bounds before invoking native calculations', () => {
    const { chart, series } = setup();
    const first = chart.addIndicator('sma', { length: 1 });
    const second = chart.addIndicator('sma', { length: 2 });
    const ids = [second.id];
    const range = { from: 0.25, to: 0.25 };
    const list = chart.indicators.bind(chart);
    vi.spyOn(chart, 'indicators').mockImplementation(() => {
      ids[0] = first.id; range.from = -2; range.to = 9;
      return list();
    });
    series.update(bar(0.375, 11));
    expect(exportChartDataCsv(chart, { indicators: ids, range }))
      .toBe(`${header},indicator:${second.id}:ma\r\n0.25,5,6,4,5,,,4\r\n`);
  });
});

describe('CSV selection and range validation', () => {
  it.each([null, 0, 'sma', {}, [1], [''], [' '], new Array(1)].map(indicators => ({ indicators })))('rejects malformed selectors before any chart read (%#)', ({ indicators }) => {
    const fixture = unreadChart();
    expect(() => exportChartDataCsv(fixture.chart, unsafe({ indicators }))).toThrow(TypeError);
    expect(fixture.primaryBars).not.toHaveBeenCalled();
    expect(fixture.indicators).not.toHaveBeenCalled();
  });

  it('rejects duplicate instance IDs before any chart read', () => {
    const fixture = unreadChart();
    expect(() => exportChartDataCsv(fixture.chart, { indicators: ['same', 'same'] })).toThrow(RangeError);
    expect(fixture.primaryBars).not.toHaveBeenCalled();
    expect(fixture.indicators).not.toHaveBeenCalled();
  });

  it('rejects unknown, descriptor and removed instance IDs before reading values', () => {
    const { chart } = setup();
    const kept = chart.addIndicator('sma', { length: 1 });
    const removed = chart.addIndicator('sma', { length: 2 });
    removed.remove();
    const values = vi.spyOn(kept, 'values');
    for (const id of ['missing', 'sma', removed.id]) {
      expect(() => exportChartDataCsv(chart, { indicators: [kept.id, id] })).toThrow(RangeError);
    }
    expect(values).not.toHaveBeenCalled();
  });

  it.each([null, [], 2, new Date(), { from: NaN }, { to: Infinity }, { from: -Infinity },
    { from: '1' }, { until: 1 }, { [Symbol('hidden')]: 1 }, Object.create({ from: 1 })].map(range => ({ range })))(
    'rejects malformed ranges before any chart read (%#)', ({ range }) => {
      const fixture = unreadChart();
      expect(() => exportChartDataCsv(fixture.chart, unsafe({ range }))).toThrow(TypeError);
      expect(fixture.primaryBars).not.toHaveBeenCalled();
      expect(fixture.indicators).not.toHaveBeenCalled();
    },
  );

  it('rejects reversed bounds before any chart read', () => {
    const fixture = unreadChart();
    expect(() => exportChartDataCsv(fixture.chart, { range: { from: 2, to: 1 } })).toThrow(RangeError);
    expect(fixture.primaryBars).not.toHaveBeenCalled();
    expect(fixture.indicators).not.toHaveBeenCalled();
  });

  it.each(['range', 'indicators'] as const)('rejects inherited %s accessors without invoking them', key => {
    const get = vi.fn(() => { throw new Error('getter invoked'); });
    const prototype = Object.defineProperty({}, key, { get });
    const fixture = unreadChart();
    expect(() => exportChartDataCsv(fixture.chart, Object.create(prototype))).toThrow(TypeError);
    expect(get).not.toHaveBeenCalled();
    expect(fixture.primaryBars).not.toHaveBeenCalled();
    expect(fixture.indicators).not.toHaveBeenCalled();
  });

  it.each(['range', 'indicators', 'from', 'to', 'array-index', 'array-extra', 'range-extra'])(
    'rejects own %s accessors without invoking them', target => {
      const get = vi.fn(() => { throw new Error('getter invoked'); });
      const options: Record<string, unknown> = {};
      if (target === 'range' || target === 'indicators') Object.defineProperty(options, target, { get });
      else if (target.startsWith('array')) {
        const ids = ['id'];
        Object.defineProperty(ids, target === 'array-index' ? '0' : 'extra', { get });
        options.indicators = ids;
      } else {
        const range = Object.create(null);
        Object.defineProperty(range, target === 'range-extra' ? 'extra' : target, { get });
        options.range = range;
      }
      const fixture = unreadChart();
      expect(() => exportChartDataCsv(fixture.chart, unsafe(options))).toThrow(TypeError);
      expect(get).not.toHaveBeenCalled();
      expect(fixture.primaryBars).not.toHaveBeenCalled();
      expect(fixture.indicators).not.toHaveBeenCalled();
    },
  );
});
