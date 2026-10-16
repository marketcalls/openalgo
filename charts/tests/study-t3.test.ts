import { describe, it, expect } from 'vitest';
import { AVERAGE_INDICATORS, T3 } from '../src/indicators/averages';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * T3 Average.
 *
 * Every number below is worked out from the definition on paper. The vehicle is
 * a straight ramp, because an SMA-seeded exponential average of a straight ramp
 * is itself exactly straight: the seed, the simple mean of the first `n` values,
 * already sits on the steady-state line, so the recursion never has an error to
 * decay and each layer is nothing but a fixed lag. That makes a six-layer nest
 * hand-computable to the last decimal instead of only approximately.
 */

/** `high = close + 1`, `low = close - 1`, so `hl2` equals `close`. */
const bars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({
    time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 1000,
  }));

/** `low = close` and `high = close + 4`, so `hl2` is `close + 2` and the two sources differ. */
const skewed = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({
    time: 1700000000 + i * 60, open: c, high: c + 4, low: c, close: c, volume: 1000,
  }));

/** A ramp of slope `step`, so bar `i` closes at `step * i`. */
const ramp = (n: number, step = 1): Bar[] =>
  bars(Array.from({ length: n }, (_, i) => step * i));

const flat = (n: number, price: number): Bar[] =>
  bars(Array.from({ length: n }, () => price));

const run = (data: Bar[], overrides: IndicatorSettings = {}) =>
  T3.calc(data, { ...indicatorDefaults(T3), ...overrides }, {}).t3;

/** Index of the first plotted bar, which is what every warmup assertion is about. */
const firstLive = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

/**
 * An SMA-seeded exponential average over a series that itself opens with a gap,
 * written out here rather than imported so the degenerate check below compares
 * against arithmetic and not against the module under test. Seeded from the
 * simple mean of the first `n` real values, so it starts `n - 1` bars after the
 * series it reads.
 */
function chainedEma(values: readonly (number | null)[], n: number): (number | null)[] {
  const out = new Array<number | null>(values.length).fill(null);
  const live: number[] = [];
  let start = -1;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (typeof v === 'number') {
      if (start < 0) start = i;
      live.push(v);
    }
  }
  if (start < 0 || live.length < n) return out;
  let prev = live.slice(0, n).reduce((a, b) => a + b, 0) / n;
  out[start + n - 1] = prev;
  const k = 2 / (n + 1);
  for (let i = n; i < live.length; i++) {
    prev = live[i] * k + prev * (1 - k);
    out[start + i] = prev;
  }
  return out;
}

const nest = (values: readonly (number | null)[], n: number, times: number): (number | null)[] => {
  let out = values as (number | null)[];
  for (let i = 0; i < times; i++) out = chainedEma(out, n);
  return out;
};

describe('T3 Average, registration', () => {
  it('is registered once, on the price pane, with the defined inputs', () => {
    expect(AVERAGE_INDICATORS.filter((d) => d.id === 't3')).toEqual([T3]);
    expect(T3.name).toBe('T3 Average');
    expect(T3.placement).toBe('onchart');
    const d = indicatorDefaults(T3);
    expect(d.length).toBe(5);
    expect(d.factor).toBe(0.7);
    expect(d.highlightMovements).toBe(true);
    expect(d.source).toBe('close');
    expect(d.neutralColor).toBe('#6d1e7f');
  });

  it('draws one line, keyed t3, two pixels wide', () => {
    expect(T3.plots).toHaveLength(1);
    const [plot] = T3.plots;
    expect(plot.key).toBe('t3');
    expect(plot.title).toBe('T3');
    expect(plot.type).toBe('line');
    expect(plot.style?.lineWidth).toBe(2);
    expect(plot.colorBy).toBeTypeOf('function');
  });

  it('is appended to the averages group without disturbing the nine already there', () => {
    expect(AVERAGE_INDICATORS).toHaveLength(10);
    expect(AVERAGE_INDICATORS[9]).toBe(T3);
    expect(AVERAGE_INDICATORS.slice(0, 9).map((d) => d.id)).toEqual([
      'ma-cross', 'mcginley-dynamic', 'median', 'ma-ribbon', 'tema', 'twap', 'vwma',
      'alligator', 'smma',
    ]);
  });
});

