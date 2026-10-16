import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  initStatus, exchangeOf, nameOf, descriptionOf, venueLive, marketStatusReading,
  previousSessionClose, dayChangeReading, venueCalendar, SESSIONS,
} from '../src/status.js';
import { UP, DOWN } from '../src/ui.js';
import { flatBar } from './helpers.js';

// Wednesday 3 January 2024, 10:00 in Kolkata: NSE is trading, New York is
// asleep (23:30 the previous evening).
const KOLKATA_MORNING = Date.UTC(2024, 0, 3, 4, 30);
// Saturday 6 January 2024, midday UTC: every venue with hours is shut.
const SATURDAY = Date.UTC(2024, 0, 6, 12);

describe('symbol classification', () => {
  it('reads the venue off the yfinance suffix', () => {
    expect(exchangeOf('RELIANCE.NS')).toBe('NSE');
    expect(exchangeOf('^NSEI')).toBe('NSE');
    expect(exchangeOf('tcs.bo')).toBe('BSE');
    expect(exchangeOf('BTC-USD')).toBe('CRYPTO');
    expect(exchangeOf('^GSPC')).toBe('US');
    expect(exchangeOf('^FTSE')).toBe('INDEX');
    expect(exchangeOf('aapl')).toBe('US');
  });

  it('strips the suffix for the legend name', () => {
    expect(nameOf('reliance.ns')).toBe('RELIANCE');
    expect(nameOf('AAPL')).toBe('AAPL');
  });

  it('has a long name only for the symbols in its table', () => {
    expect(descriptionOf('aapl')).toBe('Apple Inc.');
    expect(descriptionOf('ZZZZ')).toBeNull();
  });
});

describe('session hours', () => {
  afterEach(() => { vi.useRealTimers(); });

  it('says which venues are trading right now, in their own zone', () => {
    vi.useFakeTimers({ now: KOLKATA_MORNING });
    expect(venueLive('RELIANCE.NS')).toBe(true);
    expect(venueLive('AAPL')).toBe(false);
    expect(venueLive('BTC-USD')).toBe(true);
    // No hours in the table means "could be live", so the feed keeps asking.
    expect(venueLive('^FTSE')).toBe(true);
  });

  it('is shut everywhere with hours on a weekend', () => {
    vi.useFakeTimers({ now: SATURDAY });
    expect(venueLive('RELIANCE.NS')).toBe(false);
    expect(venueLive('AAPL')).toBe(false);
    expect(venueLive('BTC-USD')).toBe(true);
  });

  it('hands the table to the library as a calendar with the extended hours the source serves', () => {
    const us = venueCalendar('US');
    expect(us.timezone).toBe('America/New_York');
    expect(us.calendar).toMatchObject({ sessions: ['0930-1600:23456'], preMarketMinutes: 330, postMarketMinutes: 240 });
    expect(venueCalendar('US')).toBe(us);
    expect(venueCalendar('NSE').calendar).not.toHaveProperty('preMarketMinutes');
    expect(venueCalendar('CRYPTO')).toBeNull();
    expect(venueCalendar('INDEX')).toBeNull();
  });

  it('reads a closed date the table lists as a holiday, which is not live either', () => {
    vi.useFakeTimers({ now: KOLKATA_MORNING });
    const regular = SESSIONS.NSE;
    initStatus({ req: { symbol: 'RELIANCE.NS' }, currentBars: [], chartTimezone: 'Asia/Kolkata' });
    try {
      SESSIONS.NSE = { ...regular, exceptions: { '2024-01-03': [] } };
      expect(marketStatusReading('RELIANCE.NS')).toEqual({ text: 'Market holiday' });
      expect(venueLive('RELIANCE.NS')).toBe(false);
    } finally { SESSIONS.NSE = regular; }
    expect(marketStatusReading('RELIANCE.NS')).toEqual({ text: 'Market open', color: UP });
  });

  it('asks the calendar once per phase, however often the legend draws, and again when it changes', () => {
    // Wednesday 3 January 2024, 15:29:50 in Kolkata: ten seconds before the close.
    vi.useFakeTimers({ now: Date.UTC(2024, 0, 3, 9, 59, 50) });
    const regular = SESSIONS.NSE;
    initStatus({ req: { symbol: 'RELIANCE.NS' }, currentBars: [], chartTimezone: 'Asia/Kolkata' });
    try {
      // A table entry of its own, so no other test's reading is held for it.
      SESSIONS.NSE = { ...regular };
      const asked = vi.spyOn(venueCalendar('NSE'), 'marketStatusAt');
      for (let frame = 0; frame < 120; frame++) {
        expect(marketStatusReading('RELIANCE.NS')).toEqual({ text: 'Market open', color: UP });
        vi.advanceTimersByTime(50);
      }
      expect(asked).toHaveBeenCalledTimes(1);
      // Past 15:30 the held reading has run out, and the close shows at once.
      vi.advanceTimersByTime(4000);
      expect(marketStatusReading('RELIANCE.NS')).toEqual({ text: 'Market closed' });
      expect(venueLive('RELIANCE.NS')).toBe(false);
      expect(asked).toHaveBeenCalledTimes(2);
    } finally { SESSIONS.NSE = regular; }
  });

  it('takes a venue that serves a pre-open and no post-close', () => {
    // 09:00 in New York on Wednesday 3 January 2024: in the pre-open.
    vi.useFakeTimers({ now: Date.UTC(2024, 0, 3, 14) });
    const us = SESSIONS.US;
    initStatus({ req: { symbol: 'AAPL', variant: { session: 'extended' } }, currentBars: [], chartTimezone: 'America/New_York' });
    try {
      SESSIONS.US = { zone: us.zone, open: us.open, close: us.close, pre: us.pre };
      expect(venueCalendar('US').calendar).toMatchObject({ preMarketMinutes: 330 });
      expect(venueCalendar('US').calendar).not.toHaveProperty('postMarketMinutes');
      expect(marketStatusReading('AAPL', 'extended')).toEqual({ text: 'Pre-market' });
      expect(venueLive('AAPL', 'extended')).toBe(true);
    } finally { SESSIONS.US = us; }
  });
});

