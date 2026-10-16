import { describe, it, expect } from 'vitest';
import { HULL_SUITE, OVERLAY_INDICATORS } from '../src/indicators/overlay';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorSettings, IndicatorValues } from '../src/model/indicator-registry';
import type { Bar } from '../src/model/bar';

/**
 * Every number below is derived by hand from the published definition of the
 * study and written out here, never read back from the descriptor. Where a
 * closed form exists it is used in preference to a transcription, because a
 * transcription can repeat the same misreading as the code it checks.
 *
 * The closed forms, all of them for a straight line `close = a + b * i`:
 *
 *   A weighted average of a straight line over `p` bars is the line lagged by
 *   `(p - 1) / 3`, and an exponential average seeded with the simple average of
 *   its first `p` values is the line lagged by `(p - 1) / 2` from its very first
 *   printed bar, exactly, because that seed is already the steady state.
 *
 *   At the defaults (length 55, multiplier 1) that gives, with the intermediate
 *   lengths truncated and only the square root rounded:
 *     Hma   inner 27 and 55, outer round(sqrt 55) = 7  ->  lag 4/3
 *     Ehma  inner 27 and 55, outer 7                   ->  lag 2
 *     Thma  half the length, so 27: inner 9, 13, 27,
 *           outer 27                                   ->  lag 4
 */

const bars = (closes: readonly number[]): Bar[] =>
  closes.map((c, i) => ({
    time: 1700000000 + i * 60,
    open: c,
    high: c + 1,
    low: c - 1,
    close: c,
    volume: 100 + i,
  }));

const RAMP_A = 100;
const RAMP_B = 0.5;
/** A straight line, long enough to clear every warmup exercised here. */
const ramp = (n = 200): Bar[] => bars(Array.from({ length: n }, (_, i) => RAMP_A + RAMP_B * i));
const line = (i: number, lag: number): number => RAMP_A + RAMP_B * (i - lag);

/** Seven closes with no repeated window, so a mixed-up length shows up. */
const SEVEN = [10, 14, 12, 13, 16, 11, 15];
const seven = (): Bar[] => bars(SEVEN);
const flat = (n = 40): Bar[] => bars(new Array<number>(n).fill(100));

const run = (data: readonly Bar[], over: Record<string, unknown> = {}): IndicatorValues =>
  HULL_SUITE.calc(data, { ...indicatorDefaults(HULL_SUITE), ...over }, {});

const settingsOf = (over: Record<string, unknown> = {}): IndicatorSettings =>
  ({ ...indicatorDefaults(HULL_SUITE), ...over });

const firstIndex = (col: readonly (number | null)[]): number => col.findIndex((v) => v !== null);

const near = (got: number | null, want: number, eps = 1e-9): void => {
  expect(got).not.toBeNull();
  expect(Math.abs((got as number) - want)).toBeLessThan(eps);
};

/** The colour the plot at `key` paints on bar `index`. */
const colorAt = (
  key: 'mhull' | 'shull',
  values: IndicatorValues,
  index: number,
  settings: IndicatorSettings,
): string | undefined => {
  const plot = HULL_SUITE.plots.find((p) => p.key === key);
  expect(plot?.colorBy).toBeTypeOf('function');
  const raw = values[key][index];
  return plot?.colorBy?.({ value: typeof raw === 'number' ? raw : NaN, index, values, settings });
};

const BULLISH = '#00ff00';
const BEARISH = '#ff0000';
const NEUTRAL = '#ff9800';

