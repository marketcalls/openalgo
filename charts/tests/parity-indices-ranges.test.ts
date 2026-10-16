/**
 * Parity regressions for the indices and ranges indicator groups.
 *
 * Every expectation is derived by hand from the published definition: either a
 * closed form the definition collapses to on a chosen series, a short table
 * worked through bar by bar in the comment above it, or a naive rebuild written
 * locally in this file. Nothing here reads a value back out of the code under
 * test, and nothing here calls `calc.ts`: a test that reused the shared helpers
 * would agree with the implementation whatever either of them computed.
 *
 * The warmup formulas are stated as arithmetic on the inputs rather than as
 * literals, because a warmup that is one bar out is the defect that shifts a
 * whole study against every other tool on the pane and is invisible in a spot
 * check of the values.
 */
import { describe, it, expect } from 'vitest';
import { NVI, PVI, PVT, PVO, MASS_INDEX, ULCER_INDEX } from '../src/indicators/indices';
import {
  STOCHASTIC_RSI, WILLIAMS_PERCENT_R, ULTIMATE_OSCILLATOR,
  RELATIVE_VIGOR_INDEX, RELATIVE_VOLATILITY_INDEX, WOODIES_CCI, SPECIAL_K,
} from '../src/indicators/ranges';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

type Row = { o?: number; h?: number; l?: number; c: number; v?: number };

const make = (rows: readonly Row[]): Bar[] =>
  rows.map((r, i) => ({
    time: 1735689600000 + i * 900000,
    open: r.o ?? r.c,
    high: r.h ?? r.c,
    low: r.l ?? r.c,
    close: r.c,
    volume: r.v ?? 1000,
  }));

/** A series with a range and a body on every bar, for the warmup assertions. */
const wave = (n: number): Bar[] =>
  make(Array.from({ length: n }, (_, i) => {
    const c = 100 + Math.sin(i / 5) * 10 + i * 0.05;
    return { o: c - 0.3, h: c + 1, l: c - 1, c, v: 1000 + ((i * 37) % 500) };
  }));

/**
 * Closes that change direction on every bar, so a two-bar RSI is never pinned
 * at an end of its scale and a short window always has some width to it. The
 * warmup formulas are exact only where the data actually leaves the study room
 * to print.
 */
const jagged = (n: number): Bar[] =>
  make(Array.from({ length: n }, (_, i) => {
    const c = 100 + i * 0.2 + (i % 2) * 2;
    return { o: c - 0.2, h: c + 0.9, l: c - 0.9, c, v: 1000 + ((i * 53) % 700) };
  }));

/** Strictly rising closes, the series most closed forms below are stated on. */
const rising = (n: number, step = 1): Bar[] =>
  make(Array.from({ length: n }, (_, i) => {
    const c = 100 + i * step;
    return { o: c, h: c + 1, l: c - 1, c, v: 1000 + i };
  }));

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {} as never);

const firstIndex = (col: readonly (number | null)[]): number =>
  col.findIndex((v) => v !== null);

// Naive rebuilds, written from the definition and used only as expectations.

/** Window mean, refusing any window that still holds a hole. */
const naiveSma = (v: readonly number[], n: number): number[] =>
  v.map((_, i) => {
    if (i < n - 1) return NaN;
    let acc = 0;
    for (let k = 0; k < n; k++) {
      const x = v[i - k];
      if (!Number.isFinite(x)) return NaN;
      acc += x;
    }
    return acc / n;
  });

/**
 * Exponential average seeded with the mean of the first `n` values, restarting
 * the seed hunt after any hole. First value lands on the last bar of the seed
 * window.
 */
const naiveEma = (v: readonly number[], n: number): number[] => {
  const seed = naiveSma(v, n);
  const k = 2 / (n + 1);
  const out = new Array<number>(v.length).fill(NaN);
  let prev = NaN;
  for (let i = 0; i < v.length; i++) {
    if (!Number.isFinite(prev)) prev = seed[i];
    else prev = Number.isFinite(v[i]) ? v[i] * k + prev * (1 - k) : NaN;
    out[i] = prev;
  }
  return out;
};

