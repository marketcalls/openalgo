/**
 * Numeric parity for the volatility family, against the standard definition of
 * each study rather than against our own code. Every expectation below is
 * written out from the formula (or from a closed form derived on paper) and
 * never read back from the descriptor: an expectation copied out of the thing
 * under test proves only that the thing has not changed.
 *
 * Warmup is part of the contract here. A study read side by side with another
 * tool has to start on the same bar, so the first non-null index is asserted as
 * explicitly as the values are.
 */
import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import {
  BOLLINGER_PERCENT_B,
  BOLLINGER_BANDWIDTH,
  BB_TREND,
  CHOPPINESS_INDEX,
  HISTORICAL_VOLATILITY,
  AVERAGE_DAILY_RANGE,
  CHAIKIN_VOLATILITY,
  STANDARD_DEVIATION,
  STANDARD_ERROR,
} from '../src/indicators/volatility';

const settingsOf = (d: IndicatorDescriptor, over: Record<string, unknown> = {}): IndicatorSettings =>
  ({ ...indicatorDefaults(d), ...over }) as IndicatorSettings;

const firstNonNull = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

/** Closes only. High and low sit on the close, so the bar range is zero. */
const closeBars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1700000000 + i * 60, open: c, high: c, low: c, close: c, volume: 100 }));

/** A fixed close with an explicit high-to-low range, for the range-driven studies. */
const rangeBars = (ranges: readonly number[]): Bar[] =>
  ranges.map((r, i) => ({
    time: 1700000000 + i * 60,
    open: 100,
    high: 100 + r / 2,
    low: 100 - r / 2,
    close: 100,
    volume: 100,
  }));

describe('Chaikin Volatility', () => {
  // periods 3 gives the EMA alpha 2/(3+1) = 0.5, so the whole series can be
  // carried in the head: seed (2+4+6)/3 = 4, then halfway to each new range.
  const ranges = [2, 4, 6, 8, 10, 12];
  const s = settingsOf(CHAIKIN_VOLATILITY, { periods: 3, rocLookback: 2 });

  it('is the rate of change of an EMA-smoothed bar range', () => {
    const out = CHAIKIN_VOLATILITY.calc(rangeBars(ranges), s, {}).chaikinVolatility;
    // ema = [-, -, 4, 6, 8, 10]; the lookback reads two bars back.
    expect(out[4]).toBeCloseTo((100 * (8 - 4)) / 4, 12); // 100
    expect(out[5]).toBeCloseTo((100 * (10 - 6)) / 6, 12); // 66.666...
  });

  it('smooths exponentially, not simply', () => {
    // A simple 3-bar average of the same ranges gives 4, 6, 8, 10 as well on
    // this arithmetic ramp, so the ramp alone cannot tell the two apart. One
    // step change does: ranges 1, 1, 1, 7 leave the SMA at 3 and the EMA at 4.
    const out = CHAIKIN_VOLATILITY.calc(rangeBars([1, 1, 1, 7, 1, 1]), settingsOf(CHAIKIN_VOLATILITY, { periods: 3, rocLookback: 1 }), {}).chaikinVolatility;
    // ema = [-, -, 1, 4, 2.5, 1.75]; sma would be [-, -, 1, 3, 3, 3].
    expect(out[3]).toBeCloseTo((100 * (4 - 1)) / 1, 12); // 300, not the 200 an SMA gives
  });

  it('starts at (periods - 1) + rocLookback and nowhere earlier', () => {
    const out = CHAIKIN_VOLATILITY.calc(rangeBars(ranges), s, {}).chaikinVolatility;
    expect(firstNonNull(out)).toBe(4);
    const dflt = CHAIKIN_VOLATILITY.calc(rangeBars(Array.from({ length: 40 }, (_, i) => 1 + i)), settingsOf(CHAIKIN_VOLATILITY), {}).chaikinVolatility;
    expect(firstNonNull(dflt)).toBe(19); // (10 - 1) + 10 at the shipped defaults
  });

  it('gaps rather than diverging when the earlier smoothed range is zero', () => {
    // Five flat bars (high === low) hold the EMA at 0, so the rate of change has
    // no base to divide by until a real range has worked through the smoother.
    const out = CHAIKIN_VOLATILITY.calc(rangeBars([0, 0, 0, 0, 0, 4, 4, 4]), s, {}).chaikinVolatility;
    expect(out[4]).toBeNull();
    expect(out[5]).toBeNull();
    expect(out[6]).toBeNull();
    // ema = [-, -, 0, 0, 0, 2, 3, 3.5]; bar 7 divides by the 2 at bar 5.
    expect(out[7]).toBeCloseTo((100 * (3.5 - 2)) / 2, 12); // 75
  });
});

