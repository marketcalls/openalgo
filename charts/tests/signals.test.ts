import { describe, it, expect } from 'vitest';
import {
  VORTEX,
  VOLATILITY_STOP,
  TREND_STRENGTH_INDEX,
  WILLIAMS_FRACTALS,
  RSI_DIVERGENCE,
  SIGNAL_INDICATORS,
} from '../src/indicators/signals';
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
/** The mirror, stepping twice as fast so the true range is asymmetric. */
const falling = (n = 40): Bar[] => bars(n, (i) => 200 - i * 2);
/** Swings whose amplitude drifts, so successive pivots disagree with price. */
const swings = (n = 400): Bar[] =>
  bars(n, (i) => 100 + Math.sin(i / 9) * 9 + Math.cos(i / 4) * 4 + Math.sin(i / 29) * 6);
/** Swings under a downward drift, which is what a hidden bearish pair needs. */
const sinking = (n = 200): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 - i * 0.05);

const defaults = (d: IndicatorDescriptor) => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});
const markersOf = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) => {
  const settings = { ...defaults(d), ...over };
  return d.markers?.({ bars: data, values: d.calc(data, settings, {}), settings }) ?? [];
};
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);
const count = (col: readonly (number | null)[]): number => col.filter((v) => v !== null).length;
const hits = (col: readonly (number | null)[]): number[] =>
  col.reduce<number[]>((acc, v, i) => (v === null ? acc : [...acc, i]), []);

