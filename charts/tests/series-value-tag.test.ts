/**
 * An indicator's current value belongs on the price axis, not only in the
 * legend.
 *
 * Reported from a live chart: a Supertrend plotted its line all the way to the
 * right edge and then said nothing about where it actually sat, while the
 * reference terminal put a tag on the axis reading 1,339.7. Tracing a line back
 * to the edge by eye is exactly what an axis exists to save you, and on a chart
 * that also draws Buy and Sell buttons the number a stop is placed against
 * should not have to be estimated.
 *
 * The pane collected one tag and stopped: `lastEntry === null` meant the first
 * price series claimed the only slot and every later series, indicator plots
 * included, was skipped.
 */
import { describe, it, expect } from 'vitest';
import { Pane, type PaneRenderContext } from '../src/core/pane';
import { DataLayer } from '../src/model/data-layer';
import { TimeScale } from '../src/scale/time-scale';
import { PriceScale } from '../src/scale/price-scale';
import { createSeriesRecord } from '../src/model/series';
import {
  drawSeriesValueTag, resolveAxisLabels, AXIS_LABEL_PRIORITY, lastPriceTagHeight,
  type PlotLayout,
} from '../src/render/axis';
import { darkTheme } from '../src/theme';
import { fakeDocument } from './helpers/fake-dom';
import { RecordingContext } from './helpers/fake-ctx';
import type { Bar } from '../src/model/bar';

const layout: PlotLayout = {
  plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, timeAxisHeight: 22, plotLeft: 0,
};

function scale(min: number, max: number, height = 400): PriceScale {
  const ps = new PriceScale();
  ps.setHeight(height);
  ps.setPriceRange({ min, max });
  return ps;
}

const texts = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');

/** The fill of the box drawn immediately before a given label. */
function fillBehind(rec: RecordingContext, label: string): string | undefined {
  const i = rec.ops.findIndex((o) => o.type === 'fillText' && o.text === label);
  if (i < 1) return undefined;
  for (let j = i - 1; j >= 0; j--) if (rec.ops[j].type === 'fillRect') return rec.ops[j].fillStyle;
  return undefined;
}

describe('drawSeriesValueTag', () => {
  it('prints the value at the scale precision, in the plot colour', () => {
    const rec = new RecordingContext();
    const ps = scale(1300, 1400);
    drawSeriesValueTag(rec as unknown as CanvasRenderingContext2D, ps, 1339.7, '#26a69a', layout, 1);
    const label = ps.format(1339.7);
    expect(texts(rec)).toContain(label);
    expect(fillBehind(rec, label)).toBe('#26a69a');
  });

  it('sits in the axis strip, to the right of the plot', () => {
    const rec = new RecordingContext();
    drawSeriesValueTag(rec as unknown as CanvasRenderingContext2D, scale(1300, 1400), 1350, '#26a69a', layout, 1);
    const box = rec.ops.find((o) => o.type === 'fillRect');
    expect(box).toBeDefined();
    expect((box as { args: number[] }).args[0]).toBeGreaterThanOrEqual(layout.plotWidth);
  });

  it('draws nothing for a value off the pane, or for one that is not a number', () => {
    for (const price of [900, 9000, Number.NaN, Number.POSITIVE_INFINITY]) {
      const rec = new RecordingContext();
      drawSeriesValueTag(rec as unknown as CanvasRenderingContext2D, scale(1300, 1400), price, '#26a69a', layout, 1);
      expect(rec.ops.length).toBe(0);
    }
  });

  it('picks text that stays legible on either a light or a dark plot colour', () => {
    const on = (fill: string): string | undefined => {
      const rec = new RecordingContext();
      drawSeriesValueTag(rec as unknown as CanvasRenderingContext2D, scale(1300, 1400), 1350, fill, layout, 1);
      return rec.ops.find((o) => o.type === 'fillText')?.fillStyle;
    };
    // A pale yellow band and a navy one cannot share one text colour. The
    // near-black is the pill renderer's, shared so the tag, the trading chips
    // and a drawing readout all pick text the same way.
    expect(on('#f7e08a')).toBe('#10131a');
    expect(on('#1a237e')).toBe('#ffffff');
    // rgba() is what an opacity setting produces, and must parse the same way.
    expect(on('rgba(247,224,138,0.8)')).toBe('#10131a');
  });
});

