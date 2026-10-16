import { describe, it, expect } from 'vitest';
import {
  ALMA,
  DEMA,
  HMA,
  ENVELOPE,
  DONCHIAN,
  CHANDE_KROLL_STOP,
  CHANDELIER_EXIT,
  STANDARD_ERROR_BANDS,
  MA_CHANNEL,
  OVERLAY_INDICATORS,
} from '../src/indicators/overlay';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * Every expectation below is derived from the published definition of the study
 * and written out here by hand, never read back from the descriptor. Where a
 * closed form exists it is used in preference to a transcription, because a
 * transcription can repeat the same misreading as the code it checks.
 */

const bars = (n: number, close: (i: number) => number, spread: (i: number) => [number, number]): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = close(i);
    const [up, down] = spread(i);
    return { time: 1700000000 + i * 60, open: c, high: c + up, low: c - down, close: c, volume: 100 + i };
  });

/**
 * Closes step by one, the high sits 3 above and the low 1 below. The asymmetry
 * is the point: with a symmetric bar the extreme of the highs and the extreme of
 * the lows differ by a constant, which hides every mix-up between the two.
 */
const stepped = (n = 12): Bar[] => bars(n, (i) => 100 + i, () => [3, 1]);
/** A pure ramp, for the identities that only hold on a straight line. */
const ramp = (n = 40, a = 100, b = 0.5): Bar[] => bars(n, (i) => a + b * i, () => [1, 1]);
const flat = (n = 12): Bar[] => bars(n, () => 100, () => [1, 1]);

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);
const near = (got: number | null, want: number, eps = 1e-9): void => {
  expect(got).not.toBeNull();
  expect(Math.abs((got as number) - want)).toBeLessThan(eps);
};

describe('overlay catalogue', () => {
  it('registers ten studies in a stable order', () => {
    expect(OVERLAY_INDICATORS.map((d) => d.id)).toEqual([
      'alma',
      'dema',
      'hma',
      'envelope',
      'donchian',
      'chande-kroll-stop',
      'chandelier-exit',
      'standard-error-bands',
      'ma-channel',
      'hull-suite',
    ]);
    // Both channels draw on the price pane, so neither may ask for one of its own.
    expect(STANDARD_ERROR_BANDS.placement).toBe('onchart');
    expect(MA_CHANNEL.placement).toBe('onchart');
    expect(STANDARD_ERROR_BANDS.name).toBe('Standard Error Bands');
    expect(MA_CHANNEL.name).toBe('Moving Average Channel');
  });

  it('carries the reference default parameters', () => {
    const d = (desc: IndicatorDescriptor, key: string): unknown => indicatorDefaults(desc)[key];
    expect([d(ALMA, 'length'), d(ALMA, 'offset'), d(ALMA, 'sigma')]).toEqual([9, 0.85, 6]);
    expect(d(DEMA, 'length')).toBe(9);
    expect(d(HMA, 'length')).toBe(9);
    expect([d(ENVELOPE, 'length'), d(ENVELOPE, 'percent')]).toEqual([20, 10]);
    expect([d(DONCHIAN, 'length'), d(DONCHIAN, 'offset')]).toEqual([20, 0]);
    expect([d(CHANDE_KROLL_STOP, 'p'), d(CHANDE_KROLL_STOP, 'x'), d(CHANDE_KROLL_STOP, 'q')]).toEqual([10, 1, 9]);
    expect([d(CHANDELIER_EXIT, 'length'), d(CHANDELIER_EXIT, 'atrLength'), d(CHANDELIER_EXIT, 'atrMultiplier')])
      .toEqual([22, 22, 3]);
    expect([
      d(STANDARD_ERROR_BANDS, 'periods'),
      d(STANDARD_ERROR_BANDS, 'errors'),
      d(STANDARD_ERROR_BANDS, 'method'),
      d(STANDARD_ERROR_BANDS, 'averagePeriods'),
    ]).toEqual([21, 2, 'Simple', 3]);
    expect([
      d(MA_CHANNEL, 'upperLength'),
      d(MA_CHANNEL, 'lowerLength'),
      d(MA_CHANNEL, 'upperOffset'),
      d(MA_CHANNEL, 'lowerOffset'),
    ]).toEqual([20, 20, 0, 0]);
  });
});

