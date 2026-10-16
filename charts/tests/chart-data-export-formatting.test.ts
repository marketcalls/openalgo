import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { exportChartDataCsv, type ChartDataCsvOptions } from '../src/model/chart-data-export';
import { fakeDocument } from './helpers/fake-dom';
import '../src/indicators/index';

const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach(c => c.destroy()); vi.restoreAllMocks(); });
function setup() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false, raf: { schedule: () => 0 } });
  charts.push(chart); chart.applySize(800, 500);
  const series = chart.addSeries('candlestick');
  series.setData([{ time: -0.5, open: -1, high: 0, low: -2, close: -1, volume: 0 }, { time: 0.5, open: 3, high: 4, low: 2, close: 3 }]);
  return { chart, series };
}
const quoted = (value: string) => /[",\r\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;

describe('CSV presentation callbacks', () => {
  it('retains raw UTC identity while adding identical human time labels', () => {
    const { chart } = setup();
    const csv = exportChartDataCsv(chart, { formatters: { time: () => '01:30' } });
    expect(csv).toBe('time,time_label,open,high,low,close,volume,oi\r\n-0.5,01:30,-1,0,-2,-1,0,\r\n0.5,01:30,3,4,2,3,,\r\n');
  });

  it('retains blank raw cells for a nonfinite installed time', () => {
    const { chart, series } = setup();
    series.setData([{ time: Infinity, open: 1, high: 1, low: 1, close: 1 }]);
    const time = vi.fn(() => 'label');
    expect(exportChartDataCsv(chart, { indicators: false })).toBe('time,open,high,low,close,volume,oi\r\n,1,1,1,1,,\r\n');
    expect(exportChartDataCsv(chart, { indicators: false, formatters: { time } })).toContain('\r\n,,1,1,1,1,,\r\n');
    expect(time).not.toHaveBeenCalled();
  });

  it('formats finite value cells only and exposes frozen canonical column metadata', () => {
    const { chart } = setup();
    const value = vi.fn((number, column) => {
      expect(Object.isFrozen(column)).toBe(true);
      expect(column.kind).toBe('primary');
      return `${column.field}:${number}`;
    });
    const csv = exportChartDataCsv(chart, { formatters: { value } });
    expect(value).toHaveBeenCalledTimes(9);
    expect(csv).toContain('-0.5,open:-1,high:0,low:-2,close:-1,volume:0,\r\n');
    expect(csv).toContain('0.5,open:3,high:4,low:2,close:3,,\r\n');
  });

  it.each(['=SUM(1,2)', '+CMD', '-1+2', '@X', '\ttext', '\rtext', '\ntext', '  =x', '\ufeff+x'])(
    'protects formatter text %j before applying CSV escaping', text => {
      const { chart } = setup();
      const csv = exportChartDataCsv(chart, { formatters: { time: () => text, value: () => text } });
      expect(csv).toContain(`-0.5,${quoted("'" + text)},${quoted("'" + text)},`);
      expect(csv).not.toContain("'-0.5");
    },
  );

  it('escapes ordinary formatted quotes and preserves canonical prefixes for duplicate headers', () => {
    const { chart } = setup();
    const csv = exportChartDataCsv(chart, { formatters: { header: () => 'same,"label"', value: () => 'a,"b"\nc' } });
    expect(csv.split('\r\n')[0]).toBe(['time', 'open', 'high', 'low', 'close', 'volume', 'oi'].map(key => quoted(`${key}:same,"label"`)).join(','));
    expect(csv).toContain('"a,""b""\nc"');
  });

  it('copies all numeric observations before any formatter can mutate or remove studies', () => {
    const { chart, series } = setup();
    const study = chart.addIndicator('sma', { length: 1 });
    let changed = false;
    const csv = exportChartDataCsv(chart, { formatters: { header: column => {
      if (!changed) { changed = true; series.setData([{ time: 99, close: 99 }]); study.remove(); }
      return column.key;
    } } });
    expect(csv).toBe(`time,open,high,low,close,volume,oi,indicator:${study.id}:ma\r\n-0.5,-1,0,-2,-1,0,,-1\r\n0.5,3,4,2,3,,,3\r\n`);
  });

  it('snapshots comparison values before callbacks and leaves projected rows unsampled', () => {
    const { chart } = setup();
    let price = 7;
    const sample = vi.fn((time: number) => ({ time, open: price, high: price, low: price, close: price }));
    const csv = exportChartDataCsv(chart, { comparisons: [{ symbol: 'OTHER', barAt: sample }], formatters: { header: column => { price = 99; return column.key; } } });
    expect(sample).toHaveBeenCalledTimes(2);
    expect(csv).toContain('-0.5,-1,0,-2,-1,0,,7\r\n0.5,3,4,2,3,,,7\r\n');
  });

  it('retains source-row comparison sampling order from the raw exporter', () => {
    const { chart } = setup();
    let count = 0;
    const sample = (time: number) => ({ time, open: 0, high: 0, low: 0, close: ++count });
    const csv = exportChartDataCsv(chart, { comparisons: [{ symbol: 'A', barAt: sample }, { symbol: 'B', barAt: sample }] });
    expect(csv).toContain('-0.5,-1,0,-2,-1,0,,1,2\r\n0.5,3,4,2,3,,,3,4\r\n');
  });

  it('keeps deliberately colliding formatted header labels unique', () => {
    const { chart } = setup();
    const csv = exportChartDataCsv(chart, { formatters: { header: column => column.key === 'close' ? 'time:x' : 'x' } });
    const headers = csv.split('\r\n')[0].split(',');
    expect(new Set(headers).size).toBe(7);
  });

  it.each(['time', 'value', 'header'] as const)('rejects a non-string %s result and propagates callback errors', key => {
    const { chart } = setup();
    expect(() => exportChartDataCsv(chart, { formatters: { [key]: () => 3 } } as ChartDataCsvOptions)).toThrow(TypeError);
    expect(() => exportChartDataCsv(chart, { formatters: { [key]: () => { throw new Error('failed callback'); } } })).toThrow('failed callback');
  });

  it.each([{ alignment: 'pixels' }, { alignment: null }, { projectTime: () => 1 }, { alignment: 'display', projectTime: 3 },
    { formatters: [] }, { formatters: { value: 4 } }, { formatters: { extra: () => '' } }])(
    'validates presentation options before reading the chart (%#)', options => {
      const chart = { primaryBars: vi.fn(), indicators: vi.fn() } as unknown as Chart;
      expect(() => exportChartDataCsv(chart, options as ChartDataCsvOptions)).toThrow(TypeError);
      expect(chart.primaryBars).not.toHaveBeenCalled(); expect(chart.indicators).not.toHaveBeenCalled();
    },
  );

  it.each(['alignment', 'projectTime', 'formatters', 'value'])('rejects %s accessors without invoking them', key => {
    const get = vi.fn(() => { throw new Error('invoked getter'); });
    const options = key === 'value' ? { formatters: Object.defineProperty({}, key, { get }) } : Object.defineProperty({}, key, { get });
    const chart = { primaryBars: vi.fn(), indicators: vi.fn() } as unknown as Chart;
    expect(() => exportChartDataCsv(chart, options)).toThrow(TypeError); expect(get).not.toHaveBeenCalled();
    expect(chart.primaryBars).not.toHaveBeenCalled();
  });
});