describe('status-line readings', () => {
  let app;
  beforeEach(() => {
    app = { req: {}, currentBars: [], chartTimezone: 'Asia/Kolkata' };
    initStatus(app);
  });
  afterEach(() => { vi.useRealTimers(); });

  it('reads a secondary instrument and its own bars without changing the primary context', () => {
    app.req = { symbol: '^FTSE' };
    const day = Date.UTC(2024, 0, 2, 12) / 1000;
    const secondary = [flatBar(day, 200), flatBar(day + 86400, 210)];
    expect(marketStatusReading('BTC-USD')).toEqual({ text: 'Open 24x7', color: UP });
    expect(previousSessionClose(secondary, 'UTC')).toBe(200);
    expect(dayChangeReading(secondary, 'UTC')).toEqual({ label: '1D', text: '+10.00 (+5.00%)', color: UP });
    expect(marketStatusReading()).toBeUndefined();
    expect(previousSessionClose()).toBeNull();
  });

  it('reports the market state, or nothing for a venue without hours', () => {
    vi.useFakeTimers({ now: KOLKATA_MORNING });
    app.req = { symbol: 'RELIANCE.NS' };
    expect(marketStatusReading()).toEqual({ text: 'Market open', color: UP });
    app.req = { symbol: 'AAPL' };
    expect(marketStatusReading()).toEqual({ text: 'Market closed' });
    app.req = { symbol: 'BTC-USD' };
    expect(marketStatusReading()).toEqual({ text: 'Open 24x7', color: UP });
    app.req = { symbol: '^FTSE' };
    expect(marketStatusReading()).toBeUndefined();
  });

  it('finds the close of the previous session in the chart zone', () => {
    // Two Kolkata sessions of hourly bars: 2 and 3 January 2024.
    const day1 = Date.UTC(2024, 0, 2, 4) / 1000;
    const day2 = Date.UTC(2024, 0, 3, 4) / 1000;
    app.currentBars = [flatBar(day1, 100), flatBar(day1 + 3600, 101), flatBar(day2, 102), flatBar(day2 + 3600, 103)];
    expect(previousSessionClose()).toBe(101);
    expect(dayChangeReading()).toEqual({ label: '1D', text: '+2.00 (+1.98%)', color: UP });
  });

  it('colours a fall and has no reading for a single session', () => {
    const day1 = Date.UTC(2024, 0, 2, 4) / 1000;
    const day2 = Date.UTC(2024, 0, 3, 4) / 1000;
    app.currentBars = [flatBar(day1, 100), flatBar(day2, 95)];
    expect(dayChangeReading()).toEqual({ label: '1D', text: '-5.00 (-5.00%)', color: DOWN });

    app.currentBars = [flatBar(day2, 102), flatBar(day2 + 3600, 103)];
    expect(previousSessionClose()).toBeNull();
    expect(dayChangeReading()).toBeUndefined();
  });

  it('memoises on the bar array and the zone, not on their contents', () => {
    const day1 = Date.UTC(2024, 0, 2, 4) / 1000;
    const day2 = Date.UTC(2024, 0, 3, 4) / 1000;
    const bars = [flatBar(day1, 100), flatBar(day2, 102)];
    app.currentBars = bars;
    expect(previousSessionClose()).toBe(100);
    bars[0].close = 50;                       // same array: the memo still answers
    expect(previousSessionClose()).toBe(100);
    app.currentBars = bars.slice();           // a new array is a new answer
    expect(previousSessionClose()).toBe(50);
  });
});
