/**
 * Drawing policies as the widget presents them. The controller already
 * refuses a read-only edit, so the failure this guards against is a control
 * that is offered and then does nothing: every surface that edits a drawing
 * must draw it disabled, with the reason, or leave it out.
 */
import { describe, it, expect, beforeAll, afterEach, vi } from 'vitest';
import { Chart, darkTheme, registerIndicator } from 'openalgo-charts';
import type { Bar, ContextMenuEvent, ContextMenuTarget } from 'openalgo-charts';
import { DrawingController, registerBuiltinDrawingTools, type DrawingInput, type DrawingPolicy } from 'openalgo-charts/draw';
import { createOverlayStack, WidgetBus, WidgetStorage, type OverlayStack, type WidgetContext } from '../src/widget/context';
import {
  mountDrawingProperties, mountLevelEditor, mountTextEditor, contextMenuEntries, type MenuEntry, type MenuItem,
} from '../src/widget/dialogs/index';
import { createObjectsPanelContent } from '../src/widget/objects-panel';
import { alertSourceFields } from '../src/widget/dialogs/alert-source';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { installDom, asDoc, asEl, type FakeElement, type Dom } from './widget-form.test';
import {
  ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey,
  type FakeElement as WidgetElement,
} from './helpers/fake-dom-widget';

const T0 = 1700000000;
const BARS: Bar[] = Array.from({ length: 40 }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: T0 + i * 60, open: c - 0.5, high: c + 1, low: c - 1, close: c, volume: 100 + i };
});
const READ_ONLY: DrawingPolicy = { editable: false };
/** A macrotask: long enough for a cut's clipboard write, and the delete after it, to finish. */
const settle = (): Promise<void> => new Promise((resolve) => { setTimeout(resolve, 0); });

interface Rig { ctx: WidgetContext; dom: Dom; chart: Chart; draw: DrawingController; toasts: string[]; stack: OverlayStack; q(sel: string): FakeElement | null; qa(sel: string): FakeElement[] }
const rigs: Rig[] = [];

function makeRig(): Rig {
  const dom = installDom();
  const doc = asDoc(dom.doc);
  const chart = new Chart(asEl(dom.chartEl), {
    document: doc, pixelRatio: () => 1, shortcuts: false, timeNavigator: false,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(958, 660);
  chart.addSeries('candlestick').setData(BARS);
  const draw = new DrawingController(chart);
  const stack = createOverlayStack(asEl(dom.root), doc);
  const toasts: string[] = [];
  const ctx: WidgetContext = {
    chart, draw, root: asEl(dom.root), document: doc, theme: 'dark', chartTheme: darkTheme,
    keymap: {} as WidgetContext['keymap'], bus: new WidgetBus(), storage: new WidgetStorage('test', null), locale: undefined,
    toast: (message, kind) => { toasts.push(`${kind ?? 'info'}:${message}`); return { node: doc.createElement('div'), dismiss: () => {} }; },
    openOverlay: (el, opts) => stack.open(el, opts), status: () => {},
    tips: { attach() {}, refreshLabel() {}, show() {}, hide() {}, target: () => null, destroy() {} },
    overlays: stack, symbol: () => ({ symbol: 'TEST', exchange: 'NSE' }), interval: () => '5m',
  };
  const layer = (): FakeElement => stack.layer as unknown as FakeElement;
  const rig: Rig = { ctx, dom, chart, draw, toasts, stack, q: (sel) => layer().querySelector(sel), qa: (sel) => layer().querySelectorAll(sel) };
  rigs.push(rig);
  return rig;
}

const add = (draw: DrawingController, tool: string, extra: Partial<DrawingInput> = {}) => draw.add({
  tool, paneIndex: 0, style: {},
  points: [{ time: T0 + 600, price: 98 }, { time: T0 + 1800, price: 103 }], ...extra,
});

const items = (entries: MenuEntry[]): MenuItem[] => entries.filter((e): e is MenuItem => e.kind === undefined || e.kind === 'item');
const menuFor = (rig: Rig, id: string): MenuItem[] => {
  const target: ContextMenuTarget = { kind: 'drawing', id: `draw:${id}` };
  const e: ContextMenuEvent = { paneIndex: 0, point: { x: 200, y: 150 }, price: 101, time: T0 + 600, index: 10, target, preventDefault: () => {} };
  return items(contextMenuEntries(rig.ctx, e));
};

const widgets: Widget[] = [];
beforeAll(() => { registerBuiltinDrawingTools(); ensureWindowGlobal(); });
afterEach(() => {
  for (const r of rigs.splice(0)) { r.stack.destroy(); r.chart.destroy(); }
  for (const w of widgets.splice(0)) if (!w.isDestroyed) w.destroy();
});

function makeWidget(options: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc) as unknown as HTMLElement, {
    document: doc as unknown as Document, persist: false, pixelRatio: () => 1,
    raf: { schedule: (cb) => { cb(); return 1; }, cancel: () => {} }, ...options,
  });
  widgets.push(w);
  w.chart.applySize(800, 600);
  w.series.setData(BARS);
  const root = w.root as unknown as WidgetElement;
  root.rect = { left: 0, top: 0, width: 800, height: 600 };
  const chartEl = root.querySelector('.oac-chart') as WidgetElement;
  fire(root, 'pointerenter');
  return { w, doc, root, chartEl };
}

