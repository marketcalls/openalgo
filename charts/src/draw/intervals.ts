/**
 * Visibility per interval: the intervals a drawing shows on.
 *
 * A level drawn on the hourly chart is often noise on the one minute chart and
 * too fine to matter on the weekly one, so a drawing may carry a range of
 * intervals, `{ from: '1m', to: '1h' }`, and it is shown only while the
 * chart's interval lies inside it, both ends included. Outside it the drawing
 * is kept, saved and undone like any other; it is simply not on the chart, so
 * nothing paints it, hit-tests it or sweeps it up in a box or an eraser drag.
 *
 * The rules, each chosen so that a range can only ever hide a drawing the user
 * asked to hide:
 *
 * - Intervals compare by the length of their bars, read from the interval
 *   registry, so `60m` and `1h` are one interval and a host's own codes
 *   (registered with `registerInterval`) take part like the built-in ones. A
 *   calendar interval counts a mean month per month: it has no fixed length,
 *   but a month is still longer than a week and shorter than a quarter.
 * - The range is the span between its two bounds, whichever way round they
 *   are written, and an absent bound is no limit on that side.
 * - A bound nothing resolves to a length (an unknown code, a tick or a volume
 *   interval) imposes no limit either. So does a chart interval of that kind,
 *   or none at all: a bar that closes on trade flow has no place on a scale of
 *   time, and a drawing is never hidden for a comparison that cannot be made.
 *
 * Reading a stored range (`readIntervalRange`) consults nothing, so the
 * migration that calls it stays pure: a host may register its intervals after
 * a layout is restored, as it may register a plugin tool.
 */
import { tryResolveInterval } from 'openalgo-charts';
import type { Drawing, DrawingIntervalRange } from './types';
import { isRecord } from './drawing-fields';

/** A mean Gregorian month, in seconds: 365.2425 days over 12. Only ever compared, never counted. */
const MONTH_SECONDS = 2629746;
const CALENDAR_MONTHS = { month: 1, quarter: 3, year: 12 } as const;

/** Longest code a range keeps. Interval codes are a few characters; this only stops a runaway string. */
const MAX_CODE = 64;

const readCode = (v: unknown): string | undefined =>
  typeof v === 'string' && v.trim() !== '' && v.length <= MAX_CODE ? v.trim() : undefined;

/**
 * A stored or requested range as a fresh record, or null when it names no
 * bound at all: an empty range limits nothing, so it is the same as none and
 * is not kept. A bound that is not a non-blank string is dropped on its own.
 */
export function readIntervalRange(value: unknown): DrawingIntervalRange | null {
  if (!isRecord(value)) return null;
  const from = readCode(value.from);
  const to = readCode(value.to);
  if (from === undefined && to === undefined) return null;
  return { ...(from === undefined ? {} : { from }), ...(to === undefined ? {} : { to }) };
}

/**
 * The length of an interval's bars in seconds, for comparison only, or null
 * when it has none: an unknown code, a blank one, or bars that close on trade
 * flow rather than on the clock.
 */
export function intervalLength(code: string | null | undefined): number | null {
  if (typeof code !== 'string' || code.trim() === '') return null;
  const found = tryResolveInterval(code);
  if (found === null) return null;
  const b = found.bucketing;
  if (b.mode === 'interval') return b.seconds;
  if (b.mode === 'calendar') return CALENDAR_MONTHS[b.unit] * Math.max(1, Math.floor(b.count ?? 1)) * MONTH_SECONDS;
  return null;
}

/**
 * The interval a data context names, or null when it names none: no context,
 * no `interval`, or a blank one.
 */
export function contextInterval(context: unknown): string | null {
  const interval = typeof context === 'object' && context !== null ? (context as { interval?: unknown }).interval : undefined;
  return typeof interval === 'string' && interval.trim() !== '' ? interval : null;
}

/**
 * The marker `publishDataContext` puts on the context it passes through on
 * the way to a change of data variant alone. That context clears the
 * interval and the real one follows at once, so following it would show
 * every drawing and hide them again within one call, dropping from the
 * selection a hidden drawing picked on purpose. The base tier does not
 * export its test, so the registered key is read here, as the indicators
 * tier reads it.
 */
const PASSING = Symbol.for('openalgo-charts.data-context.passing');

/** Whether a `data:context` payload is that passing context. */
export const passingContext = (context: unknown): boolean =>
  typeof context === 'object' && context !== null && (context as Record<symbol, unknown>)[PASSING] === true;

/**
 * A test of whether a drawing is shown on `interval`, with the interval
 * resolved once: the layers ask it of every drawing on every re-list.
 */
export function intervalFilter(interval: string | null | undefined): (drawing: Pick<Drawing, 'intervals'>) => boolean {
  const length = intervalLength(interval);
  if (length === null) return () => true;
  return (drawing) => {
    const range = drawing.intervals;
    if (range === undefined) return true;
    const a = intervalLength(range.from);
    const b = intervalLength(range.to);
    const lo = a !== null && b !== null ? Math.min(a, b) : a;
    const hi = a !== null && b !== null ? Math.max(a, b) : b;
    return (lo === null || length >= lo) && (hi === null || length <= hi);
  };
}

/**
 * Whether a drawing is shown on a chart whose interval is `interval`. A
 * drawing with no range is shown on every interval. For a host marking the
 * drawings a range hides (an objects panel, a settings preview) without a
 * controller at hand; `DrawingController.shownOnInterval` answers for the
 * chart the controller is on.
 */
export function drawingShownOnInterval(drawing: Pick<Drawing, 'intervals'>, interval: string | null | undefined): boolean {
  return intervalFilter(interval)(drawing);
}

/**
 * The document version that describes `drawings`: 3 when any carries an
 * interval range, the one field version 3 added, else 2. Writing the lowest
 * version that holds the content keeps every document without a range byte
 * for byte what an earlier build wrote and reads, and an earlier build's
 * clipboard, which refuses a newer payload, still takes a copy of one.
 */
export function drawingsDocumentVersion(drawings: readonly Pick<Drawing, 'intervals'>[]): 2 | 3 {
  return drawings.some((d) => d.intervals !== undefined) ? 3 : 2;
}
