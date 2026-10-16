/**
 * Line-family renderers (ARCHITECTURE.md §6, §6A): line, line+markers, step,
 * area, baseline, HLC-area. Pure point geometry is split out for unit testing.
 */
import type { Bar } from '../model/bar';
import type { SeriesStyle } from './series-style';
import { verticalGradient } from './gradient';
import type { LooseOptional } from '../helpers/types';

export interface LineDrawItem {
  x: number; // bar center, media px
  bar: Bar;
  /** Set on a neighbour beyond the view: the x of the plot edge it lies past (DrawItem.edgeX). */
  edgeX?: number;
}

export interface Pt {
  x: number;
  y: number;
}

/** Pure: project items to screen points using a value accessor (default close). */
export function valuePoints(
  items: readonly LineDrawItem[],
  toY: (value: number) => number,
  value: (b: Bar) => number = (b) => b.close,
): Pt[] {
  return items.map((it) => ({ x: it.x, y: toY(value(it.bar)) }));
}

/** Pure: expand a value polyline into a step (HV) polyline. */
export function stepPoints(pts: readonly Pt[]): Pt[] {
  if (pts.length === 0) return [];
  // Every index read here is below pts.length.
  const out: Pt[] = [{ ...pts[0]! }];
  for (let i = 1; i < pts.length; i++) {
    out.push({ x: pts[i]!.x, y: pts[i - 1]!.y }); // horizontal
    out.push({ x: pts[i]!.x, y: pts[i]!.y }); // vertical
  }
  return out;
}

/**
 * A polyline in media px, as two coordinate arrays and a count.
 *
 * The renderers below run for every line series (every indicator plot among
 * them) on every frame of a pan, and they used to build a `{ x, y }` object
 * per bar each time, twice for a step line and twice again under an area:
 * garbage by the next frame. They fill these in place instead. A renderer
 * runs start to end without yielding, so one set serves every series; each
 * is filled and read within one renderer, and a renderer that calls
 * `drawLine` is done with the line's points before it does.
 *
 * Both arrays hold a value at every index below `n` (they may run longer,
 * with a wider frame's leftovers), so a read under `n` carries `!`.
 */
export interface Polyline {
  xs: number[];
  ys: number[];
  /** First point to draw: `trimToView` can drop a leg that lies wholly past the view. */
  s: number;
  n: number;
  /**
   * Where a leg in from beyond the view ends (the first bar in view, or the
   * corner under it on a step whose first bar is a gap), and where the bars
   * in view end before a leg out to beyond it: -1 when there is none. A
   * dashed stroke keeps those legs off the bars' own path (strokePolyline).
   */
  a: number;
  b: number;
}

export const polyline = (): Polyline => ({ xs: [], ys: [], s: 0, n: 0, a: -1, b: -1 });

/** The values' line and its step form; an HLC band's upper and lower edges. */
const VALUES = polyline(), STEPS = polyline(), HIGHS = polyline(), LOWS = polyline();

/** Per-point colours of the line being drawn, reused like the points. */
const COLORS: (string | undefined)[] = [];

/**
 * Close a fill of `n` points. A view zoomed back in from a very wide one gives
 * the room back rather than keeping a whole history's worth for good.
 */
function settle(line: Polyline, n: number): void {
  line.s = 0;
  line.a = line.b = -1;
  line.n = n;
  if (line.xs.length > 16_384 && n * 4 < line.xs.length) line.xs.length = line.ys.length = n;
}

/** Which bar value a polyline follows. */
export const CLOSE = 0, HIGH = 1, LOW = 2;

/** `valuePoints`, written into `line`: the same x and y for each item, in order. */
export function project(line: Polyline, items: readonly LineDrawItem[], toY: (value: number) => number, field: number): void {
  const xs = line.xs, ys = line.ys;
  for (let i = 0; i < items.length; i++) {
    const it = items[i]!, b = it.bar;
    xs[i] = it.x;
    ys[i] = toY(field === CLOSE ? b.close : field === HIGH ? b.high : b.low);
  }
  settle(line, items.length);
}

/** `stepPoints`, written into `out`: 2n - 1 points, the horizontal leg of each step first. */
export function projectSteps(src: Polyline, out: Polyline): void {
  const sx = src.xs, sy = src.ys, xs = out.xs, ys = out.ys;
  let k = 0;
  for (let i = 0; i < src.n; i++) {
    if (i > 0) { xs[k] = sx[i]!; ys[k++] = sy[i - 1]!; } // horizontal
    xs[k] = sx[i]!; ys[k++] = sy[i]!; // vertical
  }
  settle(out, k);
}

