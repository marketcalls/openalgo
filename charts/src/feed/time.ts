/**
 * Time conversions (ARCHITECTURE.md §4.0). Internal time is always UTC seconds.
 * Feed adapters convert broker formats here, at the edge:
 *   - REST history: IST date/time strings
 *   - WS feed: epoch milliseconds
 * India observes no DST, so IST is a fixed UTC+5:30 offset.
 */

/** IST offset in seconds (UTC+5:30). */
export const IST_OFFSET_SECONDS = 5 * 3600 + 30 * 60;

/** Epoch milliseconds to UTC seconds. */
export function epochMsToUtcSeconds(ms: number): number {
  return Math.floor(ms / 1000);
}

/**
 * Parse an IST wall-clock date/time string to UTC seconds. Accepts
 * `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, and the `T`-separated ISO variant.
 * Parsing is explicit (never relies on the host machine's locale/timezone).
 */
export function istStringToUtcSeconds(input: string): number {
  const s = input.trim();
  const dt = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(s);
  if (dt === null) {
    throw new Error(`openalgo-charts: unparseable IST time string "${input}"`);
  }
  const year = Number(dt[1]);
  const month = Number(dt[2]);
  const day = Number(dt[3]);
  const hour = dt[4] !== undefined ? Number(dt[4]) : 0;
  const min = dt[5] !== undefined ? Number(dt[5]) : 0;
  const sec = dt[6] !== undefined ? Number(dt[6]) : 0;
  // Treat the components as IST wall-clock, then subtract the offset to get UTC.
  const asUtcMs = Date.UTC(year, month - 1, day, hour, min, sec);
  return Math.floor(asUtcMs / 1000) - IST_OFFSET_SECONDS;
}

export interface IstParts {
  year: number;
  month: number; // 1-12
  day: number;
  hour: number;
  minute: number;
  second: number;
  /** 0 = Sunday .. 6 = Saturday, in IST. */
  weekday: number;
}

/** UTC seconds to IST calendar parts (for axis labels / tick decisions). */
export function utcSecondsToIstParts(utcSeconds: number): IstParts {
  const d = new Date((utcSeconds + IST_OFFSET_SECONDS) * 1000);
  return {
    year: d.getUTCFullYear(),
    month: d.getUTCMonth() + 1,
    day: d.getUTCDate(),
    hour: d.getUTCHours(),
    minute: d.getUTCMinutes(),
    second: d.getUTCSeconds(),
    weekday: d.getUTCDay(),
  };
}

const pad2 = (n: number): string => (n < 10 ? `0${n}` : String(n));

/** Format UTC seconds as an IST `HH:MM` clock label. */
export function formatIstTime(utcSeconds: number): string {
  const p = utcSecondsToIstParts(utcSeconds);
  return `${pad2(p.hour)}:${pad2(p.minute)}`;
}

/** Format UTC seconds as an IST `HH:MM:SS` clock label (sub-minute / tick timeframes). */
export function formatIstTimeSeconds(utcSeconds: number): string {
  const p = utcSecondsToIstParts(utcSeconds);
  return `${pad2(p.hour)}:${pad2(p.minute)}:${pad2(p.second)}`;
}

/** Format UTC seconds as an IST `YYYY-MM-DD` date (for OpenAlgo history requests). */
export function utcSecondsToIstDateString(utcSeconds: number): string {
  const p = utcSecondsToIstParts(utcSeconds);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)}`;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

/** Format UTC seconds as an IST `DD Mon` date label. */
export function formatIstDate(utcSeconds: number): string {
  const p = utcSecondsToIstParts(utcSeconds);
  return `${pad2(p.day)} ${MONTHS[p.month - 1]}`;
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

/**
 * Crosshair time-tag label in IST, matching the reference style:
 * `Wed 21 May '26`, with ` HH:MM` appended for intraday (non-midnight) bars.
 */
