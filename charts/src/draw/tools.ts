/**
 * Built-in drawing tools: the line family, shapes, curves, freehand ink and
 * cycles, plus the catalogue of every built-in in registration order. The
 * other families live beside it (fib-tools.ts, measure-tools.ts,
 * annotation-tools.ts and the advanced, pattern and analysis modules), what
 * they paint with in tool-paint.ts, and the registry in registry.ts.
 *
 * `draw` receives anchors already in device px; `distance` receives them in
 * media px, the same space as the incoming cursor.
 *
 * Text lives in `drawing.text` (a `DrawingText`), never in the style bag: a
 * shape's outline colour and its label colour are two decisions, and a tool
 * that prints only a readout (a fib ladder, a measure chip) still reads its
 * face from there. Ladders read `FibLevel[]` and stroke each level in its own
 * colour, taken from the shared palette in levels.ts.
 *
 * Every tool declares `settings`: the fields a host may show for it. The
 * schema is a contract, not a wish list. A field is declared only when the
 * tool reads it, because a control with nothing behind it is a defect.
 */
import type {
  AnchoredTool, DrawContext, DrawingTool, ScreenPoint, ToolAnchors,
} from './types';
import { lineAlertValue, horizontalAlertValue, channelAlertValue, channelAlertLevels } from './alert-values';
import {
  distToSegment, distToLine, distToHorizontal, distToVertical,
  distToRect, distToEllipse, distToPolyline, rectOf, boundsOf, extendSegment,
} from './geometry';
import {
  type SettingsField, type SettingsSchema,
  LINE_FIELDS, FILL_FIELDS, EXTEND_FIELDS, FONT_FIELDS, SHAPE_TEXT_FIELDS,
  COLOR_FIELD, LINE_WIDTH_FIELD, SHOW_LABELS_FIELD, SPACE_FIELD,
  composeSettings,
} from './schema';
import { catmullRom, pressureWidth } from './freehand';
import { insidePolygon } from './advanced-shared';
import { ADVANCED_LINE_TOOLS } from './advanced-lines';
import { ADVANCED_GEOMETRY_TOOLS } from './advanced-geometry';
import { PATTERN_DRAWING_TOOLS } from './pattern-tools';
import { registerDrawingTool, LINE_SETTINGS } from './registry';
import {
  OPACITY_FIELD, applyStroke, withFill, label, grouped, arrowHead, tintOf, shapeLabel, shapeBounds,
} from './tool-paint';
import { FIB_RETRACEMENT, FIB_EXTENSION, FIB_CHANNEL, FIB_TIME_ZONE, FIB_FAN, GANN_FAN, GANN_BOX } from './fib-tools';
import { MEASURE, LONG_POSITION, SHORT_POSITION, PRICE_RANGE, DATE_RANGE, FORECAST } from './measure-tools';
import {
  TEXT, PRICE_LABEL, CALLOUT, FLAG_MARK, NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE, TABLE,
  ARROW_UP, ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT,
} from './annotation-tools';
import { ANCHORED_VWAP, FIXED_RANGE_VOLUME_PROFILE } from './analysis-tools';

/** `showLabels` on a horizontal line toggles exactly one thing: the price tag. */
const PRICE_TAG_FIELD: SettingsField = { ...SHOW_LABELS_FIELD, label: 'Show price' };

/** The midpoint readout of a two-anchor line: change, percent, bars, angle. */
const STATS_FIELD: SettingsField = { path: 'style.showStats', label: 'Show stats', kind: 'boolean', group: 'behavior' };

/** Let pen pressure swell and thin a freehand stroke. */
const PRESSURE_FIELD: SettingsField = { path: 'style.pressure', label: 'Pen pressure', kind: 'boolean', group: 'line' };

/**
 * The midpoint readout of a two-anchor line, when `showStats` asks for it:
 * signed change and percent, bars between the anchors, and the angle the
 * line makes on screen. Bars come from logical indices so the count matches
 * the gapless axis; the angle is measured in device px because a slope in
 * price-per-second means nothing to the eye, and it is what the eye sees
 * that the readout describes. Off by default, so a line paints exactly as it
 * did before the readout existed.
 */