/** Wilder's RSI: the mean of the first `n` deltas, then the 1/n recursion. */
const naiveRsi = (v: readonly number[], n: number): number[] => {
  const out = new Array<number>(v.length).fill(NaN);
  if (v.length <= n) return out;
  let up = 0;
  let down = 0;
  for (let i = 1; i <= n; i++) {
    const d = v[i] - v[i - 1];
    if (d > 0) up += d;
    else down -= d;
  }
  up /= n;
  down /= n;
  out[n] = down === 0 ? 100 : 100 - 100 / (1 + up / down);
  for (let i = n + 1; i < v.length; i++) {
    const d = v[i] - v[i - 1];
    up = (up * (n - 1) + Math.max(d, 0)) / n;
    down = (down * (n - 1) + Math.max(-d, 0)) / n;
    out[i] = down === 0 ? 100 : 100 - 100 / (1 + up / down);
  }
  return out;
};

/** Position inside the window's own range, undefined when the range is zero. */
const naiveStoch = (v: readonly number[], n: number): number[] =>
  v.map((_, i) => {
    if (i < n - 1) return NaN;
    let hi = -Infinity;
    let lo = Infinity;
    for (let k = 0; k < n; k++) {
      const x = v[i - k];
      if (!Number.isFinite(x)) return NaN;
      if (x > hi) hi = x;
      if (x < lo) lo = x;
    }
    return hi === lo ? NaN : (100 * (v[i] - lo)) / (hi - lo);
  });

describe('Negative and Positive Volume Index', () => {
  /**
   * Fosback's index: a base of 1000 compounded by the bar's percentage price
   * change, but only across the bars where volume moved the qualifying way.
   * Every other bar carries the previous value forward, so there is no warmup
   * and bar 0 is the base itself.
   *
   *   i  close  volume  volume fell   NVI
   *   0    100    1000       -        1000
   *   1    110     900      yes       1000 * 110/100 = 1100
   *   2    121    1000       no       1100
   *   3    121     800      yes       1100 * 121/121 = 1100
   *   4    100     700      yes       1100 * 100/121 = 110000/121
   */
  const data = make([
    { c: 100, v: 1000 }, { c: 110, v: 900 }, { c: 121, v: 1000 },
    { c: 121, v: 800 }, { c: 100, v: 700 },
  ]);

  it('compounds only the falling-volume bars, from a base of 1000', () => {
    const out = run(NVI, data, { maLength: 3 });
    expect(firstIndex(out.nvi)).toBe(0);
    expect(out.nvi[0]).toBe(1000);
    expect(out.nvi[1]).toBeCloseTo(1100, 10);
    expect(out.nvi[2]).toBeCloseTo(1100, 10);
    expect(out.nvi[3]).toBeCloseTo(1100, 10);
    expect(out.nvi[4] as number).toBeCloseTo(110000 / 121, 10);
  });

  it('takes the complementary set of bars for the positive index', () => {
    // Only bar 2 rose, so the whole move lands there: 1000 * 121/110.
    const out = run(PVI, data, { maLength: 3 });
    expect(out.pvi[0]).toBe(1000);
    expect(out.pvi[1]).toBeCloseTo(1000, 10);
    expect(out.pvi[2] as number).toBeCloseTo((1000 * 121) / 110, 10);
    expect(out.pvi[4] as number).toBeCloseTo((1000 * 121) / 110, 10);
  });

  it('runs its signal average over the index, seeded from a plain mean', () => {
    // seed at bar 2 = (1000 + 1100 + 1100)/3, then alpha 2/(3+1).
    const out = run(NVI, data, { maLength: 3 });
    expect(firstIndex(out.ema)).toBe(2);
    const seed = 3200 / 3;
    expect(out.ema[2] as number).toBeCloseTo(seed, 10);
    expect(out.ema[3] as number).toBeCloseTo(1100 * 0.5 + seed * 0.5, 10);
    const third = 1100 * 0.5 + seed * 0.5;
    expect(out.ema[4] as number).toBeCloseTo((110000 / 121) * 0.5 + third * 0.5, 10);
  });

  it('holds the index across a zero previous close instead of compounding a hole', () => {
    // A zero close makes the percentage change undefined. Compounding it into a
    // running product would destroy every later bar, so the bar is skipped the
    // same way a non-qualifying one is.
    const out = run(NVI, make([{ c: 0, v: 1000 }, { c: 50, v: 900 }, { c: 55, v: 800 }]), { maLength: 2 });
    expect(out.nvi[0]).toBe(1000);
    expect(out.nvi[1]).toBe(1000);
    expect(out.nvi[2] as number).toBeCloseTo(1000 * (55 / 50), 10);
  });
});

