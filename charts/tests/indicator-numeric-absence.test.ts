import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import { indicatorDefaults } from '../src/model/indicator-registry';
import { CCI, STOCHASTIC } from '../src/indicators/momentum';
import { FISHER_TRANSFORM } from '../src/indicators/oscillators';
import { RELATIVE_VOLATILITY_INDEX } from '../src/indicators/ranges';
import { MASS_INDEX, NVI, PVI, PVO } from '../src/indicators/indices';
import { TSI, SMI_ERGODIC_INDICATOR, SMI_ERGODIC_OSCILLATOR } from '../src/indicators/strength';
import { TREND_STRENGTH_INDEX } from '../src/indicators/signals';
import {
  change, correlation, highest, lowest, nulls, rollingSum, sma, smaSeededEma, stdev,
} from '../src/indicators/calc';

/**
 * Absent observations and non-finite intermediates in seven studies.
 *
 * Each boundary expectation below is an independent reading: either derived by
 * hand in the comment above it or recorded from the companion language engine
 * on the same rows. None is read back out of the code under test. The
 * "ordinary data" checks at the end compare against the formulas as they stood
 * before these corrections, so a change that moved an ordinary finite reading
 * would show up there.
 */

type Row = readonly [number | null, number | null, number | null, number | null, number | null];

/** [open, high, low, close, volume]; a null price is a missing observation. */
const barsOf = (rows: readonly Row[]): Bar[] => rows.map(([o, h, l, c, v], i) => ({
  time: 1700000000 + i * 60,
  open: o ?? NaN, high: h ?? NaN, low: l ?? NaN, close: c ?? NaN,
  volume: v ?? undefined,
}));

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {});

/** A long, gapless series at an ordinary price level with no flat stretch. */
const wave = (n = 400, level = 100): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = level + Math.sin(i / 5) * 10 + Math.cos(i / 11) * 3 + i * 0.05;
  return {
    time: 1700000000 + i * 60,
    open: c - 0.25, high: c + 1.5 + (i % 3) * 0.25, low: c - 1.5 - (i % 4) * 0.25, close: c,
    volume: 100 + (i % 7),
  };
});

describe('CCI leaves a window with an absent or overflowing deviation absent', () => {
  // Recorded from the language engine: cci(3) over these rows. Bar 2 has no
  // high, so every window reaching it (bars 2, 3 and 4) has no mean deviation.
  const rows: Row[] = [
    [10, 11, 9, 10, 1], [10, 12, 10, 11, 1], [11, null, 10, 12, 1], [12, 13, 11, 12, 1],
    [12, 14, 12, 13, 1], [13, 15, 12, 14, 1], [14, 16, 13, 15, 1],
  ];

  it('prints nothing, not 0, over the windows that hold the missing bar', () => {
    const out = run(CCI, barsOf(rows), { period: 3, maType: 'None' });
    expect(out.cci).toEqual([null, null, null, null, null, 87.50000000000006, 100.0000000000001]);
  });

  it('keeps the smoothing average from averaging invented zeros', () => {
    // With the zeros gone the length-2 SMA has its first complete window at
    // bars 5 and 6: (87.50000000000006 + 100.0000000000001) / 2.
    const out = run(CCI, barsOf(rows), { period: 3, maType: 'SMA', maLength: 2 });
    expect(out.ma.slice(0, 6)).toEqual([null, null, null, null, null, null]);
    expect(out.ma[6] as number).toBeCloseTo(93.75, 10);
  });

  it('does not turn an overflowing deviation into a zero reading', () => {
    // Typical prices alternate +-5.9e307 (each finite), so the length-4 mean is
    // 0 and the four absolute deviations sum past the largest double. The
    // deviation is therefore infinite and the ratio has no value.
    const big = 5.9e307;
    const data = barsOf([big, -big, big, -big, big].map((p): Row => [p, p, p, p, 1]));
    const out = run(CCI, data, { period: 4, maType: 'None' });
    expect(out.cci).toEqual([null, null, null, null, null]);
  });

  it('still reads 0 on a flat window, which is a documented choice', () => {
    const flat = barsOf([[5, 5, 5, 5, 1], [5, 5, 5, 5, 1], [5, 5, 5, 5, 1]]);
    expect(run(CCI, flat, { period: 3, maType: 'None' }).cci[2]).toBe(0);
  });
});

