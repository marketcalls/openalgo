/**
 * IndicatorFill's gradient and per-bar colour (1.7.0). A flat two-colour band
 * must keep taking the original path, so the no-gradient case is pinned by
 * comparing the emitted polygon against the graded one.
 */
import { describe, expect, it } from 'vitest';
import { IndicatorFill } from '../src/primitives/indicator-fill';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx, type RecordingContext } from './helpers/fake-ctx';

/**
 * The gradient facts an assertion needs, read back off the recorded op stream.
 * A vertical gradient's meaning is where its axis sits, so the y extent is
 * kept beside the stops: identical stops at a different y are a different fill.
 */
interface Calls {
  translate: number[][];
  gradients: { y0: number; y1: number; stops: [number, string][] }[];
  fills: unknown[];
  path: number[][];
}

function read(rec: RecordingContext): Calls {
  const out: Calls = { translate: [], gradients: [], fills: [], path: [] };
  let current: { y0: number; y1: number; stops: [number, string][] } | null = null;
  for (const op of rec.ops) {
    if (op.type === 'translate') out.translate.push(op.args);
    else if (op.type === 'moveTo' || op.type === 'lineTo') out.path.push(op.args);
    else if (op.type === 'fill') out.fills.push(op.fillStyle);
    else if (op.type === 'createLinearGradient') {
      current = { y0: op.args[1], y1: op.args[3], stops: [] };
      out.gradients.push(current);
    } else if (op.type === 'addColorStop' && current !== null) {
      current.stops.push([op.args[0], op.text ?? '']);
    }
  }
  return out;
}

const DPR = 2;
const rc = {
  dpr: DPR,
  timeScale: { indexToX: (i: number) => i * 10 },
  priceScale: { priceToY: (v: number) => 100 - v },
} as unknown as PrimitiveRenderContext;

const flat = [
  { index: 0, a: 60, b: 40 },
  { index: 1, a: 60, b: 40 },
  { index: 2, a: 60, b: 40 },
];

describe('IndicatorFill gradient', () => {
  it('flat fill takes no gradient path at all', () => {
    const f = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    f.setPoints(flat);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.gradients).toHaveLength(0);
    expect(calls.translate).toHaveLength(0);
    expect(calls.fills).toEqual(['#0f0']);
  });

  it('anchors the stops to topValue/bottomValue in price space', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0',
      colorDown: '#f00',
      gradient: { topValue: 70, bottomValue: 30, topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints(flat);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    // y(70) = (100-70)*2 = 60, y(30) = (100-30)*2 = 140
    expect(calls.gradients).toHaveLength(1);
    expect([calls.gradients[0].y0, calls.gradients[0].y1]).toEqual([60, 140]);
    expect(calls.gradients[0].stops).toEqual([[0, '#aaa'], [1, '#bbb']]);
    expect(calls.fills).toHaveLength(1);
    expect(calls.fills[0]).not.toBe('#0f0');
  });

  it('spans the band\'s own extent when no values are given', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0',
      colorDown: '#f00',
      gradient: { topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints([...flat, { index: 3, a: null, b: null }, { index: 4, a: 90, b: 10 }, { index: 5, a: 90, b: 10 }]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    // max 90 -> y 20, min 10 -> y 180
    expect([calls.gradients[0].y0, calls.gradients[0].y1]).toEqual([20, 180]);
  });

  it('one value given, the other from the band', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topValue: 100, topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints(flat);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    // top pinned at 100 -> y 0; bottom from the band's low 40 -> y 120
    expect([calls.gradients[0].y0, calls.gradients[0].y1]).toEqual([0, 120]);
  });

  it('a degenerate band still paints', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints([{ index: 0, a: 50, b: 50 }, { index: 1, a: 50, b: 50 }]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.gradients[0].y1 - calls.gradients[0].y0).toBe(1);
    expect(calls.fills).toHaveLength(1);
  });

  it('gradient replaces both up and down colours across a crossing', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topValue: 60, bottomValue: 40, topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints([
      { index: 0, a: 60, b: 40 },
      { index: 1, a: 40, b: 60 },
      { index: 2, a: 40, b: 60 },
    ]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.fills).toHaveLength(2);
    expect(calls.fills).not.toContain('#0f0');
    expect(calls.fills).not.toContain('#f00');
    // same anchor for both runs: the shading does not restart per run
    expect(calls.gradients).toHaveLength(1);
    expect([calls.gradients[0].y0, calls.gradients[0].y1]).toEqual([80, 120]);
  });

  it('setOptions clears the gradient back to the flat fill', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints(flat);
    f.setOptions({ gradient: undefined });
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.gradients).toHaveLength(0);
    expect(calls.fills).toEqual(['#0f0']);
  });

  it('path geometry is unchanged by the gradient', () => {
    const a = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    const b = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topColor: '#aaa', bottomColor: '#bbb' },
    });
    a.setPoints(flat); b.setPoints(flat);
    const ca = makeCtx(); const cb = makeCtx();
    a.draw(ca.ctx, rc); b.draw(cb.ctx, rc);
    expect(read(cb.rec).path).toEqual(read(ca.rec).path);
  });
});

describe('IndicatorFill per-bar colour', () => {
  it('splits the run where the colour changes, sharing the bar edge', () => {
    const f = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    f.setPoints([
      { index: 0, a: 60, b: 40, color: '#111' },
      { index: 1, a: 60, b: 40, color: '#111' },
      { index: 2, a: 60, b: 40, color: '#222' },
      { index: 3, a: 60, b: 40, color: '#222' },
    ]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.fills).toEqual(['#111', '#222']);
    // The split bar (index 2 -> x 40) belongs to both runs, so no gap opens.
    const xs = calls.path.map((p) => p[0]);
    expect(xs.filter((v) => v === 40)).toHaveLength(4);
  });

  it('an uncoloured series is untouched', () => {
    const f = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    f.setPoints(flat);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.fills).toEqual(['#0f0']);
  });

  it('carries the colour across a crossing split', () => {
    const f = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    f.setPoints([
      { index: 0, a: 60, b: 40, color: '#111' },
      { index: 1, a: 40, b: 60, color: '#222' },
      { index: 2, a: 40, b: 60, color: '#222' },
    ]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.fills).toEqual(['#111', '#222']);
  });

  it('a point colour beats the gradient, the rest of the band still grades', () => {
    const f = new IndicatorFill({
      colorUp: '#0f0', colorDown: '#f00',
      gradient: { topValue: 70, bottomValue: 30, topColor: '#aaa', bottomColor: '#bbb' },
    });
    f.setPoints([
      { index: 0, a: 60, b: 40 },
      { index: 1, a: 60, b: 40 },
      { index: 2, a: 60, b: 40, color: '#333' },
      { index: 3, a: 60, b: 40, color: '#333' },
    ]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.gradients).toHaveLength(1);
    expect(calls.fills[1]).toBe('#333');
  });

  it('dropping back to no colour resumes up/down', () => {
    const f = new IndicatorFill({ colorUp: '#0f0', colorDown: '#f00' });
    f.setPoints([
      { index: 0, a: 60, b: 40, color: '#111' },
      { index: 1, a: 60, b: 40, color: '#111' },
      { index: 2, a: 60, b: 40 },
      { index: 3, a: 60, b: 40 },
    ]);
    const { ctx, rec } = makeCtx();
    f.draw(ctx, rc);
    const calls = read(rec);
    expect(calls.fills).toEqual(['#111', '#0f0']);
  });
});
