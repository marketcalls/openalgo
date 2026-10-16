/**
 * Parity for the studies built on the seeded exponential average: ZLEMA,
 * VIDYA, Elder-Ray and the Schaff Trend Cycle, against their published
 * formulas.
 *
 * Every expectation is worked out by hand from the definition on a fixture
 * small enough to follow, and the arithmetic is written beside it so a reader
 * can re-derive it without running anything. Nothing is read back out of
 * `calc`. The first printed bar and the zero-denominator rules are pinned as
 * explicitly as the values: a line that opens a bar early sits shifted against
 * every other tool, and a flat window is where published variants disagree.
 */
import { describe, it, expect } from 'vitest';
import { ZLEMA, VIDYA, ELDER_RAY, SCHAFF_TREND_CYCLE, EXPONENTIAL_INDICATORS } from '../src/indicators/exponential';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const at = (i: number): number => 1735689600 + i * 900;

/** Bars carrying a close; high and low sit `up` and `down` away from it. */
const closeBars = (closes: readonly number[], up = 1, down = 1): Bar[] =>
  closes.map((c, i) => ({ time: at(i), open: c, high: c + up, low: c - down, close: c, volume: 1000 }));

/** A seeded random walk, the shape of a traded stock, for the warmup checks. */
function walk(n: number, seed = 7): Bar[] {
  let s = seed;
  const rnd = (): number => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const out: Bar[] = [];
  let price = 1000;
  for (let i = 0; i < n; i++) {
    const open = price;
    price = Math.max(1, price * (1 + (rnd() - 0.5) * 0.02));
    const high = Math.max(open, price) * (1 + rnd() * 0.005);
    const low = Math.min(open, price) * (1 - rnd() * 0.005);
    out.push({ time: at(i), open, high, low, close: price, volume: 1000 + Math.floor(rnd() * 5000) });
  }
  return out;
}