describe('Stochastic scales by 100 before dividing and leaves a non-finite %K absent', () => {
  it('forms (100 * (close - low)) / span', () => {
    // high 3, low 0, close 1: (100 * 1) / 3 rounds to 33.333333333333336,
    // where dividing first and then scaling gives 33.33333333333333.
    const out = run(STOCHASTIC, barsOf([[1, 3, 0, 1, 1]]), { kPeriod: 1, kSmoothing: 1, dPeriod: 1 });
    expect(out.k).toEqual([33.333333333333336]);
    expect(out.d).toEqual([33.333333333333336]);
  });

  it('leaves the reading absent when the window span overflows', () => {
    // high 1e308 and low -1e308 are both finite but their span is not. With
    // the close on the low the scaled distance is 0, and 0 divided by an
    // infinite span used to print a flat 0.
    const out = run(STOCHASTIC, barsOf([[0, 1e308, -1e308, -1e308, 1]]), { kPeriod: 1, kSmoothing: 1, dPeriod: 1 });
    expect(out.k).toEqual([null]);
    expect(out.d).toEqual([null]);
  });

  it('leaves the reading absent when the scaled distance overflows', () => {
    // close - low is 2e307, finite; 100 times that is not, so the reading is
    // absent at the step that overflowed.
    const out = run(STOCHASTIC, barsOf([[0, 1e307, -1e307, 1e307, 1]]), { kPeriod: 1, kSmoothing: 1, dPeriod: 1 });
    expect(out.k).toEqual([null]);
  });

  it('leaves the reading absent on a bar with no close', () => {
    const out = run(STOCHASTIC, barsOf([[1, 3, 0, 1, 1], [1, 3, 0, null, 1], [1, 3, 0, 2, 1]]),
      { kPeriod: 2, kSmoothing: 1, dPeriod: 1 });
    expect(out.k[1]).toBeNull();
    expect(out.k[2]).toBe(200 / 3);
  });
});

describe('Fisher Transform restarts its recursion after a missing midpoint', () => {
  // Bar 3 has no high, so its midpoint is missing. The descriptor's own rule
  // is that a missing previous value counts as 0 on the next printed bar, so
  // bar 4 starts afresh: a flat 2-bar window of midpoints 13 and 13 gives
  //   raw  = 0.66 * (0 / 0.001 - 0.5) + 0.67 * 0 = -0.33
  //   fish = 0.5 * ln(0.67 / 1.33) = -0.34282825441539394
  const rows: Row[] = [
    [10, 11, 9, 10, 1], [10, 12, 10, 11, 1], [11, 13, 10, 12, 1], [12, null, 11, 12, 1],
    [12, 14, 12, 13, 1], [13, 15, 12, 14, 1], [14, 16, 13, 15, 1],
  ];

  it('prints again on the next bar instead of staying absent for good', () => {
    const out = run(FISHER_TRANSFORM, barsOf(rows), { length: 2 });
    expect(out.fisher).toEqual([
      null, 0.34282825441539394, 0.7913738721291064, null,
      -0.34282825441539394, -0.06208054853744893, 0.39614103556792124,
    ]);
    expect(out.trigger).toEqual([
      null, null, 0.34282825441539394, 0.7913738721291064, null,
      -0.34282825441539394, -0.06208054853744893,
    ]);
  });
});

/** Language engine 0.7.1, RVI composition at deviation length 30, bars 55 to 94 (bar 60 missing). */
const RVI_30_GAP_55_TO_94: (number | null)[] = [
  45.41492269409936, 52.678572279239376, 45.845997532311216, 39.82753940209933, 47.81779288417503,
  ...new Array<null>(30).fill(null),
  19.158320801590772, 49.661512209913305, 65.43743504020281, 47.708376997786104, 59.90520272216512,
];

