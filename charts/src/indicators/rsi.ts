/**
 * Relative Strength Index using Wilder smoothing.
 *
 * Uses Wilder smoothing (RMA): the first average gain/loss is the simple mean of
 * a complete finite window of `period` deltas, then each subsequent average
 * carries `(prev*(period-1) + current)/period`. Missing deltas preserve seeded
 * state but emit NaN. Each leg retries an unavailable seed independently.
 */
import type { Bar } from '../model/bar';

/** Wilder RSI over a numeric series. Returns NaN for the first `period` slots. */
export function rsi(values: readonly number[], period = 14): number[] {
  if (period <= 0) throw new Error('openalgo-charts: RSI period must be > 0');
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (n <= period || !Number.isInteger(period)) return out;

  let avgGain = NaN;
  let avgLoss = NaN;
  let gainSeeded = false;
  let lossSeeded = false;
  let finiteRun = 0;
  // Deltas start at bar 1, so `finiteRun` finite ones ending at `i` put the
  // seed window's first `j - 1` at zero or later.
  for (let i = 1; i < n; i++) {
    const d = values[i]! - values[i - 1]!;
    if (!Number.isFinite(d)) {
      finiteRun = 0;
      continue;
    }
    finiteRun++;
    const g = d > 0 ? d : 0;
    const l = d < 0 ? -d : 0;
    // A valid recurrence commits even when it overflows. It must not turn into
    // a new seed or let the other leg manufacture a finite extreme reading.
    if (gainSeeded) avgGain = (avgGain * (period - 1) + g) / period;
    if (lossSeeded) avgLoss = (avgLoss * (period - 1) + l) / period;
    if ((!gainSeeded || !lossSeeded) && finiteRun >= period) {
      let gain = 0;
      let loss = 0;
      // Fresh chronological sums allow a failed seed to recover after the
      // overflowing window expires, without subtraction drift in later seeds.
      for (let j = i - period + 1; j <= i; j++) {
        const change = values[j]! - values[j - 1]!;
        if (change >= 0) gain += change;
        else loss -= change;
      }
      if (!gainSeeded && Number.isFinite(gain / period)) {
        avgGain = gain / period;
        gainSeeded = true;
      }
      if (!lossSeeded && Number.isFinite(loss / period)) {
        avgLoss = loss / period;
        lossSeeded = true;
      }
    }
    if (Number.isFinite(avgGain) && Number.isFinite(avgLoss)) {
      const value = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
      if (Number.isFinite(value)) out[i] = value;
    }
  }
  return out;
}

/**
 * RSI of bar closes as plottable bars (close = rsi). Warmup bars carry NaN so a
 * `line` series breaks cleanly before the first value (the renderer skips
 * non-finite points) instead of dropping to zero.
 */
export function rsiSeries(bars: readonly Bar[], period = 14): Bar[] {
  const r = rsi(bars.map((b) => b.close), period);
  // `r` has one value per bar.
  return bars.map((b, i) => ({ time: b.time, open: r[i]!, high: r[i]!, low: r[i]!, close: r[i]! }));
}
