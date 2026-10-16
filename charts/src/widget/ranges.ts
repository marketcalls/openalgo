/**
 * Preset ranges: a named span of history (a day, five days, a month, the year
 * to date) with the interval it reads best at. DOM-free, so the packaged
 * widget and a custom host size and place a range by one set of rules.
 *
 * Two decisions carry it:
 *
 * - **A day is a trading session, not 24 hours.** One NSE day at one minute is
 *   375 bars, and asking a feed for 1,440 minutes back from 10:00 lands in the
 *   previous afternoon. With a session calendar a range walks back through the
 *   calendar's sessions, so a weekend or a closed date is skipped rather than
 *   counted. Without one it counts weekdays, and once bars are loaded it counts
 *   the dates the bars fall on.
 * - **A range ends at the latest bar it has, not at the wall clock.** Before
 *   the open, over a weekend, or with a feed that lags, "one day" is the last
 *   session that traded. The clock sizes the fetch; the bars place the view.
 */
import {
  DEFAULT_TIMEZONE, tryResolveInterval, utcSecondsToZonedParts, zonedWallClockToUtcSeconds,
  type InstrumentSession, type SessionCalendarSource,
} from 'openalgo-charts';

/**
 * How a range measures its span: trading sessions, calendar months or years
 * back, the year to date, or all the history the source has.
 */
export type WidgetRangeUnit = 'session' | 'month' | 'year' | 'ytd' | 'all';

/** A preset range for the bottom bar and `Widget.setRange`. */
export interface WidgetRange {
  /** Stable id: what `setRange` takes and `range()` returns. */
  readonly id: string;
  /** The button's text. */
  readonly label: string;
  /**
   * The interval the range shows. A host that does not offer it gets the
   * nearest interval it does offer (`rangeInterval`).
   */
  readonly interval: string;
  readonly unit: WidgetRangeUnit;
  /** How many units back, for `session`, `month` and `year`. Default 1. */
  readonly count?: number;
}

/** The window a range covers: UTC seconds, both ends inclusive. */
export interface WidgetRangeWindow {
  from: number;
  to: number;
}

export interface RangeWindowOptions {
  /**
   * The instant the range ends at, in UTC seconds: the clock when sizing a
   * fetch, the latest bar when placing a view.
   */
  readonly end: number;
  /** The zone a month, a year and a date without a calendar are counted in. Default `DEFAULT_TIMEZONE`. */
  readonly zone?: string;
  /** Trading hours: a `session` range counts this calendar's sessions. */
  readonly calendar?: SessionCalendarSource | null;
  /**
   * Bars already loaded, oldest first. Without a calendar a `session` range
   * counts the dates they fall on, and `all` starts at the first of them.
   */
  readonly bars?: readonly { readonly time: number }[] | undefined;
}

const DAY = 86400;
/** How far back one step of a session walk looks: two weeks of closures, with room to spare. */
const WALK_DAYS = 21;
/** The most sessions a range counts, so a walk stays a bounded number of calendar reads. */
const MAX_SESSIONS = 400;
/** How far back `all` asks a source, when there are no bars yet to start from. */
const ALL_YEARS = 30;

const freeze = (range: WidgetRange): WidgetRange => Object.freeze({ ...range });

/**
 * The presets the bottom bar offers when the host names none. Each pairs a
 * span with an interval that draws it in a few hundred bars, not tens of
 * thousands: a day at one minute, a year at one day.
 */