describe('Relative Volatility Index keeps its averages across a missing bar', () => {
  // Recorded from the language engine: the RVI composition with a 14-bar EMA
  // over a 2-bar standard deviation. Bar 20 is missing, so bars 20 and 21 have
  // no change or deviation; the averages hold and resume on bar 22 instead of
  // waiting fourteen bars for a fresh seed.
  const rows: Row[] = Array.from({ length: 40 }, (_, i): Row => {
    const c = 100 + ((i * 7) % 5) - ((i * 3) % 4);
    return [c, c + 1, c - 1, c, 1];
  });
  rows[20] = [null, null, null, null, 1];
  const expected = [
    null, null, null, null, null, null, null, null, null, null, null, null, null, null,
    51.21951219512195, 46.34974533106961, 53.93069417965683, 51.15078423511509,
    45.71310774166658, 54.149295689517594, null, null, 61.120663786150075,
    54.720663337316736, 61.66765119046308, 45.54284391493495, 52.6810650447231,
    58.89762173661184, 53.49183304274355, 50.80179585893948, 45.5192442562249,
    53.82875468658113, 60.738297992755086, 45.146939106329185, 52.222525680958455,
    47.5085236560697, 54.60127471437842, 51.90383333573365, 46.59206533654013,
    54.62847719894914,
  ];

  it('matches the language reading on every bar', () => {
    expect(run(RELATIVE_VOLATILITY_INDEX, barsOf(rows), { length: 2, maType: 'None' }).rvi).toEqual(expected);
  });

  it('carries the EMA smoothing option across the same gap', () => {
    // A 3-bar EMA of the RVI holds through bars 20 and 21 and then takes one
    // ordinary step from the bar 19 value: alpha is 2 / (3 + 1) = 0.5.
    const out = run(RELATIVE_VOLATILITY_INDEX, barsOf(rows), { length: 2, maType: 'EMA', maLength: 3 });
    expect(out.ma[20]).toBeNull();
    expect(out.ma[21]).toBeNull();
    expect(out.ma[22] as number).toBe(
      (expected[22] as number) * 0.5 + (out.ma[19] as number) * (1 - 0.5),
    );
  });

  it('holds across a missing close after a long deviation warmup', () => {
    // Recorded from the language engine: the same composition with a 30-bar
    // deviation over 130 bars, bar 60 missing. The deviation has no value on
    // the thirty windows holding bar 60, so on those bars each average only
    // takes its real zeros and holds on the others; the reading comes back on
    // bar 90 from the held state. Reseeding would wait fourteen more bars.
    const long: Row[] = Array.from({ length: 130 }, (_, i): Row => {
      const c = 100 + ((i * 7) % 5) - ((i * 3) % 4);
      return [c, c + 1, c - 1, c, 1];
    });
    long[60] = [null, null, null, null, 1];
    const out = run(RELATIVE_VOLATILITY_INDEX, barsOf(long), { length: 30, maType: 'None' });
    expect(out.rvi.findIndex((v) => v !== null)).toBe(42);
    expect(out.rvi.slice(55, 95)).toEqual(RVI_30_GAP_55_TO_94);
  });

  it('reseeds inside a long deviation warmup, as it always has (K12)', () => {
    // With a 40-bar deviation the two sources are real zeros on one side and
    // absent on the other for 39 bars. The lower average meets fourteen zeros
    // of a rising run in that warmup. The chart restarts it on the next absent
    // bar, the reference recursion, and prints nothing until bar 52, exactly
    // as the formula it has always used. The language holds that seed: its
    // engine starts at bar 39 with exactly 100, and a seeded average over the
    // whole series, which is that rule, reproduces the recording.
    const data = wave();
    const out = run(RELATIVE_VOLATILITY_INDEX, data, { length: 40, maType: 'None' });
    expect(out.rvi.findIndex((v) => v !== null)).toBe(52);
    expect(out.rvi).toEqual(nulls(legacyRvi(data, 40)));
    const language = nulls(heldRvi(data, 40));
    expect(language.findIndex((v) => v !== null)).toBe(39);
    expect(language.slice(38, 43)).toEqual([null, 100, 100, 61.50613115716168, 42.55143054942978]);
  });
});

describe('Mass Index keeps its second EMA across a missing bar', () => {
  // Recorded from the language engine: sum(ema(high - low, 9) / ema(that, 9), 3).
  // Bar 25 has no high. The ratio is absent there, the 3-bar sum is absent on
  // the three windows holding it, and bar 28 prints again.
  const rows: Row[] = Array.from({ length: 45 }, (_, i): Row => {
    const c = 100 + (i % 4);
    return [c, c + 1 + (i % 3), c - 1, c, 1];
  });
  rows[25] = [101, null, 99, 101, 1];

  it('matches the language reading on every bar', () => {
    expect(run(MASS_INDEX, barsOf(rows), { length: 3 }).mi).toEqual([
      null, null, null, null, null, null, null, null, null, null, null, null, null, null,
      null, null, null, null, 3.0289115261301767, 3.02637716199908, 3.023376298350731,
      3.0207928971298394, 3.018268811899217, 3.015707481922666, 3.013616226598646,
      null, null, null, 2.9934105582882236, 2.9968084394205077, 2.99908883238002,
      3.000583092985635, 3.0014694850074615, 3.0019948360189295, 3.002238558382273,
      3.0022546805867805, 3.002194820703106, 3.002052965320293, 3.001837479612545,
      3.0016387634851918, 3.0014298501040826, 3.001205143393612, 3.0010174650328496,
      3.0008408008696956, 3.0006672384309936,
    ]);
  });
});