describe('Hull Suite - descriptor shape', () => {
  it('is the last overlay registered, on the price pane, with a unique id', () => {
    expect(HULL_SUITE.id).toBe('hull-suite');
    expect(HULL_SUITE.name).toBe('Hull Suite');
    expect(HULL_SUITE.placement).toBe('onchart');
    expect(OVERLAY_INDICATORS[OVERLAY_INDICATORS.length - 1]).toBe(HULL_SUITE);
    const ids = OVERLAY_INDICATORS.map((d) => d.id);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it('declares the inputs of the published definition, and their defaults', () => {
    const byKey = new Map(HULL_SUITE.inputs.map((i) => [i.key, i]));
    expect([...byKey.keys()]).toEqual([
      'source', 'mode', 'length', 'lengthMult', 'switchColor', 'candleCol', 'visualSwitch',
      'bullishColor', 'bearishColor', 'neutralColor',
    ]);
    const defaults = indicatorDefaults(HULL_SUITE);
    expect(defaults.source).toBe('close');
    expect(defaults.mode).toBe('Hma');
    expect(defaults.length).toBe(55);
    expect(defaults.lengthMult).toBe(1);
    expect(defaults.switchColor).toBe(true);
    expect(defaults.candleCol).toBe(false);
    expect(defaults.visualSwitch).toBe(true);
    expect(defaults.bullishColor).toBe(BULLISH);
    expect(defaults.bearishColor).toBe(BEARISH);
    expect(defaults.neutralColor).toBe(NEUTRAL);
    const mode = byKey.get('mode');
    expect(mode?.type).toBe('select');
    expect(mode?.type === 'select' ? mode.options.map((o) => o.value) : []).toEqual(['Hma', 'Thma', 'Ehma']);
  });

  it('offers no control this engine cannot back', () => {
    // A thickness input would have nowhere to land: `style.lineWidth` is static
    // and the plot has no width settings key. A transparency input would have
    // nowhere either: a fill's `opacity` is a fixed number. A higher-timeframe
    // mode cannot be honoured at all, since `calc` only ever sees these bars.
    const keys = HULL_SUITE.inputs.map((i) => i.key.toLowerCase());
    for (const banned of ['width', 'thick', 'transp', 'opacity', 'resolution', 'timeframe', 'htf']) {
      expect(keys.some((k) => k.includes(banned)), `input matching ${banned}`).toBe(false);
    }
  });

  it('plots the hull twice, both keyed to a declared colour input', () => {
    expect(HULL_SUITE.plots.map((p) => p.key)).toEqual(['mhull', 'shull']);
    for (const plot of HULL_SUITE.plots) {
      expect(plot.type).toBe('line');
      expect(plot.style?.lineWidth).toBe(2);
      const declared = HULL_SUITE.inputs.find((i) => i.key === plot.colorKey);
      expect(declared?.type, `${plot.key} colorKey`).toBe('color');
    }
  });

  it('bands the two plots, up where the first leads', () => {
    expect(HULL_SUITE.fills).toHaveLength(1);
    const fill = (HULL_SUITE.fills ?? [])[0];
    expect(fill.between).toEqual(['mhull', 'shull']);
    expect(fill.colorUp).toBe(BULLISH);
    expect(fill.colorDown).toBe(BEARISH);
    expect(fill.colorUpKey).toBe('bullishColor');
    expect(fill.colorDownKey).toBe('bearishColor');
    expect(fill.opacity).toBe(0.6);
  });
});

describe('Hull Suite - the three variations at the defaults', () => {
  const data = ramp();

  it('Hma first prints at 60 and sits 4/3 of a bar behind a straight line', () => {
    // wma over 55 first prints at 54; the outer wma over 7 needs seven of those,
    // so 54 + 6.
    const values = run(data, { mode: 'Hma' });
    expect(firstIndex(values.mhull)).toBe(60);
    near(values.mhull[60], line(60, 4 / 3));
    near(values.mhull[120], line(120, 4 / 3));
    near(values.mhull[199], line(199, 4 / 3));
  });

  it('Ehma first prints at 60 and sits 2 bars behind a straight line', () => {
    // The inner exponential average over 55 first prints at 54, and the outer
    // one is seeded from the simple average of seven of those: 54 + 6.
    const values = run(data, { mode: 'Ehma' });
    expect(firstIndex(values.mhull)).toBe(60);
    near(values.mhull[60], line(60, 2));
    near(values.mhull[130], line(130, 2));
  });

  it('Thma first prints at 52 and sits 4 bars behind a straight line', () => {
    // Half the length, so every window is 27 wide: the inner wma prints at 26
    // and the outer one needs 27 of those, 26 + 26.
    const values = run(data, { mode: 'Thma' });
    expect(firstIndex(values.mhull)).toBe(52);
    near(values.mhull[52], line(52, 4));
    near(values.mhull[100], line(100, 4));
  });

  it('reads the source input rather than always the close', () => {
    // The highs are the closes plus one, so the whole line moves by one.
    const values = run(data, { source: 'high' });
    near(values.mhull[80], line(80, 4 / 3) + 1);
  });
});

describe('Hull Suite - the two quirks of the published definition', () => {
  it('hands the Thma variation half the length, and the others all of it', () => {
    // Length 6 over seven bars. Halved, every Thma window is 3 wide and the
    // first value lands at 2 + 2 = 4. Handed the full 6 instead, the inner wma
    // would not print before bar 5 and the outer would need six more, so the
    // whole column would be empty on this series.
    const values = run(seven(), { mode: 'Thma', length: 6 });
    expect(firstIndex(values.mhull)).toBe(4);

    // Hma at the same setting keeps the full length: inner wma over 6 prints at
    // 5, outer over round(sqrt 6) = 2 needs one more, so bar 6.
    expect(firstIndex(run(seven(), { mode: 'Hma', length: 6 }).mhull)).toBe(6);
  });

  it('rounds the outer square root and truncates the inner lengths', () => {
    // sqrt(63) is 7.94: rounded that is 8, truncated it would be 7. The inner
    // wma over 63 prints at 62, so a rounded root first prints at 69 and a
    // truncated one would print a bar earlier.
    expect(firstIndex(run(ramp(), { length: 63 }).mhull)).toBe(69);

    // And the inner halving truncates: 55 / 2 is 27, not 28. A rounded 28 would
    // put the line 2 bars behind a straight ramp instead of 4/3.
    near(run(ramp(), { length: 55 }).mhull[90], line(90, 4 / 3));
  });

  it('applies the multiplier before the lengths are derived', () => {
    // 55 * 0.5 truncates to 27: inner windows 13 and 27, outer round(sqrt 27) = 5.
    // First value at 26 + 4 = 30, and the lag is (2 * 12 - 26) / 3 + 4 / 3, which
    // is -2/3 + 4/3 = 2/3.
    const values = run(ramp(), { lengthMult: 0.5 });
    expect(firstIndex(values.mhull)).toBe(30);
    near(values.mhull[60], line(60, 2 / 3));
  });
});

describe('Hull Suite - hand-worked values on seven bars', () => {
  // Closes 10, 14, 12, 13, 16, 11, 15 throughout.
  it('Hma at length 4', () => {
    // fast[i] = (2c[i] + c[i-1]) / 3, slow[i] = (4c[i] + 3c[i-1] + 2c[i-2] + c[i-3]) / 10,
    // raw = 2 * fast - slow, hull[i] = (2 raw[i] + raw[i-1]) / 3.
    //   raw[3] = 76/3 - 63/5   = 191/15
    //   raw[4] = 30   - 141/10 = 159/10
    //   raw[5] = 76/3 - 13     = 37/3
    //   raw[6] = 82/3 - 69/5   = 203/15
    const values = run(seven(), { mode: 'Hma', length: 4 });
    expect(firstIndex(values.mhull)).toBe(4);
    near(values.mhull[4], 1336 / 90);
    near(values.mhull[5], 1217 / 90);
    near(values.mhull[6], 591 / 45);
  });

  it('Thma at length 6, which is three bars per window', () => {
    // Windows 1, 1 and 3, so raw[i] = 3c[i] - c[i] - (3c[i] + 2c[i-1] + c[i-2]) / 6,
    // which is (9c[i] - 2c[i-1] - c[i-2]) / 6, then hull = wma(raw, 3).
    //   raw[2] = 35/3, raw[3] = 79/6, raw[4] = 53/3, raw[5] = 9, raw[6] = 97/6
    const values = run(seven(), { mode: 'Thma', length: 6 });
    expect(firstIndex(values.mhull)).toBe(4);
    near(values.mhull[4], 91 / 6);
    near(values.mhull[5], 453 / 36);
    near(values.mhull[6], 505 / 36);
  });

  it('Ehma at length 4, seeded from the simple average and not from bar zero', () => {
    // E(c,2) seeds at bar 1 with (10 + 14) / 2 and runs at 2/3; E(c,4) seeds at
    // bar 3 with 49/4 and runs at 2/5. raw = 2 E2 - E4, first real at bar 3, and
    // the outer E over 2 is seeded from the mean of raw[3] and raw[4].
    //   raw[3] = 76/3 - 49/4 = 157/12,  raw[4] = 268/9 - 55/4 = 577/36
    //   raw[5] = 664/27 - 253/20 = 6449/540
    const values = run(seven(), { mode: 'Ehma', length: 4 });
    // An average seeded from bar zero would print from bar zero. This one does
    // not, which is the whole difference between the two exponential averages
    // this project ships.
    expect(firstIndex(values.mhull)).toBe(4);
    near(values.mhull[4], 131 / 9);
    near(values.mhull[5], 10379 / 810);
  });
});

describe('Hull Suite - the two-bar displacement', () => {
  it('makes shull the same series two bars back, slot for slot', () => {
    for (const mode of ['Hma', 'Thma', 'Ehma']) {
      const values = run(ramp(), { mode });
      const { mhull, shull } = values;
      expect(shull.length).toBe(mhull.length);
      expect(shull[0]).toBeNull();
      expect(shull[1]).toBeNull();
      for (let i = 2; i < mhull.length; i++) {
        expect(shull[i], `${mode} shull[${i}]`).toBe(mhull[i - 2]);
      }
    }
  });

  it('displaces by exactly two, which on a straight line is one bar of value', () => {
    // The ramp climbs 0.5 a bar, so two bars back is a full 1.0 lower. This
    // pins the displacement to two: one bar or three would read 0.5 or 1.5.
    const { mhull, shull } = run(ramp());
    near(shull[100], (mhull[100] as number) - 2 * RAMP_B);
    near(shull[100], line(100, 4 / 3 + 2));
  });

  it('drops the displaced line entirely when the band is switched off', () => {
    const off = run(ramp(), { visualSwitch: false });
    const on = run(ramp(), { visualSwitch: true });
    expect(off.shull.length).toBe(off.mhull.length);
    expect(off.shull.every((v) => v === null)).toBe(true);
    // The hull itself is untouched: the switch hides a view, it does not change
    // the calculation.
    expect(off.mhull).toEqual(on.mhull);
  });
});

describe('Hull Suite - colouring', () => {
  const rising = run(ramp());
  const risingSettings = settingsOf();

  it('paints both lines bullish while the hull is above its own two-bar past', () => {
    expect(colorAt('mhull', rising, 100, risingSettings)).toBe(BULLISH);
    expect(colorAt('shull', rising, 100, risingSettings)).toBe(BULLISH);
  });

  it('paints bearish on a falling series', () => {
    const falling = run(bars(Array.from({ length: 200 }, (_, i) => 300 - 0.5 * i)));
    expect(colorAt('mhull', falling, 100, settingsOf())).toBe(BEARISH);
    expect(colorAt('shull', falling, 100, settingsOf())).toBe(BEARISH);
  });

  it('treats a flat series as not rising, so it reads bearish', () => {
    // Every average of a constant is that constant, so the hull equals its own
    // two-bar past exactly and the comparison is a tie, not a rise.
    const values = run(flat(120));
    near(values.mhull[100], 100);
    expect(values.mhull[100]).toBe(values.shull[100]);
    expect(colorAt('mhull', values, 100, settingsOf())).toBe(BEARISH);
  });

  it('has no rise to report before the second printed bar', () => {
    // Length 1 collapses every window to one bar, so the hull is the source and
    // prints from bar zero. Bars zero and one still have nothing two bars back.
    const values = run(seven(), { length: 1 });
    expect(firstIndex(values.mhull)).toBe(0);
    near(values.mhull[3], 13);
    expect(colorAt('mhull', values, 0, settingsOf({ length: 1 }))).toBe(BEARISH);
    expect(colorAt('mhull', values, 1, settingsOf({ length: 1 }))).toBe(BEARISH);
    // 12 against 10 two bars back is a rise.
    expect(colorAt('mhull', values, 2, settingsOf({ length: 1 }))).toBe(BULLISH);
  });

  it('falls back to the neutral colour when trend colouring is off', () => {
    const s = settingsOf({ switchColor: false });
    for (const index of [60, 100, 199]) {
      expect(colorAt('mhull', rising, index, s)).toBe(NEUTRAL);
      expect(colorAt('shull', rising, index, s)).toBe(NEUTRAL);
    }
  });

  it('honours colours a host has restyled', () => {
    const s = settingsOf({ bullishColor: '#123456', bearishColor: '#654321', neutralColor: '#abcdef' });
    expect(colorAt('mhull', rising, 100, s)).toBe('#123456');
    expect(colorAt('mhull', run(flat(120)), 100, s)).toBe('#654321');
    expect(colorAt('mhull', rising, 100, { ...s, switchColor: false })).toBe('#abcdef');
  });

  it('keeps its colour when the band is hidden, since it reads mhull either way', () => {
    const hidden = run(ramp(), { visualSwitch: false });
    expect(colorAt('mhull', hidden, 100, settingsOf({ visualSwitch: false }))).toBe(BULLISH);
    expect(colorAt('shull', hidden, 100, settingsOf({ visualSwitch: false }))).toBe(BULLISH);
  });

  it('agrees with the band: mhull leads shull exactly where the colour is bullish', () => {
    // This is the reason a plain two-colour fill can carry the trend at all.
    const wave = bars(Array.from({ length: 300 }, (_, i) => 100 + Math.sin(i / 7) * 12 + i * 0.02));
    const values = run(wave);
    const s = settingsOf();
    let seenUp = 0;
    let seenDown = 0;
    for (let i = 0; i < wave.length; i++) {
      const a = values.mhull[i];
      const b = values.shull[i];
      if (a === null || b === null) continue;
      const leads = a > b;
      expect(colorAt('mhull', values, i, s), `bar ${i}`).toBe(leads ? BULLISH : BEARISH);
      if (leads) seenUp += 1; else seenDown += 1;
    }
    expect(seenUp).toBeGreaterThan(0);
    expect(seenDown).toBeGreaterThan(0);
  });
});

describe('Hull Suite - candle colouring', () => {
  const data = ramp();

  it('leaves the candles alone by default', () => {
    const values = run(data);
    const colors = HULL_SUITE.barColors?.({ bars: data, values, settings: settingsOf() });
    expect(colors).toHaveLength(data.length);
    expect(colors?.every((c) => c === null)).toBe(true);
  });

  it('paints every candle the colour the hull is using, when asked', () => {
    const s = settingsOf({ candleCol: true });
    const values = run(data);
    const colors = HULL_SUITE.barColors?.({ bars: data, values, settings: s }) ?? [];
    expect(colors).toHaveLength(data.length);
    for (let i = 0; i < data.length; i++) {
      expect(colors[i], `bar ${i}`).toBe(colorAt('mhull', values, i, s));
    }
    expect(colors[100]).toBe(BULLISH);
  });

  it('paints them neutral when trend colouring is off', () => {
    const s = settingsOf({ candleCol: true, switchColor: false });
    const colors = HULL_SUITE.barColors?.({ bars: data, values: run(data), settings: s }) ?? [];
    expect(colors.every((c) => c === NEUTRAL)).toBe(true);
  });

  it('reads an absent setting as its default, not as on', () => {
    // A host's settings blob carries only what its UI has written, and repainting
    // the price candles is the one thing here that reaches outside the study. An
    // absent key must leave them alone rather than claim them.
    const bare: IndicatorSettings = {};
    const values = HULL_SUITE.calc(data, bare, {});
    expect(HULL_SUITE.barColors?.({ bars: data, values, settings: bare })?.every((c) => c === null))
      .toBe(true);
    // The rest of the defaults hold too: length 55 on the Hma variation, trend
    // colouring on, and the band drawn.
    expect(firstIndex(values.mhull)).toBe(60);
    expect(values.shull[100]).toBe(values.mhull[98]);
    expect(colorAt('mhull', values, 100, bare)).toBe(BULLISH);
  });

  it('returns one entry per bar even with no bars at all', () => {
    const colors = HULL_SUITE.barColors?.({
      bars: [], values: run([]), settings: settingsOf({ candleCol: true }),
    });
    expect(colors).toEqual([]);
  });
});

describe('Hull Suite - degenerate input', () => {
  it('survives an empty series, a single bar, and a series shorter than the warmup', () => {
    for (const mode of ['Hma', 'Thma', 'Ehma']) {
      for (const n of [0, 1, 2, 30]) {
        const data = ramp(n);
        const values = run(data, { mode });
        for (const key of ['mhull', 'shull']) {
          expect(values[key].length, `${mode} ${key} at ${n} bars`).toBe(n);
          expect(values[key].every((v) => v === null), `${mode} ${key} at ${n} bars`).toBe(true);
        }
      }
    }
  });

  it('never emits a non-finite number, whatever the settings say', () => {
    const cases: Record<string, unknown>[] = [
      {},
      { mode: 'Thma' },
      { mode: 'Ehma' },
      { length: 1 },
      { length: 1, mode: 'Thma' },
      { length: 1, mode: 'Ehma' },
      { length: 2, lengthMult: 0.1 },
      { lengthMult: 0 },
      { lengthMult: -3 },
      { length: 0 },
      { length: Number.NaN },
      { lengthMult: Number.POSITIVE_INFINITY },
      { source: 'volume' },
      { mode: 'not-a-mode' },
    ];
    for (const over of cases) {
      for (const data of [ramp(0), ramp(1), seven(), flat(60), ramp(120)]) {
        const values = run(data, over);
        for (const key of ['mhull', 'shull']) {
          const col = values[key];
          expect(col.length, `${JSON.stringify(over)} ${key}`).toBe(data.length);
          for (const v of col) {
            expect(v === null || Number.isFinite(v), `${JSON.stringify(over)} ${key} emitted ${v}`).toBe(true);
          }
        }
      }
    }
  });

  it('falls back to the Hma variation for a mode it does not know', () => {
    expect(run(ramp(), { mode: 'not-a-mode' }).mhull).toEqual(run(ramp(), { mode: 'Hma' }).mhull);
  });

  it('collapses every window to one bar at the shortest length, rather than to none', () => {
    // length 1 leaves half of 1 and a third of 1 at zero before the floor is
    // applied. A zero-bar window would return nothing at all.
    for (const mode of ['Hma', 'Thma', 'Ehma']) {
      const values = run(seven(), { mode, length: 1 });
      expect(firstIndex(values.mhull), mode).toBe(0);
      near(values.mhull[6], 15);
    }
  });
});
