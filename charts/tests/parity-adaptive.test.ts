/**
 * Parity regression for the adaptive tier: the numbers each of these studies
 * must produce, derived by hand from the standard definition rather than read
 * back out of the code.
 *
 * Every expectation here is a closed form. Where a study is recursive, the
 * recursion is written out in the test from its own definition (seed point,
 * alpha, and all), so a change to the implementation cannot quietly drag the
 * expectation along with it.
 */
import { describe, it, expect } from 'vitest';
import {
  ADAPTIVE_INDICATORS,
  KAMA, KELTNER_CHANNEL, LSMA, KLINGER_OSCILLATOR, KNOW_SURE_THING, LINREG_SLOPE,
} from '../src/indicators/adaptive';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * A symmetric bar, so `hlc3` collapses to the close and the true range is the
 * full `2 * half` on every bar after the first. That is what makes the range
 * family hand-checkable without a second series of arithmetic.
 */
const bar = (i: number, close: number, half = 1, volume = 1000): Bar => ({
  time: 1700000000000 + i * 60000,
  open: close,
  high: close + half,
  low: close - half,
  close,
  volume,
});
const from = (closes: readonly number[], half = 1, volume = 1000): Bar[] =>
  closes.map((c, i) => bar(i, c, half, volume));
const ramp = (n: number, f: (i: number) => number, half = 1, volume = 1000): Bar[] =>
  Array.from({ length: n }, (_, i) => bar(i, f(i), half, volume));

const run = (d: IndicatorDescriptor, data: Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...overrides }, {});

