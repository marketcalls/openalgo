/**
 * Array-based statistics with explicit observation windows. Results keep the
 * input length and never mutate inputs. NaN and infinities are missing values.
 * Numeric warmup and undefined statistics are NaN; boolean warmup is false.
 */

/** Missing-value policy shared by numerical statistics and predicates. */
export interface NumericalWindowOptions {
  /**
   * `propagate` (default) uses chronological windows and rejects missing terms.
   * `skip` uses finite observations, preserving their original order. Rolling
   * numeric results hold across missing bars once the window is full.
   * Predicates require a finite current observation and otherwise return false.
   */
  missing?: 'propagate' | 'skip';
}

/** Estimator choice for {@link rollingVariance}. */
export interface RollingVarianceOptions extends NumericalWindowOptions {
  /** Divide by period-1 for a sample, or period for the default population. */
  sample?: boolean;
}

/**
 * The one check for a window period and a `NumericalWindowOptions`, shared by
 * these statistics and the option path of ./calc, so one mistake gets one
 * error whichever family it reaches: RangeError for a period that is not a
 * positive safe integer (`undefined` when the helper takes none), TypeError
 * for options that are not an object or name another policy.
 */
export function windowPolicy(period: number | undefined, options: NumericalWindowOptions): 'propagate' | 'skip' {
  if (period !== undefined && (!Number.isSafeInteger(period) || period <= 0)) {
    throw new RangeError('Missing-value window period must be a positive safe integer');
  }
  if (options === null || typeof options !== 'object' || Array.isArray(options)) {
    throw new TypeError('Missing-value options must be an object');
  }
  const missing = options.missing === undefined ? 'propagate' : options.missing;
  if (missing !== 'propagate' && missing !== 'skip') {
    throw new TypeError('Missing-value policy must be propagate or skip');
  }
  return missing;
}

/** `evaluate` is handed exactly `period` finite values, so it may read any index below `period`. */
function rolling(
  values: readonly number[],
  period: number,
  options: NumericalWindowOptions,
  evaluate: (window: readonly number[]) => number,
): number[] {
  const missing = windowPolicy(period, options);
  const out = new Array<number>(values.length).fill(NaN);
  const window: number[] = [];
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (missing === 'skip' && !Number.isFinite(value)) {
      if (i > 0) out[i] = out[i - 1]!;
      continue;
    }
    window.push(value);
    if (window.length > period) window.shift();
    if (window.length === period && window.every(Number.isFinite)) out[i] = evaluate(window);
  }
  return out;
}

/**
 * Rolling median, averaging the middle pair for even periods. Uses a full
 * period including the current bar, with NaN until ready. Missing values
 * propagate by default; `skip` collects period finite observations and holds
 * across gaps. Equal values retain their multiplicity. Invalid periods throw
 * RangeError; an unknown missing policy throws TypeError.
 */
export function rollingMedian(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): number[] {
  return rolling(values, period, options, (window) => {
    const sorted = window.slice().sort((a, b) => a - b);
    const middle = Math.floor(period / 2);
    if (period % 2 !== 0) return sorted[middle]!;
    const lower = sorted[middle - 1]!;
    const upper = sorted[middle]!;
    return lower === upper ? lower : lower / 2 + upper / 2;
  });
}

/**
 * Most frequent value in a full period ending at the current bar; equal
 * frequencies choose the smallest value. Warmup is NaN. Missing values
 * propagate by default; `skip` collects period finite observations and holds
 * across gaps. Invalid periods throw RangeError; unknown policies TypeError.
 */
export function rollingMode(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): number[] {
  return rolling(values, period, options, (window) => {
    const counts = new Map<number, number>();
    let best = Infinity;
    let frequency = 0;
    for (const value of window) {
      const count = (counts.get(value) ?? 0) + 1;
      counts.set(value, count);
      if (count > frequency || (count === frequency && value < best)) {
        best = value;
        frequency = count;
      }
    }
    return best;
  });
}

