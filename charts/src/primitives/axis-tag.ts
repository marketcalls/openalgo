/**
 * The price tag a price line or a price level puts in the price-axis column,
 * one routine so the level tags and the alert and order tags keep lining up
 * when tag geometry changes.
 *
 * A tag sits in the column of the scale the pane binds, on its side, shrinks
 * its text to fit a narrow column, and is held whole inside the plot when its
 * price runs near an edge. A context that gives no placement keeps the
 * right-edge tag every primitive has always drawn.
 */

/**
 * The slice of a primitive's render context a tag reads, which
 * `PrimitiveRenderContext` has. Declared here rather than imported so this
 * module stays out of the import loop the primitive types sit in.
 */
interface AxisTagContext {
  dpr: number;
  plotWidth: number;
  plotHeight: number;
  priceAxisWidth: number;
  priceAxisSide?: 'left' | 'right' | 'hidden';
  priceAxisOffset?: number;
}

/**
 * Draw `text` on a tag of `fill` at device-pixel `y`, `height` device pixels
 * tall, in the caller's 11px font. Nothing is drawn for a hidden or zero-width
 * axis.
 *
 * `clipAlways` confines a left-column tag to its column even when the chart
 * gives no offset, measuring the column from its edges; without it such a tag
 * is measured from the axis width and not clipped. Price levels clip always
 * and price lines do not, which is how each has always drawn.
 */
export function drawAxisTag(ctx: CanvasRenderingContext2D, rc: AxisTagContext, y: number, text: string,
  fill: string, ink: string, height: number, clipAlways: boolean): void {
  if (rc.priceAxisSide === 'hidden' || !(rc.priceAxisWidth > 0)) return;
  const dpr = rc.dpr;
  const padX = 6 * dpr;
  const left = rc.priceAxisSide === 'left';
  if (left || rc.priceAxisOffset !== undefined) {
    const offset = rc.priceAxisOffset ?? 0;
    const edge = Math.round(offset * dpr);
    const outer = Math.round((offset + (left ? -rc.priceAxisWidth : rc.priceAxisWidth)) * dpr);
    const clip = clipAlways || rc.priceAxisOffset !== undefined;
    const available = (clip ? Math.abs(outer - edge) : Math.round(rc.priceAxisWidth * dpr)) - 1;
    const maxY = rc.plotHeight * dpr;
    if (Number.isFinite(edge) && Number.isFinite(outer) && available > 0 && maxY >= height) {
      ctx.save();
      if (clip) {
        ctx.beginPath();
        ctx.rect(Math.min(edge, outer), 0, available + 1, maxY);
        ctx.clip();
      }
      const padding = Math.min(padX, available / 4), textWidth = ctx.measureText(text).width;
      const width = Math.min(available, textWidth + padding * 2);
      const x = left ? edge - 1 - width : edge + 1;
      const tagY = Math.max(height / 2, Math.min(maxY - height / 2, y));
      ctx.fillStyle = fill;
      ctx.fillRect(x, tagY - height / 2, width, height);
      ctx.fillStyle = ink;
      ctx.font = `500 ${11 * dpr * (textWidth > 0 ? Math.min(1, (width - padding * 2) / textWidth) : 1)}px system-ui, sans-serif`;
      ctx.fillText(text, x + padding, tagY);
      ctx.restore();
      ctx.font = `500 ${11 * dpr}px system-ui, sans-serif`;
    }
  } else {
    // Omitted placement retains the original synthetic-context geometry.
    const xEnd = Math.round(rc.plotWidth * dpr);
    ctx.fillStyle = fill;
    ctx.fillRect(xEnd + 1, y - height / 2, ctx.measureText(text).width + padX * 2, height);
    ctx.fillStyle = ink;
    ctx.fillText(text, xEnd + 1 + padX, y);
  }
}
