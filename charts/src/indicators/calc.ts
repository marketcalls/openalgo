/**
 * Pure calculation helpers shared by the Tier-1 indicator descriptors
 * (`openalgo-charts/indicators`). Every function returns an array the same
 * length as its input, with `NaN` in warmup slots: the line renderer breaks
 * across non-finite points and autoscale skips them, so a warmup gap draws as
 * nothing rather than as a spike to zero.
 *
 * `ema`, `rsi`, `atr`, `trueRange`, and `supertrend` are NOT re-implemented
 * here: they ship in the base bundle and the tier imports them from it.
 *
 * For helpers accepting missing-value options, omitted options use each
 * helper's documented default. Supplied options treat NaN and infinities as
 * missing. An empty options object selects chronological propagation.
 *
 * Varying window lengths must align with the source. Each bar uses its own
 * positive safe-integer length; NaN lengths produce gaps without discarding
 * source history. Other invalid numeric lengths throw RangeError, malformed
 * elements throw TypeError, and unequal array lengths throw RangeError.
 * Array lengths default to chronological propagation. With `skip`, changed
 * lengths reevaluate finite history even on missing source bars. These paths
 * use O(n + sum of evaluated window lengths) time and O(n) working storage.
 */

import { windowPolicy, type NumericalWindowOptions } from './statistics';
import { windowMean, windowSum } from './window-mean';

// An index read marked `!` sits in a loop whose bounds keep it inside the
// series; each block says what bounds it. The paths kept for unsupported
// scalar periods are the one exception, and say so: a fractional period
// indexes between elements, and the undefined that comes back computes as NaN
// and compares false, which is the historical output those paths preserve.

interface Observation { value: number; index: number }

/**
 * Opt-in windows require positive safe-integer periods and finite observations.
 * Keeping original indices lets skipped gaps age an extreme's bar offset.
 */
function observationWindows(
  values: readonly number[], period: number, options: NumericalWindowOptions,
  evaluate: (window: readonly Observation[], index: number) => number,
  previousOnly = false,
): number[] {
  const policy = windowPolicy(period, options);
  const out = new Array<number>(values.length).fill(NaN);
  const window: Observation[] = [];
  let missing = 0;
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    const finite = Number.isFinite(value);
    if (previousOnly && finite && window.length === period && missing === 0) out[i] = evaluate(window, i);
    if (policy === 'propagate' || finite) {
      window.push({ value, index: i });
      if (!finite) missing++;
      if (window.length > period && !Number.isFinite(window.shift()!.value)) missing--;
    }
    if (!previousOnly && window.length === period && missing === 0) out[i] = evaluate(window, i);
  }
  return out;
}

function checkedVaryingParameter(value: number, minimum: number, label: string, missingAllowed: boolean): void {
  if (typeof value !== 'number') throw new TypeError(`${label} must contain numbers`);
  if (missingAllowed && Number.isNaN(value)) return;
  if (!Number.isSafeInteger(value) || value < minimum) {
    throw new RangeError(`${label} must be a safe integer greater than or equal to ${minimum}`);
  }
}

function checkedParameterSeries(parameters: readonly number[], length: number, minimum: number, label: string): void {
  if (!Array.isArray(parameters)) throw new TypeError(`${label} must be an array`);
  if (parameters.length !== length) throw new RangeError(`${label} array length must match the source`);
  for (let i = 0; i < parameters.length; i++) checkedVaryingParameter(parameters[i], minimum, label, true);
}

/** Retained history lets later windows grow past an earlier, shorter window. */
function varyingWindows(
  values: readonly number[], periods: readonly number[], options: NumericalWindowOptions | undefined,
  evaluate: (window: readonly Observation[], index: number) => number,
  previousOnly = false,
): number[] {
  checkedParameterSeries(periods, values.length, 1, 'Window length');
  const policy = windowPolicy(1, options === undefined ? {} : options);
  const out = new Array<number>(values.length).fill(NaN);
  const history: Observation[] = [];
  let consecutive = 0;
  const observe = (value: number, index: number): void => {
    const finite = Number.isFinite(value);
    consecutive = finite ? consecutive + 1 : 0;
    if (policy === 'propagate' || finite) history.push({ value, index });
  };
  // `periods` was checked above to have one length per value.
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (!previousOnly) observe(value, i);
    const period = periods[i]!;
    if (!Number.isNaN(period) && period <= history.length &&
        (policy === 'skip' || period <= consecutive) && (!previousOnly || Number.isFinite(value))) {
      out[i] = evaluate(history.slice(history.length - period), i);
    }
    if (previousOnly) observe(value, i);
  }
  return out;
}

/** Exact integer units of 2^-1074 retain residuals after overflowing sums. */
function exactFiniteAverage(values: readonly number[], weights?: readonly number[]): number {
  const bits = new DataView(new ArrayBuffer(8));
  const fractionMask = (1n << 52n) - 1n;
  let numerator = 0n;
  let denominator = 0n;
  for (let i = 0; i < values.length; i++) {
    const weight = BigInt(weights?.[i] ?? 1);
    if (weight === 0n) continue;
    bits.setFloat64(0, values[i]!);
    const encoded = bits.getBigUint64(0);
    const exponent = Number((encoded >> 52n) & 0x7ffn);
    const fraction = encoded & fractionMask;
    const magnitude = exponent === 0 ? fraction : ((1n << 52n) | fraction) << BigInt(exponent - 1);
    numerator += (encoded >> 63n ? -magnitude : magnitude) * weight;
    denominator += weight;
  }
  return roundedBinaryAverage(numerator, denominator);
}

