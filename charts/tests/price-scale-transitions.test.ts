import { describe, expect, it } from 'vitest';
import { PriceScale, type PriceScaleMode } from '../src/scale/price-scale';

describe('price scale navigation', () => {
  it.each<PriceScaleMode>(['linear', 'logarithmic', 'percentage', 'indexed-to-100'])('eases the projected price rather than jumping to a new extent in %s mode', mode => {
    const scale = new PriceScale({ mode }); scale.setHeight(500); scale.setBaseline(100);
    scale.autoscale(100, 120);
    const before = scale.priceToY(110);
    const target = new PriceScale({ mode }); target.setHeight(500); target.setBaseline(100); target.autoscale(100, 600);
    const finalY = target.priceToY(110);
    expect(scale.autoscale(100, 600, 0.25)).toBe(true);
    expect(scale.priceToY(110)).toBeCloseTo(before + (finalY - before) * 0.25, 8);
    for (let i = 0; i < 100; i++) scale.autoscale(100, 600, 0.25);
    expect(scale.priceRange()).toEqual(target.priceRange());
    expect(scale.autoscale(100, 600, 0.25)).toBe(false);
  });

  it('snaps the first measured range and keeps a fixed band', () => {
    const scale = new PriceScale(); scale.setHeight(500);
    expect(scale.autoscale(100, 120, 0.1)).toBe(false);
    expect(scale.priceRange()).toEqual({ min: 97.5, max: 122.5 });
    scale.setFixedRange({ min: 0, max: 100 }); scale.autoscale(-20, 600, 0.1);
    expect(scale.priceRange()).toEqual({ min: 0, max: 100 });
  });

  it.each([false, true])('anchors wheel scaling at the pointer with inverted=%s', inverted => {
    const scale = new PriceScale({ mode: 'logarithmic', inverted }); scale.setHeight(500); scale.autoscale(100, 1000);
    const price = scale.yToPrice(123);
    scale.scaleAtY(123, 0.8);
    expect(scale.priceToY(price)).toBeCloseTo(123, 8);
    expect(scale.autoScale).toBe(false);
  });
});
