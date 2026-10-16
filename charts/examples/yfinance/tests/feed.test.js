import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  YFinanceDataFeed, initFeed, barsRequest, fetchBars, fetchNote, abortFetch,
  classifyHistoryResponse, feedErrorState, staleness, currentStaleness, syncStaleBadge,
  FeedError, NotFoundError, RateLimitedError, NetworkError, AbortedError, STALE_GRACE_SEC, overdueText,
} from '../src/feed.js';
import { UnknownIntervalError } from '../src/intervals.js';
import { fakeDom, flatBar } from './helpers.js';

const DAY = 86400;
// Saturday 6 January 2024, midday UTC: the US tape is shut, so the request
// window stops at the newest bar the page has seen.
const SATURDAY = Date.UTC(2024, 0, 6, 12);
// Wednesday 10 January 2024, 15:07 UTC is 10:07 in New York: the US tape is
// open, and the five-minute bar that opened at 15:05 is still forming.
const WEDNESDAY_1507 = Date.UTC(2024, 0, 10, 15, 7);
const at = (h, m, s = 0) => Date.UTC(2024, 0, 10, h, m, s) / 1000;

const REQ = { symbol: 'AAPL', interval: '1d', period: '1y' };

/** What `fetch` resolves to: the adapter reads the body as text. */
const response = (status, body) => ({
  ok: status >= 200 && status < 300, status,
  json: async () => body,
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)),
});

/** A `fetch` that answers every history request with `bars`, recording the URLs. */
function stubFetch(bars, calls) {
  globalThis.fetch = vi.fn(async (url) => {
    calls.push(String(url));
    return response(200, bars);
  });
}

/** A `fetch` that answers each call with the next handler in the list. */
function fetchQueue(handlers, calls = []) {
  globalThis.fetch = vi.fn((url, init) => {
    calls.push(String(url));
    return handlers.shift()(url, init);
  });
  return calls;
}

/** A request that never completes on its own: it rejects only when its signal fires. */
const hang = () => (url, { signal }) => new Promise((_, reject) => {
  signal.addEventListener('abort', () => reject(Object.assign(new Error('aborted'), { name: 'AbortError' })));
});
const offline = () => async () => { throw new TypeError('Failed to fetch'); };
const answer = (status, body) => async () => response(status, body);

describe('YFinanceDataFeed', () => {
  it('surfaces the server error message rather than an empty chart', async () => {
    globalThis.fetch = async () => response(200, { error: 'boom' });
    await expect(new YFinanceDataFeed().getBars(REQ)).rejects.toThrow('boom');
    globalThis.fetch = async () => response(500, {});
    await expect(new YFinanceDataFeed().getBars(REQ)).rejects.toThrow('history failed (500)');
  });

  it('gives up on a request that does not answer in time', async () => {
    fetchQueue([hang()]);
    const feed = new YFinanceDataFeed({ timeoutMs: 20, retries: 0 });
    const err = await feed.getBars(REQ).catch((e) => e);
    expect(err).toBeInstanceOf(NetworkError);
    expect(err.reason).toBe('timeout');
    expect(err.retryable).toBe(false);
    expect(feedErrorState(err)).toEqual({ state: 'network', message: err.message, retryable: false });
  });

  it('retries a dropped connection once, after a pause', async () => {
    const bars = [flatBar(1, 1)];
    const calls = fetchQueue([offline(), answer(200, bars)]);
    const feed = new YFinanceDataFeed({ retryDelayMs: 1 });
    await expect(feed.getBars(REQ)).resolves.toEqual(bars);
    expect(calls).toHaveLength(2);
    // Twice offline is the answer.
    fetchQueue([offline(), offline()], calls);
    const err = await feed.getBars(REQ).catch((e) => e);
    expect(err).toBeInstanceOf(NetworkError);
    expect(err.reason).toBe('offline');
    expect(calls).toHaveLength(4);
  });

  it('does not retry what will not change: a missing symbol, a throttle, a timeout', async () => {
    const feed = new YFinanceDataFeed({ retryDelayMs: 1 });
    let calls = fetchQueue([answer(404, { error: 'nope' }), answer(200, [flatBar(1, 1)])]);
    await expect(feed.getBars(REQ)).rejects.toBeInstanceOf(NotFoundError);
    expect(calls).toHaveLength(1);
    calls = fetchQueue([answer(429, {}), answer(200, [flatBar(1, 1)])]);
    await expect(feed.getBars(REQ)).rejects.toBeInstanceOf(RateLimitedError);
    expect(calls).toHaveLength(1);
  });

  it('is cancelled through the request signal, during the fetch and during the backoff', async () => {
    const feed = new YFinanceDataFeed({ retryDelayMs: 50 });
    fetchQueue([hang()]);
    let ctl = new AbortController();
    let p = feed.getBars({ ...REQ, signal: ctl.signal });
    ctl.abort();
    await expect(p).rejects.toBeInstanceOf(AbortedError);
    // Offline, then aborted while waiting to try again: no second round trip.
    const calls = fetchQueue([offline(), answer(200, [])]);
    ctl = new AbortController();
    p = feed.getBars({ ...REQ, signal: ctl.signal });
    await new Promise((r) => setTimeout(r, 5));
    ctl.abort();
    await expect(p).rejects.toBeInstanceOf(AbortedError);
    expect(calls).toHaveLength(1);
  });
});

