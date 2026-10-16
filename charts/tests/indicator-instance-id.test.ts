/**
 * A host naming the id of a study it adds: how a chart-wide undo brings a
 * removed study back as itself, so what read its output or named it finds it.
 */
import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 80 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 100 + i, high: 102 + i + (i % 3), low: 99 + i - (i % 2), close: 101 + i + (i % 5) - 2, volume: 100,
  })));
  charts.push(chart);
  return chart;
}
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

const last = (values: readonly (number | null | undefined)[] | undefined): number | null | undefined =>
  values === undefined ? undefined : values[values.length - 1];

describe('addIndicator with an instance id', () => {
  it('takes the id it is given, and a removed study comes back as itself', () => {
    const chart = makeChart();
    const osc = chart.addIndicator('rsi', { length: 5 }, { instanceId: 'osc' });
    expect(osc.id).toBe('osc');
    const reader = chart.addIndicator('sma', { length: 3, source: { kind: 'indicator', instanceId: 'osc', plotKey: 'rsi' } });
    const before = last(reader.values().ma as (number | null)[]);
    expect(Number.isFinite(before)).toBe(true);
    expect(chart.removeIndicator('osc')).toBe(true);
    expect(Number.isFinite(last(reader.values().ma as (number | null)[]))).toBe(false);
    // A new study without an id never takes the removed one's.
    expect(chart.addIndicator('rsi').id).not.toBe('osc');
    const back = chart.addIndicator('rsi', { length: 5 }, { instanceId: 'osc', paneIndex: osc.paneIndex });
    expect(back.id).toBe('osc');
    expect(last(reader.values().ma as (number | null)[])).toBe(before);
    expect(chart.getState().indicators!.filter(item => item.instanceId === 'osc')).toHaveLength(1);
  });

  it('refuses an id a study on the chart holds, and one that is not an id, before adding anything', () => {
    const chart = makeChart();
    const held = chart.addIndicator('sma', {}, { instanceId: 'held' });
    const count = chart.indicators().length;
    expect(() => chart.addIndicator('ema', {}, { instanceId: held.id })).toThrow(/already in use/);
    expect(() => chart.addIndicator('ema', {}, { instanceId: '  ' })).toThrow(TypeError);
    expect(() => chart.addIndicator('ema', {}, { instanceId: 7 as never })).toThrow(TypeError);
    expect(chart.indicators()).toHaveLength(count);
    expect(chart.panes()).toHaveLength(1);
  });
});