describe('NVI and PVI hold their index across a missing close', () => {
  // Volume falls on every bar for NVI and rises on every bar for PVI, so each
  // bar qualifies and a missing close would be compounded in. Bar 2 has no
  // close: the change into it and the change out of it are unknown, so the
  // index holds on both bars, as it already did after a zero previous close.
  //   bar 0  base              1000
  //   bar 1  * 110/100         1100
  //   bar 2  close missing     held
  //   bar 3  previous missing  held
  //   bar 4  * 132/120         1000 * 1.1 * 1.1
  const closes = [100, 110, null, 120, 132];
  const falling = barsOf(closes.map((c, i): Row => [c, c, c, c, 60 - 10 * i]));
  const rising = barsOf(closes.map((c, i): Row => [c, c, c, c, 10 + 10 * i]));
  const index = [1000, (110 / 100) * 1000, (110 / 100) * 1000, (110 / 100) * 1000, (110 / 100) * (132 / 120) * 1000];

  it('keeps the index instead of losing it for the rest of the history', () => {
    expect(run(NVI, falling, { maLength: 2 }).nvi).toEqual(index);
    expect(run(PVI, rising, { maLength: 2 }).pvi).toEqual(index);
  });

  it('carries the index average through the same bars', () => {
    // Seeded on bars 0 and 1 at (1000 + 1100) / 2, then alpha 2 / (2 + 1).
    const alpha = 2 / 3;
    let expected = (index[0] + index[1]) / 2;
    const ema = run(NVI, falling, { maLength: 2 }).ema;
    expect(ema[0]).toBeNull();
    expect(ema[1] as number).toBeCloseTo(expected, 10);
    for (let i = 2; i < index.length; i++) {
      expected = index[i] * alpha + expected * (1 - alpha);
      expect(ema[i] as number, `bar ${i}`).toBeCloseTo(expected, 10);
    }
    expect(run(PVI, rising, { maLength: 2 }).ema).toEqual(ema);
  });
});

describe('PVO restarts its signal after a window with no traded volume (K13)', () => {
  // SMA oscillator, fast 1, slow 2, EMA signal 2. The slow average is exactly
  // 0 on bars 3 and 4, where two bars in a row traded nothing, so PVO has no
  // reading there:
  //   pvo 1 = (100 * (20 - 15)) / 15    pvo 2 = (100 * (0 - 10)) / 10 = -100
  //   pvo 5 = (100 * (30 - 15)) / 15 = 100    pvo 6 = (100 * (40 - 35)) / 35
  // The chart's signal starts again on the next full window of readings, so
  // bar 5 has no signal and bar 6 is the fresh seed (pvo 5 + pvo 6) / 2. The
  // language's average would hold its bar 2 value and print on bar 5.
  const volumes = [10, 20, 0, 0, 0, 30, 40, 50, 60];
  const data = barsOf(volumes.map((v): Row => [10, 10, 10, 10, v]));
  const over = { oscType: 'SMA', sigType: 'EMA', fastLength: 1, slowLength: 2, signalLength: 2 };

  it('waits a whole signal window after the gap, as it always has', () => {
    const out = run(PVO, data, over);
    expect(out.pvo.slice(0, 7)).toEqual([null, (100 * (20 - 15)) / 15, -100, null, null, 100, (100 * (40 - 35)) / 35]);
    expect(out.signal[2]).toBe(((100 * (20 - 15)) / 15 + -100) / 2);
    expect(out.signal.slice(3, 6)).toEqual([null, null, null]);
    expect(out.signal[6]).toBe((100 + (100 * (40 - 35)) / 35) / 2);
  });
});

describe('True Strength Index scales by 100 before dividing and leaves overflow absent', () => {
  // Recorded from the language engine: tsi(close, 2, 2) on closes 15, 14, 16, 17.
  const rows: Row[] = [[15, 16, 14, 15, 1], [14, 15, 13, 14, 1], [16, 17, 15, 16, 1], [17, 18, 16, 17, 1]];

  it('forms (100 * smoothed change) / smoothed size', () => {
    expect(run(TSI, barsOf(rows), { long: 2, short: 2, signal: 2 }).tsi)
      .toEqual([null, null, null, 49.99999999999999]);
  });

  // At both lengths 1 each smoothed series is the raw one-bar change. A change
  // of 2^1020 (about 1.1e307) is finite and so is its size, but 100 times it
  // is not. The last change, -2^1010, scales and divides exactly to -100.
  const steep: Row[] = [0, 2 ** 1020, 2 ** 1021, 2 ** 1021 - 2 ** 1010].map((c): Row => [c, c, c, c, 1]);

  it('leaves the True Strength Index absent where the scaled change overflows', () => {
    const out = run(TSI, barsOf(steep), { long: 1, short: 1, signal: 1 });
    expect(out.tsi).toEqual([null, null, null, -100]);
    expect(out.signal).toEqual([null, null, null, -100]);
  });

  it('shares the rule with both SMI Ergodic studies', () => {
    const settings = { longlen: 1, shortlen: 1, siglen: 1 };
    const indicator = run(SMI_ERGODIC_INDICATOR, barsOf(steep), settings);
    expect(indicator.erg).toEqual([null, null, null, -100]);
    expect(indicator.sig).toEqual([null, null, null, -100]);
    expect(run(SMI_ERGODIC_OSCILLATOR, barsOf(steep), settings).osc).toEqual([null, null, null, 0]);
    expect(run(SMI_ERGODIC_INDICATOR, barsOf(rows), { longlen: 2, shortlen: 2, siglen: 2 }).erg)
      .toEqual([null, null, null, 49.99999999999999]);
  });
});

