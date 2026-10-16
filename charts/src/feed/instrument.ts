import type { Chart } from '../core/chart';
import type { ChartDataContext } from '../model/indicator-registry';
import { tryResolveInterval } from './intervals';
import { isValidTimezone, parseSessionSpec, utcSecondsToZonedParts, zonedWallClockToUtcSeconds, type SessionSpec } from './time';
import { TickSchedule, type TickBand } from './tick-schedule';
import { partitionPhases, statusOf, type MarketStatus, type PhaseWindow, type SessionPhase, type SessionPhaseSpan } from './market-status';
import type { LooseOptional } from '../helpers/types';

export interface InstrumentCalendar {
  /** HHMM-HHMM[:days], with opening weekdays 1 (Sunday) through 7. */
  readonly sessions: readonly string[];
  /** Local opening dates replace weekly sessions. An empty list closes that date. */
  readonly exceptions?: Readonly<Record<string, readonly string[]>>;
  /**
   * Whole minutes of pre-open trading before each trading date's first
   * regular opening, 0 to 1439. Counted from the opening, so a shortened day,
   * a special session and a closed date move it with them.
   */
  readonly preMarketMinutes?: number;
  /** Whole minutes of post-close trading after each trading date's last regular close, 0 to 1439. */
  readonly postMarketMinutes?: number;
  /**
   * Extended hours of their own, such as an overnight session, written like
   * `sessions`. They open on their own days, except on a date the exceptions
   * close.
   */
  readonly extendedHours?: readonly string[];
}

/** Host-supplied market rules, separate from observations and saved user preferences. */
export interface InstrumentMetadata {
  readonly symbol: string;
  readonly exchange: string;
  readonly timezone: string;
  /** The minimum move: with `tickBands`, the schedule's common grid. */
  readonly priceTick: number;
  readonly pricePrecision: number;
  /**
   * Price-dependent ticks, supplied by the host from its venue's rules. Absent
   * means one tick at every price, which is `priceTick`.
   */
  readonly tickBands?: readonly TickBand[];
  /** In the order adapter's units. This is a grid, never a lot conversion factor. */
  readonly quantityStep: number;
  readonly intervals: readonly string[];
  readonly calendar: InstrumentCalendar;
  readonly hasOpenInterest?: boolean;
}

export interface InstrumentSession {
  /** Local opening date, including for an overnight window. */
  readonly date: string;
  /** UTC seconds, inclusive. */
  readonly open: number;
  /** UTC seconds, exclusive. */
  readonly close: number;
}

/**
 * Trading hours on their own: the calendar part of {@link InstrumentMetadata}
 * with the zone its times are written in, for a host that knows a venue's
 * hours but has no tick or quantity rules to supply.
 */
export interface SessionCalendarSpec extends InstrumentCalendar {
  /** IANA zone the session windows and exception dates are read in. */
  readonly timezone: string;
}

type Fail = (message: string) => never;
const failWith = (subject: string): Fail => message => { throw new Error(`Invalid ${subject}: ${message}`); };
const fail = failWith('instrument');
function record(value: unknown, f: Fail = fail): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return f('expected a plain object');
  if (Object.values(Object.getOwnPropertyDescriptors(value)).some(item => !('value' in item))) return f('accessors are not metadata');
  return value as Record<string, unknown>;
}
function text(value: unknown, label: string, f: Fail = fail): string {
  if (typeof value !== 'string' || !value.trim() || value.length > 200 || Array.from(value).some(char => char.charCodeAt(0) < 32)) return f(label);
  return value;
}
function positive(value: unknown, label: string): number {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return fail(label);
  return value;
}
function strings(value: unknown, limit: number, f: Fail = fail): string[] {
  if (!Array.isArray(value) || value.length > limit) return f('invalid list');
  return value.map(item => text(item, 'invalid list item', f));
}
function sessions(value: unknown, f: Fail, label = 'invalid session'): readonly string[] {
  const result = strings(value, 16, f);
  if (result.some(item => !parseSessionSpec(item))) return f(label);
  return Object.freeze(result);
}
function dateString(date: Date): string { return date.toISOString().slice(0, 10); }
function date(value: string, f: Fail): Date {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return f('invalid exception date');
  const result = new Date(value + 'T00:00:00Z');
  if (!Number.isFinite(result.getTime()) || dateString(result) !== value) return f('invalid exception date');
  return result;
}
function zone(value: unknown, f: Fail): string {
  const timezone = text(value, 'timezone', f);
  return isValidTimezone(timezone) ? timezone : f('unknown timezone');
}
/**
 * A calendar's exception dates, validated the same way for an instrument and
 * a bare calendar so both refuse the same input. The weekly sessions are
 * checked by the caller, after the rest of its fields.
 */
