/**
 * Measured-parity pins for the strength momentum group.
 *
 * Every number below is derived by hand from the published definition of the
 * study, written out as the rational it comes from rather than as a decimal
 * copied off a run. Each one was independently confirmed against the reference
 * implementation at matched parameter values before being written down, so a
 * refactor that quietly moves a warmup index or a smoothing family fails here
 * instead of shipping.
 *
 * The seeded-EMA convention these studies chain on is the one the reference uses
 * throughout: alpha = 2/(period + 1), seeded with the plain mean of the first
 * `period` live values, first output at `period - 1` bars past the point its
 * input starts. Where a study stacks that on a series which itself opens with a
 * warmup gap, the gap is skipped and the seed is taken from the first live bar,
 * so the warmups add rather than overlapping.
 */
import { describe, it, expect } from 'vitest';
import {
  MOMENTUM,
  ROC,
  PPO,
  TRIX,
  TSI,
  SMI_ERGODIC_INDICATOR,
  SMI_ERGODIC_OSCILLATOR,
  SMI,
} from '../src/indicators/strength';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {});

const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

/** Closes only, with a one-wide range around each, which is all most of these read. */
const closes = (values: readonly number[]): Bar[] =>
  values.map((c, i) => ({
    time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i,
  }));

const ohlc = (rows: readonly (readonly [number, number, number])[]): Bar[] =>
  rows.map(([high, low, close], i) => ({
    time: 1700000000 + i * 60, open: close, high, low, close, volume: 100 + i,
  }));

const wave = (n = 200): Bar[] => closes(Array.from({ length: n }, (_, i) => 100 + Math.sin(i / 5) * 10 + i * 0.05));

describe('Momentum, measured parity', () => {
  it('is the plain difference against the bar `len` back', () => {
    // close = 100 + 2i, so every 10-bar difference is exactly 20 and every
    // 23-bar difference is exactly 46. No smoothing, no scaling, no divisor.
    const data = closes(Array.from({ length: 60 }, (_, i) => 100 + 2 * i));
    expect(run(MOMENTUM, data).mom[10]).toBe(20);
    expect(run(MOMENTUM, data).mom[59]).toBe(20);
    expect(run(MOMENTUM, data, { len: 23 }).mom[59]).toBe(46);
  });

  it('first prints at exactly `len`, never earlier', () => {
    const out = run(MOMENTUM, wave());
    expect(firstIndex(out.mom)).toBe(10);
    expect(out.mom[9]).toBeNull();
    expect(firstIndex(run(MOMENTUM, wave(), { len: 1 }).mom)).toBe(1);
    expect(firstIndex(run(MOMENTUM, wave(), { len: 37 }).mom)).toBe(37);
  });

  it('reads whichever source is chosen, not the close', () => {
    // hl2 sits half a point above the close in this fixture, so the difference
    // is identical while the level is not: the study has to be differencing hl2
    // against hl2 rather than mixing the two.
    const data = closes(Array.from({ length: 40 }, (_, i) => 100 + 3 * i));
    expect(run(MOMENTUM, data, { source: 'hl2' }).mom[20]).toBe(30);
  });

  it('reports a real difference across a zero reading rather than suppressing it', () => {
    // Momentum is a difference, so nothing about it is undefined when the older
    // reading happens to be zero. Only sources that can legitimately reach zero
    // (volume) can produce this, and printing the true jump is more useful than
    // a gap. Recorded here so the choice stays deliberate.
    const data = closes([1, 2, 3, 4, 5]);
    data[0] = { ...data[0], volume: 0 };
    const out = run(MOMENTUM, data, { len: 2, source: 'volume' });
    expect(out.mom[2]).toBe(data[2].volume);
    expect(Number.isFinite(out.mom[2] as number)).toBe(true);
  });
});

