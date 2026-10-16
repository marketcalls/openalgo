import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { MFI } from '../src/indicators/momentum';

const bars = (prices: readonly number[], volumes?: readonly (number | undefined)[]): Bar[] =>
  prices.map((close, i) => ({
    time: 1700000000 + i * 60, open: close, high: close + 1, low: close - 1,
    close, volume: volumes === undefined ? 1 : volumes[i],
  }));

const values = (data: readonly Bar[], period: number) => MFI.calc(data, { period }, {}).mfi;

describe('MFI finite directional flows and chronological windows', () => {
  it('rejects an overflowing upward flow and recovers when it expires', () => {
    expect(values(bars([100, 101, 102, 103, 104], [1, 1e308, 1, 1, 1]), 2))
      .toEqual([null, null, null, 100, 100]);
  });

  it('does not turn an overflowing downward flow into zero', () => {
    expect(values(bars([104, 103, 102, 101, 100], [1, 1e308, 1, 1, 1]), 2))
      .toEqual([null, null, null, 0, 0]);
  });

  it('rejects an overflowing sum of individually finite upward flows', () => {
    // The first two rises contribute 1e308 and 1.2e308. Their sum is unavailable.
    expect(values(bars([1, 2, 3, 4, 5], [1, 5e307, 4e307, 1, 1]), 2))
      .toEqual([null, null, null, 100, 100]);
  });

  it('rejects an overflowing downward sum before computing a finite ratio', () => {
    expect(values(bars([3, 2, 1, 2, 3], [1, 5e307, 1e308, 1, 1]), 2))
      .toEqual([null, null, null, 0, 100]);
  });

  it('keeps period one local to the current directional contribution', () => {
    expect(values(bars([100, 101, 100, 101], [1, 1e308, 1, 1]), 1))
      .toEqual([null, null, 0, 100]);
  });

  it('recovers the default window after its first unavailable flow expires', () => {
    const prices = [100, 101, ...Array<number>(15).fill(102)];
    const volume = [1, 1e308, ...Array<number>(15).fill(1)];
    const result = MFI.calc(bars(prices, volume), {}, {}).mfi;
    expect(result).toEqual([...Array<null>(15).fill(null), 100, 100]);
  });

  it('requires finite current and previous typical prices', () => {
    expect(values(bars([1, 1e308, 1e308, 2, 3]), 1))
      .toEqual([null, null, null, null, 100]);
    expect(values(bars([1, NaN, 2, 3]), 1)).toEqual([null, null, null, 100]);
  });

  it('does not treat explicitly nonfinite volume as a known flat contribution', () => {
    expect(values(bars([1, 1, 1, 2], [1, NaN, 1, 1]), 1))
      .toEqual([null, null, 100, 100]);
  });

  it('preserves omitted volume as zero traded volume', () => {
    expect(values(bars([1, 2, 1], [1, undefined, 1]), 2)).toEqual([null, null, 0]);
  });

  it('preserves the flat-price branch even if its unused product would overflow', () => {
    expect(values(bars([2, 2, 2], [1e308, 1e308, 1e308]), 2))
      .toEqual([null, null, 100]);
  });

  it('preserves exact ordinary ratios and no-down-flow behavior', () => {
    expect(values(bars([1, 2, 1, 1], [1, 1, 2, 1e308]), 2))
      .toEqual([null, null, 50, 0]);
    expect(values(bars([1, 2, 3]), 2)).toEqual([null, null, 100]);
  });

  it('does not discard subnormal but finite directional flows', () => {
    const input = bars([1, 2, 1, 2], Array<number>(4).fill(Number.MIN_VALUE));
    expect(values(input, 2)).toEqual([null, null, 100 - 100 / 3, 100 - 100 / 3]);
  });

  it('sums ordinary fractional-volume contributions in chronological order', () => {
    // Exact-rational rounding of each binary64 operation gives this final value.
    // Oldest-first rises are 2, 3*0.1, 4*0.4; the falling contribution is 3*0.2.
    expect(values(bars([1, 2, 3, 4, 3], [1, 1, 0.1, 0.4, 0.2]), 4))
      .toEqual([null, null, null, null, 86.66666666666666]);
  });

  it('retains chronological rounding through finite signed-price cancellation', () => {
    // Rises -2*0.4, -1*0.4, 2*0.4 cancel before the ratio to the fall 1*0.7.
    expect(values(bars([-3, -2, -1, 2, 1], [0.3, 0.4, 0.4, 0.4, 0.7]), 4))
      .toEqual([null, null, null, null, -133.33333333333343]);
  });

  it('is causal and does not retain a rejected forming calculation', () => {
    const data = Object.freeze(bars([1, 2, 3, 4, 5], [1, 5e307, 4e307, 1, 1])
      .map((bar) => Object.freeze(bar)));
    const expected = [null, null, null, 100, 100];
    for (let count = 0; count <= data.length; count++) {
      const prefix = data.slice(0, count);
      MFI.calc([...prefix, ...bars([1e308], [1e308])], { period: 2 }, {});
      expect(values(prefix, 2)).toEqual(expected.slice(0, count));
    }
  });

  it('keeps bands, empty inputs and short histories aligned', () => {
    const result = MFI.calc(bars([1, 2]), { period: 2 }, {});
    expect(result).toEqual({ mfi: [null, null], upperLevel: [80, 80], lowerLevel: [20, 20] });
    expect(MFI.calc([], {}, {})).toEqual({ mfi: [], upperLevel: [], lowerLevel: [] });
  });
});
