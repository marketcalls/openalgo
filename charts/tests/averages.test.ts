import { describe, it, expect } from 'vitest';
import {
  AVERAGE_INDICATORS,
  MA_CROSS, MCGINLEY_DYNAMIC, MEDIAN, MA_RIBBON, TEMA, TWAP, VWMA, ALLIGATOR,
} from '../src/indicators/averages';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import { sma, wma, rma } from '../src/indicators/calc';
import type { Bar } from '../src/model/bar';

/**
 * `high = close + 1` and `low = close - 1` makes `hl2` equal `close`, and with
 * `open = close` so does `ohlc4`, so every hand-computed expectation below can
 * be written against the close list whatever source the study defaults to.
 */
const bars = (
  n: number,
  f: (i: number) => number,
  v: (i: number) => number = (i) => 100 + i,
): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: v(i) };
  });

const wave = (n = 240): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);
const ramp = (n = 40): Bar[] => bars(n, (i) => i);

/** Closes chosen so every rolling window has a distinct extreme. */
const jagged = (): Bar[] => bars(4, (i) => [10, 14, 12, 13][i]);

/**
 * Hourly bars straddling 18:30 UTC, which is midnight IST: the boundary
 * `isNewIstDay` splits on, and therefore where a session anchor resets.
 */
const acrossIstMidnight = (): Bar[] => {
  const start = Date.UTC(2024, 0, 2, 16, 30) / 1000;
  const closes = [10, 20, 30, 40];
  return closes.map((c, i) => ({
    time: start + i * 3600, open: c, high: c + 1, low: c - 1, close: c, volume: 100,
  }));
};