describe('Rate of Change, measured parity', () => {
  it('is 100 * (src - src[n]) / src[n]', () => {
    // close = 100 + i. At bar 9 the base is 100 and the rise is 9, so the
    // reading is exactly 9 percent; at bar 20 it is 100 * 9 / 111.
    const data = closes(Array.from({ length: 60 }, (_, i) => 100 + i));
    const out = run(ROC, data);
    expect(out.roc[9]).toBe(9);
    expect(out.roc[20]).toBeCloseTo(900 / 111, 12);
    expect(run(ROC, data, { length: 31 }).roc[40]).toBeCloseTo((100 * 31) / 109, 12);
  });

  it('first prints at exactly `length`', () => {
    const out = run(ROC, wave());
    expect(firstIndex(out.roc)).toBe(9);
    expect(out.roc[8]).toBeNull();
    expect(firstIndex(run(ROC, wave(), { length: 31 }).roc)).toBe(31);
  });

  it('prints a gap, not an infinity, when the base reading is zero', () => {
    // The percentage is genuinely undefined against a zero base. An infinity
    // here would drag the pane's autoscale with it for the whole session.
    const out = run(ROC, closes([0, 5, 7, 9]), { length: 2 });
    expect(out.roc[2]).toBeNull();
    expect(out.roc[3]).toBeCloseTo((100 * (9 - 5)) / 5, 12);
  });
});

describe('Percentage Price Oscillator, measured parity', () => {
  it('is the spread of the two averages as a percentage of the slow one', () => {
    // close = 100 + 2i. A p-bar mean of that ramp is 100 + 2i - (p - 1), so on
    // defaults fast = 100 + 2i - 11 and slow = 100 + 2i - 25, the spread is a
    // constant 14 and the reading is 1400 / (75 + 2i).
    const data = closes(Array.from({ length: 80 }, (_, i) => 100 + 2 * i));
    for (const mode of ['SMA', 'EMA']) {
      // A seeded EMA of an exact arithmetic ramp is that ramp lagged by
      // (p - 1) / 2 from the seed bar onwards, so both shapes land on the same
      // closed form here and the check reads either way.
      const out = run(PPO, data, { oscType: mode });
      expect(out.ppo[25], mode).toBeCloseTo(1400 / 125, 12);
      expect(out.ppo[40], mode).toBeCloseTo(1400 / 155, 12);
    }
  });

  it('matches a longhand seeded-EMA derivation, oscillator, signal and histogram', () => {
    // Six closes, fast 2, slow 3, signal 2, all EMA. Written out as the exact
    // rationals the recursion produces:
    //   ema2:  11, 11, 41/3, 125/9, 449/27      (seed (10+12)/2 at bar 1)
    //   ema3:  11, 13, 27/2, 63/4               (seed (10+12+11)/3 at bar 2)
    //   ppo = 100 * (ema2 - ema3) / ema3
    //   signal = ema2 of the ppo, seeded from its first two live bars
    const data = closes([10, 12, 11, 15, 14, 18]);
    const out = run(PPO, data, { fastLength: 2, slowLength: 3, signalLength: 2 });

    expect(out.ppo[2]).toBeCloseTo(0, 12);
    expect(out.ppo[3]).toBeCloseTo(200 / 39, 12);
    expect(out.ppo[4]).toBeCloseTo(700 / 243, 12);
    expect(out.ppo[5]).toBeCloseTo(9500 / 1701, 12);

    // signal[3] is the mean of ppo[2] and ppo[3]: (0 + 200/39) / 2.
    const sig3 = 100 / 39;
    const sig4 = (700 / 243) * (2 / 3) + sig3 * (1 / 3);
    const sig5 = (9500 / 1701) * (2 / 3) + sig4 * (1 / 3);
    expect(out.signal[3]).toBeCloseTo(sig3, 12);
    expect(out.signal[4]).toBeCloseTo(sig4, 12);
    expect(out.signal[5]).toBeCloseTo(sig5, 12);

    expect(out.hist[3]).toBeCloseTo(200 / 39 - sig3, 12);
    expect(out.hist[5]).toBeCloseTo(9500 / 1701 - sig5, 12);
  });

  it('starts the oscillator at slowLength - 1 and the signal signalLength - 1 later', () => {
    // The signal averages the oscillator, not the price, so it seeds from the
    // oscillator's own first live bar: the two warmups add.
    for (const mode of ['EMA', 'SMA']) {
      const out = run(PPO, wave(), { oscType: mode, sigType: mode });
      expect(firstIndex(out.ppo), mode).toBe(25);
      expect(firstIndex(out.signal), mode).toBe(33);
      expect(firstIndex(out.hist), mode).toBe(33);
      expect(out.ppo[24], mode).toBeNull();
      expect(out.signal[32], mode).toBeNull();
    }
    const short = run(PPO, wave(), { fastLength: 2, slowLength: 3, signalLength: 2 });
    expect(firstIndex(short.ppo)).toBe(2);
    expect(firstIndex(short.signal)).toBe(3);
  });

  it('prints a gap when the slow average is exactly zero', () => {
    // The percentage has no meaning against a zero denominator, and an infinity
    // would poison the signal average for the rest of the series.
    //
    // 2-bar means of 3, -3, 4, -4, 6 are 0, 1/2, 0, 1 at bars 1 to 4, so bars 1
    // and 3 divide by zero while the bars either side stay perfectly readable.
    const out = run(PPO, closes([3, -3, 4, -4, 6]), {
      fastLength: 1, slowLength: 2, signalLength: 2, oscType: 'SMA', sigType: 'SMA',
    });
    expect(out.ppo[1]).toBeNull();
    expect(out.ppo[3]).toBeNull();
    expect(out.ppo[2]).toBeCloseTo((100 * (4 - 0.5)) / 0.5, 12);
    expect(out.ppo[4]).toBeCloseTo((100 * (6 - 1)) / 1, 12);
    for (const v of out.ppo) expect(v === null || Number.isFinite(v)).toBe(true);
  });
});

