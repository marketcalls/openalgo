/**
 * The crosshair a linked chart shows for someone else's cursor.
 *
 * The engine's own crosshair is driven by the pointer that is inside that
 * chart, and there is exactly one of them per chart. A follower needs a second,
 * independent one, so it is a primitive rather than anything in the core: it
 * sits on the `top` z-order, which is the layer `Pane.paintTop` repaints for a
 * cursor move, so a linked crosshair costs the same overlay repaint the native
 * one does.
 *
 * Two deliberate differences from the native crosshair:
 *
 * - **Vertical line only.** The horizontal line marks a price, and the price
 *   under a cursor on another instrument is not a price on this one. On a grid
 *   of four symbols a mirrored price line would be a straight lie four times
 *   over. The vertical line marks an instant, and an instant is shared.
 * - **Drawn at reduced opacity**, in the follower's own crosshair colour, so it
 *   reads as a reflection of a cursor somewhere else rather than a second
 *   cursor in this chart.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from '../primitives/primitive';
import { drawCrosshair, resolveCrosshairStyle } from '../render/crosshair';
import { withAlpha } from '../render/pill';

/** Opacity of a linked crosshair relative to the pane's own crosshair colour. */
export const LINK_CROSSHAIR_ALPHA = 0.55;

export class LinkCrosshair implements IPrimitive {
  private _index: number | null = null;
  private _host: PrimitiveHost | null = null;

  public attached(host: PrimitiveHost): void {
    this._host = host;
  }

  public detached(): void {
    this._host = null;
  }

  public zOrder(): ZOrder {
    return 'top';
  }

  /** The follower's own logical index to draw at; null draws nothing. */
  public index(): number | null {
    return this._index;
  }

  /** Move (or clear) the line. Repaints only when something actually changed. */
  public setIndex(index: number | null): void {
    if (index === this._index) return;
    this._index = index;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const index = this._index;
    if (index === null) return;
    // No visible-range test here: `drawCrosshair` already declines an x outside
    // the plot, and a second bounds check against the same numbers would be a
    // branch no input can reach.
    const style = resolveCrosshairStyle(rc.theme, undefined, rc.dpr);
    drawCrosshair(
      ctx,
      rc.timeScale.indexToX(index),
      null, // no price line: see the note at the top of this file
      rc.plotWidth,
      rc.plotHeight,
      rc.dpr,
      withAlpha(style.color, LINK_CROSSHAIR_ALPHA),
      style.width,
      style.dash,
    );
  }
}
