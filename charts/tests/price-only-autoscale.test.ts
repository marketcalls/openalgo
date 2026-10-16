import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import type { PriceScaleId } from '../src/model/series';
import type { IPrimitive } from '../src/primitives/primitive';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
const bars = (values: number[]) => values.map((close, index) => ({
  time: 1700000000 + index * 60, open: close, high: close, low: close, close,
}));

function fixture(options: Partial<ChartOptions> = {}) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false, animZoom: false, animAutoscale: false,
    priceScale: { marginTop: 0, marginBottom: 0 }, timeScale: { maxBarSpacing: 1000 },
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} }, ...options,
  });
  charts.push(chart);
  chart.applySize(800, 600);
  return chart;
}

function populated(options: Partial<ChartOptions> = {}, paneIndex = 0) {
  const chart = fixture(options);
  const primary = chart.addSeries('line', { paneIndex });
  primary.setData(bars([100, 110, 120]));
  const peer = chart.addSeries('line', { paneIndex });
  peer.setData(bars([10000, 11000, 12000]));
  chart.setVisibleLogicalRange({ from: 0, to: 2 });
  return { chart, primary, peer };
}

afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

describe('primary-price-only autoscale', () => {
  it('keeps the default combined range and narrows the measured primary line scale on demand', () => {
    const { chart, primary, peer } = populated();
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 12000 });
    const peerData = peer.getData(), objects = vi.fn();
    chart.on('objects:change', objects);
    expect(chart.priceOnlyAutoScale()).toBe(false);
    chart.setPriceOnlyAutoScale(true);
    expect(primary.priceScale().height).toBeGreaterThan(100);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(chart.priceOnlyAutoScale()).toBe(true);
    expect(peer.getData()).toEqual(peerData);
    expect(chart.panes()[0].series()).toHaveLength(2);
    expect(objects).toHaveBeenCalledTimes(1);
    chart.setPriceOnlyAutoScale(true);
    expect(objects).toHaveBeenCalledTimes(1);
    chart.setPriceOnlyAutoScale(false);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 12000 });
    expect(objects).toHaveBeenCalledTimes(2);
  });

  it('applies the constructor preference to incoming data and forming updates', () => {
    const { chart, primary, peer } = populated({ priceOnlyAutoScale: true });
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    peer.update({ ...bars([0, 0, 90000])[2] });
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    primary.update({ ...bars([0, 0, 140])[2] });
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 140 });
    expect(chart.getState().priceOnlyAutoScale).toBe(true);
  });

  it.each<PriceScaleId>(['left', 'overlay:primary', ''])('follows primary identity onto %j and releases its former scale', id => {
    const { chart, primary, peer } = populated({ priceOnlyAutoScale: true });
    const resident = chart.addSeries('line', { priceScaleId: id });
    resident.priceScale().setOptions({ marginTop: 0, marginBottom: 0 });
    resident.setData(bars([-900, -800, -700]));
    chart.setSeriesPriceScale(primary, id);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(peer.priceScale().priceRange()).toEqual({ min: 10000, max: 12000 });
    chart.setSeriesPriceScale(primary, 'right');
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(resident.priceScale().priceRange()).toEqual({ min: -900, max: -700 });
  });

  it('restricts only the actual primary pane, including after pane reordering', () => {
    const { chart, primary } = populated({ priceOnlyAutoScale: true }, 1);
    const other = chart.addSeries('line', { paneIndex: 0 }); other.setData(bars([-20, 0, 30]));
    chart.addSeries('line', { paneIndex: 0 }).setData(bars([-200, 0, 300]));
    const primaryPane = chart.panes()[1];
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(other.priceScale().priceRange()).toEqual({ min: -200, max: 300 });
    chart.addSeries('line', { paneIndex: 2 });
    expect(chart.movePane(1, 1)).toBe(true);
    expect(chart.panes()[2]).toBe(primaryPane);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(other.priceScale().priceRange()).toEqual({ min: -200, max: 300 });
  });

  it.each(['hidden', 'empty', 'gaps'] as const)('does not fall back to the peer when the primary is %s', state => {
    const { chart, primary, peer } = populated({ priceOnlyAutoScale: true });
    const range = primary.priceScale().priceRange();
    if (state === 'hidden') primary.applyOptions({ visible: false });
    else if (state === 'empty') primary.setData([]);
    else primary.setData(bars([NaN, NaN, NaN]));
    peer.update(bars([0, 0, 90000])[2]);
    chart.setVisibleLogicalRange({ from: 0, to: 2 });
    expect(primary.priceScale().priceRange()).toEqual(range);
  });

  it('leaves other sources unrestricted without a primary and resumes for a new primary', () => {
    const { chart, primary, peer } = populated({ priceOnlyAutoScale: true });
    primary.remove();
    expect(chart.primarySeries()).toBeNull();
    expect(peer.priceScale().priceRange()).toEqual({ min: 10000, max: 12000 });
    const next = chart.addSeries('line'); next.setData(bars([2, 3, 4]));
    expect(chart.primarySeries()).toBe(next);
    expect(next.priceScale().priceRange()).toEqual({ min: 2, max: 4 });
  });

  it('retains the default range when the primary has never had visible data', () => {
    const chart = fixture({ priceOnlyAutoScale: true });
    const primary = chart.addSeries('line');
    chart.addSeries('line').setData(bars([10000, 11000, 12000]));
    chart.setVisibleLogicalRange({ from: 0, to: 2 });
    expect(primary.priceScale().priceRange()).toEqual({ min: 0, max: 1 });
  });

  it.each(['percentage', 'indexed-to-100'] as const)('rebases %s from the offset primary and never a preceding histogram', mode => {
    const chart = fixture({ priceOnlyAutoScale: true });
    chart.addSeries('histogram').setData(bars([1000, 2000, 3000, 4000, 5000]));
    const primary = chart.addSeries('line', { style: { barOffset: 2 } });
    primary.setData(bars([10, 20, 30, 400, 500]));
    primary.priceScale().setOptions({ mode });
    chart.setVisibleLogicalRange({ from: 2, to: 4 });
    expect(chart.primarySeries()).toBe(primary);
    expect(primary.priceScale().baseline).toBe(10);
    expect(primary.priceScale().priceRange()).toEqual({ min: 10, max: 30 });
    primary.applyOptions({ visible: false });
    expect(primary.priceScale().baseline).toBeNull();
    expect(primary.priceScale().priceRange()).toEqual({ min: 10, max: 30 });
  });

  it('uses the current primary renderer extents and its visible bar offset', () => {
    const chart = fixture({ priceOnlyAutoScale: true });
    const primary = chart.addSeries('candlestick', { style: { barOffset: 2 } });
    primary.setData(bars([10, 20, 30, 400, 500]).map(bar => ({ ...bar, high: bar.close + 3, low: bar.close - 2 })));
    chart.addSeries('line').setData(bars([1000, 2000, 3000, 4000, 5000]));
    chart.setVisibleLogicalRange({ from: 2, to: 4 });
    expect(primary.priceScale().priceRange()).toEqual({ min: 8, max: 33 });
    chart.setSeriesType(primary, 'line');
    expect(primary.priceScale().priceRange()).toEqual({ min: 10, max: 30 });
  });

  it.each(['manual', 'fixed', 'ratio'] as const)('does not override a %s range or enable auto-fit', policy => {
    const { chart, primary } = populated();
    const scale = primary.priceScale();
    scale.setAutoScale(false); scale.setPriceRange({ min: 20, max: 40 });
    if (policy === 'fixed') scale.setFixedRange({ min: 20, max: 40 });
    if (policy === 'ratio') expect(chart.setPriceAxisLockRatio(0, 'right', true)).toBe(true);
    const state = chart.priceAxisState(0, 'right');
    chart.setPriceOnlyAutoScale(true);
    expect(scale.priceRange()).toEqual({ min: 20, max: 40 });
    expect(scale.autoScale).toBe(false);
    expect(chart.priceAxisState(0, 'right')).toEqual(state);
    chart.setPriceOnlyAutoScale(false);
    expect(scale.priceRange()).toEqual({ min: 20, max: 40 });
  });

  it('excludes only primary-scale primitive extents and still runs afterAutoscale extensions', () => {
    const { chart, primary } = populated({ priceOnlyAutoScale: true });
    const other = chart.addSeries('line', { priceScaleId: 'left' });
    other.priceScale().setOptions({ marginTop: 0, marginBottom: 0 }); other.setData(bars([1, 2, 3]));
    const primaryExtents = vi.fn(() => ({ min: -50000, max: 50000 }));
    const draw = vi.fn();
    const primitive: IPrimitive = { zOrder: () => 'normal', draw, autoscaleInfo: primaryExtents };
    const side: IPrimitive = { zOrder: () => 'normal', draw() {}, autoscaleInfo: () => ({ min: -600, max: 600 }) };
    chart.addPrimitive(primitive); chart.addPrimitive(side);
    chart.panes()[0].bindPrimitiveScale(side, 'left');
    chart.setGridOptions({ vertLines: false });
    expect(primaryExtents).not.toHaveBeenCalled();
    expect(draw).toHaveBeenCalled();
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(other.priceScale().priceRange()).toEqual({ min: -600, max: 600 });
    chart.addPrimitive({ zOrder: () => 'normal', draw() {}, afterAutoscale() {
      primary.priceScale().setPriceRange({ min: 90, max: 150 });
    } });
    chart.setGridOptions({ vertLines: true });
    expect(primary.priceScale().priceRange()).toEqual({ min: 90, max: 150 });
  });

  it('round-trips the preference, preserves omitted partial restores, and emits changed state', () => {
    const { chart, primary } = populated();
    const objects = vi.fn(); chart.on('objects:change', objects);
    expect(chart.getState().priceOnlyAutoScale).toBe(false);
    expect(chart.restoreState({ version: 1, priceOnlyAutoScale: true }).applied).toBe(true);
    expect(chart.priceOnlyAutoScale()).toBe(true);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 120 });
    expect(objects).toHaveBeenCalled();
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    chart.setPriceOnlyAutoScale(false);
    expect(chart.restoreState(saved).applied).toBe(true);
    expect(chart.priceOnlyAutoScale()).toBe(true);
    chart.restoreState({ version: 1, grid: { vertLines: false, horzLines: false } });
    expect(chart.priceOnlyAutoScale()).toBe(true);
    chart.restoreState({ version: 1, priceOnlyAutoScale: false });
    expect(chart.priceOnlyAutoScale()).toBe(false);
    expect(primary.priceScale().priceRange()).toEqual({ min: 100, max: 12000 });
  });

  it('rejects malformed preferences before any restore mutation', () => {
    const { chart } = populated({ priceOnlyAutoScale: true });
    const before = chart.getState(), started = vi.fn(); chart.on('state:restore:start', started);
    for (const value of [null, 1, 'true', {}]) {
      expect(chart.restoreState({ version: 1, priceOnlyAutoScale: value, grid: { vertLines: false, horzLines: false } }).applied).toBe(false);
      expect(chart.getState()).toEqual(before);
    }
    const read = vi.fn(() => false);
    const state = Object.defineProperty({ version: 1 }, 'priceOnlyAutoScale', { get: read });
    expect(chart.restoreState(state).applied).toBe(false);
    expect(read).not.toHaveBeenCalled();
    expect(started).not.toHaveBeenCalled();
  });

  it('publishes a restored preference after the layout is applied so a newer callback restore wins', () => {
    const { chart, primary } = populated();
    const pane = chart.getState().panes![0];
    let replaced = false;
    chart.on('objects:change', () => {
      if (replaced) return;
      replaced = true;
      chart.restoreState({ version: 1, priceOnlyAutoScale: false,
        panes: [{ ...pane, priceScale: { ...pane.priceScale, marginTop: 0.4 } }] });
    });
    chart.restoreState({ version: 1, priceOnlyAutoScale: true,
      panes: [{ ...pane, priceScale: { ...pane.priceScale, marginTop: 0.2 } }] });
    expect(replaced).toBe(true);
    expect(chart.priceOnlyAutoScale()).toBe(false);
    expect(primary.priceScale().options.marginTop).toBe(0.4);
  });
});
