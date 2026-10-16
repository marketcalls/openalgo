/** Internal drawing geometry in media pixels, shared by paint and hit testing. */
import type { PrimitiveRenderContext } from 'openalgo-charts';
import type {
  AnchoredTool, DrawContext, Drawing, DrawingTool, HitContext, ScreenPoint, ToolAnchors,
} from './types';
import { distToSegment } from './geometry';
import { drawingTextWidth } from './text-metrics';
import { analysisNumber } from './analysis';
import { fontOf, strokeWidth, textOf } from './tool-paint';
import { dashFor } from '../render/line';

export interface GeometryPath {
  points: ScreenPoint[];
  /** Native canvas curve; points are unused when present. Radii are media px. */
  arc?: GeometryArc;
  closed?: boolean;
  /** Filled paths use the drawing's fill settings. */
  fill?: boolean;
  /** False permits fill polygons without introducing visible end caps. */
  stroke?: boolean;
  color?: string | undefined;
}
interface GeometryArc {
  center: ScreenPoint;
  rx: number;
  ry: number;
  start: number;
  sweep: number;
  /** Close a filled arc through its center, for a circular sector. */
  sector?: boolean;
}
export interface GeometryLabel { at: ScreenPoint; text: string; color?: string | undefined }
export interface DrawingGeometry { paths: GeometryPath[]; labels?: GeometryLabel[] }
/** Builds from media-px anchors, as many as the tool declares (`ToolAnchors`). */
type GeometryBuilder<N extends number = number> = (c: HitContext & ToolAnchors<N>) => DrawingGeometry;

export const midpoint = (a: ScreenPoint, b: ScreenPoint): ScreenPoint => ({ x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 });
export const interpolate = (a: ScreenPoint, b: ScreenPoint, t: number): ScreenPoint => ({ x: a.x + (b.x - a.x) * t, y: a.y + (b.y - a.y) * t });
export const finitePoint = (p: ScreenPoint): boolean => Number.isFinite(p.x) && Number.isFinite(p.y);
/** A numeric `props` entry held to `min..max`, or `fallback` when it is not a finite number. */
export function numericProp(d: Drawing, key: string, fallback: number, min: number, max: number): number {
  return analysisNumber(d.props?.[key], fallback, min, max);
}

/** Clip a parametric segment, ray or line to the plot, including vertical rays. */
export function clippedLine(
  a: ScreenPoint, b: ScreenPoint, rc: Pick<PrimitiveRenderContext, 'plotWidth' | 'plotHeight'>,
  from = 0, to = 1,
): [] | [ScreenPoint, ScreenPoint] {
  if (!finitePoint(a) || !finitePoint(b)) return [];
  const dx = b.x - a.x, dy = b.y - a.y;
  if (dx === 0 && dy === 0) return a.x >= 0 && a.x <= rc.plotWidth && a.y >= 0 && a.y <= rc.plotHeight ? [a, a] : [];
  for (const [p, delta, max] of [[a.x, dx, rc.plotWidth], [a.y, dy, rc.plotHeight]] as const) {
    if (delta === 0) { if (p < 0 || p > max) return []; continue; }
    const t0 = -p / delta, t1 = (max - p) / delta;
    from = Math.max(from, Math.min(t0, t1));
    to = Math.min(to, Math.max(t0, t1));
    if (from > to) return [];
  }
  return [interpolate(a, b, from), interpolate(a, b, to)];
}

export function extendedLine(a: ScreenPoint, b: ScreenPoint, c: HitContext): ScreenPoint[] {
  // Left/right extension changes the time span, so a vertical segment keeps
  // its anchors. Directional rays use clippedLine with explicit bounds.
  if (a.x === b.x) return clippedLine(a, b, c.rc);
  const forward = b.x >= a.x;
  return clippedLine(a, b, c.rc,
    (forward ? c.drawing.style.extendLeft : c.drawing.style.extendRight) === true ? -Infinity : 0,
    (forward ? c.drawing.style.extendRight : c.drawing.style.extendLeft) === true ? Infinity : 1);
}