describe('ALMA', () => {
  it('normalises its kernel, so a flat series returns the level itself', () => {
    const out = run(ALMA, flat(20)).alma;
    expect(firstIndex(out)).toBe(8);
    near(out[8], 100);
    near(out[19], 100);
  });

  it('weights the window by the Gaussian the definition specifies', () => {
    const data = ramp(20, 100, 2);
    const length = 5;
    const offset = 0.85;
    const sigma = 3;
    const out = run(ALMA, data, { length, offset, sigma }).alma;
    // Transcribed from the definition: peak at offset * (length - 1), width
    // length / sigma, weights indexed oldest to newest across the window.
    const m = offset * (length - 1);
    const s = length / sigma;
    let num = 0;
    let den = 0;
    for (let k = 0; k < length; k++) {
      const w = Math.exp(-((k - m) * (k - m)) / (2 * s * s));
      num += data[15 - (length - 1) + k].close * w;
      den += w;
    }
    expect(firstIndex(out)).toBe(length - 1);
    near(out[15], num / den);
  });
});

describe('DEMA', () => {
  /**
   * length 3 over closes 1, 2, 3, ... The inner average seeds at index 2 with
   * (1+2+3)/3 = 2 and then runs at alpha 1/2: 3, 4, 5, 6. The outer average sees
   * that series only from index 2, so it seeds at index 4 with (2+3+4)/3 = 3 and
   * runs 4, 5. `2 * inner - outer` is therefore 5 at bar 4, 6 at bar 5, 7 at bar 6,
   * and nothing at all before `2 * length - 2`.
   */
  it('re-seeds its second pass after the first pass warmup', () => {
    const data = bars(9, (i) => i + 1, () => [1, 1]);
    const out = run(DEMA, data, { length: 3 }).dema;
    expect(firstIndex(out)).toBe(4);
    near(out[4], 5);
    near(out[5], 6);
    near(out[6], 7);
  });

  it('reproduces the level on a flat series', () => {
    const out = run(DEMA, flat(40), { length: 9 }).dema;
    expect(firstIndex(out)).toBe(16);
    near(out[39], 100);
  });
});

describe('HMA', () => {
  /**
   * A whole-window weighted average lags a straight line by `(period - 1) / 3`.
   * Length 9 uses inner lengths 4 and 9 and smoothing length 3, so the combined
   * lag is `2 * 1 - 8/3 + 2/3 = 0`.
   */
  it('uses an integer half window on an odd length', () => {
    const data = ramp(30, 100, 1);
    const out = run(HMA, data, { length: 9 }).hma;
    expect(firstIndex(out)).toBe(10);
    near(out[10], 110);
    near(out[20], 120);
    near(out[29], 129);
  });

  it('rounds the smoothing length to the nearest whole window', () => {
    // Lengths 6, 13 and 4 give combined lag 2 * 5/3 - 4 + 1 = 1/3.
    const out = run(HMA, ramp(30, 100, 1), { length: 13 }).hma;
    expect(firstIndex(out)).toBe(15);
    near(out[20], 120 - 1 / 3);
  });

  it('carries the lag the same three windows imply at an even length', () => {
    // Length 16 halves to 8 and smooths over round(sqrt(16)) = 4, so the lag is
    // 2 * (7/3) - (15/3) + (3/3) = 2/3 of a bar rather than none.
    const out = run(HMA, ramp(40, 100, 1), { length: 16 }).hma;
    expect(firstIndex(out)).toBe(18);
    near(out[30], 130 - 2 / 3);
  });
});

describe('Envelope', () => {
  it('brackets a simple average by the percentage on both sides', () => {
    const data = stepped(12);
    const out = run(ENVELOPE, data, { length: 3, percent: 10 });
    // Mean of three consecutive closes ending at bar 5: (103 + 104 + 105) / 3.
    const basis = 104;
    expect(firstIndex(out.basis)).toBe(2);
    near(out.basis[5], basis);
    near(out.upper[5], basis * 1.1);
    near(out.lower[5], basis * 0.9);
  });

  it('seeds its exponential basis from a simple average of the first window', () => {
    // A step, not a ramp: on a straight line an exponential average and a simple
    // one of the same length carry an identical lag and the two are
    // indistinguishable. Closes hold at 100 and then jump to 110.
    const data = bars(8, (i) => (i < 3 ? 100 : 110), () => [1, 1]);
    const out = run(ENVELOPE, data, { length: 3, percent: 10, exponential: true });
    expect(firstIndex(out.basis)).toBe(2);
    // Seed (100 + 100 + 100) / 3, then alpha 2 / (3 + 1) onto the 110s.
    near(out.basis[2], 100);
    near(out.basis[3], 105);
    near(out.basis[4], 107.5);
    // The simple basis over the same bars is 103.3333 at bar 3, not 105.
    near(run(ENVELOPE, data, { length: 3, percent: 10 }).basis[3], 310 / 3);
  });
});

