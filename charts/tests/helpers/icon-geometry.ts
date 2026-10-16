/**
 * Path geometry for the icon tests.
 *
 * SVG path data walked into absolute subpaths of segments, so a check can
 * reason about the drawing rather than about how its string happened to be
 * written: the same box from another corner, a line from its other end, an
 * arc started on its far side and a smooth curve spelled out in full are one
 * picture each, and the checks built on this treat them as one.
 */

export type Pt = readonly [number, number];

export type Segment =
  | { readonly kind: 'L'; readonly from: Pt; readonly to: Pt }
  | { readonly kind: 'C'; readonly from: Pt; readonly c1: Pt; readonly c2: Pt; readonly to: Pt }
  | { readonly kind: 'Q'; readonly from: Pt; readonly c: Pt; readonly to: Pt }
  | {
    readonly kind: 'A'; readonly from: Pt; readonly rx: number; readonly ry: number;
    readonly rot: number; readonly large: number; readonly sweep: number; readonly to: Pt;
  };

/** One subpath of a glyph, in absolute coordinates. */
export interface Subpath {
  readonly start: Pt;
  readonly segments: Segment[];
  /** Ended with `z`. */
  closed: boolean;
  /** The on-grid points: the start, then each segment's endpoint. */
  readonly points: Pt[];
  /** Points along every segment, curves and arcs included: the extent a stroke covers. */
  readonly extent: Pt[];
}

/** Every number literal in a path, as written. */
export function coords(d: string): number[] {
  return (d.match(/-?\d+(\.\d+)?/g) ?? []).map(Number);
}

/**
 * Points along an SVG elliptical arc, from its endpoint form (SVG 1.1 F.6.5).
 * Sixteen samples per half turn: enough for an extent and for a distance.
 */
export function arcSamples(
  x1: number, y1: number, rx: number, ry: number, rot: number, large: number, sweep: number, x2: number, y2: number,
): Pt[] {
  if (rx === 0 || ry === 0 || (x1 === x2 && y1 === y2)) return [[x2, y2]];
  const phi = (rot * Math.PI) / 180;
  const cos = Math.cos(phi);
  const sin = Math.sin(phi);
  const dx = (x1 - x2) / 2;
  const dy = (y1 - y2) / 2;
  const xp = cos * dx + sin * dy;
  const yp = -sin * dx + cos * dy;
  let a = Math.abs(rx);
  let b = Math.abs(ry);
  const scale = (xp * xp) / (a * a) + (yp * yp) / (b * b);
  if (scale > 1) { a *= Math.sqrt(scale); b *= Math.sqrt(scale); }
  const num = a * a * b * b - a * a * yp * yp - b * b * xp * xp;
  const den = a * a * yp * yp + b * b * xp * xp;
  const k = (large === sweep ? -1 : 1) * Math.sqrt(Math.max(0, num / den));
  const cxp = (k * a * yp) / b;
  const cyp = (-k * b * xp) / a;
  const cx = cos * cxp - sin * cyp + (x1 + x2) / 2;
  const cy = sin * cxp + cos * cyp + (y1 + y2) / 2;
  const angle = (ux: number, uy: number, vx: number, vy: number): number =>
    Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy);
  const t1 = angle(1, 0, (xp - cxp) / a, (yp - cyp) / b);
  let dt = angle((xp - cxp) / a, (yp - cyp) / b, (-xp - cxp) / a, (-yp - cyp) / b);
  if (sweep === 0 && dt > 0) dt -= 2 * Math.PI;
  if (sweep === 1 && dt < 0) dt += 2 * Math.PI;
  const steps = Math.max(2, Math.ceil(Math.abs(dt) / (Math.PI / 16)));
  const out: Pt[] = [];
  for (let i = 1; i <= steps; i++) {
    const t = t1 + (dt * i) / steps;
    out.push([cx + a * Math.cos(t) * cos - b * Math.sin(t) * sin, cy + a * Math.cos(t) * sin + b * Math.sin(t) * cos]);
  }
  return out;
}

/** Points along one segment after its start, in order, ending on its endpoint. */
export function samples(g: Segment): Pt[] {
  const n = 16;
  const out: Pt[] = [];
  switch (g.kind) {
    case 'L': return [g.to];
    case 'C':
      for (let i = 1; i <= n; i++) {
        const t = i / n; const u = 1 - t;
        out.push([
          u * u * u * g.from[0] + 3 * u * u * t * g.c1[0] + 3 * u * t * t * g.c2[0] + t * t * t * g.to[0],
          u * u * u * g.from[1] + 3 * u * u * t * g.c1[1] + 3 * u * t * t * g.c2[1] + t * t * t * g.to[1],
        ]);
      }
      return out;
    case 'Q':
      for (let i = 1; i <= n; i++) {
        const t = i / n; const u = 1 - t;
        out.push([
          u * u * g.from[0] + 2 * u * t * g.c[0] + t * t * g.to[0],
          u * u * g.from[1] + 2 * u * t * g.c[1] + t * t * g.to[1],
        ]);
      }
      return out;
    case 'A': return arcSamples(g.from[0], g.from[1], g.rx, g.ry, g.rot, g.large, g.sweep, g.to[0], g.to[1]);
  }
}

