/**
 * The runtime's side of a study's `calcTail`: the tail returns values for the
 * bars from its first index on, and the instance lays them over the result it
 * already holds for the bars before it.
 */

/**
 * A study's output columns by key, the shape of `IndicatorValues`. Written
 * out rather than imported, so this module imports nothing and closes no type
 * cycle through the registry.
 */
type Columns = Readonly<Record<string, readonly (number | null)[]>>;

/**
 * Overlay a `calcTail` result (values for `[from, n)`) onto the previous full
 * result, which covers the bars through `from`, the one the tail replaces. A
 * tail without exactly the previous result's keys, or a column of either of the
 * wrong length, forces the caller back to a full recompute by returning `null`.
 */
export function spliceTail(
  previous: Columns,
  tail: Columns,
  from: number,
  n: number,
): Record<string, (number | null)[]> | null {
  const out: Record<string, (number | null)[]> = {};
  // Same count and every tail key held: the same keys, so no column is dropped.
  if (Object.keys(previous).length !== Object.keys(tail).length) return null;
  for (const key of Object.keys(tail)) {
    const prev = previous[key];
    const add = tail[key];
    if (prev === undefined || add === undefined) return null;
    if (prev.length !== from + 1 || add.length !== n - from) return null;
    const col = new Array<number | null>(n);
    for (let i = 0; i < from; i++) col[i] = prev[i] ?? null;
    for (let i = from; i < n; i++) col[i] = add[i - from] ?? null;
    out[key] = col;
  }
  return out;
}