describe('Donchian channels', () => {
  const data = stepped(12);

  it('takes the extremes of the highs and the lows, and the midpoint of the two', () => {
    const out = run(DONCHIAN, data, { length: 3, offset: 0 });
    expect(firstIndex(out.upper)).toBe(2);
    // Bar 5 window is bars 3, 4, 5: highs 106..108, lows 102..104.
    near(out.upper[5], 108);
    near(out.lower[5], 102);
    near(out.basis[5], 105);
  });

  it('displaces the channel forward for a positive offset and back for a negative one', () => {
    const forward = run(DONCHIAN, data, { length: 3, offset: 2 });
    const backward = run(DONCHIAN, data, { length: 3, offset: -2 });
    // Forward: bar 7 carries what bar 5 computed. Backward: bar 3 does.
    near(forward.upper[7], 108);
    near(backward.upper[3], 108);
    expect(firstIndex(forward.upper)).toBe(4);
    // Nothing is drawn past the end of the data, so a forward shift loses its tail.
    expect(forward.upper[11]).not.toBeNull();
    expect(backward.upper[11]).toBeNull();
  });
});

describe('Chande Kroll Stop', () => {
  /**
   * Closes step by one with the high 3 above and the low 1 below, so every true
   * range is 4 and the average of them is 4 from bar 2 onward. At p = 3, x = 1,
   * q = 2 the padded legs are `highest(high, 3) - 4 = close - 1` and
   * `lowest(low, 3) + 4 = close + 1`, and the second pass over two bars leaves
   * the short stop at `close - 1` and the long stop at the previous bar's
   * `close + 1`, which on this series is the current close.
   *
   * The long stop is the discriminating half. Built on the lowest **high**
   * instead of the lowest low, as the reference implementation builds it, bar 5
   * would read 109 rather than 105.
   */
  const data = stepped(12);

  it('pads the extremes by the average true range and then runs a second extreme', () => {
    const out = run(CHANDE_KROLL_STOP, data, { p: 3, x: 1, q: 2 });
    expect(firstIndex(out.stopShort)).toBe(3);
    expect(firstIndex(out.stopLong)).toBe(3);
    near(out.stopShort[5], 104);
    near(out.stopLong[5], 105);
    near(out.stopShort[9], 108);
    near(out.stopLong[9], 109);
  });

  it('waits for the whole second window to clear the average true range warmup', () => {
    // p + q - 2 with p = 4 and q = 3.
    expect(firstIndex(run(CHANDE_KROLL_STOP, data, { p: 4, x: 1, q: 3 }).stopLong)).toBe(5);
    expect(firstIndex(run(CHANDE_KROLL_STOP, data, { p: 4, x: 1, q: 3 }).stopShort)).toBe(5);
  });

  it('yields nothing at all when the bars cannot fill both windows', () => {
    const out = run(CHANDE_KROLL_STOP, stepped(4), { p: 3, x: 1, q: 3 });
    expect(out.stopLong.every((v) => v === null)).toBe(true);
  });
});

describe('Chandelier Exit', () => {
  /**
   * No reference counterpart ships for this one, so it is held to the published
   * definition: the highest high of the window pulled down by `mult` average
   * true ranges, and the lowest low pushed up by the same.
   */
  it('hangs each stop off the opposite extreme', () => {
    const data = stepped(12);
    const out = run(CHANDELIER_EXIT, data, { length: 3, atrLength: 3, atrMultiplier: 1 });
    expect(firstIndex(out.longExit)).toBe(2);
    // Bar 5: highest high 108 less an average true range of 4; lowest low 102 plus 4.
    near(out.longExit[5], 104);
    near(out.shortExit[5], 106);
  });

  it('scales the pad by the multiplier', () => {
    const out = run(CHANDELIER_EXIT, stepped(12), { length: 3, atrLength: 3, atrMultiplier: 2.5 });
    near(out.longExit[5], 108 - 2.5 * 4);
    near(out.shortExit[5], 102 + 2.5 * 4);
  });
});

