import { describe, expect, it } from 'vitest';
import { HMA } from '../src/indicators/overlay';
import type { Bar } from '../src/model/bar';

const bars = (values: readonly number[]): Bar[] => values.map((close, index) => ({
  time: 1700000000 + index * 60, open: close, high: close + 1, low: close - 1, close, volume: 1,
}));

describe('integer Hull window lengths', () => {
  it.each([
    [1, 0, 0], [2, 1, -1 / 3], [9, 10, 0], [13, 15, 1 / 3], [16, 18, 2 / 3], [25, 28, 2 / 3],
  ])('length %s has first value %s and linear lag %s', (length, first, lag) => {
    const input = Array.from({ length: 50 }, (_, i) => i + 1);
    const output = HMA.calc(bars(input), { length }, {}).hma;
    expect(output.slice(0, first)).toEqual(Array(first).fill(null));
    // A whole-window weighted average lags a ramp by (length - 1) / 3.
    // Combining the three independently known lags gives these constants.
    for (let index = first; index < input.length; index++) {
      expect(output[index], `bar ${index}`).toBeCloseTo(input[index] - lag, 12);
    }
  });

  it.each([9, 13])('length %s preserves a flat level and recovers after a source hole', length => {
    const values = Array<number>(60).fill(7);
    values[30] = NaN;
    const output = HMA.calc(bars(values), { length }, {}).hma;
    const root = Math.round(Math.sqrt(length));
    expect(output[length + root - 2]).toBe(7);
    expect(output.slice(30, 30 + length + root - 1)).toEqual(Array(length + root - 1).fill(null));
    expect(output[30 + length + root - 1]).toBe(7);
  });

  it('does not depend on bars after the current reading', () => {
    const input = bars(Array.from({ length: 40 }, (_, i) => i + 1));
    const full = HMA.calc(input, { length: 13 }, {}).hma;
    for (let length = 0; length <= input.length; length++) {
      expect(HMA.calc(input.slice(0, length), { length: 13 }, {}).hma).toEqual(full.slice(0, length));
    }
  });
});
