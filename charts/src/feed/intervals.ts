/**
 * Interval registry (ARCHITECTURE.md 10.2). A host registers its own interval
 * codes here, and the engine asks this module how a code buckets.
 *
 * The entry is a *bucketing rule*, not a duration, because three of the four
 * kinds have no duration to state:
 *   - `interval`  fixed seconds per bar, the only kind a code-to-seconds map
 *                 could ever have expressed.
 *   - `calendar`  month / quarter / year, whose length depends on which month
 *                 and which year, and whose boundaries land at local midnight
 *                 in the chart's configured zone. A month is not 30 days, a
 *                 year is not 365, and a New York month is not a Mumbai month.
 *   - `ticks`     a bar closes after N trades.
 *   - `volume`    a bar closes after N traded quantity.
 *
 * The last three are exactly the modes `TickBarAggregator` already had, so this
 * is that vocabulary widened by one case rather than a second system: the older
 * `TickTimeframe` name is still here and still means the same three modes.
 *
 * Registering nothing leaves every built-in code resolving exactly as it did
 * before this module existed. An unrecognised code is an error, not a minute.
 */
import { DEFAULT_TIMEZONE, utcSecondsToZonedParts, zonedWallClockToUtcSeconds } from './time';

/** Fixed-length bars: `seconds` each, aligned to `anchorSec` (default epoch). */
export interface IntervalBucketing {
  mode: 'interval';
  seconds: number;
  anchorSec?: number;
}

/** A bar closes after `count` trades. */
export interface TickCountBucketing {
  mode: 'ticks';
  count: number;
}

/** A bar closes after `perBar` traded quantity. */
export interface VolumeBucketing {
  mode: 'volume';
  perBar: number;
}

/** Calendar periods, which are not a fixed number of seconds. */
export type CalendarUnit = 'month' | 'quarter' | 'year';

/**
 * A bar spans `count` calendar units, opening at local midnight on the first
 * day of the period in `timezone`.
 *
 * `timezone` on the entry pins the code to one exchange's calendar; leaving it
 * off lets the bucket follow whatever zone the caller resolves in, which is the
 * chart's configured zone.
 */
export interface CalendarBucketing {
  mode: 'calendar';
  unit: CalendarUnit;
  /** Periods per bar (default 1): `{ unit: 'month', count: 6 }` is a half-year. */
  count?: number;
  timezone?: string;
}

/** Every way this engine knows how to close a bar. */
export type Bucketing = IntervalBucketing | TickCountBucketing | VolumeBucketing | CalendarBucketing;

/**
 * The three time-agnostic modes `TickBarAggregator` shipped with. Kept as a
 * distinct name because `FootprintAggregator` handles exactly these three.
 */
export type TickTimeframe = IntervalBucketing | TickCountBucketing | VolumeBucketing;

/** A registered interval code and the rule that buckets it. */
export interface IntervalDescriptor {
  /** The code a host passes as `BarsRequest.interval`, e.g. `5m`, `MN`, `T500`. */
  code: string;
  bucketing: Bucketing;
}

/** Thrown when a code matches neither a registered entry nor a built-in token. */
export class UnknownIntervalError extends Error {
  public readonly code: string;

  public constructor(code: string) {
    super(
      `openalgo-charts: unknown interval "${code}". Register it with registerInterval() `
      + `or use a built-in token (1s, 1m, 5m, 1h, D, W).`,
    );
    this.name = 'UnknownIntervalError';
    this.code = code;
  }
}

// ---------------------------------------------------------------------------
// Built-in tokens
// ---------------------------------------------------------------------------

/**
 * The original token grammar, byte for byte: an optional count followed by a
 * unit, so the bare OpenAlgo tokens `D` and `W` work alongside `1d` / `1w`.
 * Anything this accepted before must still resolve to the same seconds, which
 * is why the odd corners (an optional space, a zero count) are preserved rather
 * than tidied.
 */