describe('a series tag yields to the levels that outrank it', () => {
  const band = (y: number, priority: number): { y: number; height: number; priority: number } =>
    ({ y, height: lastPriceTagHeight(1), priority });

  it('loses its slot to the last price and keeps it against a tick', () => {
    const [lastPrice, seriesValue] = resolveAxisLabels(
      [band(200, AXIS_LABEL_PRIORITY.lastPrice), band(204, AXIS_LABEL_PRIORITY.seriesValue)], 2,
    );
    expect(lastPrice).toBe(true);
    expect(seriesValue).toBe(false);

    const [tick, value] = resolveAxisLabels(
      [band(200, AXIS_LABEL_PRIORITY.tick), band(204, AXIS_LABEL_PRIORITY.seriesValue)], 2,
    );
    expect(value).toBe(true);
    expect(tick).toBe(false);
  });

  it('resolves two of its own by input order, so they do not flicker', () => {
    const bands = [band(200, AXIS_LABEL_PRIORITY.seriesValue), band(203, AXIS_LABEL_PRIORITY.seriesValue)];
    expect(resolveAxisLabels(bands, 2)).toEqual([true, false]);
    expect(resolveAxisLabels(bands, 2)).toEqual([true, false]);
  });
});

describe('the pane tags every series that plots a number', () => {
  const ohlc = (t: number, v: number): Bar => ({ time: t, open: v, high: v + 1, low: v - 1, close: v });
  const flat = (t: number, v: number): Bar => ({ time: t, open: v, high: v, low: v, close: v });

  /** A pane carrying the instrument plus whatever overlays the case needs. */
  function paint(overlays: { values: number[]; style?: Record<string, unknown> }[]): RecordingContext {
    const dl = new DataLayer();
    const ts = new TimeScale({ barSpacing: 30 });
    ts.setWidth(600);
    const priceId = dl.createSeries();
    dl.setSeriesData(priceId, [ohlc(1000, 1330), ohlc(1060, 1335), ohlc(1120, 1340)]);
    const pane = new Pane(fakeDocument());
    pane.addSeries(createSeriesRecord(priceId, 'candlestick'));
    for (const o of overlays) {
      const id = dl.createSeries();
      dl.setSeriesData(id, o.values.map((v, i) => flat(1000 + i * 60, v)));
      pane.addSeries(createSeriesRecord(id, 'line', o.style));
    }
    pane.resize(600, 400, 1);
    ts.setBaseIndex(dl.baseIndex);
    const ctx: PaneRenderContext = {
      timeScale: ts, dataLayer: dl, dpr: 1, priceAxisWidth: 56, timeAxisHeight: 22,
      showTimeAxis: true, conflate: false, conflationFactor: 1, theme: darkTheme,
      showVertGrid: false, showHorzGrid: false,
    };
    // Without this the scale sits on its 0..1 placeholder and every tag bails
    // as out of plot, which is a green suite proving nothing.
    pane.autoscale(ctx);
    pane.paintBase(ctx);
    return pane.base.ctx as unknown as RecordingContext;
  }

  it('draws a tag for an overlay, in that overlay own colour', () => {
    const rec = paint([{ values: [1331, 1332, 1332.25], style: { color: '#ff9800' } }]);
    const tag = texts(rec).find((t) => t.startsWith('1332'));
    expect(tag).toBeDefined();
    expect(fillBehind(rec, tag as string)).toBe('#ff9800');
  });

  it('draws one per overlay rather than stopping after the first', () => {
    const rec = paint([
      { values: [1330, 1331, 1331.5], style: { color: '#ff9800' } },
      { values: [1336, 1337, 1337.5], style: { color: '#2196f3' } },
    ]);
    const drawn = texts(rec);
    expect(drawn.some((t) => t.startsWith('1331'))).toBe(true);
    expect(drawn.some((t) => t.startsWith('1337'))).toBe(true);
  });

  it('skips a plot whose current value is na, rather than showing a stale one', () => {
    // A Supertrend writes NaN on the half that is not active. A tag reading the
    // last number it had would be a price the study is not saying.
    const rec = paint([{ values: [1331.5, 1332.5, Number.NaN], style: { color: '#ff9800' } }]);
    expect(texts(rec).some((t) => t.startsWith('1331.5') || t.startsWith('1332.5'))).toBe(false);
  });

  it('honours lastValueVisible false on an overlay', () => {
    const rec = paint([{ values: [1330, 1332, 1332.25], style: { color: '#ff9800', lastValueVisible: false } }]);
    expect(texts(rec).some((t) => t.startsWith('1332.2'))).toBe(false);
  });

  it('leaves the instrument own last-price tag alone', () => {
    const rec = paint([{ values: [1330, 1332, 1332.25], style: { color: '#ff9800' } }]);
    // 1340 is the last close, and it still gets the dedicated up/down tag.
    expect(texts(rec).some((t) => t.startsWith('1340'))).toBe(true);
  });
});
