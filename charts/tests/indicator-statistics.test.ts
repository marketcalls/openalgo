import { describe, expect, it } from 'vitest';
import {
  rollingMedian, rollingMode, rollingVariance, rollingRange, percentileLinear,
  rankCorrelation, centerOfGravity, runningMin, runningMax,
  crossesAbove, crossesBelow, crosses, rising, falling, sma,
} from '../src/indicators/index';
import type { NumericalWindowOptions } from '../src/indicators/index';

const skip: NumericalWindowOptions = { missing: 'skip' };

function expectNumbers(actual: readonly number[], expected: readonly number[]): void {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, index) => {
    if (Number.isNaN(value)) expect(actual[index], `index ${index}`).toBeNaN();
    else expect(actual[index], `index ${index}`).toBeCloseTo(value, 10);
  });
}

describe('rolling numerical statistics', () => {
  it('averages the two middle values for even medians', () => {
    expectNumbers(rollingMedian([4, 1, 3, 2], 4), [NaN, NaN, NaN, 2.5]);
    expectNumbers(rollingMedian([9, 1, 4, 8], 3), [NaN, NaN, 4, 4]);
  });

  it('chooses the smallest mode among equally frequent values', () => {
    expectNumbers(rollingMode([4, 2, 4, 2, 9], 4), [NaN, NaN, NaN, 2, 2]);
    expectNumbers(rollingMode([9, 3, 6], 3), [NaN, NaN, 3]);
    expectNumbers(rollingMode([-1, -2, -1, -2], 4), [NaN, NaN, NaN, -2]);
  });

  it('separates population and sample variance', () => {
    expectNumbers(rollingVariance([1, 2, 3, 4], 3), [NaN, NaN, 2 / 3, 2 / 3]);
    expectNumbers(rollingVariance([1, 2, 3, 4], 3, { sample: true }), [NaN, NaN, 1, 1]);
    expectNumbers(rollingVariance([8, 9], 1), [0, 0]);
    expectNumbers(rollingVariance([8, 9], 1, { sample: true }), [NaN, NaN]);
  });

  it('retains small variance in data with a large common offset', () => {
    expectNumbers(rollingVariance([1e12 + 1, 1e12 + 2, 1e12 + 3], 3), [NaN, NaN, 2 / 3]);
  });

  it.each([
    [1e154, -1e154, 0], [1e154, 0, -1e154],
    [-1e154, 1e154, 0], [-1e154, 0, 1e154],
    [0, 1e154, -1e154], [0, -1e154, 1e154],
  ])('keeps representable variance finite for [%s, %s, %s]', (...values) => {
    expect(rollingVariance(values, 3)[2] / 1e308).toBeCloseTo(2 / 3, 14);
    expect(rollingVariance(values, 3, { sample: true })[2] / 1e308).toBeCloseTo(1, 14);
  });

  it('divides before squaring when a single unnormalized square would overflow', () => {
    expect(rollingVariance([1.5e154, -1.5e154, 0], 3)[2] / 1e308).toBeCloseTo(1.5, 14);
    expect(rollingVariance([1.5e154, -1.5e154, 0], 3, { sample: true })[2]).toBe(Infinity);
  });

  it('returns positive overflow for extreme spreads while retaining zero for large constants', () => {
    for (const values of [[1e308, -1e308], [-1e308, 1e308], [1e308, 1e308, -1e308]]) {
      expect(rollingVariance(values, values.length)[values.length - 1]).toBe(Infinity);
      expect(rollingVariance(values, values.length, { sample: true })[values.length - 1]).toBe(Infinity);
    }
    expectNumbers(rollingVariance([1e308, 1e308], 2), [NaN, 0]);
  });

  it('returns the distance between the largest and smallest values', () => {
    expectNumbers(rollingRange([3, -2, 5, 4], 3), [NaN, NaN, 7, 7]);
    expectNumbers(rollingRange([5, 5], 2), [NaN, 0]);
  });

  it('interpolates using percentage times n minus one as the zero-based rank', () => {
    expectNumbers(percentileLinear([0, 10, 20, 30], 4, 25), [NaN, NaN, NaN, 7.5]);
    expectNumbers(percentileLinear([0, 10, 20, 30], 4, 0), [NaN, NaN, NaN, 0]);
    expectNumbers(percentileLinear([0, 10, 20, 30], 4, 100), [NaN, NaN, NaN, 30]);
    expectNumbers(percentileLinear([7, 8], 1, 31), [7, 8]);
  });

  it('does not overflow a median or percentile whose answer is representable', () => {
    expect(rollingMedian([1e308, 1e308], 2)[1]).toBe(1e308);
    expect(rollingMedian([-1e308, 1e308], 2)[1]).toBe(0);
    expect(percentileLinear([-1e308, 1e308], 2, 50)[1]).toBe(0);
  });

  it('correlates price ranks with chronological order and averages tied ranks', () => {
    expectNumbers(rankCorrelation([1, 2, 3], 3), [NaN, NaN, 100]);
    expectNumbers(rankCorrelation([3, 2, 1], 3), [NaN, NaN, -100]);
    expectNumbers(rankCorrelation([10, 30, 20], 3), [NaN, NaN, 50]);
    expectNumbers(rankCorrelation([1, 1, 2], 3), [NaN, NaN, 86.60254037844386]);
    expectNumbers(rankCorrelation([2, 2, 2], 3), [NaN, NaN, NaN]);
    expectNumbers(rankCorrelation([2], 1), [NaN]);
  });

  it('weights older observations more heavily in center of gravity', () => {
    expectNumbers(centerOfGravity([1, 2, 3, 4], 3), [NaN, NaN, -5 / 3, -16 / 9]);
    expectNumbers(centerOfGravity([5, 5, 5], 3), [NaN, NaN, -2]);
    expectNumbers(centerOfGravity([1, -1], 2), [NaN, NaN]);
    expectNumbers(centerOfGravity([4], 1), [-1]);
    expectNumbers(centerOfGravity([0], 1), [NaN]);
  });

  it.each([
    [1, -3, 2], [1, 2, -3], [-3, 1, 2],
    [-3, 2, 1], [2, 1, -3], [2, -3, 1],
  ])('treats an exactly zero ordinary sum as missing for [%s, %s, %s]', (...values) => {
    expect(centerOfGravity(values, 3)[2]).toBeNaN();
  });

  it.each([
    { values: [1, -3, 2 + 2 ** -50], expected: 2 ** 50 - 1 },
    { values: [-3, 2 + 2 ** -50, 1], expected: 4 * 2 ** 50 - 2 },
    { values: [2 + 2 ** -50, -3, 1], expected: -(2 ** 50 + 3) },
    { values: [1, -3, 2 - 2 ** -50], expected: -(2 ** 50 + 1) },
    { values: [1e16, 1, -1e16], expected: -2e16 },
  ])('preserves a nonzero denominator after cancellation in $values', ({ values, expected }) => {
    expect(centerOfGravity(values, 3)[2]).toBe(expected);
  });

  it('distinguishes a subnormal nonzero denominator from zero', () => {
    expect(centerOfGravity([2, -2, Number.MIN_VALUE], 3)[2]).toBe(-Infinity);
    expect(centerOfGravity([2, -2, -Number.MIN_VALUE], 3)[2]).toBe(Infinity);
  });

  it('keeps scale-invariant gravity finite when ordinary totals overflow', () => {
    expect(centerOfGravity([1e308, 1e308], 2)[1]).toBe(-1.5);
  });

  const rollingCases = [
    { name: 'median', run: rollingMedian, expected: [NaN, NaN, NaN, 2, 3, 3, 5] },
    { name: 'mode', run: rollingMode, expected: [NaN, NaN, NaN, 1, 3, 3, 3] },
    { name: 'variance', run: rollingVariance, expected: [NaN, NaN, NaN, 1, 0, 0, 4] },
    { name: 'range', run: rollingRange, expected: [NaN, NaN, NaN, 2, 0, 0, 4] },
    { name: 'percentile', run: (values: readonly number[], period: number, options?: NumericalWindowOptions) => percentileLinear(values, period, 25, options), expected: [NaN, NaN, NaN, 1.5, 3, 3, 4] },
    { name: 'rank', run: rankCorrelation, expected: [NaN, NaN, NaN, 100, NaN, NaN, 100] },
    { name: 'gravity', run: centerOfGravity, expected: [NaN, NaN, NaN, -1.25, -1.5, -1.5, -1.3] },
  ];

  it.each(rollingCases)('$name skips leading and internal gaps only when requested', ({ run, expected }) => {
    const source = [NaN, 1, NaN, 3, 3, Infinity, 7];
    expectNumbers(run(source, 2, skip), expected);
    const chronological = run(source, 2);
    expect(chronological.slice(0, 4).every(Number.isNaN)).toBe(true);
    expect(chronological[5]).toBeNaN();
    expect(chronological[6]).toBeNaN();
    expectNumbers(run([NaN, 1, 3], 2), [NaN, NaN, expected[3]]);
  });

  it.each(rollingCases)('$name handles empty and insufficient history without mutating input', ({ run }) => {
    expect(run([], 2)).toEqual([]);
    expectNumbers(run([1], 2), [NaN]);
    expectNumbers(run([NaN, Infinity], 1, skip), [NaN, NaN]);
    const source = Object.freeze([3, 1, 2]);
    expect(run(source, 2)).toHaveLength(3);
    expect(source).toEqual([3, 1, 2]);
  });
});

