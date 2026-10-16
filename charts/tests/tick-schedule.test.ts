import { describe, expect, it } from 'vitest';
import { TickSchedule, type TickBand } from '../src/feed/tick-schedule';

// A synthetic schedule, not any venue's: three bands with two boundaries, so
// a price can cross each boundary in both directions.
const BANDS: TickBand[] = [{ tick: 0.01 }, { from: 10, tick: 0.05 }, { from: 100, tick: 0.1 }];
const schedule = (): TickSchedule => new TickSchedule(BANDS);
/** Two bands with an unset slot between them, as JSON never makes but code can. */
function holey(): unknown[] {
  const bands: unknown[] = [{ tick: 0.01 }];
  bands[2] = { from: 100, tick: 0.05 };
  return bands;
}

describe('tick schedule construction', () => {
  it('detaches and freezes the bands, dropping unrelated fields', () => {
    const source: Array<{ from?: number; tick: number; note?: string }> = [
      { tick: 0.01, note: 'not a rule' }, { from: 10, tick: 0.05 },
    ];
    const ticks = new TickSchedule(source);
    source[1].tick = 1; source.push({ from: 50, tick: 1 });
    expect(ticks.bands).toEqual([{ tick: 0.01 }, { from: 10, tick: 0.05 }]);
    expect(Object.isFrozen(ticks.bands)).toBe(true);
    expect(Object.isFrozen(ticks.bands[1])).toBe(true);
    expect(ticks.bands[0]).not.toHaveProperty('note');
  });

  it('reports the finest grid every scheduled price lies on as the minimum move', () => {
    expect(schedule().minMove).toBe(0.01);
    // 20.05 is a valid price here and is not a multiple of 0.02, the smallest
    // tick, so the price scale needs the common grid, not the smallest band.
    expect(new TickSchedule([{ tick: 0.02 }, { from: 20, tick: 0.05 }]).minMove).toBe(0.01);
    expect(new TickSchedule([{ tick: 0.01 }, { from: 10, tick: 0.025 }]).minMove).toBe(0.005);
    expect(new TickSchedule([{ tick: 5 }, { from: 1000, tick: 25 }]).minMove).toBe(5);
    expect(new TickSchedule([{ tick: 0.00000001 }]).minMove).toBe(0.00000001);
  });

  it.each<[string, unknown, RegExp]>([
    ['a non-list', { tick: 0.05 }, /1 to 64 bands/],
    ['null', null, /1 to 64 bands/],
    ['no bands', [], /1 to 64 bands/],
    ['too many bands', Array.from({ length: 65 }, (_, i) => (i ? { from: i, tick: 1 } : { tick: 1 })), /1 to 64 bands/],
    ['a zero tick', [{ tick: 0 }], /bands\[0\]\.tick/],
    ['a negative tick', [{ tick: -0.05 }], /bands\[0\]\.tick/],
    ['a NaN tick', [{ tick: NaN }], /bands\[0\]\.tick/],
    ['an infinite tick', [{ tick: Infinity }], /bands\[0\]\.tick/],
    ['a string tick', [{ tick: '0.05' }], /bands\[0\]\.tick/],
    ['a tick finer than 12 decimals', [{ tick: 1e-13 }], /bands\[0\]\.tick/],
    ['a band that is not an object', [0.05], /bands\[0\]\.tick/],
    ['a tick behind an accessor', [{ get tick() { return 0.05; } }], /bands\[0\]\.tick/],
    ['a lower bound on the first band', [{ from: 0, tick: 0.01 }], /bands\[0\] covers every lower price/],
    ['a later band with no lower bound', [{ tick: 0.01 }, { tick: 0.05 }], /bands\[1\]\.from/],
    ['an infinite lower bound', [{ tick: 0.01 }, { from: Infinity, tick: 0.05 }], /bands\[1\]\.from/],
    ['bounds out of order', [{ tick: 0.01 }, { from: 100, tick: 0.1 }, { from: 10, tick: 0.05 }], /ascending/],
    ['a repeated bound', [{ tick: 0.01 }, { from: 10, tick: 0.05 }, { from: 10, tick: 0.1 }], /ascending/],
    ['a bound off its own grid', [{ tick: 0.01 }, { from: 10.02, tick: 0.05 }], /bands\[1\]\.from 10\.02 is not a multiple of bands\[1\]\.tick 0\.05/],
    ['a bound off the previous grid', [{ tick: 0.05 }, { from: 10.02, tick: 0.01 }], /bands\[1\]\.from 10\.02 is not a multiple of bands\[0\]\.tick 0\.05/],
    ['ticks with no common grid in safe integers', [{ tick: 1e-12 }, { from: 10000, tick: 10000 }], /common grid/],
    // A hole is skipped by forEach, so the next band once met no previous one.
    ['a hole in the band list', holey(), /bands\[1\]\.tick/],
  ])('rejects %s with a clear error', (_label, input, message) => {
    expect(() => new TickSchedule(input as TickBand[])).toThrow(message);
    expect(() => new TickSchedule(input as TickBand[])).toThrow(/^Invalid tick schedule: /);
  });
});