describe('the context menu on a read-only drawing', () => {
  it('keeps copy and duplicate, and draws every edit disabled with the reason', () => {
    const rig = makeRig();
    const fixed = add(rig.draw, 'rectangle', { policy: READ_ONLY });
    const rows = menuFor(rig, fixed.id);
    const by = (id: string): MenuItem => rows.find((r) => r.id === id) as MenuItem;
    expect(rig.draw.selection()).toEqual([fixed.id]);
    for (const id of ['draw-cut', 'draw-lock', 'draw-hide', 'draw-delete']) {
      expect(by(id).disabled, id).toBe(true);
      expect(by(id).note, id).toBe('read-only');
    }
    for (const id of ['draw-props', 'draw-copy', 'draw-duplicate']) expect(by(id).disabled, id).not.toBe(true);
    // Only the drawings the user may remove are counted, and removed.
    const free = add(rig.draw, 'rectangle');
    const clear = menuFor(rig, fixed.id).find((r) => r.id === 'draw-clear') as MenuItem;
    expect(clear.label).toBe('Remove all drawings (1)');
    clear.run?.();
    expect(rig.draw.get(free.id)).toBeUndefined();
    expect(rig.draw.get(fixed.id)).toBeDefined();
    expect(menuFor(rig, fixed.id).some((r) => r.id === 'draw-clear')).toBe(false);
  });

  it('draws the text and level editors disabled for a read-only text and ladder', () => {
    const rig = makeRig();
    const note = add(rig.draw, 'text', { policy: READ_ONLY, points: [{ time: T0 + 600, price: 100 }], text: { value: 'Fixed' } });
    const fib = add(rig.draw, 'fib-retracement', { policy: READ_ONLY });
    expect(menuFor(rig, note.id).find((r) => r.id === 'draw-text')?.disabled).toBe(true);
    expect(menuFor(rig, fib.id).find((r) => r.id === 'draw-levels')?.disabled).toBe(true);
  });
});

describe('the alert dialog\'s study lists', () => {
  it('leave a study its host keeps unlisted out, unless the alert already names it', () => {
    const rig = makeRig();
    registerIndicator({ id: 'policy-level', name: 'Level', placement: 'onchart', inputs: [],
      plots: [{ key: 'v', title: 'Level', type: 'line' }], calc: bars => ({ v: bars.map(() => 100) }) });
    const shown = rig.chart.addIndicator('policy-level');
    const quiet = rig.chart.addIndicator('policy-level', {}, { policy: { listed: false } });
    const line = add(rig.draw, 'horizontal-line', { points: [{ time: T0 + 600, price: 100 }] });
    const choices = (key: string, draft: Record<string, unknown>): string[] => {
      const control = alertSourceFields(rig.ctx, draft).controls.find((c) => c.key === key);
      return (control?.options ?? []).map((o) => o.value);
    };
    expect(choices('instanceId', { kind: 'indicator' })).toEqual([shown.id]);
    expect(choices('instanceId', { kind: 'indicator', instanceId: quiet.id })).toEqual([shown.id, quiet.id]);
    // The study a drawing alert compares with follows the same rule.
    expect(choices('inputInstanceId', { kind: 'drawing', drawingId: line.id })).toEqual(['', shown.id]);
    expect(choices('inputInstanceId', { kind: 'drawing', drawingId: line.id, inputInstanceId: quiet.id })).toEqual(['', shown.id, quiet.id]);
  });
});

