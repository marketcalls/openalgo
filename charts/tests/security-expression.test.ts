import { describe, expect, it } from 'vitest';
import { securityExpression, securitySeries } from '../src/indicators/security';
import type { Bar } from '../src/model/bar';
import { registerInterval } from '../src/feed/intervals';

const bars = (n = 9): Bar[] => Array.from({ length: n }, (_, i) => ({
  time: i * 60, open: i + 1, high: i + 2, low: i, close: i + 1, volume: 10, oi: 100 + i,
}));
const expression = (input: readonly Bar[]) => ({
  close: input.map(bar => bar.close),
  mean: input.map((bar, i) => i === 0 ? null : (bar.close + input[i - 1].close) / 2),
  volume: input.map(bar => bar.volume ?? null),
  oi: input.map(bar => bar.oi ?? null),
});

describe('requested timeframe expressions', () => {
  it('calculates on aggregated bars before aligning confirmed outputs', () => {
    const result = securityExpression(bars(), '3m', expression, { timezone: 'UTC' });
    expect(result.close).toEqual([null, null, null, 3, 3, 3, 6, 6, 6]);
    expect(result.mean).toEqual([null, null, null, null, null, null, 4.5, 4.5, 4.5]);
    expect(result.volume).toEqual([null, null, null, 30, 30, 30, 30, 30, 30]);
    expect(result.oi).toEqual([null, null, null, 102, 102, 102, 105, 105, 105]);
  });

  it('recalculates the developing requested bar without exposing later source bars', () => {
    const observed: number[] = [];
    const result = securityExpression(bars(), '3m', input => {
      observed.push(input[input.length - 1].close);
      return expression(input);
    }, { timezone: 'UTC', mode: 'developing' });
    expect(observed).toEqual([1, 2, 3, 4, 5, 6, 7, 8, 9]);
    expect(result.mean).toEqual([null, null, null, 3.5, 4, 4.5, 6.5, 7, 7.5]);
    expect(result.volume).toEqual([10, 20, 30, 10, 20, 30, 10, 20, 30]);
    expect(result.oi).toEqual([100, 101, 102, 103, 104, 105, 106, 107, 108]);
  });

  it('makes final bucket values available early only in explicit lookahead mode', () => {
    const result = securityExpression(bars(), '3m', expression, { timezone: 'UTC', mode: 'lookahead' });
    expect(result.close).toEqual([3, 3, 3, 6, 6, 6, 9, 9, 9]);
    expect(result.mean).toEqual([null, null, null, 4.5, 4.5, 4.5, 7.5, 7.5, 7.5]);
  });

  it('keeps causal historical results unchanged when source history grows', () => {
    for (const mode of ['confirmed', 'developing'] as const) {
      const prefix = securityExpression(bars(5), '3m', expression, { timezone: 'UTC', mode });
      const full = securityExpression(bars(9), '3m', expression, { timezone: 'UTC', mode });
      expect(full.mean.slice(0, 5)).toEqual(prefix.mean);
      expect(full.close.slice(0, 5)).toEqual(prefix.close);
    }
  });

  it('uses the session anchor and keeps missing buckets absent', () => {
    const source = [0, 1, 2, 3].map((i) => ({ ...bars(4)[i], time: (9 * 60 + 15 + i * 10) * 60 }));
    expect(securityExpression(source, '30m', expression, { timezone: 'UTC', session: '0915-1530' }).close)
      .toEqual([null, null, null, 3]);
    const sparse = [bars(9)[0], bars(9)[8]];
    expect(securityExpression(sparse, '3m', expression, { timezone: 'UTC' }).close).toEqual([null, 1]);
  });

  it('returns no columns for empty data and rejects invalid requests or expression shapes', () => {
    expect(securityExpression([], '3m', () => { throw new Error('must not evaluate'); })).toEqual({});
    expect(() => securityExpression(bars(), '3m', () => ({ short: [1] }))).toThrow(/length/i);
    expect(() => securityExpression(bars(), '3m', expression, { mode: 'future' as never })).toThrow(/mode/i);
    expect(() => securityExpression(bars(), '3m', expression, { session: 'invalid' })).toThrow(/session/i);
    expect(() => securityExpression([bars()[1], bars()[0]], '3m', expression)).toThrow(/increasing/i);
    expect(() => securityExpression([bars()[0], bars()[0]], '3m', expression)).toThrow(/increasing/i);
  });

  it('anchors a session to its local wall clock on an offset-change day', () => {
    const source = ['2026-03-08T14:15:00Z', '2026-03-08T14:45:00Z', '2026-03-08T15:45:00Z']
      .map((time, i) => ({ ...bars(3)[i], time: Date.parse(time) / 1000 }));
    const options = { timezone: 'America/New_York', session: '0930-1600' };
    expect(securitySeries(source, '2h', options).isNew).toEqual([true, false, true]);
    expect(securityExpression(source, '2h', expression, options).close).toEqual([null, null, 2]);
  });

  it('uses requested calendar periods across month boundaries', () => {
    const source = ['2026-01-02T00:00:00Z', '2026-01-31T00:00:00Z', '2026-02-01T00:00:00Z']
      .map((time, i) => ({ ...bars(3)[i], time: Date.parse(time) / 1000 }));
    const dispose = registerInterval({ code: 'expression-month', bucketing: { mode: 'calendar', unit: 'month' } });
    try {
      expect(securityExpression(source, 'expression-month', expression, { timezone: 'UTC' }).close).toEqual([null, null, 2]);
    } finally { dispose(); }
  });

  it('normalizes non-finite results and rejects changing output columns', () => {
    expect(securityExpression(bars(3), '3m', input => ({ invalid: input.map(() => Infinity) }), { mode: 'lookahead' }).invalid)
      .toEqual([null, null, null]);
    let call = 0;
    expect(() => securityExpression(bars(3), '3m', input => ({ [String(call++)]: input.map(() => 1) }), { mode: 'developing' }))
      .toThrow(/keys/i);
  });

  it('isolates expression inputs from the caller and later developing updates', () => {
    const source = bars(3);
    const original = structuredClone(source);
    const inputs: (readonly Readonly<Bar>[])[] = [];
    securityExpression(source, '3m', input => {
      inputs.push(input);
      expect(() => { (input[0] as Bar).close = 99; }).toThrow(TypeError);
      expect(() => { (input as Bar[]).push(source[0]); }).toThrow(TypeError);
      return expression(input);
    }, { mode: 'developing' });
    expect(source).toEqual(original);
    expect(inputs.map(input => input[0].close)).toEqual([1, 2, 3]);
    expect(inputs.map(input => input[0].volume)).toEqual([10, 20, 30]);
  });

  it('retains zero and negative OHLC observations with sparse optional data', () => {
    const source: Bar[] = [
      { time: 0, open: NaN, high: NaN, low: NaN, close: NaN },
      { time: 60, open: -3, high: 0, low: -4, close: -2, volume: 0, oi: 7 },
      { time: 120, open: -2, high: -1, low: -5, close: 0, oi: 0 },
      { time: 180, open: 0, high: 1, low: -1, close: 1 },
    ];
    const result = securityExpression(source, '3m', input => ({
      open: input.map(bar => bar.open), high: input.map(bar => bar.high),
      low: input.map(bar => bar.low), ...expression(input),
    }), { timezone: 'UTC' });
    expect(Object.fromEntries(Object.entries(result).map(([key, values]) => [key, values[3]])))
      .toEqual({ open: -3, high: 0, low: -5, close: 0, mean: null, volume: 0, oi: 0 });
  });
});
