import { describe, expect, it, vi } from 'vitest';
import { withDrawingTextMetrics, drawingTextWidth } from '../src/draw/text-metrics';
import { DrawingLayer, registerBuiltinDrawingTools } from '../src/draw/index';
import { makeCtx } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

describe('drawing text measurement within a paint', () => {
  it('measures a repeated label once while keeping fonts and canvases independent', () => {
    const { ctx } = makeCtx();
    const measure = vi.spyOn(ctx, 'measureText');
    withDrawingTextMetrics(ctx, () => {
      ctx.font = '12px sans-serif';
      expect(drawingTextWidth(ctx, '100')).toBe(18);
      expect(drawingTextWidth(ctx, '100')).toBe(18);
      ctx.font = '18px sans-serif';
      drawingTextWidth(ctx, '100');
      drawingTextWidth(makeCtx().ctx, '100');
    });
    expect(measure).toHaveBeenCalledTimes(2);
  });

  it('remeasures on the next paint after font availability changes', () => {
    const { ctx } = makeCtx();
    const measure = vi.spyOn(ctx, 'measureText').mockReturnValue({ width: 20 } as TextMetrics);
    withDrawingTextMetrics(ctx, () => expect(drawingTextWidth(ctx, 'Label')).toBe(20));
    measure.mockReturnValue({ width: 30 } as TextMetrics);
    withDrawingTextMetrics(ctx, () => expect(drawingTextWidth(ctx, 'Label')).toBe(30));
    expect(measure).toHaveBeenCalledTimes(2);
  });

  it('drops temporary measurements after an exception', () => {
    const { ctx } = makeCtx();
    const measure = vi.spyOn(ctx, 'measureText');
    expect(() => withDrawingTextMetrics(ctx, () => { drawingTextWidth(ctx, 'Label'); throw new Error('paint stopped'); })).toThrow('paint stopped');
    drawingTextWidth(ctx, 'Label');
    expect(measure).toHaveBeenCalledTimes(2);
  });

  it('shares repeated Fibonacci label widths across drawings in a real layer paint', () => {
    registerBuiltinDrawingTools();
    const layer = new DrawingLayer();
    layer.setDrawings(Array.from({ length: 100 }, (_, i) => ({
      id: 'fib-' + i, tool: 'fib-retracement', paneIndex: 0, zIndex: 0, style: {},
      points: [{ time: 100, price: 100 }, { time: 200, price: 200 }],
    })));
    const rc = {
      plotWidth: 800, plotHeight: 500, priceAxisWidth: 64, dpr: 1, theme: darkTheme,
      timeScale: { indexToX: (i: number) => i },
      priceScale: { priceToY: (p: number) => p, format: (p: number) => p.toFixed(2) },
      dataLayer: { timeToIndexFloat: (t: number) => t },
    } as unknown as PrimitiveRenderContext;
    const { ctx, rec } = makeCtx();
    const measure = vi.spyOn(ctx, 'measureText');
    layer.draw(ctx, rc);
    expect(rec.count('fillText')).toBe(700);
    expect(measure).toHaveBeenCalledTimes(7);
    layer.draw(ctx, rc);
    expect(measure).toHaveBeenCalledTimes(14);
  });
});
