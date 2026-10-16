/**
 * Finite-window sums must depend only on their current window. Carrying
 * an earlier rounded sum can invent a crossing or retain an expired overflow.
 * Sum chronologically afresh; a missing or overflowing window stays absent.
 * Every caller passes a whole period of one or more (./calc checks it, the
 * studies round or floor theirs to at least 1), so each read lies in [0, i].
 */
export function windowSum(values: readonly number[], period: number): number[] {
  const out = new Array<number>(values.length).fill(NaN);
  if (values.length < period) return out;
  if (period === 1) {
    for (let i = 0; i < values.length; i++) {
      const value = values[i]!;
      if (Number.isFinite(value)) out[i] = value === 0 ? 0 : value;
    }
    return out;
  }
  // Only validity metadata is incremental. Numeric additions stay in window
  // order; subtracting an expired observation cannot undo earlier rounding.
  let missing = 0;
  for (let i = 0; i < values.length; i++) {
    if (!Number.isFinite(values[i])) missing++;
    if (i >= period && !Number.isFinite(values[i - period])) missing--;
    if (i < period - 1 || missing !== 0) continue;
    let sum = 0;
    for (let j = i - period + 1; j <= i; j++) sum += values[j]!;
    if (Number.isFinite(sum)) out[i] = sum;
  }
  return out;
}

export function windowMean(values: readonly number[], period: number): number[] {
  const out = windowSum(values, period);
  if (period !== 1) for (let i = 0; i < out.length; i++) out[i]! /= period;
  return out;
}
