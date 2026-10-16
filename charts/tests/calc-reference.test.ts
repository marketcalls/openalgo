import { describe, it, expect } from 'vitest';
import {
  sma, smaSeededEma, change, roc, dev, percentRank, alma, vwma,
  highestBars, lowestBars, rollingSum, cumulative, linreg, percentileNearestRank, valueWhen,
} from '../src/indicators/calc';
import { ema } from '../src/indicators/ema';

/**
 * These built-in indicators are ports of well-known published formulas, and
 * the parity that matters is not just the formula but *where the warmup ends*.
 * These tests pin the conventions the indicator descriptors are built on.
 */
describe('the reference-compatible calc helpers', () => {
  describe('smaSeededEma', () => {
    it('seeds from the SMA of the first period values, unlike the base ema', () => {
      const v = [1, 2, 3, 4, 5, 6];
      const out = smaSeededEma(v, 3);
      expect(out.slice(0, 2).every(Number.isNaN)).toBe(true);
      expect(out[2]).toBe(2); // (1+2+3)/3
      const k = 2 / 4;
      expect(out[3]).toBeCloseTo(4 * k + 2 * (1 - k), 12);
    });

    it('differs from the base ema during warmup and converges after', () => {
      const v = Array.from({ length: 200 }, (_, i) => 100 + Math.sin(i / 7) * 5);
      const reference = smaSeededEma(v, 20);
      const base = ema(v, 20);
      // The base ema answers from bar 0; the reference one is still NaN there.
      expect(Number.isNaN(reference[0])).toBe(true);
      expect(Number.isFinite(base[0])).toBe(true);
      // Far from the seed the two are indistinguishable.
      expect(reference[199]).toBeCloseTo(base[199], 6);
    });

    it('returns all NaN when there is less data than the period', () => {
      expect(smaSeededEma([1, 2], 5).every(Number.isNaN)).toBe(true);
    });
  });

  describe('change and roc', () => {
    it('change is src - src[n] with an n-bar warmup', () => {
      const out = change([5, 7, 10], 1);
      expect(Number.isNaN(out[0])).toBe(true);
      expect(out.slice(1)).toEqual([2, 3]);
      expect(change([5, 7, 10], 2)[2]).toBe(5);
    });

    it('roc is a percentage of the value n bars back', () => {
      expect(roc([10, 11], 1)[1]).toBeCloseTo(10, 12);
      expect(roc([10, 5], 1)[1]).toBeCloseTo(-50, 12);
    });

    it('roc refuses to divide by a zero base rather than emitting Infinity', () => {
      expect(Number.isNaN(roc([0, 5], 1)[1])).toBe(true);
    });
  });

  describe('dev', () => {
    it('is the mean absolute deviation, not a standard deviation', () => {
      // values 1,2,6 -> mean 3; |1-3|+|2-3|+|6-3| = 6; 6/3 = 2
      expect(dev([1, 2, 6], 3)[2]).toBeCloseTo(2, 12);
    });

    it('is zero on a flat window', () => {
      expect(dev([4, 4, 4, 4], 3)[3]).toBe(0);
    });
  });

  describe('percentRank', () => {
    it('ranks the current value against the previous period values', () => {
      // At index 3 the previous 3 values are 1,2,3 and all are <= 4 -> 100.
      expect(percentRank([1, 2, 3, 4], 3)[3]).toBe(100);
      // At index 3 the previous 3 are 4,5,6, none <= 1 -> 0.
      expect(percentRank([9, 4, 5, 6, 1], 3)[4]).toBe(0);
    });

    it('counts ties as satisfying the comparison', () => {
      expect(percentRank([2, 2, 2], 2)[2]).toBe(100);
    });

    it('warms up one bar later than a plain window, since the current bar is the subject', () => {
      const out = percentRank([1, 2, 3, 4], 3);
      expect(out.slice(0, 3).every(Number.isNaN)).toBe(true);
      expect(Number.isFinite(out[3])).toBe(true);
    });
  });

  describe('alma', () => {
    it('matches a hand-built Gaussian weighting', () => {
      const v = [1, 2, 3, 4, 5];
      const period = 3;
      const offset = 0.85;
      const sigma = 6;
      const m = offset * (period - 1);
      const s = period / sigma;
      let num = 0;
      let den = 0;
      for (let i = 0; i < period; i++) {
        const w = Math.exp(-((i - m) * (i - m)) / (2 * s * s));
        den += w;
        num += v[4 - (period - 1 - i)] * w;
      }
      expect(alma(v, period, offset, sigma)[4]).toBeCloseTo(num / den, 12);
    });

    it('reproduces a constant series exactly, whatever the weights', () => {
      expect(alma([7, 7, 7, 7, 7], 4, 0.85, 6)[4]).toBeCloseTo(7, 12);
    });
  });

  describe('vwma', () => {
    it('collapses to a plain SMA when every bar carries the same volume', () => {
      const v = [1, 2, 3, 4, 5];
      const vol = [10, 10, 10, 10, 10];
      expect(vwma(v, vol, 3)[4]).toBeCloseTo(sma(v, 3)[4], 12);
    });

    it('leans towards the heavier bar', () => {
      const out = vwma([10, 20], [1, 99], 2)[1];
      expect(out).toBeGreaterThan(19);
    });
  });

  describe('highestBars and lowestBars', () => {
    it('return 0 when the current bar is the extreme', () => {
      expect(highestBars([1, 2, 3], 3)[2]).toBe(0);
      expect(lowestBars([3, 2, 1], 3)[2]).toBe(0);
    });

    it('return a negative offset back to the extreme', () => {
      // The oldest bar of the 3-bar window is the highest.
      expect(highestBars([9, 2, 3], 3)[2]).toBe(-2);
      expect(lowestBars([0, 2, 3], 3)[2]).toBe(-2);
    });

    it('resolve ties to the most recent bar', () => {
      expect(highestBars([5, 5, 5], 3)[2]).toBe(0);
    });

    it('give Aroon its 100 at a new high', () => {
      const length = 3;
      const high = [1, 2, 3, 4];
      const up = 100 * (highestBars(high, length + 1)[3] + length) / length;
      expect(up).toBe(100);
    });
  });

  describe('rollingSum and cumulative', () => {
    it('rollingSum totals the trailing window', () => {
      const out = rollingSum([1, 2, 3, 4], 2);
      expect(Number.isNaN(out[0])).toBe(true);
      expect(out.slice(1)).toEqual([3, 5, 7]);
    });

    it('cumulative is a running total from the first bar', () => {
      expect(cumulative([1, 2, 3])).toEqual([1, 3, 6]);
    });

    it('cumulative treats a non-finite term as zero rather than poisoning the total', () => {
      expect(cumulative([1, NaN, 2])).toEqual([1, 1, 3]);
    });
  });

  describe('linreg', () => {
    it('reproduces a perfectly linear series exactly', () => {
      // A least-squares fit of a straight line is that line, so the regression
      // value at the current bar is the current value.
      const v = Array.from({ length: 20 }, (_, i) => 3 * i + 5);
      const out = linreg(v, 10);
      for (let i = 9; i < 20; i++) expect(out[i]).toBeCloseTo(v[i], 9);
    });

    it('is flat and equal to the level on a constant series', () => {
      expect(linreg([4, 4, 4, 4, 4], 4)[4]).toBeCloseTo(4, 12);
    });

    it('offset steps back along the fitted line', () => {
      const v = Array.from({ length: 20 }, (_, i) => 3 * i + 5);
      // One bar back on a slope-3 line is 3 lower.
      expect(linreg(v, 10, 1)[19]).toBeCloseTo(linreg(v, 10, 0)[19] - 3, 9);
    });

    it('warms up until a full window exists', () => {
      const out = linreg([1, 2, 3, 4, 5], 4);
      expect(out.slice(0, 3).every(Number.isNaN)).toBe(true);
      expect(Number.isFinite(out[3])).toBe(true);
    });
  });

  // Out-of-range arguments give warmup-style NaN slots, never an undefined in a
  // number[] and never a throw from inside the kernel.
  describe('arguments outside their range', () => {
    const closes = [101.2, 100.8, 102.4, 103.1, 102.9, 104.6, 103.8];
    const allNumbers = (out: readonly number[]): boolean => out.every((v) => typeof v === 'number');

    it('percentileNearestRank above 100 or NaN reads NaN', () => {
      for (const percentage of [150, NaN]) {
        const out = percentileNearestRank(closes, 3, percentage);
        expect(out).toHaveLength(closes.length);
        expect(allNumbers(out)).toBe(true);
        expect(out.every(Number.isNaN)).toBe(true);
      }
      // Below 0 still ranks the window's lowest, as it always has.
      expect(percentileNearestRank(closes, 3, -20)[2]).toBe(100.8);
    });

    it('valueWhen with a fractional or negative occurrence, or a shorter source, reads NaN', () => {
      const cond = closes.map((c, i) => i > 0 && c > closes[i - 1]!);
      for (const occurrence of [0.5, -1]) {
        const out = valueWhen(cond, closes, occurrence);
        expect(allNumbers(out)).toBe(true);
        expect(out.every(Number.isNaN)).toBe(true);
      }
      const short = valueWhen(cond, closes.slice(0, 4), 0);
      expect(allNumbers(short)).toBe(true);
      expect(short[5]).toBeNaN();
      expect(short[3]).toBe(103.1);
    });

    it('alma with a fractional or non-finite period reads NaN instead of throwing', () => {
      for (const period of [2.5, NaN, Infinity]) {
        const out = alma(closes, period, 0.85, 6);
        expect(out).toHaveLength(closes.length);
        expect(out.every(Number.isNaN)).toBe(true);
      }
    });
  });
});
