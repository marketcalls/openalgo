import { describe, expect, it } from 'vitest';
import * as Depth from '../website/components/depth-market';

type Bar = { time: number; open: number; high: number; low: number; close: number; volume?: number };
const { chartBar, makeDepth } = Depth as unknown as {
  chartBar(sequence: number, scenario: 'option-option' | 'spot-option'): Bar;
  makeDepth(frame: number, levels: number): { ltp: number; bids: Array<{ price: number }>; asks: Array<{ price: number }> };
};

describe('depth demo synthetic market', () => {
  it('keeps candles and ladder quotes aligned with varied candle direction', () => {
    const bars = Array.from({ length: 80 }, (_, i) => chartBar(i, 'option-option'));
    for (const [i, bar] of bars.entries()) {
      expect(bar.high).toBeGreaterThanOrEqual(Math.max(bar.open, bar.close));
      expect(bar.low).toBeLessThanOrEqual(Math.min(bar.open, bar.close));
      if (i > 0) expect(bar.open).toBe(bars[i - 1].close);
      expect(makeDepth(i, 5).ltp).toBe(bar.close);
    }
    expect(bars.filter(bar => bar.close > bar.open).length).toBeGreaterThan(10);
    expect(bars.filter(bar => bar.close < bar.open).length).toBeGreaterThan(10);
    expect(new Set(bars.map(bar => bar.volume)).size).toBeGreaterThan(50);
  });
});