describe('T3 Average, warmup', () => {
  it('first prints at 6 * (length - 1), which is 24 at the default length', () => {
    const out = run(ramp(60));
    expect(out).toHaveLength(60);
    expect(firstLive(out)).toBe(24);
    // Not one bar of the six-layer nest may be computed off a partial window.
    expect(out.slice(0, 24).every((v) => v === null)).toBe(true);
    expect(out[24]).toBeTypeOf('number');
  });

  it('scales that warmup with the length: two averages per layer, three layers', () => {
    const data = ramp(200);
    expect(firstLive(run(data, { length: 2 }))).toBe(6);
    expect(firstLive(run(data, { length: 3 }))).toBe(12);
    expect(firstLive(run(data, { length: 7 }))).toBe(36);
    expect(firstLive(run(data, { length: 21 }))).toBe(120);
    // Length 1 makes every layer the identity, so there is nothing to warm up
    // and the line is the source itself.
    const unit = run(data, { length: 1 });
    expect(firstLive(unit)).toBe(0);
    for (let i = 0; i < data.length; i++) {
      expect(unit[i] as number).toBeCloseTo(data[i].close, 9);
    }
  });

  it('prints nothing at all on a series shorter than the warmup', () => {
    const out = run(ramp(24));
    expect(out).toHaveLength(24);
    expect(out.every((v) => v === null)).toBe(true);
  });
});

describe('T3 Average, values', () => {
  /*
   * Length 2, factor 0.5, on a ramp of slope 3, worked out on paper.
   *
   * A length-2 average has k = 2/3 and a steady-state lag of 3 * (1 - k) / k,
   * which is 1.5 on this ramp, and its seed (v[i-1] + v[i]) / 2 already sits on
   * that line, so every layer is exactly "the ramp, 1.5 later" from its own
   * first bar. Writing a layer's output as `3i - L`:
   *
   *   e1  L = 1.50, from bar 1        e2  L = 3.00, from bar 2
   *   gd1 = 1.5 * e1 - 0.5 * e2  ->  L = 2.25 - 1.50 = 0.75, from bar 2
   *   f1  L = 2.25, from bar 3        f2  L = 3.75, from bar 4
   *   gd2 = 1.5 * f1 - 0.5 * f2  ->  L = 3.375 - 1.875 = 1.50, from bar 4
   *   g1  L = 3.00, from bar 5        g2  L = 4.50, from bar 6
   *   t3  = 1.5 * g1 - 0.5 * g2  ->  L = 4.50 - 2.25 = 2.25, from bar 6
   *
   * Six averages of averages would lag 9.0; the factor buys that down to 2.25.
   */
  it('tracks a ramp at exactly the lag the nesting predicts', () => {
    const out = run(ramp(12, 3), { length: 2, factor: 0.5 });
    expect(firstLive(out)).toBe(6);
    for (let i = 6; i < 12; i++) expect(out[i] as number).toBeCloseTo(3 * i - 2.25, 9);
    // A plain six-deep chain of the same averages would sit far behind it.
    expect(out[11] as number).toBeCloseTo(30.75, 9);
    expect(out[11] as number).not.toBeCloseTo(3 * 11 - 9, 6);
  });

  it('collapses to three chained averages at factor 0, not six', () => {
    // The second average inside each layer carries the weight `factor`, so at
    // zero the layer is one plain average and the three-deep nest is three of
    // them. Six is the depth of the longest term once the factor is live, which
    // is where the default's 24-bar warmup comes from, not the depth here.
    const data = ramp(80);
    const out = run(data, { factor: 0 });
    const closes = data.map((b) => b.close);
    const triple = nest(closes, 5, 3);
    const sextuple = nest(closes, 5, 6);
    expect(firstLive(out)).toBe(12);
    expect(firstLive(triple)).toBe(12);
    expect(firstLive(sextuple)).toBe(24);
    for (let i = 0; i < data.length; i++) {
      if (triple[i] === null) expect(out[i]).toBeNull();
      else expect(out[i] as number).toBeCloseTo(triple[i] as number, 9);
    }
    // And the same series is demonstrably not the six-deep chain.
    expect(out[79] as number).not.toBeCloseTo(sextuple[79] as number, 6);
    // On this unit ramp the three-deep chain lags 3 * (length - 1) / 2 = 6 bars.
    expect(out[79] as number).toBeCloseTo(79 - 6, 9);
  });

  it('holds a flat series at its own level, with no divergence anywhere', () => {
    // Every average of a constant is that constant, so each layer reads
    // 100 * (1 + factor) - 100 * factor = 100 whatever the factor is.
    const out = run(flat(40, 100));
    expect(firstLive(out)).toBe(24);
    for (let i = 24; i < 40; i++) expect(out[i] as number).toBeCloseTo(100, 9);
    for (const f of [0, 0.25, 1]) {
      const alt = run(flat(40, 100), { factor: f });
      for (const v of alt) expect(v === null || Math.abs(v - 100) < 1e-9).toBe(true);
    }
    // Zero is the other flat level worth checking: nothing here divides by the
    // source, so it must simply hold at zero rather than go non-finite.
    for (const v of run(flat(40, 0))) expect(v === null || v === 0).toBe(true);
  });

  it('reads the configured source', () => {
    // hl2 is close + 2 on these bars, and every layer is affine, so the whole
    // printed line has to sit exactly 2 above the close-sourced one.
    const data = skewed(Array.from({ length: 40 }, (_, i) => i));
    const closed = run(data);
    const mid = run(data, { source: 'hl2' });
    expect(firstLive(mid)).toBe(24);
    for (let i = 24; i < 40; i++) {
      expect(mid[i] as number).toBeCloseTo((closed[i] as number) + 2, 9);
    }
  });

  it('emits null, never NaN or Infinity, on every degenerate series', () => {
    const cases: Bar[][] = [
      [],
      ramp(1),
      ramp(2),
      flat(30, 0),
      bars([5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5, 5, -5,
        5, -5, 5, -5, 5, -5, 5, -5, 5, -5]),
    ];
    for (const data of cases) {
      for (const settings of [{}, { length: 1 }, { factor: 0 }, { factor: 1 }]) {
        const out = run(data, settings);
        expect(out).toHaveLength(data.length);
        for (const v of out) expect(v === null || Number.isFinite(v)).toBe(true);
      }
    }
  });

  it('handles an empty and a one-bar series without throwing', () => {
    expect(run([])).toEqual([]);
    expect(run(ramp(1))).toEqual([null]);
    expect(run(ramp(1), { length: 1 })).toEqual([0]);
  });
});