function exceptionsOf(calendar: Record<string, unknown>, f: Fail): Readonly<Record<string, readonly string[]>> {
  const exceptions: Record<string, readonly string[]> = {};
  if (calendar.exceptions !== undefined) {
    const values = record(calendar.exceptions, f);
    if (Object.keys(values).length > 3660) return f('too many session exceptions');
    for (const [key, value] of Object.entries(values)) { date(key, f); exceptions[key] = sessions(value, f); }
  }
  return Object.freeze(exceptions);
}
type ExtendedHours = Pick<InstrumentCalendar, 'preMarketMinutes' | 'postMarketMinutes' | 'extendedHours'>;
/**
 * A calendar's extended hours, checked after every field that existed before
 * them so an input with an older fault still reports that fault first. Absent
 * fields stay absent, so a calendar without them keeps its old shape.
 */
function extendedOf(calendar: Record<string, unknown>, f: Fail): ExtendedHours {
  const out: { -readonly [K in keyof ExtendedHours]: ExtendedHours[K] } = {};
  for (const key of ['preMarketMinutes', 'postMarketMinutes'] as const) {
    const value = calendar[key];
    if (value === undefined) continue;
    if (typeof value !== 'number' || !Number.isInteger(value) || value < 0 || value >= 1440) return f(`${key} must be whole minutes under a day`);
    out[key] = value;
  }
  if (calendar.extendedHours !== undefined) out.extendedHours = sessions(calendar.extendedHours, f, 'invalid extended hours');
  return out;
}
function metadata(input: unknown): InstrumentMetadata {
  // The order of these checks decides which fault a host sees when an input
  // has several, and a host may match on that message, so it does not move.
  const raw = record(input), calendar = record(raw.calendar);
  const timezone = zone(raw.timezone, fail);
  const priceTick = positive(raw.priceTick, 'price tick');
  const precision = raw.pricePrecision;
  if (typeof precision !== 'number' || !Number.isInteger(precision) || precision < 0 || precision > 12) return fail('price precision must be 0..12');
  const units = priceTick * 10 ** precision;
  if (!Number.isFinite(units) || units < 1 || Math.abs(units - Math.round(units)) > 8 * Number.EPSILON * Math.max(1, units)) {
    return fail('price precision cannot represent the tick');
  }
  const intervals = strings(raw.intervals, 128);
  if (!intervals.length || new Set(intervals).size !== intervals.length) return fail('intervals must be nonempty and unique');
  for (const code of intervals) {
    const rule = tryResolveInterval(code)?.bucketing;
    if (!rule || (rule.mode === 'interval' && (!Number.isFinite(rule.seconds) || rule.seconds <= 0))) return fail(`unsupported interval ${code}`);
  }
  const exceptions = exceptionsOf(calendar, fail);
  if (raw.hasOpenInterest !== undefined && typeof raw.hasOpenInterest !== 'boolean') return fail('invalid OI capability');
  const bands = raw.tickBands === undefined ? undefined : new TickSchedule(raw.tickBands as readonly TickBand[]);
  // One number for the axis and the old tickSize readers, so it has to be the
  // grid every band lies on; a coarser one would move valid prices.
  if (bands && bands.minMove !== priceTick) return fail(`price tick ${priceTick} must equal the schedule's minimum move ${bands.minMove}`);
  return Object.freeze({
    symbol: text(raw.symbol, 'symbol'), exchange: text(raw.exchange, 'exchange'), timezone,
    priceTick, pricePrecision: precision, quantityStep: positive(raw.quantityStep, 'quantity step'),
    intervals: Object.freeze(intervals),
    calendar: Object.freeze({ sessions: sessions(calendar.sessions, fail), exceptions, ...extendedOf(calendar, fail) }),
    // A boolean by the check above; said again for a checker without strict
    // null checks (the docs site's), which does not carry that narrowing here.
    ...(raw.hasOpenInterest === undefined ? {} : { hasOpenInterest: raw.hasOpenInterest as boolean }),
    ...(bands ? { tickBands: bands.bands } : {}),
  });
}