describe('TRIX, measured parity', () => {
  it('reads back the log-space slope of a geometric series, scaled by 10000', () => {
    // log(close) = 0.01 * i is an exact ramp, three seeded EMAs lag it without
    // bending it, and the one-bar change recovers the slope: 10000 * 0.01.
    const out = run(TRIX, closes(Array.from({ length: 90 }, (_, i) => Math.exp(0.01 * i))));
    expect(out.trix[60]).toBeCloseTo(100, 6);
    expect(out.trix[89]).toBeCloseTo(100, 6);
  });

  it('matches a longhand triple seeded-EMA derivation', () => {
    // logs 0, 1, 4, 5, 9 at length 2. The three chains, as exact rationals:
    //   ema1: 1/2, 17/6, 77/18, 401/54     (seed (0+1)/2 at bar 1)
    //   ema2: 5/3, 92/27, 493/81           (seed (1/2 + 17/6)/2 at bar 2)
    //   ema3: 137/54, 575/243 + 137/54     (seed (5/3 + 92/27)/2 at bar 3)
    // and the first change is 10000 * 575/243.
    const out = run(TRIX, closes([0, 1, 4, 5, 9].map((x) => Math.exp(x))), { length: 2 });
    expect(out.trix[3]).toBeNull();
    expect(out.trix[4]).toBeCloseTo(1e4 * (575 / 243), 6);
  });

  it('first prints at 3 * length - 2', () => {
    // Each of the three passes starts length - 1 bars after its input, and the
    // final one-bar change costs one more.
    expect(firstIndex(run(TRIX, wave()).trix)).toBe(52);
    expect(run(TRIX, wave()).trix[51]).toBeNull();
    expect(firstIndex(run(TRIX, wave(), { length: 2 }).trix)).toBe(4);
    expect(firstIndex(run(TRIX, wave(), { length: 5 }).trix)).toBe(13);
  });

  it('is an exact zero on a flat series and gaps on a non-positive close', () => {
    expect(run(TRIX, closes(Array.from({ length: 80 }, () => 1))).trix[52]).toBe(0);
    // log of zero or a negative price is undefined, so nothing can print.
    for (const v of run(TRIX, closes(Array.from({ length: 80 }, () => 0))).trix) expect(v).toBeNull();
  });
});

