import { describe, it, expect } from 'vitest';
import { niceNum, niceTicks, precisionForStep } from '../src/scale/ticks';
import { PriceScale, autoscaleRange } from '../src/scale/price-scale';
import { TimeScale } from '../src/scale/time-scale';
import { optimalBarWidth } from '../src/render/candles';

describe('ticks', () => {
  it('rounds to nice numbers', () => {
    expect(niceNum(0.9, true)).toBe(1);
    expect(niceNum(23, true)).toBe(20);
    expect(niceNum(7, false)).toBe(10);
  });

  it('generates ascending in-range ticks', () => {
    const t = niceTicks(0, 100, 6);
    expect(t[0]).toBeGreaterThanOrEqual(0);
    expect(t[t.length - 1]).toBeLessThanOrEqual(100);
    for (let i = 1; i < t.length; i++) expect(t[i]).toBeGreaterThan(t[i - 1]);
  });

  it('keeps density on a narrow range far from zero', () => {
    // A footprint on a 65000 instrument autoscales to a ~10-point window. Rounding
    // the span to a nice number before dividing used to yield 3 labels, not 6.
    const t = niceTicks(64994.875, 65005.375, 6);
    expect(t.length).toBeGreaterThanOrEqual(5);
    expect(t.length).toBeLessThanOrEqual(6);
  });

  it('never returns more than maxTicks', () => {
    const ranges: [number, number][] = [
      [0, 7], [0, 0.003], [19800, 20450], [-50, 50], [0, 1e6],
      [2.5, 2.5001], [1.2, 1.35], [0, 100], [100, 105], [0.0001, 0.0009],
    ];
    for (const [min, max] of ranges) {
      for (const maxTicks of [3, 4, 6, 10]) {
        const t = niceTicks(min, max, maxTicks);
        expect(t.length, `[${min}, ${max}] @ ${maxTicks}`).toBeLessThanOrEqual(maxTicks);
        for (let i = 1; i < t.length; i++) expect(t[i]).toBeGreaterThan(t[i - 1]);
      }
    }
  });

  it('handles degenerate ranges without looping', () => {
    expect(niceTicks(5, 5)).toEqual([5]);
    expect(niceTicks(NaN, 10)).toHaveLength(1);
  });

  it('derives precision from step', () => {
    expect(precisionForStep(1)).toBe(0);
    expect(precisionForStep(0.05)).toBe(2);
    expect(precisionForStep(0.001)).toBe(3);
  });
});

describe('PriceScale', () => {
  it('autoscale adds margins around extremes', () => {
    // 0.1/0.1 leaves the data 80% of the pane, so the span is 1/0.8 of 100.
    const r = autoscaleRange(100, 200, 0.1, 0.1);
    expect(r.min).toBeCloseTo(87.5);
    expect(r.max).toBeCloseTo(212.5);
  });

  it('reserves margins as a fraction of pane height, not of the data span', () => {
    // The volume-overlay case: 0.82 must leave the series the bottom 18% of
    // the pane. Padding the span instead left it 55%.
    const r = autoscaleRange(0, 1000, 0.82, 0);
    expect(r.min).toBeCloseTo(0);
    expect(1000 / (r.max - r.min)).toBeCloseTo(0.18);
  });

  it('keeps the data centred when the margins match', () => {
    const r = autoscaleRange(0, 100, 0.25, 0.25);
    expect(100 / (r.max - r.min)).toBeCloseTo(0.5);
    expect(r.min).toBeCloseTo(-50);
    expect(r.max).toBeCloseTo(150);
  });

  it('stays finite when the margins leave no room', () => {
    const r = autoscaleRange(0, 100, 0.7, 0.7);
    expect(Number.isFinite(r.min)).toBe(true);
    expect(Number.isFinite(r.max)).toBe(true);
    expect(r.max).toBeGreaterThan(r.min);
  });

  it('widens a flat range so it is drawable', () => {
    const r = autoscaleRange(100, 100, 0.1, 0.1);
    expect(r.max).toBeGreaterThan(r.min);
  });

  it('maps between price and y invertibly (a higher price gives a smaller y)', () => {
    const ps = new PriceScale();
    ps.setHeight(400);
    ps.setPriceRange({ min: 0, max: 100 });
    expect(ps.priceToY(100)).toBeCloseTo(0);
    expect(ps.priceToY(0)).toBeCloseTo(400);
    expect(ps.priceToY(50)).toBeCloseTo(200);
    expect(ps.yToPrice(200)).toBeCloseTo(50);
  });

  it('snaps to tick size and formats with derived precision', () => {
    const ps = new PriceScale({ minMove: 0.05 });
    expect(ps.snapToTick(100.07)).toBeCloseTo(100.05);
    expect(ps.format(100.05)).toBe('100.05');
  });

  it('panByPixels pans vertically: content tracks 1:1, span preserved, manual mode', () => {
    const ps = new PriceScale();
    ps.setHeight(400);
    ps.setPriceRange({ min: 100, max: 200 });
    const y0 = ps.priceToY(150);
    ps.panByPixels(40); // drag the plot down 40px
    expect(ps.priceToY(150)).toBeCloseTo(y0 + 40, 6); // that price moved down 40px with the cursor
    expect(ps.priceRange().max - ps.priceRange().min).toBeCloseTo(100, 6); // span unchanged
    expect(ps.priceRange().min).toBeGreaterThan(100); // window shifted up to higher prices
    expect(ps.autoScale).toBe(false);
  });
});

