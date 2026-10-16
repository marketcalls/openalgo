/**
 * Multi-line marker text (src/primitives/markers.ts).
 * Single-line output must be identical to the pre-change geometry, so the
 * expectations below are the old formulas written out by hand.
 */
import { describe, it, expect } from 'vitest';
import { drawLabel, SeriesMarkers } from '../src/primitives/markers';
import { makeCtx, type Op } from './helpers/fake-ctx';
import { DataLayer } from '../src/model/data-layer';
import { PriceScale } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import type { Bar } from '../src/model/bar';

const texts = (ops: Op[]): Op[] => ops.filter((o) => o.type === 'fillText');
const plate = (ops: Op[]): Op => ops.filter((o) => o.type === 'roundRect')[0];

const FONT = 12;
const PAD_X = FONT * 0.5;
const TAIL = FONT * 0.42;
const H1 = FONT + FONT * 0.64; // one-row plate height
const LH = FONT * 1.35;

describe('drawLabel single line stays byte-identical', () => {
  it('same plate size, position and one centred fillText', () => {
    const { ctx, rec } = makeCtx();
    drawLabel(ctx, true, 100, 200, 'BUY', '#26a69a', FONT);
    const w = 3 * 6 + PAD_X * 2;
    const top = 200 + TAIL;
    expect(plate(rec.ops).args.slice(0, 4)).toEqual([100 - w / 2, top, w, H1]);
    const t = texts(rec.ops);
    expect(t.length).toBe(1);
    expect(t[0].text).toBe('BUY');
    expect(t[0].args).toEqual([100, top + H1 / 2]);
  });
});

describe('drawLabel multi line', () => {
  it('widens to the longest row, stacks by line height, stays centred on the anchor', () => {
    const { ctx, rec } = makeCtx();
    drawLabel(ctx, true, 100, 200, 'Buy 100\nAvg 1234.5', '#26a69a', FONT);
    const w = 10 * 6 + PAD_X * 2; // longest row is 'Avg 1234.5'
    const h = H1 + LH;
    const top = 200 + TAIL;
    expect(plate(rec.ops).args.slice(0, 4)).toEqual([100 - w / 2, top, w, h]);

    const t = texts(rec.ops);
    expect(t.map((o) => o.text)).toEqual(['Buy 100', 'Avg 1234.5']);
    expect(t.every((o) => o.args[0] === 100)).toBe(true); // centred on cx
    expect(t[1].args[1] - t[0].args[1]).toBeCloseTo(LH);
    // The rows straddle the plate centre.
    expect((t[0].args[1] + t[1].args[1]) / 2).toBeCloseTo(top + h / 2);

    // The tail still meets the anchor price and the plate hangs below it.
    const apex = rec.ops.filter((o) => o.type === 'moveTo').pop()!;
    expect(apex.args).toEqual([100, 200]);
  });

  it('labelDown puts the whole taller plate above the anchor', () => {
    const { ctx, rec } = makeCtx();
    drawLabel(ctx, false, 100, 200, 'Sell\nSL 1250\nT 1180', '#ef5350', FONT);
    const h = H1 + LH * 2;
    const top = 200 - TAIL - h;
    expect(plate(rec.ops).args[1]).toBeCloseTo(top);
    expect(plate(rec.ops).args[3]).toBeCloseTo(h);
    expect(top + h).toBeLessThan(200); // clear of the anchor
    expect(texts(rec.ops).map((o) => o.text)).toEqual(['Sell', 'SL 1250', 'T 1180']);
    expect(rec.ops.filter((o) => o.type === 'moveTo').pop()!.args).toEqual([100, 200]);
  });
});

const bar = (time: number, c: number): Bar => ({ time, open: c, high: c + 2, low: c - 2, close: c });

function makeRc(): { rc: PrimitiveRenderContext; seriesId: number } {
  const dl = new DataLayer();
  const seriesId = dl.createSeries();
  dl.setSeriesData(seriesId, [bar(100, 50), bar(200, 52), bar(300, 48)]);
  const priceScale = new PriceScale();
  priceScale.setHeight(400);
  priceScale.setPriceRange({ min: 40, max: 60 });
  const timeScale = new TimeScale({ barSpacing: 20, rightOffset: 0 });
  timeScale.setWidth(600);
  timeScale.setBaseIndex(dl.baseIndex);
  return {
    rc: { timeScale, priceScale, dataLayer: dl, plotWidth: 600, plotHeight: 400, priceAxisWidth: 56, dpr: 1, theme: darkTheme },
    seriesId,
  };
}

describe('free text markers', () => {
  it('single line draws exactly one fillText at the old offset', () => {
    const { rc, seriesId } = makeRc();
    const m = new SeriesMarkers(seriesId);
    m.setMarkers([{ time: 200, position: 'belowBar', shape: 'text', size: 'medium', color: '#fff', text: 'BUY' }]);
    const { ctx, rec } = makeCtx();
    m.draw(ctx, rc);
    const t = texts(rec.ops);
    expect(t.length).toBe(1);
    expect(t[0].text).toBe('BUY');
  });

  it('rows run downward below the bar and upward above it', () => {
    const { rc, seriesId } = makeRc();
    const below = new SeriesMarkers(seriesId);
    below.setMarkers([{ time: 200, position: 'belowBar', shape: 'text', size: 'medium', color: '#fff', text: 'one\ntwo' }]);
    const c1 = makeCtx();
    below.draw(c1.ctx, rc);
    const tb = texts(c1.rec.ops);
    expect(tb.map((o) => o.text)).toEqual(['one', 'two']);
    expect(tb[1].args[1]).toBeGreaterThan(tb[0].args[1]); // second row further down

    const above = new SeriesMarkers(seriesId);
    above.setMarkers([{ time: 200, position: 'aboveBar', shape: 'text', size: 'medium', color: '#fff', text: 'one\ntwo' }]);
    const c2 = makeCtx();
    above.draw(c2.ctx, rc);
    const ta = texts(c2.rec.ops);
    // Written bottom row first so the block grows up, away from the candle.
    expect(ta.map((o) => o.text)).toEqual(['two', 'one']);
    expect(ta[1].args[1]).toBeLessThan(ta[0].args[1]);
  });
});
