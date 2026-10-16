import { afterEach, describe, it, expect, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.workspace.mjs', () => import('../../../src/workspace/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
import { Chart, registerIndicator } from '../../../src/index.ts';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { captureIndicatorTemplate, applyIndicatorTemplate, templateUnavailableReason } from '../src/indicator-templates.js';

for (const id of ['ema', 'rsi', 'macd']) registerIndicator({ id, name: id, placement: id === 'ema' ? 'onchart' : 'pane', inputs: [],
  plots: [{ key: 'value', type: 'line' }], calc: bars => ({ value: bars.map(bar => bar.close) }) });
const charts = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));

const study = (patch = {}) => ({ indicatorId: 'ema', settings: { length: 9, color: '#12abcd' },
  paneIndex: 0, instanceId: 'original', visible: false, ...patch });

function setup(pane = 1) {
  let valid = true;
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), { document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} } });
  charts.push(chart); chart.applySize(800, 500);
  chart.addSeries('line').setData([{ time: 100, open: 42, high: 42, low: 42, close: 42 }]);
  chart.addSeries('line', { paneIndex: 1 });
  chart.restoreState({ version: 1, indicators: [study()] });
  chart.setPaneWeight(0, 3); chart.setPaneWeight(1, 1);
  chart.setDrawingState({ version: 2, drawings: [{ id: 'line' }] });
  chart.setAlertState({ version: 1, alerts: [{ id: 'fired', state: 'triggered', source: { kind: 'price', price: 40 },
    condition: 'greaterThan', policy: 'onTouch', repeat: 'once', title: 'Saved alert', cooldownSeconds: 0, scope: {} }] });
  const original = chart.getState();
  vi.spyOn(chart, 'restoreState');
  const target = { pane, chart, current: () => valid };
  const app = { chart: pane === 1 ? chart : {}, chart2: pane === 2 ? chart : null, activeIndicators: ['untouched'] };
  return { app, target, chart, original, get state() { return chart.getState(); }, invalidate: () => { valid = false; } };
}

describe('reference indicator template actions', () => {
  it('captures detached styles, grouping, visibility and rich layout identities', () => {
    const h = setup(), captured = captureIndicatorTemplate(h.app, h.target);
    expect(captured.indicators[0]).toMatchObject({ indicatorId: 'ema', settings: { length: 9 }, visible: false, paneIndex: 0 });
    expect(captured.indicators[0].instanceId).toBe('original'); captured.indicators[0].settings.length = 99;
    expect(captured.layout.plots).toContainEqual({ instanceId: 'original', plotKey: 'value', paneIndex: 0, scaleId: 'right' });
    expect(h.state.indicators[0].settings.length).toBe(9);
  });

  it('applies only planned studies while retaining decorations and the primary scale', () => {
    const h = setup();
    applyIndicatorTemplate(h.app, h.target, [study({ indicatorId: 'rsi', paneIndex: 1 })], 'replace');
    const applied = h.chart.restoreState.mock.calls[0][0];
    expect(applied).toMatchObject({ drawings: h.original.drawings, alerts: h.original.alerts, panes: [h.original.panes[0]] });
    expect(applied).not.toHaveProperty('series'); expect(applied).not.toHaveProperty('viewport');
    expect(applied.indicators[0]).not.toHaveProperty('instanceId');
    expect(h.app.activeIndicators).toEqual(h.state.indicators); expect(h.app.applyingTemplate).toBe(false);
  });

  it('saves a template without the protected study of the host, and a replace keeps that study once', () => {
    const h = setup();
    const pinned = h.chart.addIndicator('rsi', {}, { policy: { removable: false, configurable: false, movable: false } });
    const captured = captureIndicatorTemplate(h.app, h.target);
    expect(captured.indicators.map(item => item.indicatorId)).toEqual(['ema']);
    applyIndicatorTemplate(h.app, h.target, captured, 'replace');
    expect(h.state.indicators.map(item => item.indicatorId)).toEqual(['rsi', 'ema']);
    expect(h.chart.indicators()[0].id).toBe(pinned.id);
    expect(h.chart.indicators()[0].policy()).toEqual({ removable: false, configurable: false, movable: false });
  });

  it('keeps the primary mirror untouched when appending to the second chart', () => {
    const h = setup(2);
    applyIndicatorTemplate(h.app, h.target, [study({ indicatorId: 'rsi', paneIndex: 1 })], 'append');
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.state.indicators.map(item => item.paneIndex)).toEqual([0, 2]);
    expect(h.state.indicators[0].instanceId).toBe('original');
    expect(h.chart.restoreState.mock.calls[0][0].panes).toEqual(h.original.panes);
  });

  it('rejects stale owners and missing custom descriptors before changing studies', () => {
    const h = setup();
    expect(() => applyIndicatorTemplate(h.app, h.target, [study({ indicatorId: 'missing' })], 'replace')).toThrow(/Missing/);
    h.invalidate();
    expect(() => captureIndicatorTemplate(h.app, h.target)).toThrow(/changed/);
    expect(() => applyIndicatorTemplate(h.app, h.target, [], 'replace')).toThrow(/changed/);
    expect(h.chart.restoreState).not.toHaveBeenCalled();
  });

  it('rolls back a partially applied restore and reports incomplete recovery', () => {
    const h = setup();
    h.chart.restoreState.mockReturnValueOnce({ applied: true, indicators: 0 });
    expect(() => applyIndicatorTemplate(h.app, h.target, [study()], 'replace')).toThrow(/all studies/);
    expect(h.chart.restoreState.mock.calls[1][0]).toMatchObject({ indicators: h.original.indicators,
      panes: h.original.panes, viewport: h.original.viewport, barSpacing: h.original.barSpacing,
      drawings: h.original.drawings, alerts: h.original.alerts });
    expect(h.app.applyingTemplate).toBe(false);
    h.chart.restoreState.mockImplementationOnce(() => { throw new Error('Apply failed'); })
      .mockReturnValueOnce({ applied: false, reason: 'Recovery refused' });
    expect(() => applyIndicatorTemplate(h.app, h.target, [], 'replace')).toThrow(/recovery failed/);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('does not restore on empty append and permits changes to the active replay prefix', () => {
    const h = setup(); h.app.replay = {};
    expect(templateUnavailableReason(h.app, h.target)).toBeNull();
    applyIndicatorTemplate(h.app, h.target, [], 'append'); expect(h.chart.restoreState).not.toHaveBeenCalled();
    h.app.replayPicking = true;
    expect(() => applyIndicatorTemplate(h.app, h.target, [], 'replace')).toThrow(/replay/);
    h.app.replayPicking = false; h.app.loading = true;
    expect(() => captureIndicatorTemplate(h.app, h.target)).toThrow(/loading/);
  });
});
