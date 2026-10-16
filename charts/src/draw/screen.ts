/**
 * Every conversion the drawing controller makes between data space and the
 * screen: an anchor to pixels and back, a move by a screen distance, the 45
 * degree lock, the pointer samples of a stroke, and the fractions a drawing
 * pinned to the viewport stores. Kept apart from the controller so that the
 * controller holds the model and the gestures, and this holds the arithmetic
 * they share, all of it reading the chart through the same optional methods
 * of `DrawingChartHost`, each of which a host may lack.
 */
import type { PlotRect } from 'openalgo-charts';
import type { Drawing, DrawingPoint, ScreenPoint, ViewportPoint } from './types';
import type { DrawingChartHost } from './controller-types';
import { placeViewportAnchors, toolBounds } from './layer';
import { boundsOf } from './geometry';
import { rdpSimplify } from './freehand';
import { clamp } from '../helpers/math';

/**
 * The time scale's default bar spacing, for a horizontal nudge on a host that
 * cannot map pixels to time. Wrong by the zoom factor there, never by an order
 * of magnitude.
 */
const FALLBACK_BAR_SPACING_PX = 8;

/** The angle step Shift locks a line to, in radians: 45 degrees. */
const ANGLE_STEP = Math.PI / 4;

/**
 * How far a thinned stroke may stray from the pointer's path, in media px.
 * Under the width of the ink itself, so the thinning is invisible; above the
 * jitter of a hand, so a stroke stops costing an anchor per pixel.
 */
const STROKE_EPSILON_PX = 1.5;

/**
 * The pressure a mouse reports while its button is held, and what a sample
 * without a value is taken to be. A sample at exactly this value stores
 * nothing, so a mouse stroke carries no pressure at all.
 */
const REST_PRESSURE = 0.5;

/** The pane-local price projection a chart pane carries, in media px. */
export interface PaneProjection {
  priceToY(price: number): number;
  yToPrice(y: number): number;
}

/** One coalesced pointer position: container x, pane-local y, pressure. */
export interface PointerSample {
  x: number;
  y: number;
  pressure?: number;
}

/**
 * Anchors on one axis, from `a0..a1`, cut so the box `b0..b1` they carry fits
 * a plot of `size`: held inside the room the box leaves them, so a label
 * above a box stays above it on the plot, or on the plot when the box adds
 * more than the plot has.
 */
const cutInto = (b0: number, b1: number, a0: number, a1: number, size: number) => {
  const lead = Math.max(0, a0 - b0);
  const trail = Math.max(0, b1 - a1);
  return (v: number): number => (b1 - b0 <= size ? v
    : lead + trail < size ? Math.min(Math.max(v, lead), size - trail)
    : clamp(v, 0, size));
};

export class DrawingScreen {
  private readonly _chart: DrawingChartHost;

  public constructor(chart: DrawingChartHost) {
    this._chart = chart;
  }

  /**
   * Bar spacing in seconds, read from the last gap in the data. A one-bar chart
   * has no gap to read, so fall back to a minute rather than answering zero and
   * producing zero-width defaults and invisible paste offsets.
   */
  public barSeconds(): number {
    const dl = this._chart.dataLayer;
    const n = dl.baseIndex;
    const a = n > 0 ? dl.indexToTime(n - 1) : undefined;
    const b = n >= 0 ? dl.indexToTime(n) : undefined;
    return a !== undefined && b !== undefined && b > a ? b - a : 60;
  }

  /**
   * Move a price down the screen by `px`. Done per anchor rather than as one
   * price delta so the move is a rigid *screen* translation, which is what the
   * eye expects and what keeps a shape's proportions on a log scale.
   */
  public offsetPrice(price: number, paneIndex: number, px: number): number {
    if (px === 0) return price;
    const toY = this._chart.priceToCoordinate;
    const toPrice = this._chart.coordinateToPrice;
    if (toY === undefined || toPrice === undefined) return price;   // time offset only
    const y = toY.call(this._chart, price, paneIndex);
    if (y === null || !Number.isFinite(y)) return price;
    const moved = toPrice.call(this._chart, y + px, paneIndex);
    if (moved === null || !Number.isFinite(moved)) return price;
    return moved;
  }

