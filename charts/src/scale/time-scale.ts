/**
 * Time scale (ARCHITECTURE.md §5.1, §5.3). Maps between the shared **logical index**
 * and x. Because x is `index × barSpacing` (not timestamp-proportional),
 * non-trading gaps collapse automatically: weekends/holidays/session breaks
 * have no logical index, so there is no blank space to draw.
 */
import { clamp } from '../helpers/math';

export interface LogicalRange {
  from: number;
  to: number;
}

export interface TimeScaleOptions {
  barSpacing: number;
  minBarSpacing: number;
  maxBarSpacing: number;
  /** Empty bars of space kept to the right of the latest bar. */
  rightOffset: number;
}

export const DEFAULT_TIME_SCALE_OPTIONS: TimeScaleOptions = {
  barSpacing: 8,
  minBarSpacing: 1,
  maxBarSpacing: 80,
  rightOffset: 4,
};

export class TimeScale {
  private _barSpacing: number;
  private _rightOffset: number;
  private readonly _minBarSpacing: number;
  private readonly _maxBarSpacing: number;
  private _width = 0;
  private _baseIndex = 0;

  public constructor(options: Partial<TimeScaleOptions> = {}) {
    const o = { ...DEFAULT_TIME_SCALE_OPTIONS, ...options };
    this._barSpacing = o.barSpacing;
    this._rightOffset = o.rightOffset;
    this._minBarSpacing = o.minBarSpacing;
    this._maxBarSpacing = o.maxBarSpacing;
  }

  public setWidth(width: number): void {
    this._width = width;
  }

  public get width(): number {
    return this._width;
  }

  public get barSpacing(): number {
    return this._barSpacing;
  }

  public setBarSpacing(value: number): void {
    const before = this.visibleRange();
    this._barSpacing = this.constrainBarSpacing(value);
    this._notifyChange(before);
  }

  /** Bound a pending zoom target without changing the displayed viewport. */
  public constrainBarSpacing(value: number): number {
    return clamp(value, this._minBarSpacing, this._maxBarSpacing);
  }

  public get rightOffset(): number {
    return this._rightOffset;
  }

  public setRightOffset(value: number): void {
    const before = this.visibleRange();
    this._rightOffset = value;
    this._notifyChange(before);
  }

  /** Logical index of the latest bar; the right edge anchors to baseIndex+rightOffset. */
  public setBaseIndex(index: number): void {
    this._baseIndex = index;
  }

  private _rightEdgeIndex(): number {
    return this._baseIndex + this._rightOffset;
  }

  /** Logical index to x (media px), bar center. */
  public indexToX(index: number): number {
    return this._width - (this._rightEdgeIndex() - index) * this._barSpacing;
  }

  /** x (media px) to fractional logical index. */
  public xToIndex(x: number): number {
    return this._rightEdgeIndex() - (this._width - x) / this._barSpacing;
  }

  /** Currently visible logical index range (fractional, unclamped to data). */
  public visibleRange(): LogicalRange {
    const to = this._rightEdgeIndex();
    const from = to - this._width / this._barSpacing;
    return { from, to };
  }

  /** Alias of `visibleRange()` for naming parity with common charting APIs. */
  public getVisibleLogicalRange(): LogicalRange {
    return this.visibleRange();
  }

  /**
   * Set the visible logical range (best effort): pick a bar spacing so the span
   * fills the width and anchor the right edge at `range.to`. Bar spacing is
   * clamped to [min,max], so an extreme span lands at the nearest zoom. Fires the
   * change handler so a host that mutates the scale directly still repaints.
   */
  public setVisibleLogicalRange(range: LogicalRange): void {
    if (this._width <= 0) return;
    const span = range.to - range.from;
    if (!(span > 0)) return;
    const before = this.visibleRange();
    this._barSpacing = this.constrainBarSpacing(this._width / span);
    this._rightOffset = range.to - this._baseIndex;
    // An explicit replacement also cancels host navigation that has not settled yet.
    this._onChange?.(before);
  }

  /** Fired after changed navigation or any valid explicit range request; layout/data setters stay silent. */
  public setChangeHandler(fn: ((before: LogicalRange) => void) | null): void {
    this._onChange = fn;
  }
  private _onChange: ((before: LogicalRange) => void) | null = null;

  private _notifyChange(before: LogicalRange): void {
    const after = this.visibleRange();
    if (before.from !== after.from || before.to !== after.to) this._onChange?.(before);
  }

  /**
   * Pan by a pixel delta. Positive `dx` drags chart content to the right
   * (revealing older bars), matching a natural left-button drag.
   */
  public scrollByPixels(dx: number): void {
    this.setRightOffset(this._rightOffset - dx / this._barSpacing);
  }

  /**
   * Zoom around an anchor x (the cursor): change bar spacing by `factor`
   * while keeping whatever logical index sits under `focusX` pinned there.
   * `factor` > 1 zooms in (wider bars).
   */
  public zoomAtX(focusX: number, factor: number): void {
    const range = this.visibleRange();
    const focusIndex = this.xToIndex(focusX);
    const before = this._barSpacing;
    this._barSpacing = this.constrainBarSpacing(before * factor);
    if (this._barSpacing === before) return; // clamped: nothing moved
    // Re-anchor: indexToX(focusIndex) must still equal focusX.
    // width - (rightEdge - focusIndex) * bs = focusX
    const rightEdge = focusIndex + (this._width - focusX) / this._barSpacing;
    this._rightOffset = rightEdge - this._baseIndex;
    this._notifyChange(range);
  }

  /** Choose bar spacing so `barCount` bars fit the width, anchored at the right edge. */
  public fitContent(barCount: number): void {
    if (barCount <= 0 || this._width <= 0) return;
    const before = this.visibleRange();
    this._baseIndex = barCount - 1;
    this._rightOffset = DEFAULT_TIME_SCALE_OPTIONS.rightOffset;
    const usable = this._width / (barCount + this._rightOffset);
    this._barSpacing = this.constrainBarSpacing(usable);
    this._notifyChange(before);
  }
}
