/**
 * Numeric parity pins for the signal and study families.
 *
 * Every expectation here is worked out by hand from the standard definition of
 * the indicator and written as arithmetic, never copied out of a run. The file
 * exists because the rest of the suite exercises these studies on smooth
 * synthetic series where several wrong formulas give the right answer:
 *
 *   - on a ramp whose high and low sit one point either side of the close, the
 *     true range equals the plain high minus low on every bar, so a true range
 *     computed without the previous close passes. The gapping fixtures below are
 *     the ones that can tell those two apart.
 *   - a window that never goes flat cannot show what happens when the
 *     denominator reaches zero, which is where a study either returns no value
 *     or quietly emits an infinity.
 *
 * Warmup indices are pinned alongside the values, because a series that starts
 * one bar early or late sits shifted against every other tool on the chart and
 * nothing about its shape gives that away.
 */
import { describe, it, expect } from 'vitest';
import {
  VORTEX, VOLATILITY_STOP, TREND_STRENGTH_INDEX, WILLIAMS_FRACTALS, RSI_DIVERGENCE,
} from '../src/indicators/signals';
import { CPR, ALPHATREND, RANGE_ANALYSIS } from '../src/indicators/studies';
import { WAVETREND } from '../src/indicators/wavetrend';
import { SEASONALITY } from '../src/indicators/seasonality';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const T0 = 1704067200; // 2024-01-01T00:00:00Z

/** Bars from explicit high, low and close triples, one minute apart. */
const ohlc = (rows: readonly (readonly [number, number, number])[]): Bar[] =>
  rows.map(([high, low, close], i) => ({
    time: T0 + i * 60, open: close, high, low, close, volume: 1000,
  }));

/** Closes with a fixed one-point wing either side, the shape most of the suite uses. */
const closes = (values: readonly number[]): Bar[] =>
  values.map((c, i) => ({
    time: T0 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 1000,
  }));

/** 09:30 IST on the given IST calendar date, in UTC seconds. IST has no daylight shift. */
const istMorning = (y: number, m: number, d: number): number => Date.UTC(y, m - 1, d, 4) / 1000;

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

describe('Vortex Indicator: parity pins', () => {
  /**
   * A gap up: bar 1 opens and trades clear of bar 0's range. Its true range is
   * then 11 (high against the previous close) where its own high minus low is
   * only 2, which is the one shape that separates the two readings.
   */
  const gapped = ohlc([[10, 8, 9], [20, 18, 19], [21, 19, 20]]);

  it('measures window travel as true range against the previous close, not as the bar range', () => {
    // Upward movement: |20 - 8| = 12 and |21 - 18| = 3, so 15 over the window.
    // Downward: |18 - 10| = 8 and |19 - 20| = 1, so 9.
    // True range: bar 1 max(2, |20 - 9|, |18 - 9|) = 11, bar 2 max(2, 2, 0) = 2.
    const out = run(VORTEX, gapped, { length: 2 });
    expect(out.vip[2]).toBeCloseTo(15 / 13, 12);
    expect(out.vim[2]).toBeCloseTo(9 / 13, 12);
    // Summing bar ranges instead would divide by 4 and read 3.75 up.
    expect(out.vip[2]).not.toBeCloseTo(15 / 4, 6);
  });

  it('starts one bar after the denominator, because bar 0 has no movement term', () => {
    const out = run(VORTEX, gapped, { length: 2 });
    expect(firstIndex(out.vip)).toBe(2);
    expect(firstIndex(out.vim)).toBe(2);
    expect(out.vip[1]).toBeNull();
  });

  it('has no reading when the window has no travel at all', () => {
    // Four bars with no range and no movement: the numerators and the
    // denominator are all zero, and zero over zero is absent, not infinite.
    const out = run(VORTEX, ohlc([[10, 10, 10], [10, 10, 10], [10, 10, 10], [10, 10, 10]]), { length: 2 });
    for (const v of out.vip) expect(v).toBeNull();
    for (const v of out.vim) expect(v).toBeNull();
  });
});

