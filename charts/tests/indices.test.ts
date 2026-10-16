import { describe, it, expect } from 'vitest';
import {
  NVI,
  PVI,
  PVT,
  PVO,
  MASS_INDEX,
  ULCER_INDEX,
  INDEX_INDICATORS,
} from '../src/indicators/indices';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorValues } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bar = (i: number, close: number, volume: number, range = 1): Bar => ({
  time: 1700000000 + i * 60,
  open: close,
  high: close + range,
  low: close - range,
  close,
  volume,
});

const bars = (n: number, close: (i: number) => number, volume: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => bar(i, close(i), volume(i)));

/** Volume that both rises and falls, so the two indices each get live and flat bars. */
const zigVolume = (i: number): number => 100 + ((i * 37) % 23);

const wave = (n = 320): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05, zigVolume);

/** Same bars, no volume at all: the degenerate feed every descriptor must survive. */
const noVolume = (n = 320): Bar[] => wave(n).map((b) => ({ ...b, volume: 0 }));

const firstValue = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const defaults = (d: IndicatorDescriptor): Record<string, unknown> => indicatorDefaults(d);

describe('Negative Volume Index', () => {
  it('compounds the price change only on the bars where volume fell', () => {
    // Bar 1 has lighter volume, so the index takes the 10 percent gain; bar 2 is
    // heavier, so it holds. Base 1.0 scales to 1000.
    const seq = [bar(0, 100, 100), bar(1, 110, 50), bar(2, 99, 60)];
    const out = NVI.calc(seq, defaults(NVI), {});
    expect(out.nvi[0]).toBe(1000);
    expect(out.nvi[1]).toBeCloseTo(1100, 9);
    expect(out.nvi[2]).toBeCloseTo(1100, 9);
  });

  it('is flat across every bar where volume did not fall', () => {
    const data = wave();
    const out = NVI.calc(data, defaults(NVI), {});
    let flat = 0;
    for (let i = 1; i < data.length; i++) {
      if ((data[i].volume ?? 0) < (data[i - 1].volume ?? 0)) continue;
      expect(out.nvi[i], `bar ${i}`).toBe(out.nvi[i - 1]);
      flat += 1;
    }
    // The complement has to be non-trivial, or the assertion above proves nothing.
    expect(flat).toBeGreaterThan(50);
    expect(flat).toBeLessThan(data.length - 50);
  });

  it('never moves at all on a feed whose volume only rises', () => {
    const out = NVI.calc(bars(40, (i) => 100 + i, (i) => 100 + i), defaults(NVI), {});
    for (let i = 0; i < 40; i++) expect(out.nvi[i]).toBe(1000);
  });

  it('starts at index 0 and its EMA of 255 at index 254', () => {
    const out = NVI.calc(wave(), defaults(NVI), {});
    expect(firstValue(out.nvi)).toBe(0);
    expect(firstValue(out.ema)).toBe(254);
    expect(out.ema[253]).toBeNull();
  });
});

describe('Positive Volume Index', () => {
  it('compounds the price change only on the bars where volume rose', () => {
    // The mirror of the NVI case on the same bars: bar 1 holds, bar 2 takes the
    // move from 110 to 99.
    const seq = [bar(0, 100, 100), bar(1, 110, 50), bar(2, 99, 60)];
    const out = PVI.calc(seq, defaults(PVI), {});
    expect(out.pvi[0]).toBe(1000);
    expect(out.pvi[1]).toBeCloseTo(1000, 9);
    expect(out.pvi[2]).toBeCloseTo(900, 9);
  });

  it('is flat across every bar where volume did not rise', () => {
    const data = wave();
    const out = PVI.calc(data, defaults(PVI), {});
    let flat = 0;
    for (let i = 1; i < data.length; i++) {
      if ((data[i].volume ?? 0) > (data[i - 1].volume ?? 0)) continue;
      expect(out.pvi[i], `bar ${i}`).toBe(out.pvi[i - 1]);
      flat += 1;
    }
    expect(flat).toBeGreaterThan(50);
    expect(flat).toBeLessThan(data.length - 50);
  });

  it('takes every bar of a feed whose volume only rises', () => {
    const data = bars(40, (i) => 100 * 1.01 ** i, (i) => 100 + i);
    const out = PVI.calc(data, defaults(PVI), {});
    // Compounding one percent a bar from a base of 1000.
    for (let i = 0; i < 40; i++) expect(out.pvi[i] as number).toBeCloseTo(1000 * 1.01 ** i, 6);
  });

  it('starts at index 0 and its EMA of 255 at index 254', () => {
    const out = PVI.calc(wave(), defaults(PVI), {});
    expect(firstValue(out.pvi)).toBe(0);
    expect(firstValue(out.ema)).toBe(254);
    expect(out.ema[253]).toBeNull();
  });
});

