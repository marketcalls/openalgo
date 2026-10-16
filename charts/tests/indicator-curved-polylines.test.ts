import { describe, expect, it } from 'vitest';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import type { IndicatorDrawing } from '../src/model/indicator-registry';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { SvgContext } from '../src/render/svg-export';
import { darkTheme } from '../src/theme';
import { makeCtx, type Op } from './helpers/fake-ctx';

type Polyline = Extract<IndicatorDrawing, { kind: 'polyline' }> & { curve?: 'linear' | 'smooth' };
const points = (...xy: number[][]) => xy.map(([time, price]) => ({ time, price }));
const anchors = points([0, 120], [60, 60], [120, 120]);
const context = (dpr = 1, mapPrice: (n: number) => number = n => n): PrimitiveRenderContext => ({
  timeScale: { indexToX: (n: number) => n },
  priceScale: { priceToY: mapPrice },
  dataLayer: { timeToIndexFloat: (n: number) => n },
  plotWidth: 240, plotHeight: 180, priceAxisWidth: 60, dpr, theme: darkTheme,
} as unknown as PrimitiveRenderContext);

function draw(item: Polyline, rc = context()): Op[] {
  const primitive = new IndicatorDrawings();
  primitive.setItems([item]);
  const { ctx, rec } = makeCtx();
  primitive.draw(ctx, rc);
  return rec.ops;
}
const paths = (ops: Op[]) => ops.filter(op => ['moveTo', 'lineTo', 'bezierCurveTo', 'closePath'].includes(op.type));
const curves = (ops: Op[]) => ops.filter(op => op.type === 'bezierCurveTo').map(op => op.args);

