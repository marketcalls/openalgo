/**
 * Free-standing shapes an indicator paints in its pane (ARCHITECTURE.md §8):
 * lines, boxes, labels and polylines anchored to time and price.
 *
 * One primitive holds the whole list rather than one primitive per shape. A
 * descriptor rebuilds its shapes on every recompute, so per-shape primitives
 * would mean attaching and detaching a dozen objects on every live tick, and
 * the pane would re-sort its z-order for each of them.
 *
 * Anchors are **times**, never logical indices: paging history in at the left
 * edge shifts every index, and a trendline pinned to an index would slide off
 * its pivots the moment it did.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from './primitive';
import type { IndicatorDrawing, DrawAnchor } from '../model/indicator-registry';
import type { PriceScale } from '../scale/price-scale';
import { roundRectPath, contrastText } from '../render/pill';
import { dashFor } from '../render/line';
import { hasTextStyle, textFont, validateTextStyle } from '../render/text-style';

type Caption = Extract<IndicatorDrawing, { kind: 'label' | 'box' }>;

/** A drawn label or box the pointer can rest on, in media px. */
interface HitRect {
  id: string;
  tooltip?: string | undefined;
  x: number;
  y: number;
  w: number;
  h: number;
  clipped?: boolean;
}

/** What a plate occupies once drawn, in device px, so a hit rect can be kept. */
interface PlateRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

type ScreenPoint = [number, number];
type CubicSegment = [number, number, number, number, number, number];

function smoothPath(xs: number[], ys: number[], closed: boolean): { points: ScreenPoint[]; segments: CubicSegment[] } | null {
  // xs and ys hold one entry per point, and every index into `points` below is
  // taken inside its length or wrapped modulo it.
  const points: ScreenPoint[] = [];
  for (let i = 0; i < xs.length; i++) {
    const previous = points[points.length - 1];
    if (!previous || previous[0] !== xs[i] || previous[1] !== ys[i]) points.push([xs[i]!, ys[i]!]);
  }
  if (closed && points.length > 1 && points[0]![0] === points[points.length - 1]![0]
    && points[0]![1] === points[points.length - 1]![1]) points.pop();
  if (points.length < 2) return null;
  const segments: CubicSegment[] = [];
  if (points.length > 2) {
    const n = points.length;
    for (let i = 0; i < (closed ? n : n - 1); i++) {
      const a = points[i]!, b = points[(i + 1) % n]!;
      const before = points[closed ? (i + n - 1) % n : Math.max(0, i - 1)]!;
      const after = points[closed ? (i + 2) % n : Math.min(n - 1, i + 2)]!;
      // Cubic controls take one third of the half-chord tangent. Repeated open
      // endpoints avoid inventing an extra anchor; closed paths wrap the seam.
      const segment: CubicSegment = [
        a[0] + (b[0] - before[0]) / 6, a[1] + (b[1] - before[1]) / 6,
        b[0] - (after[0] - a[0]) / 6, b[1] - (after[1] - a[1]) / 6, b[0], b[1],
      ];
      if (!segment.every(Number.isFinite)) return null;
      segments.push(segment);
    }
  }
  return { points, segments };
}

/**
 * A rounded plate with one row per `\n`-separated line, sized to the widest.
 * `x` is the plate's left, centre or right edge per `align`; `y` its middle.
 */
function drawPlate(
  ctx: CanvasRenderingContext2D,
  d: number,
  x: number,
  y: number,
  text: string,
  bg: string,
  textColor: string | undefined,
  align: 'left' | 'center' | 'right',
  style?: Caption,
  clip?: { w: number; h: number },
): PlateRect | null {
  const size = (style?.fontSize ?? 11) * d;
  if (!Number.isFinite(size) || size <= 0) return null;
  ctx.font = textFont(style, size, 'ui-sans-serif, system-ui, sans-serif');
  ctx.textBaseline = 'middle';
  ctx.textAlign = style?.textAlign ?? 'left';
  const lines = text.split('\n');
  let textW = 0;
  for (const line of lines) textW = Math.max(textW, ctx.measureText(line).width);
  const padX = 5 * d;
  const padY = 3 * d;
  const lh = size * 1.35;
  const w = textW + padX * 2;
  const h = lh * lines.length + padY * 2;
  const bx = align === 'center' ? x - w / 2 : align === 'right' ? x - w : x;
  const by = style?.verticalAlign === 'top' ? y : style?.verticalAlign === 'bottom' ? y - h : y - h / 2;
  if (clip) {
    if (![bx, by, w, h].every(Number.isFinite) || bx + w < 0 || bx > clip.w || by + h < 0 || by > clip.h) return null;
    ctx.save(); ctx.beginPath(); ctx.rect(0, 0, clip.w, clip.h); ctx.clip();
  }
  ctx.beginPath();
  roundRectPath(ctx, bx, by, w, h, 3 * d);
  ctx.fillStyle = bg;
  ctx.fill();
  ctx.fillStyle = textColor ?? contrastText(bg);
  const tx = style?.textAlign === 'center' ? bx + w / 2 : style?.textAlign === 'right' ? bx + w - padX : bx + padX;
  for (let i = 0; i < lines.length; i++) ctx.fillText(lines[i]!, tx, by + padY + lh * (i + 0.5));
  if (clip) ctx.restore();
  return { x: bx, y: by, w, h };
}

