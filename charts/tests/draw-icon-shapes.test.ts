/**
 * The construction glyphs, checked against what their tools draw.
 *
 * `draw-icons.test.ts` holds every glyph to the grid, the stroke and the
 * margin. That keeps a set consistent, and says nothing about whether a
 * glyph looks like its tool: the pitchforks were four overlapping crosses,
 * the Fibonacci circles two half rings, the spiral three arcs that did not
 * meet and left a stray tail at the edge, and the six harmonic patterns six
 * zigzags that five of their own pattern tools rejected.
 *
 * Each check here reads the path data (all a host that wraps the registry
 * itself draws) and asks for the one construction its tool is named after:
 * where a pitchfork's median starts, circles that share a centre, a spiral
 * whose quarter turns grow as Fibonacci numbers, a sector with its levels,
 * waves tangent to a cone. The harmonics go further and are handed to their
 * own pattern tool, which has to accept each as a valid instance of itself
 * and of no other harmonic.
 */
import { describe, expect, it } from 'vitest';
import { DRAWING_TOOL_ACCENTS, DRAWING_TOOL_ICONS } from '../src/draw/icons';
import { PATTERN_DRAWING_TOOLS } from '../src/draw/pattern-tools';
import type { Drawing, DrawingTool } from '../src/draw/types';
import type { PrimitiveRenderContext } from '../src';
import { RecordingContext } from './helpers/fake-ctx';
import { isClosed, samples, subpaths, type Pt, type Segment } from './helpers/icon-geometry';

const EPS = 1e-6;
const glyph = (id: string): string => DRAWING_TOOL_ICONS[id];

const sub = (a: Pt, b: Pt): Pt => [a[0] - b[0], a[1] - b[1]];
const add = (a: Pt, b: Pt): Pt => [a[0] + b[0], a[1] + b[1]];
const scale = (a: Pt, k: number): Pt => [a[0] * k, a[1] * k];
const mid = (a: Pt, b: Pt): Pt => [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
const cross = (a: Pt, b: Pt): number => a[0] * b[1] - a[1] * b[0];
const dotp = (a: Pt, b: Pt): number => a[0] * b[0] + a[1] * b[1];
const len = (a: Pt): number => Math.hypot(a[0], a[1]);
const same = (a: Pt, b: Pt): boolean => len(sub(a, b)) < EPS;
/** Parallel and pointing the same way. */
const along = (a: Pt, b: Pt): boolean => Math.abs(cross(a, b)) < EPS && dotp(a, b) > 0;

/**
 * Every straight segment of a glyph, the closing edge of a closed subpath
 * included: a `z` strokes that edge as surely as an `L` does.
 */
function lines(d: string): [Pt, Pt][] {
  return subpaths(d).flatMap((s) => {
    const out = s.segments.filter((g) => g.kind === 'L').map((g) => [g.from, g.to] as [Pt, Pt]);
    const last = s.segments[s.segments.length - 1];
    if (s.closed && last !== undefined && !same(last.to, s.start)) out.push([last.to, s.start]);
    return out;
  });
}

/** True when `p` lies on the segment `a`..`b`. */
function onSegment(p: Pt, [a, b]: [Pt, Pt]): boolean {
  const ab = sub(b, a);
  const ap = sub(p, a);
  if (Math.abs(cross(ab, ap)) > EPS) return false;
  const t = dotp(ap, ab) / dotp(ab, ab);
  return t > -EPS && t < 1 + EPS;
}

/** A straight stroke runs from `p` to `q`, on its own or as part of a longer one. */
function drawn(d: string, p: Pt, q: Pt): boolean {
  return lines(d).some((s) => onSegment(p, s) && onSegment(q, s));
}

/** Centres of the round marks a glyph's accent fills. */
function pivots(id: string): Pt[] {
  return subpaths(DRAWING_TOOL_ACCENTS[id] ?? '').map((s) => {
    const xs = s.extent.map((p) => p[0]);
    const ys = s.extent.map((p) => p[1]);
    return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2] as Pt;
  });
}

