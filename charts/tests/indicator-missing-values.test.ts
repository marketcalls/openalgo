import { describe, expect, it } from 'vitest';
import {
  sma, wma, rma, stdev, dev, smaSeededEma, highest, lowest,
  highestBars, lowestBars, percentRank,
} from '../src/indicators/calc';
import type { NumericalWindowOptions } from '../src/indicators/statistics';

const skip: NumericalWindowOptions = { missing: 'skip' };
const propagate: NumericalWindowOptions = { missing: 'propagate' };

function expectNumbers(actual: readonly number[], expected: readonly number[]): void {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, index) => {
    if (Number.isNaN(value)) expect(actual[index], `index ${index}`).toBeNaN();
    else if (!Number.isFinite(value)) expect(actual[index], `index ${index}`).toBe(value);
    else expect(actual[index], `index ${index}`).toBeCloseTo(value, 12);
  });
}

const cases = [
  {
    name: 'sma', run: sma,
    legacy: [NaN, 1.5, NaN, NaN, 4.5, NaN],
    skipped: [NaN, NaN, NaN, 2, 4, 4, 6, 6],
    propagated: [NaN, NaN, 2, NaN, NaN, 6, 8, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'wma', run: wma,
    legacy: [NaN, 5 / 3, NaN, NaN, 14 / 3, NaN],
    skipped: [NaN, NaN, NaN, 7 / 3, 13 / 3, 13 / 3, 19 / 3, 19 / 3],
    propagated: [NaN, NaN, 7 / 3, NaN, NaN, 19 / 3, 25 / 3, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'rma', run: rma,
    legacy: [NaN, 1.5, NaN, 2.75, 3.875, NaN],
    skipped: [NaN, NaN, NaN, 2, 3.5, 3.5, 5.25, 5.25],
    propagated: [NaN, NaN, 2, NaN, NaN, 6, 7.5, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'stdev', run: stdev,
    legacy: [NaN, 0.5, NaN, NaN, 0.5, NaN],
    skipped: [NaN, NaN, NaN, 1, 1, 1, 1, 1],
    propagated: [NaN, NaN, 1, NaN, NaN, 1, 1, NaN],
    singleSkip: [NaN, 0, 0, 0], singlePropagate: [NaN, 0, NaN, 0],
  },
  {
    name: 'dev', run: dev,
    legacy: [NaN, 0.5, NaN, NaN, 0.5, NaN],
    skipped: [NaN, NaN, NaN, 1, 1, 1, 1, 1],
    propagated: [NaN, NaN, 1, NaN, NaN, 1, 1, NaN],
    singleSkip: [NaN, 0, 0, 0], singlePropagate: [NaN, 0, NaN, 0],
  },
  {
    name: 'smaSeededEma', run: smaSeededEma,
    legacy: [NaN, 1.5, NaN, 3.1666666666666665, 4.388888888888888, NaN],
    skipped: [NaN, NaN, NaN, 2, 4, 4, 6, 6],
    propagated: [NaN, NaN, 2, NaN, NaN, 6, 8, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'highest', run: highest,
    legacy: [NaN, 2, 2, 4, 5, 5],
    skipped: [NaN, NaN, NaN, 3, 5, 5, 7, 7],
    propagated: [NaN, NaN, 3, NaN, NaN, 7, 9, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'lowest', run: lowest,
    legacy: [NaN, 1, 2, 4, 4, 5],
    skipped: [NaN, NaN, NaN, 1, 3, 3, 5, 5],
    propagated: [NaN, NaN, 1, NaN, NaN, 5, 7, NaN],
    singleSkip: [NaN, 2, 2, 4], singlePropagate: [NaN, 2, NaN, 4],
  },
  {
    name: 'highestBars', run: highestBars,
    legacy: [NaN, 0, 0, 0, 0, 0],
    skipped: [NaN, NaN, NaN, 0, 0, -1, 0, -1],
    propagated: [NaN, NaN, 0, NaN, NaN, 0, 0, NaN],
    singleSkip: [NaN, 0, -1, 0], singlePropagate: [NaN, 0, NaN, 0],
  },
  {
    name: 'lowestBars', run: lowestBars,
    legacy: [NaN, -1, 0, 0, -1, 0],
    skipped: [NaN, NaN, NaN, -2, -1, -2, -2, -3],
    propagated: [NaN, NaN, -1, NaN, NaN, -1, -1, NaN],
    singleSkip: [NaN, 0, -1, 0], singlePropagate: [NaN, 0, NaN, 0],
  },
  {
    name: 'percentRank', run: percentRank,
    legacy: [NaN, NaN, 0, 50, 50, 0],
    skipped: [NaN, NaN, NaN, NaN, 100, NaN, 100, NaN],
    propagated: [NaN, NaN, NaN, NaN, NaN, NaN, 100, NaN],
    singleSkip: [NaN, NaN, NaN, 100], singlePropagate: [NaN, NaN, NaN, NaN],
  },
];

describe('default scalar-window behavior', () => {
  it.each(cases)('$name preserves omitted and undefined option results', ({ run, legacy }) => {
    const values = [1, 2, NaN, 4, 5, NaN];
    expect(run(values, 2)).toEqual(legacy);
    expect(run(values, 2, undefined)).toEqual(legacy);
    expect(run([1, 2], 0)).toEqual([NaN, NaN]);
  });

  it('retains existing missing-extrema sentinels and rank results by default', () => {
    expect(highest([NaN, NaN], 2)).toEqual([NaN, -Infinity]);
    expect(lowest([NaN, NaN], 2)).toEqual([NaN, Infinity]);
    expect(highestBars([9, 2, NaN], 3)).toEqual([NaN, NaN, 0]);
    expect(percentRank([1, 2, NaN], 2)).toEqual([NaN, NaN, 0]);
    expect(sma([1, 2, 3], 1.5)).toEqual([NaN, 2, NaN]);
  });
});

describe('opt-in scalar-window missing policies', () => {
  it.each(cases)('$name collects finite observations across leading, internal and trailing gaps', ({ run, skipped }) => {
    expectNumbers(run([NaN, 1, NaN, 3, 5, NaN, 7, NaN], 2, skip), skipped);
  });

  it.each(cases)('$name propagates chronological gaps and recovers with a complete valid window', ({ run, propagated }) => {
    const values = [NaN, 1, 3, NaN, 5, 7, 9, NaN];
    expectNumbers(run(values, 2, propagate), propagated);
    expectNumbers(run(values, 2, {}), propagated);
  });

  it.each(cases)('$name handles period one and treats both infinities as missing observations', ({ run, singleSkip, singlePropagate }) => {
    expectNumbers(run([NaN, 2, NaN, 4], 1, skip), singleSkip);
    expectNumbers(run([Infinity, 2, -Infinity, 4], 1, skip), singleSkip);
    expectNumbers(run([NaN, 2, NaN, 4], 1, propagate), singlePropagate);
  });

  it.each(cases)('$name handles empty, short and entirely missing inputs without mutation', ({ run }) => {
    for (const options of [skip, propagate]) {
      expect(run([], 2, options)).toEqual([]);
      expectNumbers(run([1], 2, options), [NaN]);
      expectNumbers(run([NaN, NaN, Infinity], 2, options), [NaN, NaN, NaN]);
      const values = Object.freeze([3, 1, 2]);
      expect(run(values, 2, options)).toHaveLength(3);
      expect(values).toEqual([3, 1, 2]);
    }
  });

  it('preserves original bar offsets and chooses the latest tied extreme', () => {
    const values = [4, NaN, 4, 3, NaN];
    expectNumbers(highestBars(values, 2, skip), [NaN, NaN, 0, -1, -2]);
    expectNumbers(lowestBars(values, 2, skip), [NaN, NaN, 0, 0, -1]);
    expect(Object.is(highestBars([1, 1], 2, skip)[1], 0)).toBe(true);
    expect(Object.is(lowestBars([1, 1], 2, propagate)[1], 0)).toBe(true);
  });

  it('excludes the rank subject from history and counts equality', () => {
    expectNumbers(percentRank([3, 1, 2, 2, 0], 2, propagate), [NaN, NaN, 50, 100, 0]);
    expectNumbers(percentRank([NaN, 3, NaN, 1, 2, NaN, 0, 2, NaN], 2, skip),
      [NaN, NaN, NaN, NaN, 50, NaN, 0, 100, NaN]);
    expectNumbers(percentRank([2, 1, NaN, 1], 1, skip), [NaN, 0, NaN, 100]);
  });

  it('restarts the full recursive seed after each propagated gap', () => {
    const values = [2, NaN, 4, 6, NaN, 8, 10, 12, 14];
    expectNumbers(rma(values, 3, propagate), [NaN, NaN, NaN, NaN, NaN, NaN, NaN, 10, 34 / 3]);
    expectNumbers(smaSeededEma(values, 3, propagate), [NaN, NaN, NaN, NaN, NaN, NaN, NaN, 10, 12]);
    expectNumbers(rma(values, 3, skip), [NaN, NaN, NaN, 4, 4, 16 / 3, 62 / 9, 232 / 27, 842 / 81]);
  });
});

describe('opt-in missing policy validation', () => {
  it.each(cases)('$name validates option-path periods without changing the default path', ({ run }) => {
    for (const period of [0, -1, 1.5, NaN, Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => run([], period, skip)).toThrow(RangeError);
      expect(() => run([], period, propagate)).toThrow(RangeError);
    }
  });

  it.each(cases)('$name rejects malformed policy options', ({ run }) => {
    for (const options of [{ missing: 'drop' }, { missing: null }, null, 'skip']) {
      expect(() => run([], 1, options as unknown as NumericalWindowOptions)).toThrow(/missing|options/i);
    }
  });
});

describe('opt-in finite arithmetic at numerical limits', () => {
  const maximum = Number.MAX_VALUE;
  const minimum = Number.MIN_VALUE;
  const averages = [
    { name: 'sma', run: sma }, { name: 'wma', run: wma },
    { name: 'rma', run: rma }, { name: 'smaSeededEma', run: smaSeededEma },
  ];

  it.each(averages)('$name retains constant extreme and subnormal values through seed and updates', ({ run }) => {
    for (const constant of [maximum, -maximum, minimum, -minimum]) {
      for (const options of [{}, skip]) {
        const result = run(new Array<number>(8).fill(constant), 3, options);
        expect(result.slice(0, 2).every(Number.isNaN)).toBe(true);
        expect(result.slice(2)).toEqual(new Array<number>(6).fill(constant));
      }
    }
  });

  it.each([{ name: 'stdev', run: stdev }, { name: 'dev', run: dev }])('$name is zero for constant extreme inputs', ({ run }) => {
    for (const constant of [maximum, -maximum, minimum, -minimum]) {
      expect(run([constant, constant, constant], 3, {})[2]).toBe(0);
    }
  });

  it.each([
    [-1, 1, 1], [1, -1, 1], [1, 1, -1],
    [1, -1, -1], [-1, 1, -1], [-1, -1, 1],
  ])('keeps asymmetric extreme deviations finite for signs [%s, %s, %s]', (...signs) => {
    const values = signs.map((sign) => sign * maximum);
    expect(stdev(values, 3, {})[2] / maximum).toBeCloseTo(Math.sqrt(8) / 3, 14);
    expect(dev(values, 3, {})[2] / maximum).toBeCloseTo(8 / 9, 14);
  });

  it('retains small spreads around a large common offset', () => {
    const origin = 2 ** 500;
    const step = 2 ** 448;
    const values = [origin, origin + step, origin + 2 * step];
    expect(sma(values, 3, {})[2]).toBe(origin + step);
    expect(stdev(values, 3, {})[2] / step).toBeCloseTo(Math.sqrt(2 / 3), 14);
    expect(dev(values, 3, {})[2] / step).toBeCloseTo(2 / 3, 14);
  });

  it('retains small normal spreads without squaring them into zero', () => {
    const unit = 1e-300;
    const values = [unit, 2 * unit, 3 * unit];
    expect(sma(values, 3, {})[2] / unit).toBeCloseTo(2, 14);
    expect(stdev(values, 3, {})[2] / unit).toBeCloseTo(Math.sqrt(2 / 3), 14);
    expect(dev(values, 3, {})[2] / unit).toBeCloseTo(2 / 3, 14);
  });

  it('rounds subnormal means and deviations without losing an entire observation', () => {
    expect(sma([0, minimum, 2 * minimum], 3, {})[2]).toBe(minimum);
    expect(stdev([0, minimum, 2 * minimum], 3, {})[2]).toBe(minimum);
    expect(dev([0, minimum, 2 * minimum], 3, {})[2]).toBe(minimum);
    expect(sma([0, minimum], 2, {})[1]).toBe(0);
    expect(stdev([0, minimum], 2, {})[1]).toBe(0);
    expect(dev([0, minimum], 2, {})[1]).toBe(0);
  });

  it('retains small residuals after ordinary or overflowing cancellation', () => {
    for (const run of [sma, rma, smaSeededEma]) {
      for (const values of [[1e16, 1, -1e16], [1e16, -1e16, 1], [1, 1e16, -1e16]]) {
        expect(run(values, 3, {})[2]).toBe(1 / 3);
      }
      expect(run([1e308, 1e308, -1e308, -1e308, 1e-100], 5, {})[4]).toBe(2e-101);
      const values = [maximum, maximum, -maximum, -maximum, minimum, minimum, minimum, minimum, minimum];
      expect(run(values, values.length, {})[values.length - 1]).toBe(minimum);
    }
  });

  it('retains a small weighted residual after cancellation', () => {
    const large = 2 ** 1022;
    expect(wma([3 * large, 3, -large], 3, {})[2]).toBe(1);
    expect(wma([-maximum, maximum], 2, {})[1]).toBe(maximum / 3);
  });

  it('keeps recursive convex combinations finite across opposite extreme values', () => {
    const values = [maximum, maximum, maximum, -maximum, maximum];
    const wilder = rma(values, 3, {});
    const exponential = smaSeededEma(values, 3, {});
    expect(wilder[2]).toBe(maximum);
    expect(wilder[3] / maximum).toBeCloseTo(1 / 3, 14);
    expect(wilder[4] / maximum).toBeCloseTo(5 / 9, 14);
    expect(exponential.slice(2)).toEqual([maximum, 0, maximum / 2]);
    expect(rma([maximum, maximum, maximum, NaN, -maximum], 3, skip)[4] / maximum).toBeCloseTo(1 / 3, 14);
  });
});
