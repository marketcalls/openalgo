/**
 * Freehand stroke geometry: the thinning a raw pointer trail goes through,
 * the spline that strokes what is left, and the pressure-to-width map. Each
 * has a formula that is easy to get almost right (a thinning that moves a
 * kept point, a spline that misses a control point, a width that drifts at
 * mouse pressure), so each is pinned by value rather than by shape.
 */
import { describe, it, expect } from 'vitest';
import { rdpSimplify, catmullRom, pressureWidth } from '../src/draw/freehand';
import { distToPolyline } from '../src/draw/geometry';
import { makeCtx } from './helpers/fake-ctx';
import type { Op } from './helpers/fake-ctx';
import type { ScreenPoint } from '../src/draw/types';

/** A deterministic 0..1 sequence, so the jittery stroke is the same every run. */
function lcg(seed: number): () => number {
  let s = seed >>> 0;
  return () => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    return s / 0x100000000;
  };
}

/** A gentle wave sampled every 1.2 px with up to a pixel of jitter: a hand-drawn stroke. */
function jitteryStroke(n = 500): ScreenPoint[] {
  const rand = lcg(7);
  const pts: ScreenPoint[] = [];
  for (let i = 0; i < n; i++) {
    pts.push({ x: i * 1.2, y: 100 + 40 * Math.sin(i / 25) + (rand() * 2 - 1) });
  }
  return pts;
}

/** Every point of `out` is a point of `input`, at the same coordinates, in input order. */
function expectSubsequence(out: ScreenPoint[], input: ScreenPoint[]): void {
  let j = 0;
  for (const p of out) {
    while (j < input.length && (input[j].x !== p.x || input[j].y !== p.y)) j++;
    expect(j, `point ${p.x},${p.y} is not in the input in order`).toBeLessThan(input.length);
    j++;
  }
}

/** Evaluate a cubic bezier recorded as a bezierCurveTo op, from `from`, at `t`. */
function bezierAt(from: ScreenPoint, op: Op, t: number): ScreenPoint {
  const [c1x, c1y, c2x, c2y, x, y] = op.args;
  const u = 1 - t;
  const b0 = u * u * u;
  const b1 = 3 * u * u * t;
  const b2 = 3 * u * t * t;
  const b3 = t * t * t;
  return {
    x: b0 * from.x + b1 * c1x + b2 * c2x + b3 * x,
    y: b0 * from.y + b1 * c1y + b2 * c2y + b3 * y,
  };
}

function record(points: ScreenPoint[], tension?: number): Op[] {
  const { ctx, rec } = makeCtx();
  catmullRom(ctx, points, tension);
  return rec.ops;
}

// ── rdpSimplify ───────────────────────────────────────────────────────────