export class IndicatorDrawings implements IPrimitive {
  private _items: readonly IndicatorDrawing[] = [];
  private _host: PrimitiveHost | null = null;
  private _visible = true;
  private readonly _priceScale: ((rc: PrimitiveRenderContext) => PriceScale | null | undefined) | undefined;
  /**
   * The labels and boxes that carry an id or a tooltip, where the last frame
   * put them. Only those are hit-testable: a bare trendline stays under the
   * pointer as pure ink, so hovering a busy study does not light up a cursor
   * on every ray it drew.
   */
  private _hits: HitRect[] = [];

  /**
   * @param priceScale The scale prices are measured on, read on every frame
   * from that frame's context. Without it, or when it returns nothing, the
   * layer uses the scale its pane binds it to. Shapes quoted in the pane's own
   * price units, the way a study's price-pane shapes are, return
   * `rc.readoutPriceScale`: they then go wherever the candles' axis goes, and
   * the layer never holds an axis of its own or pins one in place.
   */
  public constructor(priceScale?: (rc: PrimitiveRenderContext) => PriceScale | null | undefined) {
    this._priceScale = priceScale;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; this._hits = []; }
  /** Over the series, under the crosshair: these are annotations on the data. */
  public zOrder(): ZOrder { return 'normal'; }
  /**
   * A shape is drawn where the descriptor put it and never argues with the
   * scale. A projection reaching far above the data would otherwise squash the
   * study it annotates into a band a few pixels tall.
   */
  public autoscaleInfo(): null { return null; }

  public setItems(items: readonly IndicatorDrawing[]): void {
    for (const item of items) if (item.kind === 'label' || item.kind === 'box') {
      validateTextStyle(item);
      if (item.verticalAlign !== undefined && !['top', 'middle', 'bottom'].includes(item.verticalAlign)) {
        throw new TypeError('Drawing verticalAlign must be top, middle or bottom');
      }
      if (item.kind === 'box' && item.align !== undefined && !['left', 'center', 'right'].includes(item.align)) {
        throw new TypeError('Box align must be left, center or right');
      }
    }
    this._items = items;
    this._hits = [];
    this._host?.requestUpdate();
  }

