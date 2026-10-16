/**
 * Freehand stroke geometry for the brush and highlighter. Pure: points in,
 * points or path commands out, no DOM and no chart. Three jobs, in the order
 * a stroke meets them.
 *
 * - `rdpSimplify` thins a raw pointer trail. A drag reports a point every few
 *   px, so a two-second stroke arrives as hundreds of anchors that each cost a
 *   time/price conversion on every frame and a row in every save. Thinning
 *   keeps the shape within a pixel tolerance and drops the rest.
 * - `catmullRom` strokes what survives as a spline through the kept points,
 *   so thinning does not turn the ink into a polyline of visible corners.
 * - `pressureWidth` maps a pen's pressure onto a width around the tool's own,
 *   so a pen stroke swells and thins while a mouse, which reports 0.5, draws
 *   at the configured width.
 */
import { clamp } from '../helpers/math';
import { distToSegment } from './geometry';
import type { ScreenPoint } from './types';

/**
 * Ramer-Douglas-Peucker thinning. Keeps the first and last points and, between
 * them, only those that pull the stroke more than `epsilonPx` away from the
 * chord of their kept neighbours; every dropped point lies within `epsilonPx`
 * of the returned polyline. Kept points come back at their exact input
 * coordinates, in input order. An `epsilonPx` that is not positive returns a
 * copy. The result never aliases its input, so a caller may mutate it.
 */
export function rdpSimplify(points: ReadonlyArray<ScreenPoint>, epsilonPx: number): ScreenPoint[] {
  const n = points.length;
  if (!(epsilonPx > 0) || n < 3) return points.map((p) => ({ x: p.x, y: p.y }));
  const keep = new Uint8Array(n);
  keep[0] = 1;
  keep[n - 1] = 1;
  // An explicit stack rather than recursion: a stroke that bends one way can
  // split off a single point per pass, and that depth is the stroke length.
  const stack: number[] = [0, n - 1];
  while (stack.length > 0) {
    const last = stack.pop() as number;
    const first = stack.pop() as number;
    // Every index on the stack, and every one between two of them, is in 0..n-1.
    const a = points[first]!;
    const b = points[last]!;
    let farthest = -1;
    let maxDist = epsilonPx;
    // Measured to the chord as a segment, not the infinite line through its
    // ends: a stroke that doubles back puts its far end beyond the chord,
    // where the line distance is zero and the excursion would be thinned away.
    for (let i = first + 1; i < last; i++) {
      const d = distToSegment(points[i]!.x, points[i]!.y, a, b);
      if (d > maxDist) { maxDist = d; farthest = i; }
    }
    if (farthest < 0) continue;
    keep[farthest] = 1;
    stack.push(first, farthest, farthest, last);
  }
  const out: ScreenPoint[] = [];
  for (let i = 0; i < n; i++) if (keep[i] === 1) out.push({ x: points[i]!.x, y: points[i]!.y }); // i is in range
  return out;
}

/**
 * Appends a Catmull-Rom spline through `points` to the current path as cubic
 * beziers: one `moveTo`, then a `bezierCurveTo` per segment that ends exactly
 * on the next point. The caller owns `beginPath` and `stroke`, so the same
 * spline can also outline a filled ribbon. Two points degrade to a straight
 * `lineTo`; fewer emit nothing.
 *
 * `tension` scales the tangent at each point: 0.5 is the classic spline and 0
 * collapses every segment to a straight line. Values outside 0..1 are clamped,
 * since past 1 the tangents grow long enough for a segment to fold back on
 * itself.
 */
export function catmullRom(ctx: CanvasRenderingContext2D, points: ReadonlyArray<ScreenPoint>, tension = 0.5): void {
  const n = points.length;
  if (n < 2) return;
  // Two points or more from here, and every index below is in 0..n-1.
  ctx.moveTo(points[0]!.x, points[0]!.y);
  if (n === 2) {
    ctx.lineTo(points[1]!.x, points[1]!.y);
    return;
  }
  // The spline's tangent at a point is `tension * (next - previous)`; a cubic
  // bezier reaches that tangent with its control point a third of the way
  // along it, hence the divisor.
  const k = clamp(tension, 0, 1) / 3;
  for (let i = 0; i < n - 1; i++) {
    // The ends have no neighbour beyond them. Doubling the endpoint gives a
    // tangent that runs along the first and last segment, so the curve
    // leaves and arrives the way the stroke did.
    const p0 = points[i === 0 ? 0 : i - 1]!;
    const p1 = points[i]!;
    const p2 = points[i + 1]!;
    const p3 = points[i + 2 < n ? i + 2 : n - 1]!;
    ctx.bezierCurveTo(
      p1.x + (p2.x - p0.x) * k, p1.y + (p2.y - p0.y) * k,
      p2.x - (p3.x - p1.x) * k, p2.y - (p3.y - p1.y) * k,
      p2.x, p2.y,
    );
  }
}

/**
 * A line width scaled by pointer pressure. Pressure 0.5, which a mouse
 * reports while a button is down, returns `baseWidth` unchanged, so a stroke
 * drawn without a pen is the width the user configured. A pen sweeps the
 * width from `baseWidth * (1 - range)` at no pressure to
 * `baseWidth * (1 + range)` at full pressure. Pressure and `range` are
 * clamped to 0..1, and a pressure that is not a number (a synthetic event)
 * counts as 0.5.
 */
export function pressureWidth(baseWidth: number, pressure: number, range = 0.6): number {
  const p = Number.isFinite(pressure) ? clamp(pressure, 0, 1) : 0.5;
  return baseWidth * (1 + (p - 0.5) * 2 * clamp(range, 0, 1));
}
