// The demo's study settings dialog is one step on the chart's timeline per
// session: each tab switch commits the form, and so does OK, and all of it is
// taken back by one undo.
import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.widget.mjs', () => import('../../../src/widget/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
vi.mock('openalgo-charts/draw', () => import('../../../src/draw/index.ts'));
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
import { Chart, darkTheme, registerIndicator } from '../../../src/index.ts';
import { DrawingController } from '../../../src/draw/index.ts';
import { createOverlayStack, WidgetBus, WidgetStorage } from '../../../src/widget/context.ts';
import { installDom } from '../../../tests/widget-form.test.ts';
import { initIndicators, openSettings, closeSettings } from '../src/indicators.js';
import { initHistory, attachHistory, historyFor } from '../src/history.js';
import { openOverlay } from '../src/ui.js';

const cleanups = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(dispose => dispose()); vi.unstubAllGlobals(); });

registerIndicator({
  id: 'demo-dialog-study', name: 'Demo dialog study', placement: 'pane',
  inputs: [{ key: 'length', type: 'number', label: 'Length', default: 5 }],
  plots: [{ key: 'value', type: 'line' }],
  calc: bars => ({ value: bars.map(bar => bar.close) }),
});
registerIndicator({
  id: 'demo-dialog-anchored', name: 'Demo anchored study', placement: 'onchart',
  inputs: [
    { key: 'at', type: 'timestamp', label: 'Anchor time', default: 1700000000, pick: true },
    { key: 'level', type: 'price', label: 'Anchor price', default: 2, min: 0, max: 100, pick: true, timeKey: 'at', anchor: true },
  ],
  plots: [{ key: 'value', type: 'line' }],
  calc: (bars, settings) => ({ value: bars.map(bar => (bar.time >= settings.at ? settings.level : null)) }),
});

function fixture(indicatorId = 'demo-dialog-study') {
  const dom = installDom(); vi.stubGlobal('document', dom.doc); vi.stubGlobal('window', dom.win);
  const doc = dom.doc;
  const modal = doc.createElement('div'); modal.id = 'setmodal'; modal.hidden = true; dom.root.appendChild(modal);
  const host = doc.createElement('div'); host.id = 'set-body'; modal.appendChild(host);
  for (const id of ['set-title', 'set-ok', 'set-x', 'set-reset']) {
    const node = doc.createElement(id === 'set-title' ? 'div' : 'button'); node.id = id; modal.appendChild(node);
  }
  for (const name of ['inputs', 'style']) {
    const tab = doc.createElement('button'); tab.className = 'set-tab'; tab.dataset.tab = name; modal.appendChild(tab);
  }
  for (const id of ['status', 'indlist', 'indadd', 'indpick']) {
    const node = doc.createElement('div'); node.id = id; dom.root.appendChild(node);
  }
  const chart = new Chart(dom.chartEl, { document: doc, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, raf: { schedule: fn => { fn(); return 1; }, cancel() {} } });
  chart.applySize(900, 600);
  chart.addSeries('line').setData([1, 2, 3, 4].map((close, i) => ({ time: 1700000000 + 60 * i, open: close, high: close, low: close, close })));
  const study = chart.addIndicator(indicatorId);
  const draw = new DrawingController(chart), overlays = createOverlayStack(dom.root, doc);
  // What the dialog's pick controls borrow from the chart's own panels.
  const context = { chart, draw, root: dom.root, document: doc, theme: 'dark', chartTheme: darkTheme,
    bus: new WidgetBus(), storage: new WidgetStorage('history-dialogs', null), toast: vi.fn(),
    overlays, openOverlay: (node, options) => overlays.open(node, options), symbol: () => ({ symbol: 'PRIMARY' }), interval: () => '1m' };
  const app = { chart, draw, alertUi: { context }, req: {}, focusPane: 1 };
  initIndicators(app);
  initHistory(app);
  attachHistory(1);
  const target = { pane: 1, chart, current: () => app.chart === chart };
  cleanups.push(() => { closeSettings(); historyFor(1)?.destroy(); overlays.destroy(); draw.destroy(); chart.destroy(); });
  const field = key => host.querySelector('#set-body_' + key);
  const click = id => doc.getElementById(id).click();
  const tab = name => [...doc.querySelectorAll('.set-tab')].find(node => node.dataset.tab === name).click();
  return { app, chart, draw, study, target, field, click, tab, host, modal };
}

