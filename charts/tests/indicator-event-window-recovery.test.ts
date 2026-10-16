import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { indicatorDefaults } from '../src/model/indicator-registry';
import { ALPHATREND } from '../src/indicators/studies';
import { WAVETREND } from '../src/indicators/wavetrend';
import { windowMean } from '../src/indicators/window-mean';

const bars = (count: number): Bar[] => Array.from({ length: count }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i / 4, high: 101 + i / 4,
  low: 99 + i / 4, close: 100 + i / 4, volume: 0,
}));

const wave = (data: readonly Bar[]) => WAVETREND.calc(data, {
  ...indicatorDefaults(WAVETREND), source: 'close', n1: 3, n2: 4,
  sigLen: 2, filterZone: false,
}, {});

const alpha = (data: readonly Bar[], period = 2) => ALPHATREND.calc(data, {
  ...indicatorDefaults(ALPHATREND), AP: period,
}, {});

describe('event-sensitive finite window means', () => {
  it('keeps equal WaveTrend lines equal without inventing a crossing on a ramp', () => {
    const result = wave(bars(10));
    const reading = 1 / 0.015;
    expect(result.wt1.slice(7)).toEqual([reading, reading, reading]);
    expect(result.wt2.slice(8)).toEqual([reading, reading]);
    expect(result.mom.slice(8)).toEqual([0, 0]);
    expect(result.buy).toEqual(Array(10).fill(null));
    expect(result.sell).toEqual(Array(10).fill(null));
  });

  it('matches a fresh chronological signal window through a changing oscillator', () => {
    const data = bars(160).map((bar, i) => ({ ...bar, close: 100 + (i % 17) / 4 }));
    const result = WAVETREND.calc(data, {
      ...indicatorDefaults(WAVETREND), source: 'close', n1: 3, n2: 4,
      sigLen: 7, filterZone: false,
    }, {});
    for (let i = 13; i < data.length; i++) {
      const expected = result.wt1.slice(i - 6, i + 1).reduce<number>((sum, value) => sum + value!, 0) / 7;
      expect(result.wt2[i]).toBe(expected);
      const before = result.wt1[i - 1]! - result.wt2[i - 1]!;
      const after = result.wt1[i]! - expected;
      if (i > 13) {
        expect(result.buy[i]).toBe(before <= 0 && after > 0 ? expected : null);
        expect(result.sell[i]).toBe(before >= 0 && after < 0 ? expected : null);
      }
    }
  });

  it('recovers AlphaTrend after an overflowing sum leaves the current window', () => {
    const data = bars(5).map((bar, i) => ({
      ...bar, open: 100, close: 100, high: i === 1 || i === 2 ? 1e308 : 102,
      low: i === 1 || i === 2 ? 0 : 98,
    }));
    const result = alpha(data);
    // The second full window has sum 2e308. Later sums are finite again:
    // (1e308 + 4) / 2, then (4 + 4) / 2, so the upward clamp recovers.
    expect(result.alphatrend).toEqual([null, null, null, 0, 94]);
    expect(result.lagged).toEqual([null, null, null, null, null]);
  });

  it('keeps AlphaTrend warmup and missing-window gaps, then recovers', () => {
    const data = bars(9).map((bar, i) => ({
      ...bar, open: 100, close: 100, high: i === 4 ? NaN : 102, low: 98,
    }));
    expect(alpha(data).alphatrend).toEqual([null, null, 94, 94, null, null, 94, 94, 94]);
  });

  it('rejects an overflowing money flow and recovers after it leaves the window', () => {
    const closes = [100, 101, 100, 101, 100, 102];
    const data = bars(closes.length).map((bar, i) => ({
      ...bar, open: closes[i], close: closes[i], high: closes[i] + 1,
      low: closes[i] - 1, volume: i === 1 ? 1e308 : 1,
    }));
    // At index 3, up/down flows are 101/100, both finite again. All later
    // gauges remain above 50, so the lower band rises from 98 to 98.5.
    expect(alpha(data).alphatrend).toEqual([null, null, null, 98, 98, 98.5]);
  });

  it('checks flow availability before the no-down-flow shortcut', () => {
    const data = bars(4).map((bar, i) => ({
      ...bar, open: 100 + i, close: 100 + i, high: 101 + i,
      low: 99 + i, volume: i === 1 ? 1e308 : 1,
    }));
    expect(alpha(data).alphatrend).toEqual([null, null, null, 100]);
  });

  it('resumes WaveTrend after a missing source without a cross-gap event', () => {
    const data = bars(24).map((bar, i) => ({ ...bar, close: i === 15 ? NaN : bar.close }));
    const result = wave(data);
    expect(result.wt1.slice(0, 7)).toEqual(Array(7).fill(null));
    expect(result.wt2.slice(0, 8)).toEqual(Array(8).fill(null));
    expect(result.wt1[14]).not.toBeNull();
    expect(result.wt1.slice(15)).toEqual([null, 72, 69.86666666666667, 67.18315789473685, 65.4950799220273, 64.80429433002797, 64.75322336418594, 65.01162983600206, 65.3659522605756]);
    expect(result.wt2.slice(15)).toEqual([null, null, 70.93333333333334, 68.52491228070176, 66.33911890838208, 65.14968712602763, 64.77875884710696, 64.88242660009399, 65.18879104828883]);
    expect(result.buy.slice(15, 18)).toEqual([null, null, null]);
    expect(result.sell.slice(15, 18)).toEqual([null, null, null]);
    expect(result.buy[22]).toBe(64.88242660009399);
  });

  it('recalculates a forming tail without retaining its transient signal', () => {
    const original = bars(20);
    const before = wave(original);
    const changed = original.map((bar, i) => i === 19 ? { ...bar, close: 50 } : bar);
    expect(wave(changed).wt1[19]).not.toBe(before.wt1[19]);
    expect(wave(original)).toEqual(before);
  });

  it('reads only each current window at the largest supported AlphaTrend period', () => {
    let reads = 0;
    const data = Array.from({ length: 5000 }, () => 1);
    const observed = new Proxy(data, {
      get(target, key, receiver): unknown {
        if (typeof key === 'string' && /^\d+$/.test(key)) reads++;
        return Reflect.get(target, key, receiver);
      },
    });
    const result = windowMean(observed, 500);
    expect(result.slice(0, 499).every(Number.isNaN)).toBe(true);
    expect(result.slice(499)).toEqual(Array(4501).fill(1));
    // At most two validity reads per input accompany the current-window sums.
    expect(reads).toBeLessThanOrEqual(4501 * 500 + 2 * data.length);
  });
});
