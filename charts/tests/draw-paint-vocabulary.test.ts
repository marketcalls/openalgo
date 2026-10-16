/**
 * One paint vocabulary across the tool families. A line style dashes the
 * same, a width strokes the same whole device pixels, and a label with no
 * family set takes the same default face, whichever family drew it: the
 * built-in lines, the advanced lines and geometry, the patterns and the
 * analysis tools. The copies each family kept had drifted apart.
 */
import { describe, expect, it, beforeAll } from 'vitest';
import { registerBuiltinDrawingTools } from '../src/draw/tools';
import { getDrawingTool } from '../src/draw/registry';
import { RecordingContext } from './helpers/fake-ctx';
import { darkTheme } from '../src/theme';
import type { Bar, PrimitiveRenderContext } from '../src';
import type { DrawContext, Drawing, DrawingPoint } from '../src/draw/types';

beforeAll(() => { registerBuiltinDrawingTools(); });

/** A seeded random walk with volume, the way a traded stock moves. */
function walk(count: number): Bar[] {
  let s = 17, price = 100;
  const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
  return Array.from({ length: count }, (_, i) => {
    const open = price;
    price = Math.max(1, open + (rnd() - 0.5) * 3);
    return { time: i * 60, open, high: Math.max(open, price) + rnd(), low: Math.min(open, price) - rnd(), close: price, volume: 1000 + Math.round(rnd() * 500) };
  });
}
const BARS = walk(80);

function context(dpr: number): PrimitiveRenderContext {
  return {
    plotWidth: 800, plotHeight: 400, dpr, theme: darkTheme, bars: () => BARS,
    dataLayer: { timeToIndexFloat: (t: number) => t / 60 },
    timeScale: { indexToX: (i: number) => 20 + i * 9 },
    priceScale: { priceToY: (p: number) => 400 - (p - 80) * 10, format: (p: number) => p.toFixed(2) },
  } as unknown as PrimitiveRenderContext;
}

/** One tool of each family, anchored on bars of the walk. */
const FAMILIES: Record<string, number[]> = {
  'trend-line': [10, 40],
  pitchfork: [10, 30, 45],
  'fib-circles': [20, 35],
  'abcd-pattern': [10, 25, 40, 55],
  'anchored-vwap': [10],
  'fixed-range-volume-profile': [10, 50],
};

function paint(id: string, dpr: number): RecordingContext {
  const rc = context(dpr);
  const points: DrawingPoint[] = FAMILIES[id]!.map((i) => ({ time: BARS[i]!.time, price: BARS[i]!.close }));
  const tool = getDrawingTool(id);
  const drawing: Drawing = {
    id: 'd', tool: id, paneIndex: 0, zIndex: 0, points,
    style: { ...tool.defaultStyle, lineWidth: 1.5, lineStyle: 'dotted', showLabels: true, showStats: true },
    text: { value: '', bold: true },
  };
  const rec = new RecordingContext();
  tool.draw({
    ctx: rec as unknown as CanvasRenderingContext2D, rc, drawing, selected: false,
    pts: points.map((p) => ({ x: rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(p.time)) * dpr, y: rc.priceScale.priceToY(p.price) * dpr })),
    style: { color: '#4f8cff', ...drawing.style }, formatPrice: (p: number) => p.toFixed(2),
  } as DrawContext);
  return rec;
}

const DEFAULT_FACE = 'ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif';

describe('the paint vocabulary', () => {
  for (const id of Object.keys(FAMILIES)) {
    for (const dpr of [1, 1.5, 2]) {
      it(`${id} at a pixel ratio of ${dpr}`, () => {
        const rec = paint(id, dpr);
        // Dotted is one device pixel of ink per three of gap, scaled.
        const dashes = rec.ops.filter((o) => o.type === 'setLineDash' && o.args.length > 0).map((o) => o.args);
        expect(dashes.length, 'a dotted stroke').toBeGreaterThan(0);
        for (const dash of dashes) expect(dash).toEqual([1 * dpr, 3 * dpr]);
        // A 1.5 px line strokes whole device pixels, as a trend line does.
        const widths = new Set(rec.ops.filter((o) => o.type === 'stroke').map((o) => o.lineWidth));
        expect(widths).toEqual(new Set([Math.max(1, Math.round(1.5 * dpr))]));
        // A bold label with no family: weight 700 and the tier's one default face.
        const fonts = rec.ops.filter((o) => o.type === 'fillText').map((o) => o.font);
        expect(fonts.length, 'a label').toBeGreaterThan(0);
        for (const font of fonts) {
          expect(font).toMatch(/^700 [\d.]+px /);
          expect(font!.endsWith(`px ${DEFAULT_FACE}`)).toBe(true);
        }
      });
    }
  }
});
