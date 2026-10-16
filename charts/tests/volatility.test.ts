import { describe, it, expect } from 'vitest';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorSettings } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';
import {
  BOLLINGER_PERCENT_B,
  BOLLINGER_BANDWIDTH,
  BB_TREND,
  CHOPPINESS_INDEX,
  HISTORICAL_VOLATILITY,
  AVERAGE_DAILY_RANGE,
  CHOP_ZONE,
  VOLATILITY_INDICATORS,
} from '../src/indicators/volatility';

/** Closes drive the bar; high/low sit one point either side, so range is 2. */
const bars = (n: number, f: (i: number) => number): Bar[] =>
  Array.from({ length: n }, (_, i) => {
    const c = f(i);
    return { time: 1700000000 + i * 60, open: c, high: c + 1, low: c - 1, close: c, volume: 100 + i };
  });

/** Long enough for the 125-bar BandWidth lookbacks to produce something. */
const wave = (n = 200): Bar[] => bars(n, (i) => 100 + Math.sin(i / 5) * 10 + i * 0.05);

const defaults = (d: IndicatorDescriptor): IndicatorSettings => indicatorDefaults(d);
const firstNonNull = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

describe('the reference platform volatility descriptors', () => {
  const data = wave();

  it('exports the eleven studies under their ids', () => {
    expect(VOLATILITY_INDICATORS.map((d) => d.id)).toEqual([
      'bollinger-percent-b',
      'bollinger-bandwidth',
      'bb-trend',
      'choppiness-index',
      'historical-volatility',
      'average-daily-range',
      'chop-zone',
      'chaikin-volatility',
      'standard-deviation',
      'standard-error',
      'volatility-squeeze',
    ]);
    for (const d of VOLATILITY_INDICATORS) expect(d.placement).toBe('pane');
  });

  it('gives every plot a colour key that resolves to a declared input', () => {
    for (const d of VOLATILITY_INDICATORS) {
      for (const plot of d.plots) {
        const declared = d.inputs.find((i) => i.key === plot.colorKey);
        expect(declared?.type, `${d.id}.${plot.key}`).toBe('color');
      }
    }
  });

  it('returns a full-length column of finite numbers or null for every key', () => {
    for (const d of VOLATILITY_INDICATORS) {
      const values = d.calc(data, defaults(d), {});
      for (const plot of d.plots) expect(values[plot.key], `${d.id}.${plot.key} missing`).toBeDefined();
      // Colour-only columns are held to the same contract as plotted ones.
      for (const [key, col] of Object.entries(values)) {
        expect(col.length, `${d.id}.${key} length`).toBe(data.length);
        for (const v of col) {
          expect(v === null || Number.isFinite(v), `${d.id}.${key} emitted ${v}`).toBe(true);
        }
      }
    }
  });

  it('survives empty and single-bar input', () => {
    for (const d of VOLATILITY_INDICATORS) {
      for (const input of [[], data.slice(0, 1)]) {
        const values = d.calc(input, defaults(d), {});
        for (const plot of d.plots) expect(values[plot.key].length).toBe(input.length);
      }
    }
  });
});

describe('Bollinger Bands %b', () => {
  it('is exactly 1 on the upper band and 0 on the lower', () => {
    // With length 2 and mult 1 the bands collapse onto the two closes
    // themselves: population stdev of {a, b} is |a - b| / 2, so upper is the
    // higher close and lower the lower one. %b must then be exactly 1 or 0.
    const alternating = bars(4, (i) => (i % 2 === 0 ? 10 : 20));
    const out = BOLLINGER_PERCENT_B.calc(alternating, { length: 2, mult: 1, source: 'close' }, {});
    expect(out.percentB[1]).toBe(1);
    expect(out.percentB[2]).toBe(0);
    expect(out.percentB[3]).toBe(1);
  });

  it('sits at 0.5 on the basis and scales linearly between the bands', () => {
    const flat = bars(5, (i) => [10, 20, 15, 15, 15][i]);
    // Window {15, 15}: the bands collapse, so the reference 0/0 stays a gap.
    expect(BOLLINGER_PERCENT_B.calc(flat, { length: 2, mult: 1, source: 'close' }, {}).percentB[4]).toBeNull();
  });

  it('starts at index length - 1', () => {
    const out = BOLLINGER_PERCENT_B.calc(wave(), defaults(BOLLINGER_PERCENT_B), {});
    expect(firstNonNull(out.percentB)).toBe(19);
  });

  it('declares the 1 / 0.5 / 0 reference lines', () => {
    expect(BOLLINGER_PERCENT_B.levels?.({}).map((l) => l.price)).toEqual([1, 0.5, 0]);
  });
});

