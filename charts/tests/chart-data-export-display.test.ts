import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { exportChartDataCsv, type ChartDataCsvOptions } from '../src/model/chart-data-export';
import { registerIndicator } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { addComparison } from '../src/compare/controller';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';

let nextId = 0;
const cleanup: (() => void)[] = [];
afterEach(() => { vi.restoreAllMocks(); cleanup.splice(0).reverse().forEach(dispose => dispose()); });
const bar = (time: number, close: number): Bar => ({ time, open: close, high: close + 1, low: close - 1, close });
function setup(offsets = [0], data = [bar(10, 1), bar(20, 2), bar(30, 3)]) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false, raf: { schedule: () => 0 } });
  cleanup.push(() => chart.destroy()); chart.applySize(800, 500);
  const primary = chart.addSeries('candlestick'); primary.setData(data);
  const id = `csv-display-${++nextId}`;
  registerIndicator({ id, name: 'Display study', placement: 'onchart', inputs: [],
    plots: offsets.map((offset, i) => ({ key: `v${i}`, title: `Value ${i}`, type: 'line', offset })),
    calc: bars => Object.fromEntries(offsets.map((_, i) => [`v${i}`, bars.map(b => b.close * (i + 1))])) });
  const study = chart.addIndicator(id);
  return { chart, primary, study, data };
}
function rows(csv: string) {
  const [head, ...body] = csv.trimEnd().split('\r\n');
  const keys = head.split(',');
  return body.map(line => Object.fromEntries(line.split(',').map((value, i) => [keys[i], value])));
}

