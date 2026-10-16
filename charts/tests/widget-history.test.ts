/**
 * The widget walks one timeline: Ctrl+Z, Ctrl+Y and Ctrl+Shift+Z, the rail's
 * two buttons, and the mobile sheets reach a study, a pane and a drawing in
 * the order they were made. The dialogs that preview live are one step per
 * session, and a Cancel leaves none; a context-menu row is one step.
 */
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { registerIndicator, type Bar, type ContextMenuEvent } from '../src/index';
import {
  createWidget, mountContextMenu, mountIndicatorSettings, mountSettingsDialog, SAVE_DEBOUNCE_MS,
  type Widget, type WidgetOptions,
} from '../src/widget/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeDocument, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);
beforeAll(() => {
  registerIndicator({
    id: 'widget-history-osc', name: 'History Osc', placement: 'pane',
    inputs: [{ key: 'length', type: 'number', label: 'Length', default: 9, min: 1, max: 99 }],
    plots: [{ key: 'osc', title: 'Osc', type: 'line' }],
    calc: (b) => ({ osc: b.map(x => x.close - x.open) }),
  });
  registerIndicator({
    id: 'widget-history-anchored', name: 'History Anchored', placement: 'onchart',
    inputs: [
      { key: 'at', type: 'timestamp', label: 'Anchor time', default: T0 + 5 * DAY, pick: true },
      { key: 'level', type: 'price', label: 'Anchor price', default: 100, pick: true, timeKey: 'at', anchor: true },
    ],
    plots: [{ key: 'v', title: 'Level', type: 'line' }],
    calc: (b, s) => ({ v: b.map(x => (x.time >= (s.at as number) ? s.level as number : null)) }),
  });
});

const DAY = 86400;
const T0 = 1700000000;
const bars = (n: number): Bar[] => Array.from({ length: n }, (_, i) => {
  const c = 100 + Math.sin(i / 4) * 5;
  return { time: T0 + i * DAY, open: c - 1, high: c + 2, low: c - 2, close: c, volume: 1000 };
});

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

interface Made { w: Widget; doc: FakeDocument; root: FakeElement; chartEl: FakeElement }
function make(opts: WidgetOptions = {}, width = 800): Made {
  const doc = fakeWidgetDocument();
  const container = fakeContainer(doc, width, 600);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document,
    pixelRatio: () => 1, panels: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(width, 600);
  w.series.setData(bars(30));
  live.push(w);
  const root = w.root as unknown as FakeElement;
  root.rect = { left: 0, top: 0, width, height: 600 };
  const chartEl = root.querySelector('.oac-chart') as FakeElement;
  fire(root, 'pointerenter');
  return { w, doc, root, chartEl };
}

const settle = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 0));
const addLine = (w: Widget, price = 100): string =>
  w.draw.add({ tool: 'horizontal-line', points: [{ time: T0 + 5 * DAY, price }], style: {}, paneIndex: 0 }).id;
const mod = { ctrlKey: true };