describe('Bollinger BandWidth', () => {
  it('measures the band spread as a percentage of the basis', () => {
    // Window {10, 20}: basis 15, band spread 10, so bandwidth is 200/3 %.
    const alternating = bars(4, (i) => (i % 2 === 0 ? 10 : 20));
    const out = BOLLINGER_BANDWIDTH.calc(
      alternating,
      { length: 2, mult: 1, source: 'close', expansionLength: 2, contractionLength: 2 },
      {},
    );
    expect(out.bandwidth[1]).toBeCloseTo(200 / 3, 10);
  });

  it('tracks the rolling extremes of the bandwidth series itself', () => {
    const data = wave(60);
    const s = { ...defaults(BOLLINGER_BANDWIDTH), expansionLength: 10, contractionLength: 10 };
    const out = BOLLINGER_BANDWIDTH.calc(data, s, {});
    const bbw = out.bandwidth;
    for (let i = 0; i < data.length; i++) {
      if (out.expansion[i] === null) continue;
      const window = bbw.slice(Math.max(0, i - 9), i + 1).filter((v): v is number => v !== null);
      expect(out.expansion[i]).toBeCloseTo(Math.max(...window), 10);
      expect(out.contraction[i]).toBeCloseTo(Math.min(...window), 10);
    }
  });

  it('does not let the bandwidth warmup poison its own extremes', () => {
    // bandwidth starts at 19 (length 20); the 125-bar extremes start as soon as
    // the lookback is long enough, at 124, not at 19 + 124, which is what a
    // NaN-poisoned rolling max would give.
    const out = BOLLINGER_BANDWIDTH.calc(wave(), defaults(BOLLINGER_BANDWIDTH), {});
    expect(firstNonNull(out.bandwidth)).toBe(19);
    expect(firstNonNull(out.expansion)).toBe(124);
    expect(firstNonNull(out.contraction)).toBe(124);
  });
});

describe('BBTrend', () => {
  it('matches a hand-computed short-versus-long band comparison', () => {
    // closes 10 20 30 40. Short (2): basis 35, stdev 5 -> bands 30 / 40.
    // Long  (4): basis 25, stdev sqrt(125) -> bands 25 -/+ 5*sqrt(5).
    // (|30 - (25 - 5r5)| - |40 - (25 + 5r5)|) / 35 * 100, r5 = sqrt(5).
    const rising = bars(4, (i) => 10 + i * 10);
    const out = BB_TREND.calc(rising, { shortLength: 2, longLength: 4, stdDevMult: 1 }, {});
    expect(out.bbtrend[3]).toBeCloseTo(((10 * Math.sqrt(5) - 10) / 35) * 100, 9);
  });

  it('starts once the longer band set is ready', () => {
    const out = BB_TREND.calc(wave(), defaults(BB_TREND), {});
    expect(firstNonNull(out.bbtrend)).toBe(49);
  });

  it('colours the columns by sign and direction, four states in all', () => {
    const plot = BB_TREND.plots[0];
    const settings = defaults(BB_TREND);
    const values = { bbtrend: [1, 2, 1.5, -0.5, -1.5, -1] } as Record<string, (number | null)[]>;
    const at = (i: number): string | undefined =>
      plot.colorBy?.({ value: values.bbtrend[i] as number, index: i, values, settings });
    expect(new Set([at(1), at(2), at(4), at(5)]).size).toBe(4);
    // the reference encodes strength as transparency on two base colours, not as four
    // hues: 25 (opaque-ish, bf) while the trend strengthens, 50 (80) as it fades.
    expect(at(1)).toBe(`${settings.posColor}bf`); // above zero and rising
    expect(at(2)).toBe(`${settings.posColor}80`); // above zero and fading
    expect(at(4)).toBe(`${settings.negColor}bf`); // below zero and falling
    expect(at(5)).toBe(`${settings.negColor}80`); // below zero and recovering
  });

  it('falls back to the weak positive colour where the reference has no matching arm', () => {
    const plot = BB_TREND.plots[0];
    const settings = defaults(BB_TREND);
    const values = { bbtrend: [3, 0] } as Record<string, (number | null)[]>;
    // Bar 0 has no previous value, and an exact zero matches no switch arm.
    expect(plot.colorBy?.({ value: 3, index: 0, values, settings })).toBe(`${settings.posColor}80`);
    expect(plot.colorBy?.({ value: 0, index: 1, values, settings })).toBe(`${settings.posColor}80`);
  });
});

