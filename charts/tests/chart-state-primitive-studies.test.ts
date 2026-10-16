import { afterEach, expect, it, vi } from 'vitest';
import { Chart } from '../src/core/chart';
import { registerIndicator } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
afterEach(() => { charts.splice(0).forEach(chart => chart.destroy()); vi.unstubAllGlobals(); });

function fixture() {
  vi.stubGlobal('window', {});
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, shortcuts: false, branding: false, pixelRatio: () => 1,
    raf: { schedule: callback => { callback(); return 1; }, cancel() {} },
  });
  charts.push(chart); chart.applySize(800, 600);
  chart.addSeries('line').setData([{ time: 1, value: 10 }, { time: 2, value: 12 }]);
  return chart;
}

it.each([true, false])('restores a study pane without plot series, with levels=%s', levels => {
  const chart = fixture(), id = `state-without-plots-${levels}`;
  registerIndicator({ id, name: 'Study without plots', placement: 'pane', inputs: [], plots: [],
    ...(levels ? { levels: () => [{ price: 50, title: 'Middle' }], range: () => ({ min: 0, max: 100 }) } : {}),
    calc: () => ({}),
  });
  const study = chart.addIndicator(id, {}, { priceScaleId: 'left' });
  chart.setPaneWeight(1, 0.7);
  const state = chart.getState();
  expect(chart.panes()[1].series()).toHaveLength(0);
  expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 1 });
  expect(chart.indicators()).toHaveLength(1);
  expect(chart.indicators()[0].id).toBe(study.id);
  expect(chart.indicators()[0].paneIndex).toBe(1);
  expect(chart.panes()).toHaveLength(2);
  expect(chart.getState().panes![1].weight).toBe(0.7);
  if (levels) expect(chart.panes()[1].scaleFor('left').fixedRange).toEqual({ min: 0, max: 100 });
});

it('retains a host primitive pane while pruning an unavailable study pane', () => {
  const chart = fixture();
  const detached = vi.fn();
  const primitive = { zOrder: () => 'normal' as const, draw() {}, detached };
  chart.addPrimitive(primitive, 1);
  chart.setPaneWeight(1, 0.6);
  const state = chart.getState();
  state.panes!.push({ ...state.panes![1], weight: 0.4 });
  state.indicators = [{ indicatorId: 'unavailable-primitive-study', settings: {}, paneIndex: 2 }];
  expect(chart.restoreState(state)).toMatchObject({ applied: true, indicators: 0 });
  expect(chart.panes()).toHaveLength(2);
  expect(chart.panes()[1].primitives()).toContain(primitive);
  expect(detached).not.toHaveBeenCalled();
});

it('stops an outer restore superseded by a newer restore in its start listener', () => {
  const chart = fixture();
  registerIndicator({ id: 'state-start-successor', name: 'Successor', placement: 'onchart', inputs: [], plots: [], calc: () => ({}) });
  const end = vi.fn(); chart.on('state:restore:end', end);
  const unsubscribe = chart.on('state:restore:start', () => {
    unsubscribe();
    expect(chart.restoreState({ version: 1, indicators: [
      { indicatorId: 'state-start-successor', instanceId: 'newer-study', settings: {}, paneIndex: 0 },
    ] })).toMatchObject({ applied: true, indicators: 1 });
  });
  const report = chart.restoreState({ version: 1, indicators: [] });
  expect(report).toMatchObject({ applied: false, reason: 'superseded by a newer chart restore' });
  expect(chart.indicators().map(study => study.id)).toEqual(['newer-study']);
  expect(end).toHaveBeenCalledTimes(2);
});
