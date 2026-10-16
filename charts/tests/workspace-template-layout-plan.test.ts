import { afterEach, describe, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator, type IndicatorDescriptor } from '../src/model/indicator-registry';
import type { PaneState } from '../src/model/chart-state';
import type { PriceScaleId } from '../src/model/series';
import type { IndicatorTemplatePayload } from '../src/workspace/documents';
import { captureIndicatorTemplate, planIndicatorTemplateState } from '../src/workspace/template-layout';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
let sequence = 0;
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });
function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, shortcuts: false, branding: false,
    pixelRatio: () => 1, raf: { schedule: () => 1, cancel() {} } });
  charts.push(chart); chart.applySize(800, 500);
  const primary = chart.addSeries('candlestick');
  primary.setData([1, 2, 3].map(time => ({ time, open: 10, high: 20, low: 5, close: 12 })));
  return { chart, primary };
}
function descriptor(patch: Partial<IndicatorDescriptor> = {}) {
  const value: IndicatorDescriptor = { id: `template-layout-${sequence++}`, name: 'Layout study', placement: 'onchart', inputs: [],
    plots: [{ key: 'local', title: 'Local', type: 'line', priceScaleId: 'overlay:metric' },
      { key: 'price', title: 'Price', type: 'line', overlay: true }],
    calc: bars => ({ local: bars.map(() => 2), price: bars.map(bar => bar.close) }), ...patch };
  registerIndicator(value); return value;
}
function payload(chart: Chart): IndicatorTemplatePayload {
  const state = chart.getState();
  return { indicators: state.indicators!, layout: { panes: state.panes!, primaryScaleId: 'right',
    plots: chart.indicators().flatMap(study => ['local', 'price'].map(plotKey => ({ instanceId: study.id, plotKey,
      paneIndex: plotKey === 'price' ? 0 : study.paneIndex, scaleId: study.plotPriceScaleId(plotKey)! }))) } };
}
function scale(pane: PaneState, id: PriceScaleId) { return id === 'right' ? pane.priceScale : pane.scales?.[id]; }

