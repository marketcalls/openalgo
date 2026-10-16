/**
 * Per-bar colour (`Bar.color`) across the Family-A renderers, and the area
 * outline's line style. A single-colour series must still emit exactly one
 * stroke, so the fast path is pinned alongside the run splitting.
 */
import { describe, it, expect } from 'vitest';
import type { Bar } from '../src/model/bar';
import { drawLine, drawArea, type LineDrawItem } from '../src/render/line';
import { drawCandles, optimalBarWidth, type CandleStyle } from '../src/render/candles';
import { drawBars, drawColumns, type BarDrawItem } from '../src/render/bars';
import type { SeriesStyle } from '../src/render/series-style';

import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

const toY = (v: number): number => 100 - v;
const DPR = 1;

/** Value points, optionally coloured, at x = 10, 20, 30 ... */
const pts = (vals: readonly (readonly [number, string | undefined])[]): LineDrawItem[] =>
  vals.map(([v, color], i) => {
    const bar: Bar = { time: i, open: v, high: v, low: v, close: v };
    if (color !== undefined) bar.color = color;
    return { x: 10 + i * 10, bar };
  });

const strokes = (rec: RecordingContext): (string | undefined)[] =>
  rec.ops.filter((o) => o.type === 'stroke').map((o) => o.strokeStyle);

describe('line: per-point colour runs', () => {
  it('strokes once when every point shares one colour', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, pts([[1, undefined], [2, undefined], [3, undefined]]), toY, DPR, { color: '#abc' });
    expect(strokes(rec)).toEqual(['#abc']);
  });

  it('splits into one stroke per colour run, in order', () => {
    const { ctx, rec } = makeCtx();
    const items = pts([[1, '#f00'], [2, '#f00'], [3, '#0f0'], [4, '#0f0'], [5, '#00f']]);
    drawLine(ctx, items, toY, DPR, { color: '#abc' });
    // Segment 0->1 takes bar 1's colour (#f00), then #0f0 from bar 2, then #00f.
    expect(strokes(rec)).toEqual(['#f00', '#0f0', '#00f']);
  });

  it('restarts the next run from the shared point, so runs abut with no gap', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, pts([[1, '#f00'], [2, '#f00'], [3, '#0f0']]), toY, DPR, { color: '#abc' });
    const moves = rec.ops.filter((o) => o.type === 'moveTo').map((o) => o.args[0]);
    // Opening moveTo at x=10, then the seam re-anchors at x=20, the last point
    // of the red run and the first of the green one.
    expect(moves).toEqual([10, 20]);
  });

  it('falls back to the series colour for a point that names none', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, pts([[1, undefined], [2, '#f00'], [3, undefined]]), toY, DPR, { color: '#abc' });
    // Three points, two segments: the one arriving at the coloured bar, then
    // one arriving at a bar that names nothing and takes the series colour.
    expect(strokes(rec)).toEqual(['#f00', '#abc']);
  });

  it('colours both legs of a step with the arriving bar', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, pts([[1, '#f00'], [2, '#0f0']]), toY, DPR, { color: '#abc', step: true });
    // Two legs, one run: horizontal to x=20 then vertical, both green.
    expect(strokes(rec)).toEqual(['#0f0']);
    const lines = rec.ops.filter((o) => o.type === 'lineTo').map((o) => o.args);
    expect(lines).toEqual([[20, 99], [20, 98]]);
  });

  it('still breaks the line at a whitespace gap', () => {
    const { ctx, rec } = makeCtx();
    const items = pts([[1, '#f00'], [NaN, undefined], [3, '#f00']]);
    drawLine(ctx, items, toY, DPR, { color: '#abc' });
    const moves = rec.ops.filter((o) => o.type === 'moveTo').map((o) => o.args[0]);
    expect(moves).toEqual([10, 30]);
  });

  it('colours markers by their own bar', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, pts([[1, '#f00'], [2, undefined]]), toY, DPR, { color: '#abc', markersOnly: true });
    expect(rec.ops.filter((o) => o.type === 'fill').map((o) => o.fillStyle)).toEqual(['#f00', '#abc']);
  });
});

