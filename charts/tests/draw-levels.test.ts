/**
 * The shared level palette, and the ladder tools that consume it.
 *
 * The palette exists so that 0.618 is one colour everywhere; the tools exist
 * to stroke each level in that colour, skip the ones switched off, and print
 * a level's own label when it has one. Both halves are pinned here: the
 * palette's table, and the op stream each tool leaves behind.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import {
  LEVEL_NEUTRAL, CYCLE_PALETTE, levelColor, cycleColor, formatRatio, gannLabel, cloneLevels,
  DEFAULT_FIB, DEFAULT_FIB_FAN, DEFAULT_GANN_FAN, DEFAULT_GANN_BOX, DEFAULT_FIB_TIME_ZONE,
} from '../src/draw/levels';
import {
  FIB_RETRACEMENT, FIB_EXTENSION, FIB_CHANNEL, FIB_FAN, FIB_TIME_ZONE, GANN_FAN, GANN_BOX,
} from '../src/draw/fib-tools';
import { registerBuiltinDrawingTools } from '../src/draw/tools';
import { RecordingContext } from './helpers/fake-ctx';
import type { Drawing, DrawingPoint, DrawingTool, DrawContext, FibLevel } from '../src/draw/types';

beforeAll(() => { registerBuiltinDrawingTools(); });

// ── the palette ───────────────────────────────────────────────────────────

describe('levelColor', () => {
  it('keeps the anchors neutral', () => {
    for (const r of [0, 1, 2, 3]) expect(levelColor(r), String(r)).toBe(LEVEL_NEUTRAL);
  });

  it('gives every ratio of a retracement a colour of its own', () => {
    const seen = new Set([0.236, 0.382, 0.5, 0.618, 0.786].map(levelColor));
    expect(seen.size).toBe(5);
    expect(seen.has(LEVEL_NEUTRAL)).toBe(false);
  });

  it('keeps a Gann box readable: its quarters do not share with the golden pair', () => {
    const seen = new Set([0.25, 0.382, 0.5, 0.618, 0.75].map(levelColor));
    expect(seen.size).toBe(5);
  });

  it('matches with a tolerance, since ratios arrive from JSON and arithmetic', () => {
    expect(levelColor(0.618 + 1e-9)).toBe(levelColor(0.618));
    expect(levelColor(0.6179999999)).toBe(levelColor(0.618));
  });

  it('is neutral for a ratio with no convention, and for garbage', () => {
    expect(levelColor(0.707)).toBe(LEVEL_NEUTRAL);
    expect(levelColor(Number.NaN)).toBe(LEVEL_NEUTRAL);
    expect(levelColor(Infinity)).toBe(LEVEL_NEUTRAL);
  });
});

describe('cycleColor', () => {
  it('walks the palette and wraps', () => {
    for (let i = 0; i < CYCLE_PALETTE.length; i++) expect(cycleColor(i)).toBe(CYCLE_PALETTE[i]);
    expect(cycleColor(CYCLE_PALETTE.length)).toBe(CYCLE_PALETTE[0]);
    expect(cycleColor(CYCLE_PALETTE.length * 3 + 2)).toBe(CYCLE_PALETTE[2]);
  });

  it('is distinguishable across one full cycle', () => {
    expect(new Set(CYCLE_PALETTE).size).toBe(CYCLE_PALETTE.length);
  });

  it('survives a negative or non-integer index', () => {
    expect(cycleColor(-1)).toBe(CYCLE_PALETTE[CYCLE_PALETTE.length - 1]);
    expect(cycleColor(2.9)).toBe(CYCLE_PALETTE[2]);
    expect(cycleColor(Number.NaN)).toBe(CYCLE_PALETTE[0]);
  });
});

describe('ratio text', () => {
  it('prints a fib ratio as a percentage', () => {
    expect(formatRatio(0.618)).toBe('61.8%');
    expect(formatRatio(1)).toBe('100.0%');
  });

  it('prints a Gann angle as price x time', () => {
    expect(gannLabel(1)).toBe('1x1');
    expect(gannLabel(0.5)).toBe('1x2');
    expect(gannLabel(0.125)).toBe('1x8');
    expect(gannLabel(4)).toBe('4x1');
    // Not a clean reciprocal: still true, just not idiomatic.
    expect(gannLabel(0.3)).toBe('0.3x1');
  });
});

describe('the default ladders', () => {
  it('carry their colours from the palette', () => {
    for (const l of DEFAULT_FIB) expect(l.color).toBe(levelColor(l.ratio));
    for (const l of DEFAULT_FIB_FAN) expect(l.color).toBe(levelColor(l.ratio));
    for (const l of DEFAULT_GANN_BOX) expect(l.color).toBe(levelColor(l.ratio));
    DEFAULT_GANN_FAN.forEach((l, i) => {
      expect(l.color).toBe(cycleColor(i));
      expect(l.label).toBe(gannLabel(l.ratio));
    });
  });

  it('leaves time zones uncoloured: there is no convention for the 13 line', () => {
    for (const l of DEFAULT_FIB_TIME_ZONE) expect(l.color).toBeUndefined();
    expect(DEFAULT_FIB_TIME_ZONE.map((l) => l.ratio)).toEqual([0, 1, 2, 3, 5, 8, 13, 21, 34, 55]);
  });

  it('are frozen, so no drawing can edit the shared default in place', () => {
    for (const list of [DEFAULT_FIB, DEFAULT_FIB_FAN, DEFAULT_GANN_FAN, DEFAULT_GANN_BOX, DEFAULT_FIB_TIME_ZONE]) {
      expect(Object.isFrozen(list)).toBe(true);
      for (const l of list) expect(Object.isFrozen(l)).toBe(true);
    }
  });

  it('are cloned into each tool default, not shared', () => {
    const own = FIB_RETRACEMENT.defaultStyle?.levels;
    expect(own).toEqual(DEFAULT_FIB);
    expect(own).not.toBe(DEFAULT_FIB);
    expect(Object.isFrozen(own)).toBe(false);
    const copy = cloneLevels(DEFAULT_FIB);
    copy[0].color = '#000000';
    expect(DEFAULT_FIB[0].color).toBe(LEVEL_NEUTRAL);
  });
});

// ── the tools ─────────────────────────────────────────────────────────────

const RC = {
  plotWidth: 800, plotHeight: 400, dpr: 1, priceAxisWidth: 60,
  theme: { background: '#0d0e12', lineColor: '#4f8cff' },
  priceScale: { priceToY: (p: number) => 400 - p, format: (p: number) => p.toFixed(2) },
  timeScale: { indexToX: (i: number) => i },
  dataLayer: { timeToIndexFloat: (t: number) => t / 6 },
};

const toPt = (p: DrawingPoint) => ({ x: p.time / 6, y: 400 - p.price });

const ANCHORS: DrawingPoint[] = [
  { time: 0, price: 100 }, { time: 600, price: 300 }, { time: 1200, price: 200 },
];

function drawingOf(tool: DrawingTool, style: Record<string, unknown> = {}): Drawing {
  return {
    id: 'd', tool: tool.id, paneIndex: 0, zIndex: 0,
    points: ANCHORS.slice(0, Math.max(1, tool.points)),
    style: { ...tool.defaultStyle, ...style },
  };
}

function paint(tool: DrawingTool, d: Drawing): RecordingContext {
  const rec = new RecordingContext();
  const style = { color: '#4f8cff', lineWidth: 1.5, ...d.style };
  tool.draw({
    ctx: rec as unknown as CanvasRenderingContext2D,
    rc: RC as never,
    pts: d.points.map(toPt),
    drawing: d,
    style,
    selected: false,
    formatPrice: (p: number) => p.toFixed(2),
  } as DrawContext);
  return rec;
}

const strokeColors = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'stroke').map((o) => o.strokeStyle ?? '');
const texts = (rec: RecordingContext): string[] =>
  rec.ops.filter((o) => o.type === 'fillText').map((o) => o.text ?? '');

describe('fib retracement', () => {
  it('strokes the leg in the drawing colour, then each level in its own', () => {
    const colors = strokeColors(paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT)));
    expect(colors[0]).toBe('#4f8cff');
    expect(colors.slice(1)).toEqual(DEFAULT_FIB.map((l) => l.color));
  });

  it('labels each level with its ratio and price, in the level colour', () => {
    const rec = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT));
    const half = rec.ops.find((o) => o.type === 'fillText' && o.text?.startsWith('50.0%'));
    expect(half).toBeDefined();
    expect(half?.text).toBe('50.0%  200.00');
    expect(half?.fillStyle).toBe(levelColor(0.5));
  });

  it('skips a level that is switched off, on screen and under the cursor', () => {
    const levels: FibLevel[] = cloneLevels(DEFAULT_FIB).map((l) => (l.ratio === 0.5 ? { ...l, enabled: false } : l));
    const d = drawingOf(FIB_RETRACEMENT, { levels });
    const rec = paint(FIB_RETRACEMENT, d);
    expect(strokeColors(rec).length).toBe(1 + DEFAULT_FIB.length - 1);
    expect(texts(rec).some((t) => t.startsWith('50.0%'))).toBe(false);
    // The 50% line sits at price 200, y = 200. Enabled it is a hit; off, it is not.
    const h = { pts: d.points.map(toPt), drawing: d, rc: RC } as never;
    expect(FIB_RETRACEMENT.distance(50, 200, h)).toBeGreaterThan(5);
    const on = drawingOf(FIB_RETRACEMENT);
    expect(FIB_RETRACEMENT.distance(50, 200, { pts: on.points.map(toPt), drawing: on, rc: RC } as never)).toBe(0);
  });

  it('prints a level label in place of the ratio when it has one', () => {
    const levels: FibLevel[] = [{ ratio: 0.5, label: 'HALF', color: '#abcdef' }];
    const rec = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { levels }));
    expect(texts(rec)).toContain('HALF  200.00');
    expect(strokeColors(rec)).toContain('#abcdef');
  });

  it('falls back to the palette for a level with no colour of its own', () => {
    const rec = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { levels: [{ ratio: 0.618 }] }));
    expect(strokeColors(rec)[1]).toBe(levelColor(0.618));
  });

  it('tints each band by the level that closes it, unless a fill colour is set', () => {
    // Labels off, so the only fillRects are the bands (a label plate is one too).
    const rec = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { showLabels: false }));
    const bands = rec.ops.filter((o) => o.type === 'fillRect').map((o) => o.fillStyle);
    expect(bands).toEqual(DEFAULT_FIB.slice(1).map((l) => l.color));
    const own = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { showLabels: false, fillColor: '#101010' }));
    const ownBands = own.ops.filter((o) => o.type === 'fillRect');
    expect(ownBands.length).toBe(DEFAULT_FIB.length - 1);
    expect(ownBands.every((o) => o.fillStyle === '#101010')).toBe(true);
  });

  it('draws no label when labels are off', () => {
    expect(texts(paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { showLabels: false })))).toEqual([]);
  });

  it('ignores a level whose ratio is not a number', () => {
    const levels = [{ ratio: Number.NaN }, { ratio: 0.5 }] as FibLevel[];
    const rec = paint(FIB_RETRACEMENT, drawingOf(FIB_RETRACEMENT, { levels }));
    expect(strokeColors(rec).length).toBe(2);
  });
});

describe('fib extension', () => {
  it('projects the leg from the third anchor, level by level', () => {
    const rec = paint(FIB_EXTENSION, drawingOf(FIB_EXTENSION));
    // Leg from p0 through p1 to p2 in the drawing colour, then the ladder.
    expect(strokeColors(rec).slice(1)).toEqual(DEFAULT_FIB.map((l) => l.color));
    // From p2 (200) with span 200: the 50% level lands on 300.
    expect(texts(rec)).toContain('50.0%  300.00');
  });
});

describe('fib channel', () => {
  it('strokes each level in its own colour', () => {
    expect(strokeColors(paint(FIB_CHANNEL, drawingOf(FIB_CHANNEL)))).toEqual(DEFAULT_FIB.map((l) => l.color));
  });

  it('drops a disabled level from the hit test too', () => {
    const on = drawingOf(FIB_CHANNEL);
    const h = (d: Drawing) => ({ pts: d.points.map(toPt), drawing: d, rc: RC } as never);
    // Level 1 runs from a + (w - b) to w, so w itself is on it.
    const w = toPt(on.points[2]);
    expect(FIB_CHANNEL.distance(w.x, w.y, h(on))).toBeCloseTo(0, 6);
    const off = drawingOf(FIB_CHANNEL, { levels: DEFAULT_FIB.map((l) => (l.ratio === 1 ? { ...l, enabled: false } : { ...l })) });
    expect(FIB_CHANNEL.distance(w.x, w.y, h(off))).toBeGreaterThan(5);
  });
});

describe('fib speed fan', () => {
  it('strokes each ray in its own colour and labels it with its ratio', () => {
    const rec = paint(FIB_FAN, drawingOf(FIB_FAN));
    expect(strokeColors(rec)).toEqual(DEFAULT_FIB_FAN.map((l) => l.color));
    expect(texts(rec)).toEqual(DEFAULT_FIB_FAN.map((l) => formatRatio(l.ratio)));
  });
});

describe('fib time zone', () => {
  it('takes the drawing colour until a zone is given its own', () => {
    const plain = strokeColors(paint(FIB_TIME_ZONE, drawingOf(FIB_TIME_ZONE)));
    expect(plain.length).toBeGreaterThan(3);
    expect(plain.every((c) => c === '#4f8cff')).toBe(true);
    const levels = cloneLevels(DEFAULT_FIB_TIME_ZONE).map((l) => (l.ratio === 2 ? { ...l, color: '#abcdef' } : l));
    expect(strokeColors(paint(FIB_TIME_ZONE, drawingOf(FIB_TIME_ZONE, { levels })))).toContain('#abcdef');
  });

  it('labels a zone by its bar multiple, not a percentage', () => {
    expect(texts(paint(FIB_TIME_ZONE, drawingOf(FIB_TIME_ZONE)))).toEqual(expect.arrayContaining(['0', '1', '2', '3', '5']));
  });
});

describe('gann fan', () => {
  it('walks the cycle palette across its angles and labels each', () => {
    const rec = paint(GANN_FAN, drawingOf(GANN_FAN));
    expect(strokeColors(rec)).toEqual(DEFAULT_GANN_FAN.map((_, i) => cycleColor(i)));
    expect(texts(rec)).toEqual(['1x8', '1x4', '1x2', '1x1', '2x1', '4x1', '8x1']);
  });

  it('keeps the 1x1 on the anchor diagonal', () => {
    const d = drawingOf(GANN_FAN);
    const h = { pts: d.points.map(toPt), drawing: d, rc: RC } as never;
    // a = (0, 300), b = (100, 100): the diagonal passes through (50, 200).
    expect(GANN_FAN.distance(50, 200, h)).toBeCloseTo(0, 6);
  });
});

describe('gann box', () => {
  it('draws the diagonal in the drawing colour and the grid in level colours', () => {
    const colors = strokeColors(paint(GANN_BOX, drawingOf(GANN_BOX)));
    expect(colors[0]).toBe('#4f8cff');
    expect(colors.slice(1)).toEqual(DEFAULT_GANN_BOX.map((l) => l.color));
  });

  it('labels its price levels off the anchor prices', () => {
    // From 100 to 300: the 0.5 line is 200.
    expect(texts(paint(GANN_BOX, drawingOf(GANN_BOX)))).toContain('50.0%');
    const rec = paint(GANN_BOX, drawingOf(GANN_BOX, { levels: [{ ratio: 0.5 }] }));
    const y = rec.ops.find((o) => o.type === 'fillText')?.args[1] ?? Number.NaN;
    // Snapped to the pixel centre, so within a pixel of the level.
    expect(Math.abs(y - 200)).toBeLessThanOrEqual(0.5);
  });
});
