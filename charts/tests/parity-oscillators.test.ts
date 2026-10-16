/**
 * Parity regression for the oscillator family, measured against the standard
 * definitions of Aroon, the Aroon Oscillator, the Awesome Oscillator, Balance
 * of Power, Chande Momentum, the Coppock Curve, the Detrended Price
 * Oscillator, the Fisher Transform and Connors RSI.
 *
 * Every expectation below is worked out from the definition on a fixture small
 * enough to do by hand, never read back out of `calc`. Each block records the
 * arithmetic so a future reader can re-derive it without running anything.
 *
 * Warmup indices and zero-denominator behaviour are pinned deliberately: a
 * series that starts one bar early sits shifted against every other tool in the
 * pane, and a zero denominator is the one place these nine disagree about
 * whether to draw a gap, carry a value or clamp.
 */
import { describe, it, expect } from 'vitest';
import {
  AROON, AROON_OSCILLATOR, AWESOME_OSCILLATOR, BALANCE_OF_POWER, CHANDE_MOMENTUM,
  COPPOCK_CURVE, DPO, FISHER_TRANSFORM, CONNORS_RSI, connorsStreak,
} from '../src/indicators/oscillators';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const at = (i: number): number => 1735689600000 + i * 900000;

/** Bars from explicit highs and lows, with open and close pinned inside them. */
const hlBars = (highs: readonly number[], lows: readonly number[]): Bar[] =>
  highs.map((h, i) => ({
    time: at(i), open: (h + lows[i]) / 2, high: h, low: lows[i], close: (h + lows[i]) / 2, volume: 1000,
  }));

/** Bars carrying a close only: high and low sit one unit either side. */
const closeBars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({ time: at(i), open: c, high: c + 1, low: c - 1, close: c, volume: 1000 }));

