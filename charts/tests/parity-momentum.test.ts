import { describe, it, expect } from 'vitest';
import { RSI, MACD, STOCHASTIC, ADX, CCI, MFI, ATR, WILLIAMS_VIX_FIX } from '../src/indicators/momentum';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * Momentum and volatility group, measured against the standard definitions.
 *
 * Every number below is worked out by hand from the definition on a series short
 * enough to follow in the comment above it, never read back out of the code under
 * test. Where a study's warmup index is asserted it is the index the definition
 * puts the first value at, counted from the data the study actually needs.
 */

const defaults = (d: IndicatorDescriptor): Record<string, unknown> => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const closeBars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({ time: 1700000000 + i * 60, open: c, high: c, low: c, close: c, volume: 100 }));

/** high, low, close rows. Open follows the close, which no study in this file reads. */
const hlcBars = (rows: readonly (readonly [number, number, number])[], volumes?: readonly number[]): Bar[] =>
  rows.map(([high, low, close], i) => ({
    time: 1700000000 + i * 60,
    open: close, high, low, close,
    volume: volumes ? volumes[i] : 100,
  }));

/** 200 bars with no flat stretch, long enough for every default warmup to land. */
const wave = (n = 200): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 5) * 10 + i * 0.05;
    return { time: 1700000000 + i * 60, open: c, high: c + 1.5, low: c - 1.5, close: c, volume: 100 + i };
  });

describe('RSI is Wilder-smoothed and starts at bar `length`', () => {
  // Closes 10, 11, 10.5, 12, 11 with length 2.
  //   deltas   +1, -0.5, +1.5, -1
  //   seed at bar 2: avgGain (1 + 0)/2 = 0.5, avgLoss (0 + 0.5)/2 = 0.25
  //     rsi = 100 - 100/(1 + 0.5/0.25) = 100 - 100/3
  //   bar 3: avgGain (0.5 + 1.5)/2 = 1, avgLoss (0.25 + 0)/2 = 0.125
  //     rsi = 100 - 100/(1 + 8) = 100 - 100/9
  //   bar 4: avgGain (1 + 0)/2 = 0.5, avgLoss (0.125 + 1)/2 = 0.5625
  //     rsi = 100 - 100/(1 + 8/9) = 100 - 900/17
  const data = closeBars([10, 11, 10.5, 12, 11]);

  it('matches the hand-computed series', () => {
    const out = RSI.calc(data, { length: 2, source: 'close' }, {});
    expect(out.rsi[0]).toBeNull();
    expect(out.rsi[1]).toBeNull();
    expect(out.rsi[2] as number).toBeCloseTo(100 - 100 / 3, 12);
    expect(out.rsi[3] as number).toBeCloseTo(100 - 100 / 9, 12);
    expect(out.rsi[4] as number).toBeCloseTo(100 - 900 / 17, 12);
  });

  it('prints 100 when the window holds no loss at all', () => {
    const out = RSI.calc(closeBars([10, 11, 12, 13]), { length: 2, source: 'close' }, {});
    expect(out.rsi[2] as number).toBe(100);
    expect(out.rsi[3] as number).toBe(100);
  });

  it('prints 0 when the window holds no gain at all', () => {
    const out = RSI.calc(closeBars([13, 12, 11, 10]), { length: 2, source: 'close' }, {});
    expect(out.rsi[2] as number).toBe(0);
  });

  it('starts at bar 14 on the default length', () => {
    const out = run(RSI, wave());
    expect(firstIndex(out.rsi)).toBe(14);
  });

  it('keeps the reference defaults', () => {
    const s = defaults(RSI);
    expect(s.length).toBe(14);
    expect(s.source).toBe('close');
  });
});

