import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import { indicatorDefaults } from '../src/model/indicator-registry';
import { atr, trueRange } from '../src/indicators/atr';
import { supertrend } from '../src/indicators/supertrend';
import { nulls, smaSeededEma } from '../src/indicators/calc';
import { ATR } from '../src/indicators/momentum';
import { KELTNER_CHANNEL } from '../src/indicators/adaptive';
import { CHANDE_KROLL_STOP, CHANDELIER_EXIT } from '../src/indicators/overlay';
import { MEDIAN, TEMA, TWAP } from '../src/indicators/averages';
import { HALFTREND, PARABOLIC_SAR, SUPERTREND, VWAP } from '../src/indicators/trend';
import { VOLATILITY_STOP } from '../src/indicators/signals';
import { ADL, OBV } from '../src/indicators/volume';
import { completeSessions, digest, GOLDEN_CASES } from './helpers/indicator-golden';

// Rows are open, high, low, close, volume; null is a value the feed did not
// send. Prices become NaN, the way a missing observation reaches a calc.
// Volume keeps undefined apart from NaN: undefined is a feed without volume,
// which the volume studies read as nothing traded, while NaN is a bad number.
type Row = readonly [number | null, number | null, number | null, number | null, (number | null | undefined)?];

const barsOf = (rows: readonly Row[], start = 1700000000, step = 60): Bar[] => rows.map((r, i) => ({
  time: start + i * step,
  open: r[0] ?? NaN, high: r[1] ?? NaN, low: r[2] ?? NaN, close: r[3] ?? NaN,
  volume: r[4] === undefined ? undefined : r[4] ?? NaN,
}));

