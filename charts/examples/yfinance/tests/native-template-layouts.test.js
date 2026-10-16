import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.workspace.mjs', () => import('../../../src/workspace/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
import { Chart, registerIndicator } from '../../../src/index.ts';
import { fakeDocument } from '../../../tests/helpers/fake-dom';
import { captureIndicatorTemplate, applyIndicatorTemplate } from '../src/indicator-templates.js';
import { capturePaneTarget } from '../src/pane-target.js';

const id = 'host-template-layout-study';
registerIndicator({ id, name: 'Host template study', placement: 'onchart', inputs: [],
  plots: [{ key: 'value', type: 'line', priceScaleId: 'overlay:metric' }],
  calc: bars => ({ value: bars.map(bar => bar.close * 10) }),
});
const formattedId = 'host-template-formatted-study';
registerIndicator({ id: formattedId, name: 'Formatted template study', placement: 'onchart', inputs: [],
  plots: [{ key: 'value', type: 'line', priceFormat: { type: 'volume' } },
    { key: 'band', type: 'line', priceScaleId: 'overlay:metric', priceFormat: { type: 'percent', precision: 1 } }],
  calc: bars => ({ value: bars.map(bar => bar.close * 10), band: bars.map(bar => bar.close * 2) }),
});
for (const [suffix, priceFormat] of [['percent', { type: 'percent', precision: 0 }], ['volume', { type: 'volume' }]]) {
  registerIndicator({ id: 'host-template-pane-' + suffix, name: suffix, placement: 'pane', inputs: [],
    plots: [{ key: 'value', type: 'line', priceFormat }], calc: bars => ({ value: bars.map(bar => bar.close * 100) }) });
}
const charts = [];
afterEach(() => charts.splice(0).forEach(chart => chart.destroy()));
function mount(pane = 1, indicatorId = id) {
  const document = fakeDocument();
  const chart = new Chart(document.createElement('div'), {
    document, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: () => 1, cancel: () => {} },
  });
  charts.push(chart);
  chart.applySize(800, 500);
  chart.setDataContext({ symbol: 'HOST', interval: '1m' });
  const source = chart.addSeries('line');
  source.setData([1, 2, 3].map((close, i) => ({ time: i * 60, open: close, high: close, low: close, close })));
  const study = chart.addIndicator(indicatorId);
  chart.setPriceAxisPlacement(0, 'overlay:metric', 'left');
  const scale = study.series('value').priceScale();
  scale.setAutoScale(false); scale.setPriceRange({ min: 0, max: 100 });
  chart.fitContent();
  let valid = true;
  const app = { chart: pane === 1 ? chart : {}, chart2: pane === 2 ? chart : null, activeIndicators: ['untouched'] };
  const target = { pane, chart, current: () => valid };
  return { app, target, chart, source, study, invalidate: () => { valid = false; } };
}
const simple = name => [{ indicatorId: id, instanceId: name, paneIndex: 0, settings: {} }];