// Static file tracers can mistake accumulator initializers for final values.
// Parameters keep them from evaluating an unexecuted zero-denominator quotient.
function roundedBinaryAverage(numerator: bigint, denominator: bigint): number {
  const negative = numerator < 0n;
  const magnitude = negative ? -numerator : numerator;
  const wholeUnits = magnitude / denominator;
  const shift = Math.max(0, wholeUnits.toString(2).length - 53);
  const divisor = denominator << BigInt(shift);
  let significand = magnitude / divisor;
  const remainder = magnitude % divisor;
  if (2n * remainder > divisor || (2n * remainder === divisor && (significand & 1n) !== 0n)) {
    significand++;
  }
  const result = Number(significand) * 2 ** (shift - 1074);
  return negative ? -result : result;
}

/**
 * Nonnegative integer weights allow division after a compensated sum. Exported
 * for the tier's resumable kernels (./steppers), not from the tier entry.
 */
export function finiteAverage(values: readonly number[], weights?: readonly number[]): number {
  let sum = 0;
  let correction = 0;
  let denominator = 0;
  let minimum = Infinity;
  let maximum = -Infinity;
  for (let i = 0; i < values.length; i++) {
    const weight = weights?.[i] ?? 1;
    if (weight === 0) continue;
    minimum = Math.min(minimum, values[i]!);
    maximum = Math.max(maximum, values[i]!);
    denominator += weight;
    const term = values[i]! * weight;
    const next = sum + term;
    correction += Math.abs(sum) >= Math.abs(term) ? (sum - next) + term : (term - next) + sum;
    sum = next;
  }
  if (minimum === maximum) return minimum;
  const numerator = sum + correction;
  const average = Number.isFinite(numerator) && Number.isSafeInteger(denominator)
    ? numerator / denominator : exactFiniteAverage(values, weights);
  // A convex average is bounded by its participating observations.
  return Math.max(minimum, Math.min(maximum, average));
}

function observationMean(window: readonly Observation[]): number {
  return finiteAverage(window.map((item) => item.value));
}

/**
 * Center before scaling to retain spreads near a large common offset. Like
 * `observationExtreme`, it is handed only full windows, of at least one
 * observation: both window builders require a period of one or more.
 */
function observationDeviation(window: readonly Observation[], squared: boolean): number {
  const origin = window[0]!.value;
  let maximum = 0;
  let spread = 0;
  let deltas = window.map(({ value }) => {
    maximum = Math.max(maximum, Math.abs(value));
    const delta = value - origin;
    spread = Math.max(spread, Math.abs(delta));
    return delta;
  });
  if (spread === 0) return 0;
  // Binary scaling also preserves subnormal inputs before final rounding.
  const scale = 2 ** Math.min(1023, Math.floor(Math.log2(Number.isFinite(spread) ? spread : maximum)));
  deltas = Number.isFinite(spread)
    ? deltas.map((delta) => delta / scale)
    : window.map(({ value }) => value / scale - origin / scale);
  const center = finiteAverage(deltas);
  const meanDeviation = finiteAverage(deltas.map((delta) => {
    const distance = Math.abs(delta - center);
    return squared ? distance * distance : distance;
  }));
  // Both population deviations are bounded by the largest absolute input.
  return Math.min(maximum, (squared ? Math.sqrt(meanDeviation) : meanDeviation) * scale);
}

function observationExtreme(window: readonly Observation[], high: boolean): Observation {
  let best = window[0]!;
  for (let i = 1; i < window.length; i++) {
    const item = window[i]!;
    if (high ? item.value >= best.value : item.value <= best.value) best = item;
  }
  return best;
}

function observedSmoothing(
  values: readonly number[], period: number, options: NumericalWindowOptions, currentWeight: number,
): number[] {
  const policy = windowPolicy(period, options);
  const out = new Array<number>(values.length).fill(NaN);
  let count = 0;
  const seed: number[] = [];
  let previous = NaN;
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (!Number.isFinite(value)) {
      if (policy === 'propagate') { count = 0; seed.length = 0; previous = NaN; }
      else if (count === period) out[i] = previous;
      continue;
    }
    if (count < period) {
      seed.push(value);
      if (++count < period) continue;
      previous = finiteAverage(seed);
      seed.length = 0;
    } else previous = finiteAverage([previous, value], [period - 1, currentWeight]);
    out[i] = previous;
  }
  return out;
}

/**
 * Simple moving average. Valid scalar windows without options sum oldest first
 * afresh, then divide once. Missing or overflowing sums produce NaN and recover
 * when they expire. This uses O(n * period) time and O(1) extra working storage.
 * Unsupported scalar periods retain their historical behavior.
 * Supplied `skip` collects period finite observations and holds across gaps;
 * `propagate` (also the default for {}) requires a complete chronological
 * window. Warmup is NaN. Option-path periods must be positive safe integers;
 * invalid periods throw RangeError and malformed options throw TypeError.
 */