const run = (d: IndicatorDescriptor, bars: readonly Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(bars, { ...indicatorDefaults(d), ...overrides }, {});

const columnsOf = (bars: readonly Bar[]) => ({
  high: bars.map((b) => b.high), low: bars.map((b) => b.low), close: bars.map((b) => b.close),
});

// The atr-hole case of the numerical audit: bar 2 has no high.
const HOLE: readonly Row[] = [
  [9, 10, 8, 9, 1],
  [9, 12, 9, 11, 1],
  [11, null, 10, 11, 1],
  [11, 14, 11, 13, 1],
  [13, 13, 10, 11, 1],
  [11, 12, 10, 12, 1],
];
// True ranges 2, 3, gap, 3, 3, 2 at length 2: seed (2 + 3) / 2, then the gap
// keeps 2.5 and the next bar carries on from it.
const HOLE_ATR = [NaN, 2.5, NaN, 2.75, 2.875, 2.4375];

/** The 2.5.4 ATR, verbatim: the finite reference every complete-data result must equal. */
function finiteReference(high: readonly number[], low: readonly number[], close: readonly number[], period: number): number[] {
  const tr = trueRange(high, low, close);
  const out = new Array<number>(tr.length).fill(NaN);
  if (tr.length < period) return out;
  let sum = 0;
  for (let i = 0; i < period; i++) sum += tr[i];
  let a = sum / period;
  out[period - 1] = a;
  for (let i = period; i < tr.length; i++) {
    a = (a * (period - 1) + tr[i]) / period;
    out[i] = a;
  }
  return out;
}

describe('atr() costs a gap only the bars it covers', () => {
  const cases: readonly { name: string; hlc: readonly (readonly [number | null, number | null, number | null])[]; period: number; expected: readonly number[] }[] = [
    { name: 'a missing high resumes from the held average', period: 2,
      hlc: HOLE.map((r) => [r[1], r[2], r[3]] as const), expected: HOLE_ATR },
    // Bar 1 has no previous close, so its true range is missing too, and the seed
    // is the first two complete true ranges: (3 + 4) / 2 at bar 3.
    { name: 'a leading missing bar seeds from the first complete window', period: 2,
      hlc: [[null, null, null], [10, 8, 9], [12, 9, 11], [11, 7, 8], [13, 9, 12]],
      expected: [NaN, NaN, NaN, 3.5, 4.25] },
    // True ranges 2, gap, 4, 5, 2: the seed waits for 4 and 5.
    { name: 'a hole inside the seed window moves the seed later', period: 2,
      hlc: [[10, 8, 9], [null, 9, 11], [11, 7, 8], [13, 9, 12], [12, 10, 11]],
      expected: [NaN, NaN, NaN, 4.5, 3.25] },
    // Bar 1's own true range needs only bar 0's close. The missing close is felt
    // one bar later, by the true range that reads it.
    { name: 'a missing close costs the next true range', period: 2,
      hlc: [[10, 8, 9], [12, 9, null], [11, 7, 8], [13, 9, 12]],
      expected: [NaN, 2.5, NaN, 3.75] },
    { name: 'a unit period is the true range, gap included', period: 1,
      hlc: [[10, 8, 9], [null, 9, 11], [11, 7, 8]], expected: [2, NaN, 4] },
    // With low and close at zero the true range is the high itself.
    { name: 'an overflowing seed retries on the next window', period: 2,
      hlc: [[1e308, 0, 0], [1e308, 0, 0], [1, 0, 0], [2, 0, 0]],
      expected: [NaN, NaN, 5e307, (5e307 + 2) / 2] },
    { name: 'a running overflow stays unavailable rather than reseeding', period: 2,
      hlc: [[0, 0, 0], [0, 0, 0], [1.7e308, 0, 0], [1.7e308, 0, 0], [0, 0, 0]],
      expected: [NaN, 0, 8.5e307, NaN, NaN] },
  ];

  for (const c of cases) {
    it(c.name, () => {
      const high = c.hlc.map((r) => r[0] ?? NaN);
      const low = c.hlc.map((r) => r[1] ?? NaN);
      const close = c.hlc.map((r) => r[2] ?? NaN);
      expect(atr(high, low, close, c.period)).toEqual(c.expected);
    });
  }

  it('is causal, and a forming bar filled in later recomputes cleanly', () => {
    const { high, low, close } = columnsOf(barsOf(HOLE));
    for (let end = 0; end <= high.length; end++) {
      expect(atr(high.slice(0, end), low.slice(0, end), close.slice(0, end), 2)).toEqual(HOLE_ATR.slice(0, end));
    }
    const forming = atr(high, [...low.slice(0, -1), NaN], close, 2);
    expect(forming).toEqual([...HOLE_ATR.slice(0, -1), NaN]);
    expect(atr(high, low, close, 2)).toEqual(HOLE_ATR);
  });

  it('returns only gaps for a fractional or oversized period and still rejects a non-positive one', () => {
    const { high, low, close } = columnsOf(barsOf(HOLE));
    expect(atr(high, low, close, 2.5)).toEqual(new Array(6).fill(NaN));
    expect(atr(high, low, close, 7)).toEqual(new Array(6).fill(NaN));
    expect(atr([], [], [], 14)).toEqual([]);
    expect(() => atr(high, low, close, 0)).toThrow('ATR period must be > 0');
  });

  it('keeps complete-data results bit for bit, which is the OpenAlgo atr parity', () => {
    const bars = completeSessions();
    const { high, low, close } = columnsOf(bars);
    for (const period of [1, 2, 3, 14, 50, 500]) {
      expect(atr(high, low, close, period)).toEqual(finiteReference(high, low, close, period));
    }
  });
});

describe('studies built on the ATR resume after a gap', () => {
  const bars = barsOf(HOLE);

  it('ATR', () => {
    expect(run(ATR, bars, { period: 2 }).atr).toEqual(nulls(HOLE_ATR));
  });

  it('Keltner Channels match the numerical audit reading', () => {
    const out = run(KELTNER_CHANNEL, bars, { length: 2, mult: 2, atrlength: 2 });
    expect(out.upper).toEqual([null, 15, null, 17.72222222222222, 17.15740740740741, 16.67746913580247]);
    expect(out.lower).toEqual(out.basis.map((b, i) => Number.isFinite(HOLE_ATR[i]) ? (b as number) - HOLE_ATR[i] * 2 : null));
  });

  it('supertrend() and the Supertrend study', () => {
    const points = supertrend(bars, 2, 1);
    expect(points.map((p) => p.value)).toEqual([NaN, 13, NaN, 13, 13, 13]);
    expect(points.map((p) => p.direction)).toEqual([1, 1, 1, 1, 1, 1]);
    const out = run(SUPERTREND, bars, { period: 2, multiplier: 1 });
    expect(out.down).toEqual([null, 13, null, 13, 13, 13]);
    expect(out.up).toEqual(new Array(6).fill(null));
    expect(out.bodyMid).toEqual([null, 10, null, 12, 12, 11.5]);
  });

  it('Supertrend leaves a missing close absent after the ATR has seeded, with no flip', () => {
    // A steady fall with a two-point range: every true range is 2, so the ATR is 2
    // wherever it exists and the upper band is close + 6 all the way down. Bar 12
    // has no close. Its own true range reads bar 11's close, so its ATR is finite;
    // bar 13's reads the missing close and is absent. Deciding bar 12 on a NaN
    // comparison flipped the trend there and dragged the bands along for 21 bars.
    const falling = (i: number): Bar => {
      const c = 200 - 0.25 * i;
      return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 1 };
    };
    const complete = Array.from({ length: 40 }, (_, i) => falling(i));
    const holed = complete.map((b, i) => (i === 12 ? { ...b, close: NaN } : b));
    const { high, low, close } = columnsOf(holed);
    expect(atr(high, low, close, 10).slice(9, 15)).toEqual([2, 2, 2, 2, NaN, 2]);

    const expected = supertrend(complete);
    const points = supertrend(holed);
    expect(points.map((p) => p.direction)).toEqual(new Array(40).fill(1));
    expect(points.map((p) => p.value)).toEqual(expected.map((p, i) => (i === 12 || i === 13 ? NaN : p.value)));

    const full = run(SUPERTREND, complete);
    const out = run(SUPERTREND, holed);
    expect(out.up).toEqual(new Array(40).fill(null));
    expect(out.down).toEqual(full.down.map((v, i) => (i === 12 || i === 13 ? null : v)));
  });

  it('Supertrend carries its bands from the last accepted close, not a skipped one', () => {
    // Bar 6 has no high, so it has no true range and is skipped, but it still
    // carries a close of 110, above the upper band of 100.75 that bar 5 left. The
    // band step on bar 7 must compare with bar 5's close, 98.75, and keep the band
    // at 100.75. Reading bar 6's close reset it to the raw 98.25 + 67 / 12.
    const rows: Row[] = Array.from({ length: 10 }, (_, i) => {
      const c = 100 - 0.25 * i;
      return i === 6 ? [c, null, c - 1, 110, 1] : [c, c + 1, c - 1, c, 1];
    });
    const points = supertrend(barsOf(rows), 3, 1);
    expect(points.map((p) => p.value)).toEqual([NaN, NaN, 101.5, 101.25, 101, 100.75, NaN, 100.75, 100.75, 100.75]);
    expect(points.map((p) => p.direction)).toEqual(new Array(10).fill(1));
    expect(run(SUPERTREND, barsOf(rows), { period: 3, multiplier: 1 }).down)
      .toEqual([null, null, 101.5, 101.25, 101, 100.75, null, 100.75, 100.75, 100.75]);
  });

  it('Chandelier Exit', () => {
    // Window extremes 12, 12, 14, 14, 13 (highs) and 8, 9, 10, 10, 10 (lows),
    // three ATRs away.
    const out = run(CHANDELIER_EXIT, bars, { length: 2, atrLength: 2, atrMultiplier: 3 });
    expect(out.longExit).toEqual([null, 4.5, null, 5.75, 5.375, 5.6875]);
    expect(out.shortExit).toEqual([null, 15.5, null, 18.25, 18.625, 17.3125]);
  });

  it('Chande Kroll Stop', () => {
    // First stops 9.5, gap, 11.25, 11.125, 10.5625 (high) and 10.5, gap, 12.75,
    // 12.875, 12.4375 (low); the second pass needs two live first stops.
    const out = run(CHANDE_KROLL_STOP, bars, { p: 2, x: 1, q: 2 });
    expect(out.stopShort).toEqual([null, null, null, null, 11.25, 11.125]);
    expect(out.stopLong).toEqual([null, null, null, null, 12.75, 12.4375]);
  });

  it('Median bands', () => {
    // A one-bar median is hl2 itself: 9, 10.5, gap, 12.5, 11.5, 11.
    const out = run(MEDIAN, bars, { length: 1, atrLength: 2, atrMult: 2 });
    expect(out.upper).toEqual([null, 15.5, null, 18, 17.25, 15.875]);
    expect(out.lower).toEqual([null, 5.5, null, 7, 5.75, 6.125]);
  });

  it('HalfTrend channel', () => {
    const out = run(HALFTREND, bars, { amplitude: 1, channelDeviation: 2, atrPeriod: 2 });
    for (let i = 0; i < bars.length; i++) {
      const level = out.up[i] ?? out.down[i];
      const channel = level !== null && Number.isFinite(HOLE_ATR[i]) ? level + 2 * (HOLE_ATR[i] / 2) : null;
      expect(out.atrHigh[i]).toBe(channel);
    }
    expect(out.atrHigh.slice(3).every((v) => v !== null)).toBe(true);
    expect(out.atrLow.slice(3).every((v) => v !== null)).toBe(true);
  });

  it('Volatility Stop scales the ATR again after a gap instead of falling back to the true range', () => {
    // Closes rise 2 a bar with a 2-point range, so every true range after bar 0
    // is 3. Bar 2 has no high, so its true range and ATR are missing, and the
    // reference definition restarts the stop at the close there. From bar 3 the
    // ATR resumes at 2.75, 2.875, ... and the band is twice that. The 2.5.4 study
    // fell back to the bare true range of 3 for good, which pulled the stop up
    // to 105, 107, 109 and 111.
    const rising = barsOf(Array.from({ length: 8 }, (_, i) => {
      const c = 100 + 2 * i;
      return [c, i === 2 ? null : c + 1, c - 1, c, 1] as const;
    }));
    const out = run(VOLATILITY_STOP, rising, { length: 2, factor: 2, source: 'close' });
    expect(out.up).toEqual([100, 100, 104, 104, 104, 104.125, 106.0625, 108.03125]);
    expect(out.down).toEqual(new Array(8).fill(null));
  });
});

