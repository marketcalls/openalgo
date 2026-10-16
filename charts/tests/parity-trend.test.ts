import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import {
  SMA, WMA, EMA, BOLLINGER, VWAP, SUPERTREND, PARABOLIC_SAR, ICHIMOKU,
} from '../src/indicators/trend';

/**
 * Trend and overlay indicators measured against the standard definition of each.
 *
 * Every number below is derived by hand from the definition and written out in
 * the comment that carries it, never read back out of the implementation. Two
 * defects and one default set are pinned here:
 *
 *  - the plotted EMA seeded from bar 0 instead of from the simple mean of the
 *    first `length` values, which shifted the whole curve for roughly the first
 *    `length` bars and gave it a value where the definition has none;
 *  - Parabolic SAR clamping the stop into the prior two bars' range *before*
 *    testing for a reversal, and accelerating on its own seed bar. Both swallow
 *    flips the definition fires;
 *  - the three moving averages defaulting to a length of 20 where the standard
 *    default is 9.
 */

const barsFrom = (
  rows: readonly (readonly [number, number, number])[],
  volume = 1000,
): Bar[] => rows.map(([high, low, close], i) => ({
  time: 1735689600 + i * 900,
  open: close,
  high,
  low,
  close,
  volume,
}));

/** A unit ramp: close = 100 + i, with the bar straddling it by one. */
const ramp = (n: number): Bar[] =>
  barsFrom(Array.from({ length: n }, (_, i) => [101 + i, 99 + i, 100 + i] as const));

const closes = (values: readonly number[]): Bar[] =>
  barsFrom(values.map((c) => [c, c, c] as const));

const firstFinite = (col: readonly (number | null)[]): number =>
  col.findIndex((v) => v !== null && Number.isFinite(v));

const defaultOf = (d: { inputs: readonly { key: string; default?: unknown }[] }, key: string): unknown =>
  d.inputs.find((i) => i.key === key)?.default;

describe('moving average defaults follow the standard definition', () => {
  // The standard default length for a plain, exponential and weighted moving
  // average is 9. This library shipped 20, so a chart saved before this change
  // draws a different line after it. That is the intended, recorded consequence.
  it('SMA, EMA and WMA all default to a length of 9', () => {
    expect(defaultOf(SMA, 'length')).toBe(9);
    expect(defaultOf(EMA, 'length')).toBe(9);
    expect(defaultOf(WMA, 'length')).toBe(9);
  });

  it('SMA at its default length is the mean of the last nine closes', () => {
    const out = SMA.calc(ramp(14), indicatorDefaults(SMA), {}).ma;
    // Nothing before the window is full, so the first value lands at index 8.
    expect(firstFinite(out)).toBe(8);
    // closes 100..108, mean 104.
    expect(out[8]).toBeCloseTo(104, 12);
    // closes 101..109, mean 105.
    expect(out[9]).toBeCloseTo(105, 12);
  });

  it('WMA at its default length weights the newest close nine times', () => {
    const out = WMA.calc(ramp(14), indicatorDefaults(WMA), {}).ma;
    expect(firstFinite(out)).toBe(8);
    // sum((108-k)*(9-k), k=0..8) = 4740, over the weight total 45.
    expect(out[8]).toBeCloseTo(4740 / 45, 12);
  });
});

describe('EMA opens on the simple mean of its first window', () => {
  /*
   * The definition seeds the recursion with the simple average of the first
   * `length` values and emits nothing before it, then carries
   * `value * k + prev * (1 - k)` with `k = 2 / (length + 1)`. Seeding from the
   * first bar instead, as this descriptor did, both invents a value for every
   * warmup bar and biases the curve toward that single close for roughly
   * `length` bars afterwards.
   */
  it('emits nothing before the window is full', () => {
    const out = EMA.calc(ramp(14), indicatorDefaults(EMA), {}).ma;
    expect(out.slice(0, 8).every((v) => v === null)).toBe(true);
    expect(firstFinite(out)).toBe(8);
  });

  it('seeds on the mean of the first nine closes and then carries k = 0.2', () => {
    const out = EMA.calc(ramp(14), indicatorDefaults(EMA), {}).ma;
    // closes 100..108, mean 104.
    expect(out[8]).toBeCloseTo(104, 12);
    // 0.2*109 + 0.8*104 = 21.8 + 83.2.
    expect(out[9]).toBeCloseTo(105, 12);
    // 0.2*110 + 0.8*105 = 22 + 84.
    expect(out[10]).toBeCloseTo(106, 12);
    // 0.2*111 + 0.8*106 = 22.2 + 84.8.
    expect(out[11]).toBeCloseTo(107, 12);
  });

  it('holds the same seeding at a short length', () => {
    const out = EMA.calc(closes([1, 2, 3, 4, 5, 6, 7, 8]), { ...indicatorDefaults(EMA), length: 3 }, {}).ma;
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(out[2]).toBeCloseTo(2, 12);          // (1+2+3)/3, k = 2/4 = 0.5
    expect(out[3]).toBeCloseTo(3, 12);          // 0.5*4 + 0.5*2
    expect(out[4]).toBeCloseTo(4, 12);          // 0.5*5 + 0.5*3
    expect(out[7]).toBeCloseTo(7, 12);
  });
});