describe('Price Volume Trend', () => {
  /**
   * The running total of the bar's percentage price change weighted by its
   * volume. Bar 0 has no previous close, contributes nothing, and the total
   * opens at 0 rather than at a gap.
   *
   *   i  close  volume  term                       running
   *   0    100    1000  none                             0
   *   1    110    2000  (10/100) * 2000 =  200         200
   *   2     99    3000  (-11/110) * 3000 = -300       -100
   *   3     99    4000  0                             -100
   */
  it('accumulates the volume-weighted percentage change from bar 0', () => {
    const out = run(PVT, make([
      { c: 100, v: 1000 }, { c: 110, v: 2000 }, { c: 99, v: 3000 }, { c: 99, v: 4000 },
    ]));
    expect(firstIndex(out.pvt)).toBe(0);
    expect(out.pvt[0]).toBe(0);
    expect(out.pvt[1] as number).toBeCloseTo(200, 10);
    expect(out.pvt[2] as number).toBeCloseTo(-100, 10);
    expect(out.pvt[3] as number).toBeCloseTo(-100, 10);
  });

  it('contributes nothing for a zero previous close and keeps accumulating after it', () => {
    const out = run(PVT, make([{ c: 0, v: 1000 }, { c: 100, v: 1000 }, { c: 110, v: 1000 }]));
    expect(out.pvt[0]).toBe(0);
    expect(out.pvt[1]).toBe(0);
    expect(out.pvt[2] as number).toBeCloseTo(100, 10);
  });
});

describe('Percentage Volume Oscillator', () => {
  /**
   * The spread between two averages of volume, expressed as a percentage of the
   * slower one, with the signal average run over the oscillator itself.
   *
   * volumes 100, 200, 300, 400, 500 with fast 2, slow 3, signal 2:
   *   fast (alpha 2/3): seed at 1 = 150, then 250, 350, 450
   *   slow (alpha 1/2): seed at 2 = 200, then 300, 400
   *   pvo: 100*(250-200)/200 = 25, 100*(350-300)/300 = 50/3, 100*(450-400)/400 = 12.5
   *   signal (alpha 2/3): seed at 3 = (25 + 50/3)/2 = 125/6, then 12.5*2/3 + (125/6)/3
   */
  const data = make([100, 200, 300, 400, 500].map((v) => ({ c: 10, v })));
  const over = { fastLength: 2, slowLength: 3, signalLength: 2 };

  it('normalises the spread by the slow average', () => {
    const out = run(PVO, data, over);
    expect(firstIndex(out.pvo)).toBe(2);
    expect(out.pvo[2] as number).toBeCloseTo(25, 10);
    expect(out.pvo[3] as number).toBeCloseTo(50 / 3, 10);
    expect(out.pvo[4] as number).toBeCloseTo(12.5, 10);
  });

  it('seeds the signal average on the oscillator, not on bar 0', () => {
    const out = run(PVO, data, over);
    expect(firstIndex(out.signal)).toBe(3);
    expect(out.signal[3] as number).toBeCloseTo(125 / 6, 10);
    expect(out.signal[4] as number).toBeCloseTo(12.5 * (2 / 3) + (125 / 6) * (1 / 3), 10);
    expect(out.hist[3] as number).toBeCloseTo(50 / 3 - 125 / 6, 10);
    expect(out.hist[4] as number).toBeCloseTo(12.5 - (12.5 * (2 / 3) + (125 / 6) * (1 / 3)), 10);
  });

  it('starts on the slower of the two averages', () => {
    for (const [fast, slow] of [[5, 10], [3, 7], [12, 26], [2, 40]]) {
      const out = run(PVO, wave(120), { fastLength: fast, slowLength: slow });
      expect(firstIndex(out.pvo), `fast ${fast} slow ${slow}`).toBe(Math.max(fast, slow) - 1);
    }
  });

  it('draws nothing where no volume traded, rather than dividing by zero', () => {
    const out = run(PVO, make(Array.from({ length: 40 }, () => ({ c: 100, v: 0 }))));
    expect(out.pvo.every((v) => v === null)).toBe(true);
    expect(out.signal.every((v) => v === null)).toBe(true);
  });
});