/**
 * Variance of a full period ending at the current bar. Population is the
 * default; `sample` divides by period-1 and gives NaN for period one. Ties are
 * repeated observations. Warmup is NaN. Missing values propagate by default;
 * `skip` collects period finite observations and holds across gaps. Invalid
 * periods throw RangeError; invalid policy or sample options throw TypeError.
 * A variance beyond the finite number range is Infinity.
 */
export function rollingVariance(
  values: readonly number[], period: number, options: RollingVarianceOptions = {},
): number[] {
  if (options.sample !== undefined && typeof options.sample !== 'boolean') {
    throw new TypeError('Numerical sample option must be boolean');
  }
  return rolling(values, period, options, (window) => {
    if (options.sample && period === 1) return NaN;
    // Subtract a nearby origin before finding the mean to retain small spreads
    // in prices with a large common offset.
    const origin = window[0]!;
    let mean = 0;
    for (const value of window) {
      const delta = value - origin;
      // An overflowing finite-value spread has unrepresentable variance even
      // after averaging over the largest possible array-sized window.
      if (!Number.isFinite(delta)) return Infinity;
      mean += delta / period;
    }
    const divisor = options.sample ? period - 1 : period;
    let variance = 0;
    for (const value of window) {
      const centered = value - origin - mean;
      // A squared deviation or their sum can overflow before the final average
      // even when the variance itself is representable.
      variance += (centered / divisor) * centered;
    }
    return variance;
  });
}

/**
 * Maximum minus minimum in a full period ending at the current bar. Repeated
 * extremes do not change the result. Warmup is NaN. Missing values propagate
 * by default; `skip` collects period finite observations and holds across gaps.
 * Invalid periods throw RangeError; unknown missing policies throw TypeError.
 */
export function rollingRange(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): number[] {
  return rolling(values, period, options, (window) => {
    let low = Infinity;
    let high = -Infinity;
    for (const value of window) {
      low = Math.min(low, value);
      high = Math.max(high, value);
    }
    return high - low;
  });
}

/**
 * Sorted-window percentile at zero-based rank (period-1)*percentage/100,
 * interpolating its adjacent values. Ties retain multiplicity; endpoints are
 * the minimum and maximum. A full period includes the current bar; warmup is
 * NaN. Missing values propagate by default; `skip` collects finite observations
 * and holds across gaps. Invalid periods or percentages outside 0..100 throw
 * RangeError; unknown missing policies throw TypeError.
 */
export function percentileLinear(
  values: readonly number[], period: number, percentage: number,
  options: NumericalWindowOptions = {},
): number[] {
  if (!Number.isFinite(percentage) || percentage < 0 || percentage > 100) {
    throw new RangeError('Numerical percentage must be finite and between 0 and 100');
  }
  return rolling(values, period, options, (window) => {
    const sorted = window.slice().sort((a, b) => a - b);
    const rank = (period - 1) * (percentage / 100);
    const lower = Math.floor(rank);
    const upper = Math.ceil(rank);
    const weight = rank - lower;
    if (sorted[lower] === sorted[upper]) return sorted[lower]!;
    return sorted[lower]! * (1 - weight) + sorted[upper]! * weight;
  });
}

/**
 * Spearman correlation of value ranks with chronological order, times 100.
 * Tied values receive their average rank. A constant or one-value window is
 * NaN, as is warmup before a full period including the current bar. Missing
 * values propagate by default; `skip` ranks the last period finite observations
 * and holds across gaps. Invalid periods throw RangeError; unknown policies
 * throw TypeError.
 */
export function rankCorrelation(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): number[] {
  return rolling(values, period, options, (window) => {
    const ordered = window.map((value, index) => ({ value, index })).sort((a, b) => a.value - b.value);
    const ranks = new Array<number>(period);
    for (let start = 0; start < period;) {
      let end = start + 1;
      while (end < period && ordered[end]!.value === ordered[start]!.value) end++;
      const rank = (start + end - 1) / 2;
      for (let i = start; i < end; i++) ranks[ordered[i]!.index] = rank;
      start = end;
    }
    const mean = (period - 1) / 2;
    let covariance = 0;
    let valueSquares = 0;
    let timeSquares = 0;
    for (let i = 0; i < period; i++) {
      const value = ranks[i]! - mean;
      const time = i - mean;
      covariance += value * time;
      valueSquares += value * value;
      timeSquares += time * time;
    }
    const denominator = Math.sqrt(valueSquares) * Math.sqrt(timeSquares);
    return denominator === 0 ? NaN : Math.max(-100, Math.min(100, 100 * covariance / denominator));
  });
}