describe('MACD is a difference of SMA-seeded exponential averages', () => {
  // Closes 100, 102, 101, 104, 103 with fast 2, slow 3, signal 2.
  //   ema2 (k = 2/3) seeds at bar 1 with 101: 101, 101, 103, 103
  //   ema3 (k = 1/2) seeds at bar 2 with 101: 101, 102.5, 102.75
  //   macd = [na, na, 0, 0.5, 0.25]
  //   the signal counts its window from the first real macd value at bar 2, so it
  //   seeds at bar 3 with (0 + 0.5)/2 = 0.25 and holds 0.25 at bar 4
  //   histogram = macd - signal = [na, na, na, 0.25, 0]
  const data = closeBars([100, 102, 101, 104, 103]);
  const settings = { fastPeriod: 2, slowPeriod: 3, signalPeriod: 2, source: 'close' };

  it('matches the hand-computed lines', () => {
    const out = MACD.calc(data, settings, {});
    expect(out.macd.slice(0, 2)).toEqual([null, null]);
    expect(out.macd[2] as number).toBeCloseTo(0, 12);
    expect(out.macd[3] as number).toBeCloseTo(0.5, 12);
    expect(out.macd[4] as number).toBeCloseTo(0.25, 12);
    expect(out.signal.slice(0, 3)).toEqual([null, null, null]);
    expect(out.signal[3] as number).toBeCloseTo(0.25, 12);
    expect(out.signal[4] as number).toBeCloseTo(0.25, 12);
    expect(out.histogram.slice(0, 3)).toEqual([null, null, null]);
    expect(out.histogram[3] as number).toBeCloseTo(0.25, 12);
    expect(out.histogram[4] as number).toBeCloseTo(0, 12);
  });

  it('starts the study at bar 25 and its signal at bar 33 on the defaults', () => {
    const out = run(MACD, wave());
    expect(firstIndex(out.macd)).toBe(25);
    expect(firstIndex(out.signal)).toBe(33);
    expect(firstIndex(out.histogram)).toBe(33);
  });

  it('keeps the reference defaults', () => {
    const s = defaults(MACD);
    expect([s.fastPeriod, s.slowPeriod, s.signalPeriod]).toEqual([12, 26, 9]);
    expect(s.source).toBe('close');
  });
});

describe('Stochastic smooths the raw %K once and the %D again', () => {
  // high, low, close over five bars, %K length 3.
  //   bar 2: highest high 13, lowest low 8,  (12 - 8)/5  * 100 = 80
  //   bar 3: highest high 13, lowest low 9,  (10 - 9)/4  * 100 = 25
  //   bar 4: highest high 14, lowest low 9,  (13 - 9)/5  * 100 = 80
  // With %K smoothing 1 the raw value is the plot; %D is its 2-bar mean.
  const data = hlcBars([
    [10, 8, 9],
    [12, 9, 11],
    [13, 10, 12],
    [12, 9, 10],
    [14, 11, 13],
  ]);

  it('matches the hand-computed %K and %D at smoothing 1', () => {
    const out = STOCHASTIC.calc(data, { kPeriod: 3, kSmoothing: 1, dPeriod: 2 }, {});
    expect(out.k.slice(0, 2)).toEqual([null, null]);
    expect(out.k[2] as number).toBeCloseTo(80, 12);
    expect(out.k[3] as number).toBeCloseTo(25, 12);
    expect(out.k[4] as number).toBeCloseTo(80, 12);
    expect(out.d.slice(0, 3)).toEqual([null, null, null]);
    expect(out.d[3] as number).toBeCloseTo(52.5, 12);
    expect(out.d[4] as number).toBeCloseTo(52.5, 12);
  });

  it('averages the raw value over the window when %K smoothing is raised', () => {
    // (80 + 25 + 80) / 3
    const out = STOCHASTIC.calc(data, { kPeriod: 3, kSmoothing: 3, dPeriod: 2 }, {});
    expect(out.k.slice(0, 4)).toEqual([null, null, null, null]);
    expect(out.k[4] as number).toBeCloseTo(185 / 3, 12);
  });

  it('defaults to an unsmoothed %K, so the plot starts at bar 13', () => {
    // The reference default for %K smoothing is 1, not 3. At 1 the plot is the
    // raw stochastic and lands as soon as the %K window is full.
    const s = defaults(STOCHASTIC);
    expect(s.kPeriod).toBe(14);
    expect(s.kSmoothing).toBe(1);
    expect(s.dPeriod).toBe(3);
    const out = run(STOCHASTIC, wave());
    expect(firstIndex(out.k)).toBe(13);
    expect(firstIndex(out.d)).toBe(15);
  });

  it('leaves a gap rather than a level when the whole window is one price', () => {
    // A flat window has no range to place the close in, so the ratio is 0/0.
    const flat = hlcBars([[5, 5, 5], [5, 5, 5], [5, 5, 5]]);
    const out = STOCHASTIC.calc(flat, { kPeriod: 3, kSmoothing: 1, dPeriod: 2 }, {});
    expect(out.k[2]).toBeNull();
  });
});