describe('Standard Deviation', () => {
  // Population standard deviation of 1..5: mean 3, squared deviations
  // 4 + 1 + 0 + 1 + 4 = 10, divided by 5 (not by 4), so the answer is sqrt(2).
  const ramp = closeBars([1, 2, 3, 4, 5]);

  it('divides by n, not by n - 1', () => {
    const out = STANDARD_DEVIATION.calc(ramp, settingsOf(STANDARD_DEVIATION, { periods: 5 }), {}).stdDev;
    expect(out[4]).toBeCloseTo(Math.sqrt(2), 12);
    expect(out[4]).not.toBeCloseTo(Math.sqrt(10 / 4), 6); // the sample reading
  });

  it('scales by the deviations multiplier', () => {
    const out = STANDARD_DEVIATION.calc(ramp, settingsOf(STANDARD_DEVIATION, { periods: 5, deviations: 2.5 }), {}).stdDev;
    expect(out[4]).toBeCloseTo(2.5 * Math.sqrt(2), 12);
  });

  it('starts at periods - 1', () => {
    const out = STANDARD_DEVIATION.calc(ramp, settingsOf(STANDARD_DEVIATION, { periods: 5 }), {}).stdDev;
    expect(firstNonNull(out)).toBe(4);
    const dflt = STANDARD_DEVIATION.calc(ramp, settingsOf(STANDARD_DEVIATION), {}).stdDev;
    expect(firstNonNull(dflt)).toBe(4); // the shipped default period is 5
  });

  it('reads zero, not a gap, on a flat window', () => {
    const out = STANDARD_DEVIATION.calc(closeBars([7, 7, 7, 7, 7]), settingsOf(STANDARD_DEVIATION, { periods: 5 }), {}).stdDev;
    expect(out[4]).toBe(0);
  });
});

describe('Standard Error', () => {
  /**
   * Length 3 over closes 1, 2, 10. Positions run 1, 2, 3 across the window, so
   * the abscissa mean is 2 and its spread Sxx is 1 + 0 + 1 = 2. The close mean
   * is 13/3, giving Syy = (17^2 + 7^2 + 10^2) / 9 = 146/3 and Sxy = -9.
   * Syy - Sxy^2 / Sxx = 146/3 - 81/2 = 49/6, and with length - 2 = 1 degree of
   * freedom left the answer is sqrt(49/6) = 7 / sqrt(6).
   *
   * Confirmed a second way, off the residuals rather than the identity: the
   * fitted line is 40/3 - 4.5x, its residuals are 7/6, -7/3 and 7/6, and their
   * squares sum to 49/6 as well.
   */
  const three = closeBars([1, 2, 10]);

  it('is the residual spread about the fitted line', () => {
    const out = STANDARD_ERROR.calc(three, settingsOf(STANDARD_ERROR, { length: 3 }), {}).stdErr;
    expect(out[2]).toBeCloseTo(7 / Math.sqrt(6), 12);
  });

  it('consumes two degrees of freedom, not one and not none', () => {
    const out = STANDARD_ERROR.calc(three, settingsOf(STANDARD_ERROR, { length: 3 }), {}).stdErr;
    expect(out[2]).not.toBeCloseTo(Math.sqrt(49 / 12), 6); // the n - 1 reading
    expect(out[2]).not.toBeCloseTo(Math.sqrt(49 / 18), 6); // the n reading
  });

  it('holds at a longer window', () => {
    // Length 4 over 1, 2, 4, 8. Abscissa mean 2.5, Sxx = 5. Close mean 3.75,
    // Syy = 28.75, Sxy = -11.5, so the answer is sqrt((28.75 - 26.45) / 2).
    const out = STANDARD_ERROR.calc(closeBars([1, 2, 4, 8]), settingsOf(STANDARD_ERROR, { length: 4 }), {}).stdErr;
    expect(out[3]).toBeCloseTo(Math.sqrt(1.15), 12);
  });

  it('reads zero on a perfectly straight run and on a flat one', () => {
    const line = STANDARD_ERROR.calc(closeBars([10, 20, 30, 40, 50]), settingsOf(STANDARD_ERROR, { length: 5 }), {}).stdErr;
    expect(line[4]).toBeCloseTo(0, 10);
    const flat = STANDARD_ERROR.calc(closeBars([7, 7, 7, 7, 7]), settingsOf(STANDARD_ERROR, { length: 5 }), {}).stdErr;
    expect(flat[4]).toBeCloseTo(0, 12);
  });

  it('starts at length - 1', () => {
    const out = STANDARD_ERROR.calc(three, settingsOf(STANDARD_ERROR, { length: 3 }), {}).stdErr;
    expect(firstNonNull(out)).toBe(2);
    const dflt = STANDARD_ERROR.calc(closeBars(Array.from({ length: 30 }, (_, i) => 100 + i * i * 0.01)), settingsOf(STANDARD_ERROR), {}).stdErr;
    expect(firstNonNull(dflt)).toBe(13); // the shipped default length is 14
  });
});