describe('running extrema', () => {
  it('tracks extrema from the first value instead of a rolling window', () => {
    expectNumbers(runningMin([5, 3, 7, 1]), [5, 3, 3, 1]);
    expectNumbers(runningMax([5, 3, 7, 1]), [5, 5, 7, 7]);
  });

  it('propagates missing data through the entire accumulated history by default', () => {
    expectNumbers(runningMin([5, NaN, 1]), [5, NaN, NaN]);
    expectNumbers(runningMax([5, NaN, 9]), [5, NaN, NaN]);
    expectNumbers(runningMax([NaN, 2]), [NaN, NaN]);
  });

  it('retains the last finite extreme when skipping missing observations', () => {
    expectNumbers(runningMin([NaN, 5, Infinity, 2, NaN, 7], skip), [NaN, 5, 5, 2, 2, 2]);
    expectNumbers(runningMax([NaN, 5, -Infinity, 2, NaN, 7], skip), [NaN, 5, 5, 5, 5, 7]);
    expect(runningMin([])).toEqual([]);
    expect(runningMax([])).toEqual([]);
    expectNumbers(runningMin([NaN], skip), [NaN]);
  });
});

describe('numerical crossing predicates', () => {
  it('includes prior equality and excludes current equality', () => {
    const source = [1, 1, 2, 1, 0, 1, 2];
    const threshold = [1, 1, 1, 1, 1, 1, 1];
    expect(crossesAbove(source, threshold)).toEqual([false, false, true, false, false, false, true]);
    expect(crossesBelow(source, threshold)).toEqual([false, false, false, false, true, false, false]);
    expect(crosses(source, threshold)).toEqual([false, false, true, false, true, false, true]);
  });

  it('detects both directions on strict crossings between unequal values', () => {
    expect(crossesAbove([0, 2, 0], [1, 1, 1])).toEqual([false, true, false]);
    expect(crossesBelow([0, 2, 0], [1, 1, 1])).toEqual([false, false, true]);
    expect(crosses([0, 2, 0], [1, 1, 1])).toEqual([false, true, true]);
  });

  it('bridges gaps using the most recent jointly finite pair only in skip mode', () => {
    const a = [0, NaN, 2, 0, 0, 2];
    const b = [1, 1, 1, Infinity, 1, 1];
    expect(crosses(a, b)).toEqual([false, false, false, false, false, true]);
    expect(crosses(a, b, skip)).toEqual([false, false, true, false, true, true]);
    expect(crossesAbove([NaN, 0, 2], [1, 1, 1], skip)).toEqual([false, false, true]);
    expect(crosses([], [])).toEqual([]);
    expect(crossesAbove([0], [1])).toEqual([false]);
  });
});

