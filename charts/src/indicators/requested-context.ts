import { IndicatorInputError, type Bar, type IndicatorValues, type RequestedBarsSnapshot } from 'openalgo-charts';
export type { RequestedBarsSnapshot } from 'openalgo-charts';

/**
 * A pure, causal calculation with one value per requested bar in each named
 * column. Output at index i may depend only on input through i. Helpers cannot
 * prove callback causality. Inputs are copied and frozen, including each bar.
 */
export type RequestedExpression = (bars: readonly Readonly<Bar>[]) => IndicatorValues;

export interface RequestedAlignmentOptions {
  /**
   * carry retains the latest eligible row, including null values. missing emits
   * only when the selected row changes; the first target is an initial reading.
   */
  gaps?: 'carry' | 'missing' | undefined;
}

/** Opening-time membership is [start, end); availability may equal end. */
export interface RequestedTimeWindow {
  start: number;
  end: number;
}

export interface RequestedIntrabarOptions {
  /** Inclusive UTC availability cutoff in addition to each window's end. */
  asOf?: number;
}

/** Arrays retain requested row order, including missing expression values. */
export interface RequestedIntrabarValues {
  times: number[][];
  values: Record<string, (number | null)[][]>;
}

function invalid(message: string): never {
  throw new IndicatorInputError(`Requested context: ${message}`);
}