/** Index of the first plotted bar: the number every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const at = (col: readonly (number | null)[], i: number): number => col[i] as number;

describe('Linear Regression Slope', () => {
  it('is registered last in the tier array under its public id', () => {
    expect(ADAPTIVE_INDICATORS[ADAPTIVE_INDICATORS.length - 1]).toBe(LINREG_SLOPE);
    expect(LINREG_SLOPE.id).toBe('linreg-slope');
    expect(LINREG_SLOPE.name).toBe('Linear Regression Slope');
    expect(LINREG_SLOPE.placement).toBe('pane');
    expect(LINREG_SLOPE.inputs.find((i) => i.key === 'periods')?.default).toBe(14);
  });

  it('first prints at periods - 1, the earliest bar the window is full', () => {
    const data = ramp(60, (i) => 100 + Math.sin(i / 4) * 5);
    expect(firstLive(run(LINREG_SLOPE, data).slope)).toBe(13);
    expect(firstLive(run(LINREG_SLOPE, data, { periods: 7 }).slope)).toBe(6);
    expect(firstLive(run(LINREG_SLOPE, data, { periods: 30 }).slope)).toBe(29);
    // Fewer bars than the window needs is an empty plot, not a throw.
    expect(run(LINREG_SLOPE, data.slice(0, 13)).slope.every((v) => v === null)).toBe(true);
  });

  it('recovers the gradient of a straight line exactly', () => {
    // Fit a line to a line and the slope comes back, whatever the window length.
    const data = ramp(40, (i) => 100 + 2.5 * i);
    for (const periods of [2, 7, 14, 30]) {
      const out = run(LINREG_SLOPE, data, { periods }).slope;
      for (let i = periods - 1; i < data.length; i++) {
        expect(at(out, i), `periods ${periods} bar ${i}`).toBeCloseTo(2.5, 12);
      }
    }
  });

  it('reports price per bar, not per window', () => {
    // The x axis is unit-spaced and nothing rescales the result, so widening the
    // window on the same straight line must not multiply the answer. A reading
    // that scaled by the window would give 2.5 * 6 against 2.5 * 29 here.
    const data = ramp(40, (i) => 100 + 2.5 * i);
    expect(at(run(LINREG_SLOPE, data, { periods: 7 }).slope, 39)).toBeCloseTo(2.5, 12);
    expect(at(run(LINREG_SLOPE, data, { periods: 30 }).slope, 39)).toBeCloseTo(2.5, 12);
  });

  it('matches a window worked out by hand', () => {
    // Closes 10, 12, 11, 20 with x running 1..3 over the window.
    // Bar 2: sum(y) = 33, sum(xy) = 10 + 24 + 33 = 67, denominator 3*14 - 36 = 6,
    //        slope = (3*67 - 6*33) / 6 = 0.5.
    // Bar 3: sum(y) = 43, sum(xy) = 12 + 22 + 60 = 94,
    //        slope = (3*94 - 6*43) / 6 = 4.
    const out = run(LINREG_SLOPE, from([10, 12, 11, 20]), { periods: 3 }).slope;
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(at(out, 2)).toBeCloseTo(0.5, 12);
    expect(at(out, 3)).toBeCloseTo(4, 12);
  });

  it('collapses to the bar-to-bar change at the shortest legal window', () => {
    // Over two points the least-squares line passes through both, so the slope
    // is the plain first difference. This pins the x spacing on its own.
    const out = run(LINREG_SLOPE, from([10, 12, 11, 20]), { periods: 2 }).slope;
    expect(out[0]).toBeNull();
    expect([at(out, 1), at(out, 2), at(out, 3)]).toEqual([2, -1, 9]);
  });

  it('reads zero on a flat tape and negative on a falling one', () => {
    const flat = run(LINREG_SLOPE, ramp(30, () => 100)).slope;
    for (let i = 13; i < 30; i++) expect(at(flat, i)).toBe(0);
    const down = run(LINREG_SLOPE, ramp(30, (i) => 100 - 1.5 * i)).slope;
    expect(at(down, 29)).toBeCloseTo(-1.5, 12);
  });

  it('has no zero-denominator case reachable through its input floor', () => {
    // The denominator is period^2 * (period^2 - 1) / 12, which vanishes only at
    // period 1. A settings blob carrying 1, 0 or a fraction is floored to 2, so
    // the plot stays finite instead of emitting Infinity.
    const data = from([10, 12, 11, 20]);
    for (const periods of [1, 0, -5, 1.4]) {
      const out = run(LINREG_SLOPE, data, { periods }).slope;
      expect(out, `periods ${periods}`).toEqual([null, 2, -1, 9]);
    }
  });
});

describe('Least Squares Moving Average', () => {
  it('sits on a straight line and steps back down it with an offset', () => {
    // Slope 2 per bar: the fit is the line itself, so the endpoint is the close,
    // and an offset of 3 walks three bars back down the same line.
    const data = ramp(40, (i) => 100 + 2 * i);
    const out = run(LSMA, data).lsma;
    expect(firstLive(out)).toBe(24);
    expect(at(out, 30)).toBeCloseTo(160, 10);
    expect(at(run(LSMA, data, { offset: 3 }).lsma, 30)).toBeCloseTo(154, 10);
  });
});

describe('Know Sure Thing', () => {
  it('starts where the slowest term does, and the signal one window later', () => {
    // The slowest term is a 30-bar rate of change smoothed over 15, so it first
    // exists at 30 + 15 - 1 = 44. The 9-bar signal then needs a full window of
    // those, landing at 44 + 9 - 1 = 52.
    const data = ramp(80, (i) => 100 + Math.sin(i / 6) * 4 + i * 0.1);
    const out = run(KNOW_SURE_THING, data);
    expect(firstLive(out.kst)).toBe(44);
    expect(firstLive(out.signal)).toBe(52);
    const wider = run(KNOW_SURE_THING, data, { roclen4: 20, smalen4: 10, siglen: 5 });
    // With the fourth term shortened the first term (10 + 10 - 1 = 19) is no
    // longer the fastest constraint: the third (20 + 10 - 1 = 29) is.
    expect(firstLive(wider.kst)).toBe(29);
    expect(firstLive(wider.signal)).toBe(33);
  });

  it('sums the four smoothed rates of change with weights 1, 2, 3 and 4', () => {
    // On a constant-growth tape every rate of change is constant, so each term
    // is its own rate of change and the whole study collapses to a number that
    // can be written down: 100 * (1.01^n - 1) for each horizon.
    const data = ramp(80, (i) => 100 * Math.pow(1.01, i));
    const term = (n: number) => 100 * (Math.pow(1.01, n) - 1);
    const want = term(10) + 2 * term(15) + 3 * term(20) + 4 * term(30);
    const out = run(KNOW_SURE_THING, data);
    expect(at(out.kst, 60)).toBeCloseTo(want, 8);
    expect(at(out.signal, 60)).toBeCloseTo(want, 8);
  });
});

describe('Klinger Oscillator', () => {
  // The periods are fixed by the definition and exposed as no input.
  const V = 1000;
  const fast = (i: number) => V - (V / 17) * (33 / 35) ** (i - 33);
  const slow = (i: number) => V - ((2 * V) / 55) * (27 / 28) ** (i - 54);

  it('stacks the two warmups: 55 bars for the spread, 13 more for the signal', () => {
    const data = ramp(80, (i) => 100 + Math.sin(i / 5) * 3, 1, V);
    const out = run(KLINGER_OSCILLATOR, data);
    expect(firstLive(out.kvo)).toBe(54);
    expect(firstLive(out.signal)).toBe(66);
  });

  it('signs an unchanged bar up and the first bar down', () => {
    // On a flat tape every change is zero. The comparison is "greater than or
    // equal", so those bars sign positive, while bar 0 has no previous close to
    // compare against and falls to the negative arm. That single negative bar is
    // the whole reason the spread is not zero here, which is what makes this
    // check discriminating: a strict "greater than" would sign every bar
    // negative, both averages would sit on -1000, and the spread would be flat 0.
    //
    // With volume constant at 1000 the seeds are therefore
    //   34-bar average at bar 33: (-1000 + 33 * 1000) / 34
    //   55-bar average at bar 54: (-1000 + 54 * 1000) / 55
    // and each then decays toward 1000 at its own alpha, 2/35 and 2/56.
    const out = run(KLINGER_OSCILLATOR, ramp(80, () => 100, 1, V));
    expect(at(out.kvo, 54)).toBeCloseTo(fast(54) - slow(54), 9);
    expect(at(out.kvo, 60)).toBeCloseTo(fast(60) - slow(60), 9);
    expect(at(out.kvo, 79)).toBeCloseTo(fast(79) - slow(79), 9);
    expect(at(out.kvo, 54)).toBeGreaterThan(0);
  });

  it('re-seeds the signal average from the first full window of the spread', () => {
    // The spread is unknown until bar 54, so the 13-bar signal cannot use an
    // average that reaches back past it: its first value is the plain mean of
    // bars 54 to 66, not a recursion carried through the warmup gap.
    const out = run(KLINGER_OSCILLATOR, ramp(80, () => 100, 1, V));
    let acc = 0;
    for (let i = 54; i <= 66; i++) acc += fast(i) - slow(i);
    expect(at(out.signal, 66)).toBeCloseTo(acc / 13, 9);
  });
});

describe('Keltner Channels', () => {
  it('seeds the basis from the simple average at length - 1', () => {
    // Closes 10, 20, 30, 40 over a 3-bar window: the seed is the mean 20 at bar
    // 2, then alpha = 2/(3+1) gives 40 * 0.5 + 20 * 0.5 = 30 at bar 3.
    const out = run(KELTNER_CHANNEL, from([10, 20, 30, 40]), { length: 3 });
    expect(out.basis[1]).toBeNull();
    expect(at(out.basis, 2)).toBeCloseTo(20, 12);
    expect(at(out.basis, 3)).toBeCloseTo(30, 12);
  });

  it('takes the simple average instead when the exponential flag is off', () => {
    const out = run(KELTNER_CHANNEL, from([10, 20, 30, 40]), { length: 3, exp: false });
    expect(at(out.basis, 2)).toBeCloseTo(20, 12);
    expect(at(out.basis, 3)).toBeCloseTo(30, 12);
  });

  it('widens each rail by the multiplier, on every band style', () => {
    // Symmetric bars of half-width 1 around a flat close: the bar range is 2 and
    // the previous close sits inside it, so the true range is 2 on every bar and
    // all three rail measures agree at 2. The rails are then basis +/- mult * 2.
    const data = ramp(40, () => 100);
    for (const bandsStyle of ['Average True Range', 'True Range', 'Range']) {
      const out = run(KELTNER_CHANNEL, data, { bandsStyle });
      expect(at(out.basis, 30), bandsStyle).toBeCloseTo(100, 10);
      expect(at(out.upper, 30), bandsStyle).toBeCloseTo(104, 10);
      expect(at(out.lower, 30), bandsStyle).toBeCloseTo(96, 10);
      expect(at(run(KELTNER_CHANNEL, data, { bandsStyle, mult: 0.5 }).upper, 30), bandsStyle)
        .toBeCloseTo(101, 10);
    }
  });

  it('starts the band at whichever of the basis and the rail is slower', () => {
    const data = ramp(60, (i) => 100 + Math.sin(i / 7) * 6);
    // Default: a 20-bar basis against a 10-bar range average, so the basis wins.
    expect(firstLive(run(KELTNER_CHANNEL, data).upper)).toBe(19);
    // A 5-bar basis against the same 10-bar range average reverses that.
    expect(firstLive(run(KELTNER_CHANNEL, data, { length: 5 }).upper)).toBe(9);
    // The raw range needs no window of its own, so only the basis holds it back.
    expect(firstLive(run(KELTNER_CHANNEL, data, { length: 5, bandsStyle: 'True Range' }).upper))
      .toBe(4);
    // The averaged range runs over its own ATR length, which is free to be the
    // slower of the two.
    expect(firstLive(run(KELTNER_CHANNEL, data, { length: 5, atrlength: 20 }).upper)).toBe(19);
    // The Range style smooths high minus low over the channel length instead, so
    // it warms up with the basis and ignores the ATR length entirely.
    const range = { bandsStyle: 'Range', length: 5, atrlength: 20 };
    expect(firstLive(run(KELTNER_CHANNEL, data, range).upper)).toBe(4);
  });
});

describe("Kaufman's Adaptive Moving Average", () => {
  const fastAlpha = 2 / 3;
  const slowAlpha = 2 / 31;

  it('interpolates the smoothing constant by the efficiency ratio', () => {
    // Two up, one down, repeating: over any ten bars the tape walks 15 points to
    // travel 5, so the efficiency ratio is exactly 1/3 from bar 10 onward and
    // the smoothing constant is the square of the interpolated alpha.
    const closes = [100];
    for (let i = 1; i < 30; i++) closes.push(closes[i - 1] + (i % 2 === 1 ? 2 : -1));
    const out = run(KAMA, from(closes)).kama;
    const alpha = (1 / 3) * (fastAlpha - slowAlpha) + slowAlpha;
    expect(at(out, 10)).toBe(closes[10]); // seeded on the source, no prior average
    expect(at(out, 11)).toBeCloseTo(closes[10] + alpha * alpha * (closes[11] - closes[10]), 12);
    let prev = closes[10];
    for (let i = 11; i < 30; i++) prev += alpha * alpha * (closes[i] - prev);
    expect(at(out, 29)).toBeCloseTo(prev, 10);
  });

  it('treats a window that never moved as maximally inefficient, not as a divide by zero', () => {
    const out = run(KAMA, ramp(30, () => 100)).kama;
    for (let i = 10; i < 30; i++) {
      expect(Number.isFinite(at(out, i)), `bar ${i}`).toBe(true);
      expect(at(out, i)).toBeCloseTo(100, 12);
    }
  });
});
