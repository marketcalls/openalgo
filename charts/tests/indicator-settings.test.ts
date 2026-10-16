/**
 * How the built-ins read a settings blob. A blob carries whatever a settings
 * UI, a saved chart or a host wrote, so every built-in reads it by one rule,
 * whichever module it lives in: the same value means the same thing to all of
 * them.
 */
import { describe, it, expect } from 'vitest';
import { BUILTIN_INDICATORS } from '../src/indicators/index';
import { indicatorDefaults } from '../src/model/indicator-registry';
import type { IndicatorDescriptor, IndicatorSettings, IndicatorValues } from '../src/model/indicator-registry';
import { completeSessions } from './helpers/indicator-golden';

const bars = completeSessions().slice(0, 400);

/**
 * Everything a study derives from its settings: its columns, the colour every
 * coloured plot gives each bar, and what each optional hook returns.
 */
function output(d: IndicatorDescriptor, settings: IndicatorSettings): unknown {
  const values: IndicatorValues = d.calc(bars, settings, {});
  const colours: Record<string, unknown[]> = {};
  for (const plot of d.plots) {
    if (plot.colorBy === undefined && plot.colorParts === undefined) continue;
    colours[plot.key] = (values[plot.key] ?? []).map((value, index) => value === null ? null : [
      plot.colorBy?.({ value, index, values, settings }),
      plot.colorParts?.({ value, index, values, settings }),
    ]);
  }
  const ctx = { bars, values, settings };
  return {
    values, colours,
    markers: d.markers?.(ctx), table: d.table?.(ctx), tables: d.tables?.(ctx), draws: d.draws?.(ctx),
    background: d.background?.(ctx), barColors: d.barColors?.(ctx),
    levels: d.levels?.({ ...settings, settings, bars, values }), range: d.range?.(settings),
  };
}

/** Each built-in with one input set to `value`, against the same study on its defaults. */
function cases(pick: (input: IndicatorDescriptor['inputs'][number]) => boolean) {
  return BUILTIN_INDICATORS.flatMap((d) => d.inputs.filter(pick).map((input) => ({ d, key: input.key })));
}

/**
 * Whole-stepped number inputs whose fraction means something: price levels, a
 * volume scale, an annualising factor, a year, a percent and a table's size.
 * Every other whole-stepped input counts bars.
 */
const NOT_BARS: Readonly<Record<string, readonly string[]>> = {
  rsi: ['overbought', 'oversold'],
  wavetrend: ['obLevel1', 'obLevel2', 'osLevel1', 'osLevel2'],
  'ease-of-movement': ['divisor'],
  'historical-volatility': ['per'],
  seasonality: ['startYear', 'cutoffPercent', 'tableWidth', 'tableHeight'],
};

const wholeStepped = (input: IndicatorDescriptor['inputs'][number]): boolean =>
  input.type === 'number' && input.step === 1 && Number.isInteger(input.default);

describe('built-in settings', () => {
  it('reads a fractional count of bars as the nearest whole number', () => {
    const differ: string[] = [];
    for (const { d, key } of cases((input) => wholeStepped(input) && !/offset|displacement/i.test(input.key))) {
      if (NOT_BARS[d.id]?.includes(key)) continue;
      const defaults = indicatorDefaults(d);
      const x = defaults[key] as number;
      const at = (v: number): string => JSON.stringify(output(d, { ...defaults, [key]: v }));
      // 14.5 reads as 15 and 14.4 as 14: rounded, neither floored nor refused.
      if (at(x + 0.5) !== at(x + 1) || at(x + 0.4) !== at(x)) differ.push(`${d.id}:${key}`);
    }
    expect(differ).toEqual([]);
  });

  it('reads a fractional plot offset as whole bars', () => {
    const differ: string[] = [];
    const offsets = cases((input) => wholeStepped(input) && /offset|displacement/i.test(input.key));
    for (const { d, key } of offsets) {
      const defaults = indicatorDefaults(d);
      const x = defaults[key] as number;
      const at = (v: number): string => JSON.stringify(output(d, { ...defaults, [key]: v }));
      if (at(x + 1.5) !== at(x + 2) || at(x + 1.4) !== at(x + 1)) differ.push(`${d.id}:${key}`);
    }
    expect(offsets.length).toBeGreaterThan(10);
    expect(differ).toEqual([]);
  });

  // A host may call a built-in's calc directly with a partial blob; the chart
  // merges the declared defaults first. Both must compute the same thing.
  it('falls back to the declared default for a setting it is not given', () => {
    const differ = BUILTIN_INDICATORS
      .filter((d) => JSON.stringify(output(d, {})) !== JSON.stringify(output(d, indicatorDefaults(d))))
      .map((d) => d.id);
    expect(differ).toEqual([]);
  });

  it('reads an empty colour or choice as its declared default', () => {
    const differ: string[] = [];
    for (const { d, key } of cases((input) => input.type === 'color' || input.type === 'select')) {
      const defaults = indicatorDefaults(d);
      if (JSON.stringify(output(d, { ...defaults, [key]: '' })) !== JSON.stringify(output(d, defaults))) {
        differ.push(`${d.id}:${key}`);
      }
    }
    expect(differ).toEqual([]);
  });
});