describe('one timeline in the widget', () => {
  it('walks a drawing, a study and a pane fold back and forth with the chords', async () => {
    const { w, chartEl } = make();
    const line = addLine(w);
    const study = w.chart.addIndicator('widget-history-osc');
    await settle();
    w.chart.setPaneCollapsed(study.paneIndex, true);
    await settle();

    fireKey(chartEl, 'z', mod);
    expect(w.chart.paneCollapsed(1)).toBe(false);
    fireKey(chartEl, 'z', mod);
    expect(w.chart.indicators()).toHaveLength(0);
    expect(w.draw.get(line)).toBeDefined();
    fireKey(chartEl, 'z', mod);
    expect(w.draw.drawings()).toHaveLength(0);

    fireKey(chartEl, 'y', mod);
    expect(w.draw.drawings()).toHaveLength(1);
    fireKey(chartEl, 'Z', { ctrlKey: true, shiftKey: true });
    expect(w.chart.indicators()).toHaveLength(1);
    fireKey(chartEl, 'y', mod);
    expect(w.chart.paneCollapsed(1)).toBe(true);
    expect(w.history.canRedo()).toBe(false);
  });

  it('lists undo and redo with the chart shortcuts, not as drawing-only keys', () => {
    const { w } = make();
    const groups = w.context.keymap.list().filter(binding => binding.label === 'Undo' || binding.label === 'Redo').map(binding => binding.group);
    expect(groups).toEqual(['Widget', 'Widget', 'Widget']);
  });

  it('drives and reflects the timeline from the rail buttons', async () => {
    const { w, root } = make();
    const rail = root.querySelector('.oac-rail') as FakeElement;
    const [, , , , , undo, redo] = rail.querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    expect(undo.classList.contains('is-off')).toBe(true);
    w.chart.addIndicator('widget-history-osc');
    await settle();
    // No drawing event says so: the rail follows the history itself.
    expect(undo.classList.contains('is-off')).toBe(false);
    undo.click();
    expect(w.chart.indicators()).toHaveLength(0);
    expect(undo.classList.contains('is-off')).toBe(true);
    expect(redo.classList.contains('is-off')).toBe(false);
    redo.click();
    expect(w.chart.indicators()).toHaveLength(1);
  });

  it('offers undo and redo on the mobile sheets, disabled with nothing to take back', async () => {
    const { w, root } = make({ mobile: 'always' }, 390);
    const action = (name: string): FakeElement => root.querySelector(`[data-mobile-action="${name}"]`) as FakeElement;
    action('more').click();
    expect(action('undo').getAttribute('aria-disabled')).toBe('true');
    expect(action('redo').getAttribute('aria-disabled')).toBe('true');
    action('close').click();

    w.chart.setSeriesType(w.series, 'line');
    await settle();
    action('more').click();
    expect(action('undo').getAttribute('aria-disabled')).toBe('false');
    action('undo').click();
    expect(w.chartType()).toBe('candlestick');
    expect(action('redo').getAttribute('aria-disabled')).toBe('false');
    action('redo').click();
    expect(w.chartType()).toBe('line');
    action('close').click();

    // With a tool armed, the drawing sheet walks the same timeline.
    addLine(w);
    w.draw.setTool('trend-line');
    action('draw').click();
    action('undo').click();
    expect(w.draw.drawings()).toHaveLength(0);
    action('undo').click();
    expect(w.chartType()).toBe('candlestick');
    action('redo').click();
    expect(w.chartType()).toBe('line');
  });

  it('keeps the top bar and the saved layout in step with an undone chart type', async () => {
    const { w } = make();
    const layouts: unknown[] = [];
    w.on('layout', event => layouts.push(event));
    w.setChartType('area');
    await settle();
    w.history.undo();
    expect(w.chartType()).toBe('candlestick');
    expect(w.getState().chartType).toBe('candlestick');
    expect(layouts).toContainEqual({ reason: 'chartType', chartType: 'candlestick' });
  });
});

