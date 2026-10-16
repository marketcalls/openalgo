import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.workspace.mjs', () => import('../../../src/workspace/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
import { Chart, registerIndicator, sourceValues } from '../../../src/index.ts';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { captureIndicatorTemplate, applyIndicatorTemplate } from '../src/indicator-templates.js';

registerIndicator({ id: 'custom-average', name: 'Custom average', placement: 'onchart',
  inputs: [{ key: 'source', type: 'source', label: 'Source', default: 'close', allowStudyOutputs: true }],
  plots: [{ key: 'ma', type: 'line' }], calc: (bars, settings, _store, context) => ({ ma: sourceValues(bars, settings.source, context) }) });
const charts = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

const reference = instanceId => ({ kind: 'indicator', instanceId, plotKey: 'ma' });
const graph = () => [
  { indicatorId: 'custom-average', instanceId: 'consumer', studyInputs: ['source'], settings: { source: reference('producer') }, paneIndex: 0 },
  { indicatorId: 'custom-average', instanceId: 'producer', settings: { length: 2 }, paneIndex: 0 },
];
function setup() {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.addSeries('line').setData([{ time: 1, open: 1, high: 1, low: 1, close: 1 }]);
  chart.restoreState({ version: 1, indicators: graph() });
  vi.spyOn(chart, 'restoreState');
  const app = { chart }, target = { chart, pane: 1, current: () => true };
  return { app, target, chart, get state() { return chart.getState(); } };
}

describe('reference dependency template capture', () => {
  it('captures the complete source graph before identity stripping can break it', () => {
    const { app, target, state } = setup();
    const result = captureIndicatorTemplate(app, target);
    expect(result.indicators).toEqual(state.indicators);
    expect(result.layout.plots).toHaveLength(2);
    result.indicators[0].settings.source.instanceId = 'changed';
    expect(state.indicators[0].settings.source).toEqual(reference('producer'));
  });

  it('appends independent copies while keeping the original source graph and primary mirror intact', () => {
    const h = setup(), captured = captureIndicatorTemplate(h.app, h.target);
    applyIndicatorTemplate(h.app, h.target, captured, 'append');
    applyIndicatorTemplate(h.app, h.target, captured, 'append');
    expect(h.state.indicators).toHaveLength(6);
    expect(new Set(h.state.indicators.map(item => item.instanceId)).size).toBe(6);
    for (let i = 0; i < 6; i += 2) {
      expect(h.state.indicators[i].settings.source).toEqual(reference(h.state.indicators[i + 1].instanceId));
    }
    expect(h.state.indicators.slice(0, 2)).toEqual(captured.indicators);
    expect(h.app.activeIndicators).toEqual(h.state.indicators);
  });

  it('rejects unavailable external dependencies before capture or restore', () => {
    const h = setup();
    h.chart.indicators().find(item => item.id === 'producer').remove();
    expect(() => captureIndicatorTemplate(h.app, h.target)).toThrow(/external|missing/i);
    expect(h.chart.restoreState).not.toHaveBeenCalled();
  });
});
