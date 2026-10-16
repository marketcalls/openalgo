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
  STRENGTH_INDICATORS,
} from '../src/indicators/strength';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 200): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);
/** Every close higher than the last, so every one-bar change is +1. */
const rising = (n = 60): Bar[] => bars(n, (i) => 100 + i);
/** The mirror: every one-bar change is -2. */
const falling = (n = 60): Bar[] => bars(n, (i) => 200 - i * 2);
/** A ramp in log space: log(close) is 0.01 * i, which is what TRIX measures. */
const logRamp = (n = 90): Bar[] => bars(n, (i) => Math.exp(0.01 * i));
/** Nothing moves at all, and high == low == close, so every range is zero. */
const frozen = (n = 40, c = 100): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1700000000 + i * 60, open: c, high: c, low: c, close: c, volume: 100,
  }));

const defaults = (d: IndicatorDescriptor) => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

/** A rolling mean written out longhand, to check the descriptors from outside. */
const meanOf = (xs: readonly number[], i: number, p: number): number => {
  let sum = 0;
  for (let k = 0; k < p; k++) sum += xs[i - k];
  return sum / p;
};

describe('Strength momentum catalogue', () => {
  it('exports the eight studies under their upstream ids', () => {
    expect(STRENGTH_INDICATORS.map((d) => d.id)).toEqual([
      'momentum',
      'roc',
      'ppo',
      'trix',
      'tsi',
      'smi-ergodic-indicator',
      'smi-ergodic-oscillator',
      'smi',
    ]);
    expect(new Set(STRENGTH_INDICATORS.map((d) => d.id)).size).toBe(8);
    for (const d of STRENGTH_INDICATORS) expect(d.placement).toBe('pane');
  });

  it('points every plot at a declared colour input', () => {
    for (const d of STRENGTH_INDICATORS) {
      for (const plot of d.plots) {
        expect(plot.colorKey, `${d.id}.${plot.key} has no colorKey`).toBeTypeOf('string');
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.colorKey} is not a colour input`).toBe('color');
      }
    }
  });

  it('returns one full-length column of finite numbers or null per plot', () => {
    const data = wave();
    for (const d of STRENGTH_INDICATORS) {
      const values = run(d, data);
      for (const plot of d.plots) {
        expect(values[plot.key], `${d.id}.${plot.key} missing`).toBeDefined();
        expect(values[plot.key].length, `${d.id}.${plot.key} length`).toBe(data.length);
      }
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${d.id}.${key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of STRENGTH_INDICATORS) {
      for (const input of [[], wave().slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });

  it('never emits a non-finite number on a completely flat series', () => {
    // Zero ranges and zero changes are where the divisions in this group blow
    // up; every one of them has to print a gap instead.
    const data = frozen();
    for (const d of STRENGTH_INDICATORS) {
      for (const [key, col] of Object.entries(run(d, data))) {
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });
});

describe('Momentum', () => {
  it('is exactly slope * length on a linear ramp', () => {
    const out = run(MOMENTUM, bars(60, (i) => 100 + 2 * i));
    expect(out.mom[10]).toBe(20);
    expect(out.mom[59]).toBe(20);
  });

  it('warms up over exactly `len` bars', () => {
    const out = run(MOMENTUM, wave());
    expect(firstIndex(out.mom)).toBe(10);
    expect(out.mom[9]).toBeNull();
    expect(firstIndex(run(MOMENTUM, wave(), { len: 5 }).mom)).toBe(5);
  });

  it('reads the chosen source', () => {
    // Volume rises by 1 a bar in the fixture, close by 2.
    const out = run(MOMENTUM, bars(60, (i) => 100 + 2 * i), { source: 'volume' });
    expect(out.mom[10]).toBe(10);
  });
});

describe('Rate of Change', () => {
  it('is named like Balance of Power, with a lower-case of', () => {
    expect(ROC.name).toBe('Rate of Change');
  });

  it('is 100 * (src - src[length]) / src[length]', () => {
    const out = run(ROC, rising());
    expect(out.roc[9]).toBe(9); // 100 * (109 - 100) / 100
    expect(out.roc[20]).toBeCloseTo((100 * (120 - 111)) / 111, 12);
  });

  it('warms up over exactly `length` bars', () => {
    const out = run(ROC, wave());
    expect(firstIndex(out.roc)).toBe(9);
    expect(out.roc[8]).toBeNull();
  });

  it('declares the zero line the source script draws', () => {
    expect(ROC.levels?.(defaults(ROC))).toEqual([
      { price: 0, color: '#787b86', title: 'Zero Line', dashed: true },
    ]);
  });
});

describe('Percentage Price Oscillator', () => {
  it('is exactly zero when the fast and slow lengths agree', () => {
    const out = run(PPO, wave(), { fastLength: 12, slowLength: 12 });
    // The two averages are then the same series, so the difference is a true
    // zero and the signal of a zero series is zero too.
    expect(out.ppo[11]).toBe(0);
    expect(out.ppo[199]).toBe(0);
    expect(out.signal[19]).toBe(0);
    expect(out.hist[19]).toBe(0);
  });

  it('matches a longhand SMA computation in SMA mode', () => {
    const data = wave();
    const closes = data.map((b) => b.close);
    const out = run(PPO, data, { oscType: 'SMA', sigType: 'SMA' });

    const refPpo = closes.map((_, i) => {
      if (i < 25) return NaN;
      const slow = meanOf(closes, i, 26);
      return (100 * (meanOf(closes, i, 12) - slow)) / slow;
    });
    expect(out.ppo[30]).toBeCloseTo(refPpo[30], 12);

    let sum = 0;
    for (let k = 0; k < 9; k++) sum += refPpo[40 - k];
    expect(out.signal[40]).toBeCloseTo(sum / 9, 12);
    expect(out.hist[40]).toBeCloseTo(refPpo[40] - sum / 9, 12);
  });

  it('starts the oscillator at slowLength - 1 and the signal a further signalLength - 1 later', () => {
    for (const mode of ['EMA', 'SMA']) {
      const out = run(PPO, wave(), { oscType: mode, sigType: mode });
      expect(firstIndex(out.ppo), mode).toBe(25);
      expect(firstIndex(out.signal), mode).toBe(33);
      expect(firstIndex(out.hist), mode).toBe(33);
      expect(out.signal[32], mode).toBeNull();
    }
  });

  it('draws the histogram as columns so the per-bar colour is honoured', () => {
    expect(PPO.plots[0].key).toBe('hist');
    expect(PPO.plots[0].type).toBe('column');
  });

  it('colours the histogram by sign and direction, in all four states', () => {
    const settings = defaults(PPO);
    const colorAt = (hist: (number | null)[], index: number): string | undefined =>
      PPO.plots[0].colorBy?.({ value: hist[index] as number, index, values: { hist }, settings });

    expect(colorAt([1, 5], 1)).toBe('#26a69a'); // positive and building
    expect(colorAt([5, 1], 1)).toBe('#b2dfdb'); // positive but fading
    expect(colorAt([-5, -1], 1)).toBe('#ffcdd2'); // negative but recovering
    expect(colorAt([-1, -5], 1)).toBe('#ff5252'); // negative and deepening
    // `hist[1]` is na on the first printed bar and `na > x` is false upstream,
    // so the very first column takes the weakening branch.
    expect(colorAt([5], 0)).toBe('#b2dfdb');
    expect(colorAt([-5], 0)).toBe('#ff5252');
  });
});

describe('TRIX', () => {
  it('is exactly zero on a constant series', () => {
    // log(1) is 0, so all three EMAs are 0 and the change of a flat triple-EMA
    // is a true zero rather than a rounding artefact.
    const out = run(TRIX, bars(80, () => 1));
    expect(out.trix[52]).toBe(0);
    expect(out.trix[79]).toBe(0);
  });

  it('reads back the log-space slope of a geometric series', () => {
    // An SMA-seeded EMA of an exact straight line is that line lagged by
    // (p-1)/2, so a triple EMA keeps the slope and the one-bar change recovers
    // it: 10000 * 0.01 = 100.
    const out = run(TRIX, logRamp());
    expect(out.trix[60]).toBeCloseTo(100, 6);
    expect(out.trix[89]).toBeCloseTo(100, 6);
  });

  it('first prints at 3 * length - 2', () => {
    const out = run(TRIX, wave());
    expect(firstIndex(out.trix)).toBe(52);
    expect(out.trix[51]).toBeNull();
    expect(firstIndex(run(TRIX, wave(), { length: 5 }).trix)).toBe(13);
  });

  it('declares the zero line the source script draws', () => {
    expect(TRIX.levels?.(defaults(TRIX))).toEqual([
      { price: 0, color: '#787b86', title: 'Zero', dashed: true },
    ]);
  });
});

describe('True Strength Index', () => {
  it('pins to +100 on a strictly rising series and -100 on a strictly falling one', () => {
    // The double-smoothed change and the double-smoothed absolute change are
    // then the same series (or exact negatives), so the ratio is +/-1.
    expect(run(TSI, rising()).tsi[37]).toBe(100);
    expect(run(TSI, rising()).tsi[59]).toBe(100);
    expect(run(TSI, falling()).tsi[37]).toBe(-100);
  });

  it('reduces to the sign of the one-bar change at length 1', () => {
    // ema(src, 1) is src, so both smoothing passes vanish and the study is
    // 100 * change / |change|.
    const data = wave();
    const out = run(TSI, data, { long: 1, short: 1 });
    for (let i = 1; i < data.length; i++) {
      const delta = data[i].close - data[i - 1].close;
      expect(out.tsi[i]).toBe(delta > 0 ? 100 : -100);
    }
    expect(out.tsi[0]).toBeNull();
  });

  it('warms up through change, the long EMA, the short EMA and the signal', () => {
    const out = run(TSI, wave());
    expect(firstIndex(out.tsi)).toBe(37); // 1 + 24 + 12
    expect(firstIndex(out.signal)).toBe(49); // + 12
    expect(out.tsi[36]).toBeNull();
    expect(out.signal[48]).toBeNull();

    const short = run(TSI, wave(), { long: 5, short: 3, signal: 2 });
    expect(firstIndex(short.tsi)).toBe(7); // 1 + 4 + 2
    expect(firstIndex(short.signal)).toBe(8);
  });

  it('declares the zero line the source script draws', () => {
    expect(TSI.levels?.(defaults(TSI))).toEqual([
      { price: 0, color: '#787b86', title: 'Zero', dashed: true },
    ]);
  });
});

describe('SMI Ergodic Indicator', () => {
  it('is tsi with the ergodic defaults, so it agrees with True Strength Index', () => {
    const data = wave();
    const erg = run(SMI_ERGODIC_INDICATOR, data).erg;
    const tsi = run(TSI, data, { long: 20, short: 5 }).tsi;
    for (let i = 0; i < data.length; i++) expect(erg[i]).toBe(tsi[i]);
  });

  it('pins to +100 on a strictly rising series', () => {
    const out = run(SMI_ERGODIC_INDICATOR, rising());
    expect(out.erg[24]).toBe(100);
    expect(out.sig[28]).toBe(100);
  });

  it('warms up to bar 24 with the signal four bars behind', () => {
    const out = run(SMI_ERGODIC_INDICATOR, wave());
    expect(firstIndex(out.erg)).toBe(24); // 1 + 19 + 4
    expect(firstIndex(out.sig)).toBe(28); // + 4
    expect(out.erg[23]).toBeNull();
    expect(out.sig[27]).toBeNull();
  });

  it('draws no horizontal lines, matching the source script', () => {
    expect(SMI_ERGODIC_INDICATOR.levels).toBeUndefined();
  });
});

describe('SMI Ergodic Oscillator', () => {
  it('is the ergodic minus its signal', () => {
    const data = wave();
    const osc = run(SMI_ERGODIC_OSCILLATOR, data).osc;
    const both = run(SMI_ERGODIC_INDICATOR, data);
    for (let i = 0; i < data.length; i++) {
      const erg = both.erg[i];
      const sig = both.sig[i];
      if (erg === null || sig === null) expect(osc[i]).toBeNull();
      else expect(osc[i]).toBeCloseTo(erg - sig, 12);
    }
  });

  it('inherits the signal warmup, so it first prints at bar 28', () => {
    const out = run(SMI_ERGODIC_OSCILLATOR, wave());
    expect(firstIndex(out.osc)).toBe(28);
    expect(out.osc[27]).toBeNull();
  });

  it('is a histogram in the upstream colour', () => {
    expect(SMI_ERGODIC_OSCILLATOR.plots[0].type).toBe('histogram');
    const declared = SMI_ERGODIC_OSCILLATOR.inputs.find((i) => i.key === 'color');
    expect(declared?.default).toBe('#ff5252');
  });
});

describe('Stochastic Momentum Index', () => {
  it('measures the close against the midpoint of the high/low range', () => {
    // On the rising fixture the 10-bar window is high[i] = 101 + i down to
    // low[i-9] = 90 + i, so the range is a constant 11 and the close sits a
    // constant 4.5 above the midpoint. Both survive the double EMA untouched.
    const out = run(SMI, rising());
    expect(out.smi[13]).toBeCloseTo(900 / 11, 10);
    expect(out.smi[59]).toBeCloseTo(900 / 11, 10);
    expect(out.ema[15]).toBeCloseTo(900 / 11, 10);
  });

  it('uses high and low for the window, not the close', () => {
    // A close-only range would be 9 wide, not 11, giving 200 * 0 / 9 = 0 here
    // (the close is the top of its own window on a rising series).
    const out = run(SMI, rising());
    expect(out.smi[13]).not.toBeCloseTo(0, 6);
  });

  it('warms up through the window and both EMA passes', () => {
    const out = run(SMI, wave());
    expect(firstIndex(out.smi)).toBe(13); // 9 + 2 + 2
    expect(firstIndex(out.ema)).toBe(15); // + 2
    expect(out.smi[12]).toBeNull();
    expect(out.ema[14]).toBeNull();
  });

  it('prints a gap rather than an infinity when the range collapses', () => {
    const out = run(SMI, frozen());
    for (const v of out.smi) expect(v).toBeNull();
    for (const v of out.ema) expect(v).toBeNull();
  });

  it('declares the +40 / 0 / -40 lines the source script draws', () => {
    expect(SMI.levels?.(defaults(SMI))).toEqual([
      { price: 40, color: '#787b86', title: 'Overbought Line', dashed: true },
      { price: 0, color: '#787b86', title: 'Middle Line', dashed: true },
      { price: -40, color: '#787b86', title: 'Oversold Line', dashed: true },
    ]);
  });
});

describe('SMI background band', () => {
  it('declares one fill whose edges are columns calc actually returns', () => {
    const fills = SMI.fills ?? [];
    // One, not three: the source also paints two clipped gradients from the
    // plot to the zero line, which a flat two-column fill cannot reproduce.
    expect(fills).toHaveLength(1);
    expect(fills[0].between).toEqual(['bandHigh', 'bandLow']);
    // A fill naming a column that does not exist renders nothing and throws
    // nothing, so the edges are checked against calc's output, not the plots.
    const out = run(SMI, wave());
    for (const key of fills[0].between) expect(out[key], `fill edge ${key}`).toBeDefined();
  });

  it('holds +40 and -40 on every bar, the study warmup included', () => {
    const data = wave();
    const out = run(SMI, data);
    expect(out.bandHigh).toHaveLength(data.length);
    expect(out.bandHigh.every((v) => v === 40)).toBe(true);
    expect(out.bandLow.every((v) => v === -40)).toBe(true);
    // Bar 12 is a bar short of the first reading, and the frozen fixture never
    // prints at all; the background covers the pane in both cases.
    expect(out.smi[12]).toBeNull();
    expect(out.bandHigh[12]).toBe(40);
    const flat = run(SMI, frozen());
    expect(flat.smi.every((v) => v === null)).toBe(true);
    expect(flat.bandLow.every((v) => v === -40)).toBe(true);
  });

  it('paints the band through a declared colour input at the source opacity', () => {
    const fill = (SMI.fills ?? [])[0];
    expect(fill.colorUpKey).toBe('fillColor');
    expect(fill.colorDownKey).toBe('fillColor');
    expect(fill.opacity).toBe(0.1);
    const declared = SMI.inputs.find((i) => i.key === 'fillColor');
    expect(declared?.type).toBe('color');
    expect(declared?.default).toBe('#2196f3');
  });

  it('leaves the published readings untouched', () => {
    expect(run(SMI, rising()).smi[13]).toBeCloseTo(900 / 11, 10);
    expect(firstIndex(run(SMI, wave()).smi)).toBe(13);
  });

  it('emits the band on empty and single-bar input too', () => {
    expect(run(SMI, []).bandHigh).toEqual([]);
    expect(run(SMI, wave().slice(0, 1)).bandLow).toEqual([-40]);
  });
});
