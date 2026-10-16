/**
 * `PlotWrites` alone, against series backed by a real `DataLayer`: whatever a
 * sequence of passes does to a plot's times and values, the series ends each
 * pass holding exactly what a whole `setData` of that pass would have left.
 */
import { describe, expect, it } from 'vitest';
import { PlotWrites } from '../src/model/indicator-plot-writes';
import { DataLayer } from '../src/model/data-layer';
import { toBar, type Bar, type SeriesDataItem } from '../src/model/bar';
import type { SeriesApi } from '../src/model/series';
import type { IndicatorPlot, IndicatorValues } from '../src/model/indicator-registry';

interface Probe { api: SeriesApi; wholes: number; points: number }

/** The data half of a chart series handle: the same data-layer calls, counted. */
function probe(layer: DataLayer): Probe {
  const id = layer.createSeries();
  const p: Probe = {
    wholes: 0, points: 0,
    api: {
      setData: (items: readonly SeriesDataItem[]) => { p.wholes++; layer.setSeriesData(id, items.map(toBar)); },
      update: (item: SeriesDataItem) => { p.points++; layer.update(id, toBar(item)); },
      getData: () => layer.indexedBars(id).map((ib) => ib.bar),
    } as unknown as SeriesApi,
  };
  return p;
}

const bars = (times: readonly number[]): Bar[] => times.map((time) => ({ time, open: 1, high: 1, low: 1, close: 1 }));
const line: IndicatorPlot = { key: 'v', type: 'line', title: 'v' };
const tinted: IndicatorPlot = {
  key: 'v', type: 'histogram', title: 'v',
  colorBy: ({ value, index }) => (value < 0 ? '#f00' : index % 3 === 0 ? undefined : '#0f0'),
};

