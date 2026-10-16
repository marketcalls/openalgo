/**
 * A higher timeframe on a built-in study: a 15-minute EMA or an hourly
 * Supertrend drawn on a 1-minute chart, without changing the chart.
 *
 * `withTimeframe(descriptor)` gives a study one more input, `timeframe`, an
 * interval select whose empty default is the chart's own. Empty, the study is
 * exactly what it was: its own `calc` and its own `calcTail`, handed the same
 * arguments. Set, the chart's bars are folded to that interval by the fold
 * `securityExpression` uses, the study's `calc` runs on the folded bars, and
 * each bucket's result is read back onto the chart bars of the bucket after
 * it: a value appears once its bucket has completed, and never moves after.
 *
 * Sub-day buckets start at the session open, the way an exchange cuts its own
 * hourly bars, and the open is read from the bars in the chart's zone (see
 * `sessionOpen`). A timeframe no coarser than the chart's is the chart's own.
 *
 * Only a calculation from the chart's bars alone folds, and only a causal one:
 * a value at a bar reads no later bar. Which built-ins opt in, and why the
 * rest do not, is in the indicators reference.
 */
import {
  DEFAULT_TIMEZONE,
  IndicatorInputError,
  isTimeBucketed,
  tryResolveInterval,
  utcSecondsToZonedParts,
  type Bar,
  type Bucketing,
  type IndicatorCalcContext,
  type IndicatorDescriptor,
  type IndicatorInput,
  type IndicatorSettings,
  type IndicatorStore,
  type IndicatorValues,
} from 'openalgo-charts';
import { keyOf, localDays, securityExpression } from './security';

/** The settings key the input writes. */
const KEY = 'timeframe';

const INPUT: IndicatorInput = {
  key: KEY, type: 'interval', label: 'Timeframe', default: '',
  tooltip: 'Compute on a higher timeframe folded from the chart bars. Each value appears once its period closes.',
};

const DAY = 86400;
/** A month's mean length, used only to order a calendar timeframe against a fixed one. */
const MONTH = 2629746;
const MONTHS = { month: 1, quarter: 3, year: 12 } as const;

/** How long one bucket runs, nominally. */
function span(b: Bucketing): number {
  if (b.mode === 'interval') return b.seconds;
  if (b.mode === 'calendar') return MONTHS[b.unit] * Math.max(1, Math.floor(b.count ?? 1)) * MONTH;
  return NaN;
}

/** A timeframe to fold to, once it has passed every check. */
interface Fold {
  tf: string;
  bucketing: Bucketing;
  zone: string;
  /** The chart declared a clock interval; without one, a fold that groups nothing is the chart's own. */
  known: boolean;
}

/**
 * What a calculation with these settings folds to, null for the chart's own
 * timeframe, or a throw naming what cannot work. Refusals go through
 * `IndicatorInputError`, so the runtime reports them on the study's status.
 */
function plan(d: IndicatorDescriptor, s: Readonly<IndicatorSettings>, ctx: IndicatorCalcContext | undefined): Fold | null {
  const raw = s[KEY];
  if (raw === undefined || raw === null) return null;
  if (typeof raw !== 'string') throw new IndicatorInputError(`${d.name}: the timeframe must be an interval code`);
  const tf = raw.trim();
  if (tf === '') return null;
  const found = tryResolveInterval(tf);
  if (found === null) throw new IndicatorInputError(`${d.name}: "${tf}" is not a known timeframe`);
  if (!isTimeBucketed(found.bucketing)) {
    throw new IndicatorInputError(`${d.name}: "${tf}" bars close on trade flow, not the clock, so they cannot be folded`);
  }
  const code = ctx?.interval;
  const chart = code === undefined || code === '' ? null : tryResolveInterval(code)?.bucketing ?? null;
  if (chart !== null) {
    if (!isTimeBucketed(chart)) {
      throw new IndicatorInputError(`${d.name}: the chart's "${code ?? ''}" bars close on trade flow, not the clock, so they cannot be folded`);
    }
    if (span(found.bucketing) <= span(chart)) return null;
  }
  if (ctx?.transformed === true) {
    throw new IndicatorInputError(`${d.name}: this chart draws transformed bars, which a timeframe cannot fold; compute the study on the underlying bars`);
  }
  for (const input of d.inputs) {
    const value = s[input.key];
    if (input.type === 'source' && typeof value === 'object' && value !== null) {
      throw new IndicatorInputError(`${d.name}: another study's output cannot be folded to a timeframe; pick a price source`);
    }
  }
  const zone = ctx?.timezone ?? (typeof s.timezone === 'string' && s.timezone !== '' ? s.timezone : DEFAULT_TIMEZONE);
  return { tf, bucketing: found.bucketing, zone, known: chart !== null };
}

