/**
 * HiDPI canvas handling (ARCHITECTURE.md §3.1).
 *
 * Each canvas has two coordinate systems: **media** (CSS px, what you reason
 * about) and **bitmap** (device px = media × devicePixelRatio, the backing
 * buffer). Drawing 1px lines in the bitmap scope with integer snapping keeps
 * them crisp on retina/HiDPI displays.
 */

import { bitmapSize } from '../helpers/math';

/**
 * Pure: move every boundary between stacked boxes onto a device-pixel edge,
 * so each box is a whole number of device pixels tall.
 *
 * Shared by weight, three panes in 517 px are 310.2 px and 103.4 px tall, and
 * at a device pixel ratio of 1.5 their boundaries fall inside a device pixel.
 * A canvas sized to such a box has a backing store the browser has to stretch
 * by a fraction of a pixel to cover it, which blurs every line on it, and the
 * separator lands on a row the two panes share. Rounding the running
 * total, rather than each height, keeps the error at half a device pixel per
 * boundary instead of letting it accumulate down the stack, and leaves the
 * outer edge where the caller put it: the container's own box is the browser's.
 */
export function alignToDevicePixels(
  boxes: readonly { top: number; height: number }[],
  dpr: number,
): { top: number; height: number }[] {
  const last = boxes[boxes.length - 1];
  if (!(dpr > 0) || !Number.isFinite(dpr) || last === undefined) return boxes.map(box => ({ ...box }));
  const end = last.top + last.height;
  let top = boxes[0]!.top; // a last box means a first one
  return boxes.map((box, i) => {
    const bottom = i === boxes.length - 1 ? end : Math.round((box.top + box.height) * dpr) / dpr;
    const out = { top, height: Math.max(0, bottom - top) };
    top = Math.max(top, bottom);
    return out;
  });
}

/**
 * Pure: whether the rule between stacked panes is drawn as the pane's 1 px top
 * border, with the pane's canvases starting under it. At a whole-number ratio
 * 1 px is a whole number of device pixels, so the canvases under the border
 * still start on a device pixel, and the layout stays the one every release
 * before this has shown. At a fractional ratio a 1 px border ends part way
 * into a device pixel, so the rule is laid over the canvases instead
 * (`hairlineHeight`). A ratio that cannot be used counts as 1.
 */
export function separatorIsBorder(dpr: number): boolean {
  return !(dpr > 0) || !Number.isFinite(dpr) || Number.isInteger(dpr);
}

/**
 * Pure: the height in CSS px of a rule that covers whole device pixels, at
 * least one. At ratios 1, 2 and 3 that is 1 px; at 1.25 and 1.5 it is one
 * device pixel, where 1 px would end part way into the next.
 */
export function hairlineHeight(dpr: number): number {
  if (!(dpr > 0) || !Number.isFinite(dpr)) return 1;
  return Math.max(1, Math.floor(dpr)) / dpr;
}

/**
 * A single `<canvas>` element with media/bitmap sizing. Constructed only in a
 * browser; the size math above is the part exercised by unit tests.
 */
export class CanvasLayer {
  public readonly element: HTMLCanvasElement;
  public readonly ctx: CanvasRenderingContext2D;
  private _mediaWidth = 0;
  private _mediaHeight = 0;
  private _dpr = 1;
  /** The device-pixel box the browser last reported for this canvas, 0 when none is trusted. */
  private _deviceWidth = 0;
  private _deviceHeight = 0;

  public constructor(doc: Document, zIndex: number) {
    this.element = doc.createElement('canvas');
    const ctx = this.element.getContext('2d');
    if (ctx === null) {
      throw new Error('openalgo-charts: 2D canvas context is not available');
    }
    this.ctx = ctx;
    const s = this.element.style;
    s.position = 'absolute';
    s.top = '0';
    s.left = '0';
    s.width = '100%';
    s.height = '100%';
    s.zIndex = String(zIndex);
  }