export function sma(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths use each current window; NaN lengths give gaps. Arrays default to propagation. */
export function sma(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function sma(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options, observationMean);
  if (options !== undefined) return observationWindows(values, period, options, observationMean);
  if (Number.isSafeInteger(period) && period > 0) return windowMean(values, period);
  // Unsupported scalar periods retain their historical behavior. Valid windows
  // above sum afresh, so an expired prefix cannot invent a numerical signal.
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // The running sum must never absorb a non-finite value: `sum += NaN` poisons
  // it permanently, and subtracting the NaN back out when it leaves the window
  // does not restore it (NaN - NaN is NaN). Any input with a warmup gap -- an
  // indicator chained onto another -- would then be NaN for the whole series.
  // So sum only the finite values and count the rest. A fractional period's
  // `gone` falls between elements, reads undefined and counts as missing; only
  // a finite reading, which is present, is subtracted.
  let sum = 0;
  let bad = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i]!;
    if (Number.isFinite(v)) sum += v;
    else bad += 1;
    if (i >= period) {
      const gone = values[i - period];
      if (Number.isFinite(gone)) sum -= gone!;
      else bad -= 1;
    }
    if (i >= period - 1) out[i] = bad === 0 ? sum / period : NaN;
  }
  return out;
}

/**
 * Linearly weighted average, newest observation carrying weight period.
 * Valid scalar defaults sum weighted terms oldest first and omit nonfinite
 * results. Supplied `skip` weights period
 * finite observations and holds across gaps; `propagate` requires a full
 * chronological window. Warmup is NaN. The option path validates a positive
 * safe-integer period and a missing policy, throwing RangeError or TypeError.
 */
export function wma(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths weight the newest selected observation most; NaN lengths give gaps. */
export function wma(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function wma(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window) => finiteAverage(window.map((item) => item.value), window.map((_, i) => i + 1)));
  if (options !== undefined) return observationWindows(values, period, options, (window) => {
    return finiteAverage(window.map((item) => item.value), window.map((_, i) => i + 1));
  });
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const denom = (period * (period + 1)) / 2;
  const chronological = Number.isSafeInteger(period);
  // A whole period reads `i - back` in [0, i]; a fractional one reads between
  // elements (see the note at the top).
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) {
      const back = chronological ? period - 1 - k : k;
      acc += values[i - back]! * (period - back);
    }
    const value = acc / denom;
    if (!chronological || Number.isFinite(value)) out[i] = value;
  }
  return out;
}

/** Seed from a current finite suffix; later source gaps leave running state intact. */
function seededSmoothing(values: readonly number[], period: number, exponential: boolean): number[] {
  const out = new Array<number>(values.length).fill(NaN);
  if (values.length < period) return out;
  const weight = 2 / (period + 1);
  let consecutive = 0, running = NaN, seeded = false;
  // The seed window starts at `i + 1 - period`, which `period` consecutive
  // values before and at `i` keep at zero or above.
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (!Number.isFinite(value)) { consecutive = 0; continue; }
    if (!seeded) {
      if (++consecutive < period) continue;
      let sum = 0;
      for (let at = i + 1 - period; at <= i; at++) sum += values[at]!;
      const mean = sum / period;
      if (!Number.isFinite(mean)) continue;
      running = mean === 0 ? 0 : mean;
      seeded = true;
    } else {
      // Overflow from an actual update remains committed. It is not a new seed.
      running = exponential ? value * weight + running * (1 - weight)
        : (running * (period - 1) + value) / period;
    }
    if (Number.isFinite(running)) out[i] = running === 0 ? 0 : running;
  }
  return out;
}

/**
 * Wilder's smoothing (RMA): seed from the first complete finite window,
 * then `(prev * (period - 1) + v) / period`. Valid scalar defaults retry
 * nonfinite seeds, leave a gap for missing inputs and retain seeded state.
 * Running overflow is unavailable without restarting. Supplied `skip` seeds from period
 * finite observations and holds state across gaps. `propagate` clears state on
 * a missing input and reseeds after period consecutive finite observations.
 * Warmup is NaN. The option path requires a positive safe-integer period and
 * valid policy, throwing RangeError or TypeError respectively.
 */
export function rma(values: readonly number[], period: number, options?: NumericalWindowOptions): number[] {
  if (options !== undefined) return observedSmoothing(values, period, options, 1);
  if (Number.isSafeInteger(period) && period > 0) return seededSmoothing(values, period, false);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // Only an unsupported period gets here. The seed reads whole indices below
  // `period`, all present as `n >= period`; the recursion starts at a
  // fractional index and so reads between elements (see the note at the top).
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i]!;
  let prev = sum / period;
  out[period - 1] = prev;
  for (let i = period; i < n; i++) {
    prev = (prev * (period - 1) + values[i]!) / period;
    out[i] = prev;
  }
  return out;
}

/**
 * Population standard deviation. Valid scalar defaults accumulate squared
 * deviations oldest first and omit nonfinite results.
 * Supplied `skip` uses period finite observations and holds across gaps;
 * `propagate` requires a full chronological window. Ties retain multiplicity;
 * warmup is NaN. Invalid option-path periods throw RangeError, malformed
 * options TypeError. A period must be a positive safe integer.
 */
export function stdev(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths select the current population; NaN lengths give gaps. Arrays default to propagation. */
export function stdev(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function stdev(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window) => observationDeviation(window, true));
  if (options !== undefined) return observationWindows(values, period, options,
    (window) => observationDeviation(window, true));
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const means = sma(values, period);
  const chronological = Number.isSafeInteger(period);
  // A whole period reads inside [0, i] of both series; a fractional one reads
  // between elements (see the note at the top).
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    const m = means[i]!;
    for (let k = 0; k < period; k++) {
      const d = values[i - (chronological ? period - 1 - k : k)]! - m;
      acc += d * d;
    }
    const value = Math.sqrt(acc / period);
    if (!chronological || Number.isFinite(value)) out[i] = value;
  }
  return out;
}

