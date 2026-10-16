/**
 * Preset ranges sized in trading sessions: a day at one minute on NSE is the
 * 375 bars from the 09:15 open, not the 1,440 minutes back from the clock,
 * and a weekend, a closed date or a clock change is walked across rather
 * than counted.
 */
import { describe, expect, it } from 'vitest';
import { SessionCalendar } from '../src/feed/instrument';
import { registerInterval } from '../src/feed/intervals';
import { zonedWallClockToUtcSeconds } from '../src/feed/time';
import { DEFAULT_RANGES, rangeInterval, rangeWindow, type WidgetRange } from '../src/widget/ranges';

const IST = 'Asia/Kolkata';
const NY = 'America/New_York';
const ist = (y: number, m: number, d: number, hh = 0, mm = 0): number => zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, IST);
const ny = (y: number, m: number, d: number, hh = 0, mm = 0): number => zonedWallClockToUtcSeconds(y, m, d, hh, mm, 0, NY);
const range = (id: string): WidgetRange => DEFAULT_RANGES.find(r => r.id === id)!;
const nse = new SessionCalendar({ timezone: IST, sessions: ['0915-1530:23456'] });

describe('rangeWindow', () => {
  it('sizes one NSE day at one minute from the session open, about 375 bars', () => {
    // Wednesday 1 October 2025, 15:30 IST.
    const end = ist(2025, 10, 1, 15, 30);
    const window = rangeWindow(range('1D'), { end, zone: IST, calendar: nse });
    expect(window).toEqual({ from: ist(2025, 10, 1, 9, 15), to: end });
    expect((window.to - window.from) / 60).toBe(375);
    // An hour into the session a day is 45 minutes, where 1,440 minutes back
    // from the clock would reach into the previous day's session.
    const early = ist(2025, 10, 1, 10, 0);
    expect(rangeWindow(range('1D'), { end: early, zone: IST, calendar: nse }).from).toBe(ist(2025, 10, 1, 9, 15));
    expect(nse.sessionAt(early - 1440 * 60)?.date).toBe('2025-09-30');
  });

  it('counts a day before the open, and over a weekend, as the last session that traded', () => {
    expect(rangeWindow(range('1D'), { end: ist(2025, 10, 1, 8, 0), zone: IST, calendar: nse }).from).toBe(ist(2025, 9, 30, 9, 15));
    // Sunday 5 October: Friday's session.
    expect(rangeWindow(range('1D'), { end: ist(2025, 10, 5, 12, 0), zone: IST, calendar: nse }).from).toBe(ist(2025, 10, 3, 9, 15));
  });

  it('walks five sessions back across a weekend and a closed date', () => {
    const closed = new SessionCalendar({ timezone: IST, sessions: ['0915-1530:23456'], exceptions: { '2025-10-02': [] } });
    // Tuesday 7 October: Tue, Mon, Fri, Wed, Tue (Thursday the 2nd is closed).
    const end = ist(2025, 10, 7, 12, 0);
    expect(rangeWindow(range('5D'), { end, zone: IST, calendar: closed }).from).toBe(ist(2025, 9, 30, 9, 15));
    expect(rangeWindow(range('5D'), { end, zone: IST, calendar: nse }).from).toBe(ist(2025, 10, 1, 9, 15));
  });

  it('counts a date with a midday break once, from its morning window', () => {
    const split = new SessionCalendar({ timezone: IST, sessions: ['0900-1130:23456', '1300-1500:23456'] });
    const end = ist(2025, 10, 1, 14, 0);
    expect(rangeWindow(range('1D'), { end, zone: IST, calendar: split }).from).toBe(ist(2025, 10, 1, 9, 0));
    expect(rangeWindow({ ...range('5D'), count: 2 }, { end, zone: IST, calendar: split }).from).toBe(ist(2025, 9, 30, 9, 0));
  });

  it('starts a day at its pre-open when the calendar trades one', () => {
    const us = new SessionCalendar({ timezone: NY, sessions: ['0930-1600:23456'], preMarketMinutes: 330 });
    // 10 March 2025 is the Monday after the clock change: the walk stays on New York's wall clock.
    expect(rangeWindow(range('1D'), { end: ny(2025, 3, 10, 12, 0), zone: NY, calendar: us }).from).toBe(ny(2025, 3, 10, 4, 0));
    expect(rangeWindow(range('5D'), { end: ny(2025, 3, 10, 12, 0), zone: NY, calendar: us }).from).toBe(ny(2025, 3, 4, 4, 0));
  });

  it('counts the dates of the loaded bars without a calendar', () => {
    const bars = [
      { time: ist(2025, 9, 29, 15, 29) },
      { time: ist(2025, 9, 30, 9, 15) }, { time: ist(2025, 9, 30, 15, 29) },
      { time: ist(2025, 10, 1, 9, 15) }, { time: ist(2025, 10, 1, 10, 0) },
    ];
    const end = bars[bars.length - 1].time;
    expect(rangeWindow(range('1D'), { end, zone: IST, bars }).from).toBe(ist(2025, 10, 1, 9, 15));
    expect(rangeWindow({ ...range('5D'), count: 2 }, { end, zone: IST, bars }).from).toBe(ist(2025, 9, 30, 9, 15));
  });

  it('reaches back over weekdays for a fetch without a calendar or bars', () => {
    // Monday before the open: Friday's midnight, so Friday's session is fetched.
    expect(rangeWindow(range('1D'), { end: ist(2025, 10, 6, 8, 0), zone: IST }).from).toBe(ist(2025, 10, 3));
    expect(rangeWindow(range('5D'), { end: ist(2025, 10, 6, 8, 0), zone: IST }).from).toBe(ist(2025, 9, 29));
  });

  it('counts months, years and the year to date on the zone\'s calendar', () => {
    const end = ist(2025, 3, 31, 12, 0);
    expect(rangeWindow(range('1M'), { end, zone: IST }).from).toBe(ist(2025, 2, 28));
    expect(rangeWindow(range('3M'), { end, zone: IST }).from).toBe(ist(2024, 12, 31));
    expect(rangeWindow(range('6M'), { end, zone: IST }).from).toBe(ist(2024, 9, 30));
    expect(rangeWindow(range('YTD'), { end, zone: IST }).from).toBe(ist(2025, 1, 1));
    expect(rangeWindow(range('1Y'), { end: ist(2024, 2, 29, 12), zone: IST }).from).toBe(ist(2023, 2, 28));
    expect(rangeWindow(range('5Y'), { end, zone: IST }).from).toBe(ist(2020, 3, 31));
  });

  it('runs all history from the first bar, or thirty years back before any load', () => {
    const end = ist(2025, 3, 31, 12, 0);
    expect(rangeWindow(range('ALL'), { end, zone: IST, bars: [{ time: 1000 }, { time: end }] }).from).toBe(1000);
    expect(rangeWindow(range('ALL'), { end, zone: IST }).from).toBe(ist(1995, 3, 31));
  });

  it('falls back to dates when the calendar cannot answer', () => {
    const broken = { sessionFrom: (): never => { throw new Error('gap'); } };
    const bars = [{ time: ist(2025, 10, 1, 9, 15) }, { time: ist(2025, 10, 1, 10, 0) }];
    expect(rangeWindow(range('1D'), { end: bars[1].time, zone: IST, calendar: broken, bars }).from).toBe(bars[0].time);
  });
});

