/** Screen-space curves and price/time constructions for advanced drawings. */
import type { DrawingTool, FibLevel, HitContext, ScreenPoint, ToolAnchors } from './types';
import { composeSettings, FILL_FIELDS, FONT_FIELDS, LEVEL_FIELDS, LINE_FIELDS } from './schema';
import { activeLevels, cloneLevels } from './levels';
import {
  clippedLine, finitePoint, geometryTool, midpoint, numericProp,
  type DrawingGeometry, type GeometryLabel, type GeometryPath,
} from './advanced-shared';

const TAU = 2 * Math.PI, PHI = (1 + Math.sqrt(5)) / 2;
const levels = (values: number[]): readonly FibLevel[] => values.map(ratio => ({ ratio }));
const RADIAL_LEVELS = levels([0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618]);
const WEDGE_LEVELS = RADIAL_LEVELS.slice(0, 6);
const TIME_LEVELS = levels([0, 0.382, 0.618, 1, 1.382, 1.618, 2, 2.382, 2.618, 3]);
const GRID_LEVELS = levels([0, 0.25, 0.382, 0.5, 0.618, 0.75, 1]);
const WAVE_LEVELS = levels(Array.from({ length: 12 }, (_, i) => i + 1));
const GOLDEN_LEVELS = levels([0.236, 0.382, 0.5, 0.618, 0.786, 1, 1.618, 2.618, 4.236, 6.854, 11.09]);
const LEVEL_SETTINGS = composeSettings([LINE_FIELDS, LEVEL_FIELDS, FONT_FIELDS]);
const RADIAL_SETTINGS = composeSettings([LINE_FIELDS, FILL_FIELDS, LEVEL_FIELDS, FONT_FIELDS]);
const empty = (): DrawingGeometry => ({ paths: [] });
const segment = (a: ScreenPoint, b: ScreenPoint, color?: string): GeometryPath => ({ points: [a, b], color });
const curve = (center: ScreenPoint, rx: number, ry = rx, start = 0, sweep = TAU, color?: string): GeometryPath =>
  ({ points: [], arc: { center, rx, ry, start, sweep }, color });
const ready = (c: HitContext, count = 2): boolean => c.pts.length >= count && c.pts.every(finitePoint);
const label = (c: HitContext, l: FibLevel, at: ScreenPoint): GeometryLabel[] => c.drawing.style.showLabels === false
  ? [] : [{ at, text: l.label ?? String(l.ratio), color: l.color }];
function preview(c: HitContext & ToolAnchors<2>): DrawingGeometry {
  return ready(c) ? { paths: [segment(c.pts[0], c.pts[1])] } : empty();
}

const trendTime = geometryTool({
  id: 'trend-fib-time', name: 'Trend Fib Time', points: 3,
  defaultStyle: { levels: cloneLevels(TIME_LEVELS) }, settings: LEVEL_SETTINGS,
}, c => {
  if (!ready(c, 3)) return preview(c);
  const [a, b, origin] = c.drawing.points;
  const index = (time: number): number => c.rc.dataLayer.timeToIndexFloat(time);
  const span = index(b.time) - index(a.time), start = index(origin.time);
  const paths: GeometryPath[] = [], labels: GeometryLabel[] = [];
  for (const l of activeLevels(c.drawing.style.levels, TIME_LEVELS)) {
    const x = c.rc.timeScale.indexToX(start + span * l.ratio);
    if (!Number.isFinite(x) || x < 0 || x > c.rc.plotWidth) continue;
    paths.push(segment({ x, y: 0 }, { x, y: c.rc.plotHeight }, l.color));
    labels.push(...label(c, l, { x: x + 3, y: 15 }));
  }
  return { paths, labels };
});