describe('Volatility Stop: parity pins', () => {
  /**
   * A low start, a gap up, two quiet steps, then a gap down through the stop.
   * The two gaps are what make the true range wider than the bar range, and the
   * low start is what leaves the running minimum well below the flip bar's
   * source, which is the only shape that can show the extreme being reset.
   */
  const data = ohlc([[6, 4, 5], [13, 11, 12], [14, 12, 13], [15, 13, 14], [9, 7, 8]]);

  it('reproduces the recursion term for term, seed, ratchet and flip', () => {
    // True range 2, 8, 2, 2, 7, so a two-bar Wilder average of 5, 3.5, 2.75 and
    // 4.875 from bar 1. The multiplier of one makes those the offsets, and bar 0
    // has no stop behind it so it seeds at the source.
    const out = run(VOLATILITY_STOP, data, { length: 2, factor: 1 });
    expect(out.up[0]).toBe(5);
    expect(out.up[1]).toBe(7); // max(5, 12 - 5)
    expect(out.up[2]).toBe(9.5); // max(7, 13 - 3.5)
    expect(out.up[3]).toBe(11.25); // max(9.5, 14 - 2.75)
    // Bar 4 closes at 8, below the stop of 11.25, so the side flips. The running
    // extreme is reset to the source before the stop is rebuilt from it, which
    // puts the new stop at 8 + 4.875 rather than at the old minimum of 5 + 4.875.
    expect(out.up[4]).toBeNull();
    expect(out.down[4]).toBe(12.875);
    expect(out.down[4]).not.toBe(9.875);
    // Were the travel taken as the bar range, the offset would be 2.375 and the
    // flip would land at 10.375 instead.
    expect(out.down[4]).not.toBe(10.375);
  });

  it('falls back to the unmultiplied true range while the average is still warming', () => {
    // A multiplier below one makes the two readings differ: the bare range of
    // 22 holds the stop at its seed of 8, where 22 times 0.5 would lift it to 19.
    const warming = ohlc([[10, 8, 8], [30, 9, 30]]);
    const out = run(VOLATILITY_STOP, warming, { length: 5, factor: 0.5 });
    expect(out.up[0]).toBe(8);
    expect(out.up[1]).toBe(8);
  });
});

describe('Trend Strength Index: parity pins', () => {
  it('is the correlation of the source with a unit-spaced, time-forward position', () => {
    // Closes 1, 2, 6 against positions 0, 1, 2. Means 3 and 1, so the centred
    // products are 5, the position variance 2 and the price variance 14.
    const out = run(TREND_STRENGTH_INDEX, closes([1, 2, 6]), { length: 3 });
    expect(out.tsi[2]).toBeCloseTo(5 / Math.sqrt(28), 12);
    expect(firstIndex(out.tsi)).toBe(2);
  });

  it('is unchanged by shifting or scaling the source, which a missing centring is not', () => {
    const base = run(TREND_STRENGTH_INDEX, closes([1, 2, 6]), { length: 3 });
    const moved = run(TREND_STRENGTH_INDEX, closes([101, 102, 106]), { length: 3 });
    const scaled = run(TREND_STRENGTH_INDEX, closes([10, 20, 60]), { length: 3 });
    expect(moved.tsi[2]).toBeCloseTo(base.tsi[2] as number, 12);
    expect(scaled.tsi[2]).toBeCloseTo(base.tsi[2] as number, 12);
  });

  it('has no reading on a flat window, where the source has no variance to correlate', () => {
    const out = run(TREND_STRENGTH_INDEX, closes([5, 5, 5, 5]), { length: 3 });
    for (const v of out.tsi) expect(v).toBeNull();
  });
});

describe('Williams Fractals: parity pins', () => {
  /**
   * A flat top two bars wide. The tolerance for equal bars sits on the older
   * side only, so the newer of the two is the fractal and the older is not.
   */
  const flatTop = ohlc(
    [1, 2, 5, 5, 2, 1].map((h) => [h, h - 10, h - 5] as [number, number, number]),
  );

  it('rejects an equal bar on the newer side and accepts one on the older side', () => {
    const out = run(WILLIAMS_FRACTALS, flatTop, { periods: 2 });
    expect(out.upFractal[2]).toBeNull();
    expect(out.upFractal[3]).toBe(5);
    // The shape is anchored to the candidate's own extreme, not to its close.
    expect(out.upFractal[3]).toBe(flatTop[3].high);
    for (const v of out.downFractal) expect(v).toBeNull();
  });

  it('needs the whole newer window, so no fractal can sit in the last `periods` bars', () => {
    const out = run(WILLIAMS_FRACTALS, flatTop, { periods: 2 });
    expect(out.upFractal[4]).toBeNull();
    expect(out.upFractal[5]).toBeNull();
  });
});

describe('RSI Divergence: parity pins', () => {
  it('starts the oscillator at the period, and fires nothing before a second pivot exists', () => {
    const data = closes(Array.from({ length: 120 }, (_, i) => 100 + Math.sin(i / 5) * 10));
    const out = run(RSI_DIVERGENCE, data);
    expect(firstIndex(out.rsi)).toBe(14);
    expect(out.rsi[13]).toBeNull();
    // The first confirmed pivot has no predecessor to disagree with, so the
    // earliest a signal can sit is behind the second one.
    const firstSignal = Math.min(
      ...[out.bull, out.bear].map(firstIndex).filter((i) => i >= 0),
    );
    expect(firstSignal).toBeGreaterThan(14);
  });
});