describe('rangeInterval', () => {
  it('uses the range\'s own interval when offered, else the nearest by ratio', () => {
    expect(rangeInterval(range('1D'), ['1m', '5m', '1d'])).toBe('1m');
    expect(rangeInterval(range('1D'), ['5m', '15m', '1d'])).toBe('5m');
    // 30 minutes sits between 15 and 60 by ratio; the longer loads fewer bars.
    expect(rangeInterval(range('1M'), ['1m', '5m', '15m', '1h', '1d', '1w'])).toBe('1h');
    expect(rangeInterval(range('5Y'), ['5m', '1d'])).toBe('1d');
  });

  it('weighs a calendar month by its length and skips tick bars', () => {
    const offMonth = registerInterval({ code: 'MO', bucketing: { mode: 'calendar', unit: 'month' } });
    const offTicks = registerInterval({ code: 'T100', bucketing: { mode: 'ticks', count: 100 } });
    try {
      expect(rangeInterval({ id: 'x', label: 'x', interval: 'MO', unit: 'all' }, ['1d', '1w', 'MO'])).toBe('MO');
      expect(rangeInterval({ id: 'x', label: 'x', interval: '4w', unit: 'all' }, ['1d', 'MO', 'T100'])).toBe('MO');
      expect(rangeInterval(range('1D'), ['T100'])).toBe('1m');
    } finally { offMonth(); offTicks(); }
  });
});
