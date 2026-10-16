/**
 * The drawing layer's hit prefilter: for each drawing, a box outside which its
 * tool can never report a hit, so a pointer move asks only the drawings near
 * the pointer rather than every drawing on the pane.
 *
 * A layer holds every drawing of its pane in one primitive, so the pane's own
 * prefilter (`IPrimitive.hitBounds`) sees one box the size of the plot and
 * asks the layer on every move. Five hundred drawings then cost five hundred
 * projections and five hundred distance calls per move.
 *
 * A box is worked out from the geometry the tool's `distance` answers from:
 * its anchors in media px, the drawing's style, and the render context. It
 * covers every point where that distance is at most the grab radius, which is
 * why the radius is part of it: an ellipse's distance is scaled by its short
 * axis, so the region it grabs grows faster than the radius along the long
 * one. Only tools whose geometry is written out here get a box. Any other
 * tool, a host's own included, and a built-in id a host has registered again
 * with its own implementation, are asked on every move as before, since the
 * box table knows the built-in objects and not their ids.
 *
 * Boxes are kept, by the drawing's place in the layer's paint order, while a
 * key reads the same: what projects an anchor (the time scale, the bars'
 * times, the price scale), the plot size, the grab radii, the tool registered
 * under each id the layer uses, and the loaded fonts, which decide the box of
 * a text. A new drawing list lets every box go, since the controller edits
 * drawings in place and hands the list over again.
 */
import { PRICE_SCALE_MODES, type PrimitiveRenderContext } from 'openalgo-charts';
import type { AtLeast, Drawing, DrawingTool, ScreenPoint } from './types';
import { extendSegment } from './geometry';
import { activeLevels, DEFAULT_FIB, DEFAULT_FIB_FAN, DEFAULT_FIB_TIME_ZONE, DEFAULT_GANN_FAN } from './levels';
import { getDrawingTool, hasDrawingTool } from './registry';
import {
  TREND_LINE, RAY, EXTENDED_LINE, ARROW, HORIZONTAL_LINE, HORIZONTAL_RAY, VERTICAL_LINE,
  RECTANGLE, ELLIPSE, PARALLEL_CHANNEL,
  PATH, BRUSH, POLYLINE, TRIANGLE, CURVE, ARC, DOUBLE_CURVE, ROTATED_RECTANGLE, CIRCLE,
  HIGHLIGHTER, CYCLIC_LINES, TIME_CYCLES, SINE_LINE,
} from './tools';
import { FIB_RETRACEMENT, FIB_EXTENSION, GANN_BOX, FIB_TIME_ZONE, FIB_FAN, GANN_FAN, FIB_CHANNEL } from './fib-tools';
import { MEASURE, LONG_POSITION, SHORT_POSITION, PRICE_RANGE, DATE_RANGE, FORECAST } from './measure-tools';
import {
  annotationBox, TEXT, TABLE, PRICE_LABEL, CALLOUT, FLAG_MARK,
  ARROW_UP, ARROW_DOWN, ARROW_LEFT, ARROW_RIGHT, NOTE, BALLOON, COMMENT, SIGNPOST, PRICE_NOTE,
} from './annotation-tools';
import { PATTERN_DRAWING_TOOLS } from './pattern-tools';

/** A hit box in media px relative to the plot, edges inclusive. */
export interface HitBox { x0: number; y0: number; x1: number; y1: number }

/** No point is inside: nothing of the drawing can be hit. */
export const NOWHERE: HitBox = { x0: Infinity, y0: Infinity, x1: -Infinity, y1: -Infinity };
/** Every point is inside: the drawing is asked on every move. */
export const EVERYWHERE: HitBox = { x0: -Infinity, y0: -Infinity, x1: Infinity, y1: Infinity };

/**
 * Whether (x, y) can be in `box`. Written as "not outside", so a box with a
 * NaN edge, which answers no comparison, is asked rather than skipped: an
 * anchor that does not map is the tool's to judge, as it always was.
 */
export function inHitBox(box: HitBox, x: number, y: number): boolean {
  return !(x < box.x0 || x > box.x1 || y < box.y0 || y > box.y1);
}

/** The extent of `pts` grown by `by`. `Math.min` and `max` carry a NaN into the edge. */
export function spanOf(pts: readonly ScreenPoint[], by: number): HitBox {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of pts) {
    x0 = Math.min(x0, p.x); y0 = Math.min(y0, p.y);
    x1 = Math.max(x1, p.x); y1 = Math.max(y1, p.y);
  }
  return { x0: x0 - by, y0: y0 - by, x1: x1 + by, y1: y1 + by };
}