  public setVisible(on: boolean): void {
    this._visible = on;
    this._hits = [];
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    this._hits = [];
    if (!this._visible || this._items.length === 0) return;
    const d = rc.dpr;
    const w = rc.plotWidth * d;
    const h = rc.plotHeight * d;
    const ink = rc.theme.axisText;
    // Plates are not measured until they are drawn, so they cull on their
    // anchor with a margin wide enough to cover any label anyone will write.
    const m = 200 * d;
    const x = (a: DrawAnchor): number => rc.timeScale.indexToX(rc.dataLayer.timeToIndexFloat(a.time)) * d;
    const scale = this._priceScale?.(rc) ?? rc.priceScale;
    const y = (a: DrawAnchor): number => scale.priceToY(a.price) * d;
    // A shape entirely off-pane costs a path and a fill for nothing, and a
    // descriptor that marks every pivot in 50k bars leaves most of them there.
    const offPane = (x0: number, y0: number, x1: number, y1: number): boolean =>
      Math.max(x0, x1) < 0 || Math.min(x0, x1) > w || Math.max(y0, y1) < 0 || Math.min(y0, y1) > h;

    ctx.save();
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';

    for (const item of this._items) {
      if (item.kind === 'label') {
        const styled = hasTextStyle(item) || item.verticalAlign !== undefined;
        const px = x(item.at);
        const py = y(item.at);
        if (!styled && (px < -m || px > w + m || py < -m || py > h + m)) continue;
        const rect = drawPlate(ctx, d, px, py, item.text, item.color ?? ink, item.textColor, item.align ?? 'center', item, styled ? { w, h } : undefined);
        if (rect) this._recordHit(item, rect, d, styled ? { w, h } : undefined);
        continue;
      }

      const color = item.color ?? ink;
      ctx.lineWidth = Math.max(1, Math.round((item.lineWidth ?? 1) * d));

      if (item.kind === 'polyline') {
        const pts = item.points;
        if (pts.length < 2) continue;
        const xs = new Array<number>(pts.length);
        const ys = new Array<number>(pts.length);
        let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
        let valid = true;
        // Every loop here stays inside the points, and xs and ys are sized to them.
        for (let i = 0; i < pts.length; i++) {
          if (!Number.isFinite(pts[i]!.time) || !Number.isFinite(pts[i]!.price)) { valid = false; break; }
          const px = x(pts[i]!);
          const py = y(pts[i]!);
          if (!Number.isFinite(px) || !Number.isFinite(py)) { valid = false; break; }
          xs[i] = px; ys[i] = py;
          if (px < x0) x0 = px;
          if (px > x1) x1 = px;
          if (py < y0) y0 = py;
          if (py > y1) y1 = py;
        }
        if (!valid) continue;
        const smooth = item.curve === 'smooth';
        const path = smooth ? smoothPath(xs, ys, item.closed === true) : null;
        if (smooth && path === null) continue;
        if (path) {
          for (const segment of path.segments) {
            for (let i = 0; i < segment.length; i += 2) { // a segment is three x, y pairs
              x0 = Math.min(x0, segment[i]!); x1 = Math.max(x1, segment[i]!);
              y0 = Math.min(y0, segment[i + 1]!); y1 = Math.max(y1, segment[i + 1]!);
            }
          }
        }
        const margin = smooth ? ctx.lineWidth / 2 : 0;
        if (offPane(x0 - margin, y0 - margin, x1 + margin, y1 + margin)) continue;
        if (smooth) {
          // Normal primitives paint after axes, so their layer does not supply
          // a plot clip. Interpolated overshoot must stay inside the data area.
          ctx.save();
          ctx.beginPath(); ctx.rect(0, 0, w, h); ctx.clip();
        }
        ctx.beginPath();
        ctx.moveTo(xs[0]!, ys[0]!);
        if (path && path.segments.length > 0) {
          for (const segment of path.segments) ctx.bezierCurveTo(...segment);
        } else if (path) {
          ctx.lineTo(path.points[1]![0], path.points[1]![1]); // a path has two points at least
        } else {
          for (let i = 1; i < pts.length; i++) ctx.lineTo(xs[i]!, ys[i]!);
        }
        if (item.closed === true) ctx.closePath();
        if (item.fillColor !== undefined) {
          ctx.globalAlpha = item.opacity ?? 0.12;
          ctx.fillStyle = item.fillColor;
          ctx.fill();
          ctx.globalAlpha = 1;
        }
        ctx.setLineDash([]);
        ctx.strokeStyle = color;
        ctx.stroke();
        if (smooth) ctx.restore();
        continue;
      }

      let ax = x(item.from);
      let ay = y(item.from);
      let bx = x(item.to);
      let by = y(item.to);

      if (item.kind === 'box') {
        const styled = hasTextStyle(item) || item.align !== undefined || item.verticalAlign !== undefined;
        if (!styled && offPane(ax, ay, bx, by)) continue;
        if (styled && ![ax, ay, bx, by].every(Number.isFinite)) continue;
        const rx = Math.min(ax, bx);
        const ry = Math.min(ay, by);
        const rw = Math.abs(bx - ax);
        const rh = Math.abs(by - ay);
        if (styled && (!Number.isFinite(rw) || !Number.isFinite(rh))) continue;
        if (styled) { ctx.save(); ctx.beginPath(); ctx.rect(0, 0, w, h); ctx.clip(); }
        if (item.fillColor !== undefined) {
          ctx.globalAlpha = item.opacity ?? 0.12;
          ctx.fillStyle = item.fillColor;
          ctx.fillRect(rx, ry, rw, rh);
          ctx.globalAlpha = 1;
        }
        ctx.setLineDash([]);
        ctx.strokeStyle = color;
        ctx.strokeRect(rx, ry, rw, rh);
        this._recordHit(item, { x: rx, y: ry, w: rw, h: rh }, d, styled ? { w, h } : undefined);
        if (item.text !== undefined && item.text !== '') {
          const cx = item.align === 'left' ? rx : item.align === 'right' ? rx + rw : rx + rw / 2;
          const cy = item.verticalAlign === 'top' ? ry : item.verticalAlign === 'bottom' ? ry + rh : ry + rh / 2;
          drawPlate(ctx, d, cx, cy, item.text, color, item.textColor, item.align ?? 'center', item, styled ? { w, h } : undefined);
        }
        if (styled) ctx.restore();
        continue;
      }

      if (item.extendLeft === true || item.extendRight === true) {
        // A ray keeps its own slope out to the pane edge, so each end is solved
        // for x rather than clamped: clamping would flatten every sloped line
        // into the horizontal one nobody asked for.
        const dx = bx - ax;
        if (dx === 0) {
          ay = 0; // a vertical line has no left or right end; either flag spans the pane
          by = h;
        } else {
          const slope = (by - ay) / dx;
          const aIsLeft = ax <= bx;
          if (item.extendLeft === true) {
            if (aIsLeft) { ay -= slope * ax; ax = 0; } else { by -= slope * bx; bx = 0; }
          }
          if (item.extendRight === true) {
            if (aIsLeft) { by += slope * (w - bx); bx = w; } else { ay += slope * (w - ax); ax = w; }
          }
        }
      }
      if (offPane(ax, ay, bx, by)) continue;
      ctx.setLineDash(dashFor(item.lineStyle, d));
      ctx.strokeStyle = color;
      ctx.beginPath();
      ctx.moveTo(ax, ay);
      ctx.lineTo(bx, by);
      ctx.stroke();
    }

    ctx.setLineDash([]);
    this._drawTooltip(ctx, rc, d, w, h, ink);
    ctx.restore();
  }