describe('native portable template layout planning', () => {
  it('captures actual primary identity, effective bindings and detached pane configuration', () => {
    const { chart, primary } = fixture(), spec = descriptor();
    const study = chart.addIndicator(spec.id);
    chart.setSeriesPriceScale(primary, 'overlay:quotes');
    chart.setPriceAxisPlacement(0, 'overlay:quotes', 'left');
    study.setPlotPriceScales({ price: 'overlay:quotes' });
    const before = chart.getState(), captured = captureIndicatorTemplate(chart);
    expect(captured.layout?.primaryScaleId).toBe('overlay:quotes');
    expect(captured.layout?.plots).toEqual([
      { instanceId: study.id, plotKey: 'local', paneIndex: 0, scaleId: 'overlay:metric' },
      { instanceId: study.id, plotKey: 'price', paneIndex: 0, scaleId: 'overlay:quotes' },
    ]);
    expect(captured.indicators[0].instanceId).toBe(study.id);
    captured.layout!.panes[0].weight = 7; captured.indicators[0].settings.changed = true;
    expect(chart.getState()).toEqual(before);
  });

  it('copies independent main scales and follows destination primary identity without changing its view', () => {
    const source = fixture(), destination = fixture(), spec = descriptor();
    source.chart.addIndicator(spec.id);
    source.chart.setPriceAxisPlacement(0, 'overlay:metric', 'right');
    source.chart.panes()[0].scaleFor('overlay:metric').setOptions({ inverted: true, minMove: 0.25 });
    destination.chart.setSeriesPriceScale(destination.primary, 'left');
    destination.primary.priceScale().setAutoScale(false); destination.primary.priceScale().setPriceRange({ min: 8, max: 18 });
    const before = destination.chart.getState(), input = payload(source.chart);
    const result = planIndicatorTemplateState(destination.chart, input, 'append');
    const study = result.indicators[0], id = study.plotPriceScaleIds!.local;
    expect(id).toMatch(/^overlay:/); expect(id).not.toBe('overlay:metric');
    expect(study.plotPriceScaleIds!.price).toBe('left');
    expect(scale(result.panes![0], id)).toMatchObject({ inverted: true, minMove: 0.25, autoScale: true, placement: { side: 'right', order: 1 } });
    expect(result.panes![0].scales!.left).toEqual(before.panes![0].scales!.left);
    expect(destination.chart.getState()).toEqual(before);
    expect(destination.chart.restoreState({ ...before, ...result }, result.restoreOptions).applied).toBe(true);
    expect(destination.chart.primarySeries()).toBe(destination.primary);
    expect(destination.chart.indicators()[0].series('price')!.priceScale()).toBe(destination.primary.priceScale());
  });

  it('deliberately shares existing main scale configuration and isolates repeated rich copies', () => {
    const source = fixture(), destination = fixture(), spec = descriptor(); source.chart.addIndicator(spec.id);
    destination.chart.addSeries('line', { priceScaleId: 'overlay:metric' });
    destination.chart.panes()[0].scaleFor('overlay:metric').setOptions({ minMove: 3, inverted: true });
    const input = payload(source.chart), before = destination.chart.getState();
    const shared = planIndicatorTemplateState(destination.chart, input, 'append', { scalePolicy: 'share' });
    expect(shared.indicators[0].plotPriceScaleIds!.local).toBe('overlay:metric');
    expect(shared.panes![0].scales!['overlay:metric']).toEqual(before.panes![0].scales!['overlay:metric']);
    const first = planIndicatorTemplateState(destination.chart, input, 'replace');
    const second = planIndicatorTemplateState(destination.chart, input, 'replace');
    expect(first.indicators[0].instanceId).not.toBe(input.indicators[0].instanceId);
    expect(second.indicators[0].instanceId).not.toBe(first.indicators[0].instanceId);
    expect(second.indicators[0].plotPriceScaleIds!.local).not.toBe(first.indicators[0].plotPriceScaleIds!.local);
  });

  it('keeps positive study groups together, reserves host panes and scales relative weights', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane' });
    source.chart.addIndicator(spec.id); source.chart.addIndicator(spec.id, {}, { paneIndex: 1 });
    source.chart.setPaneWeight(0, 2); source.chart.setPaneWeight(1, 1);
    destination.chart.addIndicator(spec.id);
    const host = destination.chart.addSeries('line', { paneIndex: 2 }); host.setData([{ time: 1, value: 20 }]);
    destination.chart.setPaneWeight(0, 4);
    const replaced = planIndicatorTemplateState(destination.chart, payload(source.chart), 'replace');
    expect(replaced.indicators.map(item => item.paneIndex)).toEqual([1, 1]);
    expect(replaced.panes![0].weight).toBe(4); expect(replaced.panes![1].weight).toBe(2);
    const hostScale = host.priceScale(); expect(destination.chart.restoreState({ ...destination.chart.getState(), ...replaced }, replaced.restoreOptions).applied).toBe(true);
    expect(host.priceScale()).toBe(hostScale); expect(host.getData()[0].close).toBe(20);
    const appended = planIndicatorTemplateState(destination.chart, payload(source.chart), 'append');
    expect(appended.indicators.slice(-2).map(item => item.paneIndex)).toEqual([3, 3]);
  });

  it('drops copied manual views by default while preserving explicit host fixed bands', () => {
    const source = fixture(), destination = fixture(), spec = descriptor(); source.chart.addIndicator(spec.id);
    const metric = source.chart.panes()[0].scaleFor('overlay:metric');
    metric.setFixedRange({ min: 0, max: 100 }); metric.setAutoScale(false); metric.setPriceRange({ min: 20, max: 30 });
    const input = payload(source.chart);
    input.layout!.panes[0].scales!['overlay:metric']!.ratioLock = { barSpacing: 8, height: 200 };
    const automatic = planIndicatorTemplateState(destination.chart, input, 'append');
    const id = automatic.indicators[0].plotPriceScaleIds!.local;
    expect(scale(automatic.panes![0], id)).toMatchObject({ autoScale: true, fixedRange: { min: 0, max: 100 } });
    expect(scale(automatic.panes![0], id)).not.toHaveProperty('range');
    expect(scale(automatic.panes![0], id)).not.toHaveProperty('ratioLock');
    const preserved = planIndicatorTemplateState(destination.chart, input, 'append', { rangePolicy: 'preserve' });
    expect(scale(preserved.panes![0], preserved.indicators[0].plotPriceScaleIds!.local)).toMatchObject({ autoScale: false,
      range: { min: 20, max: 30 }, ratioLock: { barSpacing: 8, height: 200 } });
  });

  it('rejects unknown or incomplete descriptor bindings before any destination mutation', () => {
    const source = fixture(), destination = fixture(), spec = descriptor(); source.chart.addIndicator(spec.id);
    const before = destination.chart.getState();
    for (const change of [(p: IndicatorTemplatePayload) => p.layout!.plots.pop(),
      (p: IndicatorTemplatePayload) => { p.layout!.plots[0].plotKey = 'unknown'; },
      (p: IndicatorTemplatePayload) => { p.layout!.plots[1].paneIndex = 1; }]) {
      const input = payload(source.chart); change(input);
      expect(() => planIndicatorTemplateState(destination.chart, input, 'append')).toThrow();
      expect(destination.chart.getState()).toEqual(before);
    }
  });

  it('retains legacy anonymous identity and omitted panes behavior', () => {
    const source = fixture(), destination = fixture(), spec = descriptor(); source.chart.addIndicator(spec.id);
    const legacy = planIndicatorTemplateState(destination.chart, source.chart.getState().indicators!, 'replace');
    expect(legacy).not.toHaveProperty('panes'); expect(legacy).not.toHaveProperty('restoreOptions'); expect(legacy.indicators[0]).not.toHaveProperty('instanceId');
  });

  it('remaps declared dependencies and all identities while leaving opaque settings alone', () => {
    const source = fixture(), destination = fixture();
    const spec = descriptor({ inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true }] });
    const producer = source.chart.addIndicator(spec.id);
    source.chart.addIndicator(spec.id, { source: { kind: 'indicator', instanceId: producer.id, plotKey: 'local' },
      annotation: { instanceId: producer.id, plotKey: 'local' } });
    const input = captureIndicatorTemplate(source.chart), original = structuredClone(input);
    const result = planIndicatorTemplateState(destination.chart, input, 'append');
    expect(new Set(result.indicators.map(study => study.instanceId)).size).toBe(2);
    expect(result.indicators[1].settings.source).toEqual({ kind: 'indicator', instanceId: result.indicators[0].instanceId, plotKey: 'local' });
    expect(result.indicators[1].settings.annotation).toEqual({ instanceId: producer.id, plotKey: 'local' });
    expect(result.indicators[0].plotPriceScaleIds!.local).toBe(result.indicators[1].plotPriceScaleIds!.local);
    expect(input).toEqual(original);
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...result }, result.restoreOptions).applied).toBe(true);
    expect(destination.chart.indicators()).toHaveLength(2);
  });

  it('copies scale identity separately per pane and preserves a price-pane overlay attachment', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane' });
    const first = source.chart.addIndicator(spec.id), second = source.chart.addIndicator(spec.id);
    first.setPlotPriceScales({ price: 'overlay:metric' });
    source.chart.panes()[1].scaleFor('overlay:metric').setOptions({ minMove: 1 });
    source.chart.panes()[2].scaleFor('overlay:metric').setOptions({ minMove: 2 });
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append');
    expect(plan.indicators.map(study => study.paneIndex)).toEqual([1, 2]);
    expect(plan.indicators[0].plotPriceScaleIds!.local).toBe('overlay:metric');
    expect(plan.indicators[0].plotPriceScaleIds!.price).not.toBe('overlay:metric');
    expect(plan.panes![1].scales!['overlay:metric']!.minMove).toBe(1);
    expect(plan.panes![2].scales!['overlay:metric']!.minMove).toBe(2);
    expect(second.paneIndex).toBe(2);
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    const restored = destination.chart.indicators()[0];
    expect(restored.series('price')!.priceScale()).toBe(destination.chart.panes()[0].scaleFor(plan.indicators[0].plotPriceScaleIds!.price));
  });

  it('appends visible copied columns in source order after existing destination columns', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ plots: [
      { key: 'a', title: 'A', type: 'line', priceScaleId: 'overlay:a' },
      { key: 'b', title: 'B', type: 'line', priceScaleId: 'overlay:b' },
      { key: 'c', title: 'C', type: 'line', priceScaleId: 'left' },
    ], calc: bars => ({ a: bars.map(() => 1), b: bars.map(() => 2), c: bars.map(() => 3) }) });
    source.chart.addIndicator(spec.id);
    source.chart.setPriceAxisPlacement(0, 'overlay:a', 'right');
    source.chart.setPriceAxisPlacement(0, 'overlay:b', 'right', 1);
    destination.chart.addSeries('line', { priceScaleId: 'overlay:existing' });
    destination.chart.setPriceAxisPlacement(0, 'overlay:existing', 'right');
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append');
    const map = plan.indicators[0].plotPriceScaleIds!;
    expect(scale(plan.panes![0], map.b)!.placement).toEqual({ side: 'right', order: 2 });
    expect(scale(plan.panes![0], map.a)!.placement).toEqual({ side: 'right', order: 3 });
    expect(scale(plan.panes![0], map.c)!.placement).toEqual({ side: 'left', order: 0 });
    expect(plan.panes![0].scales).not.toHaveProperty('overlay:a');
  });

  it.each(['auto', 'preserve'] as const)('remaps owned default metadata correctly with %s range policy', rangePolicy => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane', range: () => ({ min: 0, max: 100 }) });
    const study = source.chart.addIndicator(spec.id), metric = source.chart.panes()[1].scaleFor('overlay:metric');
    metric.setAutoScale(false); metric.setPriceRange({ min: 20, max: 30 });
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append', { rangePolicy });
    const saved = plan.panes![1].scales!['overlay:metric']!;
    if (rangePolicy === 'auto') { expect(saved).not.toHaveProperty('indicatorRange'); expect(saved).not.toHaveProperty('fixedRange'); }
    else expect(saved.indicatorRange).toEqual({ instanceId: plan.indicators[0].instanceId, manual: true });
    expect(plan.indicators[0].instanceId).not.toBe(study.id);
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    const restored = destination.chart.panes()[1].scaleFor('overlay:metric');
    expect(restored.fixedRange).toEqual({ min: 0, max: 100 });
    expect(restored.priceRange()).toEqual(rangePolicy === 'auto' ? { min: 0, max: 100 } : { min: 20, max: 30 });
    expect(destination.chart.getState().panes![1].scales!['overlay:metric']!.indicatorRange?.instanceId).toBe(plan.indicators[0].instanceId);
  });

  it('clears orphan outgoing defaults while retaining a host manual view on an unused destination scale', () => {
    const source = fixture(), destination = fixture(), old = descriptor({ range: () => ({ min: 0, max: 100 }) });
    destination.chart.addIndicator(old.id);
    const metric = destination.chart.panes()[0].scaleFor('overlay:metric');
    metric.setAutoScale(false); metric.setPriceRange({ min: 23, max: 29 });
    const next = descriptor({ plots: [{ key: 'price', type: 'line', title: 'Price', overlay: true }] });
    source.chart.addIndicator(next.id);
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'replace');
    const retained = plan.panes![0].scales!['overlay:metric']!;
    expect(retained).not.toHaveProperty('indicatorRange'); expect(retained).not.toHaveProperty('fixedRange');
    expect(retained).toMatchObject({ autoScale: false, range: { min: 23, max: 29 } });
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    expect(metric.fixedRange).toBeNull(); expect(metric.priceRange()).toEqual({ min: 23, max: 29 });
  });

  it('captures and restores primitive-only fallback scales without losing their positive pane', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane', plots: [],
      calc: () => ({}), range: () => ({ min: -1, max: 1 }), levels: () => [{ price: 0 }] });
    source.chart.addIndicator(spec.id, {}, { priceScaleId: 'left' });
    const input = captureIndicatorTemplate(source.chart);
    expect(input.layout!.plots).toEqual([]);
    const plan = planIndicatorTemplateState(destination.chart, input, 'append');
    expect(plan.indicators[0].priceScaleId).toBe('left');
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    expect(destination.chart.indicators()).toHaveLength(1); expect(destination.chart.panes()).toHaveLength(2);
    expect(destination.chart.panes()[1].scaleFor('left').fixedRange).toEqual({ min: -1, max: 1 });
  });

  it('counts only live study handles when reserving a destination host pane', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane' });
    source.chart.addIndicator(spec.id);
    const removed = destination.chart.addIndicator(spec.id); removed.series('local')!.remove();
    const host = destination.chart.addSeries('line', { paneIndex: 1 });
    host.setData([{ time: 1, value: 25 }]);
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'replace');
    expect(plan.indicators[0].paneIndex).toBe(2);
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    expect(host.getData()[0].close).toBe(25);
  });

  it('rejects capture after a declared plot is removed and rejects invalid policy options without calling accessors', () => {
    const source = fixture(), destination = fixture(), spec = descriptor();
    const study = source.chart.addIndicator(spec.id), input = captureIndicatorTemplate(source.chart);
    study.series('local')!.remove(); expect(() => captureIndicatorTemplate(source.chart)).toThrow(/removed/i);
    const getter = vi.fn(() => 'share');
    for (const options of [{ scalePolicy: 'unknown' }, { rangePolicy: null }, Object.defineProperty({}, 'scalePolicy', { enumerable: true, get: getter })]) {
      expect(() => planIndicatorTemplateState(destination.chart, input, 'append', options as never)).toThrow();
    }
    expect(getter).not.toHaveBeenCalled();
  });

  it('keeps empty append a no-op and rejects a positive pane beyond the native limit', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane' });
    destination.chart.addSeries('line', { paneIndex: 31 });
    const before = destination.chart.getState();
    const empty = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append');
    expect(empty.indicators).toEqual([]); expect(empty).not.toHaveProperty('panes');
    source.chart.addIndicator(spec.id);
    expect(() => planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append')).toThrow(/pane limit/i);
    expect(destination.chart.getState()).toEqual(before);
  });

  it('rejects remapping a calculated overlay fill fallback away from its fixed right binding', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({
      plots: [{ key: 'price', title: 'Price', type: 'line', overlay: true }],
      fills: [{ between: ['price', 'base'], overlay: true }],
      calc: bars => ({ price: bars.map(bar => bar.close), base: bars.map(() => 10) }),
    });
    source.chart.addIndicator(spec.id); destination.chart.setSeriesPriceScale(destination.primary, 'left');
    const before = destination.chart.getState();
    expect(() => planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append')).toThrow(/fill/i);
    expect(destination.chart.getState()).toEqual(before);
  });

  it('rejects missing or spurious dependency metadata and unknown scalar source plots', () => {
    const source = fixture(), destination = fixture();
    const spec = descriptor({ inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true }] });
    const producer = source.chart.addIndicator(spec.id);
    source.chart.addIndicator(spec.id, { source: { kind: 'indicator', instanceId: producer.id, plotKey: 'local' } });
    const before = destination.chart.getState();
    for (const modify of [
      (p: IndicatorTemplatePayload) => { delete p.indicators[1].studyInputs; },
      (p: IndicatorTemplatePayload) => { p.indicators[1].settings.annotation = p.indicators[1].settings.source;
        p.indicators[1].settings.source = 'close'; p.indicators[1].studyInputs = ['annotation']; },
      (p: IndicatorTemplatePayload) => { (p.indicators[1].settings.source as { plotKey: string }).plotKey = 'unknown'; },
    ]) {
      const input = captureIndicatorTemplate(source.chart); modify(input);
      expect(() => planIndicatorTemplateState(destination.chart, input, 'append')).toThrow(/source|depend|input|plot/i);
      expect(destination.chart.getState()).toEqual(before);
    }
  });

  it('creates default state only for an unused explicit whole scale and keeps its future fallback', () => {
    const source = fixture(), destination = fixture(), spec = descriptor();
    source.chart.addIndicator(spec.id, {}, { priceScaleId: 'overlay:unused', plotPriceScaleIds: { local: 'left' } });
    const input = captureIndicatorTemplate(source.chart);
    expect(input.layout!.panes[0].scales).not.toHaveProperty('overlay:unused');
    const plan = planIndicatorTemplateState(destination.chart, input, 'append');
    const whole = plan.indicators[0].priceScaleId!;
    expect(whole).not.toBe('overlay:unused');
    expect(scale(plan.panes![0], whole)).toMatchObject({ mode: 'linear', autoScale: true, minMove: 0 });
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    const restored = destination.chart.indicators()[0];
    restored.setPlotPriceScales({ local: null }); expect(restored.plotPriceScaleId('local')).toBe(whole);
  });

  it.each([true, false])('preserves the destination primary formatter choice and numeric precision (custom=%s)', custom => {
    const source = fixture(), destination = fixture(), spec = descriptor({
      plots: [{ key: 'price', type: 'line', title: 'Price', priceFormat: { type: 'percent', precision: 0 }, style: { precision: 0 } }],
    });
    source.chart.addIndicator(spec.id);
    destination.chart.setSeriesPriceScale(destination.primary, 'left');
    const axis = destination.primary.priceScale();
    const formatter = (value: number) => `Quote ${value.toFixed(2)}`;
    axis.setPriceFormatter(custom ? formatter : null); axis.setOptions({ minMove: 0.01, minPrecision: 2 });
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append');
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    expect(axis.format(12.345)).toBe(custom ? 'Quote 12.35' : '12.35');
    expect(axis.options).toMatchObject({ minMove: 0.01, minPrecision: 2 });
    expect(plan.restoreOptions?.preserveScaleFormats).toEqual([{ paneIndex: 0, scaleId: 'right' }, { paneIndex: 0, scaleId: 'left' }]);
  });

  it('keeps a deliberately shared named scale formatter while new copy scales use their descriptor format', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ plots: [
      { key: 'local', title: 'Ratio', type: 'line', priceScaleId: 'overlay:metric', priceFormat: { type: 'percent', precision: 1 } },
    ] });
    source.chart.addIndicator(spec.id);
    destination.chart.addSeries('line', { priceScaleId: 'overlay:metric' });
    const axis = destination.chart.panes()[0].scaleFor('overlay:metric');
    axis.setPriceFormatter(value => `Metric ${value}`);
    const input = captureIndicatorTemplate(source.chart);
    const shared = planIndicatorTemplateState(destination.chart, input, 'append', { scalePolicy: 'share' });
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...shared }, shared.restoreOptions).applied).toBe(true);
    expect(axis.format(2)).toBe('Metric 2');
    const copied = planIndicatorTemplateState(destination.chart, input, 'append');
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...copied }, copied.restoreOptions).applied).toBe(true);
    const copiedId = copied.indicators[copied.indicators.length - 1].plotPriceScaleIds!.local;
    expect(destination.chart.panes()[0].scaleFor(copiedId).format(2)).toBe('2.0%');
    expect(axis.format(2)).toBe('Metric 2');
  });

  it('preserves formats of existing positive-pane studies recreated by append, including empty append', () => {
    const source = fixture(), destination = fixture(), current = descriptor({ placement: 'pane', plots: [
      { key: 'local', title: 'Ratio', type: 'line', priceFormat: { type: 'percent', precision: 0 } },
    ] });
    destination.chart.addIndicator(current.id);
    const axis = destination.chart.panes()[1].priceScale;
    axis.setPriceFormatter(value => `Existing ${value}`);
    const incoming = descriptor();
    for (const add of [false, true]) {
      if (add) source.chart.addIndicator(incoming.id);
      const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'append');
      expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
      expect(axis.format(2)).toBe('Existing 2');
      expect(plan.restoreOptions?.preserveScaleFormats).toContainEqual({ paneIndex: 1, scaleId: 'right' });
    }
  });

  it('preserves formats on host panes during replace and excludes source-replaced study-only slots', () => {
    const source = fixture(), destination = fixture(), spec = descriptor({ placement: 'pane', plots: [
      { key: 'local', title: 'Ratio', type: 'line', priceFormat: { type: 'percent', precision: 1 } },
    ] });
    source.chart.addIndicator(spec.id); destination.chart.addIndicator(spec.id);
    destination.chart.panes()[1].priceScale.setPriceFormatter(value => `Old ${value}`);
    const host = destination.chart.addSeries('line', { paneIndex: 2, priceScaleId: 'left' });
    host.priceScale().setPriceFormatter(value => `Host ${value}`);
    const plan = planIndicatorTemplateState(destination.chart, captureIndicatorTemplate(source.chart), 'replace');
    expect(plan.restoreOptions?.preserveScaleFormats).toEqual([
      { paneIndex: 0, scaleId: 'right' }, { paneIndex: 2, scaleId: 'right' }, { paneIndex: 2, scaleId: 'left' },
    ]);
    expect(destination.chart.restoreState({ ...destination.chart.getState(), ...plan }, plan.restoreOptions).applied).toBe(true);
    expect(destination.chart.panes()[1].priceScale.format(2)).toBe('2.0%');
    expect(host.priceScale().format(2)).toBe('Host 2');
  });
});