const join = (a: HitBox, b: HitBox): HitBox => ({
  x0: Math.min(a.x0, b.x0), y0: Math.min(a.y0, b.y0), x1: Math.max(a.x1, b.x1), y1: Math.max(a.y1, b.y1),
});

/**
 * A tool's box from its anchors in media px. `toolHitBox` is called only after
 * the layer's count check, so an entry reads the `N` anchors its tool declares
 * without a check of its own (`ToolAnchors` in types.ts states the same for
 * the tools). A method's type, so one table holds entries that read different
 * counts.
 */
type BoxOf<N extends number = 1> = { of(pts: Pts<N>, d: Drawing, rc: PrimitiveRenderContext, grab: number): HitBox }['of'];
type Pts<N extends number> = AtLeast<ScreenPoint, N>;

/** Segments, polylines, closed shapes and curves inside the hull of their anchors. */
const around: BoxOf = (pts, _d, _rc, grab) => spanOf(pts, grab);

/** Trend line, ray and extended line: the segment as extended to the plot's edges. */
const line = (left: boolean, right: boolean): BoxOf<2> => (pts, d, rc, grab) => {
  const el = d.style.extendLeft ?? left;
  const er = d.style.extendRight ?? right;
  const [a, b] = pts;
  if (el && er) {
    // The distance is to the infinite line: bounded only when it is level
    // or upright, and a point when the anchors coincide.
    if (a.x === b.x && a.y === b.y) return spanOf([a], grab);
    if (a.y === b.y) return { x0: -Infinity, y0: a.y - grab, x1: Infinity, y1: a.y + grab };
    if (a.x === b.x) return { x0: a.x - grab, y0: -Infinity, x1: a.x + grab, y1: Infinity };
    return EVERYWHERE;
  }
  return spanOf(extendSegment(a, b, rc.plotWidth, el, er), grab);
};

