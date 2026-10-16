/**
 * Average True Range: Wilder's ATR, matching `openalgo.atr(high, low, close, 14)`.
 * Shared by the Supertrend indicator. True range of the first bar is high-low.
 */

/** True range series. tr[0] = high[0]-low[0]; thereafter the classic 3-way max. */
export function trueRange(
  high: readonly number[],
  low: readonly number[],
  close: readonly number[],
): number[] {
  const n = high.length;
  const tr = new Array<number>(n);
  if (n === 0) return tr;
  // `low` and `close` run alongside `high`. One that is shorter reads
  // undefined past its end, and that bar's true range is NaN.
  tr[0] = high[0]! - low[0]!;
  for (let i = 1; i < n; i++) {
    const hl = high[i]! - low[i]!;
    const hc = Math.abs(high[i]! - close[i - 1]!);
    const lc = Math.abs(low[i]! - close[i - 1]!);
    tr[i] = Math.max(hl, hc, lc);
  }
  return tr;
}

/**
 * Wilder ATR. The first value is the SMA of the first `period` consecutive
 * finite true ranges, so on complete data it lands at index period-1. A missing
 * or overflowing true range leaves its own slot NaN and keeps the average, and
 * the next finite one carries on from it: a gap costs only the bars it covers.
 */
export function atr(
  high: readonly number[],
  low: readonly number[],
  close: readonly number[],
  period = 14,
): number[] {
  if (period <= 0) throw new Error('openalgo-charts: ATR period must be > 0');
  const tr = trueRange(high, low, close);
  const n = tr.length;
  const out = new Array<number>(n).fill(NaN);
  if (n < period || !Number.isInteger(period)) return out;
  // NaN until seeded. A running overflow stays committed as Infinity, so it is
  // never mistaken for an unseeded average and restarted from a fresh window.
  let a = NaN;
  let run = 0;
  // `run` finite true ranges end at `i`, so a seed window of `period` of them
  // starts at zero or later.
  for (let i = 0; i < n; i++) {
    const t = tr[i]!;
    if (!Number.isFinite(t)) { run = 0; continue; }
    run++;
    if (!Number.isNaN(a)) a = (a * (period - 1) + t) / period;
    else if (run >= period) {
      // Summed oldest first, as the complete-data seed always was, and afresh
      // each time: a seed that overflowed retries once its window moves on.
      let sum = 0;
      for (let j = i - period + 1; j <= i; j++) sum += tr[j]!;
      if (Number.isFinite(sum / period)) a = sum / period;
    }
    if (Number.isFinite(a)) out[i] = a;
  }
  return out;
}
