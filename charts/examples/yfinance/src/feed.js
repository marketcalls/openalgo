import * as engine from '/dist/openalgo-charts.mjs';
import {
  intervalSeconds, foldedInterval, foldToBuckets, PERIOD_DAYS, resolvePickerInterval, UnknownIntervalError,
} from './intervals.js';
import { venueLive, exchangeOf } from './status.js';
import { popupMenu } from './menus.js';
import { renderToolbar } from './toolbar.js';
import { el, toast } from './ui.js';
import { extendedSessionAvailable, requestVariant, sessionOf } from './session.js';

// 1.3 surfaces: chart linking, the bar cache and the interval registry.
// Same namespace read for the same reason: this page must still draw
// against an older dist/ and say which features that dist cannot serve,
// rather than failing at link time and showing a blank document.
const { withBarCache, barCloseSec } = engine;

let app;
let liveFeed = null;
let feed = null;

// ── errors ─────────────────────────────────────────────────────────────
// One class per thing the shell can do differently. A string message is
// enough to print, and not enough to decide: whether to retry, whether to
// keep the last chart up, whether to say "try again in a minute" or "check
// the symbol" are different answers, and matching on message text is how a
// reworded server string silently turns one into another. `state` is the
// word the UI keys on; `feedErrorState` maps anything, typed or not.
export class FeedError extends Error {
  constructor(message, { status, cause } = {}) {
    super(message);
    this.name = 'FeedError';
    this.state = 'error';
    this.status = status;
    if (cause !== undefined) this.cause = cause;
  }
}
/** The source has no bars for this symbol and range. Retrying will not help. */
export class NotFoundError extends FeedError {
  constructor(message, opts) { super(message, opts); this.name = 'NotFoundError'; this.state = 'not-found'; }
}
/** The source is throttling us. Retrying at once makes it worse. */
export class RateLimitedError extends FeedError {
  constructor(message, opts = {}) {
    super(message, opts);
    this.name = 'RateLimitedError';
    this.state = 'rate-limited';
    this.retryAfterSec = opts.retryAfterSec;
  }
}
/**
 * The request did not complete: offline, the server unreachable, a gateway
 * in between giving up, or our own timeout. `reason` says which, and
 * `retryable` is whether one more try is worth it: a dropped connection
 * often is, a twenty-second timeout is not.
 */
export class NetworkError extends FeedError {
  constructor(message, opts = {}) {
    super(message, opts);
    this.name = 'NetworkError';
    this.state = 'network';
    this.reason = opts.reason || 'offline';
    this.retryable = opts.retryable === true;
  }
}
/**
 * The source does not have the session asked for: extended hours for a
 * symbol or an interval it only serves in regular hours. Retrying will not
 * help; choosing regular hours will.
 */
export class UnsupportedSessionError extends FeedError {
  constructor(message, opts) { super(message, opts); this.name = 'UnsupportedSessionError'; this.state = 'unsupported'; }
}
/** Superseded by a newer request, or cancelled by the caller. Not a fault. */
export class AbortedError extends FeedError {
  constructor(message = 'request aborted', opts) { super(message, opts); this.name = 'AbortedError'; this.state = 'aborted'; }
}

/**
 * What the shell should do with a failure, whatever threw it. `aborted` is
 * the one state that wants nothing shown: a newer load is already on its
 * way, and an error for the one it replaced would overwrite that load's
 * own "loading" readout.
 */
export function feedErrorState(e) {
  if (e instanceof FeedError) return { state: e.state, message: e.message, retryable: e instanceof NetworkError && e.retryable };
  if (e instanceof UnknownIntervalError) return { state: 'unknown-interval', message: e.message, retryable: false };
  return { state: 'error', message: e && e.message ? e.message : String(e), retryable: false };
}

// ── the adapter ────────────────────────────────────────────────────────
/** Per attempt. yfinance answers a five-year daily request in a second or two; a request still open after this is not going to. */
export const DEFAULT_TIMEOUT_MS = 20_000;
/** Before the one retry. Long enough for a dropped connection to come back, short enough that the user has not given up. */
export const DEFAULT_RETRY_DELAY_MS = 750;