/**
 * Rolling maximum. Omitted options preserve legacy warmup and gap behavior.
 * Supplied `skip` searches period finite observations and holds across gaps;
 * `propagate` requires period chronological finite bars. Insufficient or
 * all-missing history is NaN. Invalid option-path periods throw RangeError;
 * malformed policies throw TypeError. Periods must be positive safe integers.
 */
export function highest(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths select the current maximum window; NaN lengths give gaps. */
export function highest(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function highest(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window) => observationExtreme(window, true).value);
  if (options !== undefined) return observationWindows(values, period, options,
    (window) => observationExtreme(window, true).value);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  // `i - k` stays in [0, i] for a whole period; a fractional one reads between
  // elements, which compare false (see the note at the top). So in `lowest`.
  for (let i = period - 1; i < n; i++) {
    let m = -Infinity;
    for (let k = 0; k < period; k++) if (values[i - k]! > m) m = values[i - k]!;
    out[i] = m;
  }
  return out;
}

/**
 * Rolling minimum. Omitted options preserve legacy warmup and gap behavior.
 * Supplied `skip` searches period finite observations and holds across gaps;
 * `propagate` requires period chronological finite bars. Insufficient or
 * all-missing history is NaN. Invalid option-path periods throw RangeError;
 * malformed policies throw TypeError. Periods must be positive safe integers.
 */
export function lowest(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths select the current minimum window; NaN lengths give gaps. */
export function lowest(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function lowest(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window) => observationExtreme(window, false).value);
  if (options !== undefined) return observationWindows(values, period, options,
    (window) => observationExtreme(window, false).value);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  for (let i = period - 1; i < n; i++) {
    let m = Infinity;
    for (let k = 0; k < period; k++) if (values[i - k]! < m) m = values[i - k]!;
    out[i] = m;
  }
  return out;
}

/** NaN to null, so a warmup slot serialises as an explicit gap. */
export function nulls(values: readonly number[]): (number | null)[] {
  const out = new Array<number | null>(values.length);
  for (let i = 0; i < values.length; i++) {
    const v = values[i]!;
    out[i] = Number.isFinite(v) ? v : null;
  }
  return out;
}

// ── the reference-compatible helpers ───────────────────────────────────────────────
// These built-in indicators are ports of well-known published formulas, and
// two of those differ from what this file already exports. They are added here
// rather than by changing the originals, which are published API with their own
// documented behaviour (`ema` matches `openalgo.ta`, not the reference).

/**
 * EMA seeded with an SMA, then smoothed with alpha=2/(period+1). Valid scalar
 * defaults seed from the first complete finite window, retry nonfinite seeds,
 * and emit gaps for missing inputs while retaining seeded state. A nonfinite
 * running update stays committed, without restarting. Supplied
 * `skip` seeds from period finite observations and holds state across gaps.
 * `propagate` clears state on any missing input and reseeds with period
 * consecutive finite observations. Warmup is NaN. Invalid option-path
 * periods throw RangeError; malformed options throw TypeError. Periods must
 * be positive safe integers.
 */
export function smaSeededEma(values: readonly number[], period: number, options?: NumericalWindowOptions): number[] {
  if (options !== undefined) return observedSmoothing(values, period, options, 2);
  if (Number.isSafeInteger(period) && period > 0) return seededSmoothing(values, period, true);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // Only an unsupported period gets here, read as in `rma`.
  let sum = 0;
  for (let i = 0; i < period; i++) sum += values[i]!;
  let prev = sum / period;
  out[period - 1] = prev;
  const k = 2 / (period + 1);
  for (let i = period; i < n; i++) {
    prev = values[i]! * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** the reference `change(src, n)`: `src - src[n]`. NaN for the first `n` bars. */
export function change(values: readonly number[], n = 1): number[] {
  const len = values.length;
  const out = new Array<number>(len).fill(NaN);
  // A whole `n` of zero or more reads inside [0, i], as in `roc`; any other
  // `n` reads outside the series (see the note at the top).
  for (let i = n; i < len; i++) out[i] = values[i]! - values[i - n]!;
  return out;
}

/** the reference `roc`: `100 * (src - src[n]) / src[n]`. NaN for the first `n` bars. */
export function roc(values: readonly number[], n: number): number[] {
  const len = values.length;
  const out = new Array<number>(len).fill(NaN);
  if (n <= 0) return out;
  for (let i = n; i < len; i++) {
    const base = values[i - n]!;
    out[i] = base === 0 ? NaN : (100 * (values[i]! - base)) / base;
  }
  return out;
}

/**
 * Mean absolute deviation from the average. Valid scalar defaults accumulate
 * deviations oldest first and omit nonfinite results.
 * Supplied `skip` uses period finite observations and holds across
 * gaps; `propagate` requires a full chronological window. Ties retain their
 * multiplicity and warmup is NaN. Invalid option-path periods throw RangeError,
 * malformed options TypeError. Periods must be positive safe integers.
 */
export function dev(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths select the current deviation window; NaN lengths give gaps. */
export function dev(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function dev(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window) => observationDeviation(window, false));
  if (options !== undefined) return observationWindows(values, period, options,
    (window) => observationDeviation(window, false));
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  const means = sma(values, period);
  const chronological = Number.isSafeInteger(period);
  // Read as in `stdev`.
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) acc += Math.abs(values[i - (chronological ? period - 1 - k : k)]! - means[i]!);
    const value = acc / period;
    if (!chronological || Number.isFinite(value)) out[i] = value;
  }
  return out;
}

