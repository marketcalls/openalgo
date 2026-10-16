/**
 * Resumable forms of the recursive kernels behind the built-ins, for their
 * `calcTail` (see ./tail). Each keeps in a plain object exactly what the batch
 * kernel keeps in locals and walks the same arithmetic in the same order, so a
 * tail resumed from a checkpoint lands on the batch result to the last bit.
 *
 * They are copies, and a copy can drift from its original. What holds them
 * together is tests/indicator-tail.test.ts: it drives every built-in's tail
 * against its full `calc` over random streams with gaps and missing values, so
 * a change to one side without the other fails there.
 *
 * A kernel still warming up keeps the run of values its seed will average,
 * never more than one window of them, so a checkpoint taken mid-warmup resumes
 * without reaching back into bars it no longer holds.
 *
 * A step that takes `bars` and `i` is driven by a machine (./tail), which
 * hands it the index of a bar it holds.
 */
import type { Bar } from 'openalgo-charts';
import { finiteAverage } from './calc';

/** `seededSmoothing` in ./calc: an EMA or Wilder average seeded on the first complete finite window. */
export interface Seeded { run: number; value: number; seeded: boolean; recent: number[] }

export const seeded = (): Seeded => ({ run: 0, value: NaN, seeded: false, recent: [] });

/** One step of `smaSeededEma` (exponential) or `rma` for a safe-integer period. */
export function smooth(st: Seeded, x: number, period: number, exponential: boolean): number {
  if (!Number.isFinite(x)) {
    st.run = 0;
    st.recent.length = 0;
    return NaN;
  }
  if (!st.seeded) {
    const recent = st.recent;
    recent.push(x);
    if (recent.length > period) recent.shift();
    if (++st.run < period) return NaN;
    let sum = 0;
    for (let k = 0; k < recent.length; k++) sum += recent[k]!;
    const mean = sum / period;
    if (!Number.isFinite(mean)) return NaN;
    st.value = mean === 0 ? 0 : mean;
    st.seeded = true;
    recent.length = 0;
  } else {
    const weight = 2 / (period + 1);
    st.value = exponential ? x * weight + st.value * (1 - weight) : (st.value * (period - 1) + x) / period;
  }
  return Number.isFinite(st.value) ? (st.value === 0 ? 0 : st.value) : NaN;
}

/** `observedSmoothing` in ./calc under the propagate policy, as `smaSeededEma` runs it on a study output. */
interface Observed { count: number; seed: number[]; value: number }

export const observed = (): Observed => ({ count: 0, seed: [], value: NaN });

export function observedStep(st: Observed, x: number, period: number): number {
  if (!Number.isFinite(x)) {
    st.count = 0;
    st.seed.length = 0;
    st.value = NaN;
    return NaN;
  }
  if (st.count < period) {
    st.seed.push(x);
    if (++st.count < period) return NaN;
    st.value = finiteAverage(st.seed);
    st.seed.length = 0;
  } else st.value = finiteAverage([st.value, x], [period - 1, 2]);
  return st.value;
}

/** `trueRange` in the base bundle, at one bar: the first bar is its own high-low. */
export function trueRangeAt(bars: readonly Bar[], i: number): number {
  const b = bars[i]!;
  if (i === 0) return b.high - b.low;
  const close = bars[i - 1]!.close;
  return Math.max(b.high - b.low, Math.abs(b.high - close), Math.abs(b.low - close));
}

/** `atr` in the base bundle: Wilder's average, seeded on `period` consecutive finite true ranges. */
interface Wilder { a: number; run: number; recent: number[] }

export const wilder = (): Wilder => ({ a: NaN, run: 0, recent: [] });

export function atrStep(st: Wilder, t: number, period: number): number {
  if (!Number.isFinite(t)) {
    st.run = 0;
    st.recent.length = 0;
    return NaN;
  }
  st.run++;
  if (!Number.isNaN(st.a)) st.a = (st.a * (period - 1) + t) / period;
  else {
    // Only a period of 1 can fall back to NaN once seeded (an infinite average
    // times zero), and its seed window is this one value.
    const recent = st.recent;
    recent.push(t);
    if (recent.length > period) recent.shift();
    if (st.run >= period) {
      let sum = 0;
      for (let k = 0; k < recent.length; k++) sum += recent[k]!;
      if (Number.isFinite(sum / period)) {
        st.a = sum / period;
        recent.length = 0;
      }
    }
  }
  return Number.isFinite(st.a) ? st.a : NaN;
}

/** `rsi` in the base bundle: Wilder gains and losses, each leg seeded on its own. */
interface Rsi {
  primed: boolean; last: number; gain: number; loss: number;
  gainSeeded: boolean; lossSeeded: boolean; run: number; recent: number[];
}

export const rsiState = (): Rsi => ({
  primed: false, last: NaN, gain: NaN, loss: NaN, gainSeeded: false, lossSeeded: false, run: 0, recent: [],
});