describe('Mass Index', () => {
  /**
   * The sum over `length` bars of a 9-bar average of the bar range divided by a
   * 9-bar average of that average. Both nines are part of the definition, not
   * inputs, and the second one restarts once the first has a value rather than
   * carrying its warmup hole forward. So the first reading lands at
   * 8 + 8 + (length - 1), which is `length + 15`.
   */
  it('collapses to the sum length on a series of constant range', () => {
    // Every range equal makes both averages that same constant and the ratio
    // exactly 1, so the sum of `length` ones is `length` itself.
    for (const length of [1, 5, 10, 25]) {
      const data = make(Array.from({ length: 80 }, (_, i) => ({ c: 100 + (i % 3), h: 100 + (i % 3) + 2, l: 100 + (i % 3) - 2 })));
      const out = run(MASS_INDEX, data, { length });
      expect(firstIndex(out.mi), `length ${length}`).toBe(length + 15);
      expect(out.mi[length + 15] as number, `length ${length}`).toBeCloseTo(length, 10);
      expect(out.mi[60] as number, `length ${length}`).toBeCloseTo(length, 10);
    }
  });

  it('matches a naive rebuild of the nested average on a moving series', () => {
    const data = wave(120);
    const span = data.map((b) => b.high - b.low);
    const single = naiveEma(span, 9);
    const double = naiveEma(single, 9);
    const ratio = single.map((v, i) => (double[i] === 0 ? NaN : v / double[i]));
    const expected = naiveSma(ratio, 10).map((v) => (Number.isFinite(v) ? v * 10 : NaN));
    const out = run(MASS_INDEX, data);
    for (const i of [25, 26, 40, 90, 119]) {
      expect(out.mi[i] as number, `bar ${i}`).toBeCloseTo(expected[i], 10);
    }
  });

  it('draws nothing when the smoothed range reaches zero', () => {
    // A run of bars with no range at all leaves the divisor at zero, and a
    // market with no expansion has no expansion to measure.
    const out = run(MASS_INDEX, make(Array.from({ length: 60 }, () => ({ c: 100 }))));
    expect(out.mi.every((v) => v === null)).toBe(true);
  });
});

describe('Ulcer Index', () => {
  /**
   * The root mean square percentage drawdown from the window's own running
   * high. The drawdown needs a full window and the mean needs a full window of
   * drawdowns, so the first reading lands at 2 * (length - 1).
   *
   * length 3 over closes 10, 12, 11, 9, 9:
   *   peaks at bars 2, 3, 4 are 12, 12, 11
   *   drawdowns 100*(11-12)/12, 100*(9-12)/12, 100*(9-11)/11
   *   the mean of their squares, square rooted, lands at bar 4
   */
  it('is the root mean square of the windowed percentage drawdowns', () => {
    const out = run(ULCER_INDEX, make([10, 12, 11, 9, 9].map((c) => ({ c }))), { length: 3 });
    expect(firstIndex(out.ui)).toBe(4);
    const dd = [(100 * (11 - 12)) / 12, (100 * (9 - 12)) / 12, (100 * (9 - 11)) / 11];
    const expected = Math.sqrt((dd[0] * dd[0] + dd[1] * dd[1] + dd[2] * dd[2]) / 3);
    expect(out.ui[4] as number).toBeCloseTo(expected, 10);
  });

  it('reads zero on a series that only rises, and starts at twice the window', () => {
    // Every close is its own window high, so every drawdown is zero. That is
    // the property that separates this from a standard deviation, which would
    // read the same rise as risk.
    for (const length of [3, 14, 20]) {
      const out = run(ULCER_INDEX, rising(80), { length });
      expect(firstIndex(out.ui), `length ${length}`).toBe(2 * (length - 1));
      expect(out.ui[2 * (length - 1)] as number, `length ${length}`).toBeCloseTo(0, 12);
      expect(out.ui[70] as number, `length ${length}`).toBeCloseTo(0, 12);
    }
  });

  it('draws nothing where the window high is zero', () => {
    const out = run(ULCER_INDEX, make(Array.from({ length: 40 }, () => ({ c: 0 }))), { length: 3 });
    expect(out.ui.every((v) => v === null)).toBe(true);
  });

  it('carries a zero edge for the shading wherever the line prints', () => {
    const out = run(ULCER_INDEX, rising(40), { length: 3 });
    expect(out.zero[3]).toBeNull();
    expect(out.zero[4]).toBe(0);
  });
});

