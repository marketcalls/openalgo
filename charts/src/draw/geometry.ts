/**
 * Hit-test geometry for the drawing tier. Everything works in media px and
 * returns a distance, so `DrawingLayer` can pick the nearest shape under the
 * cursor with one comparison rather than each tool inventing its own tolerance.
 */
import type { ScreenPoint } from './types';

/** Distance from a point to a line segment. */
export function distToSegment(px: number, py: number, a: ScreenPoint, b: ScreenPoint): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len2 = dx * dx + dy * dy;
  if (len2 === 0) return Math.hypot(px - a.x, py - a.y);
  // Project onto the segment, clamped to its ends.
  let t = ((px - a.x) * dx + (py - a.y) * dy) / len2;
  t = t < 0 ? 0 : t > 1 ? 1 : t;
  return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
}

/** Distance to an infinite line through `a` and `b`. */
export function distToLine(px: number, py: number, a: ScreenPoint, b: ScreenPoint): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy);
  if (len === 0) return Math.hypot(px - a.x, py - a.y);
  return Math.abs(dy * (px - a.x) - dx * (py - a.y)) / len;
}

/** Distance to a horizontal line at `y` (infinite in x). */
export function distToHorizontal(py: number, y: number): number {
  return Math.abs(py - y);
}

/** Distance to a vertical line at `x`. */
export function distToVertical(px: number, x: number): number {
  return Math.abs(px - x);
}

/** Distance to a polyline's nearest segment. */
export function distToPolyline(px: number, py: number, pts: readonly ScreenPoint[]): number {
  let best = Infinity;
  for (let i = 1; i < pts.length; i++) {
    const d = distToSegment(px, py, pts[i - 1]!, pts[i]!); // i is in range
    if (d < best) best = d;
  }
  return best;
}

/** Normalised rect corners from two opposite anchors. */
export function rectOf(a: ScreenPoint, b: ScreenPoint): { x0: number; y0: number; x1: number; y1: number } {
  return {
    x0: Math.min(a.x, b.x), y0: Math.min(a.y, b.y),
    x1: Math.max(a.x, b.x), y1: Math.max(a.y, b.y),
  };
}

/**
 * The axis-aligned box around any number of points. What a shape's label is
 * laid out against when the shape itself is not a rectangle (a triangle, a
 * rotated rectangle, a circle's centre plus radius).
 */
export function boundsOf(pts: readonly ScreenPoint[]): { x0: number; y0: number; x1: number; y1: number } {
  let x0 = Infinity;
  let y0 = Infinity;
  let x1 = -Infinity;
  let y1 = -Infinity;
  for (const p of pts) {
    if (p.x < x0) x0 = p.x;
    if (p.y < y0) y0 = p.y;
    if (p.x > x1) x1 = p.x;
    if (p.y > y1) y1 = p.y;
  }
  return { x0, y0, x1, y1 };
}

/**
 * Distance to a rectangle: 0 anywhere inside when `filled`, otherwise the
 * distance to the nearest edge. An unfilled rect must stay grabbable only by
 * its outline, or it would swallow every click in its interior.
 */
export function distToRect(px: number, py: number, a: ScreenPoint, b: ScreenPoint, filled: boolean): number {
  const r = rectOf(a, b);
  const inside = px >= r.x0 && px <= r.x1 && py >= r.y0 && py <= r.y1;
  if (inside && filled) return 0;
  const corners: ScreenPoint[] = [
    { x: r.x0, y: r.y0 }, { x: r.x1, y: r.y0 },
    { x: r.x1, y: r.y1 }, { x: r.x0, y: r.y1 },
  ];
  let best = Infinity;
  for (let i = 0; i < 4; i++) {
    const d = distToSegment(px, py, corners[i]!, corners[(i + 1) % 4]!); // four corners
    if (d < best) best = d;
  }
  return best;
}

/**
 * Distance to an axis-aligned ellipse inscribed in the box `a`..`b`. Uses the
 * normalised radius, scaled back by the smaller semi-axis: exact enough for a
 * grab tolerance and far cheaper than the true closest-point solve.
 */
export function distToEllipse(px: number, py: number, a: ScreenPoint, b: ScreenPoint, filled: boolean): number {
  const r = rectOf(a, b);
  const cx = (r.x0 + r.x1) / 2;
  const cy = (r.y0 + r.y1) / 2;
  const rx = Math.max(1e-6, (r.x1 - r.x0) / 2);
  const ry = Math.max(1e-6, (r.y1 - r.y0) / 2);
  const nx = (px - cx) / rx;
  const ny = (py - cy) / ry;
  const norm = Math.hypot(nx, ny);
  if (filled && norm <= 1) return 0;
  return Math.abs(norm - 1) * Math.min(rx, ry);
}

/** Clamp a segment's endpoints out to the plot edges, keeping its slope. */
export function extendSegment(
  a: ScreenPoint, b: ScreenPoint, width: number, left: boolean, right: boolean,
): [ScreenPoint, ScreenPoint] {
  const dx = b.x - a.x;
  if (dx === 0) return [a, b]; // vertical: nothing to extend along x
  const slope = (b.y - a.y) / dx;
  const start = left ? { x: 0, y: a.y + (0 - a.x) * slope } : a;
  const end = right ? { x: width, y: a.y + (width - a.x) * slope } : b;
  return [start, end];
}
