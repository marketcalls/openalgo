import { describe, expect, it } from 'vitest';
import type { Bar } from '../src/model/bar';
import { mergeBars } from '../src/model/conflation';
import { securitySeries } from '../src/indicators/security';
import { mapHistoryResponse } from '../src/feed/openalgo-rest';
import { CandleBuilder } from '../src/feed/candle-builder';
import { TickBarAggregator } from '../src/feed/tick-aggregator';
import { runTransform } from '../src/transform/transform';
import { HeikinAshiTransform } from '../src/transform/heikin-ashi';
import { RenkoTransform } from '../src/transform/renko';
import { RangeBarsTransform } from '../src/transform/range-bars';
import { LineBreakTransform } from '../src/transform/line-break';
import { PointFigureTransform } from '../src/transform/point-figure';
import { KagiTransform } from '../src/transform/kagi';
import { evaluateExpression, parseExpression } from '../src/transform/expression';

const bar = (time: number, oi?: number, close = 100): Bar => ({
  time, open: close, high: close + 1, low: close - 1, close, volume: 10,
  ...(oi === undefined ? {} : { oi }),
});
const readings = () => [100, 110, 120, 130, 140].map((oi, i) => bar(i * 60, oi));

describe('open interest is an optional level', () => {
  it('folds five readings to the last level while summing volume', () => {
    expect(mergeBars(readings())).toMatchObject({ oi: 140, volume: 50 });
  });

  it('keeps the latest defined historical level and a genuine zero', () => {
    expect(mergeBars([bar(0, 100), bar(60), bar(120, 0), bar(180)]).oi).toBe(0);
    expect(mergeBars([bar(0), bar(60)])).not.toHaveProperty('oi');
  });

  it('reads only the revealed level in a developing higher-timeframe bucket', () => {
    const values = securitySeries(readings(), '5m');
    expect(values.oi).toEqual([100, 110, 120, 130, 140]);
    expect(values.volume).toEqual([10, 20, 30, 40, 50]);
  });

  it('reads 140 in the completed bucket and never carries it into an empty bucket', () => {
    const rows = [...readings(), ...[300, 360, 420, 480, 540, 600].map(time => bar(time))];
    expect(securitySeries(rows, '5m', { offset: 1 }).oi)
      .toEqual([null, null, null, null, null, 140, 140, 140, 140, 140, null]);
    expect(securitySeries(rows, '5m').oi)
      .toEqual([100, 110, 120, 130, 140, null, null, null, null, null, null]);
    expect(securitySeries([], '5m').oi).toEqual([]);
  });

  it('preserves zero and absence at the history adapter boundary', () => {
    const rows = [bar(60, 150), bar(120), bar(180, 0)];
    expect(mapHistoryResponse({ status: 'success', data: rows }).map(row => row.oi))
      .toEqual([150, undefined, 0]);
  });

  it('omits unreadable optional history levels without manufacturing zero', () => {
    const rows = [bar(60, NaN), bar(120, Infinity), { ...bar(180), oi: null }];
    expect(mapHistoryResponse({ status: 'success', data: rows as Bar[] }).map(row => row.oi))
      .toEqual([undefined, undefined, undefined]);
  });

  it('removes the old candle level when a newer live quote has no reading', () => {
    const builder = new CandleBuilder();
    builder.seed(bar(60, 100));
    expect(builder.onTick({ time: 61, price: 102, ltq: 1 })?.bar).not.toHaveProperty('oi');
    expect(builder.onTick({ time: 62, price: 103, oi: 0 })?.bar.oi).toBe(0);
    expect(builder.onTick({ time: 63, price: 104 })?.bar).not.toHaveProperty('oi');
    expect(builder.onTick({ time: 64, price: 104, oi: NaN })?.bar).not.toHaveProperty('oi');
  });

  it('removes the old tick-bar level when the feed stops reporting it', () => {
    const builder = new TickBarAggregator({ mode: 'ticks', count: 5 });
    builder.onTick({ time: 60, price: 100, qty: 1, oi: 200 });
    expect(builder.onTick({ time: 61, price: 101, qty: 1 }).bar).not.toHaveProperty('oi');
    expect(builder.onTick({ time: 62, price: 101, qty: 1, oi: 0 }).bar.oi).toBe(0);
    expect(builder.onTick({ time: 63, price: 101, qty: 1, oi: Infinity }).bar).not.toHaveProperty('oi');
  });

  it('replaces the candle level on every supplied tick instead of adding it', () => {
    const builder = new CandleBuilder();
    expect(builder.onTick({ time: 60, price: 100, ltq: 2, oi: 100 })?.bar.oi).toBe(100);
    expect(builder.onTick({ time: 61, price: 101, ltq: 3, oi: 110 })?.bar)
      .toMatchObject({ oi: 110, volume: 5 });
    expect(builder.onTick({ time: 120, price: 102, ltq: 1, oi: 0 })?.bar.oi).toBe(0);
    expect(builder.onTick({ time: 180, price: 102, ltq: 1 })?.bar.oi).toBeUndefined();
  });

  it('replaces tick-bar levels and starts a new bar without inherited open interest', () => {
    const builder = new TickBarAggregator({ mode: 'ticks', count: 2 });
    expect(builder.onTick({ time: 60, price: 100, qty: 2, oi: 100 }).bar.oi).toBe(100);
    expect(builder.onTick({ time: 61, price: 101, qty: 3, oi: 0 }).bar)
      .toMatchObject({ oi: 0, volume: 5 });
    expect(builder.onTick({ time: 62, price: 101, qty: 1 }).bar.oi).toBeUndefined();
  });

  it('preserves the column and its gaps through the one-to-one transform', () => {
    const rows = [bar(60, 150), bar(120), bar(180, 0)];
    expect(runTransform(new HeikinAshiTransform(), rows).map(row => row.oi))
      .toEqual([150, undefined, 0]);
  });

  it.each([
    ['renko', new RenkoTransform({ boxSize: 1 })],
    ['range', new RangeBarsTransform({ range: 2 })],
    ['line break', new LineBreakTransform({ lines: 3 })],
    ['point and figure', new PointFigureTransform({ boxSize: 1, reversal: 3 })],
    ['kagi', new KagiTransform({ reversal: 2 })],
  ] as const)('omits levels from price-generated %s bars', (_name, transform) => {
    const rows = [100, 104, 95, 108, 90].map((price, i) => bar(i * 60, 200 + i, price));
    const output = runTransform(transform, rows);
    expect(output.length).toBeGreaterThan(0);
    for (const row of output) expect(row).not.toHaveProperty('oi');
  });

  it('omits levels from an expression even when combined leg volume is requested', () => {
    const rows = readings();
    const output = evaluateExpression(parseExpression('A/B'), { A: rows, B: rows }, { volume: 'sum' });
    expect(output).toHaveLength(5);
    for (const row of output) {
      expect(row.volume).toBe(20);
      expect(row).not.toHaveProperty('oi');
    }
  });
});
