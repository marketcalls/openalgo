import { describe, it, expect } from 'vitest';
import { computeMarketProfile, tpoLetter, rowTicksFor, nakedLevels, TRADING_HOURS } from '../src/profile/market-profile';
import { istStringToUtcSeconds } from '../src/feed/time';
import type { Bar } from '../src/model/bar';

const bar = (time: number, low: number, high: number, volume = 100): Bar => ({
  time, open: low, high, low, close: high, volume,
});

describe('TPO letters', () => {
  it('maps period index to A-Z then a-z and wraps', () => {
    expect(tpoLetter(0)).toBe('A');
    expect(tpoLetter(25)).toBe('Z');
    expect(tpoLetter(26)).toBe('a');
    expect(tpoLetter(51)).toBe('z');
    expect(tpoLetter(52)).toBe('A');
  });
});

describe('computeMarketProfile', () => {
  // Two 30-minute periods in one IST day, tick = 1.
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');
  const bars = [
    bar(t0, 100, 110),          // period 0 (A): 100..110
    bar(t0 + 1800, 105, 110),   // period 1 (B): 105..110
  ];

  it('builds one day session with letters, POC, IB and value area', () => {
    const { sessions } = computeMarketProfile(bars, { tickSize: 1, session: 'day', blockMinutes: 30, initialBalancePeriods: 2 });
    expect(sessions).toHaveLength(1);
    const s = sessions[0];
    expect(s.periods).toBe(2);
    // Top level 110 was touched by both periods -> "AB".
    expect(s.levels[0].price).toBe(110);
    expect(s.levels[0].letters).toBe('AB');
    // Initial balance spans both periods' range.
    expect(s.initialBalance).toEqual({ high: 110, low: 100 });
    // VAH >= POC >= VAL by price.
    expect(s.vah).toBeGreaterThanOrEqual(s.poc);
    expect(s.poc).toBeGreaterThanOrEqual(s.val);
  });

  it('flags poor highs and single prints', () => {
    const { sessions } = computeMarketProfile(bars, { tickSize: 1, session: 'day', blockMinutes: 30 });
    const s = sessions[0];
    // 110 printed two TPOs -> weak (poor) high; 100 printed one -> not a poor low.
    expect(s.poorHigh).toBe(true);
    expect(s.poorLow).toBe(false);
    // 101..104 are lone TPOs away from the extremes.
    expect(s.singlePrints).toContain(102);
    expect(s.singlePrints).not.toContain(100); // bottom extreme excluded
  });

  it('segments sessions by IST day', () => {
    const day2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    const multi = [...bars, bar(day2, 120, 125), bar(day2 + 1800, 121, 126)];
    const { sessions } = computeMarketProfile(multi, { tickSize: 1, session: 'day', blockMinutes: 30 });
    expect(sessions).toHaveLength(2);
    expect(sessions[1].levels[0].price).toBe(126);
  });

  it('composite mode builds a single profile over all bars', () => {
    const day2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    const multi = [...bars, bar(day2, 120, 125)];
    const { sessions } = computeMarketProfile(multi, { tickSize: 1, session: 'composite', blockMinutes: 30 });
    expect(sessions).toHaveLength(1);
  });

  it('distributes volume across the price range', () => {
    const { sessions } = computeMarketProfile([bar(t0, 100, 104, 500)], { tickSize: 1, session: 'day' });
    const s = sessions[0];
    const totalVol = s.levels.reduce((sum, l) => sum + l.volume, 0);
    expect(Math.round(totalVol)).toBe(500);
    expect(s.totalVolume).toBe(500);
  });
});

describe('TPO row size', () => {
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');

  it('rowTicks widens rows without changing the instrument tick', () => {
    // Nifty-style: 0.1 tick, 2-point TPO rows -> rowTicks 20.
    const bars = [bar(t0, 24000, 24010), bar(t0 + 1800, 24000, 24010)];
    const fine = computeMarketProfile(bars, { tickSize: 0.1, rowTicks: 1, blockMinutes: 30 });
    const coarse = computeMarketProfile(bars, { tickSize: 0.1, rowTicks: 20, blockMinutes: 30 });
    // 10 points at 0.1 is ~101 rows; at 2-point rows it is ~6.
    expect(fine.sessions[0].levels.length).toBeGreaterThan(90);
    expect(coarse.sessions[0].levels.length).toBeLessThan(10);
    // The row grid really is 2 points apart.
    const ls = coarse.sessions[0].levels;
    expect(Math.abs((ls[0].price - ls[1].price) - 2)).toBeLessThan(1e-6);
    // tickSize is reported unchanged: rowTicks is a display multiplier.
    expect(coarse.options.tickSize).toBe(0.1);
    expect(coarse.options.rowTicks).toBe(20);
  });

  it('rowTicksFor converts a row size to the multiplier', () => {
    expect(rowTicksFor(2, 0.1)).toBe(20);
    expect(rowTicksFor(0.25, 0.05)).toBe(5);
    expect(rowTicksFor(0, 0.1)).toBe(1);   // degenerate input floors at 1
  });
});

