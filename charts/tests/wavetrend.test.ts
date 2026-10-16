import { describe, it, expect } from 'vitest';
import { WAVETREND, WAVETREND_INDICATORS } from '../src/indicators/wavetrend';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

/** Every price identical, so the source never leaves its own mean. */
const frozen = (n = 80, price = 100): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1700000000 + i * 60, open: price, high: price, low: price, close: price, volume: 100,
  }));

/** high == low == close, so hlc3 is exactly the value passed in. */
const exact = (values: readonly number[]): Bar[] =>
  values.map((v, i) => ({ time: 1700000000 + i * 60, open: v, high: v, low: v, close: v, volume: 100 }));

const wave = (n = 300): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

/**
 * A deterministic pseudo-random walk. The oscillator needs a series that
 * actually reaches the zones and makes disagreeing pivots, which a clean sine
 * never does.
 */
const walk = (n = 400, seed = 10): Bar[] => {
  let s = seed;
  const rnd = (): number => {
    s = (s * 1103515245 + 12345) % 2147483648;
    return s / 2147483648;
  };
  let p = 100;
  return Array.from({ length: n }, (_, i) => {
    p += (rnd() - 0.5) * 3;
    const high = p + rnd() * 1.5;
    const low = p - rnd() * 1.5;
    return { time: 1700000000 + i * 60, open: p, high, low, close: p, volume: 100 + i };
  });
};

const defaults = (): Record<string, unknown> => indicatorDefaults(WAVETREND);
const run = (data: readonly Bar[], over: Record<string, unknown> = {}) =>
  WAVETREND.calc(data, { ...defaults(), ...over }, {});
const markersOf = (data: readonly Bar[], over: Record<string, unknown> = {}) => {
  const settings = { ...defaults(), ...over };
  return WAVETREND.markers?.({ bars: data, values: WAVETREND.calc(data, settings, {}), settings }) ?? [];
};
const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);
const hits = (col: readonly (number | null)[]): number[] =>
  col.reduce<number[]>((acc, v, i) => (v === null ? acc : [...acc, i]), []);
const at = (col: readonly (number | null)[], i: number): number => col[i] as number;

// ── the formula, written out again from the definition ────────────────────────
// Deliberately independent of the module's own helpers: if both agree, the
// chain is right for reasons other than "the same code ran twice".

const firstReal = (xs: readonly number[]): number => xs.findIndex((v) => Number.isFinite(v));