/** Media px past the plot edge a cut segment still runs, on top of its line width: past any cap or join. */
export const EDGE_PAD = 8;

/**
 * The length of one repeat of a dash list given in device px, as a 2D context
 * reads it (an odd list is repeated to make it even), in media px; 0 for solid.
 */
export function dashPeriod(dash: readonly number[], dpr: number): number {
  let total = 0;
  for (let i = 0; i < dash.length; i++) total += dash[i]!;
  return total > 0 ? (dash.length % 2 === 1 ? 2 * total : total) / dpr : 0;
}

/**
 * Cut the segments that join `items`' first and last point to a neighbour
 * beyond the view (`edgeX`) at the plot edge, `pad` media px out, in place.
 *
 * Uncut, that segment runs to a bar that can be millions of pixels off
 * screen. The GPU backend walked a dashed one in script and built a quad for
 * every dash of it, on every frame (a level with its bars a session either
 * side took a fifth of a second a frame), and a 2D context or an exported
 * document was left to cope with coordinates that far out. The cut is on the
 * segment itself, in screen space, so the visible part neither bends (a log
 * scale is not linear in price) nor moves.
 *
 * `period` (media px, 0 for solid) keeps the dash phase where it was before
 * the neighbours were drawn at all: the path starts a whole number of periods
 * back from the first bar in view, so every dash from that bar on lands where
 * it always did and only the segment out to the edge is new. That start may
 * lie a little past the cut, or past a neighbour that was already near,
 * always further from the plot. A step's leading leg is horizontal at the
 * neighbour's level and then vertical at the first bar, and both count.
 *
 * A leg with no value at either end (a study's plot stores a bar without one
 * as NaN) is dropped as well, and its outer point emptied: a gap is never
 * bridged, and an area, baseline or band fill would otherwise shade from the
 * plot edge to the first value, or across the gap to the next one. A step
 * still holds its level up to a bar that is a gap, as it does in view.
 */
export function trimToView(
  line: Polyline, items: readonly LineDrawItem[], step: boolean, period: number, pad: number,
): void {
  const count = items.length;
  if (count === 0) return;
  const head = items[0]!.edgeX, tail = items[count - 1]!.edgeX;
  if (head === undefined && tail === undefined) return;
  // A lone neighbour has nothing in view to join.
  if (count === 1) { line.n = 0; return; }
  // Two items or more: `line` holds two points or more (three or more on a
  // step), and every index read below is under `line.n`.
  const xs = line.xs, ys = line.ys;
  if (head !== undefined) {
    const lo = head - pad;
    // The leg runs from the neighbour to its inner end: the first bar, or
    // the corner under it on a step.
    const ix = xs[1]!, iy = ys[1]!, ox = xs[0]!, oy = ys[0]!;
    if (ix < lo || !Number.isFinite(oy) || !Number.isFinite(iy)) {
      // Out of sight (zoomed in so far that the first bar is past the
      // margin itself) or a gap: the path starts at the first bar, as it did
      // before. The emptied point keeps a band, which pairs its two edges by
      // index, from reaching for it.
      line.s = step ? 2 : 1;
      ys[0] = NaN;
    } else {
      const len = Math.hypot(ox - ix, oy - iy);
      let reach = ox < lo ? len * (ix - lo) / (ix - ox) : len;
      // The dash phase is anchored to the first bar's own value, which on a
      // step is the vertical leg further on; when that value is a gap, to the
      // corner under it, where the step's hold ends.
      const on = step && Number.isFinite(ys[2]);
      const lead = on ? Math.abs(ys[2]! - iy) : 0;
      if (period > 0) reach = Math.ceil((reach + lead) / period) * period - lead;
      if (reach !== len) {
        const f = reach / len;
        xs[0] = ix + (ox - ix) * f;
        ys[0] = iy + (oy - iy) * f;
      }
      line.a = on ? 2 : 1;
    }
  }
  if (tail !== undefined) {
    const hi = tail + pad;
    // A step's last bar is two points (the horizontal leg's end, then the
    // vertical one); its leg starts at the bar before.
    const k = step ? line.n - 2 : line.n - 1;
    const ix = xs[k - 1]!, iy = ys[k - 1]!, ox = xs[k]!, oy = ys[k]!;
    if (ix > hi || !Number.isFinite(iy) || !Number.isFinite(oy)) {
      line.n = k;
      ys[k] = NaN;
    } else {
      if (ox > hi) {
        ys[k] = iy + (oy - iy) * ((hi - ix) / (ox - ix));
        xs[k] = hi;
        line.n = k + 1;
      }
      line.b = k - 1;
    }
  }
}

