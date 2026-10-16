import { expect, it, vi } from 'vitest';
import { DrawingLayer } from '../src/draw/layer';
import { registerDrawingTool } from '../src/draw/registry';
import type { PrimitiveRenderContext } from '../src/primitives/primitive';

const rc = { plotWidth: 800, plotHeight: 500,
  timeScale: { indexToX: (i: number) => i },
  priceScale: { priceToY: (p: number) => p }, dataLayer: { timeToIndexFloat: (t: number) => t },
} as unknown as PrimitiveRenderContext;

it('stops at the topmost exact body hit in a dense stack', () => {
  const distance = vi.fn(() => 0);
  registerDrawingTool({ id: 'test-exact-hit', name: 'Exact hit', points: 1, draw() {}, distance });
  const layer = new DrawingLayer();
  layer.setDrawings(Array.from({ length: 500 }, (_, i) => ({ id: String(i), tool: 'test-exact-hit',
    points: [{ time: 100, price: 100 }], style: {}, paneIndex: 0, zIndex: i })));
  expect(layer.hitTest(100, 100, rc)?.externalId).toBe('draw:499');
  expect(distance).toHaveBeenCalledTimes(1);
});

it('still chooses the nearest nonzero body before using paint order to break ties', () => {
  registerDrawingTool({ id: 'test-nearest-hit', name: 'Nearest hit', points: 1, draw() {}, distance: (_x, _y, c) => Number(c.drawing.id) });
  const layer = new DrawingLayer();
  layer.setDrawings([1, 2, 3].map(i => ({ id: String(i), tool: 'test-nearest-hit',
    points: [{ time: 100, price: 100 }], style: {}, paneIndex: 0, zIndex: i })));
  expect(layer.hitTest(100, 100, rc)?.externalId).toBe('draw:1');
});