describe('classifyHistoryResponse', () => {
  const bars = [flatBar(1, 1)];
  it('returns the bars for a good answer', () => {
    expect(classifyHistoryResponse(200, JSON.stringify(bars), REQ)).toEqual(bars);
  });

  it('types the failures the shell treats differently', () => {
    const err = (status, body) => {
      try { classifyHistoryResponse(status, body, REQ); } catch (e) { return e; }
      return null;
    };
    expect(err(404, '{}')).toBeInstanceOf(NotFoundError);
    expect(err(429, '{}')).toBeInstanceOf(RateLimitedError);
    expect(err(503, '')).toBeInstanceOf(NetworkError);
    expect(err(503, '').retryable).toBe(true);
    // The server's own faults carry a code and a sentence: the code is what
    // is keyed on, and a 503 with the install instruction is not retried.
    const notInstalled = err(503, JSON.stringify({ error: 'yfinance is not installed: pip install -r requirements.txt, or start with --fixture', code: 'not_installed' }));
    expect(notInstalled).toBeInstanceOf(NetworkError);
    expect(notInstalled.retryable).toBe(false);
    expect(notInstalled.message).toContain('pip install');
    expect(err(500, JSON.stringify({ error: 'nothing here', code: 'no_data' }))).toBeInstanceOf(NotFoundError);
    expect(err(500, JSON.stringify({ error: 'slow down', code: 'rate_limited' }))).toBeInstanceOf(RateLimitedError);
    const throttled = (() => {
      try { classifyHistoryResponse(429, '{"error":"x","code":"rate_limited"}', REQ, new Map([['Retry-After', '30']])); } catch (e) { return e; }
      return null;
    })();
    expect(throttled.retryAfterSec).toBe(30);
    // A 1.x server answered every fault with a 500 and the Python
    // exception's text; the text is still read when there is no code.
    expect(err(500, JSON.stringify({ error: 'YFRateLimitError: Too Many Requests. Rate limited. Try after a while.' })))
      .toBeInstanceOf(RateLimitedError);
    expect(err(500, JSON.stringify({ error: 'No data found, symbol may be delisted' }))).toBeInstanceOf(NotFoundError);
    // yfinance's answer for a symbol it does not know is an empty frame.
    const empty = err(200, '[]');
    expect(empty).toBeInstanceOf(NotFoundError);
    expect(empty.message).toContain('AAPL');
    expect(err(500, JSON.stringify({ error: 'ValueError: something else' }))).toBeInstanceOf(FeedError);
    expect(err(500, JSON.stringify({ error: 'ValueError: something else' })).state).toBe('error');
    expect(err(200, '<html>')).toBeInstanceOf(FeedError);
    expect(err(200, '{"bars":[]}').message).toContain('shape');
  });

  it('maps every error, typed or not, to a state', () => {
    expect(feedErrorState(new NotFoundError('x')).state).toBe('not-found');
    expect(feedErrorState(new RateLimitedError('x')).state).toBe('rate-limited');
    expect(feedErrorState(new AbortedError()).state).toBe('aborted');
    expect(feedErrorState(new UnknownIntervalError('3x')).state).toBe('unknown-interval');
    expect(feedErrorState(new Error('plain'))).toEqual({ state: 'error', message: 'plain', retryable: false });
    expect(feedErrorState('text')).toEqual({ state: 'error', message: 'text', retryable: false });
  });
});