function gravitySum(window: readonly number[], scale: number, weighted: boolean): number {
  let sum = 0;
  let correction = 0;
  for (let i = 0; i < window.length; i++) {
    const term = (window[i]! / scale) * (weighted ? window.length - i : 1);
    const next = sum + term;
    correction += Math.abs(sum) >= Math.abs(term) ? (sum - next) + term : (term - next) + sum;
    sum = next;
  }
  return sum + correction;
}

/**
 * Negative weighted sum divided by the ordinary sum over a full period,
 * assigning weight one to the newest value and period to the oldest. Equal
 * values remain separate observations. A zero compensated ordinary sum and
 * warmup are NaN; a nonzero sum is never discarded using an epsilon cutoff.
 * Ratios beyond the finite number range yield signed Infinity.
 * Missing values propagate by default; `skip` weights the last period finite
 * observations and holds across gaps. Invalid periods throw RangeError;
 * unknown missing policies throw TypeError.
 */
export function centerOfGravity(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): number[] {
  return rolling(values, period, options, (window) => {
    // Preserve cancellation in the original units before any scaling can
    // round an exact zero sum or erase a small, valid denominator.
    const sum = gravitySum(window, 1, false);
    if (sum === 0) return NaN;
    const weighted = gravitySum(window, 1, true);
    if (Number.isFinite(sum) && Number.isFinite(weighted)) return -weighted / sum;

    // Power-of-two scaling avoids overflow without introducing the rounding
    // from an arbitrary divisor into every observation.
    let magnitude = 0;
    for (const value of window) magnitude = Math.max(magnitude, Math.abs(value));
    const scale = 2 ** Math.min(1023, Math.floor(Math.log2(magnitude)));
    const scaledSum = Number.isFinite(sum) ? sum / scale : gravitySum(window, scale, false);
    const scaledWeighted = gravitySum(window, scale, true);
    if (scaledSum === 0) {
      return Number.isFinite(sum) ? -(scaledWeighted / sum) * scale : NaN;
    }
    return -scaledWeighted / scaledSum;
  });
}

function runningExtreme(
  values: readonly number[], options: NumericalWindowOptions, high: boolean,
): number[] {
  const missing = windowPolicy(undefined, options);
  const out = new Array<number>(values.length).fill(NaN);
  let best = NaN;
  let poisoned = false;
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (!Number.isFinite(value)) {
      if (missing === 'propagate') poisoned = true;
    } else if (!poisoned) {
      if (Number.isNaN(best) || (high ? value > best : value < best)) best = value;
    }
    if (!poisoned) out[i] = best;
  }
  return out;
}

/**
 * Minimum from the first bar through the current bar; equal minima retain the
 * existing value. There is no fixed warmup. Default `propagate` makes the
 * entire remaining history NaN after any missing term. `skip` holds the last
 * finite minimum, with NaN before the first finite term. Unknown policies
 * throw TypeError; empty input returns an empty array.
 */
export function runningMin(values: readonly number[], options: NumericalWindowOptions = {}): number[] {
  return runningExtreme(values, options, false);
}

/**
 * Maximum from the first bar through the current bar; equal maxima retain the
 * existing value. There is no fixed warmup. Default `propagate` makes the
 * remaining history NaN after any missing term. `skip` holds the last finite
 * maximum, with NaN before the first finite term. Unknown policies throw
 * TypeError; empty input returns an empty array.
 */
export function runningMax(values: readonly number[], options: NumericalWindowOptions = {}): number[] {
  return runningExtreme(values, options, true);
}