describe('Stochastic RSI', () => {
  /**
   * The position of the RSI inside its own recent range, smoothed twice. Every
   * warmup stacks: `lengthRSI` bars for the RSI, `lengthStoch - 1` more before
   * its window is full of real values, then `smoothK - 1`. So K lands at
   * lengthRSI + lengthStoch + smoothK - 2 and D at smoothD - 1 beyond it.
   */
  it('stacks four warmups, on the defaults and on three other settings', () => {
    const data = jagged(140);
    const sets = [[14, 14, 3, 3], [7, 21, 5, 2], [21, 5, 1, 1], [2, 3, 2, 4]];
    for (const [lengthRSI, lengthStoch, smoothK, smoothD] of sets) {
      const out = run(STOCHASTIC_RSI, data, { lengthRSI, lengthStoch, smoothK, smoothD });
      const k = lengthRSI + lengthStoch + smoothK - 2;
      expect(firstIndex(out.k), `k ${lengthRSI}/${lengthStoch}/${smoothK}/${smoothD}`).toBe(k);
      expect(firstIndex(out.d), `d ${lengthRSI}/${lengthStoch}/${smoothK}/${smoothD}`).toBe(k + smoothD - 1);
    }
  });

  it('matches a naive rebuild of RSI, then position, then two means', () => {
    const data = wave(140);
    const r = naiveRsi(data.map((b) => b.close), 14);
    const expectedK = naiveSma(naiveStoch(r, 14), 3);
    const expectedD = naiveSma(expectedK, 3);
    const out = run(STOCHASTIC_RSI, data);
    for (const i of [29, 30, 45, 100, 139]) {
      expect(out.k[i] as number, `k bar ${i}`).toBeCloseTo(expectedK[i], 9);
    }
    for (const i of [31, 32, 45, 100, 139]) {
      expect(out.d[i] as number, `d bar ${i}`).toBeCloseTo(expectedD[i], 9);
    }
  });

  it('draws nothing while the RSI window has no range at all', () => {
    // A series that only rises pins the RSI at 100, and a window of identical
    // values has no width to measure a position against. The band edges still
    // have to exist, because the shading spans the whole pane.
    const out = run(STOCHASTIC_RSI, rising(80));
    expect(out.k.every((v) => v === null)).toBe(true);
    expect(out.d.every((v) => v === null)).toBe(true);
    expect(out.bandHigh[0]).toBe(80);
    expect(out.bandLow[79]).toBe(20);
  });
});

describe('Williams Percent Range', () => {
  /**
   * The distance from the window high down to the close, as a percentage of the
   * window. A close at the window high is 0 and one at the window low is -100.
   *
   *   i  high  low  close   window high  window low   %R over 3 bars
   *   0    10    8      9
   *   1    12    9     11
   *   2    11    7      8        12           7       100*(8-12)/5  = -80
   *   3    13   10     12        13           7       100*(12-13)/6 = -100/6
   */
  const data = make([
    { h: 10, l: 8, c: 9 }, { h: 12, l: 9, c: 11 },
    { h: 11, l: 7, c: 8 }, { h: 13, l: 10, c: 12 },
  ]);

  it('measures the close against the window high over the window range', () => {
    const out = run(WILLIAMS_PERCENT_R, data, { length: 3 });
    expect(firstIndex(out.percentR)).toBe(2);
    expect(out.percentR[2] as number).toBeCloseTo(-80, 10);
    expect(out.percentR[3] as number).toBeCloseTo(-100 / 6, 10);
  });

  it('pins the two ends of its scale exactly', () => {
    // A close at a fresh window high is 0 and one at the window low is -100:
    // the sign convention is the whole point of the study.
    const out = run(WILLIAMS_PERCENT_R, rising(40), { length: 5 });
    expect(firstIndex(out.percentR)).toBe(4);
    // On a rising series the close sits one unit under the current high and
    // four units plus one over the oldest low, so the window is 5 + 1 wide.
    expect(out.percentR[10] as number).toBeCloseTo((100 * -1) / 6, 10);
    const top = run(WILLIAMS_PERCENT_R, make([
      { h: 10, l: 5, c: 6 }, { h: 11, l: 6, c: 7 }, { h: 12, l: 7, c: 12 },
    ]), { length: 3 });
    expect(top.percentR[2] as number).toBeCloseTo(0, 12);
    const bottom = run(WILLIAMS_PERCENT_R, make([
      { h: 10, l: 5, c: 6 }, { h: 11, l: 6, c: 7 }, { h: 9, l: 5, c: 5 },
    ]), { length: 3 });
    expect(bottom.percentR[2] as number).toBeCloseTo(-100, 12);
  });

  it('draws nothing where the window has no range', () => {
    const out = run(WILLIAMS_PERCENT_R, make(Array.from({ length: 20 }, () => ({ c: 100 }))), { length: 5 });
    expect(out.percentR.every((v) => v === null)).toBe(true);
    expect(out.bandHigh[0]).toBe(-20);
    expect(out.bandLow[0]).toBe(-80);
  });
});

