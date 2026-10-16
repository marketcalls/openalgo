import { describe, it, expect } from 'vitest';
import {
  AVERAGE_INDICATORS, MA_CROSS, ALLIGATOR, SMMA, MCGINLEY_DYNAMIC, TEMA, VWMA,
} from '../src/indicators/averages';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * Parity regression for the averages group.
 *
 * Every number below is worked out from the definition on paper, never read
 * back out of the code under test: a window mean written as a fraction, a
 * Wilder step written as `(prev * (n - 1) + src) / n`. The measured comparison
 * against the reference implementation lives outside the repository, so this
 * file has to stand on its own arithmetic.
 */

/** `high = close + 1`, `low = close - 1`, so `hl2` equals `close`. */
const bars = (closes: readonly number[], volume = 1000): Bar[] =>
  closes.map((c, i) => ({
    time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume,
  }));

/** `low = close` and `high = close + 4`, so `hl2` is `close + 2` and the two sources differ. */
const skewed = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({
    time: 1700000000 + i * 60, open: c, high: c + 4, low: c, close: c, volume: 1000,
  }));

const ramp = (n: number): Bar[] => bars(Array.from({ length: n }, (_, i) => i));

/** Index of the first plotted bar, which is what every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const run = (d: IndicatorDescriptor, data: Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...overrides }, {});

describe('Smoothed Moving Average', () => {
  it('is registered once, on the price pane, with the reference defaults', () => {
    expect(AVERAGE_INDICATORS.filter((d) => d.id === 'smma')).toEqual([SMMA]);
    expect(SMMA.name).toBe('Smoothed Moving Average');
    expect(SMMA.placement).toBe('onchart');
    const d = indicatorDefaults(SMMA);
    expect(d.length).toBe(7);
    expect(d.source).toBe('close');
  });

  it('smooths with alpha 1 / length, not the exponential 2 / (length + 1)', () => {
    // Closes 10, 20, 30, 40, 50 at length 3. Seed is the plain mean of the first
    // three, 60 / 3 = 20. Then (20 * 2 + 40) / 3 = 80 / 3, and
    // (80 / 3 * 2 + 50) / 3 = (160 / 3 + 150 / 3) / 3 = 310 / 9.
    const out = run(SMMA, bars([10, 20, 30, 40, 50]), { length: 3 });
    expect(out.smma[2] as number).toBeCloseTo(20, 12);
    expect(out.smma[3] as number).toBeCloseTo(80 / 3, 12);
    expect(out.smma[4] as number).toBeCloseTo(310 / 9, 12);
    // An EMA of the same length carries alpha 0.5 and would read 30 on bar 3.
    expect(out.smma[3] as number).not.toBeCloseTo(30, 6);
  });

  it('first prints at length - 1, and is the source itself at length 1', () => {
    const data = ramp(40);
    expect(firstLive(run(SMMA, data).smma)).toBe(6);
    expect(firstLive(run(SMMA, data, { length: 3 }).smma)).toBe(2);
    // Length 1 is the degenerate divisor the settings floor allows: the seed is
    // the first value and every step is (prev * 0 + src) / 1, so the line is the
    // source and nothing anywhere is divided by zero.
    const unit = run(SMMA, data, { length: 1 }).smma;
    expect(firstLive(unit)).toBe(0);
    expect(unit).toEqual(data.map((b) => b.close));
  });

  it('reads the configured source', () => {
    // hl2 is close + 2 on these bars, and the smoother is affine, so every
    // printed value has to sit exactly 2 above the close-sourced line.
    const data = skewed([10, 20, 30, 40, 50]);
    const closed = run(SMMA, data, { length: 3 });
    const halved = run(SMMA, data, { length: 3, source: 'hl2' });
    expect(halved.smma[4] as number).toBeCloseTo((closed.smma[4] as number) + 2, 12);
    expect(halved.smma[2] as number).toBeCloseTo(22, 12);
  });

  it('holds a constant series flat and survives empty and single-bar input', () => {
    const flat = run(SMMA, bars(new Array(30).fill(42)));
    expect(flat.smma[6] as number).toBe(42);
    expect(flat.smma[29] as number).toBeCloseTo(42, 12);
    for (const input of [[], bars([10])]) {
      expect(run(SMMA, input).smma).toHaveLength(input.length);
    }
    expect(run(SMMA, bars([10])).smma).toEqual([null]);
  });
});

describe('MA Cross, long length default', () => {
  it('defaults the long average to 26 bars', () => {
    expect(indicatorDefaults(MA_CROSS).longLength).toBe(26);
    expect(indicatorDefaults(MA_CROSS).shortLength).toBe(9);
  });

  it('plots the 26-bar mean under the default settings', () => {
    // Closes are 0, 1, 2, ... so a window mean is the mean of consecutive
    // integers: bars 0..25 average 12.5 and bars 5..30 average 17.5.
    const out = run(MA_CROSS, ramp(40));
    expect(firstLive(out.long)).toBe(25);
    expect(out.long[25] as number).toBeCloseTo(12.5, 12);
    expect(out.long[30] as number).toBeCloseTo(17.5, 12);
    // The short leg is unchanged: bars 0..8 average 4.
    expect(firstLive(out.short)).toBe(8);
    expect(out.short[8] as number).toBeCloseTo(4, 12);
  });

  it('marks a bar only where the two averages actually crossed', () => {
    // sma(2) over 10, 10, 10, 20, 10, 10 is na, 10, 10, 15, 15, 10 and sma(3) is
    // na, na, 10, 40/3, 40/3, 40/3. The fast leg goes above on bar 3 and back
    // below on bar 5, and stays above in between without recrossing.
    const out = run(MA_CROSS, bars([10, 10, 10, 20, 10, 10]), { shortLength: 2, longLength: 3 });
    expect(out.cross).toEqual([null, null, null, 15, null, 10]);
  });
});

describe('Williams Alligator, smoothing length defaults', () => {
  it('defaults to 21 / 13 / 8 lengths against unchanged 8 / 5 / 3 offsets', () => {
    const d = indicatorDefaults(ALLIGATOR);
    expect([d.jawLength, d.teethLength, d.lipsLength]).toEqual([21, 13, 8]);
    expect([d.jawOffset, d.teethOffset, d.lipsOffset]).toEqual([8, 5, 3]);
  });

  it('first prints each line at its own length - 1, displaced by its offset', () => {
    const out = run(ALLIGATOR, ramp(60));
    expect(firstLive(out.jaw)).toBe(28);   // 21 - 1 + 8
    expect(firstLive(out.teeth)).toBe(17); // 13 - 1 + 5
    expect(firstLive(out.lips)).toBe(10);  //  8 - 1 + 3
  });

  it('seeds each line on the plain mean of its own window', () => {
    // hl2 equals the close here, which runs 0, 1, 2, ... so the Wilder seed is
    // the mean of consecutive integers: 0..20 average 10, 0..12 average 6,
    // 0..7 average 3.5. Each lands `offset` slots later than the bar it was
    // computed on, and the step after the jaw seed is (10 * 20 + 21) / 21.
    const out = run(ALLIGATOR, ramp(60));
    expect(out.jaw[28] as number).toBeCloseTo(10, 12);
    expect(out.jaw[29] as number).toBeCloseTo(221 / 21, 12);
    expect(out.teeth[17] as number).toBeCloseTo(6, 12);
    expect(out.lips[10] as number).toBeCloseTo(3.5, 12);
  });
});

describe('averages whose kernels the parity run confirmed unchanged', () => {
  const data = ramp(60);

  it('starts McGinley at length - 1, where its seeding average starts', () => {
    expect(firstLive(run(MCGINLEY_DYNAMIC, data).mg)).toBe(13);
  });

  it('starts TEMA at 3 * length - 3, since each stage waits on the last', () => {
    expect(firstLive(run(TEMA, data).tema)).toBe(24);
  });

  it('starts VWMA at length - 1 and goes blank on a window of no volume', () => {
    expect(firstLive(run(VWMA, data).vwma)).toBe(19);
    const dead = bars(Array.from({ length: 40 }, (_, i) => 100 + i), 0);
    expect(run(VWMA, dead, { length: 5 }).vwma.every((v) => v === null)).toBe(true);
  });
});
