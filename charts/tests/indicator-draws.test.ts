/**
 * The indicator drawings layer (src/primitives/indicator-draws.ts), the tier
 * that lets a descriptor annotate its own study with lines, boxes, labels and
 * polylines anchored in time and price.
 */
import { describe, it, expect } from 'vitest';
import { IndicatorDrawings } from '../src/primitives/indicator-draws';
import type { IndicatorDrawing } from '../src/model/indicator-registry';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { darkTheme } from '../src/theme';
import { makeCtx, type Op } from './helpers/fake-ctx';

// index i maps to time 1000 + i*60; x = index * 10; price maps y = 500 - price.
// Everything the primitive draws is in device px, so a non-unit dpr multiplies
// both axes and is worth its own pass.
const rcOf = (dpr: number): PrimitiveRenderContext => ({
  timeScale: { indexToX: (i: number) => i * 10 },
  priceScale: { priceToY: (p: number) => 500 - p },
  dataLayer: { timeToIndexFloat: (t: number) => (t - 1000) / 60 },
  plotWidth: 400, plotHeight: 300, priceAxisWidth: 60, dpr, theme: darkTheme,
} as unknown as PrimitiveRenderContext);
const rc = rcOf(1);

const at = (i: number, price: number) => ({ time: 1000 + i * 60, price });

function run(items: IndicatorDrawing[], dpr = 1): Op[] {
  const d = new IndicatorDrawings();
  d.setItems(items);
  const { ctx, rec } = makeCtx();
  d.draw(ctx, rcOf(dpr));
  return rec.ops;
}

const first = (ops: Op[], type: string): Op | undefined => ops.find((o) => o.type === type);
const textsOf = (ops: Op[]): (string | undefined)[] =>
  ops.filter((o) => o.type === 'fillText').map((o) => o.text);