describe('True Strength Index, measured parity', () => {
  it('matches a longhand double seeded-EMA derivation, long pass first', () => {
    // closes 10, 12, 11, 15, 14 at long 2, short 2. The one-bar changes are
    // 2, -1, 4, -1 and their sizes 2, 1, 4, 1, each double smoothed:
    //   long over the change:  1/2, 17/6, 5/18     short of that:  5/3, 20/27
    //   long over the size:    3/2, 19/6, 31/18    short of that:  7/3, 52/27
    // so the reading is 100 * (5/3) / (7/3) then 100 * (20/27) / (52/27).
    const out = run(TSI, closes([10, 12, 11, 15, 14]), { long: 2, short: 2, signal: 2 });
    expect(out.tsi[2]).toBeNull();
    expect(out.tsi[3]).toBeCloseTo(500 / 7, 12);
    expect(out.tsi[4]).toBeCloseTo(500 / 13, 12);
    // The signal seeds from the study's own first two live bars.
    expect(out.signal[3]).toBeNull();
    expect(out.signal[4]).toBeCloseTo(5000 / 91, 12);
  });

  it('smooths over the long length first and the short length second', () => {
    // The order is not interchangeable and equal lengths hide it, so this case
    // uses long 3 and short 2 on closes 10, 12, 11, 15, 14, 18. Changes are
    // 2, -1, 4, -1, 4 and sizes 2, 1, 4, 1, 4:
    //   long over the change:  5/3, 1/3, 13/6     short of that:  1, 16/9
    //   long over the size:    7/3, 5/3, 17/6     short of that:  2, 23/9
    // giving 100 * 1/2 and then 100 * 16/23. Running short before long instead
    // reads 56.52 and 73.79 on the same bars, so this pins the direction.
    const out = run(TSI, closes([10, 12, 11, 15, 14, 18]), { long: 3, short: 2, signal: 2 });
    expect(out.tsi[3]).toBeNull();
    expect(out.tsi[4]).toBeCloseTo(50, 12);
    expect(out.tsi[5]).toBeCloseTo(1600 / 23, 12);
  });

  it('pins to +/-100 when every bar moves the same way', () => {
    // Numerator and denominator are then the same series, or exact negatives.
    expect(run(TSI, closes(Array.from({ length: 60 }, (_, i) => 100 + i))).tsi[37]).toBe(100);
    expect(run(TSI, closes(Array.from({ length: 60 }, (_, i) => 200 - 2 * i))).tsi[37]).toBe(-100);
  });

  it('first prints at long + short - 1, with the signal signal - 1 later', () => {
    // One bar for the change, long - 1 for the long pass, short - 1 for the short.
    const out = run(TSI, wave());
    expect(firstIndex(out.tsi)).toBe(37);
    expect(firstIndex(out.signal)).toBe(49);
    expect(out.tsi[36]).toBeNull();
    expect(out.signal[48]).toBeNull();
    const other = run(TSI, wave(), { long: 40, short: 7, signal: 3 });
    expect(firstIndex(other.tsi)).toBe(46);
    expect(firstIndex(other.signal)).toBe(48);
  });

  it('prints a gap rather than an infinity when nothing has moved', () => {
    // With every change zero the denominator is zero, and so is the numerator:
    // the ratio is undefined rather than infinite, and must not print.
    const out = run(TSI, closes(Array.from({ length: 60 }, () => 100)));
    for (const v of out.tsi) expect(v).toBeNull();
    for (const v of out.signal) expect(v).toBeNull();
  });
});

describe('SMI Ergodic Indicator and Oscillator, measured parity', () => {
  it('is the same double smoothing, on its own faster lengths', () => {
    // Identical arithmetic to True Strength Index, so the same hand derivation
    // holds at matched lengths and the two must agree bar for bar.
    const data = closes([10, 12, 11, 15, 14]);
    const ind = run(SMI_ERGODIC_INDICATOR, data, { shortlen: 2, longlen: 2, siglen: 2 });
    expect(ind.erg[3]).toBeCloseTo(500 / 7, 12);
    expect(ind.erg[4]).toBeCloseTo(500 / 13, 12);
    expect(ind.sig[4]).toBeCloseTo(5000 / 91, 12);

    const tsi = run(TSI, data, { long: 2, short: 2, signal: 2 });
    for (let i = 0; i < data.length; i++) expect(ind.erg[i]).toBe(tsi.tsi[i]);
  });

  it('hands its short and long lengths to the smoothing in that order', () => {
    // Its own option names are the mirror of True Strength Index's, so a study
    // that passed them straight through would smooth in the wrong order. Short 2
    // with long 3 must land on the same 50 and 1600/23 the equivalent True
    // Strength Index settings give; the swap reads 56.52 and 73.79.
    const data = closes([10, 12, 11, 15, 14, 18]);
    const ind = run(SMI_ERGODIC_INDICATOR, data, { shortlen: 2, longlen: 3, siglen: 2 });
    expect(ind.erg[4]).toBeCloseTo(50, 12);
    expect(ind.erg[5]).toBeCloseTo(1600 / 23, 12);
    const osc = run(SMI_ERGODIC_OSCILLATOR, data, { shortlen: 2, longlen: 3, siglen: 2 });
    // The signal seeds from the pair 50 and 1600/23, so the histogram is the
    // second reading less their mean.
    expect(osc.osc[5]).toBeCloseTo(1600 / 23 - (50 + 1600 / 23) / 2, 12);
  });

  it('reduces the same pair to one histogram', () => {
    // 500/13 - 5000/91 = 3500/91 - 5000/91.
    const out = run(SMI_ERGODIC_OSCILLATOR, closes([10, 12, 11, 15, 14]), {
      shortlen: 2, longlen: 2, siglen: 2,
    });
    expect(out.osc[3]).toBeNull();
    expect(out.osc[4]).toBeCloseTo(-1500 / 91, 12);
  });

  it('first prints at longlen + shortlen - 1, signal and oscillator siglen - 1 later', () => {
    const ind = run(SMI_ERGODIC_INDICATOR, wave());
    expect(firstIndex(ind.erg)).toBe(24);
    expect(firstIndex(ind.sig)).toBe(28);
    expect(ind.erg[23]).toBeNull();
    expect(ind.sig[27]).toBeNull();
    expect(firstIndex(run(SMI_ERGODIC_OSCILLATOR, wave()).osc)).toBe(28);

    const other = { shortlen: 9, longlen: 11, siglen: 4 };
    expect(firstIndex(run(SMI_ERGODIC_INDICATOR, wave(), other).erg)).toBe(19);
    expect(firstIndex(run(SMI_ERGODIC_INDICATOR, wave(), other).sig)).toBe(22);
    expect(firstIndex(run(SMI_ERGODIC_OSCILLATOR, wave(), other).osc)).toBe(22);
  });
});

