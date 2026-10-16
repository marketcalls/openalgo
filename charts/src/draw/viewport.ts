/**
 * The arithmetic of viewport anchors (`Drawing.space === 'viewport'`), shared
 * by the layer that paints them, the controller that moves them, and the
 * migration and clipboard that read them from outside. Pure: no registry, no
 * chart, so the migration can use it and stay pure too.
 *
 * A viewport anchor is a fraction of its pane's plot, so the only operations
 * are validation, the scaling to pixels, which needs nothing but the plot's
 * size, and keeping a drawing's box inside the plot, which needs the box.
 */
import type { Drawing, ScreenPoint, ViewportPoint } from './types';
import { isNum, isRecord } from './drawing-fields';

/** The anchors a drawing carries in its own space: what decides whether it is complete. */
export const anchorCount = (d: Drawing): number =>
  d.space === 'viewport' ? d.viewportPoints?.length ?? 0 : d.points.length;

/**
 * A list of finite `{ x, y }` records as fresh objects, or null. Empty is
 * null as well: a drawing with no anchor can never be painted or grabbed.
 * Values outside 0..1 are kept as given: the layer paints the drawing with
 * its box moved inside the plot whatever its anchors say, so a value a host
 * set outside cannot hide it.
 */
export function readViewportPoints(value: unknown, max = Infinity): ViewportPoint[] | null {
  if (!Array.isArray(value) || value.length === 0 || value.length > max) return null;
  const out: ViewportPoint[] = [];
  for (const p of value) {
    if (!isRecord(p) || !isNum(p.x) || !isNum(p.y)) return null;
    out.push({ x: p.x, y: p.y });
  }
  return out;
}

/** An extent in plot px: what a pinned drawing covers, and so what must stay on screen. */
export interface PlotBox { x0: number; y0: number; x1: number; y1: number }

/**
 * The step along one axis that brings the span `lo..hi` inside `0..size`, or,
 * when the span is longer than that, brings its start to 0: the top-left of a
 * note or a table is what is read first, so it is the part kept in view.
 */
const into = (lo: number, hi: number, size: number): number =>
  lo < 0 || hi - lo > size ? -lo : hi > size ? size - hi : 0;

/**
 * Anchors in plot px moved together, so the shape keeps its size, by as much
 * as it takes to bring `box` (the drawing's extent at those anchors) inside a
 * plot of `width` by `height`. It is the box and not the anchors that is kept
 * in: a text note is laid out right of and below its one anchor, so an anchor
 * held at the plot's edge leaves the whole note outside it, where it can be
 * neither seen nor clicked.
 */
export function containInPlot(pts: readonly ScreenPoint[], box: PlotBox, width: number, height: number): ScreenPoint[] {
  const dx = into(box.x0, box.x1, width);
  const dy = into(box.y0, box.y1, height);
  return pts.map((p) => ({ x: p.x + dx, y: p.y + dy }));
}

/** Viewport anchors to plot-relative media px on a plot of `width` by `height`. */
export function viewportToPlot(points: readonly ViewportPoint[], width: number, height: number): ScreenPoint[] {
  return points.map((p) => ({ x: p.x * width, y: p.y * height }));
}