describe('Signal indicator catalogue', () => {
  it('exports the six studies under their catalogue ids', () => {
    expect(SIGNAL_INDICATORS.map((d) => d.id)).toEqual([
      'vortex',
      'volatility-stop',
      'trend-strength-index',
      'williams-fractals',
      'rsi-divergence',
      'consolidation-breakout',
    ]);
    expect(new Set(SIGNAL_INDICATORS.map((d) => d.id)).size).toBe(6);
  });

  it('places the overlays on the price pane and the studies in their own', () => {
    expect(VORTEX.placement).toBe('pane');
    expect(VOLATILITY_STOP.placement).toBe('onchart');
    expect(TREND_STRENGTH_INDEX.placement).toBe('pane');
    expect(WILLIAMS_FRACTALS.placement).toBe('onchart');
    expect(RSI_DIVERGENCE.placement).toBe('pane');
  });

  it('points every plot at a declared colour input', () => {
    for (const d of SIGNAL_INDICATORS) {
      for (const plot of d.plots) {
        expect(plot.colorKey, `${d.id}.${plot.key} has no colorKey`).toBeTypeOf('string');
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.colorKey} is not a colour input`).toBe('color');
      }
    }
  });

  it('returns one full-length column of finite numbers or null per plot', () => {
    const data = wave();
    for (const d of SIGNAL_INDICATORS) {
      const values = run(d, data);
      for (const plot of d.plots) {
        expect(values[plot.key], `${d.id}.${plot.key} missing`).toBeDefined();
        expect(values[plot.key].length, `${d.id}.${plot.key} length`).toBe(data.length);
      }
      // The signal columns carry no plot of their own but feed the marker layer,
      // and they obey the same contract.
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${d.id}.${key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input, markers included', () => {
    for (const d of SIGNAL_INDICATORS) {
      for (const input of [[], wave().slice(0, 1)]) {
        const values = run(d, input);
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
        expect(markersOf(d, input)).toEqual([]);
      }
    }
  });
});

describe('Vortex Indicator', () => {
  it('divides each direction of movement by the window travel', () => {
    const data = wave(60);
    const length = 6;
    const at = 30;
    const out = run(VORTEX, data, { length });
    // Recomputed from the definition: sum |high - low[1]| and sum |low - high[1]|
    // over the window, both against the summed true range.
    let vmp = 0;
    let vmm = 0;
    let travel = 0;
    for (let k = 0; k < length; k++) {
      const i = at - k;
      vmp += Math.abs(data[i].high - data[i - 1].low);
      vmm += Math.abs(data[i].low - data[i - 1].high);
      travel += Math.max(
        data[i].high - data[i].low,
        Math.abs(data[i].high - data[i - 1].close),
        Math.abs(data[i].low - data[i - 1].close),
      );
    }
    expect(out.vip[at]).toBeCloseTo(vmp / travel, 12);
    expect(out.vim[at]).toBeCloseTo(vmm / travel, 12);
  });

  it('reads 1.5 up against 0.5 down on a one-point-per-bar rise', () => {
    // Every bar: |high - low[1]| = 3, |low - high[1]| = 1, true range = 2.
    const out = run(VORTEX, rising());
    expect(out.vip[20]).toBe(1.5);
    expect(out.vim[20]).toBe(0.5);
  });

  it('inverts on the fall: no upward movement, and every point of travel downward', () => {
    // Two points per bar down: |high - low[1]| = 0, |low - high[1]| = 4, TR = 3.
    const out = run(VORTEX, falling());
    expect(out.vip[20]).toBe(0);
    expect(out.vim[20]).toBeCloseTo(4 / 3, 12);
    // The rise says the opposite, which is the whole point of the pair.
    const up = run(VORTEX, rising());
    expect(up.vip[20]!).toBeGreaterThan(up.vim[20]!);
    expect(out.vip[20]!).toBeLessThan(out.vim[20]!);
  });

  it('keeps both lines non-negative, and both live on a two-sided series', () => {
    const out = run(VORTEX, wave());
    for (let i = 0; i < 200; i++) {
      if (out.vip[i] === null) continue;
      expect(out.vip[i]!).toBeGreaterThan(0);
      expect(out.vim[i]!).toBeGreaterThan(0);
    }
  });

  it('starts at index length, one bar later than the denominator', () => {
    // Bar 0 has no previous bar, so its movement term is na and every window
    // containing it is na too: the numerator needs `length` bars after bar 0.
    const out = run(VORTEX, wave());
    expect(firstIndex(out.vip)).toBe(14);
    expect(firstIndex(out.vim)).toBe(14);
    expect(out.vip[13]).toBeNull();
    expect(firstIndex(run(VORTEX, wave(), { length: 6 }).vip)).toBe(6);
  });
});

describe('Volatility Stop', () => {
  it('prints a stop from the very first bar, seeded at the source', () => {
    const data = rising();
    const out = run(VOLATILITY_STOP, data);
    expect(firstIndex(out.up)).toBe(0);
    expect(out.up[0]).toBe(data[0].close);
  });

  it('falls back to the bare true range, not range times multiplier, while the ATR warms', () => {
    // Rising by one with a two-point range: the stop is max(prev, close - 2).
    // Were the multiplier applied to the fallback it would be close - 4, and
    // bar 3 would still read 100 instead of 101.
    const data = rising();
    const out = run(VOLATILITY_STOP, data, { length: 20, factor: 2 });
    expect(out.up.slice(0, 3)).toEqual([100, 100, 100]);
    for (let i = 3; i <= 18; i++) expect(out.up[i], `bar ${i}`).toBe(data[i].close - 2);
  });

  it('never moves the stop down while the uptrend holds', () => {
    const out = run(VOLATILITY_STOP, wave());
    let prev: number | null = null;
    for (const v of out.up) {
      if (v === null) { prev = null; continue; } // the trend ended; the next run restarts
      if (prev !== null) expect(v).toBeGreaterThanOrEqual(prev - 1e-9);
      prev = v;
    }
  });

  it('flips on the first bar that closes through the stop and ratchets down after', () => {
    const data = falling();
    const out = run(VOLATILITY_STOP, data, { length: 20 });
    // Bar 0 seeds long at 200; bar 1 closes 2 below it, so the trend flips and
    // the stop restarts a true range above the new minimum.
    expect(out.up[0]).toBe(200);
    expect(out.up[1]).toBeNull();
    expect(out.down[1]).toBe(201);
    for (let i = 2; i <= 18; i++) expect(out.down[i], `bar ${i}`).toBe(data[i].close + 3);
  });

  it('holds exactly one side of the stop per bar', () => {
    const out = run(VOLATILITY_STOP, wave());
    for (let i = 0; i < 200; i++) {
      const both = out.up[i] !== null && out.down[i] !== null;
      const neither = out.up[i] === null && out.down[i] === null;
      expect(both || neither, `bar ${i} carries ${out.up[i]} / ${out.down[i]}`).toBe(false);
    }
    // A 200-bar sine crosses often enough that both sides must appear.
    expect(count(out.up)).toBeGreaterThan(0);
    expect(count(out.down)).toBeGreaterThan(0);
  });

  it('widens the distance to price as the multiplier grows', () => {
    const data = wave();
    const near = run(VOLATILITY_STOP, data, { factor: 1 });
    const far = run(VOLATILITY_STOP, data, { factor: 4 });
    const gap = (col: readonly (number | null)[]): number => {
      let acc = 0;
      let n = 0;
      for (let i = 60; i < data.length; i++) {
        if (col[i] === null) continue;
        acc += Math.abs(data[i].close - col[i]!);
        n += 1;
      }
      return acc / n;
    };
    expect(gap(far.up)).toBeGreaterThan(gap(near.up));
  });
});

describe('Trend Strength Index', () => {
  it('is +1 on a straight rise and -1 on a straight fall', () => {
    // Perfect correlation with the bar index. The summation form lands one ulp
    // short of exactly 1, hence the tolerance rather than toBe.
    expect(run(TREND_STRENGTH_INDEX, rising()).tsi[39]!).toBeCloseTo(1, 12);
    expect(run(TREND_STRENGTH_INDEX, falling()).tsi[39]!).toBeCloseTo(-1, 12);
  });

  it('matches a correlation recomputed from the definition', () => {
    const data = wave(80);
    const length = 10;
    const at = 50;
    const out = run(TREND_STRENGTH_INDEX, data, { length });
    let sx = 0, sy = 0, sxx = 0, syy = 0, sxy = 0;
    for (let k = 0; k < length; k++) {
      const i = at - k;
      const x = data[i].close;
      const y = i;
      sx += x; sy += y; sxx += x * x; syy += y * y; sxy += x * y;
    }
    const cov = length * sxy - sx * sy;
    const den = Math.sqrt(length * sxx - sx * sx) * Math.sqrt(length * syy - sy * sy);
    expect(out.tsi[at]).toBeCloseTo(cov / den, 12);
  });

  it('stays inside the -1..1 band it declares', () => {
    const out = run(TREND_STRENGTH_INDEX, wave());
    for (const v of out.tsi) if (v !== null) expect(Math.abs(v)).toBeLessThanOrEqual(1);
    expect(TREND_STRENGTH_INDEX.range?.(defaults(TREND_STRENGTH_INDEX))).toEqual({ min: -1, max: 1 });
  });

  it('has no answer for a flat series, where the deviation is zero', () => {
    expect(run(TREND_STRENGTH_INDEX, bars(30, () => 100)).tsi.every((v) => v === null)).toBe(true);
  });

  it('warms up over the window, so the first value is at index 13', () => {
    const out = run(TREND_STRENGTH_INDEX, wave());
    expect(firstIndex(out.tsi)).toBe(13);
    expect(out.tsi[12]).toBeNull();
    expect(firstIndex(run(TREND_STRENGTH_INDEX, wave(), { length: 20 }).tsi)).toBe(19);
  });

  it('draws the bands the gradient fills cannot be', () => {
    const levels = TREND_STRENGTH_INDEX.levels?.(defaults(TREND_STRENGTH_INDEX)) ?? [];
    expect(levels.map((l) => l.price)).toEqual([1, 0, -1]);
    expect(levels[0].color).toBe('#089981');
    expect(levels[2].color).toBe('#f23645');
  });
});

describe('Williams Fractals', () => {
  /** A symmetric triangle: closes 1..5..1, so highs and lows both peak at bar 4. */
  const triangle = (): Bar[] => bars(9, (i) => (i <= 4 ? i + 1 : 9 - i));

  it('marks the apex of a symmetric triangle and nothing else', () => {
    const data = triangle();
    const out = run(WILLIAMS_FRACTALS, data);
    expect(hits(out.upFractal)).toEqual([4]);
    expect(out.upFractal[4]).toBe(data[4].high);
    // The lows rise and fall with the highs, so there is no trough to mark.
    expect(hits(out.downFractal)).toEqual([]);
  });

  it('tolerates a plateau, marking the last bar of a flat top', () => {
    // Highs 2,3,4,4,3,2. A strict pivot finds nothing here: bar 2 is beaten by
    // its equal neighbour on the right and bar 3 by its equal neighbour on the
    // left. The reference's plateau variants let bar 3 through.
    const data = bars(6, (i) => [1, 2, 3, 3, 2, 1][i]);
    const out = run(WILLIAMS_FRACTALS, data);
    expect(hits(out.upFractal)).toEqual([3]);
    expect(out.upFractal[3]).toBe(data[3].high);
  });

  it('accepts a plateau up to four bars wide and no wider', () => {
    // Five equal highs then a drop. The candidate is the last of the flat run,
    // which needs four tolerated bars behind it: exactly the deepest variant.
    const four = bars(12, (i) => [1, 2, 3, 7, 7, 7, 7, 7, 3, 2, 1, 0][i]);
    expect(hits(run(WILLIAMS_FRACTALS, four).upFractal)).toEqual([7]);
    // One equal bar more and no variant reaches back to a strictly lower run.
    const five = bars(13, (i) => [1, 2, 3, 7, 7, 7, 7, 7, 7, 3, 2, 1, 0][i]);
    expect(hits(run(WILLIAMS_FRACTALS, five).upFractal)).toEqual([]);
  });

  it('marks a trough as a down fractal', () => {
    const data = bars(9, (i) => (i <= 4 ? 5 - i : i - 3));
    const out = run(WILLIAMS_FRACTALS, data);
    expect(hits(out.downFractal)).toEqual([4]);
    expect(out.downFractal[4]).toBe(data[4].low);
    expect(hits(out.upFractal)).toEqual([]);
  });

  it('needs n bars either side, so the first n and last n bars are always empty', () => {
    const data = wave();
    const n = 3;
    const out = run(WILLIAMS_FRACTALS, data, { periods: n });
    for (let i = 0; i < n; i++) {
      expect(out.upFractal[i], `head ${i}`).toBeNull();
      expect(out.downFractal[i], `head ${i}`).toBeNull();
    }
    for (let i = data.length - n; i < data.length; i++) {
      expect(out.upFractal[i], `tail ${i}`).toBeNull();
      expect(out.downFractal[i], `tail ${i}`).toBeNull();
    }
    expect(count(out.upFractal)).toBeGreaterThan(0);
    expect(count(out.downFractal)).toBeGreaterThan(0);
  });

  it('agrees with a fractal test recomputed from the definition', () => {
    const data = wave();
    const n = 2;
    const out = run(WILLIAMS_FRACTALS, data, { periods: n });
    const highs = data.map((b) => b.high);
    // Independent restatement: n strictly lower bars on the newer side, and on
    // the older side up to four bars that may only equal the candidate followed
    // by n strictly lower ones.
    const expected: number[] = [];
    for (let p = 0; p < data.length; p++) {
      const v = highs[p];
      const lower = (j: number): boolean => j >= 0 && j < data.length && highs[j] < v;
      const notAbove = (j: number): boolean => j >= 0 && j < data.length && highs[j] <= v;
      let right = true;
      for (let k = 1; k <= n; k++) right = right && lower(p + k);
      let left = false;
      for (let flat = 0; flat <= 4 && !left; flat++) {
        let ok = true;
        for (let k = 1; k <= flat; k++) ok = ok && notAbove(p - k);
        for (let k = 1; k <= n; k++) ok = ok && lower(p - flat - k);
        left = left || ok;
      }
      if (right && left) expected.push(p);
    }
    expect(hits(out.upFractal)).toEqual(expected);
  });

  it('carries the shapes as markers on a series that draws nothing', () => {
    const data = wave();
    const out = run(WILLIAMS_FRACTALS, data);
    // The single declared plot exists only to own the marker layer.
    expect(WILLIAMS_FRACTALS.plots).toHaveLength(1);
    expect(out.fractals.every((v) => v === null)).toBe(true);

    const marks = markersOf(WILLIAMS_FRACTALS, data);
    expect(marks).toHaveLength(count(out.upFractal) + count(out.downFractal));
    const times = new Set(data.map((b) => b.time));
    for (const m of marks) {
      // A marker whose time is not a real bar time is dropped silently.
      expect(times.has(m.time)).toBe(true);
      expect(m.position).toBe('atPrice');
      expect(['triangleUp', 'triangleDown']).toContain(m.shape);
      expect(Number.isFinite(m.price)).toBe(true);
    }
    const up = marks.filter((m) => m.shape === 'triangleUp');
    expect(up).toHaveLength(count(out.upFractal));
    expect(up.map((m) => m.price)).toEqual(hits(out.upFractal).map((i) => out.upFractal[i]));
  });

  it('clears the layer when both sides are switched off', () => {
    const data = wave();
    expect(markersOf(WILLIAMS_FRACTALS, data, { showUp: false, showDown: false })).toEqual([]);
    const out = run(WILLIAMS_FRACTALS, data, { showUp: false, showDown: false });
    expect(count(out.upFractal) + count(out.downFractal)).toBe(0);
    // One side off leaves the other alone.
    const half = markersOf(WILLIAMS_FRACTALS, data, { showUp: false });
    expect(half.length).toBeGreaterThan(0);
    expect(half.every((m) => m.shape === 'triangleDown')).toBe(true);
  });
});

describe('RSI Divergence Indicator', () => {
  /**
   * The four signal classes restated from the definition: walk the oscillator's
   * confirmed pivots, and for each consecutive pair check the price/oscillator
   * disagreement and the spacing window. `column` is the direction under test.
   */
  const expectedSignals = (
    data: readonly Bar[],
    osc: readonly (number | null)[],
    opts: { high: boolean; oscHigher: boolean },
    lbL = 5,
    lbR = 5,
    lower = 5,
    upper = 60,
  ): number[] => {
    const n = data.length;
    const at = (i: number): number => (osc[i] === null ? NaN : osc[i]!);
    const price = (i: number): number => (opts.high ? data[i].high : data[i].low);
    const pivots: number[] = [];
    for (let p = 0; p < n; p++) {
      if (p - lbL < 0 || p + lbR >= n || !Number.isFinite(at(p))) continue;
      let ok = true;
      for (let k = 1; k <= lbL && ok; k++) {
        const o = at(p - k);
        if (!Number.isFinite(o) || (opts.high ? o >= at(p) : o <= at(p))) ok = false;
      }
      for (let k = 1; k <= lbR && ok; k++) {
        const o = at(p + k);
        if (!Number.isFinite(o) || (opts.high ? o >= at(p) : o <= at(p))) ok = false;
      }
      if (ok) pivots.push(p);
    }
    const out: number[] = [];
    for (let k = 1; k < pivots.length; k++) {
      const p = pivots[k];
      const q = pivots[k - 1];
      // barssince runs on the found flag delayed one bar, so the gap counted is
      // the distance between the two pivots less one.
      const gap = p - q - 1;
      if (gap < lower || gap > upper) continue;
      const oscMoved = opts.oscHigher ? at(p) > at(q) : at(p) < at(q);
      // Price always has to move the other way: that disagreement is the
      // divergence, and it is what all four classes have in common.
      const priceMoved = opts.oscHigher ? price(p) < price(q) : price(p) > price(q);
      if (oscMoved && priceMoved) out.push(p);
    }
    return out;
  };

  it('plots the RSI itself, warming up at index 14', () => {
    const out = run(RSI_DIVERGENCE, wave());
    expect(firstIndex(out.rsi)).toBe(14);
    expect(out.rsi[13]).toBeNull();
    expect(firstIndex(run(RSI_DIVERGENCE, wave(), { length: 21 }).rsi)).toBe(21);
    expect(RSI_DIVERGENCE.range?.(defaults(RSI_DIVERGENCE))).toEqual({ min: 0, max: 100 });
    expect((RSI_DIVERGENCE.levels?.(defaults(RSI_DIVERGENCE)) ?? []).map((l) => l.price)).toEqual([70, 50, 30]);
  });

  it('finds the regular bullish pairs a re-derivation of the rules finds', () => {
    const data = swings();
    const out = run(RSI_DIVERGENCE, data);
    expect(count(out.bull)).toBeGreaterThan(0);
    expect(hits(out.bull)).toEqual(expectedSignals(data, out.rsi, { high: false, oscHigher: true }));
    // The plate sits on the RSI reading of the pivot bar it belongs to.
    for (const i of hits(out.bull)) expect(out.bull[i]).toBe(out.rsi[i]);
  });

  it('finds the regular bearish pairs the same way', () => {
    const data = swings();
    const out = run(RSI_DIVERGENCE, data);
    expect(count(out.bear)).toBeGreaterThan(0);
    expect(hits(out.bear)).toEqual(expectedSignals(data, out.rsi, { high: true, oscHigher: false }));
    for (const i of hits(out.bear)) expect(out.bear[i]).toBe(out.rsi[i]);
  });

  it('keeps the hidden classes off until they are asked for', () => {
    const out = run(RSI_DIVERGENCE, wave());
    expect(count(out.hiddenBull)).toBe(0);
    expect(count(out.hiddenBear)).toBe(0);
    const bull = run(RSI_DIVERGENCE, wave(), { plotHiddenBull: true });
    expect(count(bull.hiddenBull)).toBeGreaterThan(0);
    expect(hits(bull.hiddenBull)).toEqual(expectedSignals(wave(), bull.rsi, { high: false, oscHigher: false }));
    const bear = run(RSI_DIVERGENCE, sinking(), { plotHiddenBear: true });
    expect(count(bear.hiddenBear)).toBeGreaterThan(0);
    expect(hits(bear.hiddenBear)).toEqual(expectedSignals(sinking(), bear.rsi, { high: true, oscHigher: true }));
  });

  it('rejects pivot pairs closer than rangeLower or further than rangeUpper', () => {
    const data = swings();
    const wide = run(RSI_DIVERGENCE, data);
    // A window that admits nothing must produce nothing, and one that admits
    // less than the default must produce a subset.
    expect(count(run(RSI_DIVERGENCE, data, { rangeLower: 900, rangeUpper: 1000 }).bull)).toBe(0);
    const narrow = run(RSI_DIVERGENCE, data, { rangeUpper: 12 });
    for (const i of hits(narrow.bull)) expect(hits(wide.bull)).toContain(i);
  });

  it('anchors every label to a real bar and matches the signal columns', () => {
    const data = swings();
    const over = { plotHiddenBull: true, plotHiddenBear: true };
    const out = run(RSI_DIVERGENCE, data, over);
    const marks = markersOf(RSI_DIVERGENCE, data, over);
    const total = count(out.bull) + count(out.hiddenBull) + count(out.bear) + count(out.hiddenBear);
    expect(marks).toHaveLength(total);
    expect(marks.length).toBeGreaterThan(0);
    const times = new Set(data.map((b) => b.time));
    for (const m of marks) {
      expect(times.has(m.time)).toBe(true);
      expect(m.position).toBe('atPrice');
      expect(['Bull', 'H Bull', 'Bear', 'H Bear']).toContain(m.text);
      // The plate hangs below a bullish low and sits above a bearish high.
      const expectedShape = m.text === 'Bull' || m.text === 'H Bull' ? 'labelUp' : 'labelDown';
      expect(m.shape).toBe(expectedShape);
    }
    const bullTimes = hits(out.bull).map((i) => data[i].time);
    expect(marks.filter((m) => m.text === 'Bull').map((m) => m.time)).toEqual(bullTimes);
  });

  it('clears the layer when all four classes are switched off', () => {
    const data = swings();
    const off = { plotBull: false, plotHiddenBull: false, plotBear: false, plotHiddenBear: false };
    expect(markersOf(RSI_DIVERGENCE, data, off)).toEqual([]);
    const out = run(RSI_DIVERGENCE, data, off);
    for (const key of ['bull', 'hiddenBull', 'bear', 'hiddenBear']) {
      expect(count(out[key]), key).toBe(0);
    }
    // The RSI is not a toggle: it must still be there.
    expect(count(out.rsi)).toBeGreaterThan(0);
    // One class on leaves only its own plates.
    const bearOnly = markersOf(RSI_DIVERGENCE, data, { ...off, plotBear: true });
    expect(bearOnly.length).toBeGreaterThan(0);
    expect(bearOnly.every((m) => m.text === 'Bear')).toBe(true);
  });
});
