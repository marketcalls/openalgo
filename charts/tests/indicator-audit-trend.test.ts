import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import { PARABOLIC_SAR } from '../src/indicators/trend';

const settings: IndicatorSettings = indicatorDefaults(PARABOLIC_SAR);

/** Build bars from explicit high/low/close triples: SAR reads nothing else. */
const bars = (rows: readonly (readonly [number, number, number])[]): Bar[] =>
  rows.map(([high, low, close], i) => ({
    time: 1700000000 + i * 300,
    open: close,
    high,
    low,
    close,
    volume: 100,
  }));

const sar = (data: readonly Bar[]): readonly (number | null)[] =>
  PARABOLIC_SAR.calc(data, settings, {}).sar;

/**
 * Every expectation below is hand-computed from Wilder's rules with the
 * shipped defaults (start 0.02, increment 0.02, maximum 0.2), never read back
 * out of the implementation. The reversal bar is the whole point: the stop
 * that ends a trend is that trend's extreme point taken over the flip bar as
 * well, so an outside bar that takes out both sides moves the reversal stop to
 * its own far side rather than leaving it inside the bar.
 */
describe('Parabolic SAR places the reversal stop outside the bar that triggered it', () => {
  // Five rising bars, then an outside bar (110/95) that takes out both sides.
  const longToShort = bars([
    [100, 98, 99],
    [102, 99, 101],
    [104, 101, 103],
    [106, 103, 105],
    [108, 105, 107],
    [110, 95, 96],
    [99, 94, 95],
  ]);

  it('carries the rising trail up to the flip bar', () => {
    const out = sar(longToShort);
    // rising, sar seeded at low[0] = 98 and ep at high[1] = 102.
    expect(out[0]).toBeNull();
    expect(out[1]).toBeCloseTo(98, 12);        // 98 + 0.02*(102-98) = 98.08, clamped to low[0]
    expect(out[2]).toBeCloseTo(98, 12);        // clamped to low[0] = 98 again, then ep = 104, af = 0.04
    expect(out[3]).toBeCloseTo(98.24, 12);     // 98 + 0.04*(104-98)
    expect(out[4]).toBeCloseTo(98.7056, 12);   // 98.24 + 0.06*(106-98.24)
  });

  it('reverses to the higher of the extreme point and the flip bar high', () => {
    const out = sar(longToShort);
    // Propagated 98.7056 + 0.08*(108-98.7056) = 99.449152 and low 95 breaks it,
    // so the short stop is max(ep = 108, high = 110) = 110, not the bare 108
    // which sits inside the 95 to 110 range of the bar that triggered it.
    expect(out[5]).toBeCloseTo(110, 12);
    expect(out[5] as number).toBeGreaterThanOrEqual(longToShort[5].high);
  });

  it('rejoins the two-bar clamp on the bar after the reversal', () => {
    const out = sar(longToShort);
    // 110 + 0.02*(95-110) = 109.7, clamped up to max(high[5], high[4]) = 110.
    expect(out[6]).toBeCloseTo(110, 12);
  });

  // The mirror image: four falling bars, then an outside bar (105/88).
  const shortToLong = bars([
    [100, 98, 99],
    [99, 95, 96],
    [97, 93, 94],
    [95, 91, 92],
    [93, 89, 90],
    [105, 88, 104],
    [106, 100, 105],
  ]);

  it('carries the falling trail down to the flip bar', () => {
    const out = sar(shortToLong);
    // falling, sar seeded at high[0] = 100 and ep at low[1] = 95.
    expect(out[1]).toBeCloseTo(100, 12);       // 99.9 clamped up to high[0] = 100
    expect(out[2]).toBeCloseTo(100, 12);       // clamped to high[0] again, then ep = 93, af = 0.04
    expect(out[3]).toBeCloseTo(99.72, 12);     // 100 + 0.04*(93-100)
    expect(out[4]).toBeCloseTo(99.1968, 12);   // 99.72 + 0.06*(91-99.72)
  });

  it('reverses to the lower of the extreme point and the flip bar low', () => {
    const out = sar(shortToLong);
    // Propagated 99.1968 + 0.08*(89-99.1968) = 98.381056 and high 105 breaks
    // it, so the long stop is min(ep = 89, low = 88) = 88, not the bare 89.
    expect(out[5]).toBeCloseTo(88, 12);
    expect(out[5] as number).toBeLessThanOrEqual(shortToLong[5].low);
    // 88 + 0.02*(105-88) = 88.34, clamped down to min(low[5], low[4]) = 88.
    expect(out[6]).toBeCloseTo(88, 12);
  });

  it('leaves an inside flip bar on the extreme point alone', () => {
    // Same rising run, but the flip bar (106/95) never trades above ep = 108,
    // so max(ep, high) is ep and the reversal stop is unchanged at 108.
    const inside = bars([
      [100, 98, 99],
      [102, 99, 101],
      [104, 101, 103],
      [106, 103, 105],
      [108, 105, 107],
      [106, 95, 96],
    ]);
    expect(sar(inside)[5]).toBeCloseTo(108, 12);
  });
});