describe('ADX leaves undefined directional ratios absent across a zero true range', () => {
  // high, low, close. Bar 3 is flat at the previous close, so its true range is
  // exactly 0, and at DI length 1 the smoothed true range is 0 with it.
  //
  //   tr   = [na, 3, 4, 0, 6, 2]        (bar 0 has no previous close)
  //   +DM  = [na, 2, 0, 0, 6, 1]
  //   -DM  = [na, 0, 2, 0, 0, 0]
  //
  // At DI length 1 Wilder's average is the value itself, so
  //   bar 1: +DI 2/3*100, -DI 0
  //   bar 2: +DI 0,       -DI 2/4*100 = 50
  //   bar 3: undefined, so both directional ratios and DX are absent
  //   bar 4: +DI 6/6*100 = 100, -DI 0
  //   bar 5: +DI 1/2*100 = 50,  -DI 0
  // One indicator is zero on every available bar here, so DX is 100 on those
  // bars. Its 2-bar average retains state across the absent bar 3.
  const locked = hlcBars([
    [10, 8, 9],
    [12, 9, 11],
    [11, 7, 8],
    [8, 8, 8],
    [14, 11, 13],
    [15, 13, 14],
  ]);

  it('emits no directional ratio at the hole and resumes finite readings', () => {
    const out = ADX.calc(locked, { period: 1, adxPeriod: 2 }, {});
    expect(out.plusDi).toEqual([null, (2 / 3) * 100, 0, null, 100, 50]);
    expect(out.minusDi).toEqual([null, 0, 50, null, 0, 0]);
  });

  it('leaves the missing DX absent while retaining the ADX smoothing state', () => {
    const out = ADX.calc(locked, { period: 1, adxPeriod: 2 }, {});
    expect(out.adx).toEqual([null, null, 100, null, 100, 100]);
  });

  // high, low, close with no flat bar, DI length 2 and ADX smoothing 2.
  //   tr    = [na, 3, 4, 5, 2]
  //   trR   = [na, na, 3.5, 4.25, 3.125]        (Wilder from bar 1)
  //   +DM   = [na, 2, 0, 2, 0] -> +DMr = [na, na, 1, 1.5, 0.75]
  //   -DM   = [na, 0, 2, 0, 0] -> -DMr = [na, na, 1, 0.5, 0.25]
  //   bar 2: +DI 1/3.5*100 = 200/7,   -DI 1/3.5*100 = 200/7,   dx = 0
  //   bar 3: +DI 1.5/4.25*100,        -DI 0.5/4.25*100,        dx = 50
  //   bar 4: +DI 0.75/3.125*100 = 24, -DI 0.25/3.125*100 = 8,  dx = 50
  //   adx seeds at bar 3 with (0 + 50)/2 = 25, then (25 + 50)/2 = 37.5
  const clean = hlcBars([
    [10, 8, 9],
    [12, 9, 11],
    [11, 7, 8],
    [13, 9, 12],
    [12, 10, 11],
  ]);

  it('matches the hand-computed indicators and ADX with no hole present', () => {
    const out = ADX.calc(clean, { period: 2, adxPeriod: 2 }, {});
    expect(out.plusDi.slice(0, 2)).toEqual([null, null]);
    expect(out.plusDi[2] as number).toBeCloseTo(200 / 7, 12);
    expect(out.minusDi[2] as number).toBeCloseTo(200 / 7, 12);
    expect(out.plusDi[3] as number).toBeCloseTo(600 / 17, 12);
    expect(out.minusDi[3] as number).toBeCloseTo((0.5 / 4.25) * 100, 12);
    expect(out.plusDi[4] as number).toBeCloseTo(24, 12);
    expect(out.minusDi[4] as number).toBeCloseTo(8, 12);
    expect(out.adx.slice(0, 3)).toEqual([null, null, null]);
    expect(out.adx[3] as number).toBeCloseTo(25, 12);
    expect(out.adx[4] as number).toBeCloseTo(37.5, 12);
  });

  it('starts the indicators at bar 14 and the ADX at bar 27 on the defaults', () => {
    const s = defaults(ADX);
    expect([s.period, s.adxPeriod]).toEqual([14, 14]);
    const out = run(ADX, wave());
    expect(firstIndex(out.plusDi)).toBe(14);
    expect(firstIndex(out.minusDi)).toBe(14);
    expect(firstIndex(out.adx)).toBe(27);
  });
});

