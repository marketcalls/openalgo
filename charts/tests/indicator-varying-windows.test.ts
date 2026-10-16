import { describe, expect, it } from 'vitest';
import {
  sma, wma, stdev, dev, highest, lowest, highestBars, lowestBars,
  percentRank, pivotHigh, pivotLow, barsSince,
} from '../src/indicators/calc';
import type { NumericalWindowOptions } from '../src/indicators/statistics';

const skip: NumericalWindowOptions = { missing: 'skip' };
const propagate: NumericalWindowOptions = { missing: 'propagate' };

function expectNumbers(actual: readonly number[], expected: readonly number[]): void {
  expect(actual).toHaveLength(expected.length);
  expected.forEach((value, index) => {
    if (Number.isNaN(value)) expect(actual[index], `index ${index}`).toBeNaN();
    else expect(actual[index], `index ${index}`).toBeCloseTo(value, 12);
  });
}

const windows = [
  { name: 'sma', run: sma, result: [2, 3, 14 / 3, 7, 7], skipped: [2, NaN, 3, 4, 14 / 3] },
  { name: 'wma', run: wma, result: [2, 10 / 3, 17 / 3, 20 / 3, 39 / 5], skipped: [2, NaN, 10 / 3, 4, 17 / 3] },
  { name: 'stdev', run: stdev, result: [0, 1, Math.sqrt(56) / 3, 1, Math.sqrt(5)], skipped: [0, NaN, 1, 0, Math.sqrt(56) / 3] },
  { name: 'dev', run: dev, result: [0, 1, 20 / 9, 1, 2], skipped: [0, NaN, 1, 0, 20 / 9] },
  { name: 'highest', run: highest, result: [2, 4, 8, 8, 10], skipped: [2, NaN, 4, 4, 8] },
  { name: 'lowest', run: lowest, result: [2, 2, 2, 6, 4], skipped: [2, NaN, 2, 4, 2] },
  { name: 'highestBars', run: highestBars, result: [0, 0, 0, -1, 0], skipped: [0, NaN, 0, -1, 0] },
  { name: 'lowestBars', run: lowestBars, result: [0, -1, -2, 0, -3], skipped: [0, NaN, -2, -1, -4] },
  { name: 'percentRank', run: percentRank, result: [NaN, NaN, NaN, 50, 100], skipped: [NaN, NaN, NaN, NaN, NaN] },
];