function record(value: unknown): boolean {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function column<T>(target: Record<string, T>, key: string, value: T): void {
  // Plot names are data; even a name matching a prototype property stays data.
  Object.defineProperty(target, key, { value, enumerable: true, writable: true, configurable: true });
}

/**
 * Every column of `values` holds one value per bar, and `eligibleAt` one time
 * per bar of the confirmed prefix, so an index below `eligibleAt.length` reads
 * a bar and every column.
 */
interface Prepared {
  bars: readonly Readonly<Bar>[];
  eligibleAt: number[];
  values: IndicatorValues;
}

function prepare(snapshot: RequestedBarsSnapshot, expression: RequestedExpression): Prepared {
  if (!record(snapshot) || !Array.isArray(snapshot.bars) || !Array.isArray(snapshot.availableAt)
    || !Array.isArray(snapshot.confirmed)) invalid('snapshot must contain bars, availableAt and confirmed arrays');
  const n = snapshot.bars.length;
  if (snapshot.availableAt.length !== n || snapshot.confirmed.length !== n) invalid('snapshot arrays must have equal lengths');
  if (typeof expression !== 'function') invalid('expression must be a function');
  const bars: Readonly<Bar>[] = [];
  const eligibleAt: number[] = [];
  let previous = -Infinity;
  let available = -Infinity;
  let blocked = false;
  for (let i = 0; i < n; i++) {
    const bar = snapshot.bars[i];
    if (!record(bar) || !Number.isFinite(bar.time) || bar.time <= previous) invalid('bar times must be finite and strictly increasing');
    if (['open', 'high', 'low', 'close'].some(key => typeof bar[key] !== 'number')
      || (bar.volume !== undefined && typeof bar.volume !== 'number')
      || (bar.oi !== undefined && typeof bar.oi !== 'number')) invalid('bar readings must be numbers');
    const at = snapshot.availableAt[i];
    if (at !== null && (!Number.isFinite(at) || at < bar.time)) invalid('availability must be null or finite and at or after bar opening');
    if (typeof snapshot.confirmed[i] !== 'boolean') invalid('confirmation must be boolean');
    previous = bar.time;
    bars.push(Object.freeze({ ...bar }));
    if (!snapshot.confirmed[i] || at === null) blocked = true;
    // Every causal result may depend on its entire prefix. A delayed ancestor
    // must not make that result visible before the ancestor itself was known.
    if (!blocked && at !== null) {
      available = Math.max(available, at);
      eligibleAt.push(available);
    }
  }
  const values: Record<string, (number | null)[]> = {};
  const frozen = Object.freeze(bars);
  if (n === 0) return { bars: frozen, eligibleAt, values };
  const result = expression(frozen);
  if (!record(result)) invalid('expression must return named columns');
  for (const key of Object.keys(result)) {
    const input = result[key];
    if (!Array.isArray(input) || input.length !== n) invalid('expression columns must match requested bar count');
    const normalized: (number | null)[] = [];
    for (let i = 0; i < n; i++) {
      const value = input[i];
      if (value !== null && typeof value !== 'number') invalid('expression values must be numbers or null');
      normalized.push(value !== null && Number.isFinite(value) ? value : null);
    }
    column(values, key, normalized);
  }
  return { bars: frozen, eligibleAt, values };
}

/**
 * Calculate once on the whole requested history, then align to finite, strictly
 * increasing UTC evaluation times. The confirmed prefix ends at the first
 * unconfirmed bar or unknown availability; that bar and all later bars remain
 * in expression input but cannot emit. Availability is the cumulative maximum
 * across each prefix. Simultaneously available rows select the latest one.
 *
 * Missing/nonfinite results become null and replace older readings. An empty
 * snapshot returns {} without invoking the expression; an empty target with
 * nonempty requested history still evaluates to obtain named empty columns.
 * Invalid timestamps, metadata, options or output shapes throw IndicatorInputError.
 * Inputs are fully validated before the callback. Runtime is O((n + targets) *
 * columns), plus expression cost. No transport, aggregation or clock inference.
 */
export function alignRequestedExpression(
  targetTimes: readonly number[], snapshot: RequestedBarsSnapshot, expression: RequestedExpression,
  options: RequestedAlignmentOptions = {},
): IndicatorValues {
  if (!Array.isArray(targetTimes)) invalid('target times must be an array');
  let previous = -Infinity;
  for (const time of targetTimes) {
    if (!Number.isFinite(time) || time <= previous) invalid('target times must be finite and strictly increasing');
    previous = time;
  }
  if (!record(options) || (options.gaps !== undefined && options.gaps !== 'carry' && options.gaps !== 'missing')) {
    invalid('gaps must be carry or missing');
  }
  const { eligibleAt, values } = prepare(snapshot, expression);
  const keys = Object.keys(values);
  const out: Record<string, (number | null)[]> = {};
  for (const key of keys) column(out, key, new Array<number | null>(targetTimes.length).fill(null));
  let selected = -1;
  let lastSelected = -1;
  for (let i = 0; i < targetTimes.length; i++) {
    while (selected + 1 < eligibleAt.length && eligibleAt[selected + 1]! <= targetTimes[i]) selected++;
    if (selected >= 0 && (options.gaps !== 'missing' || selected !== lastSelected)) {
      for (const key of keys) out[key]![i] = values[key]![selected] as number | null;
    }
    lastSelected = selected;
  }
  return out;
}

/**
 * Calculate once across all requested observations, then group by nonoverlapping
 * ordered windows. Windows must have finite start < end; gaps are allowed.
 * An observation belongs by its opening in [start, end), and emits only when
 * its confirmed prefix is available by end and by optional finite asOf.
 * Delayed observations never move to a later window. Expression history never
 * restarts at window boundaries. Empty windows return empty arrays.
 *
 * Uses the same prefix, missing-value, validation and empty-snapshot rules as
 * alignRequestedExpression. Result times are openings, not availability times.
 * Runtime is O(n * columns + windows * columns), plus expression cost.
 */
export function requestedIntrabars(
  targetWindows: readonly RequestedTimeWindow[], snapshot: RequestedBarsSnapshot, expression: RequestedExpression,
  options: RequestedIntrabarOptions = {},
): RequestedIntrabarValues {
  if (!Array.isArray(targetWindows)) invalid('target windows must be an array');
  let previousEnd = -Infinity;
  for (const window of targetWindows) {
    if (!record(window) || !Number.isFinite(window.start) || !Number.isFinite(window.end)
      || window.start >= window.end || window.start < previousEnd) invalid('windows must be finite, ordered and nonoverlapping with start < end');
    previousEnd = window.end;
  }
  if (!record(options) || (options.asOf !== undefined && !Number.isFinite(options.asOf))) invalid('asOf must be finite');
  const { bars, eligibleAt, values } = prepare(snapshot, expression);
  const keys = Object.keys(values);
  const out: RequestedIntrabarValues = { times: targetWindows.map(() => []), values: {} };
  for (const key of keys) column(out.values, key, targetWindows.map(() => []));
  // `out` holds one list per window in every column; `row` reads as `Prepared` says.
  let row = 0;
  for (let i = 0; i < targetWindows.length; i++) {
    const { start, end } = targetWindows[i];
    const cutoff = Math.min(end, options.asOf ?? Infinity);
    while (row < eligibleAt.length && bars[row]!.time < start) row++;
    while (row < eligibleAt.length && bars[row]!.time < end) {
      if (eligibleAt[row]! <= cutoff) {
        out.times[i]!.push(bars[row]!.time);
        for (const key of keys) out.values[key]![i]!.push(values[key]![row] as number | null);
      }
      row++;
    }
  }
  return out;
}