/**
 * A path walked into absolute subpaths. Relative commands carry the pen from
 * the current point, the smooth shorthands are expanded to the curve they
 * stand for, and a drawing command after `z` opens a new subpath where the
 * closed one started, as the SVG rules have it.
 */
export function subpaths(d: string): Subpath[] {
  const out: Subpath[] = [];
  let cur: Subpath | undefined;
  let x = 0;
  let y = 0;
  let sx = 0;
  let sy = 0;
  // The last control point, for S and T to reflect.
  let lastC: Pt | undefined;
  let lastQ: Pt | undefined;
  const open = (px: number, py: number): void => {
    cur = { start: [px, py], segments: [], closed: false, points: [[px, py]], extent: [[px, py]] };
    out.push(cur);
    x = sx = px;
    y = sy = py;
  };
  const add = (g: Segment): void => {
    if (cur === undefined) open(x, y);
    cur!.segments.push(g);
    cur!.points.push(g.to);
    cur!.extent.push(...samples(g));
    x = g.to[0];
    y = g.to[1];
  };
  for (const m of d.matchAll(/([MmLlHhVvCcSsQqTtAaZz])([^A-Za-z]*)/g)) {
    const cmd = m[1];
    const up = cmd.toUpperCase();
    const rel = cmd !== up;
    const n = coords(m[2]);
    const ox = (): number => (rel ? x : 0);
    const oy = (): number => (rel ? y : 0);
    if (up !== 'C' && up !== 'S') lastC = undefined;
    if (up !== 'Q' && up !== 'T') lastQ = undefined;
    switch (up) {
      case 'M':
        for (let i = 0; i + 1 < n.length; i += 2) {
          // A leading lower-case m is absolute: there is no current point yet.
          const base = rel && (i > 0 || out.length > 0);
          const p: Pt = [(base ? x : 0) + n[i], (base ? y : 0) + n[i + 1]];
          if (i === 0) open(p[0], p[1]); else add({ kind: 'L', from: [x, y], to: p });
        }
        break;
      case 'L':
        for (let i = 0; i + 1 < n.length; i += 2) add({ kind: 'L', from: [x, y], to: [ox() + n[i], oy() + n[i + 1]] });
        break;
      case 'H': for (const v of n) add({ kind: 'L', from: [x, y], to: [ox() + v, y] }); break;
      case 'V': for (const v of n) add({ kind: 'L', from: [x, y], to: [x, oy() + v] }); break;
      case 'C':
        for (let i = 0; i + 5 < n.length; i += 6) {
          const c1: Pt = [ox() + n[i], oy() + n[i + 1]];
          const c2: Pt = [ox() + n[i + 2], oy() + n[i + 3]];
          const to: Pt = [ox() + n[i + 4], oy() + n[i + 5]];
          add({ kind: 'C', from: [x, y], c1, c2, to });
          lastC = c2;
        }
        break;
      case 'S':
        for (let i = 0; i + 3 < n.length; i += 4) {
          const c1: Pt = lastC === undefined ? [x, y] : [2 * x - lastC[0], 2 * y - lastC[1]];
          const c2: Pt = [ox() + n[i], oy() + n[i + 1]];
          const to: Pt = [ox() + n[i + 2], oy() + n[i + 3]];
          add({ kind: 'C', from: [x, y], c1, c2, to });
          lastC = c2;
        }
        break;
      case 'Q':
        for (let i = 0; i + 3 < n.length; i += 4) {
          const c: Pt = [ox() + n[i], oy() + n[i + 1]];
          add({ kind: 'Q', from: [x, y], c, to: [ox() + n[i + 2], oy() + n[i + 3]] });
          lastQ = c;
        }
        break;
      case 'T':
        for (let i = 0; i + 1 < n.length; i += 2) {
          const c: Pt = lastQ === undefined ? [x, y] : [2 * x - lastQ[0], 2 * y - lastQ[1]];
          add({ kind: 'Q', from: [x, y], c, to: [ox() + n[i], oy() + n[i + 1]] });
          lastQ = c;
        }
        break;
      case 'A':
        for (let i = 0; i + 6 < n.length; i += 7) {
          add({
            kind: 'A', from: [x, y], rx: n[i], ry: n[i + 1], rot: n[i + 2], large: n[i + 3], sweep: n[i + 4],
            to: [ox() + n[i + 5], oy() + n[i + 6]],
          });
        }
        break;
      case 'Z':
        if (cur !== undefined) cur.closed = true;
        cur = undefined;
        x = sx;
        y = sy;
        break;
      default: break;
    }
  }
  return out;
}

/**
 * Coordinates that are positions on the grid: each subpath's start and every
 * segment's endpoint. Control points and arc radii are not grid points.
 */
export function gridPoints(d: string): number[] {
  return subpaths(d).flatMap((s) => s.points.flatMap((p) => [p[0], p[1]]));
}

const same = (a: Pt, b: Pt): boolean => a[0] === b[0] && a[1] === b[1];