describe('bar requests', () => {
  let app;
  const calls = [];
  beforeEach(() => {
    calls.length = 0;
    app = { chartTimezone: 'Asia/Kolkata', cache: null, req: {} };
    initFeed(app);
    vi.useFakeTimers({ now: SATURDAY });
  });
  afterEach(() => { vi.useRealTimers(); });

  it('wraps the live feed in the bar cache this dist ships', () => {
    expect(app.cache).not.toBeNull();
    expect(typeof app.cache.stats).toBe('function');
  });

  it('snaps the range to the bar grid and names the venue', () => {
    const now = Math.floor(SATURDAY / 1000);
    const r = barsRequest('RELIANCE.NS', '1d', '1y');
    expect(r.exchange).toBe('NSE');
    expect(r.interval).toBe('1d');
    expect(r.period).toBe('1y');
    expect(r.from % DAY).toBe(0);
    expect(r.from).toBe(Math.floor((now - 366 * DAY) / DAY) * DAY);
    expect(r.to).toBe(Math.floor(now / DAY) * DAY + DAY - 1);
  });

  it('fetches a folded frame at its source interval and buckets the result', async () => {
    // Daily bars either side of the February boundary in Kolkata.
    const bars = [
      flatBar(Date.UTC(2024, 0, 30, 12) / 1000, 100, 1),
      flatBar(Date.UTC(2024, 0, 31, 12) / 1000, 101, 2),
      flatBar(Date.UTC(2024, 1, 1, 12) / 1000, 102, 3),
    ];
    stubFetch(bars, calls);
    const out = await fetchBars('AAPL', '1mo', '5y');
    expect(calls).toHaveLength(1);
    expect(calls[0]).toContain('interval=1d');
    expect(calls[0]).toContain('period=5y');
    expect(out).toHaveLength(2);
    expect(out[0].volume).toBe(3);
    expect(out[1].close).toBe(102);
  });

  it('stops asking past the newest bar while the venue is shut', async () => {
    const last = Date.UTC(2024, 0, 5, 0) / 1000;   // Friday's daily bar
    stubFetch([flatBar(last - DAY, 99), flatBar(last, 100)], calls);
    await fetchBars('AAPL', '1d', '1y');
    expect(barsRequest('AAPL', '1d', '1y').to).toBe(last + DAY - 1);
    // A venue that never closes keeps running to the end of the forming bar.
    stubFetch([flatBar(last, 100)], calls);
    await fetchBars('BTC-USD', '1d', '1y');
    const now = Math.floor(SATURDAY / 1000);
    expect(barsRequest('BTC-USD', '1d', '1y').to).toBe(Math.floor(now / DAY) * DAY + DAY - 1);
  });

  it('folds a secondary request in its captured timezone instead of the primary zone', async () => {
    const bars = [
      flatBar(Date.UTC(2024, 0, 31, 18) / 1000, 100, 1),
      flatBar(Date.UTC(2024, 0, 31, 20) / 1000, 101, 2),
      flatBar(Date.UTC(2024, 1, 1, 6) / 1000, 102, 3),
    ];
    stubFetch(bars, calls);
    const out = await fetchBars('ZONE', '1mo', '5y', { timezone: 'America/New_York' });
    expect(out.map(bar => bar.volume)).toEqual([3, 3]);
    expect(app.chartTimezone).toBe('Asia/Kolkata');
  });

  it('reports a cold load and then a warm one from the cache', async () => {
    const last = Date.UTC(2024, 0, 5, 0) / 1000;
    stubFetch([flatBar(last - DAY, 99), flatBar(last, 100)], calls);
    await fetchBars('MSFT', '1d', '1y');
    expect(fetchNote()).toMatch(/^ {2}· {2}fetched \d+ ms$/);
    await fetchBars('MSFT', '1d', '1y');
    expect(fetchNote()).toMatch(/^ {2}· {2}warm \d+ ms$/);
    expect(calls).toHaveLength(1);
  });

  it('reaches the wire again when a warm answer would end before the newest bar seen', async () => {
    // 16:30 in New York on Wednesday 10 January: the day's bar has traded and,
    // by its length, has not closed, so the cache rightly holds it back.
    vi.setSystemTime(Date.UTC(2024, 0, 10, 21, 30));
    const today = Date.UTC(2024, 0, 10, 14, 30) / 1000;
    stubFetch([flatBar(today - DAY, 99), flatBar(today, 100)], calls);
    await fetchBars('AMZN', '1d', '1y');
    const again = await fetchBars('AMZN', '1d', '1y');
    expect(again.at(-1)).toMatchObject({ time: today, close: 100 });
    expect(calls).toHaveLength(2);
    expect(fetchNote()).toMatch(/^ {2}· {2}fetched \d+ ms$/);
  });

  it('reaches the wire again when asked to ignore the cache', async () => {
    const last = Date.UTC(2024, 0, 5, 0) / 1000;
    stubFetch([flatBar(last, 100)], calls);
    await fetchBars('NVDA', '1d', '1y');
    await fetchBars('NVDA', '1d', '1y', { noCache: true });
    expect(calls).toHaveLength(2);
  });

  it('turns an empty answer into a NotFound rather than an empty chart', async () => {
    stubFetch([], calls);
    await expect(fetchBars('NOSUCH', '1d', '1y')).rejects.toBeInstanceOf(NotFoundError);
  });

  it('refuses a code the registry does not know before anything is fetched', async () => {
    const dom = fakeDom();
    stubFetch([flatBar(1, 1)], calls);
    await expect(fetchBars('AAPL', '3x', '1y')).rejects.toBeInstanceOf(UnknownIntervalError);
    expect(calls).toHaveLength(0);
    const toasts = dom.get('toasts').children;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].textContent).toContain('"3x"');
  });
});

