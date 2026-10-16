import { afterEach, describe, expect, it, vi } from 'vitest';
vi.mock('/dist/openalgo-charts.mjs', () => import('../../../src/index.ts'));
vi.mock('/dist/openalgo-charts.widget.mjs', () => import('../../../src/widget/index.ts'));
vi.mock('openalgo-charts', () => import('../../../src/index.ts'));
vi.mock('openalgo-charts/draw', () => import('../../../src/draw/index.ts'));
vi.mock('../src/persist.js', () => ({ autosave: vi.fn() }));
import { Chart, darkTheme, registerIndicator } from '../../../src/index.ts';
import { DrawingController } from '../../../src/draw/index.ts';
import { createOverlayStack, WidgetBus, WidgetStorage } from '../../../src/widget/context.ts';
import { controlsFromInputs, renderForm } from '../../../src/widget/form.ts';
import { installDom } from '../../../tests/widget-form.test.ts';
import { renderInputRows, destroyInputRows, collectInputRows, initIndicators, openSettings, closeSettings, collectSettings } from '../src/indicators.js';
import { validateTypedRows } from '../src/indicator-input-controls.js';
import { openOverlay } from '../src/ui.js';

// The reference host's own form reads the same descriptor rules as the widget:
// rows shown by a setting, rows enabled by one, and neighbours on one row.
const MODES = [{ label: 'Simple', value: 'simple' }, { label: 'Bands', value: 'bands' }];
const inputs = [
  { key: 'length', type: 'number', label: 'Length', default: 14, min: 1, max: 500, inline: 'len' },
  { key: 'source', type: 'source', label: 'Source', default: 'close', inline: 'len' },
  { key: 'mode', type: 'select', label: 'Mode', default: 'simple', options: MODES },
  { key: 'width', type: 'number', label: 'Band width', default: 2, min: 0.5, max: 5, step: 0.5, visibleWhen: { key: 'mode', is: 'bands' } },
  { key: 'level', type: 'price', label: 'Anchor price', default: 10, min: 0, max: 100, visibleWhen: { key: 'mode', is: 'bands' } },
  { key: 'smoothing', type: 'select', label: 'Smoothing', default: 'none', group: 'Smoothing',
    options: [{ label: 'None', value: 'none' }, { label: 'Moving average', value: 'sma' }] },
  { key: 'smoothLength', type: 'number', label: 'Smoothing length', default: 5, min: 1, max: 50, group: 'Smoothing',
    activeWhen: { key: 'smoothing', isNot: 'none' } },
  { key: 'showSignal', type: 'boolean', label: 'Signal', default: false, group: 'Signal', inline: 'signal' },
  { key: 'signalLength', type: 'number', label: 'Length', default: 9, min: 1, max: 50, group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
  { key: 'signalColor', type: 'color', label: 'Colour', default: '#f59e0b', group: 'Signal', inline: 'signal',
    activeWhen: { key: 'showSignal', is: true } },
];
const defaults = Object.fromEntries(inputs.map(input => [input.key, input.default]));
let serial = 0;
const cleanups = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(dispose => dispose()); vi.unstubAllGlobals(); });

/** False when the node or an ancestor below the host is hidden, which also takes it out of the tab order. */
function shown(node, host) {
  for (let n = node; n && n !== host; n = n.parentElement) if (n.hidden) return false;
  return true;
}

function form(list = inputs, values = defaults, unavailable = undefined) {
  const dom = installDom(); vi.stubGlobal('document', dom.doc); vi.stubGlobal('window', dom.win);
  const host = dom.doc.createElement('div'); host.id = 'set-body'; dom.root.appendChild(host);
  renderInputRows(host, list, values, undefined, unavailable);
  const field = key => host.querySelector('#set-body_' + key);
  const choose = (key, value) => { field(key).value = value; field(key).fire('change'); };
  const live = () => host.querySelector('[role="status"][aria-live="polite"]');
  return { dom, host, field, choose, live, visible: key => shown(field(key), host) };
}

/** The widget's own generated form over the same inputs, driven the same way, for answers both must share. */
function widgetForm(list, values) {
  const dom = installDom();
  const host = dom.doc.createElement('div'); dom.root.appendChild(host);
  renderForm(host, controlsFromInputs(list), { values, idPrefix: 'w', onChange() {} });
  const field = key => host.querySelector('#w-' + key);
  const live = () => host.querySelector('[role="status"][aria-live="polite"]');
  return { host, field, live, visible: key => shown(field(key), host) };
}

/** How many listeners of one event type the host element itself carries, from the test document's bookkeeping. */
function listeners(host, type) {
  return host._listeners.get(type)?.length ?? 0;
}