const BUILTIN_TOKEN = /^(\d*)\s*([smhdw])$/i;

const UNIT_SECONDS: Readonly<Record<string, number>> = {
  s: 1, m: 60, h: 3600, d: 86400, w: 604800,
};

/**
 * Lower-case `m` is minutes and upper-case `M` is a month, across every terminal
 * that uses these tokens. The regex above folds case, which is right for `D` and
 * `H` and `W` (no other unit collides with them) and wrong for exactly this one
 * pair: it made a monthly bar resolve to sixty seconds.
 *
 * That is not a cosmetic mismatch. Anything gating on "has the next bar closed
 * yet" then believes a month closes every minute, which is how a cache serves a
 * stale monthly bar all day. No month is registered by default, so `M` resolves
 * to nothing and a host that wants one registers a calendar interval
 * deliberately. Failing to resolve is the safe direction; guessing minutes is not.
 */
function builtinBucketing(trimmed: string): IntervalBucketing | null {
  if (/^\d*\s*M$/.test(trimmed)) return null;
  const m = BUILTIN_TOKEN.exec(trimmed);
  if (m === null) return null;
  // Both groups take part in every match, and the second admits only the units listed.
  const n = m[1] === '' ? 1 : Number(m[1]);
  return { mode: 'interval', seconds: n * UNIT_SECONDS[m[2]!.toLowerCase()]! };
}

// ---------------------------------------------------------------------------
// The registry
// ---------------------------------------------------------------------------

/**
 * Keyed by lower-cased code, because the built-in tokens have always been
 * case-insensitive (`D` and `d` are one interval) and a host's codes should not
 * behave differently from the shipped ones.
 */
const REGISTRY = new Map<string, IntervalDescriptor>();

function normalise(code: string): string {
  return code.trim().toLowerCase();
}

function validate(b: Bucketing): void {
  if (b.mode === 'interval' && !(b.seconds > 0)) {
    throw new Error('openalgo-charts: interval bucketing needs seconds > 0');
  }
  if (b.mode === 'ticks' && !(b.count >= 1)) {
    throw new Error('openalgo-charts: tick bucketing needs count >= 1');
  }
  if (b.mode === 'volume' && !(b.perBar > 0)) {
    throw new Error('openalgo-charts: volume bucketing needs perBar > 0');
  }
  if (b.mode === 'calendar' && b.count !== undefined && !(b.count >= 1)) {
    throw new Error('openalgo-charts: calendar bucketing needs count >= 1');
  }
}

/**
 * Register an interval code. Returns a disposer, so a host that adds codes for
 * one instrument can take them away again.
 *
 * A registered code shadows a built-in token of the same name: a host whose
 * `W` means "calendar week in the exchange's zone" rather than "604800 seconds
 * from the epoch" is entitled to say so.
 */
export function registerInterval(descriptor: IntervalDescriptor): () => void {
  const key = normalise(descriptor.code);
  if (key === '') throw new Error('openalgo-charts: interval code must not be empty');
  validate(descriptor.bucketing);
  REGISTRY.set(key, descriptor);
  return () => {
    // Only remove our own entry: a later registration of the same code owns it.
    if (REGISTRY.get(key) === descriptor) REGISTRY.delete(key);
  };
}

/** Remove a registered code. Returns false if nothing was registered under it. */
export function unregisterInterval(code: string): boolean {
  return REGISTRY.delete(normalise(code));
}

/** Every registered code, in registration order. Built-in tokens are not listed. */
export function registeredIntervals(): readonly IntervalDescriptor[] {
  return Array.from(REGISTRY.values());
}

/** Resolve a code, or null when nothing recognises it. */
export function tryResolveInterval(code: string): IntervalDescriptor | null {
  const trimmed = code.trim();
  const registered = REGISTRY.get(trimmed.toLowerCase());
  if (registered !== undefined) return registered;
  const builtin = builtinBucketing(trimmed);
  return builtin === null ? null : { code: trimmed, bucketing: builtin };
}

