import { describe, expect, it } from 'vitest';
import { volumePoint, volumeAverage, volumeAveragePoint, volumeValues } from '../src/volume.js';

describe('reference volume', () => {
  it('matches candle overrides and previous-close direction', () => {
    const bar = { time: 1, open: 100, high: 102, low: 98, close: 101, volume: 50 };
    const style = { upColor: '#11aa22', downColor: '#cc3344', colorByPreviousClose: true };
    expect(volumePoint(bar, 102, style, true).color).toBe('#cc3344');
    expect(volumePoint(bar, undefined, style, true).color).toBe('#11aa22');
    expect(volumePoint({ ...bar, color: '#123456' }, 102, style, true).color).toBe('#123456');
    expect(volumePoint(bar, 102, style, false).color).toBeUndefined();
  });

  it('keeps the average warmup and unknown volume as gaps and computes a live tail from one window', () => {
    const bars = [10, 20, 30, 40].map((close, time) => ({ time, close }));
    expect(volumeAverage(bars, 3).map(bar => bar.close)).toEqual([NaN, NaN, 20, 30]);
    bars[3].close = 60;
    expect(volumeAveragePoint(bars, 3, 3).close).toBeCloseTo(110 / 3);
    bars.push({ time: 4, close: 50 });
    expect(volumeAveragePoint(bars, 4, 3).close).toBeCloseTo(140 / 3);
    bars[2].close = NaN;
    expect(volumeAverage(bars, 3).map(bar => bar.close)).toEqual([NaN, NaN, NaN, NaN, NaN]);
    expect(volumePoint({ time: 1, open: 1, close: 2 }, undefined, {}, true).close).toBeNaN();
  });

  it('validates saved values and limits averaging windows', () => {
    expect(volumeValues({ 'volume.maPeriod': 0, 'volume.showMA': 'yes', extra: true }))
      .toMatchObject({ 'volume.maPeriod': 1, 'volume.showMA': false });
    expect(volumeValues({ 'volume.maPeriod': 501 })['volume.maPeriod']).toBe(500);
    expect(volumeValues({ 'volume.maPeriod': NaN })['volume.maPeriod']).toBe(20);
    expect(volumeValues({ 'volume.maStyle': 'invalid' })['volume.maStyle']).toBe('solid');
  });
});
