/**
 * A `DrawingLayer` renders the drawings of one pane and answers the chart's
 * hit-test. Anchors live in `{ time, price }`, so the layer maps them through
 * the *fractional* index helpers: the gapless axis means an anchor can sit
 * between bars (inside a collapsed weekend) or past the last one (a forward
 * projection), and whole-index lookups have nothing to return there.
 *
 * Each pane carries a `bottom` layer for drawings with a negative `zIndex`
 * (under the series), a `top` one for the rest, and a `series` layer for each
 * series-band entry a drawing is placed above (`stackAbove`), which the chart
 * paints right after that entry's series. The top one takes over handles and
 * hit-testing for the others through `setBelow`, so a shape parked under the
 * candles still shows its grab handles above them and a click lands on
 * whatever the eye sees on top: the top layer's bodies first, then each layer
 * under it in the order they paint, front to back.
 *
 * Hit ids are `draw:<id>` for the body and `draw:<id>#<n>` for anchor `n`, so
 * the controller can tell "move the whole shape" from "move this handle".
 *
 * A viewport drawing (`space: 'viewport'`) skips the time and price mapping:
 * its anchors are fractions of this pane's plot and scale by the plot size in
 * the render context, which is all that pan and zoom never touch. The one step
 * added is keeping its box inside the plot. Everything after the projection
 * (paint, handles, hit-testing) is shared, so the two spaces cannot drift
 * apart in how they are grabbed.
 *
 * The hover ring, the magnet ring and the hover handles are all overlay
 * state: they change on every pointer move, so they must only ever cost the
 * top canvas. The layer that paints them is the one whose `requestUpdate`
 * the chart maps to the cursor tier, which is why the bottom layer of a pair
 * stores that state and asks for nothing.
 *
 * A hit test asks a tool for its distance only where the drawing can be: each
 * layer keeps a box per drawing (src/draw/hit-index.ts) and a pointer outside
 * it costs four comparisons. The answer is the one a test of every drawing
 * gives, because a box covers every point its tool would report as a hit.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, PrimitiveHit, ZOrder } from 'openalgo-charts';
import type { Drawing, DrawingPoint, ScreenPoint, ViewportPoint } from './types';
import { getDrawingTool, hasDrawingTool } from './registry';
import { withDrawingTextMetrics } from './text-metrics';
import { anchorCount, containInPlot, viewportToPlot, type PlotBox } from './viewport';
import { boundsOf } from './geometry';
import { projectPoint } from './tool-paint';
import { createDrawingHitIndex, EVERYWHERE, NOWHERE, inHitBox, spanOf, toolHitBox, type HitBox } from './hit-index';

/** Grab radius for a shape, in media px. */
const GRAB = 6;
/** Anchor handle radius, in media px. */
const HANDLE = 5;
/** Radius of the magnet ring, in media px. */
const SNAP_RING = 5.5;
/**
 * A fingertip covers far more than a mouse pointer, and it hides what it
 * touches. Doubling the targets is what keeps a handle grabbable on a phone
 * without a visible change on a desktop.
 */
const TOUCH_SCALE = 2;

/**
 * Where a layer paints: under the series, in the series band (placed above an
 * entry by the controller, and over the series while it is not), or on top.
 */
export type DrawingLayerOrder = 'bottom' | 'series' | 'top';

/** The pointer kinds the layer sizes its targets for. */
export type DrawingPointerKind = 'mouse' | 'touch' | 'pen';

/** A `zIndex` a host forgot, or corrupted, paints with the series band. */
const zOf = (d: Drawing): number => (Number.isFinite(d.zIndex) ? d.zIndex : 0);

/** Read-only to the user (`policy.editable` false): selectable, never grabbed. */
export const readOnly = (d: Drawing | undefined): boolean => d?.policy?.editable === false;

/**
 * Whether the layer can run this drawing's tool at all. A viewport drawing
 * whose tool never declared viewport support (a plugin tool, a hand-edited
 * save) would hand the tool an empty `drawing.points` it may index into, so
 * it is kept in the model and left unpainted and unhittable instead.
 */
