/**
 * Exponential moving average (ARCHITECTURE.md §8: an indicator that validates
 * the series/extensibility model). Pure; the result is plotted as a `line`
 * series, demonstrating derived data on the shared time axis.
 */
import type { Bar } from '../model/bar';

/** EMA over a numeric series. Seeds from the first value; k = 2/(period+1). */
export function ema(values: readonly number[], period: number): number[] {
  if (period <= 0) throw new Error('openalgo-charts: EMA period must be > 0');
  const out: number[] = [];
  if (values.length === 0) return out;
  const k = 2 / (period + 1);
  let prev = values[0]!;
  out.push(prev);
  for (let i = 1; i < values.length; i++) {
    prev = values[i]! * k + prev * (1 - k);
    out.push(prev);
  }
  return out;
}

/**
 * EMA of bar closes as plottable bars (close = ema; O/H/L = ema), ready to feed
 * a `line` series via `series.setData(...)`.
 */
export function emaSeries(bars: readonly Bar[], period: number): Bar[] {
  const values = bars.map((b) => b.close);
  const e = ema(values, period);
  // `e` has one value per bar.
  return bars.map((b, i) => ({ time: b.time, open: e[i]!, high: e[i]!, low: e[i]!, close: e[i]! }));
}