describe('superseded requests', () => {
  let app;
  beforeEach(() => {
    app = { chartTimezone: 'Asia/Kolkata', cache: null, req: {} };
    initFeed(app);
  });

  it('aborts the slot\'s previous request when a newer one starts', async () => {
    const bars = [flatBar(Date.UTC(2024, 0, 5) / 1000, 100)];
    const calls = fetchQueue([hang(), answer(200, bars)]);
    const first = fetchBars('AAPL', '1d', '1y', { slot: 'main' });
    // Let the first request reach the wire before the second replaces it.
    await new Promise((r) => setTimeout(r, 0));
    const second = fetchBars('MSFT', '1d', '1y', { slot: 'main' });
    const err = await first.catch((e) => e);
    expect(err).toBeInstanceOf(AbortedError);
    expect(feedErrorState(err).state).toBe('aborted');
    await expect(second).resolves.toEqual(bars);
    expect(calls).toHaveLength(2);
  });

  it('leaves requests in different slots, and unslotted ones, alone', async () => {
    const bars = [flatBar(Date.UTC(2024, 0, 5) / 1000, 100)];
    fetchQueue([hang(), answer(200, bars), answer(200, bars)]);
    const pane2 = fetchBars('AAPL', '1h', '1mo', { slot: 'pane2' });
    await new Promise((r) => setTimeout(r, 0));
    await expect(fetchBars('MSFT', '1d', '1y', { slot: 'main' })).resolves.toEqual(bars);
    await expect(fetchBars('GOOGL', '1d', '1y')).resolves.toEqual(bars);
    expect(abortFetch('pane2')).toBe(true);
    await expect(pane2).rejects.toBeInstanceOf(AbortedError);
    expect(abortFetch('pane2')).toBe(false);
  });
});

