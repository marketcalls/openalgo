import * as engine from '/dist/openalgo-charts.mjs';
import { fmt, UP, DOWN } from './ui.js';
import { sessionOf } from './session.js';

// Read off the namespace, like the other version-dependent surfaces: an older
// dist/ without session phases still loads, and reads the table by the clock.
const { SessionCalendar } = engine;

let app;
export function initStatus(a) { app = a; }

// The venue a yfinance symbol trades on. It answers three questions at once:
// what the status line prints after the interval, what the ticker title mode
// prefixes the name with, and which session table says whether the market is
// open. A plain ticker is the US tape, which is yfinance's own default
// namespace; an index yfinance carries that is not one of the four below is
// 'INDEX', a venue this demo has no session hours for.
export function exchangeOf(sym) {
  const s = String(sym).toUpperCase();
  if (s.endsWith('.NS') || s === '^NSEI' || s === '^NSEBANK') return 'NSE';
  if (s.endsWith('.BO') || s === '^BSESN') return 'BSE';
  if (s.endsWith('-USD')) return 'CRYPTO';
  if (s === '^GSPC' || s === '^DJI' || s === '^IXIC' || s === '^RUT' || s === '^VIX') return 'US';
  if (s.startsWith('^')) return 'INDEX';
  return 'US';
}
export const nameOf = (sym) => sym.toUpperCase().replace(/\.(NS|BO)$/, '');

// ── status-line data ───────────────────────────────────────────────────
// The legend draws the row; these four fields are the ones it has no way to
// derive, so the Readout tab's switches for them are live only because the
// host feeds them. Anything the demo genuinely cannot supply is left absent
// here and its control is drawn disabled (see chartSettingUnavailable).

/**
 * Long names for the instruments this demo points at. `/api/history` returns
 * bars and nothing else, so a description is either in this table or the
 * demo does not have one: the "Description" title mode is disabled for a
 * symbol that is not here rather than silently drawing the ticker instead.
 */
export const LONG_NAMES = {
  AAPL: 'Apple Inc.', MSFT: 'Microsoft Corporation', GOOGL: 'Alphabet Inc.',
  AMZN: 'Amazon.com, Inc.', META: 'Meta Platforms, Inc.', TSLA: 'Tesla, Inc.',
  NVDA: 'NVIDIA Corporation', NFLX: 'Netflix, Inc.', AMD: 'Advanced Micro Devices, Inc.',
  'RELIANCE.NS': 'Reliance Industries Limited',
  'TCS.NS': 'Tata Consultancy Services Limited',
  'INFY.NS': 'Infosys Limited', 'HDFCBANK.NS': 'HDFC Bank Limited',
  'ICICIBANK.NS': 'ICICI Bank Limited', 'SBIN.NS': 'State Bank of India',
  'TATAMOTORS.NS': 'Tata Motors Limited', 'ITC.NS': 'ITC Limited',
  '^NSEI': 'NIFTY 50', '^NSEBANK': 'NIFTY Bank', '^BSESN': 'S&P BSE SENSEX',
  '^GSPC': 'S&P 500', '^DJI': 'Dow Jones Industrial Average', '^IXIC': 'NASDAQ Composite',
  'BTC-USD': 'Bitcoin / US Dollar', 'ETH-USD': 'Ethereum / US Dollar',
};
export const descriptionOf = (sym) => LONG_NAMES[String(sym).toUpperCase()] || null;

/**
 * Regular hours per venue, as an IANA zone and a local window in minutes
 * from midnight. Never a fixed UTC offset: New York is four hours off UTC
 * for part of the year and five for the rest, and a constant would be
 * silently wrong for half of it. `null` means the venue never closes; a
 * venue absent from the table has no hours here and says so. `pre` and
 * `post` bound the extended session where the source serves one: an
 * extended chart is trading, and can go stale, from `pre` to `post`. An
 * optional `exceptions` map closes (`[]`) or shortens local dates, in the
 * library calendar's own form; the demo lists none, so a holiday reads as
 * an ordinary weekday until a host supplies its venue's closed dates.
 */
export const SESSIONS = {
  NSE: { zone: 'Asia/Kolkata', open: 9 * 60 + 15, close: 15 * 60 + 30 },
  BSE: { zone: 'Asia/Kolkata', open: 9 * 60 + 15, close: 15 * 60 + 30 },
  US: { zone: 'America/New_York', open: 9 * 60 + 30, close: 16 * 60, pre: 4 * 60, post: 20 * 60 },
  CRYPTO: null,
};
const WEEKDAY = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };

/** Weekday and minute-of-day for an instant, in an IANA zone. */
const zoneParts = (() => {
  const fmts = new Map();
  return (ms, zone) => {
    let f = fmts.get(zone);
    if (!f) {
      f = new Intl.DateTimeFormat('en-GB', {
        timeZone: zone, weekday: 'short', hour: '2-digit', minute: '2-digit', hour12: false,
      });
      fmts.set(zone, f);
    }
    const p = {};
    for (const part of f.formatToParts(new Date(ms))) p[part.type] = part.value;
    // hour12:false gives 24 for midnight in some engines, hence the modulo.
    return { day: WEEKDAY[p.weekday], minutes: (Number(p.hour) % 24) * 60 + Number(p.minute) };
  };
})();

const hhmm = (minutes) => String(Math.floor(minutes / 60)).padStart(2, '0') + String(minutes % 60).padStart(2, '0');

/** One library calendar per table entry, built on first use and rebuilt only for a replaced entry. */
const venueCalendars = new WeakMap();

/**
 * A venue's hours as the library's `SessionCalendar`: its regular window on
 * weekdays, the pre-open and post-close the source serves around it, and the
 * closed dates the table lists. The library then answers which part of the
 * day it is, holidays included, in the venue's own zone. Null for a venue
 * with no hours here, one that never closes, or a dist/ without calendars.
 */
export function venueCalendar(venue) {
  const hours = SESSIONS[venue];
  if (!hours || !SessionCalendar) return null;
  let calendar = venueCalendars.get(hours);
  if (!calendar) {
    calendar = new SessionCalendar({
      timezone: hours.zone,
      sessions: [`${hhmm(hours.open)}-${hhmm(hours.close)}:23456`],
      // Each side on its own: a venue may serve a pre-open and no post-close.
      ...(hours.pre === undefined ? {} : { preMarketMinutes: hours.open - hours.pre }),
      ...(hours.post === undefined ? {} : { postMarketMinutes: hours.post - hours.close }),
      ...(hours.exceptions ? { exceptions: hours.exceptions } : {}),
    });
    venueCalendars.set(hours, calendar);
  }
  return calendar;
}

/**
 * The phase last read from each calendar and the time it holds for. The
 * symbol legend asks on every frame it draws, and laying a calendar's dates
 * out costs several times the clock read it replaced, so it is asked once
 * per phase and again when the status says the phase changes (or a day on,
 * for one that holds longer).
 */
const heldPhases = new WeakMap();

/**
 * The part of the trading day it is at a venue: 'regular', 'pre', 'post',
 * 'holiday' or 'closed', from the library calendar. A dist/ from before
 * session phases reads the same windows by the clock, with no dates closed.
 */
function venuePhase(venue, ms = Date.now()) {
  const calendar = venueCalendar(venue), sec = ms / 1000;
  if (typeof calendar?.marketStatusAt === 'function') {
    let held = heldPhases.get(calendar);
    if (!held || sec < held.from || sec >= held.until) {
      const status = calendar.marketStatusAt(sec);
      held = { phase: status.phase, from: sec, until: status.changesAt ?? sec + 86400 };
      heldPhases.set(calendar, held);
    }
    return held.phase;
  }
  const hours = SESSIONS[venue];
  const { day, minutes } = zoneParts(ms, hours.zone);
  if (day < 1 || day > 5) return 'closed';
  if (minutes >= hours.open && minutes < hours.close) return 'regular';
  if (hours.pre !== undefined && minutes >= hours.pre && minutes < hours.open) return 'pre';
  return hours.post !== undefined && minutes >= hours.close && minutes < hours.post ? 'post' : 'closed';
}

/**
 * Whether the venue is trading right now, for a chart on `session`: the
 * library's derivation from the venue calendar, so a closed date the table
 * lists reads as a holiday. A chart on extended hours is told which side of
 * the regular session its bars come from; a regular-hours chart has no bars
 * there, so for it those hours are closed.
 */
export function marketStatusReading(symbol = app.req.symbol || '', session = sessionOf(app?.req)) {
  const venue = exchangeOf(symbol);
  if (!(venue in SESSIONS)) return undefined;    // no hours for this venue
  if (SESSIONS[venue] === null) return { text: 'Open 24x7', color: UP };
  const phase = venuePhase(venue);
  if (phase === 'regular') return { text: 'Market open', color: UP };
  if (session === 'extended' && phase === 'pre') return { text: 'Pre-market' };
  if (session === 'extended' && phase === 'post') return { text: 'Post-market' };
  return { text: phase === 'holiday' ? 'Market holiday' : 'Market closed' };
}

/**
 * Can this venue still be producing bars right now? The same calendar as the
 * status line above, so a listed holiday is not live either. A chart on
 * extended hours counts them where the venue has them. Read by `barsRequest`
 * to decide how far ahead it is worth asking for data, and by `staleness` to
 * decide whether a bar can be late at all.
 */