  public get mediaWidth(): number {
    return this._mediaWidth;
  }

  public get mediaHeight(): number {
    return this._mediaHeight;
  }

  public get pixelRatio(): number {
    return this._dpr;
  }

  /** Resize backing buffer + CSS box. No-op if nothing changed. */
  public resize(mediaWidth: number, mediaHeight: number, dpr: number): void {
    if (mediaWidth === this._mediaWidth && mediaHeight === this._mediaHeight && dpr === this._dpr) {
      return;
    }
    this._mediaWidth = mediaWidth;
    this._mediaHeight = mediaHeight;
    this._dpr = dpr;
    const bmp = bitmapSize(mediaWidth, mediaHeight, dpr);
    // The browser reports a device-pixel box only when it changes. A resize by
    // less than a pixel often leaves it as it was, so no report follows, and
    // the estimate would stretch the store by a pixel for good. The box last
    // reported is still the box then, and is kept while it is one the new
    // size can snap to: the whole number of device pixels either side of the
    // estimate. A step that moves the estimate past it (800 to 801 px at
    // ratio 1) cannot be that box, and keeping it would paint into a store
    // the browser's next report clears for a second full paint.
    this.element.width = this._snapsTo(this._deviceWidth, mediaWidth * dpr) ?? bmp.width;
    this.element.height = this._snapsTo(this._deviceHeight, mediaHeight * dpr) ?? bmp.height;
    this.element.style.width = `${mediaWidth}px`;
    this.element.style.height = `${mediaHeight}px`;
  }

  /**
   * Size the backing store to the device pixels the browser reports the box
   * covers (`devicePixelContentBoxSize`). `media x dpr` is only an estimate:
   * a box that starts part way into a device pixel is snapped by the browser
   * to one pixel more or fewer, and a backing store one pixel off is stretched
   * across the box, blurring everything on it. The media size and the ratio
   * are unchanged, so drawing code keeps scaling by `dpr`.
   *
   * A report more than a pixel away from `media x dpr` is not a snapped box
   * but a different scale, and is refused: an emulated device scale reports
   * the box at the host's real ratio while `devicePixelRatio` says another,
   * and a store sized to it would crop the chart.
   *
   * Returns true when the bitmap changed, which clears it: the caller repaints.
   */
  public setDeviceSize(width: number, height: number): boolean {
    const w = this._reported(width, this._mediaWidth * this._dpr);
    const h = this._reported(height, this._mediaHeight * this._dpr);
    if (w === null || h === null) {
      this.forgetDeviceSize();
      return false;
    }
    this._deviceWidth = w;
    this._deviceHeight = h;
    if (this.element.width === w && this.element.height === h) return false;
    this.element.width = w;
    this.element.height = h;
    return true;
  }

  /**
   * Drop the reported box, for a report the caller could not match to this
   * canvas's current size: `resize` then estimates until the next report.
   */
  public forgetDeviceSize(): void {
    this._deviceWidth = 0;
    this._deviceHeight = 0;
  }

  /** A reported device size, if it is whole, positive and within a pixel of `estimate`. */
  private _reported(device: number, estimate: number): number | null {
    return Number.isInteger(device) && device > 0 && Math.abs(device - estimate) <= 1 ? device : null;
  }

  /**
   * A device size last reported, if a box of `estimate` device pixels can
   * still snap to it: the floor or the ceiling of the estimate, which for a
   * whole size is the one less than a pixel away.
   */
  private _snapsTo(device: number, estimate: number): number | null {
    return device > 0 && Math.abs(device - estimate) < 1 ? device : null;
  }

  /** Clear the whole bitmap and reset the transform to bitmap (device-px) scope. */
  public clearBitmap(): void {
    this.ctx.setTransform(1, 0, 0, 1, 0, 0);
    this.ctx.clearRect(0, 0, this.element.width, this.element.height);
  }
}
