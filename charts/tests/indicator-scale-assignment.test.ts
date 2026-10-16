import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { IndicatorInstance } from '../src/model/indicator-instance';
import type { PriceScaleId } from '../src/model/series';
import type { Bar } from '../src/model/bar';
import { fakeDocument, type FakeElement } from './helpers/fake-dom';

const charts: Chart[] = [];
let next = 0;
const bars = Array.from({ length: 20 }, (_, i) => ({
  time: 1700000000 + i * 60, open: 100 + i, high: 103 + i, low: 99 + i, close: 102 + i,
}));
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

function fixture(patch: Partial<IndicatorDescriptor> = {}) {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const element = document.createElement('div') as unknown as FakeElement;
  const chart = new Chart(element, { document, pixelRatio: () => 1, shortcuts: false,
    animZoom: false, animAutoscale: false,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} },
  });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars);
  chart.setVisibleLogicalRange({ from: 0, to: 19 });
  const calc = vi.fn((source: readonly Bar[]) => ({ upper: source.map(() => 75), lower: source.map(() => 25) }));
  const attach = vi.fn();
  const id = `scale-study-${next++}`;
  registerIndicator({ id, name: 'Band readings', placement: 'pane', inputs: [],
    plots: [{ key: 'upper', type: 'line', title: 'Upper', style: { color: '#ff0000' } },
      { key: 'lower', type: 'line', title: 'Lower', style: { color: '#00ff00' } }],
    fills: [{ between: ['upper', 'lower'] }], levels: () => [{ price: 50, title: 'Middle' }],
    range: () => ({ min: 0, max: 100 }), calc, attach, ...patch,
  });
  const study = chart.addIndicator(id) as IndicatorInstance;
  return { chart, study, calc, attach, id, pane: chart.panes()[study.paneIndex] };
}

