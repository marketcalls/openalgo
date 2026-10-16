/**
 * Per-bar pane shading: one full-height column behind the data, in whatever
 * colour the descriptor gave that bar.
 *
 * A regime study answers "which state is the market in", and that is a property
 * of the whole bar rather than of a price. As a column it reads at a glance and
 * costs the price scale nothing, where a plot would need a value to sit at and
 * would drag the pane's autoscale around with it.
 *
 * What makes it affordable is the work skipped: everything outside the visible
 * range is dropped before anything is painted, and adjacent bars sharing a
 * colour become one rect instead of one rect each. A year of two-state shading
 * is a handful of fills, not one per bar per frame.
 */
import type { IPrimitive, PrimitiveHost, PrimitiveRenderContext, ZOrder } from './primitive';
import type { Bar } from '../model/bar';

export class IndicatorBackground implements IPrimitive {
  private _colors: readonly (string | null)[] = [];
  /** Time of `_colors[0]`'s bar. See `draw` for why this is a time, not an index. */
  private _anchor = NaN;
  private _host: PrimitiveHost | null = null;
  private _visible = true;

  public attached(host: PrimitiveHost): void { this._host = host; }
  public detached(): void { this._host = null; }
  /** The same layer the bands use: behind the series, so the candles stay crisp. */
  public zOrder(): ZOrder { return 'bottom'; }
  /** Shading has no price of its own and must never widen the pane's range. */
  public autoscaleInfo(): null { return null; }

  public setColors(colors: readonly (string | null)[], bars: readonly Bar[]): void {
    this._colors = colors;
    this._anchor = bars.length > 0 ? bars[0]!.time : NaN;
    this._host?.requestUpdate();
  }

  public setVisible(on: boolean): void {
    this._visible = on;
    this._host?.requestUpdate();
  }

  public draw(ctx: CanvasRenderingContext2D, rc: PrimitiveRenderContext): void {
    const colors = this._colors;
    const n = colors.length;
    if (!this._visible || n === 0) return;

    // The colours are indexed off the descriptor's own bars, so the layer is
    // anchored to the first bar's TIME: a page of history arriving at the left
    // edge shifts every logical index, and until the next recompute the shading
    // would otherwise sit a page away from the bars it describes.
    const off = Math.round(rc.dataLayer.timeToIndexFloat(this._anchor));
    const vis = rc.timeScale.visibleRange();
    const lo = Math.max(0, Math.floor(vis.from - off));
    const hi = Math.min(n - 1, Math.ceil(vis.to - off));
    const d = rc.dpr;
    const w = rc.plotWidth * d;
    const h = rc.plotHeight * d;
    // Bands meet on bar midpoints, so one run paints as a seamless rect and two
    // neighbouring runs share an edge exactly instead of overlapping by a pixel.
    // Clamped to the plot because nothing clips it: the axis strips, drawn in
    // absolute coordinates, share this canvas.
    const edge = (i: number): number =>
      Math.min(w, Math.max(0, Math.round(rc.timeScale.indexToX(off + i - 0.5) * d)));

    ctx.save();
    for (let i = lo, start = lo; i <= hi; i++) {
      const c = colors[i];
      if (i < hi && colors[i + 1] === c) continue;
      // Truthy rather than a null check: a descriptor that builds its array by
      // index leaves holes, and an undefined colour would silently paint in
      // whichever colour was set last.
      if (c) {
        const x = edge(start);
        ctx.fillStyle = c;
        ctx.fillRect(x, 0, edge(i + 1) - x, h);
      }
      start = i + 1;
    }
    ctx.restore();
  }
}