describe('VWAP skips a bar with a missing price or an unusable volume', () => {
  const settings = { anchor: 'continuous', timezone: 'UTC' };

  it('a NaN volume leaves that bar absent and the totals untouched', () => {
    const out = run(VWAP, barsOf([[10, 11, 9, 10, 100], [10, 12, 10, 11, null], [11, 13, 11, 12, 100], [12, 13, 11, 12, 200]]), settings);
    expect(out.vwap).toEqual([10, null, 11, 11.5]);
    // Volume-weighted variance 0, then 122 - 121, then 133 - 132.25.
    expect(out.upper1).toEqual([10, null, 12, 11.5 + Math.sqrt(0.75)]);
    expect(out.lower1).toEqual([10, null, 10, 11.5 - Math.sqrt(0.75)]);
  });

  it('a missing price is skipped, whatever volume it carries', () => {
    for (const volume of [100, 0]) {
      const out = run(VWAP, barsOf([[10, 11, 9, 10, 100], [null, null, null, null, volume], [11, 13, 11, 12, 100], [12, 13, 11, 12, 200]]), settings);
      expect(out.vwap, `volume ${volume}`).toEqual([10, null, 11, 11.5]);
    }
  });

  it('an infinite volume is skipped', () => {
    for (const volume of [Infinity, -Infinity]) {
      const out = run(VWAP, barsOf([[10, 11, 9, 10, 100], [10, 12, 10, 11, volume], [11, 13, 11, 12, 100]]), settings);
      expect(out.vwap).toEqual([10, null, 11]);
    }
  });

  it('keeps reading an undefined volume as a bar that traded nothing', () => {
    const out = run(VWAP, barsOf([[10, 11, 9, 10, 100], [10, 12, 10, 11, undefined], [11, 13, 11, 12, 100]]), settings);
    expect(out.vwap).toEqual([10, 10, 11]);
  });

  it('still restarts on a session whose first bar is missing', () => {
    // Two sessions a day apart. The second opens on a missing bar; the restart
    // belongs to the session, so its next bar starts from its own price alone.
    const day = barsOf([[10, 11, 9, 10, 100], [20, 21, 19, 20, 100]], 1704081600);
    const next = barsOf([[null, null, null, null, 100], [30, 31, 29, 30, 100], [40, 41, 39, 40, 100]], 1704081600 + 86400);
    const out = run(VWAP, [...day, ...next]);
    expect(out.vwap).toEqual([10, 15, null, 30, 35]);
  });
});

