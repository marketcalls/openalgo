import * as engine from '/dist/openalgo-charts.mjs';
import { el } from './ui.js';

// Only what this page actually calls. `registeredIntervals` and
// `isKnownInterval` are on the engine too, and were pulled in here and then
// used by nothing: the picker is built from CUSTOM_INTERVALS, which is the
// list that also has the labels and the fold source, so reading the
// registry back would be a second source of truth for the same thing.
const { registerInterval, tryResolveInterval, bucketStartOf } = engine;

/**
 * The error a code nothing recognises raises. The engine's own class when
 * this dist/ ships it, so a caller's `instanceof` holds whichever side threw;
 * a stand-in of the same name and shape on a build that predates it.
 */
export const UnknownIntervalError = engine.UnknownIntervalError || class UnknownIntervalError extends Error {
  constructor(code) {
    super(`unknown interval "${code}"`);
    this.name = 'UnknownIntervalError';
    this.code = code;
  }
};

// ── interval registry ──────────────────────────────────────────────────
// The picker speaks yfinance's tokens, and two of them are not tokens the
// engine's built-in grammar accepts: `1wk` has a two-letter unit, and a
// calendar month has no fixed length at all, so it cannot be a duration.
// Registering them is what makes `resolveInterval` answer for every code
// this page can put on screen, which is in turn what lets the cache below
// ask the registry (rather than a private table) how long a bar is.
//
// `1mo` and `1q` are the demonstration: the engine has no such interval and
// yfinance's own monthly frame is not what a calendar bucket means here.
// They are folded locally from daily bars through `bucketStartOf`, so a
// month runs first-to-first at local midnight in the chart's timezone and
// February really is 29 days long in 2024.
export const CUSTOM_INTERVALS = [
  { code: '1wk', label: '1W', name: 'Week', bucketing: { mode: 'interval', seconds: 604800 } },
  { code: '1mo', label: '1MO', name: 'Calendar month', bucketing: { mode: 'calendar', unit: 'month', count: 1 }, foldFrom: '1d' },
  { code: '1q', label: '1Q', name: 'Calendar quarter', bucketing: { mode: 'calendar', unit: 'quarter', count: 1 }, foldFrom: '1d' },
];
if (registerInterval) {
  for (const iv of CUSTOM_INTERVALS) registerInterval({ code: iv.code, bucketing: iv.bucketing });
}
/** The demo's own entry for a code, when it has one. */
export const customInterval = (code) => CUSTOM_INTERVALS.find((i) => i.code === code) || null;
/** A code we fold ourselves out of a shorter frame, rather than fetch. */
export const foldedInterval = (code) => {
  const iv = customInterval(code);
  return iv && iv.foldFrom ? iv : null;
};

/**
 * Validate a code before anything is fetched with it. The picker only ever
 * writes codes from INTERVALS, but the hidden select can be set by hand and
 * a saved layout can name a frame from another build, and a code that
 * reaches the wire unchecked draws whatever the server felt like sending
 * under the label the user picked. Returns the registry's descriptor, or
 * throws UnknownIntervalError, which the feed turns into a toast.
 *
 * A dist/ without the registry cannot answer, so the picker's own list is
 * the fallback there: it is exactly the set of codes the page can put on
 * screen against such a build.
 */
export function resolvePickerInterval(code) {
  const c = String(code == null ? '' : code).trim();
  if (c !== '') {
    if (tryResolveInterval) {
      const d = tryResolveInterval(c);
      if (d) return d;
    } else if (INTERVALS.includes(c)) {
      return { code: c, bucketing: null };
    }
  }
  throw new UnknownIntervalError(c);
}

/** Bar length in seconds, straight off the registry. 0 for anything with none. */
export function intervalSeconds(code) {
  const d = tryResolveInterval ? tryResolveInterval(code) : null;
  return d && d.bucketing.mode === 'interval' ? d.bucketing.seconds : 0;
}

/**
 * Fold shorter bars into calendar buckets. The bucket start comes from the
 * registry, never from arithmetic here: that is the whole point of a
 * calendar bucketing, and it is why changing the chart's timezone moves the
 * month boundary instead of leaving it pinned to UTC.
 */
export function foldToBuckets(bars, bucketing, zone) {
  const out = [];
  let cur = null;
  let start = null;
  for (const b of bars) {
    const s = bucketStartOf(bucketing, b.time, zone);
    if (s !== start) {
      if (cur) out.push(cur);
      start = s;
      cur = { time: s, open: b.open, high: b.high, low: b.low, close: b.close, volume: b.volume || 0 };
    } else {
      if (b.high > cur.high) cur.high = b.high;
      if (b.low < cur.low) cur.low = b.low;
      cur.close = b.close;
      cur.volume += b.volume || 0;
    }
  }
  if (cur) out.push(cur);
  return out;
}

