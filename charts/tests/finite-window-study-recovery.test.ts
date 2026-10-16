import { describe, expect, it } from 'vitest';
import { CHAIKIN_MONEY_FLOW } from '../src/indicators/flow';
import { CHANDE_MOMENTUM } from '../src/indicators/oscillators';
import { ULTIMATE_OSCILLATOR } from '../src/indicators/ranges';
import { VORTEX } from '../src/indicators/signals';
import { CHOPPINESS_INDEX } from '../src/indicators/volatility';
import { indicatorDefaults } from '../src/model/indicator-registry';

const bars = (values: readonly number[]) => values.map((close, i) => ({
  time: 1700000000 + i * 60, open: close, high: close, low: close, close, volume: 1,
}));

describe('studies built from finite chronological windows', () => {
  it('does not report neutral money flow for an unavailable volume sum', () => {
    const data = bars([0.5, 0.5, 0.5, 0.5]).map((bar, i) => ({
      ...bar, high: 1, low: 0, volume: i < 2 ? 1e308 : 1,
    }));
    // A centered close contributes zero flow. The volume sum is unavailable
    // only for its overflowing window, then finite windows give exactly zero.
    expect(CHAIKIN_MONEY_FLOW.calc(data, { ...indicatorDefaults(CHAIKIN_MONEY_FLOW), length: 2 }, {}).cmf)
      .toEqual([null, null, 0, 0]);
  });

  it('normalizes a summed true range before the Ultimate ratio', () => {
    const data = bars([0, 0, 0, 0, 0]).map((bar, i) => ({ ...bar, high: i < 3 ? 1e308 : 1, low: 0 }));
    expect(ULTIMATE_OSCILLATOR.calc(data, {
      ...indicatorDefaults(ULTIMATE_OSCILLATOR), length1: 2, length2: 2, length3: 2,
    }, {}).uo).toEqual([null, null, null, 0, 0]);
  });

  it('recovers the Ultimate current-bar ratio after a missing high expires', () => {
    const data = bars([1, 1, 1, 1]).map((bar, i) => ({ ...bar, high: i === 1 ? NaN : 2, low: 0 }));
    // For length one, valid current buying pressure is 1 and true range is 2.
    expect(ULTIMATE_OSCILLATOR.calc(data, {
      ...indicatorDefaults(ULTIMATE_OSCILLATOR), length1: 1, length2: 1, length3: 1,
    }, {}).uo).toEqual([null, null, 50, 50]);
  });

  it('recovers both Vortex movement ratios after old large ranges expire', () => {
    const data = bars([0, 0, 0, 0, 0]).map((bar, i) => ({ ...bar, high: i < 2 ? 1e308 : 1, low: 0 }));
    const result = VORTEX.calc(data, { ...indicatorDefaults(VORTEX), length: 2 }, {});
    // Both movement windows are 1+1 and the true-range window is 1+1.
    expect(result.vip[4]).toBe(1);
    expect(result.vim[4]).toBe(1);
  });

  it('recovers Chande momentum from the two current positive unit changes', () => {
    const result = CHANDE_MOMENTUM.calc(bars([0, 1e308, -1e308, 0, 1, 2]), {
      ...indicatorDefaults(CHANDE_MOMENTUM), length: 2,
    }, {});
    expect(result.cmo[5]).toBe(100);
  });

  it('recovers Choppiness from the current range without a retained overflow', () => {
    const data = bars([1, 1, 1, 1, 1]).map((bar, i) => ({ ...bar, high: i < 2 ? 1e308 : 2, low: 0 }));
    const result = CHOPPINESS_INDEX.calc(data, { ...indicatorDefaults(CHOPPINESS_INDEX), length: 2 }, {});
    // Two ranges 2+2 over a span of 2 give 100*log10(2)/log10(2).
    expect(result.chop.slice(3)).toEqual([100, 100]);
  });
});