/** The dash pattern of a named line style in device px: the one table series lines, study drawings and drawing tools share (not the grid's). */
export function dashFor(lineStyle: SeriesStyle['lineStyle'], dpr: number): number[] {
  return lineStyle === 'dashed' ? [6 * dpr, 4 * dpr] : lineStyle === 'dotted' ? [1 * dpr, 3 * dpr] : [];
}

/**
 * Per-point colours aligned to the polyline drawn for `items`, or undefined
 * when not one point carries its own. Undefined is the fast path every
 * ordinary series takes: `strokePolyline` then walks the whole line into a
 * single stroke, as before.
 */
export function pointColors(items: readonly LineDrawItem[], step: boolean): (string | undefined)[] | undefined {
  let any = false;
  for (let i = 0; i < items.length; i++) if (items[i]!.bar.color !== undefined) { any = true; break; }
  if (!any) return undefined;
  let k = 0;
  for (let i = 0; i < items.length; i++) {
    const color = items[i]!.bar.color;
    // A step's horizontal and vertical legs both belong to the span arriving at
    // this bar, so they take one colour rather than meeting half-recoloured.
    if (step && k > 0) COLORS[k++] = color;
    COLORS[k++] = color;
  }
  COLORS.length = k;
  return COLORS;
}

/**
 * When `dashed`, the legs in from and out to beyond the view (`Polyline.a`,
 * `.b`) are strokes of their own. A browser rasterises a dashed stroke as one
 * shape, and a segment added anywhere on its path moves the anti-aliasing of
 * dashes all along it, so with the legs on it the bars' own dashes would
 * still differ, if only by a few levels, from the ones drawn before the legs
 * were. The leg out carries the dash pattern on through `lineDashOffset`. A
 * solid line keeps its legs in its one path, where they meet the bars with a
 * join and no seam at any opacity.
 */
function strokePolyline(
  ctx: CanvasRenderingContext2D,
  line: Polyline,
  dpr: number,
  colors?: readonly (string | undefined)[],
  dashed = false,
): void {
  const n = line.n, xs = line.xs, ys = line.ys, a = line.a;
  // The point the leg out reaches, if there is one.
  const out = line.b < 0 ? -1 : line.b + 1;
  if (n <= line.s) return;
  // What a point that names no colour of its own falls back to.
  const fallback = ctx.strokeStyle;
  // Break the line across non-finite points (whitespace gaps) so indicators with
  // holes (an RSI warm-up, the Supertrend up/down split) render as separate segments.
  ctx.beginPath();
  let prev = -1;
  let run: string | undefined;
  let drawn = false; // the open path holds at least one segment
  // Media px of dashed path since its pattern last started.
  let walked = 0;
  for (let i = line.s; i < n; i++) {
    const x = xs[i]!, y = ys[i]!;
    if (!Number.isFinite(x) || !Number.isFinite(y)) { prev = -1; continue; }
    if (prev < 0) { ctx.moveTo(x * dpr, y * dpr); prev = i; walked = 0; continue; }
    // A per-point colour series: the segment arriving at a bar takes that
    // bar's colour. A change strokes the run accumulated so far and restarts the
    // path from the same point, so consecutive runs abut with no seam. With no
    // colours at all `c` tracks `run`, the test never fires, and the whole line
    // goes down in one stroke exactly as it did before.
    const c = colors === undefined ? run : colors[i];
    if (c !== run) {
      if (drawn) {
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(xs[prev]! * dpr, ys[prev]! * dpr);
        drawn = false;
        walked = 0;
      }
      ctx.strokeStyle = c ?? fallback;
      run = c;
    }
    if (dashed && drawn && i === out) {
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(xs[prev]! * dpr, ys[prev]! * dpr);
      ctx.lineDashOffset = walked * dpr;
      drawn = false;
    }
    ctx.lineTo(x * dpr, y * dpr);
    if (dashed) walked += Math.hypot(x - xs[prev]!, y - ys[prev]!);
    prev = i;
    drawn = true;
    if (dashed && i === a) {
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(x * dpr, y * dpr);
      drawn = false;
      walked = 0;
    }
  }
  ctx.stroke();
}

