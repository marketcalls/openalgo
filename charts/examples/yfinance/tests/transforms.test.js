import { describe, it, expect } from 'vitest';
import { getSeriesTransform } from '/dist/openalgo-charts.mjs';
import { BOX_DEFAULTS, boxFields, boxOptions, chartTypeSeries, inChartTransforms, keepsView, sameType, savedTransforms } from '../src/transforms.js';

const PF_QUARTER = { mode: 'percent', percent: 0.25, reversal: 2, method: 'close' };

describe('chartTypeSeries', () => {
  it('hands a renderer choice straight through', () => {
    expect(chartTypeSeries('line')).toEqual({ type: 'line', transform: null });
    expect(chartTypeSeries('candlestick', { 'point-figure': PF_QUARTER })).toEqual({ type: 'candlestick', transform: null });
  });

  it('maps each transform choice onto the renderer and the transform the chart applies', () => {
    expect(inChartTransforms).toBe(true);
    expect(chartTypeSeries('t:heikin-ashi')).toEqual({ type: 'candlestick', transform: { type: 'heikin-ashi' } });
    expect(chartTypeSeries('t:line-break')).toEqual({ type: 'candlestick', transform: { type: 'line-break' } });
    expect(chartTypeSeries('t:kagi')).toEqual({ type: 'kagi', transform: { type: 'kagi' } });
    // The select's value predates the transform's own id and stays for saved layouts.
    expect(chartTypeSeries('t:range')).toEqual({ type: 'candlestick', transform: { type: 'range-bars' } });
  });

  it('draws point and figure and Renko with their own options, or their defaults until they have some', () => {
    expect(chartTypeSeries('t:point-figure').transform)
      .toEqual({ type: 'point-figure', options: { mode: 'atr', atrMultiplier: 1, atrPeriod: 14, reversal: 3, method: 'hl' } });
    expect(chartTypeSeries('t:renko')).toEqual({ type: 'candlestick', transform: { type: 'renko', options: { mode: 'fixed', boxSize: 0, method: 'close' } } });
    const kept = { 'point-figure': PF_QUARTER, renko: { mode: 'atrPercent', percent: 40, atrPeriod: 14, method: 'hl' } };
    expect(chartTypeSeries('t:point-figure', kept).transform).toEqual({ type: 'point-figure', options: PF_QUARTER });
    expect(chartTypeSeries('t:renko', kept).transform).toEqual({ type: 'renko', options: kept.renko });
    // A copy: the chart holding the spec cannot reach back into the demo's options.
    expect(chartTypeSeries('t:point-figure', kept).transform.options).not.toBe(PF_QUARTER);
  });

  it('builds only options the engine takes, for every method and price choice', () => {
    for (const kind of ['point-figure', 'renko']) {
      for (const mode of ['fixed', 'percent', 'atr', 'atrPercent']) {
        for (const method of ['close', 'hl']) {
          const options = boxOptions(kind, { mode, size: 2, reversal: 4, method });
          expect(() => getSeriesTransform(kind).create(options), `${kind} ${mode} ${method}`).not.toThrow();
          expect(boxFields(kind, options)).toEqual({ mode, size: 2, atrPeriod: 14, reversal: kind === 'point-figure' ? 4 : 3, method });
        }
      }
    }
    expect(boxOptions('point-figure', { mode: 'fixed', size: 0, reversal: 3, method: 'hl' })).toEqual({ mode: 'fixed', boxSize: 0, reversal: 3, method: 'hl' });
    expect(boxOptions('point-figure', { mode: 'atr', size: 1.5, reversal: 3, method: 'hl' }))
      .toEqual({ mode: 'atr', atrMultiplier: 1.5, atrPeriod: 14, reversal: 3, method: 'hl' });
    expect(boxOptions('renko', { mode: 'atrPercent', size: 50, method: 'close' })).toEqual({ mode: 'atrPercent', percent: 50, atrPeriod: 14, method: 'close' });
    // Keys left out read as the engine reads them: an option put back to its default is dropped from the spec.
    expect(boxFields('point-figure', {})).toEqual({ mode: 'fixed', size: 0, atrPeriod: 14, reversal: 3, method: 'hl' });
    expect(boxFields('renko', { mode: 'atr' })).toEqual({ mode: 'atr', size: 1, atrPeriod: 14, reversal: 3, method: 'close' });
  });
});