  /** Move a time right along the screen by `px`. */
  public offsetTime(time: number, px: number): number {
    if (px === 0) return time;
    const toX = this._chart.timeToCoordinate;
    const toTime = this._chart.coordinateToTime;
    if (toX !== undefined && toTime !== undefined) {
      const x = toX.call(this._chart, time);
      if (Number.isFinite(x)) {
        const moved = toTime.call(this._chart, x + px);
        if (Number.isFinite(moved)) return moved;
      }
    }
    return time + (px / FALLBACK_BAR_SPACING_PX) * this.barSeconds();
  }

  /** How far down the screen `to` is from `from` on one pane, in media px. */
  public pixelDelta(from: number, to: number, paneIndex: number): number {
    const toY = this._chart.priceToCoordinate;
    if (toY === undefined) return 0;
    const y0 = toY.call(this._chart, from, paneIndex);
    const y1 = toY.call(this._chart, to, paneIndex);
    return y0 === null || y1 === null || !Number.isFinite(y0) || !Number.isFinite(y1) ? 0 : y1 - y0;
  }

  /** An anchor in container media px, or null on a host without the mapping. */
  public toPixel(p: DrawingPoint, paneIndex: number): ScreenPoint | null {
    const toX = this._chart.timeToCoordinate;
    const toY = this._chart.priceToCoordinate;
    if (toX === undefined || toY === undefined) return null;
    const x = toX.call(this._chart, p.time);
    const y = toY.call(this._chart, p.price, paneIndex);
    return y === null || !Number.isFinite(x) || !Number.isFinite(y) ? null : { x, y };
  }

  /** The inverse of `toPixel`. */
  public fromPixel(at: ScreenPoint, paneIndex: number): DrawingPoint | null {
    const toTime = this._chart.coordinateToTime;
    const toPrice = this._chart.coordinateToPrice;
    if (toTime === undefined || toPrice === undefined) return null;
    const time = toTime.call(this._chart, at.x);
    const price = toPrice.call(this._chart, at.y, paneIndex);
    return price === null || !Number.isFinite(time) || !Number.isFinite(price) ? null : { time, price };
  }

  /**
   * `free` projected onto the nearest 45 degree ray from `anchor`, all in
   * screen space: the angle the eye reads is the one on the canvas, and a log
   * scale or a tall pane would make a data-space angle anything but. The
   * projection rather than a rotation, so a level line still ends under the
   * pointer's x and a vertical one under its y; only the stray axis is
   * dropped. Null when the host cannot map pixels, or the two coincide.
   */
  public lockAngle(anchor: DrawingPoint, free: DrawingPoint, paneIndex: number): DrawingPoint | null {
    const a = this.toPixel(anchor, paneIndex);
    const b = this.toPixel(free, paneIndex);
    if (a === null || b === null) return null;
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    if (dx === 0 && dy === 0) return null;
    const angle = Math.round(Math.atan2(dy, dx) / ANGLE_STEP) * ANGLE_STEP;
    const ux = Math.cos(angle);
    const uy = Math.sin(angle);
    const along = dx * ux + dy * uy;
    return this.fromPixel({ x: a.x + along * ux, y: a.y + along * uy }, paneIndex);
  }

  // ── freehand samples ────────────────────────────────────────────────────

  /**
   * The positions a pressed move passed through, as anchors, ending on the
   * move's own point. The samples carry pixels (container x, pane-local y);
   * the payload's point is the same position in its own space, so the gap
   * between the two is the pane's offset, and each sample maps back through
   * the host's converters. A host without them, or a payload without
   * samples, inks the one point the move reports.
   */
  public coalesced(
    p: { point?: { x: number; y: number } | null; samples?: PointerSample[]; pressure?: number },
    last: DrawingPoint, paneIndex: number,
  ): DrawingPoint[] {
    const samples = p.samples;
    const end = { ...last, ...this.pressureOf(p.pressure) };
    const toTime = this._chart.coordinateToTime;
    const toPrice = this._chart.coordinateToPrice;
    if (!Array.isArray(samples) || samples.length < 2 || toTime === undefined || toPrice === undefined
      || p.point === null || p.point === undefined) {
      return [end];
    }
    const tail = samples[samples.length - 1]!; // two or more, by the check above
    const shift = p.point.y - tail.y;
    if (!Number.isFinite(shift)) return [end];
    const out: DrawingPoint[] = [];
    for (let i = 0; i < samples.length - 1; i++) {
      const s = samples[i]!; // i is in range
      const time = toTime.call(this._chart, s.x);
      const price = toPrice.call(this._chart, s.y + shift, paneIndex);
      if (price === null || !Number.isFinite(time) || !Number.isFinite(price)) continue;
      out.push({ time, price, ...this.pressureOf(s.pressure) });
    }
    out.push({ ...end, ...this.pressureOf(tail.pressure ?? p.pressure) });
    return out;
  }