describe('host native template payloads', () => {
  it('captures detached identities, effective bindings and manual scale settings', () => {
    const h = mount(), payload = captureIndicatorTemplate(h.app, h.target);
    expect(payload).toHaveProperty('layout');
    expect(payload.indicators[0].instanceId).toBe(h.study.id);
    expect(payload.layout).toMatchObject({ primaryScaleId: 'right', plots: [
      { instanceId: h.study.id, plotKey: 'value', paneIndex: 0, scaleId: 'overlay:metric' },
    ] });
    expect(payload.layout.panes[0].scales['overlay:metric']).toMatchObject({ autoScale: false, range: { min: 0, max: 100 } });
    payload.layout.panes[0].scales['overlay:metric'].range.max = 999;
    expect(h.study.series('value').priceScale().priceRange().max).toBe(100);
  });

  it('applies a full payload with independent scale defaults and keeps the data handle', () => {
    const h = mount(), before = h.chart.getState(), sourceBars = [...h.chart.primaryBars()];
    const payload = captureIndicatorTemplate(h.app, h.target);
    const restore = vi.spyOn(h.chart, 'restoreState');
    applyIndicatorTemplate(h.app, h.target, payload, 'append');
    expect(h.chart.indicators()).toHaveLength(2);
    const added = h.chart.indicators()[1];
    expect(added.id).not.toBe(h.study.id);
    expect(added.plotPriceScaleId('value')).not.toBe('overlay:metric');
    expect(added.series('value').priceScale().autoScale).toBe(true);
    expect(h.chart.primarySeries()).toBe(h.source);
    expect(h.chart.primaryBars()).toEqual(sourceBars);
    const patch = restore.mock.calls[0][0];
    expect(patch).toHaveProperty('panes');
    expect(patch.drawings).toEqual(before.drawings); expect(patch.alerts).toEqual(before.alerts);
    expect(patch).not.toHaveProperty('series'); expect(patch).not.toHaveProperty('viewport');
    expect(h.app.activeIndicators).toEqual(h.chart.getState().indicators);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('forwards explicit sharing and saved-range choices to the native planner', () => {
    const h = mount(), payload = captureIndicatorTemplate(h.app, h.target), originalScale = h.study.series('value').priceScale();
    applyIndicatorTemplate(h.app, h.target, payload, 'append', { scalePolicy: 'share', rangePolicy: 'preserve' });
    expect(h.chart.indicators()[1].plotPriceScaleId('value')).toBe('overlay:metric');
    expect(h.chart.indicators()[1].series('value').priceScale()).toBe(originalScale);
    const other = mount();
    applyIndicatorTemplate(other.app, other.target, payload, 'append', { scalePolicy: 'copy', rangePolicy: 'preserve' });
    expect(other.chart.indicators()[1].series('value').priceScale().priceRange()).toEqual({ min: 0, max: 100 });
  });

  it('retains destination primary formatting while copied scales use descriptor formats', () => {
    const donor = mount(1, formattedId), h = mount();
    const scale = h.source.priceScale();
    scale.setOptions({ minMove: 0.05, minPrecision: 3 });
    scale.setPriceFormatter(value => 'HOST ' + value);
    applyIndicatorTemplate(h.app, h.target, captureIndicatorTemplate(donor.app, donor.target), 'append');
    expect(scale.format(1234)).toBe('HOST 1234');
    expect(scale.options).toMatchObject({ minMove: 0.05, minPrecision: 3 });
    const copied = h.chart.indicators().find(item => item.indicatorId === formattedId);
    expect(copied.series('value').priceScale()).toBe(scale);
    expect(copied.series('band').priceScale().format(12.5)).toBe('12.5%');
  });

  it('preserves protected formatters during recovery and reinstalls outgoing study-pane formats', () => {
    const donor = mount(1, formattedId), h = mount(1, formattedId);
    donor.chart.addIndicator('host-template-pane-volume');
    h.chart.addIndicator('host-template-pane-percent');
    const scale = h.source.priceScale();
    scale.setPriceFormatter(value => 'HOST ' + value);
    const nativeRestore = h.chart.restoreState.bind(h.chart);
    vi.spyOn(h.chart, 'restoreState').mockImplementationOnce((next, options) => ({ ...nativeRestore(next, options), indicators: 0 }));
    expect(() => applyIndicatorTemplate(h.app, h.target, captureIndicatorTemplate(donor.app, donor.target), 'replace')).toThrow(/all studies/);
    expect(scale.format(1234)).toBe('HOST 1234');
    expect(h.chart.indicators().find(item => item.indicatorId === 'host-template-pane-percent')
      .series('value').priceScale().format(1200)).toBe('1200%');
    expect(h.chart.indicators().some(item => item.indicatorId === 'host-template-pane-volume')).toBe(false);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('filters removed scales from recovery selectors before native validation', () => {
    const donor = mount(1, formattedId), h = mount();
    const temporary = h.chart.addSeries('line', { priceScaleId: 'overlay:temporary' });
    expect(h.chart.getState().panes[0].scales).toHaveProperty('overlay:temporary');
    const restore = vi.spyOn(h.chart, 'restoreState').mockImplementationOnce(() => {
      temporary.remove();
      expect(h.chart.getState().panes[0].scales).not.toHaveProperty('overlay:temporary');
      return { applied: false, indicators: 0, reason: 'Partial restore failed' };
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, captureIndicatorTemplate(donor.app, donor.target), 'append'))
      .toThrow('Partial restore failed');
    expect(restore).toHaveBeenCalledTimes(2);
    expect(restore.mock.calls[0][1].preserveScaleFormats).toContainEqual({ paneIndex: 0, scaleId: 'overlay:temporary' });
    expect(restore.mock.calls[1][1].preserveScaleFormats).not.toContainEqual({ paneIndex: 0, scaleId: 'overlay:temporary' });
    expect(h.chart.indicators().map(item => item.indicatorId)).toEqual([id]);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('validates rich metadata before restore or host flags change', () => {
    const h = mount(), payload = captureIndicatorTemplate(h.app, h.target);
    expect(payload).toHaveProperty('layout');
    payload.layout.plots[0].plotKey = 'absent';
    const restore = vi.spyOn(h.chart, 'restoreState');
    expect(() => applyIndicatorTemplate(h.app, h.target, payload, 'replace')).toThrow();
    expect(restore).not.toHaveBeenCalled(); expect(h.app.applyingTemplate).toBeUndefined();
    expect(h.chart.indicators()[0]).toBe(h.study);
  });

  it('keeps legacy arrays and replay-prefix application without updating the other chart mirror', () => {
    const h = mount(2), restore = vi.spyOn(h.chart, 'restoreState'); h.app.replay = {};
    applyIndicatorTemplate(h.app, h.target, simple('legacy'), 'replace');
    expect(h.chart.indicators()).toHaveLength(1);
    expect(h.chart.primaryBars()).toHaveLength(3);
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(restore.mock.calls[0]).toHaveLength(1);
  });

  it('does not roll back a newer direct restore started by the same chart callback', () => {
    const h = mount(), nativeRestore = h.chart.restoreState.bind(h.chart);
    const restore = vi.spyOn(h.chart, 'restoreState').mockImplementationOnce(next => ({ ...nativeRestore(next), indicators: 0 }));
    let once = true;
    h.chart.on('state:restore:end', () => {
      if (!once) return;
      once = false;
      h.chart.restoreState({ version: 1, indicators: simple('newer-owner') });
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('outer'), 'replace')).toThrow(/all studies/);
    expect(restore).toHaveBeenCalledTimes(2);
    expect(h.chart.indicators().map(item => item.id)).toEqual(['newer-owner']);
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('reports supersession even when the older restore itself returned successfully', () => {
    const h = mount(); let once = true;
    h.chart.on('state:restore:end', () => {
      if (!once) return;
      once = false; h.chart.restoreState({ version: 1, indicators: simple('newer-owner') });
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('outer'), 'replace')).toThrow(/newer|changed|superseded/i);
    expect(h.chart.indicators().map(item => item.id)).toEqual(['newer-owner']);
    expect(h.app.activeIndicators).toEqual(['untouched']);
  });

  it('preserves a newer restore started from the outer restore start callback', () => {
    const h = mount(), panes = h.chart.getState().panes;
    panes[0].weight = 7;
    panes[0].priceScale.autoScale = false;
    panes[0].priceScale.range = { min: -10, max: 10 };
    let once = true;
    h.chart.on('state:restore:start', () => {
      if (!once) return;
      once = false;
      h.chart.restoreState({ version: 1, indicators: simple('start-successor'), panes });
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('older-start'), 'replace')).toThrow(/newer|changed|superseded/i);
    expect(h.chart.indicators().map(item => item.id)).toEqual(['start-successor']);
    expect(h.chart.getState().panes[0]).toMatchObject({ weight: 7,
      priceScale: { autoScale: false, range: { min: -10, max: 10 } } });
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('does not recover or refresh mirrors after the captured owner changes', () => {
    const h = mount(), restore = vi.spyOn(h.chart, 'restoreState');
    h.app.req = { symbol: 'HOST', interval: '1m', period: '1d' };
    const target = capturePaneTarget(h.app);
    h.chart.on('state:restore:end', () => h.chart.setDataContext({ symbol: 'NEXT', interval: '1m' }));
    expect(() => applyIndicatorTemplate(h.app, target, simple('outer'), 'replace')).toThrow(/changed/);
    expect(restore).toHaveBeenCalledTimes(1);
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('keeps a newer helper operation and clears only each operation own flag', () => {
    const h = mount(), otherApp = { chart: h.chart, activeIndicators: ['other'] };
    let once = true;
    h.chart.on('state:restore:end', () => {
      if (!once) return;
      once = false; applyIndicatorTemplate(otherApp, h.target, simple('newer-helper'), 'replace');
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('older-helper'), 'replace')).toThrow(/newer|changed/);
    expect(otherApp.activeIndicators).toEqual(h.chart.getState().indicators);
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.app.applyingTemplate).toBe(false); expect(otherApp.applyingTemplate).toBe(false);
  });

  it('does not publish the old mirror when a newer restore starts during recovery', () => {
    const h = mount(), restore = vi.spyOn(h.chart, 'restoreState').mockReturnValueOnce({ applied: true, indicators: 0 });
    let once = true;
    h.chart.on('state:restore:end', () => {
      if (!once) return;
      once = false; h.chart.restoreState({ version: 1, indicators: simple('recovery-successor') });
    });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('outer'), 'replace')).toThrow(/all studies/);
    expect(restore).toHaveBeenCalledTimes(3);
    expect(h.chart.indicators().map(item => item.id)).toEqual(['recovery-successor']);
    expect(h.app.activeIndicators).toEqual(['untouched']);
    expect(h.app.applyingTemplate).toBe(false);
  });

  it('disposes the restore fence on success and failed application with recovery', () => {
    const h = mount(), nativeOn = h.chart.on.bind(h.chart), disposers = [];
    vi.spyOn(h.chart, 'on').mockImplementation((name, callback) => {
      const off = nativeOn(name, callback);
      if (name !== 'state:restore:start') return off;
      const dispose = vi.fn(off); disposers.push(dispose); return dispose;
    });
    applyIndicatorTemplate(h.app, h.target, simple('first'), 'replace');
    vi.spyOn(h.chart, 'restoreState').mockReturnValueOnce({ applied: false, reason: 'Rejected restore' });
    expect(() => applyIndicatorTemplate(h.app, h.target, simple('second'), 'replace')).toThrow('Rejected restore');
    expect(disposers).toHaveLength(2);
    for (const dispose of disposers) expect(dispose).toHaveBeenCalledOnce();
    expect(h.app.applyingTemplate).toBe(false);
  });
});