describe('tick schedule boundaries', () => {
  it('gives an exact boundary the tick of the band that starts there', () => {
    const ticks = schedule();
    expect(ticks.tickAt(9.99)).toBe(0.01);
    expect(ticks.tickAt(10)).toBe(0.05);
    expect(ticks.tickAt(99.95)).toBe(0.05);
    expect(ticks.tickAt(100)).toBe(0.1);
    expect(ticks.tickAt(1e9)).toBe(0.1);
    expect(ticks.tickAt(NaN)).toBeNaN();
    expect(ticks.tickAt(Infinity)).toBeNaN();
  });

  it('rounds to the nearest valid price on each side of a boundary', () => {
    const ticks = schedule();
    expect(ticks.round(9.994)).toBe(9.99);
    // Below the boundary the finer grid still reaches the boundary itself.
    expect(ticks.round(9.996)).toBe(10);
    expect(ticks.round(10)).toBe(10);
    expect(ticks.round(10.02)).toBe(10);
    expect(ticks.round(10.03)).toBe(10.05);
    expect(ticks.round(99.97)).toBe(99.95);
    expect(ticks.round(99.98)).toBe(100);
    expect(ticks.round(100.04)).toBe(100);
    expect(ticks.round(100.06)).toBe(100.1);
  });

  it('returns exact decimals and rounds a written halfway price up', () => {
    const ticks = schedule();
    // 10.025 is stored a hair below the decimal it was written as; a plain
    // divide-and-round would send it down to 10.00.
    expect(ticks.round(10.025)).toBe(10.05);
    expect(ticks.round(10.075)).toBe(10.1);
    expect(ticks.round(100.05)).toBe(100.1);
    expect(ticks.round(0.005)).toBe(0.01);
    expect(ticks.round(10.07)).toBe(10.05);
    expect(ticks.round(12.345678)).toBe(12.35);
    expect(new TickSchedule([{ tick: 0.05 }]).round(100.07)).toBe(100.05);
  });

  it('rounds to the nearer valid price however many ticks the price is from zero', () => {
    // A halfway allowance that grew with price / tick once sent a price 0.49
    // of a tick above a valid price up to the next one.
    const pico = new TickSchedule([{ tick: 1e-12 }]), fine = new TickSchedule([{ tick: 1e-8 }]);
    expect(pico.round(5.00000000000049)).toBe(5);
    expect(pico.round(5.00000000000051)).toBe(5.000000000001);
    expect(fine.round(50000.0000000049)).toBe(50000);
    expect(fine.round(50000.0000000051)).toBe(50000.00000001);
    // A price written exactly halfway still rounds up at that scale.
    expect(pico.round(5.0000000000005)).toBe(5.000000000001);
    expect(fine.round(50000.000000005)).toBe(50000.00000001);
    expect(fine.round(-50000.000000005)).toBe(-50000);
    // Every price between two valid ones goes to the nearer of them.
    const ticks = schedule();
    for (let cents = 900; cents <= 1100; cents++) {
      for (const part of [0.1, 0.3, 0.45, 0.55, 0.7, 0.9]) {
        const price = (cents + part) / 100, tick = ticks.tickAt(price);
        const below = Math.floor(price / tick + 1e-9) * tick;
        const nearer = price - below < below + tick - price ? below : below + tick;
        expect(ticks.round(price)).toBeCloseTo(nearer, 9);
      }
    }
  });

  it('keeps zero and negative prices on the first band without a signed zero', () => {
    const ticks = schedule();
    expect(Object.is(ticks.round(0), 0)).toBe(true);
    expect(Object.is(ticks.round(-0), 0)).toBe(true);
    expect(Object.is(ticks.round(-0.004), 0)).toBe(true);
    expect(ticks.round(-0.013)).toBe(-0.01);
    expect(ticks.round(-12.371)).toBe(-12.37);
    // Halfway still rounds toward positive infinity below zero.
    expect(ticks.round(-0.005)).toBe(0);
    expect(ticks.round(-0.015)).toBe(-0.01);
    expect(ticks.tickAt(0)).toBe(0.01);
    expect(ticks.tickAt(-500)).toBe(0.01);
    expect(ticks.round(NaN)).toBeNaN();
    expect(ticks.round(-Infinity)).toBeNaN();
  });

  it('steps whole ticks across boundaries in both directions', () => {
    const ticks = schedule();
    expect(ticks.step(9.98, 1)).toBe(9.99);
    expect(ticks.step(9.98, 2)).toBe(10);
    expect(ticks.step(9.98, 3)).toBe(10.05);
    // Down from an exact boundary moves on the band below it.
    expect(ticks.step(10, -1)).toBe(9.99);
    expect(ticks.step(10.05, -2)).toBe(9.99);
    expect(ticks.step(99.9, 3)).toBe(100.1);
    expect(ticks.step(100, -1)).toBe(99.95);
    expect(ticks.step(0, -2)).toBe(-0.02);
    expect(ticks.step(-0.01, 1)).toBe(0);
    // Off-grid input is rounded first, then stepped.
    expect(ticks.step(10.03, 0)).toBe(10.05);
    expect(ticks.step(9.994, 1)).toBe(10);
    // Large counts jump band by band: 1000 ticks to 10, 1800 to 100, 97200 above.
    expect(ticks.step(0, 100000)).toBe(9820);
    expect(ticks.step(9820, -100000)).toBe(0);
    expect(ticks.step(NaN, 1)).toBeNaN();
    expect(() => ticks.step(10, 0.5)).toThrow(RangeError);
  });
});