const run = (d: IndicatorDescriptor, bars: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(bars, { ...indicatorDefaults(d), ...over }, {});

const firstFinite = (a: readonly (number | null)[]): number =>
  a.findIndex((v) => typeof v === 'number' && Number.isFinite(v));

describe('the exponential family', () => {
  it('ships four descriptors, each registered by its own id', () => {
    expect(EXPONENTIAL_INDICATORS.map((d) => d.id)).toEqual(['zlema', 'vidya', 'elder-ray', 'schaff-trend-cycle']);
  });
});

describe('ZLEMA', () => {
  // length 3: lag = floor((3 - 1) / 2) = 1, alpha = 2 / (3 + 1) = 0.5.
  //   close  10  12  11  14  13  15
  //   data    -  14  10  17  12  17     data = close + (close - close[1])
  //   bar 3  seed = mean(14, 10, 17)     = 41/3
  //   bar 4  0.5 * 12 + 0.5 * 41/3       = 77/6
  //   bar 5  0.5 * 17 + 0.5 * 77/6       = 179/12
  const bars = closeBars([10, 12, 11, 14, 13, 15]);

  it('is an EMA of the source pushed ahead by its own change over the lag', () => {
    const out = run(ZLEMA, bars, { length: 3 }).zlema;
    expect(out.slice(0, 3)).toEqual([null, null, null]);
    expect(out[3]).toBeCloseTo(41 / 3, 12);
    expect(out[4]).toBeCloseTo(77 / 6, 12);
    expect(out[5]).toBeCloseTo(179 / 12, 12);
  });

  it('first prints at lag + length - 1, since the first lag bars have no change to add', () => {
    // Default length 20: lag 9, so the EMA's first full window ends at 9 + 19.
    expect(firstFinite(run(ZLEMA, walk(80)).zlema)).toBe(28);
    expect(firstFinite(run(ZLEMA, walk(80), { length: 4 }).zlema)).toBe(1 + 3);
  });

  it('sits on a straight ramp exactly when the length is odd, the lag it was built to remove', () => {
    // On close = i with lag (L - 1) / 2, data = i + lag, whose seed mean is i and
    // whose every EMA step lands back on i: alpha * lag = (1 - alpha).
    const ramp = closeBars(Array.from({ length: 40 }, (_, i) => 100 + i));
    const out = run(ZLEMA, ramp, { length: 7 }).zlema;
    for (let i = 9; i < 40; i++) expect(out[i]).toBeCloseTo(100 + i, 9);
  });

  it('is the source itself at length 1', () => {
    const out = run(ZLEMA, bars, { length: 1 }).zlema;
    expect(out).toEqual([10, 12, 11, 14, 13, 15]);
  });
});

describe('VIDYA', () => {
  // length 3 (alpha 0.5), cmoLength 3. k = |up - down| / (up + down) over the
  // last three one-bar changes, the Chande momentum as a fraction.
  //   close    10  11  13  12  14  15
  //   change    -   1   2  -1   2   1
  //   bar 3  up 3, down 1, k = 1/2     seed on the source          = 12
  //   bar 4  up 4, down 1, k = 3/5     0.3 * 14 + 0.7 * 12         = 12.6
  //   bar 5  up 3, down 1, k = 1/2     0.25 * 15 + 0.75 * 12.6     = 13.2
  const bars = closeBars([10, 11, 13, 12, 14, 15]);

  it('weights each step by alpha times the momentum share of the window', () => {
    const out = run(VIDYA, bars, { length: 3, cmoLength: 3 }).vidya;
    expect(out.slice(0, 3)).toEqual([null, null, null]);
    expect(out[3]).toBe(12);
    expect(out[4]).toBeCloseTo(12.6, 12);
    expect(out[5]).toBeCloseTo(13.2, 12);
  });

  it('first prints at cmoLength, seeded on the source there', () => {
    const data = walk(60);
    const out = run(VIDYA, data).vidya;
    expect(firstFinite(out)).toBe(9);
    expect(out[9]).toBe(data[9].close);
  });

  it('holds its value through a window that did not move at all', () => {
    // A flat window is 0/0. It has no momentum, so k is 0 and the average
    // stays where it was rather than dropping out or restarting.
    //   close 10 10 10 10 10 12
    //   bar 3 seed 10; bar 4 k 0, holds 10; bar 5 changes 0 0 2, k 1: 0.5 * 12 + 0.5 * 10 = 11
    const out = run(VIDYA, closeBars([10, 10, 10, 10, 10, 12]), { length: 3, cmoLength: 3 }).vidya;
    expect(out.slice(3)).toEqual([10, 10, 11]);
  });

  it('skips the bars whose window holds a missing close and resumes from the value it held', () => {
    // A missing close at 5 spoils the changes at 5 and 6, so the windows
    // ending at 5 through 8 have no reading. Bar 9 resumes from bar 4's value.
    //   close 10 11 13 12 14  -  14 15 16 18
    //   bar 9 changes 1 1 2: up 4, down 0, k 1, 0.5 * 18 + 0.5 * 12.6 = 15.3
    const closes = [10, 11, 13, 12, 14, NaN, 14, 15, 16, 18];
    const out = run(VIDYA, closeBars(closes), { length: 3, cmoLength: 3 }).vidya;
    expect(out[4]).toBeCloseTo(12.6, 12);
    expect(out.slice(5, 9)).toEqual([null, null, null, null]);
    expect(out[9]).toBeCloseTo(15.3, 12);
  });
});

describe('Elder-Ray', () => {
  // length 3, alpha 0.5, over the close. High is close + 2, low is close - 3.
  //   close 10 12 14 13
  //   ema    -  - 12 12.5
  //   bull   -  - 16 - 12 = 4     15 - 12.5 = 2.5
  //   bear   -  - 11 - 12 = -1    10 - 12.5 = -2.5
  const bars = closeBars([10, 12, 14, 13], 2, 3);

  it('is the high and the low measured from the same EMA of the close', () => {
    const out = run(ELDER_RAY, bars, { length: 3 });
    expect(out.bull).toEqual([null, null, 4, 2.5]);
    expect(out.bear).toEqual([null, null, -1, -2.5]);
  });

  it('first prints where the EMA does, at length - 1', () => {
    const out = run(ELDER_RAY, walk(40));
    expect(firstFinite(out.bull)).toBe(12);
    expect(firstFinite(out.bear)).toBe(12);
  });

  it('never has bear power above bull power, since a low never tops its high', () => {
    const out = run(ELDER_RAY, walk(200));
    for (let i = 12; i < 200; i++) expect(out.bull[i]! - out.bear[i]!).toBeGreaterThanOrEqual(0);
  });
});

describe('Schaff Trend Cycle', () => {
  // fast 2 (alpha 2/3), slow 3 (alpha 1/2), cycle 3, factor 0.5.
  //   close  10 12 11 13 16 14 15 18 17 19
  //
  //   fast EMA, seed mean(10, 12) = 11 at bar 1, then 2/3 x + 1/3 prev:
  //     11, 11, 37/3, 133/9, 385/27, 1195/81, 4111/243, 12373/729, 40075/2187
  //   slow EMA, seed mean(10, 12, 11) = 11 at bar 2, then halfway:
  //     11, 12, 14, 14, 14.5, 16.25, 16.625, 17.8125
  //   macd, bars 2..9, over 2187:
  //     0, 729, 1701, 567, 553.5, 1460.25, 760.125, 1119.0625
  //
  //   f1 = 100 * (macd - lowest) / (highest - lowest) over three macd values:
  //     bar 4  (0, 729, 1701)              100
  //     bar 5  (729, 1701, 567)            0
  //     bar 6  (1701, 567, 553.5)          0
  //     bar 7  (567, 553.5, 1460.25)       100
  //     bar 8  (553.5, 1460.25, 760.125)   100 * 206.625 / 906.75
  //     bar 9  (1460.25, 760.125, 1119.0625)  100 * 358.9375 / 700.125
  //   pf seeds on f1, then halfway to each new f1: 100, 50, 25, 62.5, ...
  //   f2 is the same stochastic over pf, first at bar 6; stc seeds on f2 and
  //   moves halfway to each new f2.
  const bars = closeBars([10, 12, 11, 13, 16, 14, 15, 18, 17, 19]);
  const s = { fastLength: 2, slowLength: 3, cycleLength: 3, factor: 0.5 };

  const f18 = (100 * 206.625) / 906.75;
  const f19 = (100 * 358.9375) / 700.125;
  const pf = [100, 50, 25, 62.5];
  pf.push(62.5 + 0.5 * (f18 - 62.5));
  pf.push(pf[4] + 0.5 * (f19 - pf[4]));
  // f2 over pf windows ending at bars 6..9 (pf index 2..5)
  const stoch = (w: number[], x: number): number => (100 * (x - Math.min(...w))) / (Math.max(...w) - Math.min(...w));
  const f2 = [2, 3, 4, 5].map((k) => stoch(pf.slice(k - 2, k + 1), pf[k]));
  const stc = [f2[0]];
  for (let k = 1; k < 4; k++) stc.push(stc[k - 1] + 0.5 * (f2[k] - stc[k - 1]));

  it('is a smoothed stochastic of a smoothed stochastic of the MACD', () => {
    // The worked values: f2 = 0, 100, ..., so stc opens at 0 and then halves
    // its distance to each new f2.
    expect(f2[0]).toBe(0);
    expect(f2[1]).toBe(100);
    const out = run(SCHAFF_TREND_CYCLE, bars, s).stc;
    expect(out.slice(0, 6)).toEqual([null, null, null, null, null, null]);
    expect(out[6]).toBe(0);
    expect(out[7]).toBe(50);
    expect(out[8]).toBeCloseTo(stc[2], 10);
    expect(out[9]).toBeCloseTo(stc[3], 10);
  });

  it('first prints at slow + 2 * cycle - 3: the MACD warmup, then two stochastic windows', () => {
    expect(firstFinite(run(SCHAFF_TREND_CYCLE, walk(120)).stc)).toBe(50 + 20 - 3);
    expect(firstFinite(run(SCHAFF_TREND_CYCLE, bars, s).stc)).toBe(6);
  });

  it('stays inside 0..100 and declares that range with 25 and 75 levels', () => {
    const out = run(SCHAFF_TREND_CYCLE, walk(400)).stc;
    for (const v of out) if (v !== null) { expect(v).toBeGreaterThanOrEqual(0); expect(v).toBeLessThanOrEqual(100); }
    const settings = indicatorDefaults(SCHAFF_TREND_CYCLE);
    expect(SCHAFF_TREND_CYCLE.range?.(settings)).toEqual({ min: 0, max: 100 });
    expect(SCHAFF_TREND_CYCLE.levels?.(settings).map((l) => l.price)).toEqual([75, 25]);
  });

  it('prints nothing when the MACD never moves, since a flat window before any reading has none to repeat', () => {
    expect(run(SCHAFF_TREND_CYCLE, closeBars(new Array(120).fill(100))).stc.every((v) => v === null)).toBe(true);
    // Equal lengths make the MACD zero on every bar, the same flat window.
    expect(run(SCHAFF_TREND_CYCLE, walk(120), { fastLength: 20, slowLength: 20 }).stc.every((v) => v === null)).toBe(true);
  });

  it('repeats its last reading through a flat window after one, rather than dropping out', () => {
    // fast 1 is the close itself and slow 3 halves toward it, so every value
    // below is exact. From bar 5 each close is the slow EMA before it plus 2,
    // which holds the MACD at exactly 1.
    //   close  10 12 14    11   16    15.75 16.75 17.75 18.75 19.75 20.75
    //   slow    -  - 12  11.5 13.75   14.75 15.75 16.75 ...
    //   macd    -  -  2  -0.5  2.25    1     1     1     1 ...
    //   f1 bar 4 (2, -0.5, 2.25) 100; bar 5 (-0.5, 2.25, 1) 1.5 / 2.75 * 100;
    //      bar 6 (2.25, 1, 1) 0; bar 7 on (1, 1, 1) has no range and repeats 0
    //   pf 100, then halfway to each f1, so it only falls: f2 is 0 from bar 6
    // Dropping the flat windows instead would leave bars 7 onwards empty.
    const closes = [10, 12, 14, 11, 16, 15.75, 16.75, 17.75, 18.75, 19.75, 20.75];
    const out = run(SCHAFF_TREND_CYCLE, closeBars(closes), { fastLength: 1, slowLength: 3, cycleLength: 3, factor: 0.5 }).stc;
    expect(out.slice(0, 6)).toEqual([null, null, null, null, null, null]);
    expect(out.slice(6)).toEqual([0, 0, 0, 0, 0]);
  });
});