describe('the alert dialog\'s drawing picker', () => {
  it('leaves unlisted drawings out, unless the alert already names one', () => {
    const rig = makeRig();
    const shown = add(rig.draw, 'horizontal-line', { points: [{ time: T0 + 600, price: 100 }] });
    const quiet = add(rig.draw, 'horizontal-line', { points: [{ time: T0 + 600, price: 99 }], policy: { listed: false } });
    const choices = (draft: Record<string, unknown>): string[] => {
      const control = alertSourceFields(rig.ctx, draft).controls.find((c) => c.key === 'drawingId');
      return (control?.options ?? []).map((o) => o.value);
    };
    expect(choices({ kind: 'drawing' })).toEqual([shown.id]);
    expect(choices({ kind: 'drawing', drawingId: quiet.id })).toEqual([shown.id, quiet.id]);
  });
});

describe('the editors on a read-only drawing', () => {
  it('opens the properties read-only: every field and edit action disabled, duplicate still there', () => {
    const rig = makeRig();
    const fixed = add(rig.draw, 'rectangle', { policy: READ_ONLY });
    mountDrawingProperties(rig.ctx, undefined, { ids: [fixed.id] });
    const color = rig.q('#oac-props-style-color') as FakeElement;
    expect(color.disabled).toBe(true);
    expect((rig.q('input[type="range"]') as FakeElement).disabled).toBe(true);
    const act = (name: string): FakeElement => rig.q(`[data-act="${name}"]`) as FakeElement;
    for (const name of ['lock', 'visible', 'delete']) expect(act(name).disabled, name).toBe(true);
    expect(act('duplicate').disabled).not.toBe(true);
    const restore = rig.qa('.oac-btn').find((b) => b.textContent === 'Restore defaults') as FakeElement;
    expect(restore.disabled).toBe(true);
  });

  it('declines to open the text box or the level ladder on one', () => {
    const rig = makeRig();
    const note = add(rig.draw, 'text', { policy: READ_ONLY, points: [{ time: T0 + 600, price: 100 }], text: { value: 'Fixed' } });
    expect(mountTextEditor(rig.ctx, undefined, { id: note.id }).isOpen()).toBe(false);
    const fib = add(rig.draw, 'fib-retracement', { policy: READ_ONLY });
    expect(mountLevelEditor(rig.ctx, undefined, { ids: [fib.id] }).isOpen()).toBe(false);
    expect(rig.stack.size()).toBe(0);
  });
});