describe('whole-study scale assignment', () => {
  it.each<PriceScaleId>(['left', '', 'overlay:study'])('moves all local resources to %j without calculation or lifecycle changes', scaleId => {
    const { chart, study, calc, attach, pane } = fixture();
    const upper = study.series('upper')!, lower = study.series('lower')!, values = study.values();
    const resources = study.renderResources();
    const calls = calc.mock.calls.length, attachments = attach.mock.calls.length;
    const objects = vi.fn(); chart.on('objects:change', objects);
    expect(study.priceScaleId()).toBeNull();
    expect(study.setPriceScale(scaleId)).toBe(true);
    expect(study.priceScaleId()).toBe(scaleId);
    expect(study.series('upper')).toBe(upper); expect(study.series('lower')).toBe(lower);
    expect(study.values()).toBe(values);
    expect(upper.priceScale()).toBe(pane.scaleFor(scaleId));
    expect(lower.priceScale()).toBe(upper.priceScale());
    expect(pane.primitiveScaleId(resources.primitives[0].primitive)).toBe(scaleId);
    expect(upper.priceScale().fixedRange).toEqual({ min: 0, max: 100 });
    expect(pane.priceScale.fixedRange).toBeNull();
    expect(calc).toHaveBeenCalledTimes(calls); expect(attach).toHaveBeenCalledTimes(attachments);
    expect(objects).toHaveBeenCalledTimes(1);
    expect(study.setPriceScale(scaleId)).toBe(false);
    expect(study.setPriceScale(null)).toBe(true);
    expect(upper.priceScale()).toBe(pane.priceScale);
  });

  it('preserves host-configured target ranges and ratio locks through movement and removal', () => {
    const { chart, study, pane } = fixture();
    const target = pane.scaleFor('left'); target.setFixedRange({ min: -100, max: 200 });
    chart.setPriceAxisOptions(study.paneIndex, 'left', { inverted: true });
    expect(chart.setPriceAxisLockRatio(study.paneIndex, 'left', true)).toBe(true);
    const before = pane.scaleStates().left;
    expect(study.setPriceScale('left')).toBe(true);
    expect(pane.scaleStates().left).toEqual(before);
    study.remove();
    expect(target.fixedRange).toEqual({ min: -100, max: 200 });
    expect(target.options.inverted).toBe(true);
  });

  it('restores overrides before calculation and retains them through settings recreation and pane moves', () => {
    const { chart, study } = fixture();
    expect(study.setPriceScale('left')).toBe(true);
    const original = study.series('upper');
    study.setSettings({ 'upper:type': 'area' });
    expect(study.series('upper')).toBe(original);
    expect(chart.seriesType(study.series('upper')!)).toBe('area');
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[1].scaleFor('left'));
    expect(chart.moveIndicator(study.id, 0)).toBe(true);
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.indicators[0].priceScaleId).toBe('left');
    expect(chart.restoreState(state).applied).toBe(true);
    const restored = chart.indicators()[0];
    expect(restored.priceScaleId()).toBe('left');
    expect(restored.series('upper')!.priceScale()).toBe(chart.panes()[0].scaleFor('left'));
  });

  it('rejects invalid and removed requests without notifications or partial mutation', () => {
    const { chart, study } = fixture();
    const objects = vi.fn(); chart.on('objects:change', objects);
    for (const value of ['unknown', 3, undefined, {}, false]) expect(study.setPriceScale(value as never)).toBe(false);
    expect(study.priceScaleId()).toBeNull(); expect(objects).not.toHaveBeenCalled();
    study.remove(); objects.mockClear();
    expect(study.setPriceScale('left')).toBe(false); expect(objects).not.toHaveBeenCalled();
  });

  it.each([false, true])('restores default range ownership with manual intent %j', manual => {
    const { chart, study, pane } = fixture();
    study.setPriceScale('left');
    if (manual) pane.scaleFor('left').setAutoScale(false);
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.panes[1].scales.left.indicatorRange).toEqual({ instanceId: study.id, manual });
    chart.restoreState(state);
    const restored = chart.indicators()[0];
    const scale = restored.series('upper')!.priceScale();
    restored.setPriceScale('right');
    expect(scale.fixedRange).toBeNull();
    expect(scale.autoScale).toBe(!manual);
  });

  it('keeps an equal-valued host fixed range distinct from a study default after restore', () => {
    const { chart, study, pane } = fixture();
    study.setPriceScale('left');
    pane.scaleFor('left').setFixedRange({ min: 0, max: 100 });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(state.panes[1].scales.left.indicatorRange).toBeUndefined();
    chart.restoreState(state);
    const scale = chart.indicators()[0].series('upper')!.priceScale();
    chart.indicators()[0].setPriceScale('right');
    expect(scale.fixedRange).toEqual({ min: 0, max: 100 });
    expect(scale.autoScale).toBe(false);
  });

  it('keeps explicit price overlays on their descriptor scale while moving local plots and levels', () => {
    const { chart, study, pane } = fixture({
      plots: [{ key: 'upper', title: 'Upper', type: 'line' }, { key: 'lower', title: 'Lower', type: 'line' },
        { key: 'price', title: 'Price', type: 'line', overlay: true }],
      calc: source => ({ upper: source.map(() => 75), lower: source.map(() => 25), price: source.map(bar => bar.close) }),
    });
    const overlay = study.series('price')!, priceScale = chart.primarySeries()!.priceScale();
    expect(study.setPriceScale('left')).toBe(true);
    expect(overlay.priceScale()).toBe(priceScale);
    const localPrices = study.renderResources().primitives.filter(item => pane.primitiveScaleId(item.primitive) !== null);
    expect(localPrices).toHaveLength(2);
    expect(localPrices.every(item => pane.primitiveScaleId(item.primitive) === 'left')).toBe(true);
    expect(chart.moveIndicator(study.id, 2)).toBe(true);
    expect(overlay.priceScale()).toBe(priceScale);
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[study.paneIndex].scaleFor('left'));
  });

  it('refuses to restore a fill across different descriptor scales without partial mutation', () => {
    const { chart, study } = fixture({ plots: [
      { key: 'upper', title: 'Upper', type: 'line', priceScaleId: 'left' },
      { key: 'lower', title: 'Lower', type: 'line' },
    ] });
    expect(study.setPriceScale('left')).toBe(true);
    const objects = vi.fn(); chart.on('objects:change', objects);
    expect(study.setPriceScale(null)).toBe(false);
    expect(study.priceScaleId()).toBe('left'); expect(objects).not.toHaveBeenCalled();
    expect(study.series('upper')!.priceScale()).toBe(study.series('lower')!.priceScale());
  });

  it('rejects a pane move that would split a fill from an explicit price overlay', () => {
    const { chart, study } = fixture({ placement: 'onchart', plots: [
      { key: 'upper', title: 'Upper', type: 'line' },
      { key: 'lower', title: 'Lower', type: 'line', overlay: true },
    ] });
    expect(chart.moveIndicator(study.id, 1)).toBe(false);
    expect(study.paneIndex).toBe(0); expect(chart.panes()).toHaveLength(1);
  });

  it('keeps a shared identical range until its final owner leaves', () => {
    const { chart, study, id, pane } = fixture();
    const peer = chart.addIndicator(id, {}, { paneIndex: 1 });
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 100 });
    study.remove();
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 100 });
    peer.setPriceScale('left');
    expect(pane.priceScale.fixedRange).toBeNull();
    expect(pane.scaleFor('left').fixedRange).toEqual({ min: 0, max: 100 });
  });

  it('retains configured destination options when moving a study into an existing pane', () => {
    const { chart, study } = fixture();
    chart.setPriceAxisOptions(0, 'left', { inverted: true, marginTop: 0.23 });
    const target = chart.panes()[0].scaleFor('left'); target.setFixedRange({ min: -20, max: 150 });
    study.setPriceScale('left');
    expect(chart.moveIndicator(study.id, 0)).toBe(true);
    expect(target.options).toMatchObject({ inverted: true, marginTop: 0.23 });
    expect(target.fixedRange).toEqual({ min: -20, max: 150 });
  });

  it('sets initial overrides and rejects invalid saved assignments before replacing existing studies', () => {
    const { chart, study, id } = fixture();
    const added = chart.addIndicator(id, {}, { priceScaleId: 'left' });
    expect(added.priceScaleId()).toBe('left');
    expect(added.series('upper')!.priceScale()).toBe(chart.panes()[added.paneIndex].scaleFor('left'));
    const state = JSON.parse(JSON.stringify(chart.getState()));
    state.indicators[0].priceScaleId = 'invalid';
    expect(chart.restoreState(state).applied).toBe(false);
    expect(chart.indicators()[0]).toBe(study);
    expect(() => chart.addIndicator(id, {}, { priceScaleId: null as never })).toThrow(TypeError);
  });

  it('publishes a complete assignment before synchronous notification reentry', () => {
    const { chart, study, pane, calc } = fixture();
    const calls = calc.mock.calls.length;
    let notifications = 0;
    chart.on('objects:change', () => {
      notifications++;
      if (notifications !== 1) return;
      expect(study.priceScaleId()).toBe('left');
      expect(study.series('upper')!.priceScale()).toBe(pane.scaleFor('left'));
      expect(study.series('lower')!.priceScale()).toBe(pane.scaleFor('left'));
      expect(pane.scaleFor('left').fixedRange).toEqual({ min: 0, max: 100 });
      expect(study.setPriceScale('overlay:again')).toBe(true);
    });
    expect(study.setPriceScale('left')).toBe(true);
    expect(study.priceScaleId()).toBe('overlay:again');
    expect(notifications).toBe(2); expect(calc).toHaveBeenCalledTimes(calls);
  });

  it('retains a uniform assignment after a whole-axis move and later settings changes', () => {
    const { chart, study } = fixture();
    study.setPriceScale('left');
    expect(chart.movePriceAxis(study.paneIndex, 'left', 'right')).toBe(true);
    expect(study.priceScaleId()).toBe('right');
    study.setSettings({ 'upper:type': 'area' });
    expect(study.series('upper')!.priceScale()).toBe(chart.panes()[study.paneIndex].priceScale);
    expect(chart.getState().indicators![0].priceScaleId).toBe('right');
  });

  it('reconciles a study default when an unrelated series enters and leaves its scale', () => {
    const { chart, pane, study } = fixture();
    const host = chart.addSeries('line', { paneIndex: study.paneIndex, priceScaleId: 'left' });
    host.setData(bars.map(bar => ({ ...bar, open: 1000, high: 1000, low: 1000, close: 1000 })));
    chart.setSeriesPriceScale(host, 'right');
    expect(pane.priceScale.fixedRange).toBeNull();
    expect(pane.priceScale.priceRange().max).toBeGreaterThan(1000);
    chart.setSeriesPriceScale(host, 'left');
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 100 });
  });

  it('preserves a shared default and manual view when peers join and its first owner leaves', () => {
    const { chart, study, id, pane } = fixture();
    pane.priceScale.setPriceRange({ min: 10, max: 90 });
    chart.addIndicator(id, {}, { paneIndex: study.paneIndex });
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 100 });
    expect(pane.priceScale.priceRange()).toEqual({ min: 10, max: 90 });
    study.remove();
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 100 });
    expect(pane.priceScale.priceRange()).toEqual({ min: 10, max: 90 });
    pane.priceScale.setAutoScale(true);
    expect(pane.priceScale.priceRange()).toEqual({ min: 0, max: 100 });
  });

  it('does not leak a new attach lifecycle when a settings notification removes the study', () => {
    const detach = vi.fn(), attach = vi.fn(() => detach);
    const { chart, study } = fixture({ attach });
    let handled = false;
    chart.on('objects:change', () => { if (!handled) { handled = true; study.remove(); } });
    study.setSettings({ 'upper:type': 'area' });
    expect(chart.indicators()).toHaveLength(0);
    expect(detach.mock.calls.length).toBe(attach.mock.calls.length);
    chart.destroy();
    expect(detach.mock.calls.length).toBe(attach.mock.calls.length);
  });

  it('reserves and releases a left axis for a study whose only price output is a level', () => {
    const { chart, id } = fixture({ plots: [], fills: [], calc: () => ({}) });
    const study = chart.addIndicator(id, {}, { priceScaleId: 'left' });
    const pane = chart.panes()[study.paneIndex];
    expect(pane.hasLeftScale()).toBe(true);
    expect(chart.timeScale.width).toBe(688);
    study.setVisible(false);
    expect(pane.hasLeftScale()).toBe(false);
    expect(chart.timeScale.width).toBe(744);
    study.setVisible(true);
    expect(chart.timeScale.width).toBe(688);
    expect(chart.movePriceAxis(study.paneIndex, 'left', 'right')).toBe(true);
    expect(study.priceScaleId()).toBe('right');
    study.setVisible(false); study.setVisible(true);
    expect(pane.hasLeftScale()).toBe(false);
  });

  it('retains host configuration and ratio locks on named hidden targets after study removal', () => {
    const { chart, study, pane } = fixture({ fills: [], levels: () => [] });
    chart.addSeries('line', { paneIndex: study.paneIndex, priceScaleId: 'left' }).setData(bars);
    const target = pane.scaleFor('overlay:host');
    target.setFixedRange({ min: -100, max: 200 }); target.setOptions({ inverted: true });
    study.setPriceScale('overlay:host');
    expect(chart.setPriceAxisLockRatio(study.paneIndex, 'overlay:host', true)).toBe(true);
    study.remove();
    expect(pane.scaleFor('overlay:host')).toBe(target);
    expect(target.fixedRange).toEqual({ min: -100, max: 200 });
    expect(target.options.inverted).toBe(true);
    expect(pane.ratioLocked('overlay:host')).toBe(true);
  });

  it('updates the declared fit after settings changes without replacing a manual view', () => {
    const { chart, study, pane } = fixture({
      inputs: [{ key: 'limit', type: 'number', label: 'Limit', default: 100 }],
      range: settings => ({ min: 0, max: Number(settings.limit) }),
    });
    pane.priceScale.setPriceRange({ min: 20, max: 80 });
    study.setSettings({ limit: 200 });
    expect(pane.priceScale.priceRange()).toEqual({ min: 20, max: 80 });
    expect(pane.priceScale.fixedRange).toEqual({ min: 0, max: 200 });
    chart.restoreState(JSON.parse(JSON.stringify(chart.getState())));
    const restored = chart.indicators()[0].series('upper')!.priceScale();
    expect(restored.priceRange()).toEqual({ min: 20, max: 80 });
    restored.setAutoScale(true);
    expect(restored.priceRange()).toEqual({ min: 0, max: 200 });
  });

  it('applies local plot formatting in descriptor order when a plot already uses the target', () => {
    const { study, pane } = fixture({ fills: [], plots: [
      { key: 'upper', title: 'Upper', type: 'line', priceFormat: { type: 'percent', precision: 1 } },
      { key: 'lower', title: 'Lower', type: 'line', priceScaleId: 'left', priceFormat: { type: 'volume' } },
    ] });
    expect(study.setPriceScale('left')).toBe(true);
    expect(pane.scaleFor('left').format(1000)).toBe('1.00K');
  });

  it('refuses a whole-axis move that would require per-plot saved assignments', () => {
    const { chart, study, pane } = fixture({ fills: [], plots: [
      { key: 'upper', title: 'Upper', type: 'line' },
      { key: 'lower', title: 'Lower', type: 'line', priceScaleId: 'overlay:local' },
    ] });
    const moved = vi.fn(); chart.on('priceAxisMoved', moved);
    expect(chart.priceAxisState(study.paneIndex, 'right')!.movable).toBe(false);
    expect(chart.movePriceAxis(study.paneIndex, 'right', 'left')).toBe(false);
    expect(study.series('upper')!.priceScale()).toBe(pane.priceScale);
    expect(moved).not.toHaveBeenCalled();
  });

  it('refuses moving an explicit price-overlay axis even when its study lives elsewhere', () => {
    const { chart } = fixture({ fills: [], plots: [
      { key: 'upper', title: 'Upper', type: 'line' },
      { key: 'lower', title: 'Lower', type: 'line', overlay: true },
    ] });
    const scale = chart.primarySeries()!.priceScale();
    expect(chart.priceAxisState(0, 'right')!.movable).toBe(false);
    expect(chart.movePriceAxis(0, 'right', 'left')).toBe(false);
    expect(chart.primarySeries()!.priceScale()).toBe(scale);
  });
});
