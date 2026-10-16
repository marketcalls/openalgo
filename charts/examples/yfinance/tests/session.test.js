import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  YFinanceDataFeed, initFeed, barsRequest, fetchBars, fetchNote, classifyHistoryResponse, feedErrorState, UnsupportedSessionError,
  staleness, currentStaleness,
} from '../src/feed.js';
import { initStatus, marketStatusReading, symbolStatus, venueLive } from '../src/status.js';
import { UP } from '../src/ui.js';
import { EXTENDED, extendedSessionAvailable, requestVariant, sessionLabel, sessionOf } from '../src/session.js';
import { referenceDataContext } from '../src/expression.js';
import { flatBar } from './helpers.js';

// Extended hours are the source's own pre and post market bars, a different
// series from the regular one. The reference host asks for them only where
// the source has them, keeps them apart from the regular series in its cache,
// and says so when an instrument or interval has none.

const WEDNESDAY_1507 = Date.UTC(2024, 0, 10, 15, 7);
const at = (h, m) => Date.UTC(2024, 0, 10, h, m) / 1000;
const response = (status, body) => ({ ok: status >= 200 && status < 300, status, headers: { get: () => null },
  text: async () => (typeof body === 'string' ? body : JSON.stringify(body)) });

describe('session identity in the reference host', () => {
  it('names extended hours as a variant and regular hours as the default series', () => {
    expect(requestVariant({ symbol: 'AAPL', interval: '5m', session: 'extended' })).toEqual(EXTENDED);
    expect(requestVariant({ symbol: 'AAPL', interval: '5m', session: 'regular' })).toBeUndefined();
    expect(requestVariant({ symbol: 'AAPL', interval: '5m' })).toBeUndefined();
    expect(sessionOf({ session: 'extended' })).toBe('extended');
    expect(sessionOf({ session: 'bogus' })).toBe('regular');
    expect(sessionLabel('extended')).toBe('Extended hours');
    expect(sessionLabel('regular')).toBe('Regular hours');
  });

  it('declares extended hours only for intraday bars of a US listed stock, as the server does', async () => {
    const feed = new YFinanceDataFeed();
    expect(await feed.dataVariants({ symbol: 'AAPL', exchange: 'US', interval: '5m' })).toEqual({ sessions: ['regular', 'extended'] });
    expect(await feed.dataVariants({ symbol: 'BRK-B', exchange: 'US', interval: '1h' })).toEqual({ sessions: ['regular', 'extended'] });
    for (const [symbol, interval] of [['AAPL', '1d'], ['RELIANCE.NS', '5m'], ['^GSPC', '5m'], ['BTC-USD', '5m'], ['AAPL', '1wk']]) {
      expect(extendedSessionAvailable(symbol, interval), symbol + ' ' + interval).toBe(false);
      expect(await feed.dataVariants({ symbol, exchange: '', interval })).toEqual({ sessions: ['regular'] });
    }
  });

  it('asks the server for extended hours only when the request names them', async () => {
    const urls = [];
    globalThis.fetch = vi.fn(async url => { urls.push(String(url)); return response(200, [flatBar(1, 1)]); });
    const feed = new YFinanceDataFeed();
    await feed.getBars({ symbol: 'AAPL', interval: '5m', period: '5d' });
    await feed.getBars({ symbol: 'AAPL', interval: '5m', period: '5d', variant: EXTENDED });
    expect(urls[0]).not.toContain('session=');
    expect(urls[1]).toContain('&session=extended');
  });

  it('types the refusal the server gives for a session the instrument does not have', () => {
    let error;
    try { classifyHistoryResponse(400, JSON.stringify({ error: 'extended hours are served only for intraday bars', code: 'unsupported_session' }), { symbol: 'AAPL', interval: '1d', period: '1y' }); }
    catch (e) { error = e; }
    expect(error).toBeInstanceOf(UnsupportedSessionError);
    expect(feedErrorState(error)).toMatchObject({ state: 'unsupported', retryable: false });
  });

  it('puts the session on the chart data context', () => {
    expect(referenceDataContext({ symbol: 'AAPL', interval: '5m', session: 'extended' })).toEqual({ symbol: 'AAPL', interval: '5m', variant: EXTENDED });
    expect(referenceDataContext({ symbol: 'AAPL', interval: '5m' })).toEqual({ symbol: 'AAPL', interval: '5m' });
  });
});