export function formatIstCrosshairLabel(utcSeconds: number): string {
  const p = utcSecondsToIstParts(utcSeconds);
  let s = `${WEEKDAYS[p.weekday]} ${pad2(p.day)} ${MONTHS[p.month - 1]} '${String(p.year).slice(-2)}`;
  if (p.hour !== 0 || p.minute !== 0 || p.second !== 0) {
    s += ` ${pad2(p.hour)}:${pad2(p.minute)}`;
    // Sub-minute (seconds / tick) timeframes: append :SS so bars within the
    // same minute are distinguishable.
    if (p.second !== 0) s += `:${pad2(p.second)}`;
  }
  return s;
}

/** True if the two UTC-second instants fall on different IST calendar days. */
export function isNewIstDay(prevUtcSeconds: number, utcSeconds: number): boolean {
  const a = utcSecondsToIstParts(prevUtcSeconds);
  const b = utcSecondsToIstParts(utcSeconds);
  return a.year !== b.year || a.month !== b.month || a.day !== b.day;
}

// ---------------------------------------------------------------------------
// Zone-aware time (general form)
//
// Everything above is the IST special case, kept because it is public API since
// 1.x. Everything below is the same job for an arbitrary IANA zone, and it is
// what the chart, the axis and the indicators should be reaching for.
//
// IANA names and not fixed offsets: IST has no DST so an offset would do for the
// default, but America/New_York and Europe/London shift twice a year and a fixed
// offset is silently wrong for half of it. Intl.DateTimeFormat ships in every
// browser and every Node, so the zone table costs nothing against the bundle and
// is DST-correct without us shipping one.
// ---------------------------------------------------------------------------

/**
 * The shipped default zone. A caller who passes no timezone gets exactly what
 * v1.2.0 produced; openalgo-charts is a general library that happens to ship an
 * Indian default, not an Indian library.
 */
export const DEFAULT_TIMEZONE = 'Asia/Kolkata';

/**
 * Calendar parts of an instant in some IANA zone. Structurally identical to
 * `IstParts`, which is now the special case rather than the assumption.
 */
export type ZonedParts = IstParts;

/** Calendar periods the indicators and profiles anchor to. */
export type ZonedPeriod = 'day' | 'week' | 'month' | 'quarter' | 'year';

/** Parts plus the derived integers, so a boundary test is an integer compare. */
interface CachedParts {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
  weekday: number;
  /** Whole days since 1970-01-01 as counted in this zone. */
  dayIndex: number;
}

interface ZoneCache {
  format: Intl.DateTimeFormat;
  /** Resolved parts by UTC second. */
  parts: Map<number, CachedParts>;
  /** One-slot front of the map: the axis asks for the same tick repeatedly. */
  lastSecond: number;
  lastParts: CachedParts | null;
}

const ZONE_CACHES = new Map<string, ZoneCache>();

/**
 * How many distinct seconds a zone remembers. A long pan visits a lot of them
 * and an unbounded map would grow for the life of the page; a frame's worth of
 * ticks is two orders of magnitude below this, so the cap is never reached by
 * the case it exists to make fast.
 */
const PARTS_CACHE_LIMIT = 4096;

const WEEKDAY_INDEX: Readonly<Record<string, number>> = {
  Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6,
};

function zoneCache(zone: string): ZoneCache {
  let cache = ZONE_CACHES.get(zone);
  if (cache === undefined) {
    let format: Intl.DateTimeFormat;
    try {
      format = new Intl.DateTimeFormat('en-US', {
        timeZone: zone,
        // h23 and not `hour12: false`: some ICU builds answer the latter with
        // hour 24 at local midnight, which would put every session opening bar
        // on the previous day.
        hourCycle: 'h23',
        year: 'numeric', month: '2-digit', day: '2-digit',
        hour: '2-digit', minute: '2-digit', second: '2-digit',
        weekday: 'short',
      });
    } catch {
      throw new Error(`openalgo-charts: unknown IANA time zone "${zone}"`);
    }
    cache = { format, parts: new Map(), lastSecond: Number.NaN, lastParts: null };
    ZONE_CACHES.set(zone, cache);
  }
  return cache;
}