function boundary(day: Date, minute: number, timezone: string, f: Fail): number {
  const civil = new Date(day.getTime() + minute * 60000);
  const year = civil.getUTCFullYear(), month = civil.getUTCMonth() + 1, d = civil.getUTCDate();
  const hour = civil.getUTCHours(), min = civil.getUTCMinutes();
  const answer = zonedWallClockToUtcSeconds(year, month, d, hour, min, 0, timezone);
  const actual = utcSecondsToZonedParts(answer, timezone);
  if (actual.year !== year || actual.month !== month || actual.day !== d || actual.hour !== hour || actual.minute !== min) {
    return f('session boundary is absent in this timezone');
  }
  return answer;
}

/**
 * How far ahead `sessionFrom` looks for an opening. Past a year of closed
 * dates the answer is "none", not a scan that grows with whatever a caller
 * asked about.
 */
const LOOKAHEAD_DAYS = 370;
/**
 * The longest range `phaseSpans` lays out. Its cost grows with the dates in
 * it, and a reader showing phases at bar level never needs more.
 */
const MAX_PHASE_RANGE = 400 * 86400;

/** Compiled windows and the reads over them, shared by an instrument and a bare calendar. */
class SessionHours {
  private readonly _sessions: readonly SessionSpec[];
  private readonly _exceptions: ReadonlyMap<string, readonly SessionSpec[]>;
  private readonly _extended: readonly SessionSpec[];
  /** Pre-open and post-close lengths, in seconds. */
  private readonly _pre: number;
  private readonly _post: number;

  public constructor(private readonly _zone: string, calendar: InstrumentCalendar, private readonly _fail: Fail) {
    this._sessions = calendar.sessions.map(item => parseSessionSpec(item)!);
    this._exceptions = new Map(Object.entries(calendar.exceptions ?? {})
      .map(([key, value]) => [key, value.map(item => parseSessionSpec(item)!)]));
    this._extended = (calendar.extendedHours ?? []).map(item => parseSessionSpec(item)!);
    this._pre = (calendar.preMarketMinutes ?? 0) * 60;
    this._post = (calendar.postMarketMinutes ?? 0) * 60;
  }

  /**
   * The windows opening on a local date. Asked about the day before an
   * instant, only a window running past midnight can still be open, and the
   * others are skipped before their boundaries are resolved: one of them may
   * fall in a daylight-saving gap that has nothing to do with the instant.
   */
  private _windows(day: Date, overnightOnly: boolean, specs?: readonly SessionSpec[]): InstrumentSession[] {
    const out: InstrumentSession[] = [], key = dateString(day);
    for (const spec of specs ?? this._exceptions.get(key) ?? this._sessions) {
      if (spec.days && !spec.days.includes(day.getUTCDay() + 1)) continue;
      if (overnightOnly && spec.end > spec.start) continue;
      out.push({
        date: key,
        open: boundary(day, spec.start, this._zone, this._fail),
        close: boundary(day, spec.end + (spec.end <= spec.start ? 1440 : 0), this._zone, this._fail),
      });
    }
    return out;
  }

