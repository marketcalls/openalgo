/**
 * How the chart follows its box and the device pixel ratio: the resize
 * observer on the container, the device-pixel observer on each canvas, and
 * the resolution query and window `resize` that report a new ratio.
 *
 * Its own module because the observers and the query are held and released
 * by these methods alone. The chart reaches them through `Chart._pixels`, and
 * they reach the chart through `PixelsHost`. Members the chart still calls
 * or reads are public on this internal class; no entry point exports the
 * class and the chart holds it in a private field, so none of it reaches the
 * published declarations.
 */
import { InvalidationLevel } from './invalidate-mask';
import type { Chart } from './chart';
import type { Pane } from './pane';
import type { CanvasLayer } from './canvas';

/**
 * The slice of the chart the observation reads and drives. The chart itself is
 * the host: each member carries the name and the type of the chart's own, so
 * the moved code reads as it did in chart.ts, and a member the chart renames
 * or retypes fails to compile here.
 */
export interface PixelsHost {
  readonly _destroyed: Chart['_destroyed'];
  readonly _destroying: Chart['_destroying'];
  readonly _panes: Chart['_panes'];
  readonly _container: Chart['_container'];
  readonly _doc: Chart['_doc'];
  readonly _layoutRatio: Chart['_layoutRatio'];
  /** The chart's own listener functions, added here and removed here by identity. */
  readonly _onPixelRatio: Chart['_onPixelRatio'];
  readonly _checkPixelRatio: Chart['_checkPixelRatio'];
  /** The chart's other collaborators, whose methods this code calls directly. */
  readonly _layout: Chart['_layout'];
  applySize: Chart['applySize'];
  _paintNow: Chart['_paintNow'];
  invalidate: Chart['invalidate'];
  _pixelRatio: Chart['_pixelRatio'];
}

export class ChartPixels {
  private readonly _host: PixelsHost;
  public _resizeObserver: ResizeObserver | null = null;
  /** Watches the canvases' device-pixel boxes, where the browser reports them. */
  public _deviceObserver: ResizeObserver | null = null;
  /** Matches the device pixel ratio the canvases were last sized at; made again on every change. */
  private _ratioQuery: MediaQueryList | null = null;
  /** The window whose `resize` also re-checks the ratio. */
  private _ratioView: Window | null = null;

  public constructor(host: PixelsHost) {
    this._host = host;
  }

  public _observeSize(): void {
    if (typeof ResizeObserver === 'undefined') return;
    this._resizeObserver = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      this._host.applySize(entry.contentRect.width, entry.contentRect.height);
      // Resizing a canvas clears it, and this callback runs after the
      // frame's animation callbacks, just before the browser paints. Left
      // to the next frame, the repaint would put one cleared frame on screen
      // for every step of a window drag.
      this._host._paintNow();
    });
    this._resizeObserver.observe(this._host._container);
    if (typeof ResizeObserverEntry !== 'undefined' && 'devicePixelContentBoxSize' in ResizeObserverEntry.prototype) {
      this._deviceObserver = new ResizeObserver(entries => this._onDevicePixels(entries));
      for (const pane of this._host._panes) this._observeCanvases(pane, true);
    }
  }

  /** Start or stop reading a pane's canvases' device-pixel boxes. */
  public _observeCanvases(pane: Pane, on: boolean): void {
    const observer = this._deviceObserver;
    if (observer === null) return;
    for (const layer of [pane.base, pane.top]) {
      if (on) observer.observe(layer.element, { box: 'device-pixel-content-box' });
      else observer.unobserve(layer.element);
    }
  }

  /**
   * Give each canvas the backing store the browser says its box covers. A
   * canvas that starts part way into a device pixel is snapped to one pixel
   * more or fewer than `media x dpr`, and a store one pixel off is stretched
   * over the box, blurring every line on it.
   */
  private _onDevicePixels(entries: readonly ResizeObserverEntry[]): void {
    if (this._host._destroyed || this._host._destroying) return;
    let changed = false;
    for (const entry of entries) {
      const layer = this._canvasLayerOf(entry.target);
      const device = entry.devicePixelContentBoxSize?.[0];
      const box = entry.contentBoxSize?.[0];
      if (layer === null || device === undefined || box === undefined) continue;
      // Measured before a relayout in this same frame: the box it describes
      // is gone, and the entry for the new one follows before the paint. What
      // the canvas last heard is no longer known to be its box either.
      if (Math.abs(box.inlineSize - layer.mediaWidth) > 0.05 || Math.abs(box.blockSize - layer.mediaHeight) > 0.05) {
        layer.forgetDeviceSize();
        continue;
      }
      if (layer.setDeviceSize(device.inlineSize, device.blockSize)) changed = true;
    }
    if (!changed) return;
    this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._paintNow();
  }

  private _canvasLayerOf(target: Element): CanvasLayer | null {
    for (const pane of this._host._panes) {
      if (pane.base.element === target) return pane.base;
      if (pane.top.element === target) return pane.top;
    }
    return null;
  }

  /** The window the chart's document shows in, or null outside a browser. */
  private _view(): Window | null {
    const view = this._host._doc.defaultView;
    if (view) return view;
    return typeof window === 'undefined' ? null : window;
  }

  /**
   * Follow the device pixel ratio. It changes with no box changing size when
   * the window moves to a screen of another density, and no size observer
   * hears of that, so the canvases would stay at the old ratio, stretched and
   * blurred. A resolution query matches the one ratio it was made for, so
   * each change makes a new one for the ratio now in force.
   *
   * The window's `resize` is heard too: a zoom fires it, and it is the one
   * signal left in a browser whose query list takes no change listener. It
   * costs a comparison when the ratio has not moved.
   */
  public _watchPixelRatio(): void {
    this._unwatchPixelRatio();
    const view = this._view();
    if (view === null || this._host._destroying || this._host._destroyed) return;
    if (typeof view.addEventListener === 'function') {
      view.addEventListener('resize', this._host._checkPixelRatio);
      this._ratioView = view;
    }
    if (typeof view.matchMedia !== 'function') return;
    const query = view.matchMedia(`(resolution: ${view.devicePixelRatio || 1}dppx)`);
    if (typeof query?.addEventListener !== 'function') return;
    query.addEventListener('change', this._host._onPixelRatio);
    this._ratioQuery = query;
  }

  public _unwatchPixelRatio(): void {
    this._ratioQuery?.removeEventListener('change', this._host._onPixelRatio);
    this._ratioQuery = null;
    this._ratioView?.removeEventListener('resize', this._host._checkPixelRatio);
    this._ratioView = null;
  }

  public _onPixelRatio(): void {
    if (this._host._destroyed || this._host._destroying) return;
    this._watchPixelRatio();
    this._checkPixelRatio();
  }

  /** Size the canvases again if the ratio is no longer the one they were sized at. */
  public _checkPixelRatio(): void {
    if (this._host._destroyed || this._host._destroying || this._host._pixelRatio() === this._host._layoutRatio) return;
    this._host._layout._relayout();
    this._host.invalidate(m => m.invalidateGlobal(InvalidationLevel.Full));
    this._host._paintNow();
  }
}
