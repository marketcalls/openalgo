import { describe, expect, it } from 'vitest';
import { DrawingLayer, registerBuiltinDrawingTools } from '../src/draw/index';
import { darkTheme } from '../src/theme';
import { makeCtx } from './helpers/fake-ctx';
import type { Drawing } from '../src/draw/types';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

registerBuiltinDrawingTools();
const rc = {
  plotWidth: 800, plotHeight: 500, priceAxisWidth: 64, dpr: 2, theme: darkTheme,
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p, format: String },
  dataLayer: { timeToIndexFloat: (t: number) => t },
} as unknown as PrimitiveRenderContext;
const partial: Drawing = {
  id: 'draft', tool: 'parallel-channel', paneIndex: 0, zIndex: 0, style: { color: '#91b5ff' },
  points: [{ time: 100, price: 120 }, { time: 350, price: 220 }],
};

describe('multi-point drawing placement guides', () => {
  it('shows the placed leg before a channel has its final anchor', () => {
    const layer = new DrawingLayer();
    layer.setPreview(partial);
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, rc);
    expect(rec.ops.some(op => op.type === 'moveTo' && op.args[0] === 200 && op.args[1] === 240)).toBe(true);
    expect(rec.ops.some(op => op.type === 'lineTo' && op.args[0] === 700 && op.args[1] === 440)).toBe(true);
    expect(rec.count('stroke')).toBeGreaterThan(0);
    expect(layer.hitTest(200, 160, rc)).toBeNull();
  });

  it('shows the first anchor and clears it when placement is cancelled', () => {
    const layer = new DrawingLayer();
    layer.setPreview({ ...partial, points: partial.points.slice(0, 1) });
    const first = makeCtx();
    layer.draw(first.ctx, rc);
    expect(first.rec.count('arc')).toBe(1);
    layer.setPreview(null);
    const cleared = makeCtx();
    layer.draw(cleared.ctx, rc);
    expect(cleared.rec.count('arc')).toBe(0);
  });

  it('keeps incomplete saved drawings invisible and never mutates draft anchors', () => {
    const layer = new DrawingLayer();
    layer.setDrawings([partial]);
    const before = JSON.stringify(partial);
    const { ctx, rec } = makeCtx();
    layer.draw(ctx, rc);
    expect(rec.count('stroke')).toBe(0);
    layer.setPreview(partial);
    layer.draw(ctx, rc);
    expect(JSON.stringify(partial)).toBe(before);
  });
});