/* The picker is built from the built-in tokens this demo's data source
   serves plus whatever was registered above, so a code added to
   CUSTOM_INTERVALS appears here without a second list to keep in step. A
   registry with no registerInterval behind it contributes nothing, which is
   why the calendar codes are guarded rather than hardcoded. */
export const INTERVALS = ['5m', '15m', '30m', '1h', '1d']
  .concat(registerInterval ? CUSTOM_INTERVALS.map((i) => i.code) : ['1wk']);
export const intervalLabel = (iv) => (customInterval(iv) || { label: iv.toUpperCase() }).label;
// Words, not codes: "5M bars" read as five months beside the bottom bar's 1M.
const INTERVAL_NAMES = { '5m': '5 minute bars', '15m': '15 minute bars', '30m': '30 minute bars', '1h': 'Hourly bars', '1d': 'Daily bars', '1wk': 'Weekly bars' };
export const intervalName = (iv) => {
  if (INTERVAL_NAMES[iv]) return INTERVAL_NAMES[iv];
  const c = customInterval(iv);
  if (c) return c.name + (c.foldFrom ? ' (folded from ' + c.foldFrom.toUpperCase() + ' bars)' : '');
  return iv.toUpperCase() + ' bars';
};
/* The hidden <select> is where the demo keeps the chosen interval, and the
   shell writes codes into it. A select silently refuses a value it has no
   option for and leaves `.value` empty, so a registered code that was in
   the pills but not in here drew daily bars under a monthly label. Built
   from the same list the pills are, so the two cannot drift. */
export function fillIntervalSelect() {
  const sel = el('interval');
  const keep = sel.value || '1d';
  sel.innerHTML = '';
  for (const iv of INTERVALS) {
    const o = document.createElement('option');
    o.value = iv;
    o.textContent = intervalLabel(iv);
    sel.appendChild(o);
  }
  sel.value = INTERVALS.includes(keep) ? keep : '1d';
}

export const PERIODS = ['1mo', '6mo', '1y', '5y', 'max'];

/* Yahoo caps how far back intraday data goes, and answers an over-long
   request with an *empty* frame rather than an error, so 5m/15m/30m with
   the default 1y range silently drew nothing while 1h and 1d worked. Clamp
   the range to what the interval can actually serve. */
export const PERIOD_DAYS = { '1mo': 31, '6mo': 186, '1y': 366, '5y': 1830, max: 1e6 };
export const INTERVAL_MAX_DAYS = { '1m': 7, '2m': 60, '5m': 60, '15m': 60, '30m': 60, '60m': 730, '90m': 60, '1h': 730 };
/* A calendar frame needs years of source bars to draw anything: a quarter
   chart over one month is a single candle, which reads as a broken load
   rather than as a range the frame cannot fill. A daily chart loads at least
   five years, so it always holds 500 candles or more where the instrument has
   that much history: two years is about 495 sessions on NSE, and the source
   has no three-year period. */
export const INTERVAL_MIN_DAYS = { '1d': 1830, '1mo': 1500, '1q': 1800 };
/** Periods this interval can serve, longest last: up to an intraday frame's cap, from a daily or calendar frame's floor. */
export function periodsFor(interval) {
  const cap = INTERVAL_MAX_DAYS[interval];
  const floor = INTERVAL_MIN_DAYS[interval];
  let out = cap === undefined ? PERIODS.slice() : PERIODS.filter((p) => PERIOD_DAYS[p] <= cap);
  if (floor !== undefined) out = out.filter((p) => PERIOD_DAYS[p] >= floor);
  return out;
}
/**
 * `wanted` if the interval can serve it, else the nearest range it can:
 * the shortest when the ask was too short for the frame, the longest when
 * it was longer than the source will go back.
 */
export function clampPeriod(interval, wanted) {
  const ok = periodsFor(interval);
  if (ok.includes(wanted)) return wanted;
  if (ok.length === 0) return PERIODS[0];
  return PERIOD_DAYS[wanted] < PERIOD_DAYS[ok[0]] ? ok[0] : ok[ok.length - 1];
}

/**
 * The interval and period a preset range loads, for a range reaching
 * `reachSec` back from now: `nearest` (the widget tier's `rangeInterval`)
 * picks among the intervals with a period that reaches that far, and the
 * shortest such period goes with it. Only those can show the whole range: a
 * month back to midnight is often a little more than the month of 30-minute
 * bars this page asks for, and the range would stop short.
 */
export function rangeLoad(range, reachSec, nearest) {
  const reaches = (p) => PERIOD_DAYS[p] * 86400 >= reachSec;
  const reaching = INTERVALS.filter((iv) => periodsFor(iv).some(reaches));
  const interval = nearest(range, reaching.length ? reaching : INTERVALS);
  const periods = periodsFor(interval);
  return { interval, period: periods.find(reaches) ?? periods[periods.length - 1] };
}
