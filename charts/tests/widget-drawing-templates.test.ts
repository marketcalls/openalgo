/**
 * Drawing style templates in the widget: a tool's default reaches only the
 * drawings placed with that tool after it was saved, as part of the
 * placement's one undo step, and a named template applies as one step.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { openTemplateNamePrompt, templateMenuRows, type TemplateMenuRow } from '../src/widget/drawing-templates';
import {
  DrawingTemplateRepository, createMemoryDrawingTemplateStorage,
  type DrawingTemplateCatalog, type DrawingTemplateStore,
} from '../src/workspace/index';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fireKey, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const T0 = 1700000100;
const bars: Bar[] = (() => {
  let seed = 11;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  let close = 812;
  return Array.from({ length: 60 }, (_, i) => {
    const open = close;
    close = Math.round((open + next() * 6) * 20) / 20;
    return { time: T0 + i * 300, open, high: Math.max(open, close) + 2, low: Math.min(open, close) - 2, close, volume: 500 + i };
  });
})();

const settle = async (): Promise<void> => { for (let i = 0; i < 6; i++) await Promise.resolve(); await new Promise((r) => setTimeout(r, 0)); };

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

async function make(opts: WidgetOptions = {}, store: DrawingTemplateStore = new DrawingTemplateRepository(createMemoryDrawingTemplateStorage(), 'desk', { id: (() => { let n = 0; return () => `t${++n}`; })() })) {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc, 1000, 640) as unknown as HTMLElement, {
    document: doc as unknown as Document, mobile: 'never', pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    drawingTemplates: store, ...opts,
  });
  w.chart.applySize(900, 560);
  w.series.setData(bars);
  live.push(w);
  await settle();
  return { w, doc, root: w.root as unknown as FakeElement, store };
}

/** Place a two-anchor drawing the way a user does: arm the tool, click twice. */
function place(w: Widget, tool: string, from = 10, to = 30): string {
  w.draw.setTool(tool);
  w.chart.emit('click', { id: null, time: bars[from].time, price: bars[from].low, paneIndex: 0, point: { x: 0, y: 0 } });
  w.chart.emit('click', { id: null, time: bars[to].time, price: bars[to].high, paneIndex: 0, point: { x: 0, y: 0 } });
  const made = w.draw.drawings()[w.draw.drawings().length - 1];
  return made.id;
}

const rows = (list: Array<TemplateMenuRow | string>): TemplateMenuRow[] => list.filter((r): r is TemplateMenuRow => typeof r !== 'string');