describe('TWAP counts only the bars it has a price for', () => {
  it('a missing price costs only its own bar', () => {
    const out = run(TWAP, barsOf([[10, 10, 10, 10, 1], [null, null, null, null, 1], [12, 12, 12, 12, 1], [14, 14, 14, 14, 1]]), {
      anchor: 'continuous', timezone: 'UTC',
    });
    expect(out.twap).toEqual([10, null, 11, 12]);
  });

  it('an infinite price is skipped the same way', () => {
    const out = run(TWAP, barsOf([[10, 10, 10, 10], [10, Infinity, 10, 10], [12, 12, 12, 12]]), { anchor: 'continuous', source: 'hl2' });
    expect(out.twap).toEqual([10, null, 11]);
  });

  it('still restarts on a session whose first bar is missing', () => {
    const day = barsOf([[10, 10, 10, 10], [20, 20, 20, 20]], 1704081600);
    const next = barsOf([[null, null, null, null], [30, 30, 30, 30], [40, 40, 40, 40]], 1704081600 + 86400);
    expect(run(TWAP, [...day, ...next]).twap).toEqual([10, 15, null, 30, 35]);
  });
});

describe('OBV and A/D keep their totals through a bar they cannot use', () => {
  it('OBV keeps its running total through a NaN volume', () => {
    const out = run(OBV, barsOf([[10, 10, 10, 10, 100], [11, 11, 11, 11, null], [12, 12, 12, 12, 100], [11, 11, 11, 11, 100]]));
    expect(out.obv).toEqual([0, 0, 100, 0]);
  });

  it('OBV weights its VWMA smoothing with the same normalised volume', () => {
    // OBV 0, 0, 100, 0, 100 with volumes 100, 0, 100, 100, 100 over two bars:
    // 0 / 100, 10000 / 100, 10000 / 200, 10000 / 200.
    const out = run(OBV, barsOf([[10, 10, 10, 10, 100], [11, 11, 11, 11, null], [12, 12, 12, 12, 100], [11, 11, 11, 11, 100], [12, 12, 12, 12, 100]]), {
      maType: 'VWMA', maLength: 2,
    });
    expect(out.obv).toEqual([0, 0, 100, 0, 100]);
    expect(out.ma).toEqual([null, 0, 100, 50, 50]);
  });

  it('A/D keeps its running total through a NaN or infinite volume', () => {
    // Close location value (3 - 1) / 4 = 0.5 on every bar.
    for (const volume of [null, Infinity]) {
      const out = run(ADL, barsOf([[10, 12, 8, 11, 100], [11, 13, 9, 12, volume], [12, 14, 10, 13, 100]]));
      expect(out.adl, String(volume)).toEqual([50, 50, 100]);
    }
  });

  it('A/D leaves a bar with a range but no close absent and keeps its total', () => {
    // The finite range made the old span test pass, the missing close made the
    // term NaN, and the NaN total blanked every later bar.
    const out = run(ADL, barsOf([[10, 12, 8, 11, 100], [11, 13, 9, null, 100], [12, 14, 10, 13, 100], [12, 14, 10, 13, 100]]));
    expect(out.adl).toEqual([50, null, 100, 150]);
  });

  it('A/D treats a missing high or low and an overflowing span or term as no term', () => {
    const rows: Row[] = [
      [10, 12, 8, 11, 100],
      // A missing high or low is not a doji, so it no longer prints the total.
      [11, null, 9, 12, 100],
      [11, 13, null, 12, 100],
      // The span overflows, which would divide the position down to an exact 0.
      [0, 1e308, -1e308, 0, 100],
      // A close far above the high: (20 - 8) - (12 - 20) = 20 over a span of 4 is
      // 5, and 5 times 1e308 overflows.
      [11, 12, 8, 20, 1e308],
      [12, 14, 10, 13, 100],
      // A doji still contributes nothing and prints the carried total.
      [12, 12, 12, 12, 100],
    ];
    expect(run(ADL, barsOf(rows)).adl).toEqual([50, null, null, null, null, 100, 100]);
  });
});

