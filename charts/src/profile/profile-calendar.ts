/**
 * Calendar reads on a zone's clock for the profile tier's session grouping,
 * shared by the market profile and the volume profile family. Tier-internal:
 * the tier index does not re-export it.
 *
 * The default zone takes the fixed-offset arithmetic. These helpers run once
 * per bar over a whole history and Intl costs roughly 25x the arithmetic, so
 * the branch hands every existing caller back the speed it had. It cannot
 * change an answer: IST is a fixed offset, and tests/profile-timezone.test.ts
 * pins the two paths together rather than assuming they agree.
 */
import {
  DEFAULT_TIMEZONE,
  IST_OFFSET_SECONDS,
  utcSecondsToIstParts,
  utcSecondsToZonedParts,
  zonedDayIndex,
} from '../feed/time';

const DAY_SECONDS = 86400;

/** Calendar parts of an instant on `zone`'s clock. */
export function partsIn(utcSeconds: number, zone: string): { year: number; month: number; day: number; hour: number; minute: number } {
  return zone === DEFAULT_TIMEZONE
    ? utcSecondsToIstParts(utcSeconds)
    : utcSecondsToZonedParts(utcSeconds, zone);
}

/** Minutes from local midnight in `zone`. */
export function minuteOfDay(utcSeconds: number, zone: string): number {
  if (zone === DEFAULT_TIMEZONE) {
    const s = (((utcSeconds + IST_OFFSET_SECONDS) % DAY_SECONDS) + DAY_SECONDS) % DAY_SECONDS;
    return Math.floor(s / 60);
  }
  const p = utcSecondsToZonedParts(utcSeconds, zone);
  return p.hour * 60 + p.minute;
}

/** Whole days since 1970-01-01 on `zone`'s calendar. */
function dayIndexIn(utcSeconds: number, zone: string): number {
  if (zone === DEFAULT_TIMEZONE) return Math.floor((utcSeconds + IST_OFFSET_SECONDS) / DAY_SECONDS);
  return zonedDayIndex(utcSeconds, zone);
}

/**
 * Session group key for the chosen mode, on `zone`'s calendar.
 *
 * An identity, not a timestamp: bars sharing a key share a profile and nothing
 * outside the tier reads the value, so a day index is both cheaper than a
 * midnight and immune to the 169-hour week a DST changeover produces. A window
 * that crosses midnight (`startMinute > endMinute`) puts its morning with the
 * evening it opened on, so an overnight session is one profile, not two halves.
 */
export function sessionKey(
  utcSeconds: number,
  mode: 'day' | 'week' | 'month' | 'composite',
  zone: string,
  w?: { startMinute: number; endMinute: number },
): number {
  if (mode === 'composite') return 0;
  if (mode === 'month') {
    const p = partsIn(utcSeconds, zone);
    return p.year * 12 + (p.month - 1);
  }
  let dayIndex = dayIndexIn(utcSeconds, zone);
  if (w !== undefined && w.startMinute > w.endMinute && minuteOfDay(utcSeconds, zone) < w.endMinute) {
    dayIndex -= 1;
  }
  if (mode === 'day') return dayIndex;
  // Monday-start weeks. 1970-01-01 was a Thursday, hence the +3 before the divide.
  return Math.floor((dayIndex + 3) / 7);
}