describe('Parabolic SAR decides the reversal before it clamps the stop', () => {
  /*
   * The order of operations inside one bar is: propagate the stop toward the
   * extreme point, test whether the bar breached it, update the acceleration
   * only when it did not, and clamp last. Clamping first pulls the stop back
   * inside the prior two bars' range, where the bar can no longer reach it, so
   * a flip the definition fires is silently dropped.
   */
  it('leaves the seed bar on its seed rather than stepping and flipping on it', () => {
    // Rising, because close[1] >= close[0]. The stop seeds on low[0] = 98 and
    // the extreme point on high[1] = 101.
    const data = barsFrom([
      [100, 98, 99],
      [101, 97.5, 100],
      [102, 99, 101],
    ]);
    const out = PARABOLIC_SAR.calc(data, indicatorDefaults(PARABOLIC_SAR), {}).sar;
    expect(out[0]).toBeNull();
    // The seed itself, untouched. Stepping it to 98 + 0.02*(101-98) = 98.06 and
    // then testing low[1] = 97.5 against it reverses the trend on the very bar
    // that established it, which puts the stop at 101, above the whole series.
    expect(out[1]).toBeCloseTo(98, 12);
    // Bar 2: 98 + 0.02*(101-98) = 98.06, no breach (low 99), the extreme point
    // moves to 102 and the acceleration to 0.04, then the stop is clamped down
    // to min(98.06, low[1] = 97.5, low[0] = 98) = 97.5.
    expect(out[2]).toBeCloseTo(97.5, 12);
  });

  it('reverses on a stop the clamp would otherwise have hidden', () => {
    const data = barsFrom([
      [100, 99, 99.5],
      [110, 105, 109],
      [120, 112, 119],
      [125, 108, 124],
    ]);
    // A large, fixed acceleration so the stop closes on the extreme point in
    // three bars instead of thirty; the ordering under test does not depend on
    // the size of the step.
    const fast = { ...indicatorDefaults(PARABOLIC_SAR), start: 0.5, increment: 0.5, maximum: 0.5 };
    const out = PARABOLIC_SAR.calc(data, fast, {}).sar;
    // Rising: stop seeds on low[0] = 99, extreme point on high[1] = 110.
    expect(out[1]).toBeCloseTo(99, 12);
    // Bar 2: 99 + 0.5*(110-99) = 104.5, no breach (low 112), extreme point 120,
    // clamped to min(104.5, low[1] = 105, low[0] = 99) = 99.
    expect(out[2]).toBeCloseTo(99, 12);
    // Bar 3: 99 + 0.5*(120-99) = 109.5 and low[3] = 108 breaks it, so the trend
    // reverses and the stop becomes max(extreme 120, high[3] = 125) = 125.
    // Clamping first would have given min(109.5, 112, 105) = 105, which 108
    // never reaches, and the series would have stayed long at 105.
    expect(out[3]).toBeCloseTo(125, 12);
    expect(out[3] as number).toBeGreaterThan(data[3].high - 1e-9);
  });

  it('has no stop on the first bar, which has no predecessor to seed from', () => {
    const out = PARABOLIC_SAR.calc(ramp(30), indicatorDefaults(PARABOLIC_SAR), {}).sar;
    expect(firstFinite(out)).toBe(1);
  });
});

