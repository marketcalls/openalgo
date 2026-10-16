import { describe, expect, it } from 'vitest';
import { EMA, SMA, WMA } from '../src/indicators/trend';
import { planIndicatorDependencies } from '../src/model/indicator-dependencies';
import {
  sourceValues, type IndicatorCalcContext, type IndicatorDescriptor, type IndicatorStudySource,
} from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const source: IndicatorStudySource = { kind: 'indicator', instanceId: 'producer', plotKey: 'ma' };
const barsOf = (values: readonly number[]): Bar[] => values.map((close, index) => ({
  time: index * 60, open: close * 2, high: close + 1, low: close - 1, close,
}));
function context(column: readonly (number | null)[]): IndicatorCalcContext {
  return {
    barState: { isNew: false, isConfirmed: true, isRealtime: false, lastIndex: column.length - 1 },
    timezone: 'Etc/UTC', now: () => 0,
    resolveSource: reference => { expect(reference).toEqual(source); return column; },
  };
}
function expectColumn(actual: readonly (number | null)[], expected: readonly (number | null)[]): void {
  expect(actual).toHaveLength(expected.length);
  for (let i = 0; i < expected.length; i++) {
    const value = expected[i];
    if (value === null) expect(actual[i], `gap at index ${i}`).toBeNull();
    else expect(actual[i], `value at index ${i}`).toBeCloseTo(value, 12);
  }
}

const resolved = Object.freeze([null, 2, 4, 8, 16, null, 10, 14, 22, 38, NaN, 30, 36, 48, 72, Infinity, 50, 70, 90, 110]);
const gapCases: { descriptor: IndicatorDescriptor; expected: (number | null)[] }[] = [
  { descriptor: SMA, expected: [null, null, null, 14 / 3, 28 / 3, null, null, null, 46 / 3, 74 / 3, null, null, null, 38, 52, null, null, null, 70, 90] },
  { descriptor: WMA, expected: [null, null, null, 17 / 3, 34 / 3, null, null, null, 52 / 3, 86 / 3, null, null, null, 41, 58, null, null, null, 230 / 3, 290 / 3] },
  { descriptor: EMA, expected: [null, null, null, 14 / 3, 31 / 3, null, null, null, 46 / 3, 80 / 3, null, null, null, 38, 55, null, null, null, 70, 90] },
];

describe.each(gapCases)('$descriptor.id with a resolved study source', ({ descriptor, expected }) => {
  it('opts its declared source input into tracked study outputs', () => {
    expect(descriptor.inputs.find(input => input.key === 'source')).toMatchObject({ type: 'source', allowStudyOutputs: true });
  });

  it('keeps missing observations as gaps and requires fresh chronological warmup', () => {
    const bars = barsOf(resolved.map(() => 1_000));
    const before = resolved.slice();
    const result = descriptor.calc(bars, { source, length: 3 }, {}, context(resolved));
    expectColumn(result.ma, expected);
    expect(resolved).toEqual(before);
  });

  it('produces the same result on each available prefix without reading future observations', () => {
    for (let length = 0; length <= resolved.length; length++) {
      const prefix = resolved.slice(0, length);
      const result = descriptor.calc(barsOf(prefix.map(() => 1_000)), { source, length: 3 }, {}, context(prefix));
      expectColumn(result.ma, expected.slice(0, length));
    }
  });

  it('preserves finite zero and negative values while rejecting every nonfinite observation at period one', () => {
    const column = [-5, 0, null, NaN, Infinity, -Infinity, 7];
    const result = descriptor.calc(barsOf(column.map(() => 100)), { source, length: 1 }, {}, context(column));
    expect(result.ma).toEqual([-5, 0, null, null, null, null, 7]);
  });

  it('does not substitute chart prices when no resolver is available', () => {
    expect(() => descriptor.calc(barsOf([10, 20, 30]), { source, length: 2 }, {})).toThrow(/resolv/i);
  });
});