/**
 * Minutes after local midnight that the session opens, read from the bars:
 * the time of day most of the loaded days start at, the earliest on a tie.
 * So a day an illiquid contract first trades at 09:17 still buckets from
 * 09:15, and a history cut inside its first session, which opens later than
 * the real open, never wins a tie. Midnight on a market that trades round the
 * clock.
 */
function sessionOpen(bars: readonly Bar[], zone: string): number | null {
  const votes = new Map<number, number>();
  const dayOf = localDays(zone);
  let day = NaN;
  for (const bar of bars) {
    const at = dayOf(bar.time).index;
    if (at === day) continue;
    const parts = utcSecondsToZonedParts(bar.time, zone);
    const minute = parts.hour * 60 + parts.minute;
    votes.set(minute, (votes.get(minute) ?? 0) + 1);
    day = at;
  }
  let best: number | null = null;
  let most = 0;
  for (const [minute, count] of votes) {
    if (count > most || (count === most && best !== null && minute < best)) { best = minute; most = count; }
  }
  return best;
}

/** A session spec whose start is `minute`, the only part a fold reads. */
function sessionAt(minute: number): string {
  const hhmm = String(Math.floor(minute / 60)).padStart(2, '0') + String(minute % 60).padStart(2, '0');
  return `${hhmm}-${hhmm}`;
}

/** The calculation context for the folded bars: their interval, their last index, no study sources. */
function folded(ctx: IndicatorCalcContext | undefined, tf: string, count: number): IndicatorCalcContext | undefined {
  if (ctx === undefined) return undefined;
  const { resolveSource: _unused, ...rest } = ctx;
  return { ...rest, interval: tf, barState: { ...ctx.barState, lastIndex: count - 1 } };
}

const cell = (v: number | null | undefined): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** Whether `a` and `b` read the same in every column over their first `count` values. */
function same(a: IndicatorValues, b: IndicatorValues, count: number): boolean {
  for (const key of Object.keys(b)) {
    const x = a[key];
    const y = b[key];
    if (x === undefined || y === undefined) return false;
    for (let i = 0; i < count; i++) if (!Object.is(cell(x[i]), cell(y[i]))) return false;
  }
  return true;
}

/**
 * What the last full calculation on a store folded, so that a tick can carry
 * its result. `identity` is a fold that grouped no two bars, which is the
 * chart's own timeframe and its values the study's own.
 */
interface Memo { tf: string; zone: string; sessionStart: number | null; identity: boolean }

const memos = new WeakMap<object, Memo>();

const owner = (store: IndicatorStore): object | null => (typeof store === 'object' && store !== null ? store : null);

function remember(store: IndicatorStore, memo: Memo | null): void {
  const key = owner(store);
  if (key === null) return;
  if (memo === null) memos.delete(key);
  else memos.set(key, memo);
}

/**
 * The descriptor with a `timeframe` input. The input goes after the study's
 * own ungrouped inputs, ahead of any grouped section, so a form renders it with
 * them. A descriptor that already has the key, or that brings its own data
 * through `attach`, cannot be folded and is refused.
 */