/** True when `code` resolves. For a host validating an interval picker's input. */
export function isKnownInterval(code: string): boolean {
  return tryResolveInterval(code) !== null;
}

/**
 * Resolve a code, throwing `UnknownIntervalError` if nothing recognises it.
 *
 * Loud on purpose. The previous behaviour was a silent fall back to 60 seconds,
 * so a typo drew minute bars under a label claiming something else, and nothing
 * anywhere said so. A chart that refuses to open is a bug report; a chart
 * showing the wrong timeframe is a wrong trade.
 */
export function resolveInterval(code: string): IntervalDescriptor {
  const found = tryResolveInterval(code);
  if (found === null) throw new UnknownIntervalError(code);
  return found;
}

// ---------------------------------------------------------------------------
// Bucketing
// ---------------------------------------------------------------------------

/** True when bars close on the clock or the calendar rather than on trade flow. */
export function isTimeBucketed(b: Bucketing): boolean {
  return b.mode === 'interval' || b.mode === 'calendar';
}

const UNIT_MONTHS: Readonly<Record<CalendarUnit, number>> = { month: 1, quarter: 3, year: 12 };

function stepMonths(b: CalendarBucketing): number {
  return UNIT_MONTHS[b.unit] * Math.max(1, Math.floor(b.count ?? 1));
}

function calendarZone(b: CalendarBucketing, zone: string | undefined): string {
  return b.timezone ?? zone ?? DEFAULT_TIMEZONE;
}

/**
 * Absolute month number of `timeSec` in `tz`, floored to the bucket. Counting
 * months from year zero rather than from the epoch is what makes quarters land
 * on January, April, July and October for every year, positive or negative.
 */
function calendarIndex(b: CalendarBucketing, timeSec: number, tz: string): number {
  const p = utcSecondsToZonedParts(timeSec, tz);
  const step = stepMonths(b);
  return Math.floor((p.year * 12 + (p.month - 1)) / step) * step;
}

function startOfMonthIndex(index: number, tz: string): number {
  return zonedWallClockToUtcSeconds(Math.floor(index / 12), (index % 12) + 1, 1, 0, 0, 0, tz);
}

/**
 * UTC seconds at which the bar containing `timeSec` opened.
 *
 * `zone` is the fallback for calendar buckets that did not pin their own, and
 * should be the chart's configured timezone. Count-driven bars have no time
 * bucket at all, so their bar simply opens at the tick that started it.
 */
export function bucketStartOf(b: Bucketing, timeSec: number, zone?: string): number {
  if (b.mode === 'interval') {
    const a = b.anchorSec ?? 0;
    return a + Math.floor((timeSec - a) / b.seconds) * b.seconds;
  }
  if (b.mode !== 'calendar') return timeSec;
  const tz = calendarZone(b, zone);
  return startOfMonthIndex(calendarIndex(b, timeSec, tz), tz);
}

/**
 * UTC seconds at which the next bar opens, or null for count-driven bars, whose
 * close depends on trade flow rather than on the clock.
 *
 * The gap between this and `bucketStartOf` is the bar's real length: 28, 29, 30
 * or 31 days for a month, and an hour short of that across a spring forward.
 */
export function nextBucketStart(b: Bucketing, timeSec: number, zone?: string): number | null {
  if (b.mode === 'interval') return bucketStartOf(b, timeSec) + b.seconds;
  if (b.mode !== 'calendar') return null;
  const tz = calendarZone(b, zone);
  return startOfMonthIndex(calendarIndex(b, timeSec, tz) + stepMonths(b), tz);
}

// ---------------------------------------------------------------------------
// Introspection
// ---------------------------------------------------------------------------