function crossing(
  a: readonly number[], b: readonly number[], options: NumericalWindowOptions,
  direction: 'above' | 'below' | 'either',
): boolean[] {
  if (a.length !== b.length) throw new RangeError('Numerical crossing arrays must have equal lengths');
  const missing = windowPolicy(undefined, options);
  const out = new Array<boolean>(a.length).fill(false);
  let previousA = NaN;
  let previousB = NaN;
  for (let i = 0; i < a.length; i++) {
    if (!Number.isFinite(a[i]) || !Number.isFinite(b[i])) {
      if (missing === 'propagate') { previousA = NaN; previousB = NaN; }
      continue;
    }
    // `b` was checked above to be as long as `a`.
    const above = a[i]! > b[i]! && previousA <= previousB;
    const below = a[i]! < b[i]! && previousA >= previousB;
    out[i] = direction === 'above' ? above : direction === 'below' ? below : above || below;
    previousA = a[i]!;
    previousB = b[i]!;
  }
  return out;
}

/**
 * Current a>b after previous a<=b. Current equality is false; prior equality
 * qualifies. Default `propagate` requires finite pairs on adjacent bars;
 * `skip` compares with the most recent jointly finite pair. Missing current
 * pairs and the first pair return false. Unequal array lengths throw
 * RangeError; unknown missing policies throw TypeError.
 */
export function crossesAbove(
  a: readonly number[], b: readonly number[], options: NumericalWindowOptions = {},
): boolean[] {
  return crossing(a, b, options, 'above');
}

/**
 * Current a<b after previous a>=b. Current equality is false; prior equality
 * qualifies. Default `propagate` requires finite adjacent pairs; `skip` uses
 * the most recent jointly finite pair. Missing current pairs and the first
 * pair return false. Unequal lengths throw RangeError; unknown policies
 * throw TypeError.
 */
export function crossesBelow(
  a: readonly number[], b: readonly number[], options: NumericalWindowOptions = {},
): boolean[] {
  return crossing(a, b, options, 'below');
}

/**
 * Crossing in either direction, with strict current inequality and inclusive
 * prior inequality. Default `propagate` requires finite adjacent pairs;
 * `skip` compares with the most recent jointly finite pair. Missing current
 * pairs and the first pair are false. Unequal lengths throw RangeError;
 * unknown missing policies throw TypeError.
 */
export function crosses(
  a: readonly number[], b: readonly number[], options: NumericalWindowOptions = {},
): boolean[] {
  return crossing(a, b, options, 'either');
}

function beyondHistory(
  values: readonly number[], period: number, options: NumericalWindowOptions, above: boolean,
): boolean[] {
  const missing = windowPolicy(period, options);
  const out = new Array<boolean>(values.length).fill(false);
  const history: number[] = [];
  for (let i = 0; i < values.length; i++) {
    const value = values[i]!;
    if (Number.isFinite(value) && history.length === period) {
      out[i] = history.every((previous) => Number.isFinite(previous) && (above ? value > previous : value < previous));
    }
    if (missing === 'propagate' || Number.isFinite(value)) {
      history.push(value);
      if (history.length > period) history.shift();
    }
  }
  return out;
}

/**
 * Whether the finite current value strictly exceeds every one of period prior
 * observations, excluding the current bar. Equality fails. Default `propagate`
 * uses prior chronological bars; `skip` collects prior finite observations.
 * Missing current values, gaps in required history, and insufficient history
 * return false. Invalid periods throw RangeError; unknown policies TypeError.
 */
export function rising(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): boolean[] {
  return beyondHistory(values, period, options, true);
}

/**
 * Whether the finite current value is strictly below every one of period prior
 * observations, excluding the current bar. Equality fails. Default `propagate`
 * uses prior chronological bars; `skip` collects prior finite observations.
 * Missing current values, gaps in required history, and insufficient history
 * return false. Invalid periods throw RangeError; unknown policies TypeError.
 */
export function falling(
  values: readonly number[], period: number, options: NumericalWindowOptions = {},
): boolean[] {
  return beyondHistory(values, period, options, false);
}
