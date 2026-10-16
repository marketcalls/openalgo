/**
 * `securitySeries` (2.4.0): the one fold from the chart's bars to a higher
 * timeframe, with its three readings pinned bar by bar. The fixture is two
 * days of 5-minute bars from a 09:15 IST open, so a session-anchored bucket
 * and an epoch-anchored one land on different bars and the test can tell
 * them apart.
 */
import { describe, it, expect } from 'vitest';
import { securitySeries } from '../src/indicators/security';
import { registerInterval, unregisterInterval } from '../src/feed/intervals';
import { IndicatorInputError } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

// Monday 14 September 2026, 09:15 IST is 03:45 UTC.
const OPEN = Date.UTC(2026, 8, 14, 3, 45) / 1000;

/** Eight 5-minute bars per day from the open, `days` days running. */
function session(days: number, first = OPEN): Bar[] {
  const out: Bar[] = [];
  for (let d = 0; d < days; d++) {
    for (let k = 0; k < 8; k++) {
      const open = 100 + k + d * 10;
      out.push({ time: first + d * 86400 + k * 300, open, high: open + 2, low: open - 1, close: open + 1, volume: 10 });
    }
  }
  return out;
}

const news = (flags: boolean[]): number[] => flags.flatMap((f, i) => (f ? [i] : []));

describe('securitySeries', () => {
  it('reads the bucket as it stood at each bar by default', () => {
    const s = securitySeries(session(1), '1d');
    // Bar 3 (09:30): open of the day, high and low so far, its own close, volume so far.
    expect(s.open[3]).toBe(100);
    expect(s.high[3]).toBe(105);
    expect(s.low[3]).toBe(99);
    expect(s.close[3]).toBe(104);
    expect(s.volume[3]).toBe(40);
    expect(s.bucketStart[3]).toBe(OPEN);
    expect(news(s.isNew)).toEqual([0]);
  });

  it('holds the previous completed bucket constant with offset 1, and is null before one exists', () => {
    const s = securitySeries(session(2), '1d', { offset: 1 });
    for (let i = 0; i < 8; i++) expect(s.close[i]).toBeNull();
    for (let i = 8; i < 16; i++) {
      expect(s.open[i]).toBe(100);
      expect(s.high[i]).toBe(109);
      expect(s.low[i]).toBe(99);
      expect(s.close[i]).toBe(108);
      expect(s.volume[i]).toBe(80);
      expect(s.bucketStart[i]).toBe(OPEN);
    }
    expect(news(s.isNew)).toEqual([0, 8]);
  });

  it('reads the final values on every bar with lookahead, which is the repainting reading', () => {
    const s = securitySeries(session(1), '1d', { lookahead: true });
    expect(s.high[0]).toBe(109);
    expect(s.close[0]).toBe(108);
    expect(s.volume[0]).toBe(80);
    expect(s.close[7]).toBe(108);
  });

  it('anchors a sub-day bucket to the session open when a session is given, and to the epoch otherwise', () => {
    const bars = session(2);
    // 09:15 to 09:45 then 09:45 to 10:15 on each day.
    const anchored = securitySeries(bars, '30m', { session: '0915-1530' });
    expect(news(anchored.isNew)).toEqual([0, 6, 8, 14]);
    expect(anchored.high[5]).toBe(107);
    expect(anchored.volume[5]).toBe(60);
    // 03:30 to 04:00 UTC holds 09:15, 09:20 and 09:25; the next bucket the rest.
    const epoch = securitySeries(bars, '30m');
    expect(news(epoch.isNew)).toEqual([0, 3, 8, 11]);
    expect(epoch.high[2]).toBe(104);
    expect(epoch.volume[2]).toBe(30);
  });

  it('cuts a week on Monday in the chart zone', () => {
    // Monday and Tuesday fall in one week.
    const s = securitySeries(session(2), '1w');
    expect(news(s.isNew)).toEqual([0]);
    expect(s.close[15]).toBe(118);
  });

  it('cuts a registered calendar interval on the calendar', () => {
    const off = registerInterval({ code: '1MN', bucketing: { mode: 'calendar', unit: 'month' } });
    try {
      // Wednesday 30 September 2026 and Thursday 1 October.
      const s = securitySeries(session(2, Date.UTC(2026, 8, 30, 3, 45) / 1000), '1MN');
      expect(news(s.isNew)).toEqual([0, 8]);
    } finally {
      off();
    }
  });

  it('refuses an interval that closes on trade flow', () => {
    const off = registerInterval({ code: 'T5', bucketing: { mode: 'ticks', count: 5 } });
    try {
      expect(() => securitySeries(session(1), 'T5')).toThrow(IndicatorInputError);
    } finally {
      off();
      unregisterInterval('T5');
    }
  });

  it('refuses a negative offset and an unreadable session', () => {
    expect(() => securitySeries(session(1), '1d', { offset: -1 })).toThrow(IndicatorInputError);
    expect(() => securitySeries(session(1), '30m', { session: 'nine to five' })).toThrow(IndicatorInputError);
  });

  it('leaves volume null on a bucket whose bars carry none', () => {
    const bars = session(1).map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close }));
    const s = securitySeries(bars, '1d');
    expect(s.volume.every((v) => v === null)).toBe(true);
    expect(s.close[7]).toBe(108);
  });

  it('returns empty columns for no bars', () => {
    const s = securitySeries([], '1d');
    expect(s.close).toEqual([]);
    expect(s.isNew).toEqual([]);
  });
});
