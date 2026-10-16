import { describe, expect, it, vi } from 'vitest';
import type { Bar } from '../src/model/bar';
import {
  alignRequestedExpression, requestedIntrabars,
  type RequestedBarsSnapshot, type RequestedExpression,
} from '../src/indicators/requested-context';
import * as indicatorExports from '../src/indicators/index';

const bar = (time: number, close: number): Bar => ({ time, open: close, high: close, low: close, close });
const snapshot = (values = [10, 20, 30], times = [0, 120, 240], availableAt = [60, 180, 300]): RequestedBarsSnapshot => ({
  bars: values.map((value, i) => bar(times[i], value)), availableAt, confirmed: values.map(() => true),
});
const close: RequestedExpression = bars => ({ close: bars.map(value => value.close) });
const average: RequestedExpression = bars => ({
  mean: bars.map((value, i) => i === 0 ? null : (value.close + bars[i - 1].close) / 2),
});
const windows = [{ start: 0, end: 180 }, { start: 180, end: 360 }];
const minutes = () => snapshot([1, 2, 3, 4, 5, 6], [0, 60, 120, 180, 240, 300], [60, 120, 180, 240, 300, 360]);

describe('requested expression alignment', () => {
  it('calculates on requested observations before carrying aligned values', () => {
    const expression = vi.fn(average);
    expect(alignRequestedExpression([0, 60, 120, 180, 240, 300], snapshot(), expression).mean)
      .toEqual([null, null, null, 15, 15, 25]);
    expect(expression).toHaveBeenCalledTimes(1);
    expect(expression.mock.calls[0][0].map(value => value.close)).toEqual([10, 20, 30]);
  });

  it('emits only newly selected requested rows with missing gaps', () => {
    expect(alignRequestedExpression([0, 60, 120, 180, 240, 300], snapshot(), average, { gaps: 'missing' }).mean)
      .toEqual([null, null, null, 15, null, 25]);
    expect(alignRequestedExpression([200, 220, 300], snapshot(), close, { gaps: 'missing' }).close)
      .toEqual([20, null, 30]);
  });

  it('waits for delayed prefix observations before exposing later calculations', () => {
    const delayed = { ...snapshot(), availableAt: [200, 180, 300] };
    expect(alignRequestedExpression([60, 180, 199, 200, 250, 300], delayed, average).mean)
      .toEqual([null, null, null, 15, 15, 25]);
    expect(alignRequestedExpression([200, 250, 300], delayed, close, { gaps: 'missing' }).close)
      .toEqual([20, null, 30]);
  });

  it.each(['unknown', 'unconfirmed'] as const)('blocks an %s interior observation without compacting history', reason => {
    const input = snapshot();
    const blocked: RequestedBarsSnapshot = reason === 'unknown'
      ? { ...input, availableAt: [60, null, 300] }
      : { ...input, confirmed: [true, false, true] };
    const expression = vi.fn(average);
    expect(alignRequestedExpression([60, 180, 300, 1000], blocked, expression).mean)
      .toEqual([null, null, null, null]);
    expect(expression.mock.calls[0][0].map(value => value.close)).toEqual([10, 20, 30]);
    expect(alignRequestedExpression([60, 300, 1000], blocked, close).close).toEqual([10, 10, 10]);
    expect(alignRequestedExpression([60, 300, 1000], blocked, close, { gaps: 'missing' }).close).toEqual([10, null, null]);
  });

  it('keeps newer missing results instead of carrying an older finite result', () => {
    const expression: RequestedExpression = () => ({ a: [10, null, NaN], b: [0, Infinity, -Infinity] });
    const result = alignRequestedExpression([60, 120, 180, 240, 300], snapshot(), expression);
    expect(result.a).toEqual([10, 10, null, null, null]);
    expect(result.b).toEqual([0, 0, null, null, null]);
  });

  it('keeps eligibility stable when future confirmed history is added', () => {
    const full = snapshot();
    const prefix = { bars: full.bars.slice(0, 2), availableAt: full.availableAt.slice(0, 2), confirmed: full.confirmed.slice(0, 2) };
    const times = [0, 60, 180, 250];
    expect(alignRequestedExpression(times, full, average)).toEqual(alignRequestedExpression(times, prefix, average));
  });

  it('handles negative and fractional timestamps and simultaneous availability', () => {
    const input = snapshot([0, -2], [-2.5, -1.5], [0, 0]);
    expect(alignRequestedExpression([-1, 0, 0.5], input, close).close).toEqual([null, -2, -2]);
  });
});