describe('Price Volume Trend', () => {
  it('accumulates the percentage change times volume', () => {
    // +10% on 20 = +2, then -10% on 30 = -3, so the total goes 0, 2, -1.
    const seq = [bar(0, 100, 10), bar(1, 110, 20), bar(2, 99, 30)];
    const out = PVT.calc(seq, defaults(PVT), {});
    expect(out.pvt[0]).toBe(0);
    expect(out.pvt[1]).toBeCloseTo(2, 9);
    expect(out.pvt[2]).toBeCloseTo(-1, 9);
  });

  it('is 0 on a flat series no matter how much traded', () => {
    const out = PVT.calc(bars(40, () => 100, (i) => 1000 * (i + 1)), defaults(PVT), {});
    for (let i = 0; i < 40; i++) expect(out.pvt[i]).toBe(0);
  });

  it('starts at index 0, where the missing previous close contributes nothing', () => {
    const out = PVT.calc(wave(), defaults(PVT), {});
    expect(firstValue(out.pvt)).toBe(0);
  });
});

describe('Percentage Volume Oscillator', () => {
  it('expresses the fast/slow spread as a percentage of the slow average', () => {
    // SMA type, fast 1 and slow 2 over volumes 10, 20, 30. slow = na, 15, 25, so
    // the oscillator is 100*(20-15)/15 then 100*(30-25)/25.
    const seq = [bar(0, 100, 10), bar(1, 100, 20), bar(2, 100, 30)];
    const s = { ...defaults(PVO), fastLength: 1, slowLength: 2, signalLength: 1, oscType: 'SMA', sigType: 'SMA' };
    const out = PVO.calc(seq, s, {});
    expect(out.pvo[0]).toBeNull();
    expect(out.pvo[1]).toBeCloseTo((100 * 5) / 15, 9);
    expect(out.pvo[2]).toBeCloseTo((100 * 5) / 25, 9);
    // A signal average of length 1 is the oscillator itself, so the histogram
    // collapses to exactly zero.
    expect(out.hist[1]).toBeCloseTo(0, 12);
    expect(out.hist[2]).toBeCloseTo(0, 12);
  });

  it('is 0 when the fast and slow lengths match', () => {
    const data = wave(60);
    const out = PVO.calc(data, { ...defaults(PVO), fastLength: 5, slowLength: 5 }, {});
    for (let i = 4; i < 60; i++) expect(out.pvo[i]).toBeCloseTo(0, 12);
  });

  it('starts at index 25 with the signal and histogram at index 33', () => {
    const out = PVO.calc(wave(), defaults(PVO), {});
    expect(firstValue(out.pvo)).toBe(25);
    expect(out.pvo[24]).toBeNull();
    // The signal EMA of 9 seeds on the first full window of real oscillator
    // values, so it lands 8 bars after the oscillator does. Feeding the
    // oscillator's warmup gap straight to the recursion would blank it forever
    // instead, which is what this index pins down.
    expect(firstValue(out.signal)).toBe(33);
    expect(firstValue(out.hist)).toBe(33);
    expect(out.signal[32]).toBeNull();
  });

  it('gaps the whole plot on a feed the vendor sends no volume for', () => {
    const out = PVO.calc(noVolume(60), defaults(PVO), {});
    for (const key of ['pvo', 'signal', 'hist']) {
      for (const v of out[key]) expect(v).toBeNull();
    }
  });

  it('colours the histogram in four states by sign and direction', () => {
    const plot = PVO.plots.find((p) => p.key === 'hist');
    expect(plot?.colorBy).toBeTypeOf('function');
    const settings = defaults(PVO);
    const at = (hist: (number | null)[], index: number): string | undefined =>
      plot?.colorBy?.({ value: hist[index] as number, index, values: { hist } as IndicatorValues, settings });

    expect(at([1, 2], 1)).toBe('#26a69a'); // positive and building
    expect(at([2, 1], 1)).toBe('#b2dfdb'); // positive but fading
    expect(at([-2, -1], 1)).toBe('#ffcdd2'); // negative but recovering
    expect(at([-1, -2], 1)).toBe('#ff5252'); // negative and deepening
    // `hist[1]` is na on the first printed bar, so the reference `hist > hist[1]` is
    // false there and the series opens on a fading colour.
    expect(at([1], 0)).toBe('#b2dfdb');
    expect(at([-1], 0)).toBe('#ff5252');
  });

  it('declares the zero line the reference draws', () => {
    expect(PVO.levels?.(defaults(PVO))?.map((l) => l.price)).toContain(0);
  });
});