/** True when the runtime recognises `zone` as an IANA zone name. */
export function isValidTimezone(zone: string): boolean {
  if (ZONE_CACHES.has(zone)) return true;
  try {
    zoneCache(zone);
    return true;
  } catch {
    return false;
  }
}

function buildParts(format: Intl.DateTimeFormat, utcSeconds: number): CachedParts {
  let year = 1970;
  let month = 1;
  let day = 1;
  let hour = 0;
  let minute = 0;
  let second = 0;
  let weekday = 4; // 1970-01-01 was a Thursday
  for (const part of format.formatToParts(new Date(utcSeconds * 1000))) {
    switch (part.type) {
      case 'year': year = Number(part.value); break;
      case 'month': month = Number(part.value); break;
      case 'day': day = Number(part.value); break;
      case 'hour': hour = Number(part.value) % 24; break;
      case 'minute': minute = Number(part.value); break;
      case 'second': second = Number(part.value); break;
      case 'weekday': weekday = WEEKDAY_INDEX[part.value] ?? 0; break;
      default: break;
    }
  }
  return {
    year, month, day, hour, minute, second, weekday,
    dayIndex: Math.floor(Date.UTC(year, month - 1, day) / 86400000),
  };
}

/**
 * The cached parts object for an instant. Internal because the object is shared
 * with every later reader of the same second: nothing may mutate it, and the
 * public getter hands back a copy.
 */
function resolveParts(utcSeconds: number, zone: string): CachedParts {
  const cache = zoneCache(zone);
  if (utcSeconds === cache.lastSecond && cache.lastParts !== null) return cache.lastParts;
  let parts = cache.parts.get(utcSeconds);
  if (parts === undefined) {
    parts = buildParts(cache.format, utcSeconds);
    if (cache.parts.size >= PARTS_CACHE_LIMIT) cache.parts.clear();
    cache.parts.set(utcSeconds, parts);
  }
  cache.lastSecond = utcSeconds;
  cache.lastParts = parts;
  return parts;
}

/** UTC seconds to calendar parts in `zone` (for axis labels / tick decisions). */
export function utcSecondsToZonedParts(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): ZonedParts {
  const p = resolveParts(utcSeconds, zone);
  // A copy on purpose: the cached object is handed to every repeat reader of
  // this second, so a caller that adjusted a field would corrupt all of them.
  return {
    year: p.year, month: p.month, day: p.day,
    hour: p.hour, minute: p.minute, second: p.second, weekday: p.weekday,
  };
}

/** Whole days since 1970-01-01, counted in `zone`. Allocation-free on a repeat. */
export function zonedDayIndex(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  return resolveParts(utcSeconds, zone).dayIndex;
}

/**
 * Week number since the epoch, counted in `zone`, weeks starting Monday.
 * 1970-01-01 was a Thursday, hence the +3 before the divide.
 */
export function zonedWeekIndex(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  return Math.floor((resolveParts(utcSeconds, zone).dayIndex + 3) / 7);
}

/**
 * The zone's offset from UTC at this instant, in seconds. DST-correct: ask it
 * for a July instant and a January one in the same northern zone and the two
 * answers differ.
 */
export function zoneOffsetSeconds(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  const p = resolveParts(utcSeconds, zone);
  const wall = Math.floor(Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) / 1000);
  return wall - utcSeconds;
}

// The boundary tests. They run per bar over tens of thousands of bars, so each
// one is two cache reads and an integer compare, with no object built once the
// second has been seen.

/** True if the two instants fall on different calendar days in `zone`. */
export function isNewZonedDay(prevUtcSeconds: number, utcSeconds: number, zone: string = DEFAULT_TIMEZONE): boolean {
  // `prev` first, so the one-slot cache ends up holding `now`, which is the
  // `prev` of the next call in a per-bar sweep.
  const a = resolveParts(prevUtcSeconds, zone).dayIndex;
  return a !== resolveParts(utcSeconds, zone).dayIndex;
}