describe('T3 Average, movement highlighting', () => {
  const paint = (
    col: readonly (number | null)[],
    settings: IndicatorSettings,
  ): (string | undefined)[] =>
    col.map((v, i) => (v === null ? undefined : T3.plots[0].colorBy?.({
      value: v, index: i, values: { t3: col }, settings,
    })));

  it('paints a rise up and everything else down', () => {
    const s = { ...indicatorDefaults(T3), length: 2, factor: 0.5 };
    // Up for eight bars, then down for eight: the turn has to change the colour.
    const closes = [...Array.from({ length: 10 }, (_, i) => 100 + i),
      ...Array.from({ length: 10 }, (_, i) => 109 - i)];
    const col = T3.calc(bars(closes), s, {}).t3;
    const colors = paint(col, s);
    const first = firstLive(col);
    expect(first).toBe(6);
    // The first printed bar has nothing behind it to rise against.
    expect(colors[first]).toBe('#ff5252');
    expect(colors[first + 1]).toBe('#26a69a');
    expect(colors[colors.length - 1]).toBe('#ff5252');
    for (let i = first + 1; i < col.length; i++) {
      const rose = (col[i] as number) > (col[i - 1] as number);
      expect(colors[i]).toBe(rose ? '#26a69a' : '#ff5252');
    }
  });

  it('calls an unchanged value falling, not rising', () => {
    const s = { ...indicatorDefaults(T3) };
    const col = T3.calc(flat(40, 100), s, {}).t3;
    for (const c of paint(col, s).slice(24)) expect(c).toBe('#ff5252');
  });

  it('paints one neutral colour when highlighting is off', () => {
    const s = { ...indicatorDefaults(T3), highlightMovements: false };
    const col = T3.calc(ramp(40), s, {}).t3;
    const colors = paint(col, s).slice(24);
    expect(colors).not.toHaveLength(0);
    for (const c of colors) expect(c).toBe('#6d1e7f');
  });

  it('honours restyled colours in all three states', () => {
    const custom = {
      ...indicatorDefaults(T3), upColor: '#111111', downColor: '#222222', neutralColor: '#333333',
    };
    const col = T3.calc(ramp(40), custom, {}).t3;
    expect(paint(col, custom)[25]).toBe('#111111');
    expect(paint(col, { ...custom, highlightMovements: false })[25]).toBe('#333333');
    const falling = T3.calc(ramp(40, -1), custom, {}).t3;
    expect(paint(falling, custom)[25]).toBe('#222222');
  });
});