function runnable(d: Drawing): boolean {
  return hasDrawingTool(d.tool) && (d.space !== 'viewport' || getDrawingTool(d.tool).viewport === true);
}

/**
 * Where a viewport drawing with anchors `points` sits on a plot of `width` by
 * `height`, in plot-relative media px: at those fractions, moved as a whole as
 * far as it takes to keep the tool's box (`DrawingTool.bounds`) inside the
 * plot. The fractions scale with the plot and a note's type does not, so it
 * is the box, measured here in pixels, that decides what stays on screen at
 * any size. What the layer paints and hit-tests, and what the controller
 * moves from, so a drag starts where the eye sees the drawing.
 */
export function placeViewportAnchors(d: Drawing, points: readonly ViewportPoint[], width: number, height: number): ScreenPoint[] {
  const pts = viewportToPlot(points, width, height);
  if (pts.length === 0) return pts;
  return containInPlot(pts, toolBounds(d, pts) ?? boundsOf(pts), width, height);
}

/**
 * The box a drawing's tool declares at `pts` (`DrawingTool.bounds`), asked
 * only of a complete anchor set, as `draw` and `distance` are. A box with one
 * corner (a hand-edited save, a host's patch) has no box of its own: it is
 * kept and not painted, and its anchors' own bounds place it.
 */
export function toolBounds(d: Drawing, pts: readonly ScreenPoint[]): PlotBox | undefined {
  const tool = hasDrawingTool(d.tool) ? getDrawingTool(d.tool) : undefined;
  return tool !== undefined && pts.length >= Math.max(1, tool.points) ? tool.bounds?.(pts, d) : undefined;
}

/**
 * A drawing's anchors in plot-relative media px: time and price through the
 * pane's scales, or viewport fractions through the plot size.
 */
export function projectAnchors(rc: PrimitiveRenderContext, d: Drawing): ScreenPoint[] {
  if (d.space === 'viewport') return placeViewportAnchors(d, d.viewportPoints ?? [], rc.plotWidth, rc.plotHeight);
  return d.points.map((p) => projectPoint(rc, p));
}

/**
 * Paint order: by `zIndex`, ties by array position. `Array.prototype.sort` is
 * stable, which is what makes the tie rule hold without a second key.
 */
export function sortByZIndex(drawings: readonly Drawing[]): Drawing[] {
  return drawings.slice().sort((a, b) => zOf(a) - zOf(b));
}

/**
 * Which anchors get a grab handle. A freehand stroke carries one anchor per
 * sample, so handling all of them buries the ink under dozens of circles and
 * makes the shape itself impossible to grab: only the two ends mean anything,
 * which is what a brush shows elsewhere.
 */
function handleIndices(toolId: string, count: number): number[] {
  if (hasDrawingTool(toolId) && getDrawingTool(toolId).freehand === true && count > 2) {
    return [0, count - 1];
  }
  return Array.from({ length: count }, (_, i) => i);
}

export class DrawingLayer implements IPrimitive {
  private readonly _order: DrawingLayerOrder;
  /** In paint order. */
  private _drawings: Drawing[] = [];
  private _host: PrimitiveHost | null = null;
  private _selected: string[] = [];
  /** The drawing under the pointer, whether or not it is selected. */
  private _hovered: string | null = null;
  /** Where the next click will land while the magnet is pulling it. */
  private _snap: DrawingPoint | null = null;
  /** Anchors of the in-progress drawing, plus the live cursor point. */
  private _preview: Drawing | null = null;
  /** The layers under this one, front to back, whose handles and hits this layer answers for. */
  private _below: DrawingLayer[] = [];
  /** The layer that has taken over this one's handles and hit-testing. */
  private _above: DrawingLayer | null = null;
  /** Sizes grab targets for the device last seen. */
  private _touch = false;
  /** Hit boxes per drawing, kept while nothing that places them changes. */
  private readonly _index = createDrawingHitIndex();
  /** Paint positions of the selected, unlocked, shown drawings, or null until asked again. */
  private _selectedAt: number[] | null = null;

