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
import { renderInputRows, collectInputRows, initIndicators, openSettings, closeSettings, collectSettings, renderIndicatorChips } from '../src/indicators.js';
import { openOverlay, topOverlay, overlayKeydown } from '../src/ui.js';

const inputs = [
  { key: 'instrument', type: 'symbol', label: 'Instrument', default: 'AAA', exchangeKey: 'venue' },
  { key: 'venue', type: 'text', label: 'Venue', default: 'X1' },
  { key: 'hours', type: 'session', label: 'Session', default: '0900-1700:23456' },
  { key: 'note', type: 'multiline', label: 'Notes', default: 'a\nb' },
  { key: 'level', type: 'price', label: 'Price', default: 12.345678901234567, min: 0, max: 100, pick: true },
  { key: 'when', type: 'timestamp', label: 'Instant', default: 1700000000.125, pick: true },
  { key: 'wall', type: 'time', label: 'Wall time', default: '2026-01-01 09:30' },
];
const defaults = Object.fromEntries(inputs.map(input => [input.key, input.default]));
let serial = 0;
const cleanups = [];
afterEach(() => { cleanups.splice(0).reverse().forEach(dispose => dispose()); vi.unstubAllGlobals(); vi.useRealTimers(); });
function form() {
  const dom = installDom(); vi.stubGlobal('document', dom.doc); vi.stubGlobal('window', dom.win);
  const host = dom.doc.createElement('div'); host.id = 'set-body'; dom.root.appendChild(host);
  renderInputRows(host, inputs, defaults);
  return { dom, host, field: key => host.querySelector('#set-body_' + key) };
}
function fixture(options = {}) {
  const h = form(), { dom } = h, doc = dom.doc;
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
  const id = `reference-typed-${++serial}`;
  registerIndicator({ id, name: 'Reference typed', placement: 'onchart', inputs: options.inputs ?? inputs,
    plots: [{ key: 'value', type: 'line' }], calc: bars => ({ value: bars.map(bar => bar.close) }) });
  const inst = chart.addIndicator(id), draw = new DrawingController(chart), overlays = createOverlayStack(dom.root, doc);
  const ctx = { chart, draw, root: dom.root, document: doc, theme: 'dark', chartTheme: darkTheme,
    bus: new WidgetBus(), storage: new WidgetStorage('reference-typed', null), toast: vi.fn(),
    overlays, openOverlay: (node, options) => overlays.open(node, options), symbol: () => ({ symbol: 'PRIMARY' }), interval: () => '1m' };
  const app = { chart, draw, alertUi: { context: ctx }, req: {}, focusPane: 1 };
  initIndicators(app);
  const target = { pane: 1, chart, current: () => app.chart === chart };
  openSettings(inst.id, target); openOverlay(modal);
  cleanups.push(() => { closeSettings(); overlays.destroy(); draw.destroy(); chart.destroy(); });
  return { ...h, app, target, chart, draw, inst, modal, ctx };
}

