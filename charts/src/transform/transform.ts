/**
 * Series transform pipeline (ARCHITECTURE.md §6A, Family B). A transform
 * re-buckets raw OHLC into a derived element series driven by price movement,
 * not the clock. A transform is incremental: `push` takes each source bar
 * once, in time order, and never recomputes what came before. Every push moves
 * the state, so a bar that is still forming is not pushed on each tick (that
 * counts it again every time); a live chart pushes it through a `clone` of
 * the state instead and pushes it for good once it has closed (see ./live).
 *
 * Each derived element is a Bar carrying its source formation time. Because the
 * time scale is index-based, derived elements get uniform spacing automatically
 * (the "ordinal" axis); axis labels read each element's formation time. We only
 * post-process times to be strictly increasing so the shared DataLayer keeps
 * every element on its own logical index (no collisions when many elements form
 * within one source bar).
 */
import type { Bar } from '../model/bar';

export interface ISeriesTransform {
  /** Reset to initial state (start of a fresh batch / re-subscribe). */
  reset(): void;
  /** Feed one source bar; return 0..n newly *completed* derived elements. */
  push(bar: Bar): Bar[];
  /** Optional: emit any in-progress element at end of data. */
  flush?(): Bar[];
  /**
   * Optional: an independent copy of the state, for a live chart to push the
   * forming bar through. `push` changes state on every call, so the bar that
   * is still forming is pushed into a copy on each tick and into the transform
   * itself only once it has closed. The built-in transforms all have one.
   */
  clone?(): ISeriesTransform;
}

/**
 * A shallow copy of a transform: its prototype and every field. A field that
 * holds an object is shared, so a transform whose state has one copies it
 * after this.
 */
export function copyState<T extends object>(transform: T): T {
  return Object.assign(Object.create(Object.getPrototypeOf(transform) as object) as T, transform);
}

/**
 * Make times strictly increasing (collisions bumped by +1s) so the DataLayer
 * assigns one logical index per element. Labels stay within a few seconds of
 * the real formation time.
 */
export function ensureIncreasingTimes(bars: readonly Bar[]): Bar[] {
  let prev = -Infinity;
  const out: Bar[] = [];
  for (const b of bars) {
    let t = b.time;
    if (t <= prev) t = prev + 1;
    prev = t;
    out.push(t === b.time ? b : { ...b, time: t });
  }
  return out;
}

/** Run a transform over a full batch of bars (history load). */
export function runTransform(transform: ISeriesTransform, bars: readonly Bar[]): Bar[] {
  transform.reset();
  const out: Bar[] = [];
  for (const b of bars) out.push(...transform.push(b));
  if (transform.flush) out.push(...transform.flush());
  return ensureIncreasingTimes(out);
}
