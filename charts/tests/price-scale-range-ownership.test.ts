import { describe, expect, it } from 'vitest';
import { PriceScale, type PriceRange } from '../src/scale/price-scale';

const declared = { min: 0, max: 100 };
const replacement = { min: -1, max: 1 };

function claimed() {
  const scale = new PriceScale();
  scale.setHeight(100);
  const owner = {};
  expect(scale.setOwnedFixedRange(owner, declared)).toBe(true);
  return { scale, owner };
}

describe('owned fixed price ranges', () => {
  it('reports detached ownership metadata for persistence, including equal-value manual writes', () => {
    const { scale, owner } = claimed();
    expect(scale.ownedFixedRangeState({})).toBeNull();
    expect(scale.ownedFixedRangeState(owner)).toEqual({ manual: false });
    scale.ownedFixedRangeState(owner)!.manual = true;
    expect(scale.ownedFixedRangeState(owner)).toEqual({ manual: false });
    scale.setPriceRange(declared);
    expect(scale.ownedFixedRangeState(owner)).toEqual({ manual: true });
    scale.setAutoScale(true);
    expect(scale.ownedFixedRangeState(owner)).toEqual({ manual: false });
    scale.setAutoScale(false);
    expect(scale.ownedFixedRangeState(owner)).toEqual({ manual: true });
    scale.clearOwnedFixedRange(owner);
    expect(scale.ownedFixedRangeState(owner)).toBeNull();
  });

  it('does not expose owned state once a public fixed-range setter takes ownership', () => {
    const { scale, owner } = claimed();
    scale.setFixedRange(declared);
    expect(scale.ownedFixedRangeState(owner)).toBeNull();
  });

  it('updates and releases an untouched default without retaining manual mode', () => {
    const { scale, owner } = claimed();
    expect(scale.ownsFixedRange(owner)).toBe(true);
    expect(scale.autoScale).toBe(false);
    expect(scale.fixedRange).toEqual(declared);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.fixedRange).toEqual(replacement);
    expect(scale.priceRange()).toEqual(replacement);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.ownsFixedRange(owner)).toBe(false);
    expect(scale.fixedRange).toBeNull();
    expect(scale.priceRange()).toEqual(replacement);
    expect(scale.autoScale).toBe(true);
    expect(scale.clearOwnedFixedRange(owner)).toBe(false);
  });

  it('refuses foreign updates and release, even when the requested values match', () => {
    const { scale, owner } = claimed();
    const foreign = {};
    expect(scale.setOwnedFixedRange(foreign, declared)).toBe(false);
    expect(scale.clearOwnedFixedRange(foreign)).toBe(false);
    expect(scale.ownsFixedRange(foreign)).toBe(false);
    expect(scale.ownsFixedRange(owner)).toBe(true);
    expect(scale.fixedRange).toEqual(declared);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.autoScale).toBe(false);
  });

  it('lets a new owner claim a scale after clean release', () => {
    const { scale, owner } = claimed();
    scale.clearOwnedFixedRange(owner);
    const next = {};
    expect(scale.setOwnedFixedRange(next, replacement)).toBe(true);
    expect(scale.ownsFixedRange(next)).toBe(true);
    expect(scale.ownsFixedRange(owner)).toBe(false);
  });

  it('detaches the owned declaration from caller and getter objects', () => {
    const scale = new PriceScale(), owner = {};
    const range = { min: 10, max: 20 };
    scale.setOwnedFixedRange(owner, range);
    range.min = 19;
    scale.fixedRange!.max = 90;
    expect(scale.fixedRange).toEqual({ min: 10, max: 20 });
    expect(scale.priceRange()).toEqual({ min: 10, max: 20 });
  });

  it('treats an equal-value public fixed declaration as host ownership', () => {
    const { scale, owner } = claimed();
    scale.setFixedRange({ ...declared });
    expect(scale.ownsFixedRange(owner)).toBe(false);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(false);
    expect(scale.clearOwnedFixedRange(owner)).toBe(false);
    expect(scale.fixedRange).toEqual(declared);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.autoScale).toBe(false);
  });

  it('keeps legacy public withdrawal semantics and relinquishes the token', () => {
    const { scale, owner } = claimed();
    scale.setFixedRange(null);
    expect(scale.ownsFixedRange(owner)).toBe(false);
    expect(scale.fixedRange).toBeNull();
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.autoScale).toBe(false);
    expect(scale.clearOwnedFixedRange(owner)).toBe(false);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(false);
  });

  it.each([declared, { min: 20, max: 80 }])('retains a public manual range %j while removing only its owned default', range => {
    const { scale, owner } = claimed();
    scale.setPriceRange(range);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.fixedRange).toEqual(replacement);
    expect(scale.priceRange()).toEqual(range);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.fixedRange).toBeNull();
    expect(scale.priceRange()).toEqual(range);
    expect(scale.autoScale).toBe(false);
  });

  it('preserves an explicit manual mode request even when its range is unchanged', () => {
    const { scale, owner } = claimed();
    scale.setAutoScale(false);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.autoScale).toBe(false);
  });

  it.each<{
    name: string; gesture: (scale: PriceScale) => void; expected: PriceRange;
  }>([
    { name: 'pan', gesture: scale => scale.panByPixels(10), expected: { min: 10, max: 110 } },
    { name: 'center zoom', gesture: scale => scale.scaleAroundCenter(0.5), expected: { min: 25, max: 75 } },
    { name: 'anchored zoom', gesture: scale => scale.scaleAtY(50, 0.5), expected: { min: 25, max: 75 } },
    { name: 'equal-range center zoom', gesture: scale => scale.scaleAroundCenter(1), expected: declared },
  ])('keeps the host range after $name', ({ gesture, expected }) => {
    const { scale, owner } = claimed();
    gesture(scale);
    expect(scale.priceRange()).toEqual(expected);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.priceRange()).toEqual(expected);
    expect(scale.autoScale).toBe(false);
  });

  it('does not claim manual intent for rejected gestures', () => {
    const { scale, owner } = claimed();
    scale.panByPixels(0);
    scale.scaleAtY(50, -1);
    scale.scaleAtY(50, NaN);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.autoScale).toBe(true);
  });

  it('fits an owned default and resets manual tracking after the host requests auto fit', () => {
    const { scale, owner } = claimed();
    scale.panByPixels(10);
    scale.setAutoScale(true);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.autoScale).toBe(false);
    expect(scale.ownsFixedRange(owner)).toBe(true);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    expect(scale.clearOwnedFixedRange(owner)).toBe(true);
    expect(scale.autoScale).toBe(true);
  });

  it.each([
    { name: 'fixed range', setup: (scale: PriceScale) => scale.setFixedRange(declared) },
    { name: 'manual mode', setup: (scale: PriceScale) => scale.setAutoScale(false) },
    { name: 'explicit range', setup: (scale: PriceScale) => scale.setPriceRange(declared) },
  ])('refuses a new owner on a host-configured $name target', ({ setup }) => {
    const scale = new PriceScale(), owner = {};
    setup(scale);
    const before = { range: scale.priceRange(), fixed: scale.fixedRange, auto: scale.autoScale };
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(false);
    expect(scale.ownsFixedRange(owner)).toBe(false);
    expect({ range: scale.priceRange(), fixed: scale.fixedRange, auto: scale.autoScale }).toEqual(before);
  });

  it('allows a fresh claim after the host returns an unowned manual scale to autoscale', () => {
    const scale = new PriceScale(), owner = {};
    scale.setPriceRange({ min: 20, max: 80 });
    scale.setAutoScale(false);
    scale.setAutoScale(true);
    expect(scale.setOwnedFixedRange(owner, declared)).toBe(true);
  });

  it('does not mistake measured or interpolated autoscale ranges for host writes', () => {
    const scale = new PriceScale(), owner = {};
    scale.setHeight(100);
    scale.autoscale(10, 20);
    expect(scale.autoscale(40, 80, 0.5)).toBe(true);
    expect(scale.setOwnedFixedRange(owner, declared)).toBe(true);
    scale.autoscale(-500, 500);
    expect(scale.priceRange()).toEqual(declared);
    expect(scale.setOwnedFixedRange(owner, replacement)).toBe(true);
    scale.clearOwnedFixedRange(owner);
    expect(scale.autoScale).toBe(true);
  });
});
