/**
 * Logic-audit regressions for the indices and ranges indicator groups.
 *
 * Every expectation here is derived from the published definition and rebuilt
 * with naive scans local to this file, never by calling the helpers the
 * implementation calls. A test that reuses `calc.ts` would pass against any
 * table of terms, which is exactly the defect this file exists to catch.
 */
import { describe, it, expect } from 'vitest';
import { SPECIAL_K } from '../src/indicators/ranges';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const wave = (n: number): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...indicatorDefaults(d), ...over }, {});

/**
 * Pring's published Special K: the short-, intermediate- and long-term daily
 * KSTs added together, each of the three groups weighted 1, 2, 3, 4 across its
 * four rate-of-change horizons.
 */
const PUBLISHED_TERMS: readonly [weight: number, roc: number, smooth: number][] = [
  [1, 10, 10], [2, 15, 10], [3, 20, 10], [4, 30, 15],
  [1, 40, 50], [2, 65, 65], [3, 75, 75], [4, 100, 100],
  [1, 195, 130], [2, 265, 130], [3, 390, 130], [4, 530, 195],
];

/** `100 * (v - v[n]) / v[n]`, NaN for the first `n` bars. */
const naiveRoc = (values: readonly number[], n: number): number[] =>
  values.map((v, i) => (i < n ? NaN : (100 * (v - values[i - n])) / values[i - n]));

/** A fresh window sum each bar, refusing any window that still holds a hole. */
const naiveSma = (values: readonly number[], n: number): number[] =>
  values.map((_, i) => {
    if (i < n - 1) return NaN;
    let acc = 0;
    for (let k = 0; k < n; k++) {
      const v = values[i - k];
      if (!Number.isFinite(v)) return NaN;
      acc += v;
    }
    return acc / n;
  });

/** The whole study, written straight out of the definition. */
const naiveSpecialK = (closes: readonly number[]): number[] => {
  const out = new Array<number>(closes.length).fill(0);
  for (const [weight, roc, smooth] of PUBLISHED_TERMS) {
    const term = naiveSma(naiveRoc(closes, roc), smooth);
    for (let i = 0; i < out.length; i++) out[i] += weight * term[i];
  }
  return out;
};

describe("Pring's Special K term table", () => {
  it('matches a term-by-term rebuild of the published definition', () => {
    const data = wave(1200);
    const expected = naiveSpecialK(data.map((b) => b.close));
    const out = run(SPECIAL_K, data);
    for (const i of [724, 725, 800, 999, 1199]) {
      expect(out.specialK[i] as number, `bar ${i}`).toBeCloseTo(expected[i], 9);
    }
  });

  it('sums the twelve published weights on a series with a closed form', () => {
    // Geometric closes make every rate of change a constant, and an SMA of a
    // constant is that constant, so the study collapses to one hand sum.
    const r = 1.001;
    const data = bars(1200, (i) => 100 * Math.pow(r, i));
    let expected = 0;
    for (const [weight, roc] of PUBLISHED_TERMS) expected += weight * 100 * (Math.pow(r, roc) - 1);
    // 1*1.004512 + 2*1.510546 + 3*2.019114 + 4*3.043909 for the short group,
    // and so on: 609.73 in total, not the 4214.54 a table weighted by its own
    // rate-of-change lengths produces.
    expect(expected).toBeCloseTo(609.7337, 3);
    const out = run(SPECIAL_K, data);
    expect(out.specialK[1000] as number).toBeCloseTo(expected, 6);
    // Two SMAs of a constant land on the same constant.
    expect(out.signal[1000] as number).toBeCloseTo(expected, 6);
  });

  it('prints exactly one value on the shortest chart that can carry it', () => {
    expect(run(SPECIAL_K, wave(724)).specialK.every((v) => v === null)).toBe(true);
    const out = run(SPECIAL_K, wave(725));
    expect(out.specialK.filter((v) => v !== null)).toHaveLength(1);
    expect(out.specialK[724]).not.toBeNull();
  });

  it('weights the short group 1/2/3/4, not by its rate-of-change lengths', () => {
    // Isolating the short group: on geometric closes the four fastest terms
    // contribute 22.259 under the published weights and 227.659 under weights
    // equal to the rate-of-change lengths, a tenfold difference before the
    // long terms are even reached.
    const r = 1.001;
    const published = PUBLISHED_TERMS.slice(0, 4)
      .reduce((acc, [weight, roc]) => acc + weight * 100 * (Math.pow(r, roc) - 1), 0);
    expect(published).toBeCloseTo(22.2586, 3);
  });
});