describe('IndicatorDrawings', () => {
  it('maps a line anchor through the time and price scales', () => {
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260) }]);
    expect(first(ops, 'moveTo')?.args).toEqual([10, 250]);
    expect(first(ops, 'lineTo')?.args).toEqual([30, 240]);
  });

  it('extends a ray to the pane edges along its own slope', () => {
    // slope = (240 - 250) / (30 - 10) = -0.5 per device px
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260), extendLeft: true, extendRight: true }]);
    expect(first(ops, 'moveTo')?.args).toEqual([0, 255]);
    expect(first(ops, 'lineTo')?.args).toEqual([400, 55]);
  });

  it('extends one end only, leaving the other on its anchor', () => {
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260), extendRight: true }]);
    expect(first(ops, 'moveTo')?.args).toEqual([10, 250]);
    expect(first(ops, 'lineTo')?.args).toEqual([400, 55]);
  });

  it('spans the pane top to bottom when a vertical line is extended', () => {
    // No slope to follow, so either flag means the full height.
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(1, 200), extendRight: true }]);
    expect(first(ops, 'moveTo')?.args).toEqual([10, 0]);
    expect(first(ops, 'lineTo')?.args).toEqual([10, 300]);
  });

  it('converts anchors and line width to device pixels', () => {
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260), lineWidth: 2, lineStyle: 'dashed' }], 2);
    expect(first(ops, 'moveTo')?.args).toEqual([20, 500]);
    expect(first(ops, 'lineTo')?.args).toEqual([60, 480]);
    expect(first(ops, 'stroke')?.lineWidth).toBe(4);
    expect(ops.filter((o) => o.type === 'setLineDash').map((o) => o.args)).toContainEqual([12, 8]);
  });

  it('culls a shape entirely off-pane', () => {
    const ops = run([{ kind: 'box', from: at(80, 250), to: at(90, 260) }]);
    expect(ops.some((o) => o.type === 'strokeRect')).toBe(false);
  });

  it('culls a label on its anchor, once it is past the plate margin', () => {
    const ops = run([{ kind: 'label', at: at(70, 250), text: 'off' }]);
    expect(textsOf(ops)).toEqual([]);
  });

  it('draws a box with a fill and a centred multi-line caption', () => {
    const ops = run([{ kind: 'box', from: at(1, 250), to: at(3, 260), fillColor: '#f00', text: 'A\nBB' }]);
    expect(first(ops, 'fillRect')?.args).toEqual([10, 240, 20, 10]);
    expect(textsOf(ops)).toEqual(['A', 'BB']);
  });

  it('draws a box as an outline when no fill colour is given', () => {
    const ops = run([{ kind: 'box', from: at(1, 250), to: at(3, 260), color: '#0af' }]);
    expect(ops.some((o) => o.type === 'fillRect')).toBe(false);
    expect(first(ops, 'strokeRect')?.args).toEqual([10, 240, 20, 10]);
    expect(first(ops, 'strokeRect')?.strokeStyle).toBe('#0af');
  });

  it('sizes a label plate to its widest line', () => {
    const ops = run([{ kind: 'label', at: at(2, 250), text: 'x\nlonger' }]);
    expect(textsOf(ops)).toEqual(['x', 'longer']);
    // widest line 'longer' = 36 px + 2*5 padding = 46, centred on x = 20.
    // roundRectPath falls back to `rect` where the context has no roundRect,
    // and both carry the plate rect in the same first four arguments.
    const plate = ops.filter((o) => o.type === 'roundRect' || o.type === 'rect')[0];
    expect(plate.args[0]).toBeCloseTo(20 - 46 / 2);
    expect(plate.args[2]).toBeCloseTo(46);
  });

  it('puts a label plate edge on the anchor when aligned', () => {
    const w = 2 * 6 + 5 * 2; // 'ab' at the fake 6 px per character, plus padding
    const left = run([{ kind: 'label', at: at(2, 250), text: 'ab', align: 'left' }]);
    const right = run([{ kind: 'label', at: at(2, 250), text: 'ab', align: 'right' }]);
    const plateX = (ops: Op[]): number => ops.filter((o) => o.type === 'roundRect' || o.type === 'rect')[0].args[0];
    expect(plateX(left)).toBeCloseTo(20);
    expect(plateX(right)).toBeCloseTo(20 - w);
  });

  it('walks a polyline and closes it when asked', () => {
    const ops = run([{ kind: 'polyline', points: [at(0, 250), at(1, 255), at(2, 240)], closed: true, fillColor: '#0f0' }]);
    expect(first(ops, 'moveTo')?.args).toEqual([0, 250]);
    expect(ops.filter((o) => o.type === 'lineTo').map((o) => o.args)).toEqual([[10, 245], [20, 260]]);
    expect(ops.some((o) => o.type === 'closePath')).toBe(true);
    expect(ops.some((o) => o.type === 'fill')).toBe(true);
  });

  it('leaves a one-point polyline undrawn', () => {
    const ops = run([{ kind: 'polyline', points: [at(1, 250)] }]);
    expect(ops.some((o) => o.type === 'stroke')).toBe(false);
  });

  it('draws nothing while hidden', () => {
    const d = new IndicatorDrawings();
    d.setItems([{ kind: 'line', from: at(1, 250), to: at(3, 260) }]);
    d.setVisible(false);
    const { ctx, rec } = makeCtx();
    d.draw(ctx, rc);
    expect(rec.ops).toHaveLength(0);
  });

  it('applies a dash pattern for a dashed line style', () => {
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260), lineStyle: 'dashed' }]);
    expect(ops.filter((o) => o.type === 'setLineDash').map((o) => o.args)).toContainEqual([6, 4]);
  });

  it('leaves the dash empty for a solid line', () => {
    const ops = run([{ kind: 'line', from: at(1, 250), to: at(3, 260) }]);
    const dash = ops.filter((o) => o.type === 'setLineDash');
    expect(dash.every((o) => o.args.length === 0)).toBe(true);
  });
});
