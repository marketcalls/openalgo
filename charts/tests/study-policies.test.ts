/**
 * Study policies: what a user may do with a study, restricted flag by flag,
 * and checked on every path a user reaches it by (the chart's own legend
 * buttons, the object inventory and the native calls a host control makes),
 * while the owning host still changes the study with `{ force: true }`.
 */
import { afterEach, describe, expect, it } from 'vitest';
import '../src/indicators/index';
import { Chart } from '../src/core/chart';
import { ChartObjects } from '../src/model/chart-objects';
import { parseIndicatorPolicy } from '../src/model/indicator-policy';
import { parseIndicatorStates, parseWorkspaceDocument } from '../src/workspace/documents';
import { planIndicatorTemplate } from '../src/workspace/templates';
import { captureIndicatorTemplate, planIndicatorTemplateState } from '../src/workspace/template-layout';
import { registerIndicator, registeredIndicators } from '../src/model/indicator-registry';
import { fakeDocument } from './helpers/fake-dom';

const charts: Chart[] = [];
function makeChart(): Chart {
  const doc = fakeDocument();
  const chart = new Chart(doc.createElement('div'), {
    document: doc, pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: (t: number) => void) => { cb(0); return 0; } },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(Array.from({ length: 80 }, (_, i) => ({
    time: 1700000000 + i * 60, open: 100 + i, high: 102 + i, low: 99 + i, close: 101 + i, volume: 100,
  })));
  charts.push(chart);
  return chart;
}
afterEach(() => { for (const chart of charts.splice(0)) chart.destroy(); });

/** Press a legend button the way a click on the canvas does. */
const press = (chart: Chart, id: string): boolean =>
  (chart as unknown as { _handleLegendAction(id: string): boolean })._handleLegendAction(id);
const legendActions = (chart: Chart, instanceId: string): readonly string[] =>
  chart.indicators().find(item => item.id === instanceId)!.legend()!.options().actions ?? [];