describe('dialogs and menus', () => {
  it('records a chart settings session as one step, and a cancelled one as none', () => {
    const { w, root } = make();
    // The host's own setting, before the user opens anything: not a step.
    w.history.ignore(() => w.chart.setGridOptions({ spacing: 120 }));
    const vertical = w.chart.gridOptions().vertLines;
    const spacing = (): number | undefined => w.chart.gridOptions().spacing;
    mountSettingsDialog(w.context, undefined, { tab: 'appearance' });
    (root.querySelector('.oac-dialog__lead button') as FakeElement).click();   // Restore this tab
    const vert = root.querySelector('#oac-cset-canvas-grid-vertLines') as FakeElement;
    vert.checked = !vert.checked;
    fire(vert, 'change');
    const afterOk = { spacing: spacing(), vertical: w.chart.gridOptions().vertLines };
    expect(afterOk.spacing).not.toBe(120);
    (root.querySelectorAll('.oac-dialog__actions button')[1]).click();   // OK
    expect(w.history.peekUndo()).toEqual({ label: 'Chart settings', changes: ['settings'] });
    w.history.undo();
    expect(w.chart.gridOptions().vertLines).toBe(vertical);
    expect(spacing()).toBe(120);
    expect(w.history.canUndo()).toBe(false);
    w.history.redo();
    expect({ spacing: spacing(), vertical: w.chart.gridOptions().vertLines }).toEqual(afterOk);

    mountSettingsDialog(w.context, undefined, { tab: 'appearance' });
    const again = root.querySelector('#oac-cset-canvas-grid-vertLines') as FakeElement;
    again.checked = !again.checked;
    fire(again, 'change');
    (root.querySelectorAll('.oac-dialog__actions button')[0]).click();   // Cancel
    expect(w.history.peekUndo()?.label).toBe('Chart settings');
    w.history.undo();
    expect(w.history.canUndo()).toBe(false);
  });

  it('records a study settings session as one step, and a cancelled one as none', async () => {
    const { w, root } = make();
    const study = w.chart.addIndicator('widget-history-osc');
    await settle();
    w.history.clear();
    mountIndicatorSettings(w.context, undefined, { instanceId: study.id });
    const input = root.querySelector(`#oac-ind-${study.id}-length`) as FakeElement & { value: string };
    for (const value of ['12', '15', '21']) {
      input.value = value;
      fire(input, 'change');
      await settle();
    }
    (root.querySelectorAll('.oac-dialog__actions button')[1]).click();   // OK
    expect(w.history.peekUndo()).toEqual({ label: 'Study settings', changes: ['study-settings'] });
    w.history.undo();
    expect(study.settings().length).toBe(9);
    expect(w.history.canUndo()).toBe(false);
    w.history.redo();
    expect(study.settings().length).toBe(21);

    mountIndicatorSettings(w.context, undefined, { instanceId: study.id });
    const next = root.querySelector(`#oac-ind-${study.id}-length`) as FakeElement & { value: string };
    next.value = '30';
    fire(next, 'change');
    await settle();
    (root.querySelectorAll('.oac-dialog__actions button')[0]).click();   // Cancel
    expect(study.settings().length).toBe(21);
    w.history.undo();
    expect(study.settings().length).toBe(9);
  });

  it('walks a line, an anchor drag and a Pick point on chart one step each, the pick taken back first', async () => {
    const { w, root } = make();
    const study = w.chart.addIndicator('widget-history-anchored');
    await settle();
    w.history.clear();
    const line = addLine(w, 97);
    const id = `input-anchor:${study.id}:level`;
    w.chart.emit('drag:start', { id, time: T0 + 5 * DAY, price: 100, paneIndex: 0 });
    w.chart.emit('drag', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    w.chart.emit('drag:end', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    await settle();
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });

    mountIndicatorSettings(w.context, undefined, { instanceId: study.id });
    const trigger = root.querySelector('[data-input-action="level"]') as FakeElement;
    expect(trigger.textContent).toBe('Pick point on chart');
    trigger.click();
    const price = w.chart.panes()[0].priceScale.yToPrice(120);
    w.chart.emit('click', { paneIndex: 0, point: { x: 400, y: 120 }, price, time: T0 + 20 * DAY + 60, id: null });
    await settle();
    expect(study.settings()).toMatchObject({ at: T0 + 20 * DAY, level: price });
    (root.querySelectorAll('.oac-dialog__actions button')[1]).click();   // OK
    expect(w.draw.historySteps().undo).toHaveLength(1);

    expect(w.history.peekUndo()).toEqual({ label: 'Study settings', changes: ['study-settings'] });
    w.history.undo();
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });
    expect(w.draw.get(line)).toBeDefined();
    w.history.undo();
    expect(study.settings()).toMatchObject({ at: T0 + 5 * DAY, level: 100 });
    expect(w.draw.get(line)).toBeDefined();
    w.history.undo();
    expect(w.draw.get(line)).toBeUndefined();
    expect(w.history.canUndo()).toBe(false);
    for (let i = 0; i < 3; i++) w.history.redo();
    expect(w.draw.get(line)).toBeDefined();
    expect(study.settings()).toMatchObject({ at: T0 + 20 * DAY, level: price });
    expect(w.history.canRedo()).toBe(false);
  });

  it('takes a Pick point on chart back first when the rail walks the drawing history alone, and never the line before it', async () => {
    const { w, root } = make();
    const [, , , , , undo] = (root.querySelector('.oac-rail') as FakeElement).querySelectorAll('.oac-rail__ctl .oac-rail__btn');
    const study = w.chart.addIndicator('widget-history-anchored');
    await settle();
    // A host that keeps no chart-wide timeline: every press is the drawing controller's own.
    w.history.destroy();
    const line = addLine(w, 97);
    const id = `input-anchor:${study.id}:level`;
    w.chart.emit('drag:start', { id, time: T0 + 5 * DAY, price: 100, paneIndex: 0 });
    w.chart.emit('drag', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    w.chart.emit('drag:end', { id, time: T0 + 12 * DAY, price: 103, paneIndex: 0 });
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });

    mountIndicatorSettings(w.context, undefined, { instanceId: study.id });
    const trigger = root.querySelector('[data-input-action="level"]') as FakeElement;
    expect(trigger.textContent).toBe('Pick point on chart');
    trigger.click();
    const price = w.chart.panes()[0].priceScale.yToPrice(120);
    w.chart.emit('click', { paneIndex: 0, point: { x: 400, y: 120 }, price, time: T0 + 20 * DAY + 60, id: null });
    await settle();
    (root.querySelectorAll('.oac-dialog__actions button')[1]).click();   // OK
    expect(study.settings()).toMatchObject({ at: T0 + 20 * DAY, level: price });

    undo.click();
    expect(w.draw.get(line)).toBeDefined();
    expect(study.settings()).toMatchObject({ at: T0 + 12 * DAY, level: 103 });
    undo.click();
    expect(w.draw.get(line)).toBeDefined();
    expect(study.settings()).toMatchObject({ at: T0 + 5 * DAY, level: 100 });
    undo.click();
    expect(w.draw.get(line)).toBeUndefined();
    expect(w.draw.canUndo()).toBe(false);
  });

  it('keeps the redo branch through a settings dialog that is cancelled', async () => {
    const { w, root } = make();
    w.chart.addIndicator('widget-history-osc');
    await settle();
    w.history.undo();
    expect(w.history.canRedo()).toBe(true);
    mountSettingsDialog(w.context, undefined, { tab: 'appearance' });
    const vert = root.querySelector('#oac-cset-canvas-grid-vertLines') as FakeElement;
    vert.checked = !vert.checked;
    fire(vert, 'change');
    (root.querySelectorAll('.oac-dialog__actions button')[0]).click();   // Cancel
    expect(w.history.canRedo()).toBe(true);
    expect(w.history.redo()).toBe(true);
    expect(w.chart.indicators()).toHaveLength(1);
  });

  it('records a colour dragged live through the study dialog as one step', async () => {
    const { w, root } = make();
    const study = w.chart.addIndicator('widget-history-osc');
    await settle();
    w.history.clear();
    const before = study.settings()['osc:color'];
    mountIndicatorSettings(w.context, undefined, { instanceId: study.id });
    (root.querySelectorAll('[role="tab"]')[1]).click();   // Style
    const color = root.querySelector(`#oac-ind-${study.id}-osc-color`) as FakeElement & { value: string };
    for (const value of ['#110000', '#550000', '#aa0000']) {
      color.value = value;
      fire(color, 'input');                                // every frame of the drag writes
      await settle();
    }
    fire(color, 'change');
    expect(study.settings()['osc:color']).toBe('#aa0000');
    (root.querySelectorAll('.oac-dialog__actions button')[1]).click();   // OK
    expect(w.history.peekUndo()).toEqual({ label: 'Study settings', changes: ['study-settings'] });
    w.history.undo();
    expect(study.settings()['osc:color']).toBe(before);
    expect(w.history.canUndo()).toBe(false);
    w.history.redo();
    expect(study.settings()['osc:color']).toBe('#aa0000');
  });

  it('makes each context-menu row one step, including what the chart does not announce', () => {
    const { w, root } = make();
    const orders = vi.fn();
    const menu = (): void => {
      mountContextMenu(w.context, undefined, { event: {
        paneIndex: 0, point: { x: 200, y: 150 }, price: 101, time: T0, index: 3,
        target: { kind: 'price-scale', id: null, side: 'right', scaleId: 'right' }, preventDefault: () => {},
      } as ContextMenuEvent, hooks: { onOrder: orders } });
    };
    menu();
    (root.querySelector('[data-act="axis-invert"]') as FakeElement).click();
    (root.querySelector('[data-act="axis-mode-logarithmic"]') as FakeElement).click();
    (root.querySelector('[data-act="chart-fit"]') as FakeElement | null)?.click();
    expect(w.chart.priceAxisState(0, 'right')).toMatchObject({ inverted: true, mode: 'logarithmic' });
    expect(w.history.peekUndo()?.label).toBe('axis-mode-logarithmic');
    w.history.undo();
    expect(w.chart.priceAxisState(0, 'right')).toMatchObject({ inverted: true, mode: 'linear' });
    w.history.undo();
    expect(w.chart.priceAxisState(0, 'right')?.inverted).toBe(false);
    expect(w.history.canUndo()).toBe(false);
    expect(orders).not.toHaveBeenCalled();
  });

  it('never places an order again when a step around an order is walked', async () => {
    const orders = vi.fn();
    const { w } = make({ onOrder: orders });
    const study = w.chart.addIndicator('widget-history-osc');
    await settle();
    mountContextMenu(w.context, undefined, { event: {
      paneIndex: 0, point: { x: 200, y: 150 }, price: 101, time: T0, index: 3,
      target: { kind: 'empty', id: null }, preventDefault: () => {},
    } as ContextMenuEvent, hooks: { onOrder: orders } });
    const rows = (w.root as unknown as FakeElement).querySelectorAll('.oac-ctx__row');
    const buy = rows.find(row => (row.dataset.act ?? '').startsWith('order-'));
    expect(buy).toBeDefined();
    buy!.click();
    const placed = orders.mock.calls.length;
    expect(placed).toBe(1);
    expect(w.history.canUndo()).toBe(true);   // the study, not the order
    study.setSettings({ length: 30 });
    await settle();
    while (w.history.undo());
    while (w.history.redo());
    expect(orders.mock.calls.length).toBe(placed);
  });
});

