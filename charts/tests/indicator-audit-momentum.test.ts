import { describe, it, expect } from 'vitest';
import { MACD, ADX } from '../src/indicators/momentum';
import type { Bar } from '../src/model/bar';

/**
 * Momentum-group parity against the standard definitions. Every expectation
 * below is worked out by hand from the definition on a series small enough to
 * follow, not read back out of the implementation.
 */

const closeBars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 }));

const ohlcBars = (rows: readonly [number, number, number][]): Bar[] =>
  rows.map(([high, low, close], i) => ({
    time: 1700000000 + i * 60, open: close, high, low, close, volume: 100,
  }));

/** 120 bars with no flat stretches, enough to see where each study starts. */
const wave = (n = 120): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 5) * 10 + i * 0.05;
    return { time: 1700000000 + i * 60, open: c, high: c + 1.5, low: c - 1.5, close: c, volume: 100 + i };
  });

const firstFinite = (col: readonly (number | null)[]): number =>
  col.findIndex((v) => v !== null);

describe('MACD uses SMA-seeded exponential averages', () => {
  // Closes 10, 11, 12, 11, 13, 14, 13 with fast 2, slow 3, signal 2.
  //
  // ema2 seeds at index 1 with (10+11)/2 = 10.5, then k = 2/3:
  //   [na, 10.5, 11.5, 11.1666667, 12.3888889, 13.462963, 13.154321]
  // ema3 seeds at index 2 with (10+11+12)/3 = 11, then k = 1/2:
  //   [na, na, 11, 11, 12, 13, 13]
  // macd = fast - slow:
  //   [na, na, 0.5, 0.1666667, 0.3888889, 0.462963, 0.154321]
  // The signal is an ema2 over that, counting its window from the first real
  // macd value at index 2, so it seeds at index 3 with (0.5 + 0.1666667)/2.
  const data = closeBars([10, 11, 12, 11, 13, 14, 13]);
  const settings = { fastPeriod: 2, slowPeriod: 3, signalPeriod: 2, source: 'close' };

  it('leaves the slow average warmup blank instead of printing from bar 0', () => {
    const out = MACD.calc(data, settings, {});
    expect(out.macd[0]).toBeNull();
    expect(out.macd[1]).toBeNull();
    expect(out.macd[2]).toBeCloseTo(0.5, 12);
  });

  it('matches the hand-computed MACD line', () => {
    const out = MACD.calc(data, settings, {});
    expect(out.macd[3] as number).toBeCloseTo(1 / 6, 12);
    expect(out.macd[4] as number).toBeCloseTo(0.3888888888888889, 12);
    expect(out.macd[5] as number).toBeCloseTo(0.46296296296296297, 12);
    expect(out.macd[6] as number).toBeCloseTo(0.15432098765432098, 12);
  });

  it('starts the signal window at the first real MACD value', () => {
    const out = MACD.calc(data, settings, {});
    expect(out.signal.slice(0, 3)).toEqual([null, null, null]);
    // (0.5 + 1/6) / 2
    expect(out.signal[3] as number).toBeCloseTo(1 / 3, 12);
    // 0.3888888889 * (2/3) + (1/3) * (1/3)
    expect(out.signal[4] as number).toBeCloseTo(0.37037037037037035, 12);
    expect(out.signal[5] as number).toBeCloseTo(0.43209876543209874, 12);
    expect(out.signal[6] as number).toBeCloseTo(0.24691358024691357, 12);
  });

  it('carries the warmup through to the histogram', () => {
    const out = MACD.calc(data, settings, {});
    expect(out.histogram.slice(0, 3)).toEqual([null, null, null]);
    expect(out.histogram[3] as number).toBeCloseTo(1 / 6 - 1 / 3, 12);
    expect(out.histogram[6] as number).toBeCloseTo(0.15432098765432098 - 0.24691358024691357, 12);
  });

  it('prints the default study from bar 25 and its signal from bar 33', () => {
    // Slow length 26 seeds at index 25; the signal's own 9-bar window then
    // counts from there and seeds 8 bars later.
    const out = MACD.calc(wave(), { fastPeriod: 12, slowPeriod: 26, signalPeriod: 9, source: 'close' }, {});
    expect(firstFinite(out.macd)).toBe(25);
    expect(firstFinite(out.signal)).toBe(33);
    expect(firstFinite(out.histogram)).toBe(33);
  });
});