describe('study policy flags', () => {
  it('starts unrestricted, reads back what the host set and normalises to the restrictions', () => {
    const chart = makeChart();
    const open = chart.addIndicator('sma');
    expect(open.policy()).toEqual({});
    const pinned = chart.addIndicator('ema', {}, { policy: { removable: false, configurable: true, listed: false } });
    expect(pinned.policy()).toEqual({ removable: false, listed: false });
    pinned.setPolicy({ movable: false });
    expect(pinned.policy()).toEqual({ movable: false });
    pinned.setPolicy(null);
    expect(pinned.policy()).toEqual({});
    expect(() => chart.addIndicator('sma', {}, { policy: { removable: 'no' } as never })).toThrow(/policy/i);
    expect(() => pinned.setPolicy({ movable: 1 } as never)).toThrow(/policy/i);
    expect(parseIndicatorPolicy({ removable: false, extra: true })).toEqual({ removable: false });
  });

  it('removable false: the legend close button, the inventory and a plain remove all leave it, and force removes it', () => {
    const chart = makeChart();
    const study = chart.addIndicator('rsi', {}, { policy: { removable: false } });
    expect(legendActions(chart, study.id)).not.toContain('close');
    expect(legendActions(chart, study.id)).toContain('settings');
    expect(press(chart, `indicator:${study.id}::close`)).toBe(true);
    expect(chart.indicators()).toContain(study);
    expect(chart.removeIndicator(study.id)).toBe(false);
    expect(study.remove()).toBe(false);
    expect(chart.removePane(study.paneIndex)).toBe(false);
    expect(chart.indicators()).toContain(study);
    const objects = new ChartObjects(chart);
    const row = objects.get('indicator:' + study.id)!;
    expect(row.capabilities.remove).toBe(false);
    expect(objects.remove(row.id)).toBe(false);
    expect(chart.indicators()).toContain(study);
    expect(chart.removeIndicator(study.id, { force: true })).toBe(true);
    expect(chart.indicators()).not.toContain(study);
    const other = chart.addIndicator('macd', {}, { policy: { removable: false } });
    expect(other.remove({ force: true })).toBe(true);
    expect(chart.indicators()).toHaveLength(0);
    objects.destroy();
  });

  it('configurable false: no gear, no settings event, no settings or scale change unless forced', () => {
    const chart = makeChart();
    const study = chart.addIndicator('sma', { length: 20 }, { policy: { configurable: false } });
    let asked = 0;
    chart.on('indicatorSettings', () => { asked++; });
    expect(legendActions(chart, study.id)).not.toContain('settings');
    expect(legendActions(chart, study.id)).toContain('close');
    expect(press(chart, `indicator:${study.id}::settings`)).toBe(true);
    expect(asked).toBe(0);
    expect(study.setSettings({ length: 5 })).toBe(false);
    expect(study.settings().length).toBe(20);
    expect(study.setPriceScale('left')).toBe(false);
    expect(study.priceScaleId()).toBeNull();
    expect(study.setPlotPriceScales({ [Object.keys(study.values())[0] ?? 'value']: 'left' })).toBe(false);
    const objects = new ChartObjects(chart, { onSettings: () => { asked++; } });
    expect(objects.get('indicator:' + study.id)!.capabilities.settings).toBe(false);
    expect(objects.openSettings('indicator:' + study.id)).toBe(false);
    expect(asked).toBe(0);
    expect(study.setSettings({ length: 5 }, { force: true })).toBe(true);
    expect(study.settings().length).toBe(5);
    expect(study.setPriceScale('left', { force: true })).toBe(true);
    expect(study.priceScaleId()).toBe('left');
    // Hiding is the user's view of the chart, not a setting.
    study.setVisible(false);
    expect(study.visible()).toBe(false);
    expect(objects.setVisible('indicator:' + study.id, true)).toBe(true);
    objects.destroy();
  });

  it('movable false: pane moves and stacking refuse the user and take the host', () => {
    const chart = makeChart();
    const first = chart.addIndicator('sma');
    const pinned = chart.addIndicator('ema', {}, { policy: { movable: false } });
    const objects = new ChartObjects(chart);
    const row = objects.get('indicator:' + pinned.id)!;
    expect(row.capabilities.reorder).toBe(false);
    expect(row.capabilities.move).toBe(false);
    expect(row.capabilities.place).toBe(false);
    expect(chart.reorderIndicator(pinned.id, -1)).toBe(false);
    expect(chart.moveIndicator(pinned.id, chart.panes().length)).toBe(false);
    expect(chart.moveInSeriesStack('indicator:' + pinned.id, 'indicator:' + first.id, 'below')).toBe(false);
    expect(objects.place('indicator:' + pinned.id, 'indicator:' + first.id, 'below')).toBe(false);
    expect(chart.indicators().map(item => item.id)).toEqual([first.id, pinned.id]);
    // Another study may still move past it: the flag holds this study's own place.
    expect(chart.reorderIndicator(first.id, 1)).toBe(true);
    expect(chart.indicators().map(item => item.id)).toEqual([pinned.id, first.id]);
    expect(chart.reorderIndicator(pinned.id, 1, { force: true })).toBe(true);
    expect(chart.moveIndicator(pinned.id, chart.panes().length, { force: true })).toBe(true);
    expect(pinned.paneIndex).toBe(1);
    objects.destroy();
  });

  it('listed false leaves the study out of the inventory only', () => {
    const chart = makeChart();
    const hidden = chart.addIndicator('sma', {}, { policy: { listed: false } });
    const shown = chart.addIndicator('ema');
    const objects = new ChartObjects(chart);
    expect(objects.get('indicator:' + hidden.id)).toBeUndefined();
    expect(objects.get('indicator:' + shown.id)).toBeDefined();
    expect(chart.indicators()).toContain(hidden);
    expect(legendActions(chart, hidden.id)).toContain('close');
    hidden.setPolicy({});
    expect(objects.get('indicator:' + hidden.id)).toBeDefined();
    objects.destroy();
  });

  it('a policy change reaches the legend buttons and the inventory at once', () => {
    const chart = makeChart();
    const study = chart.addIndicator('rsi');
    const objects = new ChartObjects(chart);
    const seen: boolean[] = [];
    objects.subscribe(rows => { const row = rows.find(item => item.id === 'indicator:' + study.id); if (row) seen.push(row.capabilities.remove); });
    study.setPolicy({ removable: false, configurable: false });
    expect(legendActions(chart, study.id)).not.toContain('close');
    expect(legendActions(chart, study.id)).not.toContain('settings');
    // The pane controls stay: they act on the pane, not on the study.
    expect(legendActions(chart, study.id)).toContain('up');
    expect(seen[seen.length - 1]).toBe(false);
    study.setPolicy(null);
    expect(legendActions(chart, study.id)).toContain('close');
    expect(seen[seen.length - 1]).toBe(true);
    objects.destroy();
  });

  it('keeps the buttons a host set on a study row through every restack, with the policy laid over them', () => {
    const chart = makeChart();
    const sma = chart.addIndicator('sma');
    sma.legend()!.setOptions({ actions: ['hide'] });
    chart.addIndicator('ema');
    expect(legendActions(chart, sma.id)).toEqual(['hide']);
    const rsi = chart.addIndicator('rsi');
    rsi.legend()!.setOptions({ actions: ['settings'] });
    chart.addIndicator('macd');
    // The row leading a lower pane still gets the pane controls around what the host kept.
    expect(legendActions(chart, rsi.id)).toEqual(['settings', 'up', 'down', 'collapse', 'maximize']);
    // A button the host gave the row shows only while the policy allows it, and comes back after.
    sma.legend()!.setOptions({ actions: ['hide', 'close'] });
    sma.setPolicy({ removable: false });
    expect(legendActions(chart, sma.id)).toEqual(['hide']);
    sma.setPolicy(null);
    expect(legendActions(chart, sma.id)).toEqual(['hide', 'close']);
  });
});