describe('Parabolic SAR steps over incomplete bars', () => {
  it('holds its state across a missing low', () => {
    // Seed long at bar 0's low, 9, with extreme 12. Bar 2 is skipped. Bar 3 steps
    // to 9.06 and is clamped by the two complete bars before it (lows 10 and 9);
    // bars 4 and 5 walk on with the acceleration raised by each new high.
    const out = run(PARABOLIC_SAR, barsOf([[10, 11, 9, 10], [10, 12, 10, 11], [11, 13, null, 12], [12, 14, 12, 13], [13, 15, 13, 14], [14, 16, 14, 15]]));
    const af4 = Math.min(0.2, 0.02 + 0.02);
    const sar4 = 9 + af4 * (14 - 9);
    const af5 = Math.min(0.2, af4 + 0.02);
    const sar5 = sar4 + af5 * (15 - sar4);
    expect(out.sar).toEqual([null, 9, null, 9, sar4, sar5]);
  });

  it('seeds from the first complete pair after a leading gap', () => {
    const rows: Row[] = [[10, 11, 9, 10], [10, 12, 10, 11], [11, 13, 10.5, 12], [12, 14, 12, 13], [11, 12, 10, 10.5]];
    const gapped = run(PARABOLIC_SAR, barsOf([[null, null, null, null], ...rows])).sar;
    expect(gapped).toEqual([null, ...run(PARABOLIC_SAR, barsOf(rows)).sar]);
    expect(gapped[2]).toBe(9);
  });

  it('reads an incomplete bar exactly as if it were not there', () => {
    const complete = completeSessions().slice(0, 400);
    const field = ['high', 'low', 'close'] as const;
    const holed = complete.map((b, i) => (i % 7 === 3 ? { ...b, [field[i % 3]]: NaN } : b));
    const kept = complete.filter((_, i) => i % 7 !== 3);
    for (const settings of [{}, { start: 0.01, increment: 0.03, maximum: 0.3 }]) {
      const out = run(PARABOLIC_SAR, holed, settings).sar;
      const expected = run(PARABOLIC_SAR, kept, settings).sar;
      let k = 0;
      for (let i = 0; i < holed.length; i++) {
        if (i % 7 === 3) expect(out[i]).toBeNull();
        else expect(out[i]).toBe(expected[k++]);
      }
    }
  });
});

