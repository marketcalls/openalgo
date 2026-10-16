/**
 * The shipped render backend: series painted by their registry renderer on the
 * pane's own 2D context. This is the path every chart took before the port
 * existed, so it is the reference the other backends are held to, pixel for
 * pixel (tests/e2e/render-parity.spec.ts).
 */
import type { DrawItem, RendererEntry, SeriesRenderContext } from '../model/chart-type-registry';
import type { SeriesStyle } from './series-style';
import { registerRenderBackend, type IRenderBackend } from './backend';

export class Canvas2dBackend implements IRenderBackend {
  public readonly kind = 'canvas2d';
  private _canvas: HTMLCanvasElement | null = null;
  private _ctx: CanvasRenderingContext2D | null = null;

  public mount(canvas: HTMLCanvasElement, ctx2d: CanvasRenderingContext2D | null): void {
    this._canvas = canvas;
    // The pane's context when it has one, so its ops and ours are one stream
    // on one object. A canvas without one (a host mounting a bare canvas)
    // gets asked for it here.
    this._ctx = ctx2d ?? canvas.getContext('2d');
    if (this._ctx === null) throw new Error('openalgo-charts: 2D canvas context is not available');
  }

  /**
   * Nothing to do: the pane's `CanvasLayer` owns the backing store and sized it
   * already. Re-sizing it here would clear a bitmap that was just painted.
   */
  public resize(_widthPx: number, _heightPx: number, _dpr: number): void {}

  /** The same clear `CanvasLayer.clearBitmap` does, so the op stream is unchanged. */
  public beginFrame(clear: boolean): void {
    if (!clear || this._ctx === null || this._canvas === null) return;
    this._ctx.setTransform(1, 0, 0, 1, 0, 0);
    this._ctx.clearRect(0, 0, this._canvas.width, this._canvas.height);
  }

  public drawSeries(
    entry: RendererEntry,
    items: readonly DrawItem[],
    priceToY: (price: number) => number,
    barSpacing: number,
    dpr: number,
    style: SeriesStyle,
    rc: SeriesRenderContext,
  ): void {
    if (this._ctx === null) return;
    entry.draw(this._ctx, items, priceToY, barSpacing, dpr, style, rc);
  }

  /** Every call above drew straight to the canvas; there is nothing to flush. */
  public endFrame(): void {}

  public overlay2d(): CanvasRenderingContext2D | null {
    return this._ctx;
  }

  public destroy(): void {
    this._ctx = null;
    this._canvas = null;
  }
}

registerRenderBackend('canvas2d', () => new Canvas2dBackend());
