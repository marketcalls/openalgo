/**
 * The segment a line-family renderer draws to a neighbour beyond the view
 * (src/render/line.ts, `trimToView`; the neighbour is `DrawItem.edgeX`).
 *
 * A sparse line's neighbour can sit millions of pixels off screen: a level
 * held for a session on an axis that also carries a five-second series. The
 * segment to it used to be stroked out to that point on every frame, and the
 * GPU backend built a quad for every dash of the off-screen length. The
 * renderers now cut that segment at the view, with a margin wider than any
 * cap or join they paint, before they stroke or fill it.
 *
 * The dash phase is the other half. 2.5.8 started the path at the first bar
 * in view, so its dash pattern began there. Starting the path at the cut
 * instead would slide every dash along the visible line. The cut is placed a
 * whole number of dash periods back from the first bar in view, so the dashes
 * from that bar on are exactly where 2.5.8 put them and only the added edge
 * segment is new.
 */
import { describe, it, expect } from 'vitest';
import { makeCtx, type Op } from './helpers/fake-ctx';
import { drawLine, drawArea, drawBaseline, drawHlcArea } from '../src/render/line';
import { drawKagi } from '../src/render/kagi';
import type { DrawItem } from '../src/model/chart-type-registry';
import type { SeriesStyle } from '../src/render/series-style';
import type { Bar } from '../src/model/bar';

const toY = (v: number): number => 400 - v * 2;
const bar = (v: number, color?: string): Bar => ({ time: 0, open: v, high: v + 4, low: v - 4, close: v, ...(color === undefined ? {} : { color }) });

/** The plot these items are drawn for, in media px. */
const PLOT = 800;

/** A far left neighbour, three bars in view and a far right neighbour. */
function sparse(far = 1e7): DrawItem[] {
  return [
    { x: -far, bar: bar(60), edgeX: 0 },
    { x: 120, bar: bar(100) },
    { x: 400, bar: bar(110) },
    { x: 610, bar: bar(95) },
    { x: PLOT + far, bar: bar(130), edgeX: PLOT },
  ];
}

/** Every x a path op or a gradient named, in device px. */
function pathXs(ops: readonly Op[]): number[] {
  return ops.filter((o) => o.type === 'moveTo' || o.type === 'lineTo' || o.type === 'arc').map((o) => o.args[0]);
}

/** The path ops as [type, x, y]. */
function path(ops: readonly Op[]): [string, number, number][] {
  return ops.filter((o) => o.type === 'moveTo' || o.type === 'lineTo').map((o) => [o.type, o.args[0], o.args[1]]);
}

/** How far outside the plot a cut may land: the renderer's margin plus one dash period. */
const REACH = 64;

function expectInsideView(ops: readonly Op[], dpr: number): void {
  const xs = pathXs(ops);
  expect(xs.length).toBeGreaterThan(0);
  for (const x of xs) {
    expect(x, 'a path point far outside the plot').toBeGreaterThanOrEqual(-REACH * dpr);
    expect(x, 'a path point far outside the plot').toBeLessThanOrEqual((PLOT + REACH) * dpr);
  }
}

const DASH_PERIOD: Record<string, number> = { dashed: 10, dotted: 4 };