describe('the forming bar and the cache', () => {
  let app;
  const calls = [];
  beforeEach(() => {
    calls.length = 0;
    app = { chartTimezone: 'America/New_York', cache: null, req: { symbol: 'AAPL', interval: '5m', period: '1mo' } };
    initFeed(app);
    vi.useFakeTimers({ now: WEDNESDAY_1507 });
  });
  afterEach(() => { vi.useRealTimers(); });

  it('never serves the forming bar warm, and goes back to the wire once it has closed', async () => {
    const bars = [flatBar(at(14, 55), 100), flatBar(at(15, 0), 101), flatBar(at(15, 5), 102)];
    stubFetch(bars, calls);
    const cold = await fetchBars('AAPL', '5m', '1mo');
    expect(cold.map((b) => b.time)).toEqual([at(14, 55), at(15, 0), at(15, 5)]);
    // The cache holds closed bars only: the 15:05 bar is still being built
    // and a snapshot of it would be a frozen candle. The page has shown that
    // bar already, so it comes from the wire, as it now stands.
    stubFetch([bars[0], bars[1], flatBar(at(15, 5), 102.5)], calls);
    const again = await fetchBars('AAPL', '5m', '1mo');
    expect(fetchNote()).toContain('fetched');
    expect(again.at(-1)).toMatchObject({ time: at(15, 5), close: 102.5 });
    expect(calls).toHaveLength(2);
    // 15:10 has passed: the 15:05 bar is closed and something newer exists,
    // so a hit past coverage is no longer safe. Well inside the TTL, so it
    // is the close time and nothing else that forces the fetch.
    vi.setSystemTime(Date.UTC(2024, 0, 10, 15, 10, 30));
    stubFetch(bars.concat(flatBar(at(15, 10), 103)), calls);
    const fresh = await fetchBars('AAPL', '5m', '1mo');
    expect(calls).toHaveLength(3);
    expect(fresh[fresh.length - 1].time).toBe(at(15, 10));
  });

  it('calls a bar stale once it has closed and the market is open', () => {
    const now = Math.floor(WEDNESDAY_1507 / 1000);
    // The forming bar: its close is still ahead.
    expect(staleness('AAPL', '5m', at(15, 5), now)).toEqual({ stale: false, overdueSec: now - at(15, 10) });
    // The bar before it: closed two minutes ago, nothing newer held.
    expect(staleness('AAPL', '5m', at(15, 0), now)).toEqual({ stale: true, overdueSec: 120 });
    // Inside the grace it is late, not stale: the source has a publication delay.
    expect(staleness('AAPL', '5m', at(15, 0), at(15, 5) + STALE_GRACE_SEC).stale).toBe(false);
    // Session-anchored hourly bars: the 09:30 bar closes at 10:30, not on the epoch grid.
    expect(staleness('AAPL', '1h', at(14, 30), now)).toEqual({ stale: false, overdueSec: now - at(15, 30) });
    // Daily bars are judged on the registry's close in the chart's zone.
    const today = Date.UTC(2024, 0, 10, 5) / 1000;
    expect(staleness('AAPL', '1d', today, now, 'America/New_York').stale).toBe(false);
    expect(staleness('AAPL', '1d', today - DAY, now, 'America/New_York').stale).toBe(true);
    // A shut venue has nothing to be late with.
    vi.setSystemTime(SATURDAY);
    expect(staleness('AAPL', '5m', at(15, 0), Math.floor(SATURDAY / 1000))).toBeNull();
    // Around the clock: always judged.
    const saturday = Math.floor(SATURDAY / 1000);
    expect(staleness('BTC-USD', '5m', saturday - 3600, saturday).stale).toBe(true);
    expect(staleness('BTC-USD', '5m', saturday - 200, saturday).stale).toBe(false);
  });

  it('puts the badge on the status line when the source falls behind and takes it off when the market shuts', async () => {
    const dom = fakeDom();
    const inserted = [];
    dom.get('status').parentNode = { insertBefore: (n) => inserted.push(n) };
    const bars = [flatBar(at(15, 0), 101), flatBar(at(15, 5), 102)];
    stubFetch(bars, calls);
    await fetchBars('AAPL', '5m', '1mo');
    expect(currentStaleness().stale).toBe(false);
    expect(dom.get('stale').hidden).toBe(true);
    // Asked again, the source has nothing past 15:00, which closed at 15:05.
    stubFetch(bars.slice(0, 1), calls);
    await fetchBars('AAPL', '5m', '1mo');
    expect(currentStaleness()).toEqual({ stale: true, overdueSec: 120 });
    const badge = dom.get('stale');
    expect(badge.hidden).toBe(false);
    expect(badge.title).toContain('closed 2 min ago');
    expect(inserted).toEqual([badge]);
    // The shell bar rebuilds its readout and moves #status into it: the
    // badge follows the readout rather than staying in the discarded one.
    const rebuilt = [];
    dom.get('status').parentNode = { insertBefore: (n) => rebuilt.push(n) };
    expect(syncStaleBadge()).toBe(badge);
    expect(rebuilt).toEqual([badge]);
    // Time passes with the page open: the reading follows the clock.
    vi.setSystemTime(Date.UTC(2024, 0, 10, 16, 7));
    expect(syncStaleBadge().title).toContain('closed 1 h 2 min ago');
    vi.setSystemTime(SATURDAY);
    expect(syncStaleBadge().hidden).toBe(true);
    // Another symbol on the main chart has no reading yet.
    vi.setSystemTime(WEDNESDAY_1507);
    app.req = { symbol: 'MSFT', interval: '5m', period: '1mo' };
    expect(currentStaleness()).toBeNull();
    expect(syncStaleBadge().hidden).toBe(true);
  });

  it('judges a folded frame on the bars it was folded from', async () => {
    app.req = { symbol: 'AAPL', interval: '1mo', period: '5y' };
    const today = Date.UTC(2024, 0, 10, 5) / 1000;
    stubFetch([flatBar(today - DAY, 100), flatBar(today, 101)], calls);
    await fetchBars('AAPL', '1mo', '5y');
    const now = Math.floor(WEDNESDAY_1507 / 1000);
    expect(currentStaleness()).toEqual({ stale: false, overdueSec: now - (today + DAY) });
  });
});

describe('overdueText', () => {
  it('rounds to the minute before it splits hours, so no reading says 60 min', () => {
    expect(overdueText(7190)).toBe('2 h 0 min');
    expect(overdueText(3660)).toBe('1 h 1 min');
    expect(overdueText(90)).toBe('2 min');
  });
});