describe('area', () => {
  it('carries lineStyle to its outline', () => {
    const { ctx, rec } = makeCtx();
    drawArea(ctx, pts([[1, undefined], [2, undefined]]), toY, DPR, 100, { color: '#abc', lineStyle: 'dashed' });
    expect(rec.ops.some((o) => o.type === 'setLineDash' && o.args.length === 2)).toBe(true);
  });

  it('splits its outline on a per-bar colour', () => {
    const { ctx, rec } = makeCtx();
    drawArea(ctx, pts([[1, '#f00'], [2, '#0f0']]), toY, DPR, 100, { color: '#abc' });
    expect(strokes(rec)).toEqual(['#0f0']);
  });
});

const cs: CandleStyle = {
  upColor: '#u1', downColor: '#d1',
  borderUpColor: '#u2', borderDownColor: '#d2',
  wickUpColor: '#u3', wickDownColor: '#d3',
  borderVisible: true, wickVisible: true,
};
const BS = 8;
const WICK_W = 1;
const BODY_W = optimalBarWidth(BS, DPR);

describe('candles and bars honour Bar.color', () => {
  const bar = (o: number, h: number, l: number, c: number, color?: string): Bar => {
    const b: Bar = { time: 1, open: o, high: h, low: l, close: c };
    if (color !== undefined) b.color = color;
    return b;
  };

  it('overrides body, border and wick together', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, [{ x: 10, bar: bar(1, 4, 0, 3, '#ff0') }], toY, BS, DPR, cs);
    const wick = rec.ops.find((o) => o.type === 'fillRect' && o.args[2] === WICK_W);
    const body = rec.ops.find((o) => o.type === 'fillRect' && o.args[2] === BODY_W);
    const outline = rec.ops.find((o) => o.type === 'strokeRect');
    expect([wick?.fillStyle, body?.fillStyle, outline?.strokeStyle]).toEqual(['#ff0', '#ff0', '#ff0']);
  });

  it('leaves an uncoloured bar on the up/down pair', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, [{ x: 10, bar: bar(1, 4, 0, 3) }], toY, BS, DPR, cs);
    const body = rec.ops.find((o) => o.type === 'fillRect' && o.args[2] === BODY_W);
    expect(body?.fillStyle).toBe('#u1');
  });

  it('colours a hollow up candle by the override', () => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, [{ x: 10, bar: bar(1, 4, 0, 3, '#ff0') }], toY, BS, DPR, { ...cs, hollow: true });
    expect(rec.ops.find((o) => o.type === 'strokeRect')?.strokeStyle).toBe('#ff0');
  });

  it('paints an OHLC bar (range and both ticks) in the override', () => {
    const { ctx, rec } = makeCtx();
    const items: BarDrawItem[] = [{ x: 10, bar: bar(1, 4, 0, 3, '#ff0') }];
    drawBars(ctx, items, toY, BS, DPR, { upColor: '#u1', downColor: '#d1' });
    const fills = rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.fillStyle);
    expect(fills).toEqual(['#ff0', '#ff0', '#ff0']);
  });
});

describe('columns', () => {
  const item = (c: number, color?: string): BarDrawItem => {
    const b: Bar = { time: 1, open: 0, high: c, low: 0, close: c };
    if (color !== undefined) b.color = color;
    return { x: 10, bar: b };
  };
  const fills = (rec: RecordingContext): (string | undefined)[] =>
    rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.fillStyle);

  it('reads style.color', () => {
    const { ctx, rec } = makeCtx();
    const style: SeriesStyle = { color: '#c0c', upColor: '#u1', downColor: '#d1', base: 0 };
    drawColumns(ctx, [item(5)], toY, BS, DPR, style);
    expect(fills(rec)).toEqual(['#c0c']);
  });

  it('keeps the per-bar colour above style.color', () => {
    const { ctx, rec } = makeCtx();
    const style: SeriesStyle = { color: '#c0c', upColor: '#u1', downColor: '#d1', base: 0 };
    drawColumns(ctx, [item(5, '#ff0')], toY, BS, DPR, style);
    expect(fills(rec)).toEqual(['#ff0']);
  });

  it('falls back to the up/down pair when neither is set', () => {
    const { ctx, rec } = makeCtx();
    drawColumns(ctx, [item(5), item(-5)], toY, BS, DPR, { upColor: '#u1', downColor: '#d1', base: 0 });
    expect(fills(rec)).toEqual(['#u1', '#d1']);
  });
});
