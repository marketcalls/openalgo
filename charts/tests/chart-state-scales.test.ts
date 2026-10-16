import { afterEach, describe, expect, it } from 'vitest';
import { Chart } from '../src/core/chart';
import type { PriceScaleId } from '../src/model/series';
import type { PriceScale } from '../src/scale/price-scale';
import { DEFAULT_PRICE_SCALE_OPTIONS } from '../src/scale/price-scale';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const bars = Array.from({ length: 60 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i,
}));
const ids: PriceScaleId[] = ['right', 'left', '', 'overlay:comparison'];

function makeChart(width = 800, height = 600): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false, animZoom: false, animAutoscale: false,
    raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(width, height);
  for (const id of ids) chart.addSeries('line', { priceScaleId: id }).setData(bars);
  chart.setVisibleLogicalRange({ from: 0, to: 40 });
  return chart;
}

function snapshot(chart: Chart) { return JSON.parse(JSON.stringify(chart.getState())); }
function manual(scale: PriceScale, min: number, max: number): void {
  scale.setAutoScale(false);
  scale.setPriceRange({ min, max });
}
function span(scale: PriceScale): number {
  const range = scale.priceRange();
  return range.max - range.min;
}

afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

describe('saved pane scales', () => {
  it('round-trips independent left and hidden scale options and manual ranges', () => {
    const source = makeChart();
    for (const [index, id] of ids.entries()) {
      const scale = source.panes()[0].scaleFor(id);
      scale.setOptions({ marginTop: 0.12 + index * 0.01, marginBottom: 0.2, minMove: 0,
        minPrecision: 3 + index, mode: index === 1 ? 'logarithmic' : 'linear', inverted: index % 2 === 1 });
      manual(scale, 20 + index * 100, 80 + index * 100);
    }
    const saved = snapshot(source);
    const target = makeChart();
    const beforeData = target.primaryBars();
    expect(target.restoreState(saved).applied).toBe(true);
    for (const [index, id] of ids.entries()) {
      const scale = target.panes()[0].scaleFor(id);
      expect(scale.options).toMatchObject({ marginTop: 0.12 + index * 0.01, marginBottom: 0.2,
        minMove: 0, minPrecision: 3 + index, mode: index === 1 ? 'logarithmic' : 'linear', inverted: index % 2 === 1 });
      expect(scale.priceRange()).toEqual({ min: 20 + index * 100, max: 80 + index * 100 });
      expect(scale.autoScale).toBe(false);
    }
    expect(target.primaryBars()).toEqual(beforeData);
    expect(target.panes()).toHaveLength(1);
    expect(target.panes()[0].series()).toHaveLength(4);
  });

  it('restores each ratio lock before resize and zoom without applying it to another scale', () => {
    const source = makeChart();
    manual(source.panes()[0].scaleFor('left'), 100, 300);
    manual(source.panes()[0].scaleFor('overlay:comparison'), 10, 90);
    expect(source.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    expect(source.setPriceAxisLockRatio(0, 'overlay:comparison', true)).toBe(true);
    const saved = snapshot(source);
    const target = makeChart();
    expect(target.restoreState(saved).applied).toBe(true);
    expect(target.priceAxisState(0, 'left')?.lockRatio).toBe(true);
    expect(target.priceAxisState(0, 'overlay:comparison')?.lockRatio).toBe(true);
    expect(target.priceAxisState(0, 'right')?.lockRatio).toBe(false);
    expect(span(target.panes()[0].scaleFor('left'))).toBeCloseTo(200, 8);
    target.setVisibleLogicalRange({ from: 20, to: 40 });
    expect(span(target.panes()[0].scaleFor('left'))).toBeCloseTo(100, 8);
    expect(span(target.panes()[0].scaleFor('overlay:comparison'))).toBeCloseTo(40, 8);
    target.applySize(800, 1178);
    expect(span(target.panes()[0].scaleFor('left'))).toBeCloseTo(200, 8);
    expect(span(target.panes()[0].scaleFor('overlay:comparison'))).toBeCloseTo(80, 8);
  });

  it('preserves a declared fit range separately from its temporary manual range', () => {
    const source = makeChart();
    const scale = source.panes()[0].scaleFor('');
    scale.setFixedRange({ min: 0, max: 100 });
    manual(scale, 20, 40);
    const target = makeChart();
    expect(target.restoreState(snapshot(source)).applied).toBe(true);
    const restored = target.panes()[0].scaleFor('');
    expect(restored.priceRange()).toEqual({ min: 20, max: 40 });
    target.setPriceAxisAutoFit(0, '', true);
    expect(restored.priceRange()).toEqual({ min: 0, max: 100 });
  });

  it('keeps a saved logarithmic ratio when restoring into a different mode and size', () => {
    const source = makeChart();
    source.setPriceAxisOptions(0, 'left', { mode: 'logarithmic' });
    manual(source.panes()[0].scaleFor('left'), 100, 10000);
    expect(source.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    const saved = snapshot(source);
    const target = makeChart(800, 1178);
    manual(target.panes()[0].scaleFor('left'), 10, 20);
    expect(target.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    expect(target.restoreState(saved).applied).toBe(true);
    const scale = target.panes()[0].scaleFor('left');
    expect(scale.options.mode).toBe('logarithmic');
    expect(scale.priceRange().min).toBeCloseTo(10, 8);
    expect(scale.priceRange().max).toBeCloseTo(100000, 8);
    target.setVisibleLogicalRange({ from: 20, to: 40 });
    expect(scale.priceRange().min).toBeCloseTo(100, 8);
    expect(scale.priceRange().max).toBeCloseTo(10000, 8);
    expect(target.restoreState(saved).applied).toBe(true);
    expect(scale.priceRange().min).toBeCloseTo(10, 8);
    expect(scale.priceRange().max).toBeCloseTo(100000, 8);
  });

  it('retains saved configuration for secondary scales created before their host series arrives', () => {
    const source = makeChart();
    const scale = source.panes()[0].scaleFor('overlay:comparison');
    scale.setOptions({ minPrecision: 5, inverted: true });
    manual(scale, 20, 60);
    const doc = fakeDocument();
    const target = new Chart(doc.createElement('div'), { document: doc, shortcuts: false,
      raf: { schedule: cb => { cb(); return 1; }, cancel: () => {} } });
    charts.push(target);
    target.applySize(800, 600);
    expect(target.restoreState(snapshot(source)).applied).toBe(true);
    expect(target.panes()[0].series()).toHaveLength(0);
    const series = target.addSeries('line', { priceScaleId: 'overlay:comparison' });
    series.setData(bars);
    expect(series.priceScale().options).toMatchObject({ minPrecision: 5, inverted: true });
    expect(series.priceScale().priceRange()).toEqual({ min: 20, max: 60 });
  });

  it('round-trips finite large and single-value ranges accepted by the native scale', () => {
    const source = makeChart();
    manual(source.panes()[0].priceScale, 2e16, 4e16);
    manual(source.panes()[0].scaleFor('left'), 42, 42);
    source.panes()[0].scaleFor('').setOptions({ marginTop: 0.9, marginBottom: 0.2 });
    const target = makeChart();
    expect(target.restoreState(snapshot(source)).applied).toBe(true);
    expect(target.panes()[0].priceScale.priceRange()).toEqual({ min: 2e16, max: 4e16 });
    expect(target.panes()[0].scaleFor('left').priceRange()).toEqual({ min: 42, max: 42 });
    expect(target.panes()[0].scaleFor('').options).toMatchObject({ marginTop: 0.9, marginBottom: 0.2 });
  });

  it('round-trips native scale names and counts without workspace-specific limits', () => {
    const source = makeChart();
    const longId: PriceScaleId = `overlay:${'x'.repeat(240)}`;
    manual(source.panes()[0].scaleFor(longId), 11, 22);
    manual(source.panes()[0].scaleFor('overlay:'), 33, 44);
    for (let index = 0; index < 513; index++) source.panes()[0].scaleFor(`overlay:${index}`);
    const target = makeChart();
    expect(target.restoreState(snapshot(source)).applied).toBe(true);
    expect(target.panes()[0].scaleFor(longId).priceRange()).toEqual({ min: 11, max: 22 });
    expect(target.panes()[0].scaleFor('overlay:').priceRange()).toEqual({ min: 33, max: 44 });
    expect(target.panes()[0].scales()).toHaveLength(source.panes()[0].scales().length);
  });

  it('restores existing host panes beyond the portable workspace pane limit', () => {
    const source = makeChart();
    for (let paneIndex = 1; paneIndex < 33; paneIndex++) {
      source.addSeries('line', { paneIndex }).setData(bars);
    }
    const saved = snapshot(source);
    expect(source.restoreState(saved).applied).toBe(true);
    expect(source.panes()).toHaveLength(33);
    expect(source.primaryBars()).toEqual(bars);
  });

  it('restoring an unlocked scale releases old locks and fixed ranges without changing chart defaults', () => {
    const source = makeChart();
    const saved = snapshot(source);
    const target = makeChart();
    target.panes()[0].scaleFor('left').setFixedRange({ min: 1, max: 2 });
    expect(target.setPriceAxisLockRatio(0, 'left', true)).toBe(true);
    expect(target.restoreState(saved).applied).toBe(true);
    expect(target.priceAxisState(0, 'left')).toMatchObject({ lockRatio: false, autoFit: true });
    expect(target.panes()[0].scaleFor('left').fixedRange).toBeNull();
    expect(DEFAULT_PRICE_SCALE_OPTIONS).toEqual({ marginTop: 0.1, marginBottom: 0.1, minMove: 0,
      minPrecision: 0, mode: 'linear', inverted: false });
    expect(makeChart().panes()[0].scaleFor('left').options).toEqual(DEFAULT_PRICE_SCALE_OPTIONS);
  });

  it('keeps legacy primary-axis restoration and host runtime formatters', () => {
    const target = makeChart();
    target.panes()[0].priceScale.setPriceFormatter(value => `price ${value}`);
    expect(target.restoreState({ version: 1, panes: [{ weight: 1, priceScale: {
      marginTop: 0.2, marginBottom: 0.15, minMove: 0.05, mode: 'linear', inverted: true,
      autoScale: false, range: { min: 90, max: 120 },
    } }] }).applied).toBe(true);
    expect(target.panes()[0].priceScale.priceRange()).toEqual({ min: 90, max: 120 });
    expect(target.panes()[0].priceScale.format(100)).toBe('price 100');
    expect(snapshot(target)).toEqual(target.getState());
  });

  it.each([
    { mode: 'unsupported' }, { minPrecision: -1 }, { marginTop: NaN },
    { range: { min: 5, max: 4 } }, { fixedRange: { min: NaN, max: 10 } },
    { ratioLock: { barSpacing: 0, height: 600 } },
    { ratioLock: { barSpacing: 8, height: Infinity } },
    { autoScale: true, ratioLock: { barSpacing: 8, height: 578 } },
  ])('rejects invalid scale state before mutating the chart: %j', patch => {
    const target = makeChart();
    const before = snapshot(target);
    const saved = snapshot(target);
    saved.grid.vertLines = false;
    saved.panes[0].scales = { left: { ...saved.panes[0].priceScale,
      autoScale: false, range: { min: 20, max: 80 }, ...patch } };
    expect(target.restoreState(saved).applied).toBe(false);
    expect(snapshot(target)).toEqual(before);
  });

  it('rejects unknown scale identities and accessor properties without evaluating them', () => {
    const target = makeChart();
    const before = snapshot(target);
    const saved = snapshot(target);
    saved.panes[0].scales = { unexpected: saved.panes[0].priceScale };
    expect(target.restoreState(saved).applied).toBe(false);
    let reads = 0;
    saved.panes[0].scales = { left: { ...saved.panes[0].priceScale,
      get minMove() { reads++; return 5; } } };
    expect(target.restoreState(saved).applied).toBe(false);
    expect(reads).toBe(0);
    expect(snapshot(target)).toEqual(before);
  });
});
