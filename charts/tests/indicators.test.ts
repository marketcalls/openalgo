import { describe, it, expect } from 'vitest';
import { rsi, rsiSeries } from '../src/indicators/rsi';
import { sma } from '../src/indicators/calc';
import { atr, trueRange } from '../src/indicators/atr';
import { supertrend, supertrendSeries } from '../src/indicators/supertrend';
import type { Bar } from '../src/model/bar';

describe('RSI (Wilder)', () => {
  it('matches the canonical Wilder/StockCharts worked example', () => {
    // The textbook 14-period RSI example; first RSI value ≈ 70.53.
    const closes = [
      44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245,
      45.8433, 46.0826, 45.8931, 46.0328, 45.6140, 46.2820, 46.2820,
    ];
    const r = rsi(closes, 14);
    expect(r[14]).toBeCloseTo(70.53, 0); // within 0.5
  });

  it('warmup is NaN; values stay within 0..100', () => {
    const closes = Array.from({ length: 40 }, (_, i) => 100 + Math.sin(i / 3) * 5);
    const r = rsi(closes, 14);
    for (let i = 0; i < 14; i++) expect(Number.isNaN(r[i])).toBe(true);
    for (let i = 14; i < r.length; i++) {
      expect(r[i]).toBeGreaterThanOrEqual(0);
      expect(r[i]).toBeLessThanOrEqual(100);
    }
  });

  it('is 100 for a pure uptrend and 0 for a pure downtrend', () => {
    const up = Array.from({ length: 20 }, (_, i) => 100 + i);
    const down = Array.from({ length: 20 }, (_, i) => 100 - i);
    expect(rsi(up, 14).slice(-1)[0]).toBe(100);
    expect(rsi(down, 14).slice(-1)[0]).toBe(0);
  });

  it('rsiSeries carries NaN during warmup, then values', () => {
    const bars: Bar[] = Array.from({ length: 30 }, (_, i) => ({ time: i, open: 0, high: 0, low: 0, close: 100 + i }));
    const s = rsiSeries(bars, 14);
    expect(Number.isNaN(s[0].close)).toBe(true);
    expect(Number.isFinite(s[29].close)).toBe(true);
    expect(s[29].close).toBeCloseTo(100, 0); // sustained uptrend: about 100
  });
});

describe('ATR (Wilder)', () => {
  it('true range of the first bar is high-low', () => {
    expect(trueRange([10], [8], [9])).toEqual([2]);
  });

  it('a constant range gives a constant ATR', () => {
    const high = Array.from({ length: 30 }, () => 12);
    const low = Array.from({ length: 30 }, () => 10);
    const close = Array.from({ length: 30 }, () => 11);
    const a = atr(high, low, close, 14);
    expect(Number.isNaN(a[12])).toBe(true);
    expect(a[13]).toBeCloseTo(2, 6);
    expect(a.slice(-1)[0]).toBeCloseTo(2, 6);
  });
});

describe('Supertrend', () => {
  const trendBars = (dir: 1 | -1): Bar[] =>
    Array.from({ length: 60 }, (_, i) => {
      const mid = 100 + dir * i; // rising or falling
      return { time: i, open: mid, high: mid + 1, low: mid - 1, close: mid };
    });

  it('settles to uptrend (-1, support below price) in a rising market', () => {
    const bars = trendBars(1);
    const st = supertrend(bars, 10, 3);
    const last = st.slice(-1)[0]!;
    expect(last.direction).toBe(-1);
    expect(last.value).toBeLessThan(bars.slice(-1)[0]!.close);
  });

  it('settles to downtrend (+1, resistance above price) in a falling market', () => {
    const bars = trendBars(-1);
    const st = supertrend(bars, 10, 3);
    const last = st.slice(-1)[0]!;
    expect(last.direction).toBe(1);
    expect(last.value).toBeGreaterThan(bars.slice(-1)[0]!.close);
  });

  it('splits into up/down series with no overlap (each bar in at most one)', () => {
    const bars = trendBars(1);
    const { up, down } = supertrendSeries(bars, 10, 3);
    expect(up).toHaveLength(bars.length);
    expect(down).toHaveLength(bars.length);
    for (let i = 0; i < bars.length; i++) {
      const upActive = Number.isFinite(up[i].close);
      const downActive = Number.isFinite(down[i].close);
      expect(upActive && downActive).toBe(false); // never both
    }
    // a sustained uptrend: the up line is populated near the end
    expect(Number.isFinite(up.slice(-1)[0]!.close)).toBe(true);
  });
});

describe('sma recovers from a warmup gap', () => {
  it('is not poisoned forever by a leading NaN', () => {
    // A running sum that absorbs NaN stays NaN for the rest of the series, so
    // any indicator chained onto one with a warmup produced nothing at all.
    const values = [NaN, NaN, 1, 2, 3, 4, 5, 6];
    const out = sma(values, 3);
    expect(Number.isNaN(out[3])).toBe(true);   // window still holds a NaN
    expect(out[4]).toBeCloseTo(2, 9);          // 1+2+3: recovered
    expect(out[7]).toBeCloseTo(5, 9);          // 4+5+6
  });

  it('reports NaN only while the gap is inside the window', () => {
    const out = sma([1, 2, NaN, 4, 5, 6], 2);
    expect(out[1]).toBeCloseTo(1.5, 9);
    expect(Number.isNaN(out[2])).toBe(true);
    expect(Number.isNaN(out[3])).toBe(true);
    expect(out[4]).toBeCloseTo(4.5, 9);        // the gap has left the window
  });
});
