import { describe, it, expect } from 'vitest';
import { FISHER_TRANSFORM } from '../src/indicators/oscillators';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

const defaults = (d: IndicatorDescriptor) => indicatorDefaults(d);
const run = (d: IndicatorDescriptor, data: readonly Bar[], over: Record<string, unknown> = {}) =>
  d.calc(data, { ...defaults(d), ...over }, {});

describe('Fisher Transform flat window', () => {
  // Hand-worked from the definition with length 3 on hl2 = 10, 11, 12, 12, 12, 12, 13, 14, 15.
  // Bars 3 to 5 hold hl2 flat, so high_ - low_ is 0 on bars 4 and 5 and the range
  // divide takes its 0.001 floor. The numerator is 0 there too, so the ratio is 0
  // and the raw value is -0.33 + 0.67 * value[1] rather than a gap.
  //
  //   bar 2  ratio 1  value 0.33      fish 0.5 * ln(1.33 / 0.67)                    =  0.34282825
  //   bar 3  ratio 1  value 0.5511    fish 0.5 * ln(1.5511 / 0.4489) + 0.5 * prev   =  0.79137387
  //   bar 4  ratio 0  value 0.039237  fish 0.5 * ln(1.039237 / 0.960763) + 0.5 prev =  0.43494409
  //   bar 5  ratio 0  value -0.303711 fish 0.5 * ln(0.696289 / 1.303711) + 0.5 prev = -0.09613083
  //   bar 6  ratio 1  value 0.126513  fish 0.5 * ln(1.126513 / 0.873487) + 0.5 prev =  0.07912961
  const flat = () => bars(9, (i) => [10, 11, 12, 12, 12, 12, 13, 14, 15][i]);

  it('prints through a flat window instead of gapping', () => {
    const out = run(FISHER_TRANSFORM, flat(), { length: 3 });
    expect(out.fisher[4]).not.toBeNull();
    expect(out.fisher[5]).not.toBeNull();
    expect(out.fisher[4] as number).toBeCloseTo(0.4349440904, 8);
    expect(out.fisher[5] as number).toBeCloseTo(-0.0961308302, 8);
  });

  it('keeps both recursion carries across the flat window', () => {
    const out = run(FISHER_TRANSFORM, flat(), { length: 3 });
    // Bar 6 has a live range again. Resetting the carries to 0 on bars 4 and 5
    // would print 0.34282825 here, the same as the very first bar.
    expect(out.fisher[6] as number).toBeCloseTo(0.0791296087, 8);
    expect(out.fisher[7] as number).toBeCloseTo(0.4809162636, 8);
    expect(out.fisher[8] as number).toBeCloseTo(0.9460289673, 8);
  });

  it('leaves the bars before the flat window untouched', () => {
    const out = run(FISHER_TRANSFORM, flat(), { length: 3 });
    expect(out.fisher[0]).toBeNull();
    expect(out.fisher[1]).toBeNull();
    expect(out.fisher[2] as number).toBeCloseTo(0.3428282544, 8);
    expect(out.fisher[3] as number).toBeCloseTo(0.7913738721, 8);
  });

  it('runs the floored recursion down a constant series rather than emitting nothing', () => {
    // Every window is flat, so every ratio is 0 and value[n] = -(1 - 0.67^n),
    // clamped at -0.999. Fisher walks toward ln(0.001 / 1.999) = -7.6004023.
    const out = run(FISHER_TRANSFORM, bars(30, () => 100), { length: 9 });
    expect(out.fisher.slice(0, 8).every((v) => v === null)).toBe(true);
    expect(out.fisher[8] as number).toBeCloseTo(-0.3428282544, 8);
    expect(out.fisher[9] as number).toBeCloseTo(-0.7913738721, 8);
    expect(out.fisher[10] as number).toBeCloseTo(-1.2614929494, 8);
    expect(out.fisher[11] as number).toBeCloseTo(-1.7251749835, 8);
    expect(out.fisher[29] as number).toBeCloseTo(-7.5989792976, 8);
    expect(out.fisher.slice(8).every((v) => v !== null && Number.isFinite(v))).toBe(true);
  });

  it('still gaps through warmup, where the window has no extreme yet', () => {
    const out = run(FISHER_TRANSFORM, bars(30, () => 100), { length: 9 });
    expect(out.fisher[7]).toBeNull();
    expect(out.trigger.slice(0, 9).every((v) => v === null)).toBe(true);
    expect(out.trigger[9] as number).toBeCloseTo(-0.3428282544, 8);
  });

  it('gaps on nothing at length 1, where every window is flat by construction', () => {
    // length 1 makes high_ == low_ == hl2 on every bar, so the old zero-span
    // branch blanked the whole series.
    const out = run(FISHER_TRANSFORM, bars(12, (i) => 100 + i), { length: 1 });
    expect(out.fisher.every((v) => v !== null)).toBe(true);
    expect(out.fisher[0] as number).toBeCloseTo(-0.3428282544, 8);
    expect(out.fisher[1] as number).toBeCloseTo(-0.7913738721, 8);
  });
});