describe('Choppiness Index', () => {
  /**
   * Three bars, hand-built so that the previous close matters:
   *   bar 0  h 10  l 8   c 9    true range 2 (no prior close, so high - low)
   *   bar 1  h 12  l 10  c 11   true range max(2, |12-9|, |10-9|) = 3
   *   bar 2  h 11  l 9   c 10   true range max(2, |11-11|, |9-11|) = 2
   * With length 2 the travel sums to 5 on both bars 1 and 2, while the ranges
   * are 12 - 8 = 4 and 12 - 9 = 3. The scale divisor log10(2) turns the base-10
   * ratio into a base-2 one.
   */
  const data: Bar[] = [
    { time: 1, open: 9, high: 10, low: 8, close: 9, volume: 1 },
    { time: 2, open: 11, high: 12, low: 10, close: 11, volume: 1 },
    { time: 3, open: 10, high: 11, low: 9, close: 10, volume: 1 },
  ];

  it('sums true range against the previous close, not the bare bar range', () => {
    const out = CHOPPINESS_INDEX.calc(data, settingsOf(CHOPPINESS_INDEX, { length: 2 }), {}).chop;
    expect(out[1]).toBeCloseTo(100 * Math.log2(5 / 4), 11);
    // Ignoring the previous close would sum 2 + 2 = 4 against a range of 4 and
    // read exactly 0, which is the shape this pin exists to reject.
    expect(out[1]).not.toBeCloseTo(0, 6);
    expect(out[2]).toBeCloseTo(100 * Math.log2(5 / 3), 11);
  });

  it('takes its extremes from the highs and the lows, and starts at length - 1', () => {
    const out = CHOPPINESS_INDEX.calc(data, settingsOf(CHOPPINESS_INDEX, { length: 2 }), {}).chop;
    expect(firstNonNull(out)).toBe(1);
  });
});

describe('Historical Volatility', () => {
  // Closes alternating 100 and 200 make every log return plus or minus ln 2.
  // A ten-bar window holds five of each, so the mean is zero and the population
  // standard deviation is exactly ln 2.
  const flip = closeBars(Array.from({ length: 14 }, (_, i) => (i % 2 === 0 ? 100 : 200)));

  it('annualises the standard deviation of log returns over 365 days', () => {
    const out = HISTORICAL_VOLATILITY.calc(flip, settingsOf(HISTORICAL_VOLATILITY, { length: 10 }), {}).hv;
    expect(out[10]).toBeCloseTo(100 * Math.log(2) * Math.sqrt(365), 10);
  });

  it('divides the year by the days-per-bar-unit input', () => {
    const out = HISTORICAL_VOLATILITY.calc(flip, settingsOf(HISTORICAL_VOLATILITY, { length: 10, per: 7 }), {}).hv;
    expect(out[10]).toBeCloseTo(100 * Math.log(2) * Math.sqrt(365 / 7), 10);
  });

  it('starts at length, not length - 1, because the first bar has no return', () => {
    const out = HISTORICAL_VOLATILITY.calc(flip, settingsOf(HISTORICAL_VOLATILITY, { length: 10 }), {}).hv;
    expect(firstNonNull(out)).toBe(10);
  });
});