describe('CCI divides by the mean absolute deviation', () => {
  // Typical price (high + low + close)/3 over five bars: 9, 11, 10, 14, 8, length 3.
  //   bar 2: mean 10,   deviations 1, 1, 0     -> md 2/3,  (10 - 10)/(0.015*2/3) = 0
  //   bar 3: mean 35/3, deviations 2/3, 5/3, 7/3 -> md 14/9, (14 - 35/3)/(0.015*14/9) = 100
  //   bar 4: mean 32/3, deviations 2/3, 10/3, 8/3 -> md 20/9, (8 - 32/3)/(0.015*20/9) = -80
  const data = hlcBars([
    [12, 6, 9],
    [13, 8, 12],
    [11, 7, 12],
    [16, 11, 15],
    [10, 5, 9],
  ]);

  it('matches the hand-computed series', () => {
    const out = CCI.calc(data, { period: 3, constant: 0.015, maType: 'None' }, {});
    expect(out.cci.slice(0, 2)).toEqual([null, null]);
    expect(out.cci[2] as number).toBeCloseTo(0, 12);
    expect(out.cci[3] as number).toBeCloseTo(100, 10);
    expect(out.cci[4] as number).toBeCloseTo(-80, 10);
  });

  it('reads zero rather than a hole when the window has no deviation at all', () => {
    // Every typical price equal makes the numerator zero as well, so the limit is
    // zero. Leaving 0/0 to become a gap would break the study for an instrument
    // locked at one price.
    const flat = hlcBars([[5, 5, 5], [5, 5, 5], [5, 5, 5]]);
    const out = CCI.calc(flat, { period: 3, constant: 0.015, maType: 'None' }, {});
    expect(out.cci[2] as number).toBe(0);
  });

  it('starts at bar 19 on the default length', () => {
    const out = run(CCI, wave());
    expect(firstIndex(out.cci)).toBe(19);
  });

  it('keeps the reference defaults, including a 20-bar smoothing length', () => {
    const s = defaults(CCI);
    expect(s.period).toBe(20);
    expect(s.constant).toBe(0.015);
    expect(s.maType).toBe('SMA');
    expect(s.maLength).toBe(20);
    // The smoothing average counts its own window from the first CCI value at
    // bar 19, so at length 20 it lands 19 bars later.
    const out = run(CCI, wave());
    expect(firstIndex(out.ma)).toBe(38);
  });
});

describe('MFI weighs typical-price flow by volume', () => {
  // Typical price 9, 11, 10, 14, 8 and volumes 100, 200, 300, 400, 500.
  //   raw flow  = 900, 2200, 3000, 5600, 4000
  //   up   bars = 1 and 3, down bars = 2 and 4
  //   bar 2: positive 2200, negative 3000 -> 2200/5200 * 100
  //   bar 3: positive 5600, negative 3000 -> 5600/8600 * 100
  //   bar 4: positive 5600, negative 4000 -> 5600/9600 * 100
  const data = hlcBars(
    [[12, 6, 9], [13, 8, 12], [11, 7, 12], [16, 11, 15], [10, 5, 9]],
    [100, 200, 300, 400, 500],
  );

  it('matches the hand-computed series', () => {
    const out = MFI.calc(data, { period: 2 }, {});
    expect(out.mfi.slice(0, 2)).toEqual([null, null]);
    expect(out.mfi[2] as number).toBeCloseTo((2200 / 5200) * 100, 12);
    expect(out.mfi[3] as number).toBeCloseTo((5600 / 8600) * 100, 12);
    expect(out.mfi[4] as number).toBeCloseTo((5600 / 9600) * 100, 12);
  });

  it('starts at bar `length`, once that many real price changes exist', () => {
    // The ratio needs `length` completed comparisons, and the first bar has no
    // previous typical price to compare against, so bar `length` is the earliest
    // honest value. Counting the first bar as both an up tick and a down tick
    // would buy one bar earlier at the cost of a wrong number.
    expect(firstIndex(MFI.calc(data, { period: 2 }, {}).mfi)).toBe(2);
    expect(firstIndex(run(MFI, wave()).mfi)).toBe(14);
    expect(defaults(MFI).period).toBe(14);
  });

  it('pins to 100 with no down flow and to 0 with no up flow', () => {
    const up = hlcBars([[1, 1, 1], [2, 2, 2], [3, 3, 3], [4, 4, 4]], [10, 10, 10, 10]);
    expect(MFI.calc(up, { period: 2 }, {}).mfi[3] as number).toBe(100);
    const down = hlcBars([[4, 4, 4], [3, 3, 3], [2, 2, 2], [1, 1, 1]], [10, 10, 10, 10]);
    expect(MFI.calc(down, { period: 2 }, {}).mfi[3] as number).toBe(0);
  });
});

