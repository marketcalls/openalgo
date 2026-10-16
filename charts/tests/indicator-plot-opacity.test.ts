/**
 * Every plot gets a generated Opacity setting (`<plot>:opacity`). The series
 * colour always folded it in; a plot that colours bar by bar (`colorBy`,
 * `colorParts`) painted each bar with the unfaded colour, so the control did
 * nothing on it. The plot writer now fades the per-bar colours the same way.
 */
import { describe, it, expect } from 'vitest';
import { PlotWrites } from '../src/model/indicator-plot-writes';
import type { IndicatorPlot } from '../src/model/indicator-registry';
import type { SeriesApi } from '../src/model/series';
import { withAlpha } from '../src/render/pill';
import { OPEN_INTEREST_CHANGE, MACD } from '../src/indicators/index';
import { completeSessions } from './helpers/indicator-golden';

/** A series that keeps what it was last handed whole. */
function series(): { api: SeriesApi; points: () => { color?: string; wickColor?: string }[] } {
  let points: { color?: string; wickColor?: string }[] = [];
  const api = { setData: (data: typeof points) => { points = data; }, update: () => {} } as unknown as SeriesApi;
  return { api, points: () => points };
}

const bars = completeSessions().slice(0, 60);

describe('plot opacity on per-bar colours', () => {
  it('fades a colorBy plot by its Opacity setting', () => {
    const plot = MACD.plots.find((p) => p.key === 'histogram')!;
    const values = MACD.calc(bars, {}, {});
    const writes = new PlotWrites();
    const faded = series();
    writes.begin(bars);
    writes.writeValues(faded.api, plot, values.histogram, bars, values, { 'histogram:opacity': 40 });
    const full = series();
    writes.begin(bars);
    writes.writeValues(full.api, plot, values.histogram, bars, values, {});
    const painted = full.points().map((p) => p.color).filter((c): c is string => c !== undefined);
    expect(painted.length).toBeGreaterThan(10);
    expect(faded.points().map((p) => p.color).filter((c) => c !== undefined)).toEqual(painted.map((c) => withAlpha(c, 0.4)));
  });

  it('fades each part of a colorParts candle plot', () => {
    const plot: IndicatorPlot = {
      key: 'c', type: 'candlestick', title: 'C', ohlc: { open: 'o', high: 'h', low: 'l', close: 'k' },
      colorParts: () => ({ body: '#26a69a', wick: '#ef5350' }),
    } as IndicatorPlot;
    const col = bars.map((b) => b.close);
    const values = { o: col, h: col, l: col, k: col };
    const writes = new PlotWrites();
    const s = series();
    writes.begin(bars);
    writes.writeCandles(s.api, plot, plot.ohlc!, bars, values, { 'c:opacity': 50 }, 'probe');
    expect(s.points()[0]).toMatchObject({ color: withAlpha('#26a69a', 0.5), wickColor: withAlpha('#ef5350', 0.5) });
  });

  it('scales the alpha a colour already carries, so a lighter bar stays lighter', () => {
    const plot = { key: 'h', type: 'histogram', title: 'H', colorBy: () => 'rgba(8,153,129,0.5)' } as unknown as IndicatorPlot;
    const col = bars.map((b) => b.close);
    const writes = new PlotWrites();
    const s = series();
    writes.begin(bars);
    writes.writeValues(s.api, plot, col, bars, { h: col }, { 'h:opacity': 50 });
    expect(new Set(s.points().map((p) => p.color))).toEqual(new Set(['rgba(8,153,129,0.25)']));
  });

  it('fades Open Interest Change once, not twice', () => {
    const plot = OPEN_INTEREST_CHANGE.plots[0]!;
    const oiBars = bars.map((b, i) => ({ ...b, oi: 1_000_000 + (i % 7) * 900 - (i % 3) * 1500 }));
    const values = OPEN_INTEREST_CHANGE.calc(oiBars, {}, {});
    const writes = new PlotWrites();
    const s = series();
    writes.begin(oiBars);
    writes.writeValues(s.api, plot, values.change, oiBars, values, { 'change:opacity': 50 });
    const colors = new Set(s.points().map((p) => p.color).filter((c) => c !== undefined));
    expect([...colors].sort()).toEqual([withAlpha('#26a69a', 0.5), withAlpha('#ef5350', 0.5)].sort());
  });
});