  private _day(utcSeconds: number): (offset: number) => Date {
    if (!Number.isFinite(utcSeconds) || !Number.isFinite(new Date(utcSeconds * 1000).getTime())) return this._fail('invalid timestamp');
    const p = utcSecondsToZonedParts(utcSeconds, this._zone);
    return offset => new Date(Date.UTC(p.year, p.month - 1, p.day + offset));
  }

  public at(utcSeconds: number): InstrumentSession | null {
    const day = this._day(utcSeconds);
    let found: InstrumentSession | null = null;
    for (const offset of [0, -1]) {
      for (const window of this._windows(day(offset), offset === -1)) {
        // UTC comparisons survive a repeated DST hour; wall minutes do not.
        if (utcSeconds < window.open || utcSeconds >= window.close) continue;
        if (found) return this._fail('overlapping active sessions');
        found = window;
      }
    }
    return found;
  }

  public from(utcSeconds: number): InstrumentSession | null {
    const day = this._day(utcSeconds);
    // Yesterday first, for an overnight window still running. Windows are
    // grouped by opening date and every window of a date opens before any of
    // the next date's, so the first date with a window not yet closed holds
    // the answer: its earliest opening.
    for (let offset = -1; offset <= LOOKAHEAD_DAYS; offset++) {
      let found: InstrumentSession | null = null;
      for (const window of this._windows(day(offset), offset === -1)) {
        if (window.close > utcSeconds && (found === null || window.open < found.open)) found = window;
      }
      if (found) return found;
    }
    return null;
  }

  /**
   * One local date's hours, with their precedence: the regular windows opening
   * on it, the pre-open and post-close around them, its own extended hours,
   * and the whole date when it is a holiday.
   */
  private _layOut(day: Date, out: PhaseWindow[]): void {
    const regular = this._windows(day, false);
    for (const w of regular) out.push({ rank: 0, start: w.open, end: w.close });
    if (regular.length > 0) {
      const open = Math.min(...regular.map(w => w.open)), close = Math.max(...regular.map(w => w.close));
      if (this._pre > 0) out.push({ rank: 1, start: open - this._pre, end: open });
      if (this._post > 0) out.push({ rank: 2, start: close, end: close + this._post });
    }
    if (this._exceptions.get(dateString(day))?.length !== 0) {
      for (const w of this._windows(day, false, this._extended)) out.push({ rank: 3, start: w.open, end: w.close });
      return;
    }
    // Closed by an exception. A holiday only where the weekly hours would have
    // opened; an exception closing a weekend changes nothing a reader can see.
    const weekday = day.getUTCDay() + 1;
    if (!this._sessions.some(spec => !spec.days || spec.days.includes(weekday))) return;
    // Midnight, not a session boundary: a zone that skips it still has a date,
    // so this takes the nearest instant instead of refusing.
    const midnight = (d: Date): number => zonedWallClockToUtcSeconds(d.getUTCFullYear(), d.getUTCMonth() + 1, d.getUTCDate(), 0, 0, 0, this._zone);
    out.push({ rank: 4, start: midnight(day), end: midnight(new Date(day.getTime() + 86400000)) });
  }

  public spans(from: number, to: number): SessionPhaseSpan[] {
    const day = this._day(from), last = this._day(to)(0);
    if (!(to > from) || to - from > MAX_PHASE_RANGE) return this._fail('phase range must be ascending and at most 400 days');
    // Two dates back and one ahead: a window opening two dates before `from`
    // can still be in its post-close hours, and a pre-open can begin on the
    // date before the opening it leads to.
    const out: PhaseWindow[] = [], days = Math.round((last.getTime() - day(0).getTime()) / 86400000);
    for (let offset = -2; offset <= days + 1; offset++) this._layOut(day(offset), out);
    return partitionPhases(from, to, out);
  }