/** Retracement and extension: the ladder's rungs, over the anchors' span or out to an extended edge. */
const fib = (anchors: 2 | 3): BoxOf<2> => (pts, d, rc, grab) => {
  // A fib is drawn in data space only, so its points are its anchors, `anchors` of them.
  const p = d.points;
  const from = anchors === 2 ? p[0]!.price : p[2]!.price;
  const span = p[1]!.price - p[0]!.price;
  const xa = pts[0].x, xb = pts[anchors - 1]!.x;
  const x0 = d.style.extendLeft === true ? 0 : Math.min(xa, xb);
  const x1 = d.style.extendRight === true ? rc.plotWidth : Math.max(xa, xb);
  let y0 = Infinity, y1 = -Infinity;
  for (const lv of activeLevels(d.style.levels, DEFAULT_FIB)) {
    const y = rc.priceScale.priceToY(from + span * lv.ratio);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return { x0: x0 - 4, y0: y0 - grab, x1: x1 + 4, y1: y1 + grab };
};

/**
 * A position box: its anchors' span in time and its three levels in price. A
 * two-anchor position derives its stop; rather than restate that ratio here,
 * such a box is left open in price.
 */
const position: BoxOf = (pts, d, rc, grab) => {
  const p = d.points;
  if (pts.length < 2 || p.length < 2) return NOWHERE;
  const xs = spanOf(pts, 4);
  if (p.length < 3) return { x0: xs.x0, y0: -Infinity, x1: xs.x1, y1: Infinity };
  const ys = spanOf(p.slice(0, 3).map((q) => ({ x: 0, y: rc.priceScale.priceToY(q.price) })), grab);
  return { x0: xs.x0, y0: ys.y0, x1: xs.x1, y1: ys.y1 };
};

/**
 * The tools grabbed anywhere inside a measured box declare that box as their
 * `bounds`, so the box is read from the tool itself and follows the text it
 * measures. `pad` is the slack their `distance` allows around it.
 */
const bounded = (tool: DrawingTool, pad: number): BoxOf => (pts, d) => {
  const b = tool.bounds?.(pts, d);
  return b === undefined ? EVERYWHERE : { x0: b.x0 - pad, y0: b.y0 - pad, x1: b.x1 + pad, y1: b.y1 + pad };
};

/** A one-anchor mark grabbed inside a fixed box around its anchor, in media px. */
const mark = (dx0: number, dy0: number, dx1: number, dy1: number): BoxOf => (pts) => {
  const p = pts[0];
  return { x0: p.x + dx0, y0: p.y + dy0, x1: p.x + dx1, y1: p.y + dy1 };
};

/**
 * The annotations grabbed on a plate or a bubble measured from their text
 * (the plate notes, the price label, the callout's bubble): the box comes from
 * annotation-tools.ts, off the plate their own hit test measures.
 */
const annotated = (tool: DrawingTool): BoxOf => (pts, d, rc) => annotationBox(tool, pts, d, rc) ?? EVERYWHERE;

const BOXES = new Map<DrawingTool, BoxOf>([
  [TREND_LINE, line(false, false)], [RAY, line(false, true)], [EXTENDED_LINE, line(true, true)],
  [ARROW, around], [FORECAST, around], [PATH, around], [BRUSH, around], [POLYLINE, around], [TRIANGLE, around],
  // A quadratic whose middle anchor is its control lies inside the three anchors' hull.
  [CURVE, around],
  [RECTANGLE, around], [MEASURE, around], [PRICE_RANGE, around], [DATE_RANGE, around], [GANN_BOX, around],
  [HORIZONTAL_LINE, (pts, _d, _rc, g) => ({ x0: -Infinity, y0: pts[0].y - g, x1: Infinity, y1: pts[0].y + g })],
  [HORIZONTAL_RAY, (pts, _d, _rc, g) => ({ x0: pts[0].x, y0: pts[0].y - g, x1: Infinity, y1: pts[0].y + g })],
  [VERTICAL_LINE, (pts, _d, _rc, g) => ({ x0: pts[0].x - g, y0: -Infinity, x1: pts[0].x + g, y1: Infinity })],
  [ELLIPSE, (pts, _d, _rc, g) => {
    const r = spanOf(pts.slice(0, 2), 0);
    const rx = Math.max(1e-6, (r.x1 - r.x0) / 2), ry = Math.max(1e-6, (r.y1 - r.y0) / 2);
    const k = 1 + g / Math.min(rx, ry);
    const cx = (r.x0 + r.x1) / 2, cy = (r.y0 + r.y1) / 2;
    return { x0: cx - rx * k, y0: cy - ry * k, x1: cx + rx * k, y1: cy + ry * k };
  }],
  [CIRCLE, (pts: Pts<2>, _d, _rc, g) => {
    const [a, b] = pts;
    return spanOf([a], Math.hypot(b.x - a.x, b.y - a.y) + g);
  }],
  [PARALLEL_CHANNEL, (pts: Pts<3>, _d, _rc, g) => {
    const [a, b, t] = pts;
    const dy = t.y - (a.y + (b.y - a.y) * 0.5);
    return spanOf([a, b, { x: a.x, y: a.y + dy }, { x: b.x, y: b.y + dy }], g);
  }],
  // The corners lie within the far anchor's reach of the first edge.
  [ROTATED_RECTANGLE, (pts: Pts<3>, _d, _rc, g) => pts.length < 3 ? NOWHERE
    : spanOf(pts.slice(0, 2), Math.hypot(pts[2].x - pts[1].x, pts[2].y - pts[1].y) + g)],
  // Both curves bend toward a control that is not an anchor.
  [ARC, (pts: Pts<3>, _d, _rc, g) => {
    const [a, m, b] = pts;
    return spanOf([a, b, { x: 2 * m.x - (a.x + b.x) / 2, y: 2 * m.y - (a.y + b.y) / 2 }], g);
  }],
  [DOUBLE_CURVE, (pts: Pts<3>, _d, _rc, g) => {
    if (pts.length < 3) return NOWHERE;
    const [a, m, b] = pts;
    return spanOf([a, m, b, { x: a.x + b.x - m.x, y: a.y + b.y - m.y }], g);
  }],
  // A stroke this wide is grabbed across all of it.
  [HIGHLIGHTER, (pts, d, _rc, g) => spanOf(pts, Math.max(g, Math.max(6, (d.style.lineWidth ?? 12) / 2)))],
  [FIB_RETRACEMENT, fib(2)], [FIB_EXTENSION, fib(3)],
  [LONG_POSITION, position], [SHORT_POSITION, position],
  [TEXT, bounded(TEXT, 3)], [TABLE, bounded(TABLE, 0)],
  // Cycles repeat twelve times from the first anchor, and span the plot's height.
  [CYCLIC_LINES, (pts: Pts<2>, _d, _rc, g) => {
    const [a, b] = pts, far = a.x + (b.x - a.x) * 12;
    return { x0: Math.min(a.x, far) - g, y0: -Infinity, x1: Math.max(a.x, far) + g, y1: Infinity };
  }],
  [TIME_CYCLES, (pts: Pts<2>, _d, _rc, g) => {
    const [a, b] = pts, far = a.x + (b.x - a.x) * 12;
    return { x0: Math.min(a.x, far) - g, y0: a.y - Math.abs(b.x - a.x) / 2 - g, x1: Math.max(a.x, far) + g, y1: a.y + 2 };
  }],
  [SINE_LINE, (pts: Pts<2>, _d, _rc, g) => {
    const [a, b] = pts, amp = Math.abs(b.y - a.y);
    return spanOf([{ x: a.x, y: a.y - amp }, { x: b.x, y: a.y + amp }], g);
  }],
  [FIB_TIME_ZONE, (pts: Pts<2>, d, _rc, g) => {
    const [a, b] = pts;
    const xs = activeLevels(d.style.levels, DEFAULT_FIB_TIME_ZONE).map((lv) => ({ x: a.x + (b.x - a.x) * lv.ratio, y: 0 }));
    const r = spanOf(xs, g);
    return { x0: r.x0, y0: xs.length === 0 ? Infinity : -Infinity, x1: r.x1, y1: xs.length === 0 ? -Infinity : Infinity };
  }],
  [FIB_FAN, (pts: Pts<2>, d, rc, g) => {
    const [a, b] = pts;
    return spanOf([a, ...activeLevels(d.style.levels, DEFAULT_FIB_FAN).map((lv) =>
      extendSegment(a, { x: b.x, y: a.y + (b.y - a.y) * lv.ratio }, rc.plotWidth, false, true)[1])], g);
  }],
  [GANN_FAN, (pts: Pts<2>, d, rc, g) => {
    const [a, b] = pts;
    return spanOf([a, ...activeLevels(d.style.levels, DEFAULT_GANN_FAN).map((lv) =>
      extendSegment(a, { x: b.x, y: a.y + (b.y - a.y) * lv.ratio }, rc.plotWidth, false, true)[1])], g);
  }],
  [FIB_CHANNEL, (pts: Pts<3>, d, rc, g) => {
    const [a, b, w] = pts, ox = w.x - b.x, oy = w.y - b.y;
    let box = NOWHERE;
    for (const lv of activeLevels(d.style.levels, DEFAULT_FIB)) {
      box = join(box, spanOf(extendSegment(
        { x: a.x + ox * lv.ratio, y: a.y + oy * lv.ratio }, { x: b.x + ox * lv.ratio, y: b.y + oy * lv.ratio },
        rc.plotWidth, d.style.extendLeft === true, d.style.extendRight === true,
      ), g));
    }
    return box;
  }],
  // The tail is a segment, grabbed within the radius, and the bubble anywhere on it.
  [CALLOUT, (pts: Pts<2>, d, rc, g) => pts.length < 2 ? NOWHERE : join(spanOf(pts.slice(0, 2), g), annotated(CALLOUT)(pts, d, rc, g))],
  [PRICE_LABEL, annotated(PRICE_LABEL)],
  [FLAG_MARK, mark(-8, -24, 16, 8)],
  [ARROW_UP, mark(-8, -20, 8, 20)], [ARROW_DOWN, mark(-8, -20, 8, 20)],
  [ARROW_LEFT, mark(-8, -20, 8, 20)], [ARROW_RIGHT, mark(-8, -20, 8, 20)],
  [NOTE, annotated(NOTE)], [BALLOON, annotated(BALLOON)], [COMMENT, annotated(COMMENT)],
  [SIGNPOST, annotated(SIGNPOST)], [PRICE_NOTE, annotated(PRICE_NOTE)],
]);
// Legs, necklines and filled triangles, all between the pattern's own anchors.
for (const tool of PATTERN_DRAWING_TOOLS) BOXES.set(tool, around);

/**
 * The box outside which `tool` reports no hit within `grab` of the pointer,
 * for a drawing whose anchors project to `pts`, or undefined when this table
 * does not know the tool. A drawing whose box cannot be worked out, a hand
 * edited one with a field of the wrong type say, is asked on every move, so
 * the tool answers it exactly as it did before there was a box. Ask only of a
 * drawing that holds the anchors its tool declares, as the layer paints.
 */
export function toolHitBox(
  tool: DrawingTool, pts: readonly ScreenPoint[], d: Drawing, rc: PrimitiveRenderContext, grab: number,
): HitBox | undefined {
  const of = BOXES.get(tool);
  if (of === undefined) return undefined;
  try {
    // A hundredth of a pixel of slack: a tool rounds its own arithmetic,
    // and a distance a few ulps under the radius must not fall outside.
    const b = of(pts as Pts<1>, d, rc, grab); // every caller checks the count first
    return { x0: b.x0 - SLACK, y0: b.y0 - SLACK, x1: b.x1 + SLACK, y1: b.y1 + SLACK };
  } catch {
    return EVERYWHERE;
  }
}

const SLACK = 0.01;

/**
 * Bumped each time the document finishes loading fonts. A text's box is its
 * measured width, and a web font arriving changes the width with nothing else
 * in the key moving.
 */
let fontEpoch = 0;
let watchingFonts = false;
function watchFonts(): void {
  if (watchingFonts) return;
  watchingFonts = true;
  try {
    (globalThis as { document?: { fonts?: EventTarget } }).document?.fonts?.addEventListener?.('loadingdone', () => { fontEpoch++; });
  } catch {
    // No font set to follow: text is measured by estimate and never changes.
  }
}

/** One layer's kept boxes, and the key they were measured against. */
interface DrawingHitIndex {
  /** A drawing's body box by paint position, or undefined before it is measured. */
  readonly bodies: (HitBox | undefined)[];
  /** A drawing's anchors grown by the handle radius, for the handle test. */
  readonly anchors: (HitBox | undefined)[];
  /** A new drawing list: every box goes, and the next check reads a fresh key. */
  reset(drawings: readonly Drawing[]): void;
  /**
   * Read the key for a hit test against `rc`, and let every kept box go when
   * it reads differently. The time scale is affine in the index, so its value
   * at two indices pins it, and a price scale is affine in its mode's own
   * space, so its value at two prices and its mode pin it. The bars' times are
   * read at both ends and counted, and the pane's price bars are compared by
   * identity, since new data for a series is a new array. A pane with no price
   * bars (a volume pane) has only the ends and the count, so the layer's first
   * and last drawings are also projected through the whole mapping, as a hit
   * would project them.
   */
  check(rc: PrimitiveRenderContext, drawings: readonly Drawing[], grab: number): void;
}

/** A closure, like the pane's hit boxes, so its state minifies to letters. */
export function createDrawingHitIndex(): DrawingHitIndex {
  const bodies: (HitBox | undefined)[] = [], anchors: (HitBox | undefined)[] = [], key: unknown[] = [];
  let at = 0, moved = false;
  /** The tool ids the layer's drawings use, whose registrations are part of the key. */
  let ids: string[] = [];
  const put = (value: unknown): void => {
    const i = at++;
    if (!Object.is(key[i], value)) { key[i] = value; moved = true; }
  };
  /** A drawing's first anchor through the time and price mapping; nothing for one pinned to the plot. */
  const probe = (d: Drawing | undefined, rc: PrimitiveRenderContext): void => {
    const p = d === undefined || d.space === 'viewport' ? undefined : d.points[0];
    put(p === undefined ? null : rc.dataLayer.timeToIndexFloat(p.time));
    put(p === undefined ? null : rc.priceScale.priceToY(p.price));
  };
  return {
    bodies, anchors,
    reset(drawings) {
      bodies.length = 0;
      anchors.length = 0;
      key.length = 0;
      ids = [...new Set(drawings.map((d) => d.tool))];
    },
    check(rc, drawings, grab) {
      watchFonts();
      at = 0;
      moved = false;
      const ts = rc.timeScale, dl = rc.dataLayer, ps = rc.priceScale, n = dl.length;
      // The handle radius follows the same pointer kind as the grab radius.
      put(fontEpoch); put(grab);
      put(rc.plotWidth); put(rc.plotHeight);
      put(ts.indexToX(0)); put(ts.indexToX(1));
      put(n);
      put(dl.indexToTime?.(0)); put(dl.indexToTime?.(1));
      put(dl.indexToTime?.(n - 2)); put(dl.indexToTime?.(n - 1));
      put(dl.sessionCalendar);
      put(ps.priceToY(1)); put(ps.priceToY(1000)); put(ps.options?.mode === undefined ? -1 : PRICE_SCALE_MODES.indexOf(ps.options.mode));
      const bars = rc.bars?.();
      put(bars !== undefined && bars.length > 0 ? bars : null);
      probe(drawings[0], rc);
      probe(drawings[drawings.length - 1], rc);
      for (const id of ids) put(hasDrawingTool(id) ? getDrawingTool(id) : null);
      if (at !== key.length) { key.length = at; moved = true; }
      if (moved) { bodies.length = 0; anchors.length = 0; }
    },
  };
}
