import { describe, it, expect } from 'vitest';
import {
  OVERLAY_INDICATORS,
  ALMA, DEMA, HMA, ENVELOPE, DONCHIAN, CHANDE_KROLL_STOP, CHANDELIER_EXIT,
} from '../src/indicators/overlay';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import { wma } from '../src/indicators/calc';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 120): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);
const ramp = (n = 40): Bar[] => bars(n, (i) => i);

/** Closes chosen so every rolling window has a distinct extreme. */
const jagged = (): Bar[] => bars(4, (i) => [10, 14, 12, 13][i]);

/** Index of the first plotted bar: the number every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const run = (d: IndicatorDescriptor, data: Bar[], overrides: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...overrides }, {});

describe('the reference platform overlays: descriptor contract', () => {
  const data = wave();

  it('exports the ten overlays with unique ids, all on the price pane', () => {
    expect(OVERLAY_INDICATORS).toHaveLength(10);
    const ids = OVERLAY_INDICATORS.map((d) => d.id);
    expect(ids).toEqual([
      'alma', 'dema', 'hma', 'envelope', 'donchian', 'chande-kroll-stop', 'chandelier-exit',
      'standard-error-bands', 'ma-channel', 'hull-suite',
    ]);
    expect(new Set(ids).size).toBe(ids.length);
    for (const d of OVERLAY_INDICATORS) expect(d.placement).toBe('onchart');
  });

  it('every plot names a declared colour input', () => {
    for (const d of OVERLAY_INDICATORS) {
      for (const plot of d.plots) {
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.key} colorKey`).toBe('color');
      }
    }
  });

  it('every fill joins two plots the descriptor actually declares', () => {
    for (const d of OVERLAY_INDICATORS) {
      const keys = d.plots.map((p) => p.key);
      for (const fill of d.fills ?? []) {
        for (const key of fill.between) expect(keys, `${d.id} fill`).toContain(key);
      }
    }
  });

  it('returns one full-length column per plot, of finite numbers or null only', () => {
    for (const d of OVERLAY_INDICATORS) {
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
    for (const d of OVERLAY_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });
});

describe('ALMA', () => {
  it('matches the Gaussian kernel by hand', () => {
    // length 2, offset 1, sigma 2 give m = 1, s = 1. The current bar sits at the
    // peak (weight 1), the previous bar one standard deviation out.
    const w = Math.exp(-0.5);
    const out = run(ALMA, bars(2, (i) => [10, 20][i]), { length: 2, offset: 1, sigma: 2 });
    expect(out.alma[0]).toBeNull();
    expect(out.alma[1] as number).toBeCloseTo((10 * w + 20 * 1) / (1 + w), 10);
  });

  it('reproduces a flat series exactly, because the weights normalise to one', () => {
    const out = run(ALMA, bars(20, () => 100));
    expect(out.alma[19] as number).toBeCloseTo(100, 10);
  });

  it('first prints at length - 1', () => {
    expect(firstLive(run(ALMA, wave()).alma)).toBe(8);
    expect(firstLive(run(ALMA, wave(), { length: 21 }).alma)).toBe(20);
  });
});

describe('DEMA', () => {
  // Double smoothing cancels the lag of a straight line, so on a unit ramp the
  // published value is the close itself. Anything that got the EMA seeding
  // wrong drifts off this immediately.
  it('lands on the close of a linear series', () => {
    const out = run(DEMA, bars(6, (i) => i + 1), { length: 2 });
    expect(out.dema.slice(2)).toEqual([3, 4, 5, 6]);
  });

  it('first prints at 2 * length - 2, not length - 1', () => {
    // The second pass runs over a series that is itself NaN for its warmup, and
    // the reference re-seeds from an SMA that cannot form until the gap has cleared.
    expect(firstLive(run(DEMA, bars(6, (i) => i + 1), { length: 2 }).dema)).toBe(2);
    expect(firstLive(run(DEMA, wave()).dema)).toBe(16);
    expect(firstLive(run(DEMA, wave(), { length: 21 }).dema)).toBe(40);
  });
});

describe('HMA', () => {
  // Whole weighted windows lag a unit ramp by (period - 1) / 3.
  // At length 9 the combined lag is 2 * 1 - 8/3 + 2/3 = 0.
  it('tracks a linear series at the default length', () => {
    const out = run(HMA, ramp());
    expect(out.hma[15] as number).toBeCloseTo(15, 10);
    expect(out.hma[39] as number).toBeCloseTo(39, 10);
  });

  it('is the weighted composition the published definition writes', () => {
    const data = wave();
    const closes = data.map((b) => b.close);
    const fast = wma(closes, 4);
    const slow = wma(closes, 9);
    const expected = wma(fast.map((v, i) => 2 * v - slow[i]), 3);
    const out = run(HMA, data);
    const i = data.length - 1;
    expect(out.hma[i] as number).toBeCloseTo(expected[i], 10);
  });

  it('first prints at length + round(sqrt(length)) - 2', () => {
    expect(firstLive(run(HMA, wave()).hma)).toBe(10);          // 9 + 3 - 2
    expect(firstLive(run(HMA, wave(), { length: 16 }).hma)).toBe(18); // 16 + 4 - 2
  });
});

describe('Envelope', () => {
  it('offsets an SMA basis by a percentage', () => {
    const out = run(ENVELOPE, bars(5, (i) => i + 1), { length: 3, percent: 10 });
    expect(out.basis[4] as number).toBeCloseTo(4, 10); // (3 + 4 + 5) / 3
    expect(out.upper[4] as number).toBeCloseTo(4.4, 10);
    expect(out.lower[4] as number).toBeCloseTo(3.6, 10);
  });

  it('seeds the exponential basis from an SMA, the reference-style', () => {
    // The base bundle's `ema` would emit from bar 0 seeded on close[0]; the reference
    // starts at length - 1 on the mean of the window.
    const out = run(ENVELOPE, bars(5, (i) => i + 1), { length: 3, exponential: true });
    expect(out.basis[0]).toBeNull();
    expect(out.basis[1]).toBeNull();
    expect(out.basis[2] as number).toBeCloseTo(2, 10); // (1 + 2 + 3) / 3
  });

  it('first prints at length - 1 either way', () => {
    expect(firstLive(run(ENVELOPE, wave()).basis)).toBe(19);
    expect(firstLive(run(ENVELOPE, wave(), { exponential: true }).upper)).toBe(19);
  });
});

describe('Donchian Channels', () => {
  it('puts the basis at the midpoint of the extremes', () => {
    const out = run(DONCHIAN, bars(5, (i) => i + 1), { length: 3 });
    expect(out.upper[4] as number).toBe(6); // highs 4, 5, 6
    expect(out.lower[4] as number).toBe(2); // lows  2, 3, 4
    expect(out.basis[4] as number).toBe(4);
    expect(out.basis[2] as number).toBe((4 + 0) / 2);
  });

  it('displaces every band by the offset setting', () => {
    const shifted = run(DONCHIAN, bars(5, (i) => i + 1), { length: 3, offset: 2 });
    expect(firstLive(shifted.basis)).toBe(4);
    expect(shifted.upper[4] as number).toBe(4); // the unshifted value from bar 2
    expect(shifted.lower[4] as number).toBe(0);
    expect(shifted.basis[4] as number).toBe(2);
  });

  it('first prints at length - 1', () => {
    expect(firstLive(run(DONCHIAN, wave()).upper)).toBe(19);
  });
});

describe('Chande Kroll Stop', () => {
  // p = 2 gives atr = [na, 3.5, 3.25, 2.625] over true ranges 2, 5, 3, 2.
  // first_high_stop = highest(high, 2) - atr, first_low_stop = lowest(low, 2) + atr,
  // then each is run through a second 2-bar extreme.
  it('stacks a second extreme on the ATR-padded band', () => {
    const out = run(CHANDE_KROLL_STOP, jagged(), { p: 2, x: 1, q: 2 });
    expect(out.stopShort[2] as number).toBeCloseTo(11.75, 10);  // max(11.5, 11.75)
    expect(out.stopShort[3] as number).toBeCloseTo(11.75, 10);  // max(11.75, 11.375)
    expect(out.stopLong[2] as number).toBeCloseTo(12.5, 10);    // min(12.5, 14.25)
    expect(out.stopLong[3] as number).toBeCloseTo(13.625, 10);  // min(14.25, 13.625)
  });

  it('holds the stop through a pullback', () => {
    // The short stop above is flat across bars 2 and 3 even though the padded
    // band fell: that monotonicity is the whole point of the second pass.
    const out = run(CHANDE_KROLL_STOP, jagged(), { p: 2, x: 1, q: 2 });
    expect(out.stopShort[3]).toBe(out.stopShort[2]);
  });

  it('first prints at p + q - 2, the ATR warmup plus the second window', () => {
    expect(firstLive(run(CHANDE_KROLL_STOP, jagged(), { p: 2, x: 1, q: 2 }).stopLong)).toBe(2);
    expect(firstLive(run(CHANDE_KROLL_STOP, wave()).stopShort)).toBe(17); // 10 + 9 - 2
    expect(firstLive(run(CHANDE_KROLL_STOP, wave(), { p: 4, q: 3 }).stopShort)).toBe(5);
  });
});

describe('Chandelier Exit', () => {
  it('pads the window extremes by ATR multiples', () => {
    const out = run(CHANDELIER_EXIT, jagged(), { length: 2, atrLength: 2, atrMultiplier: 1 });
    expect(out.longExit[1] as number).toBeCloseTo(15 - 3.5, 10);
    expect(out.longExit[2] as number).toBeCloseTo(15 - 3.25, 10);
    expect(out.longExit[3] as number).toBeCloseTo(14 - 2.625, 10);
    expect(out.shortExit[1] as number).toBeCloseTo(9 + 3.5, 10);
    expect(out.shortExit[2] as number).toBeCloseTo(11 + 3.25, 10);
    expect(out.shortExit[3] as number).toBeCloseTo(11 + 2.625, 10);
  });

  it('collapses onto the raw extremes at a zero multiplier', () => {
    const data = wave();
    const out = run(CHANDELIER_EXIT, data, { atrMultiplier: 0 });
    const i = data.length - 1;
    const window = data.slice(i - 21, i + 1);
    expect(out.longExit[i] as number).toBeCloseTo(Math.max(...window.map((b) => b.high)), 10);
    expect(out.shortExit[i] as number).toBeCloseTo(Math.min(...window.map((b) => b.low)), 10);
  });

  it('first prints once both the window and the ATR have filled', () => {
    expect(firstLive(run(CHANDELIER_EXIT, wave()).longExit)).toBe(21);
    expect(firstLive(run(CHANDELIER_EXIT, wave(), { length: 5, atrLength: 30 }).longExit)).toBe(29);
    expect(firstLive(run(CHANDELIER_EXIT, wave(), { length: 30, atrLength: 5 }).shortExit)).toBe(29);
  });
});