const run = (d: IndicatorDescriptor, bars: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(bars, { ...indicatorDefaults(d), ...over }, {} as never);

const firstFinite = (a: readonly (number | null)[]): number =>
  a.findIndex((v) => typeof v === 'number' && Number.isFinite(v));

describe('Aroon', () => {
  // length 3, so the window is 4 bars (the study counts the gaps between bars,
  // not the bars). `highestbars` is the negative offset to the extreme, zero on
  // the current bar, and ties resolve to the most recent bar.
  //
  //   highs 10 12 11  9  8 13 13  7
  //   lows   5  6  4  7  3  3  9  9
  //
  //   bar 3  highs 10,12,11,9  peak at bar 1, offset -2  up   = 100*(-2+3)/3 = 33.333333
  //          lows   5, 6, 4,7  low  at bar 2, offset -1  down = 100*(-1+3)/3 = 66.666667
  //   bar 4  peak still bar 1, offset -3                 up   = 100*0/3      = 0
  //          low at bar 4, offset 0                      down = 100          = 100
  //   bar 5  peak bar 5, offset 0                        up   = 100
  //          low ties bars 4 and 5, newest wins, 0       down = 100
  //   bar 6  peak ties bars 5 and 6, newest wins, 0      up   = 100
  //          low ties bars 4 and 5, newest is 5, -1      down = 66.666667
  //   bar 7  peak ties 5 and 6, newest is 6, -1          up   = 66.666667
  //          low ties 4 and 5, newest is 5, -2           down = 100*(-2+3)/3 = 33.333333
  const highs = [10, 12, 11, 9, 8, 13, 13, 7];
  const lows = [5, 6, 4, 7, 3, 3, 9, 9];

  it('maps the offset to the extreme onto 0..100', () => {
    const out = run(AROON, hlBars(highs, lows), { length: 3 });
    expect(out.up.slice(3)).toEqual([
      100 / 3 * 1, 0, 100, 100, 100 / 3 * 2,
    ].map((v) => expect.closeTo(v, 10)));
    expect(out.down.slice(3)).toEqual([
      100 / 3 * 2, 100, 100, 100 / 3 * 2, 100 / 3 * 1,
    ].map((v) => expect.closeTo(v, 10)));
  });

  it('starts at index length, one bar after the window fills', () => {
    const out = run(AROON, hlBars(highs, lows), { length: 3 });
    expect(out.up.slice(0, 3)).toEqual([null, null, null]);
    expect(firstFinite(out.up)).toBe(3);
    expect(firstFinite(out.down)).toBe(3);
    // The default length is 14, so the default warmup is 14 bars, not 13.
    const long = run(AROON, closeBars(Array.from({ length: 30 }, (_, i) => 100 + i)));
    expect(firstFinite(long.up)).toBe(14);
  });

  it('reads a flat series as a fresh extreme on both legs', () => {
    // Every bar ties, ties resolve to the current bar, so both offsets are 0
    // and both legs read exactly 100. No division by a zero range is involved:
    // the denominator is the length, never the price range.
    const out = run(AROON, closeBars(new Array(20).fill(100)), { length: 5 });
    expect(out.up[19]).toBe(100);
    expect(out.down[19]).toBe(100);
  });
});

describe('Aroon Oscillator', () => {
  // Aroon Up minus Aroon Down on the same window, which reduces to
  // 100 * (upOffset - downOffset) / length. Same fixture as above.
  const bars = hlBars([10, 12, 11, 9, 8, 13, 13, 7], [5, 6, 4, 7, 3, 3, 9, 9]);

  it('is the signed gap between the two legs', () => {
    const out = run(AROON_OSCILLATOR, bars, { length: 3 });
    expect(out.osc.slice(3)).toEqual([
      -100 / 3, -100, 0, 100 / 3, 100 / 3,
    ].map((v) => expect.closeTo(v, 10)));
  });

  it('shares Aroon warmup and carries a zero edge only where the line prints', () => {
    const out = run(AROON_OSCILLATOR, bars, { length: 3 });
    expect(firstFinite(out.osc)).toBe(3);
    expect(out.zero.slice(0, 3)).toEqual([null, null, null]);
    expect(out.zero[3]).toBe(0);
  });
});

describe('Awesome Oscillator', () => {
  // sma(hl2, 5) - sma(hl2, 34), both periods fixed by the definition.
  //
  // The fixture keeps the midpoint clear of the close so the two cannot be
  // mistaken for each other: high = i^2 + i + 1000, low = i^2 - 1 + 1000,
  // close = i^2 + 1000, giving hl2 = i^2 + (i - 1)/2 + 1000. The constant
  // cancels in the difference, so with exact polynomial averages
  //   on i^2:       sma5 = i^2 - 4i + 6, sma34 = i^2 - 33i + 368.5, gap 29i - 362.5
  //   on (i - 1)/2: sma5 = (i - 3)/2,    sma34 = (i - 17.5)/2,      gap 7.25
  // the oscillator is 29i - 355.25: 601.75 at bar 33, rising by 29 a bar. The
  // same study read off the close instead would print 594.5.
  const squares: Bar[] = Array.from({ length: 40 }, (_, i) => ({
    time: at(i), open: i * i + 1000, high: i * i + i + 1000, low: i * i - 1 + 1000,
    close: i * i + 1000, volume: 1000,
  }));

  it('is the gap between the 5 and 34 bar midpoint averages', () => {
    const out = run(AWESOME_OSCILLATOR, squares);
    expect(out.ao[33] as number).toBeCloseTo(601.75, 9);
    expect(out.ao[34] as number).toBeCloseTo(630.75, 9);
    expect(out.ao[35] as number).toBeCloseTo(659.75, 9);
  });

  it('reads the bar midpoint, not the close', () => {
    // A close-based reading of the same bars is 594.5 at bar 33, so the two are
    // 7.25 apart and cannot both pass.
    const out = run(AWESOME_OSCILLATOR, squares);
    expect(Math.abs((out.ao[33] as number) - 594.5)).toBeCloseTo(7.25, 9);
  });

  it('starts at index 33, where the 34 bar average first exists', () => {
    const out = run(AWESOME_OSCILLATOR, squares);
    expect(out.ao[32]).toBeNull();
    expect(firstFinite(out.ao)).toBe(33);
  });

  it('is a constant 14.5 on a unit ramp, the difference of the two lags', () => {
    // A straight line makes each average lag by (period - 1) / 2, so the gap is
    // 16.5 - 2. Useful because it also drives the colour rule to an exact tie.
    const ramp = closeBars(Array.from({ length: 40 }, (_, i) => i)).map((b, i) => ({
      ...b, high: i + 1, low: i - 1,
    }));
    const out = run(AWESOME_OSCILLATOR, ramp);
    expect(out.ao[33] as number).toBeCloseTo(14.5, 10);
    expect(out.ao[39] as number).toBeCloseTo(14.5, 10);

    // Colour is the second half of the signal: falling when the change against
    // the previous bar is <= 0, so an exact tie is falling, and the first
    // printed bar has no previous value and reads rising.
    const s = indicatorDefaults(AWESOME_OSCILLATOR);
    const colorBy = AWESOME_OSCILLATOR.plots[0].colorBy!;
    const call = (i: number) =>
      colorBy({ value: out.ao[i] as number, index: i, values: out, settings: s });
    expect(call(33)).toBe(s.upColor);
    expect(call(34)).toBe(s.downColor);
  });
});

describe('Balance of Power', () => {
  it('is where the close finished inside the range, relative to the open', () => {
    // (close - open) / (high - low): (12 - 10) / (14 - 8) = 2 / 6.
    const bars: Bar[] = [{ time: at(0), open: 10, high: 14, low: 8, close: 12, volume: 1000 }];
    expect(run(BALANCE_OF_POWER, bars).bop[0] as number).toBeCloseTo(1 / 3, 12);
  });

  it('prints from bar zero: it has no window and no warmup', () => {
    const out = run(BALANCE_OF_POWER, closeBars([10, 11, 12]));
    expect(firstFinite(out.bop)).toBe(0);
  });

  it('draws a gap on a zero range bar rather than a spike', () => {
    // A bar with high === low forces open === close === high === low too, so
    // the quotient is 0/0. The standard definition carries no guard, which
    // makes the value undefined, so the bar has to draw as a gap.
    const bars: Bar[] = [
      { time: at(0), open: 10, high: 12, low: 8, close: 11, volume: 1000 },
      { time: at(1), open: 10, high: 10, low: 10, close: 10, volume: 1000 },
    ];
    const out = run(BALANCE_OF_POWER, bars);
    expect(out.bop[0]).not.toBeNull();
    expect(out.bop[1]).toBeNull();
  });
});

describe('Chande Momentum Oscillator', () => {
  // 100 * (sumUp - sumDown) / (sumUp + sumDown) over `length` one bar changes.
  // An unchanged close counts as an up move of zero, not a down move.
  //
  //   closes  10 12 11 14 14  9  9  9
  //   change      +2 -1 +3  0 -5  0  0
  //
  //   bar 3  changes +2,-1,+3   up 5  down 1  100 * 4/6  =  66.666667
  //   bar 4  changes -1,+3, 0   up 3  down 1  100 * 2/4  =  50
  //   bar 5  changes +3, 0,-5   up 3  down 5  100 * -2/8 = -25
  //   bar 6  changes  0,-5, 0   up 0  down 5  100 * -5/5 = -100
  //   bar 7  changes -5, 0, 0   up 0  down 5             = -100
  const closes = [10, 12, 11, 14, 14, 9, 9, 9];

  it('is the signed ratio of summed up moves to summed total movement', () => {
    const out = run(CHANDE_MOMENTUM, closeBars(closes), { length: 3 });
    expect(out.cmo.slice(3)).toEqual([
      200 / 3, 50, -25, -100, -100,
    ].map((v) => expect.closeTo(v, 10)));
  });

  it('starts at index length, because the first bar has no change behind it', () => {
    const out = run(CHANDE_MOMENTUM, closeBars(closes), { length: 3 });
    expect(out.cmo.slice(0, 3)).toEqual([null, null, null]);
    expect(firstFinite(out.cmo)).toBe(3);
    // Default length 9, so the default first print is bar 9, not bar 8.
    const long = run(CHANDE_MOMENTUM, closeBars(Array.from({ length: 20 }, (_, i) => 100 + (i % 3))));
    expect(firstFinite(long.cmo)).toBe(9);
  });

  it('draws a gap when the window has no movement at all', () => {
    // Every change zero makes both sums zero and the quotient 0/0.
    const out = run(CHANDE_MOMENTUM, closeBars(new Array(10).fill(100)), { length: 3 });
    expect(out.cmo.every((v) => v === null)).toBe(true);
  });
});

describe('Coppock Curve', () => {
  // wma(roc(close, long) + roc(close, short), wmaLength).
  //
  // Closes 100, 150, 225, 337.5, 506.25, 1012.5 with long 2 and short 1:
  //   roc2  bar 2..4  100*(225-100)/100 = 125, and 125, 125; bar 5 100*675/337.5 = 200
  //   roc1  bar 1..4  50 throughout;            bar 5 100*506.25/506.25 = 100
  //   sum   bar 2..4  175;                      bar 5 300
  //   wma3  bar 4  (175*3 + 175*2 + 175*1)/6 = 175
  //         bar 5  (300*3 + 175*2 + 175*1)/6 = 1425/6 = 237.5
  const closes = [100, 150, 225, 337.5, 506.25, 1012.5];

  it('weights the newest rate of change most heavily', () => {
    const out = run(COPPOCK_CURVE, closeBars(closes), { wmaLength: 3, longRoCLength: 2, shortRoCLength: 1 });
    expect(out.curve[4] as number).toBeCloseTo(175, 10);
    expect(out.curve[5] as number).toBeCloseTo(237.5, 10);
  });

  it('starts at longRoCLength + wmaLength - 1', () => {
    const out = run(COPPOCK_CURVE, closeBars(closes), { wmaLength: 3, longRoCLength: 2, shortRoCLength: 1 });
    expect(out.curve.slice(0, 4)).toEqual([null, null, null, null]);
    expect(firstFinite(out.curve)).toBe(4);
    // Defaults 10 / 14 / 11 put the first print at bar 23.
    const geo = closeBars(Array.from({ length: 40 }, (_, i) => 100 * 1.01 ** i));
    expect(firstFinite(run(COPPOCK_CURVE, geo).curve)).toBe(23);
  });

  it('gaps where a rate of change divides by a zero base', () => {
    const out = run(COPPOCK_CURVE, closeBars([0, 10, 20, 30, 40, 50, 60]), {
      wmaLength: 2, longRoCLength: 2, shortRoCLength: 1,
    });
    // Bar 2 divides by close[0] = 0, so it is undefined, and the weighted
    // average carrying it is undefined too. Bar 4 is the first clean window.
    expect(out.curve[3]).toBeNull();
    expect(out.curve[4]).not.toBeNull();
  });
});

describe('Detrended Price Oscillator', () => {
  // barsback = floor(period / 2) + 1. At period 4 that is 3.
  //
  //   closes 10 20 30 40 50 60 70 80 90 200
  //   sma4       -  -  - 25 35 45 55 65 75 110
  //
  // Plain mode is close[i] - ma[i - 3]:
  //   bar 6  70 -  25 =  45     bar 7  80 - 35 = 45
  //   bar 8  90 -  45 =  45     bar 9 200 - 55 = 145
  //
  // Centered mode is the same figure drawn three bars earlier, which folds to
  // close[i] - ma[i + 3]:
  //   bars 0..5  -15 throughout   bar 6  70 - 110 = -40
  //   bars 7..9  nothing, the line stops barsback short of the right edge
  const closes = [10, 20, 30, 40, 50, 60, 70, 80, 90, 200];

  it('measures price against an average taken barsback ago', () => {
    const out = run(DPO, closeBars(closes), { period: 4 });
    expect(out.dpo.slice(6)).toEqual([45, 45, 45, 145].map((v) => expect.closeTo(v, 10)));
  });

  it('starts at period - 1 + barsback in plain mode', () => {
    const out = run(DPO, closeBars(closes), { period: 4 });
    expect(out.dpo.slice(0, 6)).toEqual([null, null, null, null, null, null]);
    expect(firstFinite(out.dpo)).toBe(6);
    // Default period 21 gives barsback 11 and a first print at bar 31.
    const long = run(DPO, closeBars(Array.from({ length: 60 }, (_, i) => 100 + i)));
    expect(firstFinite(long.dpo)).toBe(31);
  });

  it('leads by barsback in centered mode and stops short of the right edge', () => {
    const out = run(DPO, closeBars(closes), { period: 4, isCentered: true });
    expect(out.dpo.slice(0, 7)).toEqual([-15, -15, -15, -15, -15, -15, -40].map((v) => expect.closeTo(v, 10)));
    expect(out.dpo.slice(7)).toEqual([null, null, null]);
  });

  it('truncates barsback the same way for odd and even periods', () => {
    // floor(period / 2) + 1 is 11 for both 20 and 21, so the two lengths share
    // a displacement and differ only in the average.
    const ramp = closeBars(Array.from({ length: 60 }, (_, i) => 100 + i));
    expect(firstFinite(run(DPO, ramp, { period: 20 }).dpo)).toBe(30);
    expect(firstFinite(run(DPO, ramp, { period: 21 }).dpo)).toBe(31);
  });
});

describe('Fisher Transform', () => {
  // value = clamp(0.66 * ((hl2 - low_) / max(high_ - low_, 0.001) - 0.5) + 0.67 * value[1])
  // fish  = 0.5 * ln((1 + value) / (1 - value)) + 0.5 * fish[1]
  // with a missing previous term reading as zero and the clamp at +/-0.999.
  //
  // length 2 on hl2 = 10, 12, 11, 11, 12, 15:
  //   bar 1  range 10..12, ratio 1     value  0.33      fish  0.342828254415
  //   bar 2  range 11..12, ratio 0     value -0.1089    fish  0.062080548537
  //   bar 3  range 11..11, flat, the 0.001 floor makes the ratio 0, not a gap
  //                                    value -0.402963  fish -0.396141035568
  //   bar 4  range 11..12, ratio 1     value  0.060015  fish -0.137983518413
  //   bar 5  range 12..15, ratio 1     value  0.37021   fish  0.319674566319
  const highs = [11, 13, 12, 12, 12, 16];
  const lows = [9, 11, 10, 10, 12, 14];
  const bars = hlBars(highs, lows);

  it('carries both recursions through a flat window instead of gapping', () => {
    const out = run(FISHER_TRANSFORM, bars, { length: 2 });
    expect(out.fisher[1] as number).toBeCloseTo(0.342828254415, 11);
    expect(out.fisher[2] as number).toBeCloseTo(0.062080548537, 11);
    expect(out.fisher[3] as number).toBeCloseTo(-0.396141035568, 11);
    expect(out.fisher[4] as number).toBeCloseTo(-0.137983518413, 11);
    expect(out.fisher[5] as number).toBeCloseTo(0.319674566319, 11);
  });

  it('starts at length - 1 and lags the trigger by exactly one bar', () => {
    const out = run(FISHER_TRANSFORM, bars, { length: 2 });
    expect(out.fisher[0]).toBeNull();
    expect(firstFinite(out.fisher)).toBe(1);
    expect(firstFinite(out.trigger)).toBe(2);
    for (let i = 2; i < bars.length; i++) expect(out.trigger[i]).toBe(out.fisher[i - 1]);
    // Default length 9 puts the first print at bar 8.
    const long = run(FISHER_TRANSFORM, closeBars(Array.from({ length: 30 }, (_, i) => 100 + (i % 7))));
    expect(firstFinite(long.fisher)).toBe(8);
  });

  it('holds at zero on a perfectly flat series rather than diverging', () => {
    // Every window is flat, so every ratio is 0 and every raw value is
    // -0.33 + 0.67 * previous, which converges rather than reaching the clamp.
    const out = run(FISHER_TRANSFORM, closeBars(new Array(30).fill(100)), { length: 3 });
    expect(firstFinite(out.fisher)).toBe(2);
    for (const v of out.fisher.slice(2)) expect(Number.isFinite(v as number)).toBe(true);
    expect(Math.abs(out.fisher[29] as number)).toBeLessThan(10);
  });
});

describe('Connors RSI', () => {
  it('counts the signed streak, resetting on an unchanged close', () => {
    // Bar 0 has no previous close, so it is neither equal nor greater and lands
    // in the down branch against a carry of zero, which is -1.
    //
    //   closes 10 11 12 12 11 10 10 12
    //   streak -1  1  2  0 -1 -2  0  1
    expect(connorsStreak([10, 11, 12, 12, 11, 10, 10, 12])).toEqual([-1, 1, 2, 0, -1, -2, 0, 1]);
  });

  it('starts at rocLength + 1, the slowest of its three legs', () => {
    // The one bar rate of change is undefined on bar 0, and the percent rank
    // compares the current value against the previous rocLength of them, so the
    // first complete rank is at rocLength + 1.
    const wobble = closeBars(Array.from({ length: 60 }, (_, i) => 100 + Math.sin(i / 3) * 5 + i * 0.1));
    expect(firstFinite(run(CONNORS_RSI, wobble, { lenrsi: 3, lenupdown: 2, lenroc: 20 }).crsi)).toBe(21);
    expect(firstFinite(run(CONNORS_RSI, wobble, { lenrsi: 3, lenupdown: 2, lenroc: 40 }).crsi)).toBe(41);
    // When the price RSI is the slowest leg it sets the warmup instead: its own
    // first value lands at bar lenrsi, because bar 0 carries no change.
    expect(firstFinite(run(CONNORS_RSI, wobble, { lenrsi: 30, lenupdown: 2, lenroc: 5 }).crsi)).toBe(30);
  });

  it('reads exactly 100 on a flat series, where every leg saturates', () => {
    // No losses at all makes both RSI legs 100. Every one bar return is 0, so
    // the whole rank window ties with the current value and the rank is 100.
    // The mean of the three is therefore 100, not a gap and not a division by
    // zero: the RSI denominator is guarded, and the rank divides by its length.
    const out = run(CONNORS_RSI, closeBars(new Array(40).fill(100)), { lenrsi: 3, lenupdown: 2, lenroc: 20 });
    expect(firstFinite(out.crsi)).toBe(21);
    expect(out.crsi[21] as number).toBeCloseTo(100, 10);
    expect(out.crsi[39] as number).toBeCloseTo(100, 10);
  });

  it('keeps the shaded band spanning the pane through the warmup', () => {
    const out = run(CONNORS_RSI, closeBars(new Array(40).fill(100)), { lenroc: 20 });
    expect(out.bandHigh[0]).toBe(70);
    expect(out.bandLow[0]).toBe(30);
    expect(out.bandHigh).toHaveLength(40);
  });
});

describe('defaults match the standard definitions', () => {
  it('pins the published default parameters', () => {
    const d = (x: IndicatorDescriptor) => indicatorDefaults(x);
    expect(d(AROON).length).toBe(14);
    expect(d(AROON_OSCILLATOR).length).toBe(14);
    expect(d(CHANDE_MOMENTUM).length).toBe(9);
    expect(d(CHANDE_MOMENTUM).source).toBe('close');
    expect(d(COPPOCK_CURVE).wmaLength).toBe(10);
    expect(d(COPPOCK_CURVE).longRoCLength).toBe(14);
    expect(d(COPPOCK_CURVE).shortRoCLength).toBe(11);
    expect(d(DPO).period).toBe(21);
    expect(d(DPO).isCentered).toBe(false);
    expect(d(FISHER_TRANSFORM).length).toBe(9);
    expect(d(CONNORS_RSI).lenrsi).toBe(3);
    expect(d(CONNORS_RSI).lenupdown).toBe(2);
    expect(d(CONNORS_RSI).lenroc).toBe(100);
    // The Awesome Oscillator's 5 and 34 are the definition, not a preference,
    // so they are not exposed as inputs at all.
    expect(AWESOME_OSCILLATOR.inputs.map((i) => i.key)).toEqual(['upColor', 'downColor']);
    expect(BALANCE_OF_POWER.inputs.map((i) => i.key)).toEqual(['color']);
  });
});