describe('study policy persistence', () => {
  it('saves only restrictions, restores them, and leaves an unrestricted layout byte for byte', () => {
    const chart = makeChart();
    chart.addIndicator('sma');
    const plain = JSON.stringify(chart.getState());
    expect(plain).not.toContain('policy');
    chart.addIndicator('rsi', {}, { policy: { removable: false, configurable: true, movable: false } });
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    expect(saved.indicators[1].policy).toEqual({ removable: false, movable: false });
    expect(saved.indicators[0].policy).toBeUndefined();
    const other = makeChart();
    expect(other.restoreState(saved).applied).toBe(true);
    expect(other.indicators()[1].policy()).toEqual({ removable: false, movable: false });
    expect(other.removeIndicator(other.indicators()[1].id)).toBe(false);
    // A restore is the host's act and replaces a protected study like any other.
    expect(other.restoreState(JSON.parse(plain)).applied).toBe(true);
    expect(other.indicators()).toHaveLength(1);
    expect(other.indicators()[0].policy()).toEqual({});
  });

  it('refuses a malformed saved policy before anything is applied', () => {
    const chart = makeChart();
    chart.addIndicator('sma');
    const saved = JSON.parse(JSON.stringify(chart.getState()));
    saved.indicators[0].policy = { removable: 'false' };
    const before = chart.indicators().map(item => item.id);
    const report = chart.restoreState(saved);
    expect(report.applied).toBe(false);
    expect(report.reason).toMatch(/policy/i);
    expect(chart.indicators().map(item => item.id)).toEqual(before);
  });

  it('keeps policies in workspace chart state, and leaves a host study out of a portable template', () => {
    const chart = makeChart();
    chart.addIndicator('rsi', {}, { policy: { removable: false, listed: false } });
    const state = JSON.parse(JSON.stringify(chart.getState()));
    expect(parseIndicatorStates(state.indicators)[0].policy).toEqual({ removable: false, listed: false });
    const document = parseWorkspaceDocument({
      kind: 'workspace', version: 1, id: 'w', name: 'W', createdAt: 1, updatedAt: 1,
      layout: { rows: 1, columns: 1, slots: [{ paneId: 'a', row: 0, column: 0 }] }, activePaneId: 'a',
      panes: [{ id: 'a', symbol: 'X', exchange: 'NSE', interval: '1m', chartType: 'candlestick', chart: state, settings: {} }],
      sync: { crosshair: false, viewport: false, symbol: false, interval: false },
    });
    expect(document.panes[0].chart.indicators?.[0].policy).toEqual({ removable: false, listed: false });
    const template = captureIndicatorTemplate(chart);
    expect(template.indicators).toEqual([]);
    expect(() => parseIndicatorStates([{ indicatorId: 'rsi', settings: {}, paneIndex: 1, policy: { listed: 0 } }])).toThrow(/policy/i);
  });

  it('captures only the studies of the user in a template, so a replace neither copies nor loses those of the host', () => {
    const chart = makeChart();
    const pinned = chart.addIndicator('rsi', {}, { policy: { removable: false } });
    const quiet = chart.addIndicator('ema', { length: 5 }, { policy: { listed: false } });
    // A user study reading the unlisted one: its copy would read nothing, so it stays out too.
    const reader = chart.addIndicator('sma', { length: 3, source: { kind: 'indicator', instanceId: quiet.id, plotKey: 'ma' } });
    const own = chart.addIndicator('macd');
    // Restricted in a way that leaves the study the user's: copied, without the restriction.
    const locked = chart.addIndicator('sma', { length: 50 }, { policy: { configurable: false } });
    const template = captureIndicatorTemplate(chart);
    expect(template.indicators.map(item => item.indicatorId)).toEqual(['macd', 'sma']);
    expect(template.indicators[1].settings.length).toBe(50);
    expect(template.indicators.every(item => item.policy === undefined)).toBe(true);
    const text = JSON.stringify(template);
    for (const id of [pinned.id, quiet.id, reader.id]) expect(text).not.toContain(id);

    const plan = planIndicatorTemplateState(chart, template, 'replace');
    expect(plan.indicators.filter(item => item.indicatorId === 'rsi')).toHaveLength(1);
    expect(plan.indicators.filter(item => item.indicatorId === 'ema')).toHaveLength(1);
    expect(plan.indicators.slice(0, 2).map(item => item.instanceId)).toEqual([pinned.id, quiet.id]);
    expect(chart.restoreState({ version: 1, indicators: plan.indicators, panes: plan.panes }, plan.restoreOptions).applied).toBe(true);
    expect(chart.indicators().map(item => item.indicatorId)).toEqual(['rsi', 'ema', 'macd', 'sma']);
    expect(chart.indicators()[0].policy()).toEqual({ removable: false });
    expect(chart.indicators()[1].policy()).toEqual({ listed: false });
    expect(chart.indicators().find(item => item.id === own.id)).toBeUndefined();
    // The restricted study of the user was replaced by its copy, which the template holds unrestricted.
    expect(chart.indicators().find(item => item.id === locked.id)).toBeUndefined();
    expect(chart.indicators()[3].policy()).toEqual({});

    // A host that hands its chart state over as the template gets the same answer.
    const available = new Set(registeredIndicators().map(item => item.id));
    const legacy = planIndicatorTemplate(chart.getState().indicators!, chart.getState().indicators!, 'replace', available, chart.panes().length);
    expect(legacy.filter(item => item.indicatorId === 'rsi')).toHaveLength(1);
    expect(legacy.filter(item => item.indicatorId === 'ema')).toHaveLength(1);
  });

  it('lets go of the scale range a host study owned when a template is captured without it', () => {
    const chart = makeChart();
    registerIndicator({ id: 'policy-band', name: 'Band', placement: 'pane', inputs: [],
      plots: [{ key: 'v', type: 'line', title: 'V' }], range: () => ({ min: 0, max: 100 }), calc: bars => ({ v: bars.map(() => 50) }) });
    const band = chart.addIndicator('policy-band', {}, { priceScaleId: 'left', policy: { removable: false } });
    expect(chart.getState().panes![band.paneIndex].scales!.left!.indicatorRange!.instanceId).toBe(band.id);
    chart.addIndicator('sma');
    const template = captureIndicatorTemplate(chart);
    expect(template.indicators.map(item => item.indicatorId)).toEqual(['sma']);
    expect(JSON.stringify(template)).not.toContain(band.id);
    const scale = template.layout!.panes[band.paneIndex].scales!.left!;
    expect(scale.indicatorRange).toBeUndefined();
    expect(scale.autoScale).toBe(true);
  });

  it('keeps a study the user cannot remove when a template replaces the others', () => {
    const chart = makeChart();
    const kept = chart.addIndicator('rsi', {}, { policy: { removable: false } });
    chart.addIndicator('sma');
    const available = new Set(registeredIndicators().map(item => item.id));
    const current = chart.getState().indicators!;
    const planned = planIndicatorTemplate(current, [{ indicatorId: 'ema', settings: {}, paneIndex: 0 }], 'replace', available, chart.panes().length);
    expect(planned.map(item => item.indicatorId)).toEqual(['rsi', 'ema']);
    expect(planned[0].instanceId).toBe(kept.id);
    expect(planned[0].policy).toEqual({ removable: false });
    const layout = captureIndicatorTemplate(chart);
    const plan = planIndicatorTemplateState(chart, layout, 'replace');
    expect(plan.indicators.filter(item => item.instanceId === kept.id)).toHaveLength(1);
  });
});