  /** Keep a label's or box's rect when it has something to say on hover or click. */
  private _recordHit(item: { id?: string; tooltip?: string }, rect: PlateRect, d: number, clip?: { w: number; h: number }): void {
    const id = item.id ?? item.tooltip;
    if (id === undefined) return;
    const x = clip ? Math.max(0, rect.x) : rect.x, y = clip ? Math.max(0, rect.y) : rect.y;
    const right = clip ? Math.min(clip.w, rect.x + rect.w) : rect.x + rect.w;
    const bottom = clip ? Math.min(clip.h, rect.y + rect.h) : rect.y + rect.h;
    if (clip && (right <= x || bottom <= y)) return;
    this._hits.push({ id, tooltip: item.tooltip, x: x / d, y: y / d, w: (right - x) / d, h: (bottom - y) / d, clipped: clip !== undefined });
  }

  /**
   * The hovered shape's tooltip, as a plate clear of the shape: above it when
   * there is room, below it otherwise. Drawn last so it sits over everything
   * else in the layer, and only while the chart reports the pointer on it, so
   * it costs nothing on a frame with nothing hovered.
   */
  private _drawTooltip(
    ctx: CanvasRenderingContext2D,
    rc: PrimitiveRenderContext,
    d: number,
    w: number,
    h: number,
    ink: string,
  ): void {
    const id = rc.hoverId;
    if (id === null || id === undefined) return;
    const hit = this._hits.find((r) => r.id === id && r.tooltip !== undefined);
    if (hit?.tooltip === undefined) return;
    const gap = 8 * d;
    const plateH = 11 * d * 1.35 * hit.tooltip.split('\n').length + 6 * d;
    const above = hit.y * d - gap - plateH >= 0;
    const cy = above ? hit.y * d - gap - plateH / 2 : (hit.y + hit.h) * d + gap + plateH / 2;
    const cx = Math.min(Math.max((hit.x + hit.w / 2) * d, 0), w);
    if (cy < -plateH || cy > h + plateH) return;
    drawPlate(ctx, d, cx, cy, hit.tooltip, ink, undefined, 'center', undefined, hit.clipped ? { w, h } : undefined);
  }

  public hitTest(x: number, y: number): PrimitiveHit | null {
    // Later items paint over earlier ones, so the last rect under the pointer
    // is the one the user sees.
    for (let i = this._hits.length - 1; i >= 0; i--) {
      const r = this._hits[i]!;
      if (x >= r.x && x <= r.x + r.w && y >= r.y && y <= r.y + r.h) {
        return { externalId: r.id, zOrder: 'normal', distance: 0, cursor: r.tooltip === undefined ? 'pointer' : 'default' };
      }
    }
    return null;
  }
}