  /** A pressure worth storing: finite, and not the mouse's stand-in. */
  public pressureOf(pressure: number | undefined): { pressure?: number } {
    return typeof pressure === 'number' && Number.isFinite(pressure) && pressure !== REST_PRESSURE
      ? { pressure: Math.min(1, Math.max(0, pressure)) }
      : {};
  }

  /**
   * A stroke thinned in screen space, since the tolerance is a pixel one. A
   * host that cannot map to pixels keeps every sample.
   */
  public thinStroke(pts: DrawingPoint[], paneIndex: number): DrawingPoint[] {
    const px: ScreenPoint[] = [];
    for (const p of pts) {
      const at = this.toPixel(p, paneIndex);
      if (at === null) return pts;
      px.push(at);
    }
    const kept = rdpSimplify(px, STROKE_EPSILON_PX);
    // Kept points come back at their exact input coordinates, in order, so
    // walking the input once pairs each with the sample it came from.
    const out: DrawingPoint[] = [];
    let j = 0;
    for (const k of kept) {
      while (j < px.length && (px[j]!.x !== k.x || px[j]!.y !== k.y)) j++; // j < length, and pts pairs px
      if (j >= px.length) return pts;   // cannot happen; keep everything rather than lose a sample
      out.push(pts[j]!);
      j++;
    }
    return out;
  }

  // ── viewport space ──────────────────────────────────────────────────────
  //
  // A viewport anchor is a fraction of its pane's plot. The layer scales it
  // by the plot size in its render context; everything here scales it by the
  // plot the chart reports (`plotRect`), the same rectangle the chart hands
  // that render context, and reads y through the pane's own readout scale,
  // the scale a gesture's price was read from. Plot-relative px therefore
  // agree with what the layer painted.

  /** A pane's price projection, when the host exposes one. */
  public pane(paneIndex: number): PaneProjection | null {
    const own = this._chart.panes?.()[paneIndex] as PaneProjection | undefined;
    return typeof own?.priceToY === 'function' && typeof own.yToPrice === 'function' ? own : null;
  }

  /**
   * Where a pane's plot is and how big, or null when it has none on screen
   * (folded to a strip, or hidden behind a maximized pane): a fraction of
   * either would be a fraction of nothing. It needs a pane projection too,
   * since every gesture reads its y back through one.
   */
  public plotFrame(paneIndex: number): PlotRect | null {
    const rect = this.pane(paneIndex) === null ? null : this._chart.plotRect?.(paneIndex) ?? null;
    return rect !== null && rect.width > 0 && rect.height > 0 ? rect : null;
  }

  /**
   * A gesture's position on its pane's plot, in media px. y reads the price
   * back through the pane's readout scale, the exact inverse of how the chart
   * read it; x is the pointer's container x less the plot's left edge, or,
   * for a payload without one, the time through the time axis.
   */
  public gesturePlot(p: { time: number; price: number; point?: { x: number } | null }, paneIndex: number): ScreenPoint | null {
    const pane = this.pane(paneIndex);
    const ts = this._chart.timeScale;
    if (pane === null || !Number.isFinite(p.price)) return null;
    const x = p.point !== undefined && p.point !== null ? p.point.x - (this.plotFrame(paneIndex)?.left ?? Number.NaN)
      : ts === undefined ? Number.NaN : ts.indexToX(this._chart.dataLayer.timeToIndexFloat(p.time));
    const y = pane.priceToY(p.price);
    return Number.isFinite(x) && Number.isFinite(y) ? { x, y } : null;
  }