/** True when a subpath encloses an area: it ends with z, or returns to where it started. */
export function isClosed(s: Subpath): boolean {
  const last = s.segments[s.segments.length - 1];
  return s.closed || (s.segments.length > 1 && last !== undefined && same(last.to, s.start));
}

/** A closed subpath's segments with the closing edge made explicit. */
function ring(s: Subpath): Segment[] {
  const segs = [...s.segments];
  const last = segs[segs.length - 1];
  if (last !== undefined && !same(last.to, s.start)) segs.push({ kind: 'L', from: last.to, to: s.start });
  return segs;
}

/** The same segment walked the other way. */
function reversed(g: Segment): Segment {
  switch (g.kind) {
    case 'L': return { kind: 'L', from: g.to, to: g.from };
    case 'C': return { kind: 'C', from: g.to, c1: g.c2, c2: g.c1, to: g.from };
    case 'Q': return { kind: 'Q', from: g.to, c: g.c, to: g.from };
    case 'A': return { ...g, from: g.to, to: g.from, sweep: 1 - g.sweep };
  }
}

function token(g: Segment): string {
  switch (g.kind) {
    case 'L': return `L${g.to}`;
    case 'C': return `C${g.c1} ${g.c2} ${g.to}`;
    case 'Q': return `Q${g.c} ${g.to}`;
    case 'A': return `A${g.rx},${g.ry},${g.rot},${g.large},${g.sweep} ${g.to}`;
  }
}

function written(segs: readonly Segment[]): string {
  return `M${segs[0].from}${segs.map(token).join('')}`;
}

/**
 * A subpath as a string that ignores how it was written: an open one read from
 * whichever end sorts first, a closed one from any of its vertices in either
 * direction. Curves and arcs reverse with their control points and sweep, so
 * an arc drawn from its other end, or a dot started on its far side, keys the
 * same as the original.
 */
export function subpathKey(s: Subpath): string {
  if (s.segments.length === 0) return `M${s.start}`;
  if (!isClosed(s)) {
    const fwd = written(s.segments);
    const back = written([...s.segments].reverse().map(reversed));
    return `O${fwd < back ? fwd : back}`;
  }
  const segs = ring(s);
  let best = '';
  for (let i = 0; i < segs.length; i++) {
    const turned = [...segs.slice(i), ...segs.slice(0, i)];
    for (const cand of [written(turned), written([...turned].reverse().map(reversed))]) {
      if (best === '' || cand < best) best = cand;
    }
  }
  return `Z${best}`;
}

/** A glyph keyed by its drawing: subpaths in any order, each written any way. */
export function drawingKey(d: string): string {
  return subpaths(d).map(subpathKey).sort().join(' | ');
}

/** The centre lines of a glyph as polylines, closed subpaths with their closing edge. */
export function polylines(d: string): Pt[][] {
  return subpaths(d).map((s) => {
    const segs = isClosed(s) ? ring(s) : s.segments;
    return [s.start, ...segs.flatMap(samples)];
  });
}

function distToSegment(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = dx * dx + dy * dy;
  const t = len === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

function inside(p: Pt, poly: readonly Pt[]): boolean {
  let hit = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if ((yi > p[1]) !== (yj > p[1]) && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) hit = !hit;
  }
  return hit;
}

/** How far a point is from the nearest centre line among `lines`. */
function clearOf(p: Pt, lines: readonly (readonly Pt[])[]): number {
  let near = Infinity;
  for (const line of lines) {
    for (let i = 1; i < line.length; i++) near = Math.min(near, distToSegment(p, line[i - 1], line[i]));
  }
  return near;
}

/**
 * The closed subpaths of a glyph that are hollow on their own at a stroke of
 * `stroke`, and that the rest of the glyph's strokes fill in. Hollow means
 * some point inside is clear of the shape's own outline by more than half
 * the line and a quarter pixel, so a hole shows; filled in means no point
 * inside is that clear of every centre line in the glyph. A shape too narrow
 * to show a hole by itself (a clip, a bar, a brush tip) is solid by design
 * and not reported. `skip` names subpaths meant to be solid, such as the
 * marks an accent fills.
 */
export function clotted(d: string, stroke: number, skip: ReadonlySet<string> = new Set()): string[] {
  const lines = polylines(d);
  const clearance = stroke / 2 + 0.25;
  const out: string[] = [];
  for (const s of subpaths(d)) {
    if (!isClosed(s) || skip.has(subpathKey(s))) continue;
    const poly = [s.start, ...ring(s).flatMap(samples)];
    const xs = poly.map((p) => p[0]);
    const ys = poly.map((p) => p[1]);
    let hollow = false;
    let open = false;
    for (let px = Math.min(...xs); px <= Math.max(...xs) && !open; px += 0.25) {
      for (let py = Math.min(...ys); py <= Math.max(...ys) && !open; py += 0.25) {
        const p: Pt = [px, py];
        if (!inside(p, poly) || clearOf(p, [poly]) <= clearance) continue;
        hollow = true;
        if (clearOf(p, lines) > clearance) open = true;
      }
    }
    if (hollow && !open) out.push(subpathKey(s));
  }
  return out;
}