describe('rdpSimplify', () => {
  it('returns a copy for a non-positive epsilon', () => {
    const input = jitteryStroke(40);
    for (const eps of [0, -1, Number.NaN]) {
      const out = rdpSimplify(input, eps);
      expect(out, String(eps)).toEqual(input);
      expect(out).not.toBe(input);
      expect(out[0]).not.toBe(input[0]);
    }
  });

  it('handles empty, one-point and two-point strokes', () => {
    expect(rdpSimplify([], 5)).toEqual([]);
    expect(rdpSimplify([{ x: 3, y: 4 }], 5)).toEqual([{ x: 3, y: 4 }]);
    expect(rdpSimplify([{ x: 0, y: 0 }, { x: 1, y: 1 }], 500)).toEqual([{ x: 0, y: 0 }, { x: 1, y: 1 }]);
  });

  it('keeps the first and last points whatever the tolerance', () => {
    const input = jitteryStroke();
    const out = rdpSimplify(input, 1000);
    expect(out).toEqual([input[0], input[input.length - 1]]);
  });

  it('collapses a straight line to its two ends', () => {
    const line: ScreenPoint[] = [];
    for (let i = 0; i < 100; i++) line.push({ x: i * 3, y: 20 + i * 1.5 });
    expect(rdpSimplify(line, 0.01)).toEqual([line[0], line[99]]);
  });

  it('thins a jittery stroke by an order of magnitude without moving a kept point', () => {
    const input = jitteryStroke(500);
    const out = rdpSimplify(input, 2);
    expect(out.length).toBeGreaterThan(2);
    expect(out.length).toBeLessThanOrEqual(50);
    expectSubsequence(out, input);
  });

  it('leaves every dropped point within epsilon of the thinned polyline', () => {
    const input = jitteryStroke(500);
    const eps = 2;
    const out = rdpSimplify(input, eps);
    for (const p of input) {
      expect(distToPolyline(p.x, p.y, out)).toBeLessThanOrEqual(eps + 1e-9);
    }
  });

  it('keeps the far end of a stroke that doubles back on itself', () => {
    // The excursion to x=20 lies on the line through the ends, so a distance
    // to that line would be zero and the whole out-and-back would vanish.
    const input: ScreenPoint[] = [
      { x: 0, y: 0 }, { x: 5, y: 0 }, { x: 10, y: 0 }, { x: 15, y: 0 }, { x: 20, y: 0 },
      { x: 15, y: 0 }, { x: 10, y: 0 },
    ];
    expect(rdpSimplify(input, 1)).toEqual([{ x: 0, y: 0 }, { x: 20, y: 0 }, { x: 10, y: 0 }]);
  });

  it('keeps the corners of a closed loop whose ends coincide', () => {
    const loop: ScreenPoint[] = [
      { x: 0, y: 0 }, { x: 5, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 5 }, { x: 10, y: 10 },
      { x: 5, y: 10 }, { x: 0, y: 10 }, { x: 0, y: 5 }, { x: 0, y: 0 },
    ];
    expect(rdpSimplify(loop, 1)).toEqual([
      { x: 0, y: 0 }, { x: 10, y: 0 }, { x: 10, y: 10 }, { x: 0, y: 10 }, { x: 0, y: 0 },
    ]);
  });

  it('copes with a long stroke', () => {
    const input = jitteryStroke(20000);
    const out = rdpSimplify(input, 1.5);
    expect(out.length).toBeLessThan(input.length / 5);
    expectSubsequence(out, input);
  });
});

// ── catmullRom ────────────────────────────────────────────────────────────