  public constructor(order: DrawingLayerOrder = 'top') {
    this._order = order;
  }

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  // A series layer paints on the base canvas, and over the series while the
  // entry it is placed above is not on its pane.
  public zOrder(): ZOrder { return this._order === 'series' ? 'normal' : this._order; }
  /** Drawings overlay the price range; they never drive it. */
  public autoscaleInfo(): null { return null; }

  /**
   * The drawings this layer paints and answers for. The hit boxes kept for
   * the previous list all go, so a drawing edited in place must be handed
   * over again, as the controller does after every edit, for a hover to see
   * where it now is.
   */
  public setDrawings(drawings: readonly Drawing[]): void {
    this._drawings = sortByZIndex(drawings);
    this._index.reset(this._drawings);
    this._selectedAt = null;
    this._host?.requestUpdate();
  }

  public setSelected(ids: readonly string[]): void {
    if (ids.length === this._selected.length && ids.every((id, i) => id === this._selected[i])) return;
    this._selected = ids.slice();
    this._selectedAt = null;
    this._host?.requestUpdate();
  }

  /**
   * The drawing under the pointer. Its handles paint at a lighter weight than
   * a selection's, as the hint that it can be grabbed. Repaints only from the
   * layer that paints handles: the adopted bottom layer keeps the id for its
   * own bookkeeping and asks for nothing, since its repaint costs the series.
   */
  public setHovered(id: string | null): void {
    if (id === this._hovered) return;
    this._hovered = id;
    this._requestOverlay();
  }

  public hovered(): string | null {
    return this._hovered;
  }

  /**
   * The point the magnet will snap the next click to, or null when it is not
   * pulling. Painted as a hollow ring so the user sees the anchor land before
   * committing to it.
   */
  public setSnapPoint(point: DrawingPoint | null): void {
    if (point === null ? this._snap === null : this._snap !== null && this._snap.time === point.time && this._snap.price === point.price) return;
    this._snap = point === null ? null : { time: point.time, price: point.price };
    this._requestOverlay();
  }

  public snapPoint(): DrawingPoint | null {
    return this._snap;
  }

  /**
   * Size the grab targets for the device in use. Touch doubles the radii; a
   * mouse or a pen keeps the desktop sizes. The render context may carry the
   * same fact (`pointerType`), and when it does that wins per call, so a
   * first touch on a fresh chart is already sized right.
   */
  public setPointerType(kind: DrawingPointerKind | null | undefined): void {
    this._touch = kind === 'touch';
  }

  public setPreview(drawing: Drawing | null): void {
    this._preview = drawing;
    this._host?.requestUpdate();
  }

  /**
   * Adopt the layers under this one, front to back: the order they paint in,
   * reversed. From then on this layer paints the handles of all of them and
   * answers `hitTest` for all of them, and the adopted layers paint bodies
   * only. Handles have to live up here: a selected drawing under the series
   * would otherwise have its handles buried under the candles, and a handle
   * you cannot see is a handle you cannot grab. Pass null to release.
   */
  public setBelow(layer: DrawingLayer | readonly DrawingLayer[] | null): void {
    const next = layer === null ? [] : Array.isArray(layer) ? [...layer as readonly DrawingLayer[]] : [layer as DrawingLayer];
    if (next.length === this._below.length && next.every((item, i) => item === this._below[i])) return;
    for (const old of this._below) if (!next.includes(old)) { old._above = null; old._host?.requestUpdate(); }
    this._below = next;
    for (const item of next) {
      if (item._above !== null && item._above !== this) item._above._below = item._above._below.filter(other => other !== item);
      item._above = this;
      item._host?.requestUpdate();
    }
    this._host?.requestUpdate();
  }

  /** Repaint for overlay-only state, from the layer that paints it. */
  private _requestOverlay(): void {
    if (this._above !== null) return;
    this._host?.requestUpdate();
  }

