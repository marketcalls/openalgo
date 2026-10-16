import { describe, expect, it } from 'vitest';
import { sourceValues } from '../src/model/indicator-registry';

const bars = [1, 3, 5, 7].map((close, time) => ({ time, open: close - 1, high: close + 1, low: close - 2, close }));
const source = { kind: 'indicator' as const, instanceId: 'producer', plotKey: 'line' };

describe('resolved study input columns', () => {
  it('retains two-argument price selection', () => {
    expect(sourceValues(bars, 'close')).toEqual([1, 3, 5, 7]);
    expect(sourceValues(bars, 'hl2')).toEqual([0.5, 2.5, 4.5, 6.5]);
  });

  it('does not silently substitute price when the resolver is missing', () => {
    expect(() => sourceValues(bars, source)).toThrow(/resolv/i);
  });

  it('preserves gaps and detaches the returned column', () => {
    const column = [null, NaN, Infinity, 5];
    const result = sourceValues(bars, source, { resolveSource: ref => {
      expect(ref).toEqual(source);
      return column;
    } });
    expect(result).toEqual(column);
    result[3] = 9;
    expect(column[3]).toBe(5);
  });

  it.each([{ column: [] }, { column: [1, 2] }, { column: [1, 2, 3, 4, 5] }])('rejects misaligned output $column', ({ column }) => {
    expect(() => sourceValues(bars, source, { resolveSource: () => column })).toThrow(/length|align/i);
  });

  it.each([null, {}, { kind: 'indicator', instanceId: '', plotKey: 'line' },
    { kind: 'indicator', instanceId: 'producer', plotKey: '' }, { ...source, kind: 'price' }])('rejects malformed reference %j', value => {
    expect(() => sourceValues(bars, value as never, { resolveSource: () => [1, 2, 3, 4] })).toThrow();
  });
});