function fixture(list = inputs) {
  const h = form(list, Object.fromEntries(list.map(input => [input.key, input.default]))), { dom } = h, doc = dom.doc;
  const modal = doc.createElement('div'); modal.id = 'setmodal'; modal.hidden = true;
  dom.root.appendChild(modal); modal.appendChild(h.host);
  for (const id of ['set-title', 'set-ok', 'set-x', 'set-reset']) {
    const node = doc.createElement(id === 'set-title' ? 'div' : 'button'); node.id = id; modal.appendChild(node);
  }
  for (const id of ['status', 'indlist', 'indadd', 'indpick']) {
    const node = doc.createElement('div'); node.id = id; dom.root.appendChild(node);
  }
  const chart = new Chart(dom.chartEl, { document: doc, pixelRatio: () => 1, shortcuts: false,
    branding: false, timeNavigator: false, raf: { schedule: fn => { fn(); return 1; }, cancel() {} } });
  chart.applySize(900, 600);
  chart.addSeries('line').setData([1, 2, 3].map((close, i) => ({ time: 1700000000 + 60 * i, open: close, high: close, low: close, close })));
  const id = `reference-conditional-${++serial}`;
  registerIndicator({ id, name: 'Reference conditional', placement: 'onchart', inputs: list,
    plots: [{ key: 'value', type: 'line' }], calc: bars => ({ value: bars.map(bar => bar.close) }) });
  const inst = chart.addIndicator(id), draw = new DrawingController(chart), overlays = createOverlayStack(dom.root, doc);
  const ctx = { chart, draw, root: dom.root, document: doc, theme: 'dark', chartTheme: darkTheme,
    bus: new WidgetBus(), storage: new WidgetStorage('reference-conditional', null), toast: vi.fn(),
    overlays, openOverlay: (node, options) => overlays.open(node, options), symbol: () => ({ symbol: 'PRIMARY' }), interval: () => '1m' };
  const app = { chart, draw, alertUi: { context: ctx }, req: {}, focusPane: 1 };
  initIndicators(app);
  const target = { pane: 1, chart, current: () => app.chart === chart };
  const open = () => { openSettings(inst.id, target); openOverlay(modal); };
  open();
  cleanups.push(() => { closeSettings(); overlays.destroy(); draw.destroy(); chart.destroy(); });
  return { ...h, chart, inst, modal, open, button: id => doc.getElementById(id) };
}