describe('a line-family segment to a neighbour beyond the view', () => {
  it('is cut at the view before it is stroked, for every line style and ratio', () => {
    for (const dpr of [1, 2]) {
      for (const lineStyle of ['solid', 'dashed', 'dotted'] as const) {
        for (const step of [false, true]) {
          const { ctx, rec } = makeCtx();
          drawLine(ctx, sparse(), toY, dpr, { lineStyle, step });
          expectInsideView(rec.ops, dpr);
          // It still crosses the plot from edge to edge: the line enters at the left and leaves at the right.
          const xs = pathXs(rec.ops);
          expect(Math.min(...xs)).toBeLessThan(0);
          expect(Math.max(...xs)).toBeGreaterThan(PLOT * dpr);
        }
      }
    }
  });

  it('keeps the cut on the line to the neighbour, so the visible part does not bend', () => {
    const items = sparse();
    const { ctx, rec } = makeCtx();
    drawLine(ctx, items, toY, 1, {});
    const p = path(rec.ops);
    const [, x0, y0] = p[0];
    const [, x1, y1] = p[1];
    // Collinear with the first bar in view and the real neighbour.
    const ax = items[0].x, ay = toY(items[0].bar.close);
    const cross = (x1 - ax) * (y0 - ay) - (y1 - ay) * (x0 - ax);
    expect(Math.abs(cross) / Math.hypot(x1 - ax, y1 - ay)).toBeLessThan(1e-6);
    expect(x1).toBe(120);
    // And the right end sits on the line to the right neighbour.
    const [, xr, yr] = p[p.length - 1];
    const [, xp, yp] = p[p.length - 2];
    const bx = items[4].x, by = toY(items[4].bar.close);
    const crossR = (bx - xp) * (yr - yp) - (by - yp) * (xr - xp);
    expect(Math.abs(crossR) / Math.hypot(bx - xp, by - yp)).toBeLessThan(1e-6);
  });

  it('starts the dash pattern at the first bar in view, as 2.5.8 did', () => {
    for (const dpr of [1, 2]) {
      for (const lineStyle of ['dashed', 'dotted'] as const) {
        for (const far of [1e7, 37.3, 3.9]) {
          const items = sparse(far);
          const { ctx, rec } = makeCtx();
          drawLine(ctx, items, toY, dpr, { lineStyle });
          const p = path(rec.ops);
          expect(p[0][0]).toBe('moveTo');
          // The path runs straight from where it starts to the first bar in
          // view, and the bars in view go on as a subpath of their own from
          // there, which is where 2.5.8's path began.
          expect(p[1][1]).toBe(120 * dpr);
          expect(p[2]).toEqual(['moveTo', 120 * dpr, toY(100) * dpr]);
          const lead = Math.hypot(p[1][1] - p[0][1], p[1][2] - p[0][2]);
          const period = DASH_PERIOD[lineStyle] * dpr;
          const phase = lead / period - Math.round(lead / period);
          expect(Math.abs(phase), `${lineStyle} at ${far} px, ratio ${dpr}: ${lead} px before the first bar`).toBeLessThan(1e-9);
          expect(lead).toBeGreaterThan(0);
        }
      }
    }
  });

  it('starts a step line\'s dash pattern at its first bar in view, after the horizontal and the vertical leg', () => {
    for (const [lineStyle, far] of [['dashed', 9_999_997.3], ['dotted', 41.7], ['dashed', 3.1]] as const) {
      const items = sparse(far);
      const { ctx, rec } = makeCtx();
      drawLine(ctx, items, toY, 1, { lineStyle, step: true });
      const p = path(rec.ops);
      // Horizontal at the neighbour's level to the first bar's x, then up to its value.
      expect(p[0][2]).toBe(toY(60));
      expect(p[1]).toEqual(['lineTo', 120, toY(60)]);
      expect(p[2]).toEqual(['lineTo', 120, toY(100)]);
      const lead = (p[1][1] - p[0][1]) + Math.abs(p[2][2] - p[1][2]);
      const period = DASH_PERIOD[lineStyle];
      expect(Math.abs(lead / period - Math.round(lead / period))).toBeLessThan(1e-9);
    }
  });

  it('strokes a dashed line\'s legs beyond the view apart from the bars\' own path, which is the one drawn without them', () => {
    for (const dpr of [1, 2]) {
      for (const [lineStyle, step] of [['dashed', false], ['dotted', false], ['dashed', true]] as const) {
        const style: SeriesStyle = { lineStyle, step };
        const offsets: number[] = [];
        const { ctx, rec } = makeCtx();
        const stroke = rec.stroke.bind(rec);
        rec.stroke = (): void => { offsets.push((rec as unknown as { lineDashOffset?: number }).lineDashOffset ?? 0); stroke(); };
        drawLine(ctx, sparse(), toY, dpr, style);
        // The leg in, the bars in view, the leg out: three strokes.
        const strokes = rec.ops.map((o, i) => (o.type === 'stroke' ? i : -1)).filter((i) => i >= 0);
        expect(strokes).toHaveLength(3);
        // The middle one is, op for op, the path drawn for the bars in view alone.
        const alone = makeCtx();
        drawLine(alone.ctx, sparse().slice(1, -1), toY, dpr, style);
        const middle = path(rec.ops.slice(strokes[0] + 1, strokes[1] + 1));
        expect(middle).toEqual(path(alone.rec.ops));
        // The leg out carries the pattern on from where the bars' path left it.
        let walked = 0;
        for (let i = 1; i < middle.length; i++) walked += Math.hypot(middle[i][1] - middle[i - 1][1], middle[i][2] - middle[i - 1][2]);
        expect(offsets[0]).toBe(0);
        expect(offsets[1]).toBe(0);
        expect(offsets[2]).toBeCloseTo(walked, 6);
      }
    }
  });

  it('keeps a solid line\'s legs in its one stroke, so a translucent line has no seam', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, sparse(), toY, 1, { color: 'rgba(64,160,255,0.5)' });
    expect(rec.count('stroke')).toBe(1);
    expect(rec.count('beginPath')).toBe(1);
  });

  it('leaves a solid line\'s near neighbour exactly where it is', () => {
    const items: DrawItem[] = [
      { x: -7, bar: bar(60), edgeX: 0 },
      { x: 1, bar: bar(100) },
      { x: 9, bar: bar(110) },
    ];
    const { ctx, rec } = makeCtx();
    drawLine(ctx, items, toY, 1, {});
    expect(path(rec.ops)[0]).toEqual(['moveTo', -7, toY(60)]);
  });

  it('drops the segment when the first bar in view is itself past the margin', () => {
    // Zoomed in far enough that the bar partly in view sits 60 px left of the plot.
    const items: DrawItem[] = [
      { x: -140, bar: bar(60), edgeX: 0 },
      { x: -60, bar: bar(100) },
      { x: 20, bar: bar(110) },
    ];
    for (const lineStyle of ['solid', 'dashed'] as const) {
      const { ctx, rec } = makeCtx();
      drawLine(ctx, items, toY, 1, { lineStyle });
      expect(path(rec.ops)[0]).toEqual(['moveTo', -60, toY(100)]);
    }
  });

  it('draws no marker on a neighbour beyond the view', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, sparse(), toY, 1, { markers: true });
    const arcs = rec.ops.filter((o) => o.type === 'arc').map((o) => o.args[0]);
    expect(arcs).toEqual([120, 400, 610]);
  });

  it('crosses the whole plot when no bar of the series is in view', () => {
    const items: DrawItem[] = [
      { x: -5e6, bar: bar(60), edgeX: 0 },
      { x: PLOT + 3e6, bar: bar(120), edgeX: PLOT },
    ];
    for (const style of [{}, { lineStyle: 'dashed' }, { step: true, lineStyle: 'dotted' }] as SeriesStyle[]) {
      const { ctx, rec } = makeCtx();
      drawLine(ctx, items, toY, 1, style);
      expectInsideView(rec.ops, 1);
      const xs = pathXs(rec.ops);
      expect(Math.min(...xs)).toBeLessThan(0);
      expect(Math.max(...xs)).toBeGreaterThan(PLOT);
    }
  });

  it('draws nothing for a lone neighbour with nothing to join it to', () => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, [{ x: -5e6, bar: bar(60), edgeX: 0 }], toY, 1, { markers: true });
    expect(path(rec.ops)).toEqual([]);
    expect(rec.count('arc')).toBe(0);
  });

  it('keeps the colour of the segment arriving at the first bar in view', () => {
    const items = sparse();
    items[1] = { x: 120, bar: bar(100, '#00ff00') };
    items[2] = { x: 400, bar: bar(110, '#ff0000') };
    const { ctx, rec } = makeCtx();
    drawLine(ctx, items, toY, 1, { lineStyle: 'dashed', color: '#123456' });
    const strokes = rec.ops.filter((o) => o.type === 'stroke').map((o) => o.strokeStyle);
    expect(strokes[0]).toBe('#00ff00');
    expect(strokes[1]).toBe('#ff0000');
    expectInsideView(rec.ops, 1);
  });

  it('cuts an area\'s fill and outline, a baseline and an HLC band the same way', () => {
    for (const dpr of [1, 2]) {
      const area = makeCtx();
      drawArea(area.ctx, sparse(), toY, dpr, 300, { lineStyle: 'dashed' });
      expectInsideView(area.rec.ops, dpr);
      const baseline = makeCtx();
      drawBaseline(baseline.ctx, sparse(), toY, dpr, { baseValue: 100 });
      expectInsideView(baseline.rec.ops, dpr);
      // The clip rectangles a baseline fills through start and end at the cut too.
      for (const r of baseline.rec.ops.filter((o) => o.type === 'rect')) {
        expect(r.args[0]).toBeGreaterThanOrEqual(-REACH * dpr);
        expect(r.args[0] + r.args[2]).toBeLessThanOrEqual((PLOT + REACH) * dpr);
      }
      const hlc = makeCtx();
      drawHlcArea(hlc.ctx, sparse(), toY, dpr, { highColor: '#ff0000', lowColor: '#0000ff' });
      expectInsideView(hlc.rec.ops, dpr);
    }
  });

  it('keeps an HLC band\'s two edges on the same x at the cut', () => {
    const { ctx, rec } = makeCtx();
    drawHlcArea(ctx, sparse(), toY, 1, {});
    // The band: highs left to right, then lows right to left, one point per bar in reach.
    const p = path(rec.ops);
    const band = p.slice(0, 1 + 5 + 5);
    const highs = band.slice(1, 6).map(([, x]) => x);
    const lows = band.slice(6).map(([, x]) => x).reverse();
    expect(highs).toEqual(lows);
  });
});