/** Clip a convex fill polygon without cutting off corners between ray exits. */
export function clipPolygon(points: readonly ScreenPoint[], rc: Pick<PrimitiveRenderContext, 'plotWidth' | 'plotHeight'>): ScreenPoint[] {
  if (!points.every(finitePoint)) return [];
  let result = points.slice();
  for (const [axis, limit, sign] of [['x', 0, 1], ['x', rc.plotWidth, -1], ['y', 0, 1], ['y', rc.plotHeight, -1]] as const) {
    const input = result;
    result = [];
    for (let i = 0; i < input.length; i++) {
      const a = input[i]!, b = input[(i + 1) % input.length]!; // both indices are in 0..length-1
      const insideA = (a[axis] - limit) * sign >= 0, insideB = (b[axis] - limit) * sign >= 0;
      if (insideA) result.push(a);
      if (insideA !== insideB) result.push(interpolate(a, b, (limit - a[axis]) / (b[axis] - a[axis])));
    }
  }
  return result;
}

/** Even-odd polygon membership follows Canvas's explicit fill rule. */
export function insidePolygon(x: number, y: number, points: readonly ScreenPoint[]): boolean {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const a = points[i]!, b = points[j]!; // i and j stay in 0..length-1
    if ((a.y > y) !== (b.y > y) && x < (b.x - a.x) * (y - a.y) / (b.y - a.y) + a.x) inside = !inside;
  }
  return inside;
}

/** A bounded polyline approximation used identically for stroke and distance. */
export function sampleArc(center: ScreenPoint, rx: number, ry: number, start: number, sweep: number): ScreenPoint[] {
  const count = Math.max(2, Math.min(96, Math.ceil(Math.abs(sweep) * Math.max(Math.abs(rx), Math.abs(ry)) / 4)));
  return Array.from({ length: count + 1 }, (_, i) => {
    const angle = start + sweep * i / count;
    return { x: center.x + rx * Math.cos(angle), y: center.y + ry * Math.sin(angle) };
  });
}

const TAU = 2 * Math.PI;
function validArc(a: GeometryArc): boolean {
  return finitePoint(a.center) && [a.rx, a.ry, a.start, a.sweep, a.start + a.sweep].every(Number.isFinite) && a.rx > 0 && a.ry > 0;
}
function finiteDevicePoint(p: ScreenPoint, dpr: number): boolean {
  return finitePoint(p) && Number.isFinite(p.x * dpr) && Number.isFinite(p.y * dpr);
}
function renderablePath(path: GeometryPath, dpr: number): boolean {
  const a = path.arc;
  return a === undefined
    ? path.points.length >= 2 && path.points.every(p => finiteDevicePoint(p, dpr))
    : validArc(a) && finiteDevicePoint(a.center, dpr) && Number.isFinite(a.rx * dpr) && Number.isFinite(a.ry * dpr);
}
function arcPoint(a: GeometryArc, angle: number): ScreenPoint {
  return { x: a.center.x + a.rx * Math.cos(angle), y: a.center.y + a.ry * Math.sin(angle) };
}
function withinSweep(angle: number, a: GeometryArc): boolean {
  if (a.sweep === 0) return false;
  const delta = ((angle - a.start) * Math.sign(a.sweep) % TAU + TAU) % TAU;
  return Math.abs(a.sweep) >= TAU - 1e-12 || delta <= Math.abs(a.sweep) + 1e-12;
}
function arcDistance(x: number, y: number, a: GeometryArc): number {
  if (a.rx === a.ry && Math.abs(a.sweep) >= TAU - 1e-12) return Math.abs(Math.hypot(x - a.center.x, y - a.center.y) - a.rx);
  const first = arcPoint(a, a.start), last = arcPoint(a, a.start + a.sweep);
  const firstDistance = Math.hypot(x - first.x, y - first.y), lastDistance = Math.hypot(x - last.x, y - last.y);
  const endpoints = Math.min(firstDistance, lastDistance);
  if (a.rx === a.ry) {
    return withinSweep(Math.atan2(y - a.center.y, x - a.center.x), a)
      ? Math.abs(Math.hypot(x - a.center.x, y - a.center.y) - a.rx) : endpoints;
  }
  // A coarse bounded search locates the nearest ellipse interval; refinement
  // avoids the flat chords that make eccentric arcs hard to select precisely.
  const distance = (t: number): number => {
    const p = arcPoint(a, a.start + a.sweep * t);
    return Math.hypot(x - p.x, y - p.y);
  };
  let best = endpoints, index = lastDistance < firstDistance ? 32 : 0;
  for (let i = 0; i <= 32; i++) {
    const d = distance(i / 32);
    if (d < best) { best = d; index = i; }
  }
  let lo = Math.max(0, (index - 1) / 32), hi = Math.min(1, (index + 1) / 32);
  const refinements = Math.min(80, Math.max(32, Math.ceil(Math.log2(Math.max(a.rx, a.ry))) * 2 + 8));
  for (let i = 0; i < refinements; i++) {
    const left = lo + (hi - lo) / 3, right = hi - (hi - lo) / 3;
    if (distance(left) < distance(right)) hi = right; else lo = left;
  }
  return Math.min(best, distance((lo + hi) / 2));
}