describe('reference typed indicator controls', () => {
  it('uses literal multiline text and exact numeric seconds while keeping legacy time strings', () => {
    const h = form();
    expect(h.field('note').tagName).toBe('TEXTAREA');
    expect(h.host.textContent).toContain('UTC seconds');
    expect(collectInputRows(h.host)).toEqual(defaults);
    h.field('note').value = ' <b>literal</b>\nnext\n';
    h.field('when').value = '5e-324';
    expect(collectInputRows(h.host)).toMatchObject({ note: ' <b>literal</b>\nnext\n', when: Number.MIN_VALUE });
  });
  it('does not coerce a blank price draft to zero', () => {
    const h = form(); h.field('level').value = '';
    expect(collectInputRows(h.host).level).toBeUndefined();
  });
  it('retains invalid session and price drafts on Apply with inline errors', () => {
    const h = fixture();
    h.field('hours').value = '0960-1700'; h.field('level').value = '-1';
    expect(collectSettings()).toBe(false);
    expect(h.field('hours').value).toBe('0960-1700');
    expect(h.field('hours').getAttribute('aria-invalid')).toBe('true');
    expect(h.field('level').getAttribute('aria-invalid')).toBe('true');
    expect(h.inst.settings().level).toBe(defaults.level);
    expect(h.modal.hidden).toBe(false);
  });
  it('stages a searched symbol pair until Apply and discards a later selection on Cancel', async () => {
    vi.useFakeTimers();
    const h = fixture(), writes = vi.spyOn(h.inst, 'setSettings');
    h.field('instrument').value = 'reliance'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    h.field('instrument').fire('keydown', { key: 'Enter' });
    expect(collectInputRows(h.host)).toMatchObject({ instrument: 'RELIANCE.NS', venue: 'NSE' });
    expect(writes).not.toHaveBeenCalled();
    expect(collectSettings()).toBe(true);
    expect(writes).toHaveBeenCalledTimes(1);
    expect(writes.mock.calls[0][0]).toMatchObject({ instrument: 'RELIANCE.NS', venue: 'NSE' });
    h.field('instrument').value = 'btc'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    h.field('instrument').fire('keydown', { key: 'Enter' });
    closeSettings();
    expect(h.inst.settings()).toMatchObject({ instrument: 'RELIANCE.NS', venue: 'NSE' });
    expect(h.ctx.symbol()).toEqual({ symbol: 'PRIMARY' });
  });
  it('suspends the reference scrim and shell focus trap, then resumes the existing draft', () => {
    const h = fixture(), trigger = h.host.querySelector('[data-input-action="level"]');
    h.field('note').value = 'unsaved\ndraft'; trigger.focus(); trigger.click();
    expect(h.modal.hidden).toBe(true); expect(topOverlay()).toBeNull();
    const event = { key: 'Tab', preventDefault: vi.fn(), stopImmediatePropagation: vi.fn() };
    overlayKeydown(event); expect(event.preventDefault).not.toHaveBeenCalled();
    h.dom.doc.activeElement.fire('keydown', { key: 'Escape' });
    expect(h.modal.hidden).toBe(false); expect(topOverlay()).toBe(h.modal);
    expect(h.field('note').value).toBe('unsaved\ndraft');
    expect(h.dom.doc.activeElement).toBe(trigger);
    closeSettings(); expect(h.inst.settings().note).toBe('a\nb');
  });
  it('stages a native targeted chart pick and never revives a removed owner', () => {
    const h = fixture(); h.inst.setPlotPriceScales({ value: 'left' });
    h.inst.series('value').priceScale().setPriceRange({ min: 10, max: 30 });
    h.host.querySelector('[data-input-action="level"]').click();
    const expected = h.inst.series('value').priceScale().yToPrice(150);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: -999, time: 1700000060, id: null });
    expect(collectInputRows(h.host).level).toBe(expected);
    expect(h.inst.settings().level).toBe(defaults.level);
    expect(h.modal.hidden).toBe(false);
    h.host.querySelector('[data-input-action="level"]').click(); h.inst.remove();
    expect(h.modal.hidden).toBe(true);
    expect(h.dom.doc.body.querySelector('.oac-input-pick')).toBeNull();
  });
  it('stages both halves of a paired point from one pick and applies them in one patch', () => {
    const paired = [
      { key: 'at', type: 'timestamp', label: 'Anchor time', default: 1700000000, pick: true },
      { key: 'level', type: 'price', label: 'Anchor price', default: 2, min: 0, max: 100, pick: true, timeKey: 'at', anchor: true },
    ];
    const h = fixture({ inputs: paired });
    const trigger = h.host.querySelector('[data-input-action="level"]');
    expect(trigger.textContent).toBe('Pick point on chart');
    trigger.click();
    const scale = h.chart.panes()[0].priceScale, expected = scale.yToPrice(150);
    h.chart.emit('click', { paneIndex: 0, point: { x: 250, y: 150 }, price: -999, time: 1700000060.4, id: null });
    expect(collectInputRows(h.host)).toMatchObject({ at: 1700000060, level: expected });
    // Staged, as every other field of this dialog is, until Apply.
    expect(h.inst.settings()).toMatchObject({ at: 1700000000, level: 2 });
    const write = vi.spyOn(h.inst, 'setSettings');
    expect(collectSettings()).toBe(true);
    expect(write).toHaveBeenCalledOnce();
    expect(h.inst.settings()).toMatchObject({ at: 1700000060, level: expected });
  });
  it('resets native defaults and keeps an invalid draft editable until then', () => {
    const h = fixture(); h.inst.setSettings({ level: 80, note: 'changed' });
    h.field('level').value = 'bad'; expect(collectSettings()).toBe(false);
    h.dom.doc.getElementById('set-reset').click();
    expect(h.inst.settings()).toMatchObject({ level: defaults.level, note: 'a\nb' });
    expect(h.modal.hidden).toBe(true);
  });
  it('owns search popups above the modal and returns Escape to the same dialog', async () => {
    vi.useFakeTimers();
    const h = fixture();
    h.field('instrument').value = 'reliance'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150);
    const root = h.dom.doc.body.querySelector('.host-input-actions');
    expect(root.parentElement).toBe(h.dom.doc.body);
    expect(topOverlay()).toBe(root.querySelector('.oac-symbol-picker'));
    overlayKeydown({ key: 'Escape', preventDefault() {}, stopImmediatePropagation() {} });
    expect(topOverlay()).toBe(h.modal); expect(h.modal.hidden).toBe(false);
    expect(h.inst.settings().instrument).toBe('AAA');
    closeSettings(); expect(h.dom.doc.body.querySelector('.host-input-actions')).toBeNull();
  });
  it('preserves rejected drafts through unrelated removal and ignores a stale pick on owner replacement', () => {
    const h = fixture(), other = h.chart.addIndicator(h.inst.indicatorId);
    h.field('level').value = '1e'; expect(collectSettings()).toBe(false);
    other.remove(); expect(h.field('level').value).toBe('1e');
    let reply = () => {}; const stop = Object.assign(vi.fn(), { active: () => true });
    vi.spyOn(h.chart, 'beginPick').mockImplementation((_kind, callback) => { reply = callback; return stop; });
    h.host.querySelector('[data-input-action="level"]').click();
    h.app.chart = null; reply(50);
    expect(h.modal.hidden).toBe(true); expect(h.inst.settings().level).toBe(defaults.level);
    closeSettings(); expect(h.dom.doc.body.querySelector('.host-input-actions')).toBeNull();
  });
  it('collects an undeclared exchange setting and resets it with the symbol', async () => {
    vi.useFakeTimers(); const h = fixture({ inputs: inputs.filter(input => input.key !== 'venue') });
    h.field('instrument').value = 'reliance'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    expect(collectInputRows(h.host)).toMatchObject({ instrument: 'RELIANCE.NS', venue: 'NSE' });
    expect(collectSettings()).toBe(true);
    h.dom.doc.getElementById('set-reset').click();
    expect(h.inst.settings()).toMatchObject({ instrument: 'AAA', venue: '' });
  });

  it.each(['constructor', '__proto__'])('stages and applies the own exchange key %s without changing its prototype', async exchangeKey => {
    vi.useFakeTimers();
    const declared = inputs.filter(input => input.key !== 'venue')
      .map(input => input.type === 'symbol' ? { ...input, exchangeKey } : input);
    const h = fixture({ inputs: declared });
    h.field('instrument').value = 'reliance'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    const patch = collectInputRows(h.host);
    expect(Object.getOwnPropertyDescriptor(patch, exchangeKey)?.value).toBe('NSE');
    expect(Object.getPrototypeOf(patch)).toBe(Object.prototype);
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('');
    expect(collectSettings()).toBe(true);
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('NSE');
    h.field('instrument').value = 'btc'; h.field('instrument').fire('input');
    await vi.advanceTimersByTimeAsync(150); h.field('instrument').fire('keydown', { key: 'Enter' });
    closeSettings();
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('NSE');
    openSettings(h.inst.id, h.target);
    h.dom.doc.getElementById('set-reset').click();
    expect(h.inst.settings().instrument).toBe('AAA');
    expect(Object.getOwnPropertyDescriptor(h.inst.settings(), exchangeKey)?.value).toBe('');
    expect(Object.getPrototypeOf(h.inst.settings())).toBe(Object.prototype);
  });

  it.each(['constructor', '__proto__'])('collects a visible typed field named %s as an own data property', key => {
    const h = form();
    renderInputRows(h.host, [{ key, type: 'multiline', label: 'Note', default: 'before' }], { [key]: 'before' });
    h.field(key).value = 'after\nnext';
    const patch = collectInputRows(h.host);
    expect(Object.getOwnPropertyDescriptor(patch, key)?.value).toBe('after\nnext');
    expect(Object.getPrototypeOf(patch)).toBe(Object.prototype);
  });
});