const settle = () => new Promise(resolve => setTimeout(resolve, 0));

describe('the demo study settings dialog', () => {
  it('is one step per session, however many tabs commit the form on the way', async () => {
    const h = fixture();
    const history = historyFor(1);
    openSettings(h.study.id, h.target);
    h.field('length').value = '12';
    h.tab('inputs');                      // a tab switch commits the form
    await settle();
    h.field('length').value = '20';
    h.click('set-ok');                    // and so does OK
    await settle();
    expect(h.study.settings().length).toBe(20);
    expect(history.peekUndo()).toEqual({ label: 'Study settings', changes: ['study-settings'] });
    expect(history.undo()).toBe(true);
    expect(h.study.settings().length).toBe(5);
    expect(history.canUndo()).toBe(false);
    expect(history.redo()).toBe(true);
    expect(h.study.settings().length).toBe(20);
  });

  it('walks a line, an anchor drag and a Pick point on chart one step each, the pick taken back first', async () => {
    const h = fixture('demo-dialog-anchored');
    const history = historyFor(1);
    const line = h.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: 1700000060, price: 1.5 }] });
    const id = `input-anchor:${h.study.id}:level`;
    h.chart.emit('drag:start', { id, time: 1700000000, price: 2, paneIndex: 0 });
    h.chart.emit('drag', { id, time: 1700000120, price: 2.5, paneIndex: 0 });
    h.chart.emit('drag:end', { id, time: 1700000120, price: 2.5, paneIndex: 0 });
    await settle();
    expect(h.study.settings()).toMatchObject({ at: 1700000120, level: 2.5 });

    openSettings(h.study.id, h.target); openOverlay(h.modal);
    const trigger = h.host.querySelector('[data-input-action="level"]');
    expect(trigger.textContent).toBe('Pick point on chart');
    trigger.click();
    const picked = h.chart.panes()[0].priceScale.yToPrice(150);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: -999, time: 1700000180.4, id: null });
    h.click('set-ok');                    // Apply writes the staged point
    await settle();
    expect(h.study.settings()).toMatchObject({ at: 1700000180, level: picked });
    // Every step is the chart timeline's: the drawing history holds the line alone.
    expect(h.draw.historySteps().undo).toHaveLength(1);

    expect(history.peekUndo()).toEqual({ label: 'Study settings', changes: ['study-settings'] });
    expect(history.undo()).toBe(true);
    expect(h.study.settings()).toMatchObject({ at: 1700000120, level: 2.5 });
    expect(history.undo()).toBe(true);
    expect(h.study.settings()).toMatchObject({ at: 1700000000, level: 2 });
    expect(h.draw.get(line.id)).toBeDefined();
    expect(history.undo()).toBe(true);
    expect(h.draw.get(line.id)).toBeUndefined();
    expect(history.canUndo()).toBe(false);
    for (let i = 0; i < 3; i++) expect(history.redo()).toBe(true);
    expect(h.study.settings()).toMatchObject({ at: 1700000180, level: picked });
    expect(h.draw.get(line.id)).toBeDefined();
  });

  it('leaves no step for a session closed with nothing changed', async () => {
    const h = fixture();
    const history = historyFor(1);
    openSettings(h.study.id, h.target);
    h.tab('style');
    await settle();
    h.click('set-x');
    await settle();
    expect(history.canUndo()).toBe(false);
  });
});