/**
 * Percentage of period previous values less than or equal to the current
 * subject, excluding the subject itself. Omitted options preserve legacy
 * behavior. Supplied `skip` collects previous finite observations; `propagate`
 * requires a full previous chronological window. A missing subject or
 * insufficient history produces NaN under either policy. Equality counts.
 * Invalid option-path periods throw RangeError; malformed policies throw
 * TypeError. Periods must be positive safe integers.
 */
export function percentRank(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths count previous observations. A missing current subject or length gives NaN. */
export function percentRank(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function percentRank(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  // The window builders hand `evaluate` the index of the bar they are on.
  if (typeof period !== 'number') return varyingWindows(values, period, options, (window, index) => {
    let count = 0;
    for (const item of window) if (item.value <= values[index]!) count++;
    return count * 100 / window.length;
  }, true);
  if (options !== undefined) return observationWindows(values, period, options, (window, index) => {
    let count = 0;
    for (const item of window) if (item.value <= values[index]!) count++;
    return count * 100 / period;
  }, true);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0) return out;
  // `i - k` stays in [0, i) for a whole period; a fractional one reads between
  // elements, which compare false (see the note at the top).
  for (let i = period; i < n; i++) {
    let count = 0;
    for (let k = 1; k <= period; k++) if (values[i - k]! <= values[i]!) count += 1;
    out[i] = (count * 100) / period;
  }
  return out;
}

/**
 * the reference `alma`: Gaussian-weighted MA, `offset` 0..1 and `sigma` > 0. A period
 * that is not a whole number of 1 or more gives NaN throughout.
 */
export function alma(
  values: readonly number[],
  period: number,
  offset: number,
  sigma: number,
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  // The kernel is built per window position, so it needs a whole period.
  if (!Number.isSafeInteger(period) || period <= 0 || sigma <= 0 || n < period) return out;
  const m = offset * (period - 1);
  const s = period / sigma;
  // The kernel depends only on the window position, so it is built once.
  const weights = new Array<number>(period);
  let norm = 0;
  for (let i = 0; i < period; i++) {
    const w = Math.exp(-((i - m) * (i - m)) / (2 * s * s));
    weights[i] = w;
    norm += w;
  }
  if (norm === 0) return out;
  // Only a whole period gets here, so the window is [i - period + 1, i] and
  // `k` indexes the kernel.
  for (let i = period - 1; i < n; i++) {
    let acc = 0;
    for (let k = 0; k < period; k++) acc += values[i - (period - 1 - k)]! * weights[k]!;
    out[i] = acc / norm;
  }
  return out;
}

/** the reference `vwma`: `sma(src * volume, len) / sma(volume, len)`. */
export function vwma(
  values: readonly number[],
  volumes: readonly number[],
  period: number,
): number[] {
  const n = values.length;
  const pv = new Array<number>(n);
  for (let i = 0; i < n; i++) pv[i] = values[i]! * (volumes[i] ?? 0);
  const num = sma(pv, period);
  const den = sma(volumes, period);
  const out = new Array<number>(n).fill(NaN);
  // `num` has n values. A volume series shorter than the values leaves `den`
  // short too, and past its end the division reads undefined and gives NaN.
  for (let i = 0; i < n; i++) out[i] = den[i] === 0 ? NaN : num[i]! / den[i]!;
  return out;
}

/**
 * Highest-value bar offset, zero for current and negative into history; ties
 * choose the latest bar. Omitted options preserve legacy behavior. Supplied
 * `skip` searches period finite observations and retains original bar indices,
 * so an offset can extend beyond period-1 and ages across missing current bars.
 * `propagate` requires period chronological finite bars. Warmup and all-missing
 * history are NaN. Invalid option-path periods throw RangeError; malformed
 * policies throw TypeError. Periods must be positive safe integers.
 */
export function highestBars(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths retain original offsets and latest ties; NaN lengths give gaps. */
export function highestBars(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function highestBars(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window, index) => observationExtreme(window, true).index - index);
  if (options !== undefined) return observationWindows(values, period, options,
    (window, index) => observationExtreme(window, true).index - index);
  return extremeBars(values, period, true);
}

/**
 * Lowest-value bar offset, zero for current and negative into history; ties
 * choose the latest bar. Omitted options preserve legacy behavior. Supplied
 * `skip` searches period finite observations using their original indices;
 * offsets age across gaps. `propagate` requires a full chronological window.
 * Warmup and all-missing history are NaN. Invalid option-path periods throw
 * RangeError; malformed policies throw TypeError. Periods must be positive
 * safe integers.
 */
export function lowestBars(values: readonly number[], period: number, options?: NumericalWindowOptions): number[];
/** Bar-aligned lengths retain original offsets and latest ties; NaN lengths give gaps. */
export function lowestBars(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[];
export function lowestBars(values: readonly number[], period: number | readonly number[], options?: NumericalWindowOptions): number[] {
  if (typeof period !== 'number') return varyingWindows(values, period, options,
    (window, index) => observationExtreme(window, false).index - index);
  if (options !== undefined) return observationWindows(values, period, options,
    (window, index) => observationExtreme(window, false).index - index);
  return extremeBars(values, period, false);
}

function extremeBars(values: readonly number[], period: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // Read as in `highest`.
  for (let i = period - 1; i < n; i++) {
    let best = values[i]!;
    let at = 0;
    for (let k = 1; k < period; k++) {
      const v = values[i - k]!;
      // Ties resolve to the most recent bar, matching the reference: the strict
      // comparison leaves `at` on the newer index when values are equal.
      if (wantHigh ? v > best : v < best) { best = v; at = k; }
    }
    // Normalised so a current-bar extreme is +0, not the -0 that negating a
    // zero offset produces. Arithmetic is unaffected, but -0 leaks into
    // Object.is comparisons and JSON round-trips.
    out[i] = at === 0 ? 0 : -at;
  }
  return out;
}

/**
 * Fresh oldest-first sum over each complete finite window; NaN on warmup or
 * overflow. Missing values expire with the window. Valid integer periods use
 * O(n * period) time and O(1) extra working storage, excluding the result.
 * Unsupported scalar periods retain their historical behavior.
 */
export function rollingSum(values: readonly number[], period: number): number[] {
  if (Number.isSafeInteger(period) && period > 0) return windowSum(values, period);
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  // Only an unsupported period gets here: `i - period` falls between elements
  // (see the note at the top).
  let acc = 0;
  for (let i = 0; i < n; i++) {
    acc += values[i]!;
    if (i >= period) acc -= values[i - period]!;
    if (i >= period - 1) out[i] = acc;
  }
  return out;
}

/** the reference `cum`: running total from the first bar. Non-finite terms count as 0. */
export function cumulative(values: readonly number[]): number[] {
  const n = values.length;
  const out = new Array<number>(n);
  let acc = 0;
  for (let i = 0; i < n; i++) {
    const v = values[i]!;
    if (Number.isFinite(v)) acc += v;
    out[i] = acc;
  }
  return out;
}

/**
 * the reference `linreg`: the least-squares regression line fitted over the last
 * `period` values, evaluated `offset` bars back from its right-hand end.
 *
 * x runs 0 (oldest bar in the window) to period-1 (current bar), so the value
 * at the current bar is `intercept + slope * (period - 1)`. A positive `offset`
 * steps back down that line, which is how LSMA's offset input shifts the plot
 * without recomputing the fit.
 */
export function linreg(values: readonly number[], period: number, offset = 0): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 1 || n < period) return out;
  // x is the same window every bar, so its sums are loop-invariant.
  const sumX = ((period - 1) * period) / 2;
  const sumXSqr = ((period - 1) * period * (2 * period - 1)) / 6;
  const denom = period * sumXSqr - sumX * sumX;
  if (denom === 0) return out;
  // A whole period reads [i - period + 1, i]; a fractional one reads between
  // elements (see the note at the top).
  for (let i = period - 1; i < n; i++) {
    let sumY = 0;
    let sumXY = 0;
    for (let k = 0; k < period; k++) {
      const y = values[i - (period - 1 - k)]!; // k = 0 is the oldest bar
      sumY += y;
      sumXY += y * k;
    }
    const slope = (period * sumXY - sumX * sumY) / denom;
    const intercept = (sumY - slope * sumX) / period;
    out[i] = intercept + slope * (period - 1 - offset);
  }
  return out;
}