describe('market profile analytics', () => {
  const t0 = istStringToUtcSeconds('2024-01-15 09:15:00');

  it('records per-period detail and a developing POC track', () => {
    const bars = [
      bar(t0, 100, 104), bar(t0 + 1800, 102, 106), bar(t0 + 3600, 101, 105),
    ];
    const s = computeMarketProfile(bars, { tickSize: 1, blockMinutes: 30 }).sessions[0];
    expect(s.periodDetail.map((p) => p.letter)).toEqual(['A', 'B', 'C']);
    expect(s.periodDetail[1]).toMatchObject({ high: 106, low: 102 });
    // One developing snapshot per period, in order.
    expect(s.developing).toHaveLength(3);
    expect(s.developing.map((d) => d.periodIndex)).toEqual([0, 1, 2]);
  });

  it('reports range extension beyond the initial balance', () => {
    const bars = [
      bar(t0, 100, 105),            // IB (single period)
      bar(t0 + 1800, 104, 112),     // extends up past 105
    ];
    const s = computeMarketProfile(bars, { tickSize: 1, blockMinutes: 30, initialBalancePeriods: 1 }).sessions[0];
    expect(s.initialBalance).toEqual({ high: 105, low: 100 });
    expect(s.rangeExtension.up).toBe(7);
    expect(s.rangeExtension.down).toBe(0);
  });

  it('filters bars to a session window and anchors letters to its open', () => {
    const bars = [
      bar(istStringToUtcSeconds('2024-01-15 08:00:00'), 100, 101), // before the open
      bar(istStringToUtcSeconds('2024-01-15 09:15:00'), 100, 102),
      bar(istStringToUtcSeconds('2024-01-15 09:45:00'), 101, 103),
    ];
    const s = computeMarketProfile(bars, {
      tickSize: 1, blockMinutes: 30, window: TRADING_HOURS['india'],
    }).sessions[0];
    // The 08:00 bar is outside the window and must not become period A.
    expect(s.startTime).toBe(istStringToUtcSeconds('2024-01-15 09:15:00'));
    expect(s.periodDetail.map((p) => p.letter)).toEqual(['A', 'B']);
    expect(s.label).toBe('India');
  });

  it('merges sessions when compositeSessions > 1', () => {
    const d1 = istStringToUtcSeconds('2024-01-15 09:15:00');
    const d2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    const bars = [bar(d1, 100, 102), bar(d2, 103, 105)];
    const split = computeMarketProfile(bars, { tickSize: 1, session: 'day' });
    const merged = computeMarketProfile(bars, { tickSize: 1, session: 'day', compositeSessions: 2 });
    expect(split.sessions).toHaveLength(2);
    expect(merged.sessions).toHaveLength(1);
    expect(merged.sessions[0].high).toBe(105);
    expect(merged.sessions[0].low).toBe(100);
  });

  it('promotes a run of single prints to a tail', () => {
    // One lone period at the top, a fat body below.
    const bars = [
      bar(t0, 100, 110),
      bar(t0 + 1800, 100, 104), bar(t0 + 3600, 100, 104), bar(t0 + 5400, 100, 104),
    ];
    const s = computeMarketProfile(bars, { tickSize: 1, blockMinutes: 30, tailEdges: 3 }).sessions[0];
    expect(s.sellingTail).not.toBeNull();
    expect(s.sellingTail?.high).toBe(110);
  });

  it('nakedLevels keeps only levels no later session traded through', () => {
    const d1 = istStringToUtcSeconds('2024-01-15 09:15:00');
    const d2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    // Day 2 trades far above day 1, so day 1's levels are never revisited.
    const bars = [bar(d1, 100, 102), bar(d2, 200, 202)];
    const res = computeMarketProfile(bars, { tickSize: 1, session: 'day' });
    const naked = nakedLevels(res);
    // Day 1's levels survive because day 2 never traded back down to them, and
    // day 2's are naked by definition: nothing came after them yet.
    expect(naked.some((n) => n.time === d1)).toBe(true);
    expect(naked.some((n) => n.time === d2)).toBe(true);
    expect(naked.some((n) => n.kind === 'poc')).toBe(true);
  });

  it('nakedLevels drops a level a later session traded back through', () => {
    const d1 = istStringToUtcSeconds('2024-01-15 09:15:00');
    const d2 = istStringToUtcSeconds('2024-01-16 09:15:00');
    // Day 2 fully covers day 1's range, so none of day 1's levels stay naked.
    const bars = [bar(d1, 100, 102), bar(d2, 90, 120)];
    const naked = nakedLevels(computeMarketProfile(bars, { tickSize: 1, session: 'day' }));
    expect(naked.some((n) => n.time === d1)).toBe(false);
  });
});
