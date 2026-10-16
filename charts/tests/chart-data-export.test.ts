import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import { exportChartDataCsv } from '../src/model/chart-data-export';
import { addComparison, comparisonController, ComparisonController } from '../src/compare/controller';
import { registerIndicator } from '../src/model/indicator-registry';
import { ReplayController } from '../src/replay/controller';
import { HeikinAshiTransform } from '../src/transform/heikin-ashi';
import type { Bar } from '../src/model/bar';
import { fakeDocument } from './helpers/fake-dom';
import '../src/indicators/index';

const cleanup: (() => void)[] = [];
afterEach(() => { for (const dispose of cleanup.splice(0).reverse()) dispose(); });
const bar = (time: number, close: number, extra: Partial<Bar> = {}): Bar =>
  ({ time, open: close, high: close + 1, low: close - 1, close, ...extra });
const header = 'time,open,high,low,close,volume,oi\r\n';
function setup(data: Bar[] = [bar(60, 10), bar(120, 12), bar(180, 14)]) {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), { document: doc, raf: { schedule: () => 0 }, shortcuts: false });
  cleanup.push(() => chart.destroy()); chart.applySize(800, 600);
  const series = chart.addSeries('candlestick'); series.setData(data);
  return { chart, series, data };
}

describe('chart data CSV', () => {
  it('exports UTC seconds and unrounded OHLC with honest absent and zero observations', () => {
    const { chart } = setup([bar(60, 1.23456789, { volume: 0, oi: 0 }), bar(120, 2)]);
    expect(exportChartDataCsv(chart)).toBe(header
      + '60,1.23456789,2.23456789,0.2345678899999999,1.23456789,0,0\r\n'
      + '120,2,3,1,2,,\r\n');
  });

  it('retains empty/gap rows and ignores private fields on bars', () => {
    const { chart, series } = setup([]);
    expect(exportChartDataCsv(chart)).toBe(header);
    series.setData([{ time: 60 }, { ...bar(120, 4), password: 'private' } as Bar]);
    expect(exportChartDataCsv(chart)).toBe(header + '60,,,,,,\r\n120,4,5,3,4,,\r\n');
  });

  it('distinguishes repeated hidden studies and leaves their warmup blank', () => {
    const { chart } = setup();
    const fast = chart.addIndicator('ema', { length: 1 });
    const slow = chart.addIndicator('ema', { length: 2 }); slow.setVisible(false);
    const rows = exportChartDataCsv(chart).trim().split('\r\n');
    expect(rows[0]).toBe(header.trim() + `,indicator:${fast.id}:ma,indicator:${slow.id}:ma`);
    expect(rows[1]).toBe('60,10,11,9,10,,,10,');
    expect(rows[2]).toBe('120,12,13,11,12,,,12,11');
    expect(exportChartDataCsv(chart, { indicators: false }).split('\r\n')[0]).toBe(header.trim());
  });

  it('flushes same-turn live updates before reading study values', () => {
    const { chart, series } = setup(); chart.addIndicator('ema', { length: 1 });
    series.update(bar(180, 19, { oi: 51 }));
    expect(exportChartDataCsv(chart).split('\r\n')[3]).toBe('180,19,20,18,19,,51,19');
  });

  it('exports only declared plots and escapes custom headers without executable cells', () => {
    const key = '=X,"Y"\nZ';
    registerIndicator({ id: 'csv-custom', name: 'Custom', placement: 'onchart', inputs: [],
      plots: [{ key, type: 'line', title: 'Custom' }],
      calc: () => ({ [key]: [null, NaN, Infinity], internal: [999, 999, 999] }) });
    const { chart } = setup(); const study = chart.addIndicator('csv-custom');
    const csv = exportChartDataCsv(chart);
    expect(csv).toBe(header.trim() + `,"indicator:${study.id}:=X,""Y""\nZ"\r\n`
      + '60,10,11,9,10,,,\r\n120,12,13,11,12,,,\r\n180,14,15,13,14,,,\r\n');
  });

  it('exports comparison prices in their own units and leaves calendar gaps blank', () => {
    const { chart } = setup();
    comparisonController(chart, { mode: 'percentage', baseline: 'common' });
    const handle = addComparison(chart, { symbol: 'SECOND', bars: [bar(60, 20), bar(180, 30)] });
    cleanup.push(() => handle.remove());
    expect(exportChartDataCsv(chart)).toBe(header.trim() + ',comparison:1:SECOND:close\r\n'
      + '60,10,11,9,10,,,20\r\n120,12,13,11,12,,,\r\n180,14,15,13,14,,,30\r\n');
  });

  it('exports installed transformed bars without recovering or refolding the raw history', () => {
    const transform = new HeikinAshiTransform();
    const transformed = [bar(60, 10, { open: 4, oi: 7 }), bar(120, 14, { open: 8, oi: 9 })]
      .flatMap(item => transform.push(item));
    const { chart } = setup(transformed);
    expect(exportChartDataCsv(chart)).toBe(header + transformed.map(item =>
      [item.time, item.open, item.high, item.low, item.close, '', item.oi].join(',') + '\r\n').join(''));
    expect(chart.primaryBars()).toEqual(transformed);
  });

  it('accepts explicitly managed comparison handles and safely prefixes their names', () => {
    const { chart } = setup(); const controller = new ComparisonController(chart, { mode: 'none' });
    const handle = controller.add({ symbol: '=FORMULA,\n"quoted"', bars: [bar(60, 4), bar(120, 5), bar(180, 6)] });
    cleanup.push(() => handle.remove());
    const csv = exportChartDataCsv(chart, { comparisons: controller.list() });
    expect(csv).toContain(',"comparison:1:=FORMULA,\n""quoted"":close"\r\n');
    expect(csv).toContain('60,10,11,9,10,,,4\r\n');
    expect(exportChartDataCsv(chart)).not.toContain('FORMULA');
  });

  it('exports only the installed replay prefix and eligible comparison readings', () => {
    const { chart, series, data } = setup(); chart.addIndicator('ema', { length: 1 });
    comparisonController(chart, { mode: 'none' });
    const handle = addComparison(chart, { symbol: 'OTHER', bars: data.map(item => bar(item.time, item.close * 10)) });
    cleanup.push(() => handle.remove());
    const replay = new ReplayController(chart, { series, bars: data, startIndex: 1 });
    cleanup.push(() => replay.stop());
    const csv = exportChartDataCsv(chart);
    expect(csv.trim().split('\r\n')).toHaveLength(3);
    expect(csv).not.toContain('180,'); expect(csv).not.toContain(',140');
    expect(csv).toContain('60,10,11,9,10,,,10,100\r\n');
    expect(chart.primaryBars()).toHaveLength(2);
  });
});