describe('Mass Index', () => {
  it('is exactly 10 when the range never changes', () => {
    // A constant span makes both EMAs equal to it, so the ratio is 1 and the
    // sum over the default 10 bars is 10.
    const data = Array.from({ length: 60 }, (_, i) => bar(i, 100 + i, 500, 2));
    const out = MASS_INDEX.calc(data, defaults(MASS_INDEX), {});
    for (let i = 25; i < 60; i++) expect(out.mi[i] as number).toBeCloseTo(10, 9);
  });

  it('matches an independent nested-EMA reference', () => {
    const data = wave(80);
    const out = MASS_INDEX.calc(data, defaults(MASS_INDEX), {});

    // Written from the formula, not from the implementation: seed each EMA with
    // the mean of its first nine real inputs, then run the recursion, and start
    // the inner one where the outer actually has values.
    const ema = (values: readonly number[], from: number, period: number): number[] => {
      const out2 = new Array<number>(values.length).fill(NaN);
      let acc = 0;
      for (let i = from; i < from + period; i++) acc += values[i];
      let prev = acc / period;
      out2[from + period - 1] = prev;
      const k = 2 / (period + 1);
      for (let i = from + period; i < values.length; i++) {
        prev = values[i] * k + prev * (1 - k);
        out2[i] = prev;
      }
      return out2;
    };

    const span = data.map((b) => b.high - b.low);
    const single = ema(span, 0, 9);
    const double = ema(single, 8, 9);
    for (let i = 25; i < 80; i++) {
      let acc = 0;
      for (let k = 0; k < 10; k++) acc += single[i - k] / double[i - k];
      expect(out.mi[i] as number, `bar ${i}`).toBeCloseTo(acc, 9);
    }
  });

  it('starts at index 25: two nine-bar EMAs plus the ten-bar sum', () => {
    const out = MASS_INDEX.calc(wave(), defaults(MASS_INDEX), {});
    expect(firstValue(out.mi)).toBe(25);
    expect(out.mi[24]).toBeNull();
  });
});