const RATE_LIMIT_TEXT = /rate.?limit|too many requests|\b429\b/i;
const NOT_FOUND_TEXT = /delisted|no data found|no price data|not found|\b404\b|no timezone found/i;

// The session goes on the URL only when the request names one, so a regular
// load asks exactly what it asked before sessions existed.
const historyUrl = (req) =>
  `/api/history?symbol=${encodeURIComponent(req.symbol)}&interval=${encodeURIComponent(req.interval)}&period=${encodeURIComponent(req.period)}`
  + (req.variant?.session ? `&session=${encodeURIComponent(req.variant.session)}` : '');

/**
 * Turn what the server sent into bars or a typed error. Pure, so the
 * mapping can be tested without a socket. The status code is the first
 * word and the body's `code` the second: this demo's server answers every
 * fault with a status and a token, and its `error` text is for people. The
 * text is still read as a last resort, for a server (a 1.x one, a proxy)
 * that answers with a 500 and the exception's words.
 *
 * An empty array is a NotFound, not a chart with no candles. yfinance's
 * answer for a symbol it does not know is an empty frame and a warning on
 * the server console, which the browser never sees; drawing nothing under
 * the symbol's name reads as the chart having broken.
 */
export function classifyHistoryResponse(status, body, req, headers) {
  // Parsed leniently: a gateway's body is an HTML page, and its status code
  // has already said everything the page would.
  let json;
  try {
    json = typeof body === 'string' ? JSON.parse(body) : body;
  } catch (_) {
    json = undefined;
  }
  const record = json && typeof json === 'object' && !Array.isArray(json) ? json : null;
  const text = record && typeof record.error === 'string' ? record.error : '';
  const code = record && typeof record.code === 'string' ? record.code : '';
  const where = `${req.symbol} ${req.interval}/${req.period}`;
  if (code === 'unsupported_session') throw new UnsupportedSessionError(text || `${req.symbol}: no extended hours for ${req.interval}`, { status });
  if (status === 404 || code === 'no_data' || NOT_FOUND_TEXT.test(text)) {
    throw new NotFoundError(`${req.symbol}: no bars${text ? ' (' + text + ')' : ''}`, { status });
  }
  if (status === 429 || code === 'rate_limited' || RATE_LIMIT_TEXT.test(text)) {
    const retryAfterSec = Number(headers && typeof headers.get === 'function' ? headers.get('Retry-After') : NaN) || undefined;
    throw new RateLimitedError('the data source is rate limiting requests; try again in a minute', { status, retryAfterSec });
  }
  if (status === 502 || status === 503 || status === 504) {
    // A 503 from this demo's server says yfinance is not installed, with
    // the fix in the message: worth showing, and not worth a retry. A bare
    // 503 from a gateway in between is the usual "try again".
    throw new NetworkError(text || `the data server is unreachable (HTTP ${status})`, { status, reason: 'gateway', retryable: code !== 'not_installed' });
  }
  if (json === undefined) throw new FeedError(`unreadable response from the data server (HTTP ${status})`, { status });
  if (text) throw new FeedError(text, { status });
  if (status < 200 || status >= 300) throw new FeedError(`history failed (${status})`, { status });
  if (!Array.isArray(json)) throw new FeedError('unexpected response shape from the data server', { status });
  if (json.length === 0) throw new NotFoundError(`${req.symbol}: no bars for ${where} (unknown symbol, or nothing in this range)`, { status });
  return json;
}

