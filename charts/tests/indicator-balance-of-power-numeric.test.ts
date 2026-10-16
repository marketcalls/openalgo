import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/index';
import { BALANCE_OF_POWER } from '../src/indicators/oscillators';

const reading = (values: Omit<Bar, 'time'>): number | null =>
  BALANCE_OF_POWER.calc([{ time: 0, ...values }], {}, {}).bop[0];

describe('Balance of Power numeric boundaries', () => {
  it.each([
    [{ open: 2, high: 6, low: 0, close: 5 }, 0.5],
    [{ open: 5, high: 6, low: 0, close: 2 }, -0.5],
    [{ open: 3, high: 6, low: 0, close: 3 }, 0],
    [{ open: 0, high: Number.MIN_VALUE, low: 0, close: Number.MIN_VALUE }, 1],
  ] as const)('preserves the finite ratio for %j', (bar, expected) => {
    expect(reading(bar)).toBe(expected);
  });

  it('leaves a zero range undefined', () => {
    expect(reading({ open: 3, high: 3, low: 3, close: 3 })).toBeNull();
  });

  it.each(['open', 'high', 'low', 'close'] as const)('returns a gap for missing %s', (key) => {
    expect(reading({ open: 1, high: 4, low: 0, close: 3, [key]: NaN })).toBeNull();
  });

  it('normalizes the undefined ratio when both finite differences overflow', () => {
    expect(reading({ open: -1e308, high: 1e308, low: -1e308, close: 1e308 })).toBeNull();
  });

  it('rejects an overflowing numerator before division', () => {
    expect(reading({ open: -1e308, high: 1, low: 0, close: 1e308 })).toBeNull();
  });

  it('rejects an overflowing range even when division would yield zero', () => {
    expect(reading({ open: 0, high: 1e308, low: -1e308, close: 1 })).toBeNull();
  });

  it('normalizes an overflowing quotient of finite differences', () => {
    expect(reading({ open: 0, high: Number.MIN_VALUE, low: 0, close: 1 })).toBeNull();
  });

  it('keeps later bars independent after an undefined reading', () => {
    const bars: Bar[] = [
      { time: 0, open: -1e308, high: 1e308, low: -1e308, close: 1e308 },
      { time: 1, open: 2, high: 6, low: 0, close: 5 },
    ];
    expect(BALANCE_OF_POWER.calc(bars, {}, {}).bop).toEqual([null, 0.5]);
    expect(BALANCE_OF_POWER.calc([], {}, {}).bop).toEqual([]);
  });
});
