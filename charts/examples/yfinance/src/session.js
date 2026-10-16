// Trading session as a data variant. Extended hours are the source's own pre
// and post market bars: a different series from the regular one, with bars
// the regular series does not have. So the session rides on every request as
// the engine's `variant`, and a chart that changes session has changed source.
// Nothing here makes one series out of the other.

/** The variant for extended hours. Regular hours are the source's default series, so they name none. */
export const EXTENDED = Object.freeze({ session: 'extended' });
export const SESSIONS = ['regular', 'extended'];

/**
 * A US listed stock as the source spells it: one to five letters and an
 * optional share class (BRK-B). The source has pre and post market bars for
 * these and nothing else it serves. The same rule as the server's
 * `extended_session_available`, which refuses anything else.
 */
const US_STOCK = /^[A-Za-z]{1,5}(?:-[A-Za-z])?$/;
/** The source's intraday wire intervals, the server's `INTRADAY`. */
const INTRADAY = new Set(['1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h']);

/** Whether the source serves extended hours for this symbol at this wire interval. */
export function extendedSessionAvailable(symbol, interval) {
  return US_STOCK.test(String(symbol || '')) && INTRADAY.has(interval);
}

/** The session a request names, regular when it names none or one this page does not know. */
export const sessionOf = request => (request?.session === 'extended' ? 'extended' : 'regular');

/** The engine variant for a request: extended hours, or undefined for the default series. */
export const requestVariant = request => (sessionOf(request) === 'extended' ? EXTENDED : undefined);

export const sessionLabel = session => (session === 'extended' ? 'Extended hours' : 'Regular hours');