describe('Trend Strength Index forms both means before any deviation', () => {
  it('keeps the reading at an ordinary price level with sub-unit moves', () => {
    // Recorded from the language engine: correlation(close, bar.index, 4). The
    // single-pass sums lose about one percent of the reading at this level.
    const closes = [100000.01, 100000.02, 100000.04, 100000.03, 100000.06, 100000.05];
    const out = run(TREND_STRENGTH_INDEX, barsOf(closes.map((c): Row => [c, c, c, c, 1])), { length: 4 });
    expect(out.tsi).toEqual([null, null, null, 0.8000000000873115, 0.8315218406391574, 0.6000000002328306]);
  });

  it('still reads at a price level of one billion', () => {
    // Recorded from the language engine; the single-pass form printed nothing.
    const closes = [1000000000, 1000000001, 1000000003, 1000000002];
    const out = run(TREND_STRENGTH_INDEX, barsOf(closes.map((c): Row => [c, c, c, c, 1])), { length: 4 });
    expect(out.tsi).toEqual([null, null, null, 0.7999999999999998]);
    expect(correlation(closes, [0, 1, 2, 3], 4)).toEqual([NaN, NaN, NaN, 0.7999999999999998]);
  });

  it('leaves a window whose deviations are all exactly zero, or with a missing value, absent', () => {
    expect(correlation([5, 5, 5], [0, 1, 2], 3)).toEqual([NaN, NaN, NaN]);
    // Only the window 3, 4, 6 against 2, 3, 4 is complete: deviations
    // (-4/3, -1/3, 5/3) and (-1, 0, 1) give 1 / sqrt(14/9 * 2/3) = sqrt(27/28).
    const partial = correlation([1, NaN, 3, 4, 6], [0, 1, 2, 3, 4], 3);
    expect(partial.slice(0, 4)).toEqual([NaN, NaN, NaN, NaN]);
    expect(partial[4]).toBeCloseTo(Math.sqrt(27 / 28), 14);
  });

  it('reads what the arithmetic gives on a flat window whose mean is inexact', () => {
    // A flat window is absent only when its mean comes out exact. Three bars of
    // 0.1 sum and divide to 0.10000000000000002, fourteen of 2.01 to
    // 2.009999999999999, so every deviation is the same few units in the last
    // place. Against the bar index those cancel exactly and the reading is 0.
    // Recorded from the language engine: correlation(close, bar.index, len).
    const flat = (c: number, n: number): Bar[] => barsOf(Array.from({ length: n }, (): Row => [c, c, c, c, 1]));
    expect((0.1 + 0.1 + 0.1) / 3).not.toBe(0.1);
    expect(run(TREND_STRENGTH_INDEX, flat(0.1, 3), { length: 3 }).tsi).toEqual([null, null, 0]);
    expect(run(TREND_STRENGTH_INDEX, flat(2.01, 14), { length: 14 }).tsi.slice(12)).toEqual([null, 0]);
    expect(correlation([0.1, 0.1, 0.1], [0, 1, 2], 3)).toEqual([NaN, NaN, 0]);
    // Fourteen bars of 0.1 average back to 0.1 exactly: no deviation, no reading.
    expect(run(TREND_STRENGTH_INDEX, flat(0.1, 14), { length: 14 }).tsi[13]).toBeNull();
    // Against a series other than the bar index the residue survives, as it
    // does in the language: within rounding of 0, not 0 and not absent.
    expect(correlation([0.1, 0.1, 0.1], [0.1, 0.2, 0.3], 3)[2]).toBe(4.532466518368395e-16);
  });

  it('still gives NaN throughout for a period that is not a whole number above 1', () => {
    const a = [1, 3, 2, 5, 4, 6, 8, 7];
    const index = a.map((_, i) => i);
    for (const period of [2.5, 1.5, 1, 0, -2, NaN, Infinity]) {
      expect([...correlation(a, index, period)]).toEqual(new Array(8).fill(NaN));
    }
  });
});

