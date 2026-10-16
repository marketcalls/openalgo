import { describe, it, expect } from 'vitest';
import {
  CHAIKIN_MONEY_FLOW,
  CHAIKIN_OSCILLATOR,
  EASE_OF_MOVEMENT,
  ELDER_FORCE_INDEX,
  FLOW_INDICATORS,
} from '../src/indicators/flow';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n = 120): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

/** Every bar the same fixed range, closing at one end of it. */
const closesAt = (n: number, end: 'high' | 'low'): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1700000000 + i * 60,
    open: 100,
    high: 102,
    low: 98,
    close: end === 'high' ? 102 : 98,
    volume: 10 + i,
  }));

/** Same bars, no volume at all: the degenerate feed every descriptor must survive. */
const noVolume = (n = 60): Bar[] => wave(n).map((b) => ({ ...b, volume: 0 }));

const firstValue = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const defaults = (d: IndicatorDescriptor): Record<string, unknown> => indicatorDefaults(d);

describe('Chaikin Money Flow', () => {
  it('is exactly +1 when every bar closes at its high and -1 at its low', () => {
    const up = CHAIKIN_MONEY_FLOW.calc(closesAt(40, 'high'), defaults(CHAIKIN_MONEY_FLOW), {});
    const down = CHAIKIN_MONEY_FLOW.calc(closesAt(40, 'low'), defaults(CHAIKIN_MONEY_FLOW), {});
    expect(up.cmf[39]).toBe(1);
    expect(down.cmf[39]).toBe(-1);
  });

  it('weights the window by traded volume', () => {
    // ad = +10 then -30, volume 40 in the window: (10 - 30) / 40 = -0.5.
    const seq: Bar[] = [
      { time: 1, open: 100, high: 102, low: 98, close: 102, volume: 10 },
      { time: 2, open: 100, high: 102, low: 98, close: 98, volume: 30 },
    ];
    expect(CHAIKIN_MONEY_FLOW.calc(seq, { length: 2 }, {}).cmf[1]).toBeCloseTo(-0.5, 12);
  });

  it('contributes 0 for a bar with no range instead of blanking the series', () => {
    const seq: Bar[] = [
      { time: 1, open: 100, high: 100, low: 100, close: 100, volume: 10 }, // doji
      { time: 2, open: 100, high: 102, low: 98, close: 102, volume: 10 },
    ];
    expect(CHAIKIN_MONEY_FLOW.calc(seq, { length: 2 }, {}).cmf[1]).toBeCloseTo(0.5, 12);
  });

  it('starts at index 19 on the default length of 20', () => {
    const out = CHAIKIN_MONEY_FLOW.calc(wave(), defaults(CHAIKIN_MONEY_FLOW), {});
    expect(firstValue(out.cmf)).toBe(19);
    expect(out.cmf[18]).toBeNull();
  });
});

describe('Chaikin Oscillator', () => {
  it('differences two EMAs of the running A/D total', () => {
    // accdist = 10, 20, 10. Fast(1) tracks it exactly; slow(2) seeds at the
    // mean of the first pair, 15, then 10*(2/3) + 15*(1/3).
    const seq: Bar[] = [
      { time: 1, open: 100, high: 102, low: 98, close: 102, volume: 10 },
      { time: 2, open: 100, high: 102, low: 98, close: 102, volume: 10 },
      { time: 3, open: 100, high: 102, low: 98, close: 98, volume: 10 },
    ];
    const out = CHAIKIN_OSCILLATOR.calc(seq, { short: 1, long: 2 }, {});
    expect(out.osc[0]).toBeNull();
    expect(out.osc[1]).toBeCloseTo(5, 12);
    expect(out.osc[2]).toBeCloseTo(10 - (10 * (2 / 3) + 15 * (1 / 3)), 12);
  });

  it('starts at index 9, where the slow EMA of 10 seeds', () => {
    const out = CHAIKIN_OSCILLATOR.calc(wave(), defaults(CHAIKIN_OSCILLATOR), {});
    expect(firstValue(out.osc)).toBe(9);
    expect(out.osc[8]).toBeNull();
  });
});

describe('Ease of Movement', () => {
  it('scales the midpoint move by range over volume', () => {
    // 10000 * (102 - 100) * (104 - 100) / 10 = 8000.
    const seq: Bar[] = [
      { time: 1, open: 100, high: 102, low: 98, close: 100, volume: 10 },
      { time: 2, open: 102, high: 104, low: 100, close: 102, volume: 10 },
    ];
    const out = EASE_OF_MOVEMENT.calc(seq, { length: 1, divisor: 10000 }, {});
    expect(out.eom[0]).toBeNull();
    expect(out.eom[1]).toBeCloseTo(8000, 9);
  });

  it('starts at index 14: the change on bar 0 is a gap the average will not cross', () => {
    const out = EASE_OF_MOVEMENT.calc(wave(), defaults(EASE_OF_MOVEMENT), {});
    expect(firstValue(out.eom)).toBe(14);
    expect(out.eom[13]).toBeNull();
  });

  it('gaps for a full window after a zero-volume bar rather than emitting Infinity', () => {
    const data = wave(40);
    data[20] = { ...data[20], volume: 0 };
    const out = EASE_OF_MOVEMENT.calc(data, defaults(EASE_OF_MOVEMENT), {});
    for (let i = 20; i < 34; i++) expect(out.eom[i]).toBeNull();
    expect(out.eom[34]).not.toBeNull();
  });
});

