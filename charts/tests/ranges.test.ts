import { describe, it, expect } from 'vitest';
import {
  STOCHASTIC_RSI,
  WILLIAMS_PERCENT_R,
  ULTIMATE_OSCILLATOR,
  RELATIVE_VIGOR_INDEX,
  RELATIVE_VOLATILITY_INDEX,
  WOODIES_CCI,
  SPECIAL_K,
  RANGE_INDICATORS,
} from '../src/indicators/ranges';
import { rsi } from '../src/indicators/rsi';
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
const rising = (n = 60): Bar[] => bars(n, (i) => 100 + i);
/** The mirror: every extreme is the oldest bar in the window. */
const falling = (n = 60): Bar[] => bars(n, (i) => 500 - i * 2);

const defaults = (d: IndicatorDescriptor) => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

/** A plain window scan, so the expectation never reuses the implementation's helpers. */
const windowSum = (values: readonly number[], at: number, period: number): number => {
  let acc = 0;
  for (let k = 0; k < period; k++) acc += values[at - k];
  return acc;
};

describe('TV3 oscillator catalogue', () => {
  it('exports the seven studies under their the reference platform ids', () => {
    expect(RANGE_INDICATORS.map((d) => d.id)).toEqual([
      'stochastic-rsi',
      'williams-percent-r',
      'ultimate-oscillator',
      'relative-vigor-index',
      'relative-volatility-index',
      'woodies-cci',
      'special-k',
    ]);
    expect(new Set(RANGE_INDICATORS.map((d) => d.id)).size).toBe(7);
    for (const d of RANGE_INDICATORS) expect(d.placement).toBe('pane');
  });

  it('points every plot at a declared colour input', () => {
    for (const d of RANGE_INDICATORS) {
      for (const plot of d.plots) {
        expect(plot.colorKey, `${d.id}.${plot.key} has no colorKey`).toBeTypeOf('string');
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.colorKey} is not a colour input`).toBe('color');
      }
    }
  });

  it('returns one full-length column of finite numbers or null per plot', () => {
    // Long enough that even Special K's signal line has values to check.
    const data = wave(1000);
    for (const d of RANGE_INDICATORS) {
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
    for (const d of RANGE_INDICATORS) {
      for (const input of [[], wave().slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });
});

describe('Stochastic RSI', () => {
  it('is the RSI stochastic smoothed twice, recomputed from the RSI series', () => {
    const data = wave();
    const out = run(STOCHASTIC_RSI, data);
    const r = rsi(data.map((b) => b.close), 14);
    const stochAt = (i: number): number => {
      let hi = -Infinity;
      let lo = Infinity;
      for (let k = 0; k < 14; k++) {
        hi = Math.max(hi, r[i - k]);
        lo = Math.min(lo, r[i - k]);
      }
      return (100 * (r[i] - lo)) / (hi - lo);
    };
    const kAt = (i: number): number => (stochAt(i) + stochAt(i - 1) + stochAt(i - 2)) / 3;
    expect(out.k[40] as number).toBeCloseTo(kAt(40), 10);
    expect(out.d[40] as number).toBeCloseTo((kAt(40) + kAt(39) + kAt(38)) / 3, 10);
  });

  it('stacks three warmups, so K starts at index 29 and D at 31', () => {
    const out = run(STOCHASTIC_RSI, wave());
    // 14 (RSI) + 13 (stochastic window of real RSI values) + 2 (K) = 29.
    expect(firstIndex(out.k)).toBe(29);
    expect(out.k[28]).toBeNull();
    expect(firstIndex(out.d)).toBe(31);
    expect(out.d[30]).toBeNull();
  });

  it('stays inside the 0..100 range it declares', () => {
    const out = run(STOCHASTIC_RSI, wave());
    let seen = 0;
    for (const v of out.k) {
      if (v === null) continue;
      seen += 1;
      // A stochastic pinned to the top of its own window can land one bit past
      // 100 in binary floating point. the reference divides the same way and overshoots
      // the same way, so the tolerance belongs here rather than a clamp in the
      // study, which would print a different number from the reference platform.
      expect(v).toBeGreaterThanOrEqual(-1e-9);
      expect(v).toBeLessThanOrEqual(100 + 1e-9);
    }
    expect(seen).toBeGreaterThan(100);
    expect(STOCHASTIC_RSI.range?.(defaults(STOCHASTIC_RSI))).toEqual({ min: 0, max: 100 });
  });

  it('gaps rather than dividing by zero when the RSI window is flat', () => {
    // A one-way market pins Wilder RSI at 100, so its own high equals its low.
    const out = run(STOCHASTIC_RSI, rising(80));
    expect(out.k.every((v) => v === null)).toBe(true);
  });

  it('draws the reference bands as levels', () => {
    expect(STOCHASTIC_RSI.levels?.(defaults(STOCHASTIC_RSI)).map((l) => l.price)).toEqual([80, 50, 20]);
  });
});

describe('Williams Percent Range', () => {
  it('is exactly 0 when the close makes the window high', () => {
    // close == high on every bar, and the series rises, so the close is the
    // highest high of the window: 100 * (src - max) / (max - min) is 0 / span.
    const data: Bar[] = Array.from({ length: 30 }, (_, i) => ({
      time: i, open: 100 + i, high: 100 + i, low: 95 + i, close: 100 + i, volume: 1,
    }));
    const out = run(WILLIAMS_PERCENT_R, data);
    expect(out.percentR[13]).toBe(0);
    expect(out.percentR[29]).toBe(0);
  });

  it('is exactly -100 when the close makes the window low', () => {
    const data: Bar[] = Array.from({ length: 30 }, (_, i) => ({
      time: i, open: 200 - i, high: 205 - i, low: 200 - i, close: 200 - i, volume: 1,
    }));
    const out = run(WILLIAMS_PERCENT_R, data);
    expect(out.percentR[13]).toBe(-100);
    expect(out.percentR[29]).toBe(-100);
  });

  it('reads the window from high/low and the numerator from the source input', () => {
    const data = wave();
    const out = run(WILLIAMS_PERCENT_R, data);
    const i = 50;
    let hi = -Infinity;
    let lo = Infinity;
    for (let k = 0; k < 14; k++) {
      hi = Math.max(hi, data[i - k].high);
      lo = Math.min(lo, data[i - k].low);
    }
    expect(out.percentR[i] as number).toBeCloseTo((100 * (data[i].close - hi)) / (hi - lo), 10);
  });

  it('needs a full window, so the first value is at index 13', () => {
    const out = run(WILLIAMS_PERCENT_R, wave());
    expect(firstIndex(out.percentR)).toBe(13);
    expect(out.percentR[12]).toBeNull();
  });

  it('runs -100..0, the mirror of a stochastic', () => {
    expect(WILLIAMS_PERCENT_R.range?.(defaults(WILLIAMS_PERCENT_R))).toEqual({ min: -100, max: 0 });
    expect(WILLIAMS_PERCENT_R.levels?.(defaults(WILLIAMS_PERCENT_R)).map((l) => l.price))
      .toEqual([-20, -50, -80]);
    for (const v of run(WILLIAMS_PERCENT_R, wave()).percentR) {
      if (v === null) continue;
      expect(v).toBeGreaterThanOrEqual(-100);
      expect(v).toBeLessThanOrEqual(0);
    }
  });
});

describe('Ultimate Oscillator', () => {
  it('collapses to a closed form when every bar has the same shape', () => {
    // Rising by 1 with high = close + 1 and low = close - 1: high_ = close + 1,
    // low_ = close[1] = close - 1, so bp = 1 and tr_ = 2 on every bar. All three
    // averages are 0.5, and 100 * (4 + 2 + 1) * 0.5 / 7 is exactly 50.
    expect(run(ULTIMATE_OSCILLATOR, rising()).uo[40]).toBe(50);
    // Falling by 2: high_ = close + 2, low_ = close - 1, bp = 1, tr_ = 3.
    expect(run(ULTIMATE_OSCILLATOR, falling()).uo[40] as number).toBeCloseTo(100 / 3, 12);
  });

  it('weights the three sums 4:2:1 over the previous close', () => {
    const data = wave();
    const bp: number[] = [];
    const tr: number[] = [];
    for (let i = 1; i < data.length; i++) {
      const prev = data[i - 1].close;
      const hi = Math.max(data[i].high, prev);
      const lo = Math.min(data[i].low, prev);
      bp.push(data[i].close - lo);
      tr.push(hi - lo);
    }
    const i = 60;
    const avg = (length: number): number =>
      windowSum(bp, i - 1, length) / windowSum(tr, i - 1, length);
    const expected = (100 * (4 * avg(7) + 2 * avg(14) + avg(28))) / 7;
    expect(run(ULTIMATE_OSCILLATOR, data).uo[i] as number).toBeCloseTo(expected, 10);
  });

  it('has no value on bar 0, so the 28-bar window first fills at index 28', () => {
    const out = run(ULTIMATE_OSCILLATOR, wave());
    expect(firstIndex(out.uo)).toBe(28);
    expect(out.uo[27]).toBeNull();
  });

  it('stays inside 0..100', () => {
    for (const v of run(ULTIMATE_OSCILLATOR, wave()).uo) {
      if (v === null) continue;
      expect(v).toBeGreaterThanOrEqual(0);
      expect(v).toBeLessThanOrEqual(100);
    }
  });
});

describe('Relative Vigor Index', () => {
  it('is exactly 1 when every bar opens at its low and closes at its high', () => {
    // close - open equals high - low bar for bar, so the two sums are the same
    // number and the ratio is 1 whatever the smoothing does.
    const data: Bar[] = Array.from({ length: 40 }, (_, i) => ({
      time: i, open: 100 + i, high: 101 + i + (i % 3), low: 100 + i, close: 101 + i + (i % 3), volume: 1,
    }));
    const out = run(RELATIVE_VIGOR_INDEX, data);
    expect(out.rvgi[20] as number).toBeCloseTo(1, 12);
    expect(out.signal[20] as number).toBeCloseTo(1, 12);
  });

  it('is the summed 1/2/2/1 body over the summed 1/2/2/1 range', () => {
    const data = wave();
    const kernel = (pick: (b: Bar) => number, at: number): number =>
      (pick(data[at - 3]) + 2 * pick(data[at - 2]) + 2 * pick(data[at - 1]) + pick(data[at])) / 6;
    const body: number[] = [];
    const range: number[] = [];
    for (let i = 3; i < data.length; i++) {
      body.push(kernel((b) => b.close - b.open, i));
      range.push(kernel((b) => b.high - b.low, i));
    }
    const i = 40;
    const expected = windowSum(body, i - 3, 10) / windowSum(range, i - 3, 10);
    const out = run(RELATIVE_VIGOR_INDEX, data);
    expect(out.rvgi[i] as number).toBeCloseTo(expected, 10);
  });

  it('starts at index 12 and signals three bars later', () => {
    const out = run(RELATIVE_VIGOR_INDEX, wave());
    // 3 bars for the swma, 10 more for the sum.
    expect(firstIndex(out.rvgi)).toBe(12);
    expect(out.rvgi[11]).toBeNull();
    expect(firstIndex(out.signal)).toBe(15);
  });

  it('implements the reference offset as a real shift of both columns', () => {
    const data = wave(60);
    const base = run(RELATIVE_VIGOR_INDEX, data);
    const right = run(RELATIVE_VIGOR_INDEX, data, { offset: 3 });
    expect(right.rvgi.slice(3)).toEqual(base.rvgi.slice(0, data.length - 3));
    expect(right.signal.slice(3)).toEqual(base.signal.slice(0, data.length - 3));
    expect(right.rvgi.slice(0, 3)).toEqual([null, null, null]);
    const left = run(RELATIVE_VIGOR_INDEX, data, { offset: -3 });
    expect(left.rvgi.slice(0, data.length - 3)).toEqual(base.rvgi.slice(3));
    expect(left.rvgi.slice(-3)).toEqual([null, null, null]);
    expect(left.rvgi.length).toBe(data.length);
  });

  it('gaps rather than dividing by zero when every bar is a doji', () => {
    const flat: Bar[] = Array.from({ length: 30 }, (_, i) => ({
      time: i, open: 100, high: 100, low: 100, close: 100, volume: 1,
    }));
    expect(run(RELATIVE_VIGOR_INDEX, flat).rvgi.every((v) => v === null)).toBe(true);
  });
});

describe('Relative Volatility Index', () => {
  it('is exactly 100 when every bar is an up bar and 0 when every bar is a down bar', () => {
    // All of the standard deviation lands on one side, so upper / (upper + 0) is
    // 1 to the last bit.
    expect(run(RELATIVE_VOLATILITY_INDEX, rising()).rvi[40]).toBe(100);
    expect(run(RELATIVE_VOLATILITY_INDEX, falling()).rvi[40]).toBe(0);
  });

  it('smooths with a hard-coded 14 rather than with the length input', () => {
    // The standard deviation is `na` for its first length - 1 bars, so the EMA's
    // seed needs a clean 14-bar window: the first print is (length - 1) + 13.
    // Were the EMA wired to the input it would be (length - 1) + (length - 1).
    expect(firstIndex(run(RELATIVE_VOLATILITY_INDEX, rising()).rvi)).toBe(22);
    expect(firstIndex(run(RELATIVE_VOLATILITY_INDEX, rising(), { length: 5 }).rvi)).toBe(17);
    expect(firstIndex(run(RELATIVE_VOLATILITY_INDEX, rising(80), { length: 20 }).rvi)).toBe(32);
  });

  it('smooths the study itself with a 14-bar SMA by default', () => {
    const out = run(RELATIVE_VOLATILITY_INDEX, rising());
    expect(firstIndex(out.ma)).toBe(35); // 22 + 13
    // A constant study has a constant average.
    expect(out.ma[40]).toBe(100);
    expect(out.bbUpper.every((v) => v === null)).toBe(true);
    expect(out.bbLower.every((v) => v === null)).toBe(true);
  });

  it('drops the smoothing line entirely when the type is None', () => {
    const out = run(RELATIVE_VOLATILITY_INDEX, wave(), { maType: 'None' });
    expect(out.ma.every((v) => v === null)).toBe(true);
    expect(out.bbUpper.every((v) => v === null)).toBe(true);
    expect(firstIndex(out.rvi)).toBeGreaterThan(0);
  });

  it('adds symmetric Bollinger bands only for the SMA + Bollinger Bands type', () => {
    const data = wave();
    const out = run(RELATIVE_VOLATILITY_INDEX, data, { maType: 'SMA + Bollinger Bands' });
    const at = firstIndex(out.bbUpper);
    expect(at).toBe(firstIndex(out.ma));
    const ma = out.ma[at + 5] as number;
    const upper = out.bbUpper[at + 5] as number;
    const lower = out.bbLower[at + 5] as number;
    expect(upper - ma).toBeCloseTo(ma - lower, 10);
    expect(upper).toBeGreaterThan(ma);
    // Twice the multiplier times the deviation, recomputed from the study.
    const mean = windowSum(out.rvi.map((v) => v as number), at + 5, 14) / 14;
    let acc = 0;
    for (let k = 0; k < 14; k++) {
      const d = (out.rvi[at + 5 - k] as number) - mean;
      acc += d * d;
    }
    expect(upper - lower).toBeCloseTo(2 * 2 * Math.sqrt(acc / 14), 8);
  });

  it('draws the reference bands as levels', () => {
    const s = defaults(RELATIVE_VOLATILITY_INDEX);
    expect(RELATIVE_VOLATILITY_INDEX.levels?.(s).map((l) => l.price)).toEqual([80, 50, 20]);
    expect(s.maLength).toBe(14);
    expect(s.bbMult).toBe(2);
    expect(s.length).toBe(10);
  });

  it('shifts only the study when the offset is set, matching the reference plots', () => {
    const data = wave(60);
    const base = run(RELATIVE_VOLATILITY_INDEX, data);
    const out = run(RELATIVE_VOLATILITY_INDEX, data, { offset: 4 });
    expect(out.rvi.slice(4)).toEqual(base.rvi.slice(0, data.length - 4));
    expect(out.ma).toEqual(base.ma);
  });
});

describe('Woodies CCI', () => {
  it('plots the same CCI 14 series as both the histogram and the line', () => {
    const out = run(WOODIES_CCI, wave());
    expect(out.hist).toEqual(out.cci14);
  });

  it('is the mean absolute deviation CCI of the close', () => {
    const data = wave();
    const closes = data.map((b) => b.close);
    const i = 40;
    const mean = windowSum(closes, i, 14) / 14;
    let mad = 0;
    for (let k = 0; k < 14; k++) mad += Math.abs(closes[i - k] - mean);
    const expected = (closes[i] - mean) / (0.015 * (mad / 14));
    expect(run(WOODIES_CCI, data).cci14[i] as number).toBeCloseTo(expected, 10);
  });

  it('starts the turbo line at index 5 and CCI 14 at index 13', () => {
    const out = run(WOODIES_CCI, wave());
    expect(firstIndex(out.turbo)).toBe(5);
    expect(firstIndex(out.cci14)).toBe(13);
    expect(out.cci14[12]).toBeNull();
  });

  it('colours the histogram by the previous five bars, then by sign', () => {
    const plot = WOODIES_CCI.plots.find((p) => p.key === 'hist');
    expect(plot?.colorBy).toBeTypeOf('function');
    const settings = defaults(WOODIES_CCI);
    const at = (hist: (number | null)[]): string | undefined =>
      plot?.colorBy?.({
        value: hist[hist.length - 1] as number,
        index: hist.length - 1,
        values: { hist },
        settings,
      });
    expect(at([10, 20, 30, 40, 50, -5])).toBe(settings.upColor);
    expect(at([-10, -20, -30, -40, -50, 5])).toBe(settings.downColor);
    // No established run: the built-in's fallback is the inverted one, teal for
    // a negative reading and red for a positive one.
    expect(at([10, -20, 30, -40, 50, -5])).toBe(settings.upColor);
    expect(at([10, -20, 30, -40, 50, 5])).toBe(settings.downColor);
    // A zero in the run breaks it: the reference comparisons are strict.
    expect(at([10, 20, 0, 40, 50, 5])).toBe(settings.downColor);
    // Warmup nulls are neither above nor below zero, so no run is established.
    expect(at([null, null, null, null, null, -5])).toBe(settings.upColor);
  });

  it('draws the zero line and both hundred lines', () => {
    expect(WOODIES_CCI.levels?.(defaults(WOODIES_CCI)).map((l) => l.price)).toEqual([100, 0, -100]);
  });
});

describe("Pring's Special K", () => {
  it('is the weighted sum of twelve smoothed rates of change', () => {
    // A geometric series makes every roc term a constant, and an SMA of a
    // constant is that constant, so the whole study has a closed form.
    const r = 1.001;
    const data = bars(1200, (i) => 100 * Math.pow(r, i));
    const terms: readonly [number, number][] = [
      [1, 10], [2, 15], [3, 20], [4, 30],
      [1, 40], [2, 65], [3, 75], [4, 100],
      [1, 195], [2, 265], [3, 390], [4, 530],
    ];
    let expected = 0;
    for (const [weight, length] of terms) expected += weight * 100 * (Math.pow(r, length) - 1);
    const out = run(SPECIAL_K, data);
    expect(out.specialK[1000] as number).toBeCloseTo(expected, 6);
    // The signal is two SMAs of a constant, so it lands on the same number.
    expect(out.signal[1000] as number).toBeCloseTo(expected, 6);
  });

  it('waits for the 530/195 term, so Special K starts at 724 and the signal at 922', () => {
    const out = run(SPECIAL_K, wave(1200));
    expect(firstIndex(out.specialK)).toBe(724); // 530 + 195 - 1
    expect(out.specialK[723]).toBeNull();
    expect(firstIndex(out.signal)).toBe(922); // 724 + 99 + 99
    expect(out.signal[921]).toBeNull();
  });

  it('prints nothing at all on a chart shorter than its longest term', () => {
    const out = run(SPECIAL_K, wave(300));
    expect(out.specialK.every((v) => v === null)).toBe(true);
    expect(out.signal.every((v) => v === null)).toBe(true);
  });

  it('draws the zero line', () => {
    expect(SPECIAL_K.levels?.(defaults(SPECIAL_K)).map((l) => l.price)).toEqual([0]);
    expect(defaults(SPECIAL_K).length1).toBe(100);
    expect(defaults(SPECIAL_K).length2).toBe(100);
  });
});

describe('reference-line background bands', () => {
  const data = wave();

  it('never names a fill edge calc does not return, on any study in the module', () => {
    // A fill pointing at a missing column renders nothing and throws nothing,
    // so the edges are checked against calc's output rather than the plots.
    for (const d of RANGE_INDICATORS) {
      const out = run(d, data);
      for (const fill of d.fills ?? []) {
        for (const key of fill.between) expect(out[key], `${d.id} fill edge ${key}`).toBeDefined();
      }
    }
  });

  it('shades Stochastic RSI between a constant 80 and 20, the warmup included', () => {
    expect(STOCHASTIC_RSI.fills).toHaveLength(1);
    expect(STOCHASTIC_RSI.fills?.[0].between).toEqual(['bandHigh', 'bandLow']);
    const out = run(STOCHASTIC_RSI, data);
    expect(out.bandHigh).toHaveLength(data.length);
    expect(out.bandHigh.every((v) => v === 80)).toBe(true);
    expect(out.bandLow.every((v) => v === 20)).toBe(true);
    // Bar 28 is a bar short of the first K: no line, but a shaded pane.
    expect(out.k[28]).toBeNull();
    expect(out.bandHigh[28]).toBe(80);
    expect(firstIndex(out.k)).toBe(29);
  });

  it('shades Williams %R between a constant -20 and -80, the warmup included', () => {
    expect(WILLIAMS_PERCENT_R.fills).toHaveLength(1);
    expect(WILLIAMS_PERCENT_R.fills?.[0].between).toEqual(['bandHigh', 'bandLow']);
    const out = run(WILLIAMS_PERCENT_R, data);
    expect(out.bandHigh.every((v) => v === -20)).toBe(true);
    expect(out.bandLow.every((v) => v === -80)).toBe(true);
    expect(out.percentR[12]).toBeNull();
    expect(out.bandLow[12]).toBe(-80);
    expect(firstIndex(out.percentR)).toBe(13);
  });

  it('adds the 80/20 band to RVI without disturbing its Bollinger fill', () => {
    expect(RELATIVE_VOLATILITY_INDEX.fills).toHaveLength(2);
    expect(RELATIVE_VOLATILITY_INDEX.fills?.[0].between).toEqual(['bbUpper', 'bbLower']);
    expect(RELATIVE_VOLATILITY_INDEX.fills?.[1].between).toEqual(['bandHigh', 'bandLow']);
    const out = run(RELATIVE_VOLATILITY_INDEX, rising());
    expect(out.bandHigh.every((v) => v === 80)).toBe(true);
    expect(out.bandLow.every((v) => v === 20)).toBe(true);
    expect(out.rvi[40]).toBe(100);
    // The offset moves the study; a reference line stays where it is.
    expect(run(RELATIVE_VOLATILITY_INDEX, rising(), { offset: 4 }).bandHigh).toEqual(out.bandHigh);
  });

  it('paints every band through a declared colour input at the source opacity', () => {
    const cases = [
      { d: STOCHASTIC_RSI, at: 0, color: '#2196f3' },
      { d: WILLIAMS_PERCENT_R, at: 0, color: '#7e57c2' },
      { d: RELATIVE_VOLATILITY_INDEX, at: 1, color: '#7e57c2' },
    ];
    for (const { d, at, color } of cases) {
      const fill = (d.fills ?? [])[at];
      expect(fill.colorUpKey, d.id).toBe('fillColor');
      expect(fill.colorDownKey, d.id).toBe('fillColor');
      expect(fill.opacity, d.id).toBe(0.1);
      const declared = d.inputs.find((i) => i.key === 'fillColor');
      expect(declared?.type, d.id).toBe('color');
      expect(declared?.default, d.id).toBe(color);
    }
  });

  it('emits the band columns on empty and single-bar input too', () => {
    for (const d of [STOCHASTIC_RSI, WILLIAMS_PERCENT_R, RELATIVE_VOLATILITY_INDEX]) {
      expect(run(d, []).bandHigh, d.id).toEqual([]);
      expect(run(d, data.slice(0, 1)).bandLow, d.id).toHaveLength(1);
    }
  });
});
