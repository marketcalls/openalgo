/**
 * The top drawing layer of a pane, with what the controller's gestures need
 * of it besides painting drawings: the render context the chart last painted
 * or hit-tested the pane with, which a gesture measures drawings against the
 * same way a click is measured, and what the gestures show over every drawing
 * on the overlay tier: the box a Ctrl+drag selects with, and the ring that
 * marks the eraser's reach at the pointer.
 *
 * The context is kept rather than rebuilt from the chart because it is the
 * exact one the pane hands its primitives: the bound scale, the plot size and
 * the readout scale a moved axis leaves. Its scales are the chart's live
 * objects, so one kept from an earlier frame maps as the chart maps now.
 */
import type { PrimitiveHit, PrimitiveHost, PrimitiveRenderContext } from 'openalgo-charts';
import type { ScreenPoint } from './types';
import { DrawingLayer } from './layer';

/** A rectangle on a pane's plot, in plot-relative media px, corners in any order. */
export interface GestureBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}

export class GestureLayer extends DrawingLayer {
  private _overlayHost: PrimitiveHost | null = null;
  private _rc: PrimitiveRenderContext | null = null;
  private _box: GestureBox | null = null;
  private _ring: { at: ScreenPoint; radius: number } | null = null;

  public constructor() {
    super('top');
  }

  public override attached(host: PrimitiveHost): void {
    super.attached(host);
    this._overlayHost = host;
  }

  public override detached(): void {
    super.detached();
    this._overlayHost = null;
  }

  public override draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    super.draw(ctx, rc);
    this._rc = rc;
    if (this._box !== null) this._drawBox(ctx, rc, this._box);
    if (this._ring !== null) this._drawRing(ctx, rc, this._ring.at, this._ring.radius);
  }

  public override hitTest(x: number, y: number, rc: PrimitiveRenderContext): PrimitiveHit | null {
    this._rc = rc;
    return super.hitTest(x, y, rc);
  }

  /**
   * The context drawings on this pane are measured in, as the layer paints
   * and hit-tests them (on the readout scale when a host moved the axis), or
   * null while the chart has neither painted nor hit-tested the pane.
   */
  public context(): PrimitiveRenderContext | null {
    const rc = this._rc;
    return rc === null || !rc.readoutPriceScale ? rc : { ...rc, priceScale: rc.readoutPriceScale };
  }

  /** The selection box to paint, or null for none. */
  public setBox(box: GestureBox | null): void {
    const was = this._box;
    if (box === null ? was === null : was !== null && was.x0 === box.x0 && was.y0 === box.y0 && was.x1 === box.x1 && was.y1 === box.y1) return;
    this._box = box === null ? null : { x0: box.x0, y0: box.y0, x1: box.x1, y1: box.y1 };
    this._overlayHost?.requestUpdate();
  }

  public box(): GestureBox | null {
    return this._box === null ? null : { ...this._box };
  }

  /** The eraser's ring at `at` (plot media px) with its reach, or null for none. */
  public setRing(at: ScreenPoint | null, radius = 0): void {
    const was = this._ring;
    if (at === null ? was === null : was !== null && was.at.x === at.x && was.at.y === at.y && was.radius === radius) return;
    this._ring = at === null ? null : { at: { x: at.x, y: at.y }, radius };
    this._overlayHost?.requestUpdate();
  }

  /** A hollow ring in the axis text colour, as the magnet's ring is. */
  private _drawRing(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, at: ScreenPoint, radius: number): void {
    const d = rc.dpr;
    ctx.save();
    ctx.setLineDash([]);
    ctx.globalAlpha = 0.9;
    ctx.lineWidth = Math.max(1, Math.round(d));
    ctx.strokeStyle = rc.theme.axisText;
    ctx.beginPath();
    ctx.arc(at.x * d, at.y * d, radius * d, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  /**
   * A translucent box with a thin solid rim in the drawing colour of the
   * theme, clipped to the plot: solid so it never reads as the crosshair,
   * whose lines are dashed and grey.
   */
  private _drawBox(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext, box: GestureBox): void {
    const d = rc.dpr;
    const x = Math.round(Math.min(box.x0, box.x1) * d) + 0.5;
    const y = Math.round(Math.min(box.y0, box.y1) * d) + 0.5;
    const w = Math.round(Math.abs(box.x1 - box.x0) * d);
    const h = Math.round(Math.abs(box.y1 - box.y0) * d);
    const color = rc.theme.lineColor;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, Math.round(rc.plotWidth * d), Math.round(rc.plotHeight * d));
    ctx.clip();
    ctx.globalAlpha = 0.12;
    ctx.fillStyle = color;
    ctx.fillRect(x, y, w, h);
    ctx.globalAlpha = 0.9;
    ctx.strokeStyle = color;
    ctx.lineWidth = Math.max(1, Math.round(d));
    ctx.setLineDash([]);
    ctx.strokeRect(x, y, w, h);
    ctx.restore();
  }
}