describe('Standard Error Bands', () => {
  /**
   * Window closes 0, 0, 3 with x running 1, 2, 3. The mean of x is 2 and the
   * mean of y is 1, so Sxx = 2, Sxy = 3 and Syy = 6. The fitted slope is 1.5 and
   * the line reaches 2.5 at the newest bar of the window. The residual sum of
   * squares is Syy - Sxy^2 / Sxx = 1.5, and the divisor is `periods - 2` = 1
   * because the slope and the intercept each cost a degree of freedom, so the
   * standard error is sqrt(1.5) = 1.224744871391589. Under the standard
   * deviation divisor `periods - 1` it would be sqrt(0.75) instead.
   */
  it('centres on the regression endpoint and spreads by the residual standard error', () => {
    const data = bars(6, (i) => (i % 3 === 2 ? 3 : 0), () => [1, 1]);
    const out = run(STANDARD_ERROR_BANDS, data, {
      periods: 3, errors: 1, method: 'Simple', averagePeriods: 1,
    });
    const se = Math.sqrt(1.5);
    expect(firstIndex(out.basis)).toBe(2);
    near(out.basis[2], 2.5);
    near(out.upper[2], 2.5 + se);
    near(out.lower[2], 2.5 - se);
    // The window repeats at bar 5, so the same three numbers must come back.
    near(out.basis[5], 2.5);
    near(out.upper[5], 2.5 + se);
  });

  it('collapses all three bands onto the line when the closes are exactly linear', () => {
    const data = ramp(30, 100, 2);
    const out = run(STANDARD_ERROR_BANDS, data, {
      periods: 5, errors: 2, method: 'Simple', averagePeriods: 1,
    });
    // A perfect fit leaves no residual, so the standard error is zero rather
    // than a small non-finite artefact of dividing by it.
    expect(firstIndex(out.basis)).toBe(4);
    near(out.basis[10], 120);
    near(out.upper[10], 120);
    near(out.lower[10], 120);
  });

  it('collapses onto a flat series without dividing by zero', () => {
    const out = run(STANDARD_ERROR_BANDS, flat(20), {
      periods: 5, errors: 2, method: 'Simple', averagePeriods: 1,
    });
    near(out.upper[10], 100);
    near(out.basis[10], 100);
    near(out.lower[10], 100);
  });

  it('smooths each leg on its own, which pushes the first bar out by the averaging window', () => {
    const data = ramp(40, 100, 2);
    const out = run(STANDARD_ERROR_BANDS, data, {
      periods: 5, errors: 2, method: 'Simple', averagePeriods: 4,
    });
    // (periods - 1) + (averagePeriods - 1).
    expect(firstIndex(out.basis)).toBe(7);
    expect(firstIndex(out.upper)).toBe(7);
    expect(firstIndex(out.lower)).toBe(7);
    // A simple average of an exact ramp lags it by (averagePeriods - 1) / 2 bars.
    near(out.basis[20], 100 + 2 * (20 - 1.5));
  });

  it('honours the weighted and exponential smoothing choices', () => {
    const data = ramp(40, 100, 2);
    const weighted = run(STANDARD_ERROR_BANDS, data, {
      periods: 5, errors: 2, method: 'Weighted', averagePeriods: 3,
    });
    const exponential = run(STANDARD_ERROR_BANDS, data, {
      periods: 5, errors: 2, method: 'Exponential', averagePeriods: 3,
    });
    // The weighted average lags a ramp by (period - 1) / 3 bars.
    near(weighted.basis[20], 100 + 2 * (20 - 2 / 3));
    // The exponential leg seeds from a simple average of its own first window,
    // so its first bar is the mean of the three regression endpoints there.
    expect(firstIndex(exponential.basis)).toBe(6);
    near(exponential.basis[6], 100 + 2 * (6 - 1));
  });

  it('yields nothing until the regression window is full', () => {
    const out = run(STANDARD_ERROR_BANDS, ramp(4, 100, 2), { periods: 5, averagePeriods: 1 });
    expect(out.basis.every((v) => v === null)).toBe(true);
  });
});

describe('Moving Average Channel', () => {
  const data = stepped(12);

  it('averages the highs and the lows separately, each over its own length', () => {
    const out = run(MA_CHANNEL, data, { upperLength: 3, lowerLength: 2 });
    // Bar 5: highs 106, 107, 108 and lows 103, 104.
    near(out.upper[5], 107);
    near(out.lower[5], 103.5);
    expect(firstIndex(out.upper)).toBe(2);
    expect(firstIndex(out.lower)).toBe(1);
  });

  it('displaces each leg by its own offset', () => {
    const out = run(MA_CHANNEL, data, {
      upperLength: 3, lowerLength: 3, upperOffset: 2, lowerOffset: -1,
    });
    // The upper leg's bar 5 value lands at bar 7, the lower leg's at bar 4.
    near(out.upper[7], 107);
    near(out.lower[4], 103);
    expect(firstIndex(out.upper)).toBe(4);
    expect(firstIndex(out.lower)).toBe(1);
  });

  it('is a channel of the highs and the lows, never of the close', () => {
    const out = run(MA_CHANNEL, data, { upperLength: 4, lowerLength: 4 });
    // Mean close over bars 2..5 is 103.5, and neither leg may sit on it.
    near(out.upper[5], 106.5);
    near(out.lower[5], 102.5);
  });
});
