import { describe, it, expect } from 'vitest';
import { TickBarAggregator, type AggTick } from '../src/feed/tick-aggregator';
import { FootprintAggregator, type FootprintTick } from '../src/profile/footprint-aggregator';
import { PriceScale } from '../src/scale/price-scale';

const tick = (time: number, price: number, qty: number): AggTick => ({ time, price, qty });

describe('TickBarAggregator: interval timeframe', () => {
  it('opens a new bar at each interval boundary, OHLCV correct', () => {
    const agg = new TickBarAggregator({ mode: 'interval', seconds: 60 });
    expect(agg.onTick(tick(0, 100, 5)).isNew).toBe(true);
    const u = agg.onTick(tick(30, 102, 3)); // same bucket
    expect(u.isNew).toBe(false);
    expect(u.bar).toMatchObject({ open: 100, high: 102, low: 100, close: 102, volume: 8 });
    expect(agg.onTick(tick(60, 99, 2)).isNew).toBe(true); // next bucket
  });
});

describe('TickBarAggregator: tick-count timeframe', () => {
  it('completes a bar every N ticks', () => {
    const agg = new TickBarAggregator({ mode: 'ticks', count: 3 });
    agg.onTick(tick(1, 10, 1)); // bar A tick 1
    agg.onTick(tick(2, 11, 1)); // A tick 2
    agg.onTick(tick(3, 9, 1));  // A tick 3 (now full)
    const u = agg.onTick(tick(4, 12, 1)); // new bar B
    expect(u.isNew).toBe(true);
    expect(u.bar.open).toBe(12);
  });
});

describe('TickBarAggregator: volume timeframe', () => {
  it('completes a bar once accumulated volume reaches perBar', () => {
    const agg = new TickBarAggregator({ mode: 'volume', perBar: 100 });
    agg.onTick(tick(1, 10, 60));   // vol 60
    const u1 = agg.onTick(tick(2, 11, 50)); // vol 110 ≥ 100
    expect(u1.isNew).toBe(false);
    const u2 = agg.onTick(tick(3, 12, 10)); // prev bar was full: new bar
    expect(u2.isNew).toBe(true);
    expect(u2.bar.open).toBe(12);
  });
});

describe('FootprintAggregator (live orderflow)', () => {
  const ftick = (time: number, price: number, qty: number, side: 'bid' | 'ask'): FootprintTick => ({ time, price, qty, side });

  it('aggregates classified ticks into interval footprint bars with delta', () => {
    const agg = new FootprintAggregator({ mode: 'interval', seconds: 60 }, 0.05);
    agg.onTick(ftick(0, 100, 30, 'ask'));   // +30
    const u = agg.onTick(ftick(30, 100, 10, 'bid')); // -10, same bar
    expect(u.isNew).toBe(false);
    expect(u.bar.delta).toBe(20); // 30 ask − 10 bid
    const at100 = u.bar.cells.find((c) => Math.abs(c.price - 100) < 1e-9)!;
    expect(at100.askVol).toBe(30);
    expect(at100.bidVol).toBe(10);
    expect(agg.onTick(ftick(60, 100, 5, 'ask')).isNew).toBe(true); // next interval: fresh bar
  });

  it('supports tick-count footprint bars', () => {
    const agg = new FootprintAggregator({ mode: 'ticks', count: 2 }, 0.05);
    agg.onTick(ftick(1, 100, 5, 'ask'));
    agg.onTick(ftick(2, 100.05, 5, 'ask')); // bar now has 2 ticks
    expect(agg.onTick(ftick(3, 100, 5, 'bid')).isNew).toBe(true); // 3rd tick: new bar
  });

  it('resets delta per bar', () => {
    const agg = new FootprintAggregator({ mode: 'ticks', count: 1 }, 0.05);
    const a = agg.onTick(ftick(1, 100, 10, 'ask'));
    expect(a.bar.delta).toBe(10);
    const b = agg.onTick(ftick(2, 100, 4, 'bid')); // new bar (count 1)
    expect(b.isNew).toBe(true);
    expect(b.bar.delta).toBe(-4); // not carried from the previous bar
  });
});

describe('PriceScale manual rescale (axis drag)', () => {
  it('scaleAroundCenter widens/narrows around the centre and disables autoscale', () => {
    const ps = new PriceScale();
    ps.setPriceRange({ min: 90, max: 110 }); // centre 100, half 10
    ps.scaleAroundCenter(2); // compress (zoom out): half 20
    expect(ps.priceRange()).toEqual({ min: 80, max: 120 });
    expect(ps.autoScale).toBe(false);
    ps.setPriceRange({ min: 90, max: 110 });
    ps.scaleAroundCenter(0.5); // expand (zoom in): half 5
    expect(ps.priceRange()).toEqual({ min: 95, max: 105 });
  });
});