describe('Ultimate Oscillator', () => {
  /**
   * Buying pressure over true range across three horizons, weighted 4:2:1.
   * Both terms reach back to the previous close, so bar 0 contributes to
   * neither sum and the first reading lands at the longest of the three
   * lengths rather than one bar earlier.
   *
   *   i  high  low  close  prev close  low_  high_  bp  tr
   *   0     -    -     10           -      -      -   -   -
   *   1    12    9     11          10      9     12   2   3
   *   2    11    8     10          11      8     11   2   3
   *
   * Over two bars every horizon averages 4/6, so the weighted blend is
   * 100 * (7 * 2/3) / 7 = 200/3.
   */
  it('weights the three horizons 4:2:1 over seven', () => {
    const data = make([
      { h: 10, l: 10, c: 10 }, { h: 12, l: 9, c: 11 }, { h: 11, l: 8, c: 10 },
    ]);
    const out = run(ULTIMATE_OSCILLATOR, data, { length1: 2, length2: 2, length3: 2 });
    expect(firstIndex(out.uo)).toBe(2);
    expect(out.uo[2] as number).toBeCloseTo(200 / 3, 10);
  });

  it('reaches back to the previous close on a gap, on both terms', () => {
    /**
     * Bar 2 opens clear above bar 1's close, so the gap itself is part of the
     * move. Reading the bar's own low instead of the lower of the low and the
     * previous close would throw the gap away.
     *
     *   i  high  low  close  prev close  low_  high_  bp  tr
     *   1    12    9     11          10     9     12   2   3
     *   2    15   13     14          11    11     15   3   4
     *
     * Over two bars the ratio is 5/7, so the blend is 100 * 5/7.
     */
    const data = make([
      { h: 10, l: 10, c: 10 }, { h: 12, l: 9, c: 11 }, { h: 15, l: 13, c: 14 },
    ]);
    const out = run(ULTIMATE_OSCILLATOR, data, { length1: 2, length2: 2, length3: 2 });
    expect(out.uo[2] as number).toBeCloseTo(500 / 7, 10);
  });

  it('starts at the longest horizon, whichever of the three that is', () => {
    const data = wave(120);
    for (const [length1, length2, length3] of [[7, 14, 28], [3, 5, 9], [1, 1, 1], [28, 14, 7]]) {
      const out = run(ULTIMATE_OSCILLATOR, data, { length1, length2, length3 });
      expect(firstIndex(out.uo), `${length1}/${length2}/${length3}`)
        .toBe(Math.max(length1, length2, length3));
    }
  });

  it('draws nothing where the summed true range is zero', () => {
    const out = run(ULTIMATE_OSCILLATOR, make(Array.from({ length: 60 }, () => ({ c: 100 }))));
    expect(out.uo.every((v) => v === null)).toBe(true);
  });
});