  /**
   * Where a drag was pressed, on its pane's plot. Read from the press's time
   * and price when the chart reports them, so the first move is measured from
   * the press and not from itself; a chart with fewer than two bars has no
   * time axis to read a position back from, so it measures from the first move.
   */
  public dragOrigin(p: { time: number; price: number; paneIndex: number; point?: { x: number } | null; fromTime?: number; fromPrice?: number }): ScreenPoint | null {
    if (p.fromTime !== undefined && p.fromPrice !== undefined && this._chart.dataLayer.length >= 2) {
      return this.gesturePlot({ time: p.fromTime, price: p.fromPrice }, p.paneIndex);
    }
    return this.gesturePlot(p, p.paneIndex);
  }

  /**
   * Data anchors as fractions of their pane's plot at the view on screen, or
   * null when it has none. What is on screen stays where it is; a drawing part
   * way or wholly off the plot comes onto it, since once pinned no pan could
   * bring it back. One that fits moves in whole. One wider or taller than the
   * plot is cut to it on that axis instead, so every handle of a pinned box
   * is on screen to be grabbed.
   */
  public toViewport(points: readonly DrawingPoint[], paneIndex: number, d: Drawing): ViewportPoint[] | null {
    const frame = this.plotFrame(paneIndex);
    const pane = this.pane(paneIndex);
    const ts = this._chart.timeScale;
    if (frame === null || pane === null || ts === undefined || points.length === 0) return null;
    const px: ScreenPoint[] = [];
    for (const p of points) {
      const x = ts.indexToX(this._chart.dataLayer.timeToIndexFloat(p.time));
      const y = pane.priceToY(p.price);
      if (!Number.isFinite(x) || !Number.isFinite(y)) return null;
      px.push({ x, y });
    }
    const own = boundsOf(px);
    const box = toolBounds(d, px) ?? own;
    const cutX = cutInto(box.x0, box.x1, own.x0, own.x1, frame.width);
    const cutY = cutInto(box.y0, box.y1, own.y0, own.y1, frame.height);
    return this.pinPlot(d, px.map((p) => ({ x: cutX(p.x), y: cutY(p.y) })), frame);
  }

  /**
   * The inverse of `toViewport`: fractions back to time and price at the view
   * on screen, from where the drawing is painted, so it does not move.
   */
  public fromViewport(points: readonly ViewportPoint[], paneIndex: number, d: Drawing): DrawingPoint[] | null {
    const frame = this.plotFrame(paneIndex);
    const pane = this.pane(paneIndex);
    const ts = this._chart.timeScale;
    if (frame === null || pane === null || ts === undefined || points.length === 0) return null;
    const out: DrawingPoint[] = [];
    for (const p of placeViewportAnchors(d, points, frame.width, frame.height)) {
      const time = this._chart.dataLayer.indexToTimeFloat(ts.xToIndex(p.x));
      const price = pane.yToPrice(p.y);
      if (!Number.isFinite(time) || !Number.isFinite(price)) return null;
      out.push({ time, price });
    }
    return out;
  }

  /**
   * Anchors in plot px as the fractions a pinned drawing stores, moved first
   * so its box lies inside the plot. Every gesture ends here, so what is
   * stored is what is painted, and no drag can leave the box where the
   * pointer cannot reach it.
   */
  public pinPlot(d: Drawing, pts: readonly ScreenPoint[], frame: PlotRect): ViewportPoint[] {
    const fraction = (p: ScreenPoint): ViewportPoint => ({ x: p.x / frame.width, y: p.y / frame.height });
    return placeViewportAnchors(d, pts.map(fraction), frame.width, frame.height).map(fraction);
  }

  /**
   * Pinned anchors moved by a screen distance in media px, from where the
   * drawing is painted rather than from what it stores: a note the layer
   * holds in from a stored place off the plot (a host's value, a larger
   * chart) moves at once, with no dead travel before it starts.
   */
  public shiftPinned(d: Drawing, points: readonly ViewportPoint[], dxPx: number, dyPx: number, frame: PlotRect): ViewportPoint[] {
    const at = placeViewportAnchors(d, points, frame.width, frame.height);
    return this.pinPlot(d, at.map((p) => ({ x: p.x + dxPx, y: p.y + dyPx })), frame);
  }
}