describe('drawing templates in the widget', () => {
  it('gives a tool default only to drawings placed with that tool afterwards', async () => {
    const { w } = await make();
    const templates = w.drawingTemplates!;
    const first = place(w, 'trend-line');
    w.draw.update(first, { style: { ...w.draw.get(first)!.style, color: '#ab79df', lineWidth: 3, lineStyle: 'dashed' } });
    const untouched = place(w, 'trend-line', 12, 40);
    const beforeUntouched = JSON.stringify(w.draw.get(untouched)!.style);
    await templates.saveDefault(first);
    expect(templates.defaultFor('trend-line')).toMatchObject({ 'style.color': '#ab79df', 'style.lineWidth': 3, 'style.lineStyle': 'dashed' });
    // Saved: the drawings already on the chart keep their look.
    expect(JSON.stringify(w.draw.get(untouched)!.style)).toBe(beforeUntouched);
    const next = place(w, 'trend-line', 20, 50);
    expect(w.draw.get(next)!.style).toMatchObject({ color: '#ab79df', lineWidth: 3, lineStyle: 'dashed' });
    // Another tool starts with its own look.
    const box = place(w, 'rectangle', 5, 25);
    expect(w.draw.get(box)!.style.color).not.toBe('#ab79df');
    // A drawing the host adds, a duplicate and a paste keep the look they came with.
    const hosted = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#2a9df4' },
      points: [{ time: bars[2].time, price: bars[2].low }, { time: bars[8].time, price: bars[8].low }] });
    expect(w.draw.get(hosted.id)!.style.color).toBe('#2a9df4');
    const [copy] = w.draw.duplicate([hosted.id]);
    expect(copy.style.color).toBe('#2a9df4');
  });

  it('leaves a duplicate, a paste and a host drawing their own look while the tool is in use', async () => {
    const { w } = await make();
    const first = place(w, 'trend-line');
    w.draw.update(first, { style: { ...w.draw.get(first)!.style, color: '#ab79df', lineWidth: 4 } });
    await w.drawingTemplates!.saveDefault(first);
    const source = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#2a9df4', lineWidth: 1 },
      points: [{ time: bars[2].time, price: bars[2].low }, { time: bars[8].time, price: bars[8].low }] });
    // Drawing stays on, so the trend line tool is still in use after each placement.
    w.draw.setOptions({ stayInDrawingMode: true });
    w.draw.setTool('trend-line');
    const [copy] = w.draw.duplicate([source.id]);
    expect(w.draw.get(copy.id)!.style).toMatchObject({ color: '#2a9df4', lineWidth: 1 });
    await w.draw.copy([source.id]);
    const [pasted] = await w.draw.paste();
    expect(w.draw.get(pasted.id)!.style).toMatchObject({ color: '#2a9df4', lineWidth: 1 });
    const hosted = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#f0a020' },
      points: [{ time: bars[3].time, price: bars[3].low }, { time: bars[9].time, price: bars[9].low }] });
    await settle();
    expect(w.draw.get(hosted.id)!.style.color).toBe('#f0a020');
    // Placements, one after another with the tool still in use, each start with the default.
    expect(w.draw.activeTool()).toBe('trend-line');
    const placed = [place(w, 'trend-line', 20, 40), place(w, 'trend-line', 22, 44)];
    for (const id of placed) expect(w.draw.get(id)!.style).toMatchObject({ color: '#ab79df', lineWidth: 4 });
  });

  it('keeps a placement with a default one undo step, and its redo brings the default back', async () => {
    const { w } = await make();
    const first = place(w, 'trend-line');
    w.draw.update(first, { style: { ...w.draw.get(first)!.style, color: '#ff9800', lineWidth: 4 } });
    await w.drawingTemplates!.saveDefault(first);
    const count = w.draw.drawings().length;
    const next = place(w, 'trend-line', 25, 55);
    expect(w.draw.get(next)!.style.lineWidth).toBe(4);
    w.history.undo();
    expect(w.draw.drawings()).toHaveLength(count);
    expect(w.draw.get(next)).toBeUndefined();
    w.history.redo();
    expect(w.draw.get(next)!.style).toMatchObject({ color: '#ff9800', lineWidth: 4 });
    // One press takes the placement back again, and nothing before it.
    w.history.undo();
    expect(w.draw.get(next)).toBeUndefined();
    expect(w.draw.get(first)!.style.lineWidth).toBe(4);
  });

  it('forgets a default, after which new drawings start with the tool\'s own look', async () => {
    const { w } = await make();
    const first = place(w, 'trend-line');
    w.draw.update(first, { style: { ...w.draw.get(first)!.style, lineWidth: 4 } });
    await w.drawingTemplates!.saveDefault(first);
    await w.drawingTemplates!.clearDefault('trend-line');
    expect(w.drawingTemplates!.defaultFor('trend-line')).toBeUndefined();
    expect(w.draw.get(place(w, 'trend-line', 30, 50))!.style.lineWidth).not.toBe(4);
  });

  it('saves a named template and applies it to a selection as one step', async () => {
    const { w, root } = await make();
    const source = place(w, 'trend-line');
    w.draw.update(source, { style: { ...w.draw.get(source)!.style, color: '#26a69a', lineWidth: 3 } });
    const saved = await w.drawingTemplates!.saveTemplate(source, 'Support');
    expect(saved).toMatchObject({ name: 'Support', tool: 'trend-line' });
    expect(saved.values).not.toHaveProperty('text.value');
    const a = place(w, 'trend-line', 30, 45);
    const b = place(w, 'trend-line', 35, 50);
    w.draw.select([a, b]);
    const list = rows(templateMenuRows(w.context, w.drawingTemplates!, [a, b], undefined));
    const apply = list.find((r) => r.label === 'Apply Support')!;
    expect(apply.disabled).toBe(false);
    apply.onSelect();
    expect([w.draw.get(a)!.style.color, w.draw.get(b)!.style.color]).toEqual(['#26a69a', '#26a69a']);
    w.history.undo();
    expect([w.draw.get(a)!.style.color, w.draw.get(b)!.style.color]).not.toContain('#26a69a');
    // The properties dialog offers the same rows, bottom left.
    w.draw.select(a);
    w.chart.emit('noop', null);
    const { mountDrawingProperties } = await import('../src/widget/dialogs/index');
    const dialog = mountDrawingProperties(w.context);
    const picker = (dialog.el as unknown as FakeElement).querySelector('[data-act="templates"]') as FakeElement;
    expect(picker.parentElement!.classList.contains('oac-dialog__lead')).toBe(true);
    picker.click();
    expect(root.querySelectorAll('.oac-menu__row').map((r) => r.textContent)).toContain('Apply Support');
  });

  it('offers no one-tool rows for a selection of several tools, and no apply on a read-only one', async () => {
    const { w } = await make();
    const line = place(w, 'trend-line');
    await w.drawingTemplates!.saveTemplate(line, 'Thin');
    const box = place(w, 'rectangle', 5, 20);
    const mixed = rows(templateMenuRows(w.context, w.drawingTemplates!, [line, box], undefined));
    expect(mixed.find((r) => r.label === 'Save as default for this tool')).toMatchObject({ disabled: true, sub: 'one tool at a time' });
    expect(mixed.some((r) => r.label.startsWith('Apply'))).toBe(false);
    const fixed = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, policy: { editable: false },
      points: [{ time: bars[1].time, price: bars[1].low }, { time: bars[9].time, price: bars[9].low }] });
    const locked = rows(templateMenuRows(w.context, w.drawingTemplates!, [fixed.id], undefined));
    expect(locked.find((r) => r.label === 'Apply Thin')).toMatchObject({ disabled: true, sub: 'read-only' });
  });

  it('asks for a name, refuses an empty one and keeps the prompt open with the store\'s reason', async () => {
    const { w, root } = await make();
    const line = place(w, 'trend-line');
    let calls = 0;
    const handle = openTemplateNamePrompt(w.context, undefined, async (name) => {
      calls++;
      if (name === 'Taken') throw new Error('A template named Taken already exists for this tool');
      await w.drawingTemplates!.saveTemplate(line, name);
    });
    const input = root.querySelector('.oac-template-name__input') as FakeElement;
    fireKey(input, 'Enter');
    await settle();
    expect(calls).toBe(0);
    expect(input.getAttribute('aria-invalid')).toBe('true');
    input.value = 'Taken';
    fireKey(input, 'Enter');
    await settle();
    expect(handle.isOpen()).toBe(true);
    expect((root.querySelector('.oac-template-name .oac-input-error') as FakeElement).textContent).toContain('already exists');
    input.value = 'Swing lows';
    (root.querySelector('[data-action="save-template"]') as FakeElement).click();
    await settle();
    expect(handle.isOpen()).toBe(false);
    expect(w.drawingTemplates!.templatesFor('trend-line').map((t) => t.name)).toEqual(['Swing lows']);
  });

  it('follows a change committed through the store elsewhere on the page, and reports a store that cannot load', async () => {
    const storage = createMemoryDrawingTemplateStorage();
    const store = new DrawingTemplateRepository(storage, 'desk', { id: () => 'x1' });
    const { w } = await make({}, store);
    await store.setDefault('ray', { 'style.color': '#123456' });
    expect(w.drawingTemplates!.defaultFor('ray')).toEqual({ 'style.color': '#123456' });
    const broken: DrawingTemplateStore = {
      load: () => Promise.reject(new Error('offline')), subscribe: () => () => {},
      saveTemplate: () => Promise.reject(new Error('offline')), renameTemplate: () => Promise.reject(new Error('offline')),
      removeTemplate: () => Promise.reject(new Error('offline')), setDefault: () => Promise.reject(new Error('offline')),
    };
    const other = await make({}, broken);
    expect(other.w.drawingTemplates!.catalog()).toBeNull();
    expect((other.root.querySelector('.oac-statusline__msg') as FakeElement).textContent).toBe('Drawing templates could not be loaded');
    const line = place(other.w, 'trend-line');
    await expect(other.w.drawingTemplates!.saveDefault(line)).rejects.toThrow('offline');
    // The default rows still work on a stale catalog; nothing is applied from nothing.
    expect(other.w.drawingTemplates!.defaultFor('trend-line')).toBeUndefined();
  });

  it('ignores a load that lands after a newer commit', async () => {
    let resolveLoad: (c: DrawingTemplateCatalog) => void = () => {};
    let listener: (c: DrawingTemplateCatalog) => void = () => {};
    const store: DrawingTemplateStore = {
      load: () => new Promise((resolve) => { resolveLoad = resolve; }),
      subscribe: (fn) => { listener = fn; return () => {}; },
      saveTemplate: async () => { throw new Error('unused'); }, renameTemplate: async () => { throw new Error('unused'); },
      removeTemplate: async () => {}, setDefault: async () => {},
    };
    const { w } = await make({}, store);
    listener({ version: 1, revision: 4, templates: [], defaults: [{ tool: 'ray', values: { 'style.lineWidth': 3 }, updatedAt: 1 }] });
    resolveLoad({ version: 1, revision: 2, templates: [], defaults: [] });
    await settle();
    expect(w.drawingTemplates!.catalog()!.revision).toBe(4);
    expect(w.drawingTemplates!.defaultFor('ray')).toEqual({ 'style.lineWidth': 3 });
  });

  it('is absent without a store, and the properties dialog then offers no template control', async () => {
    const { w } = await make({ drawingTemplates: undefined });
    expect(w.drawingTemplates).toBeNull();
    expect(w.context.drawingTemplates).toBeUndefined();
    const line = place(w, 'trend-line');
    w.draw.select(line);
    const { mountDrawingProperties } = await import('../src/widget/dialogs/index');
    const dialog = mountDrawingProperties(w.context);
    expect((dialog.el as unknown as FakeElement).querySelector('[data-act="templates"]')).toBeNull();
  });
});