/** the reference `swma`: the fixed 4-bar symmetrically weighted average, 1/2/2/1 over 6. */
export function swma(values: readonly number[]): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  for (let i = 3; i < n; i++) {
    out[i] = (values[i - 3]! + 2 * values[i - 2]! + 2 * values[i - 1]! + values[i]!) / 6;
  }
  return out;
}

/**
 * the reference `stoch(source, high, low, length)`. Note the three series are
 * independent: Stochastic RSI passes the RSI in for all three, which is why
 * this cannot just take bars.
 */
export function stoch(
  source: readonly number[],
  high: readonly number[],
  low: readonly number[],
  period: number,
): number[] {
  const n = source.length;
  const out = new Array<number>(n).fill(NaN);
  const hi = highest(high, period);
  const lo = lowest(low, period);
  // `hi` and `lo` are as long as `high` and `low`, which run alongside
  // `source`; one shorter than it reads undefined past its end, giving NaN.
  for (let i = 0; i < n; i++) {
    const span = hi[i]! - lo[i]!;
    out[i] = span === 0 ? NaN : (100 * (source[i]! - lo[i]!)) / span;
  }
  return out;
}

/**
 * the reference `percentile_nearest_rank`. The nearest-rank method returns an
 * actual member of the window rather than interpolating between two, so a
 * 50th percentile over an even-length window is the upper of the two middles,
 * not their mean. That difference is visible on Median's default length of 3.
 * A percentage above 100, or NaN, has no reading.
 */
export function percentileNearestRank(
  values: readonly number[],
  period: number,
  percentage: number,
): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 0 || n < period) return out;
  for (let i = period - 1; i < n; i++) {
    const win = values.slice(i - period + 1, i + 1);
    if (win.some((v) => !Number.isFinite(v))) continue;
    win.sort((a, b) => a - b);
    const rank = Math.max(1, Math.ceil((percentage / 100) * period));
    // A percentage up to 100 ranks inside the window (below 0 ranks the
    // lowest). One above 100, or NaN, ranks past it and has no reading.
    out[i] = win[rank - 1] ?? NaN;
  }
  return out;
}