export const DEFAULT_RANGES: readonly WidgetRange[] = Object.freeze([
  freeze({ id: '1D', label: '1D', interval: '1m', unit: 'session', count: 1 }),
  freeze({ id: '5D', label: '5D', interval: '5m', unit: 'session', count: 5 }),
  freeze({ id: '1M', label: '1M', interval: '30m', unit: 'month', count: 1 }),
  freeze({ id: '3M', label: '3M', interval: '1h', unit: 'month', count: 3 }),
  freeze({ id: '6M', label: '6M', interval: '1d', unit: 'month', count: 6 }),
  freeze({ id: 'YTD', label: 'YTD', interval: '1d', unit: 'ytd' }),
  freeze({ id: '1Y', label: '1Y', interval: '1d', unit: 'year', count: 1 }),
  freeze({ id: '5Y', label: '5Y', interval: '1w', unit: 'year', count: 5 }),
  freeze({ id: 'ALL', label: 'All', interval: '1w', unit: 'all' }),
]);

/** A bar's length in seconds, a calendar month taken at its average; null for tick and volume bars. */
function approxSeconds(code: string): number | null {
  const found = tryResolveInterval(code);
  if (found === null) return null;
  const b = found.bucketing;
  if (b.mode === 'interval') return b.seconds;
  if (b.mode !== 'calendar') return null;
  const months = (b.unit === 'year' ? 12 : b.unit === 'quarter' ? 3 : 1) * Math.max(1, Math.floor(b.count ?? 1));
  return months * 30.44 * DAY;
}

/**
 * The interval a range is shown at, from those `offered`: its own when it is
 * offered, else the nearest time-based one by ratio (a 30-minute range picks
 * 15 minutes or an hour, not 5 minutes), the longer on a tie so the range
 * loads fewer bars. Its own interval when nothing offered is time-based.
 */
export function rangeInterval(range: WidgetRange, offered: readonly string[]): string {
  if (offered.includes(range.interval)) return range.interval;
  const want = approxSeconds(range.interval);
  if (want === null) return range.interval;
  let best: string | null = null;
  let bestGap = Infinity;
  let bestSeconds = 0;
  for (const code of offered) {
    const seconds = approxSeconds(code);
    if (seconds === null) continue;
    const gap = Math.abs(Math.log(seconds / want));
    if (gap < bestGap - 1e-9 || (Math.abs(gap - bestGap) <= 1e-9 && seconds > bestSeconds)) {
      best = code;
      bestGap = gap;
      bestSeconds = seconds;
    }
  }
  return best ?? range.interval;
}

/** The last session to open before `t`, or null when none opened in the look-back. */
function sessionBefore(calendar: SessionCalendarSource, t: number): InstrumentSession | null {
  for (let back = 1; back <= WALK_DAYS; back++) {
    let s = calendar.sessionFrom(t - back * DAY);
    if (s === null) return null;
    if (s.open >= t) continue;
    // The probe landed a day back; walk forward to the last window opening before t,
    // which on a date with a break is its afternoon window, not its morning one.
    for (let next = calendar.sessionFrom(s.close); next !== null && next.open < t && next.open > s.open; next = calendar.sessionFrom(next.close)) s = next;
    return s;
  }
  return null;
}

/**
 * Where `count` trading dates back from `end` begin: the first opening of the
 * oldest of them. A date with a midday break is one date, and extended hours
 * right before that opening belong to it. Null without a session near `end`.
 */
function sessionsStart(calendar: SessionCalendarSource, end: number, count: number): number | null {
  let s = calendar.sessionFrom(end);
  if (s === null || s.open > end) s = sessionBefore(calendar, end);
  if (s === null) return null;
  let date = s.date;
  let first = s.open;
  let dates = 1;
  for (let guard = 0; guard < count * 12 + 12; guard++) {
    const p = sessionBefore(calendar, first);
    if (p === null) break;
    if (p.date === date) { first = p.open; continue; }
    if (dates >= count) break;
    dates++;
    date = p.date;
    first = p.open;
  }
  if (calendar.phaseSpans) {
    try {
      const spans = calendar.phaseSpans(first - DAY, first);
      const last = spans[spans.length - 1];
      if (last !== undefined && last.phase === 'pre' && last.end === first) first = last.start;
    } catch { /* The opening stands without its pre-open. */ }
  }
  return first;
}