function radial(id: string, name: string, kind: 'circle' | 'arc' | 'wedge'): DrawingTool {
  const defaults = kind === 'wedge' ? WEDGE_LEVELS : RADIAL_LEVELS;
  return geometryTool({ id, name, points: kind === 'wedge' ? 3 : 2,
    defaultStyle: { fill: false, levels: cloneLevels(defaults) }, settings: RADIAL_SETTINGS,
  }, c => {
    if (!ready(c, kind === 'wedge' ? 3 : 2)) return preview(c);
    const [a, b, other] = c.pts, radius = Math.hypot(b.x - a.x, b.y - a.y);
    if (!Number.isFinite(radius) || radius === 0) return preview(c);
    let start = 0, sweep = TAU;
    const paths: GeometryPath[] = [], labels: GeometryLabel[] = [];
    if (kind !== 'circle') {
      start = Math.atan2(b.y - a.y, b.x - a.x);
      paths.push(segment(a, b));
      if (kind === 'arc') { start -= Math.PI / 2; sweep = Math.PI; }
      else {
        const angle = Math.atan2(other!.y - a.y, other!.x - a.x); // a wedge declares three anchors
        sweep = ((angle - start + 3 * Math.PI) % TAU) - Math.PI;
        paths.push(segment(a, { x: a.x + radius * Math.cos(angle), y: a.y + radius * Math.sin(angle) }));
      }
    }
    let outer = 0;
    for (const l of activeLevels(c.drawing.style.levels, defaults)) {
      const r = radius * l.ratio;
      if (!(r > 0) || !Number.isFinite(r)) continue;
      outer = Math.max(outer, r);
      paths.push(curve(a, r, r, start, sweep, l.color));
      const angle = kind === 'circle' ? 0 : start + sweep / 2;
      labels.push(...label(c, l, { x: a.x + r * Math.cos(angle) + 3, y: a.y + r * Math.sin(angle) }));
    }
    if (outer > 0 && c.drawing.style.fill === true) {
      const fill = curve(a, outer, outer, start, sweep);
      fill.arc!.sector = kind !== 'circle';
      paths.unshift({ ...fill, fill: true, stroke: false, closed: true });
    }
    return { paths, labels };
  });
}

const spiral = geometryTool({ id: 'fib-spiral', name: 'Fib Spiral', points: 2, settings: composeSettings([LINE_FIELDS]) }, c => {
  if (!ready(c)) return empty();
  const [a, b] = c.pts, radius = Math.hypot(b.x - a.x, b.y - a.y);
  if (!Number.isFinite(radius) || radius < 0.5) return preview(c);
  const growth = Math.log(PHI) / (Math.PI / 2), angle = Math.atan2(b.y - a.y, b.x - a.x);
  const inward = Math.max(-16 * Math.PI, Math.log(0.5 / radius) / growth);
  const points: ScreenPoint[] = [];
  // Quarter-turn boundaries include the defining edge exactly. Each interval
  // adapts to its radius, with a fixed upper bound even at extreme zoom.
  const breaks = [inward];
  for (let quarter = Math.ceil(inward / (Math.PI / 2)); quarter < 2; quarter++) breaks.push(quarter * Math.PI / 2);
  breaks.push(Math.PI);
  for (let i = 1; i < breaks.length; i++) {
    const from = breaks[i - 1]!, to = breaks[i]!; // i is in range
    const count = Math.max(2, Math.min(32, Math.ceil((to - from) * Math.sqrt(radius * Math.exp(growth * to) / 0.8))));
    for (let j = i === 1 ? 0 : 1; j <= count; j++) {
      const t = from + (to - from) * j / count, r = radius * Math.exp(growth * t);
      points.push({ x: a.x + r * Math.cos(angle + t), y: a.y + r * Math.sin(angle + t) });
    }
  }
  return { paths: [{ points }] };
});