describe('TEMA adds its three terms left to right', () => {
  /** Chained EMA started at the first finite value of its input, as the study chains them. */
  const chained = (values: readonly number[], period: number): number[] => {
    const start = values.findIndex((v) => Number.isFinite(v));
    const out = new Array<number>(values.length).fill(NaN);
    if (start < 0) return out;
    smaSeededEma(values.slice(start), period).forEach((v, i) => { out[start + i] = v; });
    return out;
  };

  it('matches the numerical audit reading', () => {
    const out = run(TEMA, barsOf([[14, 15, 13, 14], [12, 13, 11, 12], [14, 15, 13, 14], [17, 18, 16, 17]]), { length: 2 });
    expect(out.tema).toEqual([null, null, null, 16.740740740740748]);
  });

  it('is absent when a term is absent or the sum is not finite', () => {
    // At length 1 every term is the close. 3 * 1e308 overflows, so the first
    // difference is Infinity minus Infinity and the bar has no reading.
    expect(run(TEMA, barsOf([[1, 1, 1, 1], [1e308, 1e308, 1e308, 1e308], [2, 2, 2, 2]]), { length: 1 }).tema)
      .toEqual([1, null, 2]);
    expect(run(TEMA, barsOf([[1, 1, 1, 1], [null, null, null, null], [2, 2, 2, 2]]), { length: 1 }).tema)
      .toEqual([1, null, 2]);
  });

  it('changes complete-data readings only in their last digits', () => {
    const closes = completeSessions().map((b) => b.close);
    for (const length of [2, 9, 21]) {
      const e1 = smaSeededEma(closes, length);
      const e2 = chained(e1, length);
      const e3 = chained(e2, length);
      const out = run(TEMA, completeSessions(), { length }).tema;
      expect(out).toEqual(nulls(e1.map((v, i) => 3 * v - 3 * e2[i] + e3[i])));
      e1.forEach((v, i) => {
        const before = 3 * (v - e2[i]) + e3[i];
        if (Number.isFinite(before)) expect(Math.abs((out[i] as number) - before)).toBeLessThanOrEqual(Math.abs(before) * 1e-14);
        else expect(out[i]).toBeNull();
      });
    }
  });
});

