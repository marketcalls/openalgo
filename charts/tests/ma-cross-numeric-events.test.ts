import { describe, expect, it } from 'vitest';
import { MA_CROSS } from '../src/indicators/averages';
import { indicatorDefaults } from '../src/model/indicator-registry';

function calculate(values: readonly number[], shortLength = 1, longLength = 2) {
  return MA_CROSS.calc(values.map((close, i) => ({
    time: 1700000000 + i * 60, open: close, high: close, low: close, close,
  })), { ...indicatorDefaults(MA_CROSS), shortLength, longLength }, {});
}

describe('MA Cross numerical event boundaries', () => {
  it('does not invent a strict crossing when the two current means are equal', () => {
    const result = calculate([1e16, 3, 1, 1]);
    expect(result.short).toEqual([1e16, 3, 1, 1]);
    expect(result.long).toEqual([null, (1e16 + 3) / 2, 2, 1]);
    expect(result.cross).toEqual([null, null, null, null]);
  });

  it('retains genuine upward and downward crossings', () => {
    expect(calculate([2, 0, 2, 0]).cross).toEqual([null, null, 2, 0]);
  });

  it('does not bridge a missing window and recognizes a later real crossing', () => {
    const result = calculate([2, 0, NaN, 2, 0, 2]);
    expect(result.long).toEqual([null, 1, null, null, 1, 1]);
    expect(result.cross).toEqual([null, null, null, null, null, 2]);
  });

  it('recovers after overflow without producing a crossing across its gap', () => {
    const result = calculate([1e308, 1e308, 1, 2, 0]);
    expect(result.long).toEqual([null, null, 5e307, 1.5, 1]);
    expect(result.cross).toEqual([null, null, null, 2, 0]);
  });

  it('removes a transient forming-bar crossing when the final value returns', () => {
    expect(calculate([1e16, 3, 1, 5]).cross[3]).toBe(5);
    expect(calculate([1e16, 3, 1, 1]).cross[3]).toBeNull();
  });

  it('keeps equal full windows equal at the declared maximum length', () => {
    const result = calculate(Array<number>(1200).fill(1), 1000, 1000);
    expect(result.short.slice(0, 999)).toEqual(Array(999).fill(null));
    expect(result.short.slice(999)).toEqual(Array(201).fill(1));
    expect(result.long).toEqual(result.short);
    expect(result.cross).toEqual(Array(1200).fill(null));
  });
});