// ---------------------------------------------------------------------------
// Ordinary data. These are the formulas as they stood before the corrections
// above, kept verbatim so a finite reading on a gapless series cannot move
// without this file noticing. Trend Strength is checked against exact
// rational arithmetic instead, because its former reading was the inaccurate
// one.

function legacyCci(data: readonly Bar[], period: number, k: number): number[] {
  const tp = data.map((b) => (b.high + b.low + b.close) / 3);
  const avg = sma(tp, period);
  const out = new Array<number>(data.length).fill(NaN);
  for (let i = period - 1; i < data.length; i++) {
    let dev = 0;
    for (let j = 0; j < period; j++) dev += Math.abs(tp[i - j] - avg[i]);
    const md = dev / period;
    out[i] = md > 0 ? (tp[i] - avg[i]) / (k * md) : 0;
  }
  return out;
}

function legacyFisher(data: readonly Bar[], length: number): number[] {
  const mid = data.map((b) => (b.high + b.low) / 2);
  const hi = highest(mid, length);
  const lo = lowest(mid, length);
  const out = new Array<number>(data.length).fill(NaN);
  let prevValue = 0;
  let prevFish = 0;
  for (let i = 0; i < data.length; i++) {
    const span = hi[i] - lo[i];
    if (!Number.isFinite(span)) { prevValue = 0; prevFish = 0; continue; }
    const raw = 0.66 * ((mid[i] - lo[i]) / Math.max(span, 0.001) - 0.5) + 0.67 * prevValue;
    const value = raw > 0.99 ? 0.999 : raw < -0.99 ? -0.999 : raw;
    const fish = 0.5 * Math.log((1 + value) / (1 - value)) + 0.5 * prevFish;
    out[i] = fish;
    prevValue = value;
    prevFish = fish;
  }
  return out;
}

/** The RVI's former private EMA, which reseeded after any gap. */
function legacySeededEma(values: readonly number[], period: number): number[] {
  const seed = sma(values, period);
  const k = 2 / (period + 1);
  let prev = NaN;
  return values.map((v, i) => {
    prev = !Number.isFinite(prev) ? seed[i] : Number.isFinite(v) ? v * k + prev * (1 - k) : NaN;
    return prev;
  });
}

function rviWith(data: readonly Bar[], length: number, average: (v: readonly number[], p: number) => number[]): number[] {
  const close = data.map((b) => b.close);
  const sd = stdev(close, length);
  const delta = change(close);
  const up = delta.map((d, i) => (Number.isFinite(d) && d <= 0 ? 0 : sd[i]));
  const down = delta.map((d, i) => (Number.isFinite(d) && d > 0 ? 0 : sd[i]));
  const upper = average(up, 14);
  const lower = average(down, 14);
  return upper.map((u, i) => (u + lower[i] === 0 ? NaN : (u / (u + lower[i])) * 100));
}

/** The RVI as 2.5.4 computed it. */
function legacyRvi(data: readonly Bar[], length: number): number[] {
  return rviWith(data, length, legacySeededEma);
}

/**
 * The language's rule for the same composition: each average seeds on its
 * first fourteen present inputs and holds across every later gap, the
 * warmup's included (K12).
 */
function heldRvi(data: readonly Bar[], length: number): number[] {
  return rviWith(data, length, smaSeededEma);
}

/** One-way runs of `run` bars, alternating direction, starting with a fall. */
const zigzag = (n: number, run: number): Bar[] => {
  let c = 100;
  let direction = -1;
  return Array.from({ length: n }, (_, i) => {
    if (i > 1 && (i - 1) % run === 0) direction = -direction;
    if (i > 0) c += direction * (1 + (i % 3) * 0.1);
    return {
      time: 1700000000 + i * 60, open: c - 0.25, high: c + 1.5, low: c - 1.5, close: c, volume: 100 + (i % 5),
    };
  });
};

/** A seeded random walk: nothing about it is tuned to a length. */
const walk = (n: number, level: number, seed: number): Bar[] => {
  let s = seed >>> 0;
  let c = level;
  return Array.from({ length: n }, (_, i) => {
    s = (Math.imul(s, 1664525) + 1013904223) >>> 0;
    c += (s / 2 ** 32 - 0.5) * level * 0.01;
    return {
      time: 1700000000 + i * 60, open: c, high: c + level * 0.002, low: c - level * 0.002, close: c, volume: 100 + (i % 7),
    };
  });
};