describe('ADX smooths a true range that has no bar-0 value', () => {
  // high, low, close. Bar 0 carries a deliberately wide high-low so that a
  // fabricated bar-0 true range would show up in every later average.
  //
  //   tr  = [na, 2, 2, 2, 3, 2]
  //   +DM = [na, 1, 1, 0, 2, 0]     -DM = [na, 0, 0, 1, 0, 1]
  //
  // With DI length 2, the true-range average counts from bar 1 and seeds at
  // bar 2 with (2+2)/2 = 2, then 2, 2.5, 2.25. The DM averages cover the
  // same transitions and seed at bar 2: +DM 1, 0.5, 1.25, 0.625 and
  // -DM 0, 0.5, 0.25, 0.625.
  const data = ohlcBars([
    [10, 4, 9],
    [11, 9, 10],
    [12, 10, 11],
    [11, 9, 10],
    [13, 11, 12],
    [12, 10, 11],
  ]);
  const settings = { period: 2, adxPeriod: 2 };

  it('holds the directional indicators back until a real true range exists', () => {
    const out = ADX.calc(data, settings, {});
    expect(out.plusDi[0]).toBeNull();
    expect(out.plusDi[1]).toBeNull();
    expect(out.minusDi[1]).toBeNull();
  });

  it('matches the hand-computed +DI and -DI', () => {
    const out = ADX.calc(data, settings, {});
    expect(out.plusDi[2] as number).toBeCloseTo(50, 10);     // 1 / 2
    expect(out.minusDi[2] as number).toBeCloseTo(0, 10);
    expect(out.plusDi[3] as number).toBeCloseTo(25, 10);     // 0.5 / 2
    expect(out.minusDi[3] as number).toBeCloseTo(25, 10);    // 0.5 / 2
    expect(out.plusDi[4] as number).toBeCloseTo(50, 10);     // 1.25 / 2.5
    expect(out.minusDi[4] as number).toBeCloseTo(10, 10);    // 0.25 / 2.5
    expect(out.plusDi[5] as number).toBeCloseTo(250 / 9, 10);
    expect(out.minusDi[5] as number).toBeCloseTo(250 / 9, 10);
  });

  it('excludes the absent bar-0 transition from both movement averages', () => {
    // Bar 0 has no previous bar. Both movement and true-range seeds therefore
    // describe transitions 1 and 2, yielding +DM 1 over true range 2.
    const out = ADX.calc(data, settings, {});
    expect(out.plusDi[2] as number).toBeCloseTo(50, 10);
  });

  it('matches the hand-computed ADX', () => {
    const out = ADX.calc(data, settings, {});
    // dx = 100, 0, 200/3, 0 from bar 2, smoothed over 2.
    expect(out.adx[2]).toBeNull();
    expect(out.adx[3] as number).toBeCloseTo(50, 10);
    expect(out.adx[4] as number).toBeCloseTo(175 / 3, 10);
    expect(out.adx[5] as number).toBeCloseTo(175 / 6, 10);
  });

  it('prints the default study from bar 14 and the ADX line from bar 27', () => {
    const out = ADX.calc(wave(), { period: 14, adxPeriod: 14 }, {});
    expect(firstFinite(out.plusDi)).toBe(14);
    expect(firstFinite(out.minusDi)).toBe(14);
    expect(firstFinite(out.adx)).toBe(27);
  });
});