describe('the widget shell with a read-only drawing selected', () => {
  it('keeps it through Delete, Backspace, the arrows and cut, and through a hover and Delete', async () => {
    const { w, chartEl } = makeWidget();
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    w.draw.select(fixed.id);
    for (const key of ['Delete', 'Backspace', 'ArrowUp', 'ArrowLeft']) fireKey(chartEl, key);
    // A cut deletes only once the clipboard write has resolved, so the
    // assertion waits for it; without the wait a cut that ignored the policy
    // would pass here too.
    fireKey(chartEl, 'x', { ctrlKey: true });
    await settle();
    expect(w.draw.get(fixed.id)).toBeDefined();
    w.draw.select(null);
    w.chart.emit('hover', { id: `draw:${fixed.id}` });
    fireKey(chartEl, 'Delete');
    expect(w.draw.get(fixed.id)?.points).toEqual([{ time: T0 + 600, price: 100 }]);
    // The same wait is long enough to see an ordinary drawing cut.
    const free = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 99 }] });
    w.draw.select(free.id);
    fireKey(chartEl, 'x', { ctrlKey: true });
    await settle();
    expect(w.draw.get(free.id)).toBeUndefined();
  });

  it('counts only what delete and cut take in a selection that mixes read-only and editable drawings', () => {
    const { w, root } = makeWidget();
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    const a = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 99 }] });
    const b = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 98 }] });
    w.draw.select([fixed.id, a.id, b.id]);
    const target: ContextMenuTarget = { kind: 'drawing', id: `draw:${fixed.id}` };
    const e: ContextMenuEvent = { paneIndex: 0, point: { x: 200, y: 150 }, price: 100, time: T0 + 600, index: 10, target, preventDefault: () => {} };
    const rows = items(contextMenuEntries(w.context, e));
    const label = (id: string): string | undefined => rows.find((r) => r.id === id)?.label;
    expect(label('draw-copy')).toBe('Copy 3 drawings');
    expect(label('draw-cut')).toBe('Cut 2 drawings');
    expect(label('draw-delete')).toBe('Delete 2 drawings');
    const rail = root.querySelector('.oac-rail') as WidgetElement;
    const trash = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn')[4];
    vi.useFakeTimers();
    try {
      trash.rect = { left: 5, top: 400, width: 32, height: 32 };
      fire(trash, 'pointerenter');
      vi.advanceTimersByTime(700);
      expect((root.querySelector('.oac-tip') as WidgetElement).textContent).toContain('Delete 2 drawings');
      fire(trash, 'pointerleave');
    } finally { vi.useRealTimers(); }
  });

  it('turns the rail\'s lock, eye and trash off and counts only removable drawings', () => {
    const { w, root } = makeWidget();
    const rail = root.querySelector('.oac-rail') as WidgetElement;
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 99 }], policy: { selectable: false } });
    w.draw.select(fixed.id);
    const [, , lock, eye, trash] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    for (const b of [lock, eye, trash]) expect(b.classList.contains('is-off')).toBe(true);
    // The tooltip says why, the way a greyed menu row does.
    vi.useFakeTimers();
    try {
      lock.rect = { left: 5, top: 400, width: 32, height: 32 };
      fire(lock, 'pointerenter');
      vi.advanceTimersByTime(700);
      expect((root.querySelector('.oac-tip') as WidgetElement).textContent).toContain('read-only');
      fire(lock, 'pointerleave');
    } finally { vi.useRealTimers(); }
    trash.click();
    expect(w.draw.get(fixed.id)).toBeDefined();
    fire(trash, 'contextmenu');
    const rows = root.querySelectorAll('.oac-menu .oac-menu__row');
    expect(rows.map((r) => r.textContent)).toEqual(['Select all (1)', 'Remove all drawings (1)']);
  });

  it('lists a read-only drawing without hide, lock or remove, and leaves an unlisted one out', () => {
    const { w } = makeWidget();
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    const quiet = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 99 }], policy: { listed: false } });
    const content = createObjectsPanelContent(w.context);
    const panel = content.element as unknown as WidgetElement;
    const row = panel.querySelector(`[data-object-id="drawing:${fixed.id}"]`) as WidgetElement;
    expect(row).not.toBeNull();
    const actions = row.querySelectorAll('[data-action]').map((b) => b.dataset.action);
    expect(actions).toContain('select');
    for (const action of ['visibility', 'lock', 'remove']) expect(actions).not.toContain(action);
    expect(panel.querySelector(`[data-object-id="drawing:${quiet.id}"]`)).toBeNull();
    content.destroy();
  });

  it('offers no grouping for a selection of read-only drawings, which keep the group the host gave them', () => {
    const { w } = makeWidget();
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    const free = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 99 }] });
    const content = createObjectsPanelContent(w.context);
    const panel = content.element as unknown as WidgetElement;
    const name = panel.querySelector('[data-action="group-name"]') as WidgetElement;
    const group = panel.querySelector('[data-action="group"]') as WidgetElement;
    name.value = 'Mine';
    w.draw.select(fixed.id);
    fire(name, 'input');
    expect(group.disabled).toBe(true);
    w.draw.select([fixed.id, free.id]);
    fire(name, 'input');
    expect(group.disabled).toBe(false);
    group.click();
    expect(w.draw.groups().map((g) => [g.name, g.members])).toEqual([['Mine', [free.id]]]);
    content.destroy();
  });

  it('greys the mobile selection bar\'s lock and delete', () => {
    const { w, root } = makeWidget({ mobile: 'always' });
    const fixed = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: T0 + 600, price: 100 }], policy: READ_ONLY });
    w.draw.select(fixed.id);
    const action = (name: string): WidgetElement => root.querySelector(`[data-mobile-action="${name}"]`) as WidgetElement;
    expect(action('lock').getAttribute('aria-disabled')).toBe('true');
    expect(action('delete').getAttribute('aria-disabled')).toBe('true');
    action('delete').click();
    expect(w.draw.get(fixed.id)).toBeDefined();
  });
});