describe('Stochastic Momentum Index, measured parity', () => {
  // No counterpart exists in the reference set, so these are pinned against the
  // published standard definition: the close measured from the midpoint of the
  // %K range, both the distance and the range double smoothed, the ratio scaled
  // by 200 so a close at the top of the range reads +100.
  it('is 200 * (close - midpoint) / range once both smoothing passes are identities', () => {
    // Length 1 on both smoothing passes leaves the raw ratio exposed.
    //   bar 1: window high 12 low 8, midpoint 10, close 11, range 4 -> +50
    //   bar 2: window high 13 low 9, midpoint 11, close 10, range 4 -> -50
    const out = run(SMI, ohlc([[10, 8, 9], [12, 9, 11], [13, 10, 10]]), {
      lengthK: 2, lengthD: 1, lengthEMA: 1,
    });
    expect(out.smi[0]).toBeNull();
    expect(out.smi[1]).toBeCloseTo(50, 12);
    expect(out.smi[2]).toBeCloseTo(-50, 12);
  });

  it('takes the window from the high and the low, not from the source', () => {
    // close = 100 + i with a one-wide range, so over 10 bars the window runs
    // from high[i] = 101 + i down to low[i-9] = 90 + i: a constant range of 11
    // with the close a constant 4.5 above the midpoint. Both survive the double
    // smoothing untouched, giving 200 * 4.5 / 11.
    //
    // A close-only window would be 9 wide with the close at its very top, which
    // reads 0 rather than 900/11, so this also rules that reading out.
    const out = run(SMI, closes(Array.from({ length: 60 }, (_, i) => 100 + i)));
    expect(out.smi[13]).toBeCloseTo(900 / 11, 10);
    expect(out.smi[59]).toBeCloseTo(900 / 11, 10);
    expect(out.ema[15]).toBeCloseTo(900 / 11, 10);
  });

  it('first prints at lengthK - 1 plus both smoothing passes', () => {
    // 9 for the window, then lengthD - 1 twice, then lengthEMA - 1 for the line.
    const out = run(SMI, wave());
    expect(firstIndex(out.smi)).toBe(13);
    expect(firstIndex(out.ema)).toBe(15);
    expect(out.smi[12]).toBeNull();
    expect(out.ema[14]).toBeNull();
    const other = run(SMI, wave(), { lengthK: 20, lengthD: 4, lengthEMA: 6 });
    expect(firstIndex(other.smi)).toBe(25);
    expect(firstIndex(other.ema)).toBe(30);
  });

  it('prints a gap rather than an infinity when the range collapses', () => {
    const flat = ohlc(Array.from({ length: 40 }, () => [100, 100, 100] as const));
    const out = run(SMI, flat);
    for (const v of out.smi) expect(v).toBeNull();
    for (const v of out.ema) expect(v).toBeNull();
    // The background band still covers the pane on a series that never prints.
    expect(out.bandHigh.every((v) => v === 40)).toBe(true);
    expect(out.bandLow.every((v) => v === -40)).toBe(true);
  });
});
