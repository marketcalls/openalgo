/**
 * Invalidation model (ARCHITECTURE.md §3.2).
 *
 * A single global level is too coarse for multi-pane indicators and trade
 * overlays, so the mask carries a **global level + a per-pane map**. Multiple
 * invalidations within one frame raise the same mask, each level only ever
 * going up. It also keeps a queue of time-scale operations that nothing in the
 * chart reads, deprecated with the methods that fill and fold it (see
 * {@link TimeScaleOp}).
 */

/** How much of a pane (or the whole chart) must be repainted this frame. */
export const InvalidationLevel = {
  /** Nothing to do. */
  None: 0,
  /** Repaint only the top (overlay) canvas: the crosshair and the top-layer primitives. */
  Cursor: 1,
  /** Repaint the base canvas at the current scales: series moved or changed, no rescale. */
  Light: 2,
  /** Recompute scales/ticks then repaint everything. */
  Full: 3,
} as const;
export type InvalidationLevel = (typeof InvalidationLevel)[keyof typeof InvalidationLevel];

/** Per-pane invalidation entry. `autoScale` requests a price-axis rescale. */
export interface PaneInvalidation {
  level: InvalidationLevel;
  autoScale: boolean;
}

/**
 * Discrete time-scale operations a mask can queue, kept for compatibility.
 * The mask queues and merges them, and the chart never reads the queue: pan,
 * zoom, fit and reset change the shared time scale directly, and the kinetic
 * and wheel-zoom glides are stepped at the top of the render loop's frame
 * (ARCHITECTURE.md §3.2).
 *
 * @deprecated Removed in 3.0.0. A queued operation does nothing; change the time scale directly with
 * `chart.timeScale`, `chart.fitContent` or `chart.setVisibleLogicalRange`.
 */
export type TimeScaleOp =
  | { type: 'fitContent' }
  | { type: 'applyBarSpacing'; value: number }
  | { type: 'applyRightOffset'; value: number }
  | { type: 'reset' };

function mergePane(prev: PaneInvalidation | undefined, next: PaneInvalidation): PaneInvalidation {
  if (prev === undefined) return { ...next };
  return {
    level: Math.max(prev.level, next.level) as InvalidationLevel,
    autoScale: prev.autoScale || next.autoScale,
  };
}

export class InvalidateMask {
  private _globalLevel: InvalidationLevel;
  private readonly _panes = new Map<number, PaneInvalidation>();
  private _timeScaleOps: TimeScaleOp[] = [];

  public constructor(globalLevel: InvalidationLevel = InvalidationLevel.None) {
    this._globalLevel = globalLevel;
  }

  public get globalLevel(): InvalidationLevel {
    return this._globalLevel;
  }

  /** Raise the chart-wide level (monotonic: it only ever increases). */
  public invalidateGlobal(level: InvalidationLevel): void {
    if (level > this._globalLevel) this._globalLevel = level;
  }

  /** Raise a single pane's level without touching the others. */
  public invalidatePane(paneIndex: number, invalidation: PaneInvalidation): void {
    this._panes.set(paneIndex, mergePane(this._panes.get(paneIndex), invalidation));
  }

  public paneInvalidation(paneIndex: number): PaneInvalidation | undefined {
    return this._panes.get(paneIndex);
  }

  public panes(): ReadonlyMap<number, PaneInvalidation> {
    return this._panes;
  }

  /**
   * Queue an operation. The chart never reads the queue; see {@link TimeScaleOp}.
   *
   * @deprecated Removed in 3.0.0. The operation does nothing; change the time scale directly.
   */
  public addTimeScaleOp(op: TimeScaleOp): void {
    this._timeScaleOps.push(op);
  }

  /**
   * The operations queued so far, which nothing in the chart reads.
   *
   * @deprecated Removed in 3.0.0 with {@link TimeScaleOp}.
   */
  public timeScaleOps(): readonly TimeScaleOp[] {
    return this._timeScaleOps;
  }

  public isEmpty(): boolean {
    return (
      this._globalLevel === InvalidationLevel.None &&
      this._panes.size === 0 &&
      this._timeScaleOps.length === 0
    );
  }

  /**
   * Fold another mask into this one.
   *
   * @deprecated Removed in 3.0.0. The chart raises one mask per frame and never folds two, and a
   * host holds only the mask `chart.invalidate` hands it; raise levels on that one.
   */
  public merge(other: InvalidateMask): void {
    this.invalidateGlobal(other._globalLevel);
    for (const [index, inv] of other._panes) {
      this.invalidatePane(index, inv);
    }
    if (other._timeScaleOps.length > 0) {
      this._timeScaleOps = this._timeScaleOps.concat(other._timeScaleOps);
    }
  }
}