describe('Choppiness Index', () => {
  it('reads 100 when every bar retraces the whole range', () => {
    // Each bar spans exactly 90..110, so 14 true ranges of 20 fit inside a
    // 14-bar range of 20: the ratio is the length, and log_length(length) = 1.
    const ranging: Bar[] = Array.from({ length: 30 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100, high: 110, low: 90,
      close: i % 2 === 0 ? 105 : 95, volume: 1,
    }));
    const out = CHOPPINESS_INDEX.calc(ranging, defaults(CHOPPINESS_INDEX), {});
    expect(out.chop[29]).toBeCloseTo(100, 10);
  });

  it('collapses on a strong trend', () => {
    // Ten points of net travel per bar for two points of bar range: the
    // 14-bar sum of true range barely exceeds the 14-bar range.
    const trend = bars(30, (i) => 100 + i * 10);
    const out = CHOPPINESS_INDEX.calc(trend, defaults(CHOPPINESS_INDEX), {});
    expect(out.chop[29] as number).toBeLessThan(20);
  });

  it('starts at index length - 1 and honours the plot offset', () => {
    const data = wave(60);
    const out = CHOPPINESS_INDEX.calc(data, defaults(CHOPPINESS_INDEX), {});
    expect(firstNonNull(out.chop)).toBe(13);
    const shifted = CHOPPINESS_INDEX.calc(data, { ...defaults(CHOPPINESS_INDEX), offset: 3 }, {});
    expect(firstNonNull(shifted.chop)).toBe(16);
    expect(shifted.chop[20]).toBe(out.chop[17]);
  });

  it('declares the 61.8 / 50 / 38.2 bands and a 0..100 pane', () => {
    expect(CHOPPINESS_INDEX.levels?.({}).map((l) => l.price)).toEqual([61.8, 50, 38.2]);
    expect(CHOPPINESS_INDEX.range?.({})).toEqual({ min: 0, max: 100 });
  });
});

describe('Historical Volatility', () => {
  it('annualises the standard deviation of log returns', () => {
    // Closes alternating 100 / 200 give log returns of +/- ln2, whose
    // population stdev over four of them is exactly ln2.
    const flip = bars(6, (i) => (i % 2 === 0 ? 100 : 200));
    const out = HISTORICAL_VOLATILITY.calc(flip, { length: 4, per: 1 }, {});
    expect(out.hv[4]).toBeCloseTo(100 * Math.log(2) * Math.sqrt(365), 6);
  });

  it('divides the annualisation by the exposed timeframe factor', () => {
    const data = wave(60);
    const daily = HISTORICAL_VOLATILITY.calc(data, { length: 10, per: 1 }, {}).hv;
    const weekly = HISTORICAL_VOLATILITY.calc(data, { length: 10, per: 7 }, {}).hv;
    expect(weekly[40]).toBeCloseTo((daily[40] as number) / Math.sqrt(7), 10);
  });

  it('starts at index length, one bar later than a plain rolling window', () => {
    // The first log return is undefined, and the reference will not average over an
    // `na`, so the window has to clear bar 0 entirely.
    const out = HISTORICAL_VOLATILITY.calc(wave(60), defaults(HISTORICAL_VOLATILITY), {});
    expect(firstNonNull(out.hv)).toBe(10);
  });
});

describe('Average Daily Range', () => {
  it('equals the range itself on a constant-range series', () => {
    const steady = bars(20, (i) => 100 + i); // every bar spans exactly 2
    const out = AVERAGE_DAILY_RANGE.calc(steady, defaults(AVERAGE_DAILY_RANGE), {});
    expect(out.adr[13]).toBe(2);
    expect(out.adr[19]).toBe(2);
  });

  it('averages the last `length` ranges', () => {
    const widening: Bar[] = Array.from({ length: 5 }, (_, i) => ({
      time: 1700000000 + i * 60, open: 100, high: 100 + i, low: 100, close: 100, volume: 1,
    }));
    // Ranges 0 1 2 3 4; the last three average to 3.
    expect(AVERAGE_DAILY_RANGE.calc(widening, { length: 3 }, {}).adr[4]).toBe(3);
  });

  it('starts at index length - 1', () => {
    const out = AVERAGE_DAILY_RANGE.calc(wave(60), defaults(AVERAGE_DAILY_RANGE), {});
    expect(firstNonNull(out.adr)).toBe(13);
  });
});