describe('PlotWrites', () => {
  it('writes whole first, then only what moved, and always the last point', () => {
    const layer = new DataLayer();
    const p = probe(layer);
    const w = new PlotWrites();
    const times = [60, 120, 180, 240];
    const pass = (col: (number | null)[], at = times): void => {
      w.begin(bars(at));
      w.writeValues(p.api, line, col, bars(at), { v: col }, {});
    };
    pass([1, 2, 3, 4]);
    expect([p.wholes, p.points]).toEqual([1, 0]);
    pass([1, 2, 3, 5]);
    expect([p.wholes, p.points]).toEqual([1, 1]);
    pass([1, 2, 3, 5]); // nothing moved: the last point still goes, so the pass repaints
    expect([p.wholes, p.points]).toEqual([1, 2]);
    pass([1, 9, 3, 5]); // an older point, then the unmoved last
    expect([p.wholes, p.points]).toEqual([1, 4]);
    pass([1, 9, 3, 5, 6], [...times, 300]); // appended
    expect([p.wholes, p.points]).toEqual([1, 5]);
    expect(p.api.getData().map((b) => [b.time, b.close])).toEqual([[60, 1], [120, 9], [180, 3], [240, 5], [300, 6]]);
    pass([0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], [60, 120, 180, 240, 300, 360, 420, 480, 540, 600, 660]);
    expect([p.wholes, p.points]).toEqual([2, 5]); // more than a few points: whole
  });

  it('writes whole when the times do not begin with the last pass\'s', () => {
    const layer = new DataLayer();
    const p = probe(layer);
    const w = new PlotWrites();
    const pass = (at: number[]): void => {
      const col = at.map((t) => t / 60);
      w.begin(bars(at));
      w.writeValues(p.api, line, col, bars(at), { v: col }, {});
    };
    pass([120, 180]);
    pass([60, 120, 180]); // older history
    pass([60, 90, 120, 180]); // a gap filled
    pass([60, 90, 120]); // shorter
    expect([p.wholes, p.points]).toEqual([4, 0]);
  });

  it('writes whole while the source times are not one per bar in order', () => {
    const layer = new DataLayer();
    const p = probe(layer);
    const w = new PlotWrites();
    const at = [60, 180, 120];
    for (let k = 0; k < 3; k++) {
      const col = [k, k, k];
      w.begin(bars(at));
      w.writeValues(p.api, line, col, bars(at), { v: col }, {});
    }
    expect([p.wholes, p.points]).toEqual([3, 0]);
  });

  it('tells zero from minus zero, and a hole from NaN not at all', () => {
    const layer = new DataLayer();
    const p = probe(layer);
    const w = new PlotWrites();
    const at = [60, 120, 180];
    const pass = (col: (number | null | undefined)[]): void => {
      w.begin(bars(at));
      w.writeValues(p.api, line, col as (number | null)[], bars(at), { v: col as (number | null)[] }, {});
    };
    pass([0, null, 1]);
    pass([-0, undefined, 1]);
    expect(p.points).toBe(2); // minus zero at 60, then the unmoved last
    expect(Object.is(p.api.getData()[0].close, -0)).toBe(true);
    pass([-0, NaN, 1]);
    expect(p.points).toBe(3); // the last only
  });

  it('a pass that throws part way leaves the plot to the next pass, whole', () => {
    const layer = new DataLayer();
    const p = probe(layer);
    const w = new PlotWrites();
    const at = [60, 120, 180, 240];
    let fail = false;
    const plot: IndicatorPlot = { ...tinted, colorBy: ({ value, index }) => { if (fail && index === 2) throw new Error('no'); return value > 2 ? '#0f0' : undefined; } };
    const pass = (col: number[]): void => {
      w.begin(bars(at));
      w.writeValues(p.api, plot, col, bars(at), { v: col }, {});
    };
    pass([1, 2, 3, 4]);
    fail = true;
    expect(() => pass([1, 2, 5, 6])).toThrow('no');
    fail = false;
    pass([1, 2, 5, 6]);
    expect(p.wholes).toBe(2);
    expect(p.api.getData().map((b) => [b.close, b.color])).toEqual([[1, undefined], [2, undefined], [5, '#0f0'], [6, '#0f0']]);
  });

  it('holds what a whole write holds through any sequence of passes', () => {
    let s = 7 >>> 0;
    const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
    // Colours read other columns, so a colour can move while the value stays.
    const shaded: IndicatorPlot = {
      key: 'v', type: 'histogram', title: 'v',
      colorBy: ({ index, values }) => {
        const x = values.x[index];
        return x === null || Number.isNaN(x) ? undefined : x > 0.3 ? '#0f0' : x < 0 ? '#f00' : undefined;
      },
    };
    const candle: IndicatorPlot = {
      key: 'c', type: 'candlestick', title: 'c', ohlc: { open: 'o', high: 'h', low: 'l', close: 'x' },
      colorBy: ({ index, values }) => ((values.o[index] ?? 0) > 0.5 ? '#0a0' : undefined),
      colorParts: ({ index, values }) => {
        const v = values.v[index];
        return v === null || Number.isNaN(v) ? undefined : v > 0.25 ? { wick: '#111' } : v < 0 ? { body: '#222', border: '#333' } : { border: '#444' };
      },
    };
    const layer = new DataLayer(), reference = new DataLayer();
    const [valuePlot, candlePlot] = [probe(layer), probe(layer)];
    const [valueRef, candleRef] = [probe(reference), probe(reference)];
    const w = new PlotWrites();
    const cell = (): number | null => {
      const r = rnd();
      return r < 0.05 ? null : r < 0.08 ? NaN : r < 0.1 ? -0 : r < 0.12 ? 0 : Math.round(rnd() * 8) / 8 - 0.25;
    };
    let times = [60, 120, 180, 240, 300];
    const cols: Record<string, (number | null)[]> = { v: [], o: [], h: [], l: [], x: [] };
    for (const key of Object.keys(cols)) cols[key] = times.map(cell);
    for (let step = 0; step < 600; step++) {
      const r = rnd();
      if (r < 0.15) {
        const last = times[times.length - 1];
        const add = 1 + Math.floor(rnd() * 3);
        for (let k = 1; k <= add; k++) times.push(last + 60 * k);
        for (const key of Object.keys(cols)) for (let k = 0; k < add; k++) cols[key].push(cell());
      } else if (r < 0.2) {
        times = [times[0] - 60, ...times];
        for (const key of Object.keys(cols)) cols[key] = [cell(), ...cols[key]];
      } else if (r < 0.23 && times.length > 3) {
        const at = 1 + Math.floor(rnd() * (times.length - 2));
        times.splice(at, 1);
        for (const key of Object.keys(cols)) cols[key].splice(at, 1);
      } else {
        // A tick: the forming bar, sometimes a few more, sometimes all of them.
        const moved = rnd() < 0.1 ? times.length : 1 + Math.floor(rnd() * 3);
        for (const key of Object.keys(cols)) {
          for (let k = 0; k < moved; k++) cols[key][rnd() < 0.7 ? times.length - 1 : Math.floor(rnd() * times.length)] = cell();
        }
      }
      const b = bars(times);
      const values: IndicatorValues = { ...cols };
      w.begin(b);
      w.writeValues(valuePlot.api, shaded, cols.v, b, values, {});
      w.writeCandles(candlePlot.api, candle, candle.ohlc!, b, values, {}, 'model');
      // The reference writes whole every pass, as every recompute used to.
      const whole = new PlotWrites();
      whole.begin(b);
      whole.writeValues(valueRef.api, shaded, cols.v, b, values, {});
      whole.writeCandles(candleRef.api, candle, candle.ohlc!, b, values, {}, 'model');
      for (const [ours, theirs] of [[valuePlot, valueRef], [candlePlot, candleRef]]) {
        expect(ours.api.getData(), `step ${step}`).toStrictEqual(theirs.api.getData());
        expect(JSON.stringify(ours.api.getData())).toBe(JSON.stringify(theirs.api.getData()));
      }
    }
    expect(valuePlot.points).toBeGreaterThan(valuePlot.wholes);
  });
});
