/**
 * Calendar boundaries on the chart's zone, for the studies that restart at a
 * week, month, quarter or year (VWAP's anchors, the pivot frames).
 * Tier-internal: the tier index does not re-export it.
 *
 * The default zone keeps the offset arithmetic. Intl is the right answer for
 * an arbitrary zone and the wrong price for the one zone that has no DST to get
 * wrong: measured over twelve thousand daily bars the sweep costs 38ms through
 * Intl against 3ms through `utcSecondsToIstParts`, and a week test runs once
 * per bar. The two answers are pinned identical for Asia/Kolkata by
 * `tests/indicator-timezone.test.ts`, so the branch changes nothing about what
 * a study returns. The foundation's own `sessionStartFlags` splits on the same
 * line for the same reason.
 */
import { DEFAULT_TIMEZONE, IST_OFFSET_SECONDS, isNewZonedPeriod, utcSecondsToIstParts } from 'openalgo-charts';

type CalendarPeriod = 'week' | 'month' | 'quarter' | 'year';

/** Monday-start week index on the default zone. 1970-01-01 was a Thursday, hence the +3. */
const istWeek = (t: number): number => Math.floor((Math.floor((t + IST_OFFSET_SECONDS) / 86400) + 3) / 7);

/**
 * Whether `now` opens a new `period` after `prev`, on the calendar of `zone`.
 * Index arithmetic rather than a day-of-week test: a holiday, a half session or
 * a feed outage can drop the bar that sits on the boundary, and comparing
 * indices still catches the crossing.
 */
export function periodBoundary(period: CalendarPeriod, zone: string): (prev: number, now: number) => boolean {
  if (zone !== DEFAULT_TIMEZONE) return (prev, now) => isNewZonedPeriod(prev, now, period, zone);
  // Week first: a Monday-start week straddles the turn of the year, so the
  // year test below would report a boundary the week itself does not have.
  if (period === 'week') return (prev, now) => istWeek(prev) !== istWeek(now);
  return (prev, now) => {
    const a = utcSecondsToIstParts(prev);
    const b = utcSecondsToIstParts(now);
    if (a.year !== b.year) return true;
    if (period === 'year') return false;
    if (period === 'quarter') return Math.floor((a.month - 1) / 3) !== Math.floor((b.month - 1) / 3);
    return a.month !== b.month;
  };
}