describe('complete data keeps every affected study bit for bit', () => {
  // Recorded from 2.5.4 (1bce964) before the gap corrections, on the same
  // generated sessions. A single last-bit change anywhere changes the digest.
  const GOLDEN: Readonly<Record<string, string>> = {
    'atr()': 'bef1a5b7e5caa230',
    'supertrend()': '5e7ce9250e83d58e',
    'ATR': '732445884bd5df43',
    'ATR period 1': 'c905c462bf4b9fac',
    'ATR period 5': '1ae65ff2af17d50a',
    'Keltner': 'bba41fa1862ef398',
    'Keltner ATR 3': '23a8aac456b40f13',
    'Chande Kroll Stop': '0f462197d06b1493',
    'Chandelier Exit': '5d2d4352e160e5e8',
    'Median': '5c0230221436510e',
    'HalfTrend': '5f7e92ddb47502b1',
    'HalfTrend ATR 10': 'ffa77ff9a67a8598',
    'Volatility Stop': '02d15ba2aa874980',
    'Supertrend': '023efa7f49441b55',
    'VWAP session': '607e59974f1e68a1',
    'VWAP week': 'f8464639bea9d57f',
    'VWAP continuous percent': '4b5551dcac039e4e',
    'VWAP New York': '69964e33c927aea3',
    'Parabolic SAR': 'e4d3bfad786941d7',
    'Parabolic SAR fast': '6b7a2f58b81f8c12',
    'OBV': '5a744e3779881cb0',
    'OBV Bollinger': 'e86626b126e31c49',
    'OBV VWMA': '6a0da443f97f5561',
    'OBV EMA': 'c5801bef17ab44bd',
    'ADL': '8656de2ec4e0dfab',
    'TWAP session': '5399e832cc38ae7c',
    'TWAP continuous': '4578e1caf2b63dd1',
  };
  const bars = completeSessions();

  it('covers every recorded case', () => {
    expect(GOLDEN_CASES.map(([name]) => name).sort()).toEqual(Object.keys(GOLDEN).sort());
  });

  for (const [name, compute] of GOLDEN_CASES) {
    it(name, async () => {
      expect(await digest(compute(bars))).toBe(GOLDEN[name]);
    });
  }
});