  /** Whether targets are sized for a fingertip on this call. */
  private _isTouch(rc: PrimitiveRenderContext): boolean {
    const kind = (rc as { pointerType?: unknown }).pointerType;
    if (kind === 'touch') return true;
    if (kind === 'mouse' || kind === 'pen') return false;
    return this._touch;
  }

  private _grabRadius(rc: PrimitiveRenderContext): number {
    return this._isTouch(rc) ? GRAB * TOUCH_SCALE : GRAB;
  }

  private _handleRadius(rc: PrimitiveRenderContext): number {
    return this._isTouch(rc) ? HANDLE * TOUCH_SCALE : HANDLE;
  }

  private _points(rc: PrimitiveRenderContext, d: Drawing): ScreenPoint[] {
    return projectAnchors(rc, d);
  }

  /** Selected, unlocked drawings of this layer, in paint order. */
  private _handled(): Drawing[] {
    if (this._selected.length === 0) return [];
    const sel = new Set(this._selected);
    return this._drawings.filter((d) => sel.has(d.id) && d.locked !== true && d.visible !== false && runnable(d));
  }

  /**
   * The hovered drawing of this layer, when it is one that could be grabbed
   * and is not already showing selection handles.
   */
  private _hoverHandled(): Drawing | null {
    const id = this._hovered;
    if (id === null || this._selected.includes(id)) return null;
    const d = this._drawings.find((x) => x.id === id);
    return d === undefined || d.locked === true || d.visible === false || readOnly(d) || !runnable(d) ? null : d;
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    // Top primitives share a canvas with axis labels and cannot rely on the
    // series clip. Keep drawing bodies, previews and handles inside this pane.
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, Math.round(rc.plotWidth * rc.dpr), Math.round(rc.plotHeight * rc.dpr));
    ctx.clip();
    try { withDrawingTextMetrics(ctx, () => this._drawContent(ctx, this._drawingContext(rc))); } finally { ctx.restore(); }
  }

  private _drawingContext(rc: PrimitiveRenderContext): PrimitiveRenderContext {
    // Drawing input uses the chart's primary price readout. Rendering and hit
    // testing must use that same scale after a host moves it to the left axis.
    return rc.readoutPriceScale ? { ...rc, priceScale: rc.readoutPriceScale } : rc;
  }

  private _drawContent(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const selected = new Set(this._selected);
    const all = this._preview === null ? this._drawings : [...this._drawings, this._preview];
    for (const d of all) {
      if (d.visible === false || !runnable(d)) continue;
      const tool = getDrawingTool(d.tool);
      const media = this._points(rc, d);
      if (media.length === 0 || !media.every((p) => Number.isFinite(p.x) && Number.isFinite(p.y))) continue;
      if (anchorCount(d) < Math.max(1, tool.points)) {
        // A multi-point tool cannot paint its final geometry yet. Keep the
        // chosen anchors visible so each click has immediate feedback.
        if (d === this._preview) this._drawPlacementGuide(ctx, rc, media, d);
        continue;
      }

      const style = {
        color: d.style.color ?? rc.theme.lineColor,
        lineWidth: d.style.lineWidth ?? 1.5,
        ...d.style,
      };
      const dpr = rc.dpr;
      ctx.save();
      if (d === this._preview) ctx.globalAlpha = 0.7;
      tool.draw({
        ctx, rc, drawing: d, selected: selected.has(d.id),
        pts: media.map((p) => ({ x: p.x * dpr, y: p.y * dpr })),
        style: { ...style, color: style.color, lineWidth: style.lineWidth },
        formatPrice: (v) => rc.priceScale.format(v),
      });
      ctx.restore();
    }

    // Handles go on after every body so they are never painted over by a
    // later shape, and only the top layer paints them at all.
    if (this._above !== null) return;
    const layers: DrawingLayer[] = [this, ...this._below];
    for (const layer of layers) {
      const d = layer._hoverHandled();
      if (d !== null) this._drawHandles(ctx, rc, this._points(rc, d), d.tool, true);
    }
    // A selected read-only drawing shows its anchors at the hover weight: the
    // selection is visible, and nothing claims it can be grabbed.
    for (const layer of layers) {
      for (const d of layer._handled()) this._drawHandles(ctx, rc, this._points(rc, d), d.tool, readOnly(d));
    }
    if (this._snap !== null) this._drawSnapRing(ctx, rc, projectPoint(rc, this._snap));
  }

  private _drawPlacementGuide(
    ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, points: readonly ScreenPoint[], drawing: Drawing,
  ): void {
    const dpr = rc.dpr;
    ctx.save();
    ctx.globalAlpha *= 0.7;
    ctx.strokeStyle = drawing.style.color ?? rc.theme.lineColor;
    ctx.lineWidth = Math.max(1, (drawing.style.lineWidth ?? 1.5) * dpr);
    ctx.setLineDash([3 * dpr, 3 * dpr]);
    ctx.beginPath();
    // The caller skips a drawing with no anchor, and i is in range.
    ctx.moveTo(points[0]!.x * dpr, points[0]!.y * dpr);
    for (let i = 1; i < points.length; i++) ctx.lineTo(points[i]!.x * dpr, points[i]!.y * dpr);
    ctx.stroke();
    ctx.setLineDash([]);
    for (const point of points) {
      ctx.beginPath();
      ctx.arc(point.x * dpr, point.y * dpr, 3 * dpr, 0, Math.PI * 2);
      ctx.fillStyle = rc.theme.background;
      ctx.fill();
      ctx.stroke();
    }
    ctx.restore();
  }

  /**
   * Anchor handles. A hover shows them light (thin, translucent) as a hint
   * that the shape can be grabbed; a selection shows them at full weight.
   */
  private _drawHandles(
    ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, pts: readonly ScreenPoint[], toolId: string, light: boolean,
  ): void {
    const dpr = rc.dpr;
    ctx.save();
    ctx.setLineDash([]);
    ctx.lineWidth = Math.max(1, Math.round((light ? 1 : 1.5) * dpr));
    if (light) ctx.globalAlpha = 0.6;
    for (const i of handleIndices(toolId, pts.length)) {
      const p = pts[i]!; // a handle is one of the anchors
      ctx.beginPath();
      ctx.arc(p.x * dpr, p.y * dpr, HANDLE * dpr, 0, Math.PI * 2);
      ctx.fillStyle = rc.theme.background;
      ctx.fill();
      ctx.strokeStyle = rc.theme.lineColor;
      ctx.stroke();
    }
    ctx.restore();
  }

  /** The magnet ring: hollow, in the axis text colour, at the snap point. */
  private _drawSnapRing(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, p: ScreenPoint): void {
    if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return;
    const dpr = rc.dpr;
    ctx.save();
    ctx.setLineDash([]);
    ctx.globalAlpha = 0.9;
    ctx.lineWidth = Math.max(1, Math.round(1.5 * dpr));
    ctx.strokeStyle = rc.theme.axisText;
    ctx.beginPath();
    ctx.arc(p.x * dpr, p.y * dpr, SNAP_RING * dpr, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  public hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    rc = this._drawingContext(rc);
    // The layer above answers for this one, so two answers never compete.
    if (this._above !== null) return null;
    const layers = [this, ...this._below];
    for (const layer of layers) layer._index.check(rc, layer._drawings, layer._grabRadius(rc));

    // Handles of every selected drawing win: they sit on top of their own body
    // and grabbing an anchor must beat dragging the whole shape.
    for (const layer of layers) {
      const handle = layer._hitHandle(x, y, rc);
      if (handle !== null) return handle;
    }

    // Bodies on a layer beat those on every layer it paints over, whatever the
    // distance: what is painted on top is what the eye expects to grab. A body
    // on a lower layer names that layer, so the chart can rank it against a
    // series painted over it.
    const own = this._hitBody(x, y, rc);
    if (own !== null) return own;
    for (const layer of this._below) {
      const body = layer._hitBody(x, y, rc);
      if (body !== null) return { ...body, paintedBy: layer };
    }
    return null;
  }

  /**
   * Paint positions of the drawings `_handled` lists, less the registry check,
   * which is read live: a tool registered after the list was made makes its
   * drawings handled from then on, with no new list to say so.
   */
  private _selectedPositions(): number[] {
    if (this._selectedAt !== null) return this._selectedAt;
    const sel = new Set(this._selected), at: number[] = [];
    if (sel.size > 0) this._drawings.forEach((d, i) => { if (sel.has(d.id) && d.locked !== true && d.visible !== false) at.push(i); });
    return this._selectedAt = at;
  }

  /**
   * A drawing's body box: none for one that cannot be hit, everywhere for a
   * tool the box table does not know, else its tool's box at this radius.
   */
  private _measure(d: Drawing, rc: PrimitiveRenderContext, grab: number): HitBox {
    if (d.visible === false || d.locked === true || d.policy?.selectable === false || !runnable(d)) return NOWHERE;
    const tool = getDrawingTool(d.tool);
    if (anchorCount(d) < Math.max(1, tool.points)) return NOWHERE;
    return toolHitBox(tool, this._points(rc, d), d, rc, grab) ?? EVERYWHERE;
  }

  private _hitHandle(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    const radius = this._handleRadius(rc) + 2;
    for (const at of this._selectedPositions()) {
      const sel = this._drawings[at]!; // a paint position in this list
      if (!runnable(sel) || readOnly(sel)) continue;
      // Every handle is an anchor, so none is further out than the anchors reach.
      if (!inHitBox(this._index.anchors[at] ??= spanOf(this._points(rc, sel), radius), x, y)) continue;
      const pts = this._points(rc, sel);
      for (const i of handleIndices(sel.tool, pts.length)) {
        if (Math.hypot(x - pts[i]!.x, y - pts[i]!.y) <= radius) { // a handle is one of the anchors
          return {
            externalId: `draw:${sel.id}#${i}`,
            zOrder: 'top', distance: 0, cursor: 'grabbing', draggable: true,
          };
        }
      }
    }
    return null;
  }

  private _hitBody(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    const grab = this._grabRadius(rc);
    let best: { d: Drawing; distance: number } | null = null;
    // Reverse paint order, so the shape painted last wins a tie.
    for (let i = this._drawings.length - 1; i >= 0; i--) {
      const d = this._drawings[i]!; // i is in range
      if (!inHitBox(this._index.bodies[i] ??= this._measure(d, rc, grab), x, y)) continue;
      // An unselectable drawing is not there to the pointer: the click goes
      // through to whatever lies under it.
      if (d.visible === false || d.locked === true || d.policy?.selectable === false || !runnable(d)) continue;
      const tool = getDrawingTool(d.tool);
      if (anchorCount(d) < Math.max(1, tool.points)) continue;
      const dist = tool.distance(x, y, { pts: this._points(rc, d), drawing: d, rc });
      // A non-finite distance must miss, not hit: `NaN > GRAB` is false, so a
      // drawing with an unmappable anchor would otherwise swallow every click
      // on the pane.
      if (dist === null || !Number.isFinite(dist) || dist > grab) continue;
      if (best === null || dist < best.distance) best = { d, distance: dist };
      // No lower shape can beat zero; reverse paint order already wins its tie.
      if (dist === 0) break;
    }
    if (best === null) return null;
    // A read-only body selects on a click, and a press-drag on it pans the
    // chart as it would on empty space, rather than arming a drag that the
    // controller would refuse and leaving the chart frozen under the hand.
    const fixed = readOnly(best.d);
    return {
      externalId: `draw:${best.d.id}`,
      zOrder: 'top', distance: best.distance, cursor: fixed ? 'pointer' : 'move', draggable: !fixed,
    };
  }
}