describe('varying finite windows', () => {
  it.each(windows)('$name evaluates each current length and can grow after shrinking', ({ run, result }) => {
    const values = Object.freeze([2, 4, 8, 6, 10]);
    const periods = Object.freeze([1, 2, 3, 2, 4]);
    expectNumbers(run(values, periods), result);
    expectNumbers(run(values, periods, {}), result);
    expect(values).toEqual([2, 4, 8, 6, 10]);
    expect(periods).toEqual([1, 2, 3, 2, 4]);
  });

  it.each(windows)('$name selects finite history and reevaluates changed lengths during gaps', ({ run, skipped }) => {
    const values = [2, NaN, 4, NaN, 8];
    const periods = [1, 2, 2, 1, 3];
    expectNumbers(run(values, periods, skip), skipped);
    expectNumbers(run(values, periods), [skipped[0], NaN, NaN, NaN, NaN]);
    expectNumbers(run(values, periods, propagate), [skipped[0], NaN, NaN, NaN, NaN]);
  });

  it.each(windows)('$name matches the scalar option path for constant length arrays', ({ run }) => {
    const values = [NaN, 2, 2, 5, NaN, -1, Number.MAX_VALUE, Number.MAX_VALUE, -Number.MAX_VALUE];
    for (const options of [{}, skip, propagate]) {
      for (const period of [1, 2, 3]) {
        expect(run(values, new Array<number>(values.length).fill(period), options)).toEqual(run(values, period, options));
      }
    }
  });

  it.each(windows)('$name keeps results stable when future bars are appended', ({ run }) => {
    const values = [2, NaN, 4, 6, 3, NaN, 8];
    const periods = [1, 2, NaN, 3, 1, 2, 5];
    for (const options of [skip, propagate]) {
      const result = run(values, periods, options);
      for (let end = 0; end <= values.length; end++) {
        expect(run(values.slice(0, end), periods.slice(0, end), options)).toEqual(result.slice(0, end));
      }
    }
  });

  it.each(windows)('$name represents unavailable lengths or insufficient history as gaps', ({ run }) => {
    expect(run([], [])).toEqual([]);
    expect(run([2], [2])).toEqual([NaN]);
    expect(run([2, 3], [NaN, NaN])).toEqual([NaN, NaN]);
    expect(run([NaN, Infinity, -Infinity], [1, 1, 1], skip)).toEqual([NaN, NaN, NaN]);
    expect(run([2, 3], [Number.MAX_SAFE_INTEGER, Number.MAX_SAFE_INTEGER], skip)).toEqual([NaN, NaN]);
  });

  it('retains observations from bars whose lengths were missing', () => {
    const values = [2, 4, 6, 8, 10];
    const periods = [1, NaN, 3, 1, 5];
    for (const options of [skip, propagate]) {
      expectNumbers(sma(values, periods, options), [2, NaN, 4, 8, 6]);
      expectNumbers(lowestBars(values, periods, options), [0, NaN, -2, 0, -4]);
    }
  });

  it('preserves original offsets and the latest tied extreme through gaps', () => {
    const periods = [1, 1, 2, 2];
    expect(highestBars([5, NaN, 5, 4], periods, skip)).toEqual([0, -1, 0, -1]);
    expect(lowestBars([1, NaN, 1, 2], periods, skip)).toEqual([0, -1, 0, -1]);
    expect(sma([2, 4, NaN], [1, 2, 1], skip)).toEqual([2, 3, 4]);
  });

  it('ranks against previous observations, requires the subject, and counts equality', () => {
    expect(percentRank([2, NaN, 4, NaN, 3], [1, 1, 1, 2, 2], skip)).toEqual([NaN, NaN, 100, NaN, 50]);
    expect(percentRank([2, 2, 1, 2], [1, 1, 2, 3])).toEqual([NaN, 100, 0, 100]);
  });

  it('composes an event-reset average from native numerical results', () => {
    const periods = barsSince([false, true, false, false, true, false]).map((distance) => distance + 1);
    expect(sma([100, 2, 4, 6, 8, 10], periods)).toEqual([NaN, 2, 3, 4, 8, 9]);
  });

  it('reads bounded history for short varying windows', () => {
    const count = 2000;
    let reads = 0;
    const source = new Proxy(new Array<number>(count).fill(7), {
      get(target, key, receiver) {
        if (typeof key === 'string' && /^\d+$/.test(key)) reads++;
        return Reflect.get(target, key, receiver);
      },
    });
    expect(sma(source, new Array<number>(count).fill(1), skip)).toEqual(new Array<number>(count).fill(7));
    expect(reads).toBeLessThanOrEqual(8 * count);
  });
});