/**
 * A study's plot stores a bar with no value as NaN (a warm-up, the dormant
 * half of a trend study), so the neighbour beyond an edge is the plot's own
 * next point, value or not. When a gap sits at the edge, that neighbour or
 * the bar in view next to it has no value, and nothing may join across it:
 * the line breaks, and a fill must not reach out from the plot edge either
 * (an area, a baseline or a band would otherwise shade from the edge to the
 * first value in view, or across the gap to the next one).
 */
describe('a gap at the edge of the view', () => {
  const gap = (): Bar => ({ time: 0, open: NaN, high: NaN, low: NaN, close: NaN });
  /** The neighbours beyond both edges are gaps. */
  const gapBeyond = (): DrawItem[] => [
    { x: -1e7, bar: gap(), edgeX: 0 },
    { x: 120, bar: bar(100) },
    { x: 400, bar: bar(110) },
    { x: 610, bar: bar(95) },
    { x: PLOT + 1e7, bar: gap(), edgeX: PLOT },
  ];
  /** The neighbours have values; the first and last bars in view are gaps. */
  const gapWithin = (): DrawItem[] => [
    { x: -1e7, bar: bar(60), edgeX: 0 },
    { x: 120, bar: gap() },
    { x: 400, bar: bar(110) },
    { x: 530, bar: bar(104) },
    { x: 610, bar: gap() },
    { x: PLOT + 1e7, bar: bar(130), edgeX: PLOT },
  ];
  /** What a canvas actually draws: it ignores a point with a coordinate that is not finite. */
  const drawn = (ops: readonly Op[]): string[] => ops
    .filter((o) => ['moveTo', 'lineTo', 'rect', 'stroke', 'fill', 'clip'].includes(o.type))
    .filter((o) => o.args.every(Number.isFinite))
    .map((o) => `${o.type} ${o.args.join(' ')}`);
  const renderers: [string, (ctx: CanvasRenderingContext2D, items: DrawItem[]) => void][] = [
    ['line', (ctx, items) => drawLine(ctx, items, toY, 1, {})],
    ['dashed line', (ctx, items) => drawLine(ctx, items, toY, 1, { lineStyle: 'dashed' })],
    ['area', (ctx, items) => drawArea(ctx, items, toY, 1, 300, {})],
    ['baseline', (ctx, items) => drawBaseline(ctx, items, toY, 1, { baseValue: 100 })],
    ['HLC band', (ctx, items) => drawHlcArea(ctx, items, toY, 1, { highColor: '#ff0000', lowColor: '#0000ff' })],
  ];

  it('is never bridged: every renderer draws what the bars in view draw on their own', () => {
    for (const [name, items] of [['beyond', gapBeyond()], ['within', gapWithin()]] as const) {
      for (const [label, draw] of renderers) {
        const edged = makeCtx();
        draw(edged.ctx, items);
        const alone = makeCtx();
        draw(alone.ctx, items.slice(1, -1));
        expect(drawn(edged.rec.ops), `${label}, gap ${name} the view`).toEqual(drawn(alone.rec.ops));
      }
    }
  });

  it('holds a step\'s last value out to a neighbour that is a gap, and draws nothing from one on the left', () => {
    // A step holds its value until the next bar, gap or not, as it does in
    // view; that is not a bridge. A gap on the left has no value to hold.
    const finite = (ops: readonly Op[]): [string, number, number][] => path(ops).filter(([, x, y]) => Number.isFinite(x) && Number.isFinite(y));
    for (const lineStyle of ['solid', 'dashed'] as const) {
      const edged = makeCtx();
      drawLine(edged.ctx, gapBeyond(), toY, 1, { step: true, lineStyle });
      const alone = makeCtx();
      drawLine(alone.ctx, gapBeyond().slice(1, -1), toY, 1, { step: true, lineStyle });
      const want = finite(alone.rec.ops), got = finite(edged.rec.ops);
      expect(got.slice(0, want.length)).toEqual(want);
      expect(got[got.length - 1]).toEqual(['lineTo', PLOT + 9.5, toY(95)]);
    }
  });

  it('holds a step at the neighbour\'s level up to a first bar in view that is a gap, on a leg of its own anchored to that bar', () => {
    // A step holds its value until the next bar, gap or not, as it does in
    // view; that is not a bridge. The hold is a stroke of its own, a whole
    // number of dash periods long from the corner under the gap, so its
    // dashes move with the bars as the view pans, not with the plot edge.
    for (const far of [1e7, 23.7]) {
      const items = gapWithin();
      items[0].x = -far;
      const { ctx, rec } = makeCtx();
      drawLine(ctx, items, toY, 1, { step: true, lineStyle: 'dashed' });
      const p = path(rec.ops);
      expect(p[0][2]).toBe(toY(60));
      expect(p[1]).toEqual(['lineTo', 120, toY(60)]);
      const lead = p[1][1] - p[0][1];
      expect(Math.abs(lead / 10 - Math.round(lead / 10)), `${lead} px before the gap`).toBeLessThan(1e-9);
      // The hold is stroked before anything else is drawn.
      const first = rec.ops.findIndex((o) => o.type === 'stroke');
      expect(path(rec.ops.slice(0, first))).toEqual(p.slice(0, 2));
    }
  });
});

describe('kagi joins its vertices across the view edge too', () => {
  it('cuts the connector to a neighbour beyond the view', () => {
    const items: DrawItem[] = [
      { x: -2e7, bar: { ...bar(60), volume: 1 }, edgeX: 0 },
      { x: 200, bar: { ...bar(100), volume: 0 } },
      { x: 500, bar: { ...bar(80), volume: 1 } },
      { x: PLOT + 2e7, bar: { ...bar(120), volume: 1 }, edgeX: PLOT },
    ];
    const { ctx, rec } = makeCtx();
    drawKagi(ctx, items, toY, 1, {});
    expectInsideView(rec.ops, 1);
    const p = path(rec.ops);
    // The first connector runs at the neighbour's level from the left of the plot to the first vertex.
    expect(p[0][1]).toBeLessThan(0);
    expect(p[0][2]).toBe(toY(60));
    expect(p[1]).toEqual(['lineTo', 200, toY(60)]);
    // The last one leaves the plot at the right at the last vertex's level, and turns nowhere.
    const last = p[p.length - 1];
    expect(last[1]).toBeGreaterThan(PLOT);
    expect(last[2]).toBe(toY(80));
  });
});