/**
 * the reference `correlation`: population Pearson correlation of two series over
 * `period`. Each window takes two passes, oldest first: both means are finished
 * before any deviation is formed, then
 * `(cross / period) / (sqrt(squaresA / period) * sqrt(squaresB / period))`.
 * A window with a missing value or an overflowing step is NaN, and so is one
 * whose deviations are all exactly zero, such as three bars of 5. A flat window
 * whose mean is inexact is not caught by that: three bars of 0.1 average to
 * slightly more than 0.1, the deviations are a few units in the last place, and
 * the window reads what that arithmetic gives, as the reference does. Against a
 * bar index that is exactly 0; against another series it is within rounding of
 * 0. A period that is not a whole number above 1 gives NaN throughout, as it
 * did before.
 */
export function correlation(
  a: readonly number[],
  b: readonly number[],
  period: number,
): number[] {
  const n = a.length;
  const out = new Array<number>(n).fill(NaN);
  if (period <= 1 || n < period) return out;
  // A whole period reads [i - period + 1, i] of `a`, and of `b` alongside it;
  // a fractional period, or a shorter `b`, reads undefined and so NaN.
  for (let i = period - 1; i < n; i++) {
    // Summing squares and cross products in one pass and subtracting at the
    // end cancels catastrophically at ordinary price levels: at 1e5 with 0.01
    // moves it was off by about one percent, and at 1e9 it had no value.
    let sumA = 0, sumB = 0, cross = 0, squaresA = 0, squaresB = 0;
    for (let k = i - period + 1; k <= i; k++) { sumA += a[k]!; sumB += b[k]!; }
    const meanA = sumA / period;
    const meanB = sumB / period;
    for (let k = i - period + 1; k <= i; k++) {
      const x = a[k]! - meanA;
      const y = b[k]! - meanB;
      cross += x * y; squaresA += x * x; squaresB += y * y;
    }
    const value = (cross / period) / (Math.sqrt(squaresA / period) * Math.sqrt(squaresB / period));
    if (Number.isFinite(value)) out[i] = value;
  }
  return out;
}

/**
 * the reference `cci`: `(src - sma) / (0.015 * dev)`, where `dev` is the mean absolute deviation.
 * A flat window (a deviation of exactly 0) has no reading here. The built-in
 * CCI study prints 0 on such a window instead, so a study ported onto this
 * function shows a gap where the built-in shows 0.
 */
export function cci(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  const mean = sma(values, period);
  const md = dev(values, period);
  // `mean` and `md` have one value per input.
  for (let i = 0; i < n; i++) out[i] = md[i] === 0 ? NaN : (values[i]! - mean[i]!) / (0.015 * md[i]!);
  return out;
}

// Kernels two built-ins share, kept out of the tier's public exports.

/**
 * Residual spread of `values` about the least squares line fitted to the last
 * `period` of them: `sqrt((Syy - Sxy^2 / Sxx) / (period - 2))`. The divisor is
 * `period - 2`, not `period` or `period - 1`, because the fitted slope and
 * intercept each consume a degree of freedom, and that is what makes this a
 * standard *error* rather than a standard deviation. x runs 1 to `period` over
 * the window, oldest last, but only its spacing reaches the answer. `period` is
 * a whole number; below 3 there is no reading.
 */
export function standardError(values: readonly number[], period: number): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  if (period < 3 || n < period) return out;
  const meanX = (period + 1) / 2;
  // x is the same ladder in every window, so its spread is a constant.
  let sxx = 0;
  for (let k = 0; k < period; k++) sxx += (meanX - k - 1) * (meanX - k - 1);
  // Each window is [i - period + 1, i].
  for (let i = period - 1; i < n; i++) {
    let sumY = 0;
    for (let k = 0; k < period; k++) sumY += values[i - k]!;
    const meanY = sumY / period;
    let syy = 0;
    let sxy = 0;
    for (let k = 0; k < period; k++) {
      const dy = meanY - values[i - k]!;
      syy += dy * dy;
      sxy += (meanX - k - 1) * dy;
    }
    out[i] = Math.sqrt((syy - (sxy * sxy) / sxx) / (period - 2));
  }
  return out;
}

/**
 * Money Flow Index from per-bar positive and negative flows, first reading at
 * index `period`: each window sums its flows afresh, a window holding a
 * missing flow or overflowing has no reading, and a window with no negative
 * flow pins at 100. How a bar's flows are formed stays with each study.
 */
export function mfiFromFlows(positive: readonly number[], negative: readonly number[], period: number): number[] {
  const n = positive.length;
  const out = new Array<number>(n).fill(NaN);
  const up = windowSum(positive, period);
  const down = windowSum(negative, period);
  // Both sums hold one value per bar.
  for (let i = period; i < n; i++) {
    const u = up[i]!;
    const d = down[i]!;
    if (!Number.isFinite(u) || !Number.isFinite(d)) continue;
    out[i] = d === 0 ? 100 : 100 - 100 / (1 + u / d);
  }
  return out;
}

/**
 * the reference `pivothigh` / `pivotlow`. A pivot is confirmed `right` bars
 * after it happens, so the answer lands on the confirming bar and refers to the
 * value `right` bars back. Comparisons are strict on both sides, so a tie is
 * not a pivot.
 */