/** A full circle drawn as one closed subpath of arcs: its centre and radius. */
function circles(d: string): { c: Pt; r: number }[] {
  const out: { c: Pt; r: number }[] = [];
  for (const s of subpaths(d)) {
    if (!isClosed(s) || s.segments.some((g) => g.kind !== 'A')) continue;
    const xs = s.extent.map((p) => p[0]);
    const ys = s.extent.map((p) => p[1]);
    const c: Pt = [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
    const r = (Math.max(...xs) - Math.min(...xs)) / 2;
    if (r > 1 && s.extent.every((p) => Math.abs(len(sub(p, c)) - r) < 1e-3)) out.push({ c, r });
  }
  return out;
}

/** The arcs of a glyph that are part of one circle about `c`, with their radius. */
function arcsAbout(d: string, c: Pt): { g: Extract<Segment, { kind: 'A' }>; r: number }[] {
  const out: { g: Extract<Segment, { kind: 'A' }>; r: number }[] = [];
  for (const s of subpaths(d)) {
    for (const g of s.segments) {
      if (g.kind !== 'A') continue;
      const pts = [g.from, ...samples(g)];
      const r = len(sub(g.from, c));
      if (pts.every((p) => Math.abs(len(sub(p, c)) - r) < 1e-3)) out.push({ g, r });
    }
  }
  return out;
}

/** The distance from `p` to the infinite line through `a` and `b`. */
function toLine(p: Pt, a: Pt, b: Pt): number {
  return Math.abs(cross(sub(b, a), sub(p, a))) / len(sub(b, a));
}

/**
 * A closed, upright rectangle among a glyph's subpaths: its corners in
 * drawing order and its four edges, the closing edge included.
 */
function box(d: string): { corners: Pt[]; edges: [Pt, Pt][] } | undefined {
  for (const s of subpaths(d)) {
    if (!isClosed(s) || s.segments.some((g) => g.kind !== 'L')) continue;
    const corners = s.points.filter((p, i) => i === 0 || !same(p, s.points[0]));
    if (corners.length !== 4) continue;
    const edges = corners.map((p, i) => [p, corners[(i + 1) % 4]] as [Pt, Pt]);
    if (edges.every(([a, b]) => a[0] === b[0] || a[1] === b[1])) return { corners, edges };
  }
  return undefined;
}

interface Trident { P: Pt; Q: Pt; M: Pt; u: Pt }

/**
 * A fork: three parallel tines of one length leaving the two ends and the
 * midpoint of a crossbar, on one side of it. `u` runs from the crossbar to
 * the tips. A tine may be the far end of a longer stroke, as the median is
 * when a handle continues it.
 */
function trident(d: string): Trident | undefined {
  const segs = lines(d);
  for (const [P, Q] of segs) {
    const M = mid(P, Q);
    for (const t of segs) {
      const tip = same(t[0], P) ? t[1] : same(t[1], P) ? t[0] : undefined;
      if (tip === undefined) continue;
      const u = sub(tip, P);
      if (Math.abs(cross(u, sub(Q, P))) < EPS) continue;
      if (drawn(d, M, add(M, u)) && drawn(d, Q, add(Q, u))) return { P, Q, M, u };
    }
  }
  return undefined;
}

describe('the pitchfork family are tridents told apart by where the median starts', () => {
  const FORKS = ['pitchfork', 'schiff-pitchfork', 'modified-schiff-pitchfork', 'inside-pitchfork'];

  it.each(FORKS)('%s is a fork: three parallel tines on a crossbar, and one pivot', (id) => {
    // The tool draws a crossbar between its second and third anchors and
    // three parallel rays from its ends and middle. The old glyphs crossed
    // their tines through the handle, and read as an X.
    expect(trident(glyph(id)), `${id} has no crossbar with three tines`).toBeDefined();
    expect(pivots(id)).toHaveLength(1);
  });

  const fork = (id: string): Trident & { A: Pt } => {
    const t = trident(glyph(id));
    expect(t, `${id} has no crossbar with three tines`).toBeDefined();
    expect(pivots(id)).toHaveLength(1);
    return { ...t!, A: pivots(id)[0] };
  };

  it('starts the standard median at the pivot: one straight handle', () => {
    const { M, u, A } = fork('pitchfork');
    expect(drawn(glyph('pitchfork'), M, A)).toBe(true);
    expect(along(sub(M, A), u), 'the handle continues the median').toBe(true);
  });

  it('starts the Schiff median half a swing above the pivot: a handle, then the price shift at right angles', () => {
    // The tool starts the median at the pivot's time and halfway to the
    // second anchor's price, so the pivot sits off the handle, square to it.
    const d = glyph('schiff-pitchfork');
    const { M, u, A } = fork('schiff-pitchfork');
    const bases = lines(d).flatMap(([a, b]) => [a, b]).filter((p) => !same(p, M) && !same(p, A)
      && drawn(d, M, p) && along(sub(M, p), u) && drawn(d, p, A));
    expect(bases, 'a handle that turns to the pivot').not.toHaveLength(0);
    for (const base of bases) expect(Math.abs(dotp(sub(A, base), u))).toBeLessThan(EPS);
  });

  it('starts the modified Schiff median at the midpoint of the swing from the pivot', () => {
    // Shifted in time as well as price: the median leaves the middle of the
    // leg from the pivot to the crossbar's end, and the glyph draws that leg.
    const d = glyph('modified-schiff-pitchfork');
    const { P, Q, M, u, A } = fork('modified-schiff-pitchfork');
    const legs = [P, Q].filter((B) => drawn(d, A, B));
    expect(legs).toHaveLength(1);
    const base = mid(A, legs[0]);
    expect(drawn(d, M, base)).toBe(true);
    expect(along(sub(M, base), u)).toBe(true);
  });

  it('starts the inside median on the crossbar itself: no handle, the fork inside the swing', () => {
    const d = glyph('inside-pitchfork');
    const { P, Q, M, u, A } = fork('inside-pitchfork');
    expect(drawn(d, A, P) && drawn(d, A, Q), 'the swing joins the pivot to both crossbar ends').toBe(true);
    expect(drawn(d, M, sub(M, scale(u, 1 / len(u)))), 'a handle below the crossbar').toBe(false);
  });
});

describe('the Fibonacci and Gann constructions', () => {
  it('draws Fib circles as concentric circles', () => {
    // The tool rings one centre at each level. Two half rings side by side,
    // as before, read as a crescent.
    const found = circles(glyph('fib-circles'));
    expect(found.length).toBeGreaterThanOrEqual(3);
    for (const { c } of found) expect(same(c, found[0].c)).toBe(true);
    expect(new Set(found.map((f) => f.r)).size).toBe(found.length);
  });

  it('draws the Fib spiral as one clean stroke of quarter turns growing as Fibonacci numbers', () => {
    // The tool's spiral grows by the golden ratio every quarter turn, which
    // quarter arcs of consecutive Fibonacci radii follow. Each arc has to
    // leave where the last one ended, heading the way it was heading: the old
    // arcs met at corners, and the last, too short a chord for its radius,
    // bulged out past the box as a stray tail. The last turn may stop short
    // of a quarter, which is how the largest radius fits the box.
    const s = subpaths(glyph('fib-spiral'));
    expect(s, 'one stroke').toHaveLength(1);
    const arcs = s[0].segments;
    expect(arcs.length).toBeGreaterThanOrEqual(4);
    let c: Pt | undefined;
    const radii: number[] = [];
    arcs.forEach((g, i) => {
      expect(g.kind).toBe('A');
      if (g.kind !== 'A' || arcs[0].kind !== 'A') return;
      const r = g.rx;
      expect(g.ry).toBe(r);
      expect(g.sweep, 'one direction of turn').toBe(arcs[0].sweep);
      const [dx, dy] = sub(g.to, g.from);
      if (i < arcs.length - 1) expect([Math.abs(dx), Math.abs(dy)], 'a quarter turn').toEqual([r, r]);
      else expect(len([dx, dy]), 'at most a quarter turn').toBeLessThanOrEqual(r * Math.SQRT2 + EPS);
      if (c === undefined) {
        // The first quarter arc's centre is one of the two corners its chord
        // spans; the sweep says which.
        c = ([[g.from[0], g.to[1]], [g.to[0], g.from[1]]] as Pt[])
          .find((k) => Math.sign(cross(sub(g.from, k), sub(g.to, k))) === (g.sweep === 1 ? 1 : -1))!;
      } else {
        // Tangent at the join: the next centre lies on the radius through
        // it, on the same side, so the stroke turns on without a corner.
        const toward = sub(c, g.from);
        c = add(g.from, scale(toward, r / len(toward)));
      }
      const centre = c;
      for (const p of samples(g)) expect(Math.abs(len(sub(p, centre)) - r), `arc ${i} about its centre`).toBeLessThan(1e-3);
      radii.push(r);
    });
    for (let i = 2; i < radii.length; i++) expect(radii[i], `radii ${radii.join(', ')}`).toBe(radii[i - 1] + radii[i - 2]);
    for (const [x, y] of s[0].extent) {
      expect(x).toBeGreaterThanOrEqual(2 - 1e-9);
      expect(x).toBeLessThanOrEqual(22 + 1e-9);
      expect(y).toBeGreaterThanOrEqual(2 - 1e-9);
      expect(y).toBeLessThanOrEqual(22 + 1e-9);
    }
  });

  it('draws the Fib wedge as a sector: two radii and its levels as arcs between them', () => {
    const d = glyph('fib-wedge');
    const ends = lines(d);
    const centres = ends.flatMap(([a, b]) => [a, b])
      .filter((p) => ends.filter(([a, b]) => same(a, p) || same(b, p)).length >= 2);
    expect(centres.length).toBeGreaterThan(0);
    const O = centres[0];
    const radii = ends.filter(([a, b]) => same(a, O) || same(b, O)).map(([a, b]) => (same(a, O) ? b : a));
    expect(radii).toHaveLength(2);
    const R = len(sub(radii[0], O));
    expect(len(sub(radii[1], O))).toBeCloseTo(R, 9);
    const arcs = arcsAbout(d, O);
    expect(arcs.length).toBeGreaterThanOrEqual(2);
    for (const { g } of arcs) {
      // Every level runs from one radius to the other.
      const onFirst = (p: Pt): boolean => onSegment(p, [O, radii[0]]);
      const onSecond = (p: Pt): boolean => onSegment(p, [O, radii[1]]);
      expect((onFirst(g.from) && onSecond(g.to)) || (onSecond(g.from) && onFirst(g.to))).toBe(true);
    }
    expect(Math.max(...arcs.map((a) => a.r)), 'the outer level closes the sector').toBeCloseTo(R, 9);
  });

  it('draws the speed resistance arcs as half circles about the trend start, facing along the trend', () => {
    // The tool centres each level's half circle on the first anchor and turns
    // it to face the second, with the trend line through their crowns.
    const d = glyph('fib-speed-resistance-arcs');
    const trend = lines(d);
    expect(trend).toHaveLength(1);
    const found = trend.flatMap(([a, b]) => [[a, b], [b, a]] as [Pt, Pt][]).map(([O, B]) => ({ O, B, arcs: arcsAbout(d, O) }))
      .filter((t) => t.arcs.length >= 2);
    expect(found).toHaveLength(1);
    const { O, B, arcs } = found[0];
    for (const { g } of arcs) {
      expect(same(mid(g.from, g.to), O), 'a half turn').toBe(true);
      const pts = samples(g);
      const crown = pts[Math.floor(pts.length / 2) - 1];
      expect(toLine(crown, O, B)).toBeLessThan(0.05);
      expect(dotp(sub(crown, O), sub(B, O))).toBeGreaterThan(0);
    }
  });

  it('draws the speed resistance fan as its tool does: the far edges of its box, and rays to both', () => {
    // The tool marks the box the two anchors span by its two far edges only,
    // and splits both at the same levels, so the fan opens both ways about
    // the diagonal. The glyph of 2.5.8 drew the near axes and was the speed
    // fan beside it; a whole box made it the Gann box and square, which sit
    // in the same flyout.
    const d = glyph('fib-speed-resistance-fan');
    const segs = lines(d);
    const axial = (a: Pt, b: Pt): boolean => a[0] === b[0] || a[1] === b[1];
    const fans: Pt[] = [];
    for (const s of segs) {
      for (const t of segs) {
        if (s === t || !axial(...s) || !axial(...t)) continue;
        // Two edges of the box meeting square at its far corner B.
        const B = [s[0], s[1]].find((p) => same(p, t[0]) || same(p, t[1]));
        if (B === undefined) continue;
        const E1 = same(s[0], B) ? s[1] : s[0];
        const E2 = same(t[0], B) ? t[1] : t[0];
        if (Math.abs(dotp(sub(E1, B), sub(E2, B))) > EPS) continue;
        const O = sub(add(E1, E2), B);
        const rays = segs.filter(([a, b]) => same(a, O) || same(b, O)).map(([a, b]) => (same(a, O) ? b : a));
        const interior = (e: [Pt, Pt]): boolean => rays.some((r) => onSegment(r, e) && !same(r, e[0]) && !same(r, e[1]));
        const lies = (e: [Pt, Pt]): boolean => segs.some((g) => !same(g[0], g[1]) && onSegment(g[0], e) && onSegment(g[1], e));
        const far: [Pt, Pt][] = [[B, E1], [B, E2]];
        const near: [Pt, Pt][] = [[O, E1], [O, E2]];
        if (drawn(d, O, B) && far.every(interior) && !near.some(lies)) fans.push(O);
      }
    }
    expect(fans.length, 'one corner fanning to the far edges, with no near edge drawn').toBeGreaterThan(0);
    expect(fans.every((O) => same(O, fans[0]))).toBe(true);
  });

  it('draws the Dedekind tessellation as its tool does: arcs standing on the base of a square', () => {
    // A square as tall as the unit arcs, which stand on its bottom corners;
    // smaller arcs a third of that on the same base, and the wall at half.
    const d = glyph('dedekind-tessellation');
    const frame = box(d);
    expect(frame, 'a square').toBeDefined();
    const xs = frame!.corners.map((p) => p[0]);
    const ys = frame!.corners.map((p) => p[1]);
    const [left, right, top, bottom] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
    const h = bottom - top;
    expect(right - left).toBe(h);
    for (const corner of [[left, bottom], [right, bottom]] as Pt[]) {
      expect(arcsAbout(d, corner).some((a) => Math.abs(a.r - h) < EPS), `a unit arc on ${corner}`).toBe(true);
    }
    const small = subpaths(d).flatMap((s) => s.segments).filter((g): g is Extract<Segment, { kind: 'A' }> =>
      g.kind === 'A' && g.from[1] === bottom && g.to[1] === bottom && Math.abs(len(sub(g.to, g.from)) / 2 - h / 3) < EPS);
    expect(small.length).toBeGreaterThanOrEqual(1);
    expect(drawn(d, [left + h / 2, top], [left + h / 2, bottom]), 'the wall at half the height').toBe(true);
  });
});

describe('the supersonic pair are waves inside a Mach cone', () => {
  /** The cone: two strokes from one nose, mirrored about an axis. */
  function cone(d: string): { nose: Pt; ends: [Pt, Pt] } {
    const s = lines(d);
    for (let i = 0; i < s.length; i++) {
      for (let j = i + 1; j < s.length; j++) {
        for (const [a, b] of [[s[i], s[j]], [s[i], [s[j][1], s[j][0]]], [[s[i][1], s[i][0]], s[j]], [[s[i][1], s[i][0]], [s[j][1], s[j][0]]]] as [Pt, Pt][][]) {
          if (same(a[0], b[0]) && Math.abs(len(sub(a[1], a[0])) - len(sub(b[1], b[0]))) < EPS) return { nose: a[0], ends: [a[1], b[1]] };
        }
      }
    }
    throw new Error('no cone');
  }

  it.each(['supersonic', 'golden-supersonic'])('%s rings the axis with circles tangent to both sides of the cone', (id) => {
    // The tool centres every wave on the cone's axis, each tangent to both
    // of its sides. The old glyphs drew half rings across the cone.
    const d = glyph(id);
    const { nose, ends } = cone(d);
    const axis = mid(ends[0], ends[1]);
    const rings = circles(d);
    expect(rings.length).toBeGreaterThanOrEqual(2);
    for (const { c, r } of rings) {
      expect(toLine(c, nose, axis), 'on the axis').toBeLessThan(EPS);
      // Whole units put a side's slope a little off the exact one, and the
      // smallest golden wave sits a third of a unit inside so that the next
      // wave's line does not fill it; half a unit off would read as a ring
      // crossing the cone rather than touching it.
      for (const side of ends) expect(Math.abs(toLine(c, nose, side) - r), `${id} ring ${r} against its side`).toBeLessThan(0.4);
    }
  });

  it('grows the supersonic waves in equal steps and the golden ones as Fibonacci numbers', () => {
    // The two tools differ only in their levels: whole multiples for the
    // one, golden ratios for the other. The glyphs show that and nothing else.
    const plain = circles(glyph('supersonic')).map((c) => c.r).sort((a, b) => a - b);
    const golden = circles(glyph('golden-supersonic')).map((c) => c.r).sort((a, b) => a - b);
    expect(plain.map((r) => r / plain[0])).toEqual(plain.map((_, i) => i + 1));
    expect(golden.length).toBeGreaterThanOrEqual(3);
    for (let i = 2; i < golden.length; i++) expect(golden[i]).toBe(golden[i - 1] + golden[i - 2]);
  });
});

describe('the harmonic patterns are drawn to their own ratios', () => {
  const NAMES: Record<string, string> = {
    gartley: 'Gartley', bat: 'Bat', butterfly: 'Butterfly', crab: 'Crab', shark: 'Shark', cypher: 'Cypher',
  };
  const HARMONICS = Object.keys(NAMES);
  const rc = {
    plotWidth: 2400, plotHeight: 2400, dpr: 1, priceAxisWidth: 60,
    priceScale: { priceToY: (price: number) => 2400 - price, format: String },
    timeScale: { indexToX: (index: number) => index },
    dataLayer: { timeToIndexFloat: (time: number) => time },
  } as unknown as PrimitiveRenderContext;
  const tool = (id: string): DrawingTool => PATTERN_DRAWING_TOOLS.find((t) => t.id === id)!;

  /** The glyph's X, A, B, C and D: the one stroke with five vertices. */
  function vertices(id: string): Pt[] {
    const legs = subpaths(glyph(id)).filter((s) => s.points.length === 5);
    expect(legs, `${id} has one five-point leg stroke`).toHaveLength(1);
    return legs[0].points;
  }

  /** What the pattern tool says of a drawing through the glyph's vertices. */
  function verdict(toolId: string, pts: Pt[]): string | undefined {
    // Grid units scaled up a hundredfold, price up the page as on a chart.
    const points = pts.map(([x, y]) => ({ time: x * 100, price: (24 - y) * 100 }));
    const d: Drawing = { id: 'glyph', tool: toolId, points, style: { ...tool(toolId).defaultStyle }, paneIndex: 0, zIndex: 0 };
    const rec = new RecordingContext();
    tool(toolId).draw({
      ctx: rec as unknown as CanvasRenderingContext2D, rc,
      pts: points.map((p) => ({ x: p.time, y: 2400 - p.price })),
      drawing: d, style: { color: '#000', lineWidth: 2, ...d.style }, selected: false, formatPrice: String,
    });
    return rec.ops.filter((op) => op.type === 'fillText').map((op) => op.text!).find((t) => t.startsWith(`${NAMES[toolId]}:`));
  }

  it.each(HARMONICS)('%s is a valid instance of its own pattern, and of no other harmonic', (id) => {
    // What tells one harmonic from another is where B and D fall against XA,
    // and the tool that draws each one checks exactly that. The six glyphs
    // were drawn by eye and five failed their own tool's check; drawn to the
    // ratios, each reads as the pattern a trader looks for, and no two can
    // be the same picture.
    const pts = vertices(id);
    expect(verdict(id, pts)).toBe(`${NAMES[id]}: valid`);
    for (const other of HARMONICS.filter((o) => o !== id)) {
      expect(verdict(other, pts), `${id} also passes as ${other}`).not.toBe(`${NAMES[other]}: valid`);
    }
  });

  it.each(HARMONICS)('%s outlines the two triangles its tool fills', (id) => {
    // The tool fills XAB and BCD; their bases XB and BD are what make a
    // harmonic read as one rather than as a plain zigzag.
    const [X, , B, , D] = vertices(id);
    expect(drawn(glyph(id), X, B) && drawn(glyph(id), B, D)).toBe(true);
  });
});