/** The Mass Index's former run-by-run smoothing of its second EMA and sum. */
function legacyRuns(values: readonly number[], period: number, smooth: (v: readonly number[], p: number) => number[]): number[] {
  const out = new Array<number>(values.length).fill(NaN);
  for (let i = 0; i < values.length;) {
    if (!Number.isFinite(values[i])) { i += 1; continue; }
    let end = i;
    while (end < values.length && Number.isFinite(values[end])) end += 1;
    smooth(values.slice(i, end), period).forEach((v, k) => { out[i + k] = v; });
    i = end;
  }
  return out;
}

function legacyMassIndex(data: readonly Bar[], length: number): number[] {
  const single = smaSeededEma(data.map((b) => b.high - b.low), 9);
  const double = legacyRuns(single, 9, smaSeededEma);
  const ratio = single.map((v, i) => (double[i] !== 0 ? v / double[i] : NaN));
  return legacyRuns(ratio, length, rollingSum);
}

/** NVI and PVI as 2.5.4 formed them, with the index average run by run. */
function legacyVolumeIndex(data: readonly Bar[], on: 'falling' | 'rising', maLength: number): [number[], number[]] {
  const vol = (b: Bar): number => (typeof b.volume === 'number' && Number.isFinite(b.volume) ? b.volume : 0);
  let index = 1;
  const out = data.map((b, i) => {
    if (i > 0) {
      const prevClose = data[i - 1].close;
      const moved = on === 'falling' ? vol(b) < vol(data[i - 1]) : vol(b) > vol(data[i - 1]);
      if (moved && prevClose !== 0 && Number.isFinite(prevClose)) index *= b.close / prevClose;
    }
    return index * 1000;
  });
  return [out, legacyRuns(out, maLength, smaSeededEma)];
}

function legacyStochasticRaw(data: readonly Bar[], period: number): number[] {
  const hi = highest(data.map((b) => b.high), period);
  const lo = lowest(data.map((b) => b.low), period);
  return data.map((b, i) => {
    const span = hi[i] - lo[i];
    return span > 0 ? ((b.close - lo[i]) / span) * 100 : NaN;
  });
}

/** Leading-gap EMA, as the TSI family chains it. */
function emaAfterGap(values: readonly number[], period: number): number[] {
  const start = values.findIndex((v) => Number.isFinite(v));
  const out = new Array<number>(values.length).fill(NaN);
  if (start < 0) return out;
  smaSeededEma(values.slice(start), period).forEach((v, i) => { out[start + i] = v; });
  return out;
}

function legacyTsi(data: readonly Bar[], short: number, long: number): number[] {
  const pc = change(data.map((b) => b.close));
  const smoothed = emaAfterGap(emaAfterGap(pc, long), short);
  const size = emaAfterGap(emaAfterGap(pc.map(Math.abs), long), short);
  return smoothed.map((v, i) => 100 * (v / size[i]));
}

/** A finite double as an exact integer count of 2^-1074. */
function exactUnits(x: number): bigint {
  const view = new DataView(new ArrayBuffer(8));
  view.setFloat64(0, x);
  const encoded = view.getBigUint64(0);
  const exponent = Number((encoded >> 52n) & 0x7ffn);
  const fraction = encoded & ((1n << 52n) - 1n);
  const magnitude = exponent === 0 ? fraction : ((1n << 52n) | fraction) << BigInt(exponent - 1);
  return encoded >> 63n ? -magnitude : magnitude;
}

/**
 * Correlation of each window with its bar index in exact rational arithmetic,
 * rounded only in the last two steps (a quotient and one square root).
 */
function exactTrendCorrelation(values: readonly number[], period: number): number[] {
  return values.map((_, i) => {
    if (i < period - 1) return NaN;
    let sx = 0n, sxx = 0n, sxy = 0n, sy = 0n, syy = 0n;
    for (let k = i - period + 1; k <= i; k++) {
      const x = exactUnits(values[k]);
      const y = BigInt(k);
      sx += x; sxx += x * x; sxy += x * y; sy += y; syy += y * y;
    }
    const n = BigInt(period);
    const cross = n * sxy - sx * sy;
    const spread = (n * sxx - sx * sx) * (n * syy - sy * sy);
    if (spread === 0n) return NaN;
    const r = Math.sqrt(Number((cross * cross << 200n) / spread) / 2 ** 200);
    return cross < 0n ? -r : r;
  });
}

/** Same bars present, every reading within `tolerance` of the former one. */
function expectCloseEverywhere(
  actual: readonly (number | null)[], former: readonly number[], tolerance: number,
): void {
  const previous = nulls(former);
  expect(actual.map((v) => v === null)).toEqual(previous.map((v) => v === null));
  let worst = 0;
  for (let i = 0; i < actual.length; i++) {
    if (actual[i] === null) continue;
    const a = actual[i] as number;
    const b = previous[i] as number;
    worst = Math.max(worst, Math.abs(a - b) / Math.max(1, Math.abs(b)));
  }
  expect(worst).toBeLessThanOrEqual(tolerance);
}