export function drawLine(
  ctx: CanvasRenderingContext2D,
  items: readonly LineDrawItem[],
  toY: (v: number) => number,
  dpr: number,
  style: SeriesStyle,
): void {
  const base = VALUES;
  project(base, items, toY, CLOSE);
  let pts = base;
  if (style.step) projectSteps(base, pts = STEPS);
  const cols = pointColors(items, style.step === true);
  const lineWidth = style.lineWidth ?? 1.5;
  const dash = dashFor(style.lineStyle, dpr);
  trimToView(pts, items, style.step === true, dashPeriod(dash, dpr), EDGE_PAD + lineWidth);
  ctx.save();
  ctx.strokeStyle = style.color ?? '#4f8cff';
  // Not rounded to whole device px: snapping a 1.5px stroke up to 2px reads
  // heavier and blockier than the width the caller asked for. Rounding only
  // helps axis-aligned rules, and a polyline is rarely one. Round caps + joins
  // keep reversals and segment ends smooth rather than chiselled.
  ctx.lineWidth = Math.max(1, lineWidth * dpr);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.setLineDash(dash);
  // markersOnly: dots with no connecting stroke (Parabolic SAR, scatter plots).
  if (!style.markersOnly) strokePolyline(ctx, pts, dpr, cols, dash.length > 0);
  ctx.setLineDash([]);
  if (style.markers || style.markersOnly) {
    const r = (style.markerRadius ?? 2) * dpr;
    const fill = style.color ?? '#4f8cff';
    ctx.fillStyle = fill;
    for (let i = 0; i < items.length; i++) {
      const x = base.xs[i]!, y = base.ys[i]!;
      // A neighbour beyond the view carries the segment in, not a dot of its
      // own; on a plain line its point is the cut one besides.
      if (!Number.isFinite(x) || !Number.isFinite(y) || items[i]!.edgeX !== undefined) continue;
      // A dot follows its own bar's colour, not the segment rule: a marker sits
      // on the bar rather than between two of them.
      if (cols !== undefined) ctx.fillStyle = items[i]!.bar.color ?? fill;
      ctx.beginPath();
      ctx.arc(x * dpr, y * dpr, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  ctx.restore();
}

export function drawArea(
  ctx: CanvasRenderingContext2D,
  items: readonly LineDrawItem[],
  toY: (v: number) => number,
  dpr: number,
  plotHeight: number,
  style: SeriesStyle,
): void {
  const pts = VALUES;
  project(pts, items, toY, CLOSE);
  trimToView(pts, items, false, 0, EDGE_PAD + (style.lineWidth ?? 1.5));
  const s = pts.s, n = pts.n, xs = pts.xs, ys = pts.ys;
  if (n <= s) return;
  const baseY = plotHeight * dpr;
  ctx.save();
  ctx.beginPath();
  ctx.moveTo(xs[s]! * dpr, baseY);
  for (let i = s; i < n; i++) ctx.lineTo(xs[i]! * dpr, ys[i]! * dpr);
  ctx.lineTo(xs[n - 1]! * dpr, baseY);
  ctx.closePath();
  // vertical gradient: solid-ish near the line fading toward the baseline
  ctx.fillStyle = verticalGradient(
    ctx, baseY,
    style.areaTopColor ?? 'rgba(79,140,255,0.40)',
    style.areaBottomColor ?? 'rgba(79,140,255,0.00)',
  );
  ctx.fill();
  ctx.restore();
  // The outline is a plain line, so it carries the dash the caller asked for.
  // The fill keeps its own gradient: a dashed edge over a solid body is the
  // shape of an area chart, and dashing the fill too would just look broken.
  // An unset lineStyle is passed on unset, which drawLine reads as solid.
  drawLine(ctx, items, toY, dpr, {
    color: style.color ?? '#4f8cff',
    lineWidth: style.lineWidth ?? 1.5,
    lineStyle: style.lineStyle,
  } satisfies LooseOptional<SeriesStyle> as SeriesStyle);
}

export function drawBaseline(
  ctx: CanvasRenderingContext2D,
  items: readonly LineDrawItem[],
  toY: (v: number) => number,
  dpr: number,
  style: SeriesStyle,
): void {
  const baseValue = style.baseValue ?? 0;
  const baseY = toY(baseValue) * dpr;
  const pts = VALUES;
  project(pts, items, toY, CLOSE);
  trimToView(pts, items, false, 0, EDGE_PAD + (style.lineWidth ?? 1.5));
  const s = pts.s, n = pts.n, xs = pts.xs, ys = pts.ys;
  if (n <= s) return;

  // Gradient fills: above-base region fades down from topFill, below-base fades up
  // from bottomFill. Built as one area polygon to the base line, clipped at baseY.
  const minX = xs[s]! * dpr;
  const maxX = xs[n - 1]! * dpr;
  const buildArea = (): void => {
    ctx.beginPath();
    ctx.moveTo(minX, baseY);
    for (let i = s; i < n; i++) ctx.lineTo(xs[i]! * dpr, ys[i]! * dpr);
    ctx.lineTo(maxX, baseY);
    ctx.closePath();
  };
  const topFill = style.areaTopColor ?? 'rgba(38,166,154,0.20)';
  const botFill = style.areaBottomColor ?? 'rgba(239,83,80,0.20)';
  const BIG = 1e5;
  // above base
  ctx.save();
  ctx.beginPath(); ctx.rect(minX, baseY - BIG, maxX - minX, BIG); ctx.clip();
  buildArea();
  ctx.fillStyle = verticalGradient(ctx, baseY, topFill, 'rgba(0,0,0,0)');
  ctx.fill();
  ctx.restore();
  // below base
  ctx.save();
  ctx.beginPath(); ctx.rect(minX, baseY, maxX - minX, BIG); ctx.clip();
  buildArea();
  ctx.fillStyle = botFill;
  ctx.fill();
  ctx.restore();

  ctx.save();
  // split stroke: above-base in topColor, below-base in bottomColor
  for (let i = s + 1; i < n; i++) {
    const ay = ys[i - 1]!, by = ys[i]!;
    const above = (ay + by) / 2 <= baseY / dpr; // smaller y = higher price = above base
    ctx.strokeStyle = above ? (style.topColor ?? '#26a69a') : (style.bottomColor ?? '#ef5350');
    ctx.lineWidth = Math.max(1, Math.round((style.lineWidth ?? 1.5) * dpr));
    ctx.beginPath();
    ctx.moveTo(xs[i - 1]! * dpr, ay * dpr);
    ctx.lineTo(xs[i]! * dpr, by * dpr);
    ctx.stroke();
  }
  ctx.restore();
}

/**
 * The HLC area band when the style sets no `areaTopColor`. It is its own
 * colour on every theme, not the theme's area colour, so a settings dialog
 * shows it as the default to report what is drawn.
 */
export const HLC_AREA_BAND_COLOR = 'rgba(79,140,255,0.15)';

export function drawHlcArea(
  ctx: CanvasRenderingContext2D,
  items: readonly LineDrawItem[],
  toY: (v: number) => number,
  dpr: number,
  style: SeriesStyle,
): void {
  if (items.length === 0) return;
  const highs = HIGHS, lows = LOWS;
  const pad = EDGE_PAD + (style.lineWidth ?? 1.5);
  project(highs, items, toY, HIGH);
  project(lows, items, toY, LOW);
  trimToView(highs, items, false, 0, pad);
  trimToView(lows, items, false, 0, pad);
  const s = highs.s, n = highs.n;
  // fill between high and low; each edge runs over its own points, since a
  // gap at the view edge drops the leg of whichever edge has no value there
  ctx.save();
  ctx.beginPath();
  if (n > s) ctx.moveTo(highs.xs[s]! * dpr, highs.ys[s]! * dpr);
  for (let i = s; i < n; i++) ctx.lineTo(highs.xs[i]! * dpr, highs.ys[i]! * dpr);
  for (let i = lows.n - 1; i >= lows.s; i--) ctx.lineTo(lows.xs[i]! * dpr, lows.ys[i]! * dpr);
  ctx.closePath();
  ctx.fillStyle = style.areaTopColor ?? HLC_AREA_BAND_COLOR;
  ctx.fill();
  ctx.restore();
  // The two edges of the band, each drawn only when the caller named a colour
  // for it. They have no default: an HLC area is a filled band plus a close
  // line, so a caller who never set these gets exactly the frame it always got.
  strokeEdge(ctx, highs, style.highColor, style, dpr);
  strokeEdge(ctx, lows, style.lowColor, style, dpr);
  drawLine(ctx, items, toY, dpr, { color: style.closeColor ?? '#4f8cff', lineWidth: style.lineWidth ?? 1.5 });
}

/** One edge of an HLC band, in its own colour, or nothing without one. */
function strokeEdge(ctx: CanvasRenderingContext2D, edge: Polyline, color: string | undefined, style: SeriesStyle, dpr: number): void {
  if (color === undefined) return;
  ctx.save();
  ctx.strokeStyle = color;
  ctx.lineWidth = Math.max(1, Math.round((style.lineWidth ?? 1.5) * dpr));
  strokePolyline(ctx, edge, dpr);
  ctx.restore();
}