  // `spans` fails a range that is not ascending, and lays one out over any other.
  public phaseAt(utcSeconds: number): SessionPhase { return this.spans(utcSeconds, utcSeconds + 1)[0]!.phase; }
}

/**
 * Validated, detached trading hours: the calendar an {@link Instrument}
 * carries, without the price and quantity rules. Apply one to a chart so
 * times past the last bar follow the venue's sessions, and read it with the
 * same `sessionAt` and `sessionFrom`.
 */
export class SessionCalendar {
  /** The validated IANA zone. */
  public readonly timezone: string;
  /** A frozen copy of the windows and exceptions, detached from the input. */
  public readonly calendar: InstrumentCalendar;
  private readonly _hours: SessionHours;

  public constructor(input: unknown) {
    const f = failWith('session calendar'), raw = record(input, f);
    this.timezone = zone(raw.timezone, f);
    const exceptions = exceptionsOf(raw, f);
    this.calendar = Object.freeze({ sessions: sessions(raw.sessions, f), exceptions, ...extendedOf(raw, f) });
    this._hours = new SessionHours(this.timezone, this.calendar, f);
  }

  /** The window active at an instant. Closed dates and breaks return null, never inferred hours. */
  public sessionAt(utcSeconds: number): InstrumentSession | null { return this._hours.at(utcSeconds); }

  /**
   * The window active at an instant, or else the next one to open, looking at
   * most about a year ahead. Null when nothing opens in that time.
   */
  public sessionFrom(utcSeconds: number): InstrumentSession | null { return this._hours.from(utcSeconds); }

  /** The part of the trading day an instant falls in. */
  public phaseAt(utcSeconds: number): SessionPhase { return this._hours.phaseAt(utcSeconds); }

  /**
   * The phases from one instant to another, as consecutive spans clipped to
   * the range, which may be at most 400 days long.
   */
  public phaseSpans(fromUtcSeconds: number, toUtcSeconds: number): readonly SessionPhaseSpan[] {
    return this._hours.spans(fromUtcSeconds, toUtcSeconds);
  }

  /** The market status at an instant: pass `Date.now() / 1000` for now. */
  public marketStatusAt(utcSeconds: number): MarketStatus { return statusOf(this, utcSeconds); }

  /**
   * Lay the chart's time axis past the last bar out in these hours, and
   * repaint, so a drawing already placed there moves to the time it now
   * means: `chart.setSessionCalendar(this)`, after checking the chart is
   * alive. `chart.dataLayer.setSessionCalendar` sets the same without asking
   * for a frame, for a host about to load bars or move the view anyway.
   */
  public applyTo(chart: Chart): void {
    if (chart.isDestroyed) return failWith('session calendar')('chart is destroyed');
    chart.setSessionCalendar(this);
  }
}

/** Charts whose data context is already watched for a symbol change. */
const watched = new WeakSet<Chart>();

/**
 * An instrument's hours belong to its symbol. A host that moves the chart to
 * a symbol it holds no instrument for must not have that symbol's future laid
 * out in the last one's sessions, which the bars cannot always reveal: a
 * round-the-clock feed seen during cash hours sits inside them. Hours a host
 * set itself are the host's to replace.
 */
function dropHoursOnSymbolChange(chart: Chart): void {
  if (watched.has(chart)) return;
  watched.add(chart);
  chart.on('data:context', () => {
    const hours = chart.dataLayer.sessionCalendar, context = chart.getDataContext();
    if (hours instanceof Instrument
      && (hours.metadata.symbol !== context?.symbol || hours.metadata.exchange !== context?.exchange)) chart.dataLayer.setSessionCalendar(null);
  });
}

/** Validated, detached rules. Construction does not change global intervals or chart defaults. */
export class Instrument {
  public readonly metadata: InstrumentMetadata;
  /**
   * The validated `tickBands`, or null for a constant tick. A constant tick
   * has no schedule, so it keeps a single snapping rule, `priceTick`, on every
   * path: the order constraints, chart drags and anything the host builds.
   */
  public readonly tickSchedule: TickSchedule | null;
  private readonly _hours: SessionHours;