describe('TimeScale', () => {
  it('maps between logical index and x invertibly', () => {
    const ts = new TimeScale({ barSpacing: 10, rightOffset: 0 });
    ts.setWidth(500);
    ts.setBaseIndex(49); // 50 bars, base at right edge
    // rightEdgeIndex = 49; indexToX(49) = width = 500
    expect(ts.indexToX(49)).toBeCloseTo(500);
    expect(ts.indexToX(48)).toBeCloseTo(490);
    expect(ts.xToIndex(500)).toBeCloseTo(49);
    expect(ts.xToIndex(490)).toBeCloseTo(48);
  });

  it('clamps bar spacing to its bounds', () => {
    const ts = new TimeScale({ minBarSpacing: 2, maxBarSpacing: 50 });
    ts.setBarSpacing(1000);
    expect(ts.barSpacing).toBe(50);
    ts.setBarSpacing(0.1);
    expect(ts.barSpacing).toBe(2);
  });

  it('fitContent sizes spacing to the bar count', () => {
    const ts = new TimeScale();
    ts.setWidth(800);
    ts.fitContent(100);
    const vis = ts.visibleRange();
    // the latest bar (index 99) should be at/near the right edge
    expect(vis.to).toBeGreaterThanOrEqual(99);
    expect(ts.barSpacing).toBeGreaterThan(0);
  });
});

describe('optimalBarWidth', () => {
  it('grows with spacing, stays >= 1, parity-matched to the wick', () => {
    expect(optimalBarWidth(1, 1)).toBeGreaterThanOrEqual(1);
    expect(optimalBarWidth(10, 1)).toBeGreaterThan(optimalBarWidth(4, 1));
    // wick width at dpr=1 is 1 (odd), so the body must be odd
    expect(optimalBarWidth(10, 1) % 2).toBe(1);
  });
});

describe('PriceScale.scaled gates the axis ladder', () => {
  it('starts unmeasured, holding a placeholder rather than a measurement', () => {
    // A pane whose only indicator output is a table or a set of markers plots
    // no values, so nothing ever calls autoscale and the range stays 0..1.
    // Labelling that prints a price ladder the pane has no prices for.
    const scale = new PriceScale();
    expect(scale.scaled).toBe(false);
    expect(scale.priceRange()).toEqual({ min: 0, max: 1 });
  });

  it('becomes measured once a series gives it a range', () => {
    const scale = new PriceScale();
    scale.autoscale(100, 200);
    expect(scale.scaled).toBe(true);
    expect(scale.priceRange().min).toBeLessThan(100);
  });

  it('becomes measured when a range is set by hand', () => {
    const scale = new PriceScale();
    scale.setPriceRange({ min: 10, max: 20 });
    expect(scale.scaled).toBe(true);
  });
});