describe('AlphaTrend: parity pins', () => {
  it('starts at the common period and pins the gauge at 100 on a feed with no volume', () => {
    // With every volume zero there is no down-flow to divide by, so the gauge
    // reads 100, the rising branch is taken on every bar, and the band is the
    // low less the average true range. Nothing here may divide by zero.
    const rows = Array.from({ length: 40 }, (_, i) => [102 + i, 98 + i, 100 + i] as [number, number, number]);
    const data = ohlc(rows).map((b) => ({ ...b, volume: 0 }));
    const out = run(ALPHATREND, data, { AP: 14, coeff: 1 });
    expect(firstIndex(out.alphatrend)).toBe(14);
    for (const v of out.alphatrend) expect(v === null || Number.isFinite(v)).toBe(true);
    // True range is 4 on every bar after the first, so the offset is 4 once the
    // window has filled and the level is low minus 4, ratcheting up with price.
    expect(out.alphatrend[20]).toBeCloseTo(data[20].low - 4, 12);
    expect(out.lagged[20]).toBe(out.alphatrend[18]);
  });
});

describe('WaveTrend Pro: parity pins', () => {
  it('stacks its warmups additively, one smoother at a time', () => {
    // The channel mean prints at n1 - 1, its deviation n1 - 1 later, the
    // oscillator n2 - 1 after that, and the signal line sigLen - 1 after that
    // again: 9, 18, 38 and 41 at the shipped lengths.
    const data = closes(Array.from({ length: 80 }, (_, i) => 100 + Math.sin(i / 7) * 8));
    const out = run(WAVETREND, data);
    expect(firstIndex(out.wt1)).toBe(38);
    expect(firstIndex(out.wt2)).toBe(41);
    expect(firstIndex(out.mom)).toBe(41);
  });

  it('reads zero, not infinity, where the source never leaves its own mean', () => {
    // A constant source has no deviation to divide by. The reading there is
    // "exactly average", which is zero, and it must not be an infinity.
    const out = run(WAVETREND, closes(new Array<number>(80).fill(50)));
    expect(out.wt1[38]).toBe(0);
    expect(out.wt2[41]).toBe(0);
    expect(out.mom[41]).toBe(0);
  });
});

describe('Range Analysis: parity pins', () => {
  it('reports the bar range from bar 0 and reads zero on a bar with no range', () => {
    const out = run(RANGE_ANALYSIS, ohlc([[12, 10, 11], [10, 10, 10], [15, 11, 14]]));
    expect(out.range).toEqual([2, 0, 4]);
    expect(firstIndex(out.range)).toBe(0);
  });
});

describe('CPR with Floor Pivot: parity pins', () => {
  it('collapses every level onto the pivot when the previous session had no range', () => {
    // High, low and close all 100 for the first session: the width is zero, so
    // the six outer levels and both edges of the central range land on the
    // pivot. Nothing in the frame divides by the width, so none of it is absent.
    const day = (d: number, price: number): Bar[] =>
      [0, 1, 2].map((i) => ({
        time: istMorning(2024, 1, d) + i * 3600,
        open: price, high: price, low: price, close: price, volume: 500,
      }));
    const bars = [...day(1, 100), ...day(2, 120)];
    const out = run(CPR, bars, { displayS1R1: true });
    for (const key of ['dPivot', 'dS1', 'dS2', 'dS3', 'dR1', 'dR2', 'dR3', 'dBc', 'dTc']) {
      expect(out[key][3], key).toBe(100);
    }
    expect(firstIndex(out.dPivot)).toBe(3);
  });
});

describe('Seasonality: parity pins', () => {
  const monthly = (values: readonly number[]): Bar[] =>
    values.map((c, i) => ({
      time: istMorning(2024, 1 + i, 15), open: c, high: c, low: c, close: c, volume: 500,
    }));

  it('measures a month against the previous month close and skips the one still forming', () => {
    // January has nothing behind it, March is the month in progress, so only
    // February is measured: 100 times (110 - 100) over 100.
    const table = SEASONALITY.table?.({
      bars: monthly([100, 110, 120]), values: {}, settings: indicatorDefaults(SEASONALITY),
    });
    expect(table).not.toBeNull();
    const row = table!.rows.find((r) => r[0].text === '2024');
    expect(row).toBeDefined();
    expect(row![1].text).toBe(''); // January, no predecessor
    expect(row![2].text).toBe('10.00%');
    expect(row![3].text).toBe('SKIP'); // March, still forming
  });

  it('leaves out a month whose predecessor closed at zero rather than dividing by it', () => {
    const table = SEASONALITY.table?.({
      bars: monthly([0, 110, 120]), values: {}, settings: indicatorDefaults(SEASONALITY),
    });
    // February is the only candidate and it has no denominator, so there is no
    // measured month left and the grid is absent rather than full of headers.
    expect(table).toBeNull();
  });
});