export function venueLive(symbol, session = 'regular') {
  const venue = exchangeOf(symbol), s = SESSIONS[venue];
  if (s === undefined || s === null) return true;   // unknown hours, or 24x7
  const phase = venuePhase(venue);
  return phase === 'regular' || (session === 'extended' && (phase === 'pre' || phase === 'post'));
}

/** A bar's local calendar day, for spotting a session boundary. */
const dayKey = (() => {
  const fmts = new Map();
  return (timeSec, zone) => {
    let f = fmts.get(zone);
    if (!f) {
      f = new Intl.DateTimeFormat('en-CA', { timeZone: zone, year: 'numeric', month: '2-digit', day: '2-digit' });
      fmts.set(zone, f);
    }
    return f.format(new Date(timeSec * 1000));
  };
})();

/**
 * Close of the session before the last bar's, in the chart's own zone. Null
 * when the loaded range holds a single session, which is the case the
 * "change since previous close" switch is disabled for: there is no previous
 * close, and drawing a zero would be an invention.
 *
 * Memoised on the bar array and the zone, because the status line asks for
 * it on every frame and a five-day one-minute chart is a few hundred
 * `Intl.format` calls per answer.
 */
const prevCloseMemo = new WeakMap();
export function previousSessionClose(bars = app.currentBars, zone = app.chartTimezone) {
  const cached = prevCloseMemo.get(bars);
  if (cached?.zone === zone && cached.length === bars.length
    && cached.last === bars.at(-1) && cached.previous === bars.at(-2)) return cached.value;
  let value = null;
  if (bars.length >= 2) {
    const last = dayKey(bars[bars.length - 1].time, zone);
    for (let i = bars.length - 2; i >= 0; i--) {
      if (dayKey(bars[i].time, zone) !== last) { value = bars[i].close; break; }
    }
  }
  prevCloseMemo.set(bars, { zone, value, length: bars.length, last: bars.at(-1), previous: bars.at(-2) });
  return value;
}

export function dayChangeReading(bars = app.currentBars, zone = app.chartTimezone) {
  const prev = previousSessionClose(bars, zone);
  if (prev == null || !bars.length) return undefined;
  const d = bars[bars.length - 1].close - prev;
  const sign = d >= 0 ? '+' : '';
  const pct = prev ? (d / prev) * 100 : 0;
  return { label: '1D', text: `${sign}${fmt(d)} (${sign}${pct.toFixed(2)}%)`, color: d >= 0 ? UP : DOWN };
}

/**
 * A monogram tile for the symbol. The demo has no brand artwork and the feed
 * returns none, so the mark is drawn from the ticker: one letter over a hue
 * derived from the name, which is a real per-symbol mark rather than one
 * placeholder repeated for every instrument.
 */
const logoCache = new Map();
export function symbolLogo(sym) {
  const name = nameOf(sym || '').replace(/^\^/, '');
  if (!name) return undefined;
  const hit = logoCache.get(name);
  if (hit) return hit;
  const side = 36;      // drawn at 3x the 12px the legend paints it at
  const c = document.createElement('canvas');
  c.width = side; c.height = side;
  const g = c.getContext('2d');
  let hue = 0;
  for (let i = 0; i < name.length; i++) hue = (hue * 31 + name.charCodeAt(i)) % 360;
  const r = 8;
  g.fillStyle = `hsl(${hue} 40% 34%)`;
  g.beginPath();
  g.moveTo(r, 0);
  g.arcTo(side, 0, side, side, r); g.arcTo(side, side, 0, side, r);
  g.arcTo(0, side, 0, 0, r); g.arcTo(0, 0, side, 0, r);
  g.closePath(); g.fill();
  g.fillStyle = '#eef1f7';
  g.font = '700 22px ui-sans-serif, system-ui, sans-serif';
  g.textAlign = 'center'; g.textBaseline = 'middle';
  g.fillText(name[0], side / 2, side / 2 + 1);
  logoCache.set(name, c);
  return c;
}

/**
 * Handed to the legend as a getter, not a snapshot: the session state is a
 * time of day, so it has to be right on the frame it is drawn rather than on
 * the frame the demo last patched options.
 */
export function symbolStatus({ symbol: sym = app.req.symbol || '', bars = app.currentBars, timezone = app.chartTimezone, session } = {}) {
  if (!sym) return null;
  return {
    logo: symbolLogo(sym),
    description: descriptionOf(sym) || undefined,
    ticker: exchangeOf(sym) + ':' + nameOf(sym),
    // The session of the chart this row belongs to: the caller names it, and
    // without one the main chart's symbol reads the main chart's session.
    marketStatus: marketStatusReading(sym, session ?? (sym === (app?.req?.symbol || '') ? sessionOf(app?.req) : 'regular')),
    lastDayChange: dayChangeReading(bars, timezone),
  };
}
