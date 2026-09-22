/**
 * Teaching the chart engine the timeframes above a week.
 *
 * There are two interval vocabularies in play and they are not the same one.
 *
 * The Historify store, `database/historify_db.py`, accepts `M`, `Q` and `Y`
 * and aggregates them from stored daily candles. The chart engine does not:
 * `registeredIntervals()` starts empty and its built-in tokens cover seconds,
 * minutes, hours, days and weeks only, so `resolveInterval('M')` throws
 * `UnknownIntervalError`. A month is not a fixed number of seconds, which is
 * why it cannot be a built-in the way `2W` can.
 *
 * The engine does know how to bucket a calendar period, it just has to be told
 * which codes mean one. `registerInterval` takes a `CalendarBucketing` of
 * `month`, `quarter` or `year` with a count, so `M`, `3M`, `Q`, `2Q`, `Y` and
 * `2Y` all describe themselves exactly rather than being approximated in
 * seconds.
 *
 * Registration is on demand rather than a fixed list, because the page composes
 * arbitrary multiples: a user can ask for 3M, and pre-registering every count
 * anyone might type is not a list worth keeping.
 *
 * The timezone is deliberate. A calendar bar opens at local midnight on the
 * first day of its period, so the zone decides which day a month starts on.
 * Indian exchange sessions are IST, which is what `DEFAULT_TIMEZONE` is.
 */

import {
  type CalendarUnit,
  DEFAULT_TIMEZONE,
  isKnownInterval,
  registerInterval,
} from 'openalgo-charts'

/** Codes above a week, and the calendar unit each one buckets by. */
const CALENDAR_UNITS: Record<string, CalendarUnit> = {
  M: 'month',
  Q: 'quarter',
  Y: 'year',
}

/** An optional count then a calendar letter: `M`, `3M`, `Q`, `2Q`, `Y`, `2Y`. */
const CALENDAR_TOKEN = /^(\d*)([MQY])$/

/**
 * Make sure the engine can resolve `code`, registering it if it is a calendar
 * timeframe it has not been told about.
 *
 * Returns false for a code nothing can resolve, so a caller can decline to use
 * it rather than discovering the problem as a thrown error mid-render.
 */
export function ensureInterval(code: string): boolean {
  const token = code?.trim()
  if (!token) return false
  if (isKnownInterval(token)) return true

  const match = CALENDAR_TOKEN.exec(token)
  if (!match) return false

  const count = match[1] === '' ? 1 : Number(match[1])
  if (!Number.isInteger(count) || count <= 0) return false

  registerInterval({
    code: token,
    bucketing: {
      mode: 'calendar',
      unit: CALENDAR_UNITS[match[2]],
      count,
      timezone: DEFAULT_TIMEZONE,
    },
  })
  return true
}

/**
 * Register the three single-period calendar codes up front.
 *
 * On-demand registration covers a timeframe the host asks for, but the widget
 * also restores its own saved interval out of its persisted layout, and that
 * happens inside `createWidget` where there is nothing to intercept. A reader
 * who left a pane on monthly and came back would hit the same unknown-interval
 * throw on first paint. Registering `M`, `Q` and `Y` before the widget is built
 * means the codes exist by the time any restore reads them.
 *
 * Safe to call repeatedly: `ensureInterval` is idempotent, and none of these
 * three shadows a built-in token, because none of them is one.
 */
export function ensureCalendarIntervals(): void {
  for (const code of Object.keys(CALENDAR_UNITS)) ensureInterval(code)
}