describe('moving averages chained through a source resolver', () => {
  const chainCases = [
    { descriptor: SMA, expected: [null, null, 4, 7, 17 / 2] },
    { descriptor: WMA, expected: [null, null, 14 / 3, 22 / 3, 26 / 3] },
    { descriptor: EMA, expected: [null, null, 4, 20 / 3, 74 / 9] },
  ];

  it.each(chainCases)('$descriptor.id uses the committed producer column before its own warmup', ({ descriptor, expected }) => {
    const bars = barsOf([1, 3, 9, 7, 11]);
    const producer = SMA.calc(bars, { source: 'close', length: 2 }, {});
    expect(producer.ma).toEqual([null, 2, 6, 8, 9]);
    expectColumn(descriptor.calc(bars, { source, length: 2 }, {}, context(producer.ma)).ma, expected);
  });
});

describe('legacy price-source moving averages', () => {
  const legacyCases = [
    { descriptor: SMA, finite: [null, 2, 6, 8, 9], gap: [null, 2, null, null, 8, 10] },
    { descriptor: WMA, finite: [null, 7 / 3, 7, 23 / 3, 29 / 3], gap: [null, 7 / 3, null, null, 25 / 3, 31 / 3] },
    { descriptor: EMA, finite: [null, 2, 20 / 3, 62 / 9, 260 / 27], gap: [null, 2, null, 16 / 3, 70 / 9, 268 / 27] },
  ];

  it.each(legacyCases)('$descriptor.id retains string, default and unknown-string selection without consulting the resolver', ({ descriptor, finite }) => {
    const bars = barsOf([1, 3, 9, 7, 11]);
    const unused = context([]);
    unused.resolveSource = () => { throw new Error('Price selection must not resolve a study.'); };
    for (const settings of [{ source: 'close' }, {}, { source: 'legacy-source' }]) {
      expectColumn(descriptor.calc(bars, { ...settings, length: 2 }, {}, unused).ma, finite);
    }
    expectColumn(descriptor.calc(bars, { source: 'open', length: 2 }, {}, unused).ma,
      finite.map(value => value === null ? null : value * 2));
  });

  it.each(legacyCases)('$descriptor.id applies its default price-gap calculation path', ({ descriptor, gap }) => {
    expectColumn(descriptor.calc(barsOf([1, 3, NaN, 7, 9, 11]), { source: 'close', length: 2 }, {}).ma, gap);
  });
});

describe('public source-reference validation matches the dependency graph', () => {
  const bars = barsOf([1, 2]);
  function graph(reference: unknown): void {
    planIndicatorDependencies([
      { id: 'producer', descriptor: SMA, settings: { source: 'close' } },
      { id: 'consumer', descriptor: SMA, settings: { source: reference } },
    ]);
  }

  it('accepts an exact null-prototype reference in both paths', () => {
    const reference = Object.assign(Object.create(null), source) as IndicatorStudySource;
    expect(() => graph(reference)).not.toThrow();
    expect(sourceValues(bars, reference, { resolveSource: () => [3, 5] })).toEqual([3, 5]);
  });

  it.each([
    { label: 'an extra string property', reference: { ...source, extra: true } },
    { label: 'an extra symbol property', reference: { ...source, [Symbol('extra')]: true } },
    { label: 'inherited reference fields', reference: Object.create(source) as unknown },
    { label: 'an empty identity', reference: { ...source, instanceId: ' ' } },
  ])('rejects $label before invoking a resolver', ({ reference }) => {
    let calls = 0;
    expect(() => graph(reference)).toThrow();
    expect(() => sourceValues(bars, reference as IndicatorStudySource, { resolveSource: () => {
      calls++; return [3, 5];
    } })).toThrow();
    expect(calls).toBe(0);
  });

  it('rejects accessors in both paths without running them', () => {
    let reads = 0;
    const reference = { ...source, get instanceId() { reads++; return 'producer'; } };
    expect(() => graph(reference)).toThrow();
    expect(() => sourceValues(bars, reference, { resolveSource: () => [3, 5] })).toThrow();
    expect(reads).toBe(0);
  });
});