describe('current value against prior observations', () => {
  it('requires the current value to exceed every prior value without requiring consecutive rises', () => {
    expect(rising([3, 1, 4, 4, 5], 2)).toEqual([false, false, true, false, true]);
    expect(falling([1, 3, 0, 0, -1], 2)).toEqual([false, false, true, false, true]);
  });

  it('uses prior finite observations in skip mode and rejects missing current values', () => {
    const source = [NaN, 1, NaN, 2, 3, Infinity, 4];
    expect(rising(source, 2)).toEqual([false, false, false, false, false, false, false]);
    expect(rising(source, 2, skip)).toEqual([false, false, false, false, true, false, true]);
    expect(falling([NaN, 4, NaN, 3, 2, NaN, 1], 2, skip)).toEqual([false, false, false, false, true, false, true]);
    expect(rising([], 1)).toEqual([]);
    expect(falling([1], 1)).toEqual([false]);
    expect(rising([1, 2], 1)).toEqual([false, true]);
    expect(falling([2, 1], 1)).toEqual([false, true]);
  });
});

describe('numerical input validation', () => {
  const withPeriod = [
    rollingMedian, rollingMode, rollingVariance, rollingRange, rankCorrelation,
    centerOfGravity, rising, falling,
    (values: readonly number[], period: number) => percentileLinear(values, period, 50),
  ];

  it.each([0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1])('rejects invalid period %s even for empty data', (period) => {
    for (const run of withPeriod) expect(() => run([], period)).toThrow(RangeError);
  });

  it.each([-1, 101, NaN, Infinity])('rejects invalid percentile %s', (percentage) => {
    expect(() => percentileLinear([], 1, percentage)).toThrow(RangeError);
  });

  it('rejects misaligned crossing arrays', () => {
    for (const run of [crossesAbove, crossesBelow, crosses]) {
      expect(() => run([1], [])).toThrow(RangeError);
      expect(() => run([], [1], skip)).toThrow(RangeError);
    }
  });

  it('rejects unknown missing policies and nonboolean sample options', () => {
    const invalid = { missing: 'drop' } as unknown as NumericalWindowOptions;
    for (const run of [rollingMedian, rollingMode, rollingVariance, rollingRange, rankCorrelation, centerOfGravity, rising, falling]) {
      expect(() => run([], 1, invalid)).toThrow(/missing/i);
    }
    expect(() => percentileLinear([], 1, 50, invalid)).toThrow(/missing/i);
    for (const run of [runningMin, runningMax]) expect(() => run([], invalid)).toThrow(/missing/i);
    for (const run of [crossesAbove, crossesBelow, crosses]) expect(() => run([], [], invalid)).toThrow(/missing/i);
    expect(() => rollingVariance([], 1, { sample: 'yes' } as unknown as { sample: boolean })).toThrow(/sample/i);
  });

  // The statistics and the calc helpers' option path take the same options
  // object, so one mistake gets one error: the same class and the same words.
  it('rejects what the calc helpers reject, in the same words', () => {
    const message = (run: () => unknown): string => {
      try { run(); } catch (e) { return `${(e as Error).constructor.name}: ${(e as Error).message}`; }
      return 'no error';
    };
    const period = message(() => sma([], 0, {}));
    expect(period).toMatch(/^RangeError/);
    for (const run of [rollingMedian, rising]) expect(message(() => run([], 0))).toBe(period);
    for (const options of [null, [], 5, 'skip', { missing: null }, { missing: 'drop' }]) {
      const bad = options as unknown as NumericalWindowOptions;
      const expected = message(() => sma([], 1, bad));
      expect(expected).toMatch(/^TypeError/);
      for (const run of [rollingMedian, rising]) expect(message(() => run([], 1, bad))).toBe(expected);
      expect(message(() => runningMax([], bad))).toBe(expected);
      expect(message(() => crosses([], [], bad))).toBe(expected);
    }
  });
});