/**
 * How a bar's length reads to a human: a count, and the unit it counts.
 *
 * `M` is months, so a quarter reads as 3 and a year as 12, keeping the token
 * grammar's rule that lower-case `m` is minutes and upper-case `M` is a month.
 * `tick` counts trades. `other` is a bucket with neither a clock length nor a
 * trade count, which today means volume, and is where a later count-driven
 * mode can land without silently changing what an existing unit means.
 */
export interface IntervalParts {
  multiplier: number;
  unit: 's' | 'm' | 'h' | 'D' | 'W' | 'M' | 'tick' | 'other';
}

/**
 * Split a code into a count and a unit, or null when nothing recognises it.
 * For an indicator that knows its own interval and wants to reason about it,
 * rather than hard-coding the handful of codes its author happened to test on.
 *
 * Read off the bucketing rule, not off the code's spelling, so it answers for
 * a registered code the built-in grammar never parsed, and it answers
 * canonically: `120m` and `2h` are the same bar and both read as 2 h. The
 * coarsest unit that divides the length wins, which is also why a 90-second
 * bar reads as 90 s rather than as one and a half minutes.
 */
export function intervalParts(code: string): IntervalParts | null {
  const found = tryResolveInterval(code);
  if (found === null) return null;
  const b = found.bucketing;
  if (b.mode === 'ticks') return { multiplier: b.count, unit: 'tick' };
  if (b.mode === 'volume') return { multiplier: b.perBar, unit: 'other' };
  if (b.mode === 'calendar') return { multiplier: stepMonths(b), unit: 'M' };
  const s = b.seconds;
  if (s % 604800 === 0) return { multiplier: s / 604800, unit: 'W' };
  if (s % 86400 === 0) return { multiplier: s / 86400, unit: 'D' };
  if (s % 3600 === 0) return { multiplier: s / 3600, unit: 'h' };
  if (s % 60 === 0) return { multiplier: s / 60, unit: 'm' };
  return { multiplier: s, unit: 's' };
}

/**
 * Bar length in seconds, or 0 when the code has no fixed one: unregistered, a
 * calendar period, or count-driven.
 *
 * The predicates below ask this rather than asking `intervalParts` for a unit,
 * because a unit is a decomposition and not a magnitude: a 25-hour code, odd
 * but registrable, decomposes into hours while covering more than a day.
 */
function fixedSeconds(code: string): number {
  const b = tryResolveInterval(code)?.bucketing;
  return b !== undefined && b.mode === 'interval' ? b.seconds : 0;
}

/**
 * True when the bar is not a whole number of minutes long, so its labels need
 * second precision. `1s`, `15s` and `90s` all qualify; `5m` does not.
 */
export function isSecondsInterval(code: string): boolean {
  const s = fixedSeconds(code);
  return s > 0 && s % 60 !== 0;
}

/**
 * True for a fixed-length bar shorter than a day: the ones that want a session
 * reset, such as a VWAP anchored to the day's open or an opening range.
 *
 * A calendar period is false because it is coarser, and a count-driven bar is
 * false because it has no clock length to compare, not because it is known to
 * be long. Ask `isTickInterval` or `intervalParts` for those.
 */
export function isIntradayInterval(code: string): boolean {
  const s = fixedSeconds(code);
  return s > 0 && s < 86400;
}

/**
 * True for a bar exactly one day long, whether spelled `D`, `24h` or `1440m`.
 *
 * Deliberately not "daily or coarser": weekly and monthly answer false, so a
 * caller can branch on intraday, daily and coarser as three independent
 * questions instead of an ordered ladder where the wrong order swallows a case.
 */
export function isDailyInterval(code: string): boolean {
  return fixedSeconds(code) === 86400;
}

/**
 * True for a bar that closes after N trades. Volume bars close on quantity, not
 * on trade count, so they answer false; `intervalParts` separates the two.
 */
export function isTickInterval(code: string): boolean {
  return tryResolveInterval(code)?.bucketing.mode === 'ticks';
}