/** Exponential average seeded with the mean of the first `p` real values. */
const refEma = (xs: readonly number[], p: number): number[] => {
  const out = new Array<number>(xs.length).fill(NaN);
  const s = firstReal(xs);
  if (s < 0 || s + p > xs.length) return out;
  let sum = 0;
  for (let i = s; i < s + p; i++) sum += xs[i];
  let prev = sum / p;
  out[s + p - 1] = prev;
  const k = 2 / (p + 1);
  for (let i = s + p; i < xs.length; i++) {
    prev = xs[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
};

/** Simple average whose window starts counting at the first real value. */
const refSma = (xs: readonly number[], p: number): number[] => {
  const out = new Array<number>(xs.length).fill(NaN);
  const s = firstReal(xs);
  if (s < 0) return out;
  for (let i = s + p - 1; i < xs.length; i++) {
    let sum = 0;
    for (let k = 0; k < p; k++) sum += xs[i - k];
    out[i] = sum / p;
  }
  return out;
};

const referenceChain = (data: readonly Bar[], n1: number, n2: number, sigLen: number) => {
  const ap = data.map((b) => (b.high + b.low + b.close) / 3);
  const esa = refEma(ap, n1);
  const deviation = refEma(ap.map((v, i) => Math.abs(v - esa[i])), n1);
  const ci = ap.map((v, i) => {
    const dv = deviation[i];
    if (!Number.isFinite(dv)) return NaN;
    return dv === 0 ? 0 : (v - esa[i]) / (0.015 * dv);
  });
  const wt1 = refEma(ci, n2);
  const wt2 = refSma(wt1, sigLen);
  return { wt1, wt2, mom: wt1.map((v, i) => v - wt2[i]) };
};

describe('WaveTrend Pro descriptor', () => {
  it('is catalogued as a momentum study in its own pane', () => {
    expect(WAVETREND.id).toBe('wavetrend');
    expect(WAVETREND.name).toBe('WaveTrend Pro');
    expect(WAVETREND.category).toBe('Momentum');
    expect(WAVETREND.placement).toBe('pane');
    expect(WAVETREND_INDICATORS.map((d) => d.id)).toEqual(['wavetrend']);
  });

  it('mirrors the source definition inputs, defaults and groups', () => {
    const byKey = new Map(WAVETREND.inputs.map((i) => [i.key, i]));
    const expected: [string, unknown, string][] = [
      ['source', 'hlc3', 'WaveTrend'],
      ['n1', 10, 'WaveTrend'],
      ['n2', 21, 'WaveTrend'],
      ['sigLen', 4, 'WaveTrend'],
      ['obLevel1', 60, 'Levels'],
      ['obLevel2', 53, 'Levels'],
      ['osLevel1', -60, 'Levels'],
      ['osLevel2', -53, 'Levels'],
      ['filterZone', true, 'Signals'],
      ['useInner', true, 'Signals'],
      ['showMom', true, 'Signals'],
      ['showRegDiv', true, 'Divergence'],
      ['showHidDiv', false, 'Divergence'],
      ['lbL', 3, 'Divergence'],
      ['lbR', 3, 'Divergence'],
      ['rangeUpper', 60, 'Divergence'],
      ['rangeLower', 5, 'Divergence'],
    ];
    for (const [key, value, group] of expected) {
      const input = byKey.get(key);
      expect(input, `${key} is not declared`).toBeDefined();
      expect(input?.default, `${key} default`).toBe(value);
      expect(input?.group, `${key} group`).toBe(group);
    }
    // Every input belongs to one of the four sections a settings dialog draws.
    for (const input of WAVETREND.inputs) {
      expect(['WaveTrend', 'Levels', 'Signals', 'Divergence']).toContain(input.group);
    }
  });

  it('points every plot at a declared colour input', () => {
    for (const plot of WAVETREND.plots) {
      expect(plot.colorKey, `${plot.key} has no colorKey`).toBeTypeOf('string');
      const declared = WAVETREND.inputs.find((i) => i.key === plot.colorKey);
      expect(declared?.type, `${plot.colorKey} is not a colour input`).toBe('color');
    }
    expect(WAVETREND.plots.map((p) => p.key)).toEqual(['mom', 'wt1', 'wt2']);
    // The per-bar colour only survives on a renderer that honours it.
    expect(WAVETREND.plots.find((p) => p.key === 'mom')?.type).toBe('histogram');
  });

  it('declares the five reference levels', () => {
    const levels = WAVETREND.levels?.(defaults()) ?? [];
    expect(levels.map((l) => l.price)).toEqual([60, 53, 0, -53, -60]);
  });
});

describe('WaveTrend Pro core chain', () => {
  it('matches the formula computed by hand on a short series', () => {
    // hlc3 is 10, 12, 11, 15, 14, 18 exactly, with n1 = n2 = sigLen = 2 so the
    // whole chain fits in six bars and every term can be written out.
    const values = run(exact([10, 12, 11, 15, 14, 18]), { n1: 2, n2: 2, sigLen: 2 });
    // esa: 11, 11, 13.666667, 13.888889, 16.62963
    // mean deviation: 0.5, 1.055556, 0.425926, 1.055556
    // ci: 0, 84.210526, 17.391304, 86.549708
    expect(at(values.wt1, 3)).toBeCloseTo(42.105263, 6);
    expect(at(values.wt1, 4)).toBeCloseTo(25.629291, 6);
    expect(at(values.wt1, 5)).toBeCloseTo(66.242902, 6);
    expect(at(values.wt2, 4)).toBeCloseTo(33.867277, 6);
    expect(at(values.wt2, 5)).toBeCloseTo(45.936096, 6);
    expect(at(values.mom, 4)).toBeCloseTo(-8.237986, 6);
    expect(at(values.mom, 5)).toBeCloseTo(20.306806, 6);
    expect(values.wt1.slice(0, 3)).toEqual([null, null, null]);
    expect(values.wt2.slice(0, 4)).toEqual([null, null, null, null]);
  });

  it('agrees with the formula bar for bar, at the defaults and away from them', () => {
    for (const [n1, n2, sigLen] of [[10, 21, 4], [5, 9, 3], [14, 30, 6]]) {
      const data = walk();
      const values = run(data, { n1, n2, sigLen });
      const reference = referenceChain(data, n1, n2, sigLen);
      for (let i = 0; i < data.length; i++) {
        const want = reference.wt1[i];
        if (!Number.isFinite(want)) expect(values.wt1[i], `wt1[${i}]`).toBeNull();
        else expect(at(values.wt1, i), `wt1[${i}]`).toBeCloseTo(want, 9);
        const wantSig = reference.wt2[i];
        if (!Number.isFinite(wantSig)) expect(values.wt2[i], `wt2[${i}]`).toBeNull();
        else expect(at(values.wt2, i), `wt2[${i}]`).toBeCloseTo(wantSig, 9);
      }
    }
  });

  it('reads zero on a flat series, where the deviation guard is the only answer', () => {
    // The source never leaves its mean, so the deviation is exactly zero and the
    // quotient would be 0/0. The guard makes that "exactly average", not a hole.
    const values = run(frozen());
    expect(firstIndex(values.wt1)).toBe(38);
    for (const v of values.wt1) expect(v === null || v === 0).toBe(true);
    for (const v of values.wt2) expect(v === null || v === 0).toBe(true);
    for (const v of values.mom) expect(v === null || v === 0).toBe(true);
    expect(at(values.wt1, 38)).toBe(0);
    expect(at(values.wt2, 41)).toBe(0);
    expect(at(values.mom, 41)).toBe(0);
    // Nothing crosses anything, so the signal and divergence layers stay empty.
    expect(hits(values.buy)).toEqual([]);
    expect(hits(values.sell)).toEqual([]);
    expect(markersOf(frozen())).toEqual([]);
  });

  it('starts each stage exactly where its warmup runs out', () => {
    // Each stage's window starts counting at its input's first real value, so
    // the gaps add: 2 * (n1 - 1) for the mean and its deviation, n2 - 1 for the
    // oscillator, sigLen - 1 for the signal line.
    const cases: [number, number, number][] = [[10, 21, 4], [5, 9, 3], [14, 30, 6], [1, 1, 1]];
    for (const [n1, n2, sigLen] of cases) {
      const values = run(wave(), { n1, n2, sigLen });
      const wt1First = 2 * (n1 - 1) + (n2 - 1);
      expect(firstIndex(values.wt1), `wt1 for ${n1}/${n2}/${sigLen}`).toBe(wt1First);
      expect(firstIndex(values.wt2), `wt2 for ${n1}/${n2}/${sigLen}`).toBe(wt1First + sigLen - 1);
      expect(firstIndex(values.mom), `mom for ${n1}/${n2}/${sigLen}`).toBe(wt1First + sigLen - 1);
    }
    const defaultRun = run(wave());
    expect(firstIndex(defaultRun.wt1)).toBe(38);
    expect(firstIndex(defaultRun.wt2)).toBe(41);
    expect(firstIndex(defaultRun.mom)).toBe(41);
  });

  it('prints the momentum as the gap between the two lines, and nowhere else', () => {
    const values = run(walk());
    for (let i = 0; i < values.mom.length; i++) {
      const fast = values.wt1[i];
      const slow = values.wt2[i];
      if (fast === null || slow === null) {
        expect(values.mom[i], `mom[${i}]`).toBeNull();
        continue;
      }
      expect(at(values.mom, i), `mom[${i}]`).toBeCloseTo(fast - slow, 12);
    }
    expect(hits(values.mom).length).toBeGreaterThan(300);
  });

  it('all-nulls the momentum when the histogram is switched off', () => {
    const off = run(walk(), { showMom: false });
    expect(off.mom.length).toBe(400);
    expect(hits(off.mom)).toEqual([]);
    // The lines are untouched by the switch.
    expect(off.wt1).toEqual(run(walk()).wt1);
  });

  it('colours the momentum by sign, which is what the shape change preserved', () => {
    const plot = WAVETREND.plots.find((p) => p.key === 'mom');
    const values = run(walk());
    const settings = defaults();
    const paint = (value: number): string | undefined =>
      plot?.colorBy?.({ value, index: 50, values, settings });
    expect(paint(1)).toBe('#008080');
    expect(paint(0)).toBe('#008080');
    expect(paint(-1)).toBe('#880e4f');
    expect(plot?.colorBy?.({ value: -1, index: 50, values, settings: { ...settings, momDownColor: '#123456' } }))
      .toBe('#123456');
  });
});

describe('WaveTrend Pro crosses', () => {
  const data = walk();

  /** Every crossing of the two lines, read back off the plotted columns. */
  const crossings = (values: Record<string, readonly (number | null)[]>, up: boolean): number[] => {
    const out: number[] = [];
    for (let i = 1; i < data.length; i++) {
      const prevFast = values.wt1[i - 1];
      const prevSlow = values.wt2[i - 1];
      const fast = values.wt1[i];
      const slow = values.wt2[i];
      if (prevFast === null || prevSlow === null || fast === null || slow === null) continue;
      if (up ? fast > slow && prevFast <= prevSlow : fast < slow && prevFast >= prevSlow) out.push(i);
    }
    return out;
  };

  it('fires on every crossing when the zone gate is off', () => {
    const values = run(data, { filterZone: false });
    expect(hits(values.buy)).toEqual(crossings(values, true));
    expect(hits(values.sell)).toEqual(crossings(values, false));
    expect(hits(values.buy).length).toBeGreaterThan(10);
    // The signal is anchored to the signal line, which is where the shape sits.
    for (const i of hits(values.buy)) expect(at(values.buy, i)).toBe(at(values.wt2, i));
    for (const i of hits(values.sell)) expect(at(values.sell, i)).toBe(at(values.wt2, i));
  });

  it('keeps only the crossings inside the zone when the gate is on', () => {
    const open = run(data, { filterZone: false });
    const inner = run(data);
    const outer = run(data, { useInner: false });

    expect(hits(inner.buy)).toEqual(hits(open.buy).filter((i) => at(open.wt2, i) <= -53));
    expect(hits(inner.sell)).toEqual(hits(open.sell).filter((i) => at(open.wt2, i) >= 53));
    expect(hits(outer.buy)).toEqual(hits(open.buy).filter((i) => at(open.wt2, i) <= -60));
    expect(hits(outer.sell)).toEqual(hits(open.sell).filter((i) => at(open.wt2, i) >= 60));

    // The inner gate is the looser of the two, and both are stricter than none.
    expect(hits(outer.buy).length).toBeLessThan(hits(inner.buy).length);
    expect(hits(outer.sell).length).toBeLessThan(hits(inner.sell).length);
    expect(hits(inner.buy).length).toBeLessThan(hits(open.buy).length);
  });

  it('moves the gate with the level inputs', () => {
    const open = run(data, { filterZone: false });
    const shallow = run(data, { obLevel2: 20, osLevel2: -20 });
    expect(hits(shallow.buy)).toEqual(hits(open.buy).filter((i) => at(open.wt2, i) <= -20));
    expect(hits(shallow.sell)).toEqual(hits(open.sell).filter((i) => at(open.wt2, i) >= 20));
    expect(hits(shallow.buy).length).toBeGreaterThan(hits(run(data).buy).length);
  });
});

describe('WaveTrend Pro divergence', () => {
  const data = walk();

  it('finds all four classes, each anchored to its pivot bar', () => {
    const values = run(data, { showHidDiv: true });
    for (const key of ['bull', 'bear', 'hiddenBull', 'hiddenBear']) {
      expect(hits(values[key]).length, `${key} found none`).toBeGreaterThan(0);
    }
    // A signal is written at the pivot, `lbR` bars before the bar that confirmed
    // it, and carries the signal line's reading there.
    for (const key of ['bull', 'bear', 'hiddenBull', 'hiddenBear']) {
      for (const i of hits(values[key])) {
        expect(at(values[key], i), `${key}[${i}]`).toBe(at(values.wt2, i));
        expect(i).toBeLessThanOrEqual(data.length - 1 - 3);
      }
    }
  });

  it('holds the price-against-oscillator disagreement each class is named for', () => {
    const values = run(data, { showHidDiv: true });
    /** Is bar `j` a 3-by-3 pivot of the signal line? Ties are not pivots. */
    const isPivot = (j: number, wantLow: boolean): boolean =>
      [-3, -2, -1, 1, 2, 3].every((k) => {
        const other = values.wt2[j + k];
        const here = values.wt2[j];
        if (other === null || other === undefined || here === null) return false;
        return wantLow ? other > here : other < here;
      });
    /** The pivot of the same kind immediately before `i`. */
    const previousPivot = (i: number, wantLow: boolean): number => {
      for (let j = i - 1; j >= 0; j--) if (isPivot(j, wantLow)) return j;
      return -1;
    };
    const check = (key: string, wantLow: boolean, oscHigher: boolean, priceHigher: boolean): void => {
      for (const i of hits(values[key])) {
        expect(isPivot(i, wantLow), `${key}[${i}] is not a pivot`).toBe(true);
        const previous = previousPivot(i, wantLow);
        expect(previous, `${key}[${i}] has no predecessor`).toBeGreaterThanOrEqual(0);
        const priceNow = wantLow ? data[i].low : data[i].high;
        const priceThen = wantLow ? data[previous].low : data[previous].high;
        expect(at(values.wt2, i) > at(values.wt2, previous), `${key}[${i}] oscillator`).toBe(oscHigher);
        expect(priceNow > priceThen, `${key}[${i}] price`).toBe(priceHigher);
        // The gate counts bars since the predecessor's confirmation, delayed one
        // bar so a pivot is never its own predecessor: that is `i - previous - 1`
        // against the 5..60 range.
        expect(i - previous - 1, `${key}[${i}] spacing`).toBeGreaterThanOrEqual(5);
        expect(i - previous - 1, `${key}[${i}] spacing`).toBeLessThanOrEqual(60);
      }
    };
    check('bull', true, true, false);
    check('bear', false, false, true);
    check('hiddenBull', true, false, true);
    check('hiddenBear', false, true, false);
  });

  it('gates each family behind its own switch', () => {
    const both = run(data, { showHidDiv: true });
    const regularOnly = run(data);
    expect(hits(regularOnly.bull)).toEqual(hits(both.bull));
    expect(hits(regularOnly.hiddenBull)).toEqual([]);
    expect(hits(regularOnly.hiddenBear)).toEqual([]);

    const hiddenOnly = run(data, { showRegDiv: false, showHidDiv: true });
    expect(hits(hiddenOnly.bull)).toEqual([]);
    expect(hits(hiddenOnly.bear)).toEqual([]);
    expect(hits(hiddenOnly.hiddenBull)).toEqual(hits(both.hiddenBull));

    const none = run(data, { showRegDiv: false, showHidDiv: false });
    for (const key of ['bull', 'bear', 'hiddenBull', 'hiddenBear']) {
      expect(hits(none[key]), key).toEqual([]);
    }
  });

  it('rejects pivot pairs outside the bar range', () => {
    const narrow = run(data, { showHidDiv: true, rangeUpper: 8 });
    const wide = run(data, { showHidDiv: true });
    for (const key of ['bull', 'bear', 'hiddenBull', 'hiddenBear']) {
      expect(hits(narrow[key]).length, key).toBeLessThanOrEqual(hits(wide[key]).length);
    }
    const raised = run(data, { showHidDiv: true, rangeLower: 40 });
    expect(hits(raised.bull).length + hits(raised.bear).length)
      .toBeLessThanOrEqual(hits(wide.bull).length + hits(wide.bear).length);
  });
});

describe('WaveTrend Pro shading', () => {
  it('resolves every fill edge to a real column', () => {
    const data = walk();
    const values = run(data);
    for (const fill of WAVETREND.fills ?? []) {
      for (const key of fill.between) {
        expect(values[key], `${key} is not a column`).toBeDefined();
        expect(values[key].length, `${key} length`).toBe(data.length);
      }
      // Each band is restyleable through a declared colour input, and its
      // literal fallback is that input's own default.
      for (const [key, literal] of [[fill.colorUpKey, fill.colorUp], [fill.colorDownKey, fill.colorDown]]) {
        const declared = WAVETREND.inputs.find((i) => i.key === key);
        expect(declared?.type, `${key}`).toBe('color');
        expect(literal, `${key} fallback`).toBe(declared?.default);
      }
      expect(fill.opacity, `${fill.between.join('/')} opacity`)
        .toBe(fill.between[0] === 'wt1' ? 0.15 : 0.08);
    }
    expect((WAVETREND.fills ?? []).map((f) => f.between)).toEqual([
      ['wt1', 'wt2'],
      ['obUpper', 'obLower'],
      ['osUpper', 'osLower'],
    ]);
  });

  it('holds the band levels on every bar, warmup included', () => {
    const data = walk(60);
    const values = run(data);
    const expected: Record<string, number> = { obUpper: 60, obLower: 53, osUpper: -53, osLower: -60 };
    for (const [key, level] of Object.entries(expected)) {
      expect(values[key].length, key).toBe(data.length);
      for (let i = 0; i < data.length; i++) expect(values[key][i], `${key}[${i}]`).toBe(level);
    }
    // The edges follow their inputs, so the shading stays glued to the lines.
    const moved = run(data, { obLevel1: 70, obLevel2: 45, osLevel1: -70, osLevel2: -45 });
    expect(new Set(moved.obUpper)).toEqual(new Set([70]));
    expect(new Set(moved.obLower)).toEqual(new Set([45]));
    expect(new Set(moved.osUpper)).toEqual(new Set([-45]));
    expect(new Set(moved.osLower)).toEqual(new Set([-70]));
  });
});

describe('WaveTrend Pro markers', () => {
  const data = walk();

  it('anchors every marker to a real bar time and its own column value', () => {
    const settings = { ...defaults(), showHidDiv: true };
    const values = WAVETREND.calc(data, settings, {});
    const markers = WAVETREND.markers?.({ bars: data, values, settings }) ?? [];
    const times = new Set(data.map((b) => b.time));
    const indexAt = new Map(data.map((b, i) => [b.time, i]));
    expect(markers.length).toBeGreaterThan(0);
    for (const m of markers) {
      expect(times.has(m.time), `time ${m.time}`).toBe(true);
      expect(m.position).toBe('atPrice');
      expect(Number.isFinite(m.price)).toBe(true);
      const i = indexAt.get(m.time) as number;
      expect(m.price).toBe(at(values.wt2, i));
    }
    // One marker per non-null signal slot, across all six classes.
    const total = ['buy', 'sell', 'bull', 'bear', 'hiddenBull', 'hiddenBear']
      .reduce((acc, key) => acc + hits(values[key]).length, 0);
    expect(markers.length).toBe(total);
  });

  it('leaves only the cross dots when both divergence families are off', () => {
    const markers = markersOf(data, { showRegDiv: false, showHidDiv: false });
    const values = run(data, { showRegDiv: false, showHidDiv: false });
    expect(markers.length).toBe(hits(values.buy).length + hits(values.sell).length);
    for (const m of markers) {
      expect(m.shape).toBe('circle');
      expect(m.size).toBe('tiny');
      expect(m.text).toBeUndefined();
      expect(['#00e676', '#ff5252']).toContain(m.color);
    }
    expect(markers.filter((m) => m.color === '#00e676').length).toBe(hits(values.buy).length);
  });

  it('plates the regular and hidden divergences apart, by letter and by shade', () => {
    const markers = markersOf(data, { showHidDiv: true });
    const regular = markers.filter((m) => m.text === 'R');
    const hidden = markers.filter((m) => m.text === 'H');
    expect(regular.length).toBeGreaterThan(0);
    expect(hidden.length).toBeGreaterThan(0);
    for (const m of regular) {
      expect(['labelUp', 'labelDown']).toContain(m.shape);
      expect(['#4caf50', '#ff5252']).toContain(m.color);
    }
    // The hidden pair is the same hue at 40 percent transparency.
    for (const m of hidden) {
      expect(['labelUp', 'labelDown']).toContain(m.shape);
      expect(['#4caf5099', '#ff525299']).toContain(m.color);
    }
    const bullish = markers.filter((m) => m.shape === 'labelUp');
    expect(bullish.every((m) => m.color.startsWith('#4caf50'))).toBe(true);
    // A recoloured input carries through to the dimmed plate too.
    const recoloured = markersOf(data, { showHidDiv: true, bullColor: '#00bcd4' });
    expect(recoloured.some((m) => m.color === '#00bcd499')).toBe(true);
  });
});

describe('WaveTrend Pro structure', () => {
  it('returns one full-length column of finite numbers or null per key', () => {
    const data = walk();
    const values = run(data, { showHidDiv: true });
    for (const plot of WAVETREND.plots) {
      expect(values[plot.key], `${plot.key} missing`).toBeDefined();
      expect(values[plot.key].length, `${plot.key} length`).toBe(data.length);
    }
    for (const [key, col] of Object.entries(values)) {
      expect(col.length, `${key} length`).toBe(data.length);
      for (const v of col) {
        expect(v === null || Number.isFinite(v), `${key} emitted ${v}`).toBe(true);
      }
    }
  });

  it('survives empty and single-bar input, markers included', () => {
    for (const input of [[] as Bar[], walk().slice(0, 1)]) {
      const values = run(input, { showHidDiv: true });
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${key} on ${input.length} bars`).toBe(input.length);
      }
      expect(markersOf(input, { showHidDiv: true })).toEqual([]);
    }
    // A single bar has no chain and no cross, but the bands still hold.
    const one = run(walk().slice(0, 1));
    expect(one.wt1).toEqual([null]);
    expect(one.obUpper).toEqual([60]);
  });

  it('shrugs off settings a UI could write', () => {
    const data = walk(80);
    const values = WAVETREND.calc(data, { n1: 0, n2: -3, sigLen: 2.7, source: 'close' }, {});
    for (const [key, col] of Object.entries(values)) {
      expect(col.length, key).toBe(data.length);
      for (const v of col) expect(v === null || Number.isFinite(v)).toBe(true);
    }
  });
});