describe('catmullRom', () => {
  it('emits nothing for fewer than two points', () => {
    expect(record([])).toEqual([]);
    expect(record([{ x: 4, y: 4 }])).toEqual([]);
  });

  it('degrades two points to a straight line', () => {
    expect(record([{ x: 1, y: 2 }, { x: 30, y: 40 }])).toEqual([
      { type: 'moveTo', args: [1, 2] },
      { type: 'lineTo', args: [30, 40] },
    ]);
  });

  it('passes through every control point', () => {
    const pts = rdpSimplify(jitteryStroke(), 2);
    const ops = record(pts);
    expect(ops[0]).toEqual({ type: 'moveTo', args: [pts[0].x, pts[0].y] });
    const curves = ops.slice(1);
    expect(curves.length).toBe(pts.length - 1);
    curves.forEach((op, i) => {
      expect(op.type).toBe('bezierCurveTo');
      expect(op.args.slice(4)).toEqual([pts[i + 1].x, pts[i + 1].y]);
    });
  });

  it('matches the closed-form conversion for a known stroke', () => {
    const ops = record([{ x: 0, y: 0 }, { x: 10, y: 0 }, { x: 20, y: 10 }, { x: 30, y: 10 }]);
    const expected = [
      // First segment: the doubled start point gives a tangent along the segment.
      [10 / 6, 0, 10 - 20 / 6, -10 / 6, 10, 0],
      [10 + 20 / 6, 10 / 6, 20 - 20 / 6, 10 - 10 / 6, 20, 10],
      // Last segment: the doubled end point gives a tangent along the segment.
      [20 + 20 / 6, 10 + 10 / 6, 30 - 10 / 6, 10, 30, 10],
    ];
    expect(ops.length).toBe(4);
    expected.forEach((want, i) => {
      const got = ops[i + 1].args;
      want.forEach((v, j) => expect(got[j], `segment ${i} arg ${j}`).toBeCloseTo(v, 9));
    });
  });

  it('is tangent-continuous at every interior point', () => {
    const pts = rdpSimplify(jitteryStroke(), 2);
    const curves = record(pts).slice(1);
    for (let i = 1; i < pts.length - 1; i++) {
      const arriving = curves[i - 1].args;
      const leaving = curves[i].args;
      const p = pts[i];
      // The tangent into p (p minus the previous curve's second control) must
      // equal the tangent out of p (the next curve's first control minus p).
      expect(leaving[0] - p.x).toBeCloseTo(p.x - arriving[2], 9);
      expect(leaving[1] - p.y).toBeCloseTo(p.y - arriving[3], 9);
    }
  });

  it('keeps a straight run straight, with no overshoot', () => {
    const pts: ScreenPoint[] = [];
    for (let i = 0; i < 6; i++) pts.push({ x: i * 10, y: 5 + i * 5 });
    const curves = record(pts).slice(1);
    let lastX = -Infinity;
    curves.forEach((op, i) => {
      for (const t of [0.25, 0.5, 0.75, 1]) {
        const q = bezierAt(pts[i], op, t);
        expect(q.y).toBeCloseTo(5 + q.x / 2, 9);
        expect(q.x).toBeGreaterThan(lastX);
        lastX = q.x;
      }
    });
  });

  it('puts the control points on the segment ends at tension 0', () => {
    const pts = rdpSimplify(jitteryStroke(), 2);
    record(pts, 0).slice(1).forEach((op, i) => {
      expect(op.args).toEqual([pts[i].x, pts[i].y, pts[i + 1].x, pts[i + 1].y, pts[i + 1].x, pts[i + 1].y]);
    });
  });

  it('clamps tension to 0..1', () => {
    const pts = rdpSimplify(jitteryStroke(), 2);
    expect(record(pts, 5)).toEqual(record(pts, 1));
    expect(record(pts, -3)).toEqual(record(pts, 0));
    expect(record(pts, 1)).not.toEqual(record(pts, 0.5));
  });

  it('leaves opening and stroking the path to the caller', () => {
    const { ctx, rec } = makeCtx();
    catmullRom(ctx, rdpSimplify(jitteryStroke(), 2));
    expect(rec.count('beginPath')).toBe(0);
    expect(rec.count('closePath')).toBe(0);
    expect(rec.count('stroke')).toBe(0);
    expect(rec.count('fill')).toBe(0);
  });
});

// ── pressureWidth ─────────────────────────────────────────────────────────

describe('pressureWidth', () => {
  it('returns the base width at mouse pressure', () => {
    for (const base of [1, 2.5, 12]) expect(pressureWidth(base, 0.5)).toBe(base);
  });

  it('sweeps the default range from no pressure to full', () => {
    expect(pressureWidth(10, 0)).toBeCloseTo(4, 9);
    expect(pressureWidth(10, 0.75)).toBeCloseTo(13, 9);
    expect(pressureWidth(10, 1)).toBeCloseTo(16, 9);
  });

  it('clamps pressure to 0..1', () => {
    expect(pressureWidth(10, 2)).toBeCloseTo(16, 9);
    expect(pressureWidth(10, -1)).toBeCloseTo(4, 9);
  });

  it('treats a missing pressure as a mouse', () => {
    expect(pressureWidth(10, Number.NaN)).toBe(10);
    expect(pressureWidth(10, Infinity)).toBe(10);
  });

  it('honours a custom range and clamps it', () => {
    expect(pressureWidth(10, 1, 0.2)).toBeCloseTo(12, 9);
    expect(pressureWidth(10, 0, 0.2)).toBeCloseTo(8, 9);
    expect(pressureWidth(10, 0, 5)).toBeCloseTo(0, 9);
    expect(pressureWidth(10, 1, -1)).toBe(10);
  });

  it('grows with pressure', () => {
    let last = -Infinity;
    for (let p = 0; p <= 1; p += 0.1) {
      const w = pressureWidth(3, p);
      expect(w).toBeGreaterThan(last);
      last = w;
    }
  });
});
