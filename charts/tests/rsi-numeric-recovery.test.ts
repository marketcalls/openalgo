import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { rsi, rsiSeries } from '../src/indicators/rsi';
import { RSI } from '../src/indicators/momentum';
import { RSI_DIVERGENCE } from '../src/indicators/signals';
import { STOCHASTIC_RSI } from '../src/indicators/ranges';
import { CONNORS_RSI } from '../src/indicators/oscillators';
import { ALPHATREND } from '../src/indicators/studies';
import { indicatorDefaults } from '../src/model/indicator-registry';

const cases = [
  { name: 'ordinary first-window arithmetic', period: 2,
    values: [1, 2, 1, 2, 3, 2], expected: [NaN, NaN, 50, 75, 87.5, 43.75] },
  { name: 'leading missing observations', period: 2,
    values: [NaN, 1, 2, 3, 2, 3], expected: [NaN, NaN, NaN, 100, 50, 75] },
  { name: 'missing deltas after seeding', period: 2,
    values: [1, 2, 1, NaN, 2, 3, 2], expected: [NaN, NaN, 50, NaN, NaN, 75, 37.5] },
  { name: 'overflowing subtraction', period: 2,
    values: [0, 1, 0, 1e308, -1e308, 0, 1, 2], expected: [NaN, NaN, 50, 100, NaN, 100, 100, 100] },
  { name: 'independent leg seeding after an overflowing seed', period: 3,
    values: [0, 1e308, 0, 1e308, 1e308, 1e308, 1e308], expected: [NaN, NaN, NaN, NaN, 60, 60, 60] },
  { name: 'committed running overflow', period: 2,
    values: [0, 1e308, 0, 1.7e308, 1.7e308, 1.7e308], expected: [NaN, NaN, 50, NaN, NaN, NaN] },
] as const;

const bars = (values: readonly number[]): Bar[] => values.map((close, i) => ({
  time: 1700000000 + i * 60, open: close, high: close + 1, low: close - 1, close, volume: 1,
}));
const nullable = (values: readonly number[]) => values.map((value) => Number.isNaN(value) ? null : value);

// This finite-only reference keeps the established first-window sum and recurrence
// order. Boundary expectations above are derived separately, not from this loop.
function finiteReference(values: readonly number[], period: number): number[] {
  const changes = values.slice(1).map((value, i) => value - values[i]);
  const up = changes.map((value) => Math.max(value, 0));
  const down = changes.map((value) => Math.max(-value, 0));
  const result = Array<number>(values.length).fill(NaN);
  let gain = up.slice(0, period).reduce((total, value) => total + value, 0) / period;
  let loss = down.slice(0, period).reduce((total, value) => total + value, 0) / period;
  for (let i = period; i < values.length; i++) {
    if (i > period) {
      gain = (gain * (period - 1) + up[i - 1]) / period;
      loss = (loss * (period - 1) + down[i - 1]) / period;
    }
    result[i] = loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
  }
  return result;
}