describe('requested intrabar arrays', () => {
  it('groups requested results without restarting expression history at each window', () => {
    const expression = vi.fn(bars => ({ ...close(bars), ...average(bars) })) as ReturnType<typeof vi.fn<RequestedExpression>>;
    const result = requestedIntrabars(windows, minutes(), expression);
    expect(result.times).toEqual([[0, 60, 120], [180, 240, 300]]);
    expect(result.values.close).toEqual([[1, 2, 3], [4, 5, 6]]);
    expect(result.values.mean).toEqual([[null, 1.5, 2.5], [3.5, 4.5, 5.5]]);
    expect(expression).toHaveBeenCalledTimes(1);
  });

  it('clips to both window ends and the inclusive availability cutoff', () => {
    expect(requestedIntrabars(windows, minutes(), close, { asOf: 270 }).values.close).toEqual([[1, 2, 3], [4]]);
    expect(requestedIntrabars(windows, minutes(), close, { asOf: 240 }).times).toEqual([[0, 60, 120], [180]]);
    expect(requestedIntrabars(windows, minutes(), close, { asOf: -1 }).times).toEqual([[], []]);
  });

  it('does not move a delayed observation into another window or fill absent bars', () => {
    const input = { ...minutes(), availableAt: [60, 120, 200, 240, 300, 360] };
    expect(requestedIntrabars(windows, input, close).values.close).toEqual([[1, 2], [4, 5, 6]]);
    const sparse = snapshot([1, 5], [0, 240], [60, 300]);
    expect(requestedIntrabars([{ start: -180, end: 0 }, ...windows], sparse, close).times).toEqual([[], [0], [240]]);
  });

  it('requires the confirmed prefix even when earlier observations are outside all windows', () => {
    const input = { ...minutes(), confirmed: [true, false, true, true, true, true] };
    expect(requestedIntrabars([windows[1]], input, close).values.close).toEqual([[]]);
    const delayed = { ...minutes(), availableAt: [400, 120, 180, 240, 300, 360] };
    expect(requestedIntrabars(windows, delayed, close).times).toEqual([[], []]);
  });

  it('normalizes missing and nonfinite expression values while retaining row positions', () => {
    const input = snapshot([1, 2, 3], [0, 60, 120], [60, 120, 180]);
    const result = requestedIntrabars([windows[0]], input, () => ({ a: [null, NaN, Infinity] }));
    expect(result.times).toEqual([[0, 60, 120]]);
    expect(result.values.a).toEqual([[null, null, null]]);
  });
});