describe('extended hours on the clock', () => {
  // Wednesday 10 January 2024 in New York (UTC-5): 07:00 is pre-market,
  // 10:07 the regular session, 17:30 post-market and 21:00 after all of it.
  const PRE = Date.UTC(2024, 0, 10, 12, 0);
  const POST = Date.UTC(2024, 0, 10, 22, 30);
  const NIGHT = Date.UTC(2024, 0, 11, 2, 0);
  afterEach(() => { vi.useRealTimers(); });

  it('says a US stock trades in its pre and post market only for an extended chart', () => {
    vi.useFakeTimers({ now: PRE });
    expect(venueLive('AAPL')).toBe(false);
    expect(venueLive('AAPL', 'extended')).toBe(true);
    expect(marketStatusReading('AAPL')).toEqual({ text: 'Market closed' });
    expect(marketStatusReading('AAPL', 'extended')).toEqual({ text: 'Pre-market' });
    vi.setSystemTime(WEDNESDAY_1507);
    expect(marketStatusReading('AAPL', 'extended')).toEqual({ text: 'Market open', color: UP });
    vi.setSystemTime(POST);
    expect(venueLive('AAPL', 'extended')).toBe(true);
    expect(marketStatusReading('AAPL', 'extended')).toEqual({ text: 'Post-market' });
    vi.setSystemTime(NIGHT);
    expect(venueLive('AAPL', 'extended')).toBe(false);
    expect(marketStatusReading('AAPL', 'extended')).toEqual({ text: 'Market closed' });
    // A venue without extended hours keeps its regular ones.
    vi.setSystemTime(Date.UTC(2024, 0, 10, 2, 0));
    expect(venueLive('RELIANCE.NS', 'extended')).toBe(false);
  });

  it('names the session state on the status line of the chart that shows it', () => {
    vi.useFakeTimers({ now: PRE });
    // The monogram tile needs a canvas; its drawing is not what is under test.
    const previous = globalThis.document;
    globalThis.document = { createElement: () => ({ getContext: () => new Proxy({}, { get: () => () => {} }) }) };
    try {
      initStatus({ req: { symbol: 'AAPL', session: 'extended' }, currentBars: [], chartTimezone: 'America/New_York' });
      expect(marketStatusReading().text).toBe('Pre-market');
      expect(symbolStatus().marketStatus.text).toBe('Pre-market');
      // The second chart names its own session, and another symbol without one reads regular hours.
      expect(symbolStatus({ symbol: 'MSFT', bars: [] }).marketStatus.text).toBe('Market closed');
      expect(symbolStatus({ symbol: 'AAPL', bars: [], session: 'extended' }).marketStatus.text).toBe('Pre-market');
      expect(symbolStatus({ symbol: 'AAPL', bars: [], session: 'regular' }).marketStatus.text).toBe('Market closed');
    } finally { globalThis.document = previous; }
  });

  it('judges an extended chart stale in the pre-market and a regular one not at all', () => {
    vi.useFakeTimers({ now: PRE });
    const now = Math.floor(PRE / 1000);
    expect(staleness('AAPL', '5m', now - 900, now)).toBeNull();
    expect(staleness('AAPL', '5m', now - 900, now, undefined, 'extended')).toMatchObject({ stale: true });
    expect(staleness('AAPL', '5m', now - 120, now, undefined, 'extended')).toMatchObject({ stale: false });
  });
});

describe('extended hours through the bar cache', () => {
  let app;
  const urls = [];
  beforeEach(() => {
    urls.length = 0;
    app = { chartTimezone: 'America/New_York', cache: null, req: { symbol: 'AAPL', interval: '5m', period: '1mo' } };
    initFeed(app);
    vi.useFakeTimers({ now: WEDNESDAY_1507 });
    // The server's extended answer has a pre-market bar the regular one lacks.
    globalThis.fetch = vi.fn(async url => {
      urls.push(String(url));
      const extended = String(url).includes('session=extended');
      return response(200, [...(extended ? [flatBar(at(13, 55), 90)] : []), flatBar(at(14, 55), 100), flatBar(at(15, 0), 101)]);
    });
  });
  afterEach(() => { vi.useRealTimers(); });

  it('keeps the regular and the extended series in separate entries', async () => {
    const regular = await fetchBars('AAPL', '5m', '1mo');
    const extended = await fetchBars('AAPL', '5m', '1mo', { variant: EXTENDED });
    expect(urls).toHaveLength(2);
    expect(regular.map(bar => bar.time)).toEqual([at(14, 55), at(15, 0)]);
    expect(extended.map(bar => bar.time)).toEqual([at(13, 55), at(14, 55), at(15, 0)]);
    // Each is warm now, from its own entry.
    expect((await fetchBars('AAPL', '5m', '1mo', { variant: EXTENDED })).map(bar => bar.time)).toEqual([at(13, 55), at(14, 55), at(15, 0)]);
    expect(fetchNote()).toContain('warm');
    expect((await fetchBars('AAPL', '5m', '1mo')).map(bar => bar.time)).toEqual([at(14, 55), at(15, 0)]);
    expect(urls).toHaveLength(2);
    expect(barsRequest('AAPL', '5m', '1mo', EXTENDED).variant).toEqual(EXTENDED);
    expect(barsRequest('AAPL', '5m', '1mo')).not.toHaveProperty('variant');
  });

  it('asks for the forming extended bar in the pre-market and reads its staleness there', async () => {
    // 07:08 New York: the regular series is shut, the extended one is
    // trading, and the source has published nothing after the 06:55 bar.
    vi.setSystemTime(Date.UTC(2024, 0, 10, 12, 8));
    globalThis.fetch = vi.fn(async url => { urls.push(String(url)); return response(200, [flatBar(at(11, 50), 90), flatBar(at(11, 55), 91)]); });
    await fetchBars('AAPL', '5m', '1mo', { variant: EXTENDED });
    // The next load reaches the bar forming now, not only the last one seen.
    expect(barsRequest('AAPL', '5m', '1mo', EXTENDED).to).toBe(at(12, 5) + 299);
    app.req = { symbol: 'AAPL', interval: '5m', period: '1mo', session: 'extended' };
    expect(currentStaleness()).toEqual({ stale: true, overdueSec: 8 * 60 });
  });

  it('refuses extended hours the source does not have without asking the server', async () => {
    const error = await fetchBars('RELIANCE.NS', '5m', '1mo', { variant: EXTENDED }).catch(e => e);
    expect(error).toBeInstanceOf(UnsupportedSessionError);
    expect(error.message).toContain('RELIANCE.NS');
    expect(urls).toHaveLength(0);
    // A daily chart has no extended hours either, whatever the symbol.
    await expect(fetchBars('AAPL', '1d', '1y', { variant: EXTENDED })).rejects.toBeInstanceOf(UnsupportedSessionError);
    expect(urls).toHaveLength(0);
  });
});