describe('warmup and vanishing denominators', () => {
  it('Bollinger collapses onto its basis on a flat window instead of dividing by nothing', () => {
    const flat = closes([100, 100, 100, 100, 100, 100]);
    const out = BOLLINGER.calc(flat, { ...indicatorDefaults(BOLLINGER), length: 3, stdDev: 2 }, {});
    expect(firstFinite(out.basis)).toBe(2);
    expect(out.basis[5]).toBeCloseTo(100, 12);
    // A zero standard deviation is a legitimate answer, not a gap: all three
    // lines sit on top of each other.
    expect(out.upper[5]).toBeCloseTo(100, 12);
    expect(out.lower[5]).toBeCloseTo(100, 12);
  });

  it('VWAP carries a zero-volume bar rather than dividing by it', () => {
    const data = ramp(5);
    data[2].volume = 0;
    const out = VWAP.calc(data, { ...indicatorDefaults(VWAP), anchor: 'continuous', source: 'close' }, {});
    // Bar 2 contributes nothing to either accumulator, so the running average is
    // unchanged from bar 1: (100 + 101) * 1000 / 2000.
    expect(out.vwap[1]).toBeCloseTo(100.5, 12);
    expect(out.vwap[2]).toBeCloseTo(100.5, 12);
    // Bar 3 resumes: (100 + 101 + 103) * 1000 / 3000.
    expect(out.vwap[3]).toBeCloseTo(304 / 3, 12);
  });

  it('VWAP stays empty while every bar carries zero volume', () => {
    const data = ramp(5).map((b) => ({ ...b, volume: 0 }));
    const out = VWAP.calc(data, { ...indicatorDefaults(VWAP), anchor: 'continuous' }, {});
    expect(out.vwap.every((v) => v === null)).toBe(true);
  });

  it('Supertrend starts on the first bar its ATR has, and survives a zero range', () => {
    const flat = closes(Array.from({ length: 12 }, () => 100));
    const out = SUPERTREND.calc(flat, { ...indicatorDefaults(SUPERTREND), period: 5, multiplier: 3 }, {});
    const band = out.up.map((v, i) => (v !== null ? v : out.down[i]));
    // Wilder's ATR seeds on the mean of the first `period` true ranges, so the
    // first band lands at index period - 1.
    expect(firstFinite(band)).toBe(4);
    // Every range is zero, so both bands sit exactly on the midpoint.
    expect(band[11]).toBeCloseTo(100, 12);
  });

  it('Ichimoku warms each line up on its own window and displaces the spans', () => {
    const data = ramp(90);
    const out = ICHIMOKU.calc(data, indicatorDefaults(ICHIMOKU), {});
    // Conversion is the midpoint of the last 9 bars: (high[8] + low[0]) / 2.
    expect(firstFinite(out.conversion)).toBe(8);
    expect(out.conversion[8]).toBeCloseTo((109 + 99) / 2, 12);
    // Base is the same over 26 bars: (high[25] + low[0]) / 2.
    expect(firstFinite(out.base)).toBe(25);
    expect(out.base[25]).toBeCloseTo((126 + 99) / 2, 12);
    // Span A is the mean of the two, drawn 26 bars forward. At bar 25 the
    // conversion is (high[25] + low[17]) / 2 = (126 + 116) / 2 = 121 and the
    // base is 112.5, so (121 + 112.5) / 2 lands at index 51.
    expect(firstFinite(out.spanA)).toBe(51);
    expect(out.spanA[51]).toBeCloseTo(116.75, 12);
    // Span B is the 52-bar midpoint, first available at 51 and drawn at 77.
    expect(firstFinite(out.spanB)).toBe(77);
    expect(out.spanB[77]).toBeCloseTo((152 + 99) / 2, 12);
    // The lagging span is the close drawn 26 bars back, so index 0 holds close[26].
    expect(out.lagging[0]).toBeCloseTo(126, 12);
    expect(out.lagging[89 - 26]).toBeCloseTo(189, 12);
    expect(out.lagging[89 - 25]).toBeNull();
  });
});

describe('Ichimoku reads its periods and displacement as whole bars', () => {
  // A settings blob carries whatever a UI or a saved layout wrote. The other
  // built-ins round a window length to the nearest whole bar, at least one.
  // Ichimoku used the raw value as a bar index, so a conversion period of 9.4
  // read bar 8.4, which does not exist, and the whole calc threw a TypeError;
  // a displacement of 25.6 found no bar to copy and blanked the cloud.
  const data = ramp(90);
  const defaults = indicatorDefaults(ICHIMOKU);
  const whole = ICHIMOKU.calc(data, defaults, {});

  it('rounds a fractional conversion, base or lagging-span period instead of throwing', () => {
    const cases = [
      ['conversionPeriod', 9.4], ['conversionPeriod', 8.6],
      ['basePeriod', 26.4], ['basePeriod', 25.5],
      ['laggingSpanPeriod', 52.4], ['laggingSpanPeriod', 51.6],
    ] as const;
    for (const [key, value] of cases) {
      const label = `${key} ${value}`;
      expect(() => ICHIMOKU.calc(data, { ...defaults, [key]: value }, {}), label).not.toThrow();
      expect(ICHIMOKU.calc(data, { ...defaults, [key]: value }, {}), label).toEqual(whole);
    }
  });

  it('reads a period below one as the one-bar window, as the declared minimum says', () => {
    const one = ICHIMOKU.calc(data, { ...defaults, conversionPeriod: 1 }, {});
    // A one-bar midpoint is the bar's own (high + low) / 2, from bar 0.
    expect(one.conversion[0]).toBeCloseTo((101 + 99) / 2, 12);
    for (const value of [0.4, 0, -3]) {
      expect(ICHIMOKU.calc(data, { ...defaults, conversionPeriod: value }, {}), String(value)).toEqual(one);
    }
  });

  it('rounds a fractional displacement rather than blanking the cloud', () => {
    for (const value of [25.6, 26.4]) {
      expect(ICHIMOKU.calc(data, { ...defaults, displacement: value }, {}), String(value)).toEqual(whole);
    }
    // A whole displacement, negative included, is used as given.
    const back = ICHIMOKU.calc(data, { ...defaults, displacement: -2 }, {});
    expect(back.lagging[2]).toBeCloseTo(100, 12);
    expect(back.lagging[1]).toBeNull();
  });
});