const gannSquare = geometryTool({
  id: 'gann-square', name: 'Gann Square', points: 2,
  defaultStyle: { fill: false, levels: cloneLevels(GRID_LEVELS) }, settings: RADIAL_SETTINGS,
}, c => {
  if (!ready(c)) return empty();
  const [a, b] = c.pts, [pa, pb] = c.drawing.points;
  const dx = b.x - a.x, dy = b.y - a.y;
  const left = Math.min(a.x, b.x), right = Math.max(a.x, b.x), top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y);
  const paths: GeometryPath[] = [], labels: GeometryLabel[] = [];
  if (c.drawing.style.fill === true) paths.push({ points: [{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }], closed: true, fill: true, stroke: false });
  const ia = c.rc.dataLayer.timeToIndexFloat(pa.time), ib = c.rc.dataLayer.timeToIndexFloat(pb.time);
  for (const l of activeLevels(c.drawing.style.levels, GRID_LEVELS)) {
    const x = c.rc.timeScale.indexToX(ia + (ib - ia) * l.ratio);
    const y = c.rc.priceScale.priceToY(pa.price + (pb.price - pa.price) * l.ratio);
    paths.push(segment({ x: left, y }, { x: right, y }, l.color), segment({ x, y: top }, { x, y: bottom }, l.color));
    labels.push(...label(c, l, { x: left + 3, y: y - 3 }));
  }
  for (const [x, y, name] of [[1, 1 / 3, '3x1'], [1, 0.5, '2x1'], [1, 1, '1x1'], [0.5, 1, '1x2'], [1 / 3, 1, '1x3']] as const) {
    const end = { x: a.x + dx * x, y: a.y + dy * y };
    paths.push(segment(a, end));
    if (c.drawing.style.showLabels !== false) labels.push({ at: { x: end.x + 3, y: end.y }, text: name });
  }
  if (dx !== 0 && dy !== 0) for (const k of [0.25, 0.5, 0.75, 1]) {
    paths.push(curve(a, Math.abs(dx) * k, Math.abs(dy) * k, dx > 0 ? 0 : Math.PI, Math.sign(dx * dy) * Math.PI / 2));
  }
  return { paths, labels };
});

/** Cut a native upper semicircle at the visible rectangle, never its chords. */
function clippedUpperArc(center: ScreenPoint, radius: number, left: number, right: number, top: number, bottom: number): GeometryPath[] {
  const boundaries = [-Math.PI, 0];
  for (const x of [left, right]) {
    const n = (x - center.x) / radius;
    if (Math.abs(n) < 1) boundaries.push(-Math.acos(n));
  }
  for (const y of [top, bottom]) {
    const n = (y - center.y) / radius;
    if (n > -1 && n < 0) { const angle = Math.asin(n); boundaries.push(angle, -Math.PI - angle); }
  }
  boundaries.sort((a, b) => a - b);
  const paths: GeometryPath[] = [];
  for (let i = 1; i < boundaries.length; i++) {
    const start = boundaries[i - 1]!, sweep = boundaries[i]! - start; // i is in range
    if (sweep < 1e-12) continue;
    const angle = start + sweep / 2, x = center.x + radius * Math.cos(angle), y = center.y + radius * Math.sin(angle);
    if (x < left || x > right || y < top || y > bottom) continue;
    paths.push(curve(center, radius, radius, start, sweep));
  }
  return paths;
}

const dedekind = geometryTool({
  id: 'dedekind-tessellation', name: 'Dedekind Tessellation', points: 2,
  settings: composeSettings([LINE_FIELDS, { path: 'props.maxCurvature', label: 'Max curvature', kind: 'number', min: 1, max: 64, step: 1, group: 'behavior' }]),
}, c => {
  if (!ready(c)) return empty();
  const [a, b] = c.pts, left = Math.min(a.x, b.x), right = Math.max(a.x, b.x), top = Math.min(a.y, b.y), bottom = Math.max(a.y, b.y);
  const height = bottom - top;
  if (height < 0.75 || right - left < 0.75 || !Number.isFinite(height)) return preview(c);
  const x0 = Math.max(0, left), x1 = Math.min(c.rc.plotWidth, right), y0 = Math.max(0, top), y1 = Math.min(c.rc.plotHeight, bottom);
  if (x0 > x1 || y0 > y1) return empty();
  const corners = [{ x: left, y: top }, { x: right, y: top }, { x: right, y: bottom }, { x: left, y: bottom }];
  const paths: GeometryPath[] = corners.map((p, i) => ({ points: clippedLine(p, corners[(i + 1) % 4]!, c.rc) })); // four corners
  const low = (x0 - left) / height, high = (x1 - left) / height;
  const firstWall = Math.ceil(low - 0.5) + 0.5;
  const wallCount = Math.min(2048, Math.floor(high - firstWall) + 1);
  for (let i = 0; i < wallCount; i++) {
    const x = left + (firstWall + i) * height;
    paths.push(segment({ x, y: y1 }, { x, y: y0 }));
  }
  const limit = Math.min(Math.round(numericProp(c.drawing, 'maxCurvature', 24, 1, 64)), Math.floor(height / 0.75));
  // Numerator residue classes repeat each unit. Enumerating only the visible
  // units keeps work independent of offscreen time extent and zoom history.
  for (let n = 1; n <= limit && paths.length < 4096; n++) {
    if (n % 2 === 0 && n % 8 !== 0) continue;
    const radius = height / n;
    if (bottom - radius > y1) continue;
    for (let k = 0; k < n && paths.length < 4096; k++) {
      const value = k * k - 1;
      if (value % n !== 0 || n % 8 === 0 && Math.abs(value / n) % 2 !== 1) continue;
      const first = Math.ceil(low - 1 / n - k / n), last = Math.floor(high + 1 / n - k / n);
      const count = Math.min(4096 - paths.length, last - first + 1);
      for (let i = 0; i < count; i++) {
        const center = { x: left + (first + i + k / n) * height, y: bottom };
        paths.push(...clippedUpperArc(center, radius, x0, x1, y0, y1));
      }
    }
  }
  return { paths };
});