describe('Bollinger readings of one basis', () => {
  // Closes 1..5 with length 5: basis 3, population deviation sqrt(2), so at
  // mult 2 the band spread is 4 * sqrt(2) and the close sits at 5.
  const ramp = closeBars([1, 2, 3, 4, 5]);
  const spread = 4 * Math.SQRT2;

  it('places %b at (close - lower) / (upper - lower)', () => {
    const out = BOLLINGER_PERCENT_B.calc(ramp, settingsOf(BOLLINGER_PERCENT_B, { length: 5 }), {}).percentB;
    expect(out[4]).toBeCloseTo((5 - (3 - 2 * Math.SQRT2)) / spread, 12);
    expect(firstNonNull(out)).toBe(4);
  });

  it('gaps %b on a flat window rather than inventing a position in a zero-width band', () => {
    const out = BOLLINGER_PERCENT_B.calc(closeBars([7, 7, 7, 7, 7]), settingsOf(BOLLINGER_PERCENT_B, { length: 5 }), {}).percentB;
    expect(out[4]).toBeNull();
  });

  /**
   * BandWidth is shipped in its percentage form, the band spread as a percentage
   * of the basis. The ratio itself matches the standard definition exactly; the
   * factor of 100 is the convention this study is published under, alongside the
   * expansion and contraction lookbacks it carries, and is deliberate.
   */
  it('reports BandWidth as a percentage of the basis', () => {
    const out = BOLLINGER_BANDWIDTH.calc(ramp, settingsOf(BOLLINGER_BANDWIDTH, { length: 5 }), {}).bandwidth;
    expect(out[4]).toBeCloseTo((spread / 3) * 100, 11);
  });
});

describe('BBTrend and Average Daily Range', () => {
  it('reads BBTrend as the band-by-band spread over the short basis', () => {
    // Closes 1..5, short length 2 and long length 4 at mult 1. At bar 3 the
    // short set is basis 3.5 with deviation 0.5, so 3 and 4; the long set is
    // basis 2.5 with deviation sqrt(5)/2. The lower gap is 0.5 + sqrt(5)/2 and
    // the upper gap is 1.5 - sqrt(5)/2, so their difference is sqrt(5) - 1.
    const out = BB_TREND.calc(
      closeBars([1, 2, 3, 4, 5]),
      settingsOf(BB_TREND, { shortLength: 2, longLength: 4, stdDevMult: 1 }),
      {},
    ).bbtrend;
    expect(out[3]).toBeCloseTo(((Math.sqrt(5) - 1) / 3.5) * 100, 11);
  });

  it('measures each band gap as a distance, so a falling series reads negative', () => {
    // The mirror of the case above. Closes 5..1 put the short set inside the
    // long one on both sides, so both raw differences are negative and only
    // taking them as distances gives the correct sign: the lower gap is
    // 1.5 - sqrt(5)/2 and the upper is 0.5 + sqrt(5)/2, so the reading is
    // (1 - sqrt(5)) / 2.5. Dropping the distances flips the sign outright.
    const out = BB_TREND.calc(
      closeBars([5, 4, 3, 2, 1]),
      settingsOf(BB_TREND, { shortLength: 2, longLength: 4, stdDevMult: 1 }),
      {},
    ).bbtrend;
    expect(out[3]).toBeCloseTo(((1 - Math.sqrt(5)) / 2.5) * 100, 11);
  });

  it('averages the bar range for ADR and starts at length - 1', () => {
    const out = AVERAGE_DAILY_RANGE.calc(rangeBars([2, 4, 6, 8]), settingsOf(AVERAGE_DAILY_RANGE, { length: 3 }), {}).adr;
    expect(firstNonNull(out)).toBe(2);
    expect(out[2]).toBeCloseTo(4, 12);
    expect(out[3]).toBeCloseTo(6, 12);
  });
});