describe('curved study polylines', () => {
  it('interpolates three anchors with the declared endpoint and interior tangents', () => {
    expect(curves(draw({ kind: 'polyline', points: anchors, curve: 'smooth' }))).toEqual([
      [10, 110, 40, 60, 60, 60],
      [80, 60, 110, 110, 120, 120],
    ]);
  });

  it('preserves the exact straight default and explicit linear path', () => {
    const ordinary: Polyline = { kind: 'polyline', points: anchors, closed: true, fillColor: '#abc' };
    expect(draw({ ...ordinary, curve: 'linear' })).toEqual(draw(ordinary));
    expect(paths(draw(ordinary)).map(op => [op.type, op.args])).toEqual([
      ['moveTo', [0, 120]], ['lineTo', [60, 60]], ['lineTo', [120, 120]], ['closePath', []],
    ]);
  });

  it('keeps two distinct anchors straight even when smooth is requested', () => {
    expect(paths(draw({ kind: 'polyline', points: anchors.slice(0, 2), curve: 'smooth' })).map(op => op.type))
      .toEqual(['moveTo', 'lineTo']);
  });

  it('collapses consecutive duplicates without adding loops', () => {
    expect(paths(draw({ kind: 'polyline', points: [anchors[0], anchors[0], anchors[1], anchors[1], anchors[2]], curve: 'smooth' })))
      .toEqual(paths(draw({ kind: 'polyline', points: anchors, curve: 'smooth' })));
  });

  it('omits a collapsed single-point path', () => {
    expect(draw({ kind: 'polyline', points: [anchors[0], anchors[0]], curve: 'smooth' }).some(op => op.type === 'stroke')).toBe(false);
  });

  it('wraps tangents across a closed seam and ignores a repeated endpoint', () => {
    const shape: Polyline = { kind: 'polyline', points: points([0, 60], [60, 0], [120, 60]), curve: 'smooth', closed: true, fillColor: '#abc' };
    const result = draw(shape);
    expect(curves(result)).toEqual([
      [-10, 50, 40, 0, 60, 0],
      [80, 0, 130, 50, 120, 60],
      [110, 70, 10, 70, 0, 60],
    ]);
    expect(paths(draw({ ...shape, points: [...shape.points, shape.points[0]] }))).toEqual(paths(result));
    expect(result.filter(op => op.type === 'fill')).toHaveLength(1);
    expect(result.filter(op => op.type === 'closePath')).toHaveLength(1);
  });

  it('keeps overshoot visible when all anchors lie above the plot', () => {
    const result = draw({ kind: 'polyline', points: points([0, -100], [60, -1], [120, -1], [180, -100]), curve: 'smooth' });
    expect(curves(result)).toHaveLength(3);
    expect(curves(result)[1]).toEqual([80, 15.5, 100, 15.5, 120, -1]);
    expect(result.some(op => op.type === 'stroke')).toBe(true);
  });

  it('still culls a curve whose entire control hull is outside the plot', () => {
    expect(draw({ kind: 'polyline', points: points([0, -300], [60, -200], [120, -300]), curve: 'smooth' }).some(op => op.type === 'stroke')).toBe(false);
  });

  it('retains a thick stroke that crosses the plot boundary', () => {
    expect(draw({ kind: 'polyline', points: points([0, -2], [60, -2], [120, -2]), curve: 'smooth', lineWidth: 8 }).some(op => op.type === 'stroke')).toBe(true);
  });

  it('clips smooth stroke and fill to the measured plot', () => {
    const ops = draw({ kind: 'polyline', points: anchors, curve: 'smooth', fillColor: '#abc' }, context(2));
    expect(ops.find(op => op.type === 'rect')?.args).toEqual([0, 0, 480, 360]);
    expect(ops.filter(op => op.type === 'clip')).toHaveLength(1);
  });

  it('keeps an open return to the first anchor and does not close its stroke', () => {
    const ops = draw({ kind: 'polyline', points: [anchors[0], anchors[1], anchors[0]], curve: 'smooth', fillColor: '#abc' });
    expect(curves(ops)).toHaveLength(2);
    expect(curves(ops)[1].slice(-2)).toEqual([0, 120]);
    expect(ops.some(op => op.type === 'closePath')).toBe(false);
    expect(ops.filter(op => op.type === 'fill')).toHaveLength(1);
  });

  it('keeps nonconsecutive repeated anchors as separate segments', () => {
    const ops = draw({ kind: 'polyline', points: [anchors[0], anchors[1], anchors[0], anchors[1]], curve: 'smooth' });
    expect(curves(ops)).toHaveLength(3);
  });

  it('rejects a nonfinite time before a mapper can turn it into a finite coordinate', () => {
    const rc = context();
    rc.dataLayer = { timeToIndexFloat: () => 60 } as unknown as PrimitiveRenderContext['dataLayer'];
    expect(draw({ kind: 'polyline', points: points([0, 120], [NaN, 60], [120, 120]), curve: 'smooth' }, rc).some(op => op.type === 'stroke')).toBe(false);
  });

  it('omits a shape when a valid time maps to an unavailable screen coordinate', () => {
    const rc = context();
    rc.timeScale = { indexToX: (n: number) => n === 60 ? Infinity : n } as unknown as PrimitiveRenderContext['timeScale'];
    expect(draw({ kind: 'polyline', points: anchors, curve: 'smooth' }, rc).some(op => op.type === 'stroke')).toBe(false);
  });

  it.each([1, 1.5, 2])('maps through the scale before smoothing at DPR %s', dpr => {
    const result = draw({ kind: 'polyline', points: points([0, 1], [60, 100], [120, 1]), curve: 'smooth' }, context(dpr, n => 120 - 30 * Math.log10(n)));
    expect(curves(result)).toEqual([
      [10, 110, 40, 60, 60, 60].map(n => n * dpr),
      [80, 60, 110, 110, 120, 120].map(n => n * dpr),
    ]);
  });

  it.each([NaN, Infinity, -Infinity])('omits a path with an unavailable mapped anchor %s', missing => {
    for (const curve of ['linear', 'smooth'] as const) {
      const result = draw({ kind: 'polyline', points: points([0, 120], [60, missing], [120, 120]), curve });
      expect(result.some(op => op.type === 'stroke')).toBe(false);
      expect(paths(result)).toEqual([]);
    }
  });

  it('omits nonfinite generated controls without exporting them as zero', () => {
    const result = draw({ kind: 'polyline', points: points([-1e308, 20], [0, 30], [1e308, 20]), curve: 'smooth' });
    expect(result.some(op => op.type === 'stroke')).toBe(false);
  });

  it('uses the same cubic path for strict vector export', () => {
    const primitive = new IndicatorDrawings();
    primitive.setItems([{ kind: 'polyline', points: anchors, curve: 'smooth' } as Polyline]);
    const svg = new SvgContext(240, 180, { strict: true });
    primitive.draw(svg.asCanvasContext(), context());
    expect(svg.toString()).toContain('M0 120C10 110 40 60 60 60C80 60 110 110 120 120');
    expect(svg.unsupported).toEqual([]);
    primitive.setVisible(false);
    const hidden = new SvgContext(240, 180, { strict: true });
    primitive.draw(hidden.asCanvasContext(), context());
    expect(hidden.toString()).not.toContain('<path');
  });
});