describe('Relative Vigor Index', () => {
  /**
   * The bar body over the bar range, both put through the fixed four-bar
   * 1/2/2/1 kernel before being summed. The kernel needs four bars and the sum
   * needs `length` of its outputs, so the line starts at `length + 2` and the
   * signal three bars later.
   *
   *   i  open  close  body  high   low  range
   *   0    10     11     1    12     9      3
   *   1    11     10    -1  11.5   9.5      2
   *   2    10     12     2  12.5   9.5      3
   *   3    12     12     0    13    11      2
   *
   * kernel over the bodies  = (1 + 2*(-1) + 2*2 + 0)/6 = 1/2
   * kernel over the ranges  = (3 + 2*2 + 2*3 + 2)/6 = 5/2
   */
  it('divides the smoothed body by the smoothed range', () => {
    const data = make([
      { o: 10, c: 11, h: 12, l: 9 }, { o: 11, c: 10, h: 11.5, l: 9.5 },
      { o: 10, c: 12, h: 12.5, l: 9.5 }, { o: 12, c: 12, h: 13, l: 11 },
    ]);
    const out = run(RELATIVE_VIGOR_INDEX, data, { length: 1 });
    expect(firstIndex(out.rvgi)).toBe(3);
    expect(out.rvgi[3] as number).toBeCloseTo(0.2, 12);
  });

  it('starts three bars past the sum, and the signal three past that', () => {
    const data = wave(120);
    for (const length of [1, 4, 10, 20]) {
      const out = run(RELATIVE_VIGOR_INDEX, data, { length });
      expect(firstIndex(out.rvgi), `length ${length}`).toBe(length + 2);
      expect(firstIndex(out.signal), `length ${length}`).toBe(length + 5);
    }
  });

  it('draws nothing where the summed range is zero', () => {
    const out = run(RELATIVE_VIGOR_INDEX, make(Array.from({ length: 40 }, () => ({ c: 100 }))));
    expect(out.rvgi.every((v) => v === null)).toBe(true);
    expect(out.signal.every((v) => v === null)).toBe(true);
  });

  it('displaces both lines together when an offset is set', () => {
    const data = wave(60);
    const plain = run(RELATIVE_VIGOR_INDEX, data);
    const moved = run(RELATIVE_VIGOR_INDEX, data, { offset: 2 });
    expect(firstIndex(moved.rvgi)).toBe(firstIndex(plain.rvgi) + 2);
    expect(moved.rvgi[20] as number).toBeCloseTo(plain.rvgi[18] as number, 12);
  });
});

describe('Relative Volatility Index', () => {
  /**
   * The RSI construction applied to the standard deviation instead of to price:
   * how much of the recent deviation arrived on up bars. The `length` input is
   * the deviation's window only. The two averages are smoothed over a fixed 14
   * whatever `length` says, which is why the first reading is at
   * (length - 1) + 13 and not at (length - 1) + (length - 1).
   */
  it('smooths over a fixed fourteen, not over the deviation window', () => {
    const data = wave(140);
    for (const length of [2, 5, 10, 30]) {
      const out = run(RELATIVE_VOLATILITY_INDEX, data, { length });
      expect(firstIndex(out.rvi), `length ${length}`).toBe(length + 12);
    }
  });

  it('reads 100 on a one-way rise and 0 on a one-way fall', () => {
    // Every bar up puts the whole deviation in the upper average and leaves the
    // lower one at exactly zero, so the ratio is 1. The mirror series pins the
    // other end, which is what catches a flipped sign.
    const up = run(RELATIVE_VOLATILITY_INDEX, rising(80), { length: 10 });
    expect(firstIndex(up.rvi)).toBe(22);
    expect(up.rvi[22] as number).toBeCloseTo(100, 10);
    expect(up.rvi[70] as number).toBeCloseTo(100, 10);
    const down = run(RELATIVE_VOLATILITY_INDEX, rising(80, -1), { length: 10 });
    expect(firstIndex(down.rvi)).toBe(22);
    expect(down.rvi[22] as number).toBeCloseTo(0, 10);
    expect(down.rvi[70] as number).toBeCloseTo(0, 10);
  });

  it('draws nothing where the deviation is zero on both sides', () => {
    const out = run(RELATIVE_VOLATILITY_INDEX, make(Array.from({ length: 60 }, () => ({ c: 100 }))));
    expect(out.rvi.every((v) => v === null)).toBe(true);
    expect(out.bandHigh[0]).toBe(80);
    expect(out.bandLow[0]).toBe(20);
  });

  it('keeps the band columns absent unless the Bollinger kernel is chosen', () => {
    const data = wave(80);
    const plain = run(RELATIVE_VOLATILITY_INDEX, data, { maType: 'SMA' });
    expect(plain.bbUpper.every((v) => v === null)).toBe(true);
    const bands = run(RELATIVE_VOLATILITY_INDEX, data, { maType: 'SMA + Bollinger Bands' });
    expect(bands.bbUpper.some((v) => v !== null)).toBe(true);
    expect(run(RELATIVE_VOLATILITY_INDEX, data, { maType: 'None' }).ma.every((v) => v === null)).toBe(true);
  });
});