describe('chart types and the view', () => {
  const pf = (options) => ({ chartType: 't:point-figure', transforms: options ? { 'point-figure': options } : {} });

  it('counts a change of options as a change of what is drawn, and defaults as the options they stand for', () => {
    expect(sameType(pf(), pf(BOX_DEFAULTS['point-figure']))).toBe(true);
    expect(sameType(pf(PF_QUARTER), pf({ ...PF_QUARTER }))).toBe(true);
    // Key order is not a difference: a layout may spell the same options another way round.
    expect(sameType(pf(PF_QUARTER), pf({ method: 'close', reversal: 2, percent: 0.25, mode: 'percent' }))).toBe(true);
    expect(sameType(pf(PF_QUARTER), pf({ ...PF_QUARTER, reversal: 3 }))).toBe(false);
    expect(sameType(pf(PF_QUARTER), pf({ ...PF_QUARTER, method: 'hl' }))).toBe(false);
    // Options kept for another transform do not change this one.
    expect(sameType(pf(), { chartType: 't:point-figure', transforms: { renko: { mode: 'percent', percent: 1, method: 'close' } } })).toBe(true);
    expect(sameType({ chartType: 'line' }, { chartType: 'line', transforms: { 'point-figure': PF_QUARTER } })).toBe(true);
  });

  it('keeps the view only where the same elements are drawn', () => {
    expect(keepsView({ chartType: 'candlestick' }, { chartType: 'line' })).toBe(true);
    expect(keepsView({ chartType: 'candlestick' }, { chartType: 't:heikin-ashi' })).toBe(true);
    expect(keepsView({ chartType: 'candlestick' }, pf())).toBe(false);
    expect(keepsView(pf(PF_QUARTER), pf({ ...PF_QUARTER }))).toBe(true);
    // A new box size forms other columns, so the old view would point at nothing.
    expect(keepsView(pf(PF_QUARTER), pf({ ...PF_QUARTER, percent: 0.5 }))).toBe(false);
    expect(keepsView(pf(PF_QUARTER), pf({ ...PF_QUARTER, reversal: 1 }))).toBe(false);
  });
});

describe('saved transform options', () => {
  it('reads the options a layout saved, as copies', () => {
    const saved = { transforms: { 'point-figure': PF_QUARTER } };
    const read = savedTransforms(saved);
    expect(read).toEqual({ 'point-figure': PF_QUARTER });
    expect(read['point-figure']).not.toBe(PF_QUARTER);
  });

  it('migrates the old box mode to the options it drew', () => {
    expect(savedTransforms({ pfmode: 'atr' })).toEqual({ 'point-figure': BOX_DEFAULTS['point-figure'] });
    expect(savedTransforms({ pfmode: 'percent' })).toEqual({ 'point-figure': { mode: 'percent', percent: 1, reversal: 3, method: 'hl' } });
    expect(savedTransforms({ pfmode: 'fixed' })).toEqual({ 'point-figure': { mode: 'fixed', boxSize: 0, reversal: 3, method: 'hl' } });
    expect(savedTransforms({})).toEqual({});
    for (const pfmode of ['unknown', 'toString', 3, null]) expect(savedTransforms({ pfmode }), String(pfmode)).toBeNull();
  });

  it('refuses options the engine would refuse, or a transform without settings here', () => {
    for (const transforms of [null, [], 'renko', { renko: null }, { kagi: {} }, { renko: { reversal: 2 } },
      { 'point-figure': { mode: 'percent', percent: 'one' } }, { 'point-figure': { reversal: 1.5 } }, { renko: { method: 'open' } }]) {
      expect(savedTransforms({ transforms }), JSON.stringify(transforms)).toBeNull();
    }
  });
});
