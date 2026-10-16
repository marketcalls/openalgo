import { describe, it, expect } from 'vitest';
import {
  ADAPTIVE_INDICATORS,
  KAMA, KELTNER_CHANNEL, LSMA, KLINGER_OSCILLATOR, KNOW_SURE_THING, LINREG_SLOPE,
} from '../src/indicators/adaptive';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 120): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

/** A steeper wave: bar-to-bar moves exceed the 2-point bar range, so gaps matter. */
const gappy = (n = 60): Bar[] => bars(n, (i) => 100 + Math.sin(i / 3) * 10);

/** Index of the first plotted bar: the number every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const run = (d: IndicatorDescriptor, data: Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...overrides }, {});

describe('the reference platform extras: descriptor contract', () => {
  const data = wave();

  it('exports the six studies with unique ids and the declared placements', () => {
    expect(ADAPTIVE_INDICATORS).toHaveLength(6);
    const ids = ADAPTIVE_INDICATORS.map((d) => d.id);
    expect(ids).toEqual([
      'kama', 'keltner-channel', 'lsma', 'klinger-oscillator', 'know-sure-thing', 'linreg-slope',
    ]);
    expect(new Set(ids).size).toBe(ids.length);
    expect(KAMA.placement).toBe('onchart');
    expect(KELTNER_CHANNEL.placement).toBe('onchart');
    expect(LSMA.placement).toBe('onchart');
    expect(KLINGER_OSCILLATOR.placement).toBe('pane');
    expect(KNOW_SURE_THING.placement).toBe('pane');
    expect(LINREG_SLOPE.placement).toBe('pane');
  });

  it('every plot names a declared colour input', () => {
    for (const d of ADAPTIVE_INDICATORS) {
      for (const plot of d.plots) {
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.key} colorKey`).toBe('color');
      }
    }
  });

  it('every fill joins two plots the descriptor actually declares', () => {
    for (const d of ADAPTIVE_INDICATORS) {
      const keys = d.plots.map((p) => p.key);
      for (const fill of d.fills ?? []) {
        for (const key of fill.between) expect(keys, `${d.id} fill`).toContain(key);
      }
    }
    expect(KELTNER_CHANNEL.fills?.[0].between).toEqual(['upper', 'lower']);
  });

  it('gives the two oscillators a zero line and the overlays none', () => {
    expect(KLINGER_OSCILLATOR.levels?.({})).toEqual([
      { price: 0, color: '#787b86', title: 'Zero', dashed: true },
    ]);
    expect(KNOW_SURE_THING.levels?.({})?.[0].price).toBe(0);
    expect(KAMA.levels).toBeUndefined();
    expect(LSMA.levels).toBeUndefined();
  });

  it('returns one full-length column per plot, of finite numbers or null only', () => {
    for (const d of ADAPTIVE_INDICATORS) {
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
    for (const d of ADAPTIVE_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });

  it('survives bars that carry no volume at all', () => {
    // `volume` is optional on Bar; a feed without it must not turn Klinger into NaN.
    const novol: Bar[] = wave(80).map(({ time, open, high, low, close }) => ({
      time, open, high, low, close,
    }));
    for (const d of ADAPTIVE_INDICATORS) {
      const values = run(d, novol);
      for (const plot of d.plots) {
        expect(values[plot.key].length).toBe(novol.length);
        for (const v of values[plot.key]) expect(v === null || Number.isFinite(v)).toBe(true);
      }
    }
  });
});

describe('KAMA', () => {
  it('reproduces a constant series exactly', () => {
    // Efficiency is 0 on a flat tape, so the smoothing constant collapses to the
    // slow alpha, but the average is already sitting on the value, so it stays.
    const out = run(KAMA, bars(40, () => 100));
    for (let i = 10; i < 40; i++) expect(out.kama[i] as number).toBeCloseTo(100, 12);
  });

  it('takes a full fast step on a perfectly efficient ramp', () => {
    // On a unit ramp the net move over 10 bars equals the path walked, so the
    // efficiency ratio is exactly 1 and the smoothing constant is fastAlpha^2.
    const out = run(KAMA, bars(20, (i) => i));
    expect(out.kama[10]).toBe(10); // seeded on the source
    const fastAlpha = 2 / (2 + 1);
    expect(out.kama[11] as number).toBeCloseTo(10 + fastAlpha * fastAlpha * 1, 12);
  });

  it('first prints at erLength, where both legs of the ratio exist', () => {
    expect(firstLive(run(KAMA, wave()).kama)).toBe(10);
    expect(firstLive(run(KAMA, wave(), { erLength: 21 }).kama)).toBe(21);
    // Fewer bars than the ratio needs is an empty plot, not a throw.
    expect(run(KAMA, wave(10)).kama.every((v) => v === null)).toBe(true);
  });

  it('tracks price more closely with a faster slow length', () => {
    const data = wave();
    const lazy = run(KAMA, data).kama;
    const eager = run(KAMA, data, { slowLength: 3 }).kama;
    const i = data.length - 1;
    const gap = (v: number | null) => Math.abs((v as number) - data[i].close);
    expect(gap(eager[i])).toBeLessThan(gap(lazy[i]));
  });
});

describe('Keltner Channels', () => {
  it('sits on a constant series with symmetric rails a hand-computed width apart', () => {
    // Every bar spans 100 +/- 1 and never gaps, so the true range is 2 on every
    // bar and the ATR is 2 exactly. mult 2 puts the rails 4 either side.
    const out = run(KELTNER_CHANNEL, bars(40, () => 100));
    for (let i = 19; i < 40; i++) {
      expect(out.basis[i] as number).toBeCloseTo(100, 12);
      expect(out.upper[i] as number).toBeCloseTo(104, 12);
      expect(out.lower[i] as number).toBeCloseTo(96, 12);
      expect((out.upper[i] as number) - (out.basis[i] as number))
        .toBeCloseTo((out.basis[i] as number) - (out.lower[i] as number), 12);
    }
  });

  it('starts every plot at length - 1 while the rail warms up faster', () => {
    const out = run(KELTNER_CHANNEL, wave());
    expect(firstLive(out.basis)).toBe(19);
    expect(firstLive(out.upper)).toBe(19);
    expect(firstLive(out.lower)).toBe(19);
    // The simple-MA basis has the same warmup, so the boundary does not move.
    expect(firstLive(run(KELTNER_CHANNEL, wave(), { exp: false }).basis)).toBe(19);
  });

  it('lets the slower of the basis and the rail set the band warmup', () => {
    // atrlength past the channel length is the one case where the rail is the
    // laggard: the basis prints nine bars before the band it belongs to.
    const out = run(KELTNER_CHANNEL, wave(), { atrlength: 30 });
    expect(firstLive(out.basis)).toBe(19);
    expect(firstLive(out.upper)).toBe(29);
    expect(firstLive(out.lower)).toBe(29);
  });

  it('gives the three band styles three different widths on the same data', () => {
    const data = gappy();
    const i = data.length - 1;
    const width = (style: string): number => {
      const out = run(KELTNER_CHANNEL, data, { bandsStyle: style });
      return (out.upper[i] as number) - (out.lower[i] as number);
    };
    const range = width('Range');
    const trueRange = width('True Range');
    const averageTrueRange = width('Average True Range');
    // "Range" ignores gaps, and these bars always span exactly 2, so 2 * mult * 2.
    expect(range).toBeCloseTo(8, 12);
    // A gapping tape ranges wider than its bars, and the smoothed rail sits
    // between the raw bar and the gap-blind one.
    expect(trueRange).toBeGreaterThan(range);
    expect(averageTrueRange).toBeGreaterThan(range);
    expect(new Set([
      range.toFixed(6), trueRange.toFixed(6), averageTrueRange.toFixed(6),
    ]).size).toBe(3);
  });

  it('scales the rails linearly with the multiplier', () => {
    const data = wave();
    const i = data.length - 1;
    const one = run(KELTNER_CHANNEL, data, { mult: 1 });
    const three = run(KELTNER_CHANNEL, data, { mult: 3 });
    const spread = (o: Record<string, readonly (number | null)[]>) =>
      (o.upper[i] as number) - (o.basis[i] as number);
    expect(spread(three)).toBeCloseTo(3 * spread(one), 10);
  });
});

describe('LSMA', () => {
  it('reproduces a perfectly linear series exactly', () => {
    // A least-squares fit of a straight line is that line, so the endpoint of
    // the fit is the bar itself, with no lag at all, unlike an SMA.
    const data = bars(40, (i) => 2 * i + 5);
    const out = run(LSMA, data);
    for (let i = 24; i < 40; i++) expect(out.lsma[i] as number).toBeCloseTo(2 * i + 5, 10);
  });

  it('steps back down the fitted line for a positive offset', () => {
    // Slope 2 per bar, so an offset of 3 must land exactly 6 below the close.
    const data = bars(40, (i) => 2 * i + 5);
    const out = run(LSMA, data, { offset: 3 });
    for (let i = 24; i < 40; i++) expect(out.lsma[i] as number).toBeCloseTo(2 * i - 1, 10);
  });

  it('first prints at length - 1', () => {
    expect(firstLive(run(LSMA, wave()).lsma)).toBe(24);
    expect(firstLive(run(LSMA, wave(), { length: 9 }).lsma)).toBe(8);
  });
});

describe('Klinger Oscillator', () => {
  it('is exactly zero when the tape carries no volume', () => {
    // Signed volume is the only input; with nothing to sign, both legs and the
    // spread collapse to zero rather than to a warmup gap.
    const data = wave(120).map((b) => ({ ...b, volume: 0 }));
    const out = run(KLINGER_OSCILLATOR, data);
    for (let i = 54; i < 120; i++) expect(out.kvo[i] as number).toBeCloseTo(0, 12);
    for (let i = 66; i < 120; i++) expect(out.signal[i] as number).toBeCloseTo(0, 12);
  });

  it('matches the closed-form EMA of a constant signed-volume series', () => {
    // hlc3 only rises and volume is 1 on every bar, so signed volume is -1 on
    // bar 0 (the reference `na >= 0` is false) and +1 after. A constant input has a
    // closed-form EMA: it decays from its SMA seed toward the constant.
    const data = bars(120, (i) => 100 + i).map((b) => ({ ...b, volume: 1 }));
    const seed = (len: number): number => (-1 + (len - 1)) / len;
    const decay = (len: number, steps: number): number => Math.pow(1 - 2 / (len + 1), steps);
    const fast = 1 + (seed(34) - 1) * decay(34, 54 - 33);
    const out = run(KLINGER_OSCILLATOR, data);
    expect(out.kvo[54] as number).toBeCloseTo(fast - seed(55), 12);
  });

  it('prints the spread at 54 and the signal 12 bars later at 66', () => {
    // The slow leg needs 55 bars; the signal EMA then re-seeds from an SMA of a
    // series that only starts there, so it cannot land before 54 + 13 - 1.
    const out = run(KLINGER_OSCILLATOR, wave(120));
    expect(firstLive(out.kvo)).toBe(54);
    expect(firstLive(out.signal)).toBe(66);
    // A chained EMA seeded from index 0 would have printed at 54 + 12 - 12 = 54.
    expect(out.signal[65]).toBeNull();
  });

  it('leaves both plots empty when there are fewer bars than the slow leg', () => {
    const out = run(KLINGER_OSCILLATOR, wave(50));
    expect(out.kvo.every((v) => v === null)).toBe(true);
    expect(out.signal.every((v) => v === null)).toBe(true);
  });
});

describe('Know Sure Thing', () => {
  it('matches the weighted sum of four hand-computed ROCs on a geometric series', () => {
    // close grows by a constant 1 % per bar, so every ROC is constant once it
    // exists and each smoothing pass returns that same constant untouched.
    const r = 1.01;
    const data = bars(60, (i) => 100 * Math.pow(r, i));
    const term = (len: number): number => 100 * (Math.pow(r, len) - 1);
    const expected = term(10) + 2 * term(15) + 3 * term(20) + 4 * term(30);
    const out = run(KNOW_SURE_THING, data);
    expect(out.kst[44] as number).toBeCloseTo(expected, 10);
    expect(out.kst[59] as number).toBeCloseTo(expected, 10);
    // The signal is an SMA of a constant, so it lands on the same number.
    expect(out.signal[52] as number).toBeCloseTo(expected, 10);
  });

  it('is zero on a flat tape, because every rate of change is zero', () => {
    const out = run(KNOW_SURE_THING, bars(60, () => 100));
    expect(out.kst[44] as number).toBeCloseTo(0, 12);
    expect(out.signal[52] as number).toBeCloseTo(0, 12);
  });

  it('prints at 44 and signals at 52, gated by the slowest term', () => {
    // roclen4 + smalen4 - 1 = 30 + 15 - 1, then siglen - 1 more for the signal.
    const out = run(KNOW_SURE_THING, wave(120));
    expect(firstLive(out.kst)).toBe(44);
    expect(firstLive(out.signal)).toBe(52);
    expect(out.kst[43]).toBeNull();
    expect(out.signal[51]).toBeNull();
  });

  it('moves both boundaries when the slowest term changes', () => {
    const out = run(KNOW_SURE_THING, wave(120), { roclen4: 40, smalen4: 5, siglen: 3 });
    expect(firstLive(out.kst)).toBe(44); // 40 + 5 - 1 still the slowest term
    expect(firstLive(out.signal)).toBe(46);
    const faster = run(KNOW_SURE_THING, wave(120), { roclen4: 12, smalen4: 5 });
    expect(firstLive(faster.kst)).toBe(29); // roclen3 + smalen3 - 1 now leads
  });
});