describe('requested helper validation and ownership', () => {
  it('exports both helpers through the indicator tier', () => {
    expect(indicatorExports.alignRequestedExpression).toBe(alignRequestedExpression);
    expect(indicatorExports.requestedIntrabars).toBe(requestedIntrabars);
  });

  it('rejects invalid callbacks even when the requested snapshot is empty', () => {
    const input: RequestedBarsSnapshot = { bars: [], availableAt: [], confirmed: [] };
    expect(() => alignRequestedExpression([], input, null as never)).toThrow(/expression/i);
    expect(() => requestedIntrabars([], input, null as never)).toThrow(/expression/i);
  });

  it('returns empty structures without invoking an expression for empty requested history', () => {
    const expression = vi.fn(() => { throw new Error('empty callback'); });
    const input: RequestedBarsSnapshot = { bars: [], availableAt: [], confirmed: [] };
    expect(alignRequestedExpression([0, 1], input, expression)).toEqual({});
    expect(requestedIntrabars(windows, input, expression)).toEqual({ times: [[], []], values: {} });
    expect(expression).not.toHaveBeenCalled();
  });

  it('retains column names for empty target lists with nonempty requested history', () => {
    expect(alignRequestedExpression([], snapshot(), average)).toEqual({ mean: [] });
    expect(requestedIntrabars([], snapshot(), average)).toEqual({ times: [], values: { mean: [] } });
  });

  it('copies and freezes expression inputs and leaves metadata and target windows untouched', () => {
    const input = minutes();
    const saved = structuredClone(input);
    const target = structuredClone(windows);
    const expression: RequestedExpression = bars => {
      expect(bars).not.toBe(input.bars);
      expect(bars[0]).not.toBe(input.bars[0]);
      expect(() => { (bars[0] as Bar).close = 99; }).toThrow(TypeError);
      expect(() => { (bars as Bar[]).pop(); }).toThrow(TypeError);
      return close(bars);
    };
    alignRequestedExpression([0, 60], input, expression);
    requestedIntrabars(target, input, expression);
    expect(input).toEqual(saved);
    expect(target).toEqual(windows);
  });

  it.each([
    null, [], {},
    { ...snapshot(), availableAt: [60] },
    { ...snapshot(), confirmed: [true] },
    { ...snapshot(), availableAt: [60, 180, Infinity] },
    { ...snapshot(), availableAt: [60, 119, 300] },
    { ...snapshot(), availableAt: [60, undefined, 300] },
    { ...snapshot(), confirmed: [true, 1, true] },
    { ...snapshot(), bars: [bar(0, 1), bar(0, 2), bar(240, 3)] },
    { ...snapshot(), bars: [bar(0, 1), bar(240, 2), bar(120, 3)] },
    { ...snapshot(), bars: [bar(0, 1), bar(120, 2), bar(NaN, 3)] },
    { ...snapshot(), bars: [bar(0, 1), null, bar(240, 3)] },
  ])('rejects malformed snapshots before invoking the expression (%#)', input => {
    const expression = vi.fn(close);
    expect(() => alignRequestedExpression([0], input as never, expression)).toThrow();
    expect(() => requestedIntrabars(windows, input as never, expression)).toThrow();
    expect(expression).not.toHaveBeenCalled();
  });

  it('validates later metadata even after an unknown prefix barrier', () => {
    const expression = vi.fn(close);
    const input = { ...snapshot(), availableAt: [null, 180, 239] };
    expect(() => alignRequestedExpression([0], input, expression)).toThrow(/availability/i);
    expect(expression).not.toHaveBeenCalled();
  });

  it.each([null, {}, [0, 0], [2, 1], [NaN], [Infinity], ['1']])('rejects invalid target times before evaluating (%#)', times => {
    const expression = vi.fn(close);
    expect(() => alignRequestedExpression(times as never, snapshot(), expression)).toThrow();
    expect(expression).not.toHaveBeenCalled();
  });

  it.each([
    null, {}, [null], [{ start: 0, end: 0 }], [{ start: 1, end: 0 }],
    [{ start: 0, end: Infinity }], [{ start: NaN, end: 1 }],
    [{ start: 0, end: 2 }, { start: 1, end: 3 }],
    [{ start: 3, end: 4 }, { start: 0, end: 1 }],
  ])('rejects invalid or overlapping windows before evaluating (%#)', target => {
    const expression = vi.fn(close);
    expect(() => requestedIntrabars(target as never, snapshot(), expression)).toThrow();
    expect(expression).not.toHaveBeenCalled();
  });

  it.each([null, [], { gaps: 'none' }, { gaps: 1 }])('rejects malformed alignment options (%#)', options => {
    const expression = vi.fn(close);
    expect(() => alignRequestedExpression([0], snapshot(), expression, options as never)).toThrow();
    expect(expression).not.toHaveBeenCalled();
  });

  it.each([null, [], { asOf: NaN }, { asOf: Infinity }, { asOf: '1' }])('rejects malformed intrabar options (%#)', options => {
    const expression = vi.fn(close);
    expect(() => requestedIntrabars(windows, snapshot(), expression, options as never)).toThrow();
    expect(expression).not.toHaveBeenCalled();
  });

  it.each([null, [], { short: [1] }, { wrong: [1, '2', 3] }, { empty: undefined }])('rejects malformed expression results (%#)', result => {
    expect(() => alignRequestedExpression([0], snapshot(), () => result as never)).toThrow(/expression/i);
    expect(() => requestedIntrabars(windows, snapshot(), () => result as never)).toThrow(/expression/i);
  });

  it('preserves arbitrary own column names without changing object prototypes', () => {
    const expression: RequestedExpression = () => Object.fromEntries([['__proto__', [1, 2, 3]], ['constructor', [4, 5, 6]]]);
    const aligned = alignRequestedExpression([60, 180], snapshot(), expression);
    expect(Object.keys(aligned)).toEqual(['__proto__', 'constructor']);
    expect(aligned.__proto__).toEqual([1, 2]);
    expect(Object.getPrototypeOf(aligned)).toBe(Object.prototype);
    const grouped = requestedIntrabars([{ start: 0, end: 400 }], snapshot(), expression);
    expect(grouped.values.__proto__).toEqual([[1, 2, 3]]);
    expect(Object.getPrototypeOf(grouped.values)).toBe(Object.prototype);
  });
});