  public constructor(input: unknown) {
    this.metadata = metadata(input);
    this.tickSchedule = this.metadata.tickBands ? new TickSchedule(this.metadata.tickBands) : null;
    this._hours = new SessionHours(this.metadata.timezone, this.metadata.calendar, fail);
  }

  /** Provider tokens are exact: a feed may distinguish monthly M from minute m. */
  public supportsInterval(code: string): boolean { return this.metadata.intervals.includes(code); }

  /** Formats display only. The source bars retain their unrounded values. */
  public formatPrice(value: number): string { return Number.isFinite(value) ? value.toFixed(this.metadata.pricePrecision) : ''; }

  /** Resolve an active window. Closed dates and breaks return null, never inferred hours. */
  public sessionAt(utcSeconds: number): InstrumentSession | null { return this._hours.at(utcSeconds); }

  /**
   * The window active at an instant, or else the next one to open, looking at
   * most about a year ahead. Null when nothing opens in that time.
   */
  public sessionFrom(utcSeconds: number): InstrumentSession | null { return this._hours.from(utcSeconds); }

  /** The part of the trading day an instant falls in. */
  public phaseAt(utcSeconds: number): SessionPhase { return this._hours.phaseAt(utcSeconds); }

  /**
   * The phases from one instant to another, as consecutive spans clipped to
   * the range, which may be at most 400 days long.
   */
  public phaseSpans(fromUtcSeconds: number, toUtcSeconds: number): readonly SessionPhaseSpan[] {
    return this._hours.spans(fromUtcSeconds, toUtcSeconds);
  }

  /** The market status at an instant: pass `Date.now() / 1000` for now. */
  public marketStatusAt(utcSeconds: number): MarketStatus { return statusOf(this, utcSeconds); }

  /** The host clears old bars and owns source loading; only metadata is applied here. */
  public applyTo(chart: Chart, interval: string): void {
    if (!this.supportsInterval(interval)) return fail(`unsupported interval ${interval}`);
    if (chart.isDestroyed) return fail('chart is destroyed');
    const series = chart.primarySeries();
    if (!series) return fail('chart needs a primary series');
    const previous = chart.getDataContext(), m = this.metadata;
    if (previous && (previous.symbol !== m.symbol || previous.exchange !== m.exchange || previous.interval !== interval)
      && chart.primaryBars().length) return fail('clear previous source bars before applying metadata');
    chart.setTimezone(m.timezone);
    // The scale holds one tick, so a schedule gives it the common grid: the
    // axis then prints every band and its own snap never moves a valid price.
    chart.setPriceScaleOptions({ minMove: m.priceTick });
    // Oscillators and volume use their own units, even when their panes already exist.
    // The primary series can use a left or hidden scale instead of the chart default.
    series.priceScale().setOptions({ minMove: m.priceTick });
    series.priceScale().setPriceFormatter(value => this.formatPrice(value));
    // The variant is the host's choice of provider series, not instrument metadata, so it stays.
    // An undefined `hasOpenInterest` is the unknown capability, which the chart reads as absent.
    chart.setDataContext({ symbol: m.symbol, exchange: m.exchange, interval, hasOpenInterest: m.hasOpenInterest,
      ...(previous?.variant === undefined ? {} : { variant: previous.variant }) } satisfies LooseOptional<ChartDataContext> as ChartDataContext);
    // Times past the last bar follow this instrument's sessions, so a drawing
    // placed there after a close lands on the next opening. Another
    // instrument replaces them, and a context moved to another symbol drops
    // them.
    dropHoursOnSymbolChange(chart);
    chart.setSessionCalendar(this);
    // Drags snap by the same schedule the order constraints carry, and a
    // constant tick clears the one an earlier instrument left.
    chart.setTickSchedule(this.tickSchedule);
  }
}
