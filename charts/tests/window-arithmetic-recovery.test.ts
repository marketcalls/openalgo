import { describe, expect, it } from 'vitest';
import { rollingSum, sma } from '../src/indicators/calc';

describe('chronological default scalar windows', () => {
  it.each([sma, rollingSum])('keeps singleton windows independent of expired magnitudes', (run) => {
    expect(run([1e16, 3, 1, 1, 1e308, 1e308, 2], 1)).toEqual([1e16, 3, 1, 1, 1e308, 1e308, 2]);
    expect(run([-0, NaN, Infinity, -Infinity, 4], 1)).toEqual([0, NaN, NaN, NaN, 4]);
  });

  it('does not retain rounded contributions after they leave a sum', () => {
    expect(rollingSum([1e16, 1, 1, 1], 2)).toEqual([NaN, 1e16, 2, 2]);
    expect(sma([1e16, 1, 1, 1], 2)).toEqual([NaN, 5e15, 1, 1]);
  });

  it('normalizes an overflowing named sum before division and recovers', () => {
    expect(rollingSum([1e308, 1e308, 1, 2], 2)).toEqual([NaN, NaN, 1e308, 3]);
    expect(sma([1e308, 1e308, 1, 2], 2)).toEqual([NaN, NaN, 5e307, 1.5]);
    expect(sma([1e308, 1e308, -1e308], 3)).toEqual([NaN, NaN, NaN]);
  });

  it.each([NaN, Infinity, -Infinity])('lets unavailable observation %s expire from both windows', (missing) => {
    const values = [missing, 1, 2, missing, 3, 4, 5];
    expect(rollingSum(values, 2)).toEqual([NaN, NaN, 3, NaN, NaN, 7, 9]);
    expect(sma(values, 2)).toEqual([NaN, NaN, 1.5, NaN, NaN, 3.5, 4.5]);
  });

  it('uses oldest-first binary64 additions, followed by a single division', () => {
    expect(rollingSum([1e16, 1, -1e16], 3)).toEqual([NaN, NaN, 0]);
    expect(rollingSum([1e16, -1e16, 1], 3)).toEqual([NaN, NaN, 1]);
    expect(sma([1e16, -1e16, 1], 3)).toEqual([NaN, NaN, 1 / 3]);
  });

  it('retains the separate compensated opt-in and varying-window contracts', () => {
    const values = [1e16, 1, -1e16];
    expect(sma(values, 3)).toEqual([NaN, NaN, 0]);
    expect(sma(values, 3, {})).toEqual([NaN, NaN, 1 / 3]);
    expect(sma(values, [3, 3, 3])).toEqual([NaN, NaN, 1 / 3]);
    expect(sma([1, NaN, 3, 5], 2, { missing: 'skip' })).toEqual([NaN, NaN, 2, 4]);
  });

  it('preserves unsupported scalar-period behavior and ordinary warmup', () => {
    expect(sma([1, 2, 3], 1.5)).toEqual([NaN, 2, NaN]);
    expect(rollingSum([1, 2, 3, 4], 2.5)).toEqual([NaN, NaN, 6, NaN]);
    for (const run of [sma, rollingSum]) {
      for (const period of [0, -1, NaN, Infinity, 5]) expect(run([1, 2, 3], period)).toEqual([NaN, NaN, NaN]);
      expect(run([], 2)).toEqual([]);
    }
  });

  it.each([sma, rollingSum])('recomputes prefixes and revised final observations without retaining state', (run) => {
    const values = Object.freeze([1e16, 3, 1, 1, NaN, 5, 7]);
    const before = run(values, 2);
    for (let end = 0; end <= values.length; end++) expect(run(values.slice(0, end), 2)).toEqual(before.slice(0, end));
    expect(run([1e16, 3, 1, 9], 2)[3]).toBe(run([1, 9], 2)[1]);
    expect(run(values, 2)).toEqual(before);
    expect(run(values.slice(5), 2)[1]).toBe(before[6]);
  });
});