function wavefront(id: string, name: string, golden: boolean, supersonic: boolean): DrawingTool {
  const defaults = golden ? GOLDEN_LEVELS : WAVE_LEVELS;
  return geometryTool({ id, name, points: 2, defaultStyle: { levels: cloneLevels(defaults) },
    settings: composeSettings([LINE_FIELDS, LEVEL_FIELDS, FONT_FIELDS,
      ...(golden ? [] : [{ path: 'props.waveCount', label: 'Wave limit', kind: 'number' as const, min: 1, max: 12, step: 1, group: 'behavior' as const }]),
      ...(supersonic ? [{ path: 'props.mach', label: 'Mach number', kind: 'number' as const, min: 1.01, max: 20, step: 0.5, group: 'behavior' as const }] : []),
    ]),
  }, c => {
    if (!ready(c)) return empty();
    const [a, b] = c.pts, center = midpoint(a, b), radius = Math.hypot(b.x - a.x, b.y - a.y) / 2;
    if (!Number.isFinite(radius) || radius < 0.5) return preview(c);
    const direction = { x: (b.x - a.x) / (2 * radius), y: (b.y - a.y) / (2 * radius) };
    const mach = supersonic ? numericProp(c.drawing, 'mach', 2, 1.01, 20) : 1;
    const nose = { x: center.x - mach * radius * direction.x, y: center.y - mach * radius * direction.y };
    const active = activeLevels(c.drawing.style.levels, defaults).filter(l => l.ratio > 0).slice().sort((a, b) => a.ratio - b.ratio);
    if (!golden) active.splice(Math.round(numericProp(c.drawing, 'waveCount', 6, 1, 12)));
    const paths: GeometryPath[] = [], labels: GeometryLabel[] = [];
    let maxRadius = 0;
    for (const l of active) {
      const r = radius * l.ratio, origin = { x: nose.x + mach * r * direction.x, y: nose.y + mach * r * direction.y };
      if (!Number.isFinite(r) || !finitePoint(origin)) continue;
      maxRadius = Math.max(maxRadius, r);
      paths.push(curve(origin, r, r, 0, TAU, l.color));
      labels.push(...label(c, l, { x: origin.x + direction.x * r + 4, y: origin.y + direction.y * r }));
    }
    if (maxRadius === 0) return empty();
    const length = mach * maxRadius + 2 * radius;
    if (supersonic) {
      const sin = 1 / mach, cos = Math.sqrt(1 - sin * sin);
      for (const sign of [-1, 1]) paths.push(segment(nose, {
        x: nose.x + length * (direction.x * cos - sign * direction.y * sin),
        y: nose.y + length * (direction.y * cos + sign * direction.x * sin),
      }));
    } else {
      paths.push(segment({ x: nose.x - direction.y * length, y: nose.y + direction.x * length },
        { x: nose.x + direction.y * length, y: nose.y - direction.x * length }));
    }
    return { paths, labels };
  });
}

export const ADVANCED_GEOMETRY_TOOLS: readonly DrawingTool[] = [
  trendTime,
  radial('fib-circles', 'Fib Circles', 'circle'),
  radial('fib-speed-resistance-arcs', 'Fib Speed Resistance Arcs', 'arc'),
  radial('fib-wedge', 'Fib Wedge', 'wedge'), spiral, gannSquare, dedekind,
  wavefront('sonic', 'Sonic', false, false), wavefront('supersonic', 'Supersonic', false, true),
  wavefront('golden-sonic', 'Golden Sonic', true, false), wavefront('golden-supersonic', 'Golden Supersonic', true, true),
];