describe('display-aligned CSV', () => {
  it('builds a sparse union with source cells attached only to installed primary positions', () => {
    const { chart, study, primary } = setup([2, -1]);
    primary.applyOptions({ barOffset: 99 });
    const sample = vi.fn((time: number) => bar(time, 100));
    const result = rows(exportChartDataCsv(chart, { alignment: 'display', comparisons: [{ symbol: 'OTHER', barAt: sample }] }));
    expect(result.map(r => [r.time, r.logical_index, r.time_origin, r.close, r[`indicator:${study.id}:v0`], r[`indicator:${study.id}:v1`], r['comparison:1:OTHER:close']]))
      .toEqual([['0', '-1', 'projected', '', '', '2', ''], ['10', '0', 'axis', '1', '', '4', '100'],
        ['20', '1', 'axis', '2', '', '6', '100'], ['30', '2', 'axis', '3', '1', '', '100'],
        ['40', '3', 'projected', '', '2', '', ''], ['50', '4', 'projected', '', '3', '', '']]);
    expect(sample.mock.calls).toEqual([[10], [20], [30]]);
  });

  it('uses the installed shared axis and actual runtime offsets instead of primary row numbers', () => {
    const { chart, study } = setup([2], [bar(10, 1), bar(30, 2)]);
    chart.addSeries('line').setData([bar(20, 100)]);
    study.series('v0')!.applyOptions({ barOffset: 1 });
    const result = rows(exportChartDataCsv(chart, { alignment: 'display' }));
    expect(result.map(r => [r.time, r.logical_index, r.close, r[`indicator:${study.id}:v0`]]))
      .toEqual([['10', '0', '1', ''], ['20', '1', '', '1'], ['30', '2', '2', ''], ['40', '3', '', '2']]);
    study.series('v0')!.applyOptions({ barOffset: 0 });
    expect(rows(exportChartDataCsv(chart, { alignment: 'display' })).map(r => r[`indicator:${study.id}:v0`])).toEqual(['1', '2']);
    expect(exportChartDataCsv(chart)).not.toContain('logical_index');
  });

  it('retains fractional logical positions and filters timestamps after shifting', () => {
    const { chart, study } = setup([0.5]);
    const result = rows(exportChartDataCsv(chart, { alignment: 'display', range: { from: 15, to: 25 } }));
    expect(result.map(r => [r.time, r.logical_index, r.time_origin, r[`indicator:${study.id}:v0`]]))
      .toEqual([['15', '0.5', 'interpolated', '1'], ['20', '1', 'axis', ''], ['25', '1.5', 'interpolated', '2']]);
  });

  it('keeps one-point projection unknown unless a detached projection callback supplies time', () => {
    const { chart, study } = setup([2, -1], [bar(60, 4)]);
    expect(rows(exportChartDataCsv(chart, { alignment: 'display' })).map(r => [r.time, r.logical_index, r.time_origin]))
      .toEqual([['', '-1', 'unknown'], ['60', '0', 'axis'], ['', '2', 'unknown']]);
    const projectTime = vi.fn((index, context) => {
      expect(Object.isFrozen(context)).toBe(true); expect(Object.isFrozen(context.axisTimes)).toBe(true);
      expect(context.axisTimes).toEqual([60]);
      study.series('v0')!.applyOptions({ barOffset: 90 });
      return 60 + index * 30;
    });
    expect(rows(exportChartDataCsv(chart, { alignment: 'display', projectTime })).map(r => r.time)).toEqual(['30', '60', '120']);
    expect(projectTime.mock.calls.map(call => call[0])).toEqual([-1, 2]);
    expect(rows(exportChartDataCsv(chart, { alignment: 'display', range: { from: 0 } })).map(r => r.time)).toEqual(['60']);
  });

  it('clips replay axis metadata and comparisons to revealed observations', () => {
    const { chart, primary, study, data } = setup([2], [bar(10, 1), bar(20, 2), bar(30, 3), bar(40, 4)]);
    chart.addSeries('line').setData([bar(25, 500), bar(35, 500)]);
    const comparison = addComparison(chart, { symbol: 'OTHER', bars: data.map(b => bar(b.time, b.close * 100)) });
    cleanup.push(() => comparison.remove());
    const replay = new ReplayController(chart, { series: primary, bars: data, startIndex: 1 });
    cleanup.push(() => replay.stop());
    const result = rows(exportChartDataCsv(chart, { alignment: 'display', projectTime: (index, context) => {
      expect(context.axisTimes).toEqual([10, 20]); expect(context.replay?.time).toBe(20);
      return 10 + index * 10;
    } }));
    expect(result.map(r => [r.time, r.time_origin, r.close, r[`indicator:${study.id}:v0`], r['comparison:1:OTHER:close']]))
      .toEqual([['10', 'axis', '1', '', '100'], ['20', 'axis', '2', '', '200'], ['30', 'projected', '', '1', ''], ['40', 'projected', '', '2', '']]);
  });

  it('exports the installed forming observation and frozen replay clock without completed future prices', () => {
    // The displayed bar holds its finer bars, as one feed's would, so the export
    // sees the forming observation itself rather than one held inside it.
    const { chart, primary, study, data } = setup([1], [{ time: 0, open: 4, high: 6, low: 3, close: 5 }, bar(300, 1000)]);
    const replay = new ReplayController(chart, { series: primary, bars: data, startTime: 60,
      timing: { barEndTime: b => b.time + 300, subBarEndTime: b => b.time + 60 }, subBars: [bar(0, 4), bar(60, 5)] });
    cleanup.push(() => replay.stop());
    const result = rows(exportChartDataCsv(chart, { alignment: 'display', projectTime: (index, context) => {
      expect(context.axisTimes).toEqual([0]);
      expect(context.replay).toEqual({ time: 0, forming: true, asOf: 60 });
      expect(Object.isFrozen(context.replay)).toBe(true);
      return index * 300;
    } }));
    expect(result.map(row => [row.time, row.close, row[`indicator:${study.id}:v0`]])).toEqual([['0', '4', ''], ['300', '', '4']]);
  });

  it('copies accepted values and offsets before a projector changes the chart', () => {
    const { chart, primary, study } = setup([1]);
    const csv = exportChartDataCsv(chart, { alignment: 'display', projectTime: () => {
      primary.setData([bar(999, 99)]); study.remove(); return 40;
    } });
    expect(rows(csv).map(row => [row.time, row.close, row[`indicator:${study.id}:v0`]]))
      .toEqual([['10', '1', ''], ['20', '2', '1'], ['30', '3', '2'], ['40', '', '3']]);
  });

  it('does not flush or read study values when display selection is empty', () => {
    const { chart, study } = setup([10]);
    const installed = vi.spyOn(chart, 'indicators'); const values = vi.spyOn(study, 'values');
    expect(rows(exportChartDataCsv(chart, { alignment: 'display', indicators: [] }))).toHaveLength(3);
    expect(installed).not.toHaveBeenCalled(); expect(values).not.toHaveBeenCalled();
  });

  it('expands declared candle fields independently only in display mode', () => {
    const { chart } = setup([], [bar(10, 2)]);
    registerIndicator({ id: 'csv-display-candle', name: 'Candle', placement: 'onchart', inputs: [],
      plots: [{ key: 'candles', title: 'Candle', type: 'candlestick', offset: 1, ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } }],
      calc: () => ({ o: [0], h: [null], l: [-2], c: [4] }) });
    const study = chart.addIndicator('csv-display-candle');
    expect(exportChartDataCsv(chart, { indicators: [study.id] }).split('\r\n')[1]).toBe('10,2,3,1,2,,,');
    const result = rows(exportChartDataCsv(chart, { indicators: [study.id], alignment: 'display' }));
    const shifted = result[1];
    expect(['open', 'high', 'low', 'close'].map(field => shifted[`indicator:${study.id}:candles:${field}`])).toEqual(['0', '', '-2', '4']);
    expect(shifted.close).toBe('');
  });

  it('does not allocate intermediate rows for large sparse offsets or absent values', () => {
    const { chart, study } = setup([1000000]);
    vi.spyOn(study, 'values').mockReturnValue({ v0: [null, NaN, 0] });
    const result = rows(exportChartDataCsv(chart, { alignment: 'display' }));
    expect(result).toHaveLength(4);
    expect(result[3].logical_index).toBe('1000002');
    expect(result[3][`indicator:${study.id}:v0`]).toBe('0');
  });

  it.each([NaN, Infinity, '2'])('rejects malformed effective offsets (%s)', offset => {
    const { chart, study } = setup();
    study.series('v0')!.applyOptions({ barOffset: offset as number });
    expect(() => exportChartDataCsv(chart, { alignment: 'display' })).toThrow(/offset|position/i);
  });

  it('rejects removed plot resources and unsafe target positions instead of guessing', () => {
    const { chart, study } = setup([Number.MAX_SAFE_INTEGER]);
    expect(() => exportChartDataCsv(chart, { alignment: 'display' })).toThrow(/position/i);
    study.series('v0')!.remove();
    expect(() => exportChartDataCsv(chart, { alignment: 'display' })).toThrow(/series|plot|resource/i);
  });

  it('rejects large fractional positions that collapse distinct observations', () => {
    const { chart } = setup([2 ** 52 - 0.5], [bar(10, 1), bar(20, 2), bar(30, 3), bar(40, 4)]);
    expect(() => exportChartDataCsv(chart, { alignment: 'display', projectTime: index => index - 2 ** 52 + 100 })).toThrow(/position/i);
  });

  it('disambiguates expanded candle headers while preserving legacy source columns', () => {
    const { chart } = setup([], [bar(10, 2)]);
    registerIndicator({ id: 'csv-display-collision', name: 'Candle', placement: 'onchart', inputs: [],
      plots: [{ key: 'candles', title: 'Candle', type: 'candlestick', ohlc: { open: 'o', high: 'h', low: 'l', close: 'c' } },
        { key: 'candles:open', title: 'Scalar', type: 'line' }],
      calc: () => ({ o: [1], h: [3], l: [0], c: [2], 'candles:open': [4] }) });
    const study = chart.addIndicator('csv-display-collision');
    expect(exportChartDataCsv(chart)).toContain(`indicator:${study.id}:candles,indicator:${study.id}:candles:open`);
    const [header, body] = exportChartDataCsv(chart, { alignment: 'display' }).split('\r\n');
    const keys = header.split(',');
    expect(new Set(keys).size).toBe(keys.length);
    expect(body.split(',').slice(-5)).toEqual(['1', '3', '0', '2', '4']);
    expect(keys[9]).toContain(`indicator:${study.id}:candles:open`);
    expect(keys[13]).toContain(`indicator:${study.id}:candles:open`);
  });

  it.each([() => Infinity, () => 10, () => 'future', (index: number) => -index])('rejects invalid or colliding projection results (%#)', projectTime => {
    const { chart } = setup([2]);
    expect(() => exportChartDataCsv(chart, { alignment: 'display', projectTime } as ChartDataCsvOptions)).toThrow();
  });

  it('permits explicit unknown projections and rejects time precision collapse', () => {
    const { chart } = setup([2]);
    expect(rows(exportChartDataCsv(chart, { alignment: 'display', projectTime: () => null })).slice(-2).map(r => r.time_origin)).toEqual(['unknown', 'unknown']);
    const other = setup([0.5], [bar(1e16, 1), bar(1e16 + 2, 2)]);
    expect(() => exportChartDataCsv(other.chart, { alignment: 'display' })).toThrow(/time|collid|order/i);
  });
});