export function rsiStep(st: Rsi, x: number, period: number): number {
  const d = x - st.last;
  st.last = x;
  if (!st.primed) {
    st.primed = true;
    return NaN;
  }
  if (!Number.isFinite(d)) {
    st.run = 0;
    st.recent.length = 0;
    return NaN;
  }
  st.run++;
  const g = d > 0 ? d : 0;
  const l = d < 0 ? -d : 0;
  if (st.gainSeeded) st.gain = (st.gain * (period - 1) + g) / period;
  if (st.lossSeeded) st.loss = (st.loss * (period - 1) + l) / period;
  if (!st.gainSeeded || !st.lossSeeded) {
    const recent = st.recent;
    recent.push(d);
    if (recent.length > period) recent.shift();
    if (st.run >= period) {
      let gain = 0;
      let loss = 0;
      for (let k = 0; k < recent.length; k++) {
        const change = recent[k]!;
        if (change >= 0) gain += change;
        else loss -= change;
      }
      if (!st.gainSeeded && Number.isFinite(gain / period)) {
        st.gain = gain / period;
        st.gainSeeded = true;
      }
      if (!st.lossSeeded && Number.isFinite(loss / period)) {
        st.loss = loss / period;
        st.lossSeeded = true;
      }
    }
  }
  if (Number.isFinite(st.gain) && Number.isFinite(st.loss)) {
    const value = st.loss === 0 ? 100 : 100 - 100 / (1 + st.gain / st.loss);
    if (Number.isFinite(value)) return value;
  }
  return NaN;
}

/** `supertrend` in the base bundle: the band a bar ends on, and which side it is. */
interface Supertrend { atr: Wilder; upper: number; lower: number; st: number; close: number; started: boolean }

export const supertrendState = (): Supertrend => ({
  atr: wilder(), upper: NaN, lower: NaN, st: NaN, close: NaN, started: false,
});

/** The stop at bar `i`, with its direction in `out` (-1 up, 1 down); NaN where the batch form skips. */
export function supertrendStep(
  st: Supertrend, bars: readonly Bar[], i: number, period: number, multiplier: number, out: { direction: -1 | 1 },
): number {
  const a = atrStep(st.atr, trueRangeAt(bars, i), period);
  const bar = bars[i]!;
  const close = bar.close;
  if (!Number.isFinite(a) || !Number.isFinite(close)) return NaN;
  const hl2 = (bar.high + bar.low) / 2;
  const basicUpper = hl2 + multiplier * a;
  const basicLower = hl2 - multiplier * a;
  const finalUpper = !st.started ? basicUpper
    : basicUpper < st.upper || st.close > st.upper ? basicUpper : st.upper;
  const finalLower = !st.started ? basicLower
    : basicLower > st.lower || st.close < st.lower ? basicLower : st.lower;
  let value: number;
  if (!st.started || st.st === st.upper) {
    if (close <= finalUpper) { value = finalUpper; out.direction = 1; } else { value = finalLower; out.direction = -1; }
  } else if (close >= finalLower) { value = finalLower; out.direction = -1; } else { value = finalUpper; out.direction = 1; }
  st.upper = finalUpper;
  st.lower = finalLower;
  st.st = value;
  st.close = close;
  st.started = true;
  return value;
}

/** The parabolic stop and reverse in ./trend, one complete bar at a time. */
interface Sar {
  prev: Bar | null; prev2: Bar | null; rising: boolean; sar: number; ep: number; af: number;
}

export const sarState = (start: number): Sar => ({ prev: null, prev2: null, rising: false, sar: NaN, ep: NaN, af: start });

export function sarStep(st: Sar, bar: Bar, start: number, inc: number, max: number): number {
  if (!Number.isFinite(bar.high) || !Number.isFinite(bar.low) || !Number.isFinite(bar.close)) return NaN;
  const prev = st.prev;
  if (prev === null) {
    st.prev = bar;
    return NaN;
  }
  if (st.prev2 === null) {
    st.rising = bar.close >= prev.close;
    st.sar = st.rising ? prev.low : prev.high;
    st.ep = st.rising ? bar.high : bar.low;
    st.prev2 = prev;
    st.prev = bar;
    return st.sar;
  }
  const prev2 = st.prev2;
  let sar = st.sar + st.af * (st.ep - st.sar);
  if (st.rising && bar.low < sar) {
    st.rising = false; sar = Math.max(st.ep, bar.high); st.ep = bar.low; st.af = start;
  } else if (!st.rising && bar.high > sar) {
    st.rising = true; sar = Math.min(st.ep, bar.low); st.ep = bar.high; st.af = start;
  } else if (st.rising && bar.high > st.ep) {
    st.ep = bar.high; st.af = Math.min(max, st.af + inc);
  } else if (!st.rising && bar.low < st.ep) {
    st.ep = bar.low; st.af = Math.min(max, st.af + inc);
  }
  if (st.rising) sar = Math.min(sar, prev.low, prev2.low);
  else sar = Math.max(sar, prev.high, prev2.high);
  st.sar = sar;
  st.prev2 = prev;
  st.prev = bar;
  return sar;
}

/** `windowMean` in ./window-mean at one bar, reading the series through `at`. */
export function meanAt(at: (j: number) => number, i: number, period: number): number {
  if (i < period - 1) return NaN;
  if (period === 1) {
    const v = at(i);
    return Number.isFinite(v) ? (v === 0 ? 0 : v) : NaN;
  }
  let sum = 0;
  for (let j = i - period + 1; j <= i; j++) {
    const v = at(j);
    if (!Number.isFinite(v)) return NaN;
    sum += v;
  }
  return Number.isFinite(sum) ? sum / period : NaN;
}