describe('layouts', () => {
  it('forgets the timeline when a layout is restored, and records nothing the restore set', async () => {
    const { w } = make();
    w.chart.addIndicator('widget-history-osc');
    await settle();
    const state = w.getState();
    addLine(w);
    const report = w.restoreState({ ...state, chartType: 'line' });
    await settle();
    expect(report.applied).toBe(true);
    expect(w.chartType()).toBe('line');
    expect(w.history.canUndo()).toBe(false);
    expect(w.history.canRedo()).toBe(false);
  });

  it('saves the layout an undo leaves, even for a change the chart does not announce', async () => {
    const saved = new Map<string, string>();
    const storage = { getItem: (k: string) => saved.get(k) ?? null, setItem: (k: string, v: string) => { saved.set(k, v); }, removeItem: (k: string) => { saved.delete(k); } };
    const { w } = make({ persist: 'undo-save', storage });
    w.chart.addIndicator('widget-history-osc');
    await settle();
    w.history.transact(() => w.chart.setPaneWeight(1, 0.9));
    await new Promise(resolve => setTimeout(resolve, SAVE_DEBOUNCE_MS + 50));
    const weight = (): number => JSON.parse(saved.get('oac-widget:undo-save:state')!).chart.panes[1].weight;
    expect(weight()).toBeCloseTo(0.9);
    w.history.undo();
    await new Promise(resolve => setTimeout(resolve, SAVE_DEBOUNCE_MS + 50));
    expect(weight()).toBeCloseTo(0.32);
  });

  it('stops following the chart when the widget is destroyed', () => {
    const { w } = make();
    const history = w.history;
    w.destroy();
    expect(history.isDestroyed).toBe(true);
    expect(history.undo()).toBe(false);
  });
});