describe('ATR averages a true range that opens with the first bar range', () => {
  // high, low, close.
  //   tr  = [10-8 = 2, 3, 4, 5, 2]     bar 0 falls back to high - low
  //   At length 2 the average seeds at bar 1 with (2 + 3)/2 = 2.5, then
  //   3.25, 4.125, 3.0625.
  const data = hlcBars([
    [10, 8, 9],
    [12, 9, 11],
    [11, 7, 8],
    [13, 9, 12],
    [12, 10, 11],
  ]);

  it('matches the hand-computed series', () => {
    const out = ATR.calc(data, { period: 2 }, {});
    expect(out.atr[0]).toBeNull();
    expect(out.atr[1] as number).toBeCloseTo(2.5, 12);
    expect(out.atr[2] as number).toBeCloseTo(3.25, 12);
    expect(out.atr[3] as number).toBeCloseTo(4.125, 12);
    expect(out.atr[4] as number).toBeCloseTo(3.0625, 12);
  });

  it('reads the gap against the previous close, not the bar range alone', () => {
    // Bar 1 opens 10 above bar 0's close and spans only 2, so its true range is
    // the 12 up to its own high, which a plain high minus low would miss.
    const gapped = hlcBars([[10, 8, 9], [21, 19, 20]]);
    const out = ATR.calc(gapped, { period: 2 }, {});
    expect(out.atr[1] as number).toBeCloseTo((2 + 12) / 2, 12);
  });

  it('starts at bar 13 on the default length', () => {
    expect(defaults(ATR).period).toBe(14);
    expect(firstIndex(run(ATR, wave()).atr)).toBe(13);
  });
});

describe('Williams Vix Fix measures the low against the highest close', () => {
  // Closes 10, 12, 11, 14, 13 and lows 9, 11, 10, 12, 12, lookback 3.
  //   highest close: bar 2 = 12, bar 3 = 14, bar 4 = 14
  //   wvf = (highest close - low) / highest close * 100
  //     bar 2 = (12 - 10)/12 * 100 = 100/6
  //     bar 3 = (14 - 12)/14 * 100 = 100/7
  //     bar 4 = (14 - 12)/14 * 100 = 100/7
  //   With a 2-bar band: mean at bar 3 = (100/6 + 100/7)/2, population deviation
  //   is half the spread, so the upper band is mean + 2 * that.
  const data: Bar[] = [10, 12, 11, 14, 13].map((c, i) => ({
    time: 1700000000 + i * 60,
    open: c, high: c + 1, low: [9, 11, 10, 12, 12][i], close: c, volume: 100,
  }));
  const settings = { pd: 3, bbl: 2, mult: 2, lb: 3, ph: 0.85, pl: 1.01 };

  it('matches the hand-computed histogram', () => {
    const out = WILLIAMS_VIX_FIX.calc(data, settings, {});
    expect(out.wvf.slice(0, 2)).toEqual([null, null]);
    expect(out.wvf[2] as number).toBeCloseTo(100 / 6, 12);
    expect(out.wvf[3] as number).toBeCloseTo(100 / 7, 12);
    expect(out.wvf[4] as number).toBeCloseTo(100 / 7, 12);
  });

  it('draws neither the band nor the range until they are switched on', () => {
    const out = WILLIAMS_VIX_FIX.calc(data, settings, {});
    expect(out.upperBand.every((v) => v === null)).toBe(true);
    expect(out.rangeHigh.every((v) => v === null)).toBe(true);
    expect(out.rangeLow.every((v) => v === null)).toBe(true);
  });

  it('matches the hand-computed upper band once it is shown', () => {
    const mean = (100 / 6 + 100 / 7) / 2;
    const dev = (100 / 6 - 100 / 7) / 2;
    const out = WILLIAMS_VIX_FIX.calc(data, { ...settings, sd: true }, {});
    expect(out.upperBand[3] as number).toBeCloseTo(mean + 2 * dev, 12);
  });

  it('matches the hand-computed range high once it is shown', () => {
    const out = WILLIAMS_VIX_FIX.calc(data, { ...settings, hp: true }, {});
    expect(out.rangeHigh[4] as number).toBeCloseTo((100 / 6) * 0.85, 12);
    expect(out.rangeLow[4] as number).toBeCloseTo((100 / 7) * 1.01, 12);
  });

  it('leaves a gap when the highest close is zero', () => {
    const zero = hlcBars([[0, 0, 0], [0, 0, 0], [0, 0, 0]]);
    const out = WILLIAMS_VIX_FIX.calc(zero, settings, {});
    expect(out.wvf[2]).toBeNull();
  });

  it('keeps the published defaults', () => {
    const s = defaults(WILLIAMS_VIX_FIX);
    expect([s.pd, s.bbl, s.mult, s.lb, s.ph, s.pl]).toEqual([22, 20, 2, 50, 0.85, 1.01]);
    expect([s.hp, s.sd]).toEqual([false, false]);
  });
});
