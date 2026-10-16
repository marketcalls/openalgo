import { describe, expect, it } from 'vitest';
import { STOCK_BARS_SOURCE } from '../website/components/synthetic-market';

interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number }
describe('website synthetic market bars', () => {
  it('repeats a seeded series with coherent OHLC, varied bodies, volume and occasional gaps', () => {
    const stockBars = new Function(`${STOCK_BARS_SOURCE}\nreturn stockBars;`)() as
      (startTime: number, count: number, intervalSec: number, startPrice: number, seed: number, volatility?: number, baseVolume?: number) => Bar[];
    const bars = stockBars(1700000000, 150, 300, 23800, 173, 0.0015, 2500);
    expect(stockBars(1700000000, 150, 300, 23800, 173, 0.0015, 2500)).toEqual(bars);
    expect(stockBars(1700000000, 150, 300, 23800, 174, 0.0015, 2500)).not.toEqual(bars);
    expect(bars).toHaveLength(150);
    for (const [i, bar] of bars.entries()) {
      expect(bar.time).toBe(1700000000 + i * 300);
      expect(bar.high).toBeGreaterThanOrEqual(Math.max(bar.open, bar.close));
      expect(bar.low).toBeLessThanOrEqual(Math.min(bar.open, bar.close));
      expect(bar.low).toBeGreaterThan(0);
      expect(bar.volume).toBeGreaterThan(0);
      for (const price of [bar.open, bar.high, bar.low, bar.close]) expect(price * 100).toBeCloseTo(Math.round(price * 100), 7);
    }
    expect(bars.filter(bar => bar.close > bar.open).length).toBeGreaterThan(35);
    expect(bars.filter(bar => bar.close < bar.open).length).toBeGreaterThan(35);
    expect(new Set(bars.map(bar => bar.volume)).size).toBeGreaterThan(100);
    expect(Math.max(...bars.map(bar => bar.volume))).toBeGreaterThan(Math.min(...bars.map(bar => bar.volume)) * 2);
    expect(bars.slice(1).filter((bar, i) => Math.abs(bar.open - bars[i].close) > 20).length).toBeGreaterThan(0);
    expect(Math.max(...bars.map(bar => bar.close)) - Math.min(...bars.map(bar => bar.close))).toBeGreaterThan(80);
  });
});