function lineStats(c: DrawContext & ToolAnchors<2>): void {
  if (c.style.showStats !== true) return;
  const [a, b] = c.pts;
  const [p0, p1] = c.drawing.points;
  const chg = p1.price - p0.price;
  const pct = p0.price !== 0 ? (chg / p0.price) * 100 : 0;
  const up = chg >= 0;
  const sign = up ? '+' : '';
  const i0 = c.rc.dataLayer.timeToIndexFloat(p0.time);
  const i1 = c.rc.dataLayer.timeToIndexFloat(p1.time);
  const bars = Math.abs(Math.round(i1 - i0));
  // Screen y grows downward, so it is negated to read as a rising angle.
  const angle = (Math.atan2(a.y - b.y, b.x - a.x) * 180) / Math.PI;
  const text = `${sign}${c.formatPrice(chg)} (${sign}${pct.toFixed(2)}%)  ${grouped(bars)} bars  ${angle.toFixed(1)} deg`;
  label(c, text, (a.x + b.x) / 2, (a.y + b.y) / 2 - 10 * c.rc.dpr, c.style.color, {
    tint: tintOf(c, up), center: true,
  });
}

/**
 * Freehand ink through the spline. A constant-width stroke is one path; with
 * `pressure` on it becomes a filled ribbon whose edges run the spline offset
 * by half the pressure width at each sample, which is the only way a single
 * fill can be fat where the pen pressed and thin where it lifted. `alpha`
 * is the highlighter's translucency; the brush passes 1.
 */