describe('Elder Force Index', () => {
  it('is 0 on a flat series', () => {
    const out = ELDER_FORCE_INDEX.calc(bars(40, () => 100), defaults(ELDER_FORCE_INDEX), {});
    for (let i = 13; i < 40; i++) expect(out.efi[i]).toBe(0);
  });

  it('is the close change times volume before smoothing', () => {
    const seq: Bar[] = [
      { time: 1, open: 100, high: 101, low: 99, close: 100, volume: 10 },
      { time: 2, open: 100, high: 106, low: 100, close: 105, volume: 10 },
    ];
    const out = ELDER_FORCE_INDEX.calc(seq, { length: 1 }, {});
    expect(out.efi[0]).toBeNull();
    expect(out.efi[1]).toBeCloseTo(50, 12);
  });

  it('starts at index 13, one bar later than a gapless EMA of 13 would', () => {
    const out = ELDER_FORCE_INDEX.calc(wave(), defaults(ELDER_FORCE_INDEX), {});
    expect(firstValue(out.efi)).toBe(13);
    expect(out.efi[12]).toBeNull();
  });
});

describe('flow descriptors', () => {
  const data = wave();

  it('returns a full-length column of finite numbers or null for every plot', () => {
    for (const d of FLOW_INDICATORS) {
      const values = d.calc(data, defaults(d), {});
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

  it('survives a feed with no volume at all', () => {
    const flat = noVolume();
    for (const d of FLOW_INDICATORS) {
      const values = d.calc(flat, defaults(d), {});
      for (const plot of d.plots) {
        expect(values[plot.key].length).toBe(flat.length);
        for (const v of values[plot.key]) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('declares a zero line wherever the reference source draws one', () => {
    for (const d of [CHAIKIN_MONEY_FLOW, CHAIKIN_OSCILLATOR, ELDER_FORCE_INDEX]) {
      expect(d.levels?.(defaults(d))?.map((l) => l.price)).toContain(0);
    }
    expect(EASE_OF_MOVEMENT.levels).toBeUndefined();
  });
});

// ── Family-wide guards ────────────────────────────────────────────────────
// The * modules land in this tier one at a time and are written by
// different hands, so these run over whichever of them exist. A static import
// of a module not written yet would take the whole suite down instead of
// skipping that one file, and the point of these guards is to catch a clash
// *between* siblings: they can only do that if a missing sibling is
// survivable. The glob resolves to the files that exist at transform time; a
// module that exists but is broken still appears here and still fails loudly.
const FAMILY = ['overlay', 'oscillators', 'volatility', 'flow'] as const;

type GlobbedModules = Record<string, () => Promise<Record<string, unknown>>>;
const found = (import.meta as unknown as { glob(pattern: string): GlobbedModules })
  .glob('../src/indicators/*.ts');

const present: { name: string; descriptors: readonly IndicatorDescriptor[] }[] = [];
const absent: string[] = [];

for (const name of FAMILY) {
  const path = Object.keys(found).find((p) => p.endsWith(`/${name}.ts`));
  if (path === undefined) {
    absent.push(name);
    continue;
  }
  const mod = await found[path]();
  const descriptors = Object.entries(mod)
    .filter(([key, value]) => key.endsWith('_INDICATORS') && Array.isArray(value))
    .flatMap(([, value]) => value as IndicatorDescriptor[]);
  present.push({ name, descriptors });
}

const family: readonly IndicatorDescriptor[] = present.flatMap((m) => m.descriptors);

describe('indicator family guards', () => {
  const data = wave();

  it('loads this module at least, and reports which siblings are missing', () => {
    expect(present.map((m) => m.name)).toContain('flow');
    expect(absent.every((n) => FAMILY.includes(n as (typeof FAMILY)[number]))).toBe(true);
  });

  it('has no duplicate id across the whole family', () => {
    const ids = family.map((d) => d.id);
    expect(new Set(ids).size, `duplicate in ${ids.join(', ')}`).toBe(ids.length);
  });

  it('returns a full-length column for every declared plot', () => {
    for (const d of family) {
      const values = d.calc(data, defaults(d), {});
      for (const plot of d.plots) {
        const col = values[plot.key];
        expect(col, `${d.id}.${plot.key} missing`).toBeDefined();
        expect(col.length, `${d.id}.${plot.key} length`).toBe(data.length);
      }
    }
  });

  it('never emits NaN', () => {
    for (const d of family) {
      const values = d.calc(data, defaults(d), {});
      for (const plot of d.plots) {
        for (const v of values[plot.key]) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of family) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = d.calc(input, defaults(d), {});
        for (const plot of d.plots) {
          expect(values[plot.key].length, `${d.id}.${plot.key}`).toBe(input.length);
        }
      }
    }
  });

  it('points every plot colorKey at an input that exists', () => {
    for (const d of family) {
      for (const plot of d.plots) {
        if (plot.colorKey === undefined) continue;
        const input = d.inputs.find((i) => i.key === plot.colorKey);
        expect(input, `${d.id}.${plot.key} colorKey ${plot.colorKey}`).toBeDefined();
        expect(input?.type).toBe('color');
      }
    }
  });
});