describe('varying window validation', () => {
  it.each(windows)('$name validates all periods even during missing-input warmup', ({ run }) => {
    for (const period of [0, -1, 1.5, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      for (const options of [undefined, skip, propagate]) {
        expect(() => run([NaN, NaN], [20, period], options)).toThrow(RangeError);
      }
    }
  });

  it.each(windows)('$name rejects misaligned or malformed periods and policies', ({ run }) => {
    for (const periods of [[], [1], [1, 1, 1]]) {
      expect(() => run([2, 3], periods)).toThrow(/length|align/i);
    }
    for (const period of [null, undefined, '2', true]) {
      expect(() => run([NaN], [period] as unknown as number[])).toThrow(TypeError);
    }
    expect(() => run([NaN], new Array<number>(1))).toThrow(TypeError);
    for (const periods of [null, {}, '2']) {
      expect(() => run([], periods as unknown as number[])).toThrow(TypeError);
    }
    for (const options of [null, [], { missing: null }, { missing: 'drop' }]) {
      expect(() => run([], [], options as unknown as NumericalWindowOptions)).toThrow(TypeError);
    }
  });
});

const pivots = [
  { name: 'pivotHigh', run: pivotHigh, sign: 1 },
  { name: 'pivotLow', run: pivotLow, sign: -1 },
];

describe('varying pivot widths', () => {
  it.each(pivots)('$name uses widths on the confirmation bar and can confirm a candidate repeatedly', ({ run, sign }) => {
    const values = Object.freeze([1, 5, 2, 1, 0].map((value) => value * sign));
    const right = Object.freeze([1, 1, 1, 2, 3]);
    expect(run(values, 1, right)).toEqual([NaN, NaN, 5 * sign, 5 * sign, 5 * sign]);
    expect(right).toEqual([1, 1, 1, 2, 3]);
  });

  it.each(pivots)('$name accepts zero widths and independently varying sides', ({ run, sign }) => {
    expect(run([1, 5, 2, 4, 1].map((value) => value * sign), [0, 1, 1, 1, 2], [0, 0, 1, 0, 1]))
      .toEqual([sign, 5 * sign, 5 * sign, 4 * sign, NaN]);
    expect(run([2, NaN, Infinity, -Infinity, 3], [0, 0, 0, 0, 0], 0)).toEqual([2, NaN, NaN, NaN, 3]);
  });

  it.each(pivots)('$name treats missing widths locally and retains the source candidate', ({ run, sign }) => {
    expect(run([1, 5, 2, 1].map((value) => value * sign), [0, NaN, 1, 1], [0, 0, 1, NaN]))
      .toEqual([sign, NaN, 5 * sign, NaN]);
    expect(run([sign, 5 * sign, 2 * sign], [1, 1, 1], 1)).toEqual([NaN, NaN, 5 * sign]);
  });

  it.each(pivots)('$name rejects plateaus and missing neighbors on either side', ({ run, sign }) => {
    for (const values of [[5, 5, 1], [1, 5, 5], [NaN, 5, 1], [1, 5, NaN], [Infinity, 5, 1], [1, 5, -Infinity]]) {
      expect(run(values.map((value) => value * sign), [1, 1, 1], [1, 1, 1])).toEqual([NaN, NaN, NaN]);
    }
  });

  it.each(pivots)('$name matches scalar widths and remains prefix stable', ({ run, sign }) => {
    const values = [1, 5, 2, NaN, 4, 6, 3].map((value) => value * sign);
    for (const left of [0, 1, 2]) {
      for (const right of [0, 1, 2]) {
        expect(run(values, new Array<number>(values.length).fill(left), right)).toEqual(run(values, left, right));
        expect(run(values, left, new Array<number>(values.length).fill(right))).toEqual(run(values, left, right));
      }
    }
    const left = [0, NaN, 1, 2, 0, 1, 2];
    const right = [0, 0, 1, 2, 1, 0, 2];
    const result = run(values, left, right);
    for (let end = 0; end <= values.length; end++) {
      expect(run(values.slice(0, end), left.slice(0, end), right.slice(0, end))).toEqual(result.slice(0, end));
    }
  });

  it.each(pivots)('$name handles empty and insufficient history without allocating enormous windows', ({ run }) => {
    expect(run([], [], [])).toEqual([]);
    expect(run([2], [1], [0])).toEqual([NaN]);
    expect(run([2], [0], [1])).toEqual([NaN]);
    expect(run([2], [Number.MAX_SAFE_INTEGER], [Number.MAX_SAFE_INTEGER])).toEqual([NaN]);
    expect(run([2], [NaN], [NaN])).toEqual([NaN]);
  });

  it.each(pivots)('$name validates both sides fully, including scalar companions and warmup bars', ({ run }) => {
    for (const width of [-1, 0.5, Infinity, -Infinity, Number.MAX_SAFE_INTEGER + 1]) {
      expect(() => run([NaN, NaN], [NaN, width], [NaN, NaN])).toThrow(RangeError);
      expect(() => run([NaN, NaN], [NaN, NaN], [NaN, width])).toThrow(RangeError);
      expect(() => run([], [], width)).toThrow(RangeError);
      expect(() => run([], width, [])).toThrow(RangeError);
    }
    expect(() => run([], [], NaN)).toThrow(RangeError);
    expect(() => run([], NaN, [])).toThrow(RangeError);
    expect(() => run([NaN], [], [1])).toThrow(/length|align/i);
    expect(() => run([NaN], [1], [])).toThrow(/length|align/i);
    for (const width of [null, undefined, '1', true]) {
      expect(() => run([NaN], [width] as unknown as number[], [1])).toThrow(TypeError);
      expect(() => run([NaN], [1], [width] as unknown as number[])).toThrow(TypeError);
    }
    expect(() => run([NaN], new Array<number>(1), [1])).toThrow(TypeError);
    expect(() => run([], null as unknown as number[], [])).toThrow(TypeError);
  });
});
