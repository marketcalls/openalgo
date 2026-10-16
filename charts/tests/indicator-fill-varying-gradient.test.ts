import { describe, expect, it } from 'vitest';
import { IndicatorFill, type FillGradient, type FillPoint } from '../src/primitives/indicator-fill';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';
import { makeCtx } from './helpers/fake-ctx';

const colors = { topColor: '#ff0000', bottomColor: '#0000ff' };
const gradient = (topValue = 80, bottomValue = 60): FillGradient => ({ ...colors, topValue, bottomValue });
const point = (index: number, grad?: FillGradient): FillPoint => ({ index, a: 80, b: 20, gradient: grad });
const context = (offset = 0, dpr = 1, inverted = false) => ({
  dpr,
  timeScale: { indexToX: (index: number) => index * 10 },
  priceScale: { priceToY: (value: number) => offset + (inverted ? value : 100 - value) },
}) as unknown as PrimitiveRenderContext;

/** Capture gradient coordinates under the transform at creation, as a canvas does. */
function canvas() {
  const { ctx, rec } = makeCtx();
  let translateY = 0;
  const stack: number[] = [];
  const axes = new Map<CanvasGradient, number[]>();
  const fills: (number[] | string)[] = [];
  const save = ctx.save.bind(ctx), restore = ctx.restore.bind(ctx), translate = ctx.translate.bind(ctx);
  const create = ctx.createLinearGradient.bind(ctx), fill = ctx.fill.bind(ctx);
  ctx.save = () => { stack.push(translateY); save(); };
  ctx.restore = () => { translateY = stack.pop() ?? 0; restore(); };
  ctx.translate = (x, y) => { translateY += y; translate(x, y); };
  ctx.createLinearGradient = (x0, y0, x1, y1) => {
    const result = create(x0, y0, x1, y1);
    axes.set(result, [y0 + translateY, y1 + translateY]);
    return result;
  };
  ctx.fill = () => {
    fills.push(typeof ctx.fillStyle === 'string' ? ctx.fillStyle : axes.get(ctx.fillStyle as CanvasGradient)!);
    fill();
  };
  return { ctx, rec, fills };
}

describe('price-anchored gradient lifetime', () => {
  it('moves both stops with a price-scale pan even when the span stays constant', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb', gradient: gradient() });
    band.setPoints([point(0), point(1)]);
    const c = canvas();
    band.draw(c.ctx, context());
    band.draw(c.ctx, context(10));
    expect(c.fills).toEqual([[20, 40], [30, 50]]);
  });

  it('does not reuse another band\'s stops on the same canvas', () => {
    const first = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb', gradient: gradient() });
    const second = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb', gradient: gradient(40, 20) });
    first.setPoints([point(0), point(1)]);
    second.setPoints([point(0), point(1)]);
    const c = canvas();
    first.draw(c.ctx, context());
    second.draw(c.ctx, context());
    expect(c.fills).toEqual([[20, 40], [60, 80]]);
  });

  it('follows a changed parent pane transform', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb', gradient: gradient() });
    band.setPoints([point(0), point(1)]);
    const c = canvas();
    c.ctx.save(); c.ctx.translate(0, 100); band.draw(c.ctx, context()); c.ctx.restore();
    c.ctx.save(); c.ctx.translate(0, 200); band.draw(c.ctx, context()); c.ctx.restore();
    expect(c.fills).toEqual([[120, 140], [220, 240]]);
  });
});

describe('per-bar fill gradients', () => {
  it('splits different anchors at a shared bar edge and coalesces equal values', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb' });
    band.setPoints([point(0, gradient()), point(1, gradient()), point(2, gradient(40, 20)), point(3, gradient(40, 20))]);
    const c = canvas(); band.draw(c.ctx, context());
    expect(c.fills).toEqual([[20, 40], [60, 80]]);
    expect(c.rec.ops.filter(op => (op.type === 'moveTo' || op.type === 'lineTo') && op.args[0] === 20)).toHaveLength(4);
  });

  it('splits changed colors without requiring changed anchors', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb' });
    band.setPoints([point(0, gradient()), point(1, { ...gradient(), bottomColor: '#00ff00' }), point(2, gradient())]);
    const c = canvas(); band.draw(c.ctx, context());
    expect(c.rec.ops.filter(op => op.type === 'addColorStop').map(op => op.text)).toEqual(['#ff0000', '#0000ff', '#ff0000', '#00ff00']);
  });

  it('uses point color, point gradient, global gradient, then the direction color', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb', gradient: gradient(90, 10) });
    const points = [
      { ...point(0, gradient()), color: '#123' },
      { ...point(1, gradient(50, 30)), color: '#123' },
      point(2, gradient()), point(3), point(4),
    ];
    band.setPoints(points);
    const c = canvas(); band.draw(c.ctx, context());
    expect(c.fills).toEqual(['#123', [20, 40], [10, 90]]);
    band.setOptions({ gradient: undefined });
    const next = canvas(); band.draw(next.ctx, context());
    expect(next.fills).toEqual(['#123', [20, 40], '#aaa']);
  });

  it('uses the whole finite band extent for omitted anchors and respects inversion and pixel ratio', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb' });
    band.setPoints([point(0, colors), point(1, colors), { index: 2, a: null, b: NaN },
      { index: 3, a: 90, b: 10, gradient: colors }, { index: 4, a: 90, b: 10, gradient: colors }]);
    const c = canvas(); band.draw(c.ctx, context(5, 2, true));
    expect(c.fills).toEqual([[190, 30], [190, 30]]);
    expect(c.rec.ops.filter(op => op.type === 'createLinearGradient')).toHaveLength(1);
  });

  it('meets at the crossing when direction and gradient change together', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb' });
    band.setPoints([point(0, gradient()), { index: 1, a: 20, b: 80, gradient: gradient(40, 20) },
      { index: 2, a: 20, b: 80, gradient: gradient(40, 20) }]);
    const c = canvas(); band.draw(c.ctx, context());
    expect(c.fills).toEqual([[20, 40], [60, 80]]);
    expect(c.rec.ops.filter(op => op.type === 'moveTo').map(op => op.args)).toEqual([[0, 20], [5, 50]]);
  });

  it('clears gradients when points change and emits nothing while hidden', () => {
    const band = new IndicatorFill({ colorUp: '#aaa', colorDown: '#bbb' });
    band.setPoints([point(0, gradient()), point(1, gradient())]);
    band.setVisible(false);
    const hidden = canvas(); band.draw(hidden.ctx, context()); expect(hidden.fills).toEqual([]);
    band.setVisible(true);
    band.setPoints([point(0), point(1)]);
    const c = canvas(); band.draw(c.ctx, context()); expect(c.fills).toEqual(['#aaa']);
  });
});
