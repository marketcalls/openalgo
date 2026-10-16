import { describe, expect, it } from 'vitest';
import { dev, stdev, wma } from '../src/indicators/calc';
import { BOLLINGER } from '../src/indicators/trend';
import { indicatorDefaults } from '../src/model/indicator-registry';

describe('default chronological weighted and deviation windows', () => {
  it('adds weighted contributions oldest first before dividing', () => {
    expect(wma([1e16, -5e15, 1 / 3], 3)).toEqual([NaN, NaN, 1 / 6]);
  });

  it('keeps ordinary population-deviation bits in chronological order', () => {
    expect(stdev([10.46, 18.45, 12.48], 3)).toEqual([NaN, NaN, 3.392170724215133]);
    expect(stdev([1e16, 1, 1], 3)).toEqual([NaN, NaN, 4714045207910317]);
  });

  it('keeps absolute-deviation bits in chronological order', () => {
    expect(dev([15.35, 37.86, 34.97], 3)).toEqual([NaN, NaN, 9.36222222222222]);
    expect(dev([1e16, 1, 1], 3)).toEqual([NaN, NaN, 4444444444444443.5]);
  });

  it.each([wma, stdev, dev])('omits nonfinite windows and recovers after their expiry', run => {
    const suffix = [2, 3, 4];
    for (const hole of [NaN, Infinity, -Infinity]) {
      const result = run([1, hole, ...suffix], 2);
      expect(result.slice(0, 3)).toEqual([NaN, NaN, NaN]);
      expect(result.slice(3)).toEqual(run(suffix, 2).slice(1));
    }
  });

  it('normalizes overflowing results without hiding finite weighted quotients', () => {
    expect(wma([0, Number.MAX_VALUE, 1, 2, 3], 2)).toEqual([NaN, NaN, Number.MAX_VALUE / 3, 5 / 3, 8 / 3]);
    expect(stdev([1e200, -1e200, 1, 2, 3], 2)).toEqual([NaN, NaN, NaN, 0.5, 0.5]);
    expect(dev([1e308, -1e308, 1, 2, 3], 2)).toEqual([NaN, NaN, 5e307, 0.5, 0.5]);
  });

  it('leaves compensated explicit options and aligned lengths separate', () => {
    const values = [1e16, -5e15, 1 / 3];
    expect(wma(values, 3, {})).toEqual([NaN, NaN, 1 / 6]);
    expect(wma(values, [3, 3, 3])).toEqual(wma(values, 3, {}));
    expect(stdev([1e308, -1e308], 2, {})).toEqual([NaN, 1e308]);
    expect(dev([1e308, -1e308], [2, 2])).toEqual([NaN, 1e308]);
  });

  it.each([wma, stdev, dev])('is independent of later bars and forming-bar revisions', run => {
    const values = Object.freeze([10.46, 18.45, 12.48, 15.35, 37.86, 34.97]);
    const complete = run(values, 3);
    for (let end = 0; end <= values.length; end++) expect(run(values.slice(0, end), 3)).toEqual(complete.slice(0, end));
    run([...values.slice(0, -1), 100], 3);
    expect(run(values, 3)).toEqual(complete);
    expect(run([1, 2, 3], 1.5)).toEqual(Object.assign([NaN, NaN, NaN], { '0.5': NaN, '1.5': NaN, '2.5': NaN }));
  });

  it('threads the corrected spread through a band descriptor', () => {
    const closes = [10.46, 18.45, 12.48];
    const bars = closes.map((close, i) => ({ time: i, open: close, high: close, low: close, close }));
    const result = BOLLINGER.calc!(bars, { ...indicatorDefaults(BOLLINGER), length: 3 }, {});
    expect(result.basis[2]).toBe((10.46 + 18.45 + 12.48) / 3);
    expect(result.upper[2]).toBe((10.46 + 18.45 + 12.48) / 3 + 2 * 3.392170724215133);
    expect(result.lower[2]).toBe((10.46 + 18.45 + 12.48) / 3 - 2 * 3.392170724215133);
  });
});