/** Local midnight `days` calendar days before the day of `t`, in `zone`. */
function midnightBefore(t: number, zone: string, days: number): number {
  const p = utcSecondsToZonedParts(t, zone);
  return zonedWallClockToUtcSeconds(p.year, p.month, p.day - days, 0, 0, 0, zone);
}

/**
 * Without a calendar: midnight of the weekday `count` weekdays before the day
 * of `end`, so a fetch made before the open, or on a weekend, still reaches
 * the last session that traded. A holiday in the span leaves it a session
 * short, which a placement makes up by loading older history.
 */
function weekdaysBack(end: number, zone: string, count: number): number {
  const weekday = utcSecondsToZonedParts(end, zone).weekday;
  let days = 0;
  for (let left = count, w = weekday; left > 0;) {
    days++;
    w = (w + 6) % 7;
    if (w !== 0 && w !== 6) left--;
  }
  return midnightBefore(end, zone, days);
}

/** The first bar of the `count`-th most recent date the bars fall on, in `zone`. */
function datesBack(bars: readonly { readonly time: number }[], zone: string, count: number): number {
  // rangeWindow passes loaded bars only, never an empty list; i stays inside them.
  let seen = 0;
  let day = NaN;
  let from = bars[bars.length - 1]!.time;
  for (let i = bars.length - 1; i >= 0; i--) {
    const midnight = midnightBefore(bars[i]!.time, zone, 0);
    if (midnight !== day) {
      if (seen === count) break;
      seen++;
      day = midnight;
    }
    from = bars[i]!.time;
  }
  return from;
}

/** Midnight on the same date `months` calendar months back, the day clamped to that month's length. */
function monthsBack(end: number, zone: string, months: number): number {
  const p = utcSecondsToZonedParts(end, zone);
  const first = new Date(Date.UTC(p.year, p.month - 1 - months, 1));
  const year = first.getUTCFullYear();
  const month = first.getUTCMonth() + 1;
  const length = new Date(Date.UTC(year, month, 0)).getUTCDate();
  return zonedWallClockToUtcSeconds(year, month, Math.min(p.day, length), 0, 0, 0, zone);
}

/**
 * The window a range covers, ending at `options.end`. A `session` range walks
 * back through the calendar's sessions when there is one; without one it
 * counts the dates of the loaded bars, or weekdays when none are loaded. A
 * month or a year runs from midnight on the same date that far back, the year
 * to date from the first of January, all history from the first loaded bar
 * (or 30 years back before any are loaded). Months, years and dates without a
 * calendar are counted in `options.zone`.
 */
export function rangeWindow(range: WidgetRange, options: RangeWindowOptions): WidgetRangeWindow {
  const end = options.end;
  const zone = options.zone ?? DEFAULT_TIMEZONE;
  const bars = options.bars !== undefined && options.bars.length > 0 ? options.bars : null;
  const count = Math.max(1, Math.min(MAX_SESSIONS, Math.floor(range.count ?? 1)));
  let from: number;
  switch (range.unit) {
    case 'session': {
      let start: number | null = null;
      if (options.calendar) {
        // A calendar that cannot answer (a window a clock change removes) falls back to dates.
        try { start = sessionsStart(options.calendar, end, count); } catch { start = null; }
      }
      from = start ?? (bars !== null ? datesBack(bars, zone, count) : weekdaysBack(end, zone, count));
      break;
    }
    case 'month': from = monthsBack(end, zone, count); break;
    case 'year': from = monthsBack(end, zone, count * 12); break;
    case 'ytd': {
      const p = utcSecondsToZonedParts(end, zone);
      from = zonedWallClockToUtcSeconds(p.year, 1, 1, 0, 0, 0, zone);
      break;
    }
    default:
      from = bars !== null ? bars[0]!.time : monthsBack(end, zone, ALL_YEARS * 12); // bars is null when empty
  }
  return { from: Math.min(from, end), to: end };
}