/** True if the two instants fall in different Monday-start weeks in `zone`. */
export function isNewZonedWeek(prevUtcSeconds: number, utcSeconds: number, zone: string = DEFAULT_TIMEZONE): boolean {
  const a = Math.floor((resolveParts(prevUtcSeconds, zone).dayIndex + 3) / 7);
  return a !== Math.floor((resolveParts(utcSeconds, zone).dayIndex + 3) / 7);
}

/** True if the two instants fall in different calendar months in `zone`. */
export function isNewZonedMonth(prevUtcSeconds: number, utcSeconds: number, zone: string = DEFAULT_TIMEZONE): boolean {
  const a = resolveParts(prevUtcSeconds, zone);
  const b = resolveParts(utcSeconds, zone);
  return a.year !== b.year || a.month !== b.month;
}

/** True if the two instants fall in different calendar quarters in `zone`. */
export function isNewZonedQuarter(prevUtcSeconds: number, utcSeconds: number, zone: string = DEFAULT_TIMEZONE): boolean {
  const a = resolveParts(prevUtcSeconds, zone);
  const b = resolveParts(utcSeconds, zone);
  return a.year !== b.year || Math.floor((a.month - 1) / 3) !== Math.floor((b.month - 1) / 3);
}

/** True if the two instants fall in different calendar years in `zone`. */
export function isNewZonedYear(prevUtcSeconds: number, utcSeconds: number, zone: string = DEFAULT_TIMEZONE): boolean {
  return resolveParts(prevUtcSeconds, zone).year !== resolveParts(utcSeconds, zone).year;
}

/** The boundary test for one period, for a caller that carries the period as data. */
export function isNewZonedPeriod(
  prevUtcSeconds: number,
  utcSeconds: number,
  period: ZonedPeriod,
  zone: string = DEFAULT_TIMEZONE,
): boolean {
  switch (period) {
    case 'week': return isNewZonedWeek(prevUtcSeconds, utcSeconds, zone);
    case 'month': return isNewZonedMonth(prevUtcSeconds, utcSeconds, zone);
    case 'quarter': return isNewZonedQuarter(prevUtcSeconds, utcSeconds, zone);
    case 'year': return isNewZonedYear(prevUtcSeconds, utcSeconds, zone);
    default: return isNewZonedDay(prevUtcSeconds, utcSeconds, zone);
  }
}

/**
 * Parse a wall-clock date/time string in `zone` to UTC seconds. Accepts the same
 * shapes as `istStringToUtcSeconds`: `YYYY-MM-DD`, `YYYY-MM-DD HH:MM[:SS]`, and
 * the `T`-separated ISO variant. Never consults the host machine's own zone.
 */