function insideArc(x: number, y: number, a: GeometryArc): boolean {
  const nx = (x - a.center.x) / a.rx, ny = (y - a.center.y) / a.ry;
  if (nx * nx + ny * ny > 1) return false;
  if (Math.abs(a.sweep) >= TAU - 1e-12) return true;
  if (a.sector === true) return withinSweep(Math.atan2(ny, nx), a);
  const mid = a.start + a.sweep / 2;
  return nx * Math.cos(mid) + ny * Math.sin(mid) >= Math.cos(Math.abs(a.sweep) / 2);
}

export function geometryDistance(x: number, y: number, geometry: DrawingGeometry, drawing: Drawing, dpr = 1): number | null {
  let best = Infinity;
  for (const path of geometry.paths) {
    if (!renderablePath(path, dpr)) continue;
    if (path.arc !== undefined) {
      const a = path.arc;
      if (path.fill === true && drawing.style.fill === true && (drawing.style.fillOpacity ?? 0.12) > 0 && insideArc(x, y, a)) return 0;
      if (path.stroke !== false) {
        best = Math.min(best, arcDistance(x, y, a));
        if (a.sector === true || path.closed === true) {
          const first = arcPoint(a, a.start), last = arcPoint(a, a.start + a.sweep);
          if (a.sector === true) {
            best = Math.min(best, distToSegment(x, y, a.center, first));
            if (path.closed === true) best = Math.min(best, distToSegment(x, y, last, a.center));
          } else best = Math.min(best, distToSegment(x, y, last, first));
        }
      }
      continue;
    }
    const p = path.points;
    const filled = path.fill === true && drawing.style.fill === true && (drawing.style.fillOpacity ?? 0.12) > 0;
    if (filled && insidePolygon(x, y, p)) return 0;
    if (path.stroke === false) continue;
    // A renderable path has two points or more, and i is in range.
    for (let i = 1; i < p.length; i++) best = Math.min(best, distToSegment(x, y, p[i - 1]!, p[i]!));
    if (path.closed === true) best = Math.min(best, distToSegment(x, y, p[p.length - 1]!, p[0]!));
  }
  return Number.isFinite(best) ? best : null;
}