describe('reference host conditional inputs', () => {
  it('shows a row only while its condition holds and re-reads it on every draft change', () => {
    const h = form();
    expect(h.visible('width')).toBe(false);
    expect(h.visible('level')).toBe(false);
    h.choose('mode', 'bands');
    expect(h.visible('width')).toBe(true);
    expect(h.visible('level')).toBe(true);
    h.choose('mode', 'simple');
    expect(h.visible('width')).toBe(false);
  });

  it('disables an inactive row with a reason, then enables it when its controller changes', () => {
    const h = form();
    const row = h.field('smoothLength').closest('.set-row');
    expect(h.field('smoothLength').disabled).toBe(true);
    expect(h.field('smoothLength').title).toBe('Depends on Smoothing');
    expect(row.classList.contains('set-row--off')).toBe(true);
    h.choose('smoothing', 'sma');
    expect(h.field('smoothLength').disabled).toBe(false);
    expect(row.classList.contains('set-row--off')).toBe(false);
  });

  it('keeps a hidden draft and still sends it when it is valid', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('width').value = '3.5'; h.field('width').fire('input');
    h.choose('mode', 'simple');
    expect(h.field('width').value).toBe('3.5');
    expect(collectInputRows(h.host)).toMatchObject({ mode: 'simple', width: 3.5 });
    h.choose('mode', 'bands');
    expect(h.field('width').value).toBe('3.5');
  });

  it('drops an invalid draft that is hidden, so the stored value stands and Apply is not blocked', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('level').value = '-3'; h.field('level').fire('input');
    expect(validateTypedRows(h.host)).toBe(false);
    h.choose('mode', 'simple');
    expect(validateTypedRows(h.host)).toBe(true);
    expect(collectInputRows(h.host)).not.toHaveProperty('level');
    const error = h.host.querySelector('#set-body_level-error');
    expect(error.hidden).toBe(true);
    h.choose('mode', 'bands');
    expect(h.field('level').value).toBe('-3');
    expect(error.hidden).toBe(false);
    expect(validateTypedRows(h.host)).toBe(false);
  });

  it('announces shown, hidden and newly editable rows in a polite live region', () => {
    const h = form();
    expect(h.live().textContent).toBe('');
    h.choose('mode', 'bands');
    expect(h.live().textContent).toBe('Shown: Band width, Anchor price');
    h.choose('smoothing', 'sma');
    expect(h.live().textContent).toBe('Available: Smoothing length');
    h.choose('mode', 'simple');
    expect(h.live().textContent).toBe('Hidden: Band width, Anchor price');
  });

  it('moves focus from a field that its own form hides', () => {
    const h = form();
    h.choose('mode', 'bands');
    h.field('width').focus();
    h.field('mode').value = 'simple'; h.field('mode').fire('change');
    expect(h.dom.doc.activeElement).toBe(h.field('mode'));
  });

  it('puts inline inputs on one row with their own labels, and dims one member alone', () => {
    const h = form();
    const len = h.host.querySelector('[data-inline="len"]');
    expect(len.classList.contains('set-row--inline')).toBe(true);
    expect(len.querySelector('#set-body_length')).toBe(h.field('length'));
    expect(len.querySelector('#set-body_source')).toBe(h.field('source'));
    expect(len.querySelectorAll('label').map(label => label.textContent)).toEqual(['Length', 'Source']);
    const signal = h.host.querySelector('[data-inline="signal"]');
    expect(signal.querySelector('#set-body_showSignal')).toBe(h.field('showSignal'));
    expect(signal.querySelector('#set-body_signalLength')).toBe(h.field('signalLength'));
    const item = h.field('signalLength').closest('.set-inline');
    expect(item.classList.contains('set-inline--off')).toBe(true);
    expect(h.field('signalColor')._colorPicker.trigger.disabled).toBe(true);
    h.field('showSignal').checked = true; h.field('showSignal').fire('change');
    expect(item.classList.contains('set-inline--off')).toBe(false);
    expect(h.field('signalColor')._colorPicker.trigger.disabled).toBe(false);
    // Items carry no data-key of their own, so collecting reads fields only.
    expect(Object.keys(collectInputRows(h.host)).sort()).toEqual(Object.keys(defaults).sort());
  });

  it('adds no live region and no listeners to a form without conditions', () => {
    const h = form([{ key: 'n', type: 'number', label: 'N', default: 1 }], { n: 1 });
    expect(h.live()).toBeNull();
    expect([listeners(h.host, 'input'), listeners(h.host, 'change')]).toEqual([0, 0]);
  });

  it('runs one refresh per edit however many times a form is rendered into the same host', () => {
    const unavailable = vi.fn(() => null);
    const h = form(inputs, defaults, unavailable);
    for (let i = 0; i < 4; i++) renderInputRows(h.host, inputs, defaults, undefined, unavailable);
    unavailable.mockClear();
    h.choose('mode', 'bands');
    // The refresh asks the host once per field; a listener left by an earlier render would ask again.
    expect(unavailable).toHaveBeenCalledTimes(h.host.querySelectorAll('[data-key]').length);
    expect([listeners(h.host, 'input'), listeners(h.host, 'change')]).toEqual([0, 1]);
    destroyInputRows(h.host);
    expect(listeners(h.host, 'change')).toBe(0);
  });

  it('keeps one form listener across every open of the settings dialog, and none once it closes', () => {
    const h = fixture();
    expect([listeners(h.host, 'input'), listeners(h.host, 'change')]).toEqual([0, 1]);
    for (let i = 0; i < 4; i++) h.open();
    expect([listeners(h.host, 'input'), listeners(h.host, 'change')]).toEqual([0, 1]);
    closeSettings();
    expect(listeners(h.host, 'change')).toBe(0);
  });

  it('reads a number and a price the way the widget form does: once committed, clamped, and a refused draft is no edit', () => {
    const list = [
      { key: 'width', type: 'number', label: 'Band width', default: 2, min: 0.5, max: 5 },
      { key: 'fill', type: 'boolean', label: 'Fill', default: false, visibleWhen: { key: 'width', isNot: 0 } },
      { key: 'wide', type: 'boolean', label: 'Wide', default: false, visibleWhen: { key: 'width', is: 5 } },
      { key: 'level', type: 'price', label: 'Anchor', default: 10, min: 0, max: 100 },
      { key: 'near', type: 'boolean', label: 'Near', default: false, visibleWhen: { key: 'level', is: 20 } },
    ];
    const values = Object.fromEntries(list.map(input => [input.key, input.default]));
    for (const [surface, s] of [['host', form(list, values)], ['widget', widgetForm(list, values)]]) {
      const type = (key, text, ...events) => { s.field(key).value = text; for (const event of events) s.field(key).fire(event); };
      // Mid-typing, a blank box is not a width of 0.
      type('width', '', 'input');
      expect([surface, s.visible('fill'), s.live().textContent]).toEqual([surface, true, '']);
      // Committed blank: no edit, and the last good value comes back.
      s.field('width').fire('change');
      expect([surface, s.field('width').value, s.visible('fill'), s.live().textContent]).toEqual([surface, '2', true, '']);
      type('width', '9', 'input', 'change');
      expect([surface, s.field('width').value, s.visible('wide'), s.live().textContent]).toEqual([surface, '5', true, 'Shown: Wide']);
      type('level', '20', 'input', 'change');
      expect([surface, s.visible('near')]).toEqual([surface, true]);
      // A price the form refuses is not written, so the last accepted one still decides.
      type('level', '-3', 'input', 'change');
      expect([surface, s.visible('near')]).toEqual([surface, true]);
    }
  });

  it('hides a row that reads the switch of a hidden colour pair, and names the pair for one that reads its swatch', () => {
    const list = [
      { key: 'on', type: 'boolean', label: 'On', default: false },
      { key: 'borders', type: 'colorPair', label: 'Borders', visibleWhen: { key: 'on', is: true },
        enabled: { key: 'pe', default: true },
        up: { key: 'pu', label: 'Up', default: '#00ff00' }, down: { key: 'pd', label: 'Down', default: '#ff0000' } },
      { key: 'w', type: 'number', label: 'Border width', default: 1, visibleWhen: { key: 'pe', is: true } },
      { key: 'shade', type: 'number', label: 'Shade', default: 1, activeWhen: { key: 'pu', isNot: '' } },
    ];
    const h = form(list, { on: false, pe: true, pu: '#00ff00', pd: '#ff0000', w: 1, shade: 1 });
    expect(h.visible('pe')).toBe(false);
    expect(h.visible('w')).toBe(false);
    expect(h.field('shade').disabled).toBe(true);
    expect(h.field('shade').title).toBe('Depends on Borders');
    h.field('on').checked = true; h.field('on').fire('change');
    expect(h.visible('w')).toBe(true);
    expect(h.field('shade').disabled).toBe(false);
    h.field('pe').checked = false; h.field('pe').fire('change');
    expect(h.visible('w')).toBe(false);
  });

  it('turns a chart pick and a symbol search off with the field they fill, and back on with it', () => {
    const h = fixture([
      { key: 'anchored', type: 'boolean', label: 'Anchor', default: false },
      { key: 'level', type: 'price', label: 'Anchor price', default: 2, pick: true, activeWhen: { key: 'anchored', is: true } },
      { key: 'other', type: 'symbol', label: 'Other symbol', default: 'AAA', activeWhen: { key: 'anchored', is: true } },
    ]);
    const pick = h.modal.querySelector('[data-input-action="level"]');
    const search = h.modal.querySelector('[data-input-action="other"]');
    for (const action of [pick, search]) {
      expect(action.disabled).toBe(true);
      expect(action.title).toBe('Depends on Anchor');
    }
    h.field('anchored').checked = true; h.field('anchored').fire('change');
    for (const action of [pick, search]) expect(action.disabled).toBe(false);
    h.field('anchored').checked = false; h.field('anchored').fire('change');
    for (const action of [pick, search]) expect(action.disabled).toBe(true);
  });

  it('applies the drafts, a hidden valid one included, and Close discards them', () => {
    const h = fixture();
    h.choose('mode', 'bands');
    h.field('width').value = '4'; h.field('width').fire('input');
    h.choose('mode', 'simple');
    closeSettings();
    expect(h.inst.settings()).toMatchObject({ mode: 'simple', width: 2 });
    h.open();
    expect(h.visible('width')).toBe(false);
    expect(h.field('width').value).toBe('2');
    h.choose('mode', 'bands');
    h.field('width').value = '4'; h.field('width').fire('input');
    h.choose('smoothing', 'sma');
    expect(collectSettings()).toBe(true);
    expect(h.inst.settings()).toMatchObject({ mode: 'bands', width: 4, smoothing: 'sma' });
  });

  it('applies past a hidden invalid draft and keeps the stored value', () => {
    const h = fixture();
    h.choose('mode', 'bands');
    h.field('level').value = '-1'; h.field('level').fire('input');
    expect(collectSettings()).toBe(false);
    h.choose('mode', 'simple');
    expect(collectSettings()).toBe(true);
    expect(h.inst.settings()).toMatchObject({ mode: 'simple', level: 10 });
  });

  it('restores every default, hidden inputs included', () => {
    const h = fixture();
    h.choose('mode', 'bands'); h.field('width').value = '4'; h.field('width').fire('input');
    expect(collectSettings()).toBe(true);
    h.open();
    h.button('set-reset').click();
    expect(h.inst.settings()).toMatchObject({ mode: 'simple', width: 2, smoothing: 'none' });
    h.open();
    expect(h.visible('width')).toBe(false);
    expect(h.field('smoothLength').disabled).toBe(true);
  });
});