describe('Chop Zone', () => {
  const colourAt = (values: Record<string, (number | null)[]>, index: number): string | undefined =>
    CHOP_ZONE.plots[0].colorBy?.({ value: 1, index, values, settings: defaults(CHOP_ZONE) });

  it('plots a constant column from the first bar and keeps the angle separate', () => {
    const data = wave(80);
    const out = CHOP_ZONE.calc(data, defaults(CHOP_ZONE), {});
    expect(out.chopZone.every((v) => v === 1)).toBe(true);
    // The EMA needs 34 bars and the slope needs the bar before it.
    expect(firstNonNull(out.angle)).toBe(34);
  });

  it('picks the extreme rungs of the ladder for strong angles', () => {
    const values = { angle: [7, -7, 0, null] } as Record<string, (number | null)[]>;
    expect(colourAt(values, 0)).toBe('#26c6da'); // steep rise
    expect(colourAt(values, 1)).toBe('#d50000'); // steep fall
    expect(colourAt(values, 2)).toBe('#fdd835'); // flat
    expect(colourAt(values, 3)).toBe('#fdd835'); // warmup takes the reference else arm
  });

  it('walks every intermediate rung in order', () => {
    const values = { angle: [4, 3, 2, -2, -3, -4] } as Record<string, (number | null)[]>;
    expect([0, 1, 2, 3, 4, 5].map((i) => colourAt(values, i))).toEqual([
      '#43a047', '#a5d6a7', '#009688', '#ffb74d', '#ff6d00', '#e91e63',
    ]);
  });

  it('turns turquoise in a sustained advance and dark red in a decline', () => {
    const up = CHOP_ZONE.calc(bars(80, (i) => 100 + i), defaults(CHOP_ZONE), {});
    const down = CHOP_ZONE.calc(bars(80, (i) => 200 - i), defaults(CHOP_ZONE), {});
    // A rising EMA gives the reference a negative drop, which the sign flip turns
    // positive, so up is green-side and down is red-side, not the reverse.
    expect(up.angle[79] as number).toBeGreaterThan(5);
    expect(down.angle[79] as number).toBeLessThan(-5);
    expect(colourAt(up as Record<string, (number | null)[]>, 79)).toBe('#26c6da');
    expect(colourAt(down as Record<string, (number | null)[]>, 79)).toBe('#d50000');
  });
});

describe('reference-line background bands', () => {
  const data = wave();
  const banded = [BOLLINGER_PERCENT_B, CHOPPINESS_INDEX];

  it('declares one fill each, whose edges are columns calc actually returns', () => {
    for (const d of banded) {
      const fills = d.fills ?? [];
      expect(fills, d.id).toHaveLength(1);
      expect(fills[0].between, d.id).toEqual(['bandHigh', 'bandLow']);
      // A fill naming a column that does not exist renders nothing and throws
      // nothing, so the edges are checked against calc's output, not the plots.
      const values = d.calc(data, defaults(d), {});
      for (const key of fills[0].between) expect(values[key], `${d.id} fill edge ${key}`).toBeDefined();
    }
  });

  it('shades Bollinger %b between a constant 1 and 0, the warmup included', () => {
    const out = BOLLINGER_PERCENT_B.calc(data, defaults(BOLLINGER_PERCENT_B), {});
    expect(out.bandHigh).toHaveLength(data.length);
    expect(out.bandHigh.every((v) => v === 1)).toBe(true);
    expect(out.bandLow.every((v) => v === 0)).toBe(true);
    // Bar 18 sits inside the 20-bar warmup: no reading, but a full band.
    expect(out.percentB[18]).toBeNull();
    expect(out.bandHigh[18]).toBe(1);
    expect(firstNonNull(out.percentB)).toBe(19);
  });

  it('shades Choppiness between 61.8 and 38.2, and never offsets those edges', () => {
    const s = defaults(CHOPPINESS_INDEX);
    const out = CHOPPINESS_INDEX.calc(data, s, {});
    expect(out.bandHigh.every((v) => v === 61.8)).toBe(true);
    expect(out.bandLow.every((v) => v === 38.2)).toBe(true);
    expect(out.chop[0]).toBeNull();
    expect(out.bandHigh[0]).toBe(61.8);
    // The plot offset moves the study; a reference line stays where it is.
    expect(CHOPPINESS_INDEX.calc(data, { ...s, offset: 3 }, {}).bandHigh).toEqual(out.bandHigh);
    expect(firstNonNull(out.chop)).toBe(13);
  });

  it('paints both bands through a declared colour input at the source opacity', () => {
    const cases = [
      { d: BOLLINGER_PERCENT_B, color: '#2962ff' },
      { d: CHOPPINESS_INDEX, color: '#2196f3' },
    ];
    for (const { d, color } of cases) {
      const fill = (d.fills ?? [])[0];
      expect(fill.colorUpKey, d.id).toBe('fillColor');
      expect(fill.colorDownKey, d.id).toBe('fillColor');
      expect(fill.opacity, d.id).toBe(0.1);
      const declared = d.inputs.find((i) => i.key === 'fillColor');
      expect(declared?.type, d.id).toBe('color');
      expect(declared?.default, d.id).toBe(color);
    }
  });

  it('emits the band columns on empty and single-bar input too', () => {
    for (const d of banded) {
      expect(d.calc([], defaults(d), {}).bandHigh, d.id).toEqual([]);
      expect(d.calc(data.slice(0, 1), defaults(d), {}).bandLow, d.id).toHaveLength(1);
    }
  });
});