export function withTimeframe(descriptor: IndicatorDescriptor): IndicatorDescriptor {
  if (descriptor.inputs.some((input) => input.key === KEY)) {
    throw new Error(`withTimeframe: ${descriptor.id} already has a "${KEY}" input`);
  }
  if (descriptor.attach !== undefined) {
    throw new Error(`withTimeframe: ${descriptor.id} brings its own data, which a timeframe cannot fold`);
  }
  const at = descriptor.inputs.findIndex((input) => input.group !== undefined);
  const inputs = at < 0 ? [...descriptor.inputs, INPUT]
    : [...descriptor.inputs.slice(0, at), INPUT, ...descriptor.inputs.slice(at)];

  const calc: IndicatorDescriptor['calc'] = (bars, settings, store, ctx) => {
    const fold = plan(descriptor, settings, ctx);
    if (fold === null || bars.length === 0) {
      remember(store, null);
      return descriptor.calc(bars, settings, store, ctx);
    }
    const sub = fold.bucketing.mode === 'interval' && fold.bucketing.seconds % DAY !== 0;
    const sessionStart = sub ? sessionOpen(bars, fold.zone) : null;
    let count = 0;
    let settled = true;
    const values = securityExpression(bars, fold.tf, (requested) => {
      count = requested.length;
      const result = descriptor.calc(requested, settings, store, folded(ctx, fold.tf, count));
      // The forming bucket is shown nowhere, so a tick inside it can carry the
      // held result only when the completed buckets read the same without it.
      // A causal study always does; one set to read ahead (a negative
      // displacement) does not, and recomputes in full on every tick.
      if (count > 1) {
        const before = descriptor.calc(requested.slice(0, -1), settings, {}, folded(ctx, fold.tf, count - 1));
        settled = same(before, result, count - 1);
      }
      return result;
    }, { mode: 'confirmed', timezone: fold.zone, ...(sessionStart === null ? {} : { session: sessionAt(sessionStart) }) });
    if (!fold.known && count === bars.length) {
      remember(store, { tf: fold.tf, zone: fold.zone, sessionStart, identity: true });
      return descriptor.calc(bars, settings, store, ctx);
    }
    remember(store, settled ? { tf: fold.tf, zone: fold.zone, sessionStart, identity: false } : null);
    return values;
  };

  const tail: NonNullable<IndicatorDescriptor['calcTail']> = (bars, settings, from, previous, store, ctx) => {
    const fold = plan(descriptor, settings, ctx);
    if (fold === null) return descriptor.calcTail?.(bars, settings, from, previous, store, ctx) ?? null;
    const key = owner(store);
    const memo = key === null ? undefined : memos.get(key);
    const n = bars.length;
    if (memo === undefined || memo.tf !== fold.tf || memo.zone !== fold.zone || from < 0 || from >= n) return null;
    // Grouping nothing, the study is its own; a tick keeps that, a new bar may not.
    if (memo.identity) return n === from + 1 ? descriptor.calcTail?.(bars, settings, from, previous, store, ctx) ?? null : null;
    // Bar `from` was there before with this time, so the completed bucket it
    // reads is unchanged. A bar after it in the same bucket reads the same one;
    // a bar that opens a new bucket completes one, which needs the full fold.
    const bucket = (i: number): number => keyOf(fold.bucketing, bars[i]?.time ?? NaN, fold.zone, memo.sessionStart);
    const own = bucket(from);
    for (let i = from + 1; i < n; i++) if (bucket(i) !== own) return null;
    const out: Record<string, (number | null)[]> = {};
    for (const name of Object.keys(previous)) {
      const column = previous[name];
      if (column === undefined || column.length <= from) return null;
      out[name] = new Array<number | null>(n - from).fill(column[from] ?? null);
    }
    return out;
  };

  const out: IndicatorDescriptor = { ...descriptor, inputs, calc };
  // Not enumerable, like a built-in's own tail: a spread that brings another
  // calc must not splice this tail onto that calc's numbers (see ./tail).
  Object.defineProperty(out, 'calcTail', { value: tail, enumerable: false, writable: true, configurable: true });
  return out;
}