describe('RSI unavailable deltas and finite seeding', () => {
  for (const fixture of cases) {
    it(fixture.name, () => {
      expect(rsi(Object.freeze([...fixture.values]), fixture.period)).toEqual(fixture.expected);
    });
  }

  it('seeds the loss leg later without resetting the already seeded gain leg', () => {
    // The loss seed overflows at index 3. At index 4 it is 1e308/3,
    // while the gain leg has advanced to ((1e308/3)*2)/3.
    const gain = ((1e308 / 3) * 2) / 3;
    const expected = 100 - 100 / (1 + gain / (1e308 / 3));
    const result = rsi([0, -1e308, 0, -1e308, -1e308], 3);
    expect(result).toEqual([NaN, NaN, NaN, NaN, expected]);
  });

  it('does not use a zero loss shortcut while the gain seed is unavailable', () => {
    expect(rsi([0, 1e308, 1.7e308, 1.79e308, 1.79e308], 3))
      .toEqual([NaN, NaN, NaN, 100, 100]);
    // A finite delta can contribute to a mean whose sequential sum overflows.
    expect(rsi([-1e308, 0, 1e308, 1e308], 2)).toEqual([NaN, NaN, NaN, 100]);
  });

  it('retains an overflowing running loss rather than emitting zero or reseeding', () => {
    expect(rsi([0, -1e308, 0, -1.7e308, NaN, -1.7e308, -1.7e308], 2))
      .toEqual([NaN, NaN, 50, NaN, NaN, NaN, NaN]);
  });

  it('requires a complete finite suffix after multiple preseed gaps', () => {
    expect(rsi([NaN, 1, 2, NaN, 4, 5, 6, 5], 2))
      .toEqual([NaN, NaN, NaN, NaN, NaN, NaN, 100, 50]);
    expect(rsi([1, Infinity, 2, 3, 4], 2)).toEqual([NaN, NaN, NaN, NaN, 100]);
  });

  it('handles unit length, flat windows, and an overflowing ratio of finite averages', () => {
    expect(rsi([1, 2, NaN, 3, 2, 2], 1)).toEqual([NaN, 100, NaN, NaN, 0, 100]);
    expect(rsi([7, 7, 7, 7], 2)).toEqual([NaN, NaN, 100, 100]);
    expect(rsi([0, -1e-300, 1e308], 2)).toEqual([NaN, NaN, 100]);
  });

  it('preserves ordinary finite arithmetic bit for bit at each supported test length', () => {
    const values = Array.from({ length: 1500 }, (_, i) => 100 + (i * 17 % 131) / 8 + i / 128);
    for (const period of [1, 2, 3, 14, 50, 500]) {
      expect(rsi(values, period)).toEqual(finiteReference(values, period));
    }
    expect(rsi([], 14)).toEqual([]);
    expect(rsi([1, 2], 2)).toEqual([NaN, NaN]);
    expect(() => rsi([1, 2], 0)).toThrow('period must be > 0');
  });

  it('keeps ordinary source reads linear even with a large seed window', () => {
    const data = Array.from({ length: 5000 }, (_, i) => 100 + i % 13);
    let reads = 0;
    const observed = new Proxy(data, {
      get(target, key, receiver): unknown {
        if (typeof key === 'string' && /^\d+$/.test(key)) reads++;
        return Reflect.get(target, key, receiver);
      },
    });
    expect(rsi(observed, 500)).toEqual(finiteReference(data, 500));
    expect(reads).toBeLessThanOrEqual(2 * data.length + 2 * 500);
  });

  it('recalculates forming tails without retaining a transient overflow or gap', () => {
    const original = [0, 1e308, 0, 0];
    const before = rsi(original, 2);
    expect(before).toEqual([NaN, NaN, 50, 50]);
    expect(rsi([...original.slice(0, -1), 1.7e308], 2)).toEqual([NaN, NaN, 50, NaN]);
    expect(rsi([...original.slice(0, -1), NaN], 2)).toEqual([NaN, NaN, 50, NaN]);
    expect(rsi(original, 2)).toEqual(before);
  });

  it('keeps plottable wrapper timestamps and unavailable OHLC slots', () => {
    const fixture = cases[2];
    const data = bars(fixture.values);
    expect(rsiSeries(data, fixture.period)).toEqual(fixture.expected.map((value, i) => ({
      time: data[i].time, open: value, high: value, low: value, close: value,
    })));
  });
});

describe('built-in RSI consumers', () => {
  it('uses corrected values in the RSI and divergence plots', () => {
    for (const fixture of cases) {
      for (const descriptor of [RSI, RSI_DIVERGENCE]) {
        const result = descriptor.calc(bars(fixture.values), {
          ...indicatorDefaults(descriptor), length: fixture.period,
        }, {});
        expect(result.rsi).toEqual(nullable(fixture.expected));
      }
    }
  });

  it('allows Stochastic RSI to start after a leading gap', () => {
    const result = STOCHASTIC_RSI.calc(bars(cases[1].values), {
      ...indicatorDefaults(STOCHASTIC_RSI), lengthRSI: 2, lengthStoch: 2, smoothK: 1, smoothD: 1,
    }, {});
    expect(result.k).toEqual([null, null, null, null, 0, 100]);
    expect(result.d).toEqual(result.k);
  });

  it('allows both Connors RSI legs to recover after a leading gap', () => {
    const result = CONNORS_RSI.calc(bars(cases[1].values), {
      ...indicatorDefaults(CONNORS_RSI), lenrsi: 2, lenupdown: 2, lenroc: 1,
    }, {});
    // The price RSI is 75. Streak values -1,-2,1,2,-1,1 seed gain/loss
    // at 1.5/0.5 and end at 1.3125/0.8125. The last return is ranked 100.
    const streak = 100 - 100 / (1 + 1.3125 / 0.8125);
    expect(result.crsi[5]).toBe((75 + streak + 100) / 3);
  });

  it('allows AlphaTrend without volume to resume after a leading gap', () => {
    const result = ALPHATREND.calc(bars([NaN, 100, 101, 102, 101, 102]), {
      ...indicatorDefaults(ALPHATREND), AP: 2, novolumedata: true,
    }, {});
    expect(result.alphatrend).toEqual([null, null, null, 99, 99, 99]);
  });
});