describe('Ulcer Index', () => {
  it('is exactly 0 on a monotonically rising series', () => {
    // Every bar is its own window high, so there is no drawdown to square.
    const out = ULCER_INDEX.calc(bars(60, (i) => 100 + i, () => 500), defaults(ULCER_INDEX), {});
    for (let i = 26; i < 60; i++) expect(out.ui[i]).toBe(0);
  });

  it('is the root mean square of the percentage drawdowns in the window', () => {
    // Length 2 over closes 100, 90, 80: the drawdowns from the rolling high are
    // -10 and -100/9 percent, and the reading is the RMS of the pair.
    const data = bars(3, (i) => 100 - 10 * i, () => 500);
    const out = ULCER_INDEX.calc(data, { ...defaults(ULCER_INDEX), length: 2 }, {});
    expect(out.ui[0]).toBeNull();
    expect(out.ui[1]).toBeNull();
    expect(out.ui[2] as number).toBeCloseTo(Math.sqrt((100 + (100 / 9) ** 2) / 2), 9);
  });

  it('starts at index 26: the drawdown warms up before the average of it does', () => {
    const out = ULCER_INDEX.calc(wave(), defaults(ULCER_INDEX), {});
    expect(firstValue(out.ui)).toBe(26);
    expect(out.ui[25]).toBeNull();
  });

  it('shades to a zero edge and declares a zero line', () => {
    expect(ULCER_INDEX.fills?.[0].between).toEqual(['ui', 'zero']);
    const out = ULCER_INDEX.calc(wave(60), defaults(ULCER_INDEX), {});
    expect(out.zero[25]).toBeNull();
    expect(out.zero[26]).toBe(0);
    expect(ULCER_INDEX.levels?.(defaults(ULCER_INDEX))?.map((l) => l.price)).toContain(0);
  });
});

describe('indices descriptors', () => {
  const data = wave();

  it('returns a full-length column of finite numbers or null for every plot', () => {
    for (const d of INDEX_INDICATORS) {
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
    for (const d of INDEX_INDICATORS) {
      const values = d.calc(flat, defaults(d), {});
      for (const plot of d.plots) {
        expect(values[plot.key].length, `${d.id}.${plot.key}`).toBe(flat.length);
        for (const v of values[plot.key]) {
          expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of INDEX_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = d.calc(input, defaults(d), {});
        for (const plot of d.plots) {
          expect(values[plot.key].length, `${d.id}.${plot.key}`).toBe(input.length);
          for (const v of values[plot.key]) {
            expect(v === null || Number.isFinite(v), `${d.id}.${plot.key} emitted ${v}`).toBe(true);
          }
        }
      }
    }
  });

  it('carries the six expected ids in picker order', () => {
    expect(INDEX_INDICATORS.map((d) => d.id)).toEqual([
      'nvi', 'pvi', 'pvt', 'pvo', 'mass-index', 'ulcer-index',
    ]);
  });

  it('groups the two volatility studies apart from the volume ones', () => {
    expect([NVI, PVI, PVT, PVO].map((d) => d.category)).toEqual(Array(4).fill('Volume'));
    expect([MASS_INDEX, ULCER_INDEX].map((d) => d.category)).toEqual(['Volatility', 'Volatility']);
    for (const d of INDEX_INDICATORS) expect(d.placement).toBe('pane');
  });

  it('points every plot colorKey at a declared color input', () => {
    for (const d of INDEX_INDICATORS) {
      for (const plot of d.plots) {
        const input = d.inputs.find((i) => i.key === plot.colorKey);
        expect(input, `${d.id}.${plot.key} colorKey ${plot.colorKey}`).toBeDefined();
        expect(input?.type).toBe('color');
      }
    }
  });
});

// Family-wide guards.
// The * modules land in this tier one at a time and are written by
// different hands, so these run over whichever of them exist. A static import of
// a module not written yet would take the whole suite down instead of skipping
// that one file, and the point of these guards is to catch a clash *between*
// siblings, which they can only do if a missing sibling is survivable. The glob
// resolves to the files that exist at transform time; a module that exists but is
// broken still appears here and still fails loudly.
const FAMILY = ['averages', 'strength', 'ranges', 'signals', 'indices'] as const;

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
    expect(present.map((m) => m.name)).toContain('indices');
    expect(absent.every((n) => FAMILY.includes(n as (typeof FAMILY)[number]))).toBe(true);
  });

  it('has no duplicate id across the whole family', () => {
    const ids = family.map((d) => d.id);
    expect(new Set(ids).size, `duplicate in ${ids.join(', ')}`).toBe(ids.length);
  });

  it('returns a full-length, never-NaN column for every declared plot', () => {
    for (const d of family) {
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
});