describe('Woodies CCI', () => {
  /**
   * A slow and a fast Commodity Channel Index drawn together. This variant
   * reads the close rather than the typical price, and the slow index is
   * plotted twice: once shaped as a histogram and once as a line.
   *
   * On any evenly rising series the index has a closed form, because the mean
   * sits at the window centre and the mean absolute deviation is the mean
   * distance from that centre. With `n` bars the numerator is the step times
   * (n - 1)/2 and the mean deviation is the step times the mean of |k - centre|:
   *
   *   n = 6:  (5/2) / (0.015 * 3/2)  = 2.5 / 0.0225   = 1000/9
   *   n = 14: (13/2) / (0.015 * 7/2) = 6.5 / 0.0525   = 1000 * 13 / 105
   *
   * The step cancels out, so the same two numbers hold on any linear series.
   */
  it('has a closed form on a linear series, on both lengths', () => {
    for (const step of [1, 7.5]) {
      const out = run(WOODIES_CCI, rising(60, step));
      expect(firstIndex(out.turbo), `step ${step}`).toBe(5);
      expect(firstIndex(out.cci14), `step ${step}`).toBe(13);
      expect(out.turbo[40] as number, `step ${step}`).toBeCloseTo(1000 / 9, 9);
      expect(out.cci14[40] as number, `step ${step}`).toBeCloseTo((1000 * 13) / 105, 9);
    }
  });

  it('reads the close, not the typical price', () => {
    // The two agree on any series whose high and low sit symmetrically about
    // the close, so the highs and lows here wobble independently of it. This
    // variant of the study is defined on the close; the standalone index is the
    // one that takes the typical price, and the two must not be confused.
    const data = make(Array.from({ length: 60 }, (_, i) => {
      const c = 100 + Math.sin(i / 4) * 6;
      return { c, h: c + (i % 5), l: c - (i % 3) };
    }));
    const naiveCci = (v: readonly number[], n: number): number[] => {
      const mean = naiveSma(v, n);
      return v.map((x, i) => {
        if (!Number.isFinite(mean[i])) return NaN;
        let acc = 0;
        for (let k = 0; k < n; k++) acc += Math.abs(v[i - k] - mean[i]);
        const md = acc / n;
        return md === 0 ? NaN : (x - mean[i]) / (0.015 * md);
      });
    };
    const closes = data.map((b) => b.close);
    const typical = data.map((b) => (b.high + b.low + b.close) / 3);
    const out = run(WOODIES_CCI, data);
    for (const [column, n] of [['cci14', 14], ['turbo', 6]] as const) {
      const onClose = naiveCci(closes, n);
      const onTypical = naiveCci(typical, n);
      expect(out[column][40] as number, column).toBeCloseTo(onClose[40], 9);
      expect(Math.abs(onClose[40] - onTypical[40]), column).toBeGreaterThan(1);
    }
  });

  it('plots the slow index twice, as one series', () => {
    const out = run(WOODIES_CCI, wave(80));
    expect(out.hist).toEqual(out.cci14);
    expect(out.hist).not.toEqual(out.turbo);
  });

  it('draws nothing where the window has no deviation', () => {
    const out = run(WOODIES_CCI, make(Array.from({ length: 40 }, () => ({ c: 100 }))));
    expect(out.turbo.every((v) => v === null)).toBe(true);
    expect(out.cci14.every((v) => v === null)).toBe(true);
  });
});

describe("Pring's Special K", () => {
  /**
   * Twelve rates of change, each smoothed and weighted, added into one line.
   * The slowest term is a 530-bar rate of change smoothed over 195, so nothing
   * prints before bar 530 + 195 - 1, and the twice-smoothed signal is 198 bars
   * behind that on the default hundreds.
   */
  it('carries the slowest term into its warmup', () => {
    const out = run(SPECIAL_K, wave(1000));
    expect(firstIndex(out.specialK)).toBe(724);
    expect(out.specialK[723]).toBeNull();
    expect(firstIndex(out.signal)).toBe(922);
  });

  it('drops the whole sum where a rate of change has a zero base', () => {
    // One zero close is enough: the term that reaches back to it is undefined,
    // and an undefined term makes the total undefined rather than smaller.
    const data = wave(1000);
    const zeroed = data.map((b, i) => (i === 200 ? { ...b, close: 0 } : b));
    const out = run(SPECIAL_K, zeroed);
    expect(out.specialK[730]).toBeNull();
    // The reach of the 530-bar term is what puts the hole here, and the series
    // recovers once every window has cleared it.
    expect(out.specialK[999]).not.toBeNull();
  });
});
