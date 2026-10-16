/**
 * Small series rules the built-ins share: what a plot offset does at the
 * edges, what a missing volume is, how two same-length series combine. One
 * copy each, so a correction lands everywhere. Tier-internal: the tier index
 * does not re-export them.
 */
import type { Bar } from 'openalgo-charts';

/**
 * the reference `plot(..., offset = k)`, baked into the column: the value computed on
 * bar `i` lands in slot `i + k`, so a positive `k` draws later and a negative
 * one earlier. A slot nothing lands in is NaN, and values pushed past either
 * end are dropped. `k` is whole: every caller reads it through `offsetOf` or
 * `int`, or passes a constant.
 */
export function shift(values: readonly number[], k: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  // `i - k` lies in [0, n) for every `i` the bounds allow.
  for (let i = Math.max(0, k), end = Math.min(n, n + k); i < end; i++) out[i] = values[i - k]!;
  return out;
}

/** `shift` for a condition series, `k` of zero or more. An out-of-range flag reads as false. */
export function shiftFlags(flags: readonly boolean[], k: number): boolean[] {
  const out = new Array<boolean>(flags.length).fill(false);
  for (let i = k; i < flags.length; i++) out[i] = flags[i - k]!;
  return out;
}

/**
 * A column holding one value on every bar, warmup slots included. The shaded
 * band between two reference levels is a fill between two such columns:
 * `fills` resolves its keys out of the `calc` result rather than out of the
 * declared plots, so a level that is never plotted can still anchor a band. It
 * must stay non-null throughout, because the shading covers the whole pane and
 * not just the stretch where the study prints.
 */
export const constant = (n: number, value: number): (number | null)[] =>
  new Array<number | null>(n).fill(value);

/**
 * the reference `nz(volume)`: a bar the feed gave no usable volume for traded nothing.
 * `?? 0` would cover only an absent volume, and one NaN would then reach a
 * running total and blank it for the rest of the history.
 */
export const volumeOf = (b: Bar): number =>
  typeof b.volume === 'number' && Number.isFinite(b.volume) ? b.volume : 0;

/** `f` over two series pairwise, for two series that hold one value per bar each. */
export function zip<A, B>(a: readonly A[], b: readonly B[], f: (x: A, y: B) => number): number[] {
  const out = new Array<number>(a.length);
  for (let i = 0; i < a.length; i++) out[i] = f(a[i]!, b[i]!);
  return out;
}