export function zonedStringToUtcSeconds(input: string, zone: string = DEFAULT_TIMEZONE): number {
  const s = input.trim();
  const dt = /^(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?/.exec(s);
  if (dt === null) {
    throw new Error(`openalgo-charts: unparseable time string "${input}"`);
  }
  return zonedWallClockToUtcSeconds(
    Number(dt[1]), Number(dt[2]), Number(dt[3]),
    dt[4] !== undefined ? Number(dt[4]) : 0,
    dt[5] !== undefined ? Number(dt[5]) : 0,
    dt[6] !== undefined ? Number(dt[6]) : 0,
    zone,
  );
}

/**
 * Wall-clock components in `zone` to UTC seconds.
 *
 * Two passes because the offset we need is the one in force at the *answer*,
 * not at the guess: on a DST changeover day the first pass can land an hour out,
 * and the second pass corrects it. A wall time that a spring-forward skipped has
 * no exact answer; this settles on the instant one offset-step later, which is
 * the same choice `Date` makes.
 */
export function zonedWallClockToUtcSeconds(
  year: number, month: number, day: number,
  hour = 0, minute = 0, second = 0,
  zone: string = DEFAULT_TIMEZONE,
): number {
  const wall = Math.floor(Date.UTC(year, month - 1, day, hour, minute, second) / 1000);
  const first = wall - zoneOffsetSeconds(wall, zone);
  return wall - zoneOffsetSeconds(first, zone);
}

/** UTC seconds of the local midnight opening this instant's day in `zone`. */
export function startOfZonedDay(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  const p = resolveParts(utcSeconds, zone);
  return zonedWallClockToUtcSeconds(p.year, p.month, p.day, 0, 0, 0, zone);
}

/** UTC seconds of the local midnight opening this instant's Monday in `zone`. */
export function startOfZonedWeek(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  const p = resolveParts(utcSeconds, zone);
  const backToMonday = (p.weekday + 6) % 7;
  // Step back in calendar days, not by 86400 seconds: a DST week is 167 or 169
  // hours long and subtracting fixed days would land on the wrong date.
  const civil = new Date(Date.UTC(p.year, p.month - 1, p.day - backToMonday));
  return zonedWallClockToUtcSeconds(
    civil.getUTCFullYear(), civil.getUTCMonth() + 1, civil.getUTCDate(), 0, 0, 0, zone,
  );
}

/** UTC seconds of the local midnight opening this instant's month in `zone`. */
export function startOfZonedMonth(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): number {
  const p = resolveParts(utcSeconds, zone);
  return zonedWallClockToUtcSeconds(p.year, p.month, 1, 0, 0, 0, zone);
}

/** Format UTC seconds as an `HH:MM` clock label in `zone`. */
export function formatZonedTime(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): string {
  const p = resolveParts(utcSeconds, zone);
  return `${pad2(p.hour)}:${pad2(p.minute)}`;
}

/** Format UTC seconds as an `HH:MM:SS` clock label in `zone` (sub-minute timeframes). */
export function formatZonedTimeSeconds(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): string {
  const p = resolveParts(utcSeconds, zone);
  return `${pad2(p.hour)}:${pad2(p.minute)}:${pad2(p.second)}`;
}

/** Format UTC seconds as a `DD Mon` date label in `zone`. */
export function formatZonedDate(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): string {
  const p = resolveParts(utcSeconds, zone);
  return `${pad2(p.day)} ${MONTHS[p.month - 1]}`;
}

/** Format UTC seconds as a `YYYY-MM-DD` date in `zone`. */
export function utcSecondsToZonedDateString(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): string {
  const p = resolveParts(utcSeconds, zone);
  return `${p.year}-${pad2(p.month)}-${pad2(p.day)}`;
}

/** Crosshair time-tag label in `zone`, in the same style as the IST form. */
export function formatZonedCrosshairLabel(utcSeconds: number, zone: string = DEFAULT_TIMEZONE): string {
  const p = resolveParts(utcSeconds, zone);
  let s = `${WEEKDAYS[p.weekday]} ${pad2(p.day)} ${MONTHS[p.month - 1]} '${String(p.year).slice(-2)}`;
  if (p.hour !== 0 || p.minute !== 0 || p.second !== 0) {
    s += ` ${pad2(p.hour)}:${pad2(p.minute)}`;
    if (p.second !== 0) s += `:${pad2(p.second)}`;
  }
  return s;
}

const HOUR_SECONDS = 3600;
const DAY_SECONDS = 86400;

/**
 * Median gap between consecutive timestamps. Median and not mean: a weekend, a
 * holiday or an outage leaves a handful of gaps orders of magnitude wider than
 * the timeframe, and an average would chase them.
 */
function medianGap(times: readonly number[]): number {
  const gaps: number[] = [];
  for (let i = 1; i < times.length; i++) {
    const d = times[i]! - times[i - 1]!;
    if (d > 0) gaps.push(d);
  }
  if (gaps.length === 0) return 0;
  gaps.sort((a, b) => a - b);
  return gaps[gaps.length >> 1]!;
}

/**
 * Bar indices that open a new trading session, read back from the timestamps.
 *
 * An exchange's overnight break is the widest recurring gap in an intraday
 * series, and it is the only thing in the bars themselves that says where one
 * trading day ends. Reading it back beats assuming a timezone: the same code
 * has to serve an exchange in Mumbai and one in New York, and a fixed midnight
 * lands mid-session for one of them. Getting it wrong splices the tail of one
 * session onto the head of the next across the overnight gap, which inflates
 * that period's high-low range and throws anything measured from it a long way
 * off.
 *
 * Returns null when the series shows no readable session break: a market that
 * never closes, bars already a day or coarser, or a feed whose only gaps are
 * weekends. The caller then falls back to a calendar rule, which is the right
 * answer in exactly those cases.
 */
export function sessionStartIndices(times: readonly number[]): number[] | null {
  const gap = medianGap(times);
  if (gap <= 0 || gap >= DAY_SECONDS) return null;
  // At least four hours and at least four bars: every market that has both a
  // lunch break and an overnight break has the shorter one well under this.
  const threshold = Math.max(4 * gap, 4 * HOUR_SECONDS);
  const starts: number[] = [];
  for (let i = 1; i < times.length; i++) {
    if (times[i]! - times[i - 1]! >= threshold) starts.push(i);
  }
  if (starts.length === 0) return null;
  // Spot FX breaks only at weekends and clears the same threshold, so its
  // "sessions" would be whole weeks. Accept the reading only when the breaks
  // recur at roughly daily cadence. The trailing partial session is left out:
  // it is short by construction and would drag the median down.
  // A start is an index of `times` past the first, so `opens` holds two or more.
  const opens = [times[0]!, ...starts.map((i) => times[i]!)];
  const spans: number[] = [];
  for (let i = 1; i < opens.length; i++) spans.push(opens[i]! - opens[i - 1]!);
  spans.sort((a, b) => a - b);
  if (spans[spans.length >> 1]! > 36 * HOUR_SECONDS) return null;
  return starts;
}

/**
 * Per-bar flags marking the first bar of each trading session.
 *
 * Falls back to the calendar day in `zone` when the series has no readable
 * session break, which is the only answer available for daily bars and a
 * defensible one for a market that never closes. The zone defaults to IST, so a
 * caller that passes nothing gets exactly the old behaviour.
 */
export function sessionStartFlags(times: readonly number[], zone: string = DEFAULT_TIMEZONE): boolean[] {
  const out = new Array<boolean>(times.length).fill(false);
  const starts = sessionStartIndices(times);
  if (starts === null) {
    // This loop runs once per bar over a whole daily history, and Intl costs
    // roughly 25x the offset arithmetic (measured: 137ms against 5ms over 50k
    // bars). The two answers are pinned identical for the default zone, so the
    // branch buys back the old speed for every existing caller and changes
    // nothing about what it returns.
    const isNewDay = zone === DEFAULT_TIMEZONE
      ? isNewIstDay
      : (prev: number, now: number): boolean => isNewZonedDay(prev, now, zone);
    for (let i = 1; i < times.length; i++) out[i] = isNewDay(times[i - 1]!, times[i]!);
    return out;
  }
  for (const i of starts) out[i] = true;
  return out;
}

/**
 * Per-bar flags marking the first bar of each calendar period, where `isNew`
 * decides what "period" means for two instants.
 *
 * The test runs on session opens rather than on every bar, so a session that
 * straddles the boundary is not cut in half: the last ninety minutes of a New
 * York Friday fall on a Saturday in IST, and testing bar to bar would start the
 * next week partway through Friday's session. With no readable sessions the
 * test runs bar to bar, which is the same thing when each bar is its own
 * session.
 */
export function calendarPeriodFlags(
  times: readonly number[],
  isNew: (prevUtcSeconds: number, utcSeconds: number) => boolean,
): boolean[] {
  const out = new Array<boolean>(times.length).fill(false);
  const starts = sessionStartIndices(times);
  if (starts === null) {
    for (let i = 1; i < times.length; i++) out[i] = isNew(times[i - 1]!, times[i]!);
    return out;
  }
  // Session starts are indices of `times` past the first, so there is a first bar.
  let prevOpen = times[0]!;
  for (const i of starts) {
    if (isNew(prevOpen, times[i]!)) out[i] = true;
    prevOpen = times[i]!;
  }
  return out;
}

// ---------------------------------------------------------------------------
// Session windows
//
// The helpers above read a session back from the bars. This is the other half:
// a window the caller states outright, for an indicator anchored to an opening
// range, a cash session inside an extended one, or one exchange's hours drawn
// on another exchange's chart. Stated and not inferred, because the bars cannot
// tell you which part of a continuous session you meant.
// ---------------------------------------------------------------------------

/** A trading window in local wall-clock terms, as parsed from a spec string. */
export interface SessionSpec {
  /** Minutes from midnight, inclusive. */
  start: number;
  /** Minutes from midnight, exclusive. */
  end: number;
  /** Days the window opens on, 1..7 with 1 = Sunday. Absent means every day. */
  days?: readonly number[];
}

// The whitespace before the optional day list lives inside the group. Left
// outside it, an absent group leaves `\s*\s*$`, and trailing spaces on a spec
// that does not match split between the two in quadratically many ways.
const SESSION_RE = /^\s*(\d{2})(\d{2})\s*-\s*(\d{2})(\d{2})(?:\s*:\s*([1-7]+))?\s*$/;

/** `HH` and `MM` as minutes from midnight, or -1 if either is out of range. */
function specMinutes(hh: string, mm: string): number {
  const h = Number(hh);
  const m = Number(mm);
  return h > 23 || m > 59 ? -1 : h * 60 + m;
}

/**
 * Parse `"0915-1015"`, optionally with a day filter after a colon:
 * `"0930-1600:23456"` is Monday to Friday. Whitespace around the parts is
 * ignored. An end at or before the start is a window that runs past midnight.
 *
 * Returns null rather than throwing, because the spec is normally a string a
 * user typed into a settings field and a half-typed one arrives on every
 * keystroke.
 */
export function parseSessionSpec(spec: string): SessionSpec | null {
  const m = SESSION_RE.exec(spec);
  if (m === null) return null;
  // The first four groups take part in every match; only the day list is optional.
  const start = specMinutes(m[1]!, m[2]!);
  const end = specMinutes(m[3]!, m[4]!);
  if (start < 0 || end < 0) return null;
  return m[5] === undefined ? { start, end } : { start, end, days: [...m[5]].map(Number) };
}

/** Membership test against already-resolved parts, so a sweep resolves once. */
function inSessionParts(p: CachedParts, spec: SessionSpec): boolean {
  const minute = p.hour * 60 + p.minute;
  const wraps = spec.end <= spec.start;
  // Half-open at the end: a bar stamped exactly at 10:15 belongs to what comes
  // after a 0915-1015 window, which is what an opening-range comparison needs.
  const past = minute < spec.end;
  if (!(wraps ? minute >= spec.start || past : minute >= spec.start && past)) return false;
  if (spec.days === undefined) return true;
  // The filter names the day the window opens on, so a window running past
  // midnight stays one session instead of being cut in half at 00:00.
  const day = wraps && past ? (p.weekday + 6) % 7 : p.weekday;
  return spec.days.includes(day + 1);
}

/** True if this instant falls inside `spec` as read in `zone`. */
export function inSessionAt(
  utcSeconds: number,
  spec: SessionSpec,
  zone: string = DEFAULT_TIMEZONE,
): boolean {
  return inSessionParts(resolveParts(utcSeconds, zone), spec);
}

/**
 * Per-bar flags marking the bars inside `spec`. An unparseable spec string
 * marks nothing: a chart that keeps drawing beats one that dies on a stray
 * character, and the caller can check `parseSessionSpec` itself to tell an
 * empty window from a bad one.
 */
export function sessionFlags(
  times: readonly number[],
  spec: string | SessionSpec,
  zone: string = DEFAULT_TIMEZONE,
): boolean[] {
  const out = new Array<boolean>(times.length).fill(false);
  const s = typeof spec === 'string' ? parseSessionSpec(spec) : spec;
  if (s === null) return out;
  for (let i = 0; i < times.length; i++) out[i] = inSessionParts(resolveParts(times[i]!, zone), s);
  return out;
}
