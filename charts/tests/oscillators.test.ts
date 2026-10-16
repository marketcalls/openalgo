import { describe, it, expect } from 'vitest';
import {
  AROON,
  AROON_OSCILLATOR,
  AWESOME_OSCILLATOR,
  BALANCE_OF_POWER,
  CHANDE_MOMENTUM,
  COPPOCK_CURVE,
  DPO,
  FISHER_TRANSFORM,
  CONNORS_RSI,
  OSCILLATOR_INDICATORS,
  connorsStreak,
} from '../src/indicators/oscillators';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 200): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);
/** Strictly rising closes, highs and lows: every extreme is the current bar. */
const rising = (n = 40): Bar[] => bars(n, (i) => 100 + i);
/** The mirror: every extreme is the oldest bar in the window. */
const falling = (n = 40): Bar[] => bars(n, (i) => 200 - i * 2);

const defaults = (d: IndicatorDescriptor) => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

describe('TV momentum catalogue', () => {
  it('exports the nine studies under their the reference platform ids', () => {
    expect(OSCILLATOR_INDICATORS.map((d) => d.id)).toEqual([
      'aroon',
      'aroon-oscillator',
      'awesome-oscillator',
      'balance-of-power',
      'chande-momentum',
      'coppock-curve',
      'dpo',
      'fisher-transform',
      'connors-rsi',
    ]);
    expect(new Set(OSCILLATOR_INDICATORS.map((d) => d.id)).size).toBe(9);
    for (const d of OSCILLATOR_INDICATORS) expect(d.placement).toBe('pane');
  });

  it('points every plot at a declared colour input', () => {
    for (const d of OSCILLATOR_INDICATORS) {
      for (const plot of d.plots) {
        expect(plot.colorKey, `${d.id}.${plot.key} has no colorKey`).toBeTypeOf('string');
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.colorKey} is not a colour input`).toBe('color');
      }
    }
  });

  it('returns one full-length column of finite numbers or null per plot', () => {
    const data = wave();
    for (const d of OSCILLATOR_INDICATORS) {
      const values = run(d, data);
      for (const plot of d.plots) {
        expect(values[plot.key], `${d.id}.${plot.key} missing`).toBeDefined();
        expect(values[plot.key].length, `${d.id}.${plot.key} length`).toBe(data.length);
      }
      // Extra columns (the oscillator's zero edge) travel to the fill layer and
      // must obey the same contract.
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${d.id}.${key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of OSCILLATOR_INDICATORS) {
      for (const input of [[], wave().slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });
});

describe('Aroon', () => {
  it('is exactly 100 up / 0 down while every bar makes the high', () => {
    const out = run(AROON, rising());
    // highestbars is 0 on a fresh high, so 100 * (0 + 14) / 14 = 100 exactly.
    expect(out.up[14]).toBe(100);
    expect(out.down[14]).toBe(0);
    expect(out.up[39]).toBe(100);
  });

  it('mirrors to 0 up / 100 down on a strictly falling series', () => {
    const out = run(AROON, falling());
    expect(out.up[39]).toBe(0);
    expect(out.down[39]).toBe(100);
  });

  it('warms up over length + 1 bars, so the first value is at index 14', () => {
    const out = run(AROON, wave());
    expect(firstIndex(out.up)).toBe(14);
    expect(firstIndex(out.down)).toBe(14);
    expect(out.up[13]).toBeNull();
  });

  it('declares the 0..100 range the study is bounded to', () => {
    expect(AROON.range?.(defaults(AROON))).toEqual({ min: 0, max: 100 });
  });
});

describe('Aroon Oscillator', () => {
  it('is Aroon Up minus Aroon Down', () => {
    const data = wave();
    const aroon = run(AROON, data);
    const osc = run(AROON_OSCILLATOR, data);
    for (let i = 0; i < data.length; i++) {
      if (aroon.up[i] === null) { expect(osc.osc[i]).toBeNull(); continue; }
      expect(osc.osc[i] as number).toBeCloseTo((aroon.up[i] as number) - (aroon.down[i] as number), 10);
    }
  });

  it('reaches +100 on a rising series and -100 on a falling one, from index 14', () => {
    expect(run(AROON_OSCILLATOR, rising()).osc[14]).toBe(100);
    expect(run(AROON_OSCILLATOR, falling()).osc[14]).toBe(-100);
    expect(firstIndex(run(AROON_OSCILLATOR, wave()).osc)).toBe(14);
  });

  it('publishes a zero edge for the sign fill, aligned with the oscillator', () => {
    expect(AROON_OSCILLATOR.fills?.[0].between).toEqual(['osc', 'zero']);
    const out = run(AROON_OSCILLATOR, wave());
    for (let i = 0; i < out.osc.length; i++) {
      expect(out.zero[i]).toBe(out.osc[i] === null ? null : 0);
    }
  });
});

describe('Awesome Oscillator', () => {
  it('is the 5-bar midpoint average minus the 34-bar one', () => {
    // hl2 on this fixture equals the close, so the arithmetic is exact:
    // mean(36..40) = 38, mean(7..40) = 23.5.
    const out = run(AWESOME_OSCILLATOR, bars(40, (i) => i + 1));
    expect(out.ao[39] as number).toBeCloseTo(38 - 23.5, 10);
  });

  it('prints nothing until the 34-bar average exists, so first value is index 33', () => {
    const out = run(AWESOME_OSCILLATOR, wave());
    expect(firstIndex(out.ao)).toBe(33);
    expect(out.ao[32]).toBeNull();
  });

  it('colours each column by its direction against the previous bar', () => {
    const plot = AWESOME_OSCILLATOR.plots.find((p) => p.key === 'ao');
    expect(plot?.colorBy).toBeTypeOf('function');
    const values = { ao: [1, 2, 1.5] } as Record<string, (number | null)[]>;
    const settings = defaults(AWESOME_OSCILLATOR);
    const at = (i: number) =>
      plot?.colorBy?.({ value: values.ao[i] as number, index: i, values, settings });
    expect(at(1)).toBe(settings.upColor);   // 2 > 1: rising
    expect(at(2)).toBe(settings.downColor); // 1.5 < 2: falling
    // the reference compares against `na` on the first bar, and `na <= 0` is false.
    expect(at(0)).toBe(settings.upColor);
  });
});

describe('Balance of Power', () => {
  it('is the body as a fraction of the range', () => {
    const seq: Bar[] = [
      { time: 1, open: 10, high: 12, low: 8, close: 11, volume: 1 },  // +1 / 4
      { time: 2, open: 10, high: 12, low: 8, close: 8, volume: 1 },   // -2 / 4
    ];
    const out = run(BALANCE_OF_POWER, seq);
    expect(out.bop[0]).toBeCloseTo(0.25, 12);
    expect(out.bop[1]).toBeCloseTo(-0.5, 12);
  });

  it('has no warmup, so the first bar already prints', () => {
    expect(firstIndex(run(BALANCE_OF_POWER, wave()).bop)).toBe(0);
  });

  it('gaps on a zero-range bar instead of dividing by zero', () => {
    const seq: Bar[] = [{ time: 1, open: 10, high: 10, low: 10, close: 10, volume: 1 }];
    expect(run(BALANCE_OF_POWER, seq).bop[0]).toBeNull();
  });
});

describe('Chande Momentum Oscillator', () => {
  it('is +100 when every change is up and -100 when every change is down', () => {
    expect(run(CHANDE_MOMENTUM, bars(20, (i) => i + 1)).cmo[19]).toBe(100);
    expect(run(CHANDE_MOMENTUM, bars(20, (i) => 20 - i)).cmo[19]).toBe(-100);
  });

  it('needs length real changes, so the first value is at index 9', () => {
    const out = run(CHANDE_MOMENTUM, wave());
    expect(firstIndex(out.cmo)).toBe(9);
    expect(out.cmo[8]).toBeNull();
    expect(out.cmo[9]).not.toBeNull();
  });

  it('gaps on a perfectly flat window rather than printing 0/0', () => {
    expect(run(CHANDE_MOMENTUM, bars(20, () => 100)).cmo.every((v) => v === null)).toBe(true);
  });
});

describe('Coppock Curve', () => {
  it('collapses to the sum of the two rates of change on a constant-growth series', () => {
    // A geometric series makes both roc terms constant, and a WMA of a
    // constant is that constant, so the expected value is closed-form.
    const data = bars(40, (i) => 100 * Math.pow(1.01, i));
    const expected = 100 * (Math.pow(1.01, 14) - 1) + 100 * (Math.pow(1.01, 11) - 1);
    const out = run(COPPOCK_CURVE, data);
    expect(out.curve[23] as number).toBeCloseTo(expected, 8);
    expect(out.curve[39] as number).toBeCloseTo(expected, 8);
  });

  it('warms up over the long RoC plus the WMA, so the first value is at index 23', () => {
    const out = run(COPPOCK_CURVE, wave());
    expect(firstIndex(out.curve)).toBe(23);
    expect(out.curve[22]).toBeNull();
  });
});

describe('Detrended Price Oscillator', () => {
  it('is a constant offset on a linear series, non-centered', () => {
    // close[i] = 100 + i, sma(21)[i - 11] = 100 + (i - 11) - 10, so the
    // difference is 21 on every printed bar.
    const out = run(DPO, rising(60));
    expect(out.dpo[31] as number).toBeCloseTo(21, 10);
    expect(out.dpo[59] as number).toBeCloseTo(21, 10);
  });

  it('warms up to barsback + length - 1 = 31 when not centered', () => {
    const out = run(DPO, wave());
    expect(firstIndex(out.dpo)).toBe(31);
    expect(out.dpo[30]).toBeNull();
  });

  it('folds the reference offset into the column when centered', () => {
    const data = rising(60);
    const out = run(DPO, data, { isCentered: true });
    // Drawn at bar i is the reference bar i + 11: close[i] - sma(21)[i + 11] = -1.
    expect(firstIndex(out.dpo)).toBe(9);
    expect(out.dpo[9] as number).toBeCloseTo(-1, 10);
    expect(out.dpo[48] as number).toBeCloseTo(-1, 10);
    // The shift is why a centered DPO stops short of the right edge.
    expect(out.dpo.slice(49).every((v) => v === null)).toBe(true);
    expect(out.dpo.length).toBe(data.length);
  });

  it('floors barsback so an even length still indexes a whole bar', () => {
    // 20 / 2 + 1 = 11, the same as 21 / 2 + 1 under truncation.
    const out = run(DPO, wave(), { period: 20 });
    expect(firstIndex(out.dpo)).toBe(30); // 11 + 20 - 1
  });
});

describe('Fisher Transform', () => {
  it('follows the clamped recursion from a zero seed', () => {
    // Every bar makes the high, so (hl2 - low_) / (high_ - low_) is 1 and the
    // raw value is 0.33 + 0.67 * previous, starting from nz(na) = 0.
    const out = run(FISHER_TRANSFORM, rising());
    const v8 = 0.33;
    const f8 = 0.5 * Math.log((1 + v8) / (1 - v8));
    const v9 = 0.33 + 0.67 * v8;
    const f9 = 0.5 * Math.log((1 + v9) / (1 - v9)) + 0.5 * f8;
    expect(out.fisher[8] as number).toBeCloseTo(f8, 12);
    expect(out.fisher[9] as number).toBeCloseTo(f9, 12);
  });

  it('starts Fisher at index 8 and Trigger one bar later', () => {
    const out = run(FISHER_TRANSFORM, wave());
    expect(firstIndex(out.fisher)).toBe(8);
    expect(firstIndex(out.trigger)).toBe(9);
  });

  it('Trigger is Fisher shifted back exactly one bar', () => {
    const out = run(FISHER_TRANSFORM, wave());
    for (let i = 1; i < out.fisher.length; i++) expect(out.trigger[i]).toBe(out.fisher[i - 1]);
    expect(out.trigger[0]).toBeNull();
  });

  it('stays finite under the +/-0.999 clamp on a long one-way run', () => {
    const out = run(FISHER_TRANSFORM, rising(300));
    for (const v of out.fisher) expect(v === null || Number.isFinite(v)).toBe(true);
  });

  it('floors the range divide rather than dividing by zero when the window is flat', () => {
    // A flat window makes the ratio 0 / 0.001 = 0, so the raw value is
    // -0.33 + 0.67 * previous and the series still prints. It walks toward the
    // clamped fixed point, ln(0.001 / 1.999) = -7.6004023.
    const out = run(FISHER_TRANSFORM, bars(30, () => 100));
    expect(out.fisher.slice(0, 8).every((v) => v === null)).toBe(true);
    expect(out.fisher[8] as number).toBeCloseTo(-0.3428282544, 9);
    expect(out.fisher[9] as number).toBeCloseTo(-0.7913738721, 9);
    expect(out.fisher[29] as number).toBeCloseTo(-7.5989792976, 9);
  });
});

describe('Connors RSI', () => {
  it('counts consecutive up and down days in the streak series', () => {
    // -1 on the first bar: the reference compares against na, which is neither equal nor
    // greater, so it lands in the down branch with nz(ud[1]) = 0.
    expect(connorsStreak([10, 11, 12, 12, 11, 10, 10.5])).toEqual([-1, 1, 2, 0, -1, -2, 1]);
    expect(connorsStreak([5, 6, 7, 8])).toEqual([-1, 1, 2, 3]);
    expect(connorsStreak([])).toEqual([]);
    expect(connorsStreak([42])).toEqual([-1]);
  });

  it('averages the three components, so a pure uptrend sits at 200 / 3', () => {
    // RSI of price = 100, RSI of the streak = 100, and the one-bar return of a
    // linear series shrinks every bar, so its percent rank is 0.
    const out = run(CONNORS_RSI, rising(150));
    expect(out.crsi[149] as number).toBeCloseTo(200 / 3, 10);
  });

  it('waits for the percent rank window, so the first value is at index 101', () => {
    const out = run(CONNORS_RSI, wave());
    expect(firstIndex(out.crsi)).toBe(101);
    expect(out.crsi[100]).toBeNull();
  });

  it('stays inside the 0..100 range it declares', () => {
    const out = run(CONNORS_RSI, wave());
    for (const v of out.crsi) {
      if (v === null) continue;
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
    expect(CONNORS_RSI.range?.(defaults(CONNORS_RSI))).toEqual({ min: 0, max: 100 });
  });

  it('draws the reference bands as levels', () => {
    expect(CONNORS_RSI.levels?.(defaults(CONNORS_RSI)).map((l) => l.price)).toEqual([70, 50, 30]);
  });
});

describe('Connors RSI background band', () => {
  it('declares one fill whose edges are columns calc actually returns', () => {
    const fills = CONNORS_RSI.fills ?? [];
    expect(fills).toHaveLength(1);
    expect(fills[0].between).toEqual(['bandHigh', 'bandLow']);
    // A fill naming a column that does not exist renders nothing and throws
    // nothing, so the edges are checked against calc's output, not the plots.
    const out = run(CONNORS_RSI, wave());
    for (const key of fills[0].between) expect(out[key], `fill edge ${key}`).toBeDefined();
  });

  it('holds 70 and 30 on every bar, the study warmup included', () => {
    const data = wave();
    const out = run(CONNORS_RSI, data);
    expect(out.bandHigh).toHaveLength(data.length);
    expect(out.bandLow).toHaveLength(data.length);
    expect(out.bandHigh.every((v) => v === 70)).toBe(true);
    expect(out.bandLow.every((v) => v === 30)).toBe(true);
    // Bar 100 is still inside the 101-bar warmup: no line, but the reference
    // shades the whole pane, so both edges have to be there.
    expect(out.crsi[100]).toBeNull();
    expect(out.bandHigh[100]).toBe(70);
    expect(out.bandLow[0]).toBe(30);
  });

  it('paints the band through a declared colour input at the source opacity', () => {
    const fill = (CONNORS_RSI.fills ?? [])[0];
    expect(fill.colorUpKey).toBe('fillColor');
    expect(fill.colorDownKey).toBe('fillColor');
    expect(fill.opacity).toBe(0.1);
    const declared = CONNORS_RSI.inputs.find((i) => i.key === 'fillColor');
    expect(declared?.type).toBe('color');
    expect(declared?.default).toBe('#2196f3');
  });

  it('leaves the published readings untouched', () => {
    expect(firstIndex(run(CONNORS_RSI, wave()).crsi)).toBe(101);
  });

  it('emits the band on empty and single-bar input too', () => {
    expect(run(CONNORS_RSI, []).bandHigh).toEqual([]);
    expect(run(CONNORS_RSI, wave().slice(0, 1)).bandLow).toEqual([30]);
  });
});
