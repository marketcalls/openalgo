import { describe, expect, it } from 'vitest';
import { paintGeometry } from '../src/draw/advanced-shared';
import type { DrawContext } from '../src/draw/types';
import { makeCtx } from './helpers/fake-ctx';

function paint(dpr = 1, height = 300, close = true) {
  const { ctx, rec } = makeCtx();
  ctx.measureText = text => ({ width: text.length * 6 * dpr } as TextMetrics);
  paintGeometry({
    ctx, rc: { dpr, plotWidth: 400, plotHeight: height },
    style: { color: '#91b5ff', lineWidth: 1 }, drawing: {},
  } as DrawContext, {
    paths: [],
    labels: Array.from({ length: 8 }, (_, i) => ({
      text: (i / 10).toFixed(3), at: { x: close ? 200 + i * 2 : 10 + i * 45, y: height / 2 },
    })),
  });
  return rec.ops.filter(op => op.type === 'fillText').map(op => ({
    text: op.text!, x: op.args[0] / dpr, y: op.args[1] / dpr, width: op.text!.length * 6,
  }));
}

describe('advanced drawing label layout', () => {
  it('separates dense level labels while preserving every readable value', () => {
    const labels = paint();
    expect(labels).toHaveLength(8);
    for (let i = 0; i < labels.length; i++) for (const other of labels.slice(i + 1)) {
      const a = labels[i];
      expect(a.x + a.width <= other.x || other.x + other.width <= a.x || Math.abs(a.y - other.y) >= 11).toBe(true);
    }
  });

  it('uses the same layout at both device pixel ratios', () => {
    expect(paint(2)).toEqual(paint(1));
  });

  it('retains sparse label positions', () => {
    expect(paint(1, 300, false).map(p => [p.x, p.y])).toEqual(Array.from({ length: 8 }, (_, i) => [10 + i * 45, 150]));
  });

  it('omits labels that cannot fit without collisions in a short plot', () => {
    const labels = paint(1, 24);
    expect(labels.length).toBeGreaterThan(0);
    expect(labels.length).toBeLessThan(8);
    for (const label of labels) {
      expect(label.y).toBeGreaterThanOrEqual(11);
      expect(label.y).toBeLessThanOrEqual(24);
    }
  });
});