export function paintGeometry(c: DrawContext, geometry: DrawingGeometry): void {
  const { ctx, rc, style } = c, dpr = rc.dpr;
  ctx.save();
  ctx.strokeStyle = style.color;
  ctx.lineWidth = strokeWidth(style.lineWidth, dpr);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.setLineDash(dashFor(style.lineStyle, dpr));
  for (const path of geometry.paths) {
    if (!renderablePath(path, dpr)) continue;
    ctx.beginPath();
    if (path.arc !== undefined) {
      const a = path.arc;
      if (a.sector === true) ctx.moveTo(a.center.x * dpr, a.center.y * dpr);
      if (a.rx === a.ry) ctx.arc(a.center.x * dpr, a.center.y * dpr, a.rx * dpr, a.start, a.start + a.sweep, a.sweep < 0);
      else ctx.ellipse(a.center.x * dpr, a.center.y * dpr, a.rx * dpr, a.ry * dpr, 0, a.start, a.start + a.sweep, a.sweep < 0);
    } else {
      // A renderable path has two points or more, and i is in range.
      ctx.moveTo(path.points[0]!.x * dpr, path.points[0]!.y * dpr);
      for (let i = 1; i < path.points.length; i++) ctx.lineTo(path.points[i]!.x * dpr, path.points[i]!.y * dpr);
    }
    if (path.closed === true) ctx.closePath();
    if (path.fill === true && style.fill === true) {
      ctx.save();
      ctx.globalAlpha *= Math.max(0, Math.min(1, style.fillOpacity ?? 0.12));
      ctx.fillStyle = style.fillColor ?? style.color;
      ctx.fill('evenodd');
      ctx.restore();
    }
    if (path.stroke !== false) { ctx.strokeStyle = path.color ?? style.color; ctx.stroke(); }
  }
  const text = c.drawing.text;
  const size = (text?.fontSize ?? 11) * dpr;
  ctx.font = fontOf(textOf(c.drawing), size);
  ctx.textAlign = 'left';
  ctx.textBaseline = 'bottom';
  const occupied: { x: number; y: number; width: number }[] = [];
  const lineHeight = size / dpr * 1.3;
  for (const label of geometry.labels ?? []) {
    if (!finiteDevicePoint(label.at, dpr)) continue;
    let { x, y } = label.at;
    // Keep nearby levels readable at ordinary zoom and on narrow panes. The
    // bounded search changes text placement only; saved anchors stay exact.
    if (x >= 0 && x <= rc.plotWidth && y >= 0 && y <= rc.plotHeight) {
      const width = drawingTextWidth(ctx, label.text) / dpr;
      x = Math.max(0, Math.min(x, rc.plotWidth - width));
      let placed = false;
      for (const lane of [0, -1, 1, -2, 2, -3, 3, -4]) {
        const candidateY = y + lane * lineHeight;
        if (candidateY < size / dpr || candidateY > rc.plotHeight) continue;
        if (occupied.some(box => x < box.x + box.width + 3 && x + width + 3 > box.x && Math.abs(candidateY - box.y) < lineHeight - 0.01)) continue;
        y = candidateY;
        occupied.push({ x, y, width });
        placed = true;
        break;
      }
      if (!placed) continue;
    }
    ctx.fillStyle = text?.color ?? label.color ?? style.color;
    ctx.fillText(label.text, x * dpr, y * dpr);
  }
  ctx.restore();
}

/** Wrap a pure media-pixel builder in the existing device-pixel draw contract. */
export function geometryTool<N extends number>(descriptor: Omit<AnchoredTool<N>, 'draw' | 'distance'>, build: GeometryBuilder<N>): DrawingTool {
  return {
    ...descriptor,
    draw(c) {
      const pts = c.pts.map(p => ({ x: p.x / c.rc.dpr, y: p.y / c.rc.dpr })) as typeof c.pts; // one for one
      paintGeometry(c, build({ pts, drawing: { ...c.drawing, style: c.style }, rc: c.rc }));
    },
    distance(x, y, c) {
      if (x < 0 || y < 0 || x > c.rc.plotWidth || y > c.rc.plotHeight) return null;
      return geometryDistance(x, y, build(c), c.drawing, c.rc.dpr);
    },
  } satisfies AnchoredTool<N>;
}