describe('host policies in the reference settings and chips', () => {
  it('reports settings the host locked while the dialog was open, on Apply and on Reset', () => {
    const h = fixture();
    const before = h.inst.settings().level;
    h.inst.setPolicy({ configurable: false });
    h.field('level').value = '5';
    expect(collectSettings()).toBe(false);
    expect(h.inst.settings().level).toBe(before);
    expect(h.dom.doc.getElementById('status').textContent).toBe('Reference typed settings are protected by the host');
    h.dom.doc.getElementById('status').textContent = '';
    h.dom.doc.getElementById('set-reset').click();
    expect(h.dom.doc.getElementById('status').textContent).toBe('Reference typed settings are protected by the host');
    // Still open on the study, with its values as they are.
    expect(h.modal.hidden).toBe(false);
  });

  it('draws a protected study as a chip with no remove button, and leaves an unlisted one out', () => {
    const h = fixture();
    const pinned = h.chart.addIndicator(h.inst.indicatorId, {}, { policy: { removable: false } });
    h.chart.addIndicator(h.inst.indicatorId, {}, { policy: { listed: false } });
    renderIndicatorChips();
    const chips = [...h.dom.doc.getElementById('indlist').querySelectorAll('.chip')];
    // The unlisted study has no chip; the two listed ones keep their order.
    expect(chips).toHaveLength(2);
    expect(chips[0].querySelector('button')).not.toBeNull();
    expect(chips[1].querySelector('button')).toBeNull();
    expect(chips[1].classList.contains('is-protected')).toBe(true);
    expect(chips[1].title).toBe(`${pinned.name} is protected by the host`);
  });
});