function ink(c: DrawContext, width: number, alpha: number): void {
  const { ctx, style } = c;
  const pts = c.pts;
  ctx.save();
  ctx.globalAlpha = alpha;
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  if (style.pressure !== true) {
    ctx.strokeStyle = style.color;
    ctx.lineWidth = width;
    ctx.beginPath();
    catmullRom(ctx, pts);
    ctx.stroke();
    ctx.restore();
    return;
  }
  const n = pts.length;
  const left: ScreenPoint[] = [];
  const right: ScreenPoint[] = [];
  for (let i = 0; i < n; i++) {
    // The tangent at a sample runs from its previous neighbour to its next
    // one; the ends use the one segment they have. Every index is in 0..n-1.
    const prev = pts[i === 0 ? 0 : i - 1]!;
    const next = pts[i === n - 1 ? n - 1 : i + 1]!;
    const len = Math.hypot(next.x - prev.x, next.y - prev.y) || 1;
    const nx = -(next.y - prev.y) / len;
    const ny = (next.x - prev.x) / len;
    const pressure = c.drawing.points[i]?.pressure;
    const half = pressureWidth(width, pressure ?? 0.5) / 2;
    left.push({ x: pts[i]!.x + nx * half, y: pts[i]!.y + ny * half });
    right.push({ x: pts[i]!.x - nx * half, y: pts[i]!.y - ny * half });
  }
  // One loop: out along the left edge, back along the right, so the spline
  // rounds the ends on its own and the fill is a single closed region.
  right.reverse();
  ctx.fillStyle = style.color;
  ctx.beginPath();
  catmullRom(ctx, left.concat(right));
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

// ── line family ───────────────────────────────────────────────────────────

/** Trend line, ray, and extended line differ only in which ends extend. */
function lineTool(id: string, name: string, left: boolean, right: boolean): DrawingTool {
  return {
    id, name, points: 2, angleLock: true,
    alertValue: lineAlertValue(left, right),
    defaultStyle: { extendLeft: left, extendRight: right },
    settings: composeSettings([LINE_FIELDS, EXTEND_FIELDS, STATS_FIELD]),
    draw: (c) => {
      const [a, b] = extendSegment(
        c.pts[0], c.pts[1], c.rc.plotWidth * c.rc.dpr,
        c.style.extendLeft ?? left, c.style.extendRight ?? right,
      );
      applyStroke(c);
      c.ctx.beginPath();
      c.ctx.moveTo(a.x, a.y);
      c.ctx.lineTo(b.x, b.y);
      c.ctx.stroke();
      c.ctx.setLineDash([]);
      lineStats(c);
    },
    distance: (x, y, h) => {
      const el = h.drawing.style.extendLeft ?? left;
      const er = h.drawing.style.extendRight ?? right;
      if (el && er) return distToLine(x, y, h.pts[0], h.pts[1]);
      const [a, b] = extendSegment(h.pts[0], h.pts[1], h.rc.plotWidth, el, er);
      return distToSegment(x, y, a, b);
    },
  } satisfies AnchoredTool<2>;
}

export const TREND_LINE: DrawingTool = { ...lineTool('trend-line', 'Trend Line', false, false), shortcut: 'Alt+T' };
export const RAY = lineTool('ray', 'Ray', false, true);
export const EXTENDED_LINE = lineTool('extended-line', 'Extended Line', true, true);

export const ARROW: DrawingTool = {
  id: 'arrow', name: 'Arrow', points: 2, angleLock: true,
  settings: composeSettings([LINE_FIELDS, STATS_FIELD]),
  draw: (c) => {
    const [a, b] = c.pts;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    c.ctx.lineTo(b.x, b.y);
    c.ctx.stroke();
    // Head at the far anchor, sized off the line width so it scales with style.
    arrowHead(c, a, b);
    c.ctx.setLineDash([]);
    lineStats(c);
  },
  distance: (x, y, h) => distToSegment(x, y, h.pts[0], h.pts[1]),
} satisfies AnchoredTool<2>;

export const HORIZONTAL_LINE: DrawingTool = {
  id: 'horizontal-line', name: 'Horizontal Line', points: 1, shortcut: 'Alt+H',
  alertValue: horizontalAlertValue(),
  defaultStyle: { showLabels: true },
  settings: composeSettings([LINE_FIELDS, PRICE_TAG_FIELD, FONT_FIELDS]),
  draw: (c) => {
    const y = Math.round(c.pts[0].y) + 0.5;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(0, y);
    c.ctx.lineTo(c.rc.plotWidth * c.rc.dpr, y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    if (c.style.showLabels !== false) {
      label(c, c.formatPrice(c.drawing.points[0].price), 4 * c.rc.dpr, y - 8 * c.rc.dpr);
    }
  },
  distance: (_x, y, h) => distToHorizontal(y, h.pts[0].y),
} satisfies AnchoredTool<1>;

export const HORIZONTAL_RAY: DrawingTool = {
  id: 'horizontal-ray', name: 'Horizontal Ray', points: 1, shortcut: 'Alt+J',
  alertValue: horizontalAlertValue(true),
  defaultStyle: { showLabels: true },
  settings: composeSettings([LINE_FIELDS, PRICE_TAG_FIELD, FONT_FIELDS]),
  draw: (c) => {
    const y = Math.round(c.pts[0].y) + 0.5;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(c.pts[0].x, y);
    c.ctx.lineTo(c.rc.plotWidth * c.rc.dpr, y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    if (c.style.showLabels !== false) {
      label(c, c.formatPrice(c.drawing.points[0].price), c.pts[0].x + 4 * c.rc.dpr, y - 8 * c.rc.dpr);
    }
  },
  distance: (x, y, h) => (x < h.pts[0].x ? null : distToHorizontal(y, h.pts[0].y)),
} satisfies AnchoredTool<1>;

export const VERTICAL_LINE: DrawingTool = {
  id: 'vertical-line', name: 'Vertical Line', points: 1, shortcut: 'Alt+V',
  settings: LINE_SETTINGS,
  draw: (c) => {
    const x = Math.round(c.pts[0].x) + 0.5;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(x, 0);
    c.ctx.lineTo(x, c.rc.plotHeight * c.rc.dpr);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, _y, h) => distToVertical(x, h.pts[0].x),
} satisfies AnchoredTool<1>;

export const CROSS_LINE: DrawingTool = {
  id: 'cross-line', name: 'Cross Line', points: 1, shortcut: 'Alt+C',
  settings: LINE_SETTINGS,
  draw: (c) => {
    const x = Math.round(c.pts[0].x) + 0.5;
    const y = Math.round(c.pts[0].y) + 0.5;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(x, 0); c.ctx.lineTo(x, c.rc.plotHeight * c.rc.dpr);
    c.ctx.moveTo(0, y); c.ctx.lineTo(c.rc.plotWidth * c.rc.dpr, y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => Math.min(distToVertical(x, h.pts[0].x), distToHorizontal(y, h.pts[0].y)),
} satisfies AnchoredTool<1>;

// ── shapes ────────────────────────────────────────────────────────────────

/** What every labelled shape declares: outline, fill, and the attached label. */
const SHAPE_SETTINGS: SettingsSchema = composeSettings([LINE_FIELDS, FILL_FIELDS, SHAPE_TEXT_FIELDS]);

/**
 * A labelled shape that can also be pinned to the screen. Only the box and the
 * ellipse: their outline, fill and label come from the anchors alone, where a
 * channel or a triangle is drawn to price action and means nothing once the
 * bars pan away from it.
 */
const PINNABLE_SHAPE_SETTINGS: SettingsSchema = composeSettings([SHAPE_SETTINGS.fields, SPACE_FIELD]);

export const RECTANGLE: DrawingTool = {
  id: 'rectangle', name: 'Rectangle', points: 2, viewport: true,
  defaultStyle: { fill: true },
  settings: PINNABLE_SHAPE_SETTINGS,
  draw: (c) => {
    const r = rectOf(c.pts[0], c.pts[1]);
    withFill(c, () => c.ctx.fillRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0));
    applyStroke(c);
    c.ctx.strokeRect(r.x0, r.y0, r.x1 - r.x0, r.y1 - r.y0);
    c.ctx.setLineDash([]);
    shapeLabel(c, r);
  },
  distance: (x, y, h) => distToRect(x, y, h.pts[0], h.pts[1], h.drawing.style.fill === true),
  bounds: shapeBounds('left', 'top'),
} satisfies AnchoredTool<2, true>;

export const ELLIPSE: DrawingTool = {
  id: 'ellipse', name: 'Ellipse', points: 2, viewport: true,
  defaultStyle: { fill: true },
  settings: PINNABLE_SHAPE_SETTINGS,
  draw: (c) => {
    const r = rectOf(c.pts[0], c.pts[1]);
    const cx = (r.x0 + r.x1) / 2;
    const cy = (r.y0 + r.y1) / 2;
    const rx = Math.max(1, (r.x1 - r.x0) / 2);
    const ry = Math.max(1, (r.y1 - r.y0) / 2);
    const path = (): void => {
      c.ctx.beginPath();
      c.ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
    };
    withFill(c, () => { path(); c.ctx.fill(); });
    applyStroke(c);
    path();
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    // A corner of an ellipse's box is outside the ellipse, so the label
    // defaults to the middle, where there is shape behind it.
    shapeLabel(c, r, 'center', 'middle');
  },
  distance: (x, y, h) => distToEllipse(x, y, h.pts[0], h.pts[1], h.drawing.style.fill === true),
  bounds: shapeBounds('center', 'middle'),
} satisfies AnchoredTool<2, true>;

export const PARALLEL_CHANNEL: DrawingTool = {
  id: 'parallel-channel', name: 'Parallel Channel', points: 3,
  alertValue: channelAlertValue('parallel'), alertLevels: channelAlertLevels,
  defaultStyle: { fill: true },
  settings: SHAPE_SETTINGS,
  draw: (c) => {
    const [a, b, t] = c.pts;
    // The third anchor sets the channel width as a vertical offset.
    const dy = t.y - (a.y + (b.y - a.y) * 0.5);
    const a2 = { x: a.x, y: a.y + dy };
    const b2 = { x: b.x, y: b.y + dy };
    withFill(c, () => {
      c.ctx.beginPath();
      c.ctx.moveTo(a.x, a.y); c.ctx.lineTo(b.x, b.y);
      c.ctx.lineTo(b2.x, b2.y); c.ctx.lineTo(a2.x, a2.y);
      c.ctx.closePath();
      c.ctx.fill();
    });
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y); c.ctx.lineTo(b.x, b.y);
    c.ctx.moveTo(a2.x, a2.y); c.ctx.lineTo(b2.x, b2.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    shapeLabel(c, boundsOf([a, b, a2, b2]));
  },
  distance: (x, y, h) => {
    const [a, b, t] = h.pts;
    const dy = t.y - (a.y + (b.y - a.y) * 0.5);
    const d1 = distToSegment(x, y, a, b);
    const d2 = distToSegment(x, y, { x: a.x, y: a.y + dy }, { x: b.x, y: b.y + dy });
    return Math.min(d1, d2);
  },
} satisfies AnchoredTool<3>;

/**
 * Path: click each vertex, double-click to finish, arrowhead on the last leg.
 * The arrow is what separates it from `polyline`: a path points somewhere.
 */
export const PATH: DrawingTool = {
  id: 'path', name: 'Path', points: 0,
  settings: LINE_SETTINGS,
  draw: (c) => {
    if (c.pts.length < 2) return;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(c.pts[0].x, c.pts[0].y);
    for (let i = 1; i < c.pts.length; i++) c.ctx.lineTo(c.pts[i]!.x, c.pts[i]!.y); // i is in range
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    arrowHead(c, c.pts[c.pts.length - 2]!, c.pts[c.pts.length - 1]!); // two or more, by the check above
  },
  distance: (x, y, h) => (h.pts.length < 2 ? null : distToPolyline(x, y, h.pts)),
} satisfies AnchoredTool<0>;

/**
 * Brush: freehand ink. Press, drag, release. The anchors are the thinned
 * samples of the gesture and the spline between them is what is stroked, so
 * the ink stays a curve after the thinning that keeps a stroke small.
 */
export const BRUSH: DrawingTool = {
  id: 'brush', name: 'Brush', points: 0, freehand: true,
  defaultStyle: { lineWidth: 2 },
  settings: composeSettings([LINE_FIELDS, PRESSURE_FIELD]),
  draw: (c) => {
    if (c.pts.length < 2) return;
    // The dash comes from the style; the width and cap from the ink helper.
    applyStroke(c);
    ink(c, Math.max(1, Math.round(c.style.lineWidth * c.rc.dpr)), 1);
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => (h.pts.length < 2 ? null : distToPolyline(x, y, h.pts)),
} satisfies AnchoredTool<0>;

/**
 * Rotated rectangle: anchors 0 and 1 lay out one edge (and so the rotation),
 * and anchor 2 sets the depth perpendicular to it. An axis-aligned `rectangle`
 * cannot follow a trend channel; this can.
 */
export const ROTATED_RECTANGLE: DrawingTool = {
  id: 'rotated-rectangle', name: 'Rotated Rectangle', points: 3,
  defaultStyle: { fill: true, fillOpacity: 0.12 },
  settings: SHAPE_SETTINGS,
  draw: (c) => {
    if (c.pts.length < 3) return;
    const corners = rotatedCorners(c.pts[0], c.pts[1], c.pts[2]);
    c.ctx.beginPath();
    c.ctx.moveTo(corners[0].x, corners[0].y);
    for (let i = 1; i < 4; i++) c.ctx.lineTo(corners[i]!.x, corners[i]!.y); // four corners
    c.ctx.closePath();
    withFill(c, () => c.ctx.fill());
    applyStroke(c);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    shapeLabel(c, boundsOf(corners), 'center', 'middle');
  },
  distance: (x, y, h) => {
    if (h.pts.length < 3) return null;
    const corners = rotatedCorners(h.pts[0], h.pts[1], h.pts[2]);
    if (h.drawing.style.fill === true && insidePolygon(x, y, corners)) return 0;
    let best = Infinity;
    for (let i = 0; i < 4; i++) {
      best = Math.min(best, distToSegment(x, y, corners[i]!, corners[(i + 1) % 4]!)); // four corners
    }
    return best;
  },
} satisfies AnchoredTool<3>;

/**
 * The four corners of a rotated rectangle: `a` to `b` is one edge, and `c` is
 * projected onto the perpendicular to give the depth.
 */
function rotatedCorners(a: ScreenPoint, b: ScreenPoint, c: ScreenPoint): [ScreenPoint, ScreenPoint, ScreenPoint, ScreenPoint] {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const len = Math.hypot(dx, dy) || 1;
  // Unit normal to the a-b edge; the signed projection of `c` onto it is depth.
  const nx = -dy / len;
  const ny = dx / len;
  const depth = (c.x - b.x) * nx + (c.y - b.y) * ny;
  return [
    a, b,
    { x: b.x + nx * depth, y: b.y + ny * depth },
    { x: a.x + nx * depth, y: a.y + ny * depth },
  ];
}

/**
 * Double curve: an S through three anchors. `curve` bends one way off a single
 * control; this mirrors that control about the midpoint so the second half bends
 * back, which is the shape a rounded top-then-bottom actually needs.
 */
export const DOUBLE_CURVE: DrawingTool = {
  id: 'double-curve', name: 'Double Curve', points: 3,
  settings: LINE_SETTINGS,
  draw: (c) => {
    if (c.pts.length < 3) return;
    const [a, mid, b] = c.pts;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    // Second control is `mid` reflected through the chord's midpoint.
    c.ctx.bezierCurveTo(mid.x, mid.y, a.x + b.x - mid.x, a.y + b.y - mid.y, b.x, b.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    if (h.pts.length < 3) return null;
    const [a, mid, b] = h.pts;
    const c2 = { x: a.x + b.x - mid.x, y: a.y + b.y - mid.y };
    return distToPolyline(x, y, sampleCubic(a, mid, c2, b, 24));
  },
} satisfies AnchoredTool<3>;

/** Flatten a cubic bezier to `steps` segments, for hit-testing curves. */
function sampleCubic(a: ScreenPoint, c1: ScreenPoint, c2: ScreenPoint, b: ScreenPoint, steps: number): ScreenPoint[] {
  const out: ScreenPoint[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    const u = 1 - t;
    const w0 = u * u * u;
    const w1 = 3 * u * u * t;
    const w2 = 3 * u * t * t;
    const w3 = t * t * t;
    out.push({
      x: w0 * a.x + w1 * c1.x + w2 * c2.x + w3 * b.x,
      y: w0 * a.y + w1 * c1.y + w2 * c2.y + w3 * b.y,
    });
  }
  return out;
}

// ── cycles ────────────────────────────────────────────────────────────────

/** How many repeats a cycle tool draws past its two anchors. */
const CYCLE_REPEATS = 12;

/**
 * Cyclic lines: vertical lines repeating at the interval the two anchors set,
 * for reading a rhythm forward off a measured swing.
 */
export const CYCLIC_LINES: DrawingTool = {
  id: 'cyclic-lines', name: 'Cyclic Lines', points: 2,
  defaultStyle: { lineStyle: 'dashed' },
  settings: LINE_SETTINGS,
  draw: (c) => {
    const [a, b] = c.pts;
    const step = b.x - a.x;
    if (!Number.isFinite(step) || Math.abs(step) < 0.5) return;
    const h = c.rc.plotHeight * c.rc.dpr;
    const w = c.rc.plotWidth * c.rc.dpr;
    applyStroke(c);
    c.ctx.beginPath();
    for (let i = 0; i <= CYCLE_REPEATS; i++) {
      const x = Math.round(a.x + step * i) + 0.5;
      if (x < 0 || x > w) continue;   // off-plot repeats cost nothing to skip
      c.ctx.moveTo(x, 0);
      c.ctx.lineTo(x, h);
    }
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    void y;
    const step = h.pts[1].x - h.pts[0].x;
    if (!Number.isFinite(step) || Math.abs(step) < 0.5) return null;
    // Distance to the nearest repeat, clamped to the ones actually drawn.
    const k = Math.round((x - h.pts[0].x) / step);
    if (k < 0 || k > CYCLE_REPEATS) return null;
    return Math.abs(x - (h.pts[0].x + step * k));
  },
} satisfies AnchoredTool<2>;

/**
 * Time cycles: semicircles of the anchors' width repeating along the axis, the
 * classic cycle-projection overlay.
 */
export const TIME_CYCLES: DrawingTool = {
  id: 'time-cycles', name: 'Time Cycles', points: 2,
  settings: LINE_SETTINGS,
  draw: (c) => {
    const [a, b] = c.pts;
    const step = b.x - a.x;
    if (!Number.isFinite(step) || Math.abs(step) < 1) return;
    const r = Math.abs(step) / 2;
    applyStroke(c);
    c.ctx.beginPath();
    for (let i = 0; i < CYCLE_REPEATS; i++) {
      const cx = a.x + step * i + step / 2;
      if (cx + r < 0 || cx - r > c.rc.plotWidth * c.rc.dpr) continue;
      c.ctx.moveTo(cx + r, a.y);
      c.ctx.arc(cx, a.y, r, 0, Math.PI, true);   // upper half only
    }
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const [a, b] = h.pts;
    const step = b.x - a.x;
    if (!Number.isFinite(step) || Math.abs(step) < 1) return null;
    const r = Math.abs(step) / 2;
    let best = Infinity;
    for (let i = 0; i < CYCLE_REPEATS; i++) {
      const cx = a.x + step * i + step / 2;
      // Distance to the rim, and only the drawn (upper) half counts.
      if (y > a.y + 2) continue;
      best = Math.min(best, Math.abs(Math.hypot(x - cx, y - a.y) - r));
    }
    return Number.isFinite(best) ? best : null;
  },
} satisfies AnchoredTool<2>;

/**
 * Sine line: a full wave between the anchors. The horizontal span is one
 * period, the vertical offset its amplitude.
 */
export const SINE_LINE: DrawingTool = {
  id: 'sine-line', name: 'Sine Line', points: 2,
  settings: LINE_SETTINGS,
  draw: (c) => {
    const pts = sinePoints(c.pts[0], c.pts[1]);
    if (pts === null) return;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(pts[0]!.x, pts[0]!.y); // a period is 65 samples
    for (let i = 1; i < pts.length; i++) c.ctx.lineTo(pts[i]!.x, pts[i]!.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const pts = sinePoints(h.pts[0], h.pts[1]);
    return pts === null ? null : distToPolyline(x, y, pts);
  },
} satisfies AnchoredTool<2>;

/** One period of a sine from `a` to `a.x + span`, amplitude `b.y - a.y`. */
function sinePoints(a: ScreenPoint, b: ScreenPoint): ScreenPoint[] | null {
  const span = b.x - a.x;
  const amp = b.y - a.y;
  if (!Number.isFinite(span) || Math.abs(span) < 1) return null;
  const steps = 64;
  const out: ScreenPoint[] = [];
  for (let i = 0; i <= steps; i++) {
    const t = i / steps;
    out.push({ x: a.x + span * t, y: a.y + amp * Math.sin(t * Math.PI * 2) });
  }
  return out;
}

// ── shapes ────────────────────────────────────────────────────────────────

/**
 * Circle from centre + a radius handle. The radius is measured in *pixels*, so
 * it stays a circle on screen instead of the ellipse the two axes' differing
 * scales would otherwise produce.
 */
export const CIRCLE: DrawingTool = {
  id: 'circle', name: 'Circle', points: 2,
  defaultStyle: { fill: true },
  settings: SHAPE_SETTINGS,
  draw: (c) => {
    const [a, b] = c.pts;
    const r = Math.hypot(b.x - a.x, b.y - a.y);
    c.ctx.beginPath();
    c.ctx.arc(a.x, a.y, r, 0, Math.PI * 2);
    withFill(c, () => c.ctx.fill());
    applyStroke(c);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    shapeLabel(c, { x0: a.x - r, y0: a.y - r, x1: a.x + r, y1: a.y + r }, 'center', 'middle');
  },
  distance: (x, y, h) => {
    const [a, b] = h.pts;
    const r = Math.hypot(b.x - a.x, b.y - a.y);
    const d = Math.hypot(x - a.x, y - a.y);
    if (h.drawing.style.fill === true && d <= r) return 0;
    return Math.abs(d - r);
  },
} satisfies AnchoredTool<2>;

export const TRIANGLE: DrawingTool = {
  id: 'triangle', name: 'Triangle', points: 3,
  defaultStyle: { fill: true },
  settings: SHAPE_SETTINGS,
  draw: (c) => {
    c.ctx.beginPath();
    c.ctx.moveTo(c.pts[0].x, c.pts[0].y);
    c.ctx.lineTo(c.pts[1].x, c.pts[1].y);
    c.ctx.lineTo(c.pts[2].x, c.pts[2].y);
    c.ctx.closePath();
    withFill(c, () => c.ctx.fill());
    applyStroke(c);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
    shapeLabel(c, boundsOf(c.pts.slice(0, 3)), 'center', 'middle');
  },
  distance: (x, y, h) => distToPolyline(x, y, [...h.pts, h.pts[0]]),
} satisfies AnchoredTool<3>;

/** Free-form polyline: click each vertex, double-click to finish. */
export const POLYLINE: DrawingTool = {
  id: 'polyline', name: 'Polyline', points: 0,
  defaultStyle: { fill: false },
  settings: composeSettings([LINE_FIELDS, FILL_FIELDS]),
  draw: (c) => {
    if (c.pts.length < 2) return;
    c.ctx.beginPath();
    c.ctx.moveTo(c.pts[0].x, c.pts[0].y);
    for (let i = 1; i < c.pts.length; i++) c.ctx.lineTo(c.pts[i]!.x, c.pts[i]!.y); // i is in range
    if (c.style.fill === true) { c.ctx.closePath(); withFill(c, () => c.ctx.fill()); }
    applyStroke(c);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => distToPolyline(x, y, h.pts),
} satisfies AnchoredTool<0>;

/** Sample a quadratic whose control is derived so the curve passes through `m`. */
function quadPoints(a: ScreenPoint, m: ScreenPoint, b: ScreenPoint): ScreenPoint[] {
  const cx = 2 * m.x - (a.x + b.x) / 2;
  const cy = 2 * m.y - (a.y + b.y) / 2;
  const out: ScreenPoint[] = [];
  for (let i = 0; i <= 16; i++) {
    const t = i / 16;
    const u = 1 - t;
    out.push({ x: u * u * a.x + 2 * u * t * cx + t * t * b.x, y: u * u * a.y + 2 * u * t * cy + t * t * b.y });
  }
  return out;
}

/** Arc through three anchors: the middle one is on the curve, not a handle. */
export const ARC: DrawingTool = {
  id: 'arc', name: 'Arc', points: 3,
  settings: LINE_SETTINGS,
  draw: (c) => {
    const [a, m, b] = c.pts;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    // Lift the control point so the curve passes *through* the middle anchor
    // rather than merely leaning toward it.
    c.ctx.quadraticCurveTo(2 * m.x - (a.x + b.x) / 2, 2 * m.y - (a.y + b.y) / 2, b.x, b.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => distToPolyline(x, y, quadPoints(h.pts[0], h.pts[1], h.pts[2])),
} satisfies AnchoredTool<3>;

/** Quadratic curve: the middle anchor is a control handle, off the curve. */
export const CURVE: DrawingTool = {
  id: 'curve', name: 'Curve', points: 3,
  settings: LINE_SETTINGS,
  draw: (c) => {
    const [a, m, b] = c.pts;
    applyStroke(c);
    c.ctx.beginPath();
    c.ctx.moveTo(a.x, a.y);
    c.ctx.quadraticCurveTo(m.x, m.y, b.x, b.y);
    c.ctx.stroke();
    c.ctx.setLineDash([]);
  },
  distance: (x, y, h) => {
    const [a, m, b] = h.pts;
    const pts: ScreenPoint[] = [];
    for (let i = 0; i <= 16; i++) {
      const t = i / 16;
      const u = 1 - t;
      pts.push({ x: u * u * a.x + 2 * u * t * m.x + t * t * b.x, y: u * u * a.y + 2 * u * t * m.y + t * t * b.y });
    }
    return distToPolyline(x, y, pts);
  },
} satisfies AnchoredTool<3>;

// ── brushes ───────────────────────────────────────────────────────────────

/** Highlighter: the brush with a fat, translucent stroke. */
export const HIGHLIGHTER: DrawingTool = {
  id: 'highlighter', name: 'Highlighter', points: 0, freehand: true,
  defaultStyle: { lineWidth: 12, fillOpacity: 0.28 },
  settings: composeSettings([COLOR_FIELD, LINE_WIDTH_FIELD, OPACITY_FIELD, PRESSURE_FIELD]),
  draw: (c) => {
    if (c.pts.length < 2) return;
    c.ctx.setLineDash([]);
    ink(c, Math.max(2, (c.style.lineWidth || 12) * c.rc.dpr), c.style.fillOpacity ?? 0.28);
  },
  distance: (x, y, h) => {
    const d = distToPolyline(x, y, h.pts);
    return d <= Math.max(6, (h.drawing.style.lineWidth ?? 12) / 2) ? 0 : d;
  },
} satisfies AnchoredTool<0>;

export const BUILTIN_DRAWING_TOOLS: readonly DrawingTool[] = [
  TREND_LINE, RAY, EXTENDED_LINE, ARROW,
  HORIZONTAL_LINE, HORIZONTAL_RAY, VERTICAL_LINE, CROSS_LINE,
  RECTANGLE, ELLIPSE, PARALLEL_CHANNEL,
  FIB_RETRACEMENT, FIB_EXTENSION,
  LONG_POSITION, SHORT_POSITION, FORECAST,
  MEASURE, PRICE_RANGE, DATE_RANGE,
  CIRCLE, TRIANGLE, POLYLINE, ARC, CURVE,
  ROTATED_RECTANGLE, DOUBLE_CURVE,
  ARROW_UP, ARROW_DOWN, HIGHLIGHTER, BRUSH,
  FIB_CHANNEL, FIB_TIME_ZONE, FIB_FAN, GANN_FAN, GANN_BOX,
  CYCLIC_LINES, TIME_CYCLES, SINE_LINE,
  TEXT, PATH, PRICE_LABEL, CALLOUT, FLAG_MARK,
  NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE, TABLE,
  ARROW_LEFT, ARROW_RIGHT,
  ...ADVANCED_LINE_TOOLS,
  ...ADVANCED_GEOMETRY_TOOLS,
  ...PATTERN_DRAWING_TOOLS,
  ANCHORED_VWAP, FIXED_RANGE_VOLUME_PROFILE,
];

let _registered = false;

/** Register every built-in tool. Idempotent; called on tier import. */
export function registerBuiltinDrawingTools(): void {
  if (_registered) return;
  _registered = true;
  for (const t of BUILTIN_DRAWING_TOOLS) registerDrawingTool(t);
}
