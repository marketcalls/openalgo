import { describe, it, expect } from 'vitest';
import { conflationGroupSize, conflateBars, mergeBars, conflateItems } from '../src/model/conflation';
import type { Bar } from '../src/model/bar';

const bar = (time: number, o: number, h: number, l: number, c: number, v?: number): Bar => ({ time, open: o, high: h, low: l, close: c, volume: v });

describe('conflationGroupSize', () => {
  it('is 1 (no conflation) while bars are wide enough', () => {
    expect(conflationGroupSize(8, 2)).toBe(1);
    expect(conflationGroupSize(1, 1)).toBe(1); // 1px >= 0.5px threshold
  });
  it('groups more bars as they shrink below the threshold', () => {
    expect(conflationGroupSize(0.25, 1)).toBe(2); // 0.25px: ceil(0.5/0.25)=2
    expect(conflationGroupSize(0.1, 1)).toBe(5);
    expect(conflationGroupSize(0.1, 1, 0.5, 2)).toBe(10); // factor doubles aggressiveness
  });
});

describe('mergeBars (OHLC-preserving)', () => {
  it('open=first, close=last, high=max, low=min, volume=sum', () => {
    const m = mergeBars([
      bar(1, 10, 12, 9, 11, 100),
      bar(2, 11, 15, 8, 14, 200),
      bar(3, 14, 14, 7, 9, 50),
    ]);
    expect(m).toMatchObject({ time: 1, open: 10, high: 15, low: 7, close: 9, volume: 350 });
  });
  it('omits volume when no bar has it', () => {
    const m = mergeBars([bar(1, 10, 12, 9, 11), bar(2, 11, 13, 10, 12)]);
    expect(m.volume).toBeUndefined();
  });
});

describe('conflateBars', () => {
  const bars = [
    bar(1, 10, 12, 9, 11, 1), bar(2, 11, 13, 10, 12, 1), bar(3, 12, 14, 11, 13, 1),
    bar(4, 13, 15, 12, 14, 1), bar(5, 14, 16, 13, 15, 1),
  ];

  it('is identity for groupSize <= 1', () => {
    expect(conflateBars(bars, 1)).toEqual(bars);
  });

  it('merges in groups while preserving overall extremes (lossless OHLC)', () => {
    const out = conflateBars(bars, 2);
    expect(out).toHaveLength(3); // [1,2],[3,4],[5]
    // first conflated bar covers bars 1-2
    expect(out[0]).toMatchObject({ open: 10, high: 13, low: 9, close: 12 });
    // the global extremes survive: overall high/low equal the union of conflated bars
    const gHigh = Math.max(...out.map((b) => b.high));
    const gLow = Math.min(...out.map((b) => b.low));
    expect(gHigh).toBe(Math.max(...bars.map((b) => b.high)));
    expect(gLow).toBe(Math.min(...bars.map((b) => b.low)));
    // total volume preserved
    expect(out.reduce((s, b) => s + (b.volume ?? 0), 0)).toBe(bars.length);
  });
});

describe('conflateItems', () => {
  it('merges draw items and centres x on the group', () => {
    const items = [
      { x: 10, bar: bar(1, 10, 12, 9, 11) },
      { x: 20, bar: bar(2, 11, 14, 8, 13) },
    ];
    const out = conflateItems(items, 2);
    expect(out).toHaveLength(1);
    expect(out[0].x).toBe(15); // (10+20)/2
    expect(out[0].bar).toMatchObject({ open: 10, high: 14, low: 8, close: 13 });
  });
});