/** Sleep `ms`, unless `signal` fires first, in which case throw AbortedError. */
function backoff(ms, signal) {
  return new Promise((resolve, reject) => {
    if (signal && signal.aborted) { reject(new AbortedError()); return; }
    const t = setTimeout(() => {
      if (signal) signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    function onAbort() { clearTimeout(t); reject(new AbortedError()); }
    if (signal) signal.addEventListener('abort', onAbort, { once: true });
  });
}

/**
 * A broker-agnostic DataFeed for yfinance: getBars hits this demo's
 * /api/history, which already returns the chart's Bar shape (time in UTC
 * seconds). Every request has a deadline and can be cancelled through
 * `req.signal`; a dropped connection gets one more try after a pause.
 */
export class YFinanceDataFeed {
  constructor({ timeoutMs = DEFAULT_TIMEOUT_MS, retryDelayMs = DEFAULT_RETRY_DELAY_MS, retries = 1 } = {}) {
    this.timeoutMs = timeoutMs;
    this.retryDelayMs = retryDelayMs;
    this.retries = retries;
  }

  /**
   * What the source serves for an instrument: regular hours always, extended
   * hours for intraday bars of a US listed stock. The same rule the server
   * enforces, so a request for anything else is refused before it is sent.
   */
  dataVariants(query) {
    return { sessions: extendedSessionAvailable(query.symbol, query.interval) ? ['regular', 'extended'] : ['regular'] };
  }

  async getBars(req) {
    const url = historyUrl(req);
    for (let attempt = 0; ; attempt++) {
      try {
        return await this._attempt(url, req);
      } catch (e) {
        // Only a failure that might not repeat is worth a second round trip:
        // a symbol that is not there stays not there, a throttle gets worse
        // when hammered, and a timeout has already spent the user's patience.
        if (attempt >= this.retries || !(e instanceof NetworkError) || !e.retryable) throw e;
        await backoff(this.retryDelayMs * (attempt + 1), req.signal);
      }
    }
  }

  async _attempt(url, req) {
    const outer = req.signal;
    if (outer && outer.aborted) throw new AbortedError();
    const ctl = new AbortController();
    let timedOut = false;
    const onOuter = () => ctl.abort();
    if (outer) outer.addEventListener('abort', onOuter, { once: true });
    // The deadline covers the body too: `fetch` resolves on headers, and a
    // server that sends them and then stalls would otherwise hang the load.
    const timer = setTimeout(() => { timedOut = true; ctl.abort(); }, this.timeoutMs);
    let status;
    let body;
    let headers;
    try {
      const res = await fetch(url, { signal: ctl.signal });
      status = res.status;
      headers = res.headers;
      body = await res.text();
    } catch (e) {
      if (outer && outer.aborted) throw new AbortedError();
      if (timedOut) {
        throw new NetworkError(`no answer from the data server in ${Math.round(this.timeoutMs / 1000)} s`, { reason: 'timeout', retryable: false, cause: e });
      }
      throw new NetworkError('could not reach the data server (offline, or the demo server is down)', { reason: 'offline', retryable: true, cause: e });
    } finally {
      clearTimeout(timer);
      if (outer) outer.removeEventListener('abort', onOuter);
    }
    return classifyHistoryResponse(status, body, req, headers);
  }
}

// ── the feed, with warm-load caching ───────────────────────────────────
// `withBarCache` is a DataFeed -> DataFeed wrapper, so the yfinance adapter
// above is untouched by it. The cache keys on symbol|exchange|interval and
// slices by range, which is why every request from here on carries an
// exchange and a quantised from/to: an unbounded request is passed straight
// through uncached, and a `from` that drifts by a second per call would miss
// on every single load.
//
// The forming bar never comes out of the cache. The wrapper drops the
// trailing bar whose close is still in the future when it stores a series,
// and serves a hit past its coverage only while the bar after its last
// closed one is still forming: so a warm load during market hours is short
// by exactly the forming bar, and never wrong about a bar it does return.
// That is the engine's guard (src/feed/cache.ts), exercised end to end by
// this page's own tests; the stale badge below is what tells the user the
// chart is a bar short, and the cache menu's reload is the remedy.
export function initFeed(a, feedOptions) {
  app = a;
  liveFeed = new YFinanceDataFeed(feedOptions);
  app.cache = withBarCache
    ? withBarCache(liveFeed, {
        ttlMs: 10 * 60_000,
        // `barCloses` reports the instant a bar CLOSES, which is not the same
        // question as how many seconds it lasts, and is the only one the cache
        // can act on: it is what decides whether the last bar is still forming
        // and must be refetched. The registry answers it for calendar codes
        // too, where there is no fixed length to state, and returns null for
        // tick and volume bars so they opt themselves out of caching.
        //
        // This used to pass `intervalSeconds`, which 1.4.0 renamed. Nothing
        // read it, so the wrapper had silently been running on its default,
        // which happens to be exactly this, hence no visible symptom.
        //
        // The zone is read inside the closure, not captured now: the chart's
        // timezone is a runtime setting, and a New York month is not a Mumbai
        // month.
        barCloses: (code, barStartSec) => barCloseSec(code, barStartSec, app.chartTimezone),
      })
    : null;
  feed = app.cache || liveFeed;
}

/** Newest bar time this page has actually seen, per `symbol|interval`, and session when it is extended. */
const lastBarSeen = new Map();
const seenKey = (symbol, interval, variant) => symbol + '|' + interval + (variant?.session === 'extended' ? '|extended' : '');
/** Newest bar per `symbol|interval` as the picker names it, with the wire frame it was judged on. */
const newestSeen = new Map();

/**
 * A cacheable request. Two things about the range matter, and both were got
 * wrong before they were got right.
 *
 * `from` is snapped to the bar grid so it is stable between two loads inside
 * the same bar. The cache treats an earlier `from` as a real gap at the left
 * edge and refetches, so an unsnapped "now minus a year" misses every time.
 *
 * `to` stops at the newest bar we have while the venue is shut. The cache
 * allows a hit past its coverage only while the bar after its last closed
 * one is still forming, which is right and which it has no way to relax: it
 * cannot know a market is closed. The host can. Asking a shut venue for
 * bars up to the end of today is asking for bars that cannot exist, and it
 * is what made every out-of-hours load cold: on a Sunday, a daily series
 * whose last bar closed on Friday is permanently past coverage. While the
 * venue is open (or trades around the clock, or has no hours in our table)
 * the request runs to the end of the forming bar as before, and the cache's
 * own forming-bar rule is what keeps it fresh.
 */
export function barsRequest(symbol, interval, period, variant) {
  const sec = intervalSeconds(interval) || 86400;
  const now = Math.floor(Date.now() / 1000);
  let to = Math.floor(now / sec) * sec + sec - 1;
  const seen = lastBarSeen.get(seenKey(symbol, interval, variant));
  // An extended series trades before and after the regular one, so its own hours decide.
  if (seen !== undefined && !venueLive(symbol, sessionOf(variant))) to = Math.min(to, seen + sec - 1);
  // `max` is 1e6 days in the picker's table, which as a `from` is an epoch
  // far enough back to be meaningless; a century is as much as any of this
  // data goes, and it keeps the value readable in a debugger.
  const days = Math.min(PERIOD_DAYS[period] || 366, 40000);
  const from = Math.floor((now - days * 86400) / sec) * sec;
  // The variant is part of the cache key, so the regular and the extended
  // series never serve each other's bars.
  return { symbol, exchange: exchangeOf(symbol), interval, period, from, to, ...(variant ? { variant } : {}) };
}

/** Was the last `fetchBars` served out of the cache, and how long did it take. */
let lastFetch = { warm: false, ms: 0, cached: false };

/**
 * In-flight requests by slot. A slot is a place on the page that shows one
 * series at a time (the main chart, the second pane): a newer request for
 * the slot makes the older one's answer useless, and worse than useless if
 * it lands second and paints the symbol the user just left. Callers that
 * can overlap legitimately (a comparison, the replay's finer bars) name no
 * slot and run independently.
 */
const inflight = new Map();

/** Cancel whatever `slot` is loading. Its caller sees an AbortedError. */
export function abortFetch(slot) {
  const ctl = inflight.get(slot);
  if (!ctl) return false;
  inflight.delete(slot);
  ctl.abort();
  return true;
}

/**
 * Every bar request in this page goes through here. A folded interval is
 * fetched at its source frame (so the cache holds daily bars once, shared
 * with the 1D view) and bucketed afterwards.
 *
 * `opts`: `noCache` reaches the wire and refreshes the entry; `slot` (see
 * `inflight`) cancels the slot's previous request; `signal` is a caller's
 * own AbortSignal for anything else.
 */
export async function fetchBars(symbol, interval, period, opts) {
  const timezone = opts?.timezone || app.chartTimezone;
  // Validated before anything is built from it: `barsRequest` would fall
  // back to a day for a code it cannot size, and the wire would then draw
  // whatever came back under the label that was asked for.
  try {
    resolvePickerInterval(interval);
  } catch (e) {
    if (e instanceof UnknownIntervalError) {
      toast('error', `"${interval}" is not an interval this build knows. Nothing was fetched.`);
    }
    throw e;
  }
  const fold = foldedInterval(interval);
  const wire = fold ? fold.foldFrom : interval;
  const variant = opts && opts.variant;
  const req = barsRequest(symbol, wire, period, variant);
  // Asked of the feed's own declaration, before the wire: extended hours the
  // source does not have are refused here rather than fetched as regular ones.
  if (variant && variant.session === 'extended' && !liveFeed.dataVariants(req).sessions.includes('extended')) {
    throw new UnsupportedSessionError(`Extended hours are not available for ${symbol} ${interval} bars from this source`);
  }
  if (opts && opts.noCache) req.noCache = true;
  let controller = null;
  const slot = opts && opts.slot;
  if (slot) {
    abortFetch(slot);
    controller = new AbortController();
    inflight.set(slot, controller);
    req.signal = controller.signal;
  } else if (opts && opts.signal) {
    req.signal = opts.signal;
  }
  const before = app.cache ? app.cache.stats().hits : 0;
  const t0 = performance.now();
  let bars;
  let warm = false;
  try {
    bars = await feed.getBars(req);
    warm = Boolean(app.cache) && app.cache.stats().hits > before;
    // The cache holds back a bar that has not closed, as it must, so a warm
    // answer can end before the newest bar this page has already shown: the
    // day's candle after the close, the forming one in the session. With no
    // live subscription here to supply it again, the chart would put an
    // older close up as the last price. The wire has it.
    const seen = lastBarSeen.get(seenKey(symbol, wire, variant));
    if (warm && seen !== undefined && (bars.at(-1)?.time ?? -Infinity) < seen) {
      bars = await feed.getBars({ ...req, noCache: true });
      warm = false;
    }
  } finally {
    if (controller && inflight.get(slot) === controller) inflight.delete(slot);
  }
  lastFetch = { cached: Boolean(app.cache), warm, ms: Math.round(performance.now() - t0) };
  if (bars.length) {
    lastBarSeen.set(seenKey(symbol, wire, variant), bars[bars.length - 1].time);
    // Freshness is judged on the wire frame: a folded month is as fresh as
    // the daily bars under it, and a calendar bucket has no length to judge by.
    newestSeen.set(seenKey(symbol, interval, variant), { wire, time: bars[bars.length - 1].time });
    syncStaleBadge();
  }
  return fold ? foldToBuckets(bars, fold.bucketing, timezone) : bars;
}

/**
 * Where the last load's bars came from. Without this the cache is a feature
 * you can only believe in: "warm" and a two-millisecond read are the whole
 * observable difference between a hit and a fetch.
 */
export function fetchNote() {
  if (!lastFetch.cached) return '';
  return `  ·  ${lastFetch.warm ? 'warm' : 'fetched'} ${lastFetch.ms} ms`;
}

// ── stale data ─────────────────────────────────────────────────────────
// A chart that stops updating looks exactly like a chart that is up to
// date, and this page draws Buy and Sell on it. The badge says when the
// newest bar is not the one that should be forming right now: the feed is
// behind, or the load was warm and the cache (rightly) kept back a forming
// bar this page had not seen yet. Judged from the registry's close time for
// the bar, not from the epoch grid, because a session-anchored hourly bar
// opens at 09:15 and the grid would call it late an hour early.

/** Seconds a bar may be overdue before it is called stale: the source's own publication delay. */
export const STALE_GRACE_SEC = 60;

/**
 * Whether the newest bar we hold is older than it should be. Null when the
 * question does not apply: the venue is shut, or the frame has no fixed
 * close. Otherwise `{ stale, overdueSec }`, where `overdueSec` is how long
 * ago the newest bar closed (negative while it is still forming).
 */
export function staleness(symbol, wireInterval, newestSec, nowSec, zone, session = 'regular') {
  if (newestSec === undefined || newestSec === null) return null;
  if (!venueLive(symbol, session)) return null;
  let closeSec = barCloseSec ? barCloseSec(wireInterval, newestSec, zone) : null;
  if (closeSec == null) {
    const sec = intervalSeconds(wireInterval);
    closeSec = sec ? newestSec + sec : null;
  }
  if (closeSec == null) return null;
  const overdueSec = nowSec - closeSec;
  return { stale: overdueSec > STALE_GRACE_SEC, overdueSec };
}

/** The reading for the symbol and interval on the main chart, or null. */
export function currentStaleness(nowSec = Math.floor(Date.now() / 1000)) {
  if (!app || !app.req || !app.req.symbol) return null;
  const seen = newestSeen.get(seenKey(app.req.symbol, app.req.interval, requestVariant(app.req)));
  if (!seen) return null;
  return staleness(app.req.symbol, seen.wire, seen.time, nowSec, app.chartTimezone, sessionOf(app.req));
}

// Minutes are rounded before the hours are split off, or 7190 s reads "1 h 60 min".
export const overdueText = (sec) => {
  const min = Math.max(1, Math.round(sec / 60));
  return min >= 60 ? `${Math.floor(min / 60)} h ${min % 60} min` : `${min} min`;
};

let staleTimer = 0;
let shellWatch = null;

/**
 * The shell bar rebuilds itself on every state change and moves `#status`
 * into a fresh readout each time, which discards whatever sat beside it,
 * badge included. Watching the bar's direct children (not its subtree) is
 * one callback per rebuild and nothing per frame, and it keeps the toolbar
 * from having to know the badge exists.
 */
function watchShellRebuilds() {
  if (shellWatch || typeof MutationObserver === 'undefined') return;
  const bar = el('shellbar');
  if (!bar) return;
  shellWatch = new MutationObserver(() => syncStaleBadge());
  shellWatch.observe(bar, { childList: true });
}

/**
 * Show or hide the badge for the main chart. Called after every load and
 * on a slow clock, because staleness is a time of day: a chart left open
 * through the bar's close goes stale without anything else happening.
 */
export function syncStaleBadge() {
  if (typeof document === 'undefined') return null;
  const status = el('status');
  if (!status || !status.parentNode) return null;
  if (!staleTimer) {
    staleTimer = setInterval(syncStaleBadge, 30_000);
    // Node hands back an object here; the browser a number. Only the former
    // can keep a process alive, and a badge must not.
    if (staleTimer && typeof staleTimer.unref === 'function') staleTimer.unref();
  }
  watchShellRebuilds();
  let badge = el('stale');
  const reading = currentStaleness();
  const on = Boolean(reading && reading.stale);
  if (!on) {
    if (badge) badge.hidden = true;
    return badge;
  }
  if (!badge) {
    badge = document.createElement('span');
    badge.id = 'stale';
    badge.className = 'badge badge--stale';
    badge.textContent = 'stale';
  }
  // Beside the readout it belongs to, wherever the readout is now.
  if (badge.parentNode !== status.parentNode) status.parentNode.insertBefore(badge, status);
  badge.hidden = false;
  badge.title = `The newest bar closed ${overdueText(reading.overdueSec)} ago while the market is open. `
    + 'The feed is behind, or this was a warm load and the cache holds only closed bars: reload ignoring the cache from the cache menu.';
  return badge;
}

// ── bar cache ──────────────────────────────────────────────────────────

export function openCacheMenu(anchor) {
  if (!app.cache) {
    el('status').textContent = 'this dist/ has no bar cache';
    return;
  }
  const s = app.cache.stats();
  const loads = s.hits + s.misses;
  popupMenu(anchor, [
    // A heading, not a row: a menu entry that only reports a number is a
    // control with nothing behind it. The two rows below both do something.
    { group: `${s.hits} warm of ${loads} load${loads === 1 ? '' : 's'} · `
      + `${s.entries} series · ${s.bars.toLocaleString('en-US')} bars` },
    {
      label: 'Reload ignoring the cache',
      onSelect: () => { app.load({ noCache: true }); },
    },
    {
      label: 'Clear the cache',
      onSelect: async () => {
        await app.cache.clear();
        el('status').textContent = 'bar cache cleared';
        renderToolbar();
      },
    },
  ]);
}
