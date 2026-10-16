/**
 * Parity for the Volatility Squeeze: Bollinger Bands measured against a
 * Keltner Channel on the same basis, and a least-squares momentum reading,
 * against the published formula.
 *
 * The fixture is small enough to carry by hand and the arithmetic is written
 * beside each expectation; nothing is read back out of `calc`. Warmup is
 * pinned for both outputs, since the state needs one window and the momentum
 * a window of windows.
 */
import { describe, it, expect } from 'vitest';
import { VOLATILITY_SQUEEZE } from '../src/indicators/volatility';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorSettings, IndicatorValues } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bar = (i: number, close: number, high: number, low: number): Bar =>
  ({ time: 1735689600 + i * 900, open: close, high, low, close, volume: 1000 });

// length 3.
//   bar  close  high  low   true range
//    0    10     11     9    2 (its own range)
//    1    11     12    10    2
//    2    12     13    11    2
//    3    11   12.5  10.5    2
//    4    13     14    12    3 (14 against the previous close of 11)
//    5    12     13    11    2
//
//   basis = sma(close, 3):           bar 2: 11, bar 3: 34/3, bar 4: 12, bar 5: 12
//   Bollinger half-width 2 * stdev:  bar 2: 2 sqrt(2/3), bar 3: 2 sqrt(2/9), bars 4, 5: 2 sqrt(2/3)
//   Keltner half-width kc * sma(tr): bars 2, 3: 2 kc, bars 4, 5: 7/3 kc
//
//   momentum = linreg over 3 of close - ((highest high + lowest low) / 2 + basis) / 2
//     bar 2: 12 - ((13 + 9) / 2 + 11) / 2        = 1
//     bar 3: 11 - ((13 + 10) / 2 + 34/3) / 2     = -5/12
//     bar 4: 13 - ((14 + 10.5) / 2 + 12) / 2     = 7/8
//     bar 5: 12 - ((14 + 10.5) / 2 + 12) / 2     = -1/8
//   the least-squares line through (0, 1), (1, -5/12), (2, 7/8) ends at 61/144,
//   and through (0, -5/12), (1, 7/8), (2, -1/8) at 37/144.
const bars: Bar[] = [
  bar(0, 10, 11, 9), bar(1, 11, 12, 10), bar(2, 12, 13, 11),
  bar(3, 11, 12.5, 10.5), bar(4, 13, 14, 12), bar(5, 12, 13, 11),
];
const settings = (over: Record<string, unknown> = {}): IndicatorSettings =>
  ({ ...indicatorDefaults(VOLATILITY_SQUEEZE), length: 3, ...over });

/** A seeded random walk, the shape of a traded stock. */
function walk(n: number): Bar[] {
  let s = 11;
  const rnd = (): number => { s = (s * 16807) % 2147483647; return s / 2147483647; };
  const out: Bar[] = [];
  let price = 500;
  for (let i = 0; i < n; i++) {
    const open = price;
    price *= 1 + (rnd() - 0.5) * 0.02;
    out.push(bar(i, price, Math.max(open, price) * (1 + rnd() * 0.004), Math.min(open, price) * (1 - rnd() * 0.004)));
  }
  return out;
}

describe('Volatility Squeeze', () => {
  it('reads the momentum as the end of a least-squares line through the distance from the midline', () => {
    const out = VOLATILITY_SQUEEZE.calc(bars, settings(), {});
    expect(out.momentum.slice(0, 4)).toEqual([null, null, null, null]);
    expect(out.momentum[4]).toBeCloseTo(61 / 144, 12);
    expect(out.momentum[5]).toBeCloseTo(37 / 144, 12);
  });

  it('is on while the Bollinger Bands sit inside the Keltner Channel', () => {
    // kc 1.5: the Keltner half-width is 3 or 3.5, wider than 2 sqrt(2/3) = 1.633
    // on every bar, so the squeeze is on throughout.
    expect(VOLATILITY_SQUEEZE.calc(bars, settings(), {}).state).toEqual([null, null, 1, 1, 1, 1]);
    // kc 0.5: half-widths 1, 1, 7/6, 7/6 against 1.633, 0.943, 1.633, 1.633.
    // Only bar 3's quiet window fits inside.
    const tight = VOLATILITY_SQUEEZE.calc(bars, settings({ kcMult: 0.5 }), {});
    expect(tight.state).toEqual([null, null, 0, 1, 0, 0]);
    // The dots sit on the zero line wherever the state is known.
    expect(tight.squeeze).toEqual([null, null, 0, 0, 0, 0]);
  });

  it('reads flat closes as a squeeze, unless the channel is flat as well', () => {
    // Closes that never move put both bands on the basis. Bars with a range
    // keep the channel open around it, so the bands sit strictly inside it;
    // bars with no range close the channel too, and nothing is inside anything.
    const ranged = [0, 1, 2, 3].map((i) => bar(i, 100, 101, 99));
    expect(VOLATILITY_SQUEEZE.calc(ranged, settings(), {}).state).toEqual([null, null, 1, 1]);
    const flat = [0, 1, 2, 3].map((i) => bar(i, 100, 100, 100));
    expect(VOLATILITY_SQUEEZE.calc(flat, settings(), {}).state).toEqual([null, null, 0, 0]);
  });

  it('colours the dots by the state and the histogram by sign and direction', () => {
    const s = settings({ kcMult: 0.5 });
    const out = VOLATILITY_SQUEEZE.calc(bars, s, {});
    const [momentum, dots] = VOLATILITY_SQUEEZE.plots;
    const dot = (i: number) => dots.colorBy!({ value: 0, index: i, values: out, settings: s });
    expect(dot(2)).toBe(s.offColor);
    expect(dot(3)).toBe(s.onColor);
    const paint = (values: IndicatorValues, i: number) =>
      momentum.colorBy!({ value: values.momentum[i] as number, index: i, values, settings: s });
    // Bar 4 is the first reading, compared with zero: above it and rising.
    expect(paint(out, 4)).toBe(s.upColor);
    // Bar 5 is still above zero but lower than bar 4: weakening.
    expect(paint(out, 5)).toBe(s.upFadeColor);
    // Below zero, falling further is the strong colour and recovering the faded one.
    expect(paint({ momentum: [-1, -2] }, 1)).toBe(s.downColor);
    expect(paint({ momentum: [-2, -1] }, 1)).toBe(s.downFadeColor);
  });

  it('knows its state after one window and its momentum after a window of windows', () => {
    const out = VOLATILITY_SQUEEZE.calc(walk(120), { ...indicatorDefaults(VOLATILITY_SQUEEZE) }, {});
    expect(out.state.findIndex((v) => v !== null)).toBe(19);
    expect(out.squeeze.findIndex((v) => v !== null)).toBe(19);
    expect(out.momentum.findIndex((v) => v !== null)).toBe(38);
  });

  it('agrees with a full calc when a live tick reruns only the last window of windows', () => {
    const data = walk(120);
    const s = { ...indicatorDefaults(VOLATILITY_SQUEEZE) };
    const store = {};
    const held = VOLATILITY_SQUEEZE.calc(data, s, store);
    const next = data.slice();
    next[119] = bar(119, data[119].close * 1.05, data[119].high * 1.06, data[119].low);
    const tail = VOLATILITY_SQUEEZE.calcTail!(next, s, 119, held, store);
    expect(tail).not.toBeNull();
    const full = VOLATILITY_SQUEEZE.calc(next, s, {});
    for (const key of Object.keys(full)) expect([...held[key].slice(0, 119), ...tail![key]]).toEqual(full[key]);
  });
});