export function pivotHigh(values: readonly number[], left: number, right: number): number[];
/**
 * Array widths align with the source and are read on the confirmation bar.
 * NaN array elements give gaps; scalar companions and other array elements
 * must be nonnegative safe integers. Mismatched array lengths throw RangeError.
 * Zero widths are valid. Finite neighbors and strict comparisons are required.
 * Results stay on confirmation bars, including repeated confirmations of one
 * candidate. Invalid numbers throw RangeError; malformed elements TypeError.
 */
export function pivotHigh(values: readonly number[], left: number | readonly number[], right: number | readonly number[]): number[];
export function pivotHigh(values: readonly number[], left: number | readonly number[], right: number | readonly number[]): number[] {
  if (typeof left !== 'number' || typeof right !== 'number') return varyingPivot(values, left, right, true);
  return pivot(values, left, right, true);
}

export function pivotLow(values: readonly number[], left: number, right: number): number[];
/**
 * Array widths follow pivotHigh's validation and confirmation placement, with
 * strictly lower candidates. Missing widths or neighbors give NaN. Both widths
 * are read from the current confirmation bar, even if the candidate repeats.
 */
export function pivotLow(values: readonly number[], left: number | readonly number[], right: number | readonly number[]): number[];
export function pivotLow(values: readonly number[], left: number | readonly number[], right: number | readonly number[]): number[] {
  if (typeof left !== 'number' || typeof right !== 'number') return varyingPivot(values, left, right, false);
  return pivot(values, left, right, false);
}

function varyingPivot(
  values: readonly number[], left: number | readonly number[], right: number | readonly number[], wantHigh: boolean,
): number[] {
  for (const [label, widths] of [['Left pivot width', left], ['Right pivot width', right]] as const) {
    if (typeof widths === 'number') checkedVaryingParameter(widths, 0, label, false);
    else checkedParameterSeries(widths, values.length, 0, label);
  }
  const out = new Array<number>(values.length).fill(NaN);
  // The widths were checked above: whole, zero or more, or NaN, and a width
  // array has one per value. Past the history check the scan stays in [0, i].
  for (let i = 0; i < values.length; i++) {
    const before = typeof left === 'number' ? left : left[i]!;
    const after = typeof right === 'number' ? right : right[i]!;
    // Check available history before adding widths or scanning a large span.
    if (Number.isNaN(before) || Number.isNaN(after) || after > i || before > i - after) continue;
    const candidate = i - after;
    const value = values[candidate]!;
    if (!Number.isFinite(value)) continue;
    let extreme = true;
    for (let index = candidate - before; index <= i && extreme; index++) {
      if (index === candidate) continue;
      const neighbor = values[index]!;
      if (!Number.isFinite(neighbor) || (wantHigh ? neighbor >= value : neighbor <= value)) extreme = false;
    }
    if (extreme) out[i] = value;
  }
  return out;
}

function pivot(values: readonly number[], left: number, right: number, wantHigh: boolean): number[] {
  const n = values.length;
  const out = new Array<number>(n).fill(NaN);
  // Whole widths of zero or more keep every read in [i - left - right, i].
  // Scalar widths are not checked, and any other width reads undefined, which
  // is not finite and so makes no pivot.
  for (let i = left + right; i < n; i++) {
    const at = i - right;
    const v = values[at]!;
    if (!Number.isFinite(v)) continue;
    let ok = true;
    for (let k = 1; k <= left && ok; k++) {
      const o = values[at - k]!;
      if (!Number.isFinite(o) || (wantHigh ? o >= v : o <= v)) ok = false;
    }
    for (let k = 1; k <= right && ok; k++) {
      const o = values[at + k]!;
      if (!Number.isFinite(o) || (wantHigh ? o >= v : o <= v)) ok = false;
    }
    if (ok) out[i] = v;
  }
  return out;
}

/** the reference `barssince`: bars elapsed since `cond` was last true, NaN before the first. */
export function barsSince(cond: readonly boolean[]): number[] {
  const n = cond.length;
  const out = new Array<number>(n).fill(NaN);
  let last = -1;
  for (let i = 0; i < n; i++) {
    if (cond[i]) last = i;
    if (last >= 0) out[i] = i - last;
  }
  return out;
}

/**
 * the reference `valuewhen(cond, source, occurrence)`: the value of `source` the
 * n-th most recent time `cond` was true, counting the current bar. Occurrence 0
 * is the latest. An occurrence that is not a whole number of 0 or more gives
 * NaN throughout, and so does a hit past the end of a shorter `source`.
 */
export function valueWhen(
  cond: readonly boolean[],
  source: readonly number[],
  occurrence: number,
): number[] {
  const n = cond.length;
  const out = new Array<number>(n).fill(NaN);
  // Only a whole occurrence of zero or more counts back through the hits.
  if (!Number.isSafeInteger(occurrence) || occurrence < 0) return out;
  const hits: number[] = [];
  // `at` stays inside `hits`. Each hit indexes `source` alongside `cond`, and
  // one past the end of a shorter `source` has no reading.
  for (let i = 0; i < n; i++) {
    if (cond[i]) hits.push(i);
    const at = hits.length - 1 - occurrence;
    if (at >= 0) out[i] = source[hits[at]!] ?? NaN;
  }
  return out;
}