/** Index of the first plotted bar: the number every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const run = (d: IndicatorDescriptor, data: Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...overrides }, {});

describe('the reference platform averages: descriptor contract', () => {
  const data = wave();

  it('exports the ten averages with unique ids, all on the price pane', () => {
    expect(AVERAGE_INDICATORS).toHaveLength(10);
    const ids = AVERAGE_INDICATORS.map((d) => d.id);
    expect(ids).toEqual([
      'ma-cross', 'mcginley-dynamic', 'median', 'ma-ribbon', 'tema', 'twap', 'vwma', 'alligator',
      'smma', 't3',
    ]);
    expect(new Set(ids).size).toBe(ids.length);
    for (const d of AVERAGE_INDICATORS) expect(d.placement).toBe('onchart');
  });

  it('every plot names a declared colour input', () => {
    for (const d of AVERAGE_INDICATORS) {
      for (const plot of d.plots) {
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.key} colorKey`).toBe('color');
      }
    }
  });

  it('every fill joins two plots the descriptor actually declares', () => {
    for (const d of AVERAGE_INDICATORS) {
      const keys = d.plots.map((p) => p.key);
      for (const fill of d.fills ?? []) {
        for (const key of fill.between) expect(keys, `${d.id} fill`).toContain(key);
      }
    }
  });

  it('declares unique input keys per descriptor', () => {
    for (const d of AVERAGE_INDICATORS) {
      const keys = d.inputs.map((i) => i.key);
      expect(new Set(keys).size, `${d.id} inputs`).toBe(keys.length);
    }
  });

  it('returns one full-length column per plot, of finite numbers or null only', () => {
    for (const d of AVERAGE_INDICATORS) {
      const values = run(d, data);
      for (const plot of d.plots) {
        const col = values[plot.key];
        expect(col, `${d.id}.${plot.key} missing`).toBeDefined();
        expect(col.length, `${d.id}.${plot.key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of AVERAGE_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });

  it('survives a feed that reports no volume', () => {
    const flat = bars(60, (i) => 100 + i, () => 0);
    for (const d of AVERAGE_INDICATORS) {
      const values = run(d, flat);
      for (const plot of d.plots) {
        for (const v of values[plot.key]) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });
});

describe('MA Cross', () => {
  // sma(2) = [na, 10, 10, 15, 15, 10] and sma(3) = [na, na, 10, 40/3, 40/3, 40/3]
  // over closes 10, 10, 10, 20, 10, 10: a crossover at bar 3 and a crossunder at
  // bar 5, and nothing in between even though the fast average stayed above.
  const stepped = () => bars(6, (i) => [10, 10, 10, 20, 10, 10][i]);

  it('marks only the bars where the averages actually crossed', () => {
    const out = run(MA_CROSS, stepped(), { shortLength: 2, longLength: 3 });
    expect(out.cross).toEqual([null, null, null, 15, null, 10]);
  });

  it('plots the two averages as plain SMAs of close', () => {
    const data = wave();
    const closes = data.map((b) => b.close);
    const i = data.length - 1;
    const out = run(MA_CROSS, data);
    expect(out.short[i] as number).toBeCloseTo(sma(closes, 9)[i], 10);
    expect(out.long[i] as number).toBeCloseTo(sma(closes, 26)[i], 10);
  });

  it('first prints each average at its own length - 1', () => {
    const out = run(MA_CROSS, wave());
    expect(firstLive(out.short)).toBe(8);
    expect(firstLive(out.long)).toBe(25);
    // Nothing can cross before the slower average exists, and the comparison
    // needs a previous bar for both, so the earliest possible cross is bar 26.
    expect(firstLive(out.cross)).toBeGreaterThanOrEqual(26);
  });
});

describe('McGinley Dynamic', () => {
  it('applies the fourth-power step by hand', () => {
    // length 1 seeds on close[0], then mg = mg[1] + (src - mg[1]) / (1 * (src / mg[1])^4).
    // With 10 then 20 the ratio is 2, so the divisor is 16 and the line advances
    // 10 / 16: a fraction of the move, which is the whole point of the kernel.
    const out = run(MCGINLEY_DYNAMIC, bars(2, (i) => [10, 20][i]), { length: 1 });
    expect(out.mg[0] as number).toBeCloseTo(10, 10);
    expect(out.mg[1] as number).toBeCloseTo(10.625, 10);
  });

  it('sits still on a constant series', () => {
    // src == mg[1] makes the numerator zero whatever the divisor is, so the
    // recursion is a fixed point and any seeding error would show as drift.
    const out = run(MCGINLEY_DYNAMIC, bars(40, () => 100));
    expect(out.mg[13] as number).toBeCloseTo(100, 10);
    expect(out.mg[39] as number).toBeCloseTo(100, 10);
  });

  it('first prints at length - 1, where its EMA seed does', () => {
    expect(firstLive(run(MCGINLEY_DYNAMIC, wave()).mg)).toBe(13);
    expect(firstLive(run(MCGINLEY_DYNAMIC, wave(), { length: 5 }).mg)).toBe(4);
    expect(firstLive(run(MCGINLEY_DYNAMIC, wave(), { length: 1 }).mg)).toBe(0);
  });
});

describe('Median', () => {
  it('is the middle of the window, banded by ATR multiples', () => {
    // hl2 equals close here, so the windows are 10/14/12 then 14/12/13, whose
    // nearest-rank 50th percentiles are 12 and 13. ATR(2) over true ranges
    // 2, 5, 3, 2 is 3.5, 3.25, 2.625 from bar 1.
    const out = run(MEDIAN, jagged(), { length: 3, atrLength: 2, atrMult: 1 });
    expect(out.median[2] as number).toBeCloseTo(12, 10);
    expect(out.median[3] as number).toBeCloseTo(13, 10);
    expect(out.upper[2] as number).toBeCloseTo(15.25, 10);
    expect(out.lower[2] as number).toBeCloseTo(8.75, 10);
    expect(out.upper[3] as number).toBeCloseTo(15.625, 10);
    expect(out.lower[3] as number).toBeCloseTo(10.375, 10);
  });

  it('returns the constant itself on a constant series', () => {
    const out = run(MEDIAN, bars(30, () => 42));
    expect(out.median[29] as number).toBe(42);
    expect(out.medianEma[29] as number).toBeCloseTo(42, 10);
  });

  it('takes the upper of the two middles on an even window', () => {
    // Nearest rank, not interpolation: ceil(0.5 * 4) = 2 of the sorted window
    // 10/12/13/14 is 12, where a mean would have said 12.5.
    const out = run(MEDIAN, jagged(), { length: 4, atrLength: 2 });
    expect(out.median[3] as number).toBe(12);
  });

  it('starts the median at length - 1, the bands at the ATR, the EMA at 2 * length - 2', () => {
    const out = run(MEDIAN, wave());
    expect(firstLive(out.median)).toBe(2);
    expect(firstLive(out.upper)).toBe(13);
    expect(firstLive(out.lower)).toBe(13);
    expect(firstLive(out.medianEma)).toBe(4);
    const slower = run(MEDIAN, wave(), { length: 5, atrLength: 3 });
    expect(firstLive(slower.median)).toBe(4);
    expect(firstLive(slower.upper)).toBe(4);
    expect(firstLive(slower.medianEma)).toBe(8);
  });

  it('emits no EMA at all when the median cannot fill one window', () => {
    const out = run(MEDIAN, jagged(), { length: 3, atrLength: 2 });
    expect(out.medianEma.every((v) => v === null)).toBe(true);
  });
});

describe('Moving Average Ribbon', () => {
  it('computes each lane with its own kernel, source and length', () => {
    const data = wave();
    const i = data.length - 1;
    const closes = data.map((b) => b.close);
    const highs = data.map((b) => b.high);
    const out = run(MA_RIBBON, data, {
      ma1Type: 'WMA', ma1Length: 10,
      ma2Type: 'SMMA (RMA)', ma2Length: 15,
      ma3Type: 'SMA', ma3Source: 'high', ma3Length: 8,
    });
    expect(out.ma1[i] as number).toBeCloseTo(wma(closes, 10)[i], 10);
    expect(out.ma2[i] as number).toBeCloseTo(rma(closes, 15)[i], 10);
    expect(out.ma3[i] as number).toBeCloseTo(sma(highs, 8)[i], 10);
  });

  it('reduces its VWMA lane to an SMA when volume is flat', () => {
    const data = bars(60, (i) => 100 + Math.sin(i) * 5, () => 250);
    const closes = data.map((b) => b.close);
    const out = run(MA_RIBBON, data, { ma1Type: 'VWMA', ma1Length: 20 });
    const expected = sma(closes, 20);
    for (let i = 19; i < data.length; i++) {
      expect(out.ma1[i] as number).toBeCloseTo(expected[i], 10);
    }
  });

  it('returns an all-null column for a hidden lane', () => {
    const data = wave();
    const out = run(MA_RIBBON, data, { showMa2: false });
    expect(out.ma2).toHaveLength(data.length);
    expect(out.ma2.every((v) => v === null)).toBe(true);
    expect(firstLive(out.ma1)).toBe(19);
  });

  it('first prints each lane at its own length - 1', () => {
    const out = run(MA_RIBBON, wave());
    expect(firstLive(out.ma1)).toBe(19);
    expect(firstLive(out.ma2)).toBe(49);
    expect(firstLive(out.ma3)).toBe(99);
    expect(firstLive(out.ma4)).toBe(199);
  });
});

describe('TEMA', () => {
  // Triple smoothing cancels the lag of a straight line exactly, so on a unit
  // ramp the published value is the close itself. Any error in how the three
  // chained EMAs are seeded shows up here immediately as a constant offset.
  it('sits on the series itself for a linear ramp', () => {
    const short = run(TEMA, ramp(12), { length: 2 });
    expect(short.tema.slice(3)).toEqual([3, 4, 5, 6, 7, 8, 9, 10, 11]);
    const wide = run(TEMA, ramp(40));
    for (let i = 24; i < 40; i++) expect(wide.tema[i] as number).toBeCloseTo(i, 8);
  });

  it('first prints at 3 * length - 3, not length - 1', () => {
    expect(firstLive(run(TEMA, ramp(12), { length: 2 }).tema)).toBe(3);
    expect(firstLive(run(TEMA, wave()).tema)).toBe(24);
    expect(firstLive(run(TEMA, wave(), { length: 21 }).tema)).toBe(60);
  });

  it('reproduces a flat series exactly', () => {
    const out = run(TEMA, bars(40, () => 100));
    expect(out.tema[39] as number).toBeCloseTo(100, 10);
  });
});

describe('TWAP', () => {
  it('is the running mean of the source since the anchor', () => {
    // ohlc4 equals close here. Bars 0 and 1 are 22:00 and 23:00 IST, bars 2 and
    // 3 are 00:00 and 01:00 of the next IST day, so the mean restarts at bar 2.
    const out = run(TWAP, acrossIstMidnight());
    expect(out.twap).toEqual([10, 15, 30, 35]);
  });

  it('never resets on the continuous anchor', () => {
    const out = run(TWAP, acrossIstMidnight(), { anchor: 'continuous' });
    expect(out.twap).toEqual([10, 15, 20, 25]);
  });

  it('prints from bar 0, since one bar is already an average', () => {
    expect(firstLive(run(TWAP, wave()).twap)).toBe(0);
  });

  it('displaces the plot by the offset setting', () => {
    const out = run(TWAP, acrossIstMidnight(), { offset: 2 });
    expect(out.twap).toEqual([null, null, 10, 15]);
    expect(firstLive(out.twap)).toBe(2);
  });
});

describe('VWMA', () => {
  it('collapses onto the SMA when volume is constant', () => {
    const data = bars(50, (i) => 100 + Math.sin(i / 3) * 4, () => 1000);
    const expected = sma(data.map((b) => b.close), 20);
    const out = run(VWMA, data);
    for (let i = 19; i < data.length; i++) expect(out.vwma[i] as number).toBeCloseTo(expected[i], 10);
  });

  it('leans on the heavy bars', () => {
    // Volumes 1, 1, 8 over closes 10, 10, 20: (10 + 10 + 160) / 10 = 18, well
    // above the 13.33 an unweighted mean would give.
    const data = bars(3, (i) => [10, 10, 20][i], (i) => [1, 1, 8][i]);
    const out = run(VWMA, data, { length: 3 });
    expect(out.vwma[2] as number).toBeCloseTo(18, 10);
  });

  it('goes blank rather than dividing by zero volume', () => {
    const out = run(VWMA, bars(40, (i) => 100 + i, () => 0), { length: 5 });
    expect(out.vwma.every((v) => v === null)).toBe(true);
  });

  it('first prints at length - 1, shifted by the offset', () => {
    expect(firstLive(run(VWMA, wave()).vwma)).toBe(19);
    expect(firstLive(run(VWMA, wave(), { length: 5 }).vwma)).toBe(4);
    expect(firstLive(run(VWMA, wave(), { length: 5, offset: 3 }).vwma)).toBe(7);
  });
});

describe('Williams Alligator', () => {
  it('smooths hl2 with Wilder RMA', () => {
    // hl2 equals close here. rma(2) over 10, 14, 12, 13 seeds at 12 on bar 1,
    // then (12 + 12) / 2 = 12 and (12 + 13) / 2 = 12.5.
    const out = run(ALLIGATOR, jagged(), {
      jawLength: 2, jawOffset: 0, teethLength: 2, teethOffset: 0, lipsLength: 2, lipsOffset: 0,
    });
    expect(out.jaw).toEqual([null, 12, 12, 12.5]);
    expect(out.jaw).toEqual(out.lips);
  });

  it('leaves exactly `offset` leading nulls and draws the value that many bars later', () => {
    // rma of length 1 is the source itself, so the only thing left in the column
    // is the displacement: the cleanest possible read on the shift.
    const out = run(ALLIGATOR, jagged(), { jawLength: 1, jawOffset: 2 });
    expect(out.jaw).toEqual([null, null, 10, 14]);
  });

  it('first prints each line at length - 1 + offset', () => {
    const out = run(ALLIGATOR, wave());
    expect(firstLive(out.jaw)).toBe(28);   // 21 - 1 + 8
    expect(firstLive(out.teeth)).toBe(17); // 13 - 1 + 5
    expect(firstLive(out.lips)).toBe(10);  //  8 - 1 + 3
  });

  it('matches the RMA composition the reference writes, bar for bar', () => {
    const data = wave();
    const hl2 = data.map((b) => (b.high + b.low) / 2);
    const out = run(ALLIGATOR, data);
    const expected = rma(hl2, 21);
    const i = data.length - 1;
    // The last slot of the jaw holds the value from 8 bars back.
    expect(out.jaw[i] as number).toBeCloseTo(expected[i - 8], 10);
  });
});
