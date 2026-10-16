/**
 * Trading-session detection, and the indicators that anchor to it.
 *
 * The bug these cover: session boundaries were a fixed IST midnight, which is
 * 18:30 UTC and therefore the middle of a New York session. VWAP restarted in
 * the afternoon and CPR built a "day" out of one session's tail plus the next
 * session's head, spanning the overnight gap.
 */
import { describe, it, expect } from 'vitest';
import { sessionStartIndices, sessionStartFlags, calendarPeriodFlags, isNewIstDay } from '../src/index';
import type { Bar } from '../src/index';
import { VWAP } from '../src/indicators/trend';

const DAY = 86400;

/** UTC seconds for a wall-clock UTC instant. */
const at = (y: number, mo: number, d: number, h: number, mi = 0): number =>
  Math.floor(Date.UTC(y, mo - 1, d, h, mi) / 1000);

/**
 * Five-minute bars for `days` consecutive New York regular sessions
 * (13:30-20:00 UTC), skipping weekends. `range` sets each session's high-low.
 */
function nySessions(days: number, range = 4): Bar[] {
  const bars: Bar[] = [];
  let d = 5; // 2024-03-05 is a Tuesday
  for (let s = 0; s < days; s++) {
    while ([0, 6].includes(new Date(Date.UTC(2024, 2, d)).getUTCDay())) d++;
    const base = 100 + s;
    for (let k = 0; k < 78; k++) {
      const t = at(2024, 3, d, 13, 30) + k * 300;
      // A single peak and trough per session, both inside the session.
      const high = k === 20 ? base + range / 2 : base + 0.1;
      const low = k === 50 ? base - range / 2 : base - 0.1;
      bars.push({ time: t, open: base, high, low, close: base, volume: 1000 });
    }
    d++;
  }
  return bars;
}

/** Daily bars stamped at the NY open, which is what a 1d feed returns. */
function nyDaily(count: number): Bar[] {
  return Array.from({ length: count }, (_, i) => ({
    time: at(2024, 3, 4, 13, 30) + i * DAY,
    open: 100, high: 101, low: 99, close: 100, volume: 1000,
  }));
}

describe('sessionStartIndices', () => {
  it('finds one boundary per overnight gap on intraday bars', () => {
    const bars = nySessions(5);
    const starts = sessionStartIndices(bars.map((b) => b.time));
    expect(starts).toEqual([78, 156, 234, 312]);
  });

  it('puts the boundary at the open, not at an IST midnight inside the session', () => {
    const bars = nySessions(3);
    const starts = sessionStartIndices(bars.map((b) => b.time)) ?? [];
    for (const i of starts) {
      const d = new Date(bars[i].time * 1000);
      expect([d.getUTCHours(), d.getUTCMinutes()]).toEqual([13, 30]);
    }
    // The old rule fired here instead: 18:30 UTC is 00:00 IST.
    const istCuts = bars.filter((b, i) => i > 0 && isNewIstDay(bars[i - 1].time, b.time));
    expect(istCuts.every((b) => new Date(b.time * 1000).getUTCHours() === 18)).toBe(true);
  });

  it('declines to read sessions from daily bars', () => {
    expect(sessionStartIndices(nyDaily(30).map((b) => b.time))).toBeNull();
  });

  it('declines when the feed never closes', () => {
    const times = Array.from({ length: 500 }, (_, i) => at(2024, 3, 4, 0) + i * 3600);
    expect(sessionStartIndices(times)).toBeNull();
  });

  it('declines when the only breaks are weekends, so weeks are not called days', () => {
    // Spot FX: hourly bars, Sunday 22:00 to Friday 22:00, no daily break.
    const times: number[] = [];
    for (let w = 0; w < 6; w++) {
      for (let h = 0; h < 120; h++) times.push(at(2024, 3, 3, 22) + w * 7 * DAY + h * 3600);
    }
    expect(sessionStartIndices(times)).toBeNull();
  });

  it('is not fooled by a lunch break shorter than four hours', () => {
    // Tokyo-style: 00:00-02:30 and 03:30-06:00 UTC, five-minute bars.
    const times: number[] = [];
    for (let d = 0; d < 6; d++) {
      const day = at(2024, 3, 4, 0) + d * DAY;
      for (let k = 0; k < 30; k++) times.push(day + k * 300);
      for (let k = 0; k < 30; k++) times.push(day + 3.5 * 3600 + k * 300);
    }
    const starts = sessionStartIndices(times) ?? [];
    expect(starts.length).toBe(5); // one per overnight gap, none for the lunch break
    for (const i of starts) expect(new Date(times[i] * 1000).getUTCHours()).toBe(0);
  });

  it('falls back to IST days in the flag form when sessions are unreadable', () => {
    const bars = nyDaily(5);
    const flags = sessionStartFlags(bars.map((b) => b.time));
    expect(flags).toEqual([false, true, true, true, true]);
  });
});

describe('calendarPeriodFlags', () => {
  it('tests session opens, so a session never splits across the boundary', () => {
    const bars = nySessions(6);
    const times = bars.map((b) => b.time);
    // A boundary every session: each flagged index must be a session open.
    const flags = calendarPeriodFlags(times, () => true);
    const opens = new Set(sessionStartIndices(times) ?? []);
    flags.forEach((f, i) => { if (f) expect(opens.has(i)).toBe(true); });
    expect(flags.filter(Boolean).length).toBe(opens.size);
  });

  it('runs bar to bar when there are no sessions to test', () => {
    const bars = nyDaily(4);
    const flags = calendarPeriodFlags(bars.map((b) => b.time), () => true);
    expect(flags).toEqual([false, true, true, true]);
  });
});

describe('VWAP session anchor', () => {
  it('restarts at the session open, not at 18:30 UTC', () => {
    const bars = nySessions(4);
    const v = VWAP.calc(bars, { anchor: 'session', source: 'hlc3' }, {});
    const vwap = v.vwap ?? [];
    const opens = new Set(sessionStartIndices(bars.map((b) => b.time)) ?? []);
    // On the bar after a restart the running mean sits on the fresh session's
    // prices; a mid-afternoon restart would land on a bar that is not an open.
    for (let i = 1; i < bars.length; i++) {
      const jumped = Math.abs((vwap[i] as number) - (vwap[i - 1] as number)) > 0.2;
      if (jumped) expect(opens.has(i)).toBe(true);
    }
    expect(opens.size).toBe(3);
  });

  it('holds one accumulation across a whole session', () => {
    const bars = nySessions(2);
    const v = VWAP.calc(bars, { anchor: 'session', source: 'close' }, {});
    // Every close within a session is the same value here, so the running VWAP
    // is flat unless it restarts. Exactly one restart, at bar 78.
    const vwap = (v.vwap ?? []) as (number | null)[];
    expect(vwap[77]).toBeCloseTo(100, 10);
    expect(vwap[78]).toBeCloseTo(101, 10);
  });
});
