import { describe, expect, it } from 'vitest';
import { RenkoTransform } from '../src/transform/renko';
import { PointFigureTransform } from '../src/transform/point-figure';
import { runTransform } from '../src/transform/transform';
import type { Bar } from '../src/model/bar';

const bar = (time: number, open: number, high: number, low: number, close: number): Bar => ({ time, open, high, low, close });
const closes = (values: number[]): Bar[] => values.map((c, i) => bar(i, c, c, c, c));

describe('Renko brick sizing and prices', () => {
  it('keeps the fixed close-driven bricks it always built', () => {
    const bricks = runTransform(new RenkoTransform({ boxSize: 1 }), closes([100, 102.5, 101]));
    expect(bricks.map(b => [b.open, b.close])).toEqual([[100, 101], [101, 102], [102, 101]]);
  });

  it('sizes each brick as a percent of the price it starts from', () => {
    const bricks = runTransform(new RenkoTransform({ mode: 'percent', percent: 1 }), closes([100, 104]));
    expect(bricks.map(b => b.close - b.open)).toEqual([1, 1.01, 1.0201].map(v => expect.closeTo(v, 9)));
  });

  it('sizes bricks from the ATR, a percent of the ATR being the ATR mode with the multiplier over 100', () => {
    const bars = Array.from({ length: 30 }, (_, i) => bar(i, 100 + i, 102 + i, 98 + i, 101 + i));
    // The anchor bar ranges 4, so a one-bar ATR of 4 times 1.5 makes the first brick 6 tall.
    const atr = runTransform(new RenkoTransform({ mode: 'atr', atrPeriod: 1, atrMultiplier: 1.5 }), bars);
    expect(atr[0]!.close - atr[0]!.open).toBeCloseTo(6);
    const share = runTransform(new RenkoTransform({ mode: 'atrPercent', atrPeriod: 1, percent: 150 }), bars);
    expect(share).toEqual(atr);
  });

  it('builds bricks from the wick with high and low prices, low first on an up bar', () => {
    const bars = [bar(0, 100, 100, 100, 100), bar(1, 100, 102, 97, 101)];
    expect(runTransform(new RenkoTransform({ boxSize: 1 }), bars).map(b => b.close)).toEqual([101]);
    expect(runTransform(new RenkoTransform({ boxSize: 1, method: 'hl' }), bars).map(b => b.close)).toEqual([99, 98, 97, 98, 99, 100, 101, 102]);
  });

  it('rejects a percent mode without a percent', () => {
    expect(() => new RenkoTransform({ mode: 'percent' })).toThrow();
    expect(() => new RenkoTransform({ mode: 'atrPercent' })).toThrow();
  });
});

describe('point and figure percent of ATR', () => {
  it('matches the ATR mode with the multiplier divided by 100', () => {
    const bars = Array.from({ length: 40 }, (_, i) => bar(i, 100 + Math.sin(i / 3) * 8, 102 + Math.sin(i / 3) * 8, 98 + Math.sin(i / 3) * 8, 100 + Math.sin(i / 3) * 8));
    const share = runTransform(new PointFigureTransform({ mode: 'atrPercent', percent: 50, atrPeriod: 5 }), bars);
    const atr = runTransform(new PointFigureTransform({ mode: 'atr', atrMultiplier: 0.5, atrPeriod: 5 }), bars);
    expect(share).toEqual(atr);
    expect(share.length).toBeGreaterThan(1);
  });
});