describe('ordinary gapless data keeps its readings', () => {
  const data = wave();

  it('CCI, Fisher, RVI and Mass Index are bit-for-bit unchanged', () => {
    for (const [period, k] of [[20, 0.015], [3, 0.015], [50, 0.02]] as const) {
      expect(run(CCI, data, { period, constant: k, maType: 'None' }).cci).toEqual(nulls(legacyCci(data, period, k)));
    }
    for (const length of [1, 2, 9, 30]) {
      expect(run(FISHER_TRANSFORM, data, { length }).fisher).toEqual(nulls(legacyFisher(data, length)));
    }
    for (const length of [1, 3, 10, 25]) {
      expect(run(MASS_INDEX, data, { length }).mi).toEqual(nulls(legacyMassIndex(data, length)));
    }
  });

  it('RVI is bit-for-bit what 2.5.4 printed at every deviation length', () => {
    // Up to a 16-bar deviation no average can seed and then meet an absent
    // bar inside the warmup. From 17 on it can: a fourteen-bar one-way run in
    // the warmup seeds one average, the next bar the other way is absent for
    // it, and 2.5.4 restarted there. The zigzag of fourteen-bar runs does that
    // at Length 17, the waves and walks at the longer lengths, so these series
    // pin the restart and not only the easy case.
    const series = [wave(), wave(400, 1e5), zigzag(400, 14), zigzag(400, 20), walk(600, 100, 7), walk(600, 25000, 99)];
    const lengths = [2, 10, 14, 16, 17, 30, 100];
    for (const bars of series) {
      for (const length of lengths) {
        const former = legacyRvi(bars, length);
        expect(run(RELATIVE_VOLATILITY_INDEX, bars, { length, maType: 'None' }).rvi, `length ${length}`)
          .toEqual(nulls(former));
        for (const maLength of [3, 14]) {
          expect(run(RELATIVE_VOLATILITY_INDEX, bars, { length, maType: 'EMA', maLength }).ma, `length ${length}`)
            .toEqual(nulls(legacySeededEma(former, maLength)));
        }
      }
    }
    // The language's hold-everywhere rule would move every one of the longer
    // lengths on at least one of these series, so the check above has teeth.
    for (const length of [17, 30, 100]) {
      const moved = series.some((bars) =>
        JSON.stringify(nulls(heldRvi(bars, length))) !== JSON.stringify(nulls(legacyRvi(bars, length))));
      expect(moved, `length ${length}`).toBe(true);
    }
  });

  it('NVI and PVI are bit-for-bit unchanged', () => {
    for (const bars of [data, wave(400, 1e5), walk(600, 100, 7)]) {
      for (const maLength of [1, 2, 20, 255]) {
        const [nvi, nviEma] = legacyVolumeIndex(bars, 'falling', maLength);
        const [pvi, pviEma] = legacyVolumeIndex(bars, 'rising', maLength);
        const negative = run(NVI, bars, { maLength });
        const positive = run(PVI, bars, { maLength });
        expect(negative.nvi).toEqual(nulls(nvi));
        expect(negative.ema).toEqual(nulls(nviEma));
        expect(positive.pvi).toEqual(nulls(pvi));
        expect(positive.ema).toEqual(nulls(pviEma));
      }
    }
  });

  it('Stochastic and the TSI family differ only in the last bits', () => {
    // Both change arithmetic order on purpose, so the check is on availability
    // (identical) and the size of the change (a few units in the last place).
    for (const period of [3, 14, 50]) {
      const raw = legacyStochasticRaw(data, period);
      expectCloseEverywhere(run(STOCHASTIC, data, { kPeriod: period, kSmoothing: 1, dPeriod: 3 }).k, raw, 1e-13);
    }
    for (const [long, short] of [[25, 13], [2, 2], [40, 5]] as const) {
      expectCloseEverywhere(run(TSI, data, { long, short }).tsi, legacyTsi(data, short, long), 1e-13);
    }
  });

  it('Trend Strength is within a few units in the last place of the exact correlation', () => {
    for (const level of [100, 1e5]) {
      const series = wave(400, level);
      for (const length of [2, 3, 14, 60]) {
        const exact = exactTrendCorrelation(series.map((b) => b.close), length);
        expectCloseEverywhere(run(TREND_STRENGTH_INDEX, series, { length }).tsi, exact, 1e-15);
      }
    }
  });
});
